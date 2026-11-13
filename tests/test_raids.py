"""D28/D60 and C3: raid schema, queue isolation and deletion on real SQLite."""

from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from pokewalker import db
from pokewalker.services import deletion, profiles
from pokewalker.services.marker_log import State
import test_db
import test_admin_channels
import test_walker_encounter


class RaidWalkerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_walker_encounter.EncounterTests.asyncSetUp
    interaction = test_walker_encounter.EncounterTests.interaction
    rows = test_walker_encounter.EncounterTests.rows
    open = test_walker_encounter.EncounterTests.open
    click = test_walker_encounter.EncounterTests.click
    enroll = test_walker_encounter.EncounterTests.enroll
    ready = test_walker_encounter.EncounterTests.ready
    current = test_walker_encounter.EncounterTests.current
    reveal = test_walker_encounter.EncounterTests.reveal
    snapshot = test_walker_encounter.EncounterTests.snapshot
    encounter_row = test_walker_encounter.EncounterTests.encounter_row

    async def raid(self, *, ordinary=True, shiny=False):
        session = await self.ready()
        identity = next(item for item in self.bot.content["identities"] if item["species_id"] == 144)
        async def seed(conn):
            if ordinary:
                await conn.execute(
                    "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,"
                    "iv_defense,iv_stamina,gender,shiny,tier,route_id,content_version,created_at) "
                    "SELECT 'ordinary',profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
                    "gender,0,tier,route_id,content_version,0 FROM encounters")
            await conn.execute(
                "INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,"
                "spawned_at,expires_at,post_state,content_version) "
                "VALUES ('spawn','123','channel',?,'articuno',900,1100,'sent','fixture')",
                (identity["pokemon_id"],))
            await conn.execute(
                "UPDATE encounters SET raid_spawn_id='spawn',pokemon_id=?,tier='Legendary',"
                "shiny=?,state='revealed' WHERE encounter_id=?",
                (identity["pokemon_id"], int(shiny), self.encounter["encounter_id"]))
            selection = {"encounter_id": self.encounter["encounter_id"], "encounter_revision": 0,
                         "ball": "poke_ball", "berry": None}
            await conn.execute("UPDATE sessions SET selection=? WHERE session_id=?",
                               (json.dumps(selection), session["session_id"]))
        await self.writer.run(seed)
        return await self.current(session)

    async def confirm(self, session, kind):
        if kind == "master":
            await self.click(session, "pick_ball", ["master_ball"])
            session = await self.current(session)
        interaction = await self.click(session, "throw" if kind == "master" else "run")
        self.assertEqual(interaction.edit_original_response.await_args.kwargs["embed"].title,
                         "Confirm Master Ball" if kind == "master" else "Confirm Run")
        return await self.current(session)

    async def assert_back(self, *, ordinary, kind):
        session = await self.raid(ordinary=ordinary, shiny=kind == "shiny")
        session = await self.confirm(session, kind)
        before = await self.encounter_row()
        selected = json.loads(session["selection"])
        interaction = await self.click(session, "open_encounter")
        selection = json.loads((await self.current(session))["selection"])
        self.assertEqual(selection["encounter_id"], self.encounter["encounter_id"])
        self.assertEqual(selection["encounter_revision"], before["revision"])
        self.assertEqual((selection["ball"], selection["berry"]), (selected["ball"], selected["berry"]))
        self.assertNotIn("master_confirm", selection)
        self.assertNotIn("run_confirm", selection)
        self.assertEqual(await self.encounter_row(), before)
        self.assertIn("Articuno", interaction.edit_original_response.await_args.kwargs["embed"].description)
        if ordinary:
            self.assertEqual((await self.rows("SELECT state FROM encounters WHERE encounter_id='ordinary'"))[0],
                             {"state": "queued"})

    async def test_open_encounter_skips_raid_rows(self):
        session = await self.raid()
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE encounters SET created_at=2 WHERE encounter_id='ordinary'"))
        before = await self.encounter_row()
        await self.click(session, "open_encounter")
        self.assertEqual(json.loads((await self.current(session))["selection"])["encounter_id"], "ordinary")
        self.assertEqual(await self.encounter_row(), before)
        await self.writer.run(lambda conn: conn.execute("DELETE FROM encounters WHERE encounter_id='ordinary'"))
        interaction = await self.click(await self.current(session), "open_encounter")
        self.assertEqual(interaction.edit_original_response.await_args.kwargs["embed"].title, "Walker")
        self.assertEqual(await self.encounter_row(), before)

    async def test_master_ball_confirm_back_returns_to_raid_with_ordinary_queued(self):
        await self.assert_back(ordinary=True, kind="master")

    async def test_master_ball_confirm_back_returns_to_raid_with_empty_queue(self):
        await self.assert_back(ordinary=False, kind="master")

    async def test_shiny_run_confirm_back_returns_to_raid_with_ordinary_queued(self):
        await self.assert_back(ordinary=True, kind="shiny")

    async def test_shiny_run_confirm_back_returns_to_raid_with_empty_queue(self):
        await self.assert_back(ordinary=False, kind="shiny")

    async def test_ordinary_confirm_back_unchanged(self):
        session = await self.ready(shiny=1)
        _, session = await self.reveal(session)
        before = await self.encounter_row()
        for kind in ("master", "shiny"):
            with self.subTest(kind=kind):
                session = await self.confirm(session, kind)
                await self.click(session, "open_encounter")
                session = await self.current(session)
                selection = json.loads(session["selection"])
                self.assertEqual(selection["encounter_id"], self.encounter["encounter_id"])
                self.assertNotIn("master_confirm", selection)
                self.assertNotIn("run_confirm", selection)
                self.assertEqual(await self.encounter_row(), before)

    async def test_back_after_raid_deleted_falls_through(self):
        session = await self.confirm(await self.raid(), "master")
        await self.writer.run(lambda conn: conn.execute("DELETE FROM world_spawns"))
        await self.click(session, "open_encounter")
        selection = json.loads((await self.current(session))["selection"])
        self.assertEqual(selection["encounter_id"], "ordinary")
        self.assertNotIn("master_confirm", selection)

    async def test_foreign_and_missing_confirm_selection_use_same_ordinary_fallback(self):
        session = await self.confirm(await self.raid(), "master")
        async def move_to_foreign_profile(conn):
            await conn.execute("INSERT INTO guilds(guild_id) VALUES ('foreign')")
            await conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                               "VALUES ('foreign','foreign','other',1)")
            await conn.execute("UPDATE encounters SET profile_id='foreign' WHERE raid_spawn_id IS NOT NULL")
        await self.writer.run(move_to_foreign_profile)
        foreign = await self.encounter_row()
        embeds = []
        for encounter_id in (self.encounter["encounter_id"], "missing"):
            selection = {"encounter_id": encounter_id, "master_confirm": 0}
            await self.writer.run(lambda conn: conn.execute(
                "UPDATE sessions SET selection=? WHERE session_id=?",
                (json.dumps(selection), session["session_id"])))
            interaction = await self.click(await self.current(session), "open_encounter")
            self.assertEqual(json.loads((await self.current(session))["selection"])["encounter_id"], "ordinary")
            embeds.append(interaction.edit_original_response.await_args.kwargs["embed"].to_dict())
        self.assertEqual(embeds[0], embeds[1])
        self.assertEqual(await self.encounter_row(), foreign)

    async def test_deleted_raid_back_with_empty_queue_clears_flags_before_home(self):
        session = await self.confirm(await self.raid(ordinary=False), "master")
        await self.writer.run(lambda conn: conn.execute("DELETE FROM world_spawns"))
        interaction = await self.click(session, "open_encounter")
        self.assertEqual(interaction.edit_original_response.await_args.kwargs["embed"].title, "Walker")
        selection = json.loads((await self.current(session))["selection"])
        self.assertNotIn("master_confirm", selection)
        self.assertNotIn("run_confirm", selection)

    async def test_fabricated_home_clears_only_confirmation_flags(self):
        session = await self.confirm(await self.raid(), "master")
        selection = json.loads(session["selection"])
        selection.update(run_confirm=True, unrelated="preserved")
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE sessions SET selection=? WHERE session_id=?",
            (json.dumps(selection), session["session_id"])))
        interaction = await self.click(await self.current(session), "home")
        self.assertEqual(interaction.edit_original_response.await_args.kwargs["embed"].title, "Walker")
        expected = {key: value for key, value in selection.items() if key not in ("run_confirm", "master_confirm")}
        self.assertEqual(json.loads((await self.current(session))["selection"]), expected)

    async def test_later_after_failed_master_throw_then_open_encounter_opens_queue_not_raid(self):
        session = await self.confirm(await self.raid(), "master")
        await self.writer.run(lambda conn: conn.execute("DELETE FROM inventory WHERE item_id='master_ball'"))
        before = await self.snapshot()
        failed = await self.click(session, "master_confirm")
        self.assertIn("none of the selected ball", failed.edit_original_response.await_args.kwargs["embed"].description)
        self.assertEqual(await self.snapshot(), before)
        await self.click(session, "later")
        session = await self.current(session)
        self.assertNotIn("master_confirm", json.loads(session["selection"]))
        await self.click(session, "open_encounter")
        self.assertEqual(json.loads((await self.current(session))["selection"])["encounter_id"], "ordinary")

    async def assert_expired_run(self, shiny, *, confirmed=True):
        session = await self.raid(shiny=shiny)
        if shiny and confirmed:
            session = await self.confirm(session, "shiny")
        self.walker.clock = lambda: 1100
        before, writes = await self.snapshot(), self.conn.total_changes
        interaction = await self.click(session, "run_confirm" if shiny and confirmed else "run")
        self.assertEqual((await self.encounter_row())["state"], "revealed")
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(self.conn.total_changes, writes)
        self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='run'"), [])
        self.assertEqual(interaction.followup.send.await_args.args[0], "The World Legendary left.")

    async def test_run_after_raid_expiry_refused_encounter_stays_revealed(self):
        await self.assert_expired_run(False)

    async def test_live_raid_run_resolves_normally(self):
        session = await self.raid()
        await self.click(session, "run")
        self.assertEqual((await self.encounter_row())["state"], "ran")
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='run'")), 1)

    async def test_shiny_run_confirm_after_raid_expiry_refused_encounter_stays_revealed(self):
        await self.assert_expired_run(True)

    async def test_shiny_run_after_raid_expiry_refused_before_confirmation(self):
        await self.assert_expired_run(True, confirmed=False)

    async def test_confirm_back_after_raid_expiry_does_not_reopen_it(self):
        session = await self.confirm(await self.raid(), "master")
        self.walker.clock = lambda: 1100
        before = await self.encounter_row()
        await self.click(session, "open_encounter")
        self.assertEqual(json.loads((await self.current(session))["selection"])["encounter_id"], "ordinary")
        self.assertEqual(await self.encounter_row(), before)

    async def expire_raid(self):
        from pokewalker.services import raids
        return await self.writer.run(lambda conn: raids.expire(conn, self.walker.clock()))

    async def test_panel_open_advance_past_expiry_cleanup_pending_throw_rejected_spends_nothing(self):
        session = await self.raid(ordinary=False)
        before = {table: await self.rows(f'SELECT * FROM {table}') for table in
                  ('sessions', 'encounters', 'inventory', 'catch_attempts', 'action_receipts', 'resource_ledger')}
        self.walker.clock = lambda: 1101
        writes = self.conn.total_changes
        with patch.object(self.walker.rng, 'random', side_effect=AssertionError('expired roll')):
            screen = await self.click(session, 'throw')
        self.assertIn('expired', screen.edit_original_response.await_args.kwargs['embed'].description)
        self.assertIn('The World Legendary left; this encounter expired.',
                      screen.edit_original_response.await_args.kwargs['embed'].description)
        self.assertEqual(self.conn.total_changes, writes)
        self.assertEqual({table: await self.rows(f'SELECT * FROM {table}') for table in before}, before)
        self.assertEqual((await self.rows('SELECT ended FROM world_spawns'))[0]['ended'], 0)

    async def test_catch_committed_before_expiry_survives_cleanup_and_is_acknowledgeable(self):
        session = await self.raid(ordinary=False)
        self.walker.clock = lambda: 1099.9
        with patch.object(self.walker.rng, 'random', return_value=0):
            await self.click(session, 'throw')
        before = {table: await self.rows(f'SELECT * FROM {table}') for table in
                  ('encounters', 'pokemon', 'pokedex', 'inventory', 'candy', 'profiles',
                   'catch_attempts', 'action_receipts', 'resource_ledger', 'milestone_awards', 'inbox_items')}
        self.assertEqual(before['encounters'][0]['state'], 'caught')
        self.walker.clock = lambda: 1101
        await self.expire_raid()
        self.assertEqual({table: await self.rows(f'SELECT * FROM {table}') for table in before}, before)
        screen, recovered = await self.open()
        self.assertEqual(screen.edit_original_response.await_args.kwargs['embed'].title, 'Encounter result')
        self.assertEqual(json.loads(recovered['selection'])['encounter_id'], self.encounter['encounter_id'])
        await self.click(recovered, 'ack')
        self.assertEqual((await self.encounter_row())['acknowledged_at'], 1101)
        caught = await self.rows('SELECT * FROM pokemon WHERE source_encounter_id=?',
                                 (self.encounter['encounter_id'],))
        self.assertEqual(len(caught), 1)
        self.assertEqual(caught[0]['state'], 'owned')
        self.assertEqual(caught[0]['caught_at'], before['encounters'][0]['resolved_at'])
        self.assertEqual(await self.rows('SELECT * FROM pokemon WHERE source_encounter_id IS NULL'),
                         before['pokemon'])
        self.assertEqual(await self.rows('SELECT * FROM resource_ledger'), before['resource_ledger'])

    async def test_expired_encounter_never_shows_in_recovery_or_queue(self):
        await self.raid()
        self.walker.clock = lambda: 1101
        await self.expire_raid()
        self.assertEqual(await self.rows('SELECT * FROM encounters WHERE raid_spawn_id IS NOT NULL'), [])
        screen, session = await self.open()
        self.assertEqual(screen.edit_original_response.await_args.kwargs['embed'].title, 'Walker')
        self.assertEqual(await profiles.queue_size(self.conn, self.profile['profile_id']), 1)
        await self.click(session, 'open_encounter')
        self.assertEqual(json.loads((await self.current(session))['selection'])['encounter_id'], 'ordinary')

    async def test_run_and_shiny_run_after_expiry_then_cleanup_removes_encounter_no_terminal_result(self):
        for shiny in (False, True):
            with self.subTest(shiny=shiny):
                await self.assert_expired_run(shiny)
                await self.expire_raid()
                self.assertEqual(await self.rows('SELECT * FROM encounters WHERE raid_spawn_id IS NOT NULL'), [])
                screen, _ = await self.open()
                self.assertEqual(screen.edit_original_response.await_args.kwargs['embed'].title, 'Walker')
                self.assertEqual(await self.rows("SELECT * FROM encounters WHERE state IN ('caught','ran','fled')"), [])
                await self.writer.run(lambda conn: conn.execute('DELETE FROM world_spawns'))
                await self.writer.run(lambda conn: conn.execute('DELETE FROM profiles'))
                self.walker.clock = lambda: 1000


class RaidSchemaTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_db.DatabaseTests.asyncSetUp
    scalar = test_db.DatabaseTests.scalar
    profile = test_db.DatabaseTests.profile

    async def spawn(self, spawn_id="spawn", guild="guild", profile_id=None):
        await self.conn.execute("INSERT OR IGNORE INTO guilds(guild_id) VALUES (?)", (guild,))
        await self.conn.execute(
            "INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,"
            "spawned_at,expires_at,spawned_by_profile_id,post_state,content_version) "
            "VALUES (?,?, 'channel',144,'articuno',100,3700,?,'pending','fixture')",
            (spawn_id, guild, profile_id))
        return spawn_id

    async def encounter(self, profile_id, encounter_id, state="queued", spawn_id=None):
        await self.conn.execute(
            "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,"
            "iv_defense,iv_stamina,gender,shiny,tier,route_id,content_version,created_at,"
            "state,raid_spawn_id) VALUES (?,?,144,2,0,0,0,'genderless',0,'Legendary',"
            "'refreshing_field','fixture',100,?,?)",
            (encounter_id, profile_id, state, spawn_id))

    async def test_raids_default_off_no_channel(self):
        await self.profile()
        row = dict((await self.conn.execute_fetchall("SELECT * FROM guilds"))[0])
        self.assertEqual(row.get("raids_enabled", "missing"), 0)
        self.assertIsNone(row.get("raid_channel_id", "missing"))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("UPDATE guilds SET raids_enabled=2")

    async def test_queue_triggers_ignore_raid_encounters(self):
        pid = await self.profile()
        await self.spawn()
        for i, state in enumerate(("queued", "revealed", "queued")):
            await self.encounter(pid, f"ordinary-{i}", state)
        await self.encounter(pid, "raid", spawn_id="spawn")
        await self.conn.execute("UPDATE encounters SET state='revealed' WHERE encounter_id='raid'")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Encounter queue full"):
            await self.encounter(pid, "fourth")
        await self.encounter(pid, "terminal", "ran")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Encounter queue full"):
            await self.conn.execute("UPDATE encounters SET state='revealed' WHERE encounter_id='terminal'")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Encounter queue full"):
            await self.conn.execute("UPDATE encounters SET raid_spawn_id=NULL WHERE encounter_id='raid'")
        other = await self.profile("other")
        await self.encounter(other, "other-ordinary")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Encounter queue full"):
            await self.conn.execute("UPDATE encounters SET profile_id=? WHERE encounter_id='other-ordinary'", (pid,))
        await self.encounter(other, "other-raid", spawn_id="spawn")
        await self.conn.execute("UPDATE encounters SET profile_id=? WHERE encounter_id='other-raid'", (pid,))
        self.assertEqual(await self.scalar("SELECT count(*) FROM encounters WHERE profile_id=?", (pid,)), 6)
        await self.conn.execute("DELETE FROM encounters WHERE encounter_id='ordinary-0'")
        await self.encounter(pid, "replacement")
        await self.conn.execute("DELETE FROM encounters WHERE encounter_id='replacement'")
        await self.conn.execute("UPDATE encounters SET raid_spawn_id=NULL WHERE encounter_id='raid'")
        self.assertEqual(await profiles.queue_size(self.conn, pid), 3)

    async def test_queue_size_skips_raid_rows(self):
        pid = await self.profile()
        await self.spawn()
        await self.encounter(pid, "ordinary")
        await self.encounter(pid, "ordinary-revealed", "revealed")
        await self.encounter(pid, "terminal", "caught")
        await self.encounter(pid, "raid-queued", spawn_id="spawn")
        await self.encounter(pid, "raid-revealed", "revealed", "spawn")
        self.assertEqual(await profiles.queue_size(self.conn, pid), 2)
        self.assertEqual(await profiles.queue_size(self.conn, await self.profile("other")), 0)

    async def test_one_active_spawn_per_guild_index(self):
        await self.spawn()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.spawn("duplicate")
        await self.spawn("foreign", "other-guild")
        await self.conn.execute("UPDATE world_spawns SET ended=1 WHERE spawn_id='spawn'")
        await self.spawn("next")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("UPDATE world_spawns SET ended=0 WHERE spawn_id='spawn'")
        for column, value in (("ended", 2), ("post_state", "unknown")):
            with self.subTest(column=column), self.assertRaises(sqlite3.IntegrityError):
                await self.conn.execute(f"UPDATE world_spawns SET {column}=? WHERE spawn_id='next'", (value,))

    async def delete_profile(self, pid):
        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            await deletion.apply(self.conn, {("guild", "user"): State(delete_ids={pid})})
            await self.conn.commit()
        except BaseException:
            await self.conn.rollback()
            raise

    async def test_profile_delete_nulls_spawn_attribution_keeps_spawn(self):
        pid = await self.profile()
        await self.spawn(profile_id=pid)
        await self.conn.execute("UPDATE world_spawns SET post_state='sent',message_id='message'")
        before = dict((await self.conn.execute_fetchall("SELECT * FROM world_spawns"))[0])
        await self.delete_profile(pid)
        after = dict((await self.conn.execute_fetchall("SELECT * FROM world_spawns"))[0])
        self.assertEqual(after, {**before, "spawned_by_profile_id": None})
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)

    async def test_profile_delete_keeps_participation_nulls_encounter_id(self):
        pid = await self.profile()
        await self.spawn(profile_id=pid)
        await self.encounter(pid, "raid", spawn_id="spawn")
        await self.conn.execute("INSERT INTO raid_participation VALUES ('guild','user','spawn','raid',101)")
        await self.delete_profile(pid)
        row = dict((await self.conn.execute_fetchall("SELECT * FROM raid_participation"))[0])
        self.assertEqual(row, {"guild_id": "guild", "user_id": "user", "spawn_id": "spawn",
                               "encounter_id": None, "joined_at": 101})
        self.assertEqual(await self.scalar("SELECT count(*) FROM encounters"), 0)
        new_pid = await self.profile()
        self.assertNotEqual(pid, new_pid)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("INSERT INTO raid_participation VALUES ('guild','user','spawn',NULL,102)")
        await self.encounter(new_pid, "new-raid", spawn_id="spawn")
        await self.conn.execute("DELETE FROM world_spawns WHERE spawn_id='spawn'")
        self.assertEqual(await self.scalar("SELECT count(*) FROM raid_participation"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM encounters"), 0)

    async def test_guild_delete_cascades_spawn_and_participation(self):
        pid = await self.profile()
        await self.spawn(profile_id=pid)
        await self.encounter(pid, "raid", spawn_id="spawn")
        await self.conn.execute("INSERT INTO raid_participation VALUES ('guild','user','spawn','raid',101)")
        await self.conn.execute("DELETE FROM guilds WHERE guild_id='guild'")
        for table in ("world_spawns", "raid_participation", "encounters"):
            self.assertEqual(await self.scalar(f"SELECT count(*) FROM {table}"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM pragma_foreign_key_check"), 0)

    async def test_migration_applies_once_and_user_version_advances(self):
        prior = Path(self.temp.name) / "prior"
        prior.mkdir()
        for migration in db.MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"):
            if int(migration.name[:4]) <= 14:
                shutil.copyfile(migration, prior / migration.name)
        path = Path(self.temp.name) / "prior.sqlite3"
        with patch.object(db, "MIGRATIONS", prior):
            old = await db.open_db(path)
        try:
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('guild')")
            await old.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                              "VALUES ('legacy','guild','user',0)")
            await old.execute("INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,"
                              "iv_attack,iv_defense,iv_stamina,gender,shiny,tier,route_id,content_version,created_at) "
                              "VALUES ('ordinary','legacy',1,2,0,0,0,'male',0,'Common','refreshing_field','fixture',0)")
            before = dict((await old.execute_fetchall("SELECT * FROM encounters"))[0])
        finally:
            await old.close()
        for _ in range(2):
            upgraded = await db.open_db(path)
            try:
                self.assertEqual((await upgraded.execute_fetchall("PRAGMA user_version"))[0][0],
                                 len(list(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))))
                after = dict((await upgraded.execute_fetchall("SELECT * FROM encounters"))[0])
                self.assertEqual(after.pop("raid_spawn_id", "missing"), None)
                self.assertEqual(after, before)
                self.assertEqual(await profiles.queue_size(upgraded, "legacy"), 1)
                self.assertEqual(await upgraded.execute_fetchall("PRAGMA foreign_key_check"), [])
            finally:
                await upgraded.close()


class RaidAdminTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_admin_channels.AdminChannelTests.asyncSetUp
    rows = test_admin_channels.AdminChannelTests.rows
    reply = test_admin_channels.AdminChannelTests.reply

    async def invoke(self, on="on", channel=None, reason=" raid policy "):
        command = self.group.get_command("raids")
        self.assertIsNotNone(command, "M8.1b raid configuration command must exist")
        await command.callback(command.binding, self.interaction, on=on, channel=channel, reason=reason)

    def permissions(self, *, embed=True, send=True):
        self.channel.permissions_for = lambda member: SimpleNamespace(embed_links=embed, send_messages=send)

    async def test_raids_on_requires_channel_sets_flag_and_channel_audited(self):
        await self.invoke()
        missing = self.reply()
        self.assertIn("channel", missing.lower())
        self.assertEqual(await self.rows("guilds"), [])
        self.assertEqual(await self.rows("mod_audit"), [])
        self.permissions()
        await self.invoke(channel=self.channel)
        guild = (await self.rows("guilds"))[0]
        self.assertEqual((guild["guild_id"], guild["raids_enabled"], guild["raid_channel_id"]), ("123", 1, "789"))
        audit = (await self.rows("mod_audit"))[0]
        self.assertEqual((audit["guild_id"], audit["actor_id"], audit["target_kind"], audit["target_id"],
                          audit["action"], audit["reason"]),
                         ("123", "456", "guild", "123", "raids_on", "raid policy"))
        self.assertGreater(audit["created_at"], 0)
        self.assertIn("on", self.reply())
        self.assertEqual(self.interaction.edit_original_response.await_args.kwargs["allowed_mentions"].to_dict(),
                         {"parse": []})
        self.channel.id = 790
        await self.invoke(channel=self.channel)
        self.assertEqual((await self.rows("guilds"))[0]["raid_channel_id"], "790")

    async def test_raids_on_channel_in_other_guild_refused(self):
        await self.invoke()
        missing = self.reply()
        self.channel.guild.id = 999
        self.channel.permissions_for = lambda member: self.fail("must not inspect foreign permissions")
        await self.invoke(channel=self.channel)
        self.assertEqual(self.reply(), missing)
        self.assertEqual(await self.rows("guilds"), [])
        self.assertEqual(await self.rows("mod_audit"), [])

    async def test_raids_off_keeps_channel_clears_flag(self):
        self.permissions()
        await self.invoke(channel=self.channel)
        await self.conn.execute("INSERT INTO guilds(guild_id,raids_enabled,raid_channel_id) VALUES ('999',1,'888')")
        self.channel.permissions_for = lambda member: self.fail("off must not inspect permissions")
        await self.invoke("off")
        rows = {r["guild_id"]: r for r in await self.rows("guilds")}
        self.assertEqual((rows["123"]["raids_enabled"], rows["123"]["raid_channel_id"]), (0, "789"))
        self.assertEqual((rows["999"]["raids_enabled"], rows["999"]["raid_channel_id"]), (1, "888"))
        self.assertEqual([r["action"] for r in await self.rows("mod_audit")], ["raids_on", "raids_off"])
        self.assertIn("off", self.reply())
        self.interaction.guild_id = 555
        await self.invoke("off")
        fresh = next(r for r in await self.rows("guilds") if r["guild_id"] == "555")
        self.assertEqual((fresh["raids_enabled"], fresh["raid_channel_id"]), (0, None))

    async def test_permission_warning_text_not_refusal(self):
        for embed, send in ((False, True), (True, False), (False, False), (True, True)):
            with self.subTest(embed=embed, send=send):
                self.permissions(embed=embed, send=send)
                await self.invoke(channel=self.channel)
                self.assertEqual((await self.rows("guilds"))[0]["raids_enabled"], 1)
                self.assertEqual((await self.rows("mod_audit"))[-1]["action"], "raids_on")
                self.assertEqual("EMBED_LINKS" in self.reply(), not (embed and send))
                self.assertEqual("SEND_MESSAGES" in self.reply(), not (embed and send))

    async def test_whitespace_reason_refused(self):
        for on in ("on", "off"):
            await self.invoke(on, self.channel, reason=" \t\n ")
            self.assertIn("reason", self.reply())
        self.assertEqual(await self.rows("guilds"), [])
        self.assertEqual(await self.rows("mod_audit"), [])

    async def test_excluded_admin_refused_inside_transaction(self):
        original_authorize = self.group.authorize

        async def exclude_after_entry(interaction):
            allowed = await original_authorize(interaction)
            async def exclude(conn):
                await conn.execute("INSERT OR IGNORE INTO guilds(guild_id) VALUES ('123')")
                await conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
            await self.writer.run(exclude)
            return allowed

        self.permissions()
        with patch.object(self.group, "authorize", side_effect=exclude_after_entry):
            await self.invoke(channel=self.channel)
        self.assertIn("excluded", self.reply().lower())
        self.assertEqual((await self.rows("guilds"))[0]["raids_enabled"], 0)
        self.assertIsNone((await self.rows("guilds"))[0]["raid_channel_id"])
        self.assertEqual(await self.rows("mod_audit"), [])

    async def test_manage_server_required(self):
        self.interaction.user.guild_permissions.manage_guild = False
        for on in ("on", "off"):
            await self.invoke(on, self.channel)
            self.assertIn("Manage Server", self.reply())
        self.interaction.user.guild_permissions.manage_guild = True
        self.interaction.guild_id = None
        await self.invoke(channel=self.channel)
        self.assertIn("server", self.reply())
        self.assertEqual(await self.rows("guilds"), [])
        self.assertEqual(await self.rows("mod_audit"), [])

    async def test_command_schema_invalid_choice_and_audit_rollback(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(SimpleNamespace())
        self.addAsyncCleanup(bot.close)
        group = bot.tree.get_command("walker-admin")
        self.assertTrue(group.guild_only)
        self.assertTrue(group.default_permissions.manage_guild)
        command = group.get_command("raids")
        self.assertIsNotNone(command)
        params = {p.name: p for p in command.parameters}
        self.assertEqual({p.name for p in command.parameters if p.required}, {"on", "reason"})
        self.assertEqual({c.value for c in params["on"].choices}, {"on", "off"})
        self.assertEqual([t.value for t in params["channel"].channel_types], [0, 5])
        await self.invoke("invalid", self.channel)
        self.assertEqual(await self.rows("guilds"), [])
        self.assertEqual(await self.rows("mod_audit"), [])
        self.permissions()
        await self.invoke(channel=self.channel)
        before = await self.rows("guilds"), await self.rows("mod_audit")
        await self.conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON mod_audit BEGIN SELECT RAISE(ABORT,'audit failed'); END")
        with self.assertRaisesRegex(Exception, "audit failed"):
            await self.invoke("off")
        self.assertEqual((await self.rows("guilds"), await self.rows("mod_audit")), before)

    async def test_private_defer_and_transaction_permission_recheck(self):
        original_authorize = self.group.authorize
        async def revoke_after_entry(interaction):
            allowed = await original_authorize(interaction)
            interaction.user.guild_permissions.manage_guild = False
            return allowed
        original_run = self.writer.run
        async def deferred_first(fn, **kwargs):
            self.interaction.response.defer.assert_awaited_once_with(ephemeral=True)
            return await original_run(fn, **kwargs)
        self.permissions()
        with patch.object(self.group, "authorize", side_effect=revoke_after_entry), \
             patch.object(self.writer, "run", side_effect=deferred_first):
            await self.invoke(channel=self.channel)
        self.assertIn("Manage Server", self.reply())
        self.assertEqual(await self.rows("guilds"), [])
        self.assertEqual(await self.rows("mod_audit"), [])


class RaidSpawnTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_db.DatabaseTests.scalar
    profile = test_db.DatabaseTests.profile
    encounter = RaidSchemaTests.encounter

    async def asyncSetUp(self):
        import random
        from unittest.mock import AsyncMock, Mock
        await test_db.DatabaseTests.asyncSetUp(self)
        self.pid = await self.profile('u', 'g')
        self.other = await self.profile('v', 'h')
        self.now = 1000
        self.content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        self.rng = random.Random(6)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.session = dict(session_id='wlt', profile_id=self.pid, guild_id='g', user_id='u', revision=0)
        await self.conn.execute("INSERT INTO sessions(session_id,profile_id,guild_id,user_id,expires_at) "
                                "VALUES ('wlt',?,'g','u',9999)", (self.pid,))
        await self.conn.execute("UPDATE guilds SET raids_enabled=1,raid_channel_id='789' WHERE guild_id='g'")
        await self.conn.execute("INSERT INTO inventory VALUES (?,'world_legendary_ticket',1)", (self.pid,))
        self.channel = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=555)))
        self.bot = SimpleNamespace(writer=self.writer, content=self.content,
            walker=SimpleNamespace(clock=lambda: self.now), get_channel=Mock(return_value=self.channel))

    def raids(self):
        import importlib
        try:
            return importlib.import_module('pokewalker.services.raids')
        except ModuleNotFoundError:
            self.fail('Raid spawn/announcement service is absent')

    async def rows(self, sql, args=()):
        return [dict(row) for row in await self.conn.execute_fetchall(sql, args)]

    async def use(self, *, checked='789', session=None):
        return await self.writer.run(lambda conn: self.raids().spawn(
            conn, session or self.session, self.now, self.rng, self.content, checked))

    async def ticket(self):
        return await self.scalar("SELECT quantity FROM inventory WHERE profile_id=? AND item_id='world_legendary_ticket'", (self.pid,))

    async def test_use_consumes_ticket_only_when_spawn_commits(self):
        with patch.object(self.conn, 'commit', side_effect=sqlite3.IntegrityError('commit failed')):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'commit failed'):
                await self.use()
        self.assertEqual(await self.ticket(), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM world_spawns'), 0)
        self.assertEqual(await self.scalar('SELECT count(*) FROM action_receipts'), 0)
        result = await self.use()
        self.assertEqual(result['status'], 'spawned')
        spawn = result['spawn']
        self.assertEqual((spawn['guild_id'], spawn['channel_id'], spawn['expires_at'], spawn['post_state']),
                         ('g', '789', 4600, 'pending'))
        self.assertEqual(spawn['spawned_by_profile_id'], self.pid)
        self.assertEqual(await self.ticket(), 0)
        ledger = (await self.rows('SELECT * FROM resource_ledger'))[0]
        self.assertEqual((ledger['delta'], ledger['reason'], ledger['resource_id']),
                         (-1, 'wlt_use', 'world_legendary_ticket'))

    async def test_refused_and_kept_when_off_no_channel_no_permission_or_active(self):
        for sql, checked, expected in (
            ("UPDATE guilds SET raids_enabled=0", '789', 'raids_off'),
            ("UPDATE guilds SET raids_enabled=1,raid_channel_id=NULL", '789', 'no_channel'),
            ("UPDATE guilds SET raid_channel_id='789'", None, 'no_permission')):
            await self.conn.execute(sql)
            self.assertEqual(await self.use(checked=checked), {'status': expected})
            self.assertEqual(await self.ticket(), 1)
        await self.use()
        await self.conn.execute("UPDATE inventory SET quantity=1 WHERE profile_id=?", (self.pid,))
        self.session['revision'] += 1
        self.assertEqual(await self.use(), {'status': 'active'})
        self.assertEqual(await self.ticket(), 1)

    async def test_channel_changed_between_check_and_commit_refused_ticket_kept(self):
        self.assertEqual(await self.use(checked='999'), {'status': 'channel_changed'})
        self.assertEqual(await self.ticket(), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM world_spawns'), 0)

    async def test_missing_ticket_refusal_does_not_create_spawn(self):
        await self.conn.execute('DELETE FROM inventory')
        self.assertEqual(await self.use(), {'status': 'missing'})
        self.assertEqual(await self.scalar('SELECT count(*) FROM world_spawns'), 0)

    async def test_spawn_stores_checked_channel_and_announce_uses_it_after_config_change(self):
        spawn = (await self.use())['spawn']
        await self.conn.execute("UPDATE guilds SET raid_channel_id='999',raids_enabled=0")
        await self.raids().announce(self.bot, spawn)
        self.bot.get_channel.assert_called_once_with(789)
        self.channel.send.assert_awaited_once()

    async def test_ticket_use_after_expiry_with_cleanup_pending_spawns_new(self):
        first = (await self.use())['spawn']
        await self.conn.execute("UPDATE inventory SET quantity=1 WHERE profile_id=?", (self.pid,))
        self.now = first['expires_at']
        self.session['revision'] += 1
        second = await self.use()
        self.assertEqual(second['status'], 'spawned')
        self.assertNotEqual(first['spawn_id'], second['spawn']['spawn_id'])
        self.assertEqual(await self.scalar('SELECT ended FROM world_spawns WHERE spawn_id=?', (first['spawn_id'],)), 1)

    async def test_expire_deletes_unfinished_raid_encounters_keeps_caught(self):
        spawn = (await self.use())['spawn']
        for state in ('queued', 'revealed', 'caught', 'ran'):
            await self.encounter(self.pid, state, state, spawn['spawn_id'])
            await self.conn.execute('INSERT INTO raid_participation VALUES (?,?,?,?,0)',
                                    ('g', state, spawn['spawn_id'], state))
        await self.encounter(self.pid, 'ordinary')
        async def expire(now, guild):
            return await self.writer.run(lambda conn: self.raids().expire(conn, now, guild))
        zero = {'spawns': 0, 'encounters': 0, 'participation': 0}
        self.assertEqual(await expire(4600, 'h'), zero)
        self.assertEqual(await expire(4599.9, None), zero)
        self.assertEqual(await expire(4600, 'g'), {'spawns': 1, 'encounters': 2, 'participation': 4})
        self.assertEqual({r['encounter_id'] for r in await self.rows('SELECT encounter_id FROM encounters')},
                         {'caught', 'ran', 'ordinary'})
        self.assertEqual(await expire(9000, None), zero)
        self.assertEqual(await self.ticket(), 0)

    async def test_spawn_uniform_legendary_not_mythical_ignores_route_seeded(self):
        import random
        pool = [i for i in self.content['identities'] if i['is_legendary'] and not i['is_mythical']]
        rng = random.Random(6)
        expected = [rng.choice(pool)['identity_id'] for _ in range(12)]
        actual = []
        for rev in range(12):
            self.session['revision'] = rev
            await self.conn.execute('UPDATE profiles SET route_id=? WHERE profile_id=?',
                                    ('noisy_forest' if rev % 2 else 'refreshing_field', self.pid))
            await self.conn.execute('UPDATE world_spawns SET ended=1')
            await self.conn.execute("UPDATE inventory SET quantity=1 WHERE profile_id=?", (self.pid,))
            actual.append((await self.use())['spawn']['identity_id'])
        self.assertEqual(actual, expected)
        self.assertTrue(any(next(i for i in pool if i['identity_id']==identity)['kind'] != 'default' for identity in actual))

    async def test_announce_marks_attempted_before_send_then_sent(self):
        spawn = (await self.use())['spawn']
        async def send(**kwargs):
            self.assertFalse(self.conn.in_transaction)
            self.assertEqual(await self.scalar('SELECT post_state FROM world_spawns'), 'attempted')
            await self.writer.run(lambda conn: conn.execute('SELECT 1'))
            return SimpleNamespace(id=555)
        self.channel.send.side_effect = send
        await self.raids().announce(self.bot, spawn)
        self.assertEqual((await self.rows('SELECT post_state,message_id FROM world_spawns'))[0],
                         {'post_state': 'sent', 'message_id': '555'})

    async def test_send_payload_has_nonce_and_enforce_nonce(self):
        from discord.http import handle_message_parameters
        spawn = (await self.use())['spawn']
        await self.raids().announce(self.bot, spawn)
        kwargs = self.channel.send.await_args.kwargs
        self.assertEqual(set(kwargs), {'embed', 'nonce', 'allowed_mentions'})
        with handle_message_parameters(**kwargs) as params:
            self.assertEqual(params.payload['nonce'], self.raids().nonce(spawn['spawn_id']))
            self.assertIs(params.payload['enforce_nonce'], True)

    def test_nonce_stable_and_at_most_25_chars(self):
        value = '12345678-1234-1234-1234-123456789abc'
        self.assertEqual(self.raids().nonce(value), '1234567812341234123412345')
        self.assertEqual(self.raids().nonce(value), self.raids().nonce(value))
        self.assertLessEqual(len(self.raids().nonce(value)), 25)

    async def test_crash_after_discord_accepts_before_id_saved_restart_no_second_post_no_refund(self):
        spawn = (await self.use())['spawn']
        await self.conn.execute("CREATE TRIGGER crash BEFORE UPDATE OF message_id ON world_spawns "
                                "BEGIN SELECT RAISE(ABORT,'crash after accept'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'crash after accept'):
            await self.raids().announce(self.bot, spawn)
        await self.writer.close()
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = self.bot.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        await self.raids().resume_pending(self.bot)
        await self.raids().announce(self.bot, spawn)
        self.channel.send.assert_awaited_once()
        self.assertEqual(await self.scalar('SELECT post_state FROM world_spawns'), 'attempted')
        self.assertEqual(await self.ticket(), 0)
        self.assertEqual(await self.scalar('SELECT ended FROM world_spawns'), 0)

    async def test_pending_at_startup_posted_once_to_stored_channel(self):
        spawn = (await self.use())['spawn']
        await self.conn.execute("UPDATE guilds SET raid_channel_id='999'")
        await self.raids().resume_pending(self.bot)
        await self.raids().resume_pending(self.bot)
        self.bot.get_channel.assert_called_once_with(int(spawn['channel_id']))
        self.channel.send.assert_awaited_once()

    async def test_send_failure_leaves_attempted_never_retried(self):
        spawn = (await self.use())['spawn']
        self.channel.send.side_effect = TimeoutError('possibly accepted')
        await self.raids().announce(self.bot, spawn)
        await self.raids().resume_pending(self.bot)
        self.channel.send.assert_awaited_once()
        self.assertEqual(await self.scalar('SELECT post_state FROM world_spawns'), 'attempted')
        self.assertEqual(await self.ticket(), 0)

    async def test_embed_sprite_species_time_no_mentions(self):
        spawn = (await self.use())['spawn']
        identity = next(i for i in self.content['identities'] if i['identity_id']==spawn['identity_id'])
        await self.raids().announce(self.bot, spawn)
        kwargs = self.channel.send.await_args.kwargs
        embed = kwargs['embed']
        self.assertIn(identity['name_en'], embed.title + embed.description)
        self.assertIn('1970-01-01 01:16:40 UTC', embed.description)
        self.assertEqual(embed.image.url, identity['sprites']['normal'])
        self.assertEqual(kwargs['allowed_mentions'].to_dict()['parse'], [])

    async def test_double_click_and_receipt_replay_one_spawn(self):
        import asyncio
        a, b = await asyncio.gather(self.use(), self.use())
        self.assertEqual(a, b)
        await self.conn.execute('UPDATE guilds SET raids_enabled=0,raid_channel_id=NULL')
        self.now = 9999
        self.assertEqual(await self.use(checked=None), a)
        self.assertEqual(await self.scalar('SELECT count(*) FROM world_spawns'), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM resource_ledger'), 1)
        self.assertEqual(await self.scalar('SELECT ended FROM world_spawns'), 0)
        receipt = (await self.rows('SELECT * FROM action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']), ('wlt:wlt:0', 'wlt_use', self.pid))

    async def test_excluded_refused_inside_transaction(self):
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
        self.assertEqual(await self.use(), {'status': 'excluded'})
        self.assertEqual(await self.ticket(), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM action_receipts'), 0)

    async def test_foreign_missing_and_forged_receipt_owner_refused(self):
        for session in ({**self.session, 'profile_id': self.other},
                        {**self.session, 'session_id': 'missing'},
                        {**self.session, 'guild_id': 'h'}):
            self.assertEqual(await self.use(session=session), {'status': 'stale'})
        await self.use()
        await self.conn.execute('UPDATE action_receipts SET profile_id=?', (self.other,))
        self.assertEqual(await self.use(), {'status': 'stale'})

    async def test_concurrent_announcers_and_expired_pending_never_duplicate(self):
        import asyncio
        spawn = (await self.use())['spawn']
        await asyncio.gather(self.raids().announce(self.bot, spawn), self.raids().resume_pending(self.bot))
        self.channel.send.assert_awaited_once()
        await self.conn.execute("UPDATE world_spawns SET post_state='pending'")
        self.now = spawn['expires_at']
        await self.raids().resume_pending(self.bot)
        await self.raids().announce(self.bot, spawn)
        self.channel.send.assert_awaited_once()

    async def test_cancelled_send_leaves_attempted_and_no_refund(self):
        import asyncio
        started = asyncio.Event()
        spawn = (await self.use())['spawn']
        async def send(**kwargs):
            started.set()
            await asyncio.Future()
        self.channel.send.side_effect = send
        task = asyncio.create_task(self.raids().announce(self.bot, spawn))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.raids().resume_pending(self.bot)
        self.channel.send.assert_awaited_once()
        self.assertEqual(await self.scalar('SELECT post_state FROM world_spawns'), 'attempted')
        self.assertEqual(await self.ticket(), 0)

    async def test_attempted_commit_failure_sends_nothing_and_pending_can_resume(self):
        spawn = (await self.use())['spawn']
        with patch.object(self.conn, 'commit', side_effect=sqlite3.IntegrityError('claim failed')):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'claim failed'):
                await self.raids().announce(self.bot, spawn)
        self.channel.send.assert_not_awaited()
        self.assertEqual(await self.scalar('SELECT post_state FROM world_spawns'), 'pending')
        await self.raids().resume_pending(self.bot)
        self.channel.send.assert_awaited_once()

    async def test_missing_cached_channel_and_null_sprite_do_not_retry(self):
        spawn = (await self.use())['spawn']
        identity = next(i for i in self.content['identities'] if i['identity_id']==spawn['identity_id'])
        identity['sprites']['normal'] = None
        await self.raids().announce(self.bot, spawn)
        embed = self.channel.send.await_args.kwargs['embed']
        self.assertIsNone(embed.image.url)
        self.assertIn(identity['name_en'], embed.description)
        # A different pending spawn whose channel disappeared still spends its one attempt.
        await self.conn.execute('UPDATE world_spawns SET ended=1')
        await self.conn.execute("UPDATE inventory SET quantity=1 WHERE profile_id=?", (self.pid,))
        self.session['revision'] += 1
        another = (await self.use())['spawn']
        self.bot.get_channel.return_value = None
        await self.raids().announce(self.bot, another)
        await self.raids().resume_pending(self.bot)
        self.channel.send.assert_awaited_once()
        self.assertEqual(await self.scalar('SELECT post_state FROM world_spawns WHERE spawn_id=?',
                                          (another['spawn_id'],)), 'attempted')

    async def test_expire_one_guild_preserves_foreign_then_all_settles_it(self):
        own = (await self.use())['spawn']
        await self.conn.execute("INSERT INTO world_spawns SELECT 'foreign','h',channel_id,pokemon_id,identity_id,"
            "spawned_at,expires_at,NULL,'pending',NULL,0,content_version FROM world_spawns WHERE spawn_id=?",
            (own['spawn_id'],))
        await self.encounter(self.other, 'foreign-encounter', 'revealed', 'foreign')
        await self.conn.execute("INSERT INTO raid_participation VALUES ('h','v','foreign','foreign-encounter',0)")
        await self.writer.run(lambda conn: self.raids().expire(conn, 4600, 'g'))
        self.assertEqual(await self.scalar("SELECT ended FROM world_spawns WHERE spawn_id='foreign'"), 0)
        self.assertEqual(await self.scalar('SELECT count(*) FROM encounters'), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM raid_participation'), 1)
        self.assertEqual(await self.writer.run(lambda conn: self.raids().expire(conn, 4600)),
                         {'spawns': 1, 'encounters': 1, 'participation': 1})

    async def test_spawn_and_expire_require_writer_transaction(self):
        with self.assertRaisesRegex(RuntimeError, 'transaction'):
            await self.raids().spawn(self.conn, self.session, self.now, self.rng, self.content, '789')
        with self.assertRaisesRegex(RuntimeError, 'transaction'):
            await self.raids().expire(self.conn, self.now)


    async def test_participation_deleted_at_expiry_rejoin_impossible_spawn_ended(self):
        spawn = (await self.use())['spawn']
        await self.writer.run(lambda conn: self.raids().join(conn, 'g', 'u', self.now, self.rng, self.content))
        self.now = spawn['expires_at']
        await self.writer.run(lambda conn: self.raids().expire(conn, self.now))
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])
        self.assertEqual(await self.scalar('SELECT ended FROM world_spawns'), 1)
        before = await self.rows('SELECT * FROM encounters')
        self.assertEqual(await self.writer.run(lambda conn: self.raids().join(
            conn, 'g', 'u', self.now, self.rng, self.content)), {'status': 'none'})
        self.assertEqual(await self.rows('SELECT * FROM encounters'), before)
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])

    async def test_delete_spender_nulls_attribution_spawn_and_announcement_kept(self):
        spawn = (await self.use())['spawn']
        await self.raids().announce(self.bot, spawn)
        before = (await self.rows('SELECT * FROM world_spawns'))[0]
        self.assertEqual((before['post_state'], before['message_id']), ('sent', '555'))
        await self.writer.run(lambda conn: deletion.apply(conn, {('g', 'u'): State(delete_ids={self.pid})}))
        retained = {**before, 'spawned_by_profile_id': None}
        self.assertEqual(await self.rows('SELECT * FROM world_spawns'), [retained])
        self.now = spawn['expires_at']
        await self.writer.run(lambda conn: self.raids().expire(conn, self.now))
        self.assertEqual(await self.rows('SELECT * FROM world_spawns'), [{**retained, 'ended': 1}])
        self.channel.send.assert_awaited_once()

    async def test_new_spawn_allowed_after_ended(self):
        first = (await self.use())['spawn']
        self.now = first['expires_at']
        await self.writer.run(lambda conn: self.raids().expire(conn, self.now))
        await self.conn.execute("UPDATE inventory SET quantity=1 WHERE profile_id=?", (self.pid,))
        self.session['revision'] += 1
        second = await self.use()
        self.assertEqual(second['status'], 'spawned')
        self.assertNotEqual(second['spawn']['spawn_id'], first['spawn_id'])
        self.assertEqual(await self.rows('SELECT spawn_id,ended FROM world_spawns ORDER BY spawned_at'),
                         [{'spawn_id': first['spawn_id'], 'ended': 1},
                          {'spawn_id': second['spawn']['spawn_id'], 'ended': 0}])


class RaidJoinTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = RaidSpawnTests.asyncSetUp
    profile = RaidSpawnTests.profile
    scalar = RaidSpawnTests.scalar
    rows = RaidSpawnTests.rows
    encounter = RaidSpawnTests.encounter
    raids = RaidSpawnTests.raids

    async def active(self, *, regional=False):
        identity = next(i for i in self.content['identities']
                        if i['species_id'] == 144 and (i['pokemon_id'] != 144) == regional)
        await self.conn.execute(
            'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,'
            'spawned_at,expires_at,post_state,content_version) '
            "VALUES ('join-spawn','g','789',?,?,1000,4600,'sent','fixture')",
            (identity['pokemon_id'], identity['identity_id']))
        return identity

    async def join(self, *, guild='g', user='u', rng=None):
        self.assertTrue(hasattr(self.raids(), 'join'), 'Raid join service is absent')
        return await self.writer.run(lambda conn: self.raids().join(
            conn, guild, user, self.now, self.rng if rng is None else rng, self.content))

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table}') for table in
                ('profiles', 'world_spawns', 'encounters', 'raid_participation', 'active_effects',
                 'pokedex', 'inventory', 'pokemon', 'catch_attempts', 'candy',
                 'milestone_awards', 'inbox_items', 'action_receipts', 'resource_ledger')}

    async def catch_session(self, encounter_id):
        await self.conn.execute("INSERT INTO inventory VALUES (?,'poke_ball',10)", (self.pid,))
        await self.conn.execute("INSERT INTO inventory VALUES (?,'razz_berry',3)", (self.pid,))
        return {**self.session, 'selection': json.dumps({'encounter_id': encounter_id,
                'encounter_revision': 0, 'ball': 'poke_ball', 'berry': 'razz_berry'})}

    async def throw(self, session, draw=0):
        from unittest.mock import Mock
        from pokewalker.services import catching
        selection = json.loads(session['selection'])
        rng = Mock()
        rng.random.return_value = draw
        result = await self.writer.run(lambda conn: catching.throw(
            conn, selection['encounter_id'], session, selection['encounter_revision'], rng,
            self.now, content=self.content))
        return result, rng

    async def test_join_none_active(self):
        before = await self.snapshot()
        self.assertEqual(await self.join(), {'status': 'none'})
        self.assertEqual(await self.snapshot(), before)
        await self.active()
        for now, ended in ((4600, 0), (4601, 0), (1000, 1)):
            self.now = now
            await self.conn.execute('UPDATE world_spawns SET ended=?', (ended,))
            before = await self.snapshot()
            self.assertIsNone(await self.raids().active_spawn(self.conn, 'g', self.now))
            self.assertEqual(await self.join(), {'status': 'none'})
            self.assertEqual(await self.snapshot(), before)

    async def test_join_once_then_rejoin_returns_same_encounter_no_reroll(self):
        from unittest.mock import Mock
        await self.active()
        rolls = Mock()
        rolls.random.return_value = .5
        rolls.randint.side_effect = [22, 2, 3, 4]
        first = await self.join(rng=rolls)
        self.assertEqual(first['status'], 'new')
        before = await self.snapshot()
        rng = Mock()
        again = await self.join(rng=rng)
        self.assertEqual(again, {**first, 'status': 'joined'})
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(rng.mock_calls, [])
        receipt = (await self.rows("SELECT * FROM action_receipts WHERE action='raid_join'"))[0]
        self.assertEqual((receipt['key'], receipt['profile_id']), ('raid:join-spawn:u', self.pid))
        self.assertEqual(json.loads(receipt['result']), first)
        row = (await self.rows('SELECT * FROM encounters'))[0]
        profile = await profiles.get_profile(self.conn, 'g', 'u')
        self.assertEqual((row['profile_id'], row['state'], row['tier'], row['route_id']),
                         (self.pid, 'revealed', 'Legendary/Mythical', profile['route_id']))
        self.assertEqual((row['level_x2'], row['iv_attack'], row['iv_defense'], row['iv_stamina'],
                          row['gender'], row['shiny']), (44, 2, 3, 4, 'genderless', 0))
        self.assertEqual(rolls.randint.call_args_list[0].args, (20, 25))
        self.assertEqual(row['content_version'], profiles.content_facts(self.content)[0])
        self.assertEqual((await self.rows('SELECT * FROM pokedex'))[0],
                         {'profile_id': self.pid, 'pokemon_id': 144, 'seen_at': 1000, 'caught_at': None})

    async def test_join_after_delete_data_and_reenroll_no_new_encounter(self):
        from datetime import datetime, timezone
        from unittest.mock import Mock
        await self.active()
        await self.join()
        await self.writer.run(lambda conn: deletion.apply(
            conn, {('g', 'u'): State(delete_ids={self.pid})}))
        self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='raid_join'"), [])
        old_pid = self.pid
        enrolled = await self.writer.run(lambda conn: profiles.enroll(
            conn, 'g', 'u', self.content['starters'][0], self.content, self.rng,
            datetime.fromtimestamp(self.now, timezone.utc)))
        self.pid = enrolled['profile_id']
        self.assertNotEqual(self.pid, old_pid)
        before = await self.snapshot()
        rng = Mock()
        self.assertEqual(await self.join(rng=rng), {'status': 'joined', 'encounter_id': None})
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(rng.mock_calls, [])

    async def test_raid_encounter_outside_queue_full_queue_still_joins(self):
        await self.active()
        for i in range(3):
            await self.encounter(self.pid, str(i))
        joined = await self.join()
        self.assertEqual(joined['status'], 'new')
        self.assertEqual(await profiles.queue_size(self.conn, self.pid), 3)
        self.assertEqual(await self.scalar('SELECT count(*) FROM encounters'), 4)

    async def test_identity_exact_form_galarian_stays(self):
        identity = await self.active(regional=True)
        joined = await self.join()
        row = (await self.rows('SELECT * FROM encounters WHERE encounter_id=?', (joined['encounter_id'],)))[0]
        self.assertEqual(row['pokemon_id'], identity['pokemon_id'])
        self.assertEqual((await self.rows('SELECT * FROM pokedex'))[0]['pokemon_id'], 144)
        result, _ = await self.throw(await self.catch_session(joined['encounter_id']))
        self.assertEqual(result.encounter['pokemon_id'], identity['pokemon_id'])
        self.assertIsNone(result.pokemon)

    async def test_lure_applies_and_decrements_on_join(self):
        import random
        from unittest.mock import Mock
        await self.active()
        await self.conn.execute('INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,expires_at,'
                                "receipt_key,remaining_encounters) VALUES ('lure',?,'shiny_lure',0,1,'fixture',1)",
                                (self.pid,))
        rng = Mock(wraps=random.Random(6))
        rng.random.return_value = .01
        joined = await self.join(rng=rng)
        row = (await self.rows('SELECT * FROM encounters'))[0]
        self.assertEqual((row['shiny'], row['lure_id']), (1, 'lure'))
        self.assertEqual(await self.scalar('SELECT remaining_encounters FROM active_effects'), 0)
        await self.join(rng=rng)
        self.assertEqual(await self.scalar('SELECT remaining_encounters FROM active_effects'), 0)
        another = await self.join(user='v', guild='h', rng=rng)
        self.assertEqual(another, {'status': 'none'})
        self.assertEqual(joined['encounter_id'], row['encounter_id'])
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('second','g','second',0)")
        ordinary = await self.join(user='second', rng=rng)
        row = (await self.rows('SELECT * FROM encounters WHERE encounter_id=?', (ordinary['encounter_id'],)))[0]
        self.assertEqual((row['shiny'], row['lure_id']), (0, None))

    async def test_catch_uses_legendary_class_never_flees_pokedex_and_milestone(self):
        from content.balance import load_table
        from pokewalker.domain.cp import catch_probability
        identity = await self.active()
        joined = await self.join()
        session = await self.catch_session(joined['encounter_id'])
        failed, rng = await self.throw(session, .999)
        self.assertEqual(failed.status, 'revealed')
        rng.random.assert_called_once()
        attempt = (await self.rows('SELECT * FROM catch_attempts'))[0]
        self.assertEqual(attempt['fled'], 0)
        self.assertEqual(attempt['p'], catch_probability(.05, failed.encounter['level_x2'], 1, 1.5,
                         multipliers=load_table('cpm')['multipliers']))
        result, _ = await self.throw(session)
        self.assertEqual(result.status, 'caught')
        self.assertEqual((result.candy, result.stardust), (identity['catch_candy'], identity['catch_stardust']))
        self.assertEqual((await self.rows('SELECT * FROM pokedex'))[0]['caught_at'], self.now)
        self.assertIn('first_legendary:first',
                      {r['milestone_id'] for r in await self.rows('SELECT * FROM milestone_awards')})
        self.assertGreater(await self.scalar('SELECT count(*) FROM inbox_items'), 0)
        self.assertEqual(await self.join(), {**joined, 'status': 'joined'})

    async def test_throw_after_expiry_rejected_spends_nothing(self):
        await self.active()
        joined = await self.join()
        session = await self.catch_session(joined['encounter_id'])
        for now in (4600, 4601):
            self.now = now
            before = await self.snapshot()
            writes = self.conn.total_changes
            result, rng = await self.throw(session)
            self.assertEqual(result.status, 'expired')
            self.assertEqual(await self.snapshot(), before)
            self.assertEqual(self.conn.total_changes, writes)
            rng.random.assert_not_called()

    async def test_catch_committed_before_expiry_survives(self):
        await self.active()
        joined = await self.join()
        session = await self.catch_session(joined['encounter_id'])
        self.now = 4599.9
        result, _ = await self.throw(session)
        self.assertEqual(result.status, 'caught')
        pokemon = await self.rows('SELECT * FROM pokemon')
        self.now = 4600
        await self.writer.run(lambda conn: self.raids().expire(conn, self.now))
        self.assertEqual(await self.rows('SELECT * FROM pokemon'), pokemon)
        self.assertEqual(await self.scalar('SELECT state FROM encounters'), 'caught')
        before = await self.snapshot()
        replay, rng = await self.throw(session)
        self.assertEqual(replay.status, 'caught')
        self.assertIsNone(result.pokemon)
        self.assertIsNone(replay.pokemon)
        self.assertEqual(await self.snapshot(), before)
        rng.random.assert_not_called()

    async def test_excluded_and_unenrolled_refused(self):
        await self.active()
        self.assertEqual(await self.join(user='missing'), {'status': 'not_enrolled'})
        await self.join()
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
        before = await self.snapshot()
        self.assertEqual(await self.join(), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_other_guild_spawn_invisible(self):
        before = await self.snapshot()
        none = await self.join(guild='h', user='v')
        self.assertEqual(await self.snapshot(), before)
        await self.active()
        before = await self.snapshot()
        self.assertEqual(await self.join(guild='h', user='v'), none)
        self.assertIsNone(await self.raids().active_spawn(self.conn, 'h', self.now))
        self.assertEqual(await self.snapshot(), before)

    async def test_join_rollback_and_writer_transaction(self):
        await self.active()
        self.assertTrue(hasattr(self.raids(), 'join'), 'Raid join service is absent')
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await self.raids().join(self.conn, 'g', 'u', self.now, self.rng, self.content)
        await self.conn.execute('INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,expires_at,'
                                "receipt_key,remaining_encounters) VALUES ('lure',?,'shiny_lure',0,1,'fixture',1)",
                                (self.pid,))
        before = await self.snapshot()
        with patch.object(self.conn, 'commit', side_effect=sqlite3.IntegrityError('commit failed')):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'commit failed'):
                await self.join()
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.join())['status'], 'new')
        self.assertEqual(await self.scalar('SELECT remaining_encounters FROM active_effects'), 0)

    async def test_concurrent_join_once_and_existing_pokedex_dates_preserved(self):
        import asyncio
        await self.active()
        await self.conn.execute('INSERT INTO pokedex VALUES (?,144,1,2)', (self.pid,))
        first, second = await asyncio.gather(self.join(), self.join())
        self.assertEqual((first['status'], second['status']), ('new', 'joined'))
        self.assertEqual(first['encounter_id'], second['encounter_id'])
        self.assertEqual(await self.scalar('SELECT count(*) FROM encounters'), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM raid_participation'), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts WHERE action='raid_join'"), 1)
        self.assertEqual((await self.rows('SELECT * FROM pokedex'))[0],
                         {'profile_id': self.pid, 'pokemon_id': 144, 'seen_at': 1, 'caught_at': 2})


    async def test_balls_thrown_before_expiry_stay_spent_ledger_intact(self):
        await self.active()
        joined = await self.join()
        session = await self.catch_session(joined['encounter_id'])
        result, _ = await self.throw(session, .999)
        self.assertEqual(result.status, 'revealed')
        inventory = await self.rows('SELECT * FROM inventory')
        ledger = await self.rows('SELECT * FROM resource_ledger')
        receipts = await self.rows('SELECT * FROM action_receipts')
        self.assertEqual([(r['resource_id'], r['delta']) for r in ledger if r['reason'] == 'catch_spend'],
                         [('poke_ball', -1), ('razz_berry', -1)])
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='poke_ball'"), 9)
        self.assertEqual(await self.scalar('SELECT count(*) FROM catch_attempts'), 1)
        self.now = 4600
        await self.writer.run(lambda conn: self.raids().expire(conn, self.now))
        self.assertEqual(await self.rows('SELECT * FROM encounters'), [])
        self.assertEqual(await self.rows('SELECT * FROM catch_attempts'), [])
        self.assertEqual(await self.rows('SELECT * FROM inventory'), inventory)
        self.assertEqual(await self.rows('SELECT * FROM resource_ledger'), ledger)
        self.assertEqual(await self.rows('SELECT * FROM action_receipts'), receipts)
        self.assertEqual(await self.rows('PRAGMA foreign_key_check'), [])

    async def test_delete_data_before_expiry_keeps_participation_until_expiry(self):
        await self.test_join_after_delete_data_and_reenroll_no_new_encounter()
        retained = await self.rows('SELECT * FROM raid_participation')
        self.assertEqual(len(retained), 1)
        self.assertEqual((retained[0]['guild_id'], retained[0]['user_id'], retained[0]['encounter_id']),
                         ('g', 'u', None))
        self.now = 4599.9
        await self.writer.run(lambda conn: self.raids().expire(conn, self.now))
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), retained)
        self.now = 4600
        await self.writer.run(lambda conn: self.raids().expire(conn, self.now))
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])
        self.assertEqual(await self.join(), {'status': 'none'})


class RaidBagTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = RaidWalkerTests.asyncSetUp
    rows = RaidWalkerTests.rows
    enroll = RaidWalkerTests.enroll
    open = RaidWalkerTests.open
    scalar = test_db.DatabaseTests.scalar

    def interaction(self, **who):
        from unittest.mock import AsyncMock, Mock
        interaction = RaidWalkerTests.interaction(self, **who)
        if not hasattr(self, 'channel'):
            self.channel = SimpleNamespace(id=789, guild=SimpleNamespace(id=123),
                permissions_for=Mock(return_value=SimpleNamespace(embed_links=True, send_messages=True)),
                send=AsyncMock(return_value=SimpleNamespace(id=555)))
            self.bot.get_channel = Mock(return_value=self.channel)
        interaction.guild = SimpleNamespace(id=interaction.guild_id, me=object(),
                                            get_channel=Mock(return_value=self.channel))
        return interaction

    async def prepare(self):
        await self.enroll()
        _, session = await self.open()
        self.pid = session['profile_id']
        await self.conn.execute("UPDATE guilds SET raids_enabled=1,raid_channel_id='789' WHERE guild_id='123'")
        await self.conn.execute("INSERT INTO inventory VALUES (?,'world_legendary_ticket',1)", (self.pid,))
        return session

    async def click(self, action, **who):
        session = (await self.rows())[0]
        interaction = self.interaction(**who)
        await self.walker.route(interaction, f"pw:v1:{session['session_id']}:{session['revision']}:{action}")
        return interaction

    async def ticket(self):
        return await self.scalar("SELECT quantity FROM inventory WHERE profile_id=? AND item_id='world_legendary_ticket'",
                                 (self.pid,))

    async def test_wlt_confirm_then_use_spawns_and_announces_after_commit(self):
        await self.prepare()
        screen = await self.click('wlt_confirm')
        screen.edit_original_response.assert_awaited_once()
        self.assertIn('Spawns a World Legendary in <#789> for 60 minutes; cannot be undone',
                      screen.edit_original_response.await_args.kwargs['embed'].description)
        self.assertEqual(await self.ticket(), 1)
        self.channel.send.assert_not_awaited()

        async def sent(**kwargs):
            self.assertFalse(self.conn.in_transaction)
            self.assertEqual(await self.ticket(), 0)
            spawn = (await self.rows('SELECT * FROM world_spawns'))[0]
            self.assertEqual((spawn['spawned_at'], spawn['expires_at'], spawn['post_state']),
                             (1000, 4600, 'attempted'))
            self.assertEqual(kwargs['allowed_mentions'].to_dict()['parse'], [])
            return SimpleNamespace(id=555)

        self.channel.send.side_effect = sent
        screen = await self.click('wlt_use')
        screen.edit_original_response.assert_awaited_once()
        spawn = (await self.rows('SELECT * FROM world_spawns'))[0]
        identity = next(i for i in self.bot.content['identities'] if i['identity_id'] == spawn['identity_id'])
        self.assertIn(f"Spawned {identity['name_en']} until 1970-01-01 01:16:40 UTC",
                      screen.edit_original_response.await_args.kwargs['embed'].description)
        self.assertEqual((spawn['post_state'], spawn['message_id']), ('sent', '555'))
        self.channel.send.assert_awaited_once()

    async def test_missing_permission_passes_none_and_keeps_ticket(self):
        from pokewalker.services import raids
        await self.prepare()
        for kind in ('embed_links', 'send_messages', 'missing', 'foreign'):
            with self.subTest(kind=kind):
                await self.click('wlt_confirm')
                self.channel.permissions_for.return_value = SimpleNamespace(
                    embed_links=kind != 'embed_links', send_messages=kind != 'send_messages')
                self.channel.guild.id = 999 if kind == 'foreign' else 123
                interaction = self.interaction()
                if kind == 'missing':
                    interaction.guild.get_channel.return_value = None
                session = (await self.rows())[0]
                with patch.object(raids, 'spawn', wraps=raids.spawn) as spawning:
                    await self.walker.route(interaction,
                        f"pw:v1:{session['session_id']}:{session['revision']}:wlt_use")
                spawning.assert_awaited_once()
                self.assertIsNone(spawning.call_args.args[-1])
                self.assertIn('EMBED_LINKS and SEND_MESSAGES', interaction.followup.send.await_args.args[0])
                self.assertEqual(await self.ticket(), 1)
                self.assertEqual(await self.rows('SELECT * FROM world_spawns'), [])
        self.channel.send.assert_not_awaited()

    async def test_handler_passes_checked_channel_id(self):
        from pokewalker.services import raids
        await self.prepare()
        await self.click('wlt_confirm')
        with patch.object(raids, 'spawn', wraps=raids.spawn) as spawning:
            screen = await self.click('wlt_use')
        spawning.assert_awaited_once()
        self.assertEqual(spawning.call_args.args[-1], 789)
        screen.guild.get_channel.assert_called_once_with(789)
        self.channel.permissions_for.assert_called_once_with(screen.guild.me)

    async def test_channel_changed_text_ticket_kept(self):
        from pokewalker.services import raids
        await self.prepare()
        await self.click('wlt_confirm')
        original = raids.spawn

        async def changed(conn, *args):
            await conn.execute("UPDATE guilds SET raid_channel_id='999' WHERE guild_id='123'")
            return await original(conn, *args)

        with patch.object(raids, 'spawn', side_effect=changed):
            screen = await self.click('wlt_use')
        self.assertEqual(screen.followup.send.await_args.args[0], 'The raid channel changed; try again.')
        self.assertEqual(await self.ticket(), 1)
        self.assertEqual(await self.rows('SELECT * FROM world_spawns'), [])
        self.channel.send.assert_not_awaited()

    async def test_use_button_only_when_held(self):
        await self.prepare()
        for quantity in (1, 0):
            await self.conn.execute("UPDATE inventory SET quantity=? WHERE profile_id=? AND item_id='world_legendary_ticket'",
                                    (quantity, self.pid))
            screen = await self.click('bag')
            view = screen.edit_original_response.await_args.kwargs['view']
            labels = [item.label for item in view.children]
            self.assertEqual('Use World Legendary Ticket' in labels, bool(quantity))
            self.assertLessEqual(len({item._rendered_row for item in view.children}), 5)
            self.assertLessEqual(max(item._rendered_row for item in view.children), 4)

    async def test_other_user_cannot_use(self):
        await self.prepare()
        await self.click('wlt_confirm')
        before = await self.rows()
        for who in ({'user': 999}, {'guild': 999}):
            screen = await self.click('wlt_use', **who)
            self.assertIn('not yours', screen.followup.send.await_args.args[0])
            self.assertEqual(await self.rows(), before)
            self.assertEqual(await self.ticket(), 1)
        self.channel.send.assert_not_awaited()

    async def test_refusals_and_skipped_confirmation_preserve_ticket(self):
        await self.prepare()
        screen = await self.click('wlt_use')
        self.assertEqual(screen.followup.send.await_args.args[0],
                         'Preview the World Legendary Ticket before confirming.')
        for sql, expected in (
            ("UPDATE guilds SET raids_enabled=0", 'Raids are turned off in this server.'),
            ("UPDATE guilds SET raids_enabled=1,raid_channel_id=NULL", 'No raid channel is configured.'),
            ("UPDATE guilds SET raid_channel_id='789'", None),
        ):
            await self.conn.execute(sql)
            await self.click('wlt_confirm')
            screen = await self.click('wlt_use')
            if expected:
                self.assertEqual(screen.followup.send.await_args.args[0], expected)
                self.assertEqual(await self.ticket(), 1)
        await self.conn.execute("UPDATE inventory SET quantity=1 WHERE profile_id=? AND item_id='world_legendary_ticket'", (self.pid,))
        await self.click('wlt_confirm')
        screen = await self.click('wlt_use')
        self.assertEqual(screen.followup.send.await_args.args[0], 'A World Legendary is already active in this server.')
        self.assertEqual(await self.ticket(), 1)

    async def test_commit_failure_does_not_announce(self):
        await self.prepare()
        await self.click('wlt_confirm')
        with patch.object(self.conn, 'commit', side_effect=sqlite3.IntegrityError('commit failed')):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'commit failed'):
                await self.click('wlt_use')
        self.assertEqual(await self.ticket(), 1)
        self.assertEqual(await self.rows('SELECT * FROM world_spawns'), [])
        self.channel.send.assert_not_awaited()

    async def test_render_functions_do_no_io(self):
        from pokewalker.bot import bag
        from content.balance import load_table
        state = dict(inventory={'world_legendary_ticket': 1}, rates=load_table('conversion_rates')['stardust_per_unit'],
            session={'session_id': 'abcd', 'revision': 0}, selection={}, units=0, limit=250,
            stardust=0, content=self.bot.content, can_expand=True, star_piece=None)
        with patch.object(self.conn, 'execute', side_effect=AssertionError('renderer DB I/O')), \
             patch.object(self.writer, 'run', side_effect=AssertionError('renderer writer I/O')):
            for mode in ('bag', 'wlt_confirm'):
                rendered = bag.render({**state, 'mode': mode})
                self.assertIsNotNone(rendered['embed'])
                self.assertTrue(rendered['view'].children)


class RaidStartupTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = RaidSpawnTests.asyncSetUp
    profile = RaidSpawnTests.profile
    raids = RaidSpawnTests.raids
    use = RaidSpawnTests.use

    async def client(self):
        from unittest.mock import AsyncMock, Mock
        from pokewalker.bot.client import WalkerBot
        from pokewalker.config import Settings, Secret
        bot = WalkerBot(Settings(Secret('synthetic'), owner_ids=frozenset({123})), clock=lambda: 999999)
        bot.writer, bot.content = self.writer, self.content
        bot.walker.clock = lambda: self.now
        bot.get_channel = self.bot.get_channel
        bot.reactions = SimpleNamespace(startup_sweep=AsyncMock())
        bot.heartbeat.start = Mock()
        bot._sweep_once = AsyncMock()
        self.addAsyncCleanup(bot.drain)
        return bot

    async def test_resume_pending_runs_once_on_ready_not_while_stopping(self):
        from unittest.mock import AsyncMock
        from pokewalker.services import raids
        bot = await self.client()
        order = []
        async def sweep():
            order.append('sweep')
        async def resume(client):
            self.assertIs(client, bot)
            order.append('resume')
        bot.reactions.startup_sweep.side_effect = sweep
        with patch.object(raids, 'resume_pending', side_effect=resume) as resuming:
            await bot.on_ready()
            await bot.on_ready()
        self.assertEqual(order, ['sweep', 'resume'])
        resuming.assert_awaited_once_with(bot)
        stopped = await self.client()
        stopped._stopping = True
        with patch.object(raids, 'resume_pending', AsyncMock()) as resuming:
            await stopped.on_ready()
        resuming.assert_not_awaited()
        stopping = await self.client()
        async def stop_in_sweep():
            stopping._stopping = True
        stopping.reactions.startup_sweep.side_effect = stop_in_sweep
        with patch.object(raids, 'resume_pending', AsyncMock()) as resuming:
            await stopping.on_ready()
        resuming.assert_not_awaited()

    async def test_resume_pending_uses_walker_clock_not_bot_monotonic(self):
        spawn = (await self.use())['spawn']
        bot = await self.client()
        self.assertLess(spawn['expires_at'], bot.clock())
        await bot.on_ready()
        await bot.on_ready()
        self.channel.send.assert_awaited_once()


