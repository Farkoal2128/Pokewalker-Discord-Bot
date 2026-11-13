"""C5 private walker entry, durable session authorization and onboarding."""

import asyncio
from datetime import datetime, timezone
import json
import random
import re
import time
from uuid import uuid4
from weakref import WeakValueDictionary

import discord
from discord import app_commands

from content.balance import load_table
from pokewalker.bot import screens, storage
from pokewalker.bot import research, powerup, pokedex
from pokewalker.bot import evolve, gyms, iv_items
from pokewalker.bot import milestones, bag, route, share, trade
from pokewalker.services.milestones import pending_count
from pokewalker.services.items import recent_finds
from pokewalker.db import with_receipt
from pokewalker.services.deletion import opted_out
from pokewalker.services import capacity, profiles, catching, storage as storage_service


CUSTOM_ID = r"^pw:v1:(?P<session>[0-9a-f-]+):(?P<rev>\d+):(?P<action>[a-z_]+)$"
EXCLUDED = "You are excluded here. Only /walker-account privacy, /walker-account delete-data and /walker-account opt-out are available."
REOPEN = "That option changed since this screen opened. Please reopen /walker to refresh."
TIMED_OUT = "This window timed out. Please reopen /walker for a fresh one."
OUTDATED = "This screen is out of date. Please reopen /walker to refresh."
TRADE_TIMED_OUT = "This window timed out. Please reopen /trade for a fresh one."
TRADE_OUTDATED = "This screen is out of date. Please reopen /trade to refresh."
TRADE_REOPEN = "That option changed since this screen opened. Please reopen /trade to refresh."
IDLE_SECONDS = 900
DOUBLE_PRESS_SECONDS = 10


class _Outdated(Exception):
    """A double press or a press racing the newer screen; dropped silently."""


class _Refused(ValueError):
    pass


def _forget(rendered):
    # Clicks route by custom_id through Walker.route, so drop the per-revision view discord.py stored.
    if rendered.get("view") is not None:
        rendered["view"].stop()


