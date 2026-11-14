"""member-prune: /walker-admin prune with real transactions and D28 markers (README PR1-PR11)."""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord

from pokewalker.bot import admin_channels
from pokewalker.bot.admin_channels import WalkerAdmin
from pokewalker.db import Writer, open_db
from pokewalker.services import deletion, marker_log, profiles

DEPARTED, PRESENT = {"789", "791"}, "790"


def unknown(code=10007, error=discord.NotFound, status=404):
    body = {"code": code, "message": "synthetic"} if code is not None else "synthetic"
    return error(SimpleNamespace(status=status, reason="synthetic"), body)


class AdminPruneTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache = Path("build/test-admin-prune")
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "markers.jsonl"
        marker_log.create_empty(self.path)
        self.conn = await open_db(":memory:", allow_unpatched=True)
        self.addAsyncCleanup(self.conn.close)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.now = 0.0
        self.bot = SimpleNamespace(writer=self.writer, settings=SimpleNamespace(marker_log_path=self.path),
                                   reactions=SimpleNamespace(remove_own=AsyncMock()), clock=lambda: self.now)
        self.group = WalkerAdmin(self.bot)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123'),('999')")
        self.content = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))
        self.ids = {user: (await self.enroll("123", user))["profile_id"] for user in ("789", "790", "791")}
        self.other = (await self.enroll("999", "789"))["profile_id"]
        self.checked = []

    async def enroll(self, guild, user):
        return await self.writer.run(lambda conn: profiles.enroll(
            conn, guild, user, 1, self.content, random.Random(8), datetime.now(timezone.utc)))

    async def fetch(self, user_id):
        self.checked.append(str(user_id))
        if str(user_id) in DEPARTED:
            raise unknown()
        return SimpleNamespace(id=user_id)

    def interaction(self):
        response = SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=Mock(return_value=False))
        response.defer.side_effect = lambda **kwargs: response.is_done.configure_mock(return_value=True)
        interaction = SimpleNamespace(guild_id=123,
            user=SimpleNamespace(id=456, guild_permissions=SimpleNamespace(manage_guild=True)),
            guild=SimpleNamespace(fetch_member=AsyncMock(side_effect=self.fetch)),
            response=response, edit_original_response=AsyncMock())

        async def edit(**kwargs):
            self.assertFalse(self.conn.in_transaction, "Reply must follow commit/rollback")
            self.assertEqual(kwargs["allowed_mentions"].to_dict()["parse"], [])
        interaction.edit_original_response.side_effect = edit
        return interaction

    async def invoke(self, interaction=None, **kwargs):
        interaction = interaction or self.interaction()
        command = self.group.get_command("prune")
        self.assertIsNotNone(command, "prune command must exist")
        kwargs.setdefault("reason", "  left the server  ")
        await command.callback(self.group, interaction, **kwargs)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.response.send_message.assert_not_awaited()
        return interaction

    async def scalar(self, sql, args=()):
        async with self.conn.execute(sql, args) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def users(self, guild="123"):
        async with self.conn.execute("SELECT user_id FROM profiles WHERE guild_id=? ORDER BY user_id", (guild,)) as cursor:
            return [row[0] for row in await cursor.fetchall()]

    def records(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def text(self, interaction):
        return interaction.edit_original_response.await_args.kwargs["content"]

    async def exclude(self, conn):
        await conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")

    async def test_shape_and_entry_refusals(self):
        command = self.group.get_command("prune")
        self.assertIsNotNone(command)
        self.assertEqual([p.name for p in command.parameters], ["reason", "confirm"])
        self.assertFalse(command.parameters[1].required)
        for mode in ("permission", "dm", "excluded", "blank"):
            interaction = self.interaction()
            reason = "x"
            if mode == "permission":
                interaction.user.guild_permissions.manage_guild = False
            elif mode == "dm":
                interaction.guild_id = None
            elif mode == "excluded":
                await self.writer.run(self.exclude)
            else:
                reason = "   "
            await self.invoke(interaction, reason=reason, confirm=True)
            interaction.guild.fetch_member.assert_not_awaited()
        self.assertEqual(self.records(), [])
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 0)
        self.assertEqual(len(await self.users()), 3)

    async def test_defer_precedes_writer_and_member_checks(self):
        order = []
        interaction = self.interaction()
        interaction.response.defer.side_effect = lambda **kwargs: (
            order.append("defer"), interaction.response.is_done.configure_mock(return_value=True))

        async def fetch(uid):
            order.append("fetch")
            return await self.fetch(uid)
        interaction.guild.fetch_member.side_effect = fetch
        real = self.writer.run

        async def run(job):
            order.append("writer")
            return await real(job)
        with patch.object(self.writer, "run", side_effect=run):
            await self.invoke(interaction)
        self.assertEqual(order[0], "defer")
        self.assertIn("fetch", order)

    async def test_dry_run_counts_and_writes_nothing(self):
        interaction = await self.invoke()
        self.assertEqual(self.text(interaction),
                         "2 of 3 profiles are no longer members. Nothing was deleted. Use confirm=True to delete "
                         "their game data; this cannot be undone.")
        self.assertEqual(sorted(self.checked), ["789", "790", "791"])
        self.assertEqual(self.records(), [])
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 0)
        self.assertEqual(len(await self.users()), 3)

    async def test_confirm_deletes_only_departed_with_delete_markers(self):
        interaction = await self.invoke(confirm=True)
        self.assertEqual(self.text(interaction),
                         "Deleted the game data of 2 of 3 profiles whose users left this server.")
        self.assertEqual(await self.users(), [PRESENT])
        self.assertEqual(await self.users("999"), ["789"])
        records = self.records()
        self.assertEqual(sorted((r["kind"], r["user_id"], r["actor_id"], r["reason"], r["profile_id"]) for r in records),
                         [("delete", u, "456", "left the server", self.ids[u]) for u in sorted(DEPARTED)])
        self.assertEqual(self.bot.reactions.remove_own.await_count, 0)  # no tracked reactions here

    async def test_confirm_removes_own_reactions_of_pruned_profile(self):
        await self.conn.execute("INSERT INTO reactions(message_id,profile_id,channel_id,desired,actual,created_at) "
                                "VALUES ('11',?,'21','add','added',0)", (self.ids["789"],))
        await self.invoke(confirm=True)
        rows = self.bot.reactions.remove_own.await_args.args[0]
        self.assertEqual([(r["message_id"], r["channel_id"]) for r in rows], [("11", "21")])

    async def test_confirm_writes_one_guild_prune_audit(self):
        await self.invoke(confirm=True)
        async with self.conn.execute("SELECT guild_id,actor_id,target_kind,target_id,action,reason FROM mod_audit") as cursor:
            rows = [tuple(row) for row in await cursor.fetchall()]
        self.assertEqual(rows, [("123", "456", "guild", "123", "prune", "left the server")])

    async def test_no_departed_writes_no_audit_or_marker(self):
        interaction = self.interaction()

        async def present(uid):
            return SimpleNamespace(id=uid)
        interaction.guild.fetch_member.side_effect = present
        await self.invoke(interaction, confirm=True)
        self.assertIn("0 of 3", self.text(interaction))
        self.assertEqual(self.records(), [])
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 0)

    async def test_audit_survives_crash_between_marker_and_commit(self):
        command = self.group.get_command("prune")
        with patch.object(deletion, "apply", side_effect=RuntimeError("crash")), \
                patch.object(deletion, "append_void"):
            with self.assertRaises(RuntimeError):
                await command.callback(self.group, self.interaction(), reason="gone", confirm=True)
        self.assertEqual(len(await self.users()), 3)
        await deletion.replay_markers(self.writer, self.path)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit WHERE action='prune'"), 1)
        self.assertNotIn(self.records()[0]["user_id"], await self.users())

    async def test_other_outcomes_stop_run_and_report_progress(self):
        failures = (unknown(10004), unknown(None), unknown(50001, discord.Forbidden, 403),
                    unknown(0, discord.HTTPException, 500), discord.RateLimited(1.0), OSError("reset"))
        for failure in failures:
            with self.subTest(failure=repr(failure)):
                self.checked.clear()
                interaction = self.interaction()

                async def fetch(uid, failure=failure):
                    self.checked.append(str(uid))
                    raise failure
                interaction.guild.fetch_member.side_effect = fetch
                await self.invoke(interaction, confirm=True)
                self.assertEqual(len(self.checked), 1)
                self.assertTrue(self.text(interaction).startswith(
                    f"Stopped: Discord could not confirm a member ({type(failure).__name__})."))
                self.assertIn("Checked 0 of 3 profiles; 0 no longer members; 0 deleted.", self.text(interaction))
        self.assertEqual(self.records(), [])
        self.assertEqual(len(await self.users()), 3)

    async def test_failure_after_deletion_keeps_it_and_stops(self):
        interaction = self.interaction()

        async def fetch(uid):
            self.checked.append(str(uid))
            if str(uid) == "789":
                raise unknown()
            raise unknown(0, discord.HTTPException, 503)
        interaction.guild.fetch_member.side_effect = fetch
        await self.invoke(interaction, confirm=True)
        self.assertEqual(self.checked, ["789", "790"])
        self.assertIn("Checked 1 of 3 profiles; 1 no longer members; 1 deleted.", self.text(interaction))
        self.assertEqual(await self.users(), ["790", "791"])

    async def test_rerun_and_replay_delete_nothing_twice(self):
        await self.invoke(confirm=True)
        markers, audits = len(self.records()), await self.scalar("SELECT count(*) FROM mod_audit")
        interaction = await self.invoke(confirm=True)
        self.assertIn("0 of 1", self.text(interaction))
        self.assertEqual((len(self.records()), await self.scalar("SELECT count(*) FROM mod_audit")), (markers, audits))
        fresh = await self.enroll("123", "789")
        await deletion.replay_markers(self.writer, self.path)
        self.assertEqual(await self.scalar("SELECT profile_id FROM profiles WHERE guild_id='123' AND user_id='789'"),
                         fresh["profile_id"])

    async def test_profile_gone_before_writer_job_is_skipped(self):
        interaction = self.interaction()

        async def fetch(uid):
            if str(uid) == "789":
                await self.writer.run(lambda conn: conn.execute("DELETE FROM profiles WHERE profile_id=?",
                                                                (self.ids["789"],)))
            return await self.fetch(uid)
        interaction.guild.fetch_member.side_effect = fetch
        await self.invoke(interaction, confirm=True)
        self.assertEqual([r["user_id"] for r in self.records()], ["791"])
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 1)
        self.assertEqual(await self.users(), [PRESENT])

    async def test_actor_excluded_mid_run_stops_before_next_marker(self):
        interaction = self.interaction()

        async def fetch(uid):
            if str(uid) == "791":
                await self.writer.run(self.exclude)
            return await self.fetch(uid)
        interaction.guild.fetch_member.side_effect = fetch
        await self.invoke(interaction, confirm=True)
        self.assertIn("excluded", self.text(interaction).lower())
        self.assertIn("1 deleted", self.text(interaction))
        self.assertEqual([r["user_id"] for r in self.records()], ["789"])
        self.assertEqual(await self.users(), ["790", "791"])

    async def test_time_budget_stops_reports_and_next_run_resumes(self):
        interaction = self.interaction()

        async def slow(uid):
            self.now += 400
            return await self.fetch(uid)
        interaction.guild.fetch_member.side_effect = slow
        await self.invoke(interaction)
        self.assertEqual(self.checked, ["789", "790"])
        self.assertEqual(self.text(interaction), "Stopped: time limit reached. Checked 2 of 3 profiles; "
                                                 "1 no longer members; 0 deleted. Run it again to continue.")
        # A stop before any check keeps the cursor.
        self.checked.clear()
        ticks = iter([0])
        self.bot.clock = lambda: next(ticks, 10_000)
        await self.invoke()
        self.assertEqual(self.checked, [])
        self.bot.clock = lambda: self.now
        self.now = 0
        interaction = await self.invoke(self.interaction(), confirm=True)
        self.assertEqual(self.checked[:1], ["791"])  # resumes after 790, then wraps
        self.assertEqual(await self.users(), [PRESENT])

    async def test_stalled_fetch_and_cleanup_are_bounded(self):
        self.bot.clock = time.monotonic
        cancelled, release = [], asyncio.Event()
        await self.conn.execute("INSERT INTO reactions(message_id,profile_id,channel_id,desired,actual,created_at) "
                                "VALUES ('11',?,'21','add','added',0)", (self.ids["789"],))

        async def stall(*args):
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.append(args)
                raise
        self.bot.reactions.remove_own = AsyncMock(side_effect=stall)
        with patch.object(admin_channels, "PRUNE_BUDGET_SECONDS", 0.2):
            started = time.monotonic()
            interaction = await self.invoke(confirm=True)
            self.assertLess(time.monotonic() - started, 2)
        self.assertIn("Stopped: time limit reached.", self.text(interaction))
        self.assertIn("1 deleted", self.text(interaction))
        self.assertNotIn("789", await self.users())

        # A stalled membership check: reply by the deadline, late answer ignored, nothing cancelled.
        late = asyncio.get_running_loop().create_future()

        async def fetch(uid):
            self.checked.append(str(uid))
            try:
                return await late
            except asyncio.CancelledError:
                cancelled.append(uid)
                raise
        interaction = self.interaction()
        interaction.guild.fetch_member.side_effect = fetch
        before = len(self.records())
        with patch.object(admin_channels, "PRUNE_BUDGET_SECONDS", 0.2):
            await self.invoke(interaction, confirm=True)
        self.assertIn("Stopped: time limit reached.", self.text(interaction))
        late.set_exception(unknown())
        release.set()
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(cancelled, [])
        self.assertEqual(len(self.records()), before)

    async def test_prune_keeps_restrictions_opt_out_and_prior_audit(self):
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,share_banned) VALUES ('123','789',1)")
        await self.conn.execute("INSERT INTO opt_outs(guild_id,user_id,created_at) VALUES ('123','791',0)")
        await self.conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                                "VALUES ('123','1','user','789','pause','earlier',0)")
        await self.invoke(confirm=True)
        self.assertEqual(await self.scalar("SELECT share_banned FROM restrictions WHERE user_id='789'"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM opt_outs WHERE user_id='791'"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit WHERE action='pause'"), 1)


if __name__ == "__main__":
    unittest.main()