class RaidCommandTests(unittest.IsolatedAsyncioTestCase):
    interaction = RaidWalkerTests.interaction
    rows = RaidWalkerTests.rows
    enroll = RaidWalkerTests.enroll
    click = RaidWalkerTests.click
    current = RaidWalkerTests.current

    async def asyncSetUp(self):
        await RaidWalkerTests.asyncSetUp(self)
        self.profile = await self.enroll()
        self.now = 1000
        self.walker.clock = lambda: self.now
        self.bot.clock = lambda: 999999

    async def active(self):
        identity = next(i for i in self.bot.content['identities'] if i['pokemon_id'] == 144)
        await self.writer.run(lambda conn: conn.execute(
            'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,'
            'spawned_at,expires_at,post_state,content_version) '
            "VALUES ('command-spawn','123','789',?,?,1000,4600,'sent','fixture')",
            (identity['pokemon_id'], identity['identity_id'])))

    def command(self):
        import importlib
        try:
            return importlib.import_module('pokewalker.bot.raid').command(self.bot)
        except ModuleNotFoundError:
            self.fail('M8.3b raid command is absent')

    async def invoke(self, **who):
        interaction = self.interaction(**who)
        await self.command().callback(interaction)
        return interaction

    async def session(self):
        return (await self.rows())[-1]

    async def raid_row(self):
        return (await self.rows('SELECT * FROM encounters WHERE raid_spawn_id IS NOT NULL'))[0]

    def rendered(self, interaction):
        return interaction.edit_original_response.await_args.kwargs

    async def pending_ordinary_catch(self):
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE encounters SET pokemon_id=25,shiny=0,tier='Common',level_x2=40"))
        await self.walker.open(self.interaction())
        await self.click(await self.session(), 'open_encounter')
        session = await self.session()
        with patch.object(self.walker.rng, 'random', return_value=0):
            await self.click(session, 'throw')
        encounter_id = json.loads(session['selection'])['encounter_id']
        self.assertEqual((await self.rows('SELECT state FROM encounters WHERE encounter_id=?',
                                         (encounter_id,)))[0]['state'], 'caught')
        await self.writer.run(lambda conn: conn.execute(
            'DELETE FROM pokemon WHERE source_encounter_id=?', (encounter_id,)))
        return encounter_id

    async def test_raid_while_stopping_gets_restart_reply(self):
        # Audit fix: like /walker, /raid must answer during the shutdown drain instead of failing.
        before = await self.rows()
        self.bot._stopping = True
        shown = await self.invoke()
        self.assertIn('restarting', self.rendered(shown)['content'])
        self.assertEqual(await self.rows(), before)

    async def test_raid_with_pending_catch_opens_menu_without_joining(self):
        encounter_id = await self.pending_ordinary_catch()
        await self.active()
        await self.writer.run(lambda conn: conn.execute(
            'INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,expires_at,'
            "receipt_key,remaining_encounters) VALUES ('lure',?,'shiny_lure',0,1,'fixture',1)",
            (self.profile['profile_id'],)))
        before = await RaidWalkerTests.snapshot(self)
        rendered = self.rendered(await self.invoke())
        self.assertEqual([b.label for b in rendered['view'].children], ['Done', 'Send for research'])
        session = await self.session()
        self.assertEqual(json.loads(session['selection']),
                         {'encounter_id': encounter_id, 'storage_limit': 250})
        self.assertEqual((session['revision'], session['expires_at']), (0, self.now + 900))
        after = await RaidWalkerTests.snapshot(self)
        self.assertEqual({k: v for k, v in after.items() if k != 'sessions'},
                         {k: v for k, v in before.items() if k != 'sessions'})
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])
        self.assertEqual(await self.rows('SELECT * FROM encounters WHERE raid_spawn_id IS NOT NULL'), [])
        self.assertEqual((await self.rows('SELECT remaining_encounters FROM active_effects'))[0],
                         {'remaining_encounters': 1})
        await self.click(session, 'ack')
        await self.invoke()
        self.assertEqual(len(await self.rows('SELECT * FROM raid_participation')), 1)
        self.assertEqual(len(await self.rows('SELECT * FROM encounters WHERE raid_spawn_id IS NOT NULL')), 1)
        self.assertEqual((await self.rows('SELECT remaining_encounters FROM active_effects'))[0],
                         {'remaining_encounters': 0})

    async def test_raid_pending_catch_excluded_refused_first(self):
        await self.pending_ordinary_catch()
        await self.active()
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)"))
        before = await RaidWalkerTests.snapshot(self)
        self.assertEqual(self.rendered(await self.invoke())['content'], self.module.EXCLUDED)
        self.assertEqual(await RaidWalkerTests.snapshot(self), before)
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])

    async def test_raid_legendary_catch_pending_survives_expiry_and_sweep(self):
        from pokewalker.bot.client import WalkerBot
        await self.active()
        await self.invoke()
        with patch.object(self.walker.rng, 'random', return_value=0):
            await self.click(await self.session(), 'throw')
        encounter = await self.raid_row()
        self.assertEqual(encounter['state'], 'caught')
        await self.writer.run(lambda conn: conn.execute(
            'DELETE FROM pokemon WHERE source_encounter_id=?', (encounter['encounter_id'],)))
        self.now += 7200
        bot = WalkerBot(SimpleNamespace())
        bot.writer, bot.content, bot.walker = self.writer, self.bot.content, self.walker
        self.addAsyncCleanup(bot.drain)
        await bot._sweep_once()
        self.assertEqual(await self.raid_row(), encounter)
        self.assertEqual((await self.rows('SELECT ended FROM world_spawns'))[0], {'ended': 1})
        self.assertEqual(await self.rows('SELECT * FROM pokemon WHERE source_encounter_id=?',
                                         (encounter['encounter_id'],)), [])
        self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='research'"), [])
        rendered = self.rendered(await self.invoke())
        self.assertEqual([b.label for b in rendered['view'].children], ['Done', 'Send for research'])
        self.assertEqual(json.loads((await self.session())['selection'])['encounter_id'],
                         encounter['encounter_id'])
        await self.click(await self.session(), 'ack')
        self.assertEqual((await self.rows('SELECT state FROM pokemon WHERE source_encounter_id=?',
                                         (encounter['encounter_id'],)))[0], {'state': 'owned'})
        self.assertEqual((await self.raid_row())['acknowledged_at'], self.now)

    async def test_raid_none_active_explains(self):
        for guild in (123, 999):
            screen = await self.invoke(guild=guild)
            self.assertEqual(self.rendered(screen)['content'], 'No World Legendary is active here.')
        await self.active()
        screen = await self.invoke(guild=999)
        self.assertEqual(self.rendered(screen)['content'], 'No World Legendary is active here.')
        self.assertEqual(await self.rows(), [])
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])

    async def test_first_raid_renders_catch_panel_with_notice(self):
        await self.active()
        screen = await self.invoke()
        rendered = self.rendered(screen)
        self.assertEqual(rendered['embed'].title, 'Wild encounter')
        self.assertIn('Articuno', rendered['embed'].description)
        self.assertIn('World Legendary · ends 1970-01-01 01:16:40 UTC', rendered['embed'].description)
        self.assertEqual({b.label for b in rendered['view'].children},
                         {'Ball', 'Berry', 'Throw', 'Later', 'Run'})
        self.assertTrue(rendered['view'].is_finished())
        session, encounter = await self.session(), await self.raid_row()
        self.assertEqual((session['guild_id'], session['user_id'], session['profile_id'], session['revision']),
                         ('123', '456', self.profile['profile_id'], 0))
        self.assertEqual(json.loads(session['selection']), {'encounter_id': encounter['encounter_id'],
                         'ball': 'poke_ball', 'berry': None, 'encounter_revision': encounter['revision']})
        self.assertEqual(len(await self.rows('SELECT * FROM raid_participation')), 1)
        self.assertEqual(rendered['allowed_mentions'].to_dict(), {'parse': []})

    async def test_raid_catch_rerenders_keep_world_legendary_line(self):
        await self.active()
        await self.invoke()
        for action, values in (('select_ball', None), ('pick_ball', ['poke_ball']),
                               ('select_berry', None), ('pick_berry', ['none'])):
            rendered = self.rendered(await self.click(await self.session(), action, values))
            self.assertEqual(rendered['embed'].title, 'Wild encounter', action)
            self.assertIn('World Legendary · ends 1970-01-01 01:16:40 UTC', rendered['embed'].description, action)

    async def test_reopen_unresolved_renders_same_encounter_catch_panel(self):
        await self.active()
        await self.invoke()
        for state in ('queued', 'revealed'):
            await self.writer.run(lambda conn: conn.execute(
                'UPDATE encounters SET state=? WHERE raid_spawn_id IS NOT NULL', (state,)))
            before = await self.raid_row()
            with patch.object(self.walker.rng, 'random', side_effect=AssertionError('rerolled')):
                screen = await self.invoke()
            self.assertEqual(self.rendered(screen)['embed'].title, 'Wild encounter')
            self.assertEqual(await self.raid_row(), before)
            self.assertEqual(json.loads((await self.session())['selection'])['encounter_id'], before['encounter_id'])
        self.assertEqual(len(await self.rows('SELECT * FROM raid_participation')), 1)

    async def assert_terminal(self, caught):
        await self.active()
        await self.invoke()
        session = await self.session()
        if caught:
            await self.writer.run(lambda conn: conn.execute(
                "INSERT INTO inventory VALUES (?,'master_ball',1)", (self.profile['profile_id'],)))
            await self.click(session, 'pick_ball', ['master_ball'])
            session = await self.current(session)
            await self.click(session, 'throw')
            await self.click(await self.current(session), 'master_confirm')
        else:
            await self.writer.run(lambda conn: conn.execute(
                'UPDATE encounters SET shiny=0 WHERE raid_spawn_id IS NOT NULL'))
            await self.click(session, 'run')
        before = await self.raid_row()
        self.assertEqual(before['state'], 'caught' if caught else 'ran')
        screen = await self.invoke()
        rendered = self.rendered(screen)
        self.assertEqual(rendered['embed'].title, 'Encounter result')
        self.assertIn('Result: ' + before['state'], rendered['embed'].description)
        self.assertEqual([b.label for b in rendered['view'].children],
                         ['Done', 'Send for research'] if caught else ['Done'])
        await self.click(await self.session(), 'ack')
        after = await self.raid_row()
        self.assertEqual(after['acknowledged_at'], self.now)
        self.assertEqual({k: v for k, v in after.items() if k != 'acknowledged_at'},
                         {k: v for k, v in before.items() if k != 'acknowledged_at'})

    async def test_reopen_after_catch_renders_terminal_without_catch_controls(self):
        await self.assert_terminal(True)

    async def test_reopen_after_run_renders_terminal_without_catch_controls(self):
        await self.assert_terminal(False)

    async def test_catch_send_raid_reopen_legendary_unlock_then_done(self):
        await self.active()
        await self.invoke()
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO inventory VALUES (?,'master_ball',1)", (self.profile['profile_id'],)))
        await self.click(await self.session(), 'pick_ball', ['master_ball'])
        await self.click(await self.session(), 'throw')
        await self.click(await self.session(), 'master_confirm')
        await self.invoke()
        session = await self.session()
        rendered = self.rendered(await self.click(session, 'catch_send'))
        self.assertIn('Articuno', rendered['embed'].description)
        self.assertIn('Legendary/Mythical', rendered['embed'].description)
        self.assertEqual([b.label for b in rendered['view'].children], ['Unlock', 'Cancel'])
        self.assertEqual(json.loads((await self.current(session))['selection'])['caught'],
                         {'encounter_id': (await self.raid_row())['encounter_id'], 'pending': True})
        rendered = self.rendered(await self.click(await self.current(session), 'storage_send_unlock'))
        self.assertIn('Legendary/Mythical', rendered['embed'].description)
        self.assertIn('+1 Articuno Candy', rendered['embed'].description)
        before = await self.rows('SELECT * FROM pokemon')
        candy_before = sum(r['quantity'] for r in await self.rows('SELECT * FROM candy'))
        rendered = self.rendered(await self.click(await self.current(session), 'storage_send_confirm'))
        self.assertEqual(rendered['embed'].description, 'Sent 1 Pokémon · +1 Articuno Candy · 0 Stardust.')
        self.assertEqual([b.label for b in rendered['view'].children], ['Done'])
        self.assertTrue(rendered['view'].children[0].custom_id.endswith(':ack'))
        sent = (await self.rows("SELECT * FROM pokemon WHERE state='sent'"))[0]
        self.assertEqual(sent['source_encounter_id'], (await self.raid_row())['encounter_id'])
        self.assertEqual([p for p in await self.rows('SELECT * FROM pokemon') if p['state'] == 'owned'],
                         [p for p in before if p['pokemon_uid'] != sent['pokemon_uid']])
        self.assertEqual(sum(r['quantity'] for r in await self.rows('SELECT * FROM candy')), candy_before + 1)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='research'")), 1)
        rendered = self.rendered(await self.click(await self.current(session), 'ack'))
        self.assertEqual(rendered['embed'].title, 'Walker')
        self.assertEqual((await self.raid_row())['acknowledged_at'], self.now)

    async def test_reopen_after_delete_and_reenroll_explains_already_joined(self):
        await self.active()
        await self.invoke()
        await self.writer.run(lambda conn: deletion.apply(conn,
            {('123', '456'): State(delete_ids={self.profile['profile_id']})}))
        self.profile = await self.enroll()
        self.assertIsNone((await self.rows('SELECT * FROM raid_participation'))[0]['encounter_id'])
        with patch.object(self.walker.rng, 'random', side_effect=AssertionError('rerolled')):
            screen = await self.invoke()
        self.assertEqual(self.rendered(screen)['content'],
                         'You already joined this World Legendary; it can be joined once.')
        self.assertEqual(await self.rows('SELECT * FROM encounters WHERE raid_spawn_id IS NOT NULL'), [])
        self.assertEqual(await self.rows(), [])

    async def test_missing_and_foreign_encounters_are_indistinguishable(self):
        await self.active()
        await self.invoke()
        original = await self.raid_row()
        from datetime import datetime, timezone
        foreign = await self.writer.run(lambda conn: profiles.enroll(
            conn, 999, 888, 1, self.bot.content, self.walker.rng,
            datetime.fromtimestamp(self.now, timezone.utc)))
        await self.writer.run(lambda conn: conn.execute(
            'UPDATE encounters SET profile_id=? WHERE encounter_id=?',
            (foreign['profile_id'], original['encounter_id'])))
        screen = await self.invoke()
        foreign_reply = self.rendered(screen)
        await self.writer.run(lambda conn: conn.execute('DELETE FROM encounters WHERE encounter_id=?',
                                                       (original['encounter_id'],)))
        screen = await self.invoke()
        missing_reply = self.rendered(screen)
        self.assertEqual(missing_reply['content'], foreign_reply['content'])
        self.assertEqual(missing_reply['allowed_mentions'].to_dict(), foreign_reply['allowed_mentions'].to_dict())
        self.assertNotIn('embed', missing_reply)
        self.assertNotIn('embed', foreign_reply)
        self.assertEqual(foreign_reply['content'],
                         'You already joined this World Legendary; it can be joined once.')
        self.assertEqual(len(await self.rows()), 1)

    async def test_session_buttons_route_through_walker_router(self):
        from pokewalker.bot.client import WalkerItem
        await self.active()
        rendered = self.rendered(await self.invoke())
        later = next(b for b in rendered['view'].children if b.label == 'Later')
        before = await self.rows()
        for who in ({'user': 999}, {'guild': 999}):
            foreign = self.interaction(**who)
            await WalkerItem(later).callback(foreign)
            self.assertIn('not yours', foreign.followup.send.await_args.args[0])
            foreign.edit_original_response.assert_not_awaited()
            self.assertEqual(await self.rows(), before)
        interaction = self.interaction()
        with patch.object(self.walker, 'route', wraps=self.walker.route) as routing:
            await WalkerItem(later).callback(interaction)
        routing.assert_awaited_once_with(interaction, later.custom_id)
        self.assertEqual(self.rendered(interaction)['embed'].title, 'Walker')
        self.assertEqual((await self.raid_row())['state'], 'revealed')

    async def test_raid_uses_walker_clock(self):
        await self.active()
        self.now = 4500
        await self.invoke()
        self.assertEqual((await self.session())['expires_at'], 5400)
        self.assertEqual((await self.raid_row())['created_at'], 4500)
        self.now = 4600
        self.assertEqual(self.rendered(await self.invoke())['content'], 'No World Legendary is active here.')

    async def test_command_guild_only_and_ephemeral(self):
        from pokewalker.bot.client import WalkerBot
        from pokewalker.config import Settings, Secret
        self.assertTrue(self.command().guild_only)
        client = WalkerBot(Settings(Secret('synthetic'), owner_ids=frozenset({123})))
        self.addAsyncCleanup(client.drain)
        self.assertIsNotNone(client.tree.get_command('raid'))
        manifest = client.command_manifest_hash()
        client.tree.remove_command('raid')
        self.assertNotEqual(client.command_manifest_hash(), manifest)
        original_run = self.writer.run
        screen = self.interaction()
        async def deferred_first(fn, **kwargs):
            screen.response.defer.assert_awaited_once_with(ephemeral=True)
            return await original_run(fn, **kwargs)
        with patch.object(self.writer, 'run', side_effect=deferred_first):
            await self.command().callback(screen)
        dm = self.interaction(guild=None)
        with patch.object(self.writer, 'run', side_effect=AssertionError('DM database access')):
            await self.command().callback(dm)
        dm.response.defer.assert_awaited_once_with(ephemeral=True)
        self.assertEqual(self.rendered(dm)['content'], 'Use /raid in a server.')

    async def test_unenrolled_excluded_and_opted_out_do_not_join(self):
        await self.active()
        self.assertIn('enroll', self.rendered(await self.invoke(user=999))['content'])
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)"))
        self.assertIn('excluded', self.rendered(await self.invoke())['content'])
        await self.writer.run(lambda conn: conn.execute('DELETE FROM restrictions'))
        await self.writer.run(lambda conn: deletion.apply(conn,
            {('123', '456'): State(delete_ids={self.profile['profile_id']}, opted_out=True)}))
        self.assertIn('opt-in', self.rendered(await self.invoke())['content'])
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])
        self.assertEqual(await self.rows(), [])


class RaidSweepTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = RaidSpawnTests.asyncSetUp
    profile = RaidSpawnTests.profile
    raids = RaidSpawnTests.raids
    use = RaidSpawnTests.use
    rows = RaidSpawnTests.rows

    def client(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(SimpleNamespace(), clock=lambda: 999999)
        bot.writer, bot.content = self.writer, self.content
        bot.walker.rng = self.rng
        bot.walker.clock = lambda: self.now
        self.addAsyncCleanup(bot.drain)
        return bot

    async def test_sweep_runs_expire_with_settle_in_one_job(self):
        from pokewalker.services import gyms, raids
        bot = self.client()
        await self.use()
        await self.conn.execute("INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,"
                                "spawned_at,expires_at,post_state,content_version) "
                                "SELECT 'foreign','h',channel_id,pokemon_id,identity_id,spawned_at,expires_at,"
                                "post_state,content_version FROM world_spawns")
        self.now = 4600
        order = []
        original_settle, original_expire = gyms.settle, raids.expire
        async def settle(conn, now, rng, content):
            self.assertIs(conn, self.conn)
            self.assertTrue(conn.in_transaction)
            order.append(('settle', now))
            return await original_settle(conn, now, rng, content)
        async def expire(conn, now):
            self.assertIs(conn, self.conn)
            self.assertTrue(conn.in_transaction)
            order.append(('expire', now))
            return await original_expire(conn, now)
        with patch.object(gyms, 'settle', side_effect=settle), \
             patch.object(raids, 'expire', side_effect=expire), \
             patch.object(self.writer, 'run', wraps=self.writer.run) as run:
            await bot._sweep_once()
        run.assert_awaited_once()
        self.assertEqual(order, [('settle', 4600), ('expire', 4600)])
        self.assertEqual({r['ended'] for r in await self.rows('SELECT ended FROM world_spawns')}, {1})
        # Expiry failure must roll back earlier gym work in the same tick.
        async def mutate(conn, *args):
            await conn.execute('UPDATE guilds SET raids_enabled=0')
        before = await self.rows('SELECT * FROM guilds')
        with patch.object(gyms, 'settle', side_effect=mutate), \
             patch.object(raids, 'expire', side_effect=RuntimeError('expiry failed')):
            with self.assertRaisesRegex(RuntimeError, 'expiry failed'):
                await bot._sweep_once()
        self.assertEqual(await self.rows('SELECT * FROM guilds'), before)

    async def test_sweep_expiry_uses_walker_clock_not_bot_monotonic(self):
        from unittest.mock import Mock
        spawn = (await self.use())['spawn']
        bot = self.client()
        self.assertGreater(bot.clock(), spawn['expires_at'])
        bot.walker.clock = Mock(return_value=4599.9)
        await bot._sweep_once()
        bot.walker.clock.assert_called_once_with()
        self.assertEqual((await self.rows('SELECT ended FROM world_spawns'))[0]['ended'], 0)
        bot.walker.clock = Mock(return_value=4600)
        await bot._sweep_once()
        bot.walker.clock.assert_called_once_with()
        self.assertEqual((await self.rows('SELECT ended FROM world_spawns'))[0]['ended'], 1)

    async def pending_catch(self):
        await RaidSchemaTests.encounter(self, self.pid, 'pending', state='caught')
        await self.conn.execute("UPDATE encounters SET pokemon_id=25,shiny=0,resolved_at=1000 "
                                "WHERE encounter_id='pending'")

    async def auto_send_state(self):
        return {table: await self.rows(f'SELECT * FROM {table}') for table in
                ('encounters', 'pokemon', 'candy', 'action_receipts', 'resource_ledger', 'guilds')}

    async def test_sweep_runs_auto_send_after_expire_in_one_job(self):
        from unittest.mock import Mock
        from pokewalker.services import gyms, raids, research
        bot = self.client()
        await self.pending_catch()
        bot.walker.clock = Mock(return_value=1900)
        order = []
        def track(name, original):
            async def call(conn, now, *args):
                self.assertIs(conn, self.conn)
                self.assertTrue(conn.in_transaction)
                order.append((name, now))
                return await original(conn, now, *args)
            return call
        with patch.object(gyms, 'settle', side_effect=track('settle', gyms.settle)), \
             patch.object(raids, 'expire', side_effect=track('expire', raids.expire)), \
             patch.object(research, 'auto_send', side_effect=track('auto_send', research.auto_send)), \
             patch.object(self.writer, 'run', wraps=self.writer.run) as run:
            await bot._sweep_once()
        run.assert_awaited_once()
        bot.walker.clock.assert_called_once_with()
        self.assertEqual(order, [('settle', 1900), ('expire', 1900), ('auto_send', 1900)])
        self.assertEqual(await self.rows("SELECT state FROM pokemon WHERE source_encounter_id='pending'"),
                         [{'state': 'sent'}])

    async def test_auto_send_catches_up_after_restart(self):
        await self.pending_catch()
        first = self.client()
        self.now = 1899
        await first._sweep_once()
        self.assertEqual(await self.rows('SELECT * FROM pokemon'), [])
        restarted = self.client()
        self.now = 1900 + 3600
        await restarted._sweep_once()
        self.assertEqual(await self.rows('SELECT state FROM pokemon'), [{'state': 'sent'}])
        self.assertEqual(await self.rows('SELECT acknowledged_at FROM encounters'), [{'acknowledged_at': self.now}])
        after = await self.auto_send_state()
        await restarted._sweep_once()
        self.assertEqual(await self.auto_send_state(), after)

    async def test_auto_send_failure_after_send_rolls_back_then_retries_once(self):
        from pokewalker.services import gyms
        await self.pending_catch()
        bot = self.client()
        self.now = 1900
        await self.conn.execute("CREATE TRIGGER fail_auto_ack BEFORE UPDATE OF acknowledged_at ON encounters "
                                "BEGIN SELECT RAISE(ABORT,'ack failed'); END")
        before = await self.auto_send_state()
        async def settle(conn, *args):
            await conn.execute('UPDATE guilds SET raids_enabled=0')
        with patch.object(gyms, 'settle', side_effect=settle):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'ack failed'):
                await bot._sweep_once()
        self.assertEqual(await self.auto_send_state(), before)
        await self.conn.execute('DROP TRIGGER fail_auto_ack')
        await bot._sweep_once()
        self.assertEqual(await self.rows('SELECT state FROM pokemon'), [{'state': 'sent'}])
        self.assertEqual(await self.rows('SELECT quantity FROM candy'), [{'quantity': 1}])
        self.assertEqual(await self.rows('SELECT key,action,profile_id FROM action_receipts'),
                         [{'key': 'research:auto:pending', 'action': 'research', 'profile_id': self.pid}])
        self.assertEqual(await self.rows('SELECT acknowledged_at FROM encounters'), [{'acknowledged_at': self.now}])
        after = await self.auto_send_state()
        await bot._sweep_once()
        self.assertEqual(await self.auto_send_state(), after)
