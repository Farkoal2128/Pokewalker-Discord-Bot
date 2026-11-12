"""Pokemon-trading T2: /walker-admin trade-channels fake interaction tests with real writer jobs."""

import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

from pokewalker.db import Writer, open_db

ADDED, REMOVED = "Trade channel added.", "Trade channel removed."
WARNING = " Missing Send Messages; trade pings will fail until permissions recover."


def perms(view=True, send=True):
    return lambda member: SimpleNamespace(view_channel=view, send_messages=send)


class AdminTradeChannelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await open_db(":memory:", allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.conn.close)
        self.addAsyncCleanup(self.writer.close)
        try:
            module = importlib.import_module("pokewalker.bot.admin_trade_channels")
        except ModuleNotFoundError:
            self.fail("T2 trade channel commands absent")
        admin = importlib.import_module("pokewalker.bot.admin_channels")
        self.bot = SimpleNamespace(db=self.conn, writer=self.writer)
        self.admin = admin.WalkerAdmin(self.bot)
        self.group = module.TradeChannels(self.admin)
        self.admin.add_command(self.group)
        self.interaction = SimpleNamespace(
            guild_id=123, guild=SimpleNamespace(me=object()),
            user=SimpleNamespace(id=456, guild_permissions=SimpleNamespace(manage_guild=True)),
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), is_done=lambda: False),
            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())
        self.interaction.response.defer.side_effect = lambda **kwargs: setattr(
            self.interaction.response, "is_done", lambda: True)
        self.channel = SimpleNamespace(id=789, guild=SimpleNamespace(id=123), permissions_for=perms())
        # 789 and 792 are eligible; 790 lacks Send, 791 lacks View, 793 lacks both.
        access = [(True, True), (True, False), (False, True), (True, True), (False, False)]
        self.interaction.guild.text_channels = [
            SimpleNamespace(id=789 + i, permissions_for=perms(view, send)) for i, (view, send) in enumerate(access)]
        self.interaction.guild.fetch_member = AsyncMock(return_value=SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_guild=True)))

    async def invoke(self, name, **kwargs):
        command = self.group.get_command(name)
        await command.callback(command.binding, self.interaction, **kwargs)

    def reply(self):
        """Last reply text; the ephemeral flag comes from the deferral that precedes it."""
        self.interaction.response.defer.assert_awaited_with(ephemeral=True)
        self.interaction.response.send_message.assert_not_awaited()
        call = self.interaction.edit_original_response.await_args
        self.assertEqual(call.kwargs["allowed_mentions"].to_dict()["parse"], [])
        return call.kwargs["content"]

    async def rows(self, table):
        async with self.conn.execute(f"SELECT * FROM {table}") as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def assert_unchanged(self, trade_channels=()):
        self.assertEqual({r["channel_id"] for r in await self.rows("trade_channels")}, set(trade_channels))
        self.assertEqual(await self.rows("mod_audit"), [])
        self.assertEqual(await self.rows("guild_channels"), [])

    async def exclude(self):
        await self.conn.execute("INSERT OR IGNORE INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")

    async def test_group_registered_under_walker_admin_with_four_commands_and_required_reason(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(SimpleNamespace())
        self.addAsyncCleanup(bot.close)
        root = bot.tree.get_command("walker-admin")
        self.assertTrue(root.guild_only)
        self.assertTrue(root.default_permissions.manage_guild)
        self.assertIsNotNone(root.get_command("channels"))
        group = root.get_command("trade-channels")
        self.assertIsNotNone(group)
        self.assertIs(group.parent, root)
        self.assertEqual({c.name for c in group.commands}, {"add", "add-all", "remove", "list"})
        required = {name: {p.name for p in group.get_command(name).parameters if p.required}
                    for name in ("add", "add-all", "remove", "list")}
        self.assertEqual(required, {"add": {"channel", "reason"}, "add-all": {"reason"},
                                    "remove": {"channel", "reason"}, "list": set()})
        for name in ("add", "remove"):
            channel = next(p for p in group.get_command(name).parameters if p.name == "channel")
            self.assertEqual([t.value for t in channel.channel_types], [0, 5])
        self.assertIn("trade-channels", {o["name"] for o in root.to_dict(bot.tree)["options"]})

    async def test_add_and_remove_write_row_and_audit_atomically(self):
        await self.invoke("add", channel=self.channel, reason="  Trade here  ")
        self.assertEqual(self.reply(), ADDED)
        self.assertEqual(await self.rows("trade_channels"), [{"guild_id": "123", "channel_id": "789"}])
        self.assertEqual(len(await self.rows("guilds")), 1)
        self.assertEqual(await self.rows("guild_channels"), [])
        audit = (await self.rows("mod_audit"))[0]
        self.assertEqual((audit["guild_id"], audit["actor_id"], audit["target_kind"], audit["target_id"],
                          audit["action"], audit["reason"]),
                         ("123", "456", "channel", "789", "trade_channels_add", "Trade here"))
        self.assertGreater(audit["created_at"], 1_600_000_000)
        await self.invoke("remove", channel=self.channel, reason="Stop trading")
        self.assertEqual(self.reply(), REMOVED)
        self.assertEqual(await self.rows("trade_channels"), [])
        self.assertEqual([(r["action"], r["reason"]) for r in await self.rows("mod_audit")],
                         [("trade_channels_add", "Trade here"), ("trade_channels_remove", "Stop trading")])
        await self.conn.execute("DELETE FROM mod_audit")
        await self.conn.execute("INSERT INTO trade_channels VALUES ('123','790')")
        await self.conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON mod_audit "
                                "BEGIN SELECT RAISE(ABORT,'audit failed'); END")
        with self.assertRaisesRegex(Exception, "audit failed"):
            await self.invoke("add", channel=self.channel, reason="Must roll back")
        self.channel.id = 790
        with self.assertRaisesRegex(Exception, "audit failed"):
            await self.invoke("remove", channel=self.channel, reason="Must roll back")
        await self.assert_unchanged({"790"})

    async def test_add_twice_is_idempotent_audits_each_call(self):
        await self.invoke("add", channel=self.channel, reason="First")
        await self.invoke("add", channel=self.channel, reason="Second")
        self.assertEqual(self.reply(), ADDED)
        self.assertEqual(await self.rows("trade_channels"), [{"guild_id": "123", "channel_id": "789"}])
        self.assertEqual([(r["action"], r["reason"]) for r in await self.rows("mod_audit")],
                         [("trade_channels_add", "First"), ("trade_channels_add", "Second")])

    async def test_add_warns_without_send_messages(self):
        self.channel.permissions_for = perms(send=False)
        await self.invoke("add", channel=self.channel, reason="Test")
        self.assertEqual(self.reply(), ADDED + WARNING)
        self.assertEqual(len(await self.rows("trade_channels")), 1)
        await self.invoke("remove", channel=self.channel, reason="Test")
        self.assertEqual(self.reply(), REMOVED)

    async def test_non_manager_and_other_guild_channel_refused(self):
        calls = (("add", {"channel": self.channel, "reason": "Test"}), ("add-all", {"reason": "Test"}),
                 ("remove", {"channel": self.channel, "reason": "Test"}), ("list", {}))
        self.interaction.user.guild_permissions.manage_guild = False
        for name, args in calls:
            await self.invoke(name, **args)
            self.assertIn("Manage Server", self.reply())
        self.interaction.user.guild_permissions.manage_guild = True
        self.interaction.guild_id = None
        await self.invoke("add", channel=self.channel, reason="Test")
        self.assertIn("Manage Server", self.reply())
        self.interaction.guild_id = 123
        self.channel.guild.id = 999
        for name in ("add", "remove"):
            await self.invoke(name, channel=self.channel, reason="Test")
            self.assertEqual(self.reply(), "Choose a channel in this server.")
        self.interaction.guild.fetch_member.assert_not_awaited()
        await self.assert_unchanged()
        self.assertEqual(await self.rows("guilds"), [])

    async def test_excluded_refused_at_entry_and_inside_job(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO trade_channels VALUES ('123','790')")
        calls = (("add", {"channel": self.channel, "reason": "Test"}), ("add-all", {"reason": "Test"}),
                 ("remove", {"channel": SimpleNamespace(id=790, guild=self.channel.guild), "reason": "Test"}),
                 ("list", {}))
        original_authorize = self.admin.authorize

        async def authorize_then_exclude(interaction):
            allowed = await original_authorize(interaction)
            await self.writer.run(lambda conn: conn.execute(
                "INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)"))
            return allowed

        for name, args in calls:
            with self.subTest(stage="inside job", name=name):
                await self.conn.execute("DELETE FROM restrictions")
                with patch.object(self.admin, "authorize", side_effect=authorize_then_exclude):
                    await self.invoke(name, **args)
                self.assertIn("excluded", self.reply().lower())
                self.assertNotIn("790", self.reply())
                await self.assert_unchanged({"790"})
        for name, args in calls:
            with self.subTest(stage="entry", name=name):
                await self.invoke(name, **args)
                self.assertIn("excluded", self.reply().lower())
        self.interaction.guild.fetch_member.assert_awaited_once_with(456)  # Only the in-job add-all case.
        await self.assert_unchanged({"790"})

    async def test_blank_reason_refused_no_write(self):
        for name, args in (("add", {"channel": self.channel}), ("remove", {"channel": self.channel}),
                           ("add-all", {})):
            await self.invoke(name, reason=" \t ", **args)
            self.assertEqual(self.reply(), "A reason is required.")
        self.interaction.guild.fetch_member.assert_not_awaited()
        await self.assert_unchanged()
        self.assertEqual(await self.rows("guilds"), [])

    async def test_add_all_requires_view_and_send_skips_others_idempotent(self):
        await self.invoke("add", channel=self.channel, reason="Existing")
        await self.invoke("add-all", reason="  Open trading  ")
        self.interaction.guild.fetch_member.assert_awaited_once_with(456)
        self.assertEqual(self.reply(), "Enabled 1 channel; skipped 3 (no access); 1 already enabled. "
                         "Channels created later are not added automatically.")
        self.assertEqual({r["channel_id"] for r in await self.rows("trade_channels")}, {"789", "792"})
        audits = await self.rows("mod_audit")
        self.assertEqual([(r["guild_id"], r["actor_id"], r["target_kind"], r["target_id"], r["action"], r["reason"])
                          for r in audits[1:]],
                         [("123", "456", "channel", "792", "trade_channels_add", "Open trading")])
        self.assertGreater(audits[1]["created_at"], 1_600_000_000)
        await self.invoke("add-all", reason="Repeat")
        self.assertEqual(self.reply(), "Enabled 0 channels; skipped 3 (no access); 2 already enabled. "
                         "Channels created later are not added automatically.")
        self.assertEqual(await self.rows("mod_audit"), audits)
        self.assertEqual(len(await self.rows("trade_channels")), 2)
        await self.conn.execute("DELETE FROM trade_channels")
        await self.invoke("add-all", reason="Both")
        self.assertIn("Enabled 2 channels; skipped 3 (no access); 0 already enabled.", self.reply())
        self.assertEqual(await self.rows("guild_channels"), [])

    async def test_add_all_fetch_member_failure_or_no_permission_refused(self):
        for error, status in ((discord.NotFound, 404), (discord.HTTPException, 500), (discord.Forbidden, 403)):
            with self.subTest(error=error.__name__):
                self.interaction.guild.fetch_member.side_effect = error(
                    SimpleNamespace(status=status, reason="synthetic"), "Cannot fetch")
                with patch.object(self.writer, "run", wraps=self.writer.run) as run:
                    await self.invoke("add-all", reason="Test")
                self.assertEqual(run.await_count, 1)  # Entry restriction read only.
                self.assertEqual(self.reply(), "Could not confirm your Manage Server permission. Nothing was changed.")
        self.interaction.guild.fetch_member.side_effect = None
        self.interaction.guild.fetch_member.return_value.guild_permissions.manage_guild = False
        with patch.object(self.writer, "run", wraps=self.writer.run) as run:
            await self.invoke("add-all", reason="Test")
        self.assertEqual(run.await_count, 1)
        self.assertEqual(self.reply(), "Manage Server permission is required.")
        await self.assert_unchanged()
        self.assertEqual(await self.rows("guilds"), [])

    async def test_add_all_rolls_back_whole_batch_on_error(self):
        await self.conn.execute("CREATE TRIGGER fail_channel BEFORE INSERT ON trade_channels "
                                "WHEN NEW.channel_id='792' BEGIN SELECT RAISE(ABORT,'channel failed'); END")
        with patch.object(self.writer, "run", wraps=self.writer.run) as run:
            with self.assertRaisesRegex(Exception, "channel failed"):
                await self.invoke("add-all", reason="Must roll back")
        self.assertEqual(run.await_count, 2)  # Entry read and one atomic mutation.
        await self.assert_unchanged()
        self.assertEqual(await self.rows("guilds"), [])

    async def test_list_reads_only_this_guild_writes_no_audit(self):
        await self.invoke("list")
        self.assertEqual(self.reply(), "No trade channels configured.")
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123'),('555')")
        await self.conn.execute("INSERT INTO trade_channels VALUES ('123','790'),('123','789'),('555','111')")
        await self.invoke("list")
        self.assertEqual(self.reply(), "<#789>\n<#790>")
        self.interaction.followup.send.assert_not_awaited()
        await self.assert_unchanged({"789", "790", "111"})
        await self.conn.executemany("INSERT INTO trade_channels VALUES ('123',?)",
                                    [(str(100000000000000000 + i),) for i in range(150)])
        await self.invoke("list")
        first = self.interaction.edit_original_response.await_args
        followups = self.interaction.followup.send.await_args_list
        texts = [self.reply(), *(call.args[0] for call in followups)]
        self.assertTrue(followups)
        self.assertTrue(all(len(text) < 2000 for text in texts))
        self.assertTrue(all(call.kwargs["ephemeral"] for call in followups))
        self.assertTrue(all(call.kwargs["allowed_mentions"].to_dict()["parse"] == []
                            for call in (first, *followups)))
        mentions = "\n".join(texts).split("\n")
        self.assertEqual(len(mentions), 152)
        self.assertNotIn("<#111>", mentions)
        await self.assert_unchanged({"789", "790", "111", *(str(100000000000000000 + i) for i in range(150))})


if __name__ == "__main__":
    unittest.main()
