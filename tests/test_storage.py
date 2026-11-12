"""M2.1 storage contracts with SQLite and synthetic Discord interactions."""

import importlib
import json
import unittest
from unittest.mock import patch

import test_walker_encounter as encounters
from pokewalker.domain.cp import appraisal, cp, hp


class StorageTests(unittest.IsolatedAsyncioTestCase):
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

    async def prepared(self, count=1, **changes):
        session = await self.ready()
        self.uid = self.profile["companion_uid"]
        async def seed(conn):
            await conn.execute("UPDATE pokemon SET caught_at=0")
            await conn.executemany(
                "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                "iv_stamina,gender,shiny,origin,source_encounter_id,favorite,state,content_version,revision,caught_at) "
                "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
                "gender,shiny,origin,NULL,favorite,'owned',content_version,revision,? FROM pokemon WHERE pokemon_uid=?",
                [(f"p-{index:03}", index, self.uid) for index in range(1, count)])
            if changes:
                await conn.execute("UPDATE pokemon SET " + ",".join(f"{key}=?" for key in changes)
                                   + " WHERE pokemon_uid=?", (*changes.values(), self.uid))
        await self.writer.run(seed)
        return session

    async def storage(self, session):
        interaction = await self.click(session, "storage")
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs, await self.current(session)

    async def details(self, session, uid=None):
        _, session = await self.storage(session)
        interaction = await self.click(session, "storage_open", [uid or self.uid])
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs, await self.current(session)

    def buttons(self, rendered):
        return {item.label: item for item in rendered["view"].children if hasattr(item, "label")}

    def service(self):
        return importlib.import_module("pokewalker.services.storage")

    async def deploy(self, session, uid="p-001"):
        from pokewalker.services import gyms
        gym = await self.writer.run(lambda conn: gyms.create(conn, session["guild_id"], "Park", 900))
        pokemon = await self.service().detail(self.conn, session["profile_id"], uid)
        result = await self.writer.run(lambda conn: gyms.deploy(
            conn, session, gym["gym_id"], uid, pokemon["revision"], 1000, self.bot.content))
        self.assertEqual(result["status"], "deployed")
        return result["deployment"]

    async def test_details_shows_gym_name_and_disables_four_buttons(self):
        session = await self.prepared(2)
        await self.deploy(session)
        module = importlib.import_module("pokewalker.bot.storage")
        with patch.object(module, "render_detail", wraps=module.render_detail) as render:
            rendered, _ = await self.details(session, "p-001")
        self.assertIn("Deployed at Park — recall it to send, power up, evolve or set companion",
                      rendered["embed"].description)
        buttons = self.buttons(rendered)
        for label in ("Send for research", "Power up", "Evolve", "Set companion"):
            self.assertTrue(buttons[label].disabled, label)
        for label in ("Unfavorite", "Back"):
            self.assertFalse(buttons[label].disabled, label)
        state = render.call_args.args[0]
        with patch.object(self.conn, "execute", side_effect=AssertionError("database I/O")), \
                patch.object(self.writer, "run", side_effect=AssertionError("writer I/O")), \
                patch("builtins.open", side_effect=AssertionError("file I/O")), \
                patch("socket.socket", side_effect=AssertionError("network I/O")):
            self.assertEqual(module.render_detail(state)["embed"].description,
                             rendered["embed"].description)

    async def test_recalled_pokemon_regains_all_actions(self):
        from pokewalker.services import gyms
        session = await self.prepared(2)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET favorite=0 WHERE pokemon_uid='p-001'"))
        deployment = await self.deploy(session)
        _, session = await self.details(session, "p-001")
        await self.writer.run(lambda conn: gyms.end_deployment(
            conn, session["guild_id"], deployment["deployment_id"], "recalled", 1001,
            self.walker.rng, self.bot.content))
        rendered = (await self.click(session, "storage_detail")).edit_original_response.await_args.kwargs
        self.assertNotIn("Deployed at", rendered["embed"].description)
        for label in ("Send for research", "Power up", "Evolve", "Set companion"):
            self.assertFalse(self.buttons(rendered)[label].disabled, label)
        session = await self.current(session)
        rendered = (await self.click(session, "companion")).edit_original_response.await_args.kwargs
        self.assertIn("Companion", rendered["embed"].description)
        self.assertEqual((await self.rows("SELECT companion_uid FROM profiles"))[0]["companion_uid"], "p-001")

    async def test_details_missing_foreign_and_other_profile_gym_names_are_indistinguishable(self):
        session = await self.prepared(2)
        deployment = await self.deploy(session)
        async def seed(conn):
            await conn.execute("INSERT INTO guilds(guild_id) VALUES ('foreign')")
            for pid, guild in (("foreign-profile", "foreign"), ("neighbor", session["guild_id"])):
                await conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES (?,?,?,0)",
                                   (pid, guild, pid))
                await conn.execute("INSERT INTO gyms(gym_id,guild_id,name,created_at) VALUES (?,?,?,0)",
                                   (pid, guild, "Secret " + pid))
                await conn.execute("INSERT INTO gym_deployments(deployment_id,guild_id,gym_id,profile_id,"
                                   "pokemon_uid,deployed_at,ends_at,ended_at) VALUES (?,?,?,?,?,0,1,1)",
                                   (pid, guild, pid, pid, "p-001"))
        await self.writer.run(seed)
        _, session = await self.details(session, "p-001")
        pokemon = await self.service().detail(self.conn, session["profile_id"], "p-001")
        descriptions = []
        for ref in ("missing", "foreign-profile", "neighbor"):
            with self.subTest(ref=ref), patch.object(self.service(), "detail", return_value={
                    **pokemon, "gym_deployment_id": ref}):
                execute, queries = self.conn.execute, []
                def scoped(sql, parameters=()):
                    if "gym_deployments" in sql:
                        queries.append((sql, parameters))
                        self.assertIn(session["guild_id"], parameters)
                        self.assertIn(session["profile_id"], parameters)
                    return execute(sql, parameters)
                with patch.object(self.conn, "execute", side_effect=scoped):
                    rendered = (await self.click(session, "storage_detail")).edit_original_response.await_args.kwargs
                session = await self.current(session)
                descriptions.append(rendered["embed"].description)
                self.assertEqual(len(queries), 1)
                self.assertIn("Deployed at a gym — recall it", descriptions[-1])
                self.assertNotIn(deployment["deployment_id"], descriptions[-1])
                for label in ("Send for research", "Power up", "Evolve", "Set companion"):
                    self.assertTrue(self.buttons(rendered)[label].disabled, label)
        self.assertEqual(descriptions, [descriptions[0]] * 3)

    async def test_storage_button_enabled_on_home_with_profile(self):
        await self.prepared()
        interaction, _ = await self.open()
        buttons = self.buttons(interaction.edit_original_response.await_args.kwargs)
        self.assertFalse(buttons["Storage"].disabled)
        self.assertFalse(buttons["Bag"].disabled)
        self.assertFalse(buttons["Pokédex"].disabled)
        self.assertFalse(buttons["Route"].disabled)

    async def test_home_renderer_preserves_callers_without_available(self):
        screens = importlib.import_module("pokewalker.bot.screens")
        state = {"session": {"session_id": "abcd", "revision": 0}, "companion": None,
                 "queue_size": 0, "encounter_meter_c": 0, "restrictions": self.module.profiles.Restrictions()}
        self.assertTrue(self.buttons(screens.home(state))["Storage"].disabled)
        state["available"] = {"storage", "bag"}
        buttons = self.buttons(screens.home(state))
        self.assertFalse(buttons["Storage"].disabled)
        self.assertFalse(buttons["Bag"].disabled)
        self.assertTrue(buttons["Route"].disabled)

    async def test_page_lists_owned_only_newest_first_ten_per_page_no_image(self):
        session = await self.prepared(12)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET caught_at=11 WHERE pokemon_uid='p-010'"))
        rendered, session = await self.storage(session)
        rows, total = await self.service().page(self.conn, self.profile["profile_id"], 0)
        self.assertEqual(total, 12)
        self.assertEqual([row["pokemon_uid"] for row in rows],
                         ["p-010", "p-011", *[f"p-{index:03}" for index in range(9, 1, -1)]])
        selector = next(item for item in rendered["view"].children if hasattr(item, "options"))
        self.assertEqual([option.value for option in selector.options], [row["pokemon_uid"] for row in rows])
        self.assertEqual(len(selector.options), 10)
        self.assertIn("#1 Bulbasaur · CP ", rendered["embed"].description)
        self.assertIn("fav", rendered["embed"].description.lower())
        self.assertIsNone(rendered["embed"].image.url)
        self.assertIsNone(rendered["embed"].thumbnail.url)
        next_action = self.buttons(rendered)["Next"].custom_id.rsplit(":", 1)[-1]
        interaction = await self.click(session, next_action)
        updated = interaction.edit_original_response.await_args.kwargs
        self.assertIn("#11 ", updated["embed"].description)
        self.assertEqual(json.loads((await self.current(session))["selection"])["offset"], 10)

    async def test_page_shows_count_of_250_and_bounds(self):
        session = await self.prepared(11)
        rendered, session = await self.storage(session)
        self.assertIn("11/250", rendered["embed"].description)
        self.assertTrue(self.buttons(rendered)["Prev"].disabled)
        self.assertFalse(self.buttons(rendered)["Next"].disabled)
        action = self.buttons(rendered)["Next"].custom_id.rsplit(":", 1)[-1]
        interaction = await self.click(session, action)
        rendered = interaction.edit_original_response.await_args.kwargs
        session = await self.current(session)
        self.assertTrue(self.buttons(rendered)["Next"].disabled)
        self.assertFalse(self.buttons(rendered)["Prev"].disabled)
        action = self.buttons(rendered)["Prev"].custom_id.rsplit(":", 1)[-1]
        interaction = await self.click(session, action)
        self.assertTrue(self.buttons(interaction.edit_original_response.await_args.kwargs)["Prev"].disabled)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET state='sent'"))
        rendered, _ = await self.storage(await self.current(session))
        self.assertIn("0/250", rendered["embed"].description)
        self.assertFalse(any(hasattr(item, "options") for item in rendered["view"].children))
        self.assertTrue(self.buttons(rendered)["Next"].disabled)

    async def test_favorites_filter_toggles_pages_and_resets_to_zero(self):
        session = await self.prepared(12)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET favorite=CASE WHEN pokemon_uid IN ('p-001','p-003','p-011') THEN 1 ELSE 0 END"))
        rendered, session = await self.storage(session)
        self.assertIn("Favorites only", self.buttons(rendered))
        toggle = self.buttons(rendered)["Favorites only"].custom_id.rsplit(":", 1)[-1]
        rendered = (await self.click(session, toggle)).edit_original_response.await_args.kwargs
        session = await self.current(session)
        self.assertEqual(json.loads(session["selection"]), {"offset": 0, "favorite_only": True})
        self.assertIn("3 favorites", rendered["embed"].description)
        selector = next(item for item in rendered["view"].children if hasattr(item, "options"))
        self.assertEqual(len(selector.options), 3)
        self.assertIn("Show all", self.buttons(rendered))
        self.assertTrue(self.buttons(rendered)["Next"].disabled)

    async def test_favorites_filter_pages_bounded_list_and_empty_state(self):
        session = await self.prepared(25)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET favorite=1 WHERE pokemon_uid LIKE 'p-%'"))
        rendered, session = await self.storage(session)
        toggle = self.buttons(rendered)["Favorites only"].custom_id.rsplit(":", 1)[-1]
        rendered = (await self.click(session, toggle)).edit_original_response.await_args.kwargs
        session = await self.current(session)
        self.assertIn("25 favorites", rendered["embed"].description)
        self.assertFalse(self.buttons(rendered)["Next"].disabled)
        action = self.buttons(rendered)["Next"].custom_id.rsplit(":", 1)[-1]
        rendered = (await self.click(session, action)).edit_original_response.await_args.kwargs
        session = await self.current(session)
        self.assertIn("#11 ", rendered["embed"].description)
        self.assertIn("Show all", self.buttons(rendered))
        toggle = self.buttons(rendered)["Show all"].custom_id.rsplit(":", 1)[-1]
        rendered = (await self.click(session, toggle)).edit_original_response.await_args.kwargs
        session = await self.current(session)
        self.assertEqual(json.loads(session["selection"]), {"offset": 0})
        self.assertIn("25/250", rendered["embed"].description)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET favorite=0"))
        toggle = self.buttons(rendered)["Favorites only"].custom_id.rsplit(":", 1)[-1]
        rendered = (await self.click(session, toggle)).edit_original_response.await_args.kwargs
        self.assertIn("0 favorites", rendered["embed"].description)
        self.assertIn("No favorites yet", rendered["embed"].description)
        self.assertFalse(any(hasattr(item, "options") for item in rendered["view"].children))

    async def test_one_favorite_uses_singular_count(self):
        session = await self.prepared(12)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET favorite=CASE WHEN pokemon_uid='p-011' THEN 1 ELSE 0 END"))
        rendered, session = await self.storage(session)
        toggle = self.buttons(rendered)["Favorites only"].custom_id.rsplit(":", 1)[-1]
        rendered = (await self.click(session, toggle)).edit_original_response.await_args.kwargs
        self.assertIn("1 favorite", rendered["embed"].description)
        self.assertNotIn("1 favorites", rendered["embed"].description)

    async def test_unfavorite_last_row_of_second_filtered_page_returns_to_page_zero(self):
        session = await self.prepared(12)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET favorite=CASE WHEN pokemon_uid LIKE 'p-%' THEN 1 ELSE 0 END"))
        rendered, session = await self.storage(session)
        toggle = self.buttons(rendered)["Favorites only"].custom_id.rsplit(":", 1)[-1]
        rendered = (await self.click(session, toggle)).edit_original_response.await_args.kwargs
        session = await self.current(session)
        self.assertIn("11 favorites", rendered["embed"].description)
        rendered = (await self.click(session, self.buttons(rendered)["Next"].custom_id.rsplit(":", 1)[-1])).edit_original_response.await_args.kwargs
        session = await self.current(session)
        self.assertIn("#11 ", rendered["embed"].description)
        selector = next(item for item in rendered["view"].children if hasattr(item, "options"))
        uid = selector.options[0].value
        self.assertEqual(uid, "p-001")
        rendered = (await self.click(session, "storage_open", [uid])).edit_original_response.await_args.kwargs
        session = await self.current(session)
        self.assertIn("Favorite: Yes", rendered["embed"].description)
        await self.click(session, "storage_favorite")
        session = await self.current(session)
        rendered = (await self.click(session, "storage_back")).edit_original_response.await_args.kwargs
        session = await self.current(session)
        self.assertIn("10 favorites", rendered["embed"].description)
        self.assertEqual(json.loads(session["selection"])["offset"], 0)
        self.assertTrue(self.buttons(rendered)["Prev"].disabled)

    async def test_unfavorite_in_filtered_storage_returns_filtered_page_and_stale_revision_refuses(self):
        session = await self.prepared(12)
        uid = "p-011"
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET favorite=CASE WHEN pokemon_uid=? THEN 1 ELSE 0 END", (uid,)))
        rendered, session = await self.storage(session)
        toggle = self.buttons(rendered)["Favorites only"].custom_id.rsplit(":", 1)[-1]
        await self.click(session, toggle)
        session = await self.current(session)
        rendered, session = await self.details(session, uid)
        self.assertEqual(json.loads(session["selection"])["favorite_only"], True)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET revision=revision+1 WHERE pokemon_uid=?", (uid,)))
        stale = await self.click(session, "storage_favorite")
        self.assertIn("reopen /walker", stale.followup.send.await_args.args[0])
        self.assertEqual((await self.rows("SELECT favorite FROM pokemon WHERE pokemon_uid=?", (uid,)))[0]["favorite"], 1)
        current = await self.current(session)
        await self.click(current, "storage_detail")
        current = await self.current(current)
        await self.click(current, "storage_favorite")
        current = await self.current(current)
        rendered = (await self.click(current, "storage_back")).edit_original_response.await_args.kwargs
        self.assertIn("No favorites yet", rendered["embed"].description)

    async def test_favorites_filter_survives_open_details_and_back_research_is_unfiltered(self):
        session = await self.prepared(12)
        uid = "p-011"
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET favorite=CASE WHEN pokemon_uid=? THEN 1 ELSE 0 END", (uid,)))
        rendered, session = await self.storage(session)
        toggle = self.buttons(rendered)["Favorites only"].custom_id.rsplit(":", 1)[-1]
        await self.click(session, toggle)
        session = await self.current(session)
        rendered, session = await self.details(session, uid)
        self.assertTrue(json.loads(session["selection"])["favorite_only"])
        back = await self.click(session, "storage_back")
        self.assertIn("1 favorite", back.edit_original_response.await_args.kwargs["embed"].description)
        session = await self.current(session)
        selection = json.loads(session["selection"])
        self.assertTrue(selection["favorite_only"])
        # Research selection uses its own unfiltered page service call.
        research = await self.click(session, "research")
        research_text = research.edit_original_response.await_args.kwargs["embed"].description
        self.assertIn("5 per page", research_text)
        self.assertIn("Bulbasaur", research_text)
        self.assertIn("12 owned", research_text)

    async def test_sent_pokemon_not_listed(self):
        session = await self.prepared(2, state="sent")
        rows, total = await self.service().page(self.conn, self.profile["profile_id"], 0)
        self.assertEqual((total, [row["pokemon_uid"] for row in rows]), (1, ["p-001"]))
        self.assertIsNone(await self.service().detail(self.conn, self.profile["profile_id"], self.uid))
        rendered, session = await self.storage(session)
        before = await self.rows()
        interaction = await self.click(session, "storage_open", [self.uid])
        self.assertEqual(await self.rows(), before)
        interaction.edit_original_response.assert_not_awaited()

    async def test_detail_shows_cp_hp_appraisal_types_no_level_text(self):
        session = await self.prepared(gender="female", shiny=1)
        rendered, session = await self.details(session)
        pokemon = (await self.rows("SELECT * FROM pokemon WHERE pokemon_uid=?", (self.uid,)))[0]
        identity, _ = self.service().identify(self.bot.content, pokemon)
        base = [identity[key] for key in ("base_attack", "base_defense", "base_stamina")]
        ivs = [pokemon[key] for key in ("iv_attack", "iv_defense", "iv_stamina")]
        text = rendered["embed"].title + rendered["embed"].description
        for expected in (identity["name_en"], identity["kind"], "♀", "Shiny", "Grass", "Poison", "1970-01-01",
                         f"CP {cp(base, ivs, pokemon['level_x2'], multipliers=self.walker.multipliers)}",
                         f"HP {hp(base, ivs, pokemon['level_x2'], multipliers=self.walker.multipliers)}",
                         f"{appraisal(ivs)} stars", "Favorite: Yes"):
            self.assertIn(expected, text)
        self.assertNotIn("level", text.lower())
        buttons = self.buttons(rendered)
        self.assertEqual(set(buttons), {"Unfavorite", "Back", "Send for research", "Power up", "Set companion", "Share", "Evolve"})
        self.assertFalse(buttons["Power up"].disabled)
        self.assertFalse(buttons["Set companion"].disabled)
        self.assertEqual(buttons["Power up"].row, 1)
        self.assertFalse(buttons["Share"].disabled)
        self.assertFalse(buttons["Evolve"].disabled)
        self.assertEqual(buttons["Evolve"].row, 1)
        for name in ("Send for research",):
            self.assertTrue(buttons[name].disabled)
            self.assertEqual(buttons[name].row, 1)
        back = await self.click(session, "storage_back")
        self.assertEqual(back.edit_original_response.await_args.kwargs["embed"].title, "Storage")
        back = await self.click(await self.current(session), "storage_back")
        self.assertEqual(back.edit_original_response.await_args.kwargs["embed"].title, "Walker")

    async def test_detail_image_exact_sprite_or_none(self):
        regional = next(item for item in self.bot.content["identities"] if item["kind"] == "regional")
        session = await self.prepared(pokemon_id=regional["pokemon_id"], shiny=1, gender="male")
        rendered, session = await self.details(session)
        self.assertEqual(rendered["embed"].image.url, regional["sprites"]["shiny"])
        regional["sprites"]["shiny"] = None
        rendered, _ = await self.details(session)
        self.assertIsNone(rendered["embed"].image.url)

    async def test_detail_female_shiny_uses_shiny_female_key(self):
        identity = next(item for item in self.bot.content["identities"] if item["species_id"] == 25)
        session = await self.prepared(pokemon_id=identity["pokemon_id"], gender="female", shiny=1)
        rendered, session = await self.details(session)
        self.assertEqual(rendered["embed"].image.url, identity["sprites"]["shiny_female"])
        male = next(item for item in self.bot.content["identities"] if item.get("gender_varieties"))
        female = male["gender_varieties"]["female"]
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET pokemon_id=?", (female["pokemon_id"],)))
        rendered, _ = await self.details(session)
        self.assertEqual(rendered["embed"].image.url, female["sprites"]["shiny_female"])

    async def test_favorite_toggle_bumps_revision(self):
        session = await self.prepared()
        rendered, session = await self.details(session)
        self.assertIn("Unfavorite", self.buttons(rendered))
        for value in (0, 1):
            before = (await self.rows("SELECT * FROM pokemon"))[0]
            interaction = await self.click(session, "storage_favorite")
            after = (await self.rows("SELECT * FROM pokemon"))[0]
            self.assertEqual(after, {**before, "favorite": value, "revision": before["revision"] + 1})
            session = await self.current(session)
            self.assertEqual(json.loads(session["selection"])["pokemon_revision"], after["revision"])
            self.assertIn("Unfavorite" if value else "Favorite", self.buttons(interaction.edit_original_response.await_args.kwargs))

    async def test_favorite_stale_revision_refused_no_change(self):
        session = await self.prepared()
        _, session = await self.details(session)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET revision=revision+1"))
        before, sessions, writes = await self.rows("SELECT * FROM pokemon"), await self.rows(), self.conn.total_changes
        self.assertIsNone(await self.writer.run(lambda conn: self.service().set_favorite(
            conn, self.profile["profile_id"], self.uid, False, 0)))
        interaction = await self.click(session, "storage_favorite")
        self.assertIn("reopen /walker", interaction.followup.send.await_args.args[0])
        self.assertEqual((await self.rows("SELECT * FROM pokemon"), await self.rows(), self.conn.total_changes),
                         (before, sessions, writes))

    async def test_favorite_double_click_second_is_stale_reopen(self):
        session = await self.prepared()
        _, session = await self.details(session)
        _, competing = await self.open()
        _, competing = await self.details(competing)
        await self.click(session, "storage_favorite")
        before, writes = await self.rows("SELECT * FROM pokemon"), self.conn.total_changes
        for stale in (session, competing):
            interaction = await self.click(stale, "storage_favorite")
            if stale is session:
                interaction.followup.send.assert_not_awaited()
            else:
                self.assertIn("reopen /walker", interaction.followup.send.await_args.args[0])
            self.assertEqual(await self.rows("SELECT * FROM pokemon"), before)
            self.assertEqual(self.conn.total_changes, writes)

    async def test_other_user_cannot_open_or_favorite(self):
        session = await self.prepared(12)
        _, session = await self.storage(session)
        before = await self.rows()
        hidden = await self.click(session, "storage_open", [self.uid])
        hidden.edit_original_response.assert_not_awaited()
        self.assertEqual(await self.rows(), before)
        _, session = await self.details(session, "p-011")
        before, writes = await self.rows("SELECT * FROM pokemon"), self.conn.total_changes
        for action in ("storage_open", "storage_favorite"):
            interaction = await self.click(session, action, ["p-011"], user=999)
            self.assertIn("not yours", interaction.followup.send.await_args.args[0])
        self.assertIsNone(await self.service().detail(self.conn, "other-profile", self.uid))
        self.assertIsNone(await self.writer.run(lambda conn: self.service().set_favorite(conn, "other-profile", self.uid, False, 0)))
        self.assertEqual(await self.rows("SELECT * FROM pokemon"), before)
        self.assertEqual(self.conn.total_changes, writes)

    async def test_excluded_refused_in_router(self):
        session = await self.prepared()
        _, session = await self.details(session)
        await self.exclude()
        before, sessions, writes = await self.rows("SELECT * FROM pokemon"), await self.rows(), self.conn.total_changes
        for action in ("storage", "storage_open", "storage_favorite", "storage_back", "storage_page", "storage_filter"):
            interaction = await self.click(session, action, [self.uid])
            self.assertIn("excluded", interaction.followup.send.await_args.args[0].lower())
        self.assertEqual((await self.rows("SELECT * FROM pokemon"), await self.rows(), self.conn.total_changes),
                         (before, sessions, writes))

    async def test_storage_limit_comes_from_profile(self):
        session = await self.prepared(250)
        _, session = await self.reveal(session)
        interaction = await self.click(session, "throw")
        rendered = interaction.edit_original_response.await_args.kwargs
        self.assertIn("Storage is full (250/250).", rendered["embed"].description)
        rendered, _ = await self.storage(await self.current(session))
        self.assertIn("250/250", rendered["embed"].description)

    async def test_identify_lift_keeps_walker_suites_green(self):
        session = await self.prepared()
        with patch.object(self.service(), "identify", wraps=self.service().identify) as identify:
            await self.open()
            await self.reveal(session)
        self.assertEqual(identify.call_count, 2)

    async def test_render_functions_do_no_io(self):
        session = await self.prepared()
        pokemon = (await self.rows("SELECT * FROM pokemon"))[0]
        identity, sprite = self.service().identify(self.bot.content, pokemon)
        module = importlib.import_module("pokewalker.bot.storage")
        state = {"session": session, "rows": [{"pokemon": pokemon, "identity": identity, "cp": 10}],
                 "total": 1, "offset": 0, "limit": 250, "pokemon": pokemon, "identity": identity,
                 "cp": 10, "hp": 10, "sprite": sprite}
        with patch.object(self.writer, "run", side_effect=AssertionError("database I/O")), \
                patch("builtins.open", side_effect=AssertionError("file I/O")), \
                patch("socket.socket", side_effect=AssertionError("network I/O")):
            self.assertEqual(module.render_page(state)["embed"].title, "Storage")
            self.assertIn(identity["name_en"], module.render_detail(state)["embed"].description)
