"""EX-Gift catalog and aggregate sends within the caller's writer transaction."""

import json

from content.balance import load_table
from pokewalker.services.profiles import restrictions


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
