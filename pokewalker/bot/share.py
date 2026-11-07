"""Receipt-backed opt-in public embeds; Discord effects follow the commit."""

from datetime import datetime, timezone
import json

import aiohttp
import discord

from pokewalker.bot import screens
from pokewalker.db import with_receipt
from pokewalker.services import profiles, storage


async def allowed(conn, session, pokemon):
    if pokemon is None or pokemon['state'] != 'owned' or pokemon['profile_id'] != session['profile_id']:
        return False
    restrictions = await profiles.restrictions(conn, session['guild_id'], session['user_id'])
    async with conn.execute('SELECT sharing FROM guilds WHERE guild_id=?', (session['guild_id'],)) as cursor:
        guild = await cursor.fetchone()
    return bool(guild and guild['sharing'] and not restrictions.share_banned)


def embed_for(walker, pokemon, interaction, caught):
    info = storage.stats(walker.bot.content, pokemon, walker.multipliers)
    identity, sprite, power = info['identity'], info['sprite'], info['cp']
    name = discord.utils.escape_markdown(interaction.user.display_name)
    date = datetime.fromtimestamp(pokemon['caught_at'], timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    embed = discord.Embed(title=f"{name} {'caught' if caught else 'shares'} {identity['name_en']}",
                          description=f"{identity['name_en']} · {identity['kind']} · {pokemon['gender']}"
                          f"\nShiny: {'Yes' if pokemon['shiny'] else 'No'} · CP {power}"
                          f"\nCatcher: {name} ({interaction.user.id})\nCaught: {date}")
    if sprite is not None:
        embed.set_image(url=sprite)
    return embed


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    async def share(conn, session, interaction):
        profile = await profiles.get_profile(conn, session['guild_id'], session['user_id'])
        if profile is None or profile['profile_id'] != session['profile_id']:
            raise _Refused(REOPEN)
        if (await profiles.restrictions(conn, session['guild_id'], session['user_id'])).share_banned:
            raise _Refused('You are share-banned here.')
        async with conn.execute('SELECT sharing FROM guilds WHERE guild_id=?', (session['guild_id'],)) as cursor:
            guild = await cursor.fetchone()
        if guild is None or not guild['sharing']:
            raise _Refused('Sharing is turned off in this server.')
        selection = json.loads(session['selection'])
        encounter_id = selection.get('encounter_id')
        if encounter_id is not None:
            async with conn.execute("SELECT pokemon.* FROM pokemon JOIN encounters USING (profile_id) "
                                    "WHERE pokemon.source_encounter_id=encounters.encounter_id "
                                    "AND encounters.encounter_id=? AND encounters.state='caught' "
                                    "AND pokemon.profile_id=? AND pokemon.state='owned'",
                                    (encounter_id, session['profile_id'])) as cursor:
                pokemon = await cursor.fetchone()
        else:
            pokemon = await storage.detail(conn, session['profile_id'], selection.get('pokemon_uid'))
        if pokemon is None:
            raise _Refused('Only a currently owned Pokémon can be shared.')
        channel = interaction.channel
        thread = channel is not None and getattr(channel, 'parent_id', None) is not None
        permission = 'send_messages_in_threads' if thread else 'send_messages'
        permissions = channel.permissions_for(interaction.guild.me) if channel is not None else None
        if permissions is None or not permissions.embed_links or not getattr(permissions, permission):
            raise _Refused(f'Missing channel permission: EMBED_LINKS and {permission.upper()} are required.')
        now = walker.clock()
        if profile['last_share_at'] is not None and now - profile['last_share_at'] < 60:
            raise _Refused('You can share at most once per minute.')
        embed = embed_for(walker, pokemon, interaction, encounter_id is not None)
        if encounter_id is not None:
            rendered = screens.render_terminal(await walker.encounter_state(conn, session, encounter_id))
        else:
            rendered = await walker.handlers['storage_detail'](conn, session, interaction)
        reserved = False

        async def reserve(conn):
            nonlocal reserved
            await conn.execute('UPDATE profiles SET last_share_at=? WHERE profile_id=?',
                               (now, session['profile_id']))
            reserved = True
            return {'reserved_at': now}, []

        await with_receipt(conn, f"share:{session['session_id']}:{session['revision']}", 'share', reserve,
                           profile_id=session['profile_id'])

        async def after_commit():
            if not reserved:
                rendered['content'] = 'This share was already reserved; delivery cannot be confirmed. Reopen /walker.'
                return rendered
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except (discord.HTTPException, discord.RateLimited, aiohttp.ClientError, OSError):
                rendered['content'] = 'Share delivery could not be confirmed; it may already be posted. The minute is spent.'
            else:
                rendered['content'] = 'Shared.'
            return rendered

        return {**rendered, 'after_commit': after_commit}

    return {'share': share}
