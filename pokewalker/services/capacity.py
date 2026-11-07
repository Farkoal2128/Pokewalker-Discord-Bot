"""Guild-scoped capacity quotes and receipt-protected expansion purchases."""

from content.balance import limits, load_table
from pokewalker.db import with_receipt
from pokewalker.services.profiles import session_owner


async def limits_for(conn, profile_id):
    async with conn.execute('SELECT storage_limit,bag_limit FROM profiles WHERE profile_id=?',
                            (profile_id,)) as cursor:
        profile = await cursor.fetchone()
    if profile is None:
        raise ValueError('Profile does not exist')
    return {'storage': profile['storage_limit'], 'bag_units': profile['bag_limit'],
            'rare_pockets': limits()['rare_pockets']}


async def quote(conn, profile_id, kind):
    if kind not in ('storage', 'bag'):
        raise ValueError('Capacity kind must be storage or bag')
    async with conn.execute('SELECT storage_limit,bag_limit,stardust FROM profiles WHERE profile_id=?',
                            (profile_id,)) as cursor:
        profile = await cursor.fetchone()
    if profile is None:
        raise ValueError('Profile does not exist')
    rules = load_table('capacities')['expansion'][kind]
    current, price, maximum = profile[f'{kind}_limit'], rules['stardust'], rules['max']
    at_cap = current >= maximum
    return {'current': current, 'next': min(current + rules['step'], maximum),
            'price': price, 'max': maximum, 'at_cap': at_cap,
            'affordable': not at_cap and profile['stardust'] >= price}


async def expand(conn, session, kind, expected_limit, now):
    if not conn.in_transaction:
        raise RuntimeError('Capacity expansion requires an active writer transaction')
    _, refusal = await session_owner(conn, session)
    if refusal is not None:
        return refusal
    if kind not in ('storage', 'bag'):
        return {'status': 'refused'}
    pid, key = session['profile_id'], f"expand:{session['session_id']}:{session['revision']}"

    async def compute(conn):
        preview = await quote(conn, pid, kind)
        if preview['current'] != expected_limit:
            return {'status': 'stale'}, []
        if preview['at_cap']:
            return {'status': 'at_cap'}, []
        if not preview['affordable']:
            return {'status': 'insufficient'}, []
        step = load_table('capacities')['expansion'][kind]['step']
        await conn.execute(f'UPDATE profiles SET stardust=stardust-?,{kind}_limit={kind}_limit+? '
                           'WHERE profile_id=?', (preview['price'], step, pid))
        lines = [{'profile_id': pid, 'resource': resource, 'resource_id': resource_id,
                  'delta': delta, 'reason': f'expand_{kind}'} for resource, resource_id, delta in
                 (('stardust', None, -preview['price']), ('capacity', kind, step))]
        return await limits_for(conn, pid), lines

    return await with_receipt(conn, key, 'expand', compute, profile_id=pid)
