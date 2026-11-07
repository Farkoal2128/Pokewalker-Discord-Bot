"""Private recipe selection and pure evolution previews using artifact names/sprites."""

import json

import discord

from content.balance import load_table
from pokewalker.bot.screens_catch import custom_id
from pokewalker.services import evolution as service, items, profiles, storage


def render_options(state):
    options = state['options']
    assert 1 <= len(options) <= 25, 'Evolution options exceed the single-select contract'
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Select(placeholder='Choose evolution', custom_id=custom_id(state, state['action']),
        options=[discord.SelectOption(label=label, value=value) for label, value in options]))
    view.add_item(discord.ui.Button(label='Back', custom_id=custom_id(state, state['back'])))
    return {'embed': discord.Embed(title='Evolve', description='Choose an evolution recipe.'), 'view': view}


def render_quote(state):
    quote = state['quote']
    text = (f"{quote['target']['name_en']}\nCP {quote['cp_before']} → {quote['cp_after']}"
            f" · {quote['candy_cost']} Candy (have {quote['candy_have']}) · {state['item_name']}")
    if quote['item'] is not None:
        text += f" (have {quote['item_have']})"
    embed = discord.Embed(title='Evolve', description=text)
    if state['sprite'] is not None:
        embed.set_image(url=state['sprite'])
    view = discord.ui.View(timeout=None)
    for label, action, disabled in (('Confirm', 'evolve_confirm', not quote['affordable']),
                                    ('Back', 'storage_detail', False)):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), disabled=disabled))
    if quote['item'] is not None and not quote['item_have'] and state.get('buy_price') is not None:
        price = state['buy_price']
        view.add_item(discord.ui.Button(label=f'Buy & evolve ({price} Stardust)',
            custom_id=custom_id(state, 'evolve_buy_confirm'),
            disabled=quote['candy_have'] < quote['candy_cost'] or state.get('stardust', 0) < price))
    return {'embed': embed, 'view': view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    def item_name(item):
        return (next(i['name_en'] for i in walker.bot.content['evolution_items'] if i['id'] == item)
                if item is not None else 'Candy only')

    async def current(conn, session):
        selection = json.loads(session['selection'])
        pokemon = await storage.detail(conn, session['profile_id'], selection.get('pokemon_uid'))
        if pokemon is None or pokemon['revision'] != selection.get('pokemon_revision'):
            raise _Refused(REOPEN)
        edges = service.options(walker.bot.content, pokemon)
        groups = {}
        for edge in edges:
            groups.setdefault(edge['item'] or '-', []).append(edge)
        assert len(groups) <= 25, 'Evolution item groups exceed the single-select contract'
        assert all(len(group) <= 25 for group in groups.values()), 'Evolution recipes exceed the single-select contract'
        return selection, pokemon, edges, groups

    def show_recipes(session, pokemon, edges, back):
        options = [(f"{service.target(walker.bot.content, pokemon, edge)['name_en']} · {item_name(edge['item'])}",
                    edge['edge_id']) for edge in edges]
        return render_options({'session': session, 'options': options, 'action': 'evolve_pick', 'back': back})

    async def show_quote(conn, session, selection, pokemon, edge_id):
        quote = await service.quote(conn, session['profile_id'], pokemon['pokemon_uid'], edge_id,
                                    walker.bot.content, walker.multipliers)
        if quote is None:
            raise _Refused(REOPEN)
        selection['edge_id'] = edge_id
        session['selection'] = json.dumps(selection)
        _, sprite = storage.identify(walker.bot.content, {**pokemon,
            'pokemon_id': quote['target']['pokemon_id'], 'form_id': quote['target']['form_id']})
        profile = await profiles.get_profile(conn, session['guild_id'], session['user_id'])
        return render_quote({'session': session, 'quote': quote, 'sprite': sprite,
                             'item_name': item_name(quote['item']), 'stardust': profile['stardust'],
                             'buy_price': load_table('evolution')['item_price_stardust']})

    async def evolve(conn, session, interaction):
        selection, pokemon, edges, groups = await current(conn, session)
        if not edges:
            raise _Refused(REOPEN)
        selection.pop('edge_id', None)
        selection.pop('evolve_item', None)
        session['selection'] = json.dumps(selection)
        if len(edges) == 1:
            return await show_quote(conn, session, selection, pokemon, edges[0]['edge_id'])
        if len(edges) > 25:
            options = [(f"{item_name(group[0]['item'])} · {len(group)} forms", item)
                       for item, group in groups.items()]
            return render_options({'session': session, 'options': options,
                                   'action': 'evolve_group', 'back': 'storage_detail'})
        return show_recipes(session, pokemon, edges, 'storage_detail')

    async def group(conn, session, interaction):
        selection, pokemon, edges, groups = await current(conn, session)
        values = interaction.data.get('values', [])
        if len(edges) <= 25 or len(values) != 1 or values[0] not in groups:
            raise _Refused(REOPEN)
        selection['evolve_item'] = values[0]
        selection.pop('edge_id', None)
        session['selection'] = json.dumps(selection)
        return show_recipes(session, pokemon, groups[values[0]], 'evolve')

    async def pick(conn, session, interaction):
        selection, pokemon, edges, groups = await current(conn, session)
        if len(edges) > 25:
            edges = groups.get(selection.get('evolve_item'), [])
        values = interaction.data.get('values', [])
        if len(values) != 1 or values[0] not in {edge['edge_id'] for edge in edges}:
            raise _Refused(REOPEN)
        return await show_quote(conn, session, selection, pokemon, values[0])

    async def confirm(conn, session, interaction):
        selection = json.loads(session['selection'])
        result = await service.evolve(conn, session, selection.get('pokemon_uid'), selection.get('edge_id'),
                                      selection.get('pokemon_revision'), walker.bot.content,
                                      walker.multipliers, walker.clock())
        if result['status'] != 'evolved':
            raise _Refused(REOPEN)
        return await walker.handlers['storage_detail'](conn, session, interaction)

    async def buy_confirm(conn, session, interaction):
        selection, pokemon, edges, _ = await current(conn, session)
        edge_id = selection.get('edge_id')
        if edge_id not in {edge['edge_id'] for edge in edges}:
            raise _Refused(REOPEN)
        quote = await service.quote(conn, session['profile_id'], pokemon['pokemon_uid'], edge_id,
                                    walker.bot.content, walker.multipliers)
        if (quote is None or quote['item'] is None or quote['item_have']
                or quote['candy_have'] < quote['candy_cost']):
            raise _Refused('Your items changed. Preview again. Nothing was spent.')
        result = await items.buy_evolution_item(conn, session, quote['item'], walker.clock(), walker.bot.content)
        if 'status' in result:
            raise _Refused({'bag_full': 'Bag is full. Nothing was spent.',
                            'insufficient': 'Not enough Stardust. Nothing was spent.'}.get(result['status'], REOPEN))
        return await confirm(conn, session, interaction)

    return {'evolve': evolve, 'evolve_group': group, 'evolve_pick': pick, 'evolve_confirm': confirm,
            'evolve_buy_confirm': buy_confirm}
