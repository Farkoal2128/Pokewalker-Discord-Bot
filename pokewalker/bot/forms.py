"""D71/D72/D73 (owner requests 2026-11-17): private Change form, Fuse, Unfuse and Change look screens."""

import json

import discord

from pokewalker.bot.screens_catch import custom_id
from pokewalker.services import forms as service, profiles, storage


FORM_TEXT = 'Pick a form. Gaining CP costs 10 Stardust per CP; the same or lower CP is free.'
FUSE_TEXT = ('Pick a partner from storage. It is held inside the fused Pokémon and comes back when you '
             'unfuse.')
NO_PARTNERS = 'No Pokémon in storage can fuse with it.'
LOOK_TEXT = 'Pick a look. Looks are free; catch or trade for a Pokémon wearing a look to unlock it.'
LOOK_ACTIONS = ('look_pick', 'look_pick_more')
DEFAULT_LOOK = 'default'


def types(identity):
    return ' / '.join(item.title() for item in identity['types'])


def price(cost):
    return 'Free' if not cost else f'{cost:,} Stardust'


def costs(cost):
    return 'free' if not cost else f'costs {cost:,} Stardust'


def render_menu(state):
    """state: session, title, text, stardust, action, options [(label, description, value)], preview, confirm."""
    text = f"{state['text']} Have {state['stardust']:,} Stardust."
    if not state['options']:
        text += '\n' + NO_PARTNERS
    if state.get('preview'):
        text += '\n\n' + state['preview']
    view = discord.ui.View(timeout=None)
    if state['options']:
        view.add_item(discord.ui.Select(
            placeholder=state['placeholder'], custom_id=custom_id(state, state['action']), row=0,
            options=[discord.SelectOption(label=label[:100], description=description[:100], value=value,
                                          default=value == state.get('picked'))
                     for label, description, value in state['options'][:25]]))
    if state.get('preview'):
        view.add_item(discord.ui.Button(label='Confirm', custom_id=custom_id(state, state['confirm']), row=1,
                                        disabled=not state['affordable']))
    view.add_item(discord.ui.Button(label='Back', custom_id=custom_id(state, 'storage_detail'), row=1))
    return {'embed': discord.Embed(title=state['title'], description=text), 'view': view}


def render_looks(state):
    """state: session, unlocked, total, options [(label, value)]; options split 25 per select."""
    text = f"{LOOK_TEXT} Unlocked {state['unlocked']} of {state['total']}."
    view = discord.ui.View(timeout=None)
    for row, action in enumerate(LOOK_ACTIONS):
        chunk = state['options'][row * 25:(row + 1) * 25]
        if chunk:
            view.add_item(discord.ui.Select(placeholder='Choose look', custom_id=custom_id(state, action), row=row,
                                            options=[discord.SelectOption(label=label[:100], value=value)
                                                     for label, value in chunk]))
    view.add_item(discord.ui.Button(label='Back', custom_id=custom_id(state, 'storage_detail'), row=2))
    return {'embed': discord.Embed(title='Change look', description=text), 'view': view}


