"""D60 private raid entry using the existing Walker session and screens."""

from datetime import datetime, timezone
import json

import discord
from discord import app_commands

from pokewalker.bot import screens
from pokewalker.services import profiles, raids
from pokewalker.services.deletion import opted_out


async def enter(walker, conn, guild_id, user_id, spawn_id, kind, session=None):
    from pokewalker.bot.walker import EXCLUDED, new_session

    now = walker.clock()
    result = await raids.join(conn, guild_id, user_id, spawn_id, now, walker.rng, walker.bot.content)
    refusals = {'none': 'That raid has ended.', 'excluded': EXCLUDED,
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
        name = 'EX-Raid' if kind == 'ex' else 'World Legendary'
        return {'content': f'You already joined this {name}; it can be joined once.'}
    selection = json.dumps({'encounter_id': encounter['encounter_id'], 'ball': 'poke_ball',
                            'berry': None, 'encounter_revision': encounter['revision']})
    if session is None:
        session = await new_session(conn, guild_id, user_id, encounter['profile_id'], now, selection)
    else:
        session['selection'] = selection
    state = await walker.encounter_state(conn, session, encounter['encounter_id'])
    if encounter['state'] in ('queued', 'revealed'):
        return screens.render_catch(state)
    state['recovery'] = True
    return screens.render_terminal(state)


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    async def pick(conn, session, kind):
        spawn_id = json.loads(session['selection']).get('raid_choices', {}).get(kind)
        if not spawn_id:
            raise _Refused(REOPEN)
        return await enter(walker, conn, session['guild_id'], session['user_id'], spawn_id, kind, session)

    async def pick_world(conn, session, interaction):
        return await pick(conn, session, 'world')

    async def pick_ex(conn, session, interaction):
        return await pick(conn, session, 'ex')

    return {'raid_pick_world': pick_world, 'raid_pick_ex': pick_ex}


def command(bot):
    from pokewalker.bot.walker import EXCLUDED, RESTARTING, _forget, new_session

    @app_commands.command(name='raid', description='Join or reopen an active raid')
    @app_commands.guild_only()
    async def raid(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.guild_id is None:
            await interaction.edit_original_response(content='Use /raid in a server.')
            return
        if getattr(bot, '_stopping', False):  # the drain closes the writer before the gateway
            await interaction.edit_original_response(content=RESTARTING)
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
            spawns = await raids.live_spawns(conn, guild_id, now)
            if not spawns:
                return {'content': 'No raid is active here.'}
            if profile is None:
                return {'content': 'Open /walker to enroll before joining.'}
            if len(spawns) == 1:
                spawn = spawns[0]
                return await enter(bot.walker, conn, guild_id, user_id, spawn['spawn_id'], spawn['kind'])
            session = await create_session(profile['profile_id'],
                                           {'raid_choices': {s['kind']: s['spawn_id'] for s in spawns}})
            view = discord.ui.View(timeout=None)
            for spawn in spawns:
                identity = next(i for i in bot.content['identities'] if i['identity_id'] == spawn['identity_id'])
                name = 'EX-Raid' if spawn['kind'] == 'ex' else 'World Legendary'
                until = datetime.fromtimestamp(spawn['expires_at'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                label = f"{name}: {identity['name_en']} · ends {until}"
                view.add_item(discord.ui.Button(label=label[:80], custom_id=screens.custom_id(
                    {'session': session}, f"raid_pick_{spawn['kind']}")))
            return {'content': 'Two raids are active here. Choose one.', 'view': view}

        rendered = await bot.writer.run(open_raid)
        await interaction.edit_original_response(**rendered, allowed_mentions=discord.AllowedMentions.none())
        _forget(rendered)

    return raid
