"""D10/D44 and C3: profile capacity purchases on real SQLite transactions."""

import asyncio
import importlib
import json
import random
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import Mock, patch

from content.balance import limits, load_table
from pokewalker import db
from pokewalker.services import capacity, catching, items, milestones
import test_db
import test_storage as storage_tests
import test_conversion as conversion_tests
from test_catching import store_legacy


class CapacityTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_db.DatabaseTests.scalar

    async def asyncSetUp(self):
        await test_db.DatabaseTests.asyncSetUp(self)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,stardust) "
                                "VALUES ('p','123','456',0,20000)")
        await self.conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) "
                                "VALUES ('abcd','123','456','p',9000)")
        self.session = {'session_id': 'abcd', 'profile_id': 'p', 'guild_id': '123',
                        'user_id': '456', 'revision': 0}

    def capacity(self):
        try:
            return importlib.import_module('pokewalker.services.capacity')
        except ModuleNotFoundError:
            self.fail('Capacity service is absent')

    async def rows(self, sql, args=()):
        return [dict(row) for row in await self.conn.execute_fetchall(sql, args)]

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table}') for table in
                ('profiles', 'action_receipts', 'resource_ledger')}

    async def expand(self, kind='storage', expected=250, session=None):
        capacity = self.capacity()
        return await self.writer.run(lambda conn: capacity.expand(
            conn, session or self.session, kind, expected, 1000))

    async def test_migration_defaults_existing_profiles_to_250_250(self):
        prior = Path(self.temp.name) / 'prior'
        prior.mkdir()
        for migration in db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'):
            if int(migration.name[:4]) <= 11:
                shutil.copyfile(migration, prior / migration.name)
        path = Path(self.temp.name) / 'prior.sqlite3'
        with patch.object(db, 'MIGRATIONS', prior):
            old = await db.open_db(path)
        try:
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('g')")
            await old.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,stardust) "
                              "VALUES ('old','g','u',10,1234)")
            before = dict((await old.execute_fetchall('SELECT * FROM profiles'))[0])
        finally:
            await old.close()
        for _ in range(2):
            upgraded = await db.open_db(path)
            try:
                after = dict((await upgraded.execute_fetchall('SELECT * FROM profiles'))[0])
                self.assertEqual((after.pop('storage_limit', None), after.pop('bag_limit', None)),
                                 (250, 250))
                self.assertIsNone(after.pop('last_battle_at', 'missing'))
                self.assertIsNone(after.pop('overflow_uid', 'missing'))
                self.assertEqual(after, before)
                self.assertEqual((await upgraded.execute_fetchall('PRAGMA foreign_key_check')), [])
                self.assertEqual((await upgraded.execute_fetchall('PRAGMA user_version'))[0][0],
                                 len(list(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))))
            finally:
                await upgraded.close()

    async def test_expand_storage_debits_5000_adds_50_with_ledger(self):
        result = await self.expand()
        self.assertEqual(result, {'storage': 300, 'bag_units': 250,
                                  'rare_pockets': limits()['rare_pockets']})
        self.assertEqual(await self.scalar("SELECT stardust FROM profiles WHERE profile_id='p'"), 15000)
        receipt = (await self.rows('SELECT * FROM action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']),
                         ('expand:abcd:0', 'expand', 'p'))
        self.assertEqual(json.loads(receipt['result']), result)
        self.assertEqual(await self.rows('SELECT resource,resource_id,delta,reason FROM resource_ledger '
                                         'ORDER BY line_key'), [
            {'resource': 'stardust', 'resource_id': None, 'delta': -5000, 'reason': 'expand_storage'},
            {'resource': 'capacity', 'resource_id': 'storage', 'delta': 50, 'reason': 'expand_storage'}])

    async def test_storage_overflow_migration_nullable_foreign_key(self):
        profile = (await self.rows("SELECT * FROM profiles WHERE profile_id='p'"))[0]
        self.assertIn('overflow_uid', profile)
        self.assertIsNone(profile['overflow_uid'])
        keys = await self.rows('PRAGMA foreign_key_list(profiles)')
        self.assertIn(('overflow_uid', 'pokemon', 'SET NULL'),
                      [(r['from'], r['table'], r['on_delete']) for r in keys])

    async def test_expand_bag_debits_2500_adds_50(self):
        self.assertEqual(await self.expand('bag'), {'storage': 250, 'bag_units': 300,
                                                  'rare_pockets': limits()['rare_pockets']})
        self.assertEqual(await self.scalar("SELECT stardust FROM profiles WHERE profile_id='p'"), 17500)
        self.assertEqual(await self.rows('SELECT resource,resource_id,delta,reason FROM resource_ledger '
                                         'ORDER BY line_key'), [
            {'resource': 'stardust', 'resource_id': None, 'delta': -2500, 'reason': 'expand_bag'},
            {'resource': 'capacity', 'resource_id': 'bag', 'delta': 50, 'reason': 'expand_bag'}])

    async def test_at_cap_1000_refused_nothing_charged(self):
        for kind in ('storage', 'bag'):
            with self.subTest(kind=kind):
                await self.conn.execute(f'UPDATE profiles SET {kind}_limit=1000')
                profiles = await self.rows('SELECT * FROM profiles')
                self.assertEqual(await self.expand(kind, 1000, {**self.session, 'revision': kind}),
                                 {'status': 'at_cap'})
                self.assertEqual(await self.rows('SELECT * FROM profiles'), profiles)
        self.assertEqual(await self.scalar('SELECT count(*) FROM resource_ledger'), 0)

    async def test_insufficient_refused_no_change(self):
        for kind, price in (('storage', 5000), ('bag', 2500)):
            with self.subTest(kind=kind):
                await self.conn.execute('UPDATE profiles SET stardust=?', (price - 1,))
                profiles = await self.rows('SELECT * FROM profiles')
                self.assertEqual(await self.expand(kind, session={**self.session, 'revision': kind}),
                                 {'status': 'insufficient'})
                self.assertEqual(await self.rows('SELECT * FROM profiles'), profiles)
        self.assertEqual(await self.scalar('SELECT count(*) FROM resource_ledger'), 0)

    async def test_expand_twice_and_restart_before_reply_one_step(self):
        results = await asyncio.gather(self.expand(), self.expand())
        self.assertEqual(results[0], results[1])
        await self.writer.close()
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        before = await self.snapshot()
        self.assertEqual(await self.expand(expected=999), results[0])
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.scalar('SELECT storage_limit FROM profiles'), 300)
        self.assertEqual(await self.scalar('SELECT stardust FROM profiles'), 15000)
        self.assertEqual(await self.scalar('SELECT count(*) FROM action_receipts'), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM resource_ledger'), 2)

    async def test_expand_with_changed_limit_since_preview_stale(self):
        await self.conn.execute('UPDATE profiles SET storage_limit=300')
        before = await self.rows('SELECT * FROM profiles')
        self.assertEqual(await self.expand(), {'status': 'stale'})
        self.assertEqual(await self.rows('SELECT * FROM profiles'), before)
        self.assertEqual(await self.scalar('SELECT count(*) FROM resource_ledger'), 0)
        await self.conn.execute('UPDATE profiles SET storage_limit=250')
        self.assertEqual(await self.expand(), {'status': 'stale'})

    async def test_quote_reports_next_and_at_cap(self):
        capacity = self.capacity()
        for kind, price in (('storage', 5000), ('bag', 2500)):
            with self.subTest(kind=kind):
                await self.conn.execute(f'UPDATE profiles SET {kind}_limit=250,stardust=?', (price,))
                self.assertEqual(await capacity.quote(self.conn, 'p', kind),
                                 {'current': 250, 'next': 300, 'price': price, 'max': 1000,
                                  'at_cap': False, 'affordable': True})
                await self.conn.execute('UPDATE profiles SET stardust=?', (price - 1,))
                self.assertFalse((await capacity.quote(self.conn, 'p', kind))['affordable'])
                await self.conn.execute(f'UPDATE profiles SET {kind}_limit=1000,stardust=20000')
                self.assertEqual(await capacity.quote(self.conn, 'p', kind),
                                 {'current': 1000, 'next': 1000, 'price': price, 'max': 1000,
                                  'at_cap': True, 'affordable': False})

    async def test_check_constraint_rejects_out_of_range(self):
        columns = {r['name'] for r in await self.rows('PRAGMA table_info(profiles)')}
        self.assertTrue({'storage_limit', 'bag_limit'} <= columns, 'Capacity columns are absent')
        for column in ('storage_limit', 'bag_limit'):
            for value in (249, 1001, 250.5, 'bad', None):
                with self.subTest(column=column, value=value), self.assertRaises(sqlite3.IntegrityError):
                    await self.conn.execute(f'UPDATE profiles SET {column}=?', (value,))
            for value in (250, 1000):
                await self.conn.execute(f'UPDATE profiles SET {column}=?', (value,))

    async def test_other_user_cannot_expand(self):
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('other','123','789',0)")
        for replay in (False, True):
            if replay:
                await self.expand()
            before = await self.snapshot()
            for session in ({**self.session, 'user_id': '789'},
                            {**self.session, 'user_id': '789', 'profile_id': 'other'},
                            {**self.session, 'session_id': 'missing'},
                            {**self.session, 'guild_id': 'different'}):
                self.assertEqual(await self.expand(session=session), {'status': 'stale'})
                self.assertEqual(await self.snapshot(), before)

    async def test_excluded_refused_inside_transaction(self):
        capacity = self.capacity()
        for replay in (False, True):
            if replay:
                await self.conn.execute('DELETE FROM restrictions')
                await self.expand()
            async def action(conn):
                await conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
                return await capacity.expand(conn, self.session, 'storage', 250, 1000)
            before = await self.snapshot()
            self.assertEqual(await self.writer.run(action), {'status': 'excluded'})
            self.assertEqual(await self.snapshot(), before)
            await self.conn.execute('DELETE FROM restrictions')

    async def test_limits_for_one_guild_not_another(self):
        capacity = self.capacity()
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('999')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('other','999','456',0)")
        await self.expand()
        self.assertEqual((await capacity.limits_for(self.conn, 'p'))['storage'], 300)
        self.assertEqual(await capacity.limits_for(self.conn, 'other'),
                         {'storage': 250, 'bag_units': 250, 'rare_pockets': limits()['rare_pockets']})
        self.assertEqual(await self.scalar("SELECT stardust FROM profiles WHERE profile_id='other'"), 0)

    async def test_failure_rolls_back_debit_capacity_receipt_and_ledger(self):
        capacity = self.capacity()
        before = await self.snapshot()
        await self.conn.execute("CREATE TRIGGER fail_capacity BEFORE INSERT ON resource_ledger "
                                "WHEN NEW.resource='capacity' BEGIN SELECT RAISE(ABORT,'ledger failed'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'ledger failed'):
            await self.expand()
        self.assertEqual(await self.snapshot(), before)
        with self.assertRaisesRegex(RuntimeError, 'transaction'):
            await capacity.expand(self.conn, self.session, 'storage', 250, 1000)

    async def test_invalid_kind_refused_and_missing_profile_explicit(self):
        capacity = self.capacity()
        before = await self.snapshot()
        self.assertEqual(await self.expand('storage_limit'), {'status': 'refused'})
        self.assertEqual(await self.snapshot(), before)
        with self.assertRaises(ValueError):
            await capacity.quote(self.conn, 'p', 'storage_limit')
        with self.assertRaises(ValueError):
            await capacity.limits_for(self.conn, 'missing')

    async def test_catch_storage_full_uses_profile_limit(self):
        content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        await self.expand()
        await self.conn.executemany(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,content_version,caught_at) "
            "VALUES (?,'p',1,2,0,0,0,'male',0,'starter','test',0)",
            [(f'owned-{i}',) for i in range(250)])
        await self.conn.executemany('INSERT INTO inventory VALUES (?,?,?)',
                                    [('p', 'poke_ball', 3), ('p', 'razz_berry', 3)])
        for count in (250, 299, 300):
            with self.subTest(owned=count):
                if count > 250:
                    await self.conn.executemany(
                        "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                        "iv_stamina,gender,shiny,origin,source_encounter_id,favorite,state,content_version,revision,caught_at) "
                        "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                        "iv_stamina,gender,shiny,origin,NULL,0,'owned',content_version,0,0 "
                        "FROM pokemon WHERE pokemon_uid='owned-0'",
                        [(f'fill-{i}',) for i in range(250 if count == 299 else 299, count)])
                eid = f'catch-{count}'
                await self.conn.execute(
                    "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,"
                    "iv_defense,iv_stamina,gender,shiny,tier,route_id,state,content_version,created_at) "
                    "VALUES (?,'p',1,2,0,0,0,'male',0,'Common','refreshing_field','revealed','test',0)",
                    (eid,))
                session = {**self.session, 'selection': json.dumps({'ball': 'poke_ball', 'berry': 'razz_berry'})}
                before = {table: await self.rows(f'SELECT * FROM {table}') for table in
                          ('profiles', 'pokemon', 'encounters', 'inventory', 'catch_attempts',
                           'action_receipts', 'resource_ledger', 'pokedex', 'candy')}
                rng = Mock()
                rng.random.return_value = 0
                result = await self.writer.run(lambda conn: catching.throw(
                    conn, eid, session, 0, rng, 1000, content=content))
                self.assertEqual(result.status, 'caught' if count < 300 else 'storage_full')
                self.assertEqual(await self.scalar("SELECT count(*) FROM pokemon WHERE state='owned'"),
                                 count)
                if count == 300:
                    self.assertEqual({table: await self.rows(f'SELECT * FROM {table}') for table in before},
                                     before)
                    rng.random.assert_not_called()
                else:
                    self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='poke_ball'"),
                                     2 if count == 250 else 1)
                    self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='razz_berry'"),
                                     2 if count == 250 else 1)

    async def test_find_overflow_uses_profile_bag_limit(self):
        await self.expand('bag')
        for limit, quantity, expected, dust in ((300, 251, 'granted', 0), (250, 251, 'overflow', 10)):
            with self.subTest(limit=limit):
                await self.conn.execute('UPDATE profiles SET bag_limit=?,find_meter_c=9900', (limit,))
                await self.conn.execute("INSERT OR REPLACE INTO inventory VALUES ('p','poke_ball',?)", (quantity,))
                before_dust = await self.scalar('SELECT stardust FROM profiles')
                profile = (await self.rows('SELECT * FROM profiles'))[0]
                with patch.object(items, 'roll_find', return_value={'item': 'poke_ball', 'quantity': 5}):
                    await self.writer.run(lambda conn: items.apply_finds(
                        conn, profile, 100, 1000, f'find-{limit}', random.Random(1), {}))
                self.assertEqual((await self.rows('SELECT outcome FROM finds ORDER BY find_id DESC'))[0],
                                 {'outcome': expected})
                self.assertEqual(await items.bag_units(self.conn, 'p'), quantity + (5 if not dust else 0))
                self.assertEqual(await self.scalar('SELECT stardust FROM profiles'), before_dust + dust)

    async def test_checkin_uses_profile_bag_limit(self):
        await self.expand('bag')
        for now, limit, units, outcomes, dust in (
                (1000, 300, 249, ['granted', 'granted'], 0),
                (5000, 250, 249, ['granted', 'overflow'], 10),
                (9000, 300, 299, ['granted', 'overflow'], 10)):
            with self.subTest(limit=limit, units=units):
                await self.conn.execute('UPDATE profiles SET bag_limit=?', (limit,))
                await self.conn.execute("INSERT OR REPLACE INTO inventory VALUES ('p','poke_ball',?)", (units,))
                before_dust = await self.scalar('SELECT stardust FROM profiles')
                with patch.object(items, 'roll_checkin', return_value={'item': 'poke_ball', 'quantity': 2}):
                    result = await self.writer.run(lambda conn: items.checkin(conn, 123, 456, now, random.Random(1)))
                self.assertEqual([entry['outcome'] for entry in result['outcomes']], outcomes)
                self.assertEqual(await items.bag_units(self.conn, 'p'), units + (3 if not dust else 1))
                self.assertEqual(await self.scalar('SELECT stardust FROM profiles'), before_dust + dust)
                self.assertEqual(await self.scalar('SELECT last_checkin_at FROM profiles'), now)

    async def test_buy_evolution_item_uses_profile_bag_limit(self):
        await self.expand('bag')
        content = {'evolution_items': [{'id': 'fire-stone'}]}
        await self.conn.execute("INSERT INTO inventory VALUES ('p','poke_ball',299)")
        before_dust = await self.scalar('SELECT stardust FROM profiles')
        result = await self.writer.run(lambda conn: items.buy_evolution_item(
            conn, self.session, 'fire-stone', 1000, content))
        self.assertEqual(result, {'item': 'fire-stone', 'quantity': 1, 'stardust': 500})
        self.assertEqual(await items.bag_units(self.conn, 'p'), 300)
        self.assertEqual(await self.scalar('SELECT stardust FROM profiles'), before_dust - 500)
        for limit, units in ((300, 299), (250, 249)):
            with self.subTest(limit=limit):
                await self.conn.execute('UPDATE profiles SET bag_limit=?', (limit,))
                await self.conn.execute("UPDATE inventory SET quantity=? WHERE item_id='poke_ball'", (units,))
                before = {table: await self.rows(f'SELECT * FROM {table}') for table in
                          ('profiles', 'inventory', 'action_receipts', 'resource_ledger')}
                refused = await self.writer.run(lambda conn: items.buy_evolution_item(
                    conn, {**self.session, 'revision': limit}, 'fire-stone', 1000, content))
                self.assertEqual(refused, {'status': 'bag_full'})
                self.assertEqual({table: await self.rows(f'SELECT * FROM {table}') for table in before}, before)

    async def test_grant_in_other_guild_profile_unaffected(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('999')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('other','999','456',0)")
        await self.expand('bag')
        await self.conn.executemany("INSERT INTO inventory VALUES (?,'poke_ball',251)", [('p',), ('other',)])
        self.assertEqual(await self.writer.run(lambda conn: items.grant(conn, 'p', 'poke_ball', 5)), ('granted', 0))
        other_before = (await self.rows("SELECT * FROM profiles WHERE profile_id='other'"))[0]
        self.assertEqual(await self.writer.run(lambda conn: items.grant(conn, 'other', 'poke_ball', 5)),
                         ('overflow', 10))
        self.assertEqual(await items.bag_units(self.conn, 'p'), 256)
        self.assertEqual(await items.bag_units(self.conn, 'other'), 251)
        self.assertEqual((await self.rows("SELECT * FROM profiles WHERE profile_id='other'"))[0],
                         {**other_before, 'stardust': 10})

    async def seed_claim(self, rewards, profile_id='p'):
        await self.conn.executemany(
            "INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) "
            "VALUES (?,'capacity','item',?,?,0)",
            [(profile_id, item, quantity) for item, quantity in rewards.items()])

    async def claim(self, session=None):
        return await self.writer.run(lambda conn: milestones.claim(conn, session or self.session, 1000))

    async def test_claim_ordinary_items_cap_uses_profile_bag_limit(self):
        await self.conn.execute('UPDATE profiles SET bag_limit=300')
        await self.conn.execute("INSERT INTO inventory VALUES ('p','poke_ball',290)")
        await self.seed_claim({'great_ball': 20})
        result = await self.claim()
        self.assertEqual(result['moved'], {'item': 10, 'stardust': 0, 'candy': 0})
        self.assertEqual(await items.bag_units(self.conn, 'p'), 300)
        self.assertEqual(await self.rows('SELECT resource_id,remaining FROM inbox_items'),
                         [{'resource_id': 'great_ball', 'remaining': 10}])
        self.assertEqual(await self.rows("SELECT resource_id,delta FROM resource_ledger"),
                         [{'resource_id': 'great_ball', 'delta': 10}])

    async def test_claim_ordinary_units_equal_bag_units(self):
        await self.conn.executemany('INSERT INTO inventory VALUES (?,?,?)',
                                    [('p', 'poke_ball', 249), ('p', 'world_legendary_ticket', 999)])
        await self.seed_claim({'great_ball': 2})
        # Simulate a later rare-kind exclusion in the shared bag counter.
        with patch.object(items, 'bag_units', return_value=249) as units:
            result = await self.claim()
        units.assert_awaited_once_with(self.conn, 'p')
        self.assertEqual(result['moved']['item'], 1)
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='great_ball'"), 1)
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='world_legendary_ticket'"), 999)
        self.assertEqual(await self.scalar('SELECT remaining FROM inbox_items'), 1)

    async def test_claim_rare_pockets_unchanged(self):
        for occupied in (False, True):
            with self.subTest(occupied=occupied):
                await self.conn.execute('DELETE FROM inventory')
                await self.conn.execute('DELETE FROM inbox_items')
                await self.conn.execute('UPDATE profiles SET bag_limit=300')
                await self.conn.execute("INSERT INTO inventory VALUES ('p','poke_ball',300)")
                if occupied:
                    await self.conn.executemany('INSERT INTO inventory VALUES (?,?,1)',
                                                [('p', 'master_ball'), ('p', 'shiny_lure')])
                await self.seed_claim({'master_ball': 2, 'shiny_lure': 2})
                result = await self.claim({**self.session, 'revision': int(occupied)})
                self.assertEqual(result['moved']['item'], 0 if occupied else 2)
                for item in ('master_ball', 'shiny_lure'):
                    self.assertEqual(await self.scalar('SELECT quantity FROM inventory WHERE item_id=?', (item,)), 1)
                    self.assertEqual(await self.scalar('SELECT remaining FROM inbox_items WHERE resource_id=?', (item,)),
                                     2 if occupied else 1)
                self.assertEqual(await items.bag_units(self.conn, 'p'), 300)

    async def test_claim_never_converts(self):
        await self.conn.executemany('INSERT INTO inventory VALUES (?,?,?)',
                                    [('p', 'poke_ball', 250), ('p', 'master_ball', 1), ('p', 'shiny_lure', 1)])
        await self.seed_claim({'great_ball': 20, 'master_ball': 1, 'shiny_lure': 1})
        before = {table: await self.rows(f'SELECT * FROM {table}') for table in
                  ('profiles', 'inventory', 'inbox_items', 'resource_ledger')}
        with patch.object(items, 'grant', side_effect=AssertionError('Claim must not convert')):
            result = await self.claim()
        self.assertEqual(result['moved'], {'item': 0, 'stardust': 0, 'candy': 0})
        self.assertEqual({table: await self.rows(f'SELECT * FROM {table}') for table in before}, before)

    async def test_claim_other_guild_profile_unaffected(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('999')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('other','999','456',0)")
        await self.conn.execute("UPDATE profiles SET bag_limit=300 WHERE profile_id='p'")
        await self.conn.executemany("INSERT INTO inventory VALUES (?,'poke_ball',290)", [('p',), ('other',)])
        await self.seed_claim({'great_ball': 20})
        await self.seed_claim({'great_ball': 20}, 'other')
        before = {table: await self.rows(f"SELECT * FROM {table} WHERE profile_id='other'") for table in
                  ('profiles', 'inventory', 'inbox_items', 'action_receipts', 'resource_ledger')}
        self.assertEqual((await self.claim())['moved']['item'], 10)
        self.assertEqual({table: await self.rows(f"SELECT * FROM {table} WHERE profile_id='other'")
                          for table in before}, before)


class StorageCapacityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = storage_tests.StorageTests.asyncSetUp
    interaction = storage_tests.StorageTests.interaction
    rows = storage_tests.StorageTests.rows
    open = storage_tests.StorageTests.open
    click = storage_tests.StorageTests.click
    enroll = storage_tests.StorageTests.enroll
    ready = storage_tests.StorageTests.ready
    current = storage_tests.StorageTests.current
    reveal = storage_tests.StorageTests.reveal
    prepared = storage_tests.StorageTests.prepared
    storage = storage_tests.StorageTests.storage
    buttons = storage_tests.StorageTests.buttons

    async def start(self):
        session = await self.prepared()
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET stardust=15000'))
        return session

    async def screen(self, session, action):
        interaction = await self.click(session, action)
        interaction.edit_original_response.assert_awaited_once()
        rendered = interaction.edit_original_response.await_args.kwargs
        self.assertLessEqual(len(rendered['view'].children), 25)
        self.assertTrue(all(i.row is None or i.row < 5 for i in rendered['view'].children))
        return rendered, await self.current(session)

    async def purchase_state(self):
        return {t: await self.rows(f'SELECT * FROM {t}') for t in
                ('profiles', 'action_receipts', 'resource_ledger')}

    async def assert_saved_refusal(self, before, status):
        after = await self.purchase_state()
        self.assertEqual(after['profiles'], before['profiles'])
        self.assertEqual(after['resource_ledger'], before['resource_ledger'])
        self.assertEqual(after['action_receipts'][:-1], before['action_receipts'])
        receipt = after['action_receipts'][-1]
        self.assertEqual(receipt['action'], 'expand')
        self.assertEqual(receipt['profile_id'], self.profile['profile_id'])
        self.assertEqual(json.loads(receipt['result']), {'status': status})

    async def test_storage_page_header_shows_profile_limit(self):
        session = await self.start()
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET storage_limit=350'))
        rendered, _ = await self.storage(session)
        self.assertIn('1/350', rendered['embed'].description)
        self.assertEqual(self.buttons(rendered)['Expand storage'].row, 2)
        self.assertIsNone(rendered['embed'].image.url)

    async def test_expand_storage_preview_then_confirm_updates_header(self):
        session = await self.start()
        rendered, session = await self.storage(session)
        self.assertTrue(self.buttons(rendered)['Expand storage'].custom_id.endswith(':expand_storage_preview'))
        before = await self.purchase_state()
        rendered, session = await self.screen(session, 'expand_storage_preview')
        self.assertIn('5,000 Stardust → 300 slots · have 15,000', rendered['embed'].description)
        self.assertFalse(self.buttons(rendered)['Confirm'].disabled)
        self.assertTrue(self.buttons(rendered)['Confirm'].custom_id.endswith(':expand_storage_confirm'))
        self.assertEqual(json.loads(session['selection'])['storage_limit'], 250)
        self.assertEqual(await self.purchase_state(), before)
        with patch.object(capacity, 'expand', wraps=capacity.expand) as expand:
            rendered, _ = await self.screen(session, 'expand_storage_confirm')
        self.assertEqual(expand.call_args.args[2:], ('storage', 250, 1000))
        self.assertIn('1/300', rendered['embed'].description)
        self.assertIn('expanded', rendered['embed'].description.lower())
        profile = (await self.rows('SELECT * FROM profiles'))[0]
        self.assertEqual((profile['storage_limit'], profile['stardust']), (300, 10000))
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='expand'")), 1)
        self.assertEqual(len(await self.rows("SELECT * FROM resource_ledger WHERE reason='expand_storage'")), 2)

    async def test_expand_confirm_disabled_at_cap_and_when_unaffordable(self):
        session = await self.start()
        for limit, dust in ((1000, 15000), (250, 4999)):
            with self.subTest(limit=limit, dust=dust):
                await self.writer.run(lambda c: c.execute(
                    'UPDATE profiles SET storage_limit=?,stardust=?', (limit, dust)))
                rendered, session = await self.screen(session, 'expand_storage_preview')
                self.assertTrue(self.buttons(rendered)['Confirm'].disabled)
                before = await self.purchase_state()
                rendered, session = await self.screen(session, 'expand_storage_confirm')
                self.assertTrue(self.buttons(rendered)['Confirm'].disabled)
                self.assertIn('nothing', rendered['embed'].description.lower())
                await self.assert_saved_refusal(before, 'at_cap' if limit == 1000 else 'insufficient')

    async def test_storage_full_warning_shows_profile_limit(self):
        session = await self.prepared(300)
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET storage_limit=300'))
        _, session = await self.reveal(session)
        before = {t: await self.rows(f'SELECT * FROM {t}') for t in
                  ('pokemon', 'inventory', 'encounters', 'catch_attempts')}
        rendered, session = await self.screen(session, 'throw')
        self.assertIn('Storage is full (300/300).', rendered['embed'].description)
        self.assertIn('A catch will wait for Send for research or Upgrade storage.', rendered['embed'].description)
        self.assertEqual(list(self.buttons(rendered)), ['Confirm throw', 'Back'])
        self.assertEqual({t: await self.rows(f'SELECT * FROM {t}') for t in before}, before)
        rendered, _ = await self.storage(session)
        self.assertIn('300/300', rendered['embed'].description)
        self.assertIn('Expand storage', self.buttons(rendered))

    async def pending_result(self):
        _, session = await self.caught_result()
        await self.writer.run(lambda c: c.execute("DELETE FROM pokemon WHERE source_encounter_id='A'"))
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET stardust=15000'))
        return await self.screen(session, 'home')

    async def fill_storage(self, total=250):
        count = len(await self.rows("SELECT * FROM pokemon WHERE state='owned'"))
        await self.writer.run(lambda c: c.executemany(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,content_version,caught_at) "
            "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,"
            "origin,content_version,caught_at FROM pokemon WHERE pokemon_uid=?",
            [(f'fill-{i}', self.uid) for i in range(count, total)]))

    async def test_pending_recovered_before_older_unacknowledged_results(self):
        _, session = await self.pending_result()
        from test_walker_ack import AcknowledgementTests
        await AcknowledgementTests.terminal_copy(self, 'older-ran', 'ran', 800)
        await AcknowledgementTests.terminal_copy(self, 'older-fled', 'fled', 900)
        interaction, fresh = await self.open()
        self.assertEqual(list(self.buttons(interaction.edit_original_response.await_args.kwargs)),
                         ['Done', 'Send for research'])
        self.assertEqual(json.loads(fresh['selection'])['encounter_id'], 'A')
        rendered, session = await self.screen(session, 'home')
        self.assertEqual(list(self.buttons(rendered)), ['Done', 'Send for research'])
        self.assertEqual(json.loads(session['selection'])['encounter_id'], 'A')
        for expected in ('older-ran', 'older-fled'):
            rendered, session = await self.screen(session, 'ack')
            self.assertEqual(json.loads(session['selection'])['encounter_id'], expected)
            self.assertEqual(list(self.buttons(rendered)), ['Done'])
        rendered, _ = await self.screen(session, 'ack')
        self.assertEqual(rendered['embed'].title, 'Walker')

    async def test_open_encounter_from_older_home_lands_on_pending_menu(self):
        _, session = await self.pending_result()
        async def older_screens(conn):
            await conn.execute("UPDATE sessions SET selection='{}' WHERE session_id=?",
                               (session['session_id'],))
            await conn.execute("UPDATE encounters SET state='revealed' WHERE encounter_id='B'")
        await self.writer.run(older_screens)
        for action in ('open_encounter', 'select_ball', 'select_berry', 'pick_ball',
                       'pick_berry', 'throw', 'master_confirm', 'run', 'run_confirm'):
            with self.subTest(action=action):
                selection = {} if action == 'open_encounter' else {
                    'encounter_id': 'B', 'encounter_revision': 0, 'ball': 'poke_ball', 'berry': 'razz_berry'}
                await self.writer.run(lambda conn: conn.execute(
                    'UPDATE sessions SET selection=? WHERE session_id=?',
                    (json.dumps(selection), session['session_id'])))
                session = await self.current(session)
                before = await self.research_state()
                rendered, session = await self.screen(session, action)
                self.assertEqual(list(self.buttons(rendered)), ['Done', 'Send for research'])
                self.assertEqual(json.loads(session['selection'])['encounter_id'], 'A')
                after = await self.research_state()
                self.assertEqual(after, before)
        rendered, _ = await self.screen(session, 'storage')
        self.assertIn('Storage', rendered['embed'].title)
        options = [option.value for item in rendered['view'].children
                   for option in getattr(item, 'options', [])]
        owned = {row['pokemon_uid'] for row in await self.rows("SELECT * FROM pokemon WHERE state='owned'")}
        self.assertEqual(set(options), owned)
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE source_encounter_id='A'"), [])

    async def test_pending_intercept_on_selected_catch_is_read_only(self):
        _, session = await self.pending_result()
        before = await self.research_state()
        for action in ('open_encounter', 'select_ball', 'select_berry', 'pick_ball',
                       'pick_berry', 'throw', 'master_confirm', 'run', 'run_confirm'):
            with self.subTest(action=action):
                session = await self.current(session)
                statements = []
                await self.conn.set_trace_callback(statements.append)
                try:
                    rendered, current = await self.screen(session, action)
                finally:
                    await self.conn.set_trace_callback(None)
                self.assertEqual(current, session)
                self.assertEqual(list(self.buttons(rendered)), ['Done', 'Send for research'])
                self.assertFalse(any(sql.upper().startswith('UPDATE SESSIONS') for sql in statements))
                self.assertEqual(await self.research_state(), before)

    async def test_older_home_pending_menu_buttons_resolve_selected_catch(self):
        _, session = await self.pending_result()
        for full, action in ((False, 'catch_send'), (False, 'ack'), (True, 'catch_send'), (True, 'catch_upgrade')):
            with self.subTest(full=full, action=action):
                async def reset(conn):
                    await conn.execute("DELETE FROM pokemon WHERE source_encounter_id='A'")
                    await conn.execute("UPDATE encounters SET acknowledged_at=NULL WHERE encounter_id='A'")
                    await conn.execute('UPDATE profiles SET storage_limit=250,stardust=15000')
                    await conn.execute("UPDATE sessions SET selection='{}' WHERE session_id=?",
                                       (session['session_id'],))
                await self.writer.run(reset)
                if full:
                    await self.fill_storage()
                session = await self.current(session)
                previous_revision = session['revision']
                rendered, session = await self.screen(session, 'open_encounter')
                self.assertEqual(session['revision'], previous_revision + 1)
                self.assertEqual(json.loads(session['selection'])['encounter_id'], 'A')
                button = next(b for b in rendered['view'].children if b.custom_id.endswith(':' + action))
                interaction = self.interaction()
                await self.walker.route(interaction, button.custom_id)
                interaction.edit_original_response.assert_awaited_once()
                rendered = interaction.edit_original_response.await_args.kwargs
                session = await self.current(session)
                if action == 'catch_send':
                    _, session = await self.screen(session, 'storage_send_confirm')
                    rendered, session = await self.screen(session, 'ack')
                self.assertEqual(rendered['embed'].title, 'Walker')
                self.assertEqual(await self.rows("SELECT state FROM pokemon WHERE source_encounter_id='A'"),
                                 [{'state': 'sent' if action == 'catch_send' else 'owned'}])
                self.assertIsNone(await self.walker.pending_catch(self.conn, session['profile_id']))
                self.assertEqual((await self.rows("SELECT acknowledged_at FROM encounters WHERE encounter_id='A'"))[0],
                                 {'acknowledged_at': self.now})

    async def test_pending_menu_with_room_shows_done_and_send_only(self):
        rendered, session = await self.pending_result()
        self.assertEqual(list(self.buttons(rendered)), ['Done', 'Send for research'])
        self.assertTrue(all(not b.disabled for b in rendered['view'].children))
        self.assertEqual(json.loads(session['selection']), {'encounter_id': 'A', 'storage_limit': 250})
        self.assertIn('Pikachu', rendered['embed'].description)
        self.assertIn('Result: caught', rendered['embed'].description)
        self.assertTrue(rendered['embed'].image.url)
        self.assertEqual(await self.walker.pending_catch(self.conn, session['profile_id']), 'A')
        self.walker = self.module.Walker(self.bot, clock=lambda: self.now)
        interaction, recovered = await self.open()
        self.assertEqual(list(self.buttons(interaction.edit_original_response.await_args.kwargs)),
                         ['Done', 'Send for research'])
        self.assertEqual(json.loads(recovered['selection']), json.loads(session['selection']))

    async def test_pending_done_stores_once_and_goes_home(self):
        _, session = await self.pending_result()
        _, competing = await self.open()
        self.now += 20
        before = await self.research_state()
        rendered, _ = await self.screen(session, 'ack')
        self.assertEqual(rendered['embed'].title, 'Walker')
        caught = await self.rows("SELECT * FROM pokemon WHERE source_encounter_id='A'")
        self.assertEqual(len(caught), 1)
        self.assertEqual(caught[0], {**self.caught, 'pokemon_uid': caught[0]['pokemon_uid']})
        encounter = (await self.rows("SELECT * FROM encounters WHERE encounter_id='A'"))[0]
        self.assertEqual(caught[0]['caught_at'], encounter['resolved_at'])
        self.assertEqual(encounter['acknowledged_at'], self.now)
        self.assertIsNone(await self.walker.pending_catch(self.conn, session['profile_id']))
        rendered, _ = await self.screen(competing, 'ack')
        self.assertEqual(rendered['embed'].title, 'Walker')
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE source_encounter_id='A'"), caught)
        after = await self.research_state()
        for table in ('profiles', 'action_receipts', 'resource_ledger', 'inventory', 'candy', 'pokedex', 'catch_attempts'):
            self.assertEqual(after[table], before[table], table)

    async def test_pending_done_at_full_storage_refused_shows_send_or_upgrade(self):
        _, session = await self.pending_result()
        await self.fill_storage()
        before = await self.research_state()
        rendered, _ = await self.screen(session, 'ack')
        self.assertIn('Nothing was stored.', rendered['embed'].description)
        self.assertEqual([b.custom_id.rsplit(':', 1)[1] for b in rendered['view'].children],
                         ['catch_send', 'catch_upgrade'])
        self.assertEqual(await self.research_state(), before)

    async def test_pending_full_menu_shows_exactly_send_and_upgrade(self):
        _, session = await self.pending_result()
        rules = load_table('capacities')['expansion']['storage']
        for total, dust, reason in ((250, 15000, None), (250, 4999, 'Not enough Stardust.'),
                                    (1000, 15000, 'Storage is at the maximum capacity.')):
            with self.subTest(total=total, dust=dust):
                await self.fill_storage(total)
                await self.writer.run(lambda c: c.execute(
                    'UPDATE profiles SET storage_limit=?,stardust=?', (total, dust)))
                rendered, session = await self.screen(session, 'home')
                self.assertEqual(list(self.buttons(rendered)), ['Send for research',
                    f"Upgrade storage space (+{rules['step']}, {rules['stardust']:,} Stardust)"])
                self.assertEqual([b.custom_id.rsplit(':', 1)[1] for b in rendered['view'].children],
                                 ['catch_send', 'catch_upgrade'])
                self.assertFalse(rendered['view'].children[0].disabled)
                self.assertEqual(rendered['view'].children[1].disabled, reason is not None)
                self.assertIn(f'Storage is full ({total}/{total}). Choose one:', rendered['embed'].description)
                self.assertEqual(json.loads(session['selection']), {'encounter_id': 'A', 'storage_limit': total})
                if reason:
                    self.assertIn(reason, rendered['embed'].description)
                    before = await self.purchase_state()
                    rendered, session = await self.screen(session, 'catch_upgrade')
                    self.assertIn(reason, rendered['embed'].description)
                    self.assertIn('Nothing was spent.', rendered['embed'].description)
                    after = await self.purchase_state()
                    self.assertEqual(after['profiles'], before['profiles'])
                    self.assertEqual(after['resource_ledger'], before['resource_ledger'])

    async def test_pending_upgrade_expands_stores_acknowledges_once(self):
        _, session = await self.pending_result()
        await self.fill_storage()
        _, session = await self.screen(session, 'home')
        _, other = await self.open()
        stale = dict(session)
        with patch.object(capacity, 'expand', wraps=capacity.expand) as expand:
            rendered, session = await self.screen(session, 'catch_upgrade')
        self.assertEqual(expand.call_args.args[2:], ('storage', 250, self.now))
        self.assertEqual(rendered['embed'].title, 'Walker')
        profile = (await self.rows('SELECT * FROM profiles'))[0]
        self.assertEqual((profile['storage_limit'], profile['stardust']), (300, 10000))
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE source_encounter_id='A'")), 1)
        self.assertEqual((await self.rows("SELECT acknowledged_at FROM encounters WHERE encounter_id='A'"))[0],
                         {'acknowledged_at': self.now})
        after = await self.research_state()
        self.assertEqual(len([r for r in after['action_receipts'] if r['action'] == 'expand']), 1)
        self.assertEqual([(r['resource'], r['delta']) for r in after['resource_ledger']
                          if r['reason'] == 'expand_storage'], [('stardust', -5000), ('capacity', 50)])
        for previous in (stale, other):
            refused = await self.click(previous, 'catch_upgrade')
            if previous is stale:
                refused.followup.send.assert_not_awaited()
            else:
                self.assertIn('reopen /walker', refused.followup.send.await_args.args[0])
            self.assertEqual(await self.research_state(), after)

    async def test_pending_upgrade_store_failure_rolls_back_then_retries_once(self):
        _, session = await self.pending_result()
        await self.fill_storage()
        _, session = await self.screen(session, 'home')
        await self.writer.run(lambda c: c.execute("CREATE TRIGGER fail_store BEFORE INSERT ON pokemon "
                                                "BEGIN SELECT RAISE(ABORT,'store failed'); END"))
        before, saved = await self.research_state(), await self.current(session)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'store failed'):
            await self.click(session, 'catch_upgrade')
        self.assertEqual(await self.research_state(), before)
        self.assertEqual(await self.current(session), saved)
        await self.writer.run(lambda c: c.execute('DROP TRIGGER fail_store'))
        rendered, _ = await self.screen(session, 'catch_upgrade')
        self.assertEqual(rendered['embed'].title, 'Walker')
        profile = (await self.rows('SELECT * FROM profiles'))[0]
        self.assertEqual((profile['storage_limit'], profile['stardust']), (300, 10000))
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='expand'")), 1)
        self.assertEqual(len(await self.rows("SELECT * FROM resource_ledger WHERE reason='expand_storage'")), 2)
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE source_encounter_id='A'")), 1)
        self.assertEqual((await self.rows("SELECT acknowledged_at FROM encounters WHERE encounter_id='A'"))[0],
                         {'acknowledged_at': self.now})

    async def test_second_screen_throw_saves_pending_menu_so_upgrade_succeeds(self):
        session = await self.prepared(250)
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET stardust=15000'))
        _, first = await self.reveal(session)
        _, second = await self.open()
        _, second = await self.reveal(second)
        encounter_id = self.encounter['encounter_id']
        _, first = await self.screen(first, 'throw')
        with patch.object(self.walker.rng, 'random', return_value=0):
            rendered, first = await self.screen(first, 'throw')
        self.assertEqual([b.custom_id.rsplit(':', 1)[1] for b in rendered['view'].children],
                         ['catch_send', 'catch_upgrade'])
        rendered, second = await self.screen(second, 'throw')
        self.assertEqual([b.custom_id.rsplit(':', 1)[1] for b in rendered['view'].children],
                         ['catch_send', 'catch_upgrade'])
        self.assertEqual(json.loads(second['selection']), {'encounter_id': encounter_id, 'storage_limit': 250})
        dust = (await self.rows('SELECT stardust FROM profiles'))[0]['stardust']
        rendered, second = await self.screen(second, 'catch_upgrade')
        self.assertEqual(rendered['embed'].title, 'Walker')
        profile = (await self.rows('SELECT * FROM profiles'))[0]
        self.assertEqual((profile['storage_limit'], profile['stardust']), (300, dust - 5000))
        self.assertEqual(len(await self.rows('SELECT * FROM pokemon WHERE source_encounter_id=?',
                                             (encounter_id,))), 1)
        self.assertIsNotNone((await self.rows('SELECT acknowledged_at FROM encounters WHERE encounter_id=?',
                                              (encounter_id,)))[0]['acknowledged_at'])
        after = await self.research_state()
        self.assertEqual(len([r for r in after['action_receipts'] if r['action'] == 'expand']), 1)
        self.assertEqual([(r['resource'], r['delta']) for r in after['resource_ledger']
                          if r['reason'] == 'expand_storage'], [('stardust', -5000), ('capacity', 50)])

    async def test_throw_response_on_pending_catch_is_the_menu(self):
        session = await self.prepared(250)
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET storage_limit=300'))
        _, session = await self.reveal(session)
        real_throw = catching.throw
        async def pending_throw(conn, *args, **kwargs):
            result = await real_throw(conn, *args, **kwargs)
            self.assertEqual(result.status, 'caught')
            await conn.execute('DELETE FROM pokemon WHERE source_encounter_id=?', (args[0],))
            if full:
                await conn.execute('UPDATE profiles SET storage_limit=250')
            return result
        for full in (False, True):
            for replay in (False, True):
                before, saved = await self.research_state(), dict(session)
                with self.subTest(full=full, replay=replay), \
                        patch.object(catching, 'throw', side_effect=pending_throw), \
                        patch.object(self.walker.rng, 'random', return_value=0):
                    rendered, session = await self.screen(session, 'throw')
                expected = ['catch_send', 'catch_upgrade'] if full else ['ack', 'catch_send']
                self.assertEqual([b.custom_id.rsplit(':', 1)[1] for b in rendered['view'].children], expected)
                if replay:
                    self.assertEqual(await self.current(session), saved)
                    self.assertEqual(await self.research_state(), before)
            if not full:
                _, session = await self.screen(session, 'ack')
                async def next_encounter(conn):
                    await conn.execute('DELETE FROM pokemon WHERE source_encounter_id=?',
                                       (self.encounter['encounter_id'],))
                    await conn.execute(
                        "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                        "iv_stamina,gender,shiny,tier,route_id,content_version,created_at) "
                        "SELECT 'full',profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,"
                        "tier,route_id,content_version,created_at FROM encounters WHERE encounter_id=?",
                        (self.encounter['encounter_id'],))
                await self.writer.run(next_encounter)
                _, session = await self.reveal(session)

    async def test_pending_send_review_confirm_inserts_sent_row_then_done(self):
        _, session = await self.pending_result()
        before = await self.research_state()
        rendered, session = await self.screen(session, 'catch_send')
        for text in ('Pikachu', 'pending:A', '+1 Pikachu Candy'):
            self.assertIn(text, rendered['embed'].description)
        selection = json.loads(session['selection'])
        encounter = before['encounters'][0]
        self.assertEqual(selection['picks'], [['pending:A', encounter['revision']]])
        self.assertEqual(selection['caught'], {'encounter_id': 'A', 'pending': True})
        rendered, session = await self.screen(session, 'storage_send_confirm')
        self.assertEqual(rendered['embed'].description, 'Sent 1 Pokémon · +1 Pikachu Candy · 0 Stardust.')
        self.assertEqual(list(self.buttons(rendered)), ['Done'])
        after = await self.research_state()
        sent = [p for p in after['pokemon'] if p['source_encounter_id'] == 'A']
        self.assertEqual(len(sent), 1)
        self.assertEqual((sent[0]['state'], sent[0]['caught_at']), ('sent', encounter['resolved_at']))
        self.assertEqual([p for p in after['pokemon'] if p['state'] == 'owned'], before['pokemon'])
        self.assertEqual(sum(r['quantity'] for r in after['candy']), sum(r['quantity'] for r in before['candy']) + 1)
        receipts = [r for r in after['action_receipts'] if r['action'] == 'research']
        self.assertEqual([r['key'] for r in receipts], ['research:' + selection['preview']['id']])
        lines = [r for r in after['resource_ledger'] if r['reason'] == 'research_send']
        self.assertEqual([(r['receipt_key'], r['delta']) for r in lines], [(receipts[0]['key'], 1)])
        for table in ('profiles', 'inventory', 'encounters', 'catch_attempts', 'pokedex'):
            self.assertEqual(after[table], before[table], table)
        rendered, _ = await self.screen(session, 'ack')
        self.assertEqual(rendered['embed'].title, 'Walker')
        self.assertEqual((await self.rows("SELECT acknowledged_at FROM encounters WHERE encounter_id='A'"))[0],
                         {'acknowledged_at': self.now})
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE source_encounter_id='A'"), sent)

    async def test_pending_send_at_full_storage_sends(self):
        _, session = await self.pending_result()
        await self.fill_storage()
        before = await self.research_state()
        _, session = await self.screen(session, 'catch_send')
        rendered, _ = await self.screen(session, 'storage_send_confirm')
        self.assertIn('Sent 1 Pokémon', rendered['embed'].description)
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE state='owned'")), 250)
        self.assertEqual((await self.rows("SELECT state FROM pokemon WHERE source_encounter_id='A'"))[0]['state'], 'sent')
        self.assertEqual((await self.research_state())['profiles'], before['profiles'])

    async def test_pending_send_shiny_needs_unlock(self):
        _, session = await self.pending_result()
        await self.writer.run(lambda c: c.execute("UPDATE encounters SET shiny=1 WHERE encounter_id='A'"))
        before = await self.research_state()
        rendered, session = await self.screen(session, 'catch_send')
        self.assertEqual(list(self.buttons(rendered)), ['Unlock', 'Cancel'])
        self.assertIn('Shiny', rendered['embed'].description)
        self.assertEqual(await self.research_state(), before)
        rendered, session = await self.screen(session, 'storage_send_confirm')
        self.assertIn('Selection changed', rendered['embed'].description)
        self.assertEqual(await self.research_state(), before)
        _, session = await self.screen(session, 'research')
        rendered, session = await self.screen(session, 'storage_send_unlock')
        self.assertIn('Shiny', rendered['embed'].description)
        self.assertTrue(json.loads(session['selection'])['preview']['unlocked'])
        self.assertEqual(await self.research_state(), before)
        _, _ = await self.screen(session, 'storage_send_confirm')
        self.assertEqual((await self.rows("SELECT state,shiny FROM pokemon WHERE source_encounter_id='A'"))[0],
                         {'state': 'sent', 'shiny': 1})

    async def test_pending_send_expired_preview_new_review_rebuilds_same_pending_catch(self):
        _, session = await self.pending_result()
        _, session = await self.screen(session, 'catch_send')
        old = json.loads(session['selection'])
        before = await self.research_state()
        self.now += 120
        rendered, session = await self.screen(session, 'storage_send_confirm')
        self.assertIn('expired', rendered['embed'].description)
        self.assertEqual(await self.research_state(), before)
        action = self.buttons(rendered)['New review'].custom_id.rsplit(':', 1)[1]
        rendered, session = await self.screen(session, action)
        fresh = json.loads(session['selection'])
        self.assertEqual(fresh['picks'], old['picks'])
        self.assertEqual(fresh['caught'], old['caught'])
        self.assertNotEqual(fresh['preview']['id'], old['preview']['id'])
        self.assertNotIn('toggles', fresh)
        self.assertNotIn('offset', fresh)
        self.assertIn('pending:A', rendered['embed'].description)
        _, session = await self.screen(session, 'storage_send_confirm')
        self.assertEqual((await self.rows("SELECT state FROM pokemon WHERE source_encounter_id='A'"))[0]['state'], 'sent')

    async def test_pending_send_confirm_twice_one_credit(self):
        _, session = await self.pending_result()
        _, session = await self.screen(session, 'catch_send')
        stale = dict(session)
        _, session = await self.screen(session, 'storage_send_confirm')
        after = await self.research_state()
        refused = await self.click(stale, 'storage_send_confirm')
        refused.followup.send.assert_not_awaited()
        self.assertEqual(await self.research_state(), after)
        self.assertEqual(len([r for r in after['action_receipts'] if r['action'] == 'research']), 1)
        self.assertEqual(len([r for r in after['resource_ledger'] if r['reason'] == 'research_send']), 1)

    async def test_pending_send_cancel_returns_to_menu(self):
        _, session = await self.pending_result()
        before = await self.research_state()
        _, session = await self.screen(session, 'catch_send')
        rendered, session = await self.screen(session, 'research_cancel')
        self.assertEqual(list(self.buttons(rendered)), ['Done', 'Send for research'])
        self.assertEqual(json.loads(session['selection'])['encounter_id'], 'A')
        self.assertEqual(await self.research_state(), before)

    async def test_pending_send_after_done_elsewhere_refused(self):
        _, session = await self.pending_result()
        _, session = await self.screen(session, 'catch_send')
        _, competing = await self.open()
        _, _ = await self.screen(competing, 'ack')
        before = await self.research_state()
        rendered, _ = await self.screen(session, 'storage_send_confirm')
        self.assertIn('Selection changed', rendered['embed'].description)
        self.assertEqual(await self.research_state(), before)
        self.assertEqual([p['state'] for p in await self.rows("SELECT * FROM pokemon WHERE source_encounter_id='A'")],
                         ['owned'])

    async def test_fresh_walker_opens_pending_menu_and_both_buttons_resolve_it(self):
        await self.pending_result()
        for full, action in ((False, 'catch_send'), (False, 'ack'), (True, 'catch_send'), (True, 'catch_upgrade')):
            with self.subTest(full=full, action=action):
                async def reset(conn):
                    await conn.execute("DELETE FROM pokemon WHERE source_encounter_id='A'")
                    await conn.execute("UPDATE encounters SET acknowledged_at=NULL WHERE encounter_id='A'")
                    await conn.execute('UPDATE profiles SET storage_limit=250,stardust=15000')
                await self.writer.run(reset)
                if full:
                    await self.fill_storage()
                self.walker = self.module.Walker(self.bot, clock=lambda: self.now)
                self.bot.walker = self.walker
                interaction, session = await self.open()
                rendered = interaction.edit_original_response.await_args.kwargs
                expected = ['catch_send', 'catch_upgrade'] if full else ['ack', 'catch_send']
                self.assertEqual([b.custom_id.rsplit(':', 1)[1] for b in rendered['view'].children], expected)
                rendered, session = await self.screen(session, action)
                if action == 'catch_send':
                    _, session = await self.screen(session, 'storage_send_confirm')
                    rendered, session = await self.screen(session, 'ack')
                self.assertEqual(rendered['embed'].title, 'Walker')
                rows = await self.rows("SELECT state FROM pokemon WHERE source_encounter_id='A'")
                self.assertEqual(rows, [{'state': 'sent' if action == 'catch_send' else 'owned'}])
                self.assertIsNone(await self.walker.pending_catch(self.conn, session['profile_id']))
                self.assertEqual((await self.rows("SELECT acknowledged_at FROM encounters WHERE encounter_id='A'"))[0],
                                 {'acknowledged_at': self.now})

    async def caught_result(self):
        session = await self.prepared(3)
        self.now = 1000
        self.walker.clock = lambda: self.now
        async def seed(conn):
            await conn.execute("UPDATE encounters SET encounter_id='A',shiny=0")
            await conn.executemany(
                "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,"
                "iv_defense,iv_stamina,gender,shiny,tier,route_id,content_version,created_at) "
                "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
                "gender,shiny,tier,route_id,content_version,? FROM encounters WHERE encounter_id='A'",
                [('B', 2), ('C', 3)])
        await self.writer.run(seed)
        _, session = await self.reveal(session)
        with patch.object(self.walker.rng, 'random', return_value=0):
            rendered, session = await self.screen(session, 'throw')
        self.assertIn('Result: caught', rendered['embed'].description)
        self.caught = await store_legacy(self.writer, 'A', self.now)
        return rendered, session

    async def test_real_catch_then_done_stores_then_second_catch_sent(self):
        session = await self.prepared()
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,"
            "iv_defense,iv_stamina,gender,shiny,tier,route_id,content_version,created_at) "
            "SELECT 'second',profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
            "gender,0,tier,route_id,content_version,2 FROM encounters LIMIT 1"))
        await self.writer.run(lambda conn: conn.execute('UPDATE encounters SET shiny=0'))
        _, session = await self.reveal(session)
        with patch.object(self.walker.rng, 'random', return_value=0):
            rendered, session = await self.screen(session, 'throw')
        self.assertEqual(list(self.buttons(rendered)), ['Done', 'Send for research'])
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE origin='catch'"), [])
        _, session = await self.screen(session, 'ack')
        stored = await self.rows("SELECT * FROM pokemon WHERE origin='catch'")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]['state'], 'owned')
        _, session = await self.reveal(session)
        with patch.object(self.walker.rng, 'random', return_value=0):
            rendered, session = await self.screen(session, 'throw')
        self.assertEqual(list(self.buttons(rendered)), ['Done', 'Send for research'])
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE origin='catch'"), stored)
        _, session = await self.screen(session, 'catch_send')
        _, session = await self.screen(session, 'storage_send_confirm')
        self.assertEqual(await self.rows("SELECT state FROM pokemon WHERE source_encounter_id='second'"),
                         [{'state': 'sent'}])
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE state='owned'")), 2)
        await self.screen(session, 'ack')

    async def test_caught_result_offers_send_fresh_and_recovered_not_fled_ran_or_sent(self):
        rendered, session = await self.caught_result()
        for recovery in (False, True):
            if recovery:
                rendered, session = await self.screen(session, 'home')
                self.assertEqual(list(self.buttons(rendered)), ['Done', 'Send for research'])
            button = self.buttons(rendered).get('Send for research')
            self.assertIsNotNone(button)
            self.assertFalse(button.disabled)
            self.assertEqual(button.row, 1)
            self.assertTrue(button.custom_id.endswith(':catch_send'))
        for state in ('fled', 'ran', 'caught'):
            await self.writer.run(lambda c: c.execute("UPDATE encounters SET state=? WHERE encounter_id='A'", (state,)))
            if state == 'caught':
                await self.writer.run(lambda c: c.execute("UPDATE pokemon SET state='sent' WHERE source_encounter_id='A'"))
            rendered, session = await self.screen(session, 'home')
            self.assertEqual(list(self.buttons(rendered)), ['Done'])

    async def test_catch_send_confirm_sends_only_caught_pokemon_then_done_acknowledges_home(self):
        _, session = await self.caught_result()
        before = await self.research_state()
        rendered, session = await self.screen(session, 'catch_send')
        self.assertIn('Pikachu', rendered['embed'].description)
        self.assertIn(self.caught['pokemon_uid'], rendered['embed'].description)
        self.assertIn('+1 Pikachu Candy', rendered['embed'].description)
        self.assertEqual(list(self.buttons(rendered)), ['Send 1 Pokémon', 'Cancel'])
        self.assertEqual(json.loads(session['selection'])['caught'], {'encounter_id': 'A'})
        rendered, session = await self.screen(session, 'storage_send_confirm')
        self.assertEqual(rendered['embed'].description, 'Sent 1 Pokémon · +1 Pikachu Candy · 0 Stardust.')
        self.assertEqual(list(self.buttons(rendered)), ['Done'])
        self.assertTrue(self.buttons(rendered)['Done'].custom_id.endswith(':ack'))
        after = await self.research_state()
        self.assertEqual([p for p in after['pokemon'] if p['state'] == 'sent'],
                         [{**self.caught, 'state': 'sent', 'revision': self.caught['revision'] + 1}])
        self.assertEqual([p for p in after['pokemon'] if p['state'] == 'owned'],
                         [p for p in before['pokemon'] if p['pokemon_uid'] != self.caught['pokemon_uid']])
        self.assertEqual(sum(r['quantity'] for r in after['candy']), sum(r['quantity'] for r in before['candy']) + 1)
        self.assertEqual(len([r for r in after['action_receipts'] if r['action'] == 'research']), 1)
        for table in ('profiles', 'inventory', 'encounters', 'catch_attempts', 'pokedex'):
            self.assertEqual(after[table], before[table])
        rendered, session = await self.screen(session, 'ack')
        self.assertEqual(rendered['embed'].title, 'Walker')
        self.assertEqual((await self.rows("SELECT acknowledged_at FROM encounters WHERE encounter_id='A'"))[0],
                         {'acknowledged_at': 1000})
        _, session = await self.reveal(session)
        self.assertEqual(json.loads(session['selection'])['encounter_id'], 'B')

    async def test_catch_send_from_fresh_walker_recovery(self):
        await self.caught_result()
        self.walker = self.module.Walker(self.bot, clock=lambda: self.now, rng=random.Random(9))
        self.bot.walker = self.walker
        interaction, session = await self.open()
        rendered = interaction.edit_original_response.await_args.kwargs
        self.assertEqual(list(self.buttons(rendered)), ['Done', 'Send for research'])
        await self.screen(session, self.buttons(rendered)['Send for research'].custom_id.rsplit(':', 1)[1])
        _, session = await self.screen(await self.current(session), 'storage_send_confirm')
        rendered, _ = await self.screen(session, 'ack')
        self.assertEqual(rendered['embed'].title, 'Walker')
        self.assertEqual((await self.rows("SELECT state FROM pokemon WHERE source_encounter_id='A'"))[0]['state'], 'sent')

    async def test_catch_send_cancel_returns_to_result_nothing_sent(self):
        _, session = await self.caught_result()
        before = await self.research_state()
        _, session = await self.screen(session, 'catch_send')
        rendered, session = await self.screen(session, 'research_cancel')
        self.assertEqual(rendered['embed'].title, 'Encounter result')
        self.assertEqual(list(self.buttons(rendered)), ['Done', 'Send for research'])
        self.assertEqual(json.loads(session['selection']), {'encounter_id': 'A'})
        self.assertEqual(await self.research_state(), before)

    async def test_catch_send_expired_preview_new_review_rebuilds_same_pokemon(self):
        _, session = await self.caught_result()
        _, session = await self.screen(session, 'catch_send')
        old_preview = json.loads(session['selection'])['preview']
        before = await self.research_state()
        self.now += 120
        rendered, session = await self.screen(session, 'storage_send_confirm')
        self.assertIn('expired', rendered['embed'].description)
        self.assertEqual(await self.research_state(), before)
        action = self.buttons(rendered)['New review'].custom_id.rsplit(':', 1)[1]
        rendered, session = await self.screen(session, action)
        self.assertEqual(list(self.buttons(rendered)), ['Send 1 Pokémon', 'Cancel'])
        selection = json.loads(session['selection'])
        self.assertEqual(selection['picks'], [[self.caught['pokemon_uid'], self.caught['revision']]])
        self.assertNotEqual(selection['preview']['id'], old_preview['id'])
        self.assertNotIn('toggles', selection)
        self.assertNotIn('offset', selection)
        _, session = await self.screen(session, 'storage_send_confirm')
        self.assertEqual([p['pokemon_uid'] for p in await self.rows("SELECT * FROM pokemon WHERE state='sent'")],
                         [self.caught['pokemon_uid']])

    async def test_catch_send_confirm_twice_one_credit(self):
        _, session = await self.caught_result()
        _, session = await self.screen(session, 'catch_send')
        stale = dict(session)
        await self.screen(session, 'storage_send_confirm')
        after = await self.research_state()
        refused = await self.click(stale, 'storage_send_confirm')
        refused.followup.send.assert_not_awaited()
        self.assertEqual(await self.research_state(), after)
        self.assertEqual(len([r for r in after['action_receipts'] if r['action'] == 'research']), 1)

    async def test_catch_send_protected_refused_nothing_sent(self):
        _, session = await self.caught_result()
        for reason in ('favorite', 'companion'):
            if reason == 'favorite':
                await self.writer.run(lambda c: c.execute("UPDATE pokemon SET favorite=1 WHERE source_encounter_id='A'"))
            else:
                await self.writer.run(lambda c: c.execute("UPDATE pokemon SET favorite=0 WHERE source_encounter_id='A'"))
                await self.writer.run(lambda c: c.execute('UPDATE profiles SET companion_uid=?', (self.caught['pokemon_uid'],)))
            before = await self.research_state()
            saved = await self.current(session)
            refused = await self.click(saved, 'catch_send')
            self.assertIn(reason, refused.followup.send.await_args.args[0])
            refused.edit_original_response.assert_not_awaited()
            self.assertEqual(await self.research_state(), before)
            self.assertEqual(await self.current(session), saved)

    async def test_catch_send_refuses_unresolved_foreign_or_sent_encounter(self):
        _, session = await self.caught_result()
        for state in ('unresolved', 'foreign', 'sent'):
            if state == 'unresolved':
                await self.writer.run(lambda c: c.execute("UPDATE encounters SET state='revealed' WHERE encounter_id='A'"))
            elif state == 'foreign':
                await self.writer.run(lambda c: c.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('other','123','999',0)"))
                await self.writer.run(lambda c: c.execute("UPDATE encounters SET state='caught',profile_id='other' WHERE encounter_id='A'"))
            else:
                await self.writer.run(lambda c: c.execute("UPDATE encounters SET profile_id=? WHERE encounter_id='A'", (session['profile_id'],)))
                await self.writer.run(lambda c: c.execute("UPDATE pokemon SET state='sent' WHERE source_encounter_id='A'"))
            before = await self.research_state()
            saved = await self.current(session)
            refused = await self.click(saved, 'catch_send')
            self.assertIn('reopen /walker', refused.followup.send.await_args.args[0])
            refused.edit_original_response.assert_not_awaited()
            self.assertEqual(await self.research_state(), before)
            self.assertEqual(await self.current(session), saved)

    async def catch_full(self, *, queued=True, raid=False):
        session = await self.prepared(300)
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET storage_limit=300,stardust=15000'))
        _, session = await self.reveal(session)
        if raid:
            identity = next(i for i in self.bot.content['identities'] if i['species_id'] == 144)
            async def seed(conn):
                await conn.execute(
                    "INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,"
                    "spawned_at,expires_at,post_state,content_version) "
                    "VALUES ('spawn','123','channel',?,'articuno',900,1100,'sent','fixture')",
                    (identity['pokemon_id'],))
                await conn.execute("UPDATE encounters SET raid_spawn_id='spawn',pokemon_id=?,tier='Legendary/Mythical' "
                                   "WHERE encounter_id=?", (identity['pokemon_id'], self.encounter['encounter_id']))
            await self.writer.run(seed)
        if queued:
            await self.writer.run(lambda c: c.executemany(
                "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,"
                "iv_defense,iv_stamina,gender,shiny,tier,route_id,content_version,created_at) "
                "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
                "gender,shiny,tier,route_id,content_version,? FROM encounters WHERE encounter_id=?",
                [(name, index, self.encounter['encounter_id']) for index, name in enumerate(('B', 'C'), 2)]))
        await self.writer.run(lambda c: c.execute('INSERT INTO inventory VALUES (?,\'great_ball\',2)',
                                                 (session['profile_id'],)))
        for action, value in (('pick_ball', 'great_ball'), ('pick_berry', 'razz_berry')):
            await self.click(session, action, [value])
            session = await self.current(session)
        rendered, session = await self.screen(session, 'throw')
        self.assertIn('Storage is full (300/300).', rendered['embed'].description)
        return rendered, session

    async def test_throw_at_limit_warns_back_spends_nothing_confirm_catches_then_full_menu(self):
        rendered, session = await self.catch_full()
        await self.writer.run(lambda c: c.execute('UPDATE encounters SET level_x2=40'))
        before = await self.research_state()
        selected = json.loads(session['selection'])
        self.assertEqual(selected['storage_confirm'], selected['encounter_revision'])
        self.assertTrue(self.buttons(rendered)['Confirm throw'].custom_id.endswith(':throw'))
        rendered, session = await self.screen(session, 'open_encounter')
        self.assertNotIn('storage_confirm', json.loads(session['selection']))
        self.assertEqual(await self.research_state(), before)
        self.assertEqual(json.loads(session['selection'])['berry'], 'razz_berry')
        _, session = await self.screen(session, 'throw')
        _, session = await self.screen(session, 'home')
        _, session = await self.screen(session, 'open_encounter')
        self.assertNotIn('storage_confirm', json.loads(session['selection']))
        self.assertEqual(await self.research_state(), before)
        _, session = await self.screen(session, 'throw')
        with patch.object(self.walker.rng, 'random', side_effect=[0.99, 0.99]):
            rendered, session = await self.screen(session, 'throw')
        self.assertIn('broke free', rendered['embed'].description)
        after = await self.research_state()
        rendered, session = await self.screen(session, 'throw')
        self.assertIn('Storage is full (300/300).', rendered['embed'].description)
        self.assertEqual(await self.research_state(), after)
        with patch.object(self.walker.rng, 'random', return_value=0):
            rendered, session = await self.screen(session, 'throw')
        self.assertEqual([b.custom_id.rsplit(':', 1)[1] for b in rendered['view'].children],
                         ['catch_send', 'catch_upgrade'])
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE state='owned'")), 300)
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE origin='catch'"), [])

    async def test_master_ball_at_limit_confirms_each_once(self):
        _, session = await self.catch_full()
        _, session = await self.screen(session, 'open_encounter')
        await self.writer.run(lambda c: c.execute('INSERT INTO inventory VALUES (?,\'master_ball\',1)',
                                                 (session['profile_id'],)))
        await self.click(session, 'pick_ball', ['master_ball'])
        session = await self.current(session)
        before = await self.research_state()
        rendered, session = await self.screen(session, 'throw')
        self.assertEqual(list(self.buttons(rendered)), ['Confirm Master Ball', 'Back'])
        rendered, session = await self.screen(session, 'master_confirm')
        self.assertEqual(list(self.buttons(rendered)), ['Confirm throw', 'Back'])
        self.assertTrue(self.buttons(rendered)['Confirm throw'].custom_id.endswith(':master_confirm'))
        self.assertEqual(await self.research_state(), before)
        with patch.object(self.walker.rng, 'random', side_effect=AssertionError('Master Ball rolled')):
            rendered, session = await self.screen(session, 'master_confirm')
        self.assertEqual([b.custom_id.rsplit(':', 1)[1] for b in rendered['view'].children],
                         ['catch_send', 'catch_upgrade'])
        after = await self.research_state()
        await self.screen(session, 'master_confirm')
        self.assertEqual(await self.research_state(), after)
        self.assertEqual((await self.rows("SELECT quantity FROM inventory WHERE item_id='master_ball'"))[0]['quantity'], 0)
        self.assertEqual(len(await self.rows('SELECT * FROM catch_attempts')), 1)

    async def test_storage_warning_after_terminal_stale_and_expired_raid(self):
        _, session = await self.catch_full(raid=True)
        await self.writer.run(lambda c: c.execute('UPDATE world_spawns SET expires_at=999'))
        before = await self.research_state()
        rendered, saved = await self.screen(session, 'throw')
        self.assertIn('expired', rendered['embed'].description)
        self.assertNotIn('Confirm throw', self.buttons(rendered))
        self.assertEqual(saved, session)
        self.assertEqual(await self.research_state(), before)
        await self.writer.run(lambda c: c.execute('UPDATE encounters SET revision=revision+1 WHERE encounter_id=?',
                                                 (self.encounter['encounter_id'],)))
        before = await self.research_state()
        rendered, saved = await self.screen(session, 'throw')
        self.assertIn('Encounter updated', rendered['embed'].description)
        self.assertNotIn('Confirm throw', self.buttons(rendered))
        self.assertEqual(saved, session)
        self.assertEqual(await self.research_state(), before)
        async def competing_throw(conn):
            await conn.execute('UPDATE world_spawns SET expires_at=1100')
            selected = json.loads(session['selection'])
            selected.update(encounter_revision=selected['encounter_revision'] + 1,
                            storage_confirm=selected['encounter_revision'] + 1)
            result = await catching.throw(conn, self.encounter['encounter_id'],
                {**session, 'selection': json.dumps(selected)}, selected['encounter_revision'],
                Mock(random=Mock(return_value=0)), 1000, content=self.bot.content)
            await conn.execute('UPDATE world_spawns SET expires_at=999')
            return result
        caught = await self.writer.run(competing_throw)
        self.assertEqual(caught.status, 'caught')
        await store_legacy(self.writer, self.encounter['encounter_id'], 1000)
        before = await self.research_state()
        rendered, saved = await self.screen(session, 'throw')
        self.assertIn('Result: caught', rendered['embed'].description)
        self.assertIn(f'+{caught.candy} Candy', rendered['embed'].description)
        self.assertIn(f'+{caught.stardust} Stardust', rendered['embed'].description)
        self.assertNotIn('Confirm throw', self.buttons(rendered))
        self.assertEqual(saved, session)
        self.assertEqual(await self.research_state(), before)

    async def test_storage_warning_back_keeps_raid_with_and_without_queue(self):
        _, session = await self.catch_full(raid=True)
        for queued in (True, False):
            with self.subTest(queued=queued):
                if not queued:
                    await self.writer.run(lambda c: c.execute("DELETE FROM encounters WHERE encounter_id IN ('B','C')"))
                selected = json.loads(session['selection'])
                before = await self.research_state()
                _, session = await self.screen(session, 'open_encounter')
                restored = json.loads(session['selection'])
                self.assertEqual(restored, {k: v for k, v in selected.items() if k != 'storage_confirm'})
                self.assertEqual(await self.research_state(), before)
                _, session = await self.screen(session, 'throw')

    async def test_storage_warning_home_clears_only_confirmation_then_opens_ordinary(self):
        _, session = await self.catch_full(raid=True)
        selected = {**json.loads(session['selection']), 'unrelated': 'preserved'}
        await self.writer.run(lambda c: c.execute('UPDATE sessions SET selection=? WHERE session_id=?',
                                                 (json.dumps(selected), session['session_id'])))
        session = await self.current(session)
        before = await self.research_state()
        _, session = await self.screen(session, 'home')
        self.assertEqual(json.loads(session['selection']),
                         {k: v for k, v in selected.items() if k != 'storage_confirm'})
        self.assertEqual(await self.research_state(), before)
        _, session = await self.screen(session, 'open_encounter')
        self.assertEqual(json.loads(session['selection'])['encounter_id'], 'B')

    async def test_storage_warning_later_after_broke_free_opens_ordinary(self):
        _, session = await self.catch_full(raid=True)
        await self.writer.run(lambda c: c.execute('UPDATE encounters SET level_x2=40'))
        with patch.object(self.walker.rng, 'random', return_value=0.99):
            rendered, session = await self.screen(session, 'throw')
        self.assertIn('broke free', rendered['embed'].description)
        selected = json.loads(session['selection'])
        self.assertIn('storage_confirm', selected)
        before = await self.research_state()
        _, session = await self.screen(session, 'later')
        later_selection = json.loads(session['selection'])
        self.assertEqual(await self.research_state(), before)
        _, session = await self.screen(session, 'open_encounter')
        self.assertEqual(json.loads(session['selection'])['encounter_id'], 'B')
        self.assertEqual(later_selection, {k: v for k, v in selected.items() if k != 'storage_confirm'})

    async def research_state(self):
        return {t: await self.rows(f'SELECT * FROM {t}') for t in
                ('profiles', 'pokemon', 'inventory', 'encounters', 'catch_attempts',
                 'candy', 'pokedex', 'action_receipts', 'resource_ledger')}

    async def test_research_from_storage_still_returns_to_storage(self):
        _, session = await self.storage(await self.start())
        for send in (False, True):
            if send:
                await self.writer.run(lambda c: c.execute('UPDATE profiles SET companion_uid=NULL'))
                await self.writer.run(lambda c: c.execute('UPDATE pokemon SET favorite=0'))
            _, session = await self.screen(session, 'research')
            self.assertNotIn('resume', json.loads(session['selection']))
            if send:
                for action in ('research_toggle_a', 'research_review', 'research_confirm'):
                    rendered, session = await self.screen(session, action)
                self.assertTrue(self.buttons(rendered)['Storage'].custom_id.endswith(':storage'))
                rendered, session = await self.storage(session)
            else:
                before = await self.research_state()
                rendered, session = await self.screen(session, 'research_cancel')
                self.assertEqual(await self.research_state(), before)
            self.assertEqual(rendered['embed'].title, 'Storage')

    async def test_storage_expand_from_storage_unchanged(self):
        _, session = await self.storage(await self.start())
        rendered, session = await self.screen(session, 'expand_storage_preview')
        self.assertTrue(self.buttons(rendered)['Back'].custom_id.endswith(':storage'))
        rendered, session = await self.screen(session, 'storage')
        self.assertEqual(rendered['embed'].title, 'Storage')
        _, session = await self.screen(session, 'expand_storage_preview')
        rendered, _ = await self.screen(session, 'expand_storage_confirm')
        self.assertEqual(rendered['embed'].title, 'Storage')
        self.assertIn('1/300', rendered['embed'].description)

    async def test_research_page_drops_legacy_resume(self):
        _, session = await self.storage(await self.start())
        selection = {'offset': 0, 'picks': [], 'resume': {'encounter_id': 'old'}}
        await self.writer.run(lambda c: c.execute('UPDATE sessions SET selection=? WHERE session_id=?',
                                                 (json.dumps(selection), session['session_id'])))
        _, session = await self.screen(await self.current(session), 'research_page')
        self.assertNotIn('resume', json.loads(session['selection']))

    async def test_research_cancel_ignores_legacy_resume(self):
        _, session = await self.storage(await self.start())
        selection = {'picks': [], 'resume': {'encounter_id': 'old'}}
        await self.writer.run(lambda c: c.execute('UPDATE sessions SET selection=? WHERE session_id=?',
                                                 (json.dumps(selection), session['session_id'])))
        before = await self.research_state()
        rendered, _ = await self.screen(await self.current(session), 'research_cancel')
        self.assertEqual(rendered['embed'].title, 'Storage')
        self.assertEqual(await self.research_state(), before)

    async def test_research_confirm_ignores_legacy_resume(self):
        _, session = await self.storage(await self.start())
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET companion_uid=NULL'))
        await self.writer.run(lambda c: c.execute('UPDATE pokemon SET favorite=0'))
        for action in ('research', 'research_toggle_a', 'research_review'):
            _, session = await self.screen(session, action)
        selection = {**json.loads(session['selection']), 'resume': {'encounter_id': 'old'}}
        await self.writer.run(lambda c: c.execute('UPDATE sessions SET selection=? WHERE session_id=?',
                                                 (json.dumps(selection), session['session_id'])))
        rendered, _ = await self.screen(await self.current(session), 'research_confirm')
        self.assertEqual(list(self.buttons(rendered)), ['Storage'])
        self.assertTrue(self.buttons(rendered)['Storage'].custom_id.endswith(':storage'))

    async def test_storage_expand_ignores_legacy_back(self):
        _, session = await self.storage(await self.start())
        selection = {**json.loads(session['selection']), 'back': 'open_encounter'}
        await self.writer.run(lambda c: c.execute('UPDATE sessions SET selection=? WHERE session_id=?',
                                                 (json.dumps(selection), session['session_id'])))
        rendered, session = await self.screen(await self.current(session), 'expand_storage_preview')
        self.assertTrue(self.buttons(rendered)['Back'].custom_id.endswith(':storage'))
        rendered, _ = await self.screen(session, 'expand_storage_confirm')
        self.assertEqual(rendered['embed'].title, 'Storage')
        self.assertIn('1/300', rendered['embed'].description)

    async def test_stale_click_after_confirm_reopens_without_second_charge(self):
        _, session = await self.screen(await self.start(), 'expand_storage_preview')
        stale = dict(session)
        _, session = await self.screen(session, 'expand_storage_confirm')
        before = await self.purchase_state()
        old = await self.click(stale, 'expand_storage_confirm')
        old.followup.send.assert_not_awaited()
        rendered, _ = await self.screen(session, 'expand_storage_confirm')
        self.assertIn('350 slots', rendered['embed'].description)
        self.assertIn('nothing', rendered['embed'].description.lower())
        self.assertEqual(await self.purchase_state(), before)

    async def test_confirm_after_limit_changed_elsewhere_re_previews_no_charge(self):
        _, session = await self.screen(await self.start(), 'expand_storage_preview')
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET storage_limit=300'))
        before = await self.purchase_state()
        rendered, session = await self.screen(session, 'expand_storage_confirm')
        self.assertIn('350 slots', rendered['embed'].description)
        self.assertIn('changed', rendered['embed'].description.lower())
        self.assertEqual(json.loads(session['selection'])['storage_limit'], 300)
        await self.assert_saved_refusal(before, 'stale')

    async def test_expand_requires_preview_and_existing_access_guards(self):
        session = await self.start()
        before = await self.purchase_state()
        rendered, session = await self.screen(session, 'expand_storage_confirm')
        self.assertEqual(await self.purchase_state(), before)
        self.assertIn('300 slots', rendered['embed'].description)
        for action in ('expand_storage_preview', 'expand_storage_confirm'):
            for who in ({'user': 999}, {'guild': 999}):
                interaction = await self.click(session, action, **who)
                interaction.edit_original_response.assert_not_awaited()
                self.assertEqual(await self.purchase_state(), before)
        await self.writer.run(lambda c: c.execute(
            "INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)"))
        for action in ('expand_storage_preview', 'expand_storage_confirm'):
            interaction = await self.click(session, action)
            self.assertIn('excluded', interaction.followup.send.await_args.args[0].lower())
            self.assertEqual(await self.purchase_state(), before)

    async def test_render_functions_do_no_io(self):
        module = importlib.import_module('pokewalker.bot.storage')
        session = await self.start()
        with patch.object(module, 'render_expand', wraps=module.render_expand) as render:
            await self.screen(session, 'expand_storage_preview')
            state = render.call_args.args[0]
        with patch.object(self.conn, 'execute', side_effect=AssertionError('database I/O')), \
                patch.object(self.writer, 'run', side_effect=AssertionError('writer I/O')), \
                patch('builtins.open', side_effect=AssertionError('file I/O')), \
                patch('socket.socket', side_effect=AssertionError('network I/O')):
            self.assertIn('Confirm', self.buttons(module.render_expand(state)))


class BagCapacityTests(unittest.IsolatedAsyncioTestCase):
    close = conversion_tests.ConversionTests.close
    rows = conversion_tests.ConversionTests.rows
    current = conversion_tests.ConversionTests.current
    interaction = conversion_tests.ConversionTests.interaction
    click = conversion_tests.ConversionTests.click
    screen = conversion_tests.ConversionTests.screen
    buttons = conversion_tests.ConversionTests.buttons

    async def asyncSetUp(self):
        await conversion_tests.ConversionTests.asyncSetUp(self)
        from pokewalker.bot.client import load_content
        self.bot.content = load_content(Path('tests/fixtures/bag_kinds/content/artifact/content.json'))
        self.bot.content['milestones'] = {}
        await self.conn.execute('UPDATE profiles SET stardust=15000')

    async def purchase_state(self):
        return {table: await self.rows(f'SELECT * FROM {table}') for table in
                ('profiles', 'inventory', 'action_receipts', 'resource_ledger')}

    async def assert_saved_refusal(self, before, status):
        after = await self.purchase_state()
        for table in ('profiles', 'inventory', 'resource_ledger'):
            self.assertEqual(after[table], before[table])
        self.assertEqual(after['action_receipts'][:-1], before['action_receipts'])
        receipt = after['action_receipts'][-1]
        self.assertEqual((receipt['action'], receipt['profile_id']), ('expand', 'p'))
        self.assertEqual(json.loads(receipt['result']), {'status': status})

    async def seed_waiting_items(self):
        await self.conn.execute("INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) "
                                "VALUES ('p','pokedex:5','item','great_ball',5,0)")
        await self.conn.execute("UPDATE inventory SET quantity=250 WHERE item_id='poke_ball'")

    async def test_inbox_expand_bag_confirm_returns_to_inbox_then_claim_moves_items(self):
        await self.seed_waiting_items()
        waiting = await self.rows('SELECT * FROM inbox_items')
        inventory = await self.rows('SELECT * FROM inventory')
        rendered = await self.screen('inbox_expand_bag')
        self.assertTrue(self.buttons(rendered)['Back'].custom_id.endswith(':inbox'))
        rendered = await self.screen('expand_bag_confirm')
        self.assertEqual(rendered['embed'].title, 'Reward inbox')
        self.assertEqual(await self.rows('SELECT bag_limit,stardust FROM profiles'),
                         [{'bag_limit': 300, 'stardust': 12500}])
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), waiting)
        self.assertEqual(await self.rows('SELECT * FROM inventory'), inventory)
        self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='claim'"), [])
        self.assertEqual(json.loads((await self.current())['selection']), {})
        await self.screen('claim')
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), [])
        self.assertEqual(await items.bag_units(self.conn, 'p'), 255)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='expand'")), 1)

    async def test_inbox_back_cancels_expansion_current_revision_confirm(self):
        await self.seed_waiting_items()
        rendered = await self.screen('inbox_expand_bag')
        back = self.buttons(rendered)['Back'].custom_id.rsplit(':', 1)[1]
        self.assertEqual((await self.screen(back))['embed'].title, 'Reward inbox')
        before = await self.purchase_state()
        waiting = await self.rows('SELECT * FROM inbox_items')
        await self.screen('expand_bag_confirm')
        self.assertEqual(await self.purchase_state(), before)
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), waiting)

    async def test_inbox_expand_insufficient_or_at_cap_keeps_back(self):
        for limit, dust, status in ((1000, 15000, 'at_cap'), (250, 2499, 'insufficient'),
                                    (250, 15000, 'stale')):
            with self.subTest(status=status):
                await self.conn.execute('UPDATE profiles SET bag_limit=?,stardust=?', (limit, dust))
                await self.screen('inbox_expand_bag')
                if status == 'stale':
                    await self.conn.execute('UPDATE profiles SET bag_limit=300')
                before = await self.purchase_state()
                rendered = await self.screen('expand_bag_confirm')
                self.assertEqual(self.buttons(rendered)['Confirm'].disabled, status != 'stale')
                self.assertIn('Nothing was spent.', rendered['embed'].description)
                self.assertTrue(self.buttons(rendered)['Back'].custom_id.endswith(':inbox'))
                self.assertEqual(json.loads((await self.current())['selection'])['back'], 'inbox')
                await self.assert_saved_refusal(before, status)

    async def test_bag_expand_and_convert_from_bag_unchanged(self):
        await self.screen('bag')
        for action in ('expand_bag_preview', 'convert_pick'):
            rendered = await self.screen(action)
            self.assertTrue(self.buttons(rendered)['Back'].custom_id.endswith(':bag'))
            await self.screen('bag')
        await self.screen('expand_bag_preview')
        self.assertEqual((await self.screen('expand_bag_confirm'))['embed'].title, 'Bag')
        await self.screen('convert_pick')
        await self.screen('convert_qty', ['poke_ball'])
        await self.screen('convert_preview', ['5'])
        self.assertEqual((await self.screen('convert_confirm'))['embed'].title, 'Bag')
        self.assertEqual(await self.rows('SELECT bag_limit,stardust FROM profiles'),
                         [{'bag_limit': 300, 'stardust': 12510}])

    async def test_bag_units_line_shows_profile_limit(self):
        await self.conn.execute('UPDATE profiles SET bag_limit=350')
        rendered = await self.screen('bag')
        self.assertIn('20/350 units', rendered['embed'].description)
        self.assertTrue(self.buttons(rendered)['Expand bag'].custom_id.endswith(':expand_bag_preview'))

    async def test_expand_bag_preview_then_confirm_updates_units_line(self):
        before = await self.purchase_state()
        rendered = await self.screen('expand_bag_preview')
        self.assertIn('2,500 Stardust → 300 units · have 15,000', rendered['embed'].description)
        self.assertFalse(self.buttons(rendered)['Confirm'].disabled)
        self.assertTrue(self.buttons(rendered)['Confirm'].custom_id.endswith(':expand_bag_confirm'))
        self.assertEqual(json.loads((await self.current())['selection'])['bag_limit'], 250)
        self.assertEqual(await self.purchase_state(), before)
        with patch.object(capacity, 'expand', wraps=capacity.expand) as expand:
            rendered = await self.screen('expand_bag_confirm')
        self.assertEqual(expand.call_args.args[2:], ('bag', 250, 1000))
        self.assertIn('20/300 units', rendered['embed'].description)
        self.assertIn('expanded', rendered['embed'].description.lower())
        profile = (await self.rows('SELECT * FROM profiles'))[0]
        self.assertEqual((profile['bag_limit'], profile['stardust'], profile['storage_limit']),
                         (300, 12500, 250))
        self.assertEqual(await self.rows('SELECT * FROM inventory'), before['inventory'])
        self.assertEqual(json.loads((await self.current())['selection']), {})
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='expand'")), 1)
        self.assertEqual(await self.rows("SELECT resource,resource_id,delta FROM resource_ledger "
                                         "WHERE reason='expand_bag' ORDER BY line_key"), [
            {'resource': 'stardust', 'resource_id': None, 'delta': -2500},
            {'resource': 'capacity', 'resource_id': 'bag', 'delta': 50}])

    async def test_expand_bag_confirm_disabled_at_cap_and_when_unaffordable(self):
        for limit, dust in ((1000, 15000), (250, 2499)):
            with self.subTest(limit=limit, dust=dust):
                await self.conn.execute('UPDATE profiles SET bag_limit=?,stardust=?', (limit, dust))
                rendered = await self.screen('expand_bag_preview')
                self.assertTrue(self.buttons(rendered)['Confirm'].disabled)
                before = await self.purchase_state()
                rendered = await self.screen('expand_bag_confirm')
                self.assertTrue(self.buttons(rendered)['Confirm'].disabled)
                self.assertIn('nothing', rendered['embed'].description.lower())
                await self.assert_saved_refusal(before, 'at_cap' if limit == 1000 else 'insufficient')

    async def test_expand_bag_twice_one_charge(self):
        await self.screen('expand_bag_preview')
        session = await self.current()
        clicks = await asyncio.gather(*(self.click(session, 'expand_bag_confirm') for _ in range(2)))
        self.assertEqual(sum(c.edit_original_response.await_count for c in clicks), 1)
        refused = next(c for c in clicks if not c.edit_original_response.await_count)
        refused.followup.send.assert_not_awaited()
        self.assertEqual(await self.rows('SELECT bag_limit,stardust FROM profiles'),
                         [{'bag_limit': 300, 'stardust': 12500}])
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='expand'")), 1)
        before = await self.purchase_state()
        rendered = await self.screen('expand_bag_confirm')
        self.assertIn('350 units', rendered['embed'].description)
        self.assertIn('nothing', rendered['embed'].description.lower())
        self.assertEqual(await self.purchase_state(), before)

    async def test_bag_confirm_after_limit_changed_re_previews(self):
        await self.screen('expand_bag_preview')
        await self.conn.execute('UPDATE profiles SET bag_limit=300')
        before = await self.purchase_state()
        rendered = await self.screen('expand_bag_confirm')
        self.assertIn('350 units', rendered['embed'].description)
        self.assertIn('changed', rendered['embed'].description.lower())
        self.assertEqual(json.loads((await self.current())['selection'])['bag_limit'], 300)
        await self.assert_saved_refusal(before, 'stale')

    async def test_bag_view_within_5_rows_all_buttons(self):
        await self.conn.executemany('INSERT INTO inventory VALUES (?,?,1)',
                                    [('p', 'master_ball'), ('p', 'shiny_lure'), ('p', 'star_piece')])
        rendered = await self.screen('bag')
        self.assertEqual(set(self.buttons(rendered)),
                         {'Convert', 'Buy evolution item', 'Shiny Lure', 'Star Piece', 'Expand bag', 'Back'})
        view = rendered['view']
        self.assertLessEqual(len(view.children), 25)
        widths = [0] * 5
        for component in view.children:
            self.assertIn(component._rendered_row, range(5))
            widths[component._rendered_row] += component.width
        self.assertTrue(all(width <= 5 for width in widths))
        self.assertTrue(all(not button.disabled for button in self.buttons(rendered).values()))

    async def test_bag_expand_requires_preview_and_existing_access_guards(self):
        before = await self.purchase_state()
        rendered = await self.screen('expand_bag_confirm')
        self.assertIn('300 units', rendered['embed'].description)
        self.assertIn('nothing', rendered['embed'].description.lower())
        self.assertEqual(await self.purchase_state(), before)
        for action in ('expand_bag_preview', 'expand_bag_confirm', 'inbox_expand_bag', 'inbox_convert'):
            for who in ({'user': 999}, {'guild': 999}):
                refused = await self.click(await self.current(), action, **who)
                refused.edit_original_response.assert_not_awaited()
                self.assertEqual(await self.purchase_state(), before)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        for action in ('expand_bag_preview', 'expand_bag_confirm', 'inbox_expand_bag', 'inbox_convert'):
            refused = await self.click(await self.current(), action)
            self.assertIn('excluded', refused.followup.send.await_args.args[0].lower())
            self.assertEqual(await self.purchase_state(), before)

    async def test_render_functions_do_no_io(self):
        module = importlib.import_module('pokewalker.bot.bag')
        states = []
        with patch.object(module, 'render', wraps=module.render) as render:
            for action in ('bag', 'expand_bag_preview'):
                await self.screen(action)
                states.append(render.call_args.args[0])
        with patch('builtins.open', side_effect=AssertionError('file I/O')), \
                patch('aiosqlite.Connection.execute', side_effect=AssertionError('DB I/O')), \
                patch.object(self.writer, 'run', side_effect=AssertionError('writer I/O')), \
                patch('socket.socket', side_effect=AssertionError('network I/O')):
            for state in states:
                self.assertIsNotNone(module.render(state)['embed'])
