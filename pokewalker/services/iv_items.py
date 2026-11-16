"""Owner amendment 2026-11-12: Bottlecap and Vitamin raise one owned Pokemon's lowest IV."""

import json

from pokewalker.db import with_receipt
from pokewalker.domain.cp import appraisal, cp
from pokewalker.services import ex_gift, storage
from pokewalker.services.profiles import session_owner


ITEMS = ('bottlecap', 'vitamin')
EX_ITEMS = ('shiny_patch', 'golden_bottlecap')
IVS = ('iv_attack', 'iv_defense', 'iv_stamina')
MAX_IV = 15


def lowest(ivs):
    """Index of the lowest IV; ties go to Attack, then Defense, then Stamina."""
    return list(ivs).index(min(ivs))


def apply(item, ivs, index=None):
    changed = list(ivs)
    index = lowest(ivs) if index is None else index
    changed[index] = MAX_IV if item == 'bottlecap' else min(MAX_IV, changed[index] + 1)
    return tuple(changed)


def perfect(pokemon):
    return all(pokemon[key] == MAX_IV for key in IVS)


async def held(conn, profile_id):
    async with conn.execute('SELECT item_id,quantity FROM inventory WHERE profile_id=? AND item_id IN (?,?)',
                            (profile_id, *ITEMS)) as cursor:
        counts = {row['item_id']: row['quantity'] for row in await cursor.fetchall()}
    return {item: counts.get(item, 0) for item in ITEMS}


def _index(pokemon, stat):
    return lowest(tuple(pokemon[key] for key in IVS)) if stat is None else IVS.index(stat)


async def quote(conn, profile_id, uid, item, content, multipliers, stat=None):
    pokemon = await storage.detail(conn, profile_id, uid)
    if pokemon is None:
        return None
    if item == 'shiny_patch':
        return {'have': (await ex_gift.held(conn, profile_id))[item], 'shiny': bool(pokemon['shiny'])}
    identity, _ = storage.identify(content, pokemon)
    base = [identity[key] for key in ('base_attack', 'base_defense', 'base_stamina')]
    before = tuple(pokemon[key] for key in IVS)
    after = (15, 15, 15) if item == 'golden_bottlecap' else before if perfect(pokemon) else apply(item, before, _index(pokemon, stat))
    level = pokemon['level_x2']
    return {'cp_before': cp(base, before, level, multipliers=multipliers),
            'cp_after': cp(base, after, level, multipliers=multipliers),
            'stars_before': appraisal(before), 'stars_after': appraisal(after),
            'have': (await (ex_gift.held(conn, profile_id) if item in EX_ITEMS else held(conn, profile_id)))[item],
            'perfect': perfect(pokemon),
            'deployed': pokemon['gym_deployment_id'] is not None}


async def use(conn, session, uid, expected_revision, item, content, multipliers, stat=None):
    if not conn.in_transaction:
        raise RuntimeError('Bottlecap and Vitamin use requires an active writer transaction')
    if item not in (*ITEMS, *EX_ITEMS) or (stat is not None and stat not in IVS):
        return {'status': 'refused', 'pokemon': None}
    profile, refusal = await session_owner(conn, session)
    if refusal is not None:
        return {**refusal, 'pokemon': None}
    pid = profile['profile_id']
    key = f'{item}:{uid}:{expected_revision}'
    if item in EX_ITEMS:
        receipt = await ex_gift.recorded(conn, key, item, pid)
        if receipt is not None:
            return receipt
    pokemon = await storage.detail(conn, pid, uid)
    if pokemon is None:
        return {'status': 'stale', 'pokemon': None}
    if item not in EX_ITEMS:
        async with conn.execute('SELECT profile_id,result FROM action_receipts WHERE key=? AND action=?',
                                (key, item)) as cursor:
            receipt = await cursor.fetchone()
        if receipt is not None:
            return json.loads(receipt['result']) if receipt['profile_id'] == pid else {'status': 'stale', 'pokemon': pokemon}
    if item == 'shiny_patch':
        status = ('stale' if pokemon['revision'] != expected_revision else
                  'shiny' if pokemon['shiny'] else
                  'missing' if (await ex_gift.held(conn, pid))[item] < 1 else None)
    else:
        status = ('deployed' if pokemon['gym_deployment_id'] is not None else
                  'stale' if pokemon['revision'] != expected_revision else
                  'perfect' if perfect(pokemon) else
                  'maxed' if stat is not None and pokemon[stat] == MAX_IV else
                  'missing' if (await (ex_gift.held(conn, pid) if item in EX_ITEMS else held(conn, pid)))[item] < 1 else None)
    if status is not None:
        return {'status': status, 'pokemon': pokemon}

    async def compute(conn):
        if item in EX_ITEMS:
            effect = ('shiny=1' if item == 'shiny_patch' else
                      'iv_attack=15,iv_defense=15,iv_stamina=15')
            await conn.execute(f'UPDATE pokemon SET {effect},revision=revision+1 '
                               "WHERE pokemon_uid=? AND profile_id=? AND revision=? AND state='owned'",
                               (uid, pid, expected_revision))
            await ex_gift.take(conn, pid, item)
            lines = [{'profile_id': pid, 'resource': 'ex_item', 'resource_id': item, 'delta': -1, 'reason': item}]
            return {'status': 'used', 'pokemon': await storage.detail(conn, pid, uid)}, lines
        changed = dict(zip(IVS, apply(item, tuple(pokemon[key] for key in IVS), _index(pokemon, stat))))
        await conn.execute('UPDATE pokemon SET iv_attack=?,iv_defense=?,iv_stamina=?,revision=revision+1 '
                           "WHERE pokemon_uid=? AND profile_id=? AND revision=? AND state='owned'",
                           (*changed.values(), uid, pid, expected_revision))
        await conn.execute('UPDATE inventory SET quantity=quantity-1 WHERE profile_id=? AND item_id=?', (pid, item))
        lines = [{'profile_id': pid, 'resource': 'item', 'resource_id': item, 'delta': -1, 'reason': item}]
        return {'status': 'used', 'pokemon': await storage.detail(conn, pid, uid)}, lines

    return await with_receipt(conn, key, item, compute, profile_id=pid)
