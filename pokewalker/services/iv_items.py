"""Owner amendment 2026-11-12: Bottlecap and Vitamin raise one owned Pokemon's lowest IV."""

import json

from pokewalker.db import with_receipt
from pokewalker.domain.cp import appraisal, cp
from pokewalker.services import storage
from pokewalker.services.profiles import session_owner


ITEMS = ('bottlecap', 'vitamin')
IVS = ('iv_attack', 'iv_defense', 'iv_stamina')
MAX_IV = 15


def lowest(ivs):
    """Index of the lowest IV; ties go to Attack, then Defense, then Stamina."""
    return list(ivs).index(min(ivs))


def apply(item, ivs):
    changed, index = list(ivs), lowest(ivs)
    changed[index] = MAX_IV if item == 'bottlecap' else min(MAX_IV, changed[index] + 1)
    return tuple(changed)


def perfect(pokemon):
    return all(pokemon[key] == MAX_IV for key in IVS)


async def held(conn, profile_id):
    async with conn.execute('SELECT item_id,quantity FROM inventory WHERE profile_id=? AND item_id IN (?,?)',
                            (profile_id, *ITEMS)) as cursor:
        counts = {row['item_id']: row['quantity'] for row in await cursor.fetchall()}
    return {item: counts.get(item, 0) for item in ITEMS}


async def quote(conn, profile_id, uid, item, content, multipliers):
    pokemon = await storage.detail(conn, profile_id, uid)
    if pokemon is None:
        return None
    identity, _ = storage.identify(content, pokemon)
    base = [identity[key] for key in ('base_attack', 'base_defense', 'base_stamina')]
    before = tuple(pokemon[key] for key in IVS)
    after = before if perfect(pokemon) else apply(item, before)
    level = pokemon['level_x2']
    return {'cp_before': cp(base, before, level, multipliers=multipliers),
            'cp_after': cp(base, after, level, multipliers=multipliers),
            'stars_before': appraisal(before), 'stars_after': appraisal(after),
            'have': (await held(conn, profile_id))[item], 'perfect': perfect(pokemon),
            'deployed': pokemon['gym_deployment_id'] is not None}


async def use(conn, session, uid, expected_revision, item, content, multipliers):
    if not conn.in_transaction:
        raise RuntimeError('Bottlecap and Vitamin use requires an active writer transaction')
    if item not in ITEMS:
        return {'status': 'refused', 'pokemon': None}
    profile, refusal = await session_owner(conn, session)
    if refusal is not None:
        return {**refusal, 'pokemon': None}
    pid = profile['profile_id']
    pokemon = await storage.detail(conn, pid, uid)
    if pokemon is None:
        return {'status': 'stale', 'pokemon': None}
    key = f'{item}:{uid}:{expected_revision}'
    async with conn.execute('SELECT profile_id,result FROM action_receipts WHERE key=? AND action=?',
                            (key, item)) as cursor:
        receipt = await cursor.fetchone()
    if receipt is not None:
        return json.loads(receipt['result']) if receipt['profile_id'] == pid else {'status': 'stale', 'pokemon': pokemon}
    status = ('deployed' if pokemon['gym_deployment_id'] is not None else
              'stale' if pokemon['revision'] != expected_revision else
              'perfect' if perfect(pokemon) else
              'missing' if (await held(conn, pid))[item] < 1 else None)
    if status is not None:
        return {'status': status, 'pokemon': pokemon}

    async def compute(conn):
        changed = dict(zip(IVS, apply(item, tuple(pokemon[key] for key in IVS))))
        await conn.execute('UPDATE pokemon SET iv_attack=?,iv_defense=?,iv_stamina=?,revision=revision+1 '
                           "WHERE pokemon_uid=? AND profile_id=? AND revision=? AND state='owned'",
                           (*changed.values(), uid, pid, expected_revision))
        await conn.execute('UPDATE inventory SET quantity=quantity-1 WHERE profile_id=? AND item_id=?', (pid, item))
        lines = [{'profile_id': pid, 'resource': 'item', 'resource_id': item, 'delta': -1, 'reason': item}]
        return {'status': 'used', 'pokemon': await storage.detail(conn, pid, uid)}, lines

    return await with_receipt(conn, key, item, compute, profile_id=pid)
