"""Private Arena screens; services own lifecycle and resource mutations."""

from functools import partial
from itertools import permutations
import json
import math

import discord

from content.balance import limits, load_table
from pokewalker.bot import gyms
from pokewalker.bot.screens_catch import custom_id
from pokewalker.domain import arena as domain
from pokewalker.services import arena as service, profiles, storage


OFF = 'The Arena is turned off in this server.'
CHANGED = 'A Pokémon changed. Pick your team again.'
FIGHTS = ('entry', 'middle', 'boss')
BERRIES = ('razz_berry', 'pinap_berry')
HEALS = ('arena_heal_one', 'arena_heal_two', 'arena_heal_three')
BREAK_ACTIONS = ('arena_fight', 'arena_heal_fight', *HEALS, 'arena_berry', 'arena_order')
STALE = 'The run changed on another screen. This is its current state.'
REDEEM = {f'arena_redeem_{tier}': tier for tier in ('bronze', 'silver', 'gold', 'platinum', 'diamond')}


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
    return {'embed': discord.Embed(title='Arena', description='\n'.join(lines)), 'view': view}


def ticket_contents(rewards):
    encounters = ('fill encounter queue' if rewards['encounters'] == 'fill'
                  else '1 encounter' if rewards['encounters'] == 1 else f"up to {rewards['encounters']} encounters")
    survivors = f"{rewards['survivor_rolls']} survivor reward" + ('' if rewards['survivor_rolls'] == 1 else 's')
    return (f"{encounters}, {rewards['stardust']} Stardust, {rewards['income_rolls']} gym income rolls, "
            + survivors)


def render_tickets(state):
    lines = [f"{tier.title()} ×{state['tickets'].get(tier, 0)}: {ticket_contents(rewards)}"
             for tier, rewards in state['tiers'].items()]
    if state.get('notice'):
        lines.append(state['notice'])
    view = gyms.buttons(state, [(tier.title(), action) for action, tier in REDEEM.items()] + [('Back', 'arena')])
    for button, tier in zip(view.children, REDEEM.values()):
        button.disabled = state['tickets'].get(tier, 0) == 0
    return {'embed': discord.Embed(title='Arena tickets', description='\n'.join(lines)), 'view': view}


def render_redeem(state):
    selection = state['selection']
    lines = [ticket_contents(state['tiers'][selection['tier']]),
             f"{selection['free']} of {state['cap']} slots free: +{selection['add']} encounters"]
    if state.get('notice'):
        lines.append(state['notice'])
    return {'embed': discord.Embed(title=f"Redeem {selection['tier'].title()} Ticket?", description='\n'.join(lines)),
            'view': gyms.buttons(state, [('Confirm', 'arena_redeem_confirm'), ('Back', 'arena_tickets')])}


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


def result_lines(state):
    result = state.get('result')
    if not result:
        return []
    names = [member['snapshot']['combatant']['name'] for member in state['run']['team']]
    lines = [f"{result['enemy']['name']} · CP {result['enemy']['cp']}",
             f"{result['outcome'].title()} · {result['ticks']} ticks"]
    lines.extend(f'{name}: HP {hp}' for name, hp in zip(names, result['party_hp']))
    lines.extend(f'{names[position]} revived at 1 HP.' for position in result['revived'])
    candy = result['candy']
    lines.append(f"Candy: +{candy['quantity']} for {names[result['finisher']]}." if candy else 'Candy: none.')
    if result['slot'] == 2 and result['outcome'] == 'win':
        tickets = result['tickets']
        lines.append(f"Floor {result['floor']} cleared" + (f": {tickets['tier'].title()} Ticket" if tickets else '.'))
        if tickets and tickets['first_clear']:
            lines.append(f"First clear: +1 {tickets['tier'].title()} Ticket")
    return lines


