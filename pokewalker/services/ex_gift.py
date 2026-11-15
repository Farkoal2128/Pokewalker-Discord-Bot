"""EX-Gift catalog, sends and player claims within the caller's writer transaction."""

import json

from content.balance import load_table
from pokewalker.db import with_receipt
from pokewalker.services.profiles import restrictions, session_owner


EX_ITEMS = {
    'time_gear_fragment': 'Time Gear Fragment',
    'shiny_patch': 'Shiny Patch',
    'golden_bottlecap': 'Golden Bottlecap',
    'ex_attack': 'EX-Attack',
    'ex_defense': 'EX-Defense',
    'arena_ex_voucher': 'Arena EX-Voucher',
}


def label(key, content):
    if key in EX_ITEMS:
        return EX_ITEMS[key]
    if key.startswith('arena_ticket:'):
        return f'{key.split(":", 1)[1].title()} Arena Ticket'
    for item in content['evolution_items']:
        if item['id'] == key:
            return item['name_en']
    return 'Poké Ball' if key == 'poke_ball' else key.replace('_', ' ').title()


def catalog(content):
    rare = load_table('capacities')['limits']['rare_pockets']
    evolution = {item['id'] for item in content['evolution_items']}
    rules = load_table('arena')['rules']
    arena = set(rules['x_items']['items']) | {f'arena_ticket:{tier}' for tier in rules['tickets']['tiers']}
    keys = (set(load_table('conversion_rates')['stardust_per_unit']) - {'evolution_item'}
            | set(rare) | evolution | arena)
    categories = {name: [] for name in ('Balls', 'Berries', 'IV items', 'Arena', 'Evolution', 'Rare')}
    for key in sorted(keys, key=lambda key: (label(key, content), key)):
        category = ('Rare' if key in rare else
                    'Evolution' if key in evolution else
                    'Arena' if key in arena else
                    'IV items' if key in ('bottlecap', 'vitamin') else
                    'Balls' if key.endswith('_ball') else
                    'Berries' if key.endswith('_berry') else 'Rare')
        categories[category].append(key)
    return categories


def page(content, category, ex, n):
    keys = list(EX_ITEMS) if ex else catalog(content).get(category, [])
    return (keys[n * 25:(n + 1) * 25] if n >= 0 else []), (len(keys) + 24) // 25


def _population(scope, guild_id, user_id):
    if scope == 'all' and guild_id is None and user_id is None:
        return '1', ()
    if scope == 'server' and guild_id is not None and user_id is None:
        return 'guild_id=?', (str(guild_id),)
    if scope == 'user' and guild_id is not None and user_id is not None:
        return 'guild_id=? AND user_id=?', (str(guild_id), str(user_id))
    return None, ()


async def target(conn, scope, guild_id, user_id):
    where, args = _population(scope, guild_id, user_id)
    if where is None:
        return {'status': 'invalid'}
    if scope != 'all':
        async with conn.execute('SELECT 1 FROM guilds WHERE guild_id=?', (str(guild_id),)) as cursor:
            if await cursor.fetchone() is None:
                return {'status': 'unknown_server'}
    async with conn.execute(f'SELECT count(*),count(DISTINCT guild_id) FROM profiles WHERE {where}', args) as cursor:
        recipients, populated = await cursor.fetchone()
    if scope == 'user' and recipients == 0:
        return {'status': 'no_profile'}
    servers = 1
    if scope == 'all':
        async with conn.execute('SELECT count(*) FROM guilds') as cursor:
            servers = (await cursor.fetchone())[0]
    return {'status': 'ok', 'servers': servers, 'servers_with_recipients': populated,
            'recipients': recipients}


def _stored(row):
    return dict(row, items=json.loads(row['items']))


async def lookup(conn, send_id):
    async with conn.execute('SELECT * FROM ex_gifts WHERE gift_id=?', (send_id,)) as cursor:
        row = await cursor.fetchone()
    return _stored(row) if row is not None else None


async def history(conn, offset):
    async with conn.execute('SELECT count(*) FROM ex_gifts') as cursor:
        total = (await cursor.fetchone())[0]
    async with conn.execute('SELECT * FROM ex_gifts ORDER BY created_at DESC,gift_id DESC LIMIT 10 OFFSET ?',
                            (offset,)) as cursor:
        rows = [_stored(row) for row in await cursor.fetchall()]
    return rows, total


