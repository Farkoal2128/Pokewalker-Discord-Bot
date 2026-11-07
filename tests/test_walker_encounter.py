"""M1.7 reveal/run contracts with real writer transactions and fake Discord I/O."""

import copy
import json
import random
import sqlite3
import unittest
from unittest.mock import patch

import test_walker_router as router
from pokewalker.domain.cp import cp


class EncounterTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = router.WalkerTests.asyncSetUp
    interaction = router.WalkerTests.interaction
    rows = router.WalkerTests.rows
    open = router.WalkerTests.open
    click = router.WalkerTests.click
    enroll = router.WalkerTests.enroll
    exclude = router.WalkerTests.exclude

    async def ready(self, **changes):
        self.profile = await self.enroll()
        identity = next(item for item in self.bot.content["identities"] if item["species_id"] == 25)
        changes = {"pokemon_id": identity["pokemon_id"], "created_at": 1, **changes}
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE encounters SET " + ",".join(f"{key}=?" for key in changes), tuple(changes.values())))
        self.encounter = (await self.rows("SELECT * FROM encounters"))[0]
        _, session = await self.open()
        return session

    async def current(self, session):
        return (await self.rows("SELECT * FROM sessions WHERE session_id=?", (session["session_id"],)))[0]

    async def reveal(self, session):
        interaction = await self.click(session, "open_encounter")
        interaction.edit_original_response.assert_awaited_once()
        return interaction, await self.current(session)

    async def encounter_row(self):
        return (await self.rows("SELECT * FROM encounters WHERE encounter_id=?",
                                (self.encounter["encounter_id"],)))[0]

    async def snapshot(self):
        return {table: await self.rows(f"SELECT * FROM {table}") for table in
                ("sessions", "encounters", "action_receipts", "pokedex", "inventory", "pokemon")}

    async def test_open_reveals_oldest_and_marks_seen_not_caught(self):
        session = await self.ready()
        await self.reveal(session)
        row = await self.encounter_row()
        self.assertEqual(row, {**self.encounter, "state": "revealed"})
        dex = (await self.rows("SELECT * FROM pokedex WHERE pokemon_id=25"))[0]
        self.assertEqual((dex["seen_at"], dex["caught_at"]), (1000, None))
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon")), 1)

    async def test_reveal_twice_is_idempotent(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        before = await self.rows("SELECT * FROM pokedex")
        await self.reveal(session)
        self.assertEqual(await self.rows("SELECT * FROM pokedex"), before)
        self.assertEqual(await self.encounter_row(), {**self.encounter, "state": "revealed"})

    async def test_reveal_later_reopen_same_encounter_no_reroll(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        await self.click(session, "later")
        _, session = await self.open()
        with patch.object(self.walker.rng, "random", side_effect=AssertionError("rerolled")):
            await self.reveal(session)
        self.assertEqual(await self.encounter_row(), {**self.encounter, "state": "revealed"})

    async def test_reveal_restart_reopen_same_encounter_no_reroll(self):
        session = await self.ready()
        await self.reveal(session)
        self.walker = self.module.Walker(self.bot, clock=lambda: 1001, rng=random.Random(99))
        self.bot.walker = self.walker
        _, session = await self.open()
        await self.reveal(session)
        self.assertEqual(await self.encounter_row(), {**self.encounter, "state": "revealed"})

    async def test_open_prefers_older_revealed_over_newer_queued(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO encounters(encounter_id,profile_id,source_channel_id,source_message_id,pokemon_id,"
            "level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,tier,route_id,lure_id,state,"
            "attempt_ordinal,revision,content_version,created_at,resolved_at,acknowledged_at) "
            "SELECT 'newer',profile_id,source_channel_id,source_message_id,pokemon_id,"
            "level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,tier,route_id,lure_id,'queued',"
            "attempt_ordinal,revision,content_version,2,NULL,NULL FROM encounters LIMIT 1"))
        await self.reveal(session)
        self.assertEqual((await self.rows("SELECT state FROM encounters WHERE encounter_id='newer'"))[0]["state"],
                         "queued")

    async def test_regional_form_marks_species_seen(self):
        regional = next(item for item in self.bot.content["identities"] if item["kind"] == "regional")
        session = await self.ready(pokemon_id=regional["pokemon_id"])
        interaction, _ = await self.reveal(session)
        ids = [row["pokemon_id"] for row in await self.rows("SELECT * FROM pokedex")]
        self.assertIn(regional["species_id"], ids)
        self.assertNotIn(regional["pokemon_id"], ids)
        embed = interaction.edit_original_response.await_args.kwargs["embed"]
        self.assertIn(regional["name_en"], embed.description)
        key = "female" if self.encounter["gender"] == "female" and regional["has_gender_differences"] else "normal"
        if self.encounter["shiny"]:
            key = "shiny_female" if key == "female" else "shiny"
        self.assertEqual(embed.image.url, regional["sprites"][key])

    async def test_reveal_preserves_existing_caught_entry(self):
        session = await self.ready(pokemon_id=1)
        dex = await self.rows("SELECT * FROM pokedex")
        await self.reveal(session)
        self.assertEqual(await self.rows("SELECT * FROM pokedex"), dex)

    async def test_catch_screen_hides_level_shows_cp_shiny_text(self):
        session = await self.ready(shiny=1, gender="female")
        interaction, session = await self.reveal(session)
        rendered = interaction.edit_original_response.await_args.kwargs
        text = rendered["embed"].title + rendered["embed"].description
        self.assertIn("CP ", text)
        self.assertIn("Shiny", text)
        self.assertIn("♀", text)
        self.assertIn("Electric", text)
        self.assertNotIn("level", text.lower())
        self.assertEqual([item.label for item in rendered["view"].children],
                         ["Ball", "Berry", "Throw", "Later", "Run"])
        selection = json.loads(session["selection"])
        self.assertEqual(selection["encounter_revision"], self.encounter["revision"])
        await self.writer.run(lambda conn: conn.execute("UPDATE inventory SET quantity=0"))
        interaction, _ = await self.reveal(session)
        self.assertTrue(interaction.edit_original_response.await_args.kwargs["view"].children[2].disabled)

    async def test_embed_image_exact_sprite_or_none(self):
        identity = next(item for item in self.bot.content["identities"] if item["species_id"] == 25)
        session = await self.ready(shiny=1, gender="female")
        interaction, session = await self.reveal(session)
        self.assertEqual(interaction.edit_original_response.await_args.kwargs["embed"].image.url,
                         identity["sprites"]["shiny_female"])
        identity["sprites"]["shiny_female"] = None
        interaction, _ = await self.reveal(session)
        self.assertIsNone(interaction.edit_original_response.await_args.kwargs["embed"].image.url)

    async def test_female_variety_renders_own_stats_and_sprite(self):
        male = next(item for item in self.bot.content["identities"] if item.get("gender_varieties"))
        female = male["gender_varieties"]["female"]
        session = await self.ready(pokemon_id=female["pokemon_id"], gender="female", shiny=1)
        interaction, _ = await self.reveal(session)
        embed = interaction.edit_original_response.await_args.kwargs["embed"]
        expected = cp([female[key] for key in ("base_attack", "base_defense", "base_stamina")],
                      [self.encounter[key] for key in ("iv_attack", "iv_defense", "iv_stamina")],
                      self.encounter["level_x2"], multipliers=self.walker.multipliers)
        self.assertIn(f"CP {expected}", embed.description)
        self.assertEqual(embed.image.url, female["sprites"]["shiny_female"])

    async def test_select_ball_berry_no_spend(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        inventory = await self.rows("SELECT * FROM inventory")
        encounter = await self.encounter_row()
        for action, value in (("pick_ball", "great_ball"), ("pick_berry", "razz_berry")):
            await self.click(session, action, [value])
            session = await self.current(session)
        self.assertEqual(json.loads(session["selection"])["ball"], "great_ball")
        self.assertEqual(json.loads(session["selection"])["berry"], "razz_berry")
        self.assertEqual(await self.rows("SELECT * FROM inventory"), inventory)
        self.assertEqual(await self.encounter_row(), encounter)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts")), 1)

    async def test_ball_berry_buttons_open_submenus_and_clear_berry(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        for action, expected in (("select_ball", ["poke_ball"]), ("select_berry", ["none", "razz_berry"])):
            interaction = await self.click(session, action)
            view = interaction.edit_original_response.await_args.kwargs["view"]
            self.assertEqual([option.value for option in view.children[-1].options], expected)
            session = await self.current(session)
            picker_action = view.children[-1].custom_id.rsplit(":", 1)[-1]
            self.assertEqual(picker_action, action.replace("select_", "pick_"))
            await self.click(session, picker_action, [expected[0]])
            session = await self.current(session)
        for value in ("razz_berry", "none"):
            await self.click(session, "pick_berry", [value])
            session = await self.current(session)
        self.assertIsNone(json.loads(session["selection"])["berry"])

    async def test_run_receipt_failure_rolls_back_resolution(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        before = await self.snapshot()
        await self.writer.run(lambda conn: conn.execute(
            "CREATE TRIGGER fail_run_receipt BEFORE INSERT ON action_receipts "
            "WHEN NEW.action='run' BEGIN SELECT RAISE(ABORT,'receipt unavailable'); END"))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "receipt unavailable"):
            await self.click(session, "run")
        self.assertEqual(await self.snapshot(), before)

    async def test_later_keeps_encounter_unchanged(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        before = await self.encounter_row()
        interaction = await self.click(session, "later")
        self.assertEqual(interaction.edit_original_response.await_args.kwargs["embed"].title, "Walker")
        self.assertEqual(await self.encounter_row(), before)

    async def test_run_shiny_requires_confirm(self):
        session = await self.ready(shiny=1)
        _, session = await self.reveal(session)
        interaction = await self.click(session, "run")
        self.assertEqual((await self.encounter_row())["state"], "revealed")
        text = interaction.edit_original_response.await_args.kwargs["embed"].description
        self.assertIn("Pikachu", text)
        self.assertIn("Shiny", text)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts")), 1)
        await self.click(await self.current(session), "run_confirm")
        self.assertEqual((await self.encounter_row())["state"], "ran")

    async def test_run_resolves_and_keeps_pokedex_seen(self):
        session = await self.ready(tier="legendary")
        _, session = await self.reveal(session)
        dex = await self.rows("SELECT * FROM pokedex")
        interaction = await self.click(session, "run")
        row = await self.encounter_row()
        self.assertEqual((row["state"], row["revision"], row["resolved_at"]), ("ran", 1, 1000))
        self.assertEqual(await self.rows("SELECT * FROM pokedex"), dex)
        self.assertEqual(await self.rows("SELECT * FROM encounters WHERE state IN ('queued','revealed')"), [])
        self.assertIn("ran", interaction.edit_original_response.await_args.kwargs["embed"].description.lower())
        receipt = (await self.rows("SELECT * FROM action_receipts WHERE action='run'"))[0]
        self.assertEqual(receipt["key"], f"run:{row['encounter_id']}:0")

    async def test_double_run_returns_saved_result(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        _, second = await self.open()
        _, second = await self.reveal(second)
        first = await self.click(session, "run")
        before = await self.encounter_row()
        snapshot, writes = await self.snapshot(), self.conn.total_changes
        result = await self.click(second, "run")
        self.assertEqual(await self.snapshot(), snapshot)
        self.assertEqual(self.conn.total_changes, writes)
        self.assertEqual(result.edit_original_response.await_args.kwargs["embed"].to_dict(),
                         first.edit_original_response.await_args.kwargs["embed"].to_dict())
        self.assertEqual(await self.encounter_row(), before)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='run'")), 1)

    async def test_run_after_catch_on_other_screen_returns_caught_result_no_overwrite(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        async def caught(conn):
            await conn.execute("UPDATE encounters SET state='caught',revision=revision+1,resolved_at=999")
            await conn.execute("INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                               "iv_stamina,gender,shiny,origin,source_encounter_id,favorite,state,content_version,revision,caught_at) "
                               "SELECT 'caught',profile_id,pokemon_id,level_x2,iv_attack,"
                               "iv_defense,iv_stamina,gender,shiny,'catch',encounter_id,0,'owned',"
                               "content_version,0,999 FROM encounters")
        await self.writer.run(caught)
        before = await self.encounter_row()
        snapshot, writes = await self.snapshot(), self.conn.total_changes
        interaction = await self.click(session, "run")
        self.assertEqual(await self.snapshot(), snapshot)
        self.assertEqual(self.conn.total_changes, writes)
        self.assertEqual(await self.encounter_row(), before)
        self.assertIn("caught", interaction.edit_original_response.await_args.kwargs["embed"].description.lower())
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts")), 1)
        state = await self.writer.run(lambda conn: self.walker.encounter_state(conn, session, before["encounter_id"]))
        self.assertEqual(state["pokemon"]["pokemon_uid"], "caught")

    async def test_run_with_stale_encounter_revision_refused(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        await self.writer.run(lambda conn: conn.execute("UPDATE encounters SET revision=revision+1"))
        before = await self.encounter_row()
        snapshot, writes = await self.snapshot(), self.conn.total_changes
        interaction = await self.click(session, "run")
        self.assertEqual(await self.snapshot(), snapshot)
        self.assertEqual(self.conn.total_changes, writes)
        for control in interaction.edit_original_response.await_args.kwargs["view"].children:
            self.assertIn(f":{session['revision']}:", control.custom_id)
        self.assertEqual(await self.encounter_row(), before)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts")), 1)

    async def test_run_refused_when_excluded(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        await self.exclude()
        before = await self.encounter_row()
        interaction = await self.click(session, "run")
        self.assertIn("excluded", interaction.followup.send.await_args.args[0].lower())
        self.assertEqual(await self.encounter_row(), before)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts")), 1)
        # The action itself also enforces exclusion inside its writer transaction.
        with self.assertRaisesRegex(ValueError, "excluded"):
            await self.writer.run(lambda conn: self.walker.run(conn, session, self.interaction()))
        self.assertEqual(await self.encounter_row(), before)

    async def test_other_user_cannot_run(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        snapshot, writes = await self.snapshot(), self.conn.total_changes
        interaction = await self.click(session, "run", user=999)
        self.assertEqual(await self.snapshot(), snapshot)
        self.assertEqual(self.conn.total_changes, writes)
        self.assertIn("not yours", interaction.followup.send.await_args.args[0])
        self.assertEqual((await self.encounter_row())["state"], "revealed")

    async def test_invalid_selection_and_unconfirmed_shiny_run_do_not_mutate(self):
        session = await self.ready(shiny=1)
        _, session = await self.reveal(session)
        before = copy.deepcopy(session)
        for action, values in (("pick_ball", ["unknown"]), ("pick_berry", ["unknown"]),
                               ("run_confirm", [])):
            await self.click(session, action, values)
            self.assertEqual(await self.current(session), before)
        self.assertEqual((await self.encounter_row())["state"], "revealed")
