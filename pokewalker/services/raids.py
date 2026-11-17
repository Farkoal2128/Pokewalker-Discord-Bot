"""Receipt-owned World Legendary spawns and at-most-once public announcements."""

from datetime import datetime, timezone
import json
from uuid import uuid4

import aiohttp
import discord

from content.balance import load_table
from pokewalker.db import with_receipt
from pokewalker.domain import encounters
from pokewalker.services import profiles
from pokewalker.services.items import active_lure, shiny_charm


def _writer(conn):
    if not conn.in_transaction:
        raise RuntimeError('Raids require an active writer transaction')


async def live_spawns(conn, guild_id, now):
    async with conn.execute('SELECT * FROM world_spawns WHERE guild_id=? AND ended=0 AND expires_at>? '
                            'ORDER BY kind DESC', (str(guild_id), now)) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def join(conn, guild_id, user_id, spawn_id, now, rng, content):
    _writer(conn)
    guild_id, user_id = str(guild_id), str(user_id)
    async with conn.execute('SELECT world_spawns.*,ex_raids.shiny,ex_raids.level,'
                            'ex_raids.iv_attack,ex_raids.iv_defense,ex_raids.iv_stamina '
                            'FROM world_spawns LEFT JOIN ex_raids USING (ex_raid_id) '
                            'WHERE spawn_id=? AND world_spawns.guild_id=? '
                            'AND ended=0 AND expires_at>?', (spawn_id, guild_id, now)) as cursor:
        spawn = await cursor.fetchone()
    if spawn is None:
        return {'status': 'none'}
    profile = await profiles.get_profile(conn, guild_id, user_id)
    if profile is None:
        return {'status': 'not_enrolled'}
    if (await profiles.restrictions(conn, guild_id, user_id)).excluded:
        return {'status': 'excluded'}
    async with conn.execute('SELECT encounter_id FROM raid_participation WHERE guild_id=? AND user_id=? AND spawn_id=?',
                            (guild_id, user_id, spawn['spawn_id'])) as cursor:
        participation = await cursor.fetchone()
    if participation is not None:
        return {'status': 'joined', 'encounter_id': participation['encounter_id']}
    pid = profile['profile_id']

    async def compute(conn):
        identity = next(i for i in content['identities'] if i['identity_id'] == spawn['identity_id'])
        lure_id = await active_lure(conn, pid) if spawn['shiny'] is None else None
        rules = load_table('catch')['rules']
        gender, variety = encounters.roll_gender(identity, rng)
        shiny = encounters.roll_shiny(rng, lure_id is not None, rules=rules,
                                      charm=await shiny_charm(conn, pid) == 'on')
        level_x2, ivs = encounters.roll_level_ivs(rng, rules=rules, level_range='raid_level_range')
        if spawn['shiny'] is not None:
            shiny = spawn['shiny']
        if spawn['level'] is not None:
            level_x2 = 2 * spawn['level']
        ivs = tuple(spawn[field] if spawn[field] is not None else rolled
                    for field, rolled in zip(('iv_attack', 'iv_defense', 'iv_stamina'), ivs))
        version, _ = profiles.content_facts(content)
        eid = str(uuid4())
        await conn.execute(
            'INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,'
            'iv_stamina,gender,shiny,tier,route_id,lure_id,state,content_version,created_at,raid_spawn_id) '
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'revealed',?,?,?)",
            (eid, pid, variety['pokemon_id'], level_x2, *ivs, gender or 'genderless', shiny,
             encounters.LEGENDARY, profile['route_id'], lure_id, version, now, spawn['spawn_id']))
        if lure_id is not None:
            await conn.execute('UPDATE active_effects SET remaining_encounters=remaining_encounters-1 WHERE effect_id=?',
                               (lure_id,))
        await conn.execute('INSERT INTO pokedex(profile_id,pokemon_id,seen_at) VALUES (?,?,?) '
                           'ON CONFLICT(profile_id,pokemon_id) DO UPDATE SET seen_at=COALESCE(seen_at,excluded.seen_at)',
                           (pid, identity['species_id'], now))
        await conn.execute('INSERT INTO raid_participation(guild_id,user_id,spawn_id,encounter_id,joined_at) '
                           'VALUES (?,?,?,?,?)', (guild_id, user_id, spawn['spawn_id'], eid, now))
        return {'status': 'new', 'encounter_id': eid}, []

    return await with_receipt(conn, f"raid:{spawn['spawn_id']}:{user_id}", 'raid_join', compute, profile_id=pid)


