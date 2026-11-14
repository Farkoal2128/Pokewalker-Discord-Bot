"""C3 Arena migration and read-only live-team boundary on real SQLite."""

import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from content.balance import load_table
from pokewalker import db
from pokewalker.services import profiles
import test_db


class ArenaSchemaTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_db.DatabaseTests.scalar
    profile = test_db.DatabaseTests.profile

    async def asyncSetUp(self):
        await test_db.DatabaseTests.asyncSetUp(self)
        self.pid = await self.profile('u', 'g')
        self.other = await self.profile('v', 'g')
        self.team = [{'uid': uid, 'family_id': 1, 'special': False,
                      'full_hp': 40, 'hp': hp, 'snapshot': {'pokemon_uid': uid}}
                     for uid, hp in (('a', 0), ('b', 20), ('c', 40))]

    async def run_row(self, **overrides):
        row = dict(run_id='r', profile_id=self.pid, started_at=100,
                   floor=1, slot=0, team=json.dumps(self.team),
                   enemy=json.dumps({'snapshot': {}, 'battle_hp': 40, 'special': False}))
        row.update(overrides)
        await self.conn.execute(
            f"INSERT INTO arena_runs({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
            tuple(row.values()))

    async def test_migration_0025_adds_tables_columns_preserving_rows(self):
        prior = Path(self.temp.name) / 'prior'
        prior.mkdir()
        for migration in db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'):
            if int(migration.name[:4]) <= 24:
                shutil.copyfile(migration, prior / migration.name)
        path = Path(self.temp.name) / 'prior.sqlite3'
        with patch.object(db, 'MIGRATIONS', prior):
            old = await db.open_db(path)
        try:
            self.assertEqual(await self.scalar('PRAGMA user_version', conn=old), 24)
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('old-g')")
            await old.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,stardust) "
                              "VALUES ('old','old-g','u',10,1234)")
            await old.execute(
                "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                "iv_stamina,gender,shiny,origin,content_version,caught_at) "
                "VALUES ('m','old',25,20,1,2,3,'female',1,'catch','test',5)")
            before = {table: [dict(row) for row in await old.execute_fetchall(f'SELECT * FROM {table}')]
                      for table in ('guilds', 'profiles', 'pokemon')}
        finally:
            await old.close()
        for _ in range(2):
            upgraded = await db.open_db(path)
            try:
                after = {table: [dict(row) for row in await upgraded.execute_fetchall(
                    f'SELECT * FROM {table}')] for table in before}
                self.assertEqual(after['guilds'][0].pop('arena_enabled'), 1)
                self.assertEqual(after['profiles'][0].pop('arena_best_floor'), 0)
                self.assertEqual(after['profiles'][0].pop('arena_stop_pct'), 50)
                self.assertEqual(after['profiles'][0].pop('arena_auto_order'), 0)
                self.assertEqual(after, before)
                self.assertEqual(await self.scalar('PRAGMA user_version', conn=upgraded), 27)
                self.assertEqual(await upgraded.execute_fetchall('PRAGMA foreign_key_check'), [])
                for table in ('arena_runs', 'arena_tickets'):
                    self.assertEqual(await self.scalar(f'SELECT count(*) FROM {table}', conn=upgraded), 0)
                indexes = {row['name'] for row in await upgraded.execute_fetchall(
                    'PRAGMA index_list(arena_runs)')}
                self.assertTrue({'arena_runs_live', 'arena_runs_profile'} <= indexes)
                self.assertEqual([row['name'] for row in await upgraded.execute_fetchall(
                    'PRAGMA index_info(arena_runs_profile)')], ['profile_id', 'started_at'])
            finally:
                await upgraded.close()
        with patch.object(db, 'MIGRATIONS', prior):
            with self.assertRaisesRegex(RuntimeError, 'schema is newer'):
                await db.open_db(path)

    async def test_migration_0026_adds_settings_preserving_rows(self):
        prior = Path(self.temp.name) / 'schema25'
        prior.mkdir()
        for migration in db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'):
            if int(migration.name[:4]) <= 25:
                shutil.copyfile(migration, prior / migration.name)
        path = Path(self.temp.name) / 'schema25.sqlite3'
        with patch.object(db, 'MIGRATIONS', prior):
            old = await db.open_db(path)
        try:
            self.assertEqual(await self.scalar('PRAGMA user_version', conn=old), 25)
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('old-g')")
            await old.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,stardust,arena_best_floor) "
                              "VALUES ('old','old-g','u',10,1234,60)")
            await old.execute("INSERT INTO arena_runs(run_id,profile_id,started_at,floor,slot,team,enemy) "
                              "VALUES ('old-run','old',100,7,2,?,?)",
                              (json.dumps(self.team), json.dumps({'snapshot': {}, 'battle_hp': 40, 'special': False})))
            await old.execute("INSERT INTO arena_tickets VALUES ('old','silver',2)")
            before = {table: [dict(row) for row in await old.execute_fetchall(f'SELECT * FROM {table}')]
                      for table in ('guilds', 'profiles', 'arena_runs', 'arena_tickets')}
        finally:
            await old.close()
        for _ in range(2):
            upgraded = await db.open_db(path)
            try:
                after = {table: [dict(row) for row in await upgraded.execute_fetchall(f'SELECT * FROM {table}')]
                         for table in before}
                self.assertEqual(after['profiles'][0].pop('arena_stop_pct'), 50)
                self.assertEqual(after['profiles'][0].pop('arena_auto_order'), 0)
                self.assertEqual(after, before)
                self.assertEqual(await self.scalar('PRAGMA user_version', conn=upgraded), 27)
                self.assertEqual(await upgraded.execute_fetchall('PRAGMA foreign_key_check'), [])
            finally:
                await upgraded.close()
        with patch.object(db, 'MIGRATIONS', prior):
            with self.assertRaisesRegex(RuntimeError, 'schema is newer'):
                await db.open_db(path)

    async def test_migration_0027_adds_month_tables_preserving_rows(self):
        prior = Path(self.temp.name) / 'schema26'
        prior.mkdir()
        for migration in db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'):
            if int(migration.name[:4]) <= 26:
                shutil.copyfile(migration, prior / migration.name)
        path = Path(self.temp.name) / 'schema26.sqlite3'
        with patch.object(db, 'MIGRATIONS', prior):
            old = await db.open_db(path)
        try:
            self.assertEqual(await self.scalar('PRAGMA user_version', conn=old), 26)
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('old-g')")
            await old.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,arena_best_floor,"
                              "arena_stop_pct,arena_auto_order) VALUES ('old','old-g','u',10,60,80,1)")
            await old.execute("INSERT INTO arena_runs(run_id,profile_id,started_at,floor,slot,team,enemy) "
                              "VALUES ('old-run','old',100,7,2,?,?)", (json.dumps(self.team), '{}'))
            await old.execute("INSERT INTO arena_tickets VALUES ('old','silver',2)")
            before = {table: [dict(row) for row in await old.execute_fetchall(f'SELECT * FROM {table}')]
                      for table in ('guilds', 'profiles', 'arena_runs', 'arena_tickets')}
        finally:
            await old.close()
        for _ in range(2):
            upgraded = await db.open_db(path)
            try:
                self.assertEqual(await self.scalar('PRAGMA user_version', conn=upgraded), 27)
                self.assertEqual({table: [dict(row) for row in await upgraded.execute_fetchall(
                    f'SELECT * FROM {table}')] for table in before}, before)
                for table in ('arena_month_scores', 'arena_months', 'arena_month_places'):
                    self.assertEqual(await self.scalar(f'SELECT count(*) FROM {table}', conn=upgraded), 0)
                self.assertEqual(await upgraded.execute_fetchall('PRAGMA foreign_key_check'), [])
                self.assertEqual([row['name'] for row in await upgraded.execute_fetchall(
                    'PRAGMA index_info(arena_month_scores_guild_month)')], ['guild_id', 'month'])
            finally:
                await upgraded.close()
        with patch.object(db, 'MIGRATIONS', prior):
            with self.assertRaisesRegex(RuntimeError, 'schema is newer'):
                await db.open_db(path)

    async def test_month_tables_reject_bad_rows(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('other-g')")
        valid = {
            'arena_month_scores': dict(guild_id='g', month='2026-11', profile_id=self.pid, floor=1, reached_at=1.5),
            'arena_months': dict(guild_id='g', month='2026-11', settled_at=2.5),
            'arena_month_places': dict(guild_id='g', month='2026-11', place=1, profile_id=self.pid, floor=1),
        }
        for table, row in valid.items():
            invalid = [dict(month=month) for month in ('bad', '2026-1', '2026-00', '2026-13', '2026-11x', None)]
            invalid += [dict(guild_id='missing'), dict(guild_id=None)]
            for column in ('floor', 'place'):
                if column in row:
                    invalid += [{column: value} for value in (0, -1, 1.5, 'bad', None)]
            if 'profile_id' in row:
                invalid += [dict(profile_id='missing'), dict(profile_id=None), dict(guild_id='other-g')]
            if 'settled_at' in row:
                invalid += [dict(settled_at=None)]
            if 'reached_at' in row:
                invalid += [dict(reached_at=None)]
            for changes in invalid:
                bad = {**row, **changes}
                with self.subTest(table=table, changes=changes), self.assertRaises(sqlite3.IntegrityError):
                    await self.conn.execute(f"INSERT INTO {table}({','.join(bad)}) "
                                            f"VALUES ({','.join('?' for _ in bad)})", tuple(bad.values()))
            await self.conn.execute(f"INSERT INTO {table}({','.join(row)}) "
                                    f"VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
            with self.subTest(duplicate=table), self.assertRaises(sqlite3.IntegrityError):
                await self.conn.execute(f"INSERT INTO {table}({','.join(row)}) "
                                        f"VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("INSERT INTO arena_month_places VALUES ('g','2026-11',2,?,3)", (self.pid,))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("INSERT INTO arena_month_places VALUES ('g','2026-11',1,?,3)", (self.other,))

    async def test_profile_delete_cascades_scores_places_guild_delete_months(self):
        for place, pid in enumerate((self.pid, self.other), 1):
            await self.conn.execute("INSERT INTO arena_month_scores VALUES ('g','2026-11',?,10,100)", (pid,))
            await self.conn.execute("INSERT INTO arena_month_places VALUES ('g','2026-11',?,?,10)", (place, pid))
        await self.conn.execute("INSERT INTO arena_months VALUES ('g','2026-11',200)")
        await self.conn.execute('DELETE FROM profiles WHERE profile_id=?', (self.pid,))
        for table in ('arena_month_scores', 'arena_month_places'):
            self.assertEqual([row[0] for row in await self.conn.execute_fetchall(
                f'SELECT profile_id FROM {table}')], [self.other])
        self.assertEqual(await self.scalar('SELECT count(*) FROM arena_months'), 1)
        await self.conn.execute("DELETE FROM guilds WHERE guild_id='g'")
        for table in ('arena_month_scores', 'arena_month_places', 'arena_months'):
            self.assertEqual(await self.scalar(f'SELECT count(*) FROM {table}'), 0)
        self.assertEqual(await self.conn.execute_fetchall('PRAGMA foreign_key_check'), [])

    async def test_settings_checks_reject_bad_values(self):
        for column, values in (('arena_stop_pct', (55, 0, 100, None)),
                               ('arena_auto_order', (2, None))):
            for value in values:
                with self.subTest(column=column, value=value), self.assertRaises(sqlite3.IntegrityError):
                    await self.conn.execute(f'UPDATE profiles SET {column}=? WHERE profile_id=?', (value, self.pid))
        for value in range(10, 100, 10):
            await self.conn.execute('UPDATE profiles SET arena_stop_pct=? WHERE profile_id=?', (value, self.pid))
        for value in (0, 1):
            await self.conn.execute('UPDATE profiles SET arena_auto_order=? WHERE profile_id=?', (value, self.pid))

    async def test_one_live_run_per_profile(self):
        await self.run_row()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.run_row(run_id='duplicate')
        await self.run_row(run_id='other', profile_id=self.other)
        for reason in ('loss', 'draw', 'expired'):
            await self.conn.execute("UPDATE arena_runs SET ended_at=200,end_reason=? WHERE run_id='r'",
                                    (reason,))
        await self.run_row(run_id='next')
        self.assertEqual(await self.scalar('SELECT count(*) FROM arena_runs'), 3)
        self.assertEqual(await self.scalar("SELECT revision FROM arena_runs WHERE run_id='next'"), 0)

    async def test_run_and_ticket_checks_reject_bad_rows(self):
        for changes in ({'run_id': None}, {'profile_id': 'missing'}, {'profile_id': None},
                        {'started_at': None}, {'revision': None},
                        {'floor': 0}, {'floor': -1}, {'floor': 1.5}, {'floor': 'bad'}, {'floor': None},
                        {'slot': -1}, {'slot': 3}, {'slot': 0.5}, {'slot': None},
                        {'team': 'bad'}, {'enemy': 'bad'}, {'team': None}, {'enemy': None},
                        {'end_reason': 'loss'}, {'ended_at': 200},
                        {'ended_at': 200, 'end_reason': 'quit'}):
            with self.subTest(run=changes), self.assertRaises(sqlite3.IntegrityError):
                await self.run_row(**changes)
        for tier in ('bronze', 'silver', 'gold', 'platinum', 'diamond'):
            await self.conn.execute('INSERT INTO arena_tickets VALUES (?,?,0)', (self.pid, tier))
        for pid, tier, quantity in ((self.pid, 'invalid', 1), ('missing', 'bronze', 1),
                                    (None, 'bronze', 1), (self.other, None, 1),
                                    (self.other, 'bronze', -1), (self.other, 'bronze', 0.5),
                                    (self.other, 'bronze', 'bad'), (self.other, 'bronze', None),
                                    (self.pid, 'bronze', 1)):
            with self.subTest(ticket=(pid, tier, quantity)), self.assertRaises(sqlite3.IntegrityError):
                await self.conn.execute('INSERT INTO arena_tickets VALUES (?,?,?)', (pid, tier, quantity))
        for table, column, bad_values in (
                ('guilds', 'arena_enabled', (-1, 2, None)),
                ('profiles', 'arena_best_floor', (-1, 0.5, 'bad', None))):
            for value in bad_values:
                with self.subTest(column=column, value=value), self.assertRaises(sqlite3.IntegrityError):
                    await self.conn.execute(f'UPDATE {table} SET {column}=?', (value,))

    async def test_profile_delete_cascades_runs_and_tickets(self):
        await self.run_row(run_id='ended', ended_at=150, end_reason='draw')
        await self.run_row()
        await self.run_row(run_id='other', profile_id=self.other)
        for pid in (self.pid, self.other):
            await self.conn.execute("INSERT INTO arena_tickets VALUES (?,'bronze',2)", (pid,))
        await self.conn.execute('DELETE FROM profiles WHERE profile_id=?', (self.pid,))
        for table in ('arena_runs', 'arena_tickets'):
            self.assertEqual([row[0] for row in await self.conn.execute_fetchall(
                f'SELECT profile_id FROM {table}')], [self.other])
        self.assertEqual(await self.conn.execute_fetchall('PRAGMA foreign_key_check'), [])

    async def test_arena_team_live_until_hour_18_then_empty_without_any_write(self):
        await self.run_row()
        before = [dict(row) for row in await self.conn.execute_fetchall('SELECT * FROM arena_runs')]
        changes = self.conn.total_changes
        duration = load_table('arena')['rules']['run_seconds']
        reader = await db.open_reader(self.path)
        try:
            for now, expected in ((100, frozenset(('a', 'b', 'c'))),
                                  (100 + duration - 0.001, frozenset(('a', 'b', 'c'))),
                                  (100 + duration, frozenset()),
                                  (100 + duration + 1, frozenset())):
                with self.subTest(now=now):
                    result = await profiles.arena_team(reader, self.pid, now)
                    self.assertIsInstance(result, frozenset)
                    self.assertEqual(result, expected)
            with patch.object(profiles, 'load_table', return_value={'rules': {'run_seconds': 10}}):
                self.assertEqual(await profiles.arena_team(reader, self.pid, 110), frozenset())
            self.assertEqual(reader.total_changes, 0)
        finally:
            await reader.close()
        self.assertEqual(self.conn.total_changes, changes)
        self.assertEqual([dict(row) for row in await self.conn.execute_fetchall('SELECT * FROM arena_runs')],
                         before)

    async def test_arena_team_empty_after_run_ended_and_for_other_profile(self):
        self.assertEqual(await profiles.arena_team(self.conn, self.pid, 100), frozenset())
        await self.run_row()
        self.assertEqual(await profiles.arena_team(self.conn, self.other, 101), frozenset())
        await self.run_row(run_id='other', profile_id=self.other, team='[{"uid":"foreign"}]')
        self.assertEqual(await profiles.arena_team(self.conn, self.other, 101), frozenset(('foreign',)))
        for reason in ('loss', 'draw', 'expired'):
            await self.conn.execute("UPDATE arena_runs SET ended_at=101,end_reason=? WHERE run_id='r'",
                                    (reason,))
            self.assertEqual(await profiles.arena_team(self.conn, self.pid, 102), frozenset())


if __name__ == '__main__':
    unittest.main()
