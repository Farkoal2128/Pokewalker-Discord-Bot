"""Private research selection, warnings and durable review confirmation."""

from collections import Counter
from functools import partial
import json
from uuid import uuid4

import discord

from pokewalker.bot.screens_catch import custom_id
from pokewalker.bot.milestones import _reward_name
from pokewalker.domain.cp import appraisal
from pokewalker.services import profiles, research as service, storage


def _candy_text(candy, content):
    return ', '.join(f"+{candy[family]} {_reward_name({'resource': 'candy', 'resource_id': family}, content)}"
                     for family in sorted(candy, key=int))


async def _pick(conn, session, uid):
    if isinstance(uid, str) and uid.startswith("pending:"):
        async with conn.execute("SELECT * FROM encounters WHERE encounter_id=? AND profile_id=? AND state='caught' "
                                "AND acknowledged_at IS NULL AND NOT EXISTS "
                                "(SELECT 1 FROM pokemon WHERE source_encounter_id=encounters.encounter_id)",
                                (uid[8:], session["profile_id"])) as cursor:
            encounter = await cursor.fetchone()
        if encounter is None:
            return None
        return {**encounter, "pokemon_uid": uid, "favorite": 0, "gym_deployment_id": None,
                "state": "pending", "caught_at": encounter["resolved_at"]}
    return await storage.detail(conn, session["profile_id"], uid)


