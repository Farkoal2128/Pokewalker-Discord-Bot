"""D40/D54 recipe previews and atomic evolution with durable authorized replay."""
import json

from pokewalker.db import with_receipt
from pokewalker.domain.cp import cp
from pokewalker.services import profiles, storage
from pokewalker.services.milestones import check_and_award


def options(content, pokemon):
    identity, _ = storage.identify(content, pokemon)
    edges = content['evolutions'].get(identity['identity_id'], [])
    return list({edge['edge_id']: edge for edge in edges
                 if edge['gender'] is None or edge['gender'] == pokemon['gender']}.values())


def target(content, pokemon, edge):
    pokemon_id, form_id = map(int, edge['to_identity_id'].split(':'))
    identity, _ = storage.identify(content, {**pokemon, 'pokemon_id': pokemon_id, 'form_id': form_id})
    return identity.get('gender_varieties', {}).get(pokemon['gender'], identity)


async def quote(conn, profile_id, pokemon_uid, edge_id, content, multipliers):
    pokemon = await storage.detail(conn, profile_id, pokemon_uid)
    if pokemon is None:
        return None
    edge = next((e for e in options(content, pokemon) if e['edge_id'] == edge_id), None)
    if edge is None:
        return None
    source, _ = storage.identify(content, pokemon)
    resolved = target(content, pokemon, edge)
    async with conn.execute('SELECT quantity FROM candy WHERE profile_id=? AND family_id=?',
                            (profile_id, source['family_id'])) as cursor:
        row = await cursor.fetchone()
        candy_have = row['quantity'] if row else 0
    async with conn.execute('SELECT quantity FROM inventory WHERE profile_id=? AND item_id=?',
                            (profile_id, edge['item'])) as cursor:
        row = await cursor.fetchone()
        item_have = row['quantity'] if row else 0
    ivs = [pokemon[k] for k in ('iv_attack', 'iv_defense', 'iv_stamina')]
    def value(identity):
        return cp([identity[k] for k in ('base_attack', 'base_defense', 'base_stamina')],
                  ivs, pokemon['level_x2'], multipliers=multipliers)
    return dict(edge_id=edge_id, target=resolved, cp_before=value(source), cp_after=value(resolved),
                candy_cost=edge['candy'], candy_have=candy_have, item=edge['item'], item_have=item_have,
                affordable=candy_have >= edge['candy'] and (edge['item'] is None or item_have >= 1))


async def evolve(conn, session, pokemon_uid, edge_id, expected_revision, content, multipliers, now):
    if not conn.in_transaction:
        raise RuntimeError('Evolution requires an active writer transaction')
    profile = await profiles.get_profile(conn, session['guild_id'], session['user_id'])
    if profile is None or profile['profile_id'] != session['profile_id']:
        return {'status': 'stale', 'pokemon': None}
    pid = profile['profile_id']
    async with conn.execute('SELECT * FROM pokemon WHERE profile_id=? AND pokemon_uid=?', (pid, pokemon_uid)) as cursor:
        row = await cursor.fetchone()
        pokemon = dict(row) if row else None
    if (await profiles.restrictions(conn, session['guild_id'], session['user_id'])).excluded:
        return {'status': 'excluded', 'pokemon': pokemon}
    if pokemon is None:
        return {'status': 'stale', 'pokemon': None}
    key = f'evolve:{pokemon_uid}:{expected_revision}'
    async with conn.execute("SELECT profile_id,result FROM action_receipts WHERE key=? AND action='evolve'", (key,)) as cursor:
        receipt = await cursor.fetchone()
    if receipt is not None:
        return json.loads(receipt['result']) if receipt['profile_id'] == pid else {'status': 'stale', 'pokemon': pokemon}
    if pokemon['gym_deployment_id'] is not None:
        return {'status': 'stale', 'pokemon': pokemon}
    if pokemon['state'] != 'owned' or pokemon['revision'] != expected_revision:
        return {'status': 'stale', 'pokemon': pokemon}
    price = await quote(conn, pid, pokemon_uid, edge_id, content, multipliers)
    if price is None or not price['affordable']:
        return {'status': 'invalid' if price is None else 'insufficient', 'pokemon': pokemon}
    family = storage.identify(content, pokemon)[0]['family_id']

    async def compute(conn):
        await conn.execute('UPDATE pokemon SET pokemon_id=?,form_id=?,revision=revision+1 WHERE pokemon_uid=?',
                           (price['target']['pokemon_id'], price['target']['form_id'], pokemon_uid))
        await conn.execute('UPDATE candy SET quantity=quantity-? WHERE profile_id=? AND family_id=?',
                           (price['candy_cost'], pid, family))
        lines = [dict(profile_id=pid, resource='candy', resource_id=str(family),
                      delta=-price['candy_cost'], reason='evolve')]
        if price['item'] is not None:
            await conn.execute('UPDATE inventory SET quantity=quantity-1 WHERE profile_id=? AND item_id=?',
                               (pid, price['item']))
            lines.append(dict(profile_id=pid, resource='item', resource_id=price['item'], delta=-1, reason='evolve'))
        await conn.execute('INSERT INTO pokedex(profile_id,pokemon_id,seen_at,caught_at) VALUES (?,?,?,?) '
                           'ON CONFLICT(profile_id,pokemon_id) DO UPDATE SET caught_at=COALESCE(caught_at,excluded.caught_at)',
                           (pid, price['target']['species_id'], now, now))
        await check_and_award(conn, pid, content, now)
        return {'status': 'evolved', 'pokemon': await storage.detail(conn, pid, pokemon_uid)}, lines

    return await with_receipt(conn, key, 'evolve', compute, profile_id=pid)
