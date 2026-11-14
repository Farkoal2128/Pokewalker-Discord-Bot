"""Private species Pokédex handlers and detached-state renderers."""

from datetime import datetime, timezone
from functools import partial
import json

import discord

from pokewalker.bot.screens_catch import custom_id
from pokewalker.bot.milestones import _milestone_name
from pokewalker.services import items, pokedex as service
from pokewalker.services import milestones as milestone_service


def _date(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if timestamp is not None else "—"


def render_page(state):
    summary = state["summary"]
    lines = [f"Seen {summary['seen']} · Caught {summary['caught']} / {summary['total']}"]
    for item in state["rows"]:
        caught = item["caught_at"] is not None
        lines.append(f"#{item['species_id']:03} {item['name']} · {'caught' if caught else 'seen'} "
                     + _date(item["caught_at"] if caught else item["seen_at"]))
    view = discord.ui.View(timeout=None)
    for label, action, disabled in (("Prev", "pokedex_prev", state["offset"] == 0),
                                    ("Next", "pokedex_page", state["offset"] + 20 >= summary["seen"]),
                                    ("Back", "pokedex_back", False)):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), disabled=disabled, row=0))
    if state["rows"]:
        view.add_item(discord.ui.Select(placeholder="Open species", custom_id=custom_id(state, "pokedex_entry"), row=1,
                                       options=[discord.SelectOption(label=f"#{item['species_id']:03} {item['name']}",
                                                                     value=str(item["species_id"])) for item in state["rows"]]))
    view.add_item(discord.ui.Button(label="Milestones", custom_id=custom_id(state, "pokedex_milestones"), row=2))
    return {"embed": discord.Embed(title="Pokédex", description="\n".join(lines)), "view": view}


def render_milestones(state):
    rows, filter_name = state['rows'], state['filter']
    lines = []
    previous_category = None
    categories = {
        'pokedex': 'Pokédex', 'starter_trios': 'Starter trios', 'regions': 'Regions',
        'mythical_sets': 'Mythical sets', 'legendary_groups': 'Legendary groups',
        'extra_bundle_lines': 'Extra evolution lines', 'all_starters': 'Starter completion',
        'all_legendaries': 'Legendary completion', 'all_mythicals': 'Mythical completion',
        'first_legendary': 'First catches', 'first_mythical': 'First catches',
        'ultra_beast_first_catches': 'Ultra Beast first catches', 'evolution_lines': 'Evolution lines',
    }
    for row in rows:
        category = categories.get(row['category'], row['category'].replace('_', ' ').title())
        if category != previous_category:
            lines.append(f'**{category}**')
            previous_category = category
        tier = f" · {row['bundle'].title()}" if row['bundle'] else (
            ' · Evolution reward' if row['category'] == 'evolution_lines' else '')
        if row['milestone_id'] == items.SHINY_CHARM_MILESTONE:
            tier += ' + Shiny Charm'
        status = f"✅ completed · {_date(row['earned_at'])}" if row['earned'] else f"⬜ missing · {row['progress']}"
        lines.append(f"{_milestone_name(row['milestone_id'], state['content'])}{tier} · {status}")
    if not lines:
        lines = ['No milestones match this filter.']
    description = '\n'.join(lines)
    if len(description) > 4096:
        raise ValueError('Milestone page exceeds Discord embed limit')
    view = discord.ui.View(timeout=None)
    for label, action, disabled in (
            ('Prev', 'milestones_prev', state['offset'] == 0),
            ('Next', 'milestones_page', state['offset'] + len(rows) >= state['total']),
            ('Back', 'milestones_back', False)):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), disabled=disabled, row=0))
    for label, value in (('Completed', 'completed'), ('Missing', 'missing'), ('All', 'all')):
        view.add_item(discord.ui.Button(label=label,
                                       custom_id=custom_id(state, f'milestones_filter_{value}'),
                                       disabled=filter_name == value, row=1))
    return {'embed': discord.Embed(title='Pokédex milestones', description=description), 'view': view}


