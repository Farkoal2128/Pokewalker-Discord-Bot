"""C3 guild-scoped gym lifecycle on real SQLite writer transactions."""

import asyncio
import importlib
import json
from pathlib import Path
import random
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from content.balance import load_table
from pokewalker import db
from pokewalker.services import items, milestones
import test_db


class GymTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_db.DatabaseTests.scalar
    profile = test_db.DatabaseTests.profile

    async def asyncSetUp(self):
        await test_db.DatabaseTests.asyncSetUp(self)
        self.pid = await self.profile('u', 'g')
        self.other = await self.profile('v', 'h')
        self.content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        self.rng = random.Random(3)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.session = {'session_id': 's', 'profile_id': self.pid, 'guild_id': 'g', 'user_id': 'u'}
        await self.pokemon('mon')

    def gyms(self):
        try:
            return importlib.import_module('pokewalker.services.gyms')
        except ModuleNotFoundError:
            self.fail('Gym lifecycle service is absent')

    async def pokemon(self, uid, pokemon_id=1, pid=None):
        await self.conn.execute(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,content_version,caught_at) "
            "VALUES (?,?,?,20,10,10,10,'male',0,'catch','test',0)", (uid, pid or self.pid, pokemon_id))

    async def rows(self, sql, args=()):
        return [dict(row) for row in await self.conn.execute_fetchall(sql, args)]

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table}') for table in
                ('gyms', 'gym_deployments', 'gym_battles', 'pokemon', 'profiles', 'action_receipts',
                 'inbox_items', 'inventory', 'resource_ledger')}

    async def create(self, name='Park', guild='g', now=100):
        return await self.writer.run(lambda conn: self.gyms().create(conn, guild, name, now))

    async def deploy(self, gym, uid='mon', rev=0, now=1000, session=None):
        return await self.writer.run(lambda conn: self.gyms().deploy(
            conn, session or self.session, gym['gym_id'], uid, rev, now, content=self.content))

    async def test_schema_rejects_deployment_or_battle_across_guilds(self):
        tables = {row['name'] for row in await self.rows("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'gyms', 'gym_deployments', 'gym_battles'} <= tables,
                        'Gym tables must persist guild-scoped lifecycle and battle history')
        gym = await self.create()
        for guild, pid in [('h', self.other), ('g', self.other)]:
            with self.subTest(guild=guild, profile=pid):
                with self.assertRaises(sqlite3.IntegrityError):
                    await self.conn.execute(
                        'INSERT INTO gym_deployments(deployment_id,guild_id,gym_id,profile_id,pokemon_uid,'
                        'deployed_at,ends_at) VALUES (?,?,?,?,?,0,28800)',
                        ('bad', guild, gym['gym_id'], pid, 'mon'))
                with self.assertRaises(sqlite3.IntegrityError):
                    await self.conn.execute(
                        'INSERT INTO gym_battles(battle_id,guild_id,gym_id,challenger_profile_id,'
                        'outcome,reason,ticks,events,engine,created_at) VALUES (?,?,?,?,?,?,?,?,?,0)',
                        ('bad', guild, gym['gym_id'], pid, 'win', 'defender_fainted', 1, '[]', '1'))
        self.assertEqual(await self.rows('PRAGMA foreign_key_check'), [])

    async def test_create_up_to_10_unique_names_1_to_32(self):
        for name in ('', 'x' * 33):
            before = await self.snapshot()
            self.assertEqual(await self.create(name), {'status': 'invalid'})
            self.assertEqual(await self.snapshot(), before)
        first = await self.create('x')
        self.assertEqual(first['name'], 'x')
        self.assertEqual(await self.gyms().get_gym(self.conn, 'g', first['gym_id']), first)
        before = await self.snapshot()
        self.assertEqual(await self.create('x'), {'status': 'duplicate'})
        self.assertEqual(await self.snapshot(), before)
        await self.create('y' * 32)
        for i in range(8):
            await self.create(f'gym-{i}')
        self.assertEqual(len(await self.gyms().list_gyms(self.conn, 'g')), 10)
        before = await self.snapshot()
        self.assertEqual(await self.create('eleven'), {'status': 'full'})
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.create('x', 'h'))['name'], 'x')

    async def test_deploy_refuses_companion_legendary_second_gym_deployed(self):
        gym = await self.create()
        await self.conn.execute('UPDATE profiles SET companion_uid=? WHERE profile_id=?', ('mon', self.pid))
        before = await self.snapshot()
        self.assertEqual((await self.deploy(gym))['status'], 'companion')
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('UPDATE profiles SET companion_uid=NULL WHERE profile_id=?', (self.pid,))
        for key in ('is_legendary', 'is_mythical'):
            identity = next(item for item in self.content['identities'] if item[key])
            await self.conn.execute('UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid=?',
                                    (identity['pokemon_id'], 'mon'))
            before = await self.snapshot()
            self.assertEqual((await self.deploy(gym))['status'], 'legendary_or_mythical')
            self.assertEqual(await self.snapshot(), before)
        await self.conn.execute("UPDATE pokemon SET pokemon_id=1 WHERE pokemon_uid='mon'")
        result = await self.deploy(gym)
        self.assertEqual(result['status'], 'deployed')
        dep = result['deployment']
        self.assertEqual((dep['guild_id'], dep['profile_id'], dep['ends_at']), ('g', self.pid, 29800))
        self.assertEqual(await self.scalar("SELECT gym_deployment_id FROM pokemon WHERE pokemon_uid='mon'"),
                         dep['deployment_id'])
        await self.pokemon('second')
        second_gym = await self.create('Other')
        before = await self.snapshot()
        self.assertEqual((await self.deploy(second_gym, 'second', session={**self.session, 'session_id': 'second'}))['status'], 'occupied')
        self.assertEqual(await self.snapshot(), before)
        pid = await self.profile('other', 'g')
        await self.pokemon('other', pid=pid)
        session = {**self.session, 'session_id': 'other', 'profile_id': pid, 'user_id': 'other'}
        before = await self.snapshot()
        self.assertEqual((await self.deploy(gym, 'other', session=session))['status'], 'occupied')
        self.assertEqual(await self.snapshot(), before)

    async def test_gym_removed_between_preview_and_confirm_deploy_stale_nothing_written(self):
        for delete in (False, True):
            gym = await self.create(f'Park-{delete}')
            if delete:
                await self.conn.execute('DELETE FROM gyms WHERE gym_id=? AND guild_id=?', (gym['gym_id'], 'g'))
            else:
                await self.writer.run(lambda conn: self.gyms().retire(
                    conn, 'g', gym['gym_id'], 500, self.rng, self.content))
            before = await self.snapshot()
            self.assertEqual(await self.deploy(gym), {'status': 'stale'})
            self.assertEqual(await self.snapshot(), before)

    async def test_foreign_guild_gym_deploy_retire_end_refused_nothing_written(self):
        gym = await self.create(guild='h')
        before = await self.snapshot()
        self.assertIsNone(await self.gyms().get_gym(self.conn, 'g', gym['gym_id']))
        self.assertEqual(await self.deploy(gym), {'status': 'stale'})
        self.assertEqual(await self.writer.run(lambda conn: self.gyms().retire(
            conn, 'g', gym['gym_id'], 1000, self.rng, self.content)), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)
        await self.pokemon('foreign', pid=self.other)
        foreign = {**self.session, 'session_id': 'foreign', 'guild_id': 'h',
                   'user_id': 'v', 'profile_id': self.other}
        dep = (await self.deploy(gym, 'foreign', session=foreign))['deployment']
        before = await self.snapshot()
        self.assertEqual(await self.writer.run(lambda conn: self.gyms().end_deployment(
            conn, 'g', dep['deployment_id'], 'recalled', 2000, self.rng, self.content)), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)

    async def test_settle_after_restart_no_tenure_extension(self):
        gym = await self.create()
        dep = (await self.deploy(gym))['deployment']
        await self.writer.close()
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        await self.writer.run(lambda conn: self.gyms().settle(conn, dep['ends_at'] - 1, self.rng, self.content))
        self.assertIsNone(await self.scalar('SELECT ended_at FROM gym_deployments'))
        await self.writer.run(lambda conn: self.gyms().settle(conn, dep['ends_at'], self.rng, self.content))
        ended = (await self.rows('SELECT * FROM gym_deployments'))[0]
        self.assertEqual((ended['ends_at'], ended['ended_at'], ended['end_reason']),
                         (dep['ends_at'], dep['ends_at'], 'expired'))
        self.assertIsNone(await self.scalar('SELECT gym_deployment_id FROM pokemon'))
        before = await self.snapshot()
        await self.writer.run(lambda conn: self.gyms().settle(conn, dep['ends_at'] + 1000, self.rng, self.content))
        self.assertEqual(await self.snapshot(), before)

    async def test_triggers_block_send_powerup_evolve_companion_while_deployed(self):
        gym = await self.create()
        await self.deploy(gym)
        for sql in ("UPDATE pokemon SET state='sent'", 'UPDATE pokemon SET level_x2=21',
                    'UPDATE pokemon SET pokemon_id=2',
                    "UPDATE profiles SET companion_uid='mon' WHERE profile_id=?"):
            with self.subTest(sql=sql):
                before = await self.snapshot()
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'deployed'):
                    await self.writer.run(lambda conn: conn.execute(sql, (self.pid,) if '?' in sql else ()))
                self.assertEqual(await self.snapshot(), before)

    async def test_trigger_still_aborts_direct_level_update(self):
        await self.deploy(await self.create())
        before = await self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'deployed'):
            await self.writer.run(lambda conn: conn.execute('UPDATE pokemon SET level_x2=level_x2+1'))
        self.assertEqual(await self.snapshot(), before)

    async def test_profile_delete_cascades_deployment(self):
        gym = await self.create()
        await self.deploy(gym)
        await self.conn.execute('DELETE FROM profiles WHERE profile_id=?', (self.pid,))
        self.assertEqual(await self.rows('SELECT * FROM gym_deployments'), [])
        self.assertEqual(await self.rows('SELECT * FROM pokemon'), [])
        self.assertEqual(await self.rows('SELECT * FROM action_receipts'), [])
        self.assertEqual(await self.rows('PRAGMA foreign_key_check'), [])
        self.assertIsNotNone(await self.gyms().get_gym(self.conn, 'g', gym['gym_id']))

    async def test_deploy_replay_after_commit_returns_saved(self):
        gym = await self.create()
        result = await self.deploy(gym)
        await self.writer.run(lambda conn: self.gyms().retire(
            conn, 'g', gym['gym_id'], 2000, self.rng, self.content))
        before = await self.snapshot()
        self.assertEqual(await self.deploy(gym, now=3000), result)
        self.assertEqual(await self.snapshot(), before)
        receipt = (await self.rows('SELECT * FROM action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']),
                         (f"deploy:s:{gym['gym_id']}:mon:0", 'deploy', self.pid))
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
        before = await self.snapshot()
        self.assertEqual(await self.deploy(gym), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_deploy_intents_replay_across_restart_without_target_collision(self):
        gym = await self.create()
        second_gym = await self.create('Other')
        await self.pokemon('second')
        first = await self.deploy(gym)
        await self.writer.run(lambda conn: self.gyms().end_deployment(
            conn, 'g', first['deployment']['deployment_id'], 'recalled', 1000, self.rng, self.content))
        await self.writer.close()
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        before = await self.snapshot()
        self.assertEqual(await self.deploy(gym), first)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.deploy(second_gym), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)
        second = await self.deploy(second_gym, 'second')
        self.assertEqual(second['deployment']['pokemon_uid'], 'second')
        self.assertEqual(second['deployment']['gym_id'], second_gym['gym_id'])
        before = await self.snapshot()
        self.assertEqual(await self.deploy(second_gym, 'second', now=2000), second)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_deployments'), 2)

    async def test_deploy_intent_receipt_and_state_rollback_together(self):
        gym = await self.create()
        before = await self.snapshot()

        async def interrupted(conn):
            self.assertEqual((await self.gyms().deploy(
                conn, self.session, gym['gym_id'], 'mon', 0, 1000, self.content))['status'], 'deployed')
            raise RuntimeError('interrupted transaction')

        with self.assertRaisesRegex(RuntimeError, 'interrupted transaction'):
            await self.writer.run(interrupted)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.deploy(gym))['status'], 'deployed')
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_deployments'), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts WHERE action='deploy'"), 1)

    async def test_deploy_owner_revision_and_unique_indexes(self):
        gym = await self.create()
        for session, uid, rev in [({**self.session, 'profile_id': self.other}, 'mon', 0),
                                  (self.session, 'missing', 0), (self.session, 'mon', 1)]:
            before = await self.snapshot()
            self.assertEqual(await self.deploy(gym, uid, rev, session=session), {'status': 'stale'})
            self.assertEqual(await self.snapshot(), before)
        dep = (await self.deploy(gym))['deployment']
        second = await self.create('second')
        pid = await self.profile('second', 'g')
        await self.pokemon('second', pid=pid)
        for field, changes in (
            ('gym_id', {'profile_id': pid, 'pokemon_uid': 'second'}),
            ('profile_id', {'gym_id': second['gym_id'], 'pokemon_uid': 'second'}),
            ('pokemon_uid', {'gym_id': second['gym_id'], 'profile_id': pid}),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(sqlite3.IntegrityError, field):
                row = {**dep, 'deployment_id': 'duplicate', **changes}
                columns = ','.join(row)
                await self.conn.execute(f"INSERT INTO gym_deployments({columns}) VALUES ({','.join('?' for _ in row)})",
                                        tuple(row.values()))
        await self.writer.run(lambda conn: self.gyms().end_deployment(
            conn, 'g', dep['deployment_id'], 'recalled', 2000, self.rng, self.content))
        row = {**dep, 'deployment_id': 'after-return'}
        await self.conn.execute(f"INSERT INTO gym_deployments({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                                tuple(row.values()))
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_deployments WHERE ended_at IS NULL'), 1)

    async def test_retire_ends_deployment_and_repeated_end_is_immutable(self):
        gym = await self.create()
        dep = (await self.deploy(gym))['deployment']
        await self.writer.run(lambda conn: self.gyms().retire(
            conn, 'g', gym['gym_id'], 2000, self.rng, self.content))
        self.assertEqual(await self.scalar('SELECT end_reason FROM gym_deployments'), 'retired')
        self.assertEqual(await self.gyms().list_gyms(self.conn, 'g'), [])
        before = await self.snapshot()
        await self.writer.run(lambda conn: self.gyms().end_deployment(
            conn, 'g', dep['deployment_id'], 'expired', 30000, self.rng, self.content))
        self.assertEqual(await self.snapshot(), before)

    async def test_deploy_uses_configured_content_and_receipt_owner(self):
        gym = await self.create()
        identity = next(item for item in self.content['identities'] if item['pokemon_id'] == 1)
        identity['is_legendary'] = True
        before = await self.snapshot()
        self.assertEqual(await self.deploy(gym), {'status': 'legendary_or_mythical'})
        self.assertEqual(await self.snapshot(), before)
        identity['is_legendary'] = False
        await self.deploy(gym)
        pid = await self.profile('second', 'g')
        await self.pokemon('second', pid=pid)
        session = {**self.session, 'profile_id': pid, 'user_id': 'second'}
        before = await self.snapshot()
        self.assertEqual(await self.deploy(gym, session=session), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)

    async def test_upgrade_from_13_preserves_pokemon_and_profile_applies_once(self):
        prior = Path(self.temp.name) / 'prior'
        prior.mkdir()
        for migration in db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'):
            if int(migration.name[:4]) <= 13:
                shutil.copyfile(migration, prior / migration.name)
        path = Path(self.temp.name) / 'prior.sqlite3'
        with patch.object(db, 'MIGRATIONS', prior):
            old = await db.open_db(path)
        try:
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('old')")
            await old.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('p','old','u',10)")
            await old.execute("INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                              "iv_stamina,gender,shiny,origin,content_version,caught_at) "
                              "VALUES ('p','p',1,20,10,10,10,'male',0,'catch','version',20)")
            before = {table: dict((await old.execute_fetchall(f'SELECT * FROM {table}'))[0])
                      for table in ('profiles', 'pokemon')}
        finally:
            await old.close()
        for _ in range(2):
            upgraded = await db.open_db(path)
            try:
                for table, column in [('profiles', 'last_battle_at'), ('pokemon', 'gym_deployment_id')]:
                    after = dict((await upgraded.execute_fetchall(f'SELECT * FROM {table}'))[0])
                    self.assertIsNone(after[column])
                    self.assertEqual({key: after[key] for key in before[table]}, before[table])
                    if table == 'pokemon':
                        self.assertIsNone(after['form_id'])
                self.assertEqual((await upgraded.execute_fetchall('PRAGMA user_version'))[0][0],
                                 len(list(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))))
                self.assertEqual(await upgraded.execute_fetchall('PRAGMA foreign_key_check'), [])
            finally:
                await upgraded.close()

    async def income_deployment(self):
        return (await self.deploy(await self.create()))['deployment']

    def income_rng(self, item='poke_ball'):
        row = next(row for row in load_table('gym_income_table')['rows'] if row['item'] == item)
        return Mock(choices=Mock(return_value=[row]), choice=Mock(side_effect=lambda kinds: kinds[0]))

    async def pay(self, dep, hours, rng=None, guild='g'):
        return await self.writer.run(lambda conn: self.gyms().pay_hours(
            conn, guild, dep['deployment_id'], dep['deployed_at'] + hours * 3600,
            rng or self.rng, self.content))

    async def end(self, dep, reason, hours, rng=None):
        return await self.writer.run(lambda conn: self.gyms().end_deployment(
            conn, 'g', dep['deployment_id'], reason, dep['deployed_at'] + hours * 3600,
            rng or self.rng, self.content))

    async def restart(self):
        await self.writer.close()
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)

    async def claim_income(self, revision=0):
        await self.conn.execute('INSERT OR IGNORE INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) '
                                "VALUES (?,'g','u',?,999999)", (self.session['session_id'], self.pid))
        return await self.writer.run(lambda conn: milestones.claim(
            conn, {**self.session, 'revision': revision}, 40000))

    async def test_pay_hours_one_receipt_and_one_inbox_row_per_hour_across_restart(self):
        dep = await self.income_deployment()
        rng = self.income_rng()
        await self.pay(dep, .99, rng)
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), [])
        await self.pay(dep, 2.5, rng)
        await self.restart()
        await self.pay(dep, 3, rng)
        await self.pay(dep, 2, rng)
        self.assertEqual(rng.choices.call_count, 3)
        receipts = await self.rows("SELECT key,action,profile_id FROM action_receipts WHERE action='gym_hour' ORDER BY key")
        self.assertEqual(receipts, [{'key': f"gym_hour:{dep['deployment_id']}:{n}", 'action': 'gym_hour',
                                     'profile_id': self.pid} for n in range(1, 4)])
        rows = await self.rows('SELECT milestone_id,resource,resource_id,remaining FROM inbox_items ORDER BY inbox_id')
        self.assertEqual(rows, [{'milestone_id': f"gym_income:{dep['deployment_id']}:{n}", 'resource': 'item',
                                'resource_id': 'poke_ball', 'remaining': 5} for n in range(1, 4)])
        self.assertEqual(await self.scalar('SELECT paid_hours FROM gym_deployments'), 3)
        self.assertEqual(await milestones.pending_count(self.conn, self.pid), 3)
        await self.pay(dep, 20, rng)
        self.assertEqual(await self.scalar('SELECT paid_hours FROM gym_deployments'), 8)
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 8)

    async def test_gym_income_goes_to_inbox_not_bag_and_claim_moves_it(self):
        dep = await self.income_deployment()
        with patch.object(items, 'grant', side_effect=AssertionError('Gym income must not grant')):
            await self.pay(dep, 1, self.income_rng())
        self.assertEqual(await self.rows('SELECT * FROM inventory'), [])
        self.assertEqual(await self.rows('SELECT * FROM resource_ledger'), [])
        result = await self.claim_income()
        self.assertEqual(result['moved'], {'item': 5, 'stardust': 0, 'candy': 0})
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='poke_ball'"), 5)
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), [])
        self.assertEqual(await self.scalar("SELECT delta FROM resource_ledger WHERE reason='milestone_claim'"), 5)

    async def test_gym_income_full_bag_and_held_master_ball_wait_never_convert(self):
        dep = await self.income_deployment()
        for item, amount in [('poke_ball', 250), ('master_ball', 1)]:
            await self.conn.execute('INSERT INTO inventory VALUES (?,?,?)', (self.pid, item, amount))
        await self.pay(dep, 1, self.income_rng())
        await self.pay(dep, 2, self.income_rng('master_ball'))
        before = await self.rows('SELECT * FROM inbox_items')
        result = await self.claim_income()
        self.assertEqual(result['moved'], {'item': 0, 'stardust': 0, 'candy': 0})
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), before)
        self.assertEqual(await self.scalar('SELECT stardust FROM profiles WHERE profile_id=?', (self.pid,)), 0)
        await self.conn.execute("UPDATE inventory SET quantity=248 WHERE item_id='poke_ball'")
        self.assertEqual((await self.claim_income(1))['moved']['item'], 2)
        self.assertEqual(await self.scalar("SELECT remaining FROM inbox_items WHERE resource_id='poke_ball'"), 3)
        self.assertEqual(await self.scalar("SELECT remaining FROM inbox_items WHERE resource_id='master_ball'"), 1)

    async def test_gym_hour_evolution_item_roll_inboxes_named_kind(self):
        dep = await self.income_deployment()
        await self.pay(dep, 1, self.income_rng('evolution_item'))
        self.assertEqual(await self.scalar('SELECT resource_id FROM inbox_items'), self.content['evolution_items'][0]['id'])
        self.assertEqual(await self.scalar('SELECT remaining FROM inbox_items'), 1)

    async def test_gym_hour_no_kinds_inboxes_100_stardust(self):
        dep = await self.income_deployment()
        self.content['evolution_items'] = []
        await self.pay(dep, 1, self.income_rng('evolution_item'))
        self.assertEqual(await self.rows('SELECT resource,resource_id,remaining FROM inbox_items'),
                         [{'resource': 'stardust', 'resource_id': None, 'remaining': 100}])
        self.assertEqual((await self.claim_income())['moved']['stardust'], 100)

    async def test_expired_undefeated_8_income_rows_one_survivor_500(self):
        dep = await self.income_deployment()
        await self.end(dep, 'expired', 10)
        self.assertEqual(await self.scalar("SELECT count(*) FROM inbox_items WHERE milestone_id LIKE 'gym_income:%'"), 8)
        survivor = await self.rows("SELECT resource,resource_id,remaining FROM inbox_items WHERE milestone_id=?",
                                   (f"survivor:{dep['deployment_id']}",))
        self.assertEqual(len(survivor), 2)
        self.assertIn({'resource': 'stardust', 'resource_id': None, 'remaining': 500}, survivor)
        self.assertEqual(await self.scalar('SELECT survivor_rolled FROM gym_deployments'), 1)
        self.assertIsNone(await self.scalar('SELECT gym_deployment_id FROM pokemon'))
        self.assertEqual(await self.scalar('SELECT revision FROM pokemon'), 2)

    async def test_survivor_roll_seeded_ticket_1_percent_second_waits(self):
        table = load_table('survivor_table')['rows']
        self.assertEqual(next(r['weight'] for r in table if r['item'] == 'world_legendary_ticket'), 100)
        self.assertEqual(sum(r['weight'] for r in table), 10000)
        for index in range(2):
            if index:
                self.session['session_id'] = 'second'
            dep = (await self.deploy(await self.create(f'Gym {index}'), rev=index * 2))['deployment']
            await self.pay(dep, 8, self.income_rng())
            await self.end(dep, 'expired', 8, random.Random(153))
            await self.claim_income(index)
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='world_legendary_ticket'"), 1)
        self.assertEqual(await self.scalar("SELECT remaining FROM inbox_items WHERE resource_id='world_legendary_ticket'"), 1)
        self.assertEqual(await self.scalar('SELECT stardust FROM profiles WHERE profile_id=?', (self.pid,)), 1000)

    async def test_interrupt_after_roll_saved_then_retry_one_roll_one_award_one_return(self):
        dep = await self.income_deployment()
        await self.pay(dep, 8, self.income_rng())
        rng = Mock(wraps=random.Random(153))
        commit = self.conn.commit

        async def lose_commit_ack():
            await commit()
            raise ConnectionError('Commit response lost')

        with patch.object(self.conn, 'commit', side_effect=lose_commit_ack):
            with self.assertRaisesRegex(ConnectionError, 'Commit response lost'):
                await self.end(dep, 'expired', 8, rng)
        before = await self.snapshot()
        await self.restart()
        await self.end(dep, 'expired', 9, rng)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(rng.choices.call_count, 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM inbox_items WHERE resource_id='world_legendary_ticket'"), 1)
        self.assertEqual(await self.scalar('SELECT revision FROM pokemon'), 2)

    async def test_retire_and_recall_pay_hours_no_survivor(self):
        for index, reason in enumerate(('retired', 'recalled', 'mod_recall', 'defeated')):
            self.session['session_id'] = str(index)
            gym = await self.create(str(index))
            dep = (await self.deploy(gym, rev=index * 2))['deployment']
            if reason == 'retired':
                await self.writer.run(lambda conn: self.gyms().retire(
                    conn, 'g', gym['gym_id'], dep['deployed_at'] + 2.5 * 3600, self.rng, self.content))
            else:
                await self.end(dep, reason, 2.5)
            self.assertEqual(await self.scalar('SELECT paid_hours FROM gym_deployments WHERE deployment_id=?',
                                              (dep['deployment_id'],)), 2)
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 8)
        self.assertEqual(await self.scalar('SELECT sum(survivor_rolled) FROM gym_deployments'), 0)

    async def test_excluded_end_forfeits_unpaid_hours(self):
        dep = await self.income_deployment()
        await self.pay(dep, 1)
        await self.end(dep, 'excluded', 3)
        self.assertEqual(await self.scalar('SELECT paid_hours FROM gym_deployments'), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 1)
        self.assertEqual(await self.scalar('SELECT survivor_rolled FROM gym_deployments'), 0)

    async def test_late_rewards_after_recall_at_hour_1_adds_nothing_at_hour_3(self):
        dep = await self.income_deployment()
        await self.end(dep, 'recalled', 1)
        before = await self.snapshot()
        await self.pay(dep, 3)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 1)

    async def test_repeated_end_is_no_op_no_second_income_or_survivor(self):
        dep = await self.income_deployment()
        await self.end(dep, 'expired', 8)
        before = await self.snapshot()
        await self.end(dep, 'expired', 20)
        self.assertEqual(await self.snapshot(), before)

    async def test_pay_hours_after_exclusion_recovers_nothing(self):
        dep = await self.income_deployment()
        await self.end(dep, 'excluded', 3)
        before = await self.snapshot()
        await self.pay(dep, 8)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), [])

    async def test_foreign_guild_pay_hours_refused(self):
        dep = await self.income_deployment()
        before = await self.snapshot()
        self.assertEqual(await self.pay(dep, 8, guild='h'), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)

    async def test_profile_delete_cascades_deployment_and_inbox_nothing_credited(self):
        dep = await self.income_deployment()
        await self.pay(dep, 1)
        await self.conn.execute('DELETE FROM profiles WHERE profile_id=?', (self.pid,))
        await self.writer.run(lambda conn: self.gyms().settle(conn, dep['ends_at'], self.rng, self.content))
        self.assertEqual(await self.rows('SELECT * FROM gym_deployments'), [])
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), [])
        self.assertEqual(await self.rows('SELECT * FROM inventory'), [])
        self.assertEqual(await self.rows('SELECT * FROM resource_ledger'), [])
        self.assertEqual(await self.rows('SELECT * FROM action_receipts'), [])
        self.assertEqual(await self.rows('PRAGMA foreign_key_check'), [])


    async def test_return_failure_rolls_back_hours_survivor_and_pokemon_together(self):
        dep = await self.income_deployment()
        before = await self.snapshot()
        await self.conn.execute("CREATE TRIGGER interrupt_gym_return BEFORE UPDATE OF gym_deployment_id ON pokemon "
                                "WHEN NEW.gym_deployment_id IS NULL BEGIN SELECT RAISE(ABORT,'return interrupted'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'return interrupted'):
            await self.end(dep, 'expired', 8)
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('DROP TRIGGER interrupt_gym_return')
        await self.end(dep, 'expired', 8)
        self.assertEqual(await self.scalar('SELECT paid_hours FROM gym_deployments'), 8)
        self.assertEqual(await self.scalar('SELECT survivor_rolled FROM gym_deployments'), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 10)
        self.assertEqual(await self.scalar('SELECT revision FROM pokemon'), 2)


    # C5 admin commands and process-owned settlement use the same real writer.
    def admin(self):
        from pokewalker.bot.admin_channels import WalkerAdmin
        bot = SimpleNamespace(writer=self.writer, content=self.content,
                              walker=SimpleNamespace(clock=lambda: 1000, rng=self.rng))
        self.admin_group = WalkerAdmin(bot)
        self.interaction = SimpleNamespace(
            guild_id='g', user=SimpleNamespace(id='u', guild_permissions=SimpleNamespace(manage_guild=True)),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=lambda: True),
            edit_original_response=AsyncMock())
        return self.admin_group

    async def admin_invoke(self, action, **kwargs):
        group = self.admin_group.get_command('gyms')
        self.assertIsNotNone(group, 'The gym administration command group is absent')
        command = group.get_command(action)
        await command.callback(command.binding, self.interaction, **kwargs)
        self.interaction.response.defer.assert_awaited_with(ephemeral=True)
        response = self.interaction.edit_original_response.await_args.kwargs
        self.assertEqual(response['allowed_mentions'].to_dict()['parse'], [])
        self.assertLessEqual(len(response['content']), 2000)
        return response['content']

    async def test_gyms_create_remove_list_audited_manage_server_only(self):
        group = self.admin()
        self.assertTrue(group.guild_only)
        self.assertTrue(group.default_permissions.manage_guild)
        await self.admin_invoke('create', name='Park', reason='  New gym  ')
        self.assertEqual(await self.scalar('SELECT created_at FROM gyms'), 1000)
        text = await self.admin_invoke('list')
        self.assertIn('Park', text)
        self.assertNotIn('embed', self.interaction.edit_original_response.await_args.kwargs)
        self.assertEqual(await self.scalar('SELECT count(*) FROM mod_audit'), 1)
        await self.admin_invoke('remove', name='Park', reason='Retire gym')
        self.assertEqual(await self.scalar('SELECT retired_at FROM gyms'), 1000)
        audit = await self.rows('SELECT guild_id,actor_id,target_kind,target_id,action,reason,created_at FROM mod_audit')
        self.assertEqual(audit, [dict(guild_id='g', actor_id='u', target_kind='guild', target_id='g',
            action='gym_create:Park', reason='New gym', created_at=1000),
            dict(guild_id='g', actor_id='u', target_kind='guild', target_id='g',
            action='gym_remove:Park', reason='Retire gym', created_at=1000)])
        self.interaction.user.guild_permissions.manage_guild = False
        for name, args in [('create', {'name': 'Other', 'reason': 'test'}),
                           ('remove', {'name': 'Park', 'reason': 'test'}), ('list', {})]:
            self.assertIn('Manage Server', await self.admin_invoke(name, **args))
        self.interaction.guild_id = None
        self.assertIn('server', (await self.admin_invoke('list')).lower())
        self.assertEqual(await self.scalar('SELECT count(*) FROM mod_audit'), 2)

    async def test_gyms_create_eleventh_refused(self):
        self.admin()
        for i in range(10):
            await self.admin_invoke('create', name=f'Gym {i}', reason='setup')
        text = await self.admin_invoke('create', name='Eleventh', reason='setup')
        self.assertIn('10', text)
        self.assertEqual(await self.scalar('SELECT count(*) FROM gyms'), 10)
        self.assertEqual(await self.scalar('SELECT count(*) FROM mod_audit'), 10)
        for name in ('', 'x' * 33):
            self.assertIn('1 to 32', await self.admin_invoke('create', name=name, reason='invalid'))
        await self.admin_invoke('create', name='Gym 0', reason='duplicate')
        self.assertEqual(await self.scalar('SELECT count(*) FROM mod_audit'), 10)

    async def test_gyms_names_are_stripped_and_blank_refused(self):
        self.admin()
        self.assertIn('1 to 32', await self.admin_invoke('create', name=' ' * 32, reason='blank'))
        await self.admin_invoke('create', name='  Park ', reason='setup')
        self.assertEqual(await self.scalar('SELECT name FROM gyms'), 'Park')
        await self.admin_invoke('create', name='Park', reason='duplicate')
        self.assertEqual(await self.scalar('SELECT count(*) FROM gyms'), 1)
        await self.admin_invoke('remove', name=' Park  ', reason='retire')
        self.assertIsNotNone(await self.scalar('SELECT retired_at FROM gyms'))

    async def test_gyms_remove_pays_hours_no_survivor(self):
        gym = await self.create()
        dep = (await self.deploy(gym))['deployment']
        group = self.admin()
        group.bot.walker.clock = lambda: dep['deployed_at'] + 2.5 * 3600
        await self.admin_invoke('remove', name='Park', reason='retiring')
        row = (await self.rows('SELECT * FROM gym_deployments'))[0]
        self.assertEqual((row['end_reason'], row['paid_hours'], row['survivor_rolled']), ('retired', 2, 0))
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 2)
        self.assertIsNone(await self.scalar('SELECT gym_deployment_id FROM pokemon'))

    async def test_gyms_remove_same_name_in_other_guild_untouched(self):
        await self.create('Park')
        foreign = await self.create('Park', 'h')
        self.admin()
        await self.admin_invoke('remove', name='Park', reason='local only')
        self.assertIsNone((await self.gyms().get_gym(self.conn, 'h', foreign['gym_id']))['retired_at'])
        first = await self.admin_invoke('remove', name='Park', reason='already removed')
        second = await self.admin_invoke('remove', name='Missing', reason='missing')
        self.assertEqual(first, second)
        self.assertEqual(await self.scalar('SELECT count(*) FROM mod_audit'), 1)

    async def test_whitespace_reason_refused(self):
        await self.create()
        self.admin()
        before = await self.snapshot()
        for action in ('create', 'remove'):
            self.assertIn('reason', (await self.admin_invoke(action, name='Park', reason=' \t ')).lower())
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.rows('SELECT * FROM mod_audit'), [])

    async def test_excluded_admin_refused_inside_transaction(self):
        await self.create()
        group = self.admin()
        original = group.authorize
        async def exclude_after_entry(interaction):
            allowed = await original(interaction)
            await self.writer.run(lambda conn: conn.execute(
                "INSERT OR REPLACE INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)"))
            return allowed
        for action, args in [('create', {'name': 'New', 'reason': 'test'}),
                             ('remove', {'name': 'Park', 'reason': 'test'}), ('list', {})]:
            await self.conn.execute('DELETE FROM restrictions')
            before = await self.snapshot()
            with patch.object(group, 'authorize', side_effect=exclude_after_entry):
                self.assertIn('excluded', (await self.admin_invoke(action, **args)).lower())
            self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.rows('SELECT * FROM mod_audit'), [])

    async def test_gym_admin_audit_failure_rolls_back_mutation(self):
        self.admin()
        await self.conn.execute("CREATE TRIGGER fail_gym_audit BEFORE INSERT ON mod_audit "
                                "BEGIN SELECT RAISE(ABORT,'audit failed'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'audit failed'):
            await self.admin_invoke('create', name='Park', reason='must roll back')
        self.assertEqual(await self.rows('SELECT * FROM gyms'), [])
        self.interaction.edit_original_response.assert_not_awaited()

    def sweep_bot(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(SimpleNamespace(), clock=lambda: 5.0)
        bot.writer, bot.content = self.writer, self.content
        bot.walker.rng = self.rng
        self.addAsyncCleanup(bot.drain)
        return bot

    async def test_sweep_settles_expired_deployment_within_one_tick(self):
        gym = await self.create()
        dep = (await self.deploy(gym))['deployment']
        bot = self.sweep_bot()
        bot.walker.clock = lambda: dep['ends_at']
        self.assertTrue(hasattr(bot, '_sweep_once'), 'Gym settlement tick is absent')
        await bot._sweep_once()
        self.assertEqual(await self.scalar('SELECT end_reason FROM gym_deployments'), 'expired')
        self.assertEqual(await self.scalar('SELECT paid_hours FROM gym_deployments'), 8)
        self.assertEqual(await self.scalar('SELECT survivor_rolled FROM gym_deployments'), 1)

    async def test_sweep_deletes_sessions_expired_over_a_day(self):
        now = 1_800_000_000
        for sid, expires in [('old', now - 86400), ('grace', now - 86399), ('live', now + 900)]:
            await self.conn.execute('INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) '
                                    "VALUES (?,'g','u',?,?)", (sid, self.pid, expires))
        bot = self.sweep_bot()
        bot.walker.clock = lambda: now
        await bot._sweep_once()
        self.assertEqual([row['session_id'] for row in await self.rows(
            'SELECT session_id FROM sessions ORDER BY session_id')], ['grace', 'live'])

    async def test_sweep_uses_walker_utc_clock_not_bot_monotonic(self):
        gym = await self.create()
        utc = 1_800_000_000
        dep = (await self.deploy(gym, now=utc))['deployment']
        bot = self.sweep_bot()
        bot.walker.clock = lambda: utc + 8 * 3600
        self.assertEqual(bot.clock(), 5.0)
        self.assertTrue(hasattr(bot, '_sweep_once'), 'Gym settlement tick is absent')
        await bot._sweep_once()
        self.assertEqual(await self.scalar('SELECT ended_at FROM gym_deployments'), dep['ends_at'])

    async def test_sweep_error_logged_loop_continues(self):
        bot = self.sweep_bot()
        self.assertTrue(hasattr(bot, '_gym_sweep'), 'Gym sweep lifecycle is absent')
        second_tick, sleeping = asyncio.Event(), asyncio.Event()
        calls = []
        async def tick():
            calls.append('tick')
            if len(calls) == 1:
                raise RuntimeError('synthetic sweep failure')
            second_tick.set()
        async def sleep(seconds):
            self.assertEqual(seconds, 60)
            if len(calls) > 1:
                sleeping.set()
                await asyncio.Future()
        with patch.object(bot, '_sweep_once', side_effect=tick), \
             patch('pokewalker.bot.client.asyncio.sleep', side_effect=sleep), \
             patch.object(bot.heartbeat, 'start'), \
             self.assertLogs('pokewalker.bot.client', level='ERROR') as logs:
            await bot.on_ready()
            task = bot._gym_sweep
            await bot.on_ready()
            self.assertIs(bot._gym_sweep, task)
            await asyncio.wait_for(second_tick.wait(), 1)
            await asyncio.wait_for(sleeping.wait(), 1)
            await bot.drain()
        self.assertEqual(calls, ['tick', 'tick'])
        self.assertIn('sweep', ' '.join(logs.output).lower())

    async def test_sweep_stops_on_drain_before_writer_close(self):
        bot = self.sweep_bot()
        self.assertTrue(hasattr(bot, '_gym_sweep'), 'Gym sweep lifecycle is absent')
        entered, stopped = asyncio.Event(), asyncio.Event()
        async def tick():
            entered.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()
        close = self.writer.close
        async def close_after_sweep():
            self.assertTrue(stopped.is_set())
            await close()
        with patch.object(bot, '_sweep_once', side_effect=tick), \
             patch.object(bot.heartbeat, 'start'), \
             patch.object(self.writer, 'close', side_effect=close_after_sweep):
            await bot.on_ready()
            task = bot._gym_sweep
            await asyncio.wait_for(entered.wait(), 1)
            await bot.drain()
            self.assertTrue(task.done())
            self.assertTrue(task.cancelled())
            await bot.on_ready()
            self.assertIs(bot._gym_sweep, task)
