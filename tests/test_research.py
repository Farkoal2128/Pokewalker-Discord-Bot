"""Research protections, atomic receipts and private multi-page interactions."""

import importlib
import json
import sqlite3
import unittest
from unittest.mock import AsyncMock, patch

import test_storage as storage_tests


class ResearchTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = storage_tests.StorageTests.asyncSetUp
    interaction = storage_tests.StorageTests.interaction
    rows = storage_tests.StorageTests.rows
    open = storage_tests.StorageTests.open
    click = storage_tests.StorageTests.click
    enroll = storage_tests.StorageTests.enroll
    exclude = storage_tests.StorageTests.exclude
    ready = storage_tests.StorageTests.ready
    current = storage_tests.StorageTests.current
    prepared = storage_tests.StorageTests.prepared
    storage = storage_tests.StorageTests.storage
    details = storage_tests.StorageTests.details
    buttons = storage_tests.StorageTests.buttons

    def service(self):
        return importlib.import_module("pokewalker.services.research")

    async def setup_research(self, count=8):
        session = await self.prepared(count)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET favorite=0"))
        return session

    async def act(self, session, action):
        interaction = await self.click(session, action)
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs, await self.current(session)

    async def review(self, count=8, picks=2):
        session = await self.setup_research(count)
        _, session = await self.act(session, "research")
        for letter in "abcde"[:picks]:
            _, session = await self.act(session, "research_toggle_" + letter)
        return await self.act(session, "research_review")

    async def direct_send(self, session, *, now=1000, picks=None, preview=None):
        saved = json.loads(session["selection"])
        return await self.writer.run(lambda conn: self.service().send(
            conn, session, picks if picks is not None else saved["picks"],
            preview if preview is not None else saved["preview"], now, self.bot.content))

    async def balances(self):
        return {table: await self.rows(f"SELECT * FROM {table}") for table in
                ("pokemon", "candy", "profiles", "pokedex", "action_receipts", "resource_ledger",
                 "gyms", "gym_deployments", "gym_battles", "inbox_items", "inventory")}

    async def deploy(self, session, uid="p-001"):
        gyms = importlib.import_module("pokewalker.services.gyms")
        gym = await self.writer.run(lambda conn: gyms.create(conn, session["guild_id"], "Park", 900))
        pokemon = (await self.rows("SELECT * FROM pokemon WHERE pokemon_uid=?", (uid,)))[0]
        result = await self.writer.run(lambda conn: gyms.deploy(
            conn, session, gym["gym_id"], uid, pokemon["revision"], 1000, self.bot.content))
        self.assertEqual(result["status"], "deployed")
        return result["deployment"]

    async def test_protected_reason_deployed_first(self):
        reason = self.service().protected_reason
        identity = {"is_legendary": True, "is_mythical": True}
        pokemon = {"pokemon_uid": "x", "favorite": True, "shiny": True, "gym_deployment_id": "gym"}
        self.assertEqual(reason(identity, pokemon, {"companion_uid": "x"}), "deployed")
        self.assertEqual(reason(identity, {**pokemon, "gym_deployment_id": None},
                                {"companion_uid": "x"}), "favorite")

    async def test_research_send_with_deployed_pick_returns_changed_no_change(self):
        session = await self.setup_research(3)
        await self.deploy(session)
        before, writes = await self.balances(), self.conn.total_changes
        for picks, single in (([["p-002", 0], ["p-001", 1]], False), ([["p-001", 1]], True)):
            with self.subTest(single=single):
                preview = {"id": "deployed", "expires_at": 1120, "unlocked": True}
                saved = {"picks": picks, "single": single, "preview": preview}
                candidate = {**session, "selection": json.dumps(saved)}
                self.assertEqual(await self.direct_send(candidate), {"status": "changed"})
                self.assertEqual((await self.balances(), self.conn.total_changes), (before, writes))

    async def test_single_send_deployed_refused_not_unlockable(self):
        session = await self.setup_research(2)
        await self.deploy(session)
        for favorite, shiny in ((0, 0), (0, 1), (1, 0), (1, 1)):
            with self.subTest(favorite=favorite, shiny=shiny):
                await self.writer.run(lambda conn: conn.execute(
                    "UPDATE pokemon SET favorite=?,shiny=? WHERE pokemon_uid='p-001'", (favorite, shiny)))
                _, session = await self.details(await self.current(session), "p-001")
                before, sessions, writes = await self.balances(), await self.rows(), self.conn.total_changes
                interaction = await self.click(session, "storage_send")
                interaction.edit_original_response.assert_not_awaited()
                self.assertIn("Recall it from the gym first", interaction.followup.send.await_args.args[0])
                self.assertEqual((await self.balances(), await self.rows(), self.conn.total_changes),
                                 (before, sessions, writes))

    async def test_candidate_list_labels_deployed(self):
        session = await self.setup_research(2)
        await self.deploy(session)
        rendered, session = await self.act(session, "research")
        self.assertIn("deployed at a gym", rendered["embed"].description)
        self.assertTrue(rendered["view"].children[0].disabled)
        before, sessions, writes = await self.balances(), await self.rows(), self.conn.total_changes
        interaction = await self.click(session, "research_toggle_a")
        interaction.edit_original_response.assert_not_awaited()
        self.assertEqual((await self.balances(), await self.rows(), self.conn.total_changes),
                         (before, sessions, writes))

    async def test_deployment_after_selection_blocks_review_and_unlock(self):
        session = await self.setup_research(2)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET shiny=1 WHERE pokemon_uid='p-001'"))
        _, session = await self.details(session, "p-001")
        _, session = await self.act(session, "storage_send")
        await self.deploy(session)
        before = await self.balances()
        rendered, _ = await self.act(session, "storage_send_unlock")
        self.assertIn("new review", rendered["embed"].description)
        self.assertNotIn("Send 1 Pokémon", self.buttons(rendered))
        self.assertEqual(await self.balances(), before)

    async def test_recalled_pokemon_sendable_again(self):
        session = await self.setup_research(2)
        deployment = await self.deploy(session)
        gyms = importlib.import_module("pokewalker.services.gyms")
        result = await self.writer.run(lambda conn: gyms.end_deployment(
            conn, session["guild_id"], deployment["deployment_id"], "recalled", 1001,
            self.walker.rng, self.bot.content))
        self.assertEqual(result["status"], "ended")
        rendered, session = await self.act(session, "research")
        self.assertNotIn("deployed at a gym", rendered["embed"].description)
        self.assertFalse(rendered["view"].children[0].disabled)
        _, session = await self.act(session, "research_toggle_a")
        _, session = await self.act(session, "research_review")
        rendered, _ = await self.act(session, "research_confirm")
        self.assertIn("Sent 1", rendered["embed"].description)
        pokemon = (await self.rows("SELECT * FROM pokemon WHERE pokemon_uid='p-001'"))[0]
        self.assertEqual((pokemon["state"], pokemon["gym_deployment_id"], pokemon["revision"]), ("sent", None, 3))
        self.assertEqual(sum(row["quantity"] for row in await self.rows("SELECT * FROM candy")), 1)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='research'")), 1)

    async def test_trigger_still_aborts_direct_state_update(self):
        session = await self.setup_research(2)
        await self.deploy(session)
        before = await self.balances()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "deployed"):
            await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET state='sent' WHERE pokemon_uid='p-001'"))
        self.assertEqual(await self.balances(), before)

    async def test_navigate_walker_storage_research_two_pages_review_send(self):
        session = await self.setup_research()
        rendered, session = await self.storage(session)
        self.assertIn("Send for research", self.buttons(rendered))
        self.assertFalse(self.buttons(rendered)["Send for research"].disabled)
        rendered, session = await self.act(session, "research")
        self.assertIn("5", rendered["embed"].description)
        _, session = await self.act(session, "research_toggle_a")
        _, session = await self.act(session, "research_page")
        _, session = await self.act(session, "research_toggle_a")
        self.assertEqual(len(json.loads(session["selection"])["picks"]), 2)
        _, session = await self.act(session, "research_review")
        rendered, _ = await self.act(session, "research_confirm")
        self.assertIn("Sent 2", rendered["embed"].description)

    async def test_protected_reason_covers_favorite_companion_shiny_legendary_mythical(self):
        await self.setup_research()
        reason = self.service().protected_reason
        identity = {"is_legendary": False, "is_mythical": False}
        pokemon = {"pokemon_uid": "x", "favorite": False, "shiny": False}
        profile = {"companion_uid": "other"}
        self.assertIsNone(reason(identity, pokemon, profile))
        for key, value, expected in (("favorite", True, "favorite"), ("shiny", True, "shiny")):
            self.assertEqual(reason(identity, {**pokemon, key: value}, profile), expected)
        self.assertEqual(reason(identity, pokemon, {"companion_uid": "x"}), "companion")
        for key in ("is_legendary", "is_mythical"):
            self.assertEqual(reason({**identity, key: True}, pokemon, profile), "legendary_or_mythical")

    async def test_non_shiny_mythical_excluded_from_bulk_needs_unlock_single(self):
        session = await self.setup_research(2)
        mythical = next(i for i in self.bot.content["identities"] if i["species_id"] == 151)
        self.assertFalse(mythical["is_legendary"])
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid='p-001'", (mythical["pokemon_id"],)))
        rendered, session = await self.act(session, "research")
        self.assertTrue(rendered["view"].children[0].disabled)
        self.assertIn("legendary_or_mythical", rendered["embed"].description)
        _, session = await self.details(session, "p-001")
        rendered, session = await self.act(session, "storage_send")
        self.assertIn("Mythical", rendered["embed"].description)
        self.assertIn("Unlock", self.buttons(rendered))
        before = await self.balances()
        await self.act(session, "storage_send_confirm")
        self.assertEqual(await self.balances(), before)
        _, session = await self.act(await self.current(session), "storage_send_unlock")
        _, session = await self.act(session, "storage_send_confirm")
        self.assertEqual((await self.rows("SELECT state FROM pokemon WHERE pokemon_uid='p-001'"))[0]["state"], "sent")

    async def test_page_size_5_and_batch_cap_20(self):
        session = await self.setup_research(26)
        for page in range(5):
            rendered, session = await self.act(session, "research" if page == 0 else "research_page")
            self.assertEqual(len([b for b in rendered["view"].children if b.row == 0]), 5)
            self.assertLessEqual(len(rendered["view"].children), 25)
            for letter in "abcde":
                _, session = await self.act(session, "research_toggle_" + letter)
        self.assertEqual(len(json.loads(session["selection"])["picks"]), 20)
        _, session = await self.act(session, "research_review")
        saved = json.loads(session["selection"])
        picks = [*saved["picks"], ["p-001", 0]]
        before = await self.balances()
        self.assertEqual((await self.direct_send(session, picks=picks))["status"], "changed")
        self.assertEqual(await self.balances(), before)

    async def test_review_names_picks_and_candy_by_family(self):
        session = await self.setup_research()
        pikachu = next(i for i in self.bot.content["identities"] if i["species_id"] == 25)
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid='p-007'", (pikachu["pokemon_id"],)))
        _, session = await self.act(session, "research")
        for letter in "ab":
            _, session = await self.act(session, "research_toggle_" + letter)
        rendered, session = await self.act(session, "research_review")
        text = rendered["embed"].description
        for expected in ("Pikachu", "Bulbasaur", "p-007", "p-006", "CP", "stars", "irreversible", "Candy", "0 Stardust"):
            self.assertIn(expected, text)
        self.assertIn("Send 2 Pokémon", self.buttons(rendered))
        self.assertEqual(len(json.loads(session["selection"])["preview"]["id"]), 36)
        self.assertIn("+1 Pikachu Candy", text)
        self.assertIn("+1 Bulbasaur Candy", text)

    async def test_confirm_sends_all_one_candy_each_zero_stardust_keeps_pokedex(self):
        _, session = await self.review()
        before = await self.balances()
        rendered, _ = await self.act(session, "research_confirm")
        after = await self.balances()
        self.assertEqual(after["pokedex"], before["pokedex"])
        self.assertEqual(after["profiles"], before["profiles"])
        self.assertEqual(sum(r["quantity"] for r in after["candy"]), 2)
        sent = [r for r in after["pokemon"] if r["state"] == "sent"]
        self.assertEqual(len(sent), 2)
        self.assertTrue(all(r["revision"] == 1 for r in sent))
        lines = [r for r in after["resource_ledger"] if r["reason"] == "research_send"]
        self.assertEqual([(r["resource"], r["delta"]) for r in lines], [("candy", 1)] * 2)
        self.assertIn("0 Stardust", rendered["embed"].description)

    async def test_confirm_names_candy_for_each_family(self):
        session = await self.setup_research()
        pidgey = next(i for i in self.bot.content["identities"] if i["species_id"] == 16)
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid='p-007'", (pidgey["pokemon_id"],)))
        _, session = await self.act(session, "research")
        for letter in "abc":
            _, session = await self.act(session, "research_toggle_" + letter)
        review, session = await self.act(session, "research_review")
        self.assertIn("+2 Bulbasaur Candy", review["embed"].description)
        self.assertIn("+1 Pidgey Candy", review["embed"].description)
        self.assertNotIn("1: +", review["embed"].description)
        rendered, _ = await self.act(session, "research_confirm")
        text = rendered["embed"].description
        self.assertIn("Sent 3 Pokémon", text)
        self.assertIn("+2 Bulbasaur Candy", text)
        self.assertIn("+1 Pidgey Candy", text)
        self.assertIn("0 Stardust", text)
        self.assertNotIn("{", text)
        self.assertNotIn("'", text)

    async def test_candy_family_sort_is_numeric(self):
        from pokewalker.bot import research
        with patch.object(research, "_reward_name", side_effect=lambda row, content: row["resource_id"]):
            self.assertEqual(research._candy_text({"10": 1, "2": 2}, {}), "+2 2, +1 10")

    async def test_confirm_twice_and_restart_before_reply_one_credit(self):
        rendered, session = await self.review()
        original_id = self.buttons(rendered)["Send 2 Pokémon"].custom_id
        interaction = self.interaction()
        interaction.edit_original_response.side_effect = RuntimeError("reply lost")
        with self.assertRaisesRegex(RuntimeError, "reply lost"):
            await self.walker.route(interaction, original_id)
        before, sessions, writes = await self.balances(), await self.rows(), self.conn.total_changes
        self.walker = self.module.Walker(self.bot, clock=lambda: 1001)
        self.bot.walker = self.walker
        for _ in range(2):
            retry = self.interaction()
            with patch.dict(self.walker.handlers, research_confirm=AsyncMock(side_effect=AssertionError("stale handler called"))):
                await self.walker.route(retry, original_id)
            retry.edit_original_response.assert_not_awaited()
            retry.followup.send.assert_not_awaited()
            self.assertEqual((await self.balances(), await self.rows(), self.conn.total_changes), (before, sessions, writes))
        self.assertEqual((await self.direct_send(session, now=9999))["status"], "sent")
        self.assertEqual(await self.balances(), before)
        _, reopened = await self.open()
        rendered, _ = await self.storage(reopened)
        self.assertIn("6/250", rendered["embed"].description)
        for uid, _ in json.loads(session["selection"])["picks"]:
            self.assertIsNone(await storage_tests.StorageTests.service(self).detail(self.conn, self.profile["profile_id"], uid))
        self.assertEqual(sum(row["quantity"] for row in await self.rows("SELECT * FROM candy")), 2)

    async def test_rendered_toggle_stays_bound_to_uid_after_concurrent_reorder(self):
        session = await self.setup_research()
        rendered, session = await self.act(session, "research")
        original_id = rendered["view"].children[0].custom_id
        self.assertIn("p-007", rendered["embed"].description)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET caught_at=99 WHERE pokemon_uid='p-001'"))
        interaction = self.interaction()
        await self.walker.route(interaction, original_id)
        interaction.edit_original_response.assert_awaited_once()
        self.assertEqual(json.loads((await self.current(session))["selection"])["picks"], [["p-007", 0]])

    async def test_rendered_toggle_removed_or_revised_is_refused(self):
        session = await self.setup_research()
        rendered, session = await self.act(session, "research")
        original_id = rendered["view"].children[0].custom_id
        for change in ("state='sent'", "revision=revision+1"):
            await self.writer.run(lambda conn: conn.execute(f"UPDATE pokemon SET {change} WHERE pokemon_uid='p-007'"))
            before, sessions, writes = await self.balances(), await self.rows(), self.conn.total_changes
            interaction = self.interaction()
            await self.walker.route(interaction, original_id)
            interaction.edit_original_response.assert_not_awaited()
            self.assertIn("reopen /walker", interaction.followup.send.await_args.args[0])
            self.assertEqual((await self.balances(), await self.rows(), self.conn.total_changes), (before, sessions, writes))
            await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET state='owned',revision=0 WHERE pokemon_uid='p-007'"))

    async def test_review_refuses_changed_selected_revision(self):
        session = await self.setup_research()
        _, session = await self.act(session, "research")
        _, session = await self.act(session, "research_toggle_a")
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET revision=revision+1 WHERE pokemon_uid='p-007'"))
        before = await self.balances()
        rendered, session = await self.act(session, "research_review")
        self.assertIn("new review", rendered["embed"].description)
        self.assertNotIn("preview", json.loads(session["selection"]))
        self.assertEqual(await self.balances(), before)

    async def test_changed_pick_sends_none_asks_new_review(self):
        _, session = await self.review()
        uid = json.loads(session["selection"])["picks"][0][0]
        for change in ("revision=revision+1", "favorite=1", "shiny=1", "state='sent'"):
            await self.writer.run(lambda conn: conn.execute(f"UPDATE pokemon SET {change} WHERE pokemon_uid=?", (uid,)))
            before = await self.balances()
            rendered, _ = await self.act(session, "research_confirm")
            self.assertIn("new review", rendered["embed"].description)
            self.assertEqual(await self.balances(), before)
            await self.writer.run(lambda conn: conn.execute(
                "UPDATE pokemon SET revision=0,favorite=0,shiny=0,state='owned' WHERE pokemon_uid=?", (uid,)))
            session = await self.current(session)

    async def test_review_expires_after_120s(self):
        _, session = await self.review()
        self.assertEqual(json.loads(session["selection"])["preview"]["expires_at"], 1120)
        before = await self.balances()
        self.assertEqual((await self.direct_send(session, now=1120))["status"], "changed")
        self.assertEqual(await self.balances(), before)

    async def test_companion_never_sendable_even_single(self):
        session = await self.setup_research(1)
        rendered, session = await self.details(session)
        self.assertTrue(self.buttons(rendered)["Send for research"].disabled)
        before = await self.balances()
        await self.click(session, "storage_send")
        preview = {"id": "companion", "expires_at": 1120, "unlocked": True}
        self.assertEqual((await self.direct_send(session, picks=[[self.uid, 0]], preview=preview))["status"], "changed")
        self.assertEqual(await self.balances(), before)

    async def test_shiny_single_send_requires_unlock_then_confirm(self):
        session = await self.setup_research(2)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET shiny=1 WHERE pokemon_uid='p-001'"))
        _, session = await self.details(session, "p-001")
        rendered, session = await self.act(session, "storage_send")
        self.assertIn("Shiny", rendered["embed"].description)
        self.assertIsNotNone(rendered["embed"].image.url)
        before = await self.balances()
        await self.act(session, "storage_send_confirm")
        self.assertEqual(await self.balances(), before)
        _, session = await self.act(await self.current(session), "storage_send_unlock")
        self.assertEqual(await self.balances(), before)
        await self.act(session, "storage_send_confirm")
        self.assertEqual(sum(r["quantity"] for r in await self.rows("SELECT * FROM candy")), 1)

    async def test_sent_pokemon_leave_storage_and_capacity_count(self):
        _, session = await self.review(count=250)
        await self.act(session, "research_confirm")
        rows, total = await storage_tests.StorageTests.service(self).page(self.conn, self.profile["profile_id"], 0)
        self.assertEqual(total, 248)
        self.assertTrue(all(row["state"] == "owned" for row in rows))
        await self.walker.recover_terminal(self.conn, session)
        interaction = await self.click(await self.current(session), "open_encounter")
        session = await self.current(session)
        interaction = await self.click(session, "throw")
        self.assertEqual(len(await self.rows("SELECT * FROM catch_attempts")), 1)

    async def test_receipt_carries_profile_id(self):
        _, session = await self.review()
        await self.direct_send(session)
        receipt = (await self.rows("SELECT * FROM action_receipts WHERE action='research'"))[0]
        self.assertEqual(receipt["profile_id"], self.profile["profile_id"])

    async def test_other_user_and_excluded_refused_inside_transaction(self):
        _, session = await self.review()
        before = await self.balances()
        for override in ({"user_id": "999"}, {"guild_id": "999"}, {"profile_id": "other"}):
            self.assertEqual((await self.direct_send({**session, **override}))["status"], "changed")
            self.assertEqual(await self.balances(), before)
        await self.exclude()
        before = await self.balances()
        self.assertEqual((await self.direct_send(session))["status"], "changed")
        self.assertEqual(await self.balances(), before)

    async def test_cancel_and_forged_toggle_change_no_resources(self):
        _, session = await self.review()
        before = await self.balances()
        await self.act(session, "research_cancel")
        self.assertEqual(await self.balances(), before)
        self.assertEqual(json.loads((await self.current(session))["selection"]), {"offset": 0})

    async def test_duplicate_forged_preview_and_changed_companion_send_none(self):
        _, session = await self.review()
        saved = json.loads(session["selection"])
        before = await self.balances()
        self.assertEqual((await self.direct_send(session, picks=[saved["picks"][0]] * 2))["status"], "changed")
        self.assertEqual((await self.direct_send(session, preview={**saved["preview"], "unlocked": True}))["status"], "changed")
        self.assertEqual(await self.balances(), before)
        await self.writer.run(lambda conn: conn.execute("UPDATE profiles SET companion_uid=?", (saved["picks"][0][0],)))
        before = await self.balances()
        self.assertEqual((await self.direct_send(session))["status"], "changed")
        self.assertEqual(await self.balances(), before)

    async def test_ledger_failure_rolls_back_all_dispositions_and_balances(self):
        _, session = await self.review()
        before = await self.balances()
        execute = self.conn.execute
        def fail_ledger(sql, parameters=()):
            if "INSERT INTO resource_ledger" in sql:
                raise RuntimeError("ledger unavailable")
            return execute(sql, parameters)
        with patch.object(self.conn, "execute", side_effect=fail_ledger):
            with self.assertRaisesRegex(RuntimeError, "ledger unavailable"):
                await self.direct_send(session)
        self.assertEqual(await self.balances(), before)


    async def pending_review(self):
        session = await self.ready()
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE encounters SET state='caught',resolved_at=900,acknowledged_at=NULL,revision=3,shiny=0 "
            "WHERE encounter_id=?", (self.encounter["encounter_id"],)))
        encounter = (await self.rows("SELECT * FROM encounters WHERE encounter_id=?",
                                     (self.encounter["encounter_id"],)))[0]
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE source_encounter_id=?",
                                         (encounter["encounter_id"],)), [])
        picks = [[f"pending:{encounter['encounter_id']}", encounter["revision"]]]
        preview = {"id": "pending-preview", "expires_at": 1120}
        selection = json.dumps({"picks": picks, "single": True, "preview": preview})
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE sessions SET selection=? WHERE session_id=?", (selection, session["session_id"])))
        return {**session, "selection": selection}, encounter, picks, preview

    async def pending_state(self):
        return {**await self.balances(), "encounters": await self.rows("SELECT * FROM encounters"),
                "sessions": await self.rows()}

    async def pending_send(self, session, picks, preview, now=1000):
        return await self.writer.run(lambda conn: self.service().send_pending_reviewed(
            conn, session, picks, preview, now, self.bot.content))

    async def test_send_pending_inserts_sent_row_candy_ledger_receipt_once(self):
        session, encounter, _, _ = await self.pending_review()
        identity, _ = importlib.import_module("pokewalker.services.storage").identify(self.bot.content, encounter)
        family = str(identity["family_id"])
        before = await self.pending_state()
        expected = {"status": "sent", "count": 1, "candy": {family: 1}, "stardust": 0}
        async def send(conn):
            return await self.service().send_pending(
                conn, session["profile_id"], encounter, "research:pending-preview", self.bot.content)
        self.assertEqual(await self.writer.run(send), expected)
        rows = await self.rows("SELECT * FROM pokemon WHERE source_encounter_id=?", (encounter["encounter_id"],))
        self.assertEqual(len(rows), 1)
        pokemon = rows[0]
        self.assertTrue(pokemon["pokemon_uid"])
        self.assertEqual((pokemon["state"], pokemon["revision"], pokemon["caught_at"], pokemon["origin"]),
                         ("sent", 1, encounter["resolved_at"], "catch"))
        for column in ("profile_id", "pokemon_id", "level_x2", "iv_attack", "iv_defense", "iv_stamina",
                       "gender", "shiny", "content_version"):
            self.assertEqual(pokemon[column], encounter[column], column)
        candy_before = sum(row["quantity"] for row in before["candy"]
                           if str(row["family_id"]) == family and row["profile_id"] == session["profile_id"])
        candy_after = await self.rows("SELECT quantity FROM candy WHERE profile_id=? AND family_id=?",
                                      (session["profile_id"], int(family)))
        self.assertEqual(candy_after, [{"quantity": candy_before + 1}])
        lines = await self.rows("SELECT * FROM resource_ledger WHERE receipt_key='research:pending-preview'")
        self.assertEqual(len(lines), 1)
        self.assertEqual({key: lines[0][key] for key in ("profile_id", "resource", "resource_id", "delta", "reason")},
                         {"profile_id": session["profile_id"], "resource": "candy", "resource_id": family,
                          "delta": 1, "reason": "research_send"})
        receipts = await self.rows("SELECT * FROM action_receipts WHERE key='research:pending-preview'")
        self.assertEqual(len(receipts), 1)
        self.assertEqual((receipts[0]["profile_id"], receipts[0]["action"], json.loads(receipts[0]["result"])),
                         (session["profile_id"], "research", expected))
        after = await self.pending_state()
        for table in ("profiles", "pokedex", "encounters", "sessions", "inventory"):
            self.assertEqual(after[table], before[table], table)
        writes = self.conn.total_changes
        self.assertEqual(await self.writer.run(send), expected)
        self.assertEqual((await self.pending_state(), self.conn.total_changes), (after, writes))

    async def test_send_pending_reviewed_guards_match_send(self):
        session, encounter, picks, preview = await self.pending_review()
        changed = {"status": "changed"}
        for overrides in ({"user_id": "999"}, {"guild_id": "999"}, {"profile_id": "foreign"}):
            before, writes = await self.pending_state(), self.conn.total_changes
            self.assertEqual(await self.pending_send({**session, **overrides}, picks, preview), changed)
            self.assertEqual((await self.pending_state(), self.conn.total_changes), (before, writes))
        for selected, shown, bind in (([], preview, True), (picks * 2, preview, True),
                                      ([["pending:missing", 3]], preview, True),
                                      ([[picks[0][0], 4]], preview, True),
                                      ([["stored", 3]], preview, True),
                                      (picks, {**preview, "expires_at": 1000}, True),
                                      ([], preview, False), (picks, {**preview, "id": "forged"}, False),
                                      (picks, None, False)):
            with self.subTest(picks=selected, preview=shown, bind=bind):
                candidate = {**session, "selection": json.dumps({"picks": selected, "preview": shown,
                                                                  "single": True})} if bind else session
                before, writes = await self.pending_state(), self.conn.total_changes
                self.assertEqual(await self.pending_send(candidate, selected, shown), changed)
                self.assertEqual((await self.pending_state(), self.conn.total_changes), (before, writes))
        mythical = next(item for item in self.bot.content["identities"]
                        if item["species_id"] == 151 and item["is_mythical"] and not item["is_legendary"])
        legendary = next(item for item in self.bot.content["identities"] if item["is_legendary"])
        for changes in ({"shiny": 1}, {"pokemon_id": mythical["pokemon_id"]},
                        {"pokemon_id": legendary["pokemon_id"]}, {"state": "revealed"},
                        {"acknowledged_at": 950}, {"profile_id": "foreign"}):
            with self.subTest(changes=changes):
                if changes.get("profile_id") == "foreign":
                    await self.writer.run(lambda conn: conn.execute(
                        "INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('foreign','123','999',0)"))
                await self.writer.run(lambda conn: conn.execute(
                    "UPDATE encounters SET " + ",".join(f"{key}=?" for key in changes) + " WHERE encounter_id=?",
                    (*changes.values(), encounter["encounter_id"])))
                before, writes = await self.pending_state(), self.conn.total_changes
                self.assertEqual(await self.pending_send(session, picks, preview), changed)
                self.assertEqual((await self.pending_state(), self.conn.total_changes), (before, writes))
                await self.writer.run(lambda conn: conn.execute(
                    "UPDATE encounters SET shiny=0,pokemon_id=?,state='caught',acknowledged_at=NULL,profile_id=? "
                    "WHERE encounter_id=?", (encounter["pokemon_id"], session["profile_id"], encounter["encounter_id"])))
        await self.writer.run(lambda conn: self.service().send_pending(
            conn, session["profile_id"], encounter, "research:already-sent", self.bot.content))
        before, writes = await self.pending_state(), self.conn.total_changes
        self.assertEqual(await self.pending_send(session, picks, preview), changed)
        self.assertEqual((await self.pending_state(), self.conn.total_changes), (before, writes))
        await self.exclude()
        before, writes = await self.pending_state(), self.conn.total_changes
        self.assertEqual(await self.pending_send(session, picks, preview), changed)
        self.assertEqual((await self.pending_state(), self.conn.total_changes), (before, writes))

    async def test_send_pending_reviewed_replays_after_expiry_and_restart(self):
        session, encounter, picks, preview = await self.pending_review()
        result = await self.pending_send(session, picks, preview)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE source_encounter_id=?",
                                            (encounter["encounter_id"],))), 1)
        before, writes = await self.pending_state(), self.conn.total_changes
        self.walker = self.module.Walker(self.bot, clock=lambda: 9999)
        self.bot.walker = self.walker
        self.assertEqual(await self.pending_send(session, picks, preview, now=self.walker.clock()), result)
        self.assertEqual((await self.pending_state(), self.conn.total_changes), (before, writes))
        for override in ({"user_id": "999"}, {"profile_id": "foreign"}):
            self.assertEqual(await self.pending_send({**session, **override}, picks, preview, now=9999),
                             {"status": "changed"})
        await self.exclude()
        before, writes = await self.pending_state(), self.conn.total_changes
        self.assertEqual(await self.pending_send(session, picks, preview, now=9999), {"status": "changed"})
        self.assertEqual((await self.pending_state(), self.conn.total_changes), (before, writes))

    async def test_send_pending_requires_writer_transaction(self):
        session, encounter, picks, preview = await self.pending_review()
        before = await self.pending_state()
        with self.assertRaisesRegex(RuntimeError, "writer transaction"):
            await self.service().send_pending(self.conn, session["profile_id"], encounter,
                                               "research:pending-preview", self.bot.content)
        with self.assertRaisesRegex(RuntimeError, "writer transaction"):
            await self.service().send_pending_reviewed(self.conn, session, picks, preview, 1000, self.bot.content)
        self.assertEqual(await self.pending_state(), before)


    async def test_send_pending_reviewed_protected_requires_single_and_unlock(self):
        session, encounter, picks, preview = await self.pending_review()
        mythical = next(item for item in self.bot.content["identities"] if item["species_id"] == 151)
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE encounters SET shiny=1,pokemon_id=? WHERE encounter_id=?",
            (mythical["pokemon_id"], encounter["encounter_id"])))
        for single, unlocked in ((False, True), (True, False), (True, True)):
            shown = {**preview, "unlocked": unlocked}
            candidate = {**session, "selection": json.dumps({"picks": picks, "preview": shown, "single": single})}
            before, writes = await self.pending_state(), self.conn.total_changes
            result = await self.pending_send(candidate, picks, shown)
            if single and unlocked:
                self.assertEqual(result, {"status": "sent", "count": 1,
                                          "candy": {str(mythical["family_id"]): 1}, "stardust": 0})
                self.assertEqual((await self.rows("SELECT state FROM pokemon WHERE source_encounter_id=?",
                                                  (encounter["encounter_id"],)))[0]["state"], "sent")
            else:
                self.assertEqual(result, {"status": "changed"})
                self.assertEqual((await self.pending_state(), self.conn.total_changes), (before, writes))

    async def test_send_pending_reviewed_foreign_receipt_is_not_replayed(self):
        session, _, picks, preview = await self.pending_review()
        async def seed(conn):
            await conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                               "VALUES ('foreign','123','999',0)")
            await conn.execute("INSERT INTO action_receipts(key,action,result,created_at,profile_id) "
                               "VALUES ('research:pending-preview','research',?,0,'foreign')",
                               (json.dumps({"status": "sent", "count": 1, "candy": {}, "stardust": 0}),))
        await self.writer.run(seed)
        before, writes = await self.pending_state(), self.conn.total_changes
        self.assertEqual(await self.pending_send(session, picks, preview, now=9999), {"status": "changed"})
        self.assertEqual((await self.pending_state(), self.conn.total_changes), (before, writes))

    async def test_send_pending_ledger_failure_rolls_back_row_candy_and_receipt(self):
        session, _, picks, preview = await self.pending_review()
        before = await self.pending_state()
        execute = self.conn.execute
        def fail_ledger(sql, parameters=()):
            if "INSERT INTO resource_ledger" in sql:
                raise RuntimeError("ledger unavailable")
            return execute(sql, parameters)
        with patch.object(self.conn, "execute", side_effect=fail_ledger):
            with self.assertRaisesRegex(RuntimeError, "ledger unavailable"):
                await self.pending_send(session, picks, preview)
        self.assertEqual(await self.pending_state(), before)

    async def auto_send(self, now):
        return await self.writer.run(lambda conn: self.service().auto_send(conn, now, self.bot.content))

    async def test_auto_send_sweeps_unconfirmed_catch_after_15_minutes_once(self):
        session, encounter, _, _ = await self.pending_review()
        before = await self.pending_state()
        due = encounter["resolved_at"] + 900
        self.assertEqual(await self.auto_send(due - 1), 0)
        self.assertEqual(await self.pending_state(), before)
        self.assertEqual(await self.auto_send(due), 1)
        rows = await self.rows("SELECT * FROM pokemon WHERE source_encounter_id=?", (encounter["encounter_id"],))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "sent")
        key = f"research:auto:{encounter['encounter_id']}"
        receipt = (await self.rows("SELECT * FROM action_receipts WHERE key=?", (key,)))[0]
        self.assertEqual((receipt["action"], receipt["profile_id"]), ("research", session["profile_id"]))
        family = self.service().storage.identify(self.bot.content, encounter)[0]["family_id"]
        quantity = sum(row["quantity"] for row in before["candy"] if row["family_id"] == family)
        self.assertEqual(await self.rows("SELECT quantity FROM candy WHERE profile_id=? AND family_id=?",
                                         (session["profile_id"], family)), [{"quantity": quantity + 1}])
        self.assertEqual(await self.rows("SELECT delta,reason FROM resource_ledger WHERE receipt_key=?", (key,)),
                         [{"delta": 1, "reason": "research_send"}])
        self.assertEqual((await self.rows("SELECT acknowledged_at FROM encounters WHERE encounter_id=?",
                                          (encounter["encounter_id"],)))[0]["acknowledged_at"], due)
        after = await self.pending_state()
        for table in ("profiles", "pokedex", "sessions", "inventory"):
            self.assertEqual(after[table], before[table], table)
        self.assertEqual(await self.auto_send(due + 60), 0)
        self.assertEqual(await self.pending_state(), after)

    async def test_auto_send_exempts_shiny_legendary_and_mythical_forever(self):
        _, encounter, _, _ = await self.pending_review()
        for species, shiny, flags in ((25, 1, (False, False)), (144, 0, (True, False)),
                                       (151, 0, (False, True))):
            identity = next(item for item in self.bot.content["identities"] if item["species_id"] == species)
            self.assertEqual((identity["is_legendary"], identity["is_mythical"]), flags)
            await self.writer.run(lambda conn: conn.execute(
                "UPDATE encounters SET pokemon_id=?,shiny=? WHERE encounter_id=?",
                (identity["pokemon_id"], shiny, encounter["encounter_id"])))
            before = await self.pending_state()
            for elapsed in (900, 7200, 86400):
                with self.subTest(species=species, elapsed=elapsed):
                    self.assertEqual(await self.auto_send(encounter["resolved_at"] + elapsed), 0)
                    self.assertEqual(await self.pending_state(), before)

    async def test_auto_send_ignores_stored_and_acknowledged_catches(self):
        session, encounter, _, _ = await self.pending_review()
        await self.writer.run(lambda conn: self.service().send_pending(
            conn, session["profile_id"], encounter, "fixture:stored", self.bot.content))
        for state in ("owned", "sent"):
            await self.writer.run(lambda conn: conn.execute(
                "UPDATE pokemon SET state=? WHERE source_encounter_id=?", (state, encounter["encounter_id"])))
            before = await self.pending_state()
            self.assertEqual(await self.auto_send(99999), 0)
            self.assertEqual(await self.pending_state(), before)
        await self.writer.run(lambda conn: conn.execute(
            "DELETE FROM pokemon WHERE source_encounter_id=?", (encounter["encounter_id"],)))
        await self.writer.run(lambda conn: conn.execute("UPDATE encounters SET acknowledged_at=1000"))
        before = await self.pending_state()
        self.assertEqual(await self.auto_send(99999), 0)
        self.assertEqual(await self.pending_state(), before)

    async def test_auto_send_excluded_stays_pending_then_retries(self):
        await self.pending_review()
        await self.exclude()
        before = await self.pending_state()
        self.assertEqual(await self.auto_send(1800), 0)
        self.assertEqual(await self.pending_state(), before)
        await self.writer.run(lambda conn: conn.execute("DELETE FROM restrictions"))
        self.assertEqual(await self.auto_send(1860), 1)
        self.assertEqual(await self.auto_send(1920), 0)
