"""M4.3 private reset/sharing commands with real transactions and D28 markers."""

from contextlib import closing
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord

from pokewalker.bot.admin_channels import WalkerAdmin
from pokewalker.db import MIGRATIONS, Writer, open_db
from pokewalker.services import deletion, marker_log, profiles


class AdminResetSharingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache = Path("build/test-admin-reset-sharing")
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "markers.jsonl"
        marker_log.create_empty(self.path)
        self.conn = await open_db(":memory:", allow_unpatched=True)
        self.addAsyncCleanup(self.conn.close)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.bot = SimpleNamespace(writer=self.writer, settings=SimpleNamespace(marker_log_path=self.path),
                                   reactions=SimpleNamespace(remove_own=AsyncMock()))
        self.group = WalkerAdmin(self.bot)
        self.member = SimpleNamespace(id=789, display_name="Departed player")
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123'),('999')")
        self.content = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))
        self.profile = await self.enroll()
        await self.conn.execute("UPDATE profiles SET stardust=321 WHERE profile_id=?", (self.profile["profile_id"],))

    async def enroll(self):
        return await self.writer.run(lambda conn: profiles.enroll(
            conn, "123", "789", 1, self.content, random.Random(8), datetime.now(timezone.utc)))

    def interaction(self):
        response = SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=Mock(return_value=False))
        response.defer.side_effect = lambda **kwargs: response.is_done.configure_mock(return_value=True)
        interaction = SimpleNamespace(guild_id=123,
            user=SimpleNamespace(id=456, guild_permissions=SimpleNamespace(manage_guild=True)),
            response=response, edit_original_response=AsyncMock())

        async def edit(**kwargs):
            self.assertFalse(self.conn.in_transaction, "Reply must follow commit/rollback")
            self.assertEqual(kwargs["allowed_mentions"].to_dict()["parse"], [])
        interaction.edit_original_response.side_effect = edit
        return interaction

    async def invoke(self, name="reset", interaction=None, **kwargs):
        interaction = interaction or self.interaction()
        command = self.group.get_command(name)
        self.assertIsNotNone(command, f"M4.3 {name} command must exist")
        if name == "reset":
            kwargs.setdefault("member", self.member)
        kwargs.setdefault("reason", "  moderation  ")
        await command.callback(self.group, interaction, **kwargs)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.response.send_message.assert_not_awaited()
        return interaction

    async def scalar(self, sql, args=()):
        async with self.conn.execute(sql, args) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    def records(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def text(self, interaction):
        return interaction.edit_original_response.await_args.kwargs["content"]

    async def exclude(self, conn):
        await conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")

    async def test_reset_requires_manage_guild_runtime_and_actor_not_excluded(self):
        for mode in ("permission", "dm", "excluded"):
            interaction = self.interaction()
            if mode == "permission":
                interaction.user.guild_permissions.manage_guild = False
            elif mode == "dm":
                interaction.guild_id = None
            else:
                await self.writer.run(self.exclude)
            await self.invoke(interaction=interaction, confirm=True)
        self.assertEqual(self.records(), [])
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)

    async def test_reset_without_confirm_names_member_and_loss_changes_nothing(self):
        interaction = await self.invoke()
        for text in ("789", "Departed player", "1", "321", "Stardust", "cannot be undone"):
            self.assertIn(text, self.text(interaction))
        self.assertEqual(self.records(), [])
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)

    async def test_reset_writes_marker_with_actor_reason_then_deletes_and_audits_in_one_job(self):
        apply = deletion.apply
        fsynced = []

        async def observe(conn, states):
            self.assertTrue(conn.in_transaction)
            self.assertTrue(fsynced)
            self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
            record = self.records()[0]
            self.assertEqual((record["actor_id"], record["user_id"], record["reason"], record["profile_id"]),
                             ("456", "789", "moderation", self.profile["profile_id"]))
            await apply(conn, states)
            self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
            self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit WHERE action='reset'"), 1)
        with patch("os.fsync", side_effect=lambda fd: fsynced.append(fd)), patch.object(deletion, "apply", side_effect=observe):
            await self.invoke(confirm=True)
        self.assertEqual(await self.scalar("SELECT key FROM action_receipts"), "reset:" + self.records()[0]["marker_id"])
        self.assertIsNone(await self.scalar("SELECT profile_id FROM action_receipts"))

    async def test_reset_removes_own_reactions_of_reset_profile(self):
        await self.conn.execute("INSERT INTO reactions(message_id,profile_id,channel_id,desired,actual,created_at) "
                                "VALUES ('11',?,'21','add','added',0)", (self.profile["profile_id"],))
        await self.invoke(confirm=True)
        rows = self.bot.reactions.remove_own.await_args.args[0]
        self.assertEqual([(r["message_id"], r["channel_id"]) for r in rows], [("11", "21")])

    async def test_reset_unenrolled_member_writes_nothing(self):
        interaction = await self.invoke(member=SimpleNamespace(id=111), confirm=True)
        self.assertIn("not enrolled", self.text(interaction).lower())
        self.assertEqual(self.records(), [])

    async def test_actor_excluded_while_reset_queued_writes_no_marker(self):
        original = self.group.authorize
        for command, args in (("reset", {"confirm": True}), ("sharing", {"on": "off"})):
            await self.conn.execute("DELETE FROM restrictions")
            entered, release = asyncio.Event(), asyncio.Event()

            async def exclude(conn):
                entered.set()
                await release.wait()
                await self.exclude(conn)

            async def authorize(interaction):
                allowed = await original(interaction)
                asyncio.create_task(self.writer.run(exclude))
                await entered.wait()
                return allowed

            with patch.object(self.group, "authorize", side_effect=authorize):
                pending = asyncio.create_task(self.invoke(command, **args))
                try:
                    await asyncio.wait_for(entered.wait(), 2)
                    async def queued():
                        while self.writer._queue.empty():
                            await asyncio.sleep(0)
                    await asyncio.wait_for(queued(), 2)
                finally:
                    release.set()
                interaction = await pending
            self.assertIn("excluded", self.text(interaction).lower())
        self.assertEqual(self.records(), [])
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertEqual(await self.scalar("SELECT sharing FROM guilds WHERE guild_id='123'"), 1)

    async def test_confirm_resolves_current_profile_and_rechecks_manage_server(self):
        original = self.group.authorize

        async def replace_profile(interaction):
            allowed = await original(interaction)
            await self.writer.run(lambda conn: conn.execute("DELETE FROM profiles WHERE guild_id='123'"))
            self.profile = await self.enroll()
            return allowed
        with patch.object(self.group, "authorize", side_effect=replace_profile):
            await self.invoke(confirm=True)
        self.assertEqual(self.records()[0]["profile_id"], self.profile["profile_id"])
        await self.enroll()

        async def revoke(interaction):
            allowed = await original(interaction)
            interaction.user.guild_permissions.manage_guild = False
            return allowed
        for command, args in (("reset", {"confirm": True}), ("sharing", {"on": "off"})):
            with patch.object(self.group, "authorize", side_effect=revoke):
                await self.invoke(command, **args)
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 1)

    async def test_whitespace_reason_refused_no_marker_no_change_next_startup_ok(self):
        for command, args in (("reset", {"confirm": True}), ("sharing", {"on": "off"})):
            interaction = await self.invoke(command, reason=" \t\n ", **args)
            self.assertEqual(self.text(interaction), "A reason is required.")
        self.assertEqual(self.records(), [])
        await deletion.replay_markers(self.writer, self.path)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 0)

    async def test_reset_keeps_restrictions_and_prior_audit(self):
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,excluded,share_banned) VALUES ('123','789',1,1,1)")
        await self.conn.execute("INSERT INTO mod_audit VALUES (41,'123','456','user','789','exclude','prior',1)")
        await self.conn.execute("INSERT INTO opt_outs VALUES ('123','789',1)")
        await self.invoke(confirm=True)
        self.assertEqual(await self.scalar("SELECT paused+excluded+share_banned FROM restrictions"), 3)
        self.assertEqual(await self.scalar("SELECT reason FROM mod_audit WHERE audit_id=41"), "prior")
        self.assertTrue(await deletion.opted_out(self.conn, "123", "789"))
        self.assertEqual(await self.scalar("SELECT count(*) FROM pokemon"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM inventory"), 0)

    async def test_reset_then_reenroll_fresh_uuid(self):
        await self.invoke(confirm=True)
        new = await self.enroll()
        self.assertNotEqual(new["profile_id"], self.profile["profile_id"])
        await deletion.replay_markers(self.writer, self.path)
        self.assertEqual(await self.scalar("SELECT profile_id FROM profiles"), new["profile_id"])

    async def test_interrupted_reset_after_marker_replays_with_exactly_one_audit_entry(self):
        marker_log.append_marker(self.path, "reset", "123", "789", 100,
                                 profile_id=self.profile["profile_id"], actor_id="456", reason="moderation")
        await deletion.replay_markers(self.writer, self.path)
        await deletion.replay_markers(self.writer, self.path)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 1)

    async def test_reset_replay_after_commit_adds_no_second_audit(self):
        await self.invoke(confirm=True)
        await self.invoke(confirm=True)
        await deletion.replay_markers(self.writer, self.path)
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 1)

    async def test_sharing_toggle_writes_flag_and_guild_audit_together_requires_reason(self):
        for on, value in (("off", 0), ("on", 1)):
            await self.invoke("sharing", on=on)
            self.assertEqual(await self.scalar("SELECT sharing FROM guilds WHERE guild_id='123'"), value)
            self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit WHERE target_kind='guild' AND target_id='123' "
                                              "AND actor_id='456' AND reason='moderation' AND action=?", ("sharing_" + on,)), 1)
        self.assertEqual(self.records(), [])
        interaction = await self.invoke("sharing", on="unexpected")
        self.assertIn("on or off", self.text(interaction))
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 2)

    async def test_sharing_default_on_for_new_guild(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('555')")
        self.assertEqual(await self.scalar("SELECT sharing FROM guilds WHERE guild_id='555'"), 1)
        interaction = self.interaction()
        interaction.guild_id = 666
        await self.invoke("sharing", interaction=interaction, on="off")
        self.assertEqual(await self.scalar("SELECT sharing FROM guilds WHERE guild_id='666'"), 0)

    async def test_rollback_leaves_no_partial_audit(self):
        await self.conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON mod_audit BEGIN SELECT RAISE(ABORT,'audit failed'); END")
        for command, args in (("sharing", {"on": "off"}), ("reset", {"confirm": True})):
            interaction = self.interaction()
            with self.assertRaisesRegex(sqlite3.IntegrityError, "audit failed"):
                await self.invoke(command, interaction=interaction, **args)
            interaction.edit_original_response.assert_not_awaited()
        self.assertEqual(await self.scalar("SELECT sharing FROM guilds WHERE guild_id='123'"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 0)
        self.assertEqual(self.records()[1]["void"], self.records()[0]["marker_id"])
        await deletion.replay_markers(self.writer, self.path)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)

    async def test_migration_rebuilds_audit_keeping_rows_and_ids(self):
        path = self.root / "legacy.sqlite3"
        with closing(sqlite3.connect(path)) as conn, conn:
            for migration in sorted(MIGRATIONS.glob("*.sql")):
                if int(migration.name[:4]) <= 8:
                    conn.executescript(migration.read_text(encoding="utf-8"))
            conn.execute("PRAGMA user_version=8")
            conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
            conn.execute("INSERT INTO mod_audit VALUES (41,'123','456','user','789','exclude','prior',1)")
            conn.execute("INSERT INTO mod_audit VALUES (99,'123','456','channel','777','channels_add','prior channel',2)")
        migrated = await open_db(path, allow_unpatched=True)
        try:
            async with migrated.execute("SELECT audit_id,target_kind,reason FROM mod_audit ORDER BY audit_id") as cursor:
                self.assertEqual([tuple(row) for row in await cursor.fetchall()],
                                 [(41, "user", "prior"), (99, "channel", "prior channel")])
            await migrated.execute("INSERT INTO mod_audit VALUES (NULL,'123','456','guild','123','sharing_off','new',3)")
            async with migrated.execute("PRAGMA foreign_key_check") as cursor:
                self.assertEqual(await cursor.fetchall(), [])
            with self.assertRaises(sqlite3.IntegrityError):
                await migrated.execute("UPDATE guilds SET sharing=2")
        finally:
            await migrated.close()

    async def test_departed_user_option_resets_only_current_guild(self):
        command = self.group.get_command("reset")
        self.assertIsNotNone(command, "M4.3 reset command must exist")
        parameter = next(p for p in command.parameters if p.name == "member")
        self.assertEqual(parameter.type, discord.AppCommandOptionType.user)
        self.assertIs(command.callback.__annotations__["member"], discord.User)
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('other','999','789',0)")
        await self.invoke(confirm=True)
        self.assertEqual(await self.scalar("SELECT profile_id FROM profiles"), "other")
        self.assertEqual(self.records()[0]["guild_id"], "123")

    async def test_private_defer_precedes_writer_wait_and_sharing_authorization(self):
        original = self.writer.run
        interaction = self.interaction()

        async def run(job):
            interaction.response.defer.assert_awaited_once_with(ephemeral=True)
            return await original(job)
        with patch.object(self.writer, "run", side_effect=run):
            await self.invoke(interaction=interaction)
        interaction = self.interaction()
        interaction.user.guild_permissions.manage_guild = False
        await self.invoke("sharing", interaction=interaction, on="off")
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 0)


if __name__ == "__main__":
    unittest.main()
