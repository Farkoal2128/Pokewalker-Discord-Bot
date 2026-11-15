"""Private EX-Gift inventory, paged deliveries and claim-all screen."""

from datetime import datetime, timezone
import json

import discord

from pokewalker.bot.screens_catch import custom_id
from pokewalker.services import cooldowns, ex_gift as service


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
    if state.get('notice'):
        lines.append(state['notice'])
    view = discord.ui.View(timeout=None)
    for label, action, disabled in (
            ('Claim', 'ex_claim', total == 0), ('Prev', 'ex_gift_prev', offset == 0),
            ('Next', 'ex_gift_next', offset + 10 >= total), ('Back', 'home', False)):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action),
                                        disabled=disabled, row=0))
    quantity = state['held'].get('time_gear_fragment', 0)
    if quantity > 0:
        view.add_item(discord.ui.Button(label=f'Use Time Gear Fragment ({quantity})',
                                        custom_id=custom_id(state, 'ex_use_time_gear_fragment'), row=1))
    return {'embed': discord.Embed(title='EX-Gift', description='\n'.join(lines)), 'view': view}


def render_time_gear(state):
    text = '\n'.join(['Reset your cooldowns in this server?', *cooldowns.PLAYER.values(),
                      'Share and message limits stay.',
                      f"Uses 1 Time Gear Fragment (have {state['quantity']})."])
    view = discord.ui.View(timeout=None)
    for label, action in (('Confirm', 'ex_time_gear_confirm'), ('Back', 'ex_gift')):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action)))
    return {'embed': discord.Embed(title='Use Time Gear Fragment', description=text), 'view': view}


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
                       'content': walker.bot.content, 'notice': notice})

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

    return {'ex_gift': open_gifts, 'ex_gift_prev': previous, 'ex_gift_next': next_page, 'ex_claim': claim,
            'ex_use_time_gear_fragment': time_gear_preview, 'ex_time_gear_confirm': time_gear_confirm}
