"""Private gym screens; mutations remain in the existing guild-scoped service."""

from functools import partial
import json

import discord

from content.balance import load_table
from pokewalker.bot.screens_catch import custom_id
from pokewalker.domain.battle import defender_hp
from pokewalker.services import gyms as service, profiles, storage


CHANGED = 'This gym changed. Reopen it.'
RECALL = 'Income for full hours is paid; the survivor roll is forfeited'


def buttons(state, actions):
    view = discord.ui.View(timeout=None)
    for label, action in actions:
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action)))
    return view


def render_list(state):
    lines = []
    for item in state['rows']:
        gym, dep = item['gym'], item['deployment']
        lines.append(f"{gym['name']} · empty" if dep is None else
                     f"{gym['name']} · Holder <@{dep['user_id']}> · Defender CP {item['cp']} · "
                     f"held {item['hours']} h · battle HP ×{item['factor']:.1f}")
    view = buttons(state, [('Back', 'home')])
    if state['rows']:
        view.add_item(discord.ui.Select(placeholder='Open gym', custom_id=custom_id(state, 'gym_view'),
                                       options=[discord.SelectOption(label=item['gym']['name'], value=item['gym']['gym_id'])
                                                for item in state['rows']]))
    return {'embed': discord.Embed(title='Gyms', description='\n'.join(lines) or 'No gyms in this server.'), 'view': view}


def render_view(state):
    dep = state['deployment']
    text = 'This gym is empty.'
    actions = [('Deploy', 'gym_deploy')]
    if dep is not None:
        identity, pokemon = state['identity'], state['pokemon']
        text = (f"{identity['name_en']} · {identity['kind']} · {pokemon['gender']}"
                + (' · Shiny' if pokemon['shiny'] else '')
                + f"\nCP {state['cp']} · Types: {' / '.join(t.title() for t in identity['types'])}"
                + f"\nHP {state['hp']} · battle HP {state['battle_hp']} · held {state['hours']} h"
                + f"\nWeakening: battle HP ×{state['factor']:.1f} · Time left: {state['left']} h"
                + f"\nHolder <@{dep['user_id']}>")
        actions = [('Recall', 'gym_recall'), ('Rewards', 'gym_rewards')] if state['mine'] else [('Battle', 'gym_battle')]
    if state.get('notice'):
        text += '\n' + state['notice']
    embed = discord.Embed(title=state['gym']['name'], description=text)
    if dep is not None and state['sprite'] is not None:
        embed.set_image(url=state['sprite'])
    return {'embed': embed, 'view': buttons(state, [*actions, ('Back', 'gyms')])}


def render_deploy(state):
    if state.get('confirm'):
        identity, pokemon = state['identity'], state['pokemon']
        text = (f"Deploy {identity['name_en']} to {state['gym']['name']}?"
                + f"\n{identity['kind']} · {pokemon['gender']}" + (' · Shiny' if pokemon['shiny'] else '')
                + f"\nCP {state['cp']} · HP {state['hp']} · Types: {' / '.join(t.title() for t in identity['types'])}")
        embed = discord.Embed(title='Deploy defender', description=text)
        if state['sprite'] is not None:
            embed.set_image(url=state['sprite'])
        return {'embed': embed, 'view': buttons(state, [('Confirm', 'gym_deploy_confirm'), ('Back', 'gym_deploy')])}
    lines = [f"{state['total']} owned Pokémon · page {state['offset'] // 10 + 1}"]
    options = []
    for item in state['rows']:
        label = f"{item['identity']['name_en']} · CP {item['cp']}" + (f" · disabled: {item['reason']}" if item['reason'] else '')
        lines.append(label)
        options.append(discord.SelectOption(label=label[:100], value=item['pokemon']['pokemon_uid']))
    view = buttons(state, [('Prev', 'gym_deploy_prev'), ('Next', 'gym_deploy_next'), ('Back', 'gym_view')])
    view.children[0].disabled = state['offset'] == 0
    view.children[1].disabled = state['offset'] + 10 >= state['total']
    if options:
        view.add_item(discord.ui.Select(placeholder='Choose defender', custom_id=custom_id(state, 'gym_deploy_select'), options=options))
    return {'embed': discord.Embed(title='Deploy defender', description='\n'.join(lines)), 'view': view}


def render_recall(state):
    return {'embed': discord.Embed(title='Recall defender?', description=RECALL),
            'view': buttons(state, [('Confirm', 'gym_recall_confirm'), ('Back', 'gym_view')])}


