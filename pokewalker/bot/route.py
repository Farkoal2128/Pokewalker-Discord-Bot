"""Private route selection; existing encounter rolls stay frozen."""

import discord

from content.balance import load_table
from pokewalker.bot.screens_catch import custom_id
from pokewalker.services.profiles import lifetime_steps_c


def render(state):
    embed = discord.Embed(title='Routes')
    locked_steps = state.get('locked_steps', {})
    for route in state['routes']:
        groups = [f"{weight}: " + ', '.join(kind.title() for kind, value in route['weights'].items()
                                          if value == weight) for weight in (3, 2, 1)]
        remaining = locked_steps.get(route['id'], 0)
        embed.add_field(name=route['name'] + (' · Current' if route['id'] == state['route_id'] else '')
                        + (f' · Locked — {remaining} steps' if remaining else ''),
                        value='\n'.join(groups), inline=False)
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Select(placeholder='Choose a route', custom_id=custom_id(state, 'route_pick'),
                                   options=[discord.SelectOption(label=route['name'], value=route['id'],
                                                                 default=route['id'] == state['route_id'])
                                            for route in state['routes']
                                            if not locked_steps.get(route['id'], 0)
                                            or route['id'] == state['route_id']]))
    view.add_item(discord.ui.Button(label='Back', custom_id=custom_id(state, 'home')))
    return {'embed': embed, 'view': view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    async def route(conn, session, interaction):
        async with conn.execute('SELECT route_id FROM profiles WHERE profile_id=?',
                                (session['profile_id'],)) as cursor:
            profile = await cursor.fetchone()
        if profile is None:
            raise _Refused(REOPEN)
        routes = load_table('routes')['routes']
        lifetime_c = await lifetime_steps_c(conn, session['profile_id'])
        locked_steps = {r['id']: max(0, (r['unlock_steps'] * 100 - lifetime_c + 99) // 100) for r in routes}
        return render({'session': session, 'routes': routes, 'route_id': profile['route_id'],
                       'locked_steps': locked_steps})

    async def pick(conn, session, interaction):
        values = interaction.data.get('values', [])
        if (not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str)
                or values[0] not in walker.bot.content['routes']):
            raise _Refused('Choose one of the displayed routes.')
        target = next(r for r in load_table('routes')['routes'] if r['id'] == values[0])
        lifetime_c = await lifetime_steps_c(conn, session['profile_id'])
        remaining = (target['unlock_steps'] * 100 - lifetime_c + 99) // 100
        if remaining > 0:
            raise _Refused(f"Walk {remaining} more steps to unlock {target['name']}")
        await conn.execute('UPDATE profiles SET route_id=? WHERE profile_id=?', (values[0], session['profile_id']))
        return await route(conn, session, interaction)

    return {'route': route, 'route_pick': pick}
