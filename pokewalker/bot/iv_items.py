"""Owner amendment 2026-11-12: private Bottlecap and Vitamin previews from Pokemon details.

D70: the preview shows IV meters and lets the player pick the IV."""

from functools import partial
import json

import discord

from pokewalker.bot.screens_catch import custom_id
from pokewalker.services import iv_items as service, storage


NAMES = {'bottlecap': 'Bottlecap', 'vitamin': 'Vitamin'}
STATS = {'iv_attack': 'Attack', 'iv_defense': 'Defense', 'iv_stamina': 'Stamina'}


def meter(value):
    """D70: 15 squares, the filled ones all one colour chosen by the IV."""
    square = '🟥' if value <= 5 else '🟨' if value <= 10 else '🟩'
    return square * value + '⬛' * (service.MAX_IV - value)


def render_preview(state):
    item, quote, stat = state['item'], state['quote'], state['stat']
    name = NAMES[item]
    meters = '\n'.join(f'**{label}**\n{meter(value)}' for label, value in zip(STATS.values(), state['ivs']))
    text = (f"{meters}\n\n{STATS[stat]} · CP {quote['cp_before']} → {quote['cp_after']} · Appraisal "
            f"{quote['stars_before']} → {quote['stars_after']} stars · uses 1 {name} (have {quote['have']})")
    view = discord.ui.View(timeout=None)
    for (key, label), value in zip(STATS.items(), state['ivs']):
        view.add_item(discord.ui.Button(
            label=label, custom_id=custom_id(state, f'iv_stat_{label.lower()}'), row=0,
            disabled=value == service.MAX_IV,
            style=discord.ButtonStyle.primary if key == stat else discord.ButtonStyle.secondary))
    for label, action in (('Confirm', f'iv_{item}_confirm'), ('Back', 'storage_detail')):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), row=1))
    return {'embed': discord.Embed(title=f'Use {name}', description=text), 'view': view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    def refusal(status, name):
        return {'perfect': f'Its IVs are already perfect. No {name} was used.',
                'missing': f'You have no {name}. Nothing was used.',
                'maxed': f'That IV is already maxed. No {name} was used.',
                'deployed': 'Recall it from the gym first'}.get(status, REOPEN)

    async def show(conn, session, item, stat):
        selection = json.loads(session['selection'])
        pokemon = await storage.detail(conn, session['profile_id'], selection.get('pokemon_uid'))
        if pokemon is None or pokemon['revision'] != selection.get('pokemon_revision'):
            raise _Refused(REOPEN)
        ivs = tuple(pokemon[key] for key in service.IVS)
        stat = stat or service.IVS[service.lowest(ivs)]
        if pokemon[stat] == service.MAX_IV and not service.perfect(pokemon):
            raise _Refused(REOPEN)
        quote = await service.quote(conn, session['profile_id'], pokemon['pokemon_uid'], item,
                                    walker.bot.content, walker.multipliers, stat=stat)
        status = ('deployed' if quote['deployed'] else 'perfect' if quote['perfect'] else
                  'missing' if quote['have'] < 1 else None)
        if status is not None:
            raise _Refused(refusal(status, NAMES[item]))
        selection.update(iv_item=item, iv_stat=stat)
        session['selection'] = json.dumps(selection)
        return render_preview({'session': session, 'item': item, 'quote': quote, 'stat': stat, 'ivs': ivs})

    async def preview(conn, session, interaction, *, item):
        return await show(conn, session, item, None)

    async def pick(conn, session, interaction, *, stat):
        item = json.loads(session['selection']).get('iv_item')
        if item not in service.ITEMS:
            raise _Refused(REOPEN)
        return await show(conn, session, item, stat)

    async def confirm(conn, session, interaction, *, item):
        selection = json.loads(session['selection'])
        if selection.get('iv_item') != item:
            raise _Refused(f'Preview the {NAMES[item]} before confirming.')
        result = await service.use(conn, session, selection.get('pokemon_uid'), selection.get('pokemon_revision'),
                                   item, walker.bot.content, walker.multipliers, stat=selection.get('iv_stat'))
        if result['status'] != 'used':
            raise _Refused(refusal(result['status'], NAMES[item]))
        return await walker.handlers['storage_detail'](conn, session, interaction)

    return {**{action: handler for item in service.ITEMS for action, handler in
               ((f'iv_{item}', partial(preview, item=item)), (f'iv_{item}_confirm', partial(confirm, item=item)))},
            **{f'iv_stat_{label.lower()}': partial(pick, stat=key) for key, label in STATS.items()}}