class Walker:
    def __init__(self, bot, *, clock=time.time, rng=None):
        self.bot, self.clock = bot, clock
        self.rng = rng if rng is not None else random.SystemRandom()
        self.multipliers = load_table("cpm")["multipliers"]
        rules = load_table("catch")["rules"]
        self.balls = [*rules["ball_multipliers"], "master_ball"]
        self.berries = list(rules["berry_multipliers"])
        self.handlers = {name: getattr(self, name) for name in
                         ("home", "onboard_gen", "onboard_pick", "onboard_confirm", "open_encounter",
                          "select_ball", "select_berry", "later", "run", "run_confirm", "throw", "master_confirm", "ack",
                          "catch_upgrade")}
        self.handlers.update(pick_ball=self.select_ball, pick_berry=self.select_berry)
        self.handlers.update(storage.handlers(self))
        self.handlers.update(research.handlers(self))
        self.handlers.update(powerup.handlers(self))
        self.handlers.update(iv_items.handlers(self))
        self.handlers.update(evolve.handlers(self))
        self.handlers.update(pokedex.handlers(self))
        self.handlers.update(milestones.handlers(self))
        self.handlers.update(bag.handlers(self))
        self.handlers.update(route.handlers(self))
        self.handlers.update(share.handlers(self))
        self.handlers.update(gyms.handlers(self))
        self.handlers.update(trade.handlers(self))
        self.before_home = self.recover_terminal
        self._locks = WeakValueDictionary()

    async def open(self, interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.guild_id is None:
            await interaction.edit_original_response(content="Use /walker in a server.")
            return

        async def create(conn):
            if (await profiles.restrictions(conn, interaction.guild_id, interaction.user.id)).excluded:
                raise _Refused(EXCLUDED)
            if await opted_out(conn, str(interaction.guild_id), str(interaction.user.id)):
                raise _Refused("Run /walker-account opt-in first")
            profile = await profiles.get_profile(conn, interaction.guild_id, interaction.user.id)
            now = self.clock()
            session = {"session_id": str(uuid4()), "guild_id": str(interaction.guild_id),
                       "user_id": str(interaction.user.id), "profile_id": profile["profile_id"] if profile else None,
                       "revision": 0, "expires_at": now + 900, "selection": "{}"}
            await conn.execute("INSERT OR IGNORE INTO guilds(guild_id,created_at) VALUES (?,?)",
                               (session["guild_id"], now))
            await conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,profile_id,revision,expires_at) "
                               "VALUES (?,?,?,?,?,?)", tuple(session[key] for key in
                               ("session_id", "guild_id", "user_id", "profile_id", "revision", "expires_at")))
            async with conn.execute("SELECT encounter_id,message_id FROM reactions WHERE profile_id=?",
                                    (session["profile_id"],)) as cursor:
                pending = await cursor.fetchall()
            await conn.execute("UPDATE reactions SET desired='remove',revision=revision+1 WHERE profile_id=?",
                               (session["profile_id"],))
            return session, pending

        try:
            session, pending = await self.bot.writer.run(create)
        except _Refused as error:
            await interaction.edit_original_response(content=str(error))
            return
        for reaction in pending:
            if reaction["encounter_id"] is None:
                await self.bot.reactions.reconcile_message(reaction["message_id"])
            else:
                await self.bot.reactions.reconcile_reaction(reaction["encounter_id"])
        try:
            rendered = await self.bot.writer.run(lambda conn: self.home(conn, session, interaction))
        except _Refused as error:
            await interaction.edit_original_response(content=str(error))
            return
        await interaction.edit_original_response(**rendered, allowed_mentions=discord.AllowedMentions.none())
        _forget(rendered)

    async def route(self, interaction, custom_id):
        await interaction.response.defer()
        match = re.fullmatch(CUSTOM_ID, custom_id)
        if match is None:
            await self.refuse(interaction, REOPEN)
            return
        session_id, revision, action = match.group("session", "rev", "action")
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            async def dispatch(conn):
                async with conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    raise _Refused(TIMED_OUT)
                session = dict(row)
                if (str(interaction.user.id) != session["user_id"]
                        or str(interaction.guild_id) != session["guild_id"]):
                    raise _Refused("This screen is not yours. Open /walker for your own screen.")
                if session["expires_at"] <= self.clock():
                    raise _Refused(TIMED_OUT)
                if str(session["revision"]) != revision:
                    # The last committed action set expires_at; a press soon after it raced that screen.
                    if self.clock() - (session["expires_at"] - IDLE_SECONDS) < DOUBLE_PRESS_SECONDS:
                        raise _Outdated()
                    raise _Refused(OUTDATED)
                if (await profiles.restrictions(conn, session["guild_id"], session["user_id"])).excluded:
                    raise _Refused(EXCLUDED)
                if await opted_out(conn, session["guild_id"], session["user_id"]):
                    raise _Refused("Run /walker-account opt-in first")
                handler = self.handlers.get(action)
                if handler is None:
                    raise _Refused(REOPEN)
                session["_original_revision"] = session["revision"]
                session["revision"] += 1
                pending = None
                if action in ("open_encounter", "select_ball", "select_berry", "pick_ball", "pick_berry",
                              "throw", "master_confirm", "run", "run_confirm"):
                    pending = await self.pending_catch(conn, session["profile_id"])
                selected = json.loads(session["selection"])
                # Replay only an already-saved menu; an older throw screen must save the menu's storage quote.
                if pending is not None and selected.get("encounter_id") == pending and "storage_limit" in selected:
                    session["revision"] = session["_original_revision"]
                    session["_read_only"] = True
                rendered = (await self.pending_menu(conn, session, pending) if pending is not None
                            else await handler(conn, session, interaction))
                if not session.get("_read_only"):
                    await conn.execute("UPDATE sessions SET revision=?,profile_id=?,selection=?,expires_at=MAX(expires_at,?) "
                                       "WHERE session_id=?", (session["revision"], session["profile_id"],
                                                              session["selection"], self.clock() + IDLE_SECONDS,
                                                              session_id))
                return rendered

            try:
                rendered = await self.bot.writer.run(dispatch)
            except _Outdated:
                return
            except _Refused as error:
                text = str(error)
                if action.startswith("trade_"):
                    text = {TIMED_OUT: TRADE_TIMED_OUT, OUTDATED: TRADE_OUTDATED, REOPEN: TRADE_REOPEN}.get(text, text)
                await self.refuse(interaction, text)
                return
            if after_commit := rendered.pop('after_commit', None):
                rendered = await after_commit()
            await interaction.edit_original_response(**rendered, allowed_mentions=discord.AllowedMentions.none())
            _forget(rendered)
            if action == 'onboard_confirm':
                page = self.bot.help_page(0)
                await interaction.followup.send(**page, ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())
                _forget(page)

    async def refuse(self, interaction, text):
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    def starters(self, generation):
        return [{"species_id": item["species_id"], "name": item["name_en"]}
                for item in self.bot.content["identities"] if item["kind"] == "default"
                and item["species_id"] in self.bot.content["starters"] and item["generation_id"] == generation]

    def onboarding(self, session):
        selection = json.loads(session["selection"])
        return screens.onboarding({"session": session, "selection": selection, "generations": list(range(1, 10)),
                                   "starters": self.starters(selection.get("generation"))})

    async def home(self, conn, session, interaction):
        if (await profiles.restrictions(conn, session["guild_id"], session["user_id"])).excluded:
            raise _Refused(EXCLUDED)
        selection = json.loads(session["selection"])
        selection.pop("run_confirm", None)
        selection.pop("master_confirm", None)
        selection.pop("storage_confirm", None)
        session["selection"] = json.dumps(selection)
        if session["profile_id"] is None:
            return self.onboarding(session)
        if self.before_home is not None:
            recovered = await self.before_home(conn, session)
            if recovered is not None:
                return recovered
        profile = await profiles.get_profile(conn, session["guild_id"], session["user_id"])
        if profile is None or profile["profile_id"] != session["profile_id"]:
            raise _Refused(REOPEN)
        companion = None
        async with conn.execute("SELECT * FROM pokemon WHERE pokemon_uid=? AND profile_id=? AND state='owned'",
                                (profile["companion_uid"], profile["profile_id"])) as cursor:
            pokemon = await cursor.fetchone()
        if pokemon is not None:
            info = storage_service.stats(self.bot.content, pokemon, self.multipliers)
            companion = {"name": info["identity"]["name_en"], "sprite": info["sprite"], "cp": info["cp"]}
        return screens.home({"session": session, "companion": companion, "available": set(self.handlers),
                             'finds': await recent_finds(conn, profile['profile_id']),
                             'rewards_waiting': await pending_count(conn, profile['profile_id']),
                             "queue_size": await profiles.queue_size(conn, profile["profile_id"]),
                             "encounter_meter_c": profile["encounter_meter_c"],
                             "restrictions": await profiles.restrictions(conn, session["guild_id"], session["user_id"])})

    async def pending_catch(self, conn, profile_id):
        async with conn.execute("SELECT encounter_id FROM encounters WHERE profile_id=? "
                                "AND state='caught' AND acknowledged_at IS NULL AND NOT EXISTS "
                                "(SELECT 1 FROM pokemon WHERE source_encounter_id=encounters.encounter_id) "
                                "ORDER BY resolved_at,encounter_id LIMIT 1", (profile_id,)) as cursor:
            row = await cursor.fetchone()
        return row["encounter_id"] if row is not None else None

    async def store(self, conn, session, encounter_id):
        await conn.execute("INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                           "iv_stamina,gender,shiny,origin,source_encounter_id,content_version,caught_at) "
                           "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,"
                           "'catch',encounter_id,content_version,resolved_at FROM encounters WHERE encounter_id=? "
                           "AND profile_id=? AND state='caught' AND acknowledged_at IS NULL AND NOT EXISTS "
                           "(SELECT 1 FROM pokemon WHERE source_encounter_id=encounters.encounter_id)",
                           (str(uuid4()), encounter_id, session["profile_id"]))

    async def pending_menu(self, conn, session, encounter_id, notice=None):
        quote = await capacity.quote(conn, session["profile_id"], "storage")
        session["selection"] = json.dumps({"encounter_id": encounter_id,
                                           "storage_limit": quote["current"]})
        if not session.get("_read_only"):
            await conn.execute("UPDATE sessions SET selection=? WHERE session_id=?",
                               (session["selection"], session["session_id"]))
        state = await self.encounter_state(conn, session, encounter_id)
        state["recovery"] = True
        rendered = screens.render_terminal(state)
        async with conn.execute("SELECT count(*) FROM pokemon WHERE profile_id=? AND state='owned'",
                                (session["profile_id"],)) as cursor:
            owned = (await cursor.fetchone())[0]
        if owned < quote["current"]:
            if notice:
                rendered["embed"].description += "\n" + notice
            return rendered
        rendered["embed"].description += f"\nStorage is full ({owned}/{quote['current']}). Choose one:"
        reason = ("Storage is at the maximum capacity." if quote["at_cap"] else
                  "Not enough Stardust." if not quote["affordable"] else None)
        for text in (reason, notice):
            if text:
                rendered["embed"].description += "\n" + text
        step = load_table("capacities")["expansion"]["storage"]["step"]
        view = discord.ui.View(timeout=None)
        for label, action, disabled in (
                ("Send for research", "catch_send", False),
                (f"Upgrade storage space (+{step}, {quote['price']:,} Stardust)",
                 "catch_upgrade", not quote["affordable"])):
            view.add_item(discord.ui.Button(label=label, custom_id=screens.custom_id(state, action),
                                           disabled=disabled))
        rendered["view"] = view
        return rendered

    async def catch_upgrade(self, conn, session, interaction):
        selection = json.loads(session["selection"])
        encounter_id = await self.pending_catch(conn, session["profile_id"])
        if encounter_id is None or encounter_id != selection.get("encounter_id"):
            raise _Refused(REOPEN)
        result = await capacity.expand(conn, session, "storage", selection.get("storage_limit"), self.clock())
        if "status" in result:
            notice = {"stale": "Storage changed. Preview again. Nothing was spent.",
                      "at_cap": "Storage is at the maximum capacity. Nothing was spent.",
                      "insufficient": "Not enough Stardust. Nothing was spent."}.get(result["status"])
            if notice is None:
                raise _Refused(REOPEN)
            return await self.pending_menu(conn, session, encounter_id, notice)
        return await self.ack(conn, session, interaction)

    async def recover_terminal(self, conn, session):
        async with conn.execute("SELECT encounter_id FROM encounters WHERE profile_id=? "
                                "AND state IN ('caught','fled','ran') AND acknowledged_at IS NULL "
                                "ORDER BY (state='caught' AND NOT EXISTS (SELECT 1 FROM pokemon "
                                "WHERE source_encounter_id=encounters.encounter_id)) DESC, "
                                "resolved_at,encounter_id LIMIT 1", (session["profile_id"],)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        session["selection"] = json.dumps({"encounter_id": row["encounter_id"]})
        await conn.execute("UPDATE sessions SET selection=? WHERE session_id=?",
                           (session["selection"], session["session_id"]))
        state = await self.encounter_state(conn, session, row["encounter_id"])
        if state["pending"]:
            return await self.pending_menu(conn, session, row["encounter_id"])
        state["recovery"] = True
        return screens.render_terminal(state)

    async def ack(self, conn, session, interaction):
        encounter_id = json.loads(session["selection"]).get("encounter_id")
        state = await self.encounter_state(conn, session, encounter_id)
        if state["encounter"]["state"] not in ("caught", "fled", "ran"):
            raise _Refused(REOPEN)
        if state["pending"]:
            quote = await capacity.quote(conn, session["profile_id"], "storage")
            async with conn.execute("SELECT count(*) FROM pokemon WHERE profile_id=? AND state='owned'",
                                    (session["profile_id"],)) as cursor:
                owned = (await cursor.fetchone())[0]
            if owned >= quote["current"]:
                return await self.pending_menu(conn, session, encounter_id, "Nothing was stored.")
            await self.store(conn, session, encounter_id)
        await conn.execute("UPDATE encounters SET acknowledged_at=? WHERE encounter_id=? "
                           "AND profile_id=? AND acknowledged_at IS NULL",
                           (self.clock(), encounter_id, session["profile_id"]))
        session["selection"] = "{}"
        return await self.home(conn, session, interaction)

    def selection_value(self, session, interaction):
        if session["profile_id"] is not None:
            raise _Refused(REOPEN)
        values = interaction.data.get("values", [])
        if len(values) != 1 or not isinstance(values[0], str) or not values[0].isascii() or not values[0].isdecimal():
            raise _Refused("Choose one of the displayed options.")
        return int(values[0])

    async def onboard_gen(self, conn, session, interaction):
        generation = self.selection_value(session, interaction)
        if not 1 <= generation <= 9:
            raise _Refused("Choose a displayed generation.")
        session["selection"] = json.dumps({"generation": generation})
        return self.onboarding(session)

    async def onboard_pick(self, conn, session, interaction):
        starter = self.selection_value(session, interaction)
        selection = json.loads(session["selection"])
        if starter not in {item["species_id"] for item in self.starters(selection.get("generation"))}:
            raise _Refused("Choose a starter from your selected generation.")
        selection["starter"] = starter
        session["selection"] = json.dumps(selection)
        return self.onboarding(session)

    async def onboard_confirm(self, conn, session, interaction):
        selection = json.loads(session["selection"])
        if session["profile_id"] is not None or selection.get("starter") not in {
                item["species_id"] for item in self.starters(selection.get("generation"))}:
            raise _Refused("Choose a generation and starter before confirming.")
        profile = await profiles.enroll(conn, session["guild_id"], session["user_id"], selection["starter"],
                                        self.bot.content, self.rng, datetime.fromtimestamp(self.clock(), timezone.utc))
        session["profile_id"] = profile["profile_id"]
        session["selection"] = "{}"
        return await self.home(conn, session, interaction)

    async def open_encounter(self, conn, session, interaction):
        if (await profiles.restrictions(conn, session["guild_id"], session["user_id"])).excluded:
            raise _Refused(EXCLUDED)
        async with conn.execute("SELECT encounter_id FROM encounters WHERE profile_id=? "
                                "AND state IN ('queued','revealed') AND raid_spawn_id IS NULL "
                                "ORDER BY created_at,encounter_id LIMIT 1",
                                (session["profile_id"],)) as cursor:
            row = await cursor.fetchone()
        selection = json.loads(session["selection"])
        if "run_confirm" in selection or "master_confirm" in selection or "storage_confirm" in selection:
            async with conn.execute(
                    "SELECT encounter_id FROM encounters JOIN world_spawns ON spawn_id=raid_spawn_id "
                    "WHERE profile_id=? AND encounter_id=? AND state IN ('queued','revealed') "
                    "AND guild_id=? AND expires_at>?",
                    (session["profile_id"], selection.get("encounter_id"), session["guild_id"], self.clock())) as cursor:
                row = await cursor.fetchone() or row
        selection.pop("storage_confirm", None)
        session["selection"] = json.dumps(selection)
        if row is None:
            return await self.home(conn, session, interaction)
        state = await self.encounter_state(conn, session, row["encounter_id"])
        encounter = state["encounter"]
        if encounter["state"] == "queued":
            await conn.execute("UPDATE encounters SET state='revealed' WHERE encounter_id=?", (row["encounter_id"],))
            await conn.execute("INSERT INTO pokedex(profile_id,pokemon_id,seen_at) VALUES (?,?,?) "
                               "ON CONFLICT(profile_id,pokemon_id) DO NOTHING",
                               (session["profile_id"], state["identity"]["species_id"], self.clock()))
            encounter["state"] = "revealed"
        selection = state["selection"]
        if selection.get("encounter_id") != encounter["encounter_id"]:
            selection = {"ball": "poke_ball", "berry": None}
        selection.update(encounter_id=encounter["encounter_id"], encounter_revision=encounter["revision"])
        selection.pop("run_confirm", None)
        selection.pop("master_confirm", None)
        session["selection"] = json.dumps(selection)
        state["selection"] = selection
        return screens.render_catch(state)

    async def encounter_state(self, conn, session, encounter_id):
        async with conn.execute("SELECT * FROM encounters WHERE encounter_id=?", (encounter_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None or row["profile_id"] != session["profile_id"]:
            raise _Refused(REOPEN)
        encounter = dict(row)
        async with conn.execute("SELECT * FROM pokemon WHERE source_encounter_id=? AND profile_id=?",
                                (encounter_id, session["profile_id"])) as cursor:
            pokemon = await cursor.fetchone()
        display = pokemon if encounter["state"] == "caught" and pokemon is not None else encounter
        info = storage_service.stats(self.bot.content, display, self.multipliers)
        identity, sprite = info["identity"], info["sprite"]
        async with conn.execute("SELECT item_id,quantity FROM inventory WHERE profile_id=?",
                                (session["profile_id"],)) as cursor:
            bag = {row["item_id"]: row["quantity"] for row in await cursor.fetchall()}
        async with conn.execute("SELECT resource,SUM(delta) AS delta FROM resource_ledger "
                                "JOIN catch_attempts ON resource_ledger.receipt_key=catch_attempts.receipt_key "
                                "WHERE encounter_id=? AND success=1 AND profile_id=? AND reason='catch_reward' "
                                "GROUP BY resource", (encounter_id, session["profile_id"])) as cursor:
            rewards = {row["resource"]: row["delta"] for row in await cursor.fetchall()}
        raid_line = None
        if encounter.get("raid_spawn_id"):
            async with conn.execute("SELECT expires_at FROM world_spawns WHERE spawn_id=?",
                                    (encounter["raid_spawn_id"],)) as cursor:
                spawn = await cursor.fetchone()
            if spawn is not None:
                until = datetime.fromtimestamp(spawn["expires_at"], timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                raid_line = f"World Legendary · ends {until}"
        return {"raid_line": raid_line, "candy": rewards.get("candy", 0), "stardust": rewards.get("stardust", 0),
                "pending": encounter["state"] == "caught" and pokemon is None,
                "session": session, "encounter": encounter, "identity": identity,
                "pokemon": dict(pokemon) if pokemon is not None else None,
                "sprite": sprite, "bag": bag, "balls": self.balls, "berries": self.berries,
                "selection": json.loads(session["selection"]),
                "cp": info["cp"]}

    async def select_item(self, conn, session, interaction, kind, allowed):
        selection = json.loads(session["selection"])
        state = await self.encounter_state(conn, session, selection.get("encounter_id"))
        if state["encounter"]["state"] not in ("queued", "revealed"):
            return screens.render_terminal(state)
        values = interaction.data.get("values", [])
        if values:
            if len(values) != 1 or values[0] not in allowed:
                raise _Refused("Choose one of the displayed options.")
            selection[kind] = None if values[0] == "none" else values[0]
            selection.pop("run_confirm", None)
            selection.pop("master_confirm", None)
            session["selection"] = json.dumps(selection)
            state["selection"] = selection
        else:
            state["picker"] = kind
        return screens.render_catch(state)

    async def select_ball(self, conn, session, interaction):
        return await self.select_item(conn, session, interaction, "ball", self.balls)

    async def select_berry(self, conn, session, interaction):
        return await self.select_item(conn, session, interaction, "berry", ["none", *self.berries])

    async def later(self, conn, session, interaction):
        selection = json.loads(session["selection"])
        selection.pop("run_confirm", None)
        selection.pop("master_confirm", None)
        session["selection"] = json.dumps(selection)
        return await self.home(conn, session, interaction)

    async def run(self, conn, session, interaction, *, confirmed=False):
        if (await profiles.restrictions(conn, session["guild_id"], session["user_id"])).excluded:
            raise _Refused(EXCLUDED)
        selection = json.loads(session["selection"])
        state = await self.encounter_state(conn, session, selection.get("encounter_id"))
        encounter = state["encounter"]
        terminal = encounter["state"] not in ("queued", "revealed")
        if terminal or encounter["revision"] != selection.get("encounter_revision"):
            session["revision"] = session.get("_original_revision", session["revision"])
            session["_read_only"] = True
            return screens.render_terminal(state) if terminal else screens.render_catch(state)
        if encounter["raid_spawn_id"] is not None:
            async with conn.execute("SELECT 1 FROM world_spawns WHERE spawn_id=? AND guild_id=? AND expires_at>?",
                                    (encounter["raid_spawn_id"], session["guild_id"], self.clock())) as cursor:
                if await cursor.fetchone() is None:
                    raise _Refused("The World Legendary left.")
        if encounter["shiny"]:
            if not confirmed:
                selection["run_confirm"] = True
                session["selection"] = json.dumps(selection)
                return screens.render_run_confirm(state)
            if not selection.get("run_confirm"):
                raise _Refused("Confirm Run from the shiny confirmation screen first.")

        async def resolve(conn):
            await conn.execute("UPDATE encounters SET state='ran',resolved_at=?,revision=revision+1 "
                               "WHERE encounter_id=?", (self.clock(), encounter["encounter_id"]))
            saved = await self.encounter_state(conn, session, encounter["encounter_id"])
            return {"encounter": saved["encounter"], "pokemon": saved["pokemon"]}, []

        saved = await with_receipt(conn, f"run:{encounter['encounter_id']}:{encounter['revision']}", "run", resolve, profile_id=session["profile_id"])
        state.update(saved)
        return screens.render_terminal(state)

    async def run_confirm(self, conn, session, interaction):
        return await self.run(conn, session, interaction, confirmed=True)

    async def throw(self, conn, session, interaction, *, confirmed=False):
        selection = json.loads(session["selection"])
        state = await self.encounter_state(conn, session, selection.get("encounter_id"))
        encounter = state["encounter"]
        if (encounter["state"] == "revealed" and encounter["revision"] == selection.get("encounter_revision")
                and selection.get("ball") == "master_ball"):
            if not confirmed:
                selection["master_confirm"] = encounter["revision"]
                session["selection"] = json.dumps(selection)
                return screens.render_master_confirm(state)
            if selection.get("master_confirm") != encounter["revision"]:
                raise _Refused("Confirm the Master Ball from its confirmation screen first.")
        elif confirmed:
            # A competing terminal result still takes priority over an old confirmation.
            if encounter["state"] == "revealed" and encounter["revision"] == selection.get("encounter_revision"):
                raise _Refused("Confirm the Master Ball from its confirmation screen first.")
        result = await catching.throw(conn, encounter["encounter_id"], session,
                                      selection.get("encounter_revision"), self.rng, self.clock(),
                                      content=self.bot.content, guaranteed=confirmed)
        if result.status == "storage_full":
            selection["storage_confirm"] = encounter["revision"]
            session["selection"] = json.dumps(selection)
            owned = (await conn.execute_fetchall(
                "SELECT count(*) FROM pokemon WHERE profile_id=? AND state='owned'",
                (session["profile_id"],)))[0][0]
            limit = (await profiles.get_profile(conn, session['guild_id'], session['user_id']))['storage_limit']
            state["notice"] = (f"Storage is full ({owned}/{limit}). "
                               "A catch will wait for Send for research or Upgrade storage.")
            rendered = screens.render_catch(state)
            view = discord.ui.View(timeout=None)
            for label, action in (("Confirm throw", "master_confirm" if confirmed else "throw"),
                                  ("Back", "open_encounter")):
                view.add_item(discord.ui.Button(label=label, custom_id=screens.custom_id(state, action)))
            rendered["view"] = view
            return rendered
        if not session.pop("_catch_applied", False):
            session["revision"] = session.get("_original_revision", session["revision"])
            session["_read_only"] = True
        state = await self.encounter_state(conn, session, encounter["encounter_id"])
        state.update(candy=result.candy, stardust=result.stardust)
        if result.status in ("caught", "fled", "ran"):
            if state["pending"]:
                return await self.pending_menu(conn, session, encounter["encounter_id"])
            return screens.render_terminal(state)
        berry = screens.label(state["selection"].get("berry"))
        notices = {"no_ball": "You have none of the selected ball.",
                   "no_berry": f"You're out of {berry}. Pick another berry or None to throw.",
                   "expired": "The World Legendary left; this encounter expired.",
                   "revealed": "It broke free!" if not session.get("_read_only") else "Encounter updated. Reopen /walker."}
        state["notice"] = notices.get(result.status, result.status)
        return screens.render_catch(state)

    async def master_confirm(self, conn, session, interaction):
        return await self.throw(conn, session, interaction, confirmed=True)


def command(bot):
    @app_commands.command(name="walker", description="Open your private walker")
    @app_commands.guild_only()
    async def walker(interaction: discord.Interaction):
        await bot.walker.open(interaction)
    return walker
