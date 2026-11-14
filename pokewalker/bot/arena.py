"""Private Arena screens; services own lifecycle and resource mutations."""

from functools import partial
import json
import math

import discord

from content.balance import load_table
from pokewalker.bot import gyms
from pokewalker.bot.screens_catch import custom_id
from pokewalker.domain import arena as domain
from pokewalker.services import arena as service, profiles, storage


OFF = 'The Arena is turned off in this server.'
CHANGED = 'A Pokémon changed. Pick your team again.'
FIGHTS = ('entry', 'middle', 'boss')


def wait(seconds):
    hours, minutes = divmod(math.ceil(seconds / 60), 60)
    return f'Next run in {hours}h {minutes}m.'


def paused(until):
    return 'Check-ins are paused ' + (f'until {until}.' if until else 'indefinitely.')


def render_home(state):
    lines = [f"Best floor: {state['best_floor']}"]
    if not state['enabled']:
        lines.append(OFF)
    run = state['run']
    if state['status'] == 'live':
        lines.append(f"Run in progress: floor {run['floor']}, {FIGHTS[run['slot']]} fight.")
        actions = [('Resume', 'arena_resume')]
    else:
        if run:
            lines.append(f"Your last run ended on floor {run['floor']}.")
        lines.append(wait(state['cooldown_left']) if state['cooldown_left'] else 'Ready for a new run.')
        actions = [('Start run', 'arena_team')]
    if state['paused']:
        lines.append(paused(state['until']))
    lines.append('Tickets: ' + (', '.join(f'{tier.title()}: {quantity}' for tier, quantity in state['tickets'].items()) or 'none'))
    view = gyms.buttons(state, [*actions, (f"Tickets ({sum(state['tickets'].values())})", 'arena_tickets'), ('Back', 'home')])
    if state['status'] != 'live':
        view.children[0].disabled = not state['enabled'] or state['paused'] or bool(state['cooldown_left'])
    view.children[-2].disabled = True
    return {'embed': discord.Embed(title='Arena', description='\n'.join(lines)), 'view': view}


def render_team(state):
    selection = state['selection']
    lines = [f"{state['total']} owned Pokémon · page {selection['offset'] // 10 + 1}"]
    for position, item in enumerate(state['members'], 1):
        lines.append(f"Team {position}: {item['identity']['name_en']}" if item else f'Team {position}: changed')
        if item and item['special']:
            lines.append(f"{item['identity']['name_en']} is a special Pokémon: it only earns Candy from boss knockouts.")
    if state.get('notice'):
        lines.append(state['notice'])
    view = gyms.buttons(state, [('Prev', 'arena_team_prev'), ('Next', 'arena_team_next'),
                               (gyms.sort_label(selection['favorites_first']), 'arena_team_sort'), ('Back', 'arena')])
    view.children[0].disabled = selection['offset'] == 0
    view.children[1].disabled = selection['offset'] + 10 >= state['total']
    options = []
    for item in state['rows']:
        label = f"{item['identity']['name_en']} · CP {item['cp']} · {' / '.join(t.title() for t in item['identity']['types'])}"
        if item['reason']:
            label += f" · unavailable: {item['reason']}"
        lines.append(label)
        options.append(discord.SelectOption(label=label[:100], value=item['pokemon']['pokemon_uid']))
    if options:
        view.add_item(discord.ui.Select(placeholder='Choose team member', custom_id=custom_id(state, 'arena_team_pick'),
                                       options=options, row=1))
    view.add_item(discord.ui.Button(label='Clear', custom_id=custom_id(state, 'arena_team_clear'), row=2))
    view.add_item(discord.ui.Button(label='Start', custom_id=custom_id(state, 'arena_start'), row=2,
                                   disabled=len(state['members']) != 3 or any(not item or item['reason'] for item in state['members'])))
    return {'embed': discord.Embed(title='Arena team', description='\n'.join(lines)), 'view': view}


