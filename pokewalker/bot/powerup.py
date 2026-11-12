"""Private power-up quotes and one-step confirmation using saved instance revisions."""

import json

import discord

from pokewalker.bot.screens_catch import custom_id
from pokewalker.services import powerup as service, storage


def render_quote(state):
    quote = state["quote"]
    text = (f"CP {quote['cp_before']} · At cap" if quote["at_cap"] else
            f"CP {quote['cp_before']} → {quote['cp_after']} · {quote['candy_cost']} Candy (have {quote['candy_have']})"
            f" · {quote['stardust_cost']} Stardust (have {quote['stardust_have']})")
    text += f"\nOr use 1 Rare Candy instead · Rare Candy (have {quote['rare_candy_have']})"
    view = discord.ui.View(timeout=None)
    for label, action, disabled in (("Confirm", "power_up_confirm", quote["at_cap"] or not quote["affordable"]),
                                    ("Use Rare Candy", "power_up_rare", not quote["rare_affordable"]),
                                    ("Back", "storage_detail", False)):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), disabled=disabled))
    return {"embed": discord.Embed(title="Power up", description=text), "view": view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN

    async def power_up(conn, session, interaction):
        selection = json.loads(session["selection"])
        pokemon = await storage.detail(conn, session["profile_id"], selection.get("pokemon_uid"))
        if pokemon is None or pokemon["revision"] != selection.get("pokemon_revision"):
            raise _Refused(REOPEN)
        quote = await service.quote(conn, session["profile_id"], pokemon["pokemon_uid"],
                                    walker.bot.content, walker.multipliers)
        return render_quote({"session": session, "quote": quote})

    async def confirm(conn, session, interaction, use_rare_candy=False):
        selection = json.loads(session["selection"])
        result = await service.power_up(conn, session, selection.get("pokemon_uid"),
                                        selection.get("pokemon_revision"), walker.bot.content, walker.multipliers,
                                        use_rare_candy=use_rare_candy)
        if result["status"] != "powered_up":
            raise _Refused(REOPEN)
        return await walker.handlers["storage_detail"](conn, session, interaction)

    async def confirm_rare(conn, session, interaction):
        return await confirm(conn, session, interaction, use_rare_candy=True)

    return {"power_up": power_up, "power_up_confirm": confirm, "power_up_rare": confirm_rare}
