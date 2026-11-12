"""C5 `/trade` command, enabled-channel gate, partner ping and sweep prune (pokemon-trading T7)."""

from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord

from pokewalker.db import Writer, open_db
from pokewalker.services import profiles
from test_reactions import FakeDiscord, http_error

CONTENT = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))
ENABLED, OTHER = 50, 51
DISABLED = ("Trading isn't enabled in this channel. A moderator can enable it with "
            "/walker-admin trade-channels add.")
PING = "<@789>, <@456> wants to trade a Pokémon with you. Run /trade and choose them to join."
PINGED = "Pinged them here."
NO_PING = "Couldn't ping them; ask them to run /trade."
RATE_LIMITED = "Opened without a ping (one per 10 minutes). Ask them to run /trade."


class TradeCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.module = importlib.import_module("pokewalker.bot.trade")
        except ModuleNotFoundError:
            self.fail("pokewalker.bot.trade is absent")
        self.assertTrue(hasattr(self.module, "command"), "/trade command factory is absent")
        self.walker_module = importlib.import_module("pokewalker.bot.walker")
        self.conn = await open_db(":memory:", allow_unpatched=True)
        self.addAsyncCleanup(self.conn.close)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.bot = FakeDiscord(self.conn)
        self.bot.writer = self.writer
        self.bot.content = CONTENT
        self.now = 2_000_000_000.0
        self.walker = self.walker_module.Walker(self.bot, clock=lambda: self.now, rng=random.Random(8))
        self.bot.walker = self.walker
        for user in (456, 789, 999):
            await self.writer.run(lambda conn, user=user: profiles.enroll(
                conn, 123, user, 1, CONTENT, random.Random(8), datetime.now(timezone.utc)))
        await self.sql("INSERT INTO trade_channels(guild_id,channel_id) VALUES ('123',?)", (str(ENABLED),))
        self.command = self.module.command(self.bot)

    # --- helpers -------------------------------------------------------------------------------------------------

    async def sql(self, statement, args=()):
        await self.writer.run(lambda conn: conn.execute(statement, args))

    async def rows(self, sql, args=()):
        return [dict(row) for row in await self.conn.execute_fetchall(sql, args)]

    async def snapshot(self):
        return {table: await self.rows(f"SELECT * FROM {table}")
                for table in ("sessions", "trades", "trade_sides", "profiles")}

    def interaction(self, user, channel_id=ENABLED, *, parent_id=None, can_send=True, send_error=None):
        trades_at_send = []

        async def send(*args, **kwargs):
            self.assertFalse(self.conn.in_transaction, "ping sent inside the writer transaction")
            trades_at_send.append(await self.rows("SELECT state FROM trades"))
            if send_error is not None:
                raise send_error

        channel = SimpleNamespace(id=channel_id, parent_id=parent_id, send=AsyncMock(side_effect=send),
                                  permissions_for=lambda member: SimpleNamespace(send_messages=can_send))
        return SimpleNamespace(user=SimpleNamespace(id=user), guild_id=123, channel_id=channel_id, channel=channel,
                               guild=SimpleNamespace(me=SimpleNamespace(id=99)), trades_at_send=trades_at_send,
                               response=SimpleNamespace(defer=AsyncMock()), edit_original_response=AsyncMock())

    async def trade(self, user, member=None, *, bot=False, **options):
        interaction = self.interaction(user, **options)
        target = None if member is None else SimpleNamespace(id=member, bot=bot)
        await self.command.callback(interaction, member=target)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        return interaction

    def reply(self, interaction):
        return interaction.edit_original_response.await_args.kwargs

    def screen(self, interaction):
        kwargs = self.reply(interaction)
        self.assertIn("embed", kwargs, kwargs.get("content"))
        return kwargs["embed"].description

    async def latest_session(self, user):
        return (await self.rows("SELECT * FROM sessions WHERE user_id=? ORDER BY rowid DESC LIMIT 1",
                                (str(user),)))[0]

    # --- registration --------------------------------------------------------------------------------------------

    def walker_bot(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(SimpleNamespace(), clock=lambda: 5.0)
        self.addAsyncCleanup(bot.drain)
        return bot

    async def test_trade_is_top_level_guild_only_and_changes_global_manifest(self):
        bot = self.walker_bot()
        command = bot.tree.get_command("trade")
        self.assertIsInstance(command, discord.app_commands.Command)
        self.assertIsNone(command.parent)
        self.assertTrue(command.guild_only)
        self.assertEqual(command.description, "Trade a Pokémon with a member of this server")
        self.assertEqual([(p.name, p.required, p.type) for p in command.parameters],
                         [("member", False, discord.AppCommandOptionType.user)])
        names = [c.name for c in bot.tree.get_commands()]
        self.assertEqual(names[names.index("raid") + 1], "trade")
        self.assertIsNone(bot.tree.get_command("trade", guild=discord.Object(id=123)))
        before = bot.command_manifest_hash()
        bot.tree.remove_command("trade")
        self.assertNotEqual(bot.command_manifest_hash(), before)

    async def test_walker_command_has_no_trade_option(self):
        bot = self.walker_bot()
        walker = bot.tree.get_command("walker")
        self.assertIsInstance(walker, discord.app_commands.Command)
        self.assertEqual(walker.parameters, [])
        self.assertNotIn("trade", json.dumps(walker.to_dict(bot.tree)).lower())

    # --- channel gate --------------------------------------------------------------------------------------------

    async def test_disabled_channel_refused_privately_nothing_created(self):
        before = await self.snapshot()
        for member in (789, None):
            interaction = await self.trade(456, member, channel_id=OTHER)
            self.assertEqual(self.reply(interaction)["content"], DISABLED)
            interaction.channel.send.assert_not_awaited()
        self.assertEqual(await self.snapshot(), before)

    async def test_thread_refused_even_if_parent_enabled(self):
        before = await self.snapshot()
        interaction = await self.trade(456, 789, channel_id=60, parent_id=ENABLED)
        self.assertEqual(self.reply(interaction)["content"], DISABLED)
        interaction.channel.send.assert_not_awaited()
        self.assertEqual(await self.snapshot(), before)

    # --- open, ping, join ----------------------------------------------------------------------------------------

    async def test_open_creates_session_screen_and_pings_partner_only_after_commit(self):
        interaction = await self.trade(456, 789)
        [trade] = await self.rows("SELECT * FROM trades")
        self.assertEqual(trade["state"], "open")
        session = await self.latest_session(456)
        self.assertEqual((session["revision"], session["expires_at"], session["guild_id"]),
                         (0, self.now + self.walker_module.IDLE_SECONDS, "123"))
        self.assertEqual(json.loads(session["selection"]), {"trade_id": trade["trade_id"], "trade_revision": 0})
        description = self.screen(interaction)
        self.assertIn("Trade with <@789>", description)
        self.assertIn(PINGED, description)
        ids = [item.custom_id for item in self.reply(interaction)["view"].children]
        self.assertIn(f"pw:v1:{session['session_id']}:0:trade_pick", ids)
        interaction.channel.send.assert_awaited_once()
        self.assertEqual(interaction.channel.send.await_args.args, (PING,))
        self.assertEqual(interaction.trades_at_send, [[{"state": "open"}]])
        mentions = self.reply(interaction)["allowed_mentions"]
        self.assertEqual(mentions.to_dict(), discord.AllowedMentions.none().to_dict())

    async def test_ping_allowed_mentions_only_partner(self):
        interaction = await self.trade(456, 789)
        mentions = interaction.channel.send.await_args.kwargs["allowed_mentions"]
        self.assertFalse(mentions.everyone)
        self.assertFalse(mentions.roles)
        self.assertEqual([user.id for user in mentions.users], [789])
        self.assertEqual(mentions.to_dict()["parse"], [])

    async def test_join_and_reopen_do_not_ping(self):
        await self.trade(456, 789)
        joined = await self.trade(789, 456)
        joined.channel.send.assert_not_awaited()
        self.assertIn("Trade with <@456>", self.screen(joined))
        self.assertNotIn("Waiting for them to join", self.screen(joined))
        reopened = await self.trade(456, 789)
        reopened.channel.send.assert_not_awaited()
        self.assertIn("Trade with <@789>", self.screen(reopened))
        self.assertNotIn(PINGED, self.screen(reopened))
        self.assertEqual(len(await self.rows("SELECT * FROM trades")), 1)

    async def test_second_open_within_10_minutes_not_pinged_opener_told(self):
        await self.trade(456, 789)
        await self.sql("UPDATE trades SET state='cancelled',ended_at=?", (self.now,))
        self.now += 60
        second = await self.trade(456, 999)
        second.channel.send.assert_not_awaited()
        self.assertIn(RATE_LIMITED, self.screen(second))
        self.assertEqual(len(await self.rows("SELECT * FROM trades WHERE state='open'")), 1)
        # Without Send Messages nothing is reserved or sent; the opener is told privately.
        await self.sql("UPDATE trades SET state='cancelled',ended_at=?", (self.now,))
        self.now += 600
        denied = await self.trade(456, 789, can_send=False)
        denied.channel.send.assert_not_awaited()
        self.assertIn(NO_PING, self.screen(denied))
        self.assertEqual((await self.rows("SELECT last_trade_ping_at FROM profiles WHERE user_id='456'"))[0],
                         {"last_trade_ping_at": self.now - 660})

    async def test_ping_failure_keeps_trade_and_tells_opener(self):
        for error in (http_error(discord.Forbidden, 403), OSError("network down")):
            with self.subTest(error=type(error).__name__):
                await self.sql("UPDATE trades SET state='cancelled',ended_at=?", (self.now,))
                self.now += 600
                interaction = await self.trade(456, 789, send_error=error)
                interaction.channel.send.assert_awaited_once()
                self.assertIn(NO_PING, self.screen(interaction))
                self.assertNotIn(PINGED, self.screen(interaction))
                [trade] = await self.rows("SELECT * FROM trades WHERE state='open'")
                session = await self.latest_session(456)
                self.assertEqual(json.loads(session["selection"])["trade_id"], trade["trade_id"])

    # --- refusals ------------------------------------------------------------------------------------------------

    async def refused(self, user, member, text, **options):
        before = await self.rows("SELECT * FROM sessions")
        interaction = await self.trade(user, member, **options)
        self.assertEqual(self.reply(interaction)["content"], text)
        self.assertNotIn("embed", self.reply(interaction))
        interaction.channel.send.assert_not_awaited()
        self.assertEqual(await self.rows("SELECT * FROM sessions"), before)

    async def test_refusal_texts_for_every_status(self):
        await self.sql("INSERT INTO opt_outs(guild_id,user_id,created_at) VALUES ('123','456',?)", (self.now,))
        await self.refused(456, 789, "Run /walker-account opt-in first")
        await self.sql("DELETE FROM opt_outs")
        await self.refused(111, 789, "Open /walker to enroll before trading.")
        await self.sql("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        await self.refused(456, 789, self.walker_module.EXCLUDED)
        await self.sql("DELETE FROM restrictions")
        await self.refused(456, 789, "You can't trade with a bot.", bot=True)
        await self.refused(456, None, "Use /trade member:@someone to start or join a trade.")
        await self.refused(456, 456, "You can't trade with yourself.")
        await self.refused(456, 222, "They haven't started walking in this server.")
        await self.sql("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','999',1)")
        await self.refused(456, 999, "They can't trade right now.")
        await self.sql("DELETE FROM restrictions")
        self.assertEqual(await self.rows("SELECT * FROM trades"), [])
        await self.trade(456, 789)
        await self.trade(789, 456)
        await self.refused(456, 999, "You're already in a trade with <@789>; finish or cancel it first.")
        await self.refused(999, 456, "They're in another trade right now.")
        await self.sql("UPDATE profiles SET last_trade_at=? WHERE user_id='999'", (self.now - 1000,))
        await self.refused(999, 789, "You can trade again in 23h 44m.")
        await self.sql("UPDATE profiles SET last_trade_at=NULL WHERE user_id='999'")
        await self.sql("UPDATE profiles SET last_trade_at=? WHERE user_id='789'", (self.now - 1000,))
        await self.refused(999, 789, "They can't trade again yet.")
        self.assertEqual(len(await self.rows("SELECT * FROM trades")), 1)

    async def test_bare_trade_reopens_current_trade(self):
        await self.trade(456, 789)
        [trade] = await self.rows("SELECT * FROM trades")
        bare = await self.trade(456)
        bare.channel.send.assert_not_awaited()
        self.assertIn("Trade with <@789>", self.screen(bare))
        session = await self.latest_session(456)
        self.assertEqual(json.loads(session["selection"]), {"trade_id": trade["trade_id"], "trade_revision": 0})
        self.assertEqual(session["expires_at"], self.now + self.walker_module.IDLE_SECONDS)
        # The invitee has not joined, so a bare /trade does not open the trade for them.
        await self.refused(789, None, "Use /trade member:@someone to start or join a trade.")

    # --- sweep ---------------------------------------------------------------------------------------------------

    async def test_sweep_prunes_trades(self):
        await self.trade(456, 789)
        await self.sql("UPDATE trades SET state='cancelled',ended_at=?", (self.now - 86400,))
        await self.trade(789, 999)
        [idle] = await self.rows("SELECT trade_id,expires_at FROM trades WHERE state='open'")
        bot = self.walker_bot()
        bot.writer, bot.content = self.writer, CONTENT
        bot.walker.clock = lambda: idle["expires_at"]
        await bot._sweep_once()
        self.assertEqual(await self.rows("SELECT trade_id,state FROM trades"),
                         [{"trade_id": idle["trade_id"], "state": "expired"}])


if __name__ == "__main__":
    unittest.main()