async def expire(conn, now, guild_id=None):
    _writer(conn)
    async with conn.execute('SELECT spawn_id FROM world_spawns WHERE ended=0 AND expires_at<=? '
                            'AND (? IS NULL OR guild_id=?)', (now, guild_id, guild_id)) as cursor:
        spawns = await cursor.fetchall()
    counts = {'spawns': 0, 'encounters': 0, 'participation': 0}
    for spawn in spawns:
        spawn_id = spawn['spawn_id']
        async with conn.execute("DELETE FROM encounters WHERE raid_spawn_id=? AND state IN ('queued','revealed')",
                                (spawn_id,)) as cursor:
            counts['encounters'] += cursor.rowcount
        async with conn.execute('DELETE FROM raid_participation WHERE spawn_id=?', (spawn_id,)) as cursor:
            counts['participation'] += cursor.rowcount
        await conn.execute('UPDATE world_spawns SET ended=1 WHERE spawn_id=?', (spawn_id,))
        counts['spawns'] += 1
    return counts


async def _refusal(conn, guild_id, now, checked_channel_id):
    """Shared spawn guards: settle the guild's overdue spawn, then refuse in contract order."""
    await expire(conn, now, guild_id)
    async with conn.execute('SELECT raids_enabled,raid_channel_id FROM guilds WHERE guild_id=?',
                            (guild_id,)) as cursor:
        guild = await cursor.fetchone()
    if guild is None or not guild['raids_enabled']:
        return {'status': 'raids_off'}
    if guild['raid_channel_id'] is None:
        return {'status': 'no_channel'}
    if checked_channel_id is None:
        return {'status': 'no_permission'}
    if guild['raid_channel_id'] != str(checked_channel_id):
        return {'status': 'channel_changed'}
    async with conn.execute("SELECT 1 FROM world_spawns WHERE guild_id=? AND ended=0 AND kind='world'",
                            (guild_id,)) as cursor:
        if await cursor.fetchone():
            return {'status': 'active'}
    return None


def _new_spawn(guild_id, pid, now, rng, content, checked_channel_id):
    identity = rng.choice([i for i in content['identities'] if i['is_legendary'] and not i['is_mythical']])
    version, _ = profiles.content_facts(content)
    return {'spawn_id': str(uuid4()), 'guild_id': guild_id, 'channel_id': str(checked_channel_id),
            'pokemon_id': identity['pokemon_id'], 'identity_id': identity['identity_id'],
            'spawned_at': now, 'expires_at': now + 3600, 'spawned_by_profile_id': pid,
            'post_state': 'pending', 'message_id': None, 'ended': 0, 'content_version': version}


async def _insert(conn, result):
    await conn.execute('INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,spawned_at,'
                       'expires_at,spawned_by_profile_id,post_state,message_id,ended,content_version) '
                       'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', tuple(result.values()))


async def spawn(conn, session, now, rng, content, checked_channel_id):
    _writer(conn)
    guild_id, pid = session['guild_id'], session['profile_id']
    _, refusal = await profiles.session_owner(conn, session)
    if refusal is not None:
        return refusal
    key = f"wlt:{session['session_id']}:{session['revision']}"
    async with conn.execute('SELECT profile_id,action,result FROM action_receipts WHERE key=?', (key,)) as cursor:
        receipt = await cursor.fetchone()
    if receipt is not None:
        if receipt['profile_id'] != pid or receipt['action'] != 'wlt_use':
            return {'status': 'stale'}
        return json.loads(receipt['result'])
    refusal = await _refusal(conn, guild_id, now, checked_channel_id)
    if refusal is not None:
        return refusal
    async with conn.execute("SELECT quantity FROM inventory WHERE profile_id=? AND item_id='world_legendary_ticket'",
                            (pid,)) as cursor:
        held = await cursor.fetchone()
    if held is None or held['quantity'] < 1:
        return {'status': 'missing'}

    async def compute(conn):
        result = _new_spawn(guild_id, pid, now, rng, content, checked_channel_id)
        await conn.execute("UPDATE inventory SET quantity=quantity-1 WHERE profile_id=? AND item_id='world_legendary_ticket'",
                           (pid,))
        await _insert(conn, result)
        return {'status': 'spawned', 'spawn': result}, [
            {'profile_id': pid, 'resource': 'item', 'resource_id': 'world_legendary_ticket',
             'delta': -1, 'reason': 'wlt_use'}]

    return await with_receipt(conn, key, 'wlt_use', compute, profile_id=pid)


FORCE_COOLDOWN = 86400


