"""M2.1 transaction handlers and pure private storage screens."""

from datetime import datetime, timezone
from functools import partial
import json

import discord

from pokewalker.bot.screens_catch import custom_id
from pokewalker.bot import share
from pokewalker.domain.cp import appraisal
from pokewalker.services import storage as service
from pokewalker.services import profiles, research, capacity, evolution


def render_page(state):
    favorite_only = state.get("favorite_only", False)
    lines = [f"{state['total']} favorite{'s' if state['total'] != 1 else ''}"
             if favorite_only else f"{state['total']}/{state['limit']} Pokémon"]
    if favorite_only and not state["rows"]:
        lines.append("No favorites yet")
    if state.get("notice"):
        lines.append(state["notice"])
    for number, item in enumerate(state["rows"], state["offset"] + 1):
        pokemon = item["pokemon"]
        lines.append(f"#{number} {item['identity']['name_en']} · CP {item['cp']}"
                     + (" · shiny" if pokemon["shiny"] else "") + (" · fav" if pokemon["favorite"] else ""))
    view = discord.ui.View(timeout=None)
    for label, action, disabled in (("Prev", "storage_prev", state["offset"] == 0),
                                    ("Next", "storage_page", state["offset"] + 10 >= state["total"]),
                                    ("Back", "storage_back", False)):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), disabled=disabled, row=0))
    view.add_item(discord.ui.Button(label="Show all" if favorite_only else "Favorites only",
                                   custom_id=custom_id(state, "storage_filter"), row=2))
    if state["rows"]:
        view.add_item(discord.ui.Select(placeholder="Open Pokémon", custom_id=custom_id(state, "storage_open"), row=1,
                                       options=[discord.SelectOption(label=f"#{number} {item['identity']['name_en']}",
                                                                     value=item["pokemon"]["pokemon_uid"])
                                                for number, item in enumerate(state["rows"], state["offset"] + 1)]))
    view.add_item(discord.ui.Button(label="Send for research", custom_id=custom_id(state, "research"), row=2))
    if state.get("can_expand"):
        view.add_item(discord.ui.Button(label="Expand storage", custom_id=custom_id(state, "expand_storage_preview"), row=2))
    return {"embed": discord.Embed(title="Storage", description="\n".join(lines)), "view": view}


def render_detail(state):
    pokemon, identity = state["pokemon"], state["identity"]
    gender = {"female": "♀", "male": "♂", "genderless": "Genderless"}[pokemon["gender"]]
    caught = datetime.fromtimestamp(pokemon["caught_at"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stars = appraisal([pokemon[key] for key in ("iv_attack", "iv_defense", "iv_stamina")])
    text = (f"{identity['name_en']} · {identity['kind']} · {gender}" + (" · Shiny" if pokemon["shiny"] else "")
            + (" · Companion" if state.get("companion") else "")
            + f"\nCP {state['cp']} · HP {state['hp']} · Appraisal: {stars} stars"
            + f"\nTypes: {' / '.join(str(item).title() for item in identity['types'])}"
            + f"\nCaught: {caught}\nFavorite: {'Yes' if pokemon['favorite'] else 'No'}")
    if state.get("protection") == "deployed":
        text += (f"\nDeployed at {state.get('gym_name', 'a gym')} — recall it to send, power up, evolve or set companion")
    embed = discord.Embed(title="Pokémon details", description=text)
    if state["sprite"] is not None:
        embed.set_image(url=state["sprite"])
    view = discord.ui.View(timeout=None)
    for label, action in (("Unfavorite" if pokemon["favorite"] else "Favorite", "storage_favorite"),
                          ("Back", "storage_back")):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), row=0))
    for label, action in (("Send for research", "storage_send"), ("Power up", "power_up"),
                          ("Set companion", "companion"), ("Share", "share"), ("Evolve", "evolve")):
        if action == 'share' and not state.get('share_allowed'):
            continue
        if action == "evolve" and not state.get("can_evolve"):
            continue
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action),
                                       disabled=(state.get("protection") == "deployed"
                                                 and action in ("storage_send", "power_up", "evolve", "companion"))
                                       or (action == "storage_send"
                                                 and state.get("protection", "favorite") in ("favorite", "companion")), row=1))
    return {"embed": embed, "view": view}


