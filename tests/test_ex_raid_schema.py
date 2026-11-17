"""C3 EX-Raid migration and constraints on real SQLite."""

from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from pokewalker import db
import test_db


class ExRaidSchemaTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_db.DatabaseTests.scalar
    asyncSetUp = test_db.DatabaseTests.asyncSetUp

    async def send(self, **overrides):
        row = dict(ex_raid_id='send', owner_id='owner', identity_id='1', shiny=None,
                   level=None, iv_attack=None, iv_defense=None, iv_stamina=None,
                   hours=1, guild_id=None, servers=1, spawned=1, skipped='{}', created_at=100)
        row.update(overrides)
        await self.conn.execute(
            f"INSERT INTO ex_raids({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
            tuple(row.values()))

    async def spawn(self, spawn_id='spawn', *, kind='world', ended=0, ex_raid_id=None):
        await self.conn.execute("INSERT OR IGNORE INTO guilds(guild_id) VALUES ('g')")
        await self.conn.execute(
            "INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,"
            "spawned_at,expires_at,post_state,ended,content_version,kind,ex_raid_id) "
            "VALUES (?,'g','c',1,'1',100,3700,'pending',?,'test',?,?)",
            (spawn_id, ended, kind, ex_raid_id))

    async def test_migration_0031_existing_spawns_become_world(self):
        prior = Path(self.temp.name) / 'schema30'
        prior.mkdir()
        for migration in db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'):
            if int(migration.name[:4]) <= 30:
                shutil.copyfile(migration, prior / migration.name)
        path = Path(self.temp.name) / 'schema30.sqlite3'
        with patch.object(db, 'MIGRATIONS', prior):
            old = await db.open_db(path)
        try:
            self.assertEqual(await self.scalar('PRAGMA user_version', conn=old), 30)
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('g')")
            for spawn_id, ended in (('live', 0), ('ended', 1)):
                await old.execute(
                    "INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,"
                    "spawned_at,expires_at,post_state,ended,content_version) "
                    "VALUES (?,'g','c',1,'1',100,3700,'pending',?,'test')", (spawn_id, ended))
            before = [dict(row) for row in await old.execute_fetchall(
                'SELECT * FROM world_spawns ORDER BY spawn_id')]
            unchanged = [tuple(row) for row in await old.execute_fetchall(
                "SELECT name,sql FROM sqlite_master WHERE name IN "
                "('raid_participation','encounters','encounter_queue_insert','encounter_queue_update') "
                "ORDER BY name")]
        finally:
            await old.close()
        for _ in range(2):
            upgraded = await db.open_db(path)
            try:
                self.assertEqual(await self.scalar('PRAGMA user_version', conn=upgraded), 31)
                self.assertEqual(await self.scalar('PRAGMA foreign_keys', conn=upgraded), 1)
                self.assertEqual([dict(row) for row in await upgraded.execute_fetchall(
                    'SELECT * FROM world_spawns ORDER BY spawn_id')],
                    [dict(row, kind='world', ex_raid_id=None) for row in before])
                self.assertEqual(await upgraded.execute_fetchall('PRAGMA foreign_key_check'), [])
                self.assertEqual([tuple(row) for row in await upgraded.execute_fetchall(
                    "SELECT name,sql FROM sqlite_master WHERE name IN "
                    "('raid_participation','encounters','encounter_queue_insert','encounter_queue_update') "
                    "ORDER BY name")], unchanged)
            finally:
                await upgraded.close()
        with patch.object(db, 'MIGRATIONS', prior):
            with self.assertRaisesRegex(RuntimeError, 'schema is newer'):
                await db.open_db(path)

    async def test_one_live_spawn_per_guild_and_kind(self):
        await self.spawn('world')
        await self.spawn('ex', kind='ex')
        for kind in ('world', 'ex'):
            with self.subTest(kind=kind):
                with self.assertRaises(sqlite3.IntegrityError):
                    await self.spawn('duplicate', kind=kind)
                await self.conn.execute('UPDATE world_spawns SET ended=1 WHERE kind=?', (kind,))
                await self.spawn(f'new-{kind}', kind=kind)
        self.assertEqual(await self.scalar('SELECT count(*) FROM world_spawns WHERE ended=0'), 2)
        self.assertEqual([row['name'] for row in await self.conn.execute_fetchall(
            'PRAGMA index_info(world_spawns_active_guild_kind)')], ['guild_id', 'kind'])

    async def test_kind_check_rejects_unknown(self):
        with self.assertRaises(sqlite3.IntegrityError):
            await self.spawn(kind='unknown')
        with self.assertRaises(sqlite3.IntegrityError):
            await self.spawn(kind=None)

    async def test_ex_raids_lock_hours_and_count_checks(self):
        bounds = {'shiny': (0, 1), 'level': (1, 40), 'iv_attack': (0, 15),
                  'iv_defense': (0, 15), 'iv_stamina': (0, 15), 'hours': (1, 24),
                  'servers': (1, None), 'spawned': (1, None)}
        for column, (lo, hi) in bounds.items():
            values = [lo - 1, 'bad', 1.5]
            if hi is not None:
                values.append(hi + 1)
            if column in ('hours', 'servers', 'spawned'):
                values.append(None)
            for value in values:
                with self.subTest(column=column, value=value):
                    with self.assertRaises(sqlite3.IntegrityError):
                        await self.send(**{column: value})
        for column in ('ex_raid_id', 'owner_id', 'identity_id', 'skipped', 'created_at'):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError):
                    await self.send(**{column: None})
        with self.assertRaises(sqlite3.IntegrityError):
            await self.send(skipped='bad')
        await self.send()
        self.assertEqual(tuple((await self.conn.execute_fetchall(
            'SELECT shiny,level,iv_attack,iv_defense,iv_stamina FROM ex_raids'))[0]), (None,) * 5)
        await self.send(ex_raid_id='zero', shiny=0, level=1, iv_attack=0, iv_defense=0, iv_stamina=0)
        await self.send(ex_raid_id='max', shiny=1, level=40, iv_attack=15, iv_defense=15,
                        iv_stamina=15, hours=24, servers=10000, spawned=10000)

    async def test_ex_raids_has_no_player_column(self):
        self.assertEqual({row['name'] for row in await self.conn.execute_fetchall(
            'PRAGMA table_info(ex_raids)')}, {'ex_raid_id', 'owner_id', 'identity_id', 'shiny',
            'level', 'iv_attack', 'iv_defense', 'iv_stamina', 'hours', 'guild_id',
            'servers', 'spawned', 'skipped', 'created_at'})
        self.assertEqual(await self.conn.execute_fetchall('PRAGMA foreign_key_list(ex_raids)'), [])
        self.assertEqual([row['name'] for row in await self.conn.execute_fetchall(
            'PRAGMA index_info(ex_raids_created_at)')], ['created_at'])
        await self.send(guild_id='not-persisted')

    async def test_spawn_ex_raid_id_must_reference_a_send(self):
        with self.assertRaises(sqlite3.IntegrityError):
            await self.spawn(kind='ex', ex_raid_id='missing')
        await self.send()
        await self.spawn(kind='ex', ex_raid_id='send')
        self.assertEqual(await self.scalar('SELECT ex_raid_id FROM world_spawns'), 'send')

    async def test_guild_delete_cascades_ex_spawns_keeps_ex_raids(self):
        await self.send(guild_id='g')
        await self.spawn(kind='ex', ex_raid_id='send')
        before = dict((await self.conn.execute_fetchall('SELECT * FROM ex_raids'))[0])
        await self.conn.execute("DELETE FROM guilds WHERE guild_id='g'")
        self.assertEqual(await self.scalar('SELECT count(*) FROM world_spawns'), 0)
        self.assertEqual(dict((await self.conn.execute_fetchall('SELECT * FROM ex_raids'))[0]), before)
        self.assertEqual(await self.conn.execute_fetchall('PRAGMA foreign_key_check'), [])
