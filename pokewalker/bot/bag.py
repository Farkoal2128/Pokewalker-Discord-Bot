"""Private bag, fixed conversion picks and explicit effect confirmations."""

from datetime import datetime, timezone
from functools import partial
import json

import discord

from content.balance import load_table
from pokewalker.bot.screens_catch import custom_id
from pokewalker.services import capacity, items, raids, stepping


def name(item, content=None):
    for kind in (content or {}).get('evolution_items', []):
        if kind['id'] == item:
            return kind['name_en']
    return 'Poké Ball' if item == 'poke_ball' else item.replace('_', ' ').title()


def quantities(item, held):
    return [1] if item in items.RARE else sorted({min(q, held) for q in (1, 5, 10, 25, 50, 100, held)})


def available(state):
    return [item for item in state['rates'] if state['inventory'].get(item, 0) > 0]


def mirror_text(encounters=10, percent=20, eligible=True):
    text = (f"For your next {encounters} generated encounters, each has a {percent}% chance to be a Pokémon "
            "from your companion's family line, on any route. ⚠ The mirror never attracts Legendary, "
            "Mythical or Rare Pokémon — those family members are skipped, and if none qualify the encounter "
            "is a normal one. Existing queued encounters are unchanged.")
    if not eligible:
        text += "\n⚠ Your current companion's family has no Pokémon the mirror can attract."
    return text


