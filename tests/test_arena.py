"""C3 Arena lifecycle: real SQLite transactions, frozen snapshots and berry debits."""

import asyncio
import importlib
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from content.balance import load_table
from pokewalker import db
from pokewalker.domain import arena as domain
from pokewalker.services import gyms, powerup, profiles, storage
import test_db


CONTENT = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
MULTIPLIERS = load_table('cpm')['multipliers']
RULES = load_table('arena')['rules']


class ArenaTests(unittest.IsolatedAsyncioTestCase):
    profile = test_db.DatabaseTests.profile
    scalar = test_db.DatabaseTests.scalar

    async def asyncSetUp(self):
        await test_db.DatabaseTests.asyncSetUp(self)
        self.pid = await self.profile('u', 'g')
        self.other = await self.profile('v', 'g')
        self.session = {'session_id': 's', 'profile_id': self.pid, 'guild_id': 'g',
                        'user_id': 'u', 'revision': 5, '_original_revision': 4}
        await self.conn.execute('INSERT INTO sessions(session_id,guild_id,user_id,profile_id,revision,expires_at) '
                                "VALUES ('s','g','u',?,5,1e12)", (self.pid,))
        self.team = [('m0', 0), ('m1', 0), ('m2', 0)]
        for uid, _ in self.team:
            await self.conn.execute(
                'INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,'
                'iv_stamina,gender,shiny,origin,content_version,caught_at) '
                "VALUES (?,?,1,20,10,10,10,'male',0,'catch','test',0)", (uid, self.pid))
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)

    def service(self):
        try:
            return importlib.import_module('pokewalker.services.arena')
        except ModuleNotFoundError:
            self.fail('Arena lifecycle service is absent')

    async def rows(self, sql, args=()):
        return [dict(row) for row in await self.conn.execute_fetchall(sql, args)]

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table} ORDER BY 1') for table in
                ('guilds', 'profiles', 'sessions', 'restrictions', 'pokemon', 'inventory',
                 'arena_runs', 'arena_tickets', 'action_receipts', 'resource_ledger')}

    async def state(self, now=1100, session=None):
        return await self.writer.run(lambda conn: self.service().state(conn, session or self.session, now))

    async def start(self, now=1000, team=None, session=None, rng=None):
        return await self.writer.run(lambda conn: self.service().start(
            conn, session or self.session, self.team if team is None else team, now,
            rng or random.Random(7), CONTENT, MULTIPLIERS))

    async def heal(self, run, positions, berry='razz_berry', now=1200):
        return await self.writer.run(lambda conn: self.service().heal(
            conn, self.session, run['run_id'], run['revision'], positions, berry, now))

    async def order(self, run, order, now=1200, session=None):
        return await self.writer.run(lambda conn: self.service().set_order(
            conn, session or self.session, run['run_id'], run['revision'], order, now))

    async def inventory(self, berry, quantity):
        await self.conn.execute('INSERT INTO inventory VALUES (?,?,?) '
                                'ON CONFLICT(profile_id,item_id) DO UPDATE SET quantity=excluded.quantity',
                                (self.pid, berry, quantity))

    async def hurt(self, run):
        for member in run['team']:
            member['hp'] = 1
        await self.conn.execute('UPDATE arena_runs SET team=? WHERE run_id=?',
                                (json.dumps(run['team']), run['run_id']))
        return run

    async def assert_refused(self, expected, **kwargs):
        before = await self.snapshot()
        self.assertEqual(await self.start(**kwargs), expected)
        self.assertEqual(await self.snapshot(), before)

    async def test_start_snapshots_and_rolls_enemy(self):
        self.assertEqual(await self.state(), {'status': 'none', 'run': None, 'cooldown_left': 0,
                                             'enabled': True, 'best_floor': 0, 'tickets': {}})
        result = await self.start()
        self.assertEqual(result['status'], 'started')
        run = result['run']
        self.assertEqual((run['profile_id'], run['started_at'], run['ended_at'], run['end_reason'],
                          run['floor'], run['slot'], run['revision']), (self.pid, 1000, None, None, 1, 0, 0))
        self.assertEqual([member['uid'] for member in run['team']], ['m0', 'm1', 'm2'])
        for member in run['team']:
            pokemon = await storage.detail(self.conn, self.pid, member['uid'])
            combatant, snapshot = gyms._battle_snapshot(pokemon, CONTENT, MULTIPLIERS)
            self.assertEqual(member, {'uid': member['uid'], 'family_id': 1, 'special': False,
                                      'full_hp': combatant.hp, 'hp': combatant.hp,
                                      'snapshot': json.loads(json.dumps(snapshot))})
        rolled = domain.roll_enemy(1, 0, CONTENT['identities'], random.Random(7), RULES)
        enemy = run['enemy']
        self.assertEqual(storage.identify(CONTENT, enemy['snapshot'])[0], rolled['identity'])
        self.assertEqual([enemy['snapshot'][key] for key in ('iv_attack', 'iv_defense', 'iv_stamina')],
                         list(rolled['ivs']))
        self.assertEqual(enemy['snapshot']['level_x2'], 2)
        self.assertEqual(enemy['snapshot']['content_version'], profiles.content_facts(CONTENT)[0])
        self.assertEqual(enemy['battle_hp'], enemy['snapshot']['combatant']['hp'])
        self.assertFalse(enemy['special'])
        self.assertEqual((await self.state())['run'], run)

    async def test_every_identity_snapshots_as_itself(self):
        for identity in CONTENT['identities']:
            with self.subTest(pokemon=identity['pokemon_id'], form=identity['form_id']):
                rolled = {'identity': identity, 'level_x2': 20, 'ivs': (1, 2, 3),
                          'factor_x10': 11, 'special': domain.is_special(identity, RULES)}
                enemy = self.service()._enemy_snapshot(rolled, CONTENT, MULTIPLIERS)
                self.assertEqual(storage.identify(CONTENT, enemy['snapshot'])[0], identity)
                self.assertEqual(enemy['battle_hp'], domain.enemy_hp(enemy['snapshot']['combatant']['hp'], 11))
                self.assertEqual(enemy['special'], rolled['special'])

    async def test_start_refusals_in_order_write_nothing(self):
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,excluded) VALUES ('g','u',1,1)")
        await self.conn.execute('UPDATE guilds SET arena_enabled=0')
        await self.assert_refused({'status': 'stale'}, session={**self.session, 'profile_id': self.other}, team=[])
        await self.assert_refused({'status': 'excluded'}, team=[])
        await self.conn.execute('UPDATE restrictions SET excluded=0')
        await self.assert_refused({'status': 'paused', 'until': None}, team=[])
        await self.conn.execute('UPDATE restrictions SET paused=0')
        await self.assert_refused({'status': 'off'}, team=[])
        await self.conn.execute('UPDATE guilds SET arena_enabled=1')
        run = (await self.start())['run']
        before = await self.snapshot()
        self.assertEqual((await self.start(team=[]))['status'], 'live')
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute("UPDATE arena_runs SET ended_at=1100,end_reason='loss'")
        await self.assert_refused({'status': 'cooldown', 'seconds_left': 64600}, now=1200, team=[])
        for team in ([], self.team[:2], [self.team[0]] * 3, [('m0',), *self.team[1:]]):
            with self.subTest(team=team):
                await self.assert_refused({'status': 'invalid'}, now=65800, team=team)
        for change in ({'revision': 1}, {'profile_id': self.other}, {'state': 'sent'}):
            key, value = next(iter(change.items()))
            await self.conn.execute(f'UPDATE pokemon SET {key}=? WHERE pokemon_uid=?', (value, 'm0'))
            await self.assert_refused({'status': 'stale'}, now=65800)
            await self.conn.execute("UPDATE pokemon SET revision=0,profile_id=?,state='owned' WHERE pokemon_uid='m0'",
                                    (self.pid,))
        await self.assert_refused({'status': 'stale'}, now=65800, team=[('missing', 0), *self.team[1:]])
        await self.conn.execute("INSERT INTO gyms(gym_id,guild_id,name,created_at) VALUES ('gym','g','Park',0)")
        await self.conn.execute('INSERT INTO gym_deployments(deployment_id,guild_id,gym_id,profile_id,pokemon_uid,'
                                "deployed_at,ends_at) VALUES ('d','g','gym',?,'m0',0,1e12)", (self.pid,))
        await self.conn.execute("UPDATE pokemon SET gym_deployment_id='d' WHERE pokemon_uid='m0'")
        await self.assert_refused({'status': 'deployed'}, now=65800)
        self.assertEqual((await self.state())['run']['run_id'], run['run_id'])

    async def test_paused_start_persists_expiry_only(self):
        run = (await self.start())['run']
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('g','u',1)")
        before = await self.snapshot()
        self.assertEqual(await self.start(now=65800), {'status': 'paused', 'until': None})
        before['arena_runs'][0].update(ended_at=65800, end_reason='expired', revision=run['revision'] + 1)
        self.assertEqual(await self.snapshot(), before)

    async def test_companion_legendary_may_join(self):
        await self.conn.execute("UPDATE profiles SET companion_uid='m0' WHERE profile_id=?", (self.pid,))
        await self.conn.execute("UPDATE pokemon SET pokemon_id=144 WHERE pokemon_uid='m0'")
        result = await self.start()
        self.assertEqual(result['status'], 'started')
        self.assertTrue(result['run']['team'][0]['special'])
        identity = next(item for item in CONTENT['identities'] if item['pokemon_id'] == 144)
        self.assertEqual(result['run']['team'][0]['family_id'], identity['family_id'])

    async def test_cooldown_runs_18h_from_start(self):
        await self.start()
        await self.conn.execute("UPDATE arena_runs SET ended_at=2000,end_reason='loss'")
        self.assertEqual((await self.state(now=2000))['cooldown_left'], 63800)
        await self.assert_refused({'status': 'cooldown', 'seconds_left': 1}, now=65799.5)
        result = await self.start(now=65800, session={**self.session, '_original_revision': 6})
        self.assertEqual(result['status'], 'started')
        self.assertEqual(result['run']['started_at'], 65800)
        self.assertEqual(await self.scalar('SELECT count(*) FROM arena_runs'), 2)

    async def test_same_start_press_one_run(self):
        results = await asyncio.gather(self.start(), self.start())
        self.assertEqual([result['status'] for result in results], ['started', 'live'])
        self.assertEqual(await self.scalar('SELECT count(*) FROM arena_runs'), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM action_receipts'), 1)
        before = await self.snapshot()
        with patch.object(domain, 'roll_enemy', side_effect=AssertionError('rerolled enemy')):
            self.assertEqual((await self.start())['status'], 'live')
        self.assertEqual(await self.snapshot(), before)

    async def test_expires_at_hour_18_first(self):
        run = await self.hurt((await self.start())['run'])
        await self.inventory('razz_berry', 3)
        self.assertEqual((await self.state(now=65799.999))['status'], 'live')
        before = await self.snapshot()
        result = await self.heal(run, [0], now=65800)
        self.assertEqual(result['status'], 'stale')
        self.assertEqual((result['run']['ended_at'], result['run']['end_reason'], result['run']['revision']),
                         (65800, 'expired', 1))
        before['arena_runs'][0].update(ended_at=65800, end_reason='expired', revision=1)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.state(now=65801))['status'], 'ended')
        self.assertEqual(await self.snapshot(), before)

    async def test_restart_resumes_same_state(self):
        run = await self.hurt((await self.start())['run'])
        await self.order(run, (2, 0, 1))
        before = await self.state()
        await self.writer.close()
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.assertEqual(await self.state(), before)

    async def test_powerup_keeps_snapshot(self):
        run = (await self.start())['run']
        await self.conn.execute('UPDATE profiles SET stardust=10000')
        await self.conn.execute('INSERT INTO candy VALUES (?,1,100)', (self.pid,))
        result = await self.writer.run(lambda conn: powerup.power_up(
            conn, self.session, 'm0', 0, CONTENT, MULTIPLIERS))
        self.assertEqual(result['status'], 'powered_up')
        self.assertEqual((await storage.detail(self.conn, self.pid, 'm0'))['level_x2'], 21)
        self.assertEqual((await self.state())['run'], run)

    async def test_set_order_persists(self):
        run = await self.hurt((await self.start())['run'])
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('g','u',1)")
        await self.conn.execute('UPDATE guilds SET arena_enabled=0')
        result = await self.order(run, (2, 0, 1))
        self.assertEqual(result['status'], 'ordered')
        self.assertEqual(result['run']['team'], [run['team'][i] for i in (2, 0, 1)])
        self.assertEqual(result['run']['revision'], 1)
        self.assertEqual((await self.state())['run'], result['run'])
        self.assertEqual(result['run']['enemy'], run['enemy'])
        self.assertEqual(await self.scalar('SELECT count(*) FROM action_receipts'), 1)
        for order in ((0, 0, 1), (0, 1), (0, 1, 3), (False, 1, 2)):
            before = await self.snapshot()
            self.assertEqual((await self.order(result['run'], order))['status'], 'invalid')
            self.assertEqual(await self.snapshot(), before)

    async def test_heal_mixed_berry_types(self):
        run = await self.hurt((await self.start())['run'])
        await self.inventory('razz_berry', 3)
        await self.inventory('pinap_berry', 3)
        first = await self.heal(run, [0])
        self.assertEqual(first['status'], 'healed')
        self.assertEqual([m['hp'] for m in first['run']['team']], [run['team'][0]['full_hp'], 1, 1])
        second = await self.heal(first['run'], [1, 2], 'pinap_berry')
        self.assertEqual(second['status'], 'healed')
        self.assertEqual(second['run']['revision'], 2)
        self.assertTrue(all(m['hp'] == m['full_hp'] for m in second['run']['team']))
        self.assertEqual(second['run']['enemy'], run['enemy'])
        self.assertEqual(await self.rows('SELECT item_id,quantity FROM inventory ORDER BY item_id'),
                         [{'item_id': 'pinap_berry', 'quantity': 1}, {'item_id': 'razz_berry', 'quantity': 2}])
        lines = await self.rows('SELECT resource,resource_id,delta,reason FROM resource_ledger ORDER BY resource_id')
        self.assertEqual(lines, [{'resource': 'item', 'resource_id': berry, 'delta': delta, 'reason': 'arena_heal'}
                                 for berry, delta in [('pinap_berry', -2), ('razz_berry', -1)]])
        repeated = await self.hurt(second['run'])
        self.assertEqual((await self.heal(repeated, [0, 1]))['status'], 'healed')

    async def test_heal_short_spends_nothing(self):
        run = await self.hurt((await self.start())['run'])
        await self.inventory('razz_berry', 1)
        before = await self.snapshot()
        self.assertEqual(await self.heal(run, [0, 1, 2]), {'status': 'missing', 'short': 2})
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.heal(run, [0, 1, 2], 'pinap_berry'), {'status': 'missing', 'short': 3})
        self.assertEqual(await self.snapshot(), before)

    async def test_golden_razz_refused(self):
        run = await self.hurt((await self.start())['run'])
        for berry in ('golden_razz_berry', 'silver_pinap_berry', 'poke_ball'):
            await self.inventory(berry, 5)
            before = await self.snapshot()
            self.assertEqual(await self.heal(run, [0], berry), {'status': 'invalid'})
            self.assertEqual(await self.snapshot(), before)

    async def test_stale_revision_spends_nothing(self):
        run = await self.hurt((await self.start())['run'])
        await self.inventory('razz_berry', 3)
        ordered = (await self.order(run, (2, 1, 0)))['run']
        for stale in (run, {**ordered, 'run_id': 'other-run'}):
            before = await self.snapshot()
            self.assertEqual(await self.heal(stale, [0]), {'status': 'stale', 'run': ordered})
            self.assertEqual(await self.order(stale, (0, 1, 2)), {'status': 'stale', 'run': ordered})
            self.assertEqual(await self.snapshot(), before)
        healed = await self.heal(ordered, [0])
        before = await self.snapshot()
        self.assertEqual((await self.heal(ordered, [0]))['status'], 'stale')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(healed['run']['revision'], 2)

    async def test_every_receipt_has_profile_id(self):
        run = await self.hurt((await self.start())['run'])
        await self.inventory('razz_berry', 1)
        await self.heal(run, [0])
        receipts = await self.rows('SELECT key,action,profile_id FROM action_receipts ORDER BY action')
        self.assertEqual(receipts, [
            {'key': f"arena_heal:{run['run_id']}:0", 'action': 'arena_heal', 'profile_id': self.pid},
            {'key': 'arena_start:s:4', 'action': 'arena_start', 'profile_id': self.pid}])

    async def test_invalid_or_full_heal_and_excluded_actions_spend_nothing(self):
        run = (await self.start())['run']
        await self.inventory('razz_berry', 3)
        before = await self.snapshot()
        self.assertEqual(await self.heal(run, [0]), {'status': 'full'})
        for positions in ([], [0, 0], [3], [-1], [True], ['0']):
            self.assertEqual(await self.heal(run, positions), {'status': 'invalid'})
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
        before = await self.snapshot()
        self.assertEqual(await self.heal(run, [0]), {'status': 'excluded'})
        self.assertEqual(await self.order(run, (2, 1, 0)), {'status': 'excluded'})
        self.assertEqual(await self.state(), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_lifecycle_requires_writer_and_state_is_profile_scoped(self):
        svc = self.service()
        for call in (lambda: svc.state(self.conn, self.session, 1000),
                     lambda: svc.start(self.conn, self.session, self.team, 1000, random.Random(7), CONTENT, MULTIPLIERS),
                     lambda: svc.set_order(self.conn, self.session, 'missing', 0, (0, 1, 2), 1000),
                     lambda: svc.heal(self.conn, self.session, 'missing', 0, [0], 'razz_berry', 1000)):
            with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
                await call()
        await self.start()
        before = await self.snapshot()
        self.assertEqual(await self.state(session={**self.session, 'profile_id': self.other}), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)