def render_break(state):
    run = state['run']
    enemy = run['enemy']['snapshot']
    lines = [f"Floor {run['floor']} · {FIGHTS[run['slot']]} fight",
             f"Next enemy: {enemy['combatant']['name']} · CP {enemy['cp']} · "
             + ' / '.join(t.title() for t in enemy['combatant']['types'])]
    lines.extend(f"{index}: {member['snapshot']['combatant']['name']} · HP {member['hp']} / {member['full_hp']}"
                 for index, member in enumerate(run['team'], 1))
    embed = discord.Embed(title='Arena break', description='\n'.join(lines))
    if state['sprite'] is not None:
        embed.set_image(url=state['sprite'])
    return {'embed': embed, 'view': gyms.buttons(state, [('Back out', 'arena')])}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN, EXCLUDED
    rules = load_table('arena')['rules']

    def pokemon_state(pokemon):
        item = storage.stats(walker.bot.content, pokemon, walker.multipliers)
        return {**item, 'reason': 'deployed' if pokemon['gym_deployment_id'] is not None else None,
                'special': domain.is_special(item['identity'], rules)}

    async def team_state(conn, session, selection, notice=None):
        rows, total = await storage.page(conn, session['profile_id'], selection['offset'],
                                         favorites_first=selection['favorites_first'])
        if selection['offset'] and not rows:
            selection['offset'] = max(0, (total - 1) // 10 * 10)
            rows, total = await storage.page(conn, session['profile_id'], selection['offset'],
                                             favorites_first=selection['favorites_first'])
        members = []
        for uid, revision in selection['team']:
            pokemon = await storage.detail(conn, session['profile_id'], uid)
            item = pokemon_state(pokemon) if pokemon else None
            if item and pokemon['revision'] != revision:
                item['reason'] = 'changed'
            members.append(item)
        return {'session': session, 'selection': selection, 'rows': [pokemon_state(row) for row in rows],
                'members': members, 'total': total, 'notice': notice}

    def open_break(session, run):
        session['selection'] = json.dumps({'phase': 'arena_break', 'run_id': run['run_id'], 'run_revision': run['revision']})
        _, sprite = storage.identify(walker.bot.content, run['enemy']['snapshot'])
        return render_break({'session': session, 'run': run, 'sprite': sprite})

    async def dispatch(action, conn, session, interaction):
        now = walker.clock()
        current = await service.state(conn, session, now)
        if current['status'] in ('stale', 'excluded'):
            raise _Refused(EXCLUDED if current['status'] == 'excluded' else REOPEN)
        if action == 'arena_resume' and current['status'] == 'live':
            return open_break(session, current['run'])
        if action in ('arena', 'arena_resume'):
            flags = await profiles.restrictions(conn, session['guild_id'], session['user_id'])
            session['selection'] = '{}'
            return render_home({'session': session, **current, 'paused': flags.paused,
                                'until': flags.paused_until.isoformat() if flags.paused_until else None})
        selection = json.loads(session['selection'])
        if action == 'arena_team':
            selection = {'phase': 'arena_team', 'team': [], 'offset': 0, 'favorites_first': False}
        elif selection.get('phase') != 'arena_team':
            raise _Refused(REOPEN)
        if action in ('arena_team_prev', 'arena_team_next'):
            _, total = await storage.page(conn, session['profile_id'], 0)
            selection['offset'] = max(0, min(selection['offset'] + (10 if action == 'arena_team_next' else -10),
                                             max(0, (total - 1) // 10 * 10)))
        if action == 'arena_team_sort':
            selection.update(favorites_first=not selection['favorites_first'], offset=0)
        if action == 'arena_team_clear':
            selection['team'] = []
        state = await team_state(conn, session, selection)
        notice = None
        if action == 'arena_team_pick':
            values = interaction.data.get('values', [])
            item = next((item for item in state['rows'] if len(values) == 1 and item['pokemon']['pokemon_uid'] == values[0]), None)
            if (item is None or item['reason'] or len(selection['team']) >= 3
                    or any(uid == values[0] for uid, _ in selection['team'])):
                raise _Refused('Choose a distinct eligible Pokémon on this page.')
            selection['team'].append([values[0], item['pokemon']['revision']])
        if action == 'arena_start':
            result = await service.start(conn, session, selection['team'], now, walker.rng, walker.bot.content, walker.multipliers)
            status = result['status']
            if status in ('started', 'live'):
                return open_break(session, result['run'])
            if status == 'excluded':
                raise _Refused(EXCLUDED)
            notice = {'stale': CHANGED, 'deployed': "A gym defender can't join an Arena team.",
                      'off': OFF, 'invalid': 'Choose three distinct eligible Pokémon.'}.get(status)
            if status == 'cooldown':
                notice = wait(result['seconds_left'])
            elif status == 'paused':
                notice = paused(result['until'])
            elif status == 'stale':
                selection['team'] = []
            if notice is None:
                raise _Refused(REOPEN)
        session['selection'] = json.dumps(selection)
        return render_team(await team_state(conn, session, selection, notice))

    return {name: partial(dispatch, name) for name in
            ('arena', 'arena_resume', 'arena_team', 'arena_team_prev', 'arena_team_next',
             'arena_team_sort', 'arena_team_pick', 'arena_team_clear', 'arena_start')}
