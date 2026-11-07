"""M1.8 catch transactions against SQLite and synthetic Discord screens."""

import asyncio
import importlib
import json
import sqlite3
import unittest
from unittest.mock import Mock
from uuid import uuid4

import test_walker_encounter as encounters


async def store_legacy(writer, encounter_id, now):
    """Model a pre-M6.8u stored result, separately from pending fixtures."""
    async def seed(conn):
        await conn.execute("INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                           "iv_stamina,gender,shiny,origin,source_encounter_id,content_version,caught_at) "
                           "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,"
                           "'catch',encounter_id,content_version,? FROM encounters WHERE encounter_id=?",
                           (str(uuid4()), now, encounter_id))
        return dict((await conn.execute_fetchall(
            "SELECT * FROM pokemon WHERE source_encounter_id=?", (encounter_id,)))[0])
    return await writer.run(seed)


class CatchingTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = encounters.EncounterTests.asyncSetUp
    interaction = encounters.EncounterTests.interaction
    rows = encounters.EncounterTests.rows
    open = encounters.EncounterTests.open
    click = encounters.EncounterTests.click
    enroll = encounters.EncounterTests.enroll
    exclude = encounters.EncounterTests.exclude
    ready = encounters.EncounterTests.ready
    current = encounters.EncounterTests.current
    reveal = encounters.EncounterTests.reveal
    encounter_row = encounters.EncounterTests.encounter_row

    async def prepared(self, **changes):
        session = await self.ready(**{"tier": "Common", "level_x2": 40, **changes})
        _, session = await self.reveal(session)
        return session

    async def inventory(self, **items):
        await self.writer.run(lambda conn: conn.executemany(
            "INSERT INTO inventory VALUES (?,?,?) ON CONFLICT(profile_id,item_id) "
            "DO UPDATE SET quantity=excluded.quantity",
            [(self.profile["profile_id"], item, count) for item, count in items.items()]))

    def choose(self, session, **selection):
        return {**session, "selection": json.dumps({**json.loads(session["selection"]), **selection})}

    async def throw(self, session, rolls=(0,), **kwargs):
        try:
            service = importlib.import_module("pokewalker.services.catching")
        except ModuleNotFoundError:
            self.fail("M1.8 atomic throw service is absent")
        rng = Mock()
        rng.random.side_effect = rolls
        selection = json.loads(session["selection"])
        result = await self.writer.run(lambda conn: service.throw(
            conn, selection["encounter_id"], session, selection["encounter_revision"], rng, 1000,
            content=self.bot.content, **kwargs))
        return result, rng

    async def snapshot(self):
        return {table: await self.rows(f"SELECT * FROM {table}") for table in
                ("encounters", "catch_attempts", "pokemon", "inventory", "candy", "pokedex",
                 "profiles", "resource_ledger", "action_receipts", "sessions")}

    async def test_throw_consumes_one_ball_and_at_most_one_berry(self):
        session = self.choose(await self.prepared(), berry="razz_berry")
        result, _ = await self.throw(session, (0.99, 0.99))
        self.assertEqual(result.status, "revealed")
        bag = {r["item_id"]: r["quantity"] for r in await self.rows("SELECT * FROM inventory")}
        self.assertEqual((bag["poke_ball"], bag["razz_berry"]), (29, 4))
        self.assertIsNone(json.loads(session["selection"])["berry"])
        attempt = (await self.rows("SELECT * FROM catch_attempts"))[0]
        self.assertEqual((attempt["ordinal"], attempt["ball"], attempt["berry"]), (0, "poke_ball", "razz_berry"))
        self.assertEqual((await self.encounter_row())["revision"], 1)
        self.assertEqual([(r["resource_id"], r["delta"]) for r in await self.rows(
            "SELECT * FROM resource_ledger WHERE reason='catch_spend'")], [("poke_ball", -1), ("razz_berry", -1)])

    async def test_throw_without_ball_refused_no_spend(self):
        session = await self.prepared()
        await self.inventory(poke_ball=0)
        before = await self.snapshot()
        result, rng = await self.throw(session, ())
        self.assertEqual(result.status, "no_ball")
        self.assertEqual(await self.snapshot(), before)
        rng.random.assert_not_called()

    async def test_missing_berry_refused_and_bad_selection_rejected_without_spend(self):
        session = await self.prepared()
        for berry in ("pinap_berry", "unknown"):
            before = await self.snapshot()
            if berry == "unknown":
                with self.assertRaisesRegex(ValueError, "selection"):
                    await self.throw(self.choose(session, berry=berry), ())
            else:
                result, _ = await self.throw(self.choose(session, berry=berry), ())
                self.assertEqual(result.status, "no_berry")
            self.assertEqual(await self.snapshot(), before)

    async def test_storage_full_spends_nothing(self):
        session = await self.prepared()
        await self.writer.run(lambda conn: conn.executemany(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,source_encounter_id,favorite,state,content_version,revision,caught_at) "
            "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
            "gender,shiny,'starter',NULL,0,'owned',content_version,0,0 FROM pokemon LIMIT 1",
            [(f"full-{i}",) for i in range(249)]))
        before = await self.snapshot()
        result, rng = await self.throw(session, ())
        self.assertEqual(result.status, "storage_full")
        self.assertEqual(await self.snapshot(), before)
        rng.random.assert_not_called()

    async def test_confirmed_throw_at_limit_catches_pending(self):
        session = await self.prepared()
        await self.writer.run(lambda conn: conn.executemany(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,content_version,caught_at) "
            "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
            "gender,shiny,'starter',content_version,0 FROM pokemon LIMIT 1",
            [(f"full-{i}",) for i in range(249)]))
        before = await self.snapshot()
        result, rng = await self.throw(session, ())
        self.assertEqual(result.status, "storage_full")
        rng.random.assert_not_called()
        self.assertEqual(await self.snapshot(), before)
        session = self.choose(session, storage_confirm=json.loads(session["selection"])["encounter_revision"])
        result, _ = await self.throw(session)
        self.assertEqual(result.status, "caught")
        self.assertIsNone(result.pokemon)
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE origin='catch'"), [])
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE state='owned'")), 250)
        before = await self.snapshot()
        replay, rng = await self.throw(session, ())
        self.assertEqual(replay, result)
        rng.random.assert_not_called()
        self.assertEqual(await self.snapshot(), before)

    async def test_throw_refused_when_excluded_after_screen_opened_no_spend(self):
        session = await self.prepared()
        await self.exclude()
        before = await self.snapshot()
        result, _ = await self.throw(session, ())
        self.assertEqual(result.status, "excluded")
        self.assertEqual(await self.snapshot(), before)

    async def test_success_commits_pending_rewards_pokedex_together(self):
        session = await self.prepared()
        result, rng = await self.throw(session)
        self.assertEqual((result.status, result.candy, result.stardust), ("caught", 5, 300))
        rng.random.assert_called_once()
        encounter = await self.encounter_row()
        self.assertEqual(encounter["state"], "caught")
        self.assertIsNone(result.pokemon)
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE origin='catch'"), [])
        self.assertEqual((await self.rows("SELECT * FROM pokedex WHERE pokemon_id=25"))[0]["caught_at"], 1000)
        self.assertEqual((await self.rows("SELECT stardust FROM profiles"))[0]["stardust"], 300)
        self.assertEqual((await self.rows("SELECT * FROM candy"))[0]["quantity"], 5)
        attempt = (await self.rows("SELECT * FROM catch_attempts"))[0]
        self.assertTrue(attempt["receipt_key"])
        self.assertEqual(len(await self.rows("SELECT * FROM resource_ledger WHERE reason='catch_reward'")), 2)
        with self.assertRaises((AttributeError, TypeError)):
            result.status = "ran"
        with self.assertRaises(TypeError):
            result.encounter["state"] = "ran"

    async def test_catch_leaves_pending_without_pokemon_row_until_done(self):
        session = await self.prepared()
        owned = await self.rows("SELECT * FROM pokemon WHERE state='owned'")
        result, _ = await self.throw(session)
        self.assertIsNone(result.pokemon)
        self.assertEqual(result.encounter["state"], "caught")
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE origin='catch'"), [])
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE state='owned'"), owned)
        self.assertEqual((await self.rows("SELECT caught_at FROM pokedex WHERE pokemon_id=25"))[0]["caught_at"], 1000)
        self.assertEqual((result.candy, result.stardust), (5, 300))
        self.assertEqual((await self.rows("SELECT quantity FROM candy"))[0]["quantity"], 5)
        self.assertEqual((await self.rows("SELECT stardust FROM profiles"))[0]["stardust"], 300)
        before = await self.snapshot()
        replay, rng = await self.throw(session, ())
        self.assertEqual(replay, result)
        rng.random.assert_not_called()
        self.assertEqual(await self.snapshot(), before)
        _, recovered = await self.open()
        await self.click(recovered, "ack")
        caught = await self.rows("SELECT * FROM pokemon WHERE origin='catch'")
        self.assertEqual(len(caught), 1)
        for key in ("pokemon_id", "level_x2", "iv_attack", "iv_defense", "iv_stamina", "gender", "shiny", "content_version"):
            self.assertEqual(caught[0][key], result.encounter[key])
        self.assertEqual((caught[0]["source_encounter_id"], caught[0]["favorite"], caught[0]["caught_at"]),
                         (result.encounter["encounter_id"], 0, result.encounter["resolved_at"]))
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE state='owned'")), len(owned) + 1)

    async def test_catch_at_limit_minus_one_stays_pending_not_counted(self):
        session = await self.prepared()
        await self.writer.run(lambda conn: conn.executemany(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,content_version,caught_at) "
            "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
            "gender,shiny,'starter',content_version,0 FROM pokemon LIMIT 1",
            [(f"fill-{i}",) for i in range(248)]))
        result, _ = await self.throw(session)
        self.assertIsNone(result.pokemon)
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE state='owned'")), 249)
        _, recovered = await self.open()
        await self.click(recovered, "ack")
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE state='owned'")), 250)

    async def test_receipt_failure_rolls_back_spend_capture_and_rewards(self):
        session = await self.prepared()
        await self.writer.run(lambda conn: conn.execute(
            "CREATE TRIGGER fail_catch BEFORE INSERT ON resource_ledger WHEN NEW.reason='catch_reward' "
            "BEGIN SELECT RAISE(ABORT,'ledger unavailable'); END"))
        before = await self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "ledger unavailable"):
            await self.throw(session)
        self.assertEqual(await self.snapshot(), before)

    async def test_failure_flee_rules_shiny_and_legendary_never(self):
        for changes, expected, rolls in (({}, "fled", (0.99, 0)), ({"shiny": 1}, "revealed", (0.99,)),
                                         ({"tier": "Legendary/Mythical"}, "revealed", (0.99,))):
            with self.subTest(changes=changes):
                session = await self.prepared(**changes)
                result, rng = await self.throw(session, rolls)
                self.assertEqual(result.status, expected)
                self.assertEqual(rng.random.call_count, len(rolls))
                await self.writer.run(lambda conn: conn.execute("DELETE FROM guilds"))
                await self.writer.run(lambda conn: conn.execute("DELETE FROM action_receipts"))

    async def test_attempt_unique_per_encounter_ordinal(self):
        session = await self.prepared()
        result, _ = await self.throw(dict(session), (0.99, 0.99))
        before = await self.snapshot()
        replay, rng = await self.throw(session, ())
        self.assertEqual(replay.status, result.status)
        self.assertEqual(await self.snapshot(), before)
        rng.random.assert_not_called()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.writer.run(lambda conn: conn.execute("INSERT INTO catch_attempts SELECT * FROM catch_attempts"))

    async def test_double_throw_returns_saved_result(self):
        session = await self.prepared()
        first, _ = await self.throw(dict(session))
        before = await self.snapshot()
        second, rng = await self.throw(session, ())
        self.assertEqual(second, first)
        self.assertEqual(await self.snapshot(), before)
        rng.random.assert_not_called()

    async def test_throw_after_run_on_other_screen_returns_ran_result_no_spend(self):
        session = await self.prepared()
        await self.click(session, "run")
        before = await self.snapshot()
        result, _ = await self.throw(session, ())
        self.assertEqual(result.status, "ran")
        self.assertEqual(await self.snapshot(), before)

    async def test_catch_then_run_and_run_then_catch_both_orders_one_terminal_state(self):
        for order in (("throw", "run"), ("run", "throw")):
            with self.subTest(order=order):
                session = await self.prepared()
                _, second = await self.open()
                _, second = await self.reveal(second)
                self.walker.rng = Mock(random=Mock(return_value=0))
                async def competing_click(panel, action):
                    interaction = self.interaction()
                    # Another queued writer may start after this action commits, before its edit.
                    interaction.edit_original_response.side_effect = None
                    await self.walker.route(interaction, f"pw:v1:{panel['session_id']}:{panel['revision']}:{action}")
                    return interaction
                interactions = await asyncio.gather(competing_click(session, order[0]), competing_click(second, order[1]))
                terminal = "caught" if order[0] == "throw" else "ran"
                self.assertEqual((await self.encounter_row())["state"], terminal)
                for interaction in interactions:
                    self.assertIn(terminal, interaction.edit_original_response.await_args.kwargs["embed"].description.lower())
                if terminal == "caught":
                    self.assertEqual(interactions[0].edit_original_response.await_args.kwargs["embed"].to_dict(),
                                     interactions[1].edit_original_response.await_args.kwargs["embed"].to_dict())
                self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE origin='catch'")), 0)
                await self.writer.run(lambda conn: conn.execute("DELETE FROM guilds"))
                await self.writer.run(lambda conn: conn.execute("DELETE FROM action_receipts"))

    async def test_crash_after_commit_before_edit_recovers_via_walker_reopen(self):
        session = await self.prepared()
        self.walker.rng = Mock(random=Mock(side_effect=(0.99, 0.99)))
        interaction = self.interaction()
        interaction.edit_original_response.side_effect = RuntimeError("HTTP failed")
        with self.assertRaisesRegex(RuntimeError, "HTTP failed"):
            await self.walker.route(interaction, f"pw:v1:{session['session_id']}:{session['revision']}:throw")
        before = await self.encounter_row()
        self.assertEqual((before["state"], before["attempt_ordinal"]), ("revealed", 1))
        _, reopened = await self.open()
        await self.reveal(reopened)
        self.assertEqual(await self.encounter_row(), before)
        self.assertEqual(len(await self.rows("SELECT * FROM catch_attempts")), 1)

    async def test_pinap_doubles_silver_floor_7b_over_3(self):
        for berry, expected in (("pinap_berry", 10), ("silver_pinap_berry", 11)):
            session = self.choose(await self.prepared(), berry=berry)
            await self.inventory(**{berry: 1})
            result, _ = await self.throw(session)
            self.assertEqual(result.candy, expected)
            await self.writer.run(lambda conn: conn.execute("DELETE FROM guilds"))
            await self.writer.run(lambda conn: conn.execute("DELETE FROM action_receipts"))

    async def test_rewards_by_depth_and_legendary(self):
        for predicate, rewards in ((lambda i: i["depth"] == 0, (3, 100)),
                                   (lambda i: i["depth"] == 1, (5, 300)),
                                   (lambda i: i["depth"] == 2, (10, 500)),
                                   (lambda i: i["is_legendary"], (10, 500))):
            identity = next(i for i in self.bot.content["identities"] if predicate(i))
            session = await self.prepared(pokemon_id=identity["pokemon_id"])
            result, _ = await self.throw(session)
            self.assertEqual((result.candy, result.stardust), rewards)
            await self.writer.run(lambda conn: conn.execute("DELETE FROM guilds"))
            await self.writer.run(lambda conn: conn.execute("DELETE FROM action_receipts"))

    async def test_master_ball_requires_confirm_then_guaranteed_no_flee(self):
        session = await self.prepared()
        await self.inventory(master_ball=1)
        await self.click(session, "select_ball", ["master_ball"])
        session = await self.current(session)
        self.walker.rng = Mock(random=Mock(side_effect=AssertionError("Master Ball rolled RNG")))
        before = await self.snapshot()
        result = await self.click(session, "throw")
        rendered = result.edit_original_response.await_args.kwargs
        self.assertIn("Pikachu", rendered["embed"].description)
        self.assertIn("Confirm", rendered["embed"].title)
        self.assertEqual(await self.rows("SELECT * FROM inventory"), before["inventory"])
        await self.click(await self.current(session), "master_confirm")
        self.assertEqual((await self.encounter_row())["state"], "caught")
        controls = result.edit_original_response.await_args.kwargs["view"].children
        self.assertIn("Confirm Master Ball", [item.label for item in controls])
        self.walker.rng.random.assert_not_called()

    async def test_master_ball_consumed_once_on_double_confirm(self):
        session = self.choose(await self.prepared(), ball="master_ball")
        await self.inventory(master_ball=1)
        await self.writer.run(lambda conn: conn.execute("UPDATE sessions SET selection=? WHERE session_id=?",
                                                       (session["selection"], session["session_id"])))
        await self.click(session, "throw")
        session = await self.current(session)
        first, stale = await asyncio.gather(self.click(session, "master_confirm"), self.click(session, "master_confirm"))
        self.assertIn("caught", first.edit_original_response.await_args.kwargs["embed"].description)
        self.assertIn("reopen", stale.followup.send.await_args.args[0].lower())
        self.assertEqual((await self.rows("SELECT * FROM inventory WHERE item_id='master_ball'"))[0]["quantity"], 0)
        self.assertEqual(len(await self.rows("SELECT * FROM catch_attempts")), 1)
        self.assertEqual((await self.rows("SELECT * FROM catch_attempts"))[0]["p"], 1)

    async def test_source_encounter_unique_prevents_dup_pokemon(self):
        session = await self.prepared()
        await self.throw(session)
        await store_legacy(self.writer, self.encounter["encounter_id"], 1000)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.writer.run(lambda conn: conn.execute(
                "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                "iv_stamina,gender,shiny,origin,source_encounter_id,favorite,state,content_version,revision,caught_at) "
                "SELECT 'duplicate',profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
                "gender,shiny,origin,source_encounter_id,favorite,state,content_version,revision,caught_at "
                "FROM pokemon WHERE origin='catch'"))

    async def test_other_owner_and_unconfirmed_master_do_not_spend(self):
        session = await self.prepared()
        before = await self.snapshot()
        with self.assertRaisesRegex(ValueError, "owner"):
            await self.throw({**session, "profile_id": "wrong"}, ())
        self.assertEqual(await self.snapshot(), before)
        await self.click(session, "select_ball", ["master_ball"])
        session = await self.current(session)
        before = await self.snapshot()
        await self.click(session, "master_confirm")
        self.assertEqual(await self.snapshot(), before)

    async def test_success_screen_and_surviving_retry_refresh_selection(self):
        session = await self.prepared()
        await self.click(session, "select_berry", ["razz_berry"])
        session = await self.current(session)
        self.walker.rng = Mock(random=Mock(side_effect=(0.99, 0.99, 0)))
        failed = await self.click(session, "throw")
        self.assertIn("broke free", failed.edit_original_response.await_args.kwargs["embed"].description)
        session = await self.current(session)
        selection = json.loads(session["selection"])
        self.assertEqual((selection["encounter_revision"], selection["berry"]), (1, None))
        caught = await self.click(session, "throw")
        rendered = caught.edit_original_response.await_args.kwargs
        self.assertIn("stars", rendered["embed"].description)
        self.assertIn("+5 Candy", rendered["embed"].description)
        self.assertIn("+300 Stardust", rendered["embed"].description)
        buttons = {button.label: button for button in rendered["view"].children}
        self.assertNotIn("Share", buttons)
        self.assertTrue(buttons["Done"].custom_id.endswith(":ack"))
        self.assertEqual(len(await self.rows("SELECT * FROM catch_attempts")), 2)