async def force_spawn(conn, guild_id, actor_user_id, reason, now, rng, content, checked_channel_id):
    """Owner amendment 2026-11-12: an administrator spawn with no ticket and a per-server cooldown."""
    _writer(conn)
    guild_id = str(guild_id)
    async with conn.execute("SELECT max(created_at) FROM mod_audit WHERE guild_id=? AND action='force_raid'",
                            (guild_id,)) as cursor:
        last = (await cursor.fetchone())[0]
    async with conn.execute("SELECT force_raid_reset_at FROM guilds WHERE guild_id=?", (guild_id,)) as cursor:
        cleared = await cursor.fetchone()
    if cleared is not None and cleared[0] is not None and last is not None and last <= cleared[0]:
        last = None  # D67 owner reset
    if last is not None and now < last + FORCE_COOLDOWN:
        return {'status': 'cooldown', 'remaining': last + FORCE_COOLDOWN - now}
    refusal = await _refusal(conn, guild_id, now, checked_channel_id)
    if refusal is not None:
        return refusal
    result = _new_spawn(guild_id, None, now, rng, content, checked_channel_id)
    await _insert(conn, result)
    await conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                       "VALUES (?,?,'guild',?,'force_raid',?,?)", (guild_id, str(actor_user_id), guild_id, reason, now))
    return {'status': 'spawned', 'spawn': result}


async def _ex_plan(conn, guild_id, now, checked):
    guild_id = str(guild_id) if guild_id is not None else None
    async with conn.execute(
            "SELECT guild_id,raids_enabled,raid_channel_id,EXISTS(SELECT 1 FROM world_spawns s "
            "WHERE s.guild_id=g.guild_id AND s.kind='ex' AND s.ended=0 AND s.expires_at>?) AS live "
            'FROM guilds g WHERE (? IS NULL OR guild_id=?) ORDER BY guild_id',
            (now, guild_id, guild_id)) as cursor:
        guilds = await cursor.fetchall()
    if guild_id is not None and not guilds:
        return {'status': 'unknown_server'}, []
    targets, skipped = [], {}
    for guild in guilds:
        reason = None
        channel = None
        if not guild['raids_enabled']:
            reason = 'raids_off'
        elif guild['raid_channel_id'] is None:
            reason = 'no_channel'
        else:
            channel = checked(guild['guild_id'], guild['raid_channel_id'])
            if channel is None:
                reason = 'no_permission'
            elif str(channel) != guild['raid_channel_id']:
                reason = 'channel_changed'
            elif guild['live']:
                reason = 'active'
        if reason is not None:
            skipped[reason] = skipped.get(reason, 0) + 1
        else:
            targets.append((guild['guild_id'], str(channel)))
    return dict(status='ok', servers=len(guilds), spawning=len(targets), skipped=skipped), targets


async def ex_target(conn, guild_id, now, checked):
    counts, _ = await _ex_plan(conn, guild_id, now, checked)
    return counts


def _ex_stored(row):
    return dict(row, skipped=json.loads(row['skipped']))


async def ex_lookup(conn, send_id):
    async with conn.execute('SELECT * FROM ex_raids WHERE ex_raid_id=?', (send_id,)) as cursor:
        row = await cursor.fetchone()
    return _ex_stored(row) if row is not None else None


async def ex_history(conn, offset):
    async with conn.execute('SELECT count(*) FROM ex_raids') as cursor:
        total = (await cursor.fetchone())[0]
    async with conn.execute('SELECT * FROM ex_raids ORDER BY created_at DESC,ex_raid_id DESC LIMIT 10 OFFSET ?',
                            (offset,)) as cursor:
        return [_ex_stored(row) for row in await cursor.fetchall()], total