def render_expand(state):
    quote = state["quote"]
    text = f"{quote['price']:,} Stardust → {quote['next']:,} slots · have {state['stardust']:,} Stardust"
    if quote["at_cap"]:
        text += "\nStorage is at the maximum capacity."
    if state.get("notice"):
        text += "\n" + state["notice"]
    view = discord.ui.View(timeout=None)
    for label, action, disabled in (("Confirm", "expand_storage_confirm", quote["at_cap"] or not quote["affordable"]),
                                    ("Back", "storage", False)):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), disabled=disabled))
    return {"embed": discord.Embed(title="Expand storage", description=text), "view": view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    def item_state(pokemon):
        return service.stats(walker.bot.content, pokemon, walker.multipliers)

    async def show_page(conn, session, offset, favorite_only=None, notice=None):
        if session["profile_id"] is None:
            raise _Refused(REOPEN)
        selection = json.loads(session["selection"])
        if favorite_only is None:
            favorite_only = selection.get("favorite_only", False)
        rows, total = await service.page(conn, session["profile_id"], offset, favorite_only)
        if offset and not rows:
            offset = max(0, (total - 1) // 10 * 10)
            rows, total = await service.page(conn, session["profile_id"], offset, favorite_only)
        selection = {"offset": offset}
        if favorite_only:
            selection["favorite_only"] = True
        session["selection"] = json.dumps(selection)
        return render_page({"session": session, "rows": [item_state(row) for row in rows],
                            "total": total, "offset": offset, "favorite_only": favorite_only,
                            "limit": (await capacity.limits_for(conn, session["profile_id"]))["storage"],
                            "can_expand": True, "notice": notice})

    async def expand_storage_preview(conn, session, interaction, *, notice=None):
        if session["profile_id"] is None:
            raise _Refused(REOPEN)
        quote = await capacity.quote(conn, session["profile_id"], "storage")
        profile = await profiles.get_profile(conn, session["guild_id"], session["user_id"])
        selection = json.loads(session["selection"])
        selection.update(phase="expand_storage", storage_limit=quote["current"])
        session["selection"] = json.dumps(selection)
        return render_expand({"session": session, "quote": quote, "stardust": profile["stardust"],
                              "notice": notice})

    async def expand_storage_confirm(conn, session, interaction):
        selection = json.loads(session["selection"])
        if selection.get("phase") != "expand_storage":
            return await expand_storage_preview(conn, session, interaction,
                                                notice="Preview storage expansion before confirming. Nothing was spent.")
        result = await capacity.expand(conn, session, "storage", selection.get("storage_limit"), walker.clock())
        if "status" in result:
            notice = {"stale": "Storage changed. Preview again. Nothing was spent.",
                      "at_cap": "Storage is at the maximum capacity. Nothing was spent.",
                      "insufficient": "Not enough Stardust. Nothing was spent."}.get(result["status"])
            if notice is None:
                raise _Refused(REOPEN)
            return await expand_storage_preview(conn, session, interaction, notice=notice)
        notice = f"Storage expanded to {result['storage']:,} slots."
        return await show_page(conn, session, selection.get("offset", 0), notice=notice)

    async def storage(conn, session, interaction):
        return await show_page(conn, session, 0)

    async def storage_page(conn, session, interaction, *, delta=10):
        offset = json.loads(session["selection"]).get("offset", 0)
        return await show_page(conn, session, max(0, offset + delta))

    async def storage_filter(conn, session, interaction):
        selection = json.loads(session["selection"])
        return await show_page(conn, session, 0, not selection.get("favorite_only", False))

    async def show_detail(conn, session, pokemon):
        selection = json.loads(session["selection"])
        selection.update(pokemon_uid=pokemon["pokemon_uid"], pokemon_revision=pokemon["revision"])
        session["selection"] = json.dumps(selection)
        item = item_state(pokemon)
        profile = await profiles.get_profile(conn, session["guild_id"], session["user_id"])
        gym_name = "a gym"
        if pokemon.get("gym_deployment_id") is not None:
            async with conn.execute(
                    "SELECT gyms.name FROM gym_deployments JOIN gyms USING (gym_id,guild_id) "
                    "WHERE deployment_id=? AND gym_deployments.guild_id=? AND profile_id=?",
                    (pokemon["gym_deployment_id"], session["guild_id"], session["profile_id"])) as cursor:
                gym = await cursor.fetchone()
                if gym is not None:
                    gym_name = gym["name"]
        return render_detail({"session": session, **item,
                              "gym_name": gym_name,
                              "can_evolve": bool(evolution.options(walker.bot.content, pokemon)),
                              "share_allowed": await share.allowed(conn, session, pokemon),
                              "companion": profile["companion_uid"] == pokemon["pokemon_uid"],
                              "protection": research.protected_reason(item["identity"], pokemon, profile)})

    async def storage_open(conn, session, interaction):
        selection = json.loads(session["selection"])
        rows, _ = await service.page(conn, session["profile_id"], selection.get("offset", 0),
                                     selection.get("favorite_only", False))
        values = interaction.data.get("values", [])
        if len(values) != 1 or values[0] not in {row["pokemon_uid"] for row in rows}:
            raise _Refused(REOPEN)
        pokemon = await service.detail(conn, session["profile_id"], values[0])
        if pokemon is None:
            raise _Refused(REOPEN)
        return await show_detail(conn, session, pokemon)

    async def storage_detail(conn, session, interaction):
        pokemon = await service.detail(conn, session["profile_id"], json.loads(session["selection"]).get("pokemon_uid"))
        if pokemon is None:
            raise _Refused(REOPEN)
        return await show_detail(conn, session, pokemon)

    async def storage_favorite(conn, session, interaction):
        selection = json.loads(session["selection"])
        pokemon = await service.detail(conn, session["profile_id"], selection.get("pokemon_uid"))
        if pokemon is None:
            raise _Refused(REOPEN)
        pokemon = await service.set_favorite(conn, session["profile_id"], pokemon["pokemon_uid"],
                                             not pokemon["favorite"], selection.get("pokemon_revision"))
        if pokemon is None:
            raise _Refused(REOPEN)
        return await show_detail(conn, session, pokemon)

    async def set_companion(conn, session, interaction):
        selection = json.loads(session["selection"])
        pokemon = await service.detail(conn, session["profile_id"], selection.get("pokemon_uid"))
        if pokemon is None or pokemon["revision"] != selection.get("pokemon_revision"):
            raise _Refused(REOPEN)
        if pokemon.get("gym_deployment_id") is not None:
            raise _Refused("Recall it from the gym first")
        await conn.execute("UPDATE profiles SET companion_uid=? WHERE profile_id=?",
                           (pokemon["pokemon_uid"], session["profile_id"]))
        return await show_detail(conn, session, pokemon)

    async def storage_back(conn, session, interaction):
        selection = json.loads(session["selection"])
        if "pokemon_uid" in selection:
            return await show_page(conn, session, selection.get("offset", 0))
        session["selection"] = "{}"
        return await walker.home(conn, session, interaction)

    return {"storage": storage, "storage_page": storage_page, "storage_filter": storage_filter,
            "expand_storage_preview": expand_storage_preview, "expand_storage_confirm": expand_storage_confirm,
            "storage_open": storage_open,
            "storage_favorite": storage_favorite, "storage_back": storage_back, "storage_detail": storage_detail,
            "storage_prev": partial(storage_page, delta=-10), "companion": set_companion}
