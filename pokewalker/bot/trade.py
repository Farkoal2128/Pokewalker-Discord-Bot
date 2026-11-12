"""Private trade screens and their handlers on the shared Walker router (C5)."""

from datetime import datetime, timezone
from functools import partial
import json
import math

import discord

from pokewalker.bot.screens_catch import custom_id
from pokewalker.domain.cp import appraisal
from pokewalker.services import storage, trading

ENDED = "This trade ended. Use /trade member to start again."
REASONS = {"favorite": "it is a favorite", "companion": "it is a companion", "deployed": "it is defending a gym",
           "not_owned": "it is no longer in storage", "changed": "it changed after it was offered"}


def _offer_line(offer):
    if offer is None:
        return "nothing yet"
    pokemon, identity = offer["pokemon"], offer["identity"]
    stars = appraisal([pokemon[key] for key in ("iv_attack", "iv_defense", "iv_stamina")])
    return f"{identity['name_en']} · {identity['kind']} · CP {offer['cp']} · {stars} stars"


def _special(owner, offer):
    flags = offer["special"] if offer is not None else {}
    labels = [label for key, label in (("shiny", "Shiny"), ("legendary", "Legendary"), ("mythical", "Mythical"),
                                       ("starter", "starter")) if flags.get(key)]
    return f"{owner} {offer['identity']['name_en']} ({', '.join(labels)})" if labels else None


def _view(state, buttons):
    view = discord.ui.View(timeout=None)
    for label, action, disabled, row in buttons:
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), disabled=disabled, row=row))
    return view


