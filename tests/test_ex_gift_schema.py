"""C3 EX-Gift migration, retention and constraints on real SQLite."""

import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from pokewalker import db
import test_db


class ExGiftSchemaTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_db.DatabaseTests.scalar
    profile = test_db.DatabaseTests.profile

    async def asyncSetUp(self):
        await test_db.DatabaseTests.asyncSetUp(self)
        self.pid = await self.profile('u', 'g')
        await self.conn.execute(
            "INSERT INTO arena_runs(run_id,profile_id,started_at,floor,slot,team,enemy) "
            "VALUES ('r',?,100,1,0,'[]','{}')", (self.pid,))

    async def schema29(self):
        prior = Path(self.temp.name) / 'schema29'
        prior.mkdir()
        for migration in db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'):
            if int(migration.name[:4]) <= 29:
                shutil.copyfile(migration, prior / migration.name)
        path = Path(self.temp.name) / 'schema29.sqlite3'
        with patch.object(db, 'MIGRATIONS', prior):
            old = await db.open_db(path)
        try:
            self.assertEqual(await self.scalar('PRAGMA user_version', conn=old), 29)
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('g')")
            await old.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,stardust) "
                              "VALUES ('old','g','u',10,1234)")
            await old.execute(
                "INSERT INTO arena_runs(run_id,profile_id,started_at,floor,slot,team,enemy) "
                "VALUES ('old-run','old',100,7,2,'[]','{}')")
            for inbox_id, resource, resource_id in (
                    (3, 'item', 'poke_ball'), (17, 'stardust', None), (98, 'candy', '1')):
                await old.execute(
                    "INSERT INTO inbox_items VALUES (?,'old','existing',?,?,7,42)",
                    (inbox_id, resource, resource_id))
            before = {table: [dict(row) for row in await old.execute_fetchall(
                f'SELECT * FROM {table}')] for table in ('profiles', 'arena_runs', 'inbox_items')}
        finally:
            await old.close()
        return path, prior, before

    async def gift(self, **overrides):
        row = dict(gift_id='gift', owner_id='owner', scope='all', guild_id=None,
                   items=json.dumps(['ex_attack']), servers=1, servers_with_recipients=1,
                   recipients=1, created_at=100)
        row.update(overrides)
        await self.conn.execute(
            f"INSERT INTO ex_gifts({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
            tuple(row.values()))

    async def test_migration_0030_preserves_inbox_rows_and_ids(self):
        path, prior, before = await self.schema29()
        for _ in range(2):
            upgraded = await db.open_db(path)
            try:
                self.assertEqual(await self.scalar('PRAGMA user_version', conn=upgraded), 34)
                self.assertEqual(await self.scalar('PRAGMA foreign_keys', conn=upgraded), 1)
                self.assertEqual([dict(row) for row in await upgraded.execute_fetchall(
                    'SELECT * FROM inbox_items ORDER BY inbox_id')], before['inbox_items'])
                self.assertEqual(await upgraded.execute_fetchall('PRAGMA foreign_key_check'), [])
                self.assertEqual([row['name'] for row in await upgraded.execute_fetchall(
                    'PRAGMA index_info(inbox_items_profile_id)')], ['profile_id'])
            finally:
                await upgraded.close()
        with patch.object(db, 'MIGRATIONS', prior):
            with self.assertRaisesRegex(RuntimeError, 'schema is newer'):
                await db.open_db(path)

    async def test_inbox_accepts_arena_ticket_rejects_unknown_resource(self):
        await self.conn.execute(
            "INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) "
            "VALUES (?,'ex_gift:gift','arena_ticket','bronze',1,100)", (self.pid,))
        self.assertEqual(await self.scalar('SELECT resource FROM inbox_items'), 'arena_ticket')
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("UPDATE inbox_items SET resource='unknown'")

    async def test_new_flags_default_off_on_existing_profiles_and_runs(self):
        path, _, before = await self.schema29()
        upgraded = await db.open_db(path)
        try:
            for table, columns in (('profiles', ('ex_attack_armed', 'ex_defense_armed')),
                                   ('arena_runs', ('ex_attack', 'ex_defense'))):
                row = dict((await upgraded.execute_fetchall(f'SELECT * FROM {table}'))[0])
                if table == 'profiles':  # D74 lifetime counters backfill to 0 here
                    self.assertEqual((row.pop('catch_total'), row.pop('steps_total_c')), (0, 0))
                for column in columns:
                    self.assertEqual(row.pop(column), 0)
                self.assertEqual(row, before[table][0])
                self.assertEqual(tuple((await self.conn.execute_fetchall(
                    f"SELECT {','.join(columns)} FROM {table}"))[0]), (0, 0))
        finally:
            await upgraded.close()

    async def test_flag_checks_reject_2_and_text(self):
        for table, columns in (('profiles', ('ex_attack_armed', 'ex_defense_armed')),
                               ('arena_runs', ('ex_attack', 'ex_defense'))):
            for column in columns:
                for value in (2, 'bad', 1.5, None):
                    with self.subTest(table=table, column=column, value=value):
                        with self.assertRaises(sqlite3.IntegrityError):
                            await self.conn.execute(f'UPDATE {table} SET {column}=?', (value,))
                for value in (1, 0):
                    await self.conn.execute(f'UPDATE {table} SET {column}=?', (value,))
                    self.assertEqual(await self.scalar(f'SELECT {column} FROM {table}'), value)

    async def test_ex_items_rejects_unknown_id_and_negative_quantity(self):
        for item_id, quantity in (('unknown', 1), ('ex_attack', -1), ('ex_attack', 1.5),
                                  ('ex_attack', 'bad'), ('ex_attack', None)):
            with self.subTest(item_id=item_id, quantity=quantity):
                with self.assertRaises(sqlite3.IntegrityError):
                    await self.conn.execute('INSERT INTO ex_items VALUES (?,?,?)',
                                            (self.pid, item_id, quantity))
        for item_id in ('time_gear_fragment', 'shiny_patch', 'golden_bottlecap',
                        'ex_attack', 'ex_defense', 'arena_ex_voucher'):
            await self.conn.execute('INSERT INTO ex_items VALUES (?,?,?)',
                                    (self.pid, item_id, 1_000_000_000))
        await self.conn.execute("UPDATE ex_items SET quantity=0 WHERE item_id='ex_attack'")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("INSERT INTO ex_items VALUES (?,'shiny_patch',1)", (self.pid,))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("INSERT INTO ex_items VALUES ('missing','ex_attack',1)")

    async def test_ex_gifts_scope_guild_and_count_checks(self):
        invalid = [dict(scope='all', guild_id='g'), dict(scope='server'), dict(scope='user'),
                   dict(scope='unknown'), dict(recipients=0), dict(items=json.dumps(['x'] * 11)),
                   dict(items='[]'), dict(items='{}'), dict(items='bad')]
        for column in ('servers', 'servers_with_recipients', 'recipients'):
            invalid += [{column: value} for value in (-1, 1.5, 'bad', None)]
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaises(sqlite3.IntegrityError):
                    await self.gift(**overrides)
        await self.gift(servers=0, servers_with_recipients=0)
        await self.gift(gift_id='server', scope='server', guild_id='not-persisted',
                        items=json.dumps(['x'] * 10))
        await self.gift(gift_id='user', scope='user', guild_id='g')

    async def test_ex_gifts_has_no_user_or_recipient_column(self):
        columns = {row['name'] for row in await self.conn.execute_fetchall('PRAGMA table_info(ex_gifts)')}
        self.assertEqual(columns, {'gift_id', 'owner_id', 'scope', 'guild_id', 'items',
                                   'servers', 'servers_with_recipients', 'recipients', 'created_at'})
        self.assertEqual(await self.conn.execute_fetchall('PRAGMA foreign_key_list(ex_gifts)'), [])
        for index, columns in (('ex_gifts_created_at', ['created_at']),
                               ('ex_gift_recipients_profile_claimed', ['profile_id', 'claimed_at'])):
            self.assertEqual([row['name'] for row in await self.conn.execute_fetchall(
                f'PRAGMA index_info({index})')], columns)

    async def test_profile_delete_cascades_recipients_ex_items_inbox_keeps_ex_gifts(self):
        await self.gift(scope='user', guild_id='g')
        await self.conn.execute('INSERT INTO ex_gift_recipients VALUES (?,?,NULL)', ('gift', self.pid))
        await self.conn.execute("INSERT INTO ex_items VALUES (?,'ex_attack',2)", (self.pid,))
        await self.conn.execute("INSERT INTO inbox_items VALUES (51,?,'ex_gift:gift','arena_ticket','gold',1,100)",
                                (self.pid,))
        before = dict((await self.conn.execute_fetchall('SELECT * FROM ex_gifts'))[0])
        await self.conn.execute('DELETE FROM profiles WHERE profile_id=?', (self.pid,))
        for table in ('ex_gift_recipients', 'ex_items', 'inbox_items'):
            self.assertEqual(await self.scalar(f'SELECT count(*) FROM {table}'), 0)
        self.assertEqual(dict((await self.conn.execute_fetchall('SELECT * FROM ex_gifts'))[0]), before)
        self.assertEqual(await self.conn.execute_fetchall('PRAGMA foreign_key_check'), [])

    async def test_recipient_pair_unique(self):
        await self.gift()
        await self.conn.execute('INSERT INTO ex_gift_recipients VALUES (?,?,NULL)', ('gift', self.pid))
        self.assertIsNone(await self.scalar('SELECT claimed_at FROM ex_gift_recipients'))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute('INSERT INTO ex_gift_recipients VALUES (?,?,123)', ('gift', self.pid))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("INSERT INTO ex_gift_recipients VALUES ('missing',?,NULL)", (self.pid,))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("INSERT INTO ex_gift_recipients VALUES ('gift','missing',NULL)")
        await self.conn.execute("DELETE FROM ex_gifts WHERE gift_id='gift'")
        self.assertEqual(await self.scalar('SELECT count(*) FROM ex_gift_recipients'), 0)