def render_break(state):
    run = state['run']
    enemy = run['enemy']['snapshot']
    lines = result_lines(state) + [f"Floor {run['floor']} · {FIGHTS[run['slot']]} fight",
             f"Next enemy: {enemy['combatant']['name']} · CP {enemy['cp']} · "
             + ' / '.join(t.title() for t in enemy['combatant']['types'])]
    lines.extend(f"{index}: {member['snapshot']['combatant']['name']} · HP {member['hp']} / {member['full_hp']}"
                 for index, member in enumerate(run['team'], 1))
    if state.get('notice'):
        lines.append(state['notice'])
    embed = discord.Embed(title='Arena break', description='\n'.join(lines))
    if state['sprite'] is not None:
        embed.set_image(url=state['sprite'])
    view = discord.ui.View(timeout=None)
    for label, action in [('Fight', 'arena_fight'), ('Heal all & fight', 'arena_heal_fight'), ('Back out', 'arena')]:
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), row=0))
    for member, action in zip(run['team'], HEALS):
        view.add_item(discord.ui.Button(label=f"Heal {member['snapshot']['combatant']['name']}",
                                       custom_id=custom_id(state, action), row=1, disabled=member['hp'] >= member['full_hp']))
    view.add_item(discord.ui.Select(placeholder='Healing berry', custom_id=custom_id(state, 'arena_berry'), row=2,
                                   options=[discord.SelectOption(label=f"{berry.replace('_', ' ').title()} ×{state['stock'].get(berry, 0)}",
                                                                 value=berry, default=state['berry'] == berry) for berry in BERRIES]))
    view.add_item(discord.ui.Select(placeholder='Party order', custom_id=custom_id(state, 'arena_order'), row=3,
                                   options=[discord.SelectOption(label=' → '.join(f"{i + 1}. {run['team'][i]['snapshot']['combatant']['name']}"
                                                                              for i in order)[:100],
                                                                 value=''.join(map(str, order)), default=order == (0, 1, 2))
                                            for order in permutations(range(3))]))
    return {'embed': embed, 'view': view}


