"""M1.4b crash and ordering contracts using SQLite and fake Discord only."""

import asyncio
import importlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from pokewalker import db


def http_error(kind, status):
    return kind(SimpleNamespace(status=status, reason="synthetic"), "synthetic")


class FakeDiscord:
    def __init__(self, conn):
        self.conn = conn
        self.calls, self.present = [], set()
        self.user = discord.Object(id=99)
        self.failure = None
        self.add_started = self.add_release = None
        self.channel = SimpleNamespace(parent_id=None)

    def get_channel(self, channel_id):
        return self.channel

    async def fetch_channel(self, channel_id):
        return self.channel

    def get_partial_messageable(self, channel_id):
        return SimpleNamespace(get_partial_message=lambda message_id: SimpleNamespace(
            add_reaction=lambda emoji: self.call("add", channel_id, message_id),
            remove_reaction=lambda emoji, user: self.call("remove", channel_id, message_id)))

    async def call(self, action, channel_id, message_id):
        assert not self.conn.in_transaction, "Discord called in writer transaction"
        self.calls.append((action, channel_id, message_id))
        if self.failure:
            raise self.failure
        if action == "add":
            if self.add_started:
                self.add_started.set()
                await self.add_release.wait()
            self.present.add(message_id)
        elif message_id in self.present:
            self.present.remove(message_id)
        else:
            raise http_error(discord.NotFound, 404)


class ReactionMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_upgrade_preserves_legacy_and_enforces_encounter_key(self):
        root = Path("build/test-reactions")
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            path = Path(temporary) / "legacy.db"
            conn = sqlite3.connect(path)
            conn.executescript((db.MIGRATIONS / "0001_core.sql").read_text())
            conn.executescript("INSERT INTO guilds(guild_id) VALUES ('1');"
                               "INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                               "VALUES ('p','1','2',0);"
                               "INSERT INTO reactions(message_id,profile_id,channel_id,desired,created_at) "
                               "VALUES ('10','p','3','remove',0); PRAGMA user_version=1;")
            conn.close()
            upgraded = await db.open_db(path)
            try:
                async with upgraded.execute("PRAGMA table_info(reactions)") as cursor:
                    self.assertIn("encounter_id", [row["name"] for row in await cursor.fetchall()])
                async with upgraded.execute("SELECT * FROM reactions") as cursor:
                    self.assertIsNone((await cursor.fetchone())["encounter_id"])
                with self.assertRaises(sqlite3.IntegrityError):
                    await upgraded.execute("UPDATE reactions SET encounter_id='missing'")
            finally:
                await upgraded.close()
            reopened = await db.open_db(path)
            await reopened.close()


class ReactionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            module = importlib.import_module("pokewalker.services.reactions")
        except ModuleNotFoundError:
            self.fail("M1.4b reaction reconciler is absent")
        self.conn = await db.open_db(":memory:")
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        await self.conn.executescript(
            "INSERT INTO guilds(guild_id) VALUES ('1');"
            "INSERT INTO guild_channels(guild_id,channel_id) VALUES ('1','3');"
            "INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('p','1','2',0);")
        self.discord = FakeDiscord(self.conn)
        self.discord.writer = self.writer
        self.service = module.ReactionService(self.discord)
        await self.seed()

    async def seed(self, encounter="e", message="10", desired="add", actual="none"):
        await self.conn.execute(
            "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,"
            "iv_defense,iv_stamina,gender,shiny,tier,route_id,content_version,created_at) "
            "VALUES (?,'p',1,2,0,0,0,'male',0,'common','refreshing_field','fixture',0)", (encounter,))
        await self.conn.execute(
            "INSERT INTO reactions(encounter_id,message_id,profile_id,channel_id,desired,actual,created_at) "
            "VALUES (?,?,'p','3',?,?,0)", (encounter, message, desired, actual))

    async def scalar(self, sql):
        async with self.conn.execute(sql) as cursor:
            return (await cursor.fetchone())[0]

    async def remove_desired(self):
        async def job(conn):
            await conn.execute("UPDATE reactions SET desired='remove',revision=revision+1")
        await self.writer.run(job)

    async def test_add_when_desired_add_and_react_enabled(self):
        await self.service.reconcile_reaction("e")
        self.assertEqual(self.discord.present, {10})
        self.assertEqual(await self.scalar("SELECT actual FROM reactions"), "added")

    async def test_legacy_message_reconciliation_retires_pending_removal(self):
        await self.conn.execute("UPDATE reactions SET encounter_id=NULL,desired='remove'")
        self.discord.present.add(10)
        self.assertTrue(hasattr(self.service, "reconcile_message"), "Legacy pending rows need a public reconcile seam")
        await self.service.reconcile_message("10")
        self.assertEqual(self.discord.present, set())
        self.assertEqual(await self.scalar("SELECT count(*) FROM reactions"), 0)

    async def test_no_add_when_channel_react_disabled(self):
        await self.conn.execute("UPDATE guild_channels SET react=0")
        await self.service.reconcile_reaction("e")
        self.assertEqual(self.discord.calls, [])
        self.assertEqual(await self.scalar("SELECT actual FROM reactions"), "none")

    async def test_add_is_noop_when_already_present(self):
        self.discord.present.add(10)
        await self.service.reconcile_reaction("e")
        await self.service.reconcile_reaction("e")
        self.assertEqual(self.discord.present, {10})
        self.assertEqual(len(self.discord.calls), 1)

    async def test_remove_attempted_regardless_of_actual(self):
        for actual in ("none", "added"):
            with self.subTest(actual=actual):
                await self.conn.execute("UPDATE reactions SET desired='remove',actual=?", (actual,))
                self.discord.present.add(10)
                await self.service.reconcile_reaction("e")
                self.assertNotIn(10, self.discord.present)
                self.assertEqual(await self.scalar("SELECT count(*) FROM reactions"), 0)
                if actual == "none":
                    await self.conn.execute("DELETE FROM encounters")
                    await self.seed()
        self.assertEqual([call[0] for call in self.discord.calls], ["remove", "remove"])

    async def test_remove_404_counts_as_removed(self):
        await self.remove_desired()
        await self.service.reconcile_reaction("e")
        self.assertEqual(await self.scalar("SELECT count(*) FROM reactions"), 0)

    async def test_crash_after_discord_add_before_db_write_then_walker_open_clears(self):
        with patch.object(self.service, "_mark_added", AsyncMock(side_effect=RuntimeError("synthetic crash"))):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                await self.service.reconcile_reaction("e")
        self.assertEqual(await self.scalar("SELECT actual FROM reactions"), "none")
        self.assertEqual(self.discord.present, {10})
        await self.remove_desired()
        restarted = type(self.service)(self.discord)
        await restarted.reconcile_reaction("e")
        self.assertEqual(self.discord.present, set())
        self.assertEqual(await self.scalar("SELECT count(*) FROM reactions"), 0)

    async def test_startup_sweep_repairs_rows_after_crash(self):
        await self.seed("e2", "11", "remove", "none")
        await self.seed("e3", "12", "add", "added")
        await self.conn.execute(
            "INSERT INTO reactions(message_id,profile_id,channel_id,desired,created_at) "
            "VALUES ('13','p','3','remove',0)")
        self.discord.present.update({11, 12, 13})
        await self.service.startup_sweep()
        self.assertEqual(self.discord.present, {10, 12})
        self.assertEqual({call[2] for call in self.discord.calls}, {10, 11, 13})

    async def test_completed_removal_retires_row_second_walker_and_startup_make_zero_calls(self):
        await self.remove_desired()
        await self.service.reconcile_reaction("e")
        self.discord.calls.clear()
        await self.service.reconcile_reaction("e")
        await self.service.startup_sweep()
        self.assertEqual(self.discord.calls, [])

    async def test_crash_between_discord_delete_and_row_delete_retries_once_then_retires(self):
        await self.remove_desired()
        self.discord.present.add(10)
        with patch.object(self.service, "_retire", AsyncMock(side_effect=RuntimeError("synthetic crash"))):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                await self.service.reconcile_reaction("e")
        self.assertEqual(self.discord.present, set())
        self.assertEqual(await self.scalar("SELECT desired FROM reactions"), "remove")
        await type(self.service)(self.discord).startup_sweep()
        self.assertEqual(await self.scalar("SELECT count(*) FROM reactions"), 0)
        self.assertEqual([call[0] for call in self.discord.calls], ["remove", "remove"])

    async def test_lock_serializes_in_flight_add_with_removal_no_recreated_reaction(self):
        self.discord.add_started, self.discord.add_release = asyncio.Event(), asyncio.Event()
        adding = asyncio.create_task(self.service.reconcile_reaction("e"))
        await self.discord.add_started.wait()
        await self.remove_desired()
        removing = asyncio.create_task(self.service.reconcile_reaction("e"))
        await asyncio.sleep(0)
        self.assertFalse(removing.done())
        self.discord.add_release.set()
        await asyncio.gather(adding, removing)
        self.assertEqual([call[0] for call in self.discord.calls], ["add", "remove"])
        self.assertEqual(self.discord.present, set())
        self.assertEqual(await self.scalar("SELECT count(*) FROM reactions"), 0)

    async def race_deletion_with_delayed_add(self, reconcile):
        from pokewalker.services import deletion, marker_log
        root = Path("build/test-reactions")
        root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "markers.jsonl"
        marker_log.create_empty(path)
        self.discord.add_started, self.discord.add_release = asyncio.Event(), asyncio.Event()
        adding = asyncio.create_task(reconcile())
        await self.discord.add_started.wait()
        deleting = asyncio.create_task(deletion.run_marker(
            self.writer, path, kind="delete", guild_id="1", user_id="2", profile_id="p", now=1,
            reactions=self.service))
        while await self.scalar("SELECT count(*) FROM profiles"):
            await asyncio.sleep(0)
        for _ in range(20):
            await asyncio.sleep(0)
        self.discord.add_release.set()
        await asyncio.gather(adding, deleting)
        self.assertEqual(self.discord.present, set())
        self.assertEqual(await self.scalar("SELECT count(*) FROM reactions"), 0)
        await self.service.startup_sweep()
        self.assertEqual(self.discord.present, set())

    async def test_delayed_encounter_add_racing_deletion_leaves_no_reaction(self):
        await self.race_deletion_with_delayed_add(lambda: self.service.reconcile_reaction("e"))

    async def test_delayed_legacy_add_racing_deletion_leaves_no_reaction(self):
        await self.conn.execute("UPDATE reactions SET encounter_id=NULL")
        await self.race_deletion_with_delayed_add(lambda: self.service.reconcile_message("10"))

    async def test_delayed_add_after_remove_is_reconciled_to_none(self):
        await self.remove_desired()
        await self.service.reconcile_reaction("e")
        await self.service.reconcile_reaction("e")
        self.assertEqual([call[0] for call in self.discord.calls], ["remove"])

    async def test_permission_error_leaves_row_and_encounter(self):
        self.discord.failure = http_error(discord.Forbidden, 403)
        with self.assertLogs("pokewalker.services.reactions", level="WARNING") as logs:
            await self.service.reconcile_reaction("e")
            await self.remove_desired()
            await self.service.reconcile_reaction("e")
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM reactions"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM encounters"), 1)

    async def test_partial_message_removes_own_reaction_without_fetching_message(self):
        removing = AsyncMock()
        self.discord._connection = SimpleNamespace(self_id=99,
            http=SimpleNamespace(remove_own_reaction=removing))
        self.discord.get_partial_messageable = lambda channel_id: discord.Client.get_partial_messageable(
            self.discord, channel_id)
        await self.remove_desired()
        await self.service.reconcile_reaction("e")
        removing.assert_awaited_once_with(3, 10, "❗")
        self.assertEqual(await self.scalar("SELECT count(*) FROM reactions"), 0)

    async def test_stale_add_cannot_mark_actual_after_remove_revision_commits(self):
        self.discord.add_started, self.discord.add_release = asyncio.Event(), asyncio.Event()
        adding = asyncio.create_task(self.service.reconcile_reaction("e"))
        await self.discord.add_started.wait()
        await self.remove_desired()
        with patch.object(self.service, "_retire", AsyncMock(side_effect=RuntimeError("synthetic crash"))):
            self.discord.add_release.set()
            with self.assertRaisesRegex(RuntimeError, "crash"):
                await adding
        self.assertEqual(await self.scalar("SELECT actual FROM reactions"), "none")
        self.assertEqual(await self.scalar("SELECT desired FROM reactions"), "remove")

    async def test_http_outage_or_rate_limit_keeps_pending_row(self):
        for desired in ("add", "remove"):
            for status in (429, 503):
                await self.conn.execute("UPDATE reactions SET desired=?", (desired,))
                self.discord.failure = http_error(discord.HTTPException, status)
                await self.service.reconcile_reaction("e")
                self.assertEqual(await self.scalar("SELECT count(*) FROM reactions"), 1)
                self.assertEqual(await self.scalar("SELECT count(*) FROM encounters"), 1)

    async def test_never_runs_inside_writer_transaction(self):
        async def job(conn):
            await self.service.reconcile_reaction("e")
        with self.assertRaisesRegex(RuntimeError, "writer transaction"):
            await self.writer.run(job)
        self.assertEqual(self.discord.calls, [])

    async def test_thread_uses_parent_channel_policy(self):
        self.discord.channel.parent_id = 4
        await self.service.reconcile_reaction("e")
        self.assertEqual(self.discord.calls, [])
        await self.conn.execute("INSERT INTO guild_channels VALUES ('1','4',1,1)")
        await self.service.reconcile_reaction("e")
        self.assertEqual(self.discord.present, {10})

    async def test_encounter_key_is_unique(self):
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute(
                "INSERT INTO reactions(encounter_id,message_id,profile_id,channel_id,desired,created_at) "
                "VALUES ('e','20','p','3','add',0)")
