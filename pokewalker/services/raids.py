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
from pokewalker.services.items import active_lure


def _writer(conn):
    if not conn.in_transaction:
        raise RuntimeError('Raids require an active writer transaction')


async def active_spawn(conn, guild_id, now):
    async with conn.execute('SELECT * FROM world_spawns WHERE guild_id=? AND ended=0 AND expires_at>?',
                            (str(guild_id), now)) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def join(conn, guild_id, user_id, now, rng, content):
    _writer(conn)
    guild_id, user_id = str(guild_id), str(user_id)
    spawn = await active_spawn(conn, guild_id, now)
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
        lure_id = await active_lure(conn, pid)
        rules = load_table('catch')['rules']
        gender, variety = encounters.roll_gender(identity, rng)
        shiny = encounters.roll_shiny(rng, lure_id is not None, rules=rules)
        level_x2, ivs = encounters.roll_level_ivs(rng, rules=rules)
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
    async with conn.execute('SELECT 1 FROM world_spawns WHERE guild_id=? AND ended=0', (guild_id,)) as cursor:
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