async def send(conn, *, send_id, owner_id, admin_guild_id, scope, guild_id, user_id, items, content, now):
    if not conn.in_transaction:
        raise RuntimeError('EX-Gift send requires an active writer transaction')
    if (await restrictions(conn, admin_guild_id, owner_id)).excluded:
        return {'status': 'excluded'}
    saved = await lookup(conn, send_id)
    if saved is not None:
        return ({'status': 'sent', 'replayed': True, **saved} if saved['owner_id'] == str(owner_id)
                else {'status': 'invalid'})
    known = {key for keys in catalog(content).values() for key in keys} | EX_ITEMS.keys()
    if (not isinstance(items, (list, tuple)) or not 1 <= len(items) <= 10
            or any(not isinstance(key, str) or key not in known for key in items)):
        return {'status': 'invalid'}
    counts = await target(conn, scope, guild_id, user_id)
    if counts['status'] != 'ok':
        return counts
    if counts['recipients'] == 0:
        return {'status': 'no_recipients'}
    await conn.execute(
        'INSERT INTO ex_gifts(gift_id,owner_id,scope,guild_id,items,servers,servers_with_recipients,recipients,created_at) '
        'VALUES (?,?,?,?,?,?,?,?,?)',
        (send_id, str(owner_id), scope, str(guild_id) if guild_id is not None else None,
         json.dumps(items), counts['servers'], counts['servers_with_recipients'], counts['recipients'], now))
    where, args = _population(scope, guild_id, user_id)
    await conn.execute('INSERT INTO ex_gift_recipients(gift_id,profile_id) '
                       f'SELECT ?,profile_id FROM profiles WHERE {where}', (send_id, *args))
    return {'status': 'sent', 'replayed': False, **await lookup(conn, send_id)}


async def held(conn, profile_id):
    async with conn.execute('SELECT item_id,quantity FROM ex_items WHERE profile_id=?', (profile_id,)) as cursor:
        counts = {row['item_id']: row['quantity'] for row in await cursor.fetchall()}
    return {item: counts.get(item, 0) for item in EX_ITEMS}


async def take(conn, profile_id, item):
    async with conn.execute('UPDATE ex_items SET quantity=quantity-1 WHERE profile_id=? AND item_id=? '
                            'AND quantity>0', (profile_id, item)) as cursor:
        return cursor.rowcount > 0


async def recorded(conn, key, action, profile_id):
    async with conn.execute('SELECT action,profile_id,result FROM action_receipts WHERE key=?', (key,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return (json.loads(row['result']) if row['action'] == action and row['profile_id'] == profile_id
            else {'status': 'stale'})


async def unclaimed(conn, profile_id, offset):
    async with conn.execute('SELECT count(*) FROM ex_gift_recipients WHERE profile_id=? AND claimed_at IS NULL',
                            (profile_id,)) as cursor:
        total = (await cursor.fetchone())[0]
    async with conn.execute('SELECT g.gift_id,g.created_at,g.items FROM ex_gift_recipients r '
                            'JOIN ex_gifts g ON g.gift_id=r.gift_id WHERE r.profile_id=? AND r.claimed_at IS NULL '
                            'ORDER BY g.created_at,g.gift_id LIMIT 10 OFFSET ?', (profile_id, offset)) as cursor:
        return [_stored(row) for row in await cursor.fetchall()], total


async def has_unclaimed(conn, profile_id):
    async with conn.execute('SELECT EXISTS(SELECT 1 FROM ex_gift_recipients '
                            'WHERE profile_id=? AND claimed_at IS NULL)', (profile_id,)) as cursor:
        return bool((await cursor.fetchone())[0])


async def claim(conn, session, now):
    if not conn.in_transaction:
        raise RuntimeError('EX-Gift claim requires an active writer transaction')
    _, refusal = await session_owner(conn, session)
    if refusal is not None:
        return refusal
    pid = session['profile_id']
    rev = session.get('_original_revision', session['revision'])
    key = f"ex_claim:{session['session_id']}:{rev}"
    saved = await recorded(conn, key, 'ex_claim', pid)
    if saved is not None:
        return saved

    async def compute(conn):
        async with conn.execute('UPDATE ex_gift_recipients SET claimed_at=? '
                                'WHERE profile_id=? AND claimed_at IS NULL RETURNING gift_id', (now, pid)) as cursor:
            ids = [row['gift_id'] for row in await cursor.fetchall()]
        gifts = [await lookup(conn, gift_id) for gift_id in ids]
        inbox, counts = 0, {}
        for gift in sorted(gifts, key=lambda gift: (gift['created_at'], gift['gift_id'])):
            for item in gift['items']:
                if item in EX_ITEMS:
                    await conn.execute('INSERT INTO ex_items VALUES (?,?,1) ON CONFLICT(profile_id,item_id) '
                                       'DO UPDATE SET quantity=quantity+1', (pid, item))
                    counts[item] = counts.get(item, 0) + 1
                else:
                    resource, resource_id = ('arena_ticket', item.split(':', 1)[1]) if item.startswith(
                        'arena_ticket:') else ('item', item)
                    await conn.execute('INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,'
                                       'remaining,created_at) VALUES (?,?,?,?,1,?)',
                                       (pid, f"ex_gift:{gift['gift_id']}", resource, resource_id, now))
                    inbox += 1
        lines = [{'profile_id': pid, 'resource': 'ex_item', 'resource_id': item,
                  'delta': quantity, 'reason': 'ex_claim'} for item, quantity in counts.items()]
        return {'status': 'claimed', 'gifts': len(gifts), 'inbox': inbox, 'ex': counts}, lines

    return await with_receipt(conn, key, 'ex_claim', compute, profile_id=pid)
