"""Owner amendment 2026-11-12: private Bottlecap and Vitamin previews from Pokemon details."""

from functools import partial
import json

import discord

from pokewalker.bot.screens_catch import custom_id
from pokewalker.services import iv_items as service, storage


NAMES = {'bottlecap': 'Bottlecap', 'vitamin': 'Vitamin'}


def render_preview(state):
    item, quote = state['item'], state['quote']
    name = NAMES[item]
    text = (f"CP {quote['cp_before']} → {quote['cp_after']} · Appraisal {quote['stars_before']} → "
            f"{quote['stars_after']} stars · uses 1 {name} (have {quote['have']})")
    view = discord.ui.View(timeout=None)
    for label, action in (('Confirm', f'iv_{item}_confirm'), ('Back', 'storage_detail')):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action)))
    return {'embed': discord.Embed(title=f'Use {name}', description=text), 'view': view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    def refusal(status, name):
        return {'perfect': f'Its IVs are already perfect. No {name} was used.',
                'missing': f'You have no {name}. Nothing was used.',
                'deployed': 'Recall it from the gym first'}.get(status, REOPEN)

    async def preview(conn, session, interaction, *, item):
        selection = json.loads(session['selection'])
        pokemon = await storage.detail(conn, session['profile_id'], selection.get('pokemon_uid'))
        if pokemon is None or pokemon['revision'] != selection.get('pokemon_revision'):
            raise _Refused(REOPEN)
        quote = await service.quote(conn, session['profile_id'], pokemon['pokemon_uid'], item,
                                    walker.bot.content, walker.multipliers)
        status = ('deployed' if quote['deployed'] else 'perfect' if quote['perfect'] else
                  'missing' if quote['have'] < 1 else None)
        if status is not None:
            raise _Refused(refusal(status, NAMES[item]))
        selection['iv_item'] = item
        session['selection'] = json.dumps(selection)
        return render_preview({'session': session, 'item': item, 'quote': quote})

    async def confirm(conn, session, interaction, *, item):
        selection = json.loads(session['selection'])
        if selection.get('iv_item') != item:
            raise _Refused(f'Preview the {NAMES[item]} before confirming.')
        result = await service.use(conn, session, selection.get('pokemon_uid'), selection.get('pokemon_revision'),
                                   item, walker.bot.content, walker.multipliers)
        if result['status'] != 'used':
            raise _Refused(refusal(result['status'], NAMES[item]))
        return await walker.handlers['storage_detail'](conn, session, interaction)

    return {action: handler for item in service.ITEMS for action, handler in
            ((f'iv_{item}', partial(preview, item=item)), (f'iv_{item}_confirm', partial(confirm, item=item)))}
