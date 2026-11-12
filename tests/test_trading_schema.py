"""C3 trading schema (migration 0018) on real SQLite."""

from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from pokewalker import db
import test_db


class TradingSchemaTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_db.DatabaseTests.scalar
    profile = test_db.DatabaseTests.profile

    async def asyncSetUp(self):
        await test_db.DatabaseTests.asyncSetUp(self)
        self.pid = await self.profile('u', 'g')
        self.partner = await self.profile('v', 'g')
        self.foreign = await self.profile('w', 'h')
        await self.pokemon('mon')

    async def pokemon(self, uid, pid=None):
        await self.conn.execute(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,content_version,caught_at) "
            "VALUES (?,?,1,20,10,10,10,'male',0,'catch','test',0)", (uid, pid or self.pid))

    async def rows(self, sql, args=()):
        return [dict(row) for row in await self.conn.execute_fetchall(sql, args)]

    async def trade(self, trade_id='t', initiator=None, partner=None, guild='g'):
        await self.conn.execute(
            "INSERT INTO trades(trade_id,guild_id,initiator_profile_id,partner_profile_id,"
            "created_at,expires_at) VALUES (?,?,?,?,100,1000)",
            (trade_id, guild, initiator or self.pid, partner or self.partner))

    async def side(self, trade_id, side, profile_id, joined_at=None, open_=0, guild='g'):
        await self.conn.execute(
            "INSERT INTO trade_sides(trade_id,guild_id,side,profile_id,joined_at,open) "
            "VALUES (?,?,?,?,?,?)", (trade_id, guild, side, profile_id, joined_at, open_))

    async def pair(self, trade_id='t'):
        await self.trade(trade_id)
        await self.side(trade_id, 0, self.pid, 100, 1)
        await self.side(trade_id, 1, self.partner, 120, 1)

    async def move(self, uid='mon', to=None):
        await self.conn.execute("UPDATE pokemon SET profile_id=? WHERE pokemon_uid=?",
                                (to or self.partner, uid))

    async def refused_move(self, uid='mon', to=None):
        before = await self.rows("SELECT * FROM pokemon WHERE pokemon_uid=?", (uid,))
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'Pokemon is not tradable'):
            await self.move(uid, to)
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE pokemon_uid=?", (uid,)), before)

    async def test_migration_0018_adds_tables_columns_triggers_preserving_rows(self):
        prior = Path(self.temp.name) / 'prior'
        prior.mkdir()
        for migration in db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'):
            if int(migration.name[:4]) <= 17:
                shutil.copyfile(migration, prior / migration.name)
        path = Path(self.temp.name) / 'prior.sqlite3'
        with patch.object(db, 'MIGRATIONS', prior):
            old = await db.open_db(path)
        try:
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('g')")
            await old.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,stardust) "
                              "VALUES ('old','g','u',10,1234)")
            await old.execute(
                "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                "iv_stamina,gender,shiny,origin,content_version,caught_at,favorite) "
                "VALUES ('m','old',25,20,1,2,3,'female',1,'catch','test',5,1)")
            before = {table: [dict(row) for row in await old.execute_fetchall(f'SELECT * FROM {table}')]
                      for table in ('guilds', 'profiles', 'pokemon')}
        finally:
            await old.close()
        for _ in range(2):
            upgraded = await db.open_db(path)
            try:
                after = {table: [dict(row) for row in await upgraded.execute_fetchall(
                    f'SELECT * FROM {table}')] for table in ('guilds', 'profiles', 'pokemon')}
                profile = after['profiles'][0]
                self.assertEqual((profile.pop('last_trade_at', 'missing'),
                                  profile.pop('last_trade_ping_at', 'missing')), (None, None))
                self.assertEqual(after, before)
                names = {(row[0], row[1]) for row in await upgraded.execute_fetchall(
                    "SELECT type,name FROM sqlite_schema")}
                self.assertTrue({('table', 'trades'), ('table', 'trade_sides'),
                                 ('table', 'trade_channels'), ('index', 'trade_sides_one_open'),
                                 ('trigger', 'trade_close_sides'),
                                 ('trigger', 'pokemon_trade_guard')} <= names)
                for table in ('trades', 'trade_sides', 'trade_channels'):
                    self.assertEqual((await upgraded.execute_fetchall(
                        f'SELECT count(*) FROM {table}'))[0][0], 0)
                self.assertEqual((await upgraded.execute_fetchall('PRAGMA foreign_key_check')), [])
                self.assertEqual((await upgraded.execute_fetchall('PRAGMA user_version'))[0][0], 18)
            finally:
                await upgraded.close()

    async def test_trade_rejects_cross_guild_profiles_and_same_profile_twice(self):
        for initiator, partner in ((self.pid, self.foreign), (self.foreign, self.partner)):
            with self.assertRaises(sqlite3.IntegrityError):
                await self.trade('x', initiator, partner)
        await self.trade()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.side('t', 1, self.foreign)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.side('t', 0, self.pid, guild='h')
        await self.side('t', 0, self.pid, 100, 1)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.side('t', 1, self.pid)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.side('t', 0, self.partner)
        for bad in (2, -1):
            with self.assertRaises(sqlite3.IntegrityError):
                await self.side('t', bad, self.partner)
        await self.side('t', 1, self.partner)
        self.assertEqual(await self.rows("SELECT side,profile_id FROM trade_sides ORDER BY side"),
                         [{'side': 0, 'profile_id': self.pid}, {'side': 1, 'profile_id': self.partner}])
        self.assertEqual(await self.rows("SELECT state,revision,ended_at FROM trades"),
                         [{'state': 'open', 'revision': 0, 'ended_at': None}])
        for sql in ("UPDATE trades SET state='done'", "UPDATE trades SET expires_at=created_at"):
            with self.assertRaises(sqlite3.IntegrityError):
                await self.conn.execute(sql)

    async def test_one_open_side_per_profile_unjoined_sides_unlimited(self):
        third = await self.profile('x', 'g')
        await self.trade('a')
        await self.side('a', 0, self.pid, 100, 1)
        await self.trade('b', third, self.pid)
        await self.side('b', 0, third, 100, 1)
        await self.trade('c', self.partner, self.pid)
        await self.side('c', 0, self.partner, 100, 1)
        for trade_id in ('a', 'b', 'c'):
            await self.side(trade_id, 1, self.pid if trade_id != 'a' else self.partner)
        self.assertEqual(await self.scalar(
            "SELECT count(*) FROM trade_sides WHERE profile_id=? AND open=0", (self.pid,)), 2)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("UPDATE trade_sides SET joined_at=110,open=1 "
                                    "WHERE trade_id='b' AND side=1")
        await self.conn.execute("UPDATE trades SET state='cancelled' WHERE trade_id='a'")
        await self.conn.execute("UPDATE trade_sides SET joined_at=110,open=1 WHERE trade_id='b' AND side=1")
        self.assertEqual(await self.scalar(
            "SELECT trade_id FROM trade_sides WHERE profile_id=? AND open=1", (self.pid,)), 'b')

    async def test_open_requires_joined_at(self):
        await self.trade()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.side('t', 0, self.pid, None, 1)
        await self.side('t', 0, self.pid)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("UPDATE trade_sides SET open=1 WHERE side=0")
        await self.side('t', 1, self.partner, 120, 1)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("UPDATE trade_sides SET joined_at=NULL WHERE side=1")
        self.assertEqual(await self.rows("SELECT side,joined_at,open FROM trade_sides ORDER BY side"),
                         [{'side': 0, 'joined_at': None, 'open': 0},
                          {'side': 1, 'joined_at': 120, 'open': 1}])

    async def test_closing_trade_closes_both_sides(self):
        for trade_id, state in (('a', 'completed'), ('b', 'cancelled'), ('c', 'expired')):
            await self.pair(trade_id)
            await self.conn.execute("UPDATE trades SET revision=revision+1 WHERE trade_id=?", (trade_id,))
            self.assertEqual(await self.scalar(
                "SELECT sum(open) FROM trade_sides WHERE trade_id=?", (trade_id,)), 2)
            await self.conn.execute("UPDATE trades SET state=?,ended_at=500 WHERE trade_id=?",
                                    (state, trade_id))
            self.assertEqual(await self.scalar(
                "SELECT sum(open) FROM trade_sides WHERE trade_id=?", (trade_id,)), 0)
            self.assertEqual(await self.scalar(
                "SELECT count(*) FROM trade_sides WHERE trade_id=? AND joined_at IS NOT NULL",
                (trade_id,)), 2)

    async def test_profile_delete_cascades_trade_and_both_sides(self):
        for victim_side in (1, 0):
            await self.pair('t')
            await self.conn.execute("UPDATE trade_sides SET pokemon_uid='mon',pokemon_revision=0 "
                                    "WHERE side=0")
            victim, survivor = [await self.scalar(
                "SELECT profile_id FROM trade_sides WHERE side=?", (side,))
                for side in (victim_side, 1 - victim_side)]
            await self.conn.execute("DELETE FROM profiles WHERE profile_id=?", (victim,))
            self.assertEqual(await self.scalar("SELECT count(*) FROM trades"), 0)
            self.assertEqual(await self.scalar("SELECT count(*) FROM trade_sides"), 0)
            self.assertEqual(await self.scalar(
                "SELECT count(*) FROM profiles WHERE profile_id=?", (survivor,)), 1)
            self.partner = await self.profile(f'new{victim_side}', 'g')
        self.assertEqual(await self.scalar("SELECT count(*) FROM pokemon"), 0)

    async def test_trade_channels_cascade_with_guild(self):
        await self.conn.execute("INSERT INTO trade_channels(guild_id,channel_id) VALUES ('g','1'),('g','2'),"
                                "('h','1')")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("INSERT INTO trade_channels(guild_id,channel_id) VALUES ('g','1')")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("INSERT INTO trade_channels(guild_id,channel_id) VALUES ('none','1')")
        await self.pair()
        await self.conn.execute("DELETE FROM guilds WHERE guild_id='g'")
        self.assertEqual(await self.rows("SELECT * FROM trade_channels"),
                         [{'guild_id': 'h', 'channel_id': '1'}])
        self.assertEqual(await self.scalar("SELECT count(*) FROM trades"), 0)

    async def test_owner_change_rejected_for_favorite(self):
        await self.conn.execute("UPDATE pokemon SET favorite=1")
        await self.refused_move()
        await self.conn.execute("UPDATE pokemon SET profile_id=?,revision=revision+1", (self.pid,))
        self.assertEqual(await self.scalar("SELECT revision FROM pokemon"), 1)

    async def test_owner_change_rejected_for_gym_deployed(self):
        await self.conn.execute("INSERT INTO gyms(gym_id,guild_id,name,created_at) VALUES ('gym','g','Park',0)")
        await self.conn.execute(
            "INSERT INTO gym_deployments(deployment_id,guild_id,gym_id,profile_id,pokemon_uid,"
            "deployed_at,ends_at) VALUES ('d','g','gym',?,'mon',0,100)", (self.pid,))
        await self.conn.execute("UPDATE pokemon SET gym_deployment_id='d'")
        await self.refused_move()

    async def test_owner_change_rejected_for_companion(self):
        for holder in (self.pid, self.partner):
            await self.conn.execute("UPDATE profiles SET companion_uid=NULL")
            await self.conn.execute("UPDATE profiles SET companion_uid='mon' WHERE profile_id=?", (holder,))
            await self.refused_move()

    async def test_owner_change_rejected_for_sent(self):
        await self.conn.execute("UPDATE pokemon SET state='sent'")
        await self.refused_move()

    async def test_owner_change_rejected_across_guilds(self):
        await self.refused_move(to=self.foreign)

    async def test_owner_change_allowed_for_eligible_same_guild(self):
        await self.pokemon('back', self.partner)
        await self.move('mon', self.partner)
        await self.move('back', self.pid)
        self.assertEqual(await self.rows("SELECT pokemon_uid,profile_id FROM pokemon ORDER BY pokemon_uid"),
                         [{'pokemon_uid': 'back', 'profile_id': self.pid},
                          {'pokemon_uid': 'mon', 'profile_id': self.partner}])
        self.assertEqual(await self.rows('PRAGMA foreign_key_check'), [])


if __name__ == '__main__':
    unittest.main()
