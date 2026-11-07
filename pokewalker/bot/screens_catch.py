"""Pure catch screens; kept separate to bound the walker/router module."""

import discord

from pokewalker.domain.cp import appraisal


def custom_id(state, action):
    session = state["session"]
    return f"pw:v1:{session['session_id']}:{session['revision']}:{action}"


def _label(item):
    return item.replace("_", " ").title() if item else "None"


def _embed(state, title):
    encounter, identity = state["encounter"], state["identity"]
    pokemon = state.get("pokemon") or encounter
    gender = {"female": "♀", "male": "♂", "genderless": "Genderless"}[pokemon["gender"]]
    shiny = "✨ Shiny · " if pokemon["shiny"] else ""
    form = identity["kind"]
    description = (f"{shiny}{identity['name_en']} · {form} · {gender}\n"
                   f"CP {state['cp']} · {' / '.join(str(item).title() for item in identity['types'])} · "
                   f"{encounter['tier'].title()}")
    embed = discord.Embed(title=title, description=description)
    if state["sprite"] is not None:
        embed.set_image(url=state["sprite"])
    return embed


def render_catch(state):
    embed = _embed(state, "Wild encounter")
    bag, selection = state["bag"], state["selection"]
    embed.description += ("\nBag: " + ", ".join(f"{_label(item)} ×{bag.get(item, 0)}"
                                              for item in [*state["balls"], *state["berries"]])
                          + f"\nSelected ball: {_label(selection.get('ball'))}"
                          + f" · Berry: {_label(selection.get('berry'))}")
    if state.get("raid_line"):
        embed.description += "\n" + state["raid_line"]
    if state.get("notice"):
        embed.description += "\n" + state["notice"]
    view = discord.ui.View(timeout=None)
    available_balls = [item for item in state["balls"] if bag.get(item, 0) > 0]
    for label, action in (("Ball", "select_ball"), ("Berry", "select_berry"), ("Throw", "throw"),
                          ("Later", "later"), ("Run", "run")):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), row=0,
                                       disabled=label in ("Ball", "Throw") and not available_balls))
    if picker := state.get("picker"):
        items = available_balls if picker == "ball" else ["none", *[item for item in state["berries"] if bag.get(item, 0) > 0]]
        if items:
            view.add_item(discord.ui.Select(placeholder=f"Choose {picker}", row=1,
                                           custom_id=custom_id(state, f"pick_{picker}"),
                                           options=[discord.SelectOption(label=_label(item), value=item) for item in items]))
    return {"embed": embed, "view": view}


def render_run_confirm(state):
    embed = _embed(state, "Confirm Run")
    embed.description += f"\nRun from Shiny {state['identity']['name_en']} permanently?"
    view = discord.ui.View(timeout=None)
    for label, action in (("Confirm Run", "run_confirm"), ("Back", "open_encounter")):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action)))
    return {"embed": embed, "view": view}


def render_terminal(state):
    embed = _embed(state, "Encounter result")
    embed.description += f"\nResult: {state['encounter']['state']}"
    if state["encounter"]["state"] == "caught":
        pokemon = state.get("pokemon") or state["encounter"]
        stars = appraisal([pokemon[key] for key in ("iv_attack", "iv_defense", "iv_stamina")])
        embed.description += (f"\nAppraisal: {stars} stars"
                              f"\n+{state.get('candy', 0)} Candy · +{state.get('stardust', 0)} Stardust")
    view = discord.ui.View(timeout=None)
    if not state.get("recovery"):
        for label in ("Ball", "Berry", "Throw", "Later", "Run"):
            view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, label.lower()), disabled=True))
    view.add_item(discord.ui.Button(label="Done", custom_id=custom_id(state, "ack"), row=1))
    if state["encounter"]["state"] == "caught" and (
            state.get("pending") or (state.get("pokemon") or {}).get("state") == "owned"):
        view.add_item(discord.ui.Button(label="Send for research", custom_id=custom_id(state, "catch_send"), row=1))
    return {"embed": embed, "view": view}


def render_master_confirm(state):
    embed = _embed(state, "Confirm Master Ball")
    embed.description += f"\nUse your Master Ball to catch {state['identity']['name_en']}?"
    view = discord.ui.View(timeout=None)
    for label, action in (("Confirm Master Ball", "master_confirm"), ("Back", "open_encounter")):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action)))
    return {"embed": embed, "view": view}
