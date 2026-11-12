"""Guild-scoped player-to-player trades inside the caller's writer transaction."""

import math
from uuid import uuid4

from pokewalker.services import profiles, research, storage

TRADE_SECONDS = 900
CAP_SECONDS = 86400
PING_SECONDS = 600
REFUSED = ('deployed', 'favorite', 'companion')
# protected_reason checks these three before Shiny and Legendary/Mythical, so a neutral
# identity gives the same answer as the real one: only identity-free reasons refuse a trade.
_NEUTRAL = {'is_legendary': False, 'is_mythical': False}
_TRADABLE = ("state='owned' AND favorite=0 AND gym_deployment_id IS NULL "
             'AND pokemon_uid IS NOT (SELECT companion_uid FROM profiles WHERE profile_id=:pid)')


def _writer(conn):
    if not conn.in_transaction:
        raise RuntimeError('Trading requires an active writer transaction')


def tradable_reason(identity, pokemon, profile):
    if pokemon is None or pokemon['state'] != 'owned' or pokemon['profile_id'] != profile['profile_id']:
        return 'not_owned'
    reason = research.protected_reason(identity, pokemon, profile)
    return reason if reason in REFUSED else None


async def eligible_page(conn, profile_id, offset):
    args = {'pid': profile_id, 'offset': offset}
    async with conn.execute(f'SELECT count(*) FROM pokemon WHERE profile_id=:pid AND {_TRADABLE}', args) as cursor:
        eligible = (await cursor.fetchone())[0]
    async with conn.execute("SELECT count(*) FROM pokemon WHERE profile_id=:pid AND state='owned'", args) as cursor:
        owned = (await cursor.fetchone())[0]
    async with conn.execute(f'SELECT * FROM pokemon WHERE profile_id=:pid AND {_TRADABLE} '
                            'ORDER BY caught_at DESC,pokemon_uid LIMIT 10 OFFSET :offset', args) as cursor:
        return [dict(row) for row in await cursor.fetchall()], eligible, owned


def cap_left(profile, now):
    last = profile['last_trade_at']
    return 0 if last is None else max(0, math.ceil(last + CAP_SECONDS - now))


async def _expire(conn, profile_ids, now):
    marks = ','.join('?' * len(profile_ids))
    await conn.execute("UPDATE trades SET state='expired',ended_at=? WHERE state='open' AND expires_at<=? "
                       f'AND (initiator_profile_id IN ({marks}) OR partner_profile_id IN ({marks}))',
                       (now, now, *profile_ids, *profile_ids))


async def _activity(conn, trade_id, now):
    await conn.execute('UPDATE trades SET expires_at=MAX(expires_at,?) WHERE trade_id=?',
                       (now + TRADE_SECONDS, trade_id))


