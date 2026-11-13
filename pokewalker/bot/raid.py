"""D60 private raid entry using the existing Walker session and screens."""

import json

import discord
from discord import app_commands

from pokewalker.bot import screens
from pokewalker.bot.walker import EXCLUDED, _forget, new_session
from pokewalker.services import profiles, raids
from pokewalker.services.deletion import opted_out


def command(bot):
    @app_commands.command(name='raid', description='Join or reopen the active World Legendary')
    @app_commands.guild_only()
    async def raid(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.guild_id is None:
            await interaction.edit_original_response(content='Use /raid in a server.')
            return

        async def open_raid(conn):
            guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
            if await opted_out(conn, guild_id, user_id):
                return {'content': 'Run /walker-account opt-in first'}
            now = bot.walker.clock()

            async def create_session(profile_id, selection):
                return await new_session(conn, guild_id, user_id, profile_id, now, json.dumps(selection))

            profile = await profiles.get_profile(conn, guild_id, user_id)
            if profile is not None:
                if (await profiles.restrictions(conn, guild_id, user_id)).excluded:
                    return {'content': EXCLUDED}
                pending = await bot.walker.pending_catch(conn, profile['profile_id'])
                if pending is not None:
                    session = await create_session(profile['profile_id'], {})
                    return await bot.walker.pending_menu(conn, session, pending)
            result = await raids.join(conn, guild_id, user_id, now, bot.walker.rng, bot.content)
            refusals = {'none': 'No World Legendary is active here.', 'excluded': EXCLUDED,
                        'not_enrolled': 'Open /walker to enroll before joining.'}
            if result['status'] in refusals:
                return {'content': refusals[result['status']]}
            async with conn.execute(
                'SELECT e.*,w.expires_at AS spawn_expires_at FROM encounters e '
                'JOIN profiles p ON p.profile_id=e.profile_id '
                'JOIN world_spawns w ON w.spawn_id=e.raid_spawn_id '
                'WHERE e.encounter_id=? AND p.guild_id=? AND p.user_id=? '
                'AND w.guild_id=? AND w.ended=0 AND w.expires_at>?',
                (result['encounter_id'], guild_id, user_id, guild_id, now)) as cursor:
                encounter = await cursor.fetchone()
            if encounter is None:
                return {'content': 'You already joined this World Legendary; it can be joined once.'}
            selection = {'encounter_id': encounter['encounter_id'], 'ball': 'poke_ball',
                         'berry': None, 'encounter_revision': encounter['revision']}
            session = await create_session(encounter['profile_id'], selection)
            state = await bot.walker.encounter_state(conn, session, encounter['encounter_id'])
            if encounter['state'] in ('queued', 'revealed'):
                return screens.render_catch(state)
            state['recovery'] = True
            return screens.render_terminal(state)

        rendered = await bot.writer.run(open_raid)
        await interaction.edit_original_response(**rendered, allowed_mentions=discord.AllowedMentions.none())
        _forget(rendered)

    return raid