async def ex_commit(conn, *, send_id, owner_id, admin_guild_id, identity_id, locks, hours,
                    guild_id, now, content, checked):
    _writer(conn)
    if (await profiles.restrictions(conn, admin_guild_id, owner_id)).excluded:
        return {'status': 'excluded'}
    saved = await ex_lookup(conn, send_id)
    if saved is not None:
        return ({'status': 'sent', 'replayed': True, **saved} if saved['owner_id'] == str(owner_id)
                else {'status': 'invalid'})
    identity = next((i for i in content['identities'] if i['identity_id'] == identity_id), None)
    bounds = dict(shiny=(0, 1), level=(1, 40), iv_attack=(0, 15), iv_defense=(0, 15), iv_stamina=(0, 15))
    if (identity is None or type(hours) is not int or not 1 <= hours <= 24
            or not isinstance(locks, dict) or locks.keys() - bounds.keys()):
        return {'status': 'invalid'}
    for field, value in locks.items():
        if value is not None and (type(value) is not int and not (field == 'shiny' and type(value) is bool)
                                  or not bounds[field][0] <= value <= bounds[field][1]):
            return {'status': 'invalid'}
    counts, targets = await _ex_plan(conn, guild_id, now, checked)
    if counts['status'] != 'ok':
        return counts
    if not targets:
        return dict(status='nothing', servers=counts['servers'], skipped=counts['skipped'])
    guild_id = str(guild_id) if guild_id is not None else None
    overdue = ('SELECT spawn_id FROM world_spawns WHERE ended=0 AND expires_at<=? '
               'AND (? IS NULL OR guild_id=?)')
    args = (now, guild_id, guild_id)
    # Remove participation first to avoid per-encounter foreign-key scans during settlement.
    await conn.execute(f'DELETE FROM raid_participation WHERE spawn_id IN ({overdue})', args)
    await conn.execute(f"DELETE FROM encounters WHERE state IN ('queued','revealed') AND raid_spawn_id IN ({overdue})", args)
    await conn.execute('UPDATE world_spawns SET ended=1 WHERE spawn_id IN (' + overdue + ')', args)
    await conn.execute(
        'INSERT INTO ex_raids(ex_raid_id,owner_id,identity_id,shiny,level,iv_attack,iv_defense,iv_stamina,'
        'hours,guild_id,servers,spawned,skipped,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (send_id, str(owner_id), identity_id, *(locks.get(field) for field in bounds), hours, guild_id,
         counts['servers'], counts['spawning'], json.dumps(counts['skipped']), now))
    version, _ = profiles.content_facts(content)
    expires_at = now + hours * 3600
    await conn.executemany(
        'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,spawned_at,'
        'expires_at,spawned_by_profile_id,post_state,message_id,ended,content_version,kind,ex_raid_id) '
        "VALUES (?,?,?,?,?,?,?,NULL,'pending',NULL,0,?,'ex',?)",
        ((str(uuid4()), guild, channel, identity['pokemon_id'], identity_id, now, expires_at, version, send_id)
         for guild, channel in targets))
    return {'status': 'sent', 'replayed': False, **await ex_lookup(conn, send_id)}


def checked_channel(guild, guild_id, raid_channel_id):
    """M8.2b: the configured raid channel ID when guild.me may embed and send there, else None."""
    channel = guild.get_channel(int(raid_channel_id)) if raid_channel_id else None
    if channel is not None and str(channel.guild.id) != str(guild_id):
        channel = None
    permissions = channel.permissions_for(guild.me) if channel is not None else None
    return channel.id if permissions and permissions.embed_links and permissions.send_messages else None


def nonce(spawn_id):
    return spawn_id.replace('-', '')[:25]


async def announce(bot, spawn):
    async def claim(conn):
        async with conn.execute("SELECT * FROM world_spawns WHERE spawn_id=? AND guild_id=? AND ended=0 "
                                "AND expires_at>? AND post_state='pending'",
                                (spawn['spawn_id'], spawn['guild_id'], bot.walker.clock())) as cursor:
            saved = await cursor.fetchone()
        if saved is None:
            return None
        await conn.execute("UPDATE world_spawns SET post_state='attempted' WHERE spawn_id=?", (saved['spawn_id'],))
        return dict(saved)

    saved = await bot.writer.run(claim)
    if saved is None:
        return
    identity = next(i for i in bot.content['identities'] if i['identity_id'] == saved['identity_id'])
    until = datetime.fromtimestamp(saved['expires_at'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    embed = discord.Embed(title=f"World Legendary: {identity['name_en']}",
                          description=f"{identity['name_en']} is here! Despawns {until}. Join with /raid.")
    if identity['sprites']['normal'] is not None:
        embed.set_image(url=identity['sprites']['normal'])
    channel = bot.get_channel(int(saved['channel_id']))
    if channel is None:
        return
    try:
        message = await channel.send(embed=embed, nonce=nonce(saved['spawn_id']),
                                     allowed_mentions=discord.AllowedMentions.none())
    except (discord.HTTPException, discord.RateLimited, aiohttp.ClientError, OSError):
        return

    async def sent(conn):
        await conn.execute("UPDATE world_spawns SET post_state='sent',message_id=? "
                           "WHERE spawn_id=? AND guild_id=? AND post_state='attempted'",
                           (str(message.id), saved['spawn_id'], saved['guild_id']))
    await bot.writer.run(sent)


async def resume_pending(bot):
    async def pending(conn):
        async with conn.execute("SELECT * FROM world_spawns WHERE post_state='pending' AND ended=0 AND expires_at>?",
                                (bot.walker.clock(),)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]
    for spawn in await bot.writer.run(pending):
        await announce(bot, spawn)