async def _joined_elsewhere(conn, profile_id):
    """User ID of the partner in this member's joined open trade, or None."""
    async with conn.execute('SELECT p.user_id FROM trade_sides s JOIN trade_sides o ON o.trade_id=s.trade_id '
                            'AND o.side<>s.side JOIN profiles p ON p.profile_id=o.profile_id '
                            'WHERE s.profile_id=? AND s.open=1', (profile_id,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row is not None else None


async def open_or_join(conn, session, partner_user_id, now, can_ping):
    _writer(conn)
    me, refusal = await profiles.session_owner(conn, session)
    if refusal:
        return refusal
    guild_id = session['guild_id']
    partner = await profiles.get_profile(conn, guild_id, partner_user_id)
    if partner is None:
        return {'status': 'partner_not_enrolled'}
    if partner['profile_id'] == me['profile_id']:
        return {'status': 'self'}
    if (await profiles.restrictions(conn, guild_id, partner_user_id)).excluded:
        return {'status': 'partner_unavailable'}
    mine, theirs = me['profile_id'], partner['profile_id']
    await _expire(conn, (mine, theirs), now)
    async with conn.execute("SELECT t.trade_id,s.joined_at FROM trades t JOIN trade_sides s "
                            "ON s.trade_id=t.trade_id AND s.profile_id=:me WHERE t.state='open' AND "
                            '((t.initiator_profile_id=:me AND t.partner_profile_id=:them) OR '
                            '(t.initiator_profile_id=:them AND t.partner_profile_id=:me))',
                            {'me': mine, 'them': theirs}) as cursor:
        pair = await cursor.fetchone()
    if pair is not None and pair['joined_at'] is not None:
        return {'status': 'reopened', 'trade_id': pair['trade_id']}
    busy = await _joined_elsewhere(conn, mine)
    if pair is None and busy is not None:
        return {'status': 'busy', 'partner_user_id': busy}
    if cap_left(me, now):
        return {'status': 'capped', 'seconds_left': cap_left(me, now)}
    if cap_left(partner, now):
        return {'status': 'partner_capped'}
    if pair is not None:
        if busy is not None:
            return {'status': 'busy', 'partner_user_id': busy}
        await conn.execute('UPDATE trade_sides SET joined_at=?,open=1 WHERE trade_id=? AND profile_id=?',
                           (now, pair['trade_id'], mine))
        await _activity(conn, pair['trade_id'], now)
        return {'status': 'joined', 'trade_id': pair['trade_id']}
    if await _joined_elsewhere(conn, theirs) is not None:
        return {'status': 'partner_busy'}
    trade_id = str(uuid4())
    await conn.execute('INSERT INTO trades(trade_id,guild_id,initiator_profile_id,partner_profile_id,'
                       'created_at,expires_at) VALUES (?,?,?,?,?,?)',
                       (trade_id, guild_id, mine, theirs, now, now + TRADE_SECONDS))
    await conn.execute('INSERT INTO trade_sides(trade_id,guild_id,side,profile_id,joined_at,open) '
                       'VALUES (?,?,0,?,?,1),(?,?,1,?,NULL,0)',
                       (trade_id, guild_id, mine, now, trade_id, guild_id, theirs))
    last_ping = me['last_trade_ping_at']
    if not can_ping:
        ping = 'no_permission'
    elif last_ping is not None and last_ping > now - PING_SECONDS:
        ping = 'rate_limited'
    else:
        ping = 'reserved'
        await conn.execute('UPDATE profiles SET last_trade_ping_at=? WHERE profile_id=?', (now, mine))
    return {'status': 'opened', 'trade_id': trade_id, 'ping': ping}


async def _sides(conn, trade_id):
    async with conn.execute('SELECT * FROM trade_sides WHERE trade_id=? ORDER BY side', (trade_id,)) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def current(conn, session, now):
    _writer(conn)
    me, refusal = await profiles.session_owner(conn, session)
    if refusal:
        return None
    await _expire(conn, (me['profile_id'],), now)
    async with conn.execute("SELECT t.* FROM trades t JOIN trade_sides s ON s.trade_id=t.trade_id "
                            "WHERE s.profile_id=? AND s.open=1 AND t.state='open'", (me['profile_id'],)) as cursor:
        row = await cursor.fetchone()
    return None if row is None else {**dict(row), 'sides': await _sides(conn, row['trade_id'])}


async def _participant(conn, session, trade_id, now):
    """(profile, trade) for a joined participant of an open trade, else (None, refusal)."""
    _writer(conn)
    me, refusal = await profiles.session_owner(conn, session)
    if refusal:
        return None, refusal
    async with conn.execute('SELECT t.* FROM trades t JOIN trade_sides s ON s.trade_id=t.trade_id '
                            'WHERE t.trade_id=? AND t.guild_id=? AND s.profile_id=? AND s.joined_at IS NOT NULL',
                            (trade_id, session['guild_id'], me['profile_id'])) as cursor:
        trade = await cursor.fetchone()
    if trade is None:
        return None, {'status': 'stale'}
    if trade['state'] == 'open' and trade['expires_at'] <= now:
        await _expire(conn, (me['profile_id'],), now)
        return None, {'status': 'expired'}
    if trade['state'] != 'open':
        return None, {'status': 'expired' if trade['state'] == 'expired' else 'ended'}
    return me, dict(trade)


async def offer(conn, session, trade_id, pokemon_uid, now):
    me, trade = await _participant(conn, session, trade_id, now)
    if me is None:
        return trade
    pokemon = await storage.detail(conn, me['profile_id'], pokemon_uid)
    reason = tradable_reason(_NEUTRAL, pokemon, me)
    if reason is not None:
        return {'status': 'ineligible', 'reason': reason}
    await conn.execute('UPDATE trade_sides SET pokemon_uid=?,pokemon_revision=? WHERE trade_id=? AND profile_id=?',
                       (pokemon_uid, pokemon['revision'], trade_id, me['profile_id']))
    await conn.execute('UPDATE trade_sides SET confirmed_revision=NULL WHERE trade_id=?', (trade_id,))
    await conn.execute('UPDATE trades SET revision=revision+1 WHERE trade_id=?', (trade_id,))
    await _activity(conn, trade_id, now)
    return {'status': 'offered', 'trade_id': trade_id, 'revision': trade['revision'] + 1}


async def cancel(conn, session, trade_id, now):
    me, trade = await _participant(conn, session, trade_id, now)
    if me is None:
        return trade
    await conn.execute("UPDATE trades SET state='cancelled',ended_at=? WHERE trade_id=?", (now, trade_id))
    return {'status': 'cancelled', 'trade_id': trade_id}
