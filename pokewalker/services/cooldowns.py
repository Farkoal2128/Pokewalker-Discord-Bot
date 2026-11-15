"""D67 owner cooldown resets: clear one player's or a whole server's cooldowns from the admin guild."""

PLAYER = {
    'checkin': 'Check-in',
    'gym_battle': 'Gym battle',
    'gym_feed': 'Razz Berry feeding',
    'arena_run': 'Arena new run',
    'trade': 'Daily trade',
    'trade_ping': 'Trade invite ping',
}
SERVER = {**PLAYER, 'force_raid': 'Force-raid'}
_COLUMNS = {'checkin': 'last_checkin_at', 'gym_battle': 'last_battle_at',
            'trade': 'last_trade_at', 'trade_ping': 'last_trade_ping_at'}


async def reset(conn, guild_id, user_id, cooldown, actor_id, now):
    """Reset `cooldown` ('all' or a key) for one user, or every profile in the guild when user_id is None."""
    if not conn.in_transaction:
        raise RuntimeError('Cooldown reset requires an active writer transaction')
    allowed = PLAYER if user_id is not None else SERVER
    if cooldown != 'all' and cooldown not in allowed:
        raise ValueError('unknown cooldown')
    guild_id = str(guild_id)
    async with conn.execute('SELECT 1 FROM guilds WHERE guild_id=?', (guild_id,)) as cursor:
        if await cursor.fetchone() is None:
            return {'status': 'unknown_server'}
    scope, args = 'guild_id=?', [guild_id]
    if user_id is not None:
        scope, args = 'guild_id=? AND user_id=?', [guild_id, str(user_id)]
    async with conn.execute(f'SELECT count(*) FROM profiles WHERE {scope}', args) as cursor:
        players = (await cursor.fetchone())[0]
    if user_id is not None and not players:
        return {'status': 'no_profile'}
    kinds = list(allowed) if cooldown == 'all' else [cooldown]
    for kind in kinds:
        if kind in _COLUMNS:
            await conn.execute(f'UPDATE profiles SET {_COLUMNS[kind]}=NULL WHERE {scope}', args)
        elif kind == 'arena_run':
            await conn.execute(f'UPDATE profiles SET arena_cooldown_reset_at=? WHERE {scope}', [now, *args])
        elif kind == 'gym_feed':
            await conn.execute('UPDATE gym_deployments SET last_fed_at=NULL WHERE ended_at IS NULL AND '
                               f'profile_id IN (SELECT profile_id FROM profiles WHERE {scope})', args)
        else:
            await conn.execute('UPDATE guilds SET force_raid_reset_at=? WHERE guild_id=?', (now, guild_id))
    await conn.execute('INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) '
                       'VALUES (?,?,?,?,?,?,?)',
                       (guild_id, str(actor_id), 'user' if user_id is not None else 'guild',
                        str(user_id) if user_id is not None else guild_id, 'cooldown_reset', cooldown, now))
    return {'status': 'reset', 'players': players, 'cooldowns': kinds}
