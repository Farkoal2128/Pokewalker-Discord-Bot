"""M1.6 durable session routing with real SQLite and synthetic Discord I/O."""

import asyncio
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

from pokewalker.db import Writer, open_db
from pokewalker.services import profiles
from pokewalker.services.reactions import ReactionService
from test_reactions import FakeDiscord


class WalkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.module = importlib.import_module("pokewalker.bot.walker")
        except ModuleNotFoundError:
            self.fail("M1.6 walker session/router implementation is absent")
        self.conn = await open_db(":memory:", allow_unpatched=True)
        self.addAsyncCleanup(self.conn.close)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.bot = FakeDiscord(self.conn)
        self.bot.writer = self.writer
        self.bot.content = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))
        self.bot.help_text = "Approved help"
        self.bot.reactions = ReactionService(self.bot)
        self.walker = self.module.Walker(self.bot, clock=lambda: 1000, rng=random.Random(8))
        self.bot.walker = self.walker

    def interaction(self, user=456, guild=123, values=None):
        events = []
        async def defer(**kwargs):
            events.append(("defer", kwargs))
        async def edit(**kwargs):
            self.assertFalse(self.conn.in_transaction)
            events.append(("edit", kwargs))
        return SimpleNamespace(user=SimpleNamespace(id=user), guild_id=guild, client=self.bot,
                               data={"values": values or []}, events=events,
                               response=SimpleNamespace(defer=AsyncMock(side_effect=defer), send_message=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()),
                               edit_original_response=AsyncMock(side_effect=edit))

    async def rows(self, sql="SELECT * FROM sessions", args=()):
        async with self.conn.execute(sql, args) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def open(self):
        interaction = self.interaction()
        await self.walker.open(interaction)
        return interaction, (await self.rows())[-1]

    async def click(self, session, action, values=None, **who):
        interaction = self.interaction(values=values, **who)
        await self.walker.route(interaction, f"pw:v1:{session['session_id']}:{session['revision']}:{action}")
        return interaction

    async def select_starter(self):
        _, session = await self.open()
        await self.click(session, "onboard_gen", ["1"])
        session = (await self.rows())[0]
        await self.click(session, "onboard_pick", ["1"])
        return (await self.rows())[0]

    async def enroll(self):
        return await self.writer.run(lambda conn: profiles.enroll(
            conn, 123, 456, 1, self.bot.content, random.Random(8), datetime.now(timezone.utc)))

    async def exclude(self):
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)"))

    async def test_screen_edits_leave_no_views_in_the_real_view_store(self):
        store = discord.ui.view.ViewStore(None)

        def storing(interaction):
            # Mirrors discord.py 2.7 edit_original_response: unfinished dispatchable views are stored.
            async def edit(**kwargs):
                view = kwargs.get("view")
                if view is not None and not view.is_finished() and view.is_dispatchable():
                    store.add_view(view, 1)
            interaction.edit_original_response.side_effect = edit
            return interaction

        await self.enroll()
        interaction = storing(self.interaction())
        await self.walker.open(interaction)
        for _ in range(100):
            session = (await self.rows())[-1]
            await self.walker.route(storing(self.interaction()),
                                    f"pw:v1:{session['session_id']}:{session['revision']}:home")
        self.assertEqual((await self.rows())[-1]["revision"] - session["revision"], 1)
        self.assertEqual((store._views, store._synced_message_views), ({}, {}))

    async def test_walker_defers_ephemeral_then_edits_original(self):
        interaction, _ = await self.open()
        self.assertEqual([event[0] for event in interaction.events], ["defer", "edit"])
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)

    async def test_no_profile_shows_onboarding_with_session_keyed_by_guild_user(self):
        interaction, session = await self.open()
        self.assertEqual((session["guild_id"], session["user_id"], session["profile_id"]), ("123", "456", None))
        self.assertEqual((session["revision"], session["expires_at"]), (0, 1900))
        self.assertIn("starter", interaction.edit_original_response.await_args.kwargs["embed"].description.lower())
        self.assertEqual(len(interaction.edit_original_response.await_args.kwargs["view"].children[0].options), 9)

    async def test_onboarding_buttons_route_through_router_without_profile(self):
        _, session = await self.open()
        interaction = await self.click(session, "onboard_gen", ["1"])
        self.assertEqual((await self.rows())[0]["revision"], 1)
        self.assertEqual(len(interaction.edit_original_response.await_args.kwargs["view"].children[0].options), 3)

    async def test_onboarding_two_step_select_then_confirm_enrolls_and_attaches_profile(self):
        session = await self.select_starter()
        interaction = await self.click(session, "onboard_confirm")
        updated = (await self.rows())[0]
        self.assertEqual(updated["revision"], 3)
        self.assertEqual(updated["profile_id"], (await self.rows("SELECT * FROM profiles"))[0]["profile_id"])
        self.assertIn("1/3", interaction.edit_original_response.await_args.kwargs["embed"].description)
        self.assertEqual((await self.rows("SELECT * FROM inventory WHERE item_id='poke_ball'"))[0]["quantity"], 30)

    async def test_onboarding_shows_help_once_after_confirmation(self):
        session = await self.select_starter()
        interaction = await self.click(session, "onboard_confirm")
        interaction.followup.send.assert_awaited_once()
        self.assertTrue(interaction.followup.send.await_args.kwargs['ephemeral'])
        self.assertEqual(interaction.followup.send.await_args.kwargs['embed'].description, self.bot.help_text)
        reopened, _ = await self.open()
        reopened.followup.send.assert_not_awaited()
        stale = await self.click(session, "onboard_confirm")
        self.assertNotIn('embed', stale.followup.send.await_args.kwargs)

    async def test_readme_works_before_enrollment_and_for_excluded_member(self):
        from pokewalker.bot.client import readme_command
        command = readme_command(self.bot)
        await self.writer.run(lambda conn: conn.execute("INSERT INTO guilds(guild_id,created_at) VALUES ('123',0)"))
        for excluded in (False, True):
            if excluded:
                await self.exclude()
            interaction = self.interaction()
            await command.callback(interaction)
            response = interaction.response.send_message.await_args.kwargs
            self.assertTrue(response['ephemeral'])
            self.assertEqual(response['embed'].description, self.bot.help_text)
        self.assertEqual(await self.rows('SELECT * FROM profiles'), [])

    async def test_confirm_twice_is_one_enrollment(self):
        session = await self.select_starter()
        await asyncio.gather(self.click(session, "onboard_confirm"), self.click(session, "onboard_confirm"))
        for table in ("profiles", "pokemon", "encounters", "action_receipts"):
            self.assertEqual(len(await self.rows(f"SELECT * FROM {table}")), 1)
        self.assertEqual((await self.rows())[0]["revision"], 3)

    async def assert_refused(self, session, text, **who):
        before = await self.rows()
        interaction = await self.click(session, "home", **who)
        self.assertEqual(await self.rows(), before)
        self.assertIn(text, interaction.followup.send.await_args.args[0])
        self.assertTrue(interaction.followup.send.await_args.kwargs["ephemeral"])
        interaction.edit_original_response.assert_not_awaited()

    async def test_router_rejects_other_user_no_state_change(self):
        _, session = await self.open()
        await self.assert_refused(session, "not yours", user=999)

    async def test_router_rejects_wrong_guild(self):
        _, session = await self.open()
        await self.assert_refused(session, "not yours", guild=999)

    async def test_stale_revision_explains_reopen(self):
        _, session = await self.open()
        session["revision"] = 10
        await self.assert_refused(session, "reopen /walker")

    async def test_expired_session_explains_reopen(self):
        _, session = await self.open()
        self.walker.clock = lambda: 1900
        await self.assert_refused(session, "reopen /walker")

    async def test_excluded_refused_at_entry_and_in_router(self):
        _, session = await self.open()
        await self.exclude()
        await self.assert_refused(session, "/walker-account privacy")
        before = await self.rows()
        interaction = self.interaction()
        await self.walker.open(interaction)
        self.assertEqual(await self.rows(), before)
        self.assertIn("delete-data", interaction.edit_original_response.await_args.kwargs["content"])

    async def test_excluded_after_session_created_is_refused_on_next_action(self):
        session = await self.select_starter()
        await self.exclude()
        interaction = await self.click(session, "onboard_confirm")
        self.assertIn("excluded", interaction.followup.send.await_args.args[0].lower())
        self.assertEqual(await self.rows("SELECT * FROM profiles"), [])
        self.assertEqual((await self.rows())[0], session)

    async def test_paused_can_still_open_encounter(self):
        await self.enroll()
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO restrictions(guild_id,user_id,paused,paused_until) VALUES ('123','456',1,9999999999)"))
        interaction, session = await self.open()
        self.assertIn("Paused", interaction.edit_original_response.await_args.kwargs["embed"].description)
        self.assertIn("until", interaction.edit_original_response.await_args.kwargs["embed"].description)
        called = []
        async def reveal(conn, current, interaction):
            self.assertTrue(conn.in_transaction)
            called.append(current["profile_id"])
            return await self.walker.home(conn, current, interaction)
        self.walker.handlers["open_encounter"] = reveal
        await self.click(session, "open_encounter")
        self.assertEqual(called, [session["profile_id"]])
        self.assertEqual((await self.rows())[0]["revision"], 1)

    async def test_uninstalled_encounter_handler_reports_unavailable_without_mutation(self):
        await self.enroll()
        _, session = await self.open()
        encounters = await self.rows("SELECT * FROM encounters")
        self.walker.handlers.pop("open_encounter")
        interaction = await self.click(session, "open_encounter")
        self.assertIn("reopen /walker", interaction.followup.send.await_args.args[0])
        self.assertEqual((await self.rows())[0], session)
        self.assertEqual(await self.rows("SELECT * FROM encounters"), encounters)

    async def test_home_uses_exact_artifact_gender_shiny_thumbnail_without_fallback(self):
        profile = await self.enroll()
        identity = next(item for item in self.bot.content["identities"]
                        if item["kind"] == "default" and item["has_gender_differences"]
                        and item["sprites"]["shiny_female"] is not None)
        for shiny, key in ((False, "female"), (True, "shiny_female")):
            await self.writer.run(lambda conn: conn.execute(
                "UPDATE pokemon SET pokemon_id=?,gender='female',shiny=? WHERE pokemon_uid=?",
                (identity["pokemon_id"], shiny, profile["companion_uid"])))
            interaction, _ = await self.open()
            self.assertEqual(interaction.edit_original_response.await_args.kwargs["embed"].thumbnail.url,
                             identity["sprites"][key])
        identity["sprites"]["shiny_female"] = None
        interaction, _ = await self.open()
        self.assertIsNone(interaction.edit_original_response.await_args.kwargs["embed"].thumbnail.url)

    async def seed_reaction(self):
        profile = await self.enroll()
        encounter = (await self.rows("SELECT * FROM encounters"))[0]
        async def seed(conn):
            await conn.execute("INSERT INTO guild_channels(guild_id,channel_id) VALUES ('123','3')")
            await conn.execute("INSERT INTO reactions(encounter_id,message_id,profile_id,channel_id,desired,created_at) "
                               "VALUES (?,'10',?,'3','add',0)", (encounter["encounter_id"], profile["profile_id"]))
        await self.writer.run(seed)
        return encounter

    async def test_walker_open_removes_reaction_without_opening_encounter(self):
        encounter = await self.seed_reaction()
        self.bot.present.add(10)
        await self.open()
        self.assertEqual(self.bot.calls, [("remove", 3, 10)])
        self.assertEqual(await self.rows("SELECT * FROM reactions"), [])
        self.assertEqual((await self.rows("SELECT * FROM encounters"))[0], encounter)
        await self.open()
        self.assertEqual(len(self.bot.calls), 1)

    async def test_exclusion_during_reaction_removal_refuses_home(self):
        await self.seed_reaction()
        async def exclude_after_commit(encounter_id):
            await self.exclude()
        with patch.object(self.bot.reactions, "reconcile_reaction", side_effect=exclude_after_commit):
            interaction = self.interaction()
            await self.walker.open(interaction)
        self.assertIn("excluded", interaction.edit_original_response.await_args.kwargs["content"].lower())

    async def test_open_clears_legacy_pending_reaction(self):
        await self.seed_reaction()
        await self.writer.run(lambda conn: conn.execute("UPDATE reactions SET encounter_id=NULL"))
        self.bot.present.add(10)
        await self.open()
        self.assertEqual(self.bot.present, set())
        self.assertEqual(await self.rows("SELECT * FROM reactions"), [])

    async def test_excluded_entry_leaves_pending_reaction_and_session_state_untouched(self):
        await self.seed_reaction()
        await self.exclude()
        before = await self.rows("SELECT * FROM reactions")
        interaction = self.interaction()
        await self.walker.open(interaction)
        self.assertEqual(await self.rows("SELECT * FROM reactions"), before)
        self.assertEqual(await self.rows(), [])
        self.assertEqual(self.bot.calls, [])

    async def test_open_while_add_in_flight_ends_with_no_reaction(self):
        encounter = await self.seed_reaction()
        self.bot.add_started, self.bot.add_release = asyncio.Event(), asyncio.Event()
        adding = asyncio.create_task(self.bot.reactions.reconcile_reaction(encounter["encounter_id"]))
        await self.bot.add_started.wait()
        opening = asyncio.create_task(self.open())
        # Wait until the committed remove request is visible, without releasing the add.
        for _ in range(100):
            if (await self.rows("SELECT * FROM reactions"))[0]["desired"] == "remove":
                break
            await asyncio.sleep(0)
        self.assertEqual((await self.rows("SELECT * FROM reactions"))[0]["desired"], "remove")
        self.bot.add_release.set()
        await asyncio.gather(adding, opening)
        self.assertEqual(self.bot.present, set())
        self.assertEqual(await self.rows("SELECT * FROM reactions"), [])

    async def test_invalid_selection_and_unknown_action_do_not_mutate(self):
        _, session = await self.open()
        before = await self.rows()
        for action, values in (("onboard_gen", ["10"]), ("onboard_pick", ["1"]),
                               ("onboard_confirm", []), ("garbage", [])):
            await self.click(session, action, values)
            self.assertEqual(await self.rows(), before)

    async def test_restart_routes_persisted_onboarding_selection(self):
        session = await self.select_starter()
        self.walker = self.module.Walker(self.bot, clock=lambda: 1001, rng=random.Random(9))
        self.bot.walker = self.walker
        await self.click(session, "onboard_confirm")
        self.assertIsNotNone((await self.rows())[0]["profile_id"])

    async def test_result_recovery_hook_runs_before_home_inside_writer(self):
        await self.enroll()
        calls = []
        async def recover(conn, session):
            self.assertTrue(conn.in_transaction)
            calls.append(session["profile_id"])
            return {"embed": discord.Embed(title="Saved result"), "view": discord.ui.View(timeout=None)}
        self.walker.before_home = recover
        with patch.object(profiles, "queue_size", side_effect=AssertionError("home ran before result recovery")):
            interaction, session = await self.open()
        self.assertEqual(calls, [session["profile_id"]])
        self.assertEqual(interaction.edit_original_response.await_args.kwargs["embed"].title, "Saved result")

    async def test_session_edits_remain_in_revision_order(self):
        _, session = await self.open()
        started, release = asyncio.Event(), asyncio.Event()
        first = self.interaction(values=["1"])
        async def slow_edit(**kwargs):
            started.set()
            await release.wait()
        first.edit_original_response.side_effect = slow_edit
        first_task = asyncio.create_task(self.walker.route(
            first, f"pw:v1:{session['session_id']}:0:onboard_gen"))
        await asyncio.wait_for(started.wait(), 2)
        second = self.interaction(values=["1"])
        second_task = asyncio.create_task(self.walker.route(
            second, f"pw:v1:{session['session_id']}:1:onboard_pick"))
        try:
            await asyncio.sleep(0)
            second.edit_original_response.assert_not_awaited()
            self.assertEqual((await self.rows())[0]["revision"], 1)
        finally:
            release.set()
        await asyncio.gather(first_task, second_task)
        self.assertEqual((await self.rows())[0]["revision"], 2)
        second.edit_original_response.assert_awaited_once()

    async def test_dm_entry_refused_without_session(self):
        interaction = self.interaction(guild=None)
        await self.walker.open(interaction)
        self.assertEqual(await self.rows(), [])
        self.assertIn("server", interaction.edit_original_response.await_args.kwargs["content"])