def render_entry(state):
    item = state["entry"]
    text = (f"Types: {' / '.join(kind.title() for kind in item['types'])}\nGeneration {item['generation_id']}"
            f"\nSeen: {_date(item['seen_at'])}\nCaught: {_date(item['caught_at'])}")
    embed = discord.Embed(title=f"#{item['species_id']:03} {item['name']}", description=text)
    if item["sprite"] is not None:
        embed.set_image(url=item["sprite"])
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Back", custom_id=custom_id(state, "pokedex_back")))
    return {"embed": embed, "view": view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    async def show_page(conn, session, offset):
        if session["profile_id"] is None:
            raise _Refused(REOPEN)
        summary = await service.summary(conn, session["profile_id"], walker.bot.content)
        offset = min(max(0, offset), max(0, (summary["seen"] - 1) // 20 * 20))
        rows = await service.page(conn, session["profile_id"], walker.bot.content, offset)
        session["selection"] = json.dumps({"offset": offset})
        return render_page({"session": session, "rows": rows, "summary": summary, "offset": offset})

    async def pokedex(conn, session, interaction):
        return await show_page(conn, session, 0)

    async def pokedex_page(conn, session, interaction, *, delta=20):
        return await show_page(conn, session, json.loads(session["selection"]).get("offset", 0) + delta)

    async def pokedex_entry(conn, session, interaction):
        selection = json.loads(session["selection"])
        rows = await service.page(conn, session["profile_id"], walker.bot.content, selection.get("offset", 0))
        values = interaction.data.get("values", [])
        if len(values) != 1 or values[0] not in {str(item["species_id"]) for item in rows}:
            raise _Refused(REOPEN)
        item = await service.entry(conn, session["profile_id"], int(values[0]), walker.bot.content)
        if item is None:
            raise _Refused(REOPEN)
        selection["species_id"] = item["species_id"]
        session["selection"] = json.dumps(selection)
        return render_entry({"session": session, "entry": item})

    async def pokedex_back(conn, session, interaction):
        selection = json.loads(session["selection"])
        if "species_id" in selection:
            return await show_page(conn, session, selection.get("offset", 0))
        session["selection"] = "{}"
        return await walker.home(conn, session, interaction)

    async def show_milestones(conn, session, offset=0, filter_name='all', pokedex_offset=0):
        if session['profile_id'] is None:
            raise _Refused(REOPEN)
        entries = await milestone_service.list_for_profile(conn, session['profile_id'], walker.bot.content)
        if filter_name == 'completed':
            entries = [row for row in entries if row['earned']]
        elif filter_name == 'missing':
            entries = [row for row in entries if not row['earned']]
        total = len(entries)
        offset = min(max(0, offset), max(0, (total - 1) // 10 * 10))
        session['selection'] = json.dumps({'milestone_offset': offset, 'milestone_filter': filter_name,
                                           'pokedex_offset': pokedex_offset})
        return render_milestones({'session': session, 'rows': entries[offset:offset + 10], 'total': total,
                                  'offset': offset, 'filter': filter_name, 'content': walker.bot.content})

    async def pokedex_milestones(conn, session, interaction):
        pokedex_offset = json.loads(session['selection']).get('offset', 0)
        return await show_milestones(conn, session, 0, 'all', pokedex_offset)

    async def milestones_page(conn, session, interaction, *, delta=10):
        selection = json.loads(session['selection'])
        return await show_milestones(conn, session, selection.get('milestone_offset', 0) + delta,
                                     selection.get('milestone_filter', 'all'), selection.get('pokedex_offset', 0))

    async def milestones_filter(conn, session, interaction, *, filter_name):
        selection = json.loads(session['selection'])
        return await show_milestones(conn, session, 0, filter_name, selection.get('pokedex_offset', 0))

    async def milestones_back(conn, session, interaction):
        selection = json.loads(session['selection'])
        return await show_page(conn, session, selection.get('pokedex_offset', 0))

    return {"pokedex": pokedex, "pokedex_page": pokedex_page, "pokedex_entry": pokedex_entry,
            "pokedex_back": pokedex_back, "pokedex_prev": partial(pokedex_page, delta=-20),
            'pokedex_milestones': pokedex_milestones, 'milestones_page': milestones_page,
            'milestones_prev': partial(milestones_page, delta=-10), 'milestones_back': milestones_back,
            **{f'milestones_filter_{value}': partial(milestones_filter, filter_name=value)
               for value in ('completed', 'missing', 'all')}}
