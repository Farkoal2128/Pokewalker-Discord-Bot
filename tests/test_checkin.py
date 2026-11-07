"""D12/D22/D29 check-in grants, serialization and private command contract."""

import asyncio
from collections import Counter
import importlib
import json
import random
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from content.balance import load_table
from pokewalker.db import Writer, open_db
from pokewalker.services import items


class CheckinTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await open_db(':memory:', allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.conn.close)
        self.addAsyncCleanup(self.writer.close)
        self.pid = 'checkin-profile'
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES (?,'123','456',0)", (self.pid,))

    async def rows(self, table):
        async with self.conn.execute(f'SELECT * FROM {table}') as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def snapshot(self):
        return {name: await self.rows(name) for name in
                ('profiles', 'inventory', 'action_receipts', 'resource_ledger', 'restrictions')}

    async def checkin(self, now=10000, seed=1, guild=123, user=456):
        self.assertTrue(hasattr(items, 'checkin'), 'M3.2 check-in service is absent')
        return await self.writer.run(lambda conn: items.checkin(conn, guild, user, now, random.Random(seed)))

    async def command(self):
        try:
            module = importlib.import_module('pokewalker.bot.checkin')
        except ModuleNotFoundError:
            self.fail('M3.2 private /checkin command is absent')
        return module.command(SimpleNamespace(writer=self.writer))

    def interaction(self, guild=123):
        return SimpleNamespace(guild_id=guild, user=SimpleNamespace(id=456),
                               response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
                               edit_original_response=AsyncMock())

    async def test_checkin_grants_poke_ball_then_weighted_pack_seeded(self):
        result = await self.checkin()
        self.assertEqual(result, {'status': 'granted', 'outcomes': [
            {'item': 'poke_ball', 'quantity': 1, 'outcome': 'granted', 'dust': 0},
            {'item': 'great_ball', 'quantity': 1, 'outcome': 'granted', 'dust': 0}]})
        self.assertEqual({r['item_id']: r['quantity'] for r in await self.rows('inventory')},
                         {'poke_ball': 1, 'great_ball': 1})
        self.assertEqual((await self.rows('profiles'))[0]['last_checkin_at'], 10000)

    async def test_pack_weights_35_30_20_15_never_rare_seeded(self):
        self.assertTrue(hasattr(items, 'roll_checkin'), 'M3.2 common pack roll is absent')
        class Tickets(random.Random):
            def random(self):
                return (next(self.tickets) + .5) / 100
        rng = Tickets(23)
        rng.tickets = iter(range(100))
        rows = [items.roll_checkin(rng) for _ in range(100)]
        self.assertEqual(Counter((r['item'], r['quantity']) for r in rows),
                         {('great_ball', 1): 35, ('razz_berry', 1): 30,
                          ('poke_ball', 2): 20, ('pinap_berry', 1): 15})
        left, right = random.Random(19), random.Random(19)
        self.assertEqual([items.roll_checkin(left) for _ in range(30)],
                         [items.roll_checkin(right) for _ in range(30)])
        self.assertTrue(all(r in load_table('checkin_table')['rows'] for r in rows))

    async def test_refused_within_60_minutes_of_last_success_no_grant_no_timer_change(self):
        await self.checkin(now=3599)
        before = await self.snapshot()
        for now, wait in ((3600, 3599), (7198.75, .25)):
            with self.subTest(now=now):
                self.assertEqual(await self.checkin(now=now), {'status': 'too_early', 'seconds_left': wait})
                self.assertEqual(await self.snapshot(), before)

    async def test_available_at_exactly_3600s_after_last_success_not_clock_hour(self):
        for start in (0, 3599):
            await self.conn.execute('UPDATE profiles SET last_checkin_at=?', (start,))
            result = await self.checkin(now=start + 3600)
            self.assertEqual(result['status'], 'granted')
            self.assertEqual((await self.rows('profiles'))[0]['last_checkin_at'], start + 3600)

    async def test_ball_first_then_pack_against_space_left_each_converts_independently(self):
        for units, expected_dust, expected_stock in ((249, 10, 250), (250, 20, 250)):
            with self.subTest(units=units):
                await self.conn.execute('UPDATE profiles SET last_checkin_at=NULL,stardust=0')
                await self.conn.execute('INSERT OR REPLACE INTO inventory VALUES (?, ?, ?)',
                                        (self.pid, 'poke_ball', units))
                result = await self.checkin(now=10000 + units, seed=0)
                self.assertEqual([o['dust'] for o in result['outcomes']],
                                 [0 if units == 249 else 10, 10])
                self.assertEqual(result['outcomes'][1]['quantity'], 2)
                self.assertEqual((await self.rows('profiles'))[0]['stardust'], expected_dust)
                self.assertEqual((await self.rows('inventory'))[0]['quantity'], expected_stock)

    async def test_always_restarts_timer_even_when_both_convert(self):
        await self.conn.execute('INSERT INTO inventory VALUES (?, ?, 250)', (self.pid, 'poke_ball'))
        self.assertEqual((await self.checkin())['status'], 'granted')
        self.assertEqual((await self.rows('profiles'))[0]['last_checkin_at'], 10000)
        self.assertEqual(await self.checkin(now=10001), {'status': 'too_early', 'seconds_left': 3599})
        self.assertEqual((await self.rows('profiles'))[0]['stardust'], 20)

    async def test_paused_and_excluded_refused_no_timer_change(self):
        for paused, until, excluded, status in ((1, None, 0, 'paused'),
                                               (1, 20000, 0, 'paused'),
                                               (1, None, 1, 'excluded')):
            with self.subTest(status=status, until=until):
                await self.conn.execute('INSERT OR REPLACE INTO restrictions '
                                        '(guild_id,user_id,paused,paused_until,excluded) VALUES (?,?,?,?,?)',
                                        ('123', '456', paused, until, excluded))
                before = await self.snapshot()
                with patch('pokewalker.services.profiles.time.time', return_value=10000):
                    result = await self.checkin()
                self.assertEqual(result['status'], status)
                if status == 'paused':
                    self.assertEqual(result['until'], None if until is None else '1970-01-01T05:33:20+00:00')
                self.assertEqual(await self.snapshot(), before)

    async def test_unenrolled_explains_walker(self):
        await self.conn.execute('DELETE FROM profiles')
        before = await self.snapshot()
        self.assertEqual(await self.checkin(), {'status': 'unenrolled'})
        interaction = self.interaction()
        command = await self.command()
        await command.callback(interaction)
        self.assertIn('/walker', interaction.edit_original_response.await_args.kwargs['content'])
        self.assertEqual(await self.snapshot(), before)

    async def test_two_commands_same_instant_one_grant(self):
        results = await asyncio.gather(self.checkin(), self.checkin())
        self.assertEqual([r['status'] for r in results], ['granted', 'too_early'])
        self.assertEqual(len(await self.rows('action_receipts')), 1)
        self.assertEqual(sum(r['quantity'] for r in await self.rows('inventory')), 2)

    async def test_receipt_and_ledger_match_grants(self):
        await self.conn.execute('INSERT INTO inventory VALUES (?, ?, 249)', (self.pid, 'poke_ball'))
        result = await self.checkin(seed=0)
        receipt = (await self.rows('action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']),
                         (f'checkin:{self.pid}:10000', 'checkin', self.pid))
        self.assertEqual(json.loads(receipt['result']), result)
        lines = await self.rows('resource_ledger')
        self.assertEqual([(r['receipt_key'], r['profile_id'], r['reason']) for r in lines],
                         [(receipt['key'], self.pid, 'checkin')] * 2)
        self.assertEqual([(r['resource'], r['resource_id'], r['delta']) for r in lines],
                         [('item', 'poke_ball', 1), ('stardust', None, 10)])

    async def test_command_guild_only_ephemeral_registered_locally(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(SimpleNamespace())
        self.addAsyncCleanup(bot.close)
        command = bot.tree.get_command('checkin')
        self.assertIsNotNone(command, '/checkin must be registered without synchronization')
        self.assertTrue(command.guild_only)
        self.assertEqual(command.parameters, [])
        interaction = self.interaction()
        bot.writer = self.writer
        with patch('pokewalker.bot.checkin.time.time', return_value=10000):
            await command.callback(interaction)
        response = interaction.edit_original_response.await_args
        self.assertIn('Poké Ball ×1', response.kwargs['content'])
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.response.send_message.assert_not_awaited()
        self.assertEqual(response.kwargs['allowed_mentions'].to_dict()['parse'], [])
        before = await self.snapshot()
        interaction.guild_id = None
        await command.callback(interaction)
        self.assertIn('server', interaction.edit_original_response.await_args.kwargs['content'])
        self.assertEqual(await self.snapshot(), before)

    async def test_command_defers_privately_before_waiting_on_busy_writer(self):
        blocked, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def block(conn):
            blocked.set()
            await release.wait()

        blocker = asyncio.create_task(self.writer.run(block))
        await asyncio.wait_for(blocked.wait(), timeout=2)
        interaction = self.interaction()
        command = await self.command()
        run = self.writer.run

        async def enqueue(job):
            queued.set()
            return await run(job)

        with patch.object(self.writer, 'run', side_effect=enqueue):
            pending = asyncio.create_task(command.callback(interaction))
            try:
                await asyncio.wait_for(queued.wait(), timeout=2)
                interaction.response.defer.assert_awaited_once_with(ephemeral=True)
                interaction.response.send_message.assert_not_awaited()
                interaction.edit_original_response.assert_not_awaited()
            finally:
                release.set()
                await asyncio.gather(blocker, pending)
        response = interaction.edit_original_response.await_args
        self.assertIn('Poké Ball ×1', response.kwargs['content'])
        self.assertEqual(response.kwargs['allowed_mentions'].to_dict()['parse'], [])
        self.assertEqual(len(await self.rows('action_receipts')), 1)

    async def test_failed_ledger_rolls_back_grants_receipt_and_timer(self):
        await self.conn.execute("CREATE TRIGGER fail_checkin BEFORE INSERT ON resource_ledger "
                                "BEGIN SELECT RAISE(ABORT,'ledger failed'); END")
        before = await self.snapshot()
        with self.assertRaisesRegex(Exception, 'ledger failed'):
            await self.checkin()
        self.assertEqual(await self.snapshot(), before)

    async def test_restrictions_read_after_pending_writer_job_and_expired_pause_allows(self):
        async def pause(conn):
            await conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,paused_until) "
                               "VALUES ('123','456',1,20000)")
        with patch('pokewalker.services.profiles.time.time', return_value=10000):
            _, result = await asyncio.gather(self.writer.run(pause), self.checkin())
        self.assertEqual(result['status'], 'paused')
        with patch('pokewalker.services.profiles.time.time', return_value=20000):
            self.assertEqual((await self.checkin(now=20000))['status'], 'granted')

    async def test_other_guild_user_cannot_access_profile_and_writer_is_required(self):
        before = await self.snapshot()
        self.assertEqual(await self.checkin(guild=999), {'status': 'unenrolled'})
        self.assertEqual(await self.checkin(user=999), {'status': 'unenrolled'})
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await items.checkin(self.conn, 123, 456, 10000, random.Random(1))
        self.assertEqual(await self.snapshot(), before)

    async def test_command_formats_overflow_wait_and_restriction_refusals(self):
        command = await self.command()
        interaction = self.interaction()
        await self.conn.execute('INSERT INTO inventory VALUES (?, ?, 249)', (self.pid, 'poke_ball'))
        with patch('pokewalker.bot.checkin.time.time', return_value=10000):
            await command.callback(interaction)
            self.assertIn('bag full, +10 Stardust', interaction.edit_original_response.await_args.kwargs['content'])
            await command.callback(interaction)
            self.assertIn('3600 seconds', interaction.edit_original_response.await_args.kwargs['content'])
        for until in (None, 20000):
            await self.conn.execute('INSERT OR REPLACE INTO restrictions '
                                    '(guild_id,user_id,paused,paused_until) VALUES (?,?,1,?)', ('123', '456', until))
            with patch('pokewalker.bot.checkin.time.time', return_value=10000):
                await command.callback(interaction)
            text = interaction.edit_original_response.await_args.kwargs['content']
            self.assertIn('paused', text)
            self.assertIn('indefinitely' if until is None else '1970-01-01T05:33:20+00:00', text)
        await self.conn.execute('UPDATE restrictions SET excluded=1')
        await command.callback(interaction)
        self.assertIn('Excluded', interaction.edit_original_response.await_args.kwargs['content'])
