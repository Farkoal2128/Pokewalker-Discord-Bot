"""Arena lifecycle inside the caller's writer transaction (C3, AR-1..8, AR-12..13)."""

import json
import math
from dataclasses import replace
from uuid import uuid4

from content.balance import limits, load_table
from pokewalker.db import with_receipt
from pokewalker.domain import arena as domain
from pokewalker.domain import battle as battle_engine
from pokewalker.services import gyms, profiles, stepping, storage


STOP_PCTS = range(10, 100, 10)


async def _latest_run(conn, profile_id):
    async with conn.execute('SELECT * FROM arena_runs WHERE profile_id=? '
                            'ORDER BY started_at DESC,run_id DESC LIMIT 1', (profile_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    run = dict(row)
    for key in ('team', 'enemy'):
        run[key] = json.loads(run[key])
    return run


async def state(conn, session, now):
    if not conn.in_transaction:
        raise RuntimeError('Arena requires an active writer transaction')
    profile, refusal = await profiles.session_owner(conn, session)
    if refusal:
        return refusal
    rules = load_table('arena')['rules']
    run = await _latest_run(conn, profile['profile_id'])
    if run and run['ended_at'] is None and now >= run['started_at'] + rules['run_seconds']:
        await conn.execute("UPDATE arena_runs SET ended_at=?,end_reason='expired',revision=revision+1 WHERE run_id=?",
                           (now, run['run_id']))
        run.update(ended_at=now, end_reason='expired', revision=run['revision'] + 1)
    async with conn.execute('SELECT arena_enabled FROM guilds WHERE guild_id=?', (profile['guild_id'],)) as cursor:
        enabled = bool((await cursor.fetchone())[0])
    async with conn.execute('SELECT tier,quantity FROM arena_tickets WHERE profile_id=?',
                            (profile['profile_id'],)) as cursor:
        tickets = {row['tier']: row['quantity'] for row in await cursor.fetchall()}
    cooldown = max(0, math.ceil(run['started_at'] + rules['cooldown_seconds'] - now)) if run else 0
    return {'status': 'none' if run is None else 'live' if run['ended_at'] is None else 'ended',
            'run': run, 'cooldown_left': cooldown, 'enabled': enabled,
            'best_floor': profile['arena_best_floor'], 'tickets': tickets,
            'stop_pct': profile['arena_stop_pct'], 'auto_order': bool(profile['arena_auto_order'])}


def _enemy_snapshot(rolled, content, multipliers):
    identity = rolled['identity']
    row = {'pokemon_uid': None, 'pokemon_id': identity['pokemon_id'], 'form_id': identity['form_id'],
           'revision': 0, 'content_version': profiles.content_facts(content)[0],
           'level_x2': rolled['level_x2'], 'gender': 'genderless', 'shiny': 0,
           **dict(zip(('iv_attack', 'iv_defense', 'iv_stamina'), rolled['ivs']))}
    combatant, snapshot = gyms._battle_snapshot(row, content, multipliers)
    return {'snapshot': snapshot, 'battle_hp': domain.enemy_hp(combatant.hp, rolled['factor_x10']),
            'special': rolled['special']}


def _roll_enemy(floor, slot, rng, content, multipliers):
    rolled = domain.roll_enemy(floor, slot, content['identities'], rng, load_table('arena')['rules'])
    return _enemy_snapshot(rolled, content, multipliers)


async def start(conn, session, team, now, rng, content, multipliers):
    current = await state(conn, session, now)
    if current['status'] in ('stale', 'excluded'):
        return current
    flags = await profiles.restrictions(conn, session['guild_id'], session['user_id'])
    if flags.paused:
        return {'status': 'paused', 'until': flags.paused_until.isoformat() if flags.paused_until else None}
    if not current['enabled']:
        return {'status': 'off'}
    if current['status'] == 'live':
        return current
    if current['cooldown_left']:
        return {'status': 'cooldown', 'seconds_left': current['cooldown_left']}
    rules = load_table('arena')['rules']
    if (not isinstance(team, (list, tuple)) or len(team) != rules['team_size']
            or any(not isinstance(pair, (list, tuple)) or len(pair) != 2
                   or not isinstance(pair[0], str) or type(pair[1]) is not int for pair in team)
            or len({uid for uid, _ in team}) != rules['team_size']):
        return {'status': 'invalid'}
    members = []
    for uid, revision in team:
        pokemon = await storage.detail(conn, session['profile_id'], uid)
        if pokemon is None or pokemon['revision'] != revision:
            return {'status': 'stale'}
        if pokemon['gym_deployment_id'] is not None:
            return {'status': 'deployed'}
        members.append(pokemon)

    async def compute(conn):
        snapshots = []
        for pokemon in members:
            identity, _ = storage.identify(content, pokemon)
            combatant, snapshot = gyms._battle_snapshot(pokemon, content, multipliers)
            snapshots.append({'uid': pokemon['pokemon_uid'], 'family_id': identity['family_id'],
                              'special': domain.is_special(identity, rules), 'full_hp': combatant.hp,
                              'hp': combatant.hp, 'snapshot': snapshot})
        enemy = _roll_enemy(1, 0, rng, content, multipliers)
        await conn.execute('INSERT INTO arena_runs(run_id,profile_id,started_at,floor,slot,team,enemy) '
                           'VALUES (?,?,?,1,0,?,?)',
                           (str(uuid4()), session['profile_id'], now, json.dumps(snapshots), json.dumps(enemy)))
        return {'status': 'started'}, []

    revision = session.get('_original_revision', session['revision'])
    result = await with_receipt(conn, f"arena_start:{session['session_id']}:{revision}", 'arena_start', compute,
                                profile_id=session['profile_id'])
    # The run is attached after the receipt so receipts stay small (never pruned).
    return {**result, 'run': await _latest_run(conn, session['profile_id'])} if result['status'] == 'started' else result


def _live_run(current, run_id, revision):
    if current['status'] in ('stale', 'excluded'):
        return None, current
    run = current['run']
    if current['status'] != 'live' or run['run_id'] != run_id or run['revision'] != revision:
        return None, {'status': 'stale', 'run': run}
    return run, None


async def set_order(conn, session, run_id, revision, order, now):
    run, refusal = _live_run(await state(conn, session, now), run_id, revision)
    if refusal:
        return refusal
    if (not isinstance(order, (list, tuple)) or any(type(position) is not int for position in order)
            or sorted(order) != list(range(len(run['team'])))):
        return {'status': 'invalid'}
    run['team'] = [run['team'][position] for position in order]
    await conn.execute('UPDATE arena_runs SET team=?,revision=revision+1 WHERE run_id=?',
                       (json.dumps(run['team']), run_id))
    run['revision'] += 1
    return {'status': 'ordered', 'run': run}


async def set_stop_pct(conn, session, run_id, revision, pct, now):
    run, refusal = _live_run(await state(conn, session, now), run_id, revision)
    if refusal:
        return refusal
    if type(pct) is not int or pct not in STOP_PCTS:
        return {'status': 'invalid'}
    await conn.execute('UPDATE profiles SET arena_stop_pct=? WHERE profile_id=?', (pct, session['profile_id']))
    await conn.execute('UPDATE arena_runs SET revision=revision+1 WHERE run_id=?', (run_id,))
    run['revision'] += 1
    return {'status': 'set', 'run': run}


async def set_auto_order(conn, session, run_id, revision, on, now):
    run, refusal = _live_run(await state(conn, session, now), run_id, revision)
    if refusal:
        return refusal
    if type(on) is not bool:
        return {'status': 'invalid'}
    await conn.execute('UPDATE profiles SET arena_auto_order=? WHERE profile_id=?', (on, session['profile_id']))
    await conn.execute('UPDATE arena_runs SET revision=revision+1 WHERE run_id=?', (run_id,))
    run['revision'] += 1
    return {'status': 'set', 'run': run}


async def heal(conn, session, run_id, revision, positions, berry, now):
    run, refusal = _live_run(await state(conn, session, now), run_id, revision)
    if refusal:
        return refusal
    if (berry not in load_table('arena')['rules']['heal_items'] or not isinstance(positions, (list, tuple))
            or not positions or any(type(position) is not int or not 0 <= position < len(run['team'])
                                    for position in positions) or len(set(positions)) != len(positions)):
        return {'status': 'invalid'}
    if any(run['team'][position]['hp'] >= run['team'][position]['full_hp'] for position in positions):
        return {'status': 'full'}
    async with conn.execute('SELECT quantity FROM inventory WHERE profile_id=? AND item_id=?',
                            (session['profile_id'], berry)) as cursor:
        held = await cursor.fetchone()
    short = len(positions) - (held['quantity'] if held else 0)
    if short > 0:
        return {'status': 'missing', 'short': short}

    async def compute(conn):
        for position in positions:
            run['team'][position]['hp'] = run['team'][position]['full_hp']
        await conn.execute('UPDATE inventory SET quantity=quantity-? WHERE profile_id=? AND item_id=?',
                           (len(positions), session['profile_id'], berry))
        await conn.execute('UPDATE arena_runs SET team=?,revision=revision+1 WHERE run_id=?',
                           (json.dumps(run['team']), run_id))
        run['revision'] += 1
        return {'status': 'healed'}, [
            {'profile_id': session['profile_id'], 'resource': 'item', 'resource_id': berry,
             'delta': -len(positions), 'reason': 'arena_heal'}]

    result = await with_receipt(conn, f'arena_heal:{run_id}:{revision}', 'arena_heal', compute,
                                profile_id=session['profile_id'])
    return {**result, 'run': run} if result['status'] == 'healed' else result


async def fight(conn, session, run_id, revision, now, rng, content, multipliers, battle_rules, chart):
    current = await state(conn, session, now)
    run, refusal = _live_run(current, run_id, revision)
    if refusal:
        return refusal
    floor, slot = run['floor'], run['slot']
    rules = load_table('arena')['rules']
    pid = session['profile_id']

    async def compute(conn):
        party = [replace(battle_engine.Combatant(**member['snapshot']['combatant']), hp=member['hp'])
                 for member in run['team']]
        enemy = battle_engine.Combatant(**run['enemy']['snapshot']['combatant'])
        battle = battle_engine.simulate(party, enemy, run['enemy']['battle_hp'], rules=battle_rules, chart=chart)
        won = battle.outcome == 'win'
        health = domain.revive(battle.party_hp) if won else battle.party_hp
        for member, hp in zip(run['team'], health):
            member['hp'] = hp
        candy = tickets = None
        lines = []
        next_floor, next_slot = floor, slot
        next_enemy = run['enemy']
        if won:
            finisher = run['team'][battle.finisher]
            amount = domain.candy_for(finisher['special'], slot, rules)
            if amount:
                family = finisher['family_id']
                await conn.execute('INSERT INTO candy VALUES (?,?,?) ON CONFLICT(profile_id,family_id) '
                                   'DO UPDATE SET quantity=quantity+excluded.quantity', (pid, family, amount))
                candy = {'family_id': family, 'quantity': amount}
                lines.append({'profile_id': pid, 'resource': 'candy', 'resource_id': str(family),
                              'delta': amount, 'reason': 'arena_candy'})
            next_slot = slot + 1
            if slot == 2:
                next_floor, next_slot = floor + 1, 0
                await conn.execute('UPDATE profiles SET arena_best_floor=MAX(arena_best_floor,?) WHERE profile_id=?',
                                   (floor, pid))
                tier = domain.ticket_for(floor, rules)
                if tier is not None:
                    first_clear = domain.first_clear_bonus(floor, current['best_floor'], rules)
                    copies = 1 + int(first_clear)
                    await conn.execute('INSERT INTO arena_tickets VALUES (?,?,?) ON CONFLICT(profile_id,tier) '
                                       'DO UPDATE SET quantity=quantity+excluded.quantity', (pid, tier, copies))
                    tickets = {'tier': tier, 'copies': copies, 'first_clear': first_clear}
                    lines.append({'profile_id': pid, 'resource': 'arena_ticket', 'resource_id': tier,
                                  'delta': copies, 'reason': 'arena_floor'})
            next_enemy = _roll_enemy(next_floor, next_slot, rng, content, multipliers)
        await conn.execute('UPDATE arena_runs SET team=?,enemy=?,floor=?,slot=?,ended_at=?,end_reason=?,'
                           'revision=revision+1 WHERE run_id=?',
                           (json.dumps(run['team']), json.dumps(next_enemy), next_floor, next_slot,
                            None if won else now, None if won else battle.outcome, run_id))
        return {'status': 'won' if won else 'defeated', 'outcome': battle.outcome, 'reason': battle.reason,
                'ticks': battle.ticks, 'engine': battle.engine_version, 'floor': floor, 'slot': slot,
                'enemy': {'name': enemy.name, 'cp': run['enemy']['snapshot']['cp'], 'types': list(enemy.types)},
                'party_hp': list(battle.party_hp),
                'revived': [i for i, hp in enumerate(battle.party_hp) if hp == 0] if won else [],
                'finisher': battle.finisher, 'candy': candy, 'tickets': tickets}, lines

    return await with_receipt(conn, f'arena_fight:{run_id}:{floor}:{slot}', 'arena_fight', compute, profile_id=pid)


async def heal_all_and_fight(conn, session, run_id, revision, berry, now, rng, content, multipliers, battle_rules, chart):
    run, refusal = _live_run(await state(conn, session, now), run_id, revision)
    if refusal:
        return refusal
    if berry not in load_table('arena')['rules']['heal_items']:
        return {'status': 'invalid'}
    positions = [i for i, member in enumerate(run['team']) if member['hp'] < member['full_hp']]
    if positions:
        result = await heal(conn, session, run_id, revision, positions, berry, now)
        if result['status'] != 'healed':
            return result
        revision = result['run']['revision']
    return await fight(conn, session, run_id, revision, now, rng, content, multipliers, battle_rules, chart)


async def redeem_quote(conn, profile_id, tier):
    rewards = load_table('arena')['rules']['tickets']['tiers'][tier]
    cap = limits()['encounter_queue']
    free = cap - await profiles.queue_size(conn, profile_id)
    count = cap if rewards['encounters'] == 'fill' else rewards['encounters']
    async with conn.execute('SELECT quantity FROM arena_tickets WHERE profile_id=? AND tier=?',
                            (profile_id, tier)) as cursor:
        held = await cursor.fetchone()
    return {'held': held[0] if held else 0, 'free': free, 'add': min(free, count)}


async def redeem(conn, session, tier, expected_free, expected_add, now, rng, content):
    current = await state(conn, session, now)
    if current['status'] in ('stale', 'excluded'):
        return current
    tiers = load_table('arena')['rules']['tickets']['tiers']
    if tier not in tiers:
        return {'status': 'invalid'}
    pid = session['profile_id']
    quote = await redeem_quote(conn, pid, tier)
    if quote['held'] < 1:
        return {'status': 'none'}
    if quote['free'] < 1:
        return {'status': 'queue_full'}
    if quote['free'] != expected_free or quote['add'] != expected_add:
        return {'status': 'quote_changed', 'free': quote['free'], 'add': quote['add']}
    rewards = tiers[tier]
    profile = await profiles.get_profile(conn, session['guild_id'], session['user_id'])

    async def compute(conn):
        redeem_id = str(uuid4())
        prefix = f'arena:{redeem_id}'
        await conn.execute('UPDATE arena_tickets SET quantity=quantity-1 WHERE profile_id=? AND tier=?', (pid, tier))
        for _ in range(quote['add']):
            await stepping.spawn_encounter(conn, profile, content, rng, now)
        await conn.execute('INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) '
                           "VALUES (?,?,'stardust',NULL,?,?)", (pid, f'{prefix}:stardust', rewards['stardust'], now))
        for n in range(rewards['income_rolls']):
            await gyms.income_roll(conn, pid, f'{prefix}:income:{n}', now, rng, content)
        for n in range(rewards['survivor_rolls']):
            await gyms.survivor_roll(conn, pid, f'{prefix}:survivor:{n}', now, rng)
        return {'status': 'redeemed', 'redeem_id': redeem_id, 'encounters': quote['add'],
                'stardust': rewards['stardust'], 'income_rolls': rewards['income_rolls'],
                'survivor_rolls': rewards['survivor_rolls']}, [
                    {'profile_id': pid, 'resource': 'arena_ticket', 'resource_id': tier,
                     'delta': -1, 'reason': 'arena_redeem'}]

    revision = session.get('_original_revision', session['revision'])
    return await with_receipt(conn, f"arena_redeem:{session['session_id']}:{revision}", 'arena_redeem', compute,
                              profile_id=pid)
