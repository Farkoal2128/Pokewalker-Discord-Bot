"""Private EX-Gift inventory, paged deliveries and claim-all screen."""

from datetime import datetime, timezone
from functools import partial
import json

import discord

from content.balance import load_table
from pokewalker.bot.screens_catch import custom_id
from pokewalker.services import arena as arena_service, cooldowns, ex_gift as service, iv_items, profiles, storage


def render(state):
    total, offset = state['total'], state['selection']['offset']
    lines = ([f'New gifts: {total} · page {offset // 10 + 1}/{(total + 9) // 10}']
             if total else ['No new gifts.'])
    for gift in state['gifts']:
        date = datetime.fromtimestamp(gift['created_at'], timezone.utc).strftime('%Y-%m-%d UTC')
        lines.append(f"{date}: {', '.join(service.label(key, state['content']) for key in gift['items'])}")
    lines.append('EX items:')
    held = [f"{name} ×{state['held'].get(key, 0)}" for key, name in service.EX_ITEMS.items()
            if state['held'].get(key, 0) > 0]
    lines.extend(held or ['No EX items yet.'])
    view = discord.ui.View(timeout=None)
    for label, action, disabled in (
            ('Claim', 'ex_claim', total == 0), ('Prev', 'ex_gift_prev', offset == 0),
            ('Next', 'ex_gift_next', offset + 10 >= total), ('Back', 'home', False)):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action),
                                        disabled=disabled, row=0))
    for item in ('time_gear_fragment', *iv_items.EX_ITEMS, 'ex_attack', 'ex_defense', 'arena_ex_voucher'):
        if state.get('profile', {}).get(f'{item}_armed'):
            lines.append(f'{service.EX_ITEMS[item]} armed for your next new Arena run.')
            continue
        quantity = state['held'].get(item, 0)
        if quantity > 0:
            action = f'ex_arm_{item}' if item in ('ex_attack', 'ex_defense') else f'ex_use_{item}'
            view.add_item(discord.ui.Button(label=f'Use {service.EX_ITEMS[item]} ({quantity})',
                                            custom_id=custom_id(state, action), row=2 if item == 'arena_ex_voucher' else 1))
    if state.get('notice'):
        lines.append(state['notice'])
    return {'embed': discord.Embed(title='EX-Gift', description='\n'.join(lines)), 'view': view}


def render_time_gear(state):
    text = '\n'.join(['Reset your cooldowns in this server?', *cooldowns.PLAYER.values(),
                      'Share and message limits stay.',
                      f"Uses 1 Time Gear Fragment (have {state['quantity']})."])
    view = discord.ui.View(timeout=None)
    for label, action in (('Confirm', 'ex_time_gear_confirm'), ('Back', 'ex_gift')):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action)))
    return {'embed': discord.Embed(title='Use Time Gear Fragment', description=text), 'view': view}


def render_picker(state):
    view = discord.ui.View(timeout=None)
    offset, total = state['selection']['offset'], state['total']
    for label, action, disabled in (('Prev', 'ex_pick_prev', offset == 0),
                                     ('Next', 'ex_pick_next', offset + 10 >= total),
                                     ('Back', 'ex_gift', False)):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), disabled=disabled, row=0))
    if state['rows']:
        view.add_item(discord.ui.Select(custom_id=custom_id(state, 'ex_pick'), row=1,
                                       options=[discord.SelectOption(label=row['label'], value=row['pokemon_uid'])
                                                for row in state['rows']]))
    return {'embed': discord.Embed(title=f"Use {service.EX_ITEMS[state['selection']['ex_item']]}", description='Pick a Pokémon.' if total else
                                   'You have no Pokémon to pick.'), 'view': view}