def render_party(state):
    selection = state['selection']
    lines = [f"Page {selection['offset'] // 10 + 1} · Fill slot {selection['slot']}"]
    for index, item in enumerate(state['members'], 1):
        lines.append(f"Slot {index}: " + (f"{item['identity']['name_en']} · CP {item['cp']}" if item else 'empty'))
    if state.get('notice'):
        lines.append(state['notice'])
    view = discord.ui.View(timeout=None)
    for label, action, disabled in (('Prev', 'gym_party_prev', selection['offset'] == 0),
                                    ('Next', 'gym_party_next', selection['offset'] + 10 >= state['total']),
                                    ('Back', 'gym_view', False)):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), row=0, disabled=disabled))
    options = []
    for item in state['rows']:
        label = f"{item['identity']['name_en']} · CP {item['cp']} · {' / '.join(item['identity']['types'])}"
        if item['reason']:
            label += f" · unavailable: {item['reason']}"
        lines.append(label)
        options.append(discord.SelectOption(label=label[:100], value=item['pokemon']['pokemon_uid']))
    if options:
        view.add_item(discord.ui.Select(placeholder='Choose attacker', custom_id=custom_id(state, 'gym_party_pick'),
                                       options=options, row=1))
    for slot in range(1, 4):
        view.add_item(discord.ui.Button(label=f'Slot {slot}', custom_id=custom_id(state, 'gym_party_slot_' + ('one', 'two', 'three')[slot - 1]), row=2))
    outcomes = [discord.SelectOption(label='Clear only', value='clear', default=selection['nominee'] is None)]
    for slot, item in enumerate(state['members'], 1):
        if item and not item['reason'] and not (item['identity']['is_legendary'] or item['identity']['is_mythical']):
            uid = item['pokemon']['pokemon_uid']
            outcomes.append(discord.SelectOption(label=f'Claim with slot {slot}', value=uid, default=selection['nominee'] == uid))
    view.add_item(discord.ui.Select(placeholder='Win outcome', custom_id=custom_id(state, 'gym_party_outcome'), options=outcomes, row=3))
    view.add_item(discord.ui.Button(label='Start', custom_id=custom_id(state, 'gym_battle_start'), row=4, disabled=not state['valid']))
    return {'embed': discord.Embed(title='Gym battle party', description='\n'.join(lines)), 'view': view}


def render_result(state):
    result = state['result']
    snapshot = result['snapshot']
    party, defender = snapshot['party'], snapshot['defender']
    def summary(item):
        identity, _ = storage.identify(state['content'], item)
        return (f"{item['combatant']['name']} · {identity['kind']} · {item['gender']}"
                + (' · Shiny' if item['shiny'] else '')
                + f" · CP {item['cp']} · {' / '.join(item['combatant']['types'])} · HP {item['combatant']['hp']}")
    lines = [f"{result['outcome'].title()} · {result['reason']} · {result['ticks']} ticks",
             f"Defender {summary(defender)} · battle HP {snapshot['defender_battle_hp']}"
             if defender is not None else 'Defender details deleted']
    lines.extend(f"Attacker {index}: {summary(item)}" for index, item in enumerate(party, 1))
    lines.append('Survivors: ' + (', '.join(f"slot {i + 1} {party[i]['combatant']['name']}" for i in result['survivors']) or 'none'))
    if result['claimed']:
        nominee = next(item for item in party if item['pokemon_uid'] == snapshot['nominee_uid'])
        lines.append(f"Claimed by {nominee['combatant']['name']}")
    elif result['outcome'] == 'win':
        lines.append('Gym cleared — you already hold a gym, so it stays empty' if snapshot['nominee_uid'] else 'Gym cleared')
    elif defender is not None:
        lines.append('Defender remains in the gym')
    lines.extend(result['events'][:15])
    embed = discord.Embed(title='Gym battle result', description='\n'.join(lines)[:4096])
    if defender is not None:
        _, sprite = storage.identify(state['content'], defender)
        if sprite is not None:
            embed.set_thumbnail(url=sprite)
    _, sprite = storage.identify(state['content'], party[0])
    if sprite is not None:
        embed.set_image(url=sprite)
    return {'embed': embed, 'view': buttons(state, [('Battle log', 'gym_battle_log'), ('Back', 'gyms')])}


