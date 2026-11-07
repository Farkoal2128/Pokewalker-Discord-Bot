"""D21/D29 passive finds, atomic grants and private summaries."""

import importlib
from contextlib import closing
import random
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from content.balance import load_table
from pokewalker.bot.walker import Walker
from pokewalker.services import milestones
import test_stepping as stepping_tests


class FindTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = stepping_tests.SteppingTests.asyncSetUp
    rows = stepping_tests.SteppingTests.rows
    credit = stepping_tests.SteppingTests.credit

    def items(self):
        return importlib.import_module('pokewalker.services.items')

    async def meter(self, value):
        await self.conn.execute('UPDATE profiles SET find_meter_c=? WHERE profile_id=?', (value, self.pid))

    async def find_meter(self):
        return (await self.rows('profiles'))[0]['find_meter_c']

    async def find(self, mid='find', at=10000, awarded=2000, item='poke_ball', quantity=5):
        async def apply(conn):
            async with conn.execute('SELECT * FROM profiles WHERE profile_id=?', (self.pid,)) as cursor:
                profile = dict(await cursor.fetchone())
            meter = await self.items().apply_finds(conn, profile, awarded, at, mid, self.rng, self.content)
            await conn.execute('UPDATE profiles SET find_meter_c=? WHERE profile_id=?', (meter, self.pid))
            return meter
        with patch.object(self.items(), 'roll_find', return_value={'item': item, 'quantity': quantity}) as roll:
            result = await self.writer.run(apply)
        return result, roll.call_count

    async def grant(self, item, quantity):
        return await self.writer.run(lambda c: self.items().grant(c, self.pid, item, quantity))

    async def stock(self, **items):
        await self.conn.executemany('INSERT OR REPLACE INTO inventory VALUES (?,?,?)',
                                    [(self.pid, item, quantity) for item, quantity in items.items()])

    async def seed_finds(self, times):
        await self.conn.executemany('INSERT INTO finds(profile_id,message_id,item_id,quantity,outcome,created_at) '
                                   "VALUES (?,?,'poke_ball',5,'granted',?)",
                                   [(self.pid, f'old-{i}', at) for i, at in enumerate(times)])

    async def test_find_every_100_awarded_keeps_remainder(self):
        await self.meter(9900)
        self.assertEqual(await self.find(awarded=425), (325, 1))
        self.assertEqual(await self.find('next', at=10060, awarded=25), (350, 0))
        self.assertEqual([(r['item_id'], r['quantity']) for r in await self.rows('inventory')], [('poke_ball', 5)])

    async def test_three_finds_per_rolling_hour_then_frozen_no_backlog(self):
        for i in range(3):
            await self.meter(9900)
            self.assertEqual((await self.find(str(i), at=10000 + i * 60))[1], 1)
        self.assertEqual(await self.find_meter(), 0)
        for i in range(3, 8):
            self.assertEqual(await self.find(str(i), at=10000 + i * 60), (0, 0))
        self.assertEqual(len(await self.rows('finds')), 3)

    async def test_third_find_sets_meter_zero_rest_of_message_discarded(self):
        await self.seed_finds([9900, 9950])
        await self.meter(9900)
        self.assertEqual(await self.find(awarded=2000), (0, 1))
        self.assertEqual(await self.find('frozen', at=10060), (0, 0))

    async def test_freeze_lifts_by_message_time_when_oldest_find_leaves_hour(self):
        await self.seed_finds([6400, 6500, 6600, 20000])
        await self.meter(9900)
        self.assertEqual(await self.find(at=9999), (9900, 0))
        # Lower boundary is excluded; a future find never counts.
        self.assertEqual(await self.find('thawed', at=10000), (0, 1))
        self.assertEqual(await self.find('later', at=10200, awarded=25), (25, 0))

    async def test_roll_uses_find_table_weights_10000_seeded(self):
        table = load_table('find_table')['rows']
        self.assertEqual(sum(r['weight'] for r in table), 10000)
        # Every midpoint ticket exercises a weight interval, including both rares.
        class Tickets(random.Random):
            def random(self):
                return (next(self.tickets) + .5) / 10000
        rng = Tickets(23)
        rng.tickets = iter(range(10000))
        observed = {r['item']: 0 for r in table}
        for _ in range(10000):
            row = self.items().roll_find(rng)
            self.assertIn(row, table)
            observed[row['item']] += 1
        self.assertEqual(observed, {r['item']: r['weight'] for r in table})
        left, right = random.Random(23), random.Random(23)
        self.assertEqual([self.items().roll_find(left) for _ in range(20)],
                         [self.items().roll_find(right) for _ in range(20)])

    async def test_ordinary_pack_that_does_not_fit_is_whole_find_10_stardust_no_reroll(self):
        await self.stock(poke_ball=248)
        await self.meter(9900)
        self.assertEqual((await self.find())[1], 1)
        self.assertEqual((await self.rows('inventory'))[0]['quantity'], 248)
        self.assertEqual((await self.rows('profiles'))[0]['stardust'], 10)
        self.assertEqual((await self.rows('finds'))[0]['outcome'], 'overflow')
        self.assertEqual([(r['reason'], r['delta']) for r in await self.rows('resource_ledger')], [('find_overflow', 10)])

    async def test_rare_find_granted_with_full_bag_outside_units(self):
        await self.stock(poke_ball=250, master_ball=0, shiny_lure=0)
        for item in ('master_ball', 'shiny_lure'):
            self.assertEqual(await self.grant(item, 1), ('granted', 0))
        self.assertEqual(await self.items().bag_units(self.conn, self.pid), 250)
        self.assertEqual({r['item_id']: r['quantity'] for r in await self.rows('inventory')},
                         {'poke_ball': 250, 'master_ball': 1, 'shiny_lure': 1})

    async def test_bag_units_exclude_all_rare_pockets_including_ticket(self):
        from content.balance import limits
        pockets = tuple(limits()['rare_pockets'])
        await self.stock(poke_ball=245, great_ball=5, **dict.fromkeys(pockets, 1))
        self.assertEqual(await self.items().bag_units(self.conn, self.pid), 250)
        self.assertEqual(self.items().RARE, pockets)
        self.assertIn('world_legendary_ticket', self.items().RARE)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('other')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('other','other','456',0)")
        await self.conn.execute("INSERT INTO inventory VALUES ('other','poke_ball',12)")
        self.assertEqual(await self.items().bag_units(self.conn, 'other'), 12)

    async def test_existing_lure_and_master_ball_pockets_unchanged(self):
        await self.stock(poke_ball=250)
        for item in ('master_ball', 'shiny_lure'):
            with self.subTest(item=item):
                self.assertEqual(await self.grant(item, 1), ('granted', 0))
                self.assertEqual(await self.grant(item, 1), ('duplicate_rare', 500))
                with self.assertRaises(ValueError):
                    await self.grant(item, 2)
        self.assertEqual(await self.items().bag_units(self.conn, self.pid), 250)
        self.assertEqual({r['item_id']: r['quantity'] for r in await self.rows('inventory')},
                         {'poke_ball': 250, 'master_ball': 1, 'shiny_lure': 1})
        self.assertEqual((await self.rows('profiles'))[0]['stardust'], 1000)

    async def test_ticket_generic_grant_uses_rare_pack_and_duplicate_rules(self):
        await self.stock(poke_ball=250)
        with self.assertRaises(ValueError):
            await self.grant('world_legendary_ticket', 2)
        self.assertEqual(await self.grant('world_legendary_ticket', 1), ('granted', 0))
        self.assertEqual(await self.grant('world_legendary_ticket', 1), ('duplicate_rare', 500))
        self.assertEqual(await self.items().bag_units(self.conn, self.pid), 250)
        self.assertEqual({r['item_id']: r['quantity'] for r in await self.rows('inventory')},
                         {'poke_ball': 250, 'world_legendary_ticket': 1})

    async def test_duplicate_rare_500_stardust_pocket_stays_one(self):
        for item in ('master_ball', 'shiny_lure'):
            await self.stock(**{item: 1})
            await self.meter(9900)
            self.assertEqual((await self.find(item, item=item, quantity=1))[1], 1)
        self.assertEqual((await self.rows('profiles'))[0]['stardust'], 1000)
        self.assertEqual([r['quantity'] for r in await self.rows('inventory')], [1, 1])
        self.assertEqual([r['outcome'] for r in await self.rows('finds')], ['duplicate_rare'] * 2)
        self.assertEqual([r['reason'] for r in await self.rows('resource_ledger')], ['find_duplicate_rare'] * 2)

    async def test_stardust_row_takes_no_units(self):
        await self.stock(poke_ball=250)
        await self.meter(9900)
        await self.find(item='stardust', quantity=100)
        self.assertEqual(await self.items().bag_units(self.conn, self.pid), 250)
        self.assertEqual((await self.rows('profiles'))[0]['stardust'], 100)
        self.assertEqual((await self.rows('finds'))[0]['outcome'], 'stardust')
        self.assertEqual((await self.rows('resource_ledger'))[0]['reason'], 'find')

    async def test_find_commits_with_step_credit_receipt_and_ledger(self):
        await self.meter(9900)
        await self.conn.execute("CREATE TRIGGER fail_find BEFORE INSERT ON resource_ledger WHEN NEW.reason='find' "
                                "BEGIN SELECT RAISE(ABORT,'find ledger unavailable'); END")
        with patch.object(self.items(), 'roll_find', return_value={'item': 'poke_ball', 'quantity': 5}):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'find ledger unavailable'):
                await self.credit()
            for table in ('step_events', 'finds', 'inventory', 'action_receipts', 'resource_ledger'):
                self.assertEqual(await self.rows(table), [], table)
            self.assertEqual(await self.find_meter(), 9900)
            await self.conn.execute('DROP TRIGGER fail_find')
            await self.credit()
        await self.credit()
        self.assertEqual(await self.find_meter(), 300)
        self.assertEqual(len(await self.rows('step_events')), 1)
        self.assertEqual(len(await self.rows('finds')), 1)
        receipt = (await self.rows('action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']), ('find:100', 'find', self.pid))
        line = (await self.rows('resource_ledger'))[0]
        self.assertEqual((line['resource'], line['resource_id'], line['delta']), ('item', 'poke_ball', 5))

    async def test_find_receipt_replay_never_rerolls_or_changes_meter(self):
        await self.meter(9900)
        await self.find()
        before = {t: await self.rows(t) for t in ('profiles', 'finds', 'inventory', 'resource_ledger')}
        self.assertEqual(await self.find(), (1900, 0))
        self.assertEqual({t: await self.rows(t) for t in before}, before)

    async def test_paused_or_excluded_message_adds_no_find(self):
        await self.meter(9900)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('123','456',1)")
        await self.credit()
        await self.conn.execute('UPDATE restrictions SET paused=0,excluded=1')
        await self.credit('excluded', 10060)
        self.assertEqual(await self.rows('finds'), [])
        self.assertEqual(await self.find_meter(), 9900)
        self.assertEqual(await self.rows('action_receipts'), [])

    async def test_home_lists_recent_find_outcomes(self):
        for i, (item, quantity) in enumerate((('poke_ball', 5), ('great_ball', 3),
                                             ('master_ball', 1), ('stardust', 100))):
            await self.meter(9900)
            await self.stock(poke_ball=250, master_ball=1)
            await self.find(str(i), at=10000 + i * 3601, item=item, quantity=quantity)
        walker = Walker(SimpleNamespace(content=self.content))
        session = {'profile_id': self.pid, 'guild_id': '123', 'user_id': '456',
                   'session_id': 'test', 'revision': 0, 'selection': '{}'}
        rendered = await self.writer.run(lambda c: walker.home(c, session, None))
        description = rendered['embed'].description
        self.assertIn('Great Ball', description)
        self.assertIn('overflow', description.lower())
        self.assertIn('10 Stardust', description)
        self.assertIn('500 Stardust', description)
        self.assertIn('100 Stardust', description)
        self.assertNotIn('Poké Ball', description)
        recent = await self.items().recent_finds(self.conn, self.pid)
        self.assertEqual([r['message_id'] for r in recent], ['3', '2', '1'])

    async def test_claim_full_bag_and_pocket_retains_inbox_rewards(self):
        await self.stock(poke_ball=250, master_ball=1)
        await self.conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) VALUES ('claim','123','456',?,999999)", (self.pid,))
        await self.conn.executemany('INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) '
                                   "VALUES (?,'reward','item',?,?,0)",
                                   [(self.pid, 'poke_ball', 5), (self.pid, 'master_ball', 1)])
        session = {'session_id': 'claim', 'profile_id': self.pid, 'guild_id': '123', 'user_id': '456', 'revision': 0}
        with patch.object(self.items(), 'grant', side_effect=AssertionError('Claim must not convert rewards')):
            result = await self.writer.run(lambda c: milestones.claim(c, session, 10000))
        self.assertEqual(result['moved'], {'item': 0, 'stardust': 0, 'candy': 0})
        self.assertEqual([r['remaining'] for r in await self.rows('inbox_items')], [5, 1])
        self.assertEqual((await self.rows('profiles'))[0]['stardust'], 0)

    async def test_existing_stepping_suite_unchanged(self):
        await self.credit()
        profile = (await self.rows('profiles'))[0]
        self.assertEqual((profile['encounter_meter_c'], profile['find_meter_c']), (400, 400))
        self.assertEqual((await self.rows('step_events'))[0]['awarded_c'], 400)
        self.assertEqual(await self.rows('finds'), [])

    async def test_grant_validates_quantity_and_active_transaction(self):
        with self.assertRaisesRegex(RuntimeError, 'transaction'):
            await self.items().grant(self.conn, self.pid, 'poke_ball', 1)
        for item, quantity in (('poke_ball', 0), ('poke_ball', -1), ('poke_ball', 1.5),
                               ('poke_ball', True), ('master_ball', 2)):
            with self.assertRaises(ValueError):
                await self.grant(item, quantity)
        self.assertEqual(await self.rows('inventory'), [])

    async def test_ordinary_pack_exact_fit_and_empty_bag(self):
        self.assertEqual(await self.items().bag_units(self.conn, self.pid), 0)
        await self.stock(poke_ball=245)
        self.assertEqual(await self.grant('poke_ball', 5), ('granted', 0))
        self.assertEqual(await self.items().bag_units(self.conn, self.pid), 250)

    async def test_find_history_and_bag_are_profile_scoped(self):
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('other','123','999',0)")
        await self.conn.execute("INSERT INTO inventory VALUES ('other','poke_ball',250)")
        await self.conn.executemany('INSERT INTO finds(profile_id,message_id,item_id,quantity,outcome,created_at) '
                                   "VALUES ('other',?,'poke_ball',5,'granted',?)",
                                   [(f'other-{i}', 10000) for i in range(3)])
        await self.meter(9900)
        self.assertEqual(await self.find(), (1900, 1))
        self.assertEqual(await self.items().bag_units(self.conn, self.pid), 5)
        self.assertEqual([r['message_id'] for r in await self.items().recent_finds(self.conn, self.pid)], ['find'])

    async def test_migration_upgrades_v4_without_losing_inventory_or_meter(self):
        from pokewalker import db
        path = self.path.with_name('v4.db')
        with closing(sqlite3.connect(path)) as old:
            for migration in sorted(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))[:4]:
                old.executescript(migration.read_text(encoding='utf-8'))
            old.executescript("PRAGMA user_version=4; INSERT INTO guilds(guild_id) VALUES ('1'); "
                              "INSERT INTO profiles(profile_id,guild_id,user_id,created_at,find_meter_c) "
                              "VALUES ('old','1','2',0,9900); INSERT INTO inventory VALUES ('old','poke_ball',250);")
        upgraded = await db.open_db(path, allow_unpatched=True)
        try:
            async with upgraded.execute("SELECT find_meter_c FROM profiles WHERE profile_id='old'") as cursor:
                self.assertEqual((await cursor.fetchone())[0], 9900)
            self.assertEqual(await self.items().bag_units(upgraded, 'old'), 250)
            self.assertEqual(await self.items().recent_finds(upgraded, 'old'), [])
        finally:
            await upgraded.close()

    async def test_migration_reopen_preserves_rows_and_deletion_cascades(self):
        await self.meter(9900)
        await self.find()
        from pokewalker.db import open_db
        other = await open_db(self.path, allow_unpatched=True)
        await other.close()
        self.assertEqual(len(await self.rows('finds')), 1)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("UPDATE finds SET outcome='unknown'")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute('UPDATE finds SET quantity=0')
        await self.conn.execute('DELETE FROM profiles WHERE profile_id=?', (self.pid,))
        self.assertEqual(await self.rows('finds'), [])