def render_trade(state):
    mine, theirs = state["mine"], state["theirs"]
    lines = [f"Trade with <@{state['partner_user_id']}>"]
    if not state["partner_joined"]:
        lines.append("Waiting for them to join: they run /trade member:@you")
    lines += [f"You offer: {_offer_line(mine)}", f"They offer: {_offer_line(theirs)}"]
    special = [text for text in (_special("your", mine), _special("their", theirs)) if text]
    if special:
        lines.append(f"Special trade: {' · '.join(special)}. A trade can't be undone.")
    lines.append(f"You: {'confirmed' if state['my_confirmed'] else 'not confirmed'} · "
                 f"Them: {'confirmed' if state['partner_confirmed'] else 'not confirmed'}")
    expires = datetime.fromtimestamp(state["expires_at"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"Expires 15 min after the last join, offer or confirm (now {expires}).")
    if state.get("notice"):
        lines.append(state["notice"])
    embed = discord.Embed(title="Trade", description="\n".join(lines))
    if theirs is not None and theirs["sprite"]:
        embed.set_image(url=theirs["sprite"])
    ready = state["partner_joined"] and mine is not None and theirs is not None and not state["my_confirmed"]
    return {"embed": embed, "view": _view(state, (("Choose Pokémon", "trade_pick", False, 0),
                                                  ("Confirm", "trade_confirm", not ready, 0),
                                                  ("Refresh", "trade_refresh", False, 0),
                                                  ("Cancel trade", "trade_cancel", False, 0)))}


def render_picker(state):
    lines = [f"{state['eligible']} tradable of {state['owned']} owned · "
             "favorites, your companion and gym defenders can't be traded"]
    if state.get("notice"):
        lines.append(state["notice"])
    view = _view(state, (("Prev", "trade_prev", state["offset"] == 0, 1),
                         ("Next", "trade_next", state["offset"] + 10 >= state["eligible"], 1),
                         ("Back", "trade_refresh", False, 1)))
    if state["rows"]:
        view.add_item(discord.ui.Select(placeholder="Offer a Pokémon", custom_id=custom_id(state, "trade_offer"), row=0,
                                       options=[discord.SelectOption(
                                           label=f"#{number} {item['identity']['name_en']} · CP {item['cp']}"[:100],
                                           value=item["pokemon"]["pokemon_uid"])
                                           for number, item in enumerate(state["rows"][:10], state["offset"] + 1)]))
    return {"embed": discord.Embed(title="Choose a Pokémon to offer", description="\n".join(lines)), "view": view}


def render_result(state):
    if state["state"] != "completed":
        text = ENDED
    elif state.get("received"):
        received = state["received"]
        text = (f"You received {received['name']} (CP {received['cp']}). It counts for your Pokédex. "
                "Open /walker → Storage to see it.")
    else:
        text = "Trade complete. It counts for your Pokédex. Open /walker → Storage to see it."
    return {"embed": discord.Embed(title="Trade", description=text), "view": None}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, TRADE_REOPEN

    def selected(session, phase=None):
        selection = json.loads(session["selection"])
        if session["profile_id"] is None or not selection.get("trade_id"):
            raise _Refused(TRADE_REOPEN)
        if phase is not None and selection.get("phase") != phase:
            raise _Refused(TRADE_REOPEN)
        return selection

    def save(session, trade_id, revision, phase, offset=0):
        session["selection"] = json.dumps({"trade_id": trade_id, "trade_revision": revision,
                                           "phase": phase, "offset": offset})

    async def snapshot(conn, session, trade_id):
        state = await trading.view(conn, session, trade_id, walker.clock(), walker.bot.content, walker.multipliers)
        if state is None:
            raise _Refused(TRADE_REOPEN)
        return {**state, "session": session}

    async def show(conn, session, trade_id, notice=None):
        state = await snapshot(conn, session, trade_id)
        if state["state"] != "open":
            save(session, trade_id, state["revision"], "result")
            return render_result(state)
        save(session, trade_id, state["revision"], "trade")
        return render_trade({**state, "notice": notice})

    async def picker(conn, session, trade_id, offset):
        state = await snapshot(conn, session, trade_id)
        if state["state"] != "open":
            save(session, trade_id, state["revision"], "result")
            return render_result(state)
        rows, eligible, owned = await trading.eligible_page(conn, session["profile_id"], offset)
        if offset and not rows:
            offset = max(0, (eligible - 1) // 10 * 10)
            rows, eligible, owned = await trading.eligible_page(conn, session["profile_id"], offset)
        save(session, trade_id, state["revision"], "pick", offset)
        return render_picker({"session": session, "offset": offset, "eligible": eligible, "owned": owned,
                              "rows": [storage.stats(walker.bot.content, row, walker.multipliers) for row in rows]})

    async def trade_refresh(conn, session, interaction):
        return await show(conn, session, selected(session)["trade_id"])

    async def trade_pick(conn, session, interaction):
        return await picker(conn, session, selected(session)["trade_id"], 0)

    async def trade_page(conn, session, interaction, *, delta):
        selection = selected(session, "pick")
        return await picker(conn, session, selection["trade_id"], max(0, selection.get("offset", 0) + delta))

    async def ended(conn, session, trade_id, result, notices):
        if result["status"] in ("expired", "ended", "completed"):
            return await show(conn, session, trade_id)
        if result["status"] not in notices:
            raise _Refused(TRADE_REOPEN)
        return await show(conn, session, trade_id, notices[result["status"]])

    async def trade_offer(conn, session, interaction):
        selection = selected(session, "pick")
        rows, _, _ = await trading.eligible_page(conn, session["profile_id"], selection.get("offset", 0))
        values = interaction.data.get("values", [])
        if len(values) != 1 or values[0] not in {row["pokemon_uid"] for row in rows}:
            raise _Refused(TRADE_REOPEN)
        result = await trading.offer(conn, session, selection["trade_id"], values[0], walker.clock())
        return await ended(conn, session, selection["trade_id"], result, {
            "offered": None, "ineligible": f"That Pokémon can't be traded: {REASONS.get(result.get('reason'), result.get('reason'))}."})

    async def trade_confirm(conn, session, interaction):
        selection = selected(session)
        result = await trading.confirm(conn, session, selection["trade_id"], selection.get("trade_revision"),
                                       walker.clock(), walker.bot.content)
        minutes = math.ceil(result.get("seconds_left", 0) / 60)
        return await ended(conn, session, selection["trade_id"], result, {
            "waiting": "Confirmed. Waiting for them.",
            "changed": "The offer changed — review it and confirm again.",
            "capped": f"You can trade again in {minutes // 60}h {minutes % 60}m.",
            "partner_capped": "They can't trade again yet.",
            "partner_unavailable": "They can't trade right now.",
            "offer_invalid": f"That Pokémon can't be traded: {REASONS.get(result.get('reason'), result.get('reason'))}."})

    async def trade_cancel(conn, session, interaction):
        selection = selected(session)
        result = await trading.cancel(conn, session, selection["trade_id"], walker.clock())
        return await ended(conn, session, selection["trade_id"], result, {"cancelled": None})

    return {"trade_pick": trade_pick, "trade_offer": trade_offer, "trade_confirm": trade_confirm,
            "trade_refresh": trade_refresh, "trade_cancel": trade_cancel,
            "trade_prev": partial(trade_page, delta=-10), "trade_next": partial(trade_page, delta=10)}
