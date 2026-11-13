"""M1.6 pure screen renderers: detached state in, Discord embed/view out."""

import discord

from content.balance import limits

# Preserve the established renderer exports after the M1.7 size split.
from pokewalker.bot.screens_catch import _label as label, custom_id, render_catch, render_run_confirm, render_terminal, render_master_confirm


def home(state):
    companion = state["companion"]
    meter = state["encounter_meter_c"]
    filled = min(10, meter // 1000)
    lines = [f"{companion['name']} · CP {companion['cp']}" if companion else "No companion selected.",
             f"Queue: {state['queue_size']}/{limits()['encounter_queue']}",
             f"Encounters: {'█' * filled}{'░' * (10 - filled)} {meter / 100:g}/100 steps"]
    flags = state["restrictions"]
    lines.append(f"Rewards waiting: {state.get('rewards_waiting', 0)}")
    for find in state.get('finds', ()):
        name = find['item_id'].replace('_', ' ').title().replace('Poke Ball', 'Poké Ball')
        outcome = {'overflow': 'overflow → 10 Stardust', 'duplicate_rare': 'duplicate rare → 500 Stardust',
                   'stardust': f"{find['quantity']} Stardust", 'granted': 'granted'}[find['outcome']]
        lines.append(f"Find: {name} ×{find['quantity']} — {outcome}")
    if flags.paused:
        until = flags.paused_until.isoformat() if flags.paused_until else "further notice"
        lines.append(f"Paused: earning is paused until {until}. Queued encounters can still be played.")
    embed = discord.Embed(title="Walker", description="\n".join(lines))
    if companion and companion["sprite"] is not None:
        embed.set_thumbnail(url=companion["sprite"])
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Open encounter", custom_id=custom_id(state, "open_encounter"),
                                    disabled=state["queue_size"] == 0))
    for label, action in (("Storage", "storage"), ("Bag", "bag"), ("Pokédex", "pokedex"), ("Route", "route"), ('Gyms', 'gyms')):
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action), disabled=action not in state.get("available", ())))
    waiting = state.get('rewards_waiting', 0)
    view.add_item(discord.ui.Button(label=f"Inbox ({waiting})", custom_id=custom_id(state, "inbox"),
                                    disabled=not waiting or "inbox" not in state.get("available", ())))
    return {"embed": embed, "view": view}


def onboarding(state):
    selection = state.get("selection", {})
    lines = ["Choose a starter to begin your walk.", "Chat in enabled channels to earn steps.",
             "Steps queue encounters; open /walker to catch or run.",
             "Start with 30 Poké Balls, 5 Razz Berries, and one encounter."]
    view = discord.ui.View(timeout=None)
    if "starter" in selection:
        starter = next(item for item in state["starters"] if item["species_id"] == selection["starter"])
        lines.append(f"Confirm {starter['name']} as your starter?")
        view.add_item(discord.ui.Button(label="Confirm starter", custom_id=custom_id(state, "onboard_confirm")))
    elif "generation" in selection:
        view.add_item(discord.ui.Select(placeholder="Choose a starter", custom_id=custom_id(state, "onboard_pick"),
                                        options=[discord.SelectOption(label=item["name"], value=str(item["species_id"]))
                                                 for item in state["starters"]]))
    else:
        view.add_item(discord.ui.Select(placeholder="Choose a generation", custom_id=custom_id(state, "onboard_gen"),
                                        options=[discord.SelectOption(label=f"Generation {generation}", value=str(generation))
                                                 for generation in state["generations"]]))
    return {"embed": discord.Embed(title="Welcome to Walker", description="\n".join(lines)), "view": view}
