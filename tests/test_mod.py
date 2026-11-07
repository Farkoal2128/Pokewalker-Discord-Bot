"""M4.2 moderation boundary with real writer transactions and fake Discord I/O."""

import asyncio
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pokewalker.db import Writer, open_db
from pokewalker.services import profiles, stepping


class ModTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await open_db(":memory:", allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.conn.close)
        self.addAsyncCleanup(self.writer.close)
        try:
            self.module = importlib.import_module("pokewalker.bot.mod")
        except ModuleNotFoundError:
            self.fail("M4.2 member moderation commands absent")
        self.bot = SimpleNamespace(db=self.conn, writer=self.writer)
        self.bot.walker = SimpleNamespace(clock=lambda: 10000, rng=random.Random(3))
        self.bot.content = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))
        self.group = self.module.WalkerMod(self.bot)
        self.member = SimpleNamespace(id=789, guild=SimpleNamespace(id=123))
        self.interaction = self.make_interaction()
        self.content = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))

    def make_interaction(self, guild=123, user=456):
        async def edit(**kwargs):
            self.assertFalse(self.conn.in_transaction, "Reply must follow commit")
        return SimpleNamespace(guild_id=guild,
            user=SimpleNamespace(id=user, guild_permissions=SimpleNamespace(moderate_members=True)),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(side_effect=edit),
            followup=SimpleNamespace(send=AsyncMock()), data={})

    async def invoke(self, name, **kwargs):
        command = self.group.get_command(name)
        await command.callback(command.binding, self.interaction, **kwargs)

    async def change(self, name, **kwargs):
        await self.invoke(name, member=self.member, reason="Test reason", **kwargs)

    async def rows(self, table):
        async with self.conn.execute(f"SELECT * FROM {table}") as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    def text(self):
        return self.interaction.edit_original_response.await_args.kwargs["content"]

    async def enroll(self):
        return await self.writer.run(lambda conn: profiles.enroll(
            conn, 123, 789, 1, self.content, random.Random(8), datetime.now(timezone.utc)))

    async def test_group_defaults_moderate_members_and_rechecks_every_use(self):
        self.assertTrue(self.group.default_permissions.moderate_members)
        self.assertTrue(self.group.guild_only)
        for name in ("pause", "resume", "exclude", "include", "share-ban", "share-unban", "status", "log"):
            self.interaction.user.guild_permissions.moderate_members = False
            args = {"member": self.member} if name == "status" else {} if name == "log" else {
                "member": self.member, "reason": "Test"}
            await self.invoke(name, **args)
            self.assertIn("Moderate Members", self.text())
        self.assertEqual(await self.rows("restrictions"), [])
        self.assertEqual(await self.rows("mod_audit"), [])
        self.interaction.user.guild_permissions.moderate_members = True
        await self.change("pause")
        self.interaction.user.guild_permissions.moderate_members = False
        await self.change("resume")
        self.assertEqual((await self.rows("restrictions"))[0]["paused"], 1)

    async def test_pause_choices_indefinite_1h_24h_7d_write_restriction_and_audit_together(self):
        parameter = next(p for p in self.group.get_command("pause").parameters if p.name == "duration")
        self.assertEqual({c.value for c in parameter.choices}, {"indefinite", "1h", "24h", "7d"})
        self.assertFalse(parameter.required)
        for value, seconds in (("indefinite", None), ("1h", 3600), ("24h", 86400), ("7d", 604800)):
            choice = next(c for c in parameter.choices if c.value == value)
            with patch.object(self.module.time, "time", return_value=10000):
                await self.change("pause", duration=choice)
            row = (await self.rows("restrictions"))[0]
            self.assertEqual((row["paused"], row["paused_until"]), (1, None if seconds is None else 10000 + seconds))
            audit = (await self.rows("mod_audit"))[-1]
            self.assertEqual((audit["guild_id"], audit["actor_id"], audit["target_kind"], audit["target_id"],
                              audit["action"], audit["reason"], audit["created_at"]),
                             ("123", "456", "user", "789", "pause", "Test reason", 10000))

    async def test_pause_without_profile_creates_row_and_applies_after_enrollment(self):
        await self.change("pause")
        self.assertEqual(await self.rows("profiles"), [])
        profile = await self.enroll()
        await self.writer.run(lambda conn: stepping.credit_message(conn, profile, ["word"] * 10,
            datetime.now(timezone.utc), "1", "222", content=self.content))
        row = (await self.rows("step_events"))[0]
        self.assertEqual((row["awarded_c"], row["discarded_words"], row["reason"]), (0, 10, "paused"))

    async def test_timed_pause_expires_resume_lifts_early(self):
        choice = next(p for p in self.group.get_command("pause").parameters if p.name == "duration").choices[1]
        with patch.object(self.module.time, "time", return_value=1000):
            await self.change("pause", duration=choice)
            self.assertTrue((await profiles.restrictions(self.conn, 123, 789)).paused)
        with patch("pokewalker.services.profiles.time.time", return_value=1000 + 604800):
            self.assertFalse((await profiles.restrictions(self.conn, 123, 789)).paused)
        await self.change("pause", duration=choice)
        await self.change("resume")
        row = (await self.rows("restrictions"))[0]
        self.assertEqual((row["paused"], row["paused_until"]), (0, None))

    async def test_exclude_then_router_refuses_next_click_include_restores(self):
        from pokewalker.bot.walker import Walker
        from uuid import uuid4
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        session = str(uuid4())
        await self.conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,expires_at) VALUES (?,'123','789',9999)",
                                (session,))
        walker = Walker(self.bot, clock=lambda: 1000)
        handler = AsyncMock(return_value={"content": "Allowed"})
        walker.handlers["home"] = handler
        target = self.make_interaction(user=789)
        await self.change("exclude")
        await walker.route(target, f"pw:v1:{session}:0:home")
        handler.assert_not_awaited()
        self.assertIn("excluded", target.followup.send.await_args.args[0])
        await self.change("include")
        await walker.route(target, f"pw:v1:{session}:0:home")
        handler.assert_awaited_once()

    async def test_share_ban_unban_independent_of_pause(self):
        await self.change("pause")
        await self.change("share-ban")
        await self.change("resume")
        flags = await profiles.restrictions(self.conn, 123, 789)
        self.assertTrue(flags.share_banned)
        self.assertFalse(flags.paused)
        await self.change("pause")
        await self.change("share-unban")
        flags = await profiles.restrictions(self.conn, 123, 789)
        self.assertFalse(flags.share_banned)
        self.assertTrue(flags.paused)

    async def test_status_fields_and_no_message_content(self):
        profile = await self.enroll()
        pid = profile["profile_id"]
        await self.conn.executemany("INSERT INTO step_events VALUES (?,?,?,10,8,2,?,'credited',?)",
            [("old", pid, "999", 125, 1000), ("recent", pid, "999", 250, 9900)])
        encounter = (await self.rows("encounters"))[0]["encounter_id"]
        await self.conn.execute("INSERT INTO catch_attempts(encounter_id,ordinal,ball,p,success,fled,created_at) "
                                "VALUES (?,0,'poke_ball',1,1,0,9000)", (encounter,))
        with patch.object(self.module.time, "time", return_value=10000):
            await self.change("pause")
            await self.change("share-ban")
            for i in range(6):
                await self.invoke("resume", member=self.member, reason=f"audit{i}")
            await self.invoke("status", member=self.member)
        text = self.text()
        for expected in ("Enrolled: True", "Paused: False", "Excluded: False", "Share-banned: True",
                         "Steps last hour: 2.5", "Steps total: 3.75", "Base steps discarded by anti-farming last hour: 2",
                         "Queue size: 1", "Catches: 1", "audit5", "audit1"):
            self.assertIn(expected, text)
        self.assertNotIn("audit0", text)
        self.assertNotIn("999", text)
        self.assertNotIn("message", text.lower())
        await self.change("pause")
        await self.invoke("status", member=self.member)
        self.assertIn("Paused: True (indefinite)", self.text())
        choice = next(p for p in self.group.get_command("pause").parameters if p.name == "duration").choices[1]
        await self.change("pause", duration=choice)
        await self.invoke("status", member=self.member)
        until = (await profiles.restrictions(self.conn, 123, 789)).paused_until.isoformat()
        self.assertIn(f"Paused: True ({until})", self.text())
        self.member = SimpleNamespace(id=888, guild=SimpleNamespace(id=123))
        await self.invoke("status", member=self.member)
        for expected in ("Enrolled: False", "Steps total: 0", "Queue size: 0", "Catches: 0"):
            self.assertIn(expected, self.text())

    async def test_status_and_log_unaudited_no_reason(self):
        for name, args in (("status", {"member": self.member}), ("log", {})):
            self.assertNotIn("reason", [p.name for p in self.group.get_command(name).parameters])
            await self.invoke(name, **args)
        self.assertEqual(await self.rows("mod_audit"), [])
        self.assertEqual(await self.rows("guilds"), [])

    async def test_log_last_25_optionally_by_member(self):
        await self.conn.executemany("INSERT INTO guilds(guild_id) VALUES (?)", [("123",), ("999",)])
        await self.conn.executemany("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
            "VALUES (?,'456',?,?,?, ?,1000)",
            [("123", "user", "789", "pause", f"entry{i}") for i in range(30)] +
            [("999", "user", "789", "pause", "other guild"),
             ("123", "channel", "789", "channels_add", "channel reason"),
             ("123", "user", "888", "resume", "other member")])
        await self.invoke("log")
        text = self.text()
        self.assertEqual(text.count("actor=456"), 25)
        self.assertIn("<#789>", text)
        self.assertIn("other member", text)
        self.assertNotIn("other guild", text)
        self.assertNotIn("entry6\n", text)
        await self.invoke("log", member=self.member)
        text = self.text()
        self.assertEqual(text.count("actor=456"), 25)
        self.assertIn("entry29", text)
        self.assertIn("entry5", text)
        self.assertNotIn("entry4\n", text)
        self.assertNotIn("channel reason", text)
        self.assertNotIn("other member", text)
        self.assertLess(text.index("entry29"), text.index("entry28"))

    async def test_blank_reason_refused_no_audit(self):
        for name in ("pause", "resume", "exclude", "include", "share-ban", "share-unban"):
            self.assertTrue(next(p for p in self.group.get_command(name).parameters if p.name == "reason").required)
            await self.invoke(name, member=self.member, reason=" \t\n")
            self.assertIn("reason", self.text())
        self.assertEqual(await self.rows("restrictions"), [])
        self.assertEqual(await self.rows("mod_audit"), [])

    async def test_mutation_rollback_leaves_no_partial_audit(self):
        await self.change("pause")
        before = await self.rows("restrictions")
        await self.conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON mod_audit BEGIN SELECT RAISE(ABORT,'audit failed'); END")
        self.interaction.edit_original_response.reset_mock()
        with self.assertRaisesRegex(Exception, "audit failed"):
            await self.change("resume")
        self.assertEqual(await self.rows("restrictions"), before)
        self.assertEqual(len(await self.rows("mod_audit")), 1)
        self.interaction.edit_original_response.assert_not_awaited()

    async def test_actor_excluded_refused(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        for name in ("pause", "resume", "exclude", "include", "share-ban", "share-unban", "status", "log"):
            await self.invoke(name, **({"member": self.member} if name == "status" else {} if name == "log" else {
                "member": self.member, "reason": "Test"}))
            self.assertIn("excluded", self.text().lower())
        self.assertEqual(await self.rows("mod_audit"), [])
        self.assertEqual(len(await self.rows("restrictions")), 1)

    async def test_moderation_never_changes_items_candy_stardust_pokemon(self):
        await self.enroll()
        tables = ("inventory", "candy", "pokemon", "profiles")
        before = {table: await self.rows(table) for table in tables}
        for name in ("pause", "resume", "exclude", "include", "share-ban", "share-unban"):
            await self.change(name)
        self.assertEqual({table: await self.rows(table) for table in tables}, before)

    async def test_commands_guild_only_ephemeral_registered_locally(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(SimpleNamespace())
        self.addAsyncCleanup(bot.close)
        group = bot.tree.get_command("walker-mod")
        self.assertIsNotNone(group)
        self.assertEqual({c.name for c in group.commands}, {
            "pause", "resume", "exclude", "include", "share-ban", "share-unban", "status", "log", "gym-recall"})
        for name in ("status", "log", "pause", "resume", "exclude", "include", "share-ban", "share-unban"):
            for guild in (None, 123):
                self.interaction = self.make_interaction(guild=guild)
                await self.invoke(name, **({"member": self.member} if name == "status" else {} if name == "log" else {
                    "member": self.member, "reason": "Test"}))
                self.interaction.response.defer.assert_awaited_once_with(ephemeral=True)
                self.assertEqual(self.interaction.edit_original_response.await_args.kwargs["allowed_mentions"].to_dict()["parse"], [])

    async def test_ack_before_queue_and_authorization_rechecked_in_job(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        for mode in ("exclude", "permission"):
            for name in ("pause", "status", "log"):
                with self.subTest(mode=mode, command=name):
                    self.interaction = self.make_interaction()
                    await self.conn.execute("DELETE FROM restrictions")
                    entered, release = asyncio.Event(), asyncio.Event()
                    async def block(conn):
                        entered.set()
                        await release.wait()
                        if mode == "exclude":
                            await conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
                        else:
                            self.interaction.user.guild_permissions.moderate_members = False
                    blocker = asyncio.create_task(self.writer.run(block))
                    await entered.wait()
                    args = {"member": self.member} if name == "status" else {} if name == "log" else {
                        "member": self.member, "reason": "Test"}
                    command = asyncio.create_task(self.invoke(name, **args))
                    async def queued():
                        while self.writer._queue.empty() and not command.done():
                            await asyncio.sleep(0)
                    try:
                        await asyncio.wait_for(queued(), 1)
                        self.assertFalse(command.done())
                        self.interaction.response.defer.assert_awaited_once_with(ephemeral=True)
                    finally:
                        release.set()
                        await asyncio.gather(blocker, command)
                    self.assertIn("excluded" if mode == "exclude" else "Moderate Members", self.text())
                    self.assertEqual(await self.rows("mod_audit"), [])

    async def test_log_chunks_long_audit_reasons_and_suppresses_mentions(self):
        await self.invoke("pause", member=self.member, reason="@everyone " + "x" * 5000)
        self.interaction = self.make_interaction()
        await self.invoke("log")
        replies = [self.interaction.edit_original_response.await_args,
                   *self.interaction.followup.send.await_args_list]
        self.assertGreater(len(replies), 1)
        for reply in replies:
            self.assertLessEqual(len(reply.kwargs["content"]), 2000)
            self.assertEqual(reply.kwargs["allowed_mentions"].to_dict()["parse"], [])
        self.assertTrue(all(reply.kwargs["ephemeral"] for reply in replies[1:]))

    async def test_foreign_guild_member_refused(self):
        self.member.guild.id = 999
        for name in ("pause", "status", "log"):
            await self.invoke(name, **({"member": self.member} if name != "pause" else {
                "member": self.member, "reason": "Test"}))
            self.assertIn("this server", self.text())
        self.assertEqual(await self.rows("restrictions"), [])

    async def test_serialized_reads_never_expose_rolled_back_restriction_or_audit(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        for name in ("status", "log"):
            with self.subTest(command=name):
                entered, release = asyncio.Event(), asyncio.Event()
                async def abort(conn):
                    await conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('123','789',1)")
                    await conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                                       "VALUES ('123','456','user','789','pause','uncommitted',1000)")
                    entered.set()
                    await release.wait()
                    raise ValueError("rollback test")
                mutation = asyncio.create_task(self.writer.run(abort))
                await entered.wait()
                command = asyncio.create_task(self.invoke(name, **({"member": self.member} if name == "status" else {})))
                async def queued():
                    while self.writer._queue.empty() and not command.done():
                        await asyncio.sleep(0)
                try:
                    await asyncio.wait_for(queued(), 1)
                    self.assertFalse(command.done())
                finally:
                    release.set()
                    result = await asyncio.gather(mutation, command, return_exceptions=True)
                self.assertIsInstance(result[0], ValueError)
                self.assertIsNone(result[1])
                self.assertNotIn("uncommitted", self.text())
                if name == "status":
                    self.assertIn("Paused: False", self.text())
                self.assertEqual(await self.rows("mod_audit"), [])

    async def test_status_is_scoped_to_current_guild_and_profile(self):
        profile = await self.enroll()
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('999')")
        await self.conn.executemany("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES (?,?,?,0)",
                                   [("otherguild", "999", "789"), ("othermember", "123", "888")])
        await self.conn.executemany("INSERT INTO step_events VALUES (?,?, '1',10,8,2,9000,'credited',9999)",
                                   [("elsewhere", "otherguild"), ("someoneelse", "othermember")])
        with patch.object(self.module.time, "time", return_value=10000):
            await self.invoke("status", member=self.member)
        self.assertIn("Steps total: 0", self.text())
        self.assertIn("Base steps discarded by anti-farming last hour: 0", self.text())
        self.assertIn("Queue size: 1", self.text())
        self.assertEqual(profile["guild_id"], "123")

    async def test_large_step_totals_and_audit_times_keep_precision(self):
        profile = await self.enroll()
        now = 1793823456.789
        await self.conn.execute("INSERT INTO step_events VALUES ('precise',?,'1',1,1,0,123456789,'accepted',?)",
                                (profile["profile_id"], now))
        with patch.object(self.module.time, "time", return_value=now):
            await self.change("pause")
            await self.invoke("status", member=self.member)
        self.assertIn("Steps last hour: 1234567.89", self.text())
        self.assertIn("Steps total: 1234567.89", self.text())
        self.assertIn("1793823456.789", self.text())

    async def test_status_counts_only_anti_farming_discarded_steps(self):
        profile = await self.enroll()
        pid, now = profile["profile_id"], 10000
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('other','123','888',0)")
        events = [(reason, pid, discarded, accepted, awarded, reason, now - 100)
                  for reason, discarded, accepted, awarded in (
                      ("minimum", 3, 0, 0), ("cooldown", 5, 0, 0), ("minute_cap", 7, 0, 0),
                      ("duplicate", 11, 0, 0), ("credited", 13, 4, 100))]
        events += [("start", pid, 17, 0, 0, "cooldown", now - 3600),
                   ("end", pid, 19, 0, 0, "minimum", now),
                   ("paused", pid, 23, 0, 0, "paused", now - 100),
                   ("no_timestamp", pid, 29, 0, 0, "no_timestamp", now - 100),
                   ("unknown", pid, 31, 0, 0, "unknown", now - 100),
                   ("before", pid, 101, 0, 0, "duplicate", now - 3600.001),
                   ("future", pid, 103, 0, 0, "minimum", now + 0.001),
                   ("unrelated", "other", 107, 0, 0, "credited", now - 100)]
        await self.conn.executemany("INSERT INTO step_events(message_id,profile_id,channel_id,eligible_words,"
            "accepted_words,discarded_words,awarded_c,reason,created_at) VALUES (?,?,'1',?,?,?,?,?,?)",
            [(mid, owner, discarded + accepted, accepted, discarded, awarded, reason, at)
             for mid, owner, discarded, accepted, awarded, reason, at in events])
        before = await self.rows("step_events")
        with patch.object(self.module.time, "time", return_value=now):
            await self.invoke("status", member=self.member)
        discarded_line = next(line for line in self.text().splitlines() if "discarded" in line.lower())
        self.assertEqual(int(discarded_line.rsplit(": ", 1)[1]), 75)
        self.assertEqual(discarded_line, "Base steps discarded by anti-farming last hour: 75")
        self.assertIn("Steps last hour: 1.00", self.text())
        self.assertIn("Steps total: 1.00", self.text())
        self.assertEqual(await self.rows("step_events"), before)
        self.assertEqual(await self.rows("mod_audit"), [])
