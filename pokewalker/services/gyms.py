"""Guild-scoped gym lifecycle inside the caller's writer transaction."""

from dataclasses import asdict
import hashlib
import json
from uuid import uuid4

from content.balance import load_table
from pokewalker.db import with_receipt
from pokewalker.domain import battle as battle_engine
from pokewalker.domain.cp import cp
from pokewalker.services import items, profiles, storage


def _writer(conn):
    if not conn.in_transaction:
        raise RuntimeError('Gyms require an active writer transaction')


async def get_gym(conn, guild_id, gym_id):
    async with conn.execute('SELECT * FROM gyms WHERE gym_id=? AND guild_id=?',
                            (gym_id, guild_id)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_gyms(conn, guild_id):
    async with conn.execute('SELECT * FROM gyms WHERE guild_id=? AND retired_at IS NULL ORDER BY name,gym_id',
                            (guild_id,)) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def create(conn, guild_id, name, now):
    _writer(conn)
    rules = load_table('capacities')['gyms']
    if not isinstance(name, str) or not 1 <= len(name) <= rules['name_max']:
        return {'status': 'invalid'}
    async with conn.execute('SELECT 1 FROM gyms WHERE guild_id=? AND name=?', (guild_id, name)) as cursor:
        if await cursor.fetchone():
            return {'status': 'duplicate'}
    if len(await list_gyms(conn, guild_id)) >= rules['per_guild']:
        return {'status': 'full'}
    gym_id = str(uuid4())
    await conn.execute('INSERT INTO gyms(gym_id,guild_id,name,created_at) VALUES (?,?,?,?)',
                       (gym_id, guild_id, name, now))
    return await get_gym(conn, guild_id, gym_id)


async def deploy(conn, session, gym_id, pokemon_uid, rev, now, content):
    _writer(conn)
    guild_id = session['guild_id']
    profile = await profiles.get_profile(conn, guild_id, session['user_id'])
    if profile is None or profile['profile_id'] != session['profile_id']:
        return {'status': 'stale'}
    if (await profiles.restrictions(conn, guild_id, session['user_id'])).excluded:
        return {'status': 'excluded'}
    key = f"deploy:{session['session_id']}:{gym_id}:{pokemon_uid}:{rev}"
    async with conn.execute("SELECT profile_id,result FROM action_receipts WHERE key=? AND action='deploy'",
                            (key,)) as cursor:
        receipt = await cursor.fetchone()
    if receipt is not None:
        return json.loads(receipt['result']) if receipt['profile_id'] == profile['profile_id'] else {'status': 'stale'}
    gym = await get_gym(conn, guild_id, gym_id)
    if gym is None or gym['retired_at'] is not None:
        return {'status': 'stale'}
    pokemon = await storage.detail(conn, profile['profile_id'], pokemon_uid)
    if pokemon is None or pokemon['revision'] != rev:
        return {'status': 'stale'}
    if profile['companion_uid'] == pokemon_uid:
        return {'status': 'companion'}
    identity, _ = storage.identify(content, pokemon)
    if identity['is_legendary'] or identity['is_mythical']:
        return {'status': 'legendary_or_mythical'}
    async with conn.execute('SELECT 1 FROM gym_deployments WHERE guild_id=? AND ended_at IS NULL '
                            'AND (gym_id=? OR profile_id=? OR pokemon_uid=?)',
                            (guild_id, gym_id, profile['profile_id'], pokemon_uid)) as cursor:
        if await cursor.fetchone() or pokemon['gym_deployment_id'] is not None:
            return {'status': 'occupied'}

    async def compute(conn):
        deployment_id = str(uuid4())
        await conn.execute('INSERT INTO gym_deployments(deployment_id,guild_id,gym_id,profile_id,pokemon_uid,'
                           'deployed_at,ends_at) VALUES (?,?,?,?,?,?,?)',
                           (deployment_id, guild_id, gym_id, profile['profile_id'], pokemon_uid,
                            now, now + load_table('gym_income_table')['tenure_seconds']))
        await conn.execute('UPDATE pokemon SET gym_deployment_id=?,revision=revision+1 '
                           "WHERE pokemon_uid=? AND profile_id=? AND state='owned'",
                           (deployment_id, pokemon_uid, profile['profile_id']))
        async with conn.execute('SELECT * FROM gym_deployments WHERE gym_id=? AND guild_id=? AND deployment_id=?',
                                (gym_id, guild_id, deployment_id)) as cursor:
            return {'status': 'deployed', 'deployment': dict(await cursor.fetchone())}, []

    return await with_receipt(conn, key, 'deploy', compute, profile_id=profile['profile_id'])


async def pay_hours(conn, guild_id, deployment_id, now, rng, content):
    _writer(conn)
    async with conn.execute('SELECT * FROM gym_deployments WHERE deployment_id=? AND guild_id=?',
                            (deployment_id, guild_id)) as cursor:
        deployment = await cursor.fetchone()
    if deployment is None:
        return {'status': 'stale'}
    if deployment['ended_at'] is not None:
        return {'status': 'ended', 'paid_hours': deployment['paid_hours']}
    completed = min(8, int((min(now, deployment['ends_at']) - deployment['deployed_at']) // 3600))
    rows = load_table('gym_income_table')['rows']
    for hour in range(1, completed + 1):
        async def compute(conn):
            selected = rng.choices(rows, weights=[row['weight'] for row in rows], k=1)[0]
            item, quantity = items.resolve_item(rng, selected['item'], selected['quantity'], content)
            await conn.execute('INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) '
                               'VALUES (?,?,?,?,?,?)', (deployment['profile_id'], f'gym_income:{deployment_id}:{hour}',
                               'stardust' if item == 'stardust' else 'item',
                               None if item == 'stardust' else item, quantity, now))
            await conn.execute('UPDATE gym_deployments SET paid_hours=MAX(paid_hours,?) '
                               'WHERE deployment_id=? AND guild_id=?', (hour, deployment_id, guild_id))
            return {'item': item, 'quantity': quantity}, []

        await with_receipt(conn, f'gym_hour:{deployment_id}:{hour}', 'gym_hour', compute,
                           profile_id=deployment['profile_id'])
    return {'status': 'paid', 'paid_hours': max(deployment['paid_hours'], completed)}


async def end_deployment(conn, guild_id, deployment_id, reason, now, rng, content):
    _writer(conn)
    async with conn.execute('SELECT * FROM gym_deployments WHERE deployment_id=? AND guild_id=?',
                            (deployment_id, guild_id)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return {'status': 'stale'}
    deployment = dict(row)
    if deployment['ended_at'] is not None:
        return {'status': 'ended', 'deployment': deployment}
    if reason != 'excluded':
        paid = await pay_hours(conn, guild_id, deployment_id, now, rng, content)
        deployment['paid_hours'] = paid['paid_hours']
    if reason == 'expired' and now >= deployment['ends_at'] and not deployment['survivor_rolled']:
        table = load_table('survivor_table')
        rows = table['rows']
        selected = rng.choices(rows, weights=[row['weight'] for row in rows], k=1)[0]
        for item, quantity in ((selected['item'], selected['quantity']), ('stardust', table['stardust_flat'])):
            await conn.execute('INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) '
                               'VALUES (?,?,?,?,?,?)', (deployment['profile_id'], f'survivor:{deployment_id}',
                               'stardust' if item == 'stardust' else 'item',
                               None if item == 'stardust' else item, quantity, now))
        await conn.execute('UPDATE gym_deployments SET survivor_rolled=1 WHERE deployment_id=? AND guild_id=?',
                           (deployment_id, guild_id))
        deployment['survivor_rolled'] = 1
    await conn.execute('UPDATE gym_deployments SET ended_at=?,end_reason=? '
                       'WHERE deployment_id=? AND gym_id=? AND guild_id=? AND ended_at IS NULL',
                       (now, reason, deployment_id, deployment['gym_id'], guild_id))
    await conn.execute('UPDATE pokemon SET gym_deployment_id=NULL,revision=revision+1 '
                       'WHERE pokemon_uid=? AND profile_id=? AND gym_deployment_id=?',
                       (deployment['pokemon_uid'], deployment['profile_id'], deployment_id))
    return {'status': 'ended', 'deployment': {**deployment, 'ended_at': now, 'end_reason': reason}}


async def retire(conn, guild_id, gym_id, now, rng, content):
    _writer(conn)
    gym = await get_gym(conn, guild_id, gym_id)
    if gym is None:
        return {'status': 'stale'}
    if gym['retired_at'] is not None:
        return {'status': 'retired'}
    async with conn.execute('SELECT deployment_id FROM gym_deployments '
                            'WHERE gym_id=? AND guild_id=? AND ended_at IS NULL',
                            (gym_id, guild_id)) as cursor:
        deployment = await cursor.fetchone()
    if deployment is not None:
        await end_deployment(conn, guild_id, deployment['deployment_id'], 'retired', now, rng, content)
    await conn.execute('UPDATE gyms SET retired_at=? WHERE gym_id=? AND guild_id=?', (now, gym_id, guild_id))
    return {'status': 'retired'}


async def settle(conn, now, rng, content):
    _writer(conn)
    async with conn.execute('SELECT deployment_id,guild_id FROM gym_deployments '
                            'WHERE ended_at IS NULL AND ends_at<=?', (now,)) as cursor:
        expired = await cursor.fetchall()
    for deployment in expired:
        await end_deployment(conn, deployment['guild_id'], deployment['deployment_id'], 'expired', now, rng, content)


def _battle_snapshot(pokemon, content, multipliers):
    identity, _ = storage.identify(content, pokemon)
    base = [identity[key] for key in ('base_attack', 'base_defense', 'base_stamina')]
    ivs = [pokemon[key] for key in ('iv_attack', 'iv_defense', 'iv_stamina')]
    attack, defense, hp = battle_engine.combat_stats(base, ivs, pokemon['level_x2'], multipliers)
    first_type = identity['types'][0]
    combatant = battle_engine.Combatant(identity['name_en'], tuple(identity['types']),
                                        attack, defense, hp, first_type, first_type)
    snapshot = {key: pokemon[key] for key in ('pokemon_uid', 'pokemon_id', 'form_id', 'revision', 'content_version',
                                             'level_x2', 'iv_attack', 'iv_defense', 'iv_stamina', 'gender', 'shiny')}
    snapshot.update(combatant=asdict(combatant), cp=cp(base, ivs, pokemon['level_x2'], multipliers=multipliers))
    return combatant, snapshot


async def battle(conn, session, gym_id, expected_deployment_id, party, nominee_uid,
                 now, rng, content, multipliers, rules, chart):
    _writer(conn)
    guild_id = session['guild_id']
    profile = await profiles.get_profile(conn, guild_id, session['user_id'])
    if profile is None or profile['profile_id'] != session['profile_id']:
        return {'status': 'stale'}
    if (await profiles.restrictions(conn, guild_id, session['user_id'])).excluded:
        return {'status': 'excluded'}
    revision = session.get('_original_revision', session['revision'])
    key = f"battle:{session['session_id']}:{revision}"
    async with conn.execute("SELECT profile_id,result FROM action_receipts WHERE key=? AND action='battle'",
                            (key,)) as cursor:
        receipt = await cursor.fetchone()
    if receipt is not None:
        return json.loads(receipt['result']) if receipt['profile_id'] == profile['profile_id'] else {'status': 'stale'}

    # Refused starts must not commit incidental expiry payouts from settle.
    await conn.execute('SAVEPOINT battle_start')

    async def refuse(status):
        await conn.execute('ROLLBACK TO battle_start')
        await conn.execute('RELEASE battle_start')
        return {'status': status}

    await settle(conn, now, rng, content)
    gym = await get_gym(conn, guild_id, gym_id)
    if gym is None or gym['retired_at'] is not None:
        return await refuse('invalid')
    async with conn.execute('SELECT * FROM gym_deployments WHERE gym_id=? AND guild_id=? AND ended_at IS NULL',
                            (gym_id, guild_id)) as cursor:
        row = await cursor.fetchone()
    if row is None or row['deployment_id'] != expected_deployment_id:
        return await refuse('stale')
    deployment = dict(row)
    if deployment['profile_id'] == profile['profile_id']:
        return await refuse('invalid')
    if profile['last_battle_at'] is not None and profile['last_battle_at'] + 600 > now:
        return await refuse('cooldown')
    if (not isinstance(party, (list, tuple)) or not 1 <= len(party) <= 3 or
            any(not isinstance(slot, (list, tuple)) or len(slot) != 2 or
                not isinstance(slot[0], str) or type(slot[1]) is not int or slot[1] < 0 for slot in party) or
            len({slot[0] for slot in party}) != len(party)):
        return await refuse('invalid')
    combatants, snapshots, owned = [], [], {}
    for uid, rev in party:
        pokemon = await storage.detail(conn, profile['profile_id'], uid)
        if pokemon is None:
            return await refuse('invalid')
        if pokemon['revision'] != rev:
            return await refuse('stale')
        if uid == profile['companion_uid'] or pokemon['gym_deployment_id'] is not None:
            return await refuse('invalid')
        owned[uid] = pokemon
        combatant, snapshot = _battle_snapshot(pokemon, content, multipliers)
        combatants.append(combatant)
        snapshots.append(snapshot)
    if nominee_uid is not None:
        if nominee_uid not in owned:
            return await refuse('invalid')
        identity, _ = storage.identify(content, owned[nominee_uid])
        if identity['is_legendary'] or identity['is_mythical']:
            return await refuse('invalid')
    pokemon = await storage.detail(conn, deployment['profile_id'], deployment['pokemon_uid'])
    defender, defender_snapshot = _battle_snapshot(pokemon, content, multipliers)
    hours = int((now - deployment['deployed_at']) // 3600)
    battle_hp = battle_engine.defender_hp(defender.hp, hours)
    snapshot = {'party': snapshots, 'defender': defender_snapshot, 'deployment': deployment,
                'nominee_uid': nominee_uid, 'hours_held': hours, 'defender_battle_hp': battle_hp,
                'ruleset_hashes': {
                    'content': profiles.content_facts(content)[0],
                    **{name: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                                       allow_nan=False).encode()).hexdigest()
                       for name, value in (('multipliers', multipliers), ('rules', rules), ('chart', chart))}}}

    async def compute(conn):
        outcome = battle_engine.simulate(combatants, defender, battle_hp, rules=rules, chart=chart)
        battle_id = str(uuid4())
        await conn.execute('INSERT INTO gym_battles(battle_id,guild_id,gym_id,deployment_id,challenger_profile_id,'
                           'outcome,reason,ticks,events,engine,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (battle_id, guild_id, gym_id, deployment['deployment_id'], profile['profile_id'],
                            outcome.outcome, outcome.reason, outcome.ticks, json.dumps(outcome.events),
                            outcome.engine_version, now))
        await conn.execute('UPDATE profiles SET last_battle_at=? WHERE profile_id=? AND guild_id=?',
                           (now, profile['profile_id'], guild_id))
        claimed = False
        if outcome.outcome == 'win':
            await end_deployment(conn, guild_id, deployment['deployment_id'], 'defeated', now, rng, content)
            if nominee_uid is not None:
                deployed = await deploy(conn, session, gym_id, nominee_uid, owned[nominee_uid]['revision'], now, content)
                claimed = deployed['status'] == 'deployed'
        return {'status': 'completed', 'battle_id': battle_id, 'guild_id': guild_id, 'gym_id': gym_id,
                'deployment_id': deployment['deployment_id'], 'outcome': outcome.outcome, 'reason': outcome.reason,
                'ticks': outcome.ticks, 'events': list(outcome.events), 'engine': outcome.engine_version,
                'survivors': list(outcome.survivors), 'snapshot': snapshot, 'claimed': claimed}, []

    result = await with_receipt(conn, key, 'battle', compute, profile_id=profile['profile_id'])
    await conn.execute('RELEASE battle_start')
    return result
