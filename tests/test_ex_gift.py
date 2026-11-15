"""C3 send snapshots and C4 complete giftable catalog, without Discord I/O."""

import importlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from content.balance import load_table
from pokewalker.db import Writer
from pokewalker.services import iv_items
import test_db


CONTENT = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))


class CatalogTests(unittest.TestCase):
    def service(self):
        self.assertIsNotNone(importlib.util.find_spec('pokewalker.services.ex_gift'),
                             'EX-Gift catalog provider is absent')
        return importlib.import_module('pokewalker.services.ex_gift')

    def test_catalog_covers_every_grantable_item(self):
        service = self.service()
        offered = {key for keys in service.catalog(CONTENT).values() for key in keys}
        granted = set()

        def weighted(node):
            if isinstance(node, dict):
                if {'item', 'weight'} <= node.keys():
                    granted.add(node['item'])
                for value in node.values():
                    weighted(value)
            elif isinstance(node, list):
                for value in node:
                    weighted(value)

        for path in Path('content/balance').glob('*.json'):
            weighted(json.loads(path.read_text(encoding='utf-8')))
        for bundle in load_table('milestones')['bundles'].values():
            granted.update(bundle)
        for rewards in load_table('arena')['rules']['leaderboard']['rewards']:
            granted.update(rewards)
        granted.update(load_table('capacities')['limits']['starter_kit'])
        granted.update(load_table('conversion_rates')['purchase_stardust'])
        granted.discard('stardust')
        if 'evolution_item' in granted:
            granted.remove('evolution_item')
            granted.update(item['id'] for item in CONTENT['evolution_items'])
        self.assertLessEqual(granted, offered)

    def test_catalog_union_categories_and_25_option_pages(self):
        service = self.service()
        categories = service.catalog(CONTENT)
        self.assertEqual({key: len(value) for key, value in categories.items()},
                         {'Balls': 3, 'Berries': 4, 'IV items': 2, 'Arena': 7,
                          'Evolution': 50, 'Rare': 6})
        self.assertEqual(set(categories['IV items']), set(iv_items.ITEMS))
        rates = load_table('conversion_rates')['stardust_per_unit']
        rare = load_table('capacities')['limits']['rare_pockets']
        arena = load_table('arena')['rules']
        expected = (set(rates) - {'evolution_item'} | set(rare)
                    | {item['id'] for item in CONTENT['evolution_items']}
                    | set(arena['x_items']['items'])
                    | {f'arena_ticket:{tier}' for tier in arena['tickets']['tiers']})
        flattened = [key for keys in categories.values() for key in keys]
        self.assertEqual(set(flattened), expected)
        self.assertEqual(len(flattened), len(expected))
        for category, keys in categories.items():
            reconstructed = []
            for n in range((len(keys) + 24) // 25):
                part, pages = service.page(CONTENT, category, False, n)
                self.assertLessEqual(len(part), 25)
                self.assertEqual(pages, (len(keys) + 24) // 25)
                reconstructed.extend(part)
            self.assertEqual(reconstructed, keys)
        self.assertEqual(service.page(CONTENT, 'Evolution', False, 99), ([], 2))
        self.assertEqual(service.page(CONTENT, 'Evolution', False, -1), ([], 2))
        self.assertEqual(service.page(CONTENT, 'unknown', False, 0), ([], 0))
        self.assertEqual(service.page(CONTENT, 'Balls', True, 0), (list(service.EX_ITEMS), 1))
        self.assertEqual(service.label('arena_ticket:bronze', CONTENT), 'Bronze Arena Ticket')
        self.assertEqual(service.label('poke_ball', CONTENT), 'Poké Ball')
        self.assertEqual(service.label('golden_bottlecap', CONTENT), 'Golden Bottlecap')
        for item in CONTENT['evolution_items']:
            self.assertEqual(service.label(item['id'], CONTENT), item['name_en'])
        changed = dict(CONTENT, evolution_items=[*CONTENT['evolution_items'],
                                               {'id': 'new_stone', 'name_en': 'New Stone'}])
        self.assertIn('new_stone', service.catalog(changed)['Evolution'])
        fresh_rates = load_table('conversion_rates')
        fresh_rates['stardust_per_unit']['new_ball'] = 1
        with patch.object(service, 'load_table', side_effect=lambda name: fresh_rates if
                          name == 'conversion_rates' else load_table(name)):
            self.assertIn('new_ball', service.catalog(CONTENT)['Balls'])

    def test_ex_ids_match_schema_and_are_disjoint(self):
        service = self.service()
        self.assertEqual(service.EX_ITEMS, {
            'time_gear_fragment': 'Time Gear Fragment', 'shiny_patch': 'Shiny Patch',
            'golden_bottlecap': 'Golden Bottlecap', 'ex_attack': 'EX-Attack',
            'ex_defense': 'EX-Defense', 'arena_ex_voucher': 'Arena EX-Voucher'})
        ordinary = {key for keys in service.catalog(CONTENT).values() for key in keys}
        self.assertTrue(ordinary.isdisjoint(service.EX_ITEMS))


class ExGiftTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_db.DatabaseTests.scalar
    profile = test_db.DatabaseTests.profile

    async def asyncSetUp(self):
        await test_db.DatabaseTests.asyncSetUp(self)
        self.service = importlib.import_module('pokewalker.services.ex_gift')
        self.p1 = await self.profile('u', 'g')
        self.p2 = await self.profile('u', 'h')
        self.p3 = await self.profile('v', 'g')
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('empty')")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','v',1)")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('g','u',1)")
        await self.conn.execute("INSERT INTO opt_outs VALUES ('h','u',0)")
        await self.conn.commit()
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)

    async def send(self, **overrides):
        args = dict(send_id='send', owner_id='owner', admin_guild_id='admin',
                    scope='all', guild_id=None, user_id=None, items=['poke_ball'],
                    content=CONTENT, now=100)
        args.update(overrides)
        return await self.writer.run(lambda conn: self.service.send(conn, **args))

    async def rows(self, table):
        return [dict(row) for row in await self.conn.execute_fetchall(f'SELECT * FROM {table}')]

    async def test_send_all_snapshots_every_profile_once(self):
        result = await self.send()
        self.assertEqual((result['status'], result['replayed']), ('sent', False))
        self.assertEqual([result[key] for key in ('servers', 'servers_with_recipients', 'recipients')],
                         [3, 2, 3])
        recipients = await self.rows('ex_gift_recipients')
        self.assertEqual({row['profile_id'] for row in recipients}, {self.p1, self.p2, self.p3})
        self.assertEqual(len(recipients), 3)
        self.assertTrue(all(row['claimed_at'] is None for row in recipients))
        for table in ('action_receipts', 'mod_audit', 'inbox_items', 'ex_items'):
            self.assertEqual(await self.rows(table), [])

    async def test_send_server_and_one_user_scopes(self):
        for scope, uid, ids in [('server', None, {self.p1, self.p3}), ('user', 'u', {self.p1})]:
            with self.subTest(scope=scope):
                result = await self.send(send_id=scope, scope=scope, guild_id='g', user_id=uid)
                self.assertEqual([result[k] for k in ('servers', 'servers_with_recipients', 'recipients')],
                                 [1, 1, len(ids)])
                rows = await self.conn.execute_fetchall(
                    'SELECT profile_id FROM ex_gift_recipients WHERE gift_id=?', (scope,))
                self.assertEqual({row[0] for row in rows}, ids)

    async def test_refusals_write_nothing(self):
        await self.profile('elsewhere', 'h')
        await self.conn.commit()
        cases = [('unknown_server', dict(scope='server', guild_id='missing')),
                 ('no_profile', dict(scope='user', guild_id='g', user_id='missing')),
                 ('no_profile', dict(scope='user', guild_id='g', user_id='elsewhere')),
                 ('no_recipients', dict(scope='server', guild_id='empty')),
                 ('invalid', dict(items=[])), ('invalid', dict(items=['poke_ball'] * 11)),
                 ('invalid', dict(items=['unknown'])), ('invalid', dict(items=['evolution_item'])),
                 ('invalid', dict(items='poke_ball')), ('invalid', dict(items=[{}])),
                 ('invalid', dict(scope='bad')),
                 ('invalid', dict(scope='all', guild_id='g')),
                 ('invalid', dict(scope='server', guild_id='g', user_id='u'))]
        for status, args in cases:
            with self.subTest(args=args):
                self.assertEqual(await self.send(**args), {'status': status})
                self.assertEqual(await self.rows('ex_gifts'), [])
                self.assertEqual(await self.rows('ex_gift_recipients'), [])
        await self.conn.execute('DELETE FROM profiles')
        await self.conn.commit()
        self.assertEqual(await self.send(), {'status': 'no_recipients'})

    async def test_ten_slot_mixed_package_with_duplicates(self):
        items = ['poke_ball', 'poke_ball', 'arena_ticket:gold', 'time_gear_fragment',
                 'shiny_patch', 'golden_bottlecap', 'ex_attack', 'ex_defense',
                 'arena_ex_voucher', 'x_attack']
        result = await self.send(items=items)
        self.assertEqual(result['items'], items)
        self.assertEqual(json.loads((await self.rows('ex_gifts'))[0]['items']), items)

    async def test_same_send_id_sends_once_returns_stored_counts(self):
        first = await self.send()
        await self.conn.execute('DELETE FROM profiles WHERE profile_id=?', (self.p2,))
        await self.profile('late', 'late-guild')
        await self.conn.commit()
        replay = await self.send(items=[], scope='server', guild_id='missing', now=200)
        self.assertEqual(replay, dict(first, replayed=True))
        self.assertEqual(len(await self.rows('ex_gifts')), 1)
        self.assertEqual(len(await self.rows('ex_gift_recipients')), 2)
        self.assertEqual(await self.send(owner_id='other'), {'status': 'invalid'})

    async def test_excluded_owner_refused_before_lookup(self):
        await self.send()
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('admin')")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('admin','owner',1)")
        await self.conn.commit()
        with patch.object(self.service, 'lookup', side_effect=AssertionError('lookup before exclusion')):
            self.assertEqual(await self.send(), {'status': 'excluded'})
            self.assertEqual(await self.send(send_id='new'), {'status': 'excluded'})
        self.assertEqual(len(await self.rows('ex_gifts')), 1)

    async def test_profile_enrolled_after_send_gets_nothing(self):
        await self.send()
        late = await self.profile('late', 'g')
        await self.conn.execute('DELETE FROM profiles WHERE profile_id=?', (self.p1,))
        replacement = await self.profile('u', 'g')
        await self.conn.commit()
        recipients = {row['profile_id'] for row in await self.rows('ex_gift_recipients')}
        self.assertTrue({late, replacement}.isdisjoint(recipients))
        self.assertEqual(len(recipients), 2)

    async def test_one_user_send_stores_no_user_id(self):
        await self.send(scope='user', guild_id='g', user_id='v')
        stored = (await self.rows('ex_gifts'))[0]
        self.assertEqual(set(stored), {'gift_id', 'owner_id', 'scope', 'guild_id', 'items',
                                      'servers', 'servers_with_recipients', 'recipients', 'created_at'})
        self.assertEqual(stored['owner_id'], 'owner')
        recipient = (await self.rows('ex_gift_recipients'))[0]
        self.assertEqual(recipient, {'gift_id': 'send', 'profile_id': self.p3, 'claimed_at': None})

    async def test_owner_can_send_to_own_profile(self):
        result = await self.send(owner_id='u', scope='user', guild_id='g', user_id='u')
        self.assertEqual(result['status'], 'sent')
        self.assertEqual((await self.rows('ex_gift_recipients'))[0]['profile_id'], self.p1)

    async def test_history_newest_first_paged_and_lookup(self):
        for n in range(12):
            await self.send(send_id=f'send{n:02}', owner_id=f'owner{n % 2}', now=100 + n // 2)
        rows, total = await self.service.history(self.conn, 0)
        self.assertEqual(total, 12)
        self.assertEqual([row['gift_id'] for row in rows], [f'send{n:02}' for n in range(11, 1, -1)])
        tail, total = await self.service.history(self.conn, 10)
        self.assertEqual([row['gift_id'] for row in tail], ['send01', 'send00'])
        self.assertEqual(await self.service.history(self.conn, 20), ([], 12))
        self.assertEqual(await self.service.lookup(self.conn, 'send11'), rows[0])
        self.assertEqual(rows[0]['items'], ['poke_ball'])
        self.assertIsNone(await self.service.lookup(self.conn, 'missing'))

    async def test_send_requires_writer_transaction_and_rolls_back_with_job(self):
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await self.service.send(self.conn, send_id='x', owner_id='owner', admin_guild_id='g',
                                    scope='all', guild_id=None, user_id=None, items=['poke_ball'],
                                    content=CONTENT, now=100)

        async def job(conn):
            await self.service.send(conn, send_id='x', owner_id='owner', admin_guild_id='g',
                                    scope='all', guild_id=None, user_id=None, items=['poke_ball'],
                                    content=CONTENT, now=100)
            raise ValueError('cancel draft')

        with self.assertRaisesRegex(ValueError, 'cancel draft'):
            await self.writer.run(job)
        self.assertEqual(await self.rows('ex_gifts'), [])
        self.assertEqual(await self.rows('ex_gift_recipients'), [])

    async def test_ex_ids_are_accepted_by_schema(self):
        for key in self.service.EX_ITEMS:
            await self.conn.execute('INSERT INTO ex_items VALUES (?,?,1)', (self.p1, key))
        self.assertEqual(await self.scalar('SELECT count(*) FROM ex_items'), 6)