def render_defeat(state):
    run = state['run']
    reason = {'loss': 'lost', 'draw': 'double knockout or time limit', 'expired': '18 hours passed'}[run['end_reason']]
    if state.get('result') and run['end_reason'] == 'draw':
        reason = 'time limit' if state['result']['reason'] == 'tick_limit' else 'double knockout'
    lines = result_lines(state) + [f"Floor {run['floor']} · {FIGHTS[run['slot']]} fight: {reason}."]
    if state.get('notice'):
        lines.append(state['notice'])
    view = gyms.buttons(state, [('Tickets', 'arena_tickets'), ('Back', 'arena')])
    return {'embed': discord.Embed(title='Arena defeat', description='\n'.join(lines)), 'view': view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN, EXCLUDED
    rules = load_table('arena')['rules']

    async def tickets_action(action, conn, session, current, now):
        tiers, cap = rules['tickets']['tiers'], limits()['encounter_queue']
        selection = json.loads(session['selection'])
        notice = None

        def preview(tier, quote, notice=None):
            selection = {'phase': 'arena_redeem', 'tier': tier, 'free': quote['free'], 'add': quote['add']}
            session['selection'] = json.dumps(selection)
            return render_redeem({'session': session, 'selection': selection, 'tiers': tiers, 'cap': cap, 'notice': notice})

        if action != 'arena_tickets':
            if action == 'arena_redeem_confirm':
                if (selection.get('phase') != 'arena_redeem' or selection.get('tier') not in tiers
                        or not {'free', 'add'} <= selection.keys()):
                    raise _Refused(REOPEN)
                tier = selection['tier']
                result = await service.redeem(conn, session, tier, expected_free=selection['free'],
                                              expected_add=selection['add'], now=now, rng=walker.rng,
                                              content=walker.bot.content)
                status = result['status']
                if status == 'quote_changed':
                    return preview(tier, result, 'Your queue changed. Nothing was spent.')
                if status == 'redeemed':
                    notice = f"Redeemed a {tier.title()} Ticket: +{result['encounters']} encounters. Rewards are in your Inbox."
                    current = await service.state(conn, session, now)
                elif status not in ('none', 'queue_full'):
                    raise _Refused(EXCLUDED if status == 'excluded' else REOPEN)
            else:
                tier = REDEEM[action]
                quote = await service.redeem_quote(conn, session['profile_id'], tier)
                status = 'none' if not quote['held'] else 'queue_full' if quote['free'] == 0 else 'preview'
                if status == 'preview':
                    return preview(tier, quote)
            if status == 'none':
                notice = f'You have no {tier.title()} Tickets.'
            elif status == 'queue_full':
                notice = f'Your encounter queue is full ({cap}/{cap}). Open an encounter first. Nothing was spent.'
        session['selection'] = '{}'
        return render_tickets({'session': session, 'tickets': current['tickets'], 'tiers': tiers, 'notice': notice})

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

    async def open_break(conn, session, run, result=None, notice=None):
        async with conn.execute('SELECT item_id,quantity FROM inventory WHERE profile_id=? AND item_id IN (?,?)',
                                (session['profile_id'], *BERRIES)) as cursor:
            stock = {row['item_id']: row['quantity'] for row in await cursor.fetchall()}
        berry = json.loads(session['selection']).get('berry')
        if berry not in BERRIES:
            berry = max(BERRIES, key=lambda item: stock.get(item, 0))
        live = run['ended_at'] is None
        session['selection'] = json.dumps({'phase': 'arena_break' if live else 'arena_defeat',
                                            'run_id': run['run_id'], 'run_revision': run['revision'], 'berry': berry})
        state = {'session': session, 'run': run, 'stock': stock, 'berry': berry, 'result': result, 'notice': notice}
        if not live:
            return render_defeat(state)
        _, sprite = storage.identify(walker.bot.content, run['enemy']['snapshot'])
        return render_break({**state, 'sprite': sprite})

    async def break_action(action, conn, session, interaction, current, now):
        selection = json.loads(session['selection'])
        if selection.get('phase') != 'arena_break':
            raise _Refused(REOPEN)
        args = (conn, session, selection['run_id'], selection['run_revision'])
        berry = selection['berry']
        values = interaction.data.get('values', [])
        if action == 'arena_berry':
            run = current['run']
            if current['status'] != 'live' or (run['run_id'], run['revision']) != (selection['run_id'], selection['run_revision']):
                result = {'status': 'stale'}
            else:
                if len(values) != 1 or values[0] not in BERRIES:
                    raise _Refused(REOPEN)
                selection['berry'] = values[0]
                session['selection'] = json.dumps(selection)
                result = {'status': 'selected'}
        elif action == 'arena_order':
            if len(values) != 1 or values[0] not in {''.join(map(str, order)) for order in permutations(range(3))}:
                raise _Refused(REOPEN)
            result = await service.set_order(*args, [int(i) for i in values[0]], now)
        elif action in HEALS:
            result = await service.heal(*args, [HEALS.index(action)], berry, now)
        else:
            function = service.fight if action == 'arena_fight' else service.heal_all_and_fight
            result = await function(*args, *(() if action == 'arena_fight' else (berry,)), now, walker.rng,
                                    walker.bot.content, walker.multipliers, load_table('battle')['rules'], walker.bot.content['type_chart'])
        status, notice = result['status'], None
        if status == 'stale':
            notice = STALE
        elif status == 'missing':
            name = berry.replace('_', ' ').title()
            notice = f'You need {result["short"]} more {name}. Nothing was spent.' if action == 'arena_heal_fight' else f'You have no {name}.'
        elif status not in ('won', 'defeated', 'healed', 'ordered', 'full', 'selected'):
            raise _Refused(EXCLUDED if status == 'excluded' else REOPEN)
        run = (await service.state(conn, session, now))['run']
        if run is None:
            rendered = await dispatch('arena', conn, session, interaction)
            rendered['embed'].description += '\n' + (notice or STALE)
            return rendered
        return await open_break(conn, session, run, result if status in ('won', 'defeated') else None, notice)

    async def dispatch(action, conn, session, interaction):
        now = walker.clock()
        current = await service.state(conn, session, now)
        if current['status'] in ('stale', 'excluded'):
            raise _Refused(EXCLUDED if current['status'] == 'excluded' else REOPEN)
        if action in REDEEM or action in ('arena_tickets', 'arena_redeem_confirm'):
            return await tickets_action(action, conn, session, current, now)
        if action in BREAK_ACTIONS:
            return await break_action(action, conn, session, interaction, current, now)
        selection = json.loads(session['selection'])
        if (action == 'arena_resume' and current['run'] or action == 'arena'
                and current['status'] == 'ended' and selection.get('phase') == 'arena_break'):
            return await open_break(conn, session, current['run'])
        if action in ('arena', 'arena_resume'):
            flags = await profiles.restrictions(conn, session['guild_id'], session['user_id'])
            session['selection'] = json.dumps({'berry': selection['berry']} if selection.get('berry') in BERRIES else {})
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
                return await open_break(conn, session, result['run'])
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
             'arena_team_sort', 'arena_team_pick', 'arena_team_clear', 'arena_start', *BREAK_ACTIONS,
             'arena_tickets', *REDEEM, 'arena_redeem_confirm')}
