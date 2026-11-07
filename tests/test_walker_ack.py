"""M1.9 durable terminal recovery through real SQLite and the session router."""

import json
import random
import sqlite3
import unittest
from unittest.mock import Mock

import test_catching as catching


class AcknowledgementTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = catching.CatchingTests.asyncSetUp
    interaction = catching.CatchingTests.interaction
    rows = catching.CatchingTests.rows
    open = catching.CatchingTests.open
    click = catching.CatchingTests.click
    enroll = catching.CatchingTests.enroll
    exclude = catching.CatchingTests.exclude
    ready = catching.CatchingTests.ready
    current = catching.CatchingTests.current
    reveal = catching.CatchingTests.reveal
    encounter_row = catching.CatchingTests.encounter_row
    prepared = catching.CatchingTests.prepared

    def rendered(self, interaction):
        return interaction.edit_original_response.await_args.kwargs

    async def caught(self):
        session = await self.prepared()
        interaction, session = await self.caught_after_prepared(session)
        self.assertIsNone((await self.encounter_row())["acknowledged_at"])
        return interaction, session

    def restart(self):
        self.walker = self.module.Walker(self.bot, clock=lambda: 1001, rng=random.Random(9))
        self.bot.walker = self.walker

    async def terminal_copy(self, encounter_id, state, resolved_at):
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO encounters(encounter_id,profile_id,source_channel_id,source_message_id,pokemon_id,"
            "level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,tier,route_id,lure_id,state,"
            "attempt_ordinal,revision,content_version,created_at,resolved_at,acknowledged_at) "
            "SELECT ?,profile_id,NULL,NULL,pokemon_id,level_x2,iv_attack,"
            "iv_defense,iv_stamina,gender,shiny,tier,route_id,lure_id,?,attempt_ordinal,revision,"
            "content_version,created_at,?,NULL FROM encounters LIMIT 1",
            (encounter_id, state, resolved_at)))

    async def test_fresh_session_shows_unacknowledged_catch_before_home(self):
        await self.caught()
        self.restart()
        interaction, session = await self.open()
        rendered = self.rendered(interaction)
        self.assertEqual(rendered["embed"].title, "Encounter result")
        self.assertIn("caught", rendered["embed"].description)
        self.assertEqual([button.label for button in rendered["view"].children], ["Done", "Send for research"])
        self.assertEqual(json.loads(session["selection"])["encounter_id"], self.encounter["encounter_id"])

    async def test_catch_result_rebuilt_from_pokemon_and_ledger(self):
        await self.caught()
        await catching.store_legacy(self.writer, self.encounter["encounter_id"], 1000)
        async def change_cached_result(conn):
            async with conn.execute("SELECT key,result FROM action_receipts WHERE action='throw'") as cursor:
                receipt = await cursor.fetchone()
            result = json.loads(receipt["result"])
            result.update(candy=999, stardust=999)
            await conn.execute("UPDATE action_receipts SET result=? WHERE key=?", (json.dumps(result), receipt["key"]))
            await conn.execute("UPDATE pokemon SET iv_attack=15,iv_defense=15,iv_stamina=15 WHERE origin='catch'")
            await conn.execute("UPDATE profiles SET stardust=9000")
            await conn.execute("UPDATE candy SET quantity=9000")
            await conn.execute("UPDATE sessions SET selection='{}'")
        await self.writer.run(change_cached_result)
        self.restart()
        interaction, _ = await self.open()
        description = self.rendered(interaction)["embed"].description
        self.assertIn("+5 Candy", description)
        self.assertIn("+300 Stardust", description)
        self.assertIn("Appraisal: 4 stars", description)
        self.assertNotIn("999", description)

    async def test_completed_catch_then_queued_encounter_shows_result_first_then_encounter(self):
        await self.caught()
        await self.terminal_copy("next", "queued", None)
        interaction, session = await self.open()
        self.assertEqual(self.rendered(interaction)["embed"].title, "Encounter result")
        interaction = await self.click(session, "ack")
        self.assertEqual(self.rendered(interaction)["embed"].title, "Walker")
        button = self.rendered(interaction)["view"].children[0]
        self.assertEqual((button.label, button.disabled), ("Open encounter", False))
        interaction = await self.click(await self.current(session), "open_encounter")
        self.assertEqual(self.rendered(interaction)["embed"].title, "Wild encounter")
        self.assertEqual((await self.rows("SELECT state FROM encounters WHERE encounter_id='next'"))[0]["state"], "revealed")

    async def test_ack_idempotent_and_advances_to_next_result(self):
        await self.caught()
        await catching.store_legacy(self.writer, self.encounter["encounter_id"], 1000)
        await self.terminal_copy("oldest", "ran", 900)
        await self.terminal_copy("middle", "fled", 950)
        _, first = await self.open()
        _, competing = await self.open()
        self.assertEqual(json.loads(first["selection"])["encounter_id"], "oldest")
        interaction = await self.click(first, "ack")
        self.assertIn("fled", self.rendered(interaction)["embed"].description)
        self.walker.clock = lambda: 1002
        interaction = await self.click(competing, "ack")
        self.assertIn("fled", self.rendered(interaction)["embed"].description)
        records = {row["encounter_id"]: row for row in await self.rows("SELECT * FROM encounters")}
        self.assertEqual(records["oldest"]["acknowledged_at"], 1000)
        self.assertIsNone(records["middle"]["acknowledged_at"])
        await self.click(await self.current(competing), "ack")
        self.assertEqual(json.loads((await self.current(competing))["selection"])["encounter_id"], self.encounter["encounter_id"])

    async def test_ran_and_fled_surface_once(self):
        session = await self.prepared(shiny=0)
        await self.click(session, "run")
        self.assertIsNone((await self.encounter_row())["acknowledged_at"])
        await self.terminal_copy("fled", "fled", 1001)
        for outcome in ("ran", "fled"):
            self.restart()
            interaction, session = await self.open()
            self.assertIn(outcome, self.rendered(interaction)["embed"].description)
            await self.click(session, "ack")
        interaction, _ = await self.open()
        self.assertEqual(self.rendered(interaction)["embed"].title, "Walker")
        self.assertTrue(all(row["acknowledged_at"] is not None for row in await self.rows("SELECT * FROM encounters")))

    async def test_done_on_result_screen_acknowledges(self):
        result, _ = await self.caught()
        done = next(button for button in self.rendered(result)["view"].children if button.label == "Done")
        interaction = self.interaction()
        await self.walker.route(interaction, done.custom_id)
        self.assertEqual((await self.encounter_row())["acknowledged_at"], 1000)
        self.restart()
        interaction, _ = await self.open()
        self.assertEqual(self.rendered(interaction)["embed"].title, "Walker")

    async def test_crash_after_commit_before_edit_recovers_through_fresh_session_router(self):
        session = await self.prepared()
        self.walker.rng = Mock(random=Mock(return_value=0))
        interaction = self.interaction()
        interaction.edit_original_response.side_effect = RuntimeError("HTTP failed")
        with self.assertRaisesRegex(RuntimeError, "HTTP failed"):
            await self.walker.route(interaction, f"pw:v1:{session['session_id']}:{session['revision']}:throw")
        self.restart()
        interaction, _ = await self.open()
        self.assertIn("caught", self.rendered(interaction)["embed"].description)
        done = self.rendered(interaction)["view"].children[0]
        interaction = self.interaction()
        await self.walker.route(interaction, done.custom_id)
        self.assertEqual(self.rendered(interaction)["embed"].title, "Walker")
        self.assertEqual(len(await self.rows("SELECT * FROM catch_attempts")), 1)
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE origin='catch'")), 1)
        self.assertIsNotNone((await self.encounter_row())["acknowledged_at"])

    async def test_failed_throw_flee_leaves_unacknowledged_result(self):
        session = await self.prepared(shiny=0)
        self.walker.rng = Mock(random=Mock(side_effect=(0.99, 0)))
        await self.click(session, "throw")
        row = await self.encounter_row()
        self.assertEqual(row["state"], "fled")
        self.assertIsNone(row["acknowledged_at"])
        self.restart()
        interaction, session = await self.open()
        self.assertIn("fled", self.rendered(interaction)["embed"].description)
        await self.click(session, "ack")
        interaction, _ = await self.open()
        self.assertEqual(self.rendered(interaction)["embed"].title, "Walker")

    async def test_other_user_cannot_ack(self):
        _, session = await self.caught()
        before = await self.encounter_row()
        for who in ({"user": 999}, {"guild": 999}):
            interaction = await self.click(session, "ack", **who)
            self.assertIn("not yours", interaction.followup.send.await_args.args[0])
            interaction.edit_original_response.assert_not_awaited()
            self.assertEqual(await self.encounter_row(), before)

    async def test_home_also_recovers_result(self):
        _, session = await self.caught()
        interaction = await self.click(session, "home")
        self.assertEqual(self.rendered(interaction)["embed"].title, "Encounter result")
        self.assertEqual([button.label for button in self.rendered(interaction)["view"].children], ["Done", "Send for research"])

    async def test_ack_rejects_unresolved_and_excluded(self):
        session = await self.prepared()
        before = await self.encounter_row()
        interaction = await self.click(session, "ack")
        interaction.edit_original_response.assert_not_awaited()
        self.assertEqual(await self.encounter_row(), before)
        _, session = await self.caught_after_prepared(session)
        await self.exclude()
        interaction = await self.click(session, "ack")
        self.assertIn("excluded", interaction.followup.send.await_args.args[0].lower())
        self.assertIsNone((await self.encounter_row())["acknowledged_at"])

    async def caught_after_prepared(self, session):
        self.walker.rng = Mock(random=Mock(return_value=0))
        interaction = await self.click(session, "throw")
        return interaction, await self.current(session)

    async def test_ack_and_session_update_rollback_together(self):
        _, session = await self.caught()
        await self.writer.run(lambda conn: conn.execute(
            "CREATE TRIGGER fail_ack_session BEFORE UPDATE ON sessions "
            "BEGIN SELECT RAISE(ABORT,'session unavailable'); END"))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "session unavailable"):
            await self.click(session, "ack")
        self.assertIsNone((await self.encounter_row())["acknowledged_at"])
        self.assertEqual(await self.current(session), session)
