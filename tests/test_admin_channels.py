"""M1.4 fake interaction tests, with real writer transactions and command schemas."""

import asyncio
import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

from pokewalker.db import Writer, open_db


class AdminChannelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await open_db(":memory:", allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.conn.close)
        self.addAsyncCleanup(self.writer.close)
        try:
            self.module = importlib.import_module("pokewalker.bot.admin_channels")
        except ModuleNotFoundError:
            self.fail("M1.4 channel commands absent")
        self.bot = SimpleNamespace(db=self.conn, writer=self.writer)
        self.group = self.module.WalkerAdmin(self.bot)
        self.channels = self.group.get_command("channels")
        self.interaction = SimpleNamespace(
            guild_id=123, guild=SimpleNamespace(me=object()),
            user=SimpleNamespace(id=456, guild_permissions=SimpleNamespace(manage_guild=True)),
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), is_done=lambda: False),
            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())
        self.interaction.response.defer.side_effect = lambda **kwargs: setattr(
            self.interaction.response, "is_done", lambda: True)
        self.channel = SimpleNamespace(id=789, guild=SimpleNamespace(id=123),
            permissions_for=lambda member: SimpleNamespace(add_reactions=True, read_message_history=True))
        self.interaction.guild.text_channels = [
            SimpleNamespace(id=789 + i, type=discord.ChannelType.news if i == 3 else discord.ChannelType.text,
                permissions_for=lambda member, visible=i < 4: SimpleNamespace(view_channel=visible))
            for i in range(5)]
        self.interaction.guild.channels = [*self.interaction.guild.text_channels,
            SimpleNamespace(id=999, type=discord.ChannelType.forum,
                permissions_for=lambda member: SimpleNamespace(view_channel=True))]
        self.interaction.guild.fetch_member = AsyncMock(return_value=SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_guild=True)))

    async def invoke(self, name, **kwargs):
        command = self.channels.get_command(name)
        await command.callback(command.binding, self.interaction, **kwargs)

    def reply(self):
        """Last reply text; the ephemeral flag comes from the deferral that precedes it."""
        self.interaction.response.defer.assert_awaited_with(ephemeral=True)
        self.interaction.response.send_message.assert_not_awaited()
        return self.interaction.edit_original_response.await_args.kwargs["content"]

    async def rows(self, table):
        async with self.conn.execute(f"SELECT * FROM {table}") as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def test_channels_add_requires_manage_guild_at_runtime(self):
        self.assertTrue(self.group.default_permissions.manage_guild)
        self.assertTrue(self.group.guild_only)
        self.interaction.user.guild_permissions.manage_guild = False
        for name, args in (("add", {"channel": self.channel, "reason": "test"}),
                           ("add-all", {"reason": "test"}),
                           ("remove", {"channel": self.channel, "reason": "test"}), ("list", {})):
            await self.invoke(name, **args)
            self.assertIn("Manage Server", self.reply())
        self.assertEqual(await self.rows("guild_channels"), [])
        self.assertEqual(await self.rows("mod_audit"), [])

    async def test_channels_add_remove_require_reason_and_write_audit_together(self):
        for name in ("add", "remove"):
            reason = next(p for p in self.channels.get_command(name).parameters if p.name == "reason")
            self.assertTrue(reason.required)
            await self.invoke(name, channel=self.channel, reason="  ")
        self.assertEqual(await self.rows("mod_audit"), [])
        await self.invoke("add", channel=self.channel, reason="Count here", count=False, react=True)
        self.assertEqual((await self.rows("guild_channels"))[0]["count_steps"], 0)
        audit = (await self.rows("mod_audit"))[0]
        self.assertEqual((audit["actor_id"], audit["target_kind"], audit["target_id"], audit["action"], audit["reason"]),
                         ("456", "channel", "789", "channels_add", "Count here"))
        self.assertGreater(audit["created_at"], 0)
        await self.invoke("remove", channel=self.channel, reason="Stop counting")
        self.assertEqual(await self.rows("guild_channels"), [])
        self.assertEqual([r["action"] for r in await self.rows("mod_audit")], ["channels_add", "channels_remove"])
        await self.conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON mod_audit BEGIN SELECT RAISE(ABORT,'audit failed'); END")
        with self.assertRaisesRegex(Exception, "audit failed"):
            await self.invoke("add", channel=self.channel, reason="Must roll back")
        self.assertEqual(await self.rows("guild_channels"), [])

    async def test_channels_list_is_ephemeral_and_unaudited(self):
        await self.invoke("add", channel=self.channel, reason="Test")
        await self.invoke("list")
        self.assertIn("789", self.reply())
        self.assertEqual(len(await self.rows("mod_audit")), 1)

    async def test_channel_commands_defer_ephemerally_before_waiting_on_writer(self):
        run = self.writer.run

        async def deferred_first(fn, **kwargs):
            self.interaction.response.defer.assert_awaited_once_with(ephemeral=True)
            return await run(fn, **kwargs)

        for name, args in (("add", {"channel": self.channel, "reason": "Test"}), ("list", {}),
                           ("add-all", {"reason": "Test"}),
                           ("remove", {"channel": self.channel, "reason": "Test"})):
            with self.subTest(name=name):
                self.interaction.response.defer.reset_mock()
                with patch.object(self.writer, "run", side_effect=deferred_first):
                    await self.invoke(name, **args)
                self.reply()

    async def test_add_warns_when_reaction_permissions_missing(self):
        for add, history in ((False, True), (True, False), (False, False)):
            self.channel.permissions_for = lambda member: SimpleNamespace(add_reactions=add, read_message_history=history)
            await self.invoke("add", channel=self.channel, reason="Test")
            self.assertIn("skip", self.reply().lower())
        self.assertEqual((await self.rows("guild_channels"))[0]["react"], 1)

    async def test_dm_and_cross_guild_channel_are_refused(self):
        self.interaction.guild_id = None
        await self.invoke("add", channel=self.channel, reason="Test")
        self.interaction.guild_id = 999
        await self.invoke("add", channel=self.channel, reason="Test")
        self.assertEqual(await self.rows("guild_channels"), [])

    async def test_registered_group_appears_in_client_manifest_without_sync(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(SimpleNamespace())
        self.addAsyncCleanup(bot.close)
        command = bot.tree.get_command("walker-admin")
        self.assertIsNotNone(command)
        channels = command.get_command("channels")
        self.assertEqual({c.name for c in channels.commands}, {"add", "add-all", "remove", "list"})
        gyms = command.get_command("gyms")
        self.assertEqual({c.name for c in gyms.commands}, {"create", "remove", "list"})
        for action in ("create", "remove"):
            self.assertEqual({p.name for p in gyms.get_command(action).parameters if p.required}, {"name", "reason"})

    async def test_large_channel_list_fits_discord_message_limit(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.executemany("INSERT INTO guild_channels VALUES ('123',?,1,1)",
                                   [(str(100000000000000000 + i),) for i in range(100)])
        await self.invoke("list")
        first = self.interaction.edit_original_response.await_args
        followups = self.interaction.followup.send.await_args_list
        texts = [self.reply(), *(response.args[0] for response in followups)]
        self.assertTrue(all(len(text) <= 2000 for text in texts))
        self.assertTrue(all(response.kwargs["ephemeral"] for response in followups))
        self.assertTrue(all(response.kwargs["allowed_mentions"].to_dict().get("parse") == []
                            for response in (first, *followups)))
        self.assertEqual(sum(text.count("count=True") for text in texts), 100)

    async def test_add_all_enables_only_visible_text_and_news_channels(self):
        await self.invoke("add-all", reason="  Enable walking  ")
        self.interaction.guild.fetch_member.assert_awaited_once_with(456)
        rows = await self.rows("guild_channels")
        self.assertEqual({r["channel_id"] for r in rows}, {"789", "790", "791", "792"})
        self.assertTrue(all((r["guild_id"], r["count_steps"], r["react"]) == ("123", 1, 1) for r in rows))
        audits = await self.rows("mod_audit")
        self.assertEqual(len(audits), 4)
        self.assertEqual({r["target_id"] for r in audits}, {r["channel_id"] for r in rows})
        self.assertTrue(all((r["guild_id"], r["actor_id"], r["target_kind"], r["action"], r["reason"])
                            == ("123", "456", "channel", "channels_add", "Enable walking")
                            and r["created_at"] > 0 for r in audits))
        self.assertEqual(self.reply(), "Enabled 4 channels; skipped 1 (no access); 0 already enabled. "
                         "Channels created later are not added automatically.")
        self.assertEqual(self.interaction.edit_original_response.await_args.kwargs["allowed_mentions"].to_dict()["parse"], [])
        parameters = {p.name: p for p in self.channels.get_command("add-all").parameters}
        self.assertEqual(set(parameters), {"reason", "count"})
        self.assertTrue(parameters["reason"].required)
        self.assertIs(parameters["count"].default, True)

    async def test_add_all_repeat_is_idempotent_no_new_audit(self):
        await self.invoke("add", channel=self.channel, reason="Existing", count=False, react=False)
        await self.invoke("add-all", reason="Enable rest")
        self.assertIn("Enabled 3 channels; skipped 1 (no access); 1 already enabled.", self.reply())
        rows, audits = await self.rows("guild_channels"), await self.rows("mod_audit")
        self.assertEqual((rows[0]["count_steps"], rows[0]["react"]), (0, 0))
        await self.invoke("add-all", reason="Repeat", count=False)
        self.assertEqual(await self.rows("guild_channels"), rows)
        self.assertEqual(await self.rows("mod_audit"), audits)
        self.assertIn("Enabled 0 channels; skipped 1 (no access); 4 already enabled.", self.reply())

    async def test_add_all_reply_uses_singular_for_one_channel(self):
        del self.interaction.guild.text_channels[1:4]
        await self.invoke("add-all", reason="One")
        self.assertIn("Enabled 1 channel; skipped 1 (no access); 0 already enabled.", self.reply())

    async def test_add_all_count_false_sets_flag(self):
        await self.invoke("add-all", reason="Reactions only", count=False)
        rows = await self.rows("guild_channels")
        self.assertEqual(len(rows), 4)
        self.assertTrue(all((r["count_steps"], r["react"]) == (0, 1) for r in rows))

    async def test_add_all_role_removed_after_interaction_refused(self):
        self.interaction.guild.fetch_member.return_value.guild_permissions.manage_guild = False
        self.assertTrue(self.interaction.user.guild_permissions.manage_guild)
        with patch.object(self.writer, "run", wraps=self.writer.run) as run:
            await self.invoke("add-all", reason="Test")
        self.assertEqual(run.await_count, 1)  # Entry restriction read only.
        self.assertEqual(self.reply(), "Manage Server permission is required.")
        for table in ("guilds", "guild_channels", "mod_audit"):
            self.assertEqual(await self.rows(table), [])

    async def test_add_all_member_fetch_failure_refused_nothing_written(self):
        for error, status in ((discord.NotFound, 404), (discord.HTTPException, 500), (discord.Forbidden, 403)):
            with self.subTest(error=error.__name__):
                self.interaction.guild.fetch_member.side_effect = error(
                    SimpleNamespace(status=status, reason="synthetic"), "Cannot fetch")
                with patch.object(self.writer, "run", wraps=self.writer.run) as run:
                    await self.invoke("add-all", reason="Test")
                self.assertEqual(run.await_count, 1)
                self.assertEqual(self.reply(), "Could not confirm your Manage Server permission. Nothing was changed.")
                for table in ("guilds", "guild_channels", "mod_audit"):
                    self.assertEqual(await self.rows(table), [])

    async def test_add_all_requires_reason_and_refuses_excluded(self):
        await self.invoke("add-all", reason="  ")
        self.assertEqual(self.reply(), "A reason is required.")
        self.interaction.guild.fetch_member.assert_not_awaited()
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        await self.invoke("add-all", reason="Test")
        self.assertIn("excluded", self.reply().lower())
        self.interaction.guild.fetch_member.assert_not_awaited()
        self.assertEqual(await self.rows("guild_channels"), [])
        self.assertEqual(await self.rows("mod_audit"), [])

    async def test_add_all_batch_is_one_writer_job(self):
        await self.conn.execute("CREATE TRIGGER fail_channel BEFORE INSERT ON guild_channels "
                                "WHEN NEW.channel_id='791' BEGIN SELECT RAISE(ABORT,'channel failed'); END")
        with patch.object(self.writer, "run", wraps=self.writer.run) as run:
            with self.assertRaisesRegex(Exception, "channel failed"):
                await self.invoke("add-all", reason="Must roll back")
        self.assertEqual(run.await_count, 2)  # Entry read and one atomic mutation.
        for table in ("guilds", "guild_channels", "mod_audit"):
            self.assertEqual(await self.rows(table), [])

    async def test_add_all_exclusion_committed_while_queued_writes_nothing(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        entered, release = asyncio.Event(), asyncio.Event()

        async def exclude(conn):
            entered.set()
            await release.wait()
            await conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")

        original_fetch = self.interaction.guild.fetch_member.side_effect
        blocker = None

        async def fetch_then_block(member_id):
            nonlocal blocker
            blocker = asyncio.create_task(self.writer.run(exclude))
            await entered.wait()
            return self.interaction.guild.fetch_member.return_value

        self.interaction.guild.fetch_member.side_effect = fetch_then_block
        command = asyncio.create_task(self.invoke("add-all", reason="Test"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            await self.wait_for_queue_or_completion(command)
            self.assertFalse(command.done())
        finally:
            release.set()
            await asyncio.gather(command, *([blocker] if blocker is not None else []))
            self.interaction.guild.fetch_member.side_effect = original_fetch
        self.assertIn("excluded", self.reply().lower())
        self.assertEqual(await self.rows("guild_channels"), [])
        self.assertEqual(await self.rows("mod_audit"), [])

    async def test_excluded_moderator_cannot_add_remove_or_list_channels(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        await self.conn.execute("INSERT INTO guild_channels VALUES ('123','789',1,1)")
        for name, args in (("add", {"channel": self.channel, "reason": "Test", "count": False}),
                           ("remove", {"channel": self.channel, "reason": "Test"}), ("list", {})):
            await self.invoke(name, **args)
            self.assertIn("excluded", self.reply().lower())
        self.assertEqual((await self.rows("guild_channels"))[0]["count_steps"], 1)
        self.assertEqual(await self.rows("mod_audit"), [])

    async def wait_for_queue_or_completion(self, command):
        async def ready():
            while not command.done() and self.writer._queue.empty():
                await asyncio.sleep(0)
        await asyncio.wait_for(ready(), timeout=1)

    async def test_exclusion_committed_while_command_queued_refuses_add_remove_and_list(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO guild_channels VALUES ('123','789',1,1)")
        for action in ("add", "remove", "list"):
            with self.subTest(action=action):
                await self.conn.execute("DELETE FROM restrictions")
                entered, release = asyncio.Event(), asyncio.Event()

                async def exclude(conn):
                    entered.set()
                    await release.wait()
                    await conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")

                original_authorize = self.group.authorize
                blocker = None

                async def authorize_then_block(interaction):
                    nonlocal blocker
                    allowed = await original_authorize(interaction)
                    blocker = asyncio.create_task(self.writer.run(exclude))
                    await entered.wait()
                    return allowed

                with patch.object(self.group, "authorize", side_effect=authorize_then_block):
                    args = {} if action == "list" else {"channel": self.channel, "reason": "Test"}
                    command = asyncio.create_task(self.invoke(action, **args))
                    try:
                        await entered.wait()
                        await self.wait_for_queue_or_completion(command)
                        self.assertFalse(command.done())
                    finally:
                        release.set()
                        await asyncio.gather(command, blocker)
                self.assertIn("excluded", self.reply().lower())
                self.assertEqual((await self.rows("guild_channels"))[0]["count_steps"], 1)
                self.assertEqual(await self.rows("mod_audit"), [])

    async def test_list_never_exposes_policy_from_rolled_back_writer_job(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        inserted, release = asyncio.Event(), asyncio.Event()

        async def abort_policy(conn):
            await conn.execute("INSERT INTO guild_channels VALUES ('123','789',1,1)")
            inserted.set()
            await release.wait()
            raise ValueError("forced rollback")

        original_authorize = self.group.authorize
        mutation = None

        async def authorize_then_insert(interaction):
            nonlocal mutation
            allowed = await original_authorize(interaction)
            mutation = asyncio.create_task(self.writer.run(abort_policy))
            await inserted.wait()
            return allowed

        with patch.object(self.group, "authorize", side_effect=authorize_then_insert):
            command = asyncio.create_task(self.invoke("list"))
            try:
                await inserted.wait()
                await self.wait_for_queue_or_completion(command)
            finally:
                release.set()
                results = await asyncio.gather(mutation, command, return_exceptions=True)
        self.assertIsInstance(results[0], ValueError)
        self.assertIsNone(results[1])
        self.assertNotIn("789", self.reply())
        self.assertEqual(await self.rows("guild_channels"), [])