def render_log(state):
    text = '\n'.join(state['result']['events'])
    offset = state['offset']
    view = buttons(state, [('Prev', 'gym_log_prev'), ('Next', 'gym_log_next'), ('Back', 'gym_battle_result')])
    view.children[0].disabled = offset == 0
    view.children[1].disabled = offset + 3500 >= len(text)
    return {'embed': discord.Embed(title='Battle log', description=text[offset:offset + 3500] or 'No events.'), 'view': view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN, EXCLUDED
    battle_rules = load_table('battle')['rules']

    def pokemon_state(pokemon):
        return storage.stats(walker.bot.content, pokemon, walker.multipliers)

    async def deployment(conn, session, gym):
        async with conn.execute('SELECT d.*,p.user_id FROM gym_deployments d JOIN profiles p '
                                'ON p.profile_id=d.profile_id AND p.guild_id=d.guild_id '
                                'WHERE d.gym_id=? AND d.guild_id=? AND d.ended_at IS NULL',
                                (gym['gym_id'], session['guild_id'])) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    def holder(session, selection, dep):
        if dep is None or dep['deployment_id'] != selection.get('deployment_id') or dep['profile_id'] != session['profile_id']:
            raise _Refused(CHANGED)

    async def gym_state(conn, session, gym, now, notice=None):
        dep = await deployment(conn, session, gym)
        state = {'session': session, 'gym': gym, 'deployment': dep, 'notice': notice}
        if dep:
            pokemon = await storage.detail(conn, dep['profile_id'], dep['pokemon_uid'])
            hours = max(0, min(7, int((now - dep['deployed_at']) // 3600)))
            state.update(pokemon_state(pokemon), hours=hours, factor=(20 - hours) / 10,
                         left=f"{max(0, (dep['ends_at'] - now) / 3600):.2f}".rstrip('0').rstrip('.'),
                         mine=dep['profile_id'] == session['profile_id'])
            state['battle_hp'] = defender_hp(state['hp'], hours)
        return state

    def reason(pokemon, identity, profile, attacking=False):
        if profile['companion_uid'] == pokemon['pokemon_uid']:
            return 'companion'
        if not attacking and (identity['is_legendary'] or identity['is_mythical']):
            return 'Legendary / Mythical'
        if pokemon['gym_deployment_id'] is not None:
            return 'deployed'
        return None

    async def party_state(conn, session, selection, profile, notice=None):
        rows, total = await storage.page(conn, session['profile_id'], selection['offset'])
        members = []
        for slot in selection['party'] + [None] * (3 - len(selection['party'])):
            pokemon = await storage.detail(conn, session['profile_id'], slot[0]) if slot else None
            item = pokemon_state(pokemon) if pokemon else None
            if item:
                item['reason'] = reason(pokemon, item['identity'], profile, attacking=True)
                if pokemon['revision'] != slot[1]:
                    item['reason'] = 'changed; choose again'
            members.append(item)
        items = [pokemon_state(row) for row in rows]
        for item in items:
            item['reason'] = reason(item['pokemon'], item['identity'], profile, attacking=True)
        valid = bool(members[0]) and all(not slot or item and not item['reason'] for slot, item in zip(selection['party'], members))
        nominee = selection['nominee']
        if nominee:
            item = next((item for item in members if item and item['pokemon']['pokemon_uid'] == nominee), None)
            valid = valid and item is not None and not (item['identity']['is_legendary'] or item['identity']['is_mythical'])
        return {'session': session, 'selection': selection, 'rows': items, 'total': total,
                'members': members, 'valid': bool(valid), 'notice': notice}

    async def battle_dispatch(action, conn, session, interaction, selection, profile, gym, now):
        if action == 'gym_battle':
            dep = await deployment(conn, session, gym)
            if dep is None or dep['profile_id'] == session['profile_id'] or dep['deployment_id'] != selection.get('deployment_id'):
                raise _Refused(CHANGED)
            selection = {'gym_id': gym['gym_id'], 'deployment_id': dep['deployment_id'],
                         'party': [], 'slot': 1, 'offset': 0, 'nominee': None, 'phase': 'gym_party'}
        elif action in ('gym_battle_log', 'gym_log_prev', 'gym_log_next', 'gym_battle_result'):
            if selection.get('phase') != 'gym_result':
                raise _Refused(REOPEN)
            state = {'session': session, 'result': selection['result'], 'content': walker.bot.content}
            if action == 'gym_battle_result':
                return render_result(state)
            text = '\n'.join(selection['result']['events'])
            offset = 0 if action == 'gym_battle_log' else selection.get('log_offset', 0) + (3500 if action == 'gym_log_next' else -3500)
            selection['log_offset'] = max(0, min(offset, max(0, (len(text) - 1) // 3500 * 3500)))
            session['selection'] = json.dumps(selection)
            return render_log({**state, 'offset': selection['log_offset']})
        elif selection.get('phase') != 'gym_party':
            raise _Refused(REOPEN)
        if action != 'gym_battle_start':
            await service.settle(conn, now, walker.rng, walker.bot.content)
        if action in ('gym_party_prev', 'gym_party_next'):
            _, total = await storage.page(conn, session['profile_id'], 0)
            selection['offset'] = max(0, min(selection['offset'] + (10 if action == 'gym_party_next' else -10), max(0, (total - 1) // 10 * 10)))
        if action.startswith('gym_party_slot_'):
            selection['slot'] = ('one', 'two', 'three').index(action.rsplit('_', 1)[1]) + 1
        state = await party_state(conn, session, selection, profile)
        values = interaction.data.get('values', [])
        if action == 'gym_party_pick':
            item = next((item for item in state['rows'] if len(values) == 1 and item['pokemon']['pokemon_uid'] == values[0]), None)
            if item is None or item['reason'] or any(slot and slot[0] == values[0] for i, slot in enumerate(selection['party'], 1) if i != selection['slot']):
                raise _Refused('Choose a distinct eligible attacker on this page.')
            selection['party'].extend([None] * (selection['slot'] - len(selection['party'])))
            selection['party'][selection['slot'] - 1] = [values[0], item['pokemon']['revision']]
            if not any(slot and slot[0] == selection['nominee'] for slot in selection['party']):
                selection['nominee'] = None
        elif action == 'gym_party_outcome':
            allowed = {item['pokemon']['pokemon_uid'] for item in state['members'] if item and not item['reason']
                       and not (item['identity']['is_legendary'] or item['identity']['is_mythical'])}
            if len(values) != 1 or values[0] not in allowed | {'clear'}:
                raise _Refused(REOPEN)
            selection['nominee'] = None if values[0] == 'clear' else values[0]
        elif action == 'gym_battle_start':
            if not state['valid']:
                raise _Refused('Choose an eligible attacker in slot 1 and check your party.')
            result = await service.battle(conn, session, gym['gym_id'], selection['deployment_id'],
                                          [tuple(slot) for slot in selection['party'] if slot], selection['nominee'],
                                          now, walker.rng, walker.bot.content, walker.multipliers, battle_rules, walker.bot.content['type_chart'])
            if result['status'] == 'completed':
                session['selection'] = json.dumps({'gym_id': gym['gym_id'], 'phase': 'gym_result', 'result': result})
                return render_result({'session': session, 'result': result, 'content': walker.bot.content})
            if result['status'] not in ('stale', 'cooldown'):
                raise _Refused(REOPEN)
            state['notice'] = CHANGED if result['status'] == 'stale' else 'Battle cooldown: wait 10 minutes after your last completed battle.'
        session['selection'] = json.dumps(selection)
        return render_party(await party_state(conn, session, selection, profile, state.get('notice')))

    async def dispatch(action, conn, session, interaction):
        now = walker.clock()
        guild = session['guild_id']
        selection = json.loads(session['selection'])
        profile = await profiles.get_profile(conn, guild, session['user_id'])
        if profile is None or profile['profile_id'] != session['profile_id']:
            raise _Refused(REOPEN)
        if (await profiles.restrictions(conn, guild, session['user_id'])).excluded:
            raise _Refused(EXCLUDED)
        gym = None
        if action != 'gyms':
            values = interaction.data.get('values', [])
            if action == 'gym_view' and values and len(values) != 1:
                raise _Refused(REOPEN)
            gym_id = values[0] if action == 'gym_view' and len(values) == 1 else selection.get('gym_id')
            gym = await service.get_gym(conn, guild, gym_id)
            if gym is None or gym['retired_at'] is not None:
                raise _Refused(CHANGED if action == 'gym_deploy_confirm' else REOPEN)
            if action in ('gym_recall', 'gym_recall_confirm', 'gym_rewards'):
                holder(session, selection, await deployment(conn, session, gym))
        if action == 'gym_battle' or action.startswith(('gym_party_', 'gym_battle_', 'gym_log_')):
            return await battle_dispatch(action, conn, session, interaction, selection, profile, gym, now)
        await service.settle(conn, now, walker.rng, walker.bot.content)
        if action == 'gyms':
            rows = [await gym_state(conn, session, item, now) for item in await service.list_gyms(conn, guild)]
            session['selection'] = '{}'
            return render_list({'session': session, 'rows': rows})
        if action == 'gym_view':
            state = await gym_state(conn, session, gym, now)
            session['selection'] = json.dumps({'gym_id': gym['gym_id'],
                                               'deployment_id': state['deployment']['deployment_id'] if state['deployment'] else None})
            return render_view(state)
        if action in ('gym_deploy', 'gym_deploy_prev', 'gym_deploy_next', 'gym_deploy_select'):
            offset = max(0, selection.get('offset', 0) + {'gym_deploy_prev': -10, 'gym_deploy_next': 10}.get(action, 0))
            if action == 'gym_deploy':
                offset = 0
            rows, total = await storage.page(conn, session['profile_id'], offset)
            if offset and not rows:
                offset = max(0, (total - 1) // 10 * 10)
                rows, total = await storage.page(conn, session['profile_id'], offset)
            if action == 'gym_deploy_select':
                values = interaction.data.get('values', [])
                pokemon = next((row for row in rows if len(values) == 1 and row['pokemon_uid'] == values[0]), None)
                if pokemon is None:
                    raise _Refused(REOPEN)
                item = pokemon_state(pokemon)
                if reason(pokemon, item['identity'], profile):
                    raise _Refused('This Pokémon cannot defend a gym.')
                selection.update(phase='gym_deploy_confirm', pokemon_uid=pokemon['pokemon_uid'], pokemon_revision=pokemon['revision'])
                session['selection'] = json.dumps(selection)
                return render_deploy({'session': session, 'gym': gym, 'confirm': True, **item})
            session['selection'] = json.dumps({'gym_id': gym['gym_id'], 'offset': offset})
            items = [pokemon_state(row) for row in rows]
            for item in items:
                item['reason'] = reason(item['pokemon'], item['identity'], profile)
            return render_deploy({'session': session, 'rows': items, 'total': total, 'offset': offset})
        notice = None
        if action == 'gym_deploy_confirm':
            if selection.get('phase') != 'gym_deploy_confirm':
                raise _Refused(CHANGED)
            result = await service.deploy(conn, session, gym['gym_id'], selection.get('pokemon_uid'),
                                          selection.get('pokemon_revision'), now, walker.bot.content)
            if result['status'] != 'deployed':
                raise _Refused(CHANGED if result['status'] == 'stale' else 'This Pokémon cannot defend this gym.')
        else:
            dep = await deployment(conn, session, gym)
            holder(session, selection, dep)
            if action == 'gym_recall':
                selection['phase'] = 'gym_recall'
                session['selection'] = json.dumps(selection)
                return render_recall({'session': session})
            if action == 'gym_recall_confirm':
                if selection.get('phase') != 'gym_recall':
                    raise _Refused(CHANGED)
                await service.end_deployment(conn, guild, dep['deployment_id'], 'recalled', now, walker.rng, walker.bot.content)
            elif action == 'gym_rewards':
                result = await service.pay_hours(conn, guild, dep['deployment_id'], now, walker.rng, walker.bot.content)
                notice = f"{result['paid_hours'] - dep['paid_hours']} hours of gym income added to your Inbox"
        state = await gym_state(conn, session, gym, now, notice)
        session['selection'] = json.dumps({'gym_id': gym['gym_id'],
                                           'deployment_id': state['deployment']['deployment_id'] if state['deployment'] else None})
        return render_view(state)

    return {action: partial(dispatch, action) for action in
            ('gyms', 'gym_view', 'gym_deploy', 'gym_deploy_prev', 'gym_deploy_next', 'gym_deploy_select',
             'gym_deploy_confirm', 'gym_recall', 'gym_recall_confirm', 'gym_rewards', 'gym_battle',
             'gym_party_prev', 'gym_party_next', 'gym_party_pick', 'gym_party_slot_one', 'gym_party_slot_two',
             'gym_party_slot_three', 'gym_party_outcome', 'gym_battle_start', 'gym_battle_log', 'gym_battle_result',
             'gym_log_prev', 'gym_log_next')}
