"""M1.5 fake Gateway events with real writer commits and recorded reactions."""

import asyncio
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from pokewalker.db import Writer, open_db
from pokewalker.bot.walker import Walker
from pokewalker.services.reactions import ReactionService
from test_reactions import FakeDiscord


class MessageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await open_db(":memory:", allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.conn.close)
        self.addAsyncCleanup(self.writer.close)
        self.pid = str(uuid4())
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO guild_channels VALUES ('123','789',1,1)")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,encounter_meter_c) VALUES (?,'123','456',0,9900)", (self.pid,))
        self.bot = SimpleNamespace(writer=self.writer,
            content=json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8")),
            reactions=SimpleNamespace(reconcile_reaction=AsyncMock()))
        try:
            self.module = importlib.import_module("pokewalker.bot.messages")
        except ModuleNotFoundError:
            self.fail("M1.5 Gateway message adapter absent")

    def message(self, **kwargs):
        value = dict(id=100, guild=SimpleNamespace(id=123), author=SimpleNamespace(id=456, bot=False),
            webhook_id=None, channel=SimpleNamespace(id=789, parent_id=None),
            content="alpha bravo charlie delta", created_at=datetime.fromtimestamp(10000, timezone.utc))
        value.update(kwargs)
        return SimpleNamespace(**value)

    async def count(self, table):
        async with self.conn.execute(f"SELECT count(*) FROM {table}") as cursor:
            return (await cursor.fetchone())[0]

    async def test_ignores_bot_webhook_dm_unconfigured_disabled_channel(self):
        for overrides in (dict(author=SimpleNamespace(id=456, bot=True)), dict(webhook_id=9),
                          dict(guild=None), dict(guild=SimpleNamespace(id=999)),
                          dict(channel=SimpleNamespace(id=999, parent_id=None))):
            await self.module.on_message(self.bot, self.message(**overrides))
        await self.conn.execute("UPDATE guild_channels SET count_steps=0")
        await self.module.on_message(self.bot, self.message())
        await self.conn.execute("UPDATE guild_channels SET count_steps=1")
        await self.conn.execute("UPDATE guilds SET enabled=0")
        await self.module.on_message(self.bot, self.message())
        self.assertEqual(await self.count("step_events"), 0)
        self.bot.reactions.reconcile_reaction.assert_not_awaited()

    async def test_unenrolled_and_excluded_write_nothing(self):
        await self.module.on_message(self.bot, self.message(author=SimpleNamespace(id=999, bot=False)))
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        await self.module.on_message(self.bot, self.message())
        self.assertEqual(await self.count("step_events"), 0)
        self.assertEqual(await self.count("encounters"), 0)

    async def test_paused_records_discard_reason(self):
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('123','456',1)")
        await self.module.on_message(self.bot, self.message())
        async with self.conn.execute("SELECT * FROM step_events") as cursor:
            row = await cursor.fetchone()
        self.assertEqual((row["reason"], row["discarded_words"], row["awarded_c"]), ("paused", 4, 0))
        self.assertEqual(await self.count("encounters"), 0)

    async def test_reconcile_called_after_commit_not_inside(self):
        async def reconcile(eid):
            self.assertFalse(self.conn.in_transaction)
            async with self.conn.execute("SELECT * FROM reactions WHERE encounter_id=?", (eid,)) as cursor:
                row = await cursor.fetchone()
            self.assertEqual((row["desired"], row["actual"], row["message_id"]), ("add", "none", "100"))
        self.bot.reactions.reconcile_reaction.side_effect = reconcile
        await self.module.on_message(self.bot, self.message())
        self.bot.reactions.reconcile_reaction.assert_awaited_once()

    async def test_each_mint_adds_reaction_full_queue_does_not_and_walker_clears_all(self):
        bot = FakeDiscord(self.conn)
        bot.writer, bot.content = self.writer, self.bot.content
        bot.reactions = ReactionService(bot)
        for index in range(3):
            await self.conn.execute("UPDATE profiles SET encounter_meter_c=9900 WHERE profile_id=?", (self.pid,))
            message = self.message(id=100 + index, content=f"unique{index} fresh other words",
                                   created_at=datetime.fromtimestamp(10000 + index * 60, timezone.utc))
            await self.module.on_message(bot, message)
            self.assertEqual(await self.count("reactions"), index + 1)
            self.assertEqual(bot.calls[-1], ("add", 789, 100 + index))
        await self.conn.execute("UPDATE profiles SET encounter_meter_c=9900 WHERE profile_id=?", (self.pid,))
        await self.module.on_message(bot, self.message(id=103, content="fourth fresh other words",
            created_at=datetime.fromtimestamp(10180, timezone.utc)))
        self.assertEqual(await self.count("encounters"), 3)
        self.assertEqual(await self.count("reactions"), 3)
        self.assertEqual(len(bot.calls), 3)
        interaction = SimpleNamespace(guild_id=123, user=SimpleNamespace(id=456),
            response=SimpleNamespace(defer=AsyncMock()), edit_original_response=AsyncMock())
        await Walker(bot, clock=lambda: 10200).open(interaction)
        self.assertEqual(await self.count("reactions"), 0)
        self.assertEqual(bot.present, set())
        self.assertCountEqual(bot.calls[3:], [("remove", 789, mid) for mid in (100, 101, 102)])

    async def test_each_message_own_commit(self):
        commits = []
        await self.conn.set_trace_callback(lambda sql: commits.append(sql) if sql == "COMMIT" else None)
        await self.module.on_message(self.bot, self.message())
        self.assertEqual(len(commits), 1)
        await self.module.on_message(self.bot, self.message(id=101,
            created_at=datetime.fromtimestamp(10060, timezone.utc), content="other fresh words here"))
        self.assertEqual(len(commits), 2)
        self.assertEqual(await self.count("step_events"), 2)

    async def test_credit_counter_waits_for_commit_and_survives_caller_cancellation(self):
        self.bot.message_counts = {'received': 0, 'credited': 0}
        entered, release = asyncio.Event(), asyncio.Event()
        commit = self.conn.commit
        async def blocked_commit():
            entered.set()
            await release.wait()
            await commit()
        with patch.object(self.conn, 'commit', side_effect=blocked_commit):
            caller = asyncio.create_task(self.module.on_message(self.bot, self.message()))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                self.assertEqual(self.bot.message_counts['credited'], 0)
                caller.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await caller
            finally:
                release.set()
                await self.writer.close()
        self.assertEqual(await self.count('step_events'), 1)
        self.assertEqual(self.bot.message_counts, {'received': 1, 'credited': 1})

    async def test_credit_counter_never_counts_failed_commit_or_duplicate(self):
        self.bot.message_counts = {'received': 0, 'credited': 0}
        with patch.object(self.conn, 'commit', AsyncMock(side_effect=RuntimeError('commit failed'))):
            with self.assertRaisesRegex(RuntimeError, 'commit failed'):
                await self.module.on_message(self.bot, self.message())
        self.assertEqual(self.bot.message_counts['credited'], 0)
        self.assertEqual(await self.count('step_events'), 0)
        await self.module.on_message(self.bot, self.message())
        await self.module.on_message(self.bot, self.message())
        self.assertEqual(self.bot.message_counts, {'received': 3, 'credited': 1})

    async def test_thread_uses_parent_count_policy(self):
        await self.module.on_message(self.bot, self.message(channel=SimpleNamespace(id=888, parent_id=789)))
        self.assertEqual(await self.count("step_events"), 1)

    async def test_missing_timestamp_does_not_credit(self):
        message = self.message()
        del message.created_at
        await self.module.on_message(self.bot, message)
        async with self.conn.execute("SELECT reason FROM step_events") as cursor:
            self.assertEqual((await cursor.fetchone())[0], "no_timestamp")
        self.assertEqual(await self.count("encounters"), 0)
