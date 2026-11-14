"""The /trade command and private trade screens with their handlers on the shared Walker router (C5)."""

from datetime import datetime, timezone
from functools import partial
import json
import math

import aiohttp
import discord
from discord import app_commands

from pokewalker.bot.screens_catch import custom_id
from pokewalker.domain.cp import appraisal
from pokewalker.services import profiles, storage, trading
from pokewalker.services.deletion import opted_out

ENDED = "This trade ended. Use /trade member to start again."
REASONS = {"favorite": "it is a favorite", "companion": "it is a companion", "deployed": "it is defending a gym",
           "not_owned": "it is no longer in storage", "changed": "it changed after it was offered",
           "in_arena": "it is on an Arena team"}


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
        return render_trade({**state, "notice": notice(state) if callable(notice) else notice})

    async def picker(conn, session, trade_id, offset):
        state = await snapshot(conn, session, trade_id)
        if state["state"] != "open":
            save(session, trade_id, state["revision"], "result")
            return render_result(state)
        rows, eligible, owned = await trading.eligible_page(conn, session["profile_id"], offset, walker.clock())
        if offset and not rows:
            offset = max(0, (eligible - 1) // 10 * 10)
            rows, eligible, owned = await trading.eligible_page(conn, session["profile_id"], offset, walker.clock())
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
        rows, _, _ = await trading.eligible_page(conn, session["profile_id"], selection.get("offset", 0), walker.clock())
        values = interaction.data.get("values", [])
        if len(values) != 1 or values[0] not in {row["pokemon_uid"] for row in rows}:
            raise _Refused(TRADE_REOPEN)
        result = await trading.offer(conn, session, selection["trade_id"], values[0], walker.clock())
        return await ended(conn, session, selection["trade_id"], result, {
            "offered": None, "ineligible": f"That Pokémon can't be traded: {REASONS.get(result.get('reason'), result.get('reason'))}."})

    async def trade_confirm(conn, session, interaction):
        selection = selected(session, "trade")
        result = await trading.confirm(conn, session, selection["trade_id"], selection.get("trade_revision"),
                                       walker.clock(), walker.bot.content)
        return await ended(conn, session, selection["trade_id"], result, {
            "waiting": "Confirmed. Waiting for them.",
            "changed": "The offer changed — review it and confirm again.",
            "capped": _capped(result.get("seconds_left", 0)),
            "partner_capped": "They can't trade again yet.",
            "partner_unavailable": "They can't trade right now.",
            "offer_invalid": lambda state: f"{'Your' if result.get('side') == state['my_side'] else 'Their'} Pokémon "
                                           f"can't be traded: {REASONS.get(result.get('reason'), result.get('reason'))}."})

    async def trade_cancel(conn, session, interaction):
        selection = selected(session)
        result = await trading.cancel(conn, session, selection["trade_id"], walker.clock())
        return await ended(conn, session, selection["trade_id"], result, {"cancelled": None})

    return {"trade_pick": trade_pick, "trade_offer": trade_offer, "trade_confirm": trade_confirm,
            "trade_refresh": trade_refresh, "trade_cancel": trade_cancel,
            "trade_prev": partial(trade_page, delta=-10), "trade_next": partial(trade_page, delta=10)}


def _capped(seconds):
    minutes = math.ceil(seconds / 60)
    return f"You can trade again in {minutes // 60}h {minutes % 60}m."


def command(bot):
    from pokewalker.bot.walker import EXCLUDED, RESTARTING, _forget, new_session

    @app_commands.command(name="trade", description="Trade a Pokémon with a member of this server")
    @app_commands.guild_only()
    async def trade(interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer(ephemeral=True)
        if interaction.guild_id is None:
            await interaction.edit_original_response(content="Use /trade in a server.")
            return
        if getattr(bot, "_stopping", False):  # the drain closes the writer before the gateway
            await interaction.edit_original_response(content=RESTARTING)
            return
        channel = interaction.channel
        permissions = channel.permissions_for(interaction.guild.me) if channel is not None else None
        can_ping = bool(permissions is not None and permissions.send_messages)

        async def open_trade(conn):
            guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
            async with conn.execute("SELECT 1 FROM trade_channels WHERE guild_id=? AND channel_id=?",
                                    (guild_id, str(interaction.channel_id))) as cursor:
                if await cursor.fetchone() is None:
                    return {"content": "Trading isn't enabled in this channel. "
                                       "A moderator can enable it with /walker-admin trade-channels add."}
            if await opted_out(conn, guild_id, user_id):
                return {"content": "Run /walker-account opt-in first"}
            profile = await profiles.get_profile(conn, guild_id, user_id)
            if profile is None:
                return {"content": "Open /walker to enroll before trading."}
            if (await profiles.restrictions(conn, guild_id, user_id)).excluded:
                return {"content": EXCLUDED}
            if member is not None and member.bot:
                return {"content": "You can't trade with a bot."}
            now = bot.walker.clock()
            session = await new_session(conn, guild_id, user_id, profile["profile_id"], now)
            if member is None:
                current = await trading.current(conn, session, now)
                result = {"status": "reopened", "trade_id": current["trade_id"]} if current else {"status": "none"}
            else:
                result = await trading.open_or_join(conn, session, str(member.id), now, can_ping)
            if "trade_id" not in result:
                await conn.execute("DELETE FROM sessions WHERE session_id=?", (session["session_id"],))
                return {"content": {
                    "none": "Use /trade member:@someone to start or join a trade.",
                    "self": "You can't trade with yourself.",
                    "partner_not_enrolled": "They haven't started walking in this server.",
                    "partner_unavailable": "They can't trade right now.",
                    "busy": f"You're already in a trade with <@{result.get('partner_user_id')}>; "
                            "finish or cancel it first.",
                    "partner_busy": "They're in another trade right now.",
                    "capped": _capped(result.get("seconds_left", 0)),
                    "partner_capped": "They can't trade again yet.",
                    "excluded": EXCLUDED}.get(result["status"], "Use /trade member:@someone to start or join a trade.")}
            state = await trading.view(conn, session, result["trade_id"], now, bot.content, bot.walker.multipliers)
            session["selection"] = json.dumps({"trade_id": result["trade_id"], "trade_revision": state["revision"],
                                               "phase": "trade"})
            await conn.execute("UPDATE sessions SET selection=? WHERE session_id=?",
                               (session["selection"], session["session_id"]))
            return {"state": {**state, "session": session}, "ping": result.get("ping"),
                    "partner": state["partner_user_id"]}

        outcome = await bot.writer.run(open_trade)
        if "state" not in outcome:
            await interaction.edit_original_response(content=outcome["content"],
                                                     allowed_mentions=discord.AllowedMentions.none())
            return
        notice = {"rate_limited": "Opened without a ping (one per 10 minutes). Ask them to run /trade.",
                  "no_permission": "Couldn't ping them; ask them to run /trade."}.get(outcome["ping"])
        if outcome["ping"] == "reserved":
            partner = int(outcome["partner"])
            try:
                await channel.send(f"<@{partner}>, <@{interaction.user.id}> wants to trade a Pokémon with you. "
                                   "Run /trade and choose them to join.",
                                   allowed_mentions=discord.AllowedMentions(
                                       everyone=False, roles=False, users=[discord.Object(id=partner)]))
            except (discord.HTTPException, discord.RateLimited, aiohttp.ClientError, OSError):
                notice = "Couldn't ping them; ask them to run /trade."
            else:
                notice = "Pinged them here."
        rendered = render_trade({**outcome["state"], "notice": notice})
        await interaction.edit_original_response(**rendered, allowed_mentions=discord.AllowedMentions.none())
        _forget(rendered)

    return trade