def render(state):
    mode, inventory = state.get('mode', 'bag'), state['inventory']
    selection, rates = state['selection'], state['rates']
    held_items = available(state)
    content = state.get('content', {})
    kinds = [kind['id'] for kind in content.get('evolution_items', [])]
    offset = selection.get('offset', 0)
    view = discord.ui.View(timeout=None)
    text = f"{state['units']}/{state['limit']} units · {state['stardust']} Stardust\n"
    text += '\n'.join(f'{name(item, content)} ×{quantity}' for item, quantity in inventory.items()
                      if item not in items.RARE and quantity > 0)
    text += '\n' + '\n'.join(f'{name(item, content)}: {inventory.get(item, 0)}/1' for item in items.RARE)
    active = state.get('lure')
    held = inventory.get('shiny_lure', 0)
    if active:
        text += f"\n{active['remaining_encounters']} encounters remaining"
    mirror = state.get('mirror')
    if mirror:
        text += f"\nCompanion Mirror: {mirror['remaining_encounters']} encounters remaining"
    star_piece = state.get('star_piece')
    if star_piece:
        text += f"\nStar Piece: {star_piece['remaining_rewards']} boosted Stardust rewards left"
    label = 'Stored — available after the current effect ends' if active and held else 'Shiny Lure'
    booster = bool(active) or bool(mirror)
    buttons = [('Convert', 'convert_pick', not held_items), (label, 'shiny_lure', booster or not held),
               ('Back', 'home', False)]
    if kinds:
        buttons.insert(1, ('Buy evolution item', 'buy_pick', False))
    if 'star_piece' in state:
        buttons.insert(-1, ('Star Piece', 'star_piece_confirm',
                           bool(star_piece) or inventory.get('star_piece', 0) < 1))
    if inventory.get('world_legendary_ticket', 0) > 0:
        buttons.insert(-1, ('Use World Legendary Ticket', 'wlt_confirm', False))
    if 'mirror' in state:
        buttons.insert(-1, ('Companion Mirror', 'mirror_confirm',
                            booster or inventory.get('companion_mirror', 0) < 1))
    if state.get('can_expand'):
        buttons.insert(-1, ('Expand bag', 'expand_bag_preview', False))
    if mode in ('pick', 'qty', 'buy_pick'):
        item = selection.get('item')
        choices = kinds if mode == 'buy_pick' else held_items
        options = ([discord.SelectOption(label=name(item, content) +
                                         (f' · have {inventory.get(item, 0)}' if mode == 'buy_pick' else ''),
                                         value=item) for item in choices[offset:offset + 10]] if mode != 'qty' else
                   [discord.SelectOption(label=f'All ({q})' if q == inventory[item] and item not in items.RARE else str(q),
                                         value=str(q)) for q in quantities(item, inventory[item])])
        action = {'pick': 'convert_qty', 'qty': 'convert_preview', 'buy_pick': 'buy_preview'}[mode]
        if options:
            view.add_item(discord.ui.Select(placeholder='Choose quantity' if mode == 'qty' else 'Choose item',
                                           custom_id=custom_id(state, action), options=options, row=1))
        buttons = [('Back', selection.get('back', 'bag'), False)]
        if mode != 'qty':
            prefix = 'buy' if mode == 'buy_pick' else 'convert'
            buttons = [('Prev', f'{prefix}_prev', offset == 0),
                       ('Next', f'{prefix}_next', offset + 10 >= len(choices)), *buttons]
    elif mode in ('preview', 'rare'):
        item, quantity = selection['item'], selection['quantity']
        text = f'{quantity} × {name(item, content)} → {rates[item] * quantity} Stardust\nThis cannot be undone.'
        if mode == 'rare':
            text += f'\nConvert your rare {name(item, content)}?'
        buttons = [('Confirm', 'convert_confirm_rare' if mode == 'rare' else 'convert_confirm', False),
                   ('Back', selection.get('back', 'bag'), False)]
    elif mode == 'buy_preview':
        item, price = selection['item'], state.get('buy_price', 500)
        text = f"{price} Stardust → 1 × {name(item, content)} · have {state['stardust']} Stardust"
        buttons = [('Confirm', 'buy_confirm', state['stardust'] < price), ('Back', 'bag', False)]
    elif mode == 'lure_confirm':
        text = '4× shiny odds for the next 10 generated encounters; existing queued encounters are unchanged.'
        buttons = [('Activate', 'lure_activate', False), ('Back', 'bag', False)]
    elif mode == 'mirror_confirm':
        text = mirror_text(state.get('mirror_encounters', 10), state.get('mirror_percent', 20),
                           state.get('mirror_eligible', True))
        buttons = [('Activate', 'mirror_activate', False), ('Back', 'bag', False)]
    elif mode == 'star_piece_confirm':
        text = '1.5× Stardust on your next 10 catch or find Stardust rewards'
        buttons = [('Activate', 'star_piece_activate', False), ('Back', 'bag', False)]
    elif mode == 'wlt_confirm':
        where = f"<#{state['raid_channel_id']}>" if state.get('raid_channel_id') else 'the raid channel'
        text = f'Spawns a World Legendary in {where} for 60 minutes; cannot be undone'
        buttons = [('Use', 'wlt_use', False), ('Back', 'bag', False)]
    elif mode == 'expand_bag':
        quote = state.get('expand_quote', {})
        text = f"{quote['price']:,} Stardust → {quote['next']:,} units · have {state['stardust']:,} Stardust"
        if quote['at_cap']:
            text += '\nBag is at the maximum capacity.'
        buttons = [('Confirm', 'expand_bag_confirm', quote['at_cap'] or not quote['affordable']),
                   ('Back', selection.get('back', 'bag'), False)]
    if state.get('notice'):
        text += '\n' + state['notice']
    for label, action, disabled in buttons:
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), disabled=disabled,
                                        row=0 if mode in ('pick', 'buy_pick') else None))
    return {'embed': discord.Embed(title='Bag', description=text), 'view': view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    async def state(conn, session, mode='bag', notice=None):
        async with conn.execute('SELECT item_id,quantity FROM inventory WHERE profile_id=?',
                                (session['profile_id'],)) as cursor:
            inventory = {row['item_id']: row['quantity'] for row in await cursor.fetchall()}
        async with conn.execute('SELECT stardust FROM profiles WHERE profile_id=?', (session['profile_id'],)) as cursor:
            profile = await cursor.fetchone()
        if profile is None:
            raise _Refused(REOPEN)
        lure = await items.active_lure(conn, session['profile_id'])
        async with conn.execute('SELECT remaining_encounters FROM active_effects WHERE effect_id=?', (lure,)) as cursor:
            active = await cursor.fetchone()
        mirror = await items.active_mirror(conn, session['profile_id'])
        async with conn.execute('SELECT remaining_encounters FROM active_effects WHERE effect_id=?', (mirror,)) as cursor:
            mirror_active = await cursor.fetchone()
        star_piece = await items.active_star_piece(conn, session['profile_id'])
        async with conn.execute('SELECT remaining_rewards FROM active_effects WHERE effect_id=?', (star_piece,)) as cursor:
            star_active = await cursor.fetchone()
        content = getattr(walker.bot, 'content', None)
        rates = dict(load_table('conversion_rates')['stardust_per_unit'])
        rules = load_table('catch')['rules']
        for kind in (content or {}).get('evolution_items', []):
            rates[kind['id']] = items.rate_for(kind['id'], content)
        return {'session': session, 'selection': json.loads(session['selection']), 'mode': mode,
                'inventory': inventory, 'units': await items.bag_units(conn, session['profile_id']),
                'limit': (await capacity.limits_for(conn, session['profile_id']))['bag_units'],
                'can_expand': True,
                'lure': dict(active) if active is not None else None,
                'star_piece': dict(star_active) if star_active is not None else None,
                'mirror': dict(mirror_active) if mirror_active is not None else None,
                'mirror_encounters': rules['mirror_encounters'],
                'mirror_percent': round(rules['mirror_probability'] * 100),
                'stardust': profile['stardust'], 'rates': rates, 'notice': notice,
                'content': content or {}, 'buy_price': load_table('evolution')['item_price_stardust']}

    async def bag(conn, session, interaction):
        session['selection'] = '{}'
        return render(await state(conn, session))

    async def expand_bag_preview(conn, session, interaction, *, notice=None, back=None):
        current = await state(conn, session, 'expand_bag', notice=notice)
        quote = await capacity.quote(conn, session['profile_id'], 'bag')
        selection = {'phase': 'expand_bag', 'bag_limit': quote['current'],
                     'back': back or current['selection'].get('back', 'bag')}
        session['selection'] = json.dumps(selection)
        return render({**current, 'selection': selection, 'expand_quote': quote})

    async def expand_bag_confirm(conn, session, interaction):
        selection = json.loads(session['selection'])
        if selection.get('phase') != 'expand_bag':
            return await expand_bag_preview(conn, session, interaction,
                                            notice='Preview bag expansion before confirming. Nothing was spent.')
        result = await capacity.expand(conn, session, 'bag', selection.get('bag_limit'), walker.clock())
        if 'status' in result:
            notice = {'stale': 'Bag changed. Preview again. Nothing was spent.',
                      'at_cap': 'Bag is at the maximum capacity. Nothing was spent.',
                      'insufficient': 'Not enough Stardust. Nothing was spent.'}.get(result['status'])
            if notice is None:
                raise _Refused(REOPEN)
            return await expand_bag_preview(conn, session, interaction, notice=notice)
        session['selection'] = '{}'
        if selection.get('back') == 'inbox':
            return await walker.handlers['inbox'](conn, session, interaction)
        return render(await state(conn, session, notice=f"Bag expanded to {result['bag_units']:,} units."))

    async def pick(conn, session, interaction, *, buy=False, delta=None, back=None):
        current = await state(conn, session)
        phase = 'buy_pick' if buy else 'pick'
        if delta is not None and current['selection'].get('phase') != phase:
            raise _Refused(REOPEN)
        choices = ([kind['id'] for kind in current['content'].get('evolution_items', [])]
                   if buy else available(current))
        offset = 0 if delta is None else current['selection'].get('offset', 0) + delta
        offset = min(max(0, offset), max(0, (len(choices) - 1) // 10 * 10))
        session['selection'] = json.dumps({'offset': offset, 'phase': phase,
                                           'back': back or current['selection'].get('back', 'bag')})
        return render(await state(conn, session, phase))

    async def qty(conn, session, interaction):
        current = await state(conn, session)
        values = interaction.data.get('values', [])
        offset = current['selection'].get('offset', 0)
        if len(values) != 1 or values[0] not in available(current)[offset:offset + 10]:
            raise _Refused('Choose a held item with a conversion rate.')
        session['selection'] = json.dumps({'item': values[0], 'phase': 'qty', 'offset': offset,
                                           'back': current['selection'].get('back', 'bag')})
        return render(await state(conn, session, 'qty'))

    async def preview(conn, session, interaction):
        current = await state(conn, session)
        selection, values = current['selection'], interaction.data.get('values', [])
        item = selection.get('item')
        held = current['inventory'].get(item, 0)
        if (selection.get('phase') != 'qty' or held < 1 or len(values) != 1
                or values[0] not in {str(q) for q in quantities(item, held)}):
            raise _Refused('Choose one of the displayed quantities.')
        selection.update(quantity=int(values[0]), phase='preview')
        session['selection'] = json.dumps(selection)
        return render(await state(conn, session, 'preview'))

    async def confirm(conn, session, interaction, *, rare=False):
        selection = json.loads(session['selection'])
        item = selection.get('item')
        if selection.get('phase') != ('rare' if rare else 'preview') or (rare and item not in items.RARE):
            raise _Refused('Preview the conversion before confirming.')
        if item in items.RARE and not rare:
            selection['phase'] = 'rare'
            session['selection'] = json.dumps(selection)
            return render(await state(conn, session, 'rare'))
        content = getattr(walker.bot, 'content', None)
        result = await items.convert(conn, session, item, selection.get('quantity'), content)
        if 'status' in result:
            raise _Refused('Items changed. Reopen Bag to preview again.' if result['status'] == 'changed' else REOPEN)
        session['selection'] = '{}'
        if selection.get('back') == 'inbox':
            return await walker.handlers['inbox'](conn, session, interaction)
        notice = f"{result['quantity']} × {name(result['item'], content)} → {result['stardust']} Stardust"
        return render(await state(conn, session, notice=notice))

    async def buy_preview(conn, session, interaction):
        current = await state(conn, session)
        selection, values = current['selection'], interaction.data.get('values', [])
        offset = selection.get('offset', 0)
        kinds = [kind['id'] for kind in current['content'].get('evolution_items', [])]
        if selection.get('phase') != 'buy_pick' or len(values) != 1 or values[0] not in kinds[offset:offset + 10]:
            raise _Refused('Choose one of the displayed evolution items.')
        session['selection'] = json.dumps({'item': values[0], 'phase': 'buy_preview', 'offset': offset})
        return render(await state(conn, session, 'buy_preview'))

    async def buy_confirm(conn, session, interaction):
        selection = json.loads(session['selection'])
        if selection.get('phase') != 'buy_preview':
            raise _Refused('Preview the purchase before confirming.')
        content = getattr(walker.bot, 'content', {})
        result = await items.buy_evolution_item(conn, session, selection.get('item'), walker.clock(), content)
        if 'status' in result:
            raise _Refused({'bag_full': 'Bag is full. Nothing was spent.',
                            'insufficient': 'Not enough Stardust. Nothing was spent.'}.get(result['status'], REOPEN))
        session['selection'] = '{}'
        notice = f"{result['stardust']} Stardust → 1 × {name(result['item'], content)}"
        return render(await state(conn, session, notice=notice))

    async def confirm_rare(conn, session, interaction):
        return await confirm(conn, session, interaction, rare=True)

    async def lure_confirm(conn, session, interaction):
        current = await state(conn, session)
        if current['lure'] or current['mirror'] or current['inventory'].get('shiny_lure', 0) < 1:
            raise _Refused('No Shiny Lure is available to activate.')
        session['selection'] = json.dumps({'phase': 'lure_confirm'})
        return render(await state(conn, session, 'lure_confirm'))

    async def lure_activate(conn, session, interaction):
        if json.loads(session['selection']).get('phase') != 'lure_confirm':
            raise _Refused('Preview the Shiny Lure before confirming.')
        result = await items.activate_lure(conn, session, walker.clock())
        if 'status' in result:
            raise _Refused('A Shiny Lure is already active.' if result['status'] == 'already_active' else REOPEN)
        session['selection'] = '{}'
        return render(await state(conn, session))

    async def mirror_confirm(conn, session, interaction):
        current = await state(conn, session)
        if current['lure'] or current['mirror'] or current['inventory'].get('companion_mirror', 0) < 1:
            raise _Refused('No Companion Mirror is available to activate.')
        content = getattr(walker.bot, 'content', None)
        pools = await stepping.companion_mirror_pools(conn, session['profile_id'], content) if content else {}
        session['selection'] = json.dumps({'phase': 'mirror_confirm'})
        return render({**await state(conn, session, 'mirror_confirm'), 'mirror_eligible': bool(pools)})

    async def mirror_activate(conn, session, interaction):
        if json.loads(session['selection']).get('phase') != 'mirror_confirm':
            raise _Refused('Preview the Companion Mirror before confirming.')
        result = await items.activate_mirror(conn, session, walker.clock())
        if 'status' in result:
            raise _Refused({'already_active': 'A Shiny Lure or Companion Mirror is already active.',
                            'missing': 'No Companion Mirror is available to activate.'}.get(result['status'], REOPEN))
        session['selection'] = '{}'
        return render(await state(conn, session))

    async def wlt_confirm(conn, session, interaction):
        current = await state(conn, session)
        if current['inventory'].get('world_legendary_ticket', 0) < 1:
            raise _Refused('No World Legendary Ticket is available to use.')
        session['selection'] = json.dumps({'phase': 'wlt_confirm'})
        async with conn.execute('SELECT raid_channel_id FROM guilds WHERE guild_id=?', (session['guild_id'],)) as cursor:
            guild = await cursor.fetchone()
        return render({**await state(conn, session, 'wlt_confirm'), 'raid_channel_id': guild and guild['raid_channel_id']})

    async def wlt_use(conn, session, interaction):
        if json.loads(session['selection']).get('phase') != 'wlt_confirm':
            raise _Refused('Preview the World Legendary Ticket before confirming.')
        async with conn.execute('SELECT raid_channel_id FROM guilds WHERE guild_id=?', (session['guild_id'],)) as cursor:
            guild = await cursor.fetchone()
        channel = interaction.guild.get_channel(int(guild['raid_channel_id'])) if guild and guild['raid_channel_id'] else None
        if channel is not None and str(channel.guild.id) != session['guild_id']:
            channel = None
        permissions = channel.permissions_for(interaction.guild.me) if channel is not None else None
        checked = channel.id if permissions and permissions.embed_links and permissions.send_messages else None
        result = await raids.spawn(conn, session, walker.clock(), walker.rng, walker.bot.content, checked)
        if result['status'] != 'spawned':
            raise _Refused({'raids_off': 'Raids are turned off in this server.',
                            'no_channel': 'No raid channel is configured.',
                            'no_permission': 'Missing raid channel permission: EMBED_LINKS and SEND_MESSAGES are required.',
                            'channel_changed': 'The raid channel changed; try again.',
                            'active': 'A World Legendary is already active in this server.',
                            'missing': 'No World Legendary Ticket is available to use.'}.get(result['status'], REOPEN))
        spawn = result['spawn']
        identity = next(i for i in walker.bot.content['identities'] if i['identity_id'] == spawn['identity_id'])
        until = datetime.fromtimestamp(spawn['expires_at'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        session['selection'] = '{}'
        rendered = render(await state(conn, session, notice=f"Spawned {identity['name_en']} until {until}"))

        async def after_commit():
            await raids.announce(walker.bot, spawn)
            return rendered

        return {**rendered, 'after_commit': after_commit}

    async def star_piece_confirm(conn, session, interaction):
        current = await state(conn, session)
        if current['star_piece'] or current['inventory'].get('star_piece', 0) < 1:
            raise _Refused('No Star Piece is available to activate.')
        session['selection'] = json.dumps({'phase': 'star_piece_confirm'})
        return render(await state(conn, session, 'star_piece_confirm'))

    async def star_piece_activate(conn, session, interaction):
        if json.loads(session['selection']).get('phase') != 'star_piece_confirm':
            raise _Refused('Preview the Star Piece before confirming.')
        result = await items.activate_star_piece(conn, session, walker.clock())
        if 'status' in result:
            raise _Refused('A Star Piece is already active.' if result['status'] == 'already_active' else REOPEN)
        session['selection'] = '{}'
        return render(await state(conn, session))

    return {'bag': bag, 'convert_pick': pick,
            'inbox_expand_bag': partial(expand_bag_preview, back='inbox'),
            'inbox_convert': partial(pick, back='inbox'),
            'expand_bag_preview': expand_bag_preview, 'expand_bag_confirm': expand_bag_confirm,
            'convert_prev': partial(pick, delta=-10), 'convert_next': partial(pick, delta=10),
            'buy_pick': partial(pick, buy=True), 'buy_prev': partial(pick, buy=True, delta=-10),
            'buy_next': partial(pick, buy=True, delta=10), 'buy_preview': buy_preview, 'buy_confirm': buy_confirm,
            'convert_qty': qty, 'convert_preview': preview,
            'shiny_lure': lure_confirm, 'lure_activate': lure_activate,
            'mirror_confirm': mirror_confirm, 'mirror_activate': mirror_activate,
            'wlt_confirm': wlt_confirm, 'wlt_use': wlt_use,
            'star_piece_confirm': star_piece_confirm, 'star_piece_activate': star_piece_activate,
            'convert_confirm': confirm, 'convert_confirm_rare': confirm_rare}