def render_unfuse(state):
    quote = state['quote']
    text = f"{state['partner']} returns to storage. CP {quote['cp_before']} → {quote['cp_after']} · free"
    view = discord.ui.View(timeout=None)
    for label, action in (('Confirm', 'unfuse_confirm'), ('Back', 'storage_detail')):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action)))
    return {'embed': discord.Embed(title='Unfuse', description=text), 'view': view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    REFUSALS = {'insufficient': 'Not enough Stardust. Nothing was spent.',
                'deployed': 'Recall it from the gym first',
                'full': 'Storage is full. Make room before unfusing.'}

    async def current(conn, session):
        selection = json.loads(session['selection'])
        pokemon = await storage.detail(conn, session['profile_id'], selection.get('pokemon_uid'))
        if pokemon is None or pokemon['revision'] != selection.get('pokemon_revision'):
            raise _Refused(REOPEN)
        if pokemon['gym_deployment_id'] is not None:
            raise _Refused(REFUSALS['deployed'])
        return selection, pokemon, await service.fusion_of(conn, pokemon['pokemon_uid'])

    async def stardust(conn, session):
        return (await profiles.get_profile(conn, session['guild_id'], session['user_id']))['stardust']

    def name(pokemon):
        return storage.identify(walker.bot.content, pokemon)[0]['name_en']

    async def form_screen(conn, session, picked=None):
        selection, pokemon, fusion = await current(conn, session)
        targets = service.options(walker.bot.content, pokemon, fusion)
        if not targets:
            raise _Refused(REOPEN)
        quotes = {t['identity_id']: (t, service.quote(walker.bot.content, pokemon, t, walker.multipliers)) for t in targets}
        if picked is not None and picked not in quotes:
            raise _Refused(REOPEN)
        selection.pop('form_target', None)
        if picked is not None:
            selection['form_target'] = picked
        session['selection'] = json.dumps(selection)
        have = await stardust(conn, session)
        state = {'session': session, 'title': 'Change form', 'text': FORM_TEXT, 'stardust': have,
                 'placeholder': 'Choose form', 'action': 'form_pick', 'confirm': 'form_confirm', 'picked': picked,
                 'options': [(f"{t['name_en']} · CP {q['cp_after']}", f"{types(t)} · {price(q['cost'])}",
                              t['identity_id']) for t, q in quotes.values()]}
        if picked is not None:
            target, quote = quotes[picked]
            state.update(preview=f"{target['name_en']}: CP {quote['cp_before']} → {quote['cp_after']} · "
                                 f"{costs(quote['cost'])}", affordable=have >= quote['cost'])
        return render_menu(state)

    async def fuse_screen(conn, session, picked=None):
        selection, pokemon, fusion = await current(conn, session)
        if not service.can_fuse(walker.bot.content, pokemon, fusion):
            raise _Refused(REOPEN)
        sid = service.species_of(walker.bot.content, pokemon)
        rows = []
        for partner in await service.partners(conn, session['profile_id'], walker.bot.content, pokemon, walker.clock()):
            target = service._form(walker.bot.content, sid, service.FUSIONS[sid][service.species_of(walker.bot.content, partner)])
            partner_cp = storage.stats(walker.bot.content, partner, walker.multipliers)['cp']
            rows.append((partner_cp, partner, target, service.quote(walker.bot.content, pokemon, target, walker.multipliers)))
        rows.sort(key=lambda row: (-row[0], row[1]['pokemon_uid']))
        rows = rows[:25]
        chosen = next((row for row in rows if row[1]['pokemon_uid'] == picked), None)
        if picked is not None and chosen is None:
            raise _Refused(REOPEN)
        for key in ('fuse_partner', 'fuse_partner_revision'):
            selection.pop(key, None)
        if chosen is not None:
            selection.update(fuse_partner=picked, fuse_partner_revision=chosen[1]['revision'])
        session['selection'] = json.dumps(selection)
        have = await stardust(conn, session)
        state = {'session': session, 'title': 'Fuse', 'text': FUSE_TEXT, 'stardust': have,
                 'placeholder': 'Choose partner', 'action': 'fuse_pick', 'confirm': 'fuse_confirm', 'picked': picked,
                 'options': [(f"{name(partner)} · CP {partner_cp}",
                              f"→ {target['name_en']} · CP {quote['cp_after']} · {price(quote['cost'])}",
                              partner['pokemon_uid']) for partner_cp, partner, target, quote in rows]}
        if chosen is not None:
            _, partner, target, quote = chosen
            state.update(preview=f"Fuse with {name(partner)}: {target['name_en']} · CP {quote['cp_before']} → "
                                 f"{quote['cp_after']} · {costs(quote['cost'])}", affordable=have >= quote['cost'])
        return render_menu(state)

    def picked(interaction):
        values = interaction.data.get('values', [])
        if len(values) != 1:
            raise _Refused(REOPEN)
        return values[0]

    async def form_menu(conn, session, interaction):
        return await form_screen(conn, session)

    async def form_pick(conn, session, interaction):
        return await form_screen(conn, session, picked(interaction))

    async def fuse_menu(conn, session, interaction):
        return await fuse_screen(conn, session)

    async def fuse_pick(conn, session, interaction):
        return await fuse_screen(conn, session, picked(interaction))

    async def finish(conn, session, result):
        if result['status'] != 'used':
            raise _Refused(REFUSALS.get(result['status'], REOPEN))
        return await walker.handlers['storage_detail'](conn, session, interaction=None)

    async def form_confirm(conn, session, interaction):
        selection = json.loads(session['selection'])
        if 'form_target' not in selection:
            raise _Refused('Pick a form first.')
        return await finish(conn, session, await service.change(
            conn, session, selection.get('pokemon_uid'), selection.get('pokemon_revision'),
            selection['form_target'], walker.bot.content, walker.multipliers))

    async def fuse_confirm(conn, session, interaction):
        selection = json.loads(session['selection'])
        if 'fuse_partner' not in selection:
            raise _Refused('Pick a partner first.')
        return await finish(conn, session, await service.fuse(
            conn, session, selection.get('pokemon_uid'), selection.get('pokemon_revision'),
            selection['fuse_partner'], selection['fuse_partner_revision'], walker.bot.content, walker.multipliers,
            walker.clock()))

    async def unfuse_preview(conn, session, interaction):
        _, pokemon, fusion = await current(conn, session)
        if fusion is None:
            raise _Refused(REOPEN)
        target = service._default(walker.bot.content, service.species_of(walker.bot.content, pokemon))
        return render_unfuse({'session': session, 'partner': name(fusion['partner']),
                              'quote': service.quote(walker.bot.content, pokemon, target, walker.multipliers)})

    async def unfuse_confirm(conn, session, interaction):
        selection = json.loads(session['selection'])
        return await finish(conn, session, await service.unfuse(
            conn, session, selection.get('pokemon_uid'), selection.get('pokemon_revision'), walker.bot.content,
            walker.clock()))

    async def look_menu(conn, session, interaction):
        _, pokemon, _ = await current(conn, session)
        looks = service.looks_of(walker.bot.content, pokemon)
        if not looks:
            raise _Refused(REOPEN)
        have = await service.unlocked(conn, session['profile_id'])
        base = storage.identify(walker.bot.content, {**pokemon, 'look_id': None})[0]['name_en']
        options = [(base, DEFAULT_LOOK)] + [(item['name_en'], str(item['look_id']))
                                             for item in looks if item['look_id'] in have]
        current_value = str(pokemon['look_id']) if pokemon.get('look_id') else DEFAULT_LOOK
        return render_looks({'session': session, 'total': len(looks),
                             'unlocked': sum(item['look_id'] in have for item in looks),
                             'options': [option for option in options if option[1] != current_value]})

    async def look_pick(conn, session, interaction):
        value = picked(interaction)
        selection = json.loads(session['selection'])
        look_id = None if value == DEFAULT_LOOK else int(value) if value.isdigit() else -1
        return await finish(conn, session, await service.set_look(
            conn, session, selection.get('pokemon_uid'), selection.get('pokemon_revision'), look_id,
            walker.bot.content))

    return {'look_menu': look_menu, **dict.fromkeys(LOOK_ACTIONS, look_pick),
            'form_menu': form_menu, 'form_pick': form_pick, 'form_confirm': form_confirm,
            'fuse_menu': fuse_menu, 'fuse_pick': fuse_pick, 'fuse_confirm': fuse_confirm,
            'unfuse_preview': unfuse_preview, 'unfuse_confirm': unfuse_confirm}