def render_item_preview(state):
    item, quote = state['item'], state['quote']
    name = service.EX_ITEMS[item]
    text = (f"{state['name']} becomes shiny. Uses 1 Shiny Patch (have {quote['have']})."
            if item == 'shiny_patch' else
            f"CP {quote['cp_before']} → {quote['cp_after']} · Appraisal {quote['stars_before']} → "
            f"{quote['stars_after']} stars · uses 1 {name} (have {quote['have']})")
    view = discord.ui.View(timeout=None)
    for label, action in (('Confirm', f'ex_{item}_confirm'), ('Back', state['back'])):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action)))
    return {'embed': discord.Embed(title=f'Use {name}', description=text), 'view': view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN, EXCLUDED

    async def show(conn, session, selection, notice=None):
        gifts, total = await service.unclaimed(conn, session['profile_id'], selection['offset'])
        if selection['offset'] and not gifts:
            selection['offset'] = max(0, (total - 1) // 10 * 10)
            gifts, total = await service.unclaimed(conn, session['profile_id'], selection['offset'])
        session['selection'] = json.dumps(selection)
        return render({'session': session, 'selection': selection, 'gifts': gifts, 'total': total,
                       'held': await service.held(conn, session['profile_id']),
                       'content': walker.bot.content, 'notice': notice,
                       'profile': await profiles.get_profile(conn, session['guild_id'], session['user_id'])})

    async def open_gifts(conn, session, interaction):
        return await show(conn, session, {'phase': 'ex_gift', 'offset': 0})

    async def page(conn, session, interaction, delta):
        selection = json.loads(session['selection'])
        if selection.get('phase') != 'ex_gift':
            raise _Refused(REOPEN)
        _, total = await service.unclaimed(conn, session['profile_id'], 0)
        selection['offset'] = max(0, min(selection['offset'] + delta, max(0, (total - 1) // 10 * 10)))
        return await show(conn, session, selection)

    async def previous(conn, session, interaction):
        return await page(conn, session, interaction, -10)

    async def next_page(conn, session, interaction):
        return await page(conn, session, interaction, 10)

    async def claim(conn, session, interaction):
        result = await service.claim(conn, session, walker.clock())
        if result['status'] != 'claimed':
            raise _Refused(EXCLUDED if result['status'] == 'excluded' else REOPEN)
        notice = (f"Claimed {result['gifts']} gifts: {result['inbox']} items went to your Inbox."
                  if result['gifts'] else 'No new gifts to claim.')
        added = [f"{name} ×{result['ex'][key]}" for key, name in service.EX_ITEMS.items()
                 if result['ex'].get(key, 0) > 0]
        if added:
            notice += '\nEX items added: ' + ', '.join(added)
        return await show(conn, session, {'phase': 'ex_gift', 'offset': 0}, notice)

    async def arm(conn, session, interaction, *, item):
        result = await arena_service.arm(conn, session, item, walker.clock())
        status = result['status']
        if status not in ('armed', 'armed_already', 'missing'):
            raise _Refused(EXCLUDED if status == 'excluded' else REOPEN)
        name, rules = service.EX_ITEMS[item], load_table('arena')['rules']
        notice = {'armed': f"{name} armed: ×{rules['x_items']['multiplier']} {rules['ex_items']['items'][item]['stat']} "
                           'for your whole next new Arena run. A run in progress does not get it.',
                  'armed_already': f'{name} is already armed. Nothing was spent.',
                  'missing': f'You have no {name}.'}[status]
        return await show(conn, session, {'phase': 'ex_gift', 'offset': 0}, notice)

    async def time_gear_preview(conn, session, interaction):
        quantity = (await service.held(conn, session['profile_id']))['time_gear_fragment']
        if quantity < 1:
            return await show(conn, session, {'phase': 'ex_gift', 'offset': 0},
                              'You have no Time Gear Fragment.')
        session['selection'] = json.dumps({'phase': 'ex_time_gear'})
        return render_time_gear({'session': session, 'quantity': quantity})

    async def time_gear_confirm(conn, session, interaction):
        if json.loads(session['selection']).get('phase') != 'ex_time_gear':
            raise _Refused(REOPEN)
        result = await cooldowns.time_gear(conn, session, walker.clock())
        if result['status'] not in ('used', 'missing'):
            raise _Refused(EXCLUDED if result['status'] == 'excluded' else REOPEN)
        notice = ('Time Gear Fragment used: your cooldowns in this server are reset.'
                  if result['status'] == 'used' else 'You have no Time Gear Fragment.')
        return await show(conn, session, {'phase': 'ex_gift', 'offset': 0}, notice)

    async def pick_page(conn, session, selection):
        rows, total = await storage.page(conn, session['profile_id'], selection['offset'])
        if selection['offset'] and not rows:
            selection['offset'] = max(0, (total - 1) // 10 * 10)
            rows, total = await storage.page(conn, session['profile_id'], selection['offset'])
        selection = {key: selection[key] for key in ('phase', 'ex_item', 'offset')}
        session['selection'] = json.dumps(selection)
        return render_picker({'session': session, 'selection': selection, 'total': total,
                              'rows': [{**row, 'label': f"{storage.identify(walker.bot.content, row)[0]['name_en']} · "
                                        f"CP {storage.stats(walker.bot.content, row, walker.multipliers)['cp']}"
                                        + (' · Shiny' if row['shiny'] else '')} for row in rows]})

    async def item_picker(conn, session, interaction, *, item):
        return await pick_page(conn, session, {'phase': 'ex_pick', 'ex_item': item, 'offset': 0})

    async def pick_paging(conn, session, interaction, delta):
        selection = json.loads(session['selection'])
        if selection.get('phase') != 'ex_pick' or selection.get('ex_item') not in iv_items.EX_ITEMS:
            raise _Refused(REOPEN)
        selection['offset'] = max(0, selection['offset'] + delta)
        return await pick_page(conn, session, selection)

    async def pick_previous(conn, session, interaction):
        return await pick_paging(conn, session, interaction, -10)

    async def pick_next(conn, session, interaction):
        return await pick_paging(conn, session, interaction, 10)

    def item_refusal(status, item):
        name = service.EX_ITEMS[item]
        return {'shiny': 'It is already shiny. No Shiny Patch was used.',
                'perfect': f'Its IVs are already perfect. No {name} was used.',
                'missing': f'You have no {name}. Nothing was used.',
                'deployed': 'Recall it from the gym first',
                'stale': 'That Pokémon changed. Pick it again.', 'excluded': EXCLUDED}.get(status, REOPEN)

    async def item_preview(conn, session, interaction, *, item):
        selection = json.loads(session['selection'])
        pokemon = await storage.detail(conn, session['profile_id'], selection.get('pokemon_uid'))
        if pokemon is None or pokemon['revision'] != selection.get('pokemon_revision'):
            raise _Refused(REOPEN)
        quote = await iv_items.quote(conn, session['profile_id'], pokemon['pokemon_uid'], item,
                                    walker.bot.content, walker.multipliers)
        status = (('shiny' if quote['shiny'] else None) if item == 'shiny_patch' else
                  'deployed' if quote['deployed'] else 'perfect' if quote['perfect'] else None)
        status = status or ('missing' if quote['have'] < 1 else None)
        if status is not None:
            raise _Refused(item_refusal(status, item))
        selection['ex_preview'] = item
        session['selection'] = json.dumps(selection)
        return render_item_preview({'session': session, 'item': item, 'quote': quote,
                                    'name': storage.identify(walker.bot.content, pokemon)[0]['name_en'],
                                    'back': selection.get('ex_back', 'storage_detail')})

    async def pick(conn, session, interaction):
        selection = json.loads(session['selection'])
        if selection.get('phase') != 'ex_pick' or selection.get('ex_item') not in iv_items.EX_ITEMS:
            raise _Refused(REOPEN)
        values = interaction.data.get('values', [])
        if not values:
            return await pick_page(conn, session, selection)
        rows, _ = await storage.page(conn, session['profile_id'], selection['offset'])
        pokemon = next((row for row in rows if row['pokemon_uid'] == values[0]), None) if len(values) == 1 else None
        if pokemon is None:
            raise _Refused(REOPEN)
        selection.update(pokemon_uid=pokemon['pokemon_uid'], pokemon_revision=pokemon['revision'], ex_back='ex_pick')
        selection.pop('ex_preview', None)
        session['selection'] = json.dumps(selection)
        return await item_preview(conn, session, interaction, item=selection['ex_item'])

    async def item_confirm(conn, session, interaction, *, item):
        selection = json.loads(session['selection'])
        if selection.get('ex_preview') != item:
            raise _Refused(f'Preview the {service.EX_ITEMS[item]} before confirming.')
        result = await iv_items.use(conn, session, selection.get('pokemon_uid'), selection.get('pokemon_revision'),
                                    item, walker.bot.content, walker.multipliers)
        if result['status'] != 'used':
            raise _Refused(item_refusal(result['status'], item))
        if selection.get('ex_back') == 'ex_pick':
            name = storage.identify(walker.bot.content, result['pokemon'])[0]['name_en']
            notice = f'{name} is now shiny.' if item == 'shiny_patch' else f"{name}'s IVs are now 15 / 15 / 15."
            return await show(conn, session, {'phase': 'ex_gift', 'offset': 0}, notice)
        return await walker.handlers['storage_detail'](conn, session, interaction)

    return {'ex_gift': open_gifts, 'ex_gift_prev': previous, 'ex_gift_next': next_page, 'ex_claim': claim,
            'ex_use_time_gear_fragment': time_gear_preview, 'ex_time_gear_confirm': time_gear_confirm,
            'ex_use_arena_ex_voucher': walker.handlers['arena_team'],
            **{f'ex_arm_{item}': partial(arm, item=item) for item in ('ex_attack', 'ex_defense')},
            'ex_pick': pick, 'ex_pick_prev': pick_previous, 'ex_pick_next': pick_next,
            **{action: partial(handler, item=item) for item in iv_items.EX_ITEMS for action, handler in
               ((f'ex_use_{item}', item_picker), (f'ex_preview_{item}', item_preview),
                (f'ex_{item}_confirm', item_confirm))}}