def screen(session, text, buttons, *, sprite=None):
    embed = discord.Embed(title="Send for research", description=text)
    if sprite:
        embed.set_image(url=sprite)
    view = discord.ui.View(timeout=None)
    for label, action, disabled, row in buttons:
        view.add_item(discord.ui.Button(label=label[:80], custom_id=custom_id({"session": session}, action),
                                       disabled=disabled, row=row))
    return {"embed": embed, "view": view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    def save(session, selection):
        session["selection"] = json.dumps(selection)

    def notice(session, text):
        return screen(session, text, [("New review", "research", False, 0), ("Cancel", "research_cancel", False, 0)])

    async def page(conn, session, interaction, *, delta=0, reset=False, toggle=None):
        if session["profile_id"] is None:
            raise _Refused(REOPEN)
        previous = json.loads(session["selection"])
        selection = {"picks": [], "offset": 0} if reset else previous
        offset = max(0, selection.get("offset", 0) + delta)
        rows, total = await service.candidates(conn, session["profile_id"], walker.bot.content, offset, walker.clock())
        picks = dict(selection.get("picks", []))
        if toggle is not None:
            binding = selection.get("toggles", {}).get(toggle)
            if binding is None:
                raise _Refused(REOPEN)
            uid, revision = binding
            pokemon = await storage.detail(conn, session["profile_id"], uid)
            if pokemon is None or pokemon["revision"] != revision:
                raise _Refused(REOPEN)
            identity, _ = storage.identify(walker.bot.content, pokemon)
            profile = await profiles.get_profile(conn, session["guild_id"], session["user_id"])
            arena_team = await profiles.arena_team(conn, session["profile_id"], walker.clock())
            if service.protected_reason(identity, pokemon, profile, arena_team) is not None:
                raise _Refused(REOPEN)
            if uid in picks:
                del picks[uid]
            elif len(picks) < 20:
                picks[uid] = revision
        save(session, {"offset": offset, "picks": list(picks.items()),
                       "toggles": {letter: [item["pokemon"]["pokemon_uid"], item["pokemon"]["revision"]]
                                   for letter, item in zip("abcde", rows)}})
        text, buttons = [f"5 per page · {len(picks)}/20 selected · {total} owned"], []
        for letter, item in zip("abcde", rows):
            pokemon, identity = item["pokemon"], item["identity"]
            selected = pokemon["pokemon_uid"] in picks
            reason = {"in_arena": "on your Arena team", "deployed": "deployed at a gym"}.get(
                item["reason"], item["reason"] or "available")
            text.append(f"{identity['name_en']} · {pokemon['pokemon_uid']} · {reason}")
            buttons.append((f"{'✓ ' if selected else ''}{identity['name_en']}", "research_toggle_" + letter,
                            item["reason"] is not None or len(picks) >= 20 and not selected, 0))
        buttons += [("Prev", "research_prev", offset == 0, 1), ("Next", "research_page", offset + 5 >= total, 1),
                    ("Review", "research_review", not picks, 1), ("Cancel", "research_cancel", False, 1)]
        return screen(session, "\n".join(text), buttons)

    async def catch_send(conn, session, interaction):
        selection = json.loads(session["selection"])
        state = await walker.encounter_state(conn, session, selection.get("encounter_id"))
        pokemon = state.get("pokemon") or {}
        if state["encounter"]["state"] != "caught" or not (state["pending"] or pokemon.get("state") == "owned"):
            raise _Refused(REOPEN)
        if state["pending"]:
            encounter = state["encounter"]
            save(session, {"pokemon_uid": "pending:" + encounter["encounter_id"],
                           "pokemon_revision": encounter["revision"],
                           "caught": {"encounter_id": encounter["encounter_id"], "pending": True}})
            return await single(conn, session, interaction)
        save(session, {"pokemon_uid": pokemon["pokemon_uid"], "pokemon_revision": pokemon["revision"],
                       "caught": {"encounter_id": state["encounter"]["encounter_id"]}})
        return await single(conn, session, interaction)

    async def review(conn, session, interaction, *, unlock=False):
        selection = json.loads(session["selection"])
        picks, text, families, sprite = [], [], Counter(), None
        profile = await profiles.get_profile(conn, session["guild_id"], session["user_id"])
        arena_team = await profiles.arena_team(conn, session["profile_id"], walker.clock())
        for uid, revision in selection.get("picks", []):
            pokemon = await _pick(conn, session, uid)
            if pokemon is None or pokemon["revision"] != revision:
                return notice(session, "Selection changed; start a new review.")
            info = storage.stats(walker.bot.content, pokemon, walker.multipliers)
            identity, sprite = info["identity"], info["sprite"]
            reason = service.protected_reason(identity, pokemon, profile, arena_team)
            if reason and not (selection.get("single") and unlock and reason in ("shiny", "legendary_or_mythical")):
                return notice(session, "Protected Pokémon; start a new review.")
            picks.append((uid, pokemon["revision"]))
            families[identity["family_id"]] += 1
            ivs = [pokemon[k] for k in ("iv_attack", "iv_defense", "iv_stamina")]
            text.append(f"{identity['name_en']} · {identity['kind']} · {uid} · "
                        f"CP {info['cp']} · {appraisal(ivs)} stars"
                        + (" · Shiny" if pokemon["shiny"] else "")
                        + (" · Legendary/Mythical" if identity["is_legendary"] or identity["is_mythical"] else ""))
        if not 1 <= len(picks) <= 20:
            return notice(session, "Select 1–20 Pokémon for a new review.")
        selection.update(picks=picks, preview={"id": str(uuid4()), "expires_at": walker.clock() + 120, "unlocked": unlock})
        save(session, selection)
        text += [f"{len(picks)} Pokémon · irreversible · expires in 120 seconds",
                 "Candy by family: " + _candy_text(families, walker.bot.content), "0 Stardust"]
        return screen(session, "\n".join(text), [(f"Send {len(picks)} Pokémon",
                      "storage_send_confirm" if selection.get("single") else "research_confirm", False, 0),
                      ("Cancel", "research_cancel", False, 0)], sprite=sprite if len(picks) == 1 else None)

    async def single(conn, session, interaction):
        selection = json.loads(session["selection"])
        pokemon = await _pick(conn, session, selection.get("pokemon_uid"))
        if pokemon is None or pokemon["revision"] != selection.get("pokemon_revision"):
            raise _Refused(REOPEN)
        profile = await profiles.get_profile(conn, session["guild_id"], session["user_id"])
        identity, sprite = storage.identify(walker.bot.content, pokemon)
        arena_team = await profiles.arena_team(conn, session["profile_id"], walker.clock())
        reason = service.protected_reason(identity, pokemon, profile, arena_team)
        if reason in ("in_arena", "deployed", "favorite", "companion"):
            if reason == "in_arena":
                raise _Refused("This Pokémon is on your Arena team. It can't be sent until the run ends.")
            if reason == "deployed":
                raise _Refused("Recall it from the gym first")
            raise _Refused(f"This Pokémon is protected: {reason}.")
        save(session, {"single": True, "picks": [(pokemon["pokemon_uid"], pokemon["revision"])],
                       **({"caught": selection["caught"]} if "caught" in selection else {})})
        if reason is None:
            return await review(conn, session, interaction)
        status = "Shiny" if reason == "shiny" else "Legendary/Mythical"
        return screen(session, f"{identity['name_en']} · {status}: unlock research sending, then confirm a second warning.",
                      [("Unlock", "storage_send_unlock", False, 0), ("Cancel", "research_cancel", False, 0)], sprite=sprite)

    async def unlock(conn, session, interaction):
        selection = json.loads(session["selection"])
        if not selection.get("single") or len(selection.get("picks", [])) != 1:
            raise _Refused(REOPEN)
        return await review(conn, session, interaction, unlock=True)

    async def confirm(conn, session, interaction):
        selection = json.loads(session["selection"])
        send = service.send_pending_reviewed if selection.get("caught", {}).get("pending") else service.send
        result = await send(conn, session, selection.get("picks", []), selection.get("preview"), walker.clock(), walker.bot.content)
        if result["status"] != "sent":
            return notice(session, "Selection changed or review expired; start a new review.")
        candy = _candy_text(result['candy'], walker.bot.content)
        if "caught" in selection:
            save(session, selection["caught"])
            return screen(session, f"Sent {result['count']} Pokémon · {candy} · 0 Stardust.",
                          [("Done", "ack", False, 0)])
        return screen(session, f"Sent {result['count']} Pokémon · {candy} · 0 Stardust.",
                      [("Storage", "storage", False, 0)])

    async def cancel(conn, session, interaction):
        selection = json.loads(session["selection"])
        if "caught" in selection:
            save(session, selection["caught"])
            return await walker.home(conn, session, interaction)
        return await walker.handlers["storage"](conn, session, interaction)

    async def research(conn, session, interaction):
        selection = json.loads(session["selection"])
        if "caught" in selection:
            save(session, selection["caught"])
            return await catch_send(conn, session, interaction)
        return await page(conn, session, interaction, reset=True)

    return {"catch_send": catch_send, "research": research, "research_page": partial(page, delta=5),
            "research_prev": partial(page, delta=-5), "research_review": review, "research_confirm": confirm,
            "research_cancel": cancel, "storage_send": single, "storage_send_unlock": unlock,
            "storage_send_confirm": confirm, **{"research_toggle_" + letter: partial(page, toggle=letter)
                                              for letter in "abcde"}}
