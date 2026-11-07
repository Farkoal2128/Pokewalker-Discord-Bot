"""Species Pokédex reads and private screens using SQLite and synthetic Discord."""

import copy
import importlib
import json
import unittest
from unittest.mock import patch

import test_walker_encounter as encounters
from pokewalker.services import research


class PokedexTests(unittest.IsolatedAsyncioTestCase):
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

    def service(self):
        return importlib.import_module("pokewalker.services.pokedex")

    def buttons(self, rendered):
        return {item.label: item for item in rendered["view"].children if hasattr(item, "label")}

    async def act(self, session, action, values=None):
        interaction = await self.click(session, action, values)
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs, await self.current(session)

    async def seed(self, count=25):
        session = await self.ready()
        async def insert(conn):
            await conn.execute("DELETE FROM pokedex")
            await conn.executemany("INSERT INTO pokedex VALUES (?,?,?,?)",
                                   [(self.profile["profile_id"], number, 0, 60 if number % 2 else None)
                                    for number in range(count, 0, -1)])
        await self.writer.run(insert)
        return session

    async def test_home_button_opens_summary_seen_caught_of_installed_total(self):
        await self.seed(3)
        interaction, session = await self.open()
        button = self.buttons(interaction.edit_original_response.await_args.kwargs)["Pokédex"]
        self.assertFalse(button.disabled)
        self.bot.content["species"].pop("1025")
        rendered, session = await self.act(session, button.custom_id.rsplit(":", 1)[-1])
        self.assertIn("Seen 3 · Caught 2 / 1024", rendered["embed"].description)
        self.assertEqual(await self.service().summary(self.conn, self.profile["profile_id"], self.bot.content),
                         {"seen": 3, "caught": 2, "total": 1024})
        self.assertEqual(json.loads(session["selection"])["offset"], 0)

    async def test_list_text_only_no_image_ordered_by_species_id_twenty_per_page(self):
        session = await self.seed()
        rendered, session = await self.act(session, "pokedex")
        rows = await self.service().page(self.conn, self.profile["profile_id"], self.bot.content, 0)
        self.assertEqual([row["species_id"] for row in rows], list(range(1, 21)))
        lines = rendered["embed"].description.splitlines()
        self.assertEqual(len(lines), 21)
        self.assertIn("#001 Bulbasaur · caught 1970-01-01", lines[1])
        self.assertIn("#002 Ivysaur · seen 1970-01-01", lines[2])
        self.assertIsNone(rendered["embed"].image.url)
        self.assertIsNone(rendered["embed"].thumbnail.url)
        self.assertTrue(self.buttons(rendered)["Prev"].disabled)
        rendered, session = await self.act(session, "pokedex_page")
        self.assertIn("#025 Pikachu", rendered["embed"].description)
        self.assertTrue(self.buttons(rendered)["Next"].disabled)
        rendered, session = await self.act(session, "pokedex_entry", ["25"])
        rendered, session = await self.act(session, "pokedex_back")
        self.assertEqual(json.loads(session["selection"])["offset"], 20)
        rendered, session = await self.act(session, "pokedex_prev")
        self.assertTrue(self.buttons(rendered)["Prev"].disabled)
        rendered, _ = await self.act(session, "pokedex_back")
        self.assertEqual(rendered["embed"].title, "Walker")

    async def test_list_omits_unseen_including_queued_unrevealed_encounter_species(self):
        session = await self.ready()
        rendered, _ = await self.act(session, "pokedex")
        self.assertNotIn("Pikachu", rendered["embed"].description)
        self.assertEqual([row["species_id"] for row in await self.service().page(
            self.conn, self.profile["profile_id"], self.bot.content, 0)], [1])
        await self.writer.run(lambda conn: conn.execute("DELETE FROM pokedex"))
        rendered, _ = await self.act(await self.current(session), "pokedex")
        self.assertFalse(any(hasattr(item, "options") for item in rendered["view"].children))
        self.assertTrue(self.buttons(rendered)["Next"].disabled)

    async def test_regional_form_counts_once_toward_species(self):
        regional = next(item for item in self.bot.content["identities"] if item["kind"] == "regional")
        session = await self.ready(pokemon_id=regional["pokemon_id"])
        _, session = await self.reveal(session)
        await self.reveal(session)
        summary = await self.service().summary(self.conn, self.profile["profile_id"], self.bot.content)
        self.assertEqual((summary["seen"], summary["caught"]), (2, 1))
        entry = await self.service().entry(self.conn, self.profile["profile_id"], regional["species_id"], self.bot.content)
        default = next(item for item in self.bot.content["identities"]
                       if item["species_id"] == regional["species_id"] and item["kind"] == "default")
        self.assertEqual((entry["name"], entry["sprite"]), (default["name_en"], default["sprites"]["normal"]))

    async def test_entry_shows_default_sprite_or_none_and_dates(self):
        session = await self.seed()
        default = next(item for item in self.bot.content["identities"]
                       if item["species_id"] == 25 and item["kind"] == "default")
        for sprite in (default["sprites"]["normal"], None):
            default["sprites"]["normal"] = sprite
            _, session = await self.act(session, "pokedex")
            _, session = await self.act(session, "pokedex_page")
            rendered, session = await self.act(session, "pokedex_entry", ["25"])
            entry = await self.service().entry(self.conn, self.profile["profile_id"], 25, self.bot.content)
            self.assertEqual((entry["seen_at"], entry["caught_at"]), (0, 60))
            self.assertEqual(entry["types"], default["types"])
            self.assertEqual(entry["generation_id"], default["generation_id"])
            self.assertEqual(rendered["embed"].image.url, sprite)
            for text in ("Electric", "Generation 1", "Seen: 1970-01-01", "Caught: 1970-01-01"):
                self.assertIn(text, rendered["embed"].description)
        _, session = await self.act(session, "pokedex")
        rendered, _ = await self.act(session, "pokedex_entry", ["2"])
        self.assertIn("Caught: —", rendered["embed"].description)

    async def test_entry_for_unseen_species_refused_no_leak(self):
        session = await self.seed()
        self.assertIsNone(await self.service().entry(self.conn, self.profile["profile_id"], 999, self.bot.content))
        self.assertIsNone(await self.service().entry(self.conn, "other-profile", 1, self.bot.content))
        for values in (["999"], ["25"], ["bad"], [], ["1", "2"]):
            _, session = await self.act(session, "pokedex")
            before = await self.rows()
            interaction = await self.click(session, "pokedex_entry", values)
            interaction.edit_original_response.assert_not_awaited()
            self.assertIn("reopen", interaction.followup.send.await_args.args[0])
            self.assertEqual(await self.rows(), before)

    async def test_run_flee_and_research_send_never_remove_entries(self):
        session = await self.ready()
        _, session = await self.reveal(session)
        before = await self.rows("SELECT * FROM pokedex")
        await self.act(session, "run")
        self.assertEqual(await self.rows("SELECT * FROM pokedex"), before)
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE encounters SET state='revealed',revision=revision+1,resolved_at=NULL"))
        _, session = await self.open()
        _, session = await self.reveal(session)
        with patch.object(self.walker.rng, "random", side_effect=[1.0, 0.0]):
            await self.act(session, "throw")
        self.assertEqual((await self.rows("SELECT state FROM encounters"))[0]["state"], "fled")
        self.assertEqual(await self.rows("SELECT * FROM pokedex"), before)
        async def send(conn):
            await conn.execute("UPDATE profiles SET companion_uid=NULL")
            await conn.execute("UPDATE pokemon SET favorite=0")
            picks = [[self.profile["companion_uid"], 0]]
            preview = {"id": "dex-research", "expires_at": 2000}
            session["selection"] = json.dumps({"picks": picks, "preview": preview})
            return await research.send(conn, session, picks, preview, 1000, self.bot.content)
        self.assertEqual((await self.writer.run(send))["status"], "sent")
        self.assertEqual(await self.rows("SELECT * FROM pokedex"), before)
        self.assertEqual((await self.service().summary(self.conn, self.profile["profile_id"], self.bot.content))["seen"], 2)

    async def test_select_options_at_most_25(self):
        session = await self.seed(51)
        for action, count in (("pokedex", 20), ("pokedex_page", 20), ("pokedex_page", 11)):
            rendered, session = await self.act(session, action)
            selector = next(item for item in rendered["view"].children if hasattr(item, "options"))
            self.assertEqual(len(selector.options), count)
            self.assertLessEqual(len(selector.options), 25)

    async def test_other_user_cannot_open(self):
        session = await self.ready()
        for action in ("pokedex", "pokedex_page", "pokedex_prev", "pokedex_entry", "pokedex_back"):
            before = await self.rows()
            interaction = await self.click(session, action, ["1"], user=999)
            self.assertEqual(await self.rows(), before)
            interaction.edit_original_response.assert_not_awaited()
            self.assertIn("not yours", interaction.followup.send.await_args.args[0])

    async def test_excluded_refused_in_router(self):
        session = await self.ready()
        await self.exclude()
        for action in ("pokedex", "pokedex_page", "pokedex_prev", "pokedex_entry", "pokedex_back"):
            before = await self.rows()
            interaction = await self.click(session, action, ["1"])
            self.assertEqual(await self.rows(), before)
            interaction.edit_original_response.assert_not_awaited()
            self.assertIn("excluded", interaction.followup.send.await_args.args[0])

    async def test_render_functions_do_no_io(self):
        session = await self.seed()
        module = importlib.import_module("pokewalker.bot.pokedex")
        state = {"session": session, "summary": await self.service().summary(
            self.conn, self.profile["profile_id"], self.bot.content), "offset": 0,
            "rows": await self.service().page(self.conn, self.profile["profile_id"], self.bot.content, 0),
            "entry": await self.service().entry(self.conn, self.profile["profile_id"], 1, self.bot.content)}
        original = copy.deepcopy(state)
        with patch("builtins.open", side_effect=AssertionError("render file I/O")), \
                patch("aiosqlite.connect", side_effect=AssertionError("render DB I/O")):
            for render in (module.render_page, module.render_entry):
                rendered = render(state)
                ids = [item.custom_id for item in rendered["view"].children]
                self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(state, original)

    async def test_milestone_page_reports_earned_and_missing_without_mutation(self):
        session = await self.seed()
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO milestone_awards(profile_id,milestone_id,earned_at) VALUES (?, 'pokedex:5', 123)",
            (self.profile["profile_id"],)))
        await self.writer.run(lambda conn: conn.execute("DELETE FROM inbox_items"))
        before = (await self.rows("SELECT * FROM milestone_awards"), await self.rows("SELECT * FROM inbox_items"),
                  await self.rows("SELECT * FROM pokedex"), await self.rows("SELECT * FROM pokemon"),
                  await self.rows("SELECT * FROM inventory"), await self.rows("SELECT * FROM candy"))
        rendered, session = await self.act(session, "pokedex")
        self.assertIn("Milestones", self.buttons(rendered))
        rendered, session = await self.act(session, "pokedex_page")
        self.assertEqual(json.loads(session['selection'])['offset'], 20)
        rendered, session = await self.act(session, "pokedex_milestones")
        self.assertEqual(rendered["embed"].title, "Pokédex milestones")
        self.assertIn("Pokédex 5%", rendered["embed"].description)
        self.assertIn("✅", rendered["embed"].description)
        self.assertIn("1970-01-01", rendered["embed"].description)
        self.assertLessEqual(len(rendered["embed"].description.splitlines()), 13)
        self.assertIn("Missing", self.buttons(rendered))
        self.assertEqual(rendered["embed"].description.count("✅") +
                         rendered["embed"].description.count("⬜"), 10)
        rendered, session = await self.act(session, "milestones_filter_completed")
        self.assertIn("Pokédex 5%", rendered["embed"].description)
        self.assertIn("✅ completed · 1970-01-01 00:02 UTC", rendered["embed"].description)
        self.assertNotIn("⬜", rendered["embed"].description)
        rendered, session = await self.act(session, "milestones_filter_missing")
        self.assertNotIn("Pokédex 5%", rendered["embed"].description)
        self.assertIn("⬜", rendered["embed"].description)
        self.assertIn("species", rendered["embed"].description)
        self.assertIn("2/3 species", rendered["embed"].description)
        rendered, session = await self.act(session, "milestones_filter_all")
        self.assertIn("Pokédex 5%", rendered["embed"].description)
        self.assertLessEqual(len(rendered["embed"].description), 4096)
        rendered, _ = await self.act(session, "milestones_back")
        self.assertEqual(rendered["embed"].title, "Pokédex")
        self.assertEqual(json.loads((await self.current(session))['selection'])['offset'], 20)
        self.assertIn("#021", rendered['embed'].description)
        self.assertEqual((await self.rows("SELECT * FROM milestone_awards"), await self.rows("SELECT * FROM inbox_items"),
                          await self.rows("SELECT * FROM pokedex"), await self.rows("SELECT * FROM pokemon"),
                          await self.rows("SELECT * FROM inventory"), await self.rows("SELECT * FROM candy")), before)

    async def test_milestone_progress_uses_the_same_completion_rules_as_due(self):
        module = importlib.import_module("pokewalker.services.milestones")
        content = self.bot.content
        for caught in (set(), {1}, {1, 4, 7}, {int(sid) for sid in content["species"]}):
            rows = module.catalog(caught, set(), content)
            complete = {row["milestone_id"] for row in rows if row["complete"]}
            self.assertEqual(complete, {milestone_id for milestone_id, _ in module.due(caught, set(), content)})
        rows = module.catalog({1}, set(), content)
        starter = next(row for row in rows if row["milestone_id"] == "starter_trios:1")
        self.assertEqual(starter["progress"], "1/3 species")
        milestones = content['milestones']
        expected = sum(len(milestones.get(category, [])) for category in (
            'pokedex', 'starter_trios', 'regions', 'mythical_sets', 'legendary_groups',
            'extra_bundle_lines', 'ultra_beast_first_catches'))
        expected += len(milestones['evolution_lines']['families'])
        expected += sum(category in milestones for category in (
            'all_starters', 'all_legendaries', 'all_mythicals', 'first_legendary', 'first_mythical'))
        self.assertEqual(len(rows), expected)
        self.assertEqual(len({row['milestone_id'] for row in rows}), expected)

    async def test_pokedex_percent_progress_matches_due_at_the_threshold(self):
        module = importlib.import_module("pokewalker.services.milestones")
        content = self.bot.content
        entry = content['milestones']['pokedex'][0]
        required = (entry['percent'] * len(content['species']) + 99) // 100
        for count, complete in ((required - 1, False), (required, True)):
            caught = {int(sid) for sid in list(content['species'])[:count]}
            row = next(item for item in module.catalog(caught, set(), content)
                       if item['milestone_id'] == f"pokedex:{entry['percent']}")
            self.assertEqual(row['progress'], f'{count}/{required} species')
            self.assertEqual(row['complete'], complete)
            self.assertEqual(complete, f"pokedex:{entry['percent']}" in
                             {milestone_id for milestone_id, _ in module.due(caught, set(), content)})

    async def test_evolution_family_without_bundle_has_reward_label(self):
        pokedex = importlib.import_module('pokewalker.bot.pokedex')
        milestones = importlib.import_module('pokewalker.services.milestones')
        session = await self.ready()
        row = next(item for item in milestones.catalog(set(), set(), self.bot.content)
                   if item['milestone_id'] == 'evolution_lines:1')
        rendered = pokedex.render_milestones({'session': session, 'rows': [row], 'total': 1,
                                               'offset': 0, 'filter': 'all', 'content': self.bot.content})
        self.assertIn('Evolution reward', rendered['embed'].description)

    async def test_milestone_filter_paging_is_bounded_and_empty_filter_is_clear(self):
        session = await self.ready()
        rendered, session = await self.act(session, "pokedex")
        rendered, session = await self.act(session, "pokedex_milestones")
        self.assertTrue(self.buttons(rendered)["Prev"].disabled)
        self.assertFalse(self.buttons(rendered)["Next"].disabled)
        rendered, session = await self.act(session, "milestones_page")
        self.assertEqual(json.loads(session["selection"])["milestone_offset"], 10)
        self.assertFalse(self.buttons(rendered)["Prev"].disabled)
        rendered, session = await self.act(session, "milestones_filter_completed")
        self.assertEqual(json.loads(session["selection"])["milestone_offset"], 0)
        self.assertIn("No milestones match", rendered["embed"].description)
        self.assertTrue(self.buttons(rendered)["Next"].disabled)

    async def test_every_milestone_filter_page_fits_discord_and_has_unique_actions(self):
        module = importlib.import_module('pokewalker.bot.pokedex')
        session = await self.ready()
        entries = await importlib.import_module('pokewalker.services.milestones').list_for_profile(
            self.conn, self.profile['profile_id'], self.bot.content)
        for filter_name in ('all', 'completed', 'missing'):
            rows = ([row for row in entries if row['earned']] if filter_name == 'completed' else
                    [row for row in entries if not row['earned']] if filter_name == 'missing' else entries)
            total = len(rows)
            offsets = list(range(0, total, 10)) or [0]
            for offset in offsets:
                page = rows[offset:offset + 10]
                rendered = module.render_milestones({'session': session, 'rows': page, 'total': total,
                                                     'offset': offset, 'filter': filter_name,
                                                     'content': self.bot.content})
                description = rendered['embed'].description
                self.assertLessEqual(len(description), 4096)
                self.assertEqual(description.count('✅') + description.count('⬜'), len(page))
                self.assertEqual(self.buttons(rendered)['Prev'].disabled, offset == 0)
                self.assertEqual(self.buttons(rendered)['Next'].disabled, offset + len(page) >= total)
                ids = [item.custom_id for item in rendered['view'].children]
                self.assertEqual(len(ids), len(set(ids)))
