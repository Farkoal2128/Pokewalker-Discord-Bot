"""C3 Arena lifecycle: real SQLite transactions, frozen snapshots and berry debits."""

import asyncio
from dataclasses import replace
import importlib
import json
from pathlib import Path
from datetime import datetime, timezone
import random
import unittest
from unittest.mock import patch

from content.balance import limits, load_table
from pokewalker import db
from pokewalker.domain import arena as domain
from pokewalker.domain import battle as battle_engine
from pokewalker.services import gyms, milestones, powerup, profiles, stepping, storage
import test_db


CONTENT = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
MULTIPLIERS = load_table('cpm')['multipliers']
RULES = load_table('arena')['rules']
MONTH_NOW = datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp()


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
                 'arena_runs', 'arena_tickets', 'arena_month_scores', 'arena_months', 'arena_month_places',
                 'inbox_items', 'action_receipts', 'resource_ledger')}

    async def state(self, now=1100, session=None):
        return await self.writer.run(lambda conn: self.service().state(conn, session or self.session, now))

    async def start(self, now=1000, team=None, session=None, rng=None, **kwargs):
        return await self.writer.run(lambda conn: self.service().start(
            conn, session or self.session, self.team if team is None else team, now,
            rng or random.Random(7), CONTENT, MULTIPLIERS, **kwargs))

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
                                             'enabled': True, 'best_floor': 0, 'tickets': {},
                                             'stop_pct': 50, 'auto_order': False,
                                             'stardust': 0, 'x_items': {'x_attack': 0, 'x_defense': 0}})
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

    async def x_press(self):
        self.session['_original_revision'] = self.session['revision']
        self.session['revision'] += 1
        await self.conn.execute('UPDATE sessions SET revision=? WHERE session_id=?',
                                (self.session['revision'], self.session['session_id']))

    async def buy_x(self, item='x_attack', *, press=True, session=None):
        if press:
            await self.x_press()
        return await self.writer.run(lambda conn: self.service().buy_x(conn, session or self.session, item))

    async def use_x(self, run, item='x_attack', now=1200):
        await self.x_press()
        return await self.writer.run(lambda conn: self.service().use_x(
            conn, self.session, run['run_id'], run['revision'], item, now))

    async def test_state_reports_stardust_and_held_x_items(self):
        self.assertEqual((await self.state())['x_items'], {'x_attack': 0, 'x_defense': 0})
        await self.conn.execute('UPDATE profiles SET stardust=1234 WHERE profile_id=?', (self.pid,))
        await self.inventory('x_defense', 2)
        await self.inventory('razz_berry', 9)
        current = await self.state()
        self.assertEqual(current['stardust'], 1234)
        self.assertEqual(current['x_items'], {'x_attack': 0, 'x_defense': 2})

    async def test_buy_x_moves_stardust_to_bag_with_buy_ledger_lines(self):
        await self.conn.execute('UPDATE profiles SET stardust=1000 WHERE profile_id=?', (self.pid,))
        for item in RULES['x_items']['items']:
            result = await self.buy_x(item)
            price = RULES['x_items']['items'][item]['stardust']
            self.assertEqual(result, {'status': 'bought', 'item': item, 'stardust': price})
            self.assertEqual(await self.scalar('SELECT quantity FROM inventory WHERE item_id=?', (item,)), 1)
            self.assertEqual(await self.rows('SELECT resource,resource_id,delta,reason FROM resource_ledger '
                                             'WHERE receipt_key=? ORDER BY line_key',
                                             (f"buy:s:{self.session['revision']}",)), [
                dict(resource='stardust', resource_id=None, delta=-price, reason='buy'),
                dict(resource='item', resource_id=item, delta=1, reason='buy')])
        self.assertEqual((await self.state())['stardust'], 400)

    async def test_buy_x_refuses_insufficient_then_bag_full(self):
        await self.inventory('poke_ball', limits()['bag_units'])
        await self.x_press()
        before = await self.snapshot()
        self.assertEqual(await self.buy_x(press=False), {'status': 'insufficient'})
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('UPDATE profiles SET stardust=1000 WHERE profile_id=?', (self.pid,))
        before = await self.snapshot()
        self.assertEqual(await self.buy_x(press=False), {'status': 'bag_full'})
        self.assertEqual(await self.snapshot(), before)

    async def test_buy_x_needs_no_run_ignores_off_cooldown_pause(self):
        await self.conn.execute('UPDATE profiles SET stardust=2000 WHERE profile_id=?', (self.pid,))
        self.assertEqual((await self.buy_x())['status'], 'bought')
        run = (await self.start())['run']
        await self.conn.execute('UPDATE guilds SET arena_enabled=0')
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('g','u',1)")
        self.assertEqual((await self.buy_x())['status'], 'bought')
        self.assertEqual((await self.state())['run'], run)
        await self.conn.execute("UPDATE arena_runs SET ended_at=1100,end_reason='loss'")
        self.assertGreater((await self.state())['cooldown_left'], 0)
        self.assertEqual((await self.buy_x())['status'], 'bought')
        self.assertEqual((await self.state())['run']['revision'], run['revision'])

    async def test_same_buy_press_buys_once(self):
        await self.conn.execute('UPDATE profiles SET stardust=300 WHERE profile_id=?', (self.pid,))
        result = await self.buy_x()
        before = await self.snapshot()
        self.assertEqual(await self.buy_x(press=False), result)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.state())['x_items']['x_attack'], 1)
        self.assertEqual(await self.rows("SELECT key FROM action_receipts WHERE action='buy'"),
                         [{'key': f"buy:s:{self.session['revision']}"}])

    async def test_use_x_sets_counter_spends_item_bumps_revision(self):
        run = (await self.start())['run']
        await self.inventory('x_attack', 2)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('g','u',1)")
        result = await self.use_x(run)
        expected = {**run, 'x_attack_left': RULES['x_items']['fights'], 'revision': run['revision'] + 1}
        self.assertEqual(result, {'status': 'used', 'run': expected})
        self.assertEqual((await self.state())['run'], expected)
        self.assertEqual((await self.state())['x_items']['x_attack'], 1)
        before = await self.snapshot()
        self.assertEqual((await self.use_x(run))['status'], 'stale')
        before['sessions'][0]['revision'] = self.session['revision']
        self.assertEqual(await self.snapshot(), before)

    async def test_use_x_active_kind_refused_other_kind_allowed(self):
        run = (await self.start())['run']
        await self.inventory('x_attack', 1)
        await self.inventory('x_defense', 1)
        run = (await self.use_x(run))['run']
        await self.x_press()
        before = await self.snapshot()
        result = await self.writer.run(lambda conn: self.service().use_x(
            conn, self.session, run['run_id'], run['revision'], 'x_attack', 1200))
        self.assertEqual(result, {'status': 'active', 'left': RULES['x_items']['fights']})
        self.assertEqual(await self.snapshot(), before)
        other = (await self.use_x(run, 'x_defense'))['run']
        self.assertEqual((other['x_attack_left'], other['x_defense_left']), (3, 3))
        self.assertEqual(other['revision'], run['revision'] + 1)

    async def test_use_x_missing_stale_invalid_write_nothing(self):
        await self.x_press()
        before = await self.snapshot()
        self.assertEqual(await self.writer.run(lambda conn: self.service().use_x(
            conn, self.session, 'absent', 0, 'unknown', 1200)), {'status': 'stale', 'run': None})
        self.assertEqual(await self.snapshot(), before)
        run = (await self.start())['run']
        for run_id, revision, item, expected in (
                (run['run_id'], 0, 'x_attack', {'status': 'missing'}),
                (run['run_id'], 0, 'unknown', {'status': 'invalid'}),
                ('other', 0, 'unknown', {'status': 'stale', 'run': run}),
                (run['run_id'], 99, 'x_attack', {'status': 'stale', 'run': run})):
            await self.x_press()
            before = await self.snapshot()
            self.assertEqual(await self.writer.run(lambda conn: self.service().use_x(
                conn, self.session, run_id, revision, item, 1200)), expected)
            self.assertEqual(await self.snapshot(), before)
        before = await self.snapshot()
        self.assertEqual(await self.buy_x('unknown', press=False), {'status': 'invalid'})
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.buy_x(press=False, session={**self.session, 'profile_id': self.other}),
                         {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)

    async def test_new_run_starts_both_counters_at_zero(self):
        run = (await self.start())['run']
        self.assertEqual((run['x_attack_left'], run['x_defense_left']), (0, 0))
        await self.inventory('x_attack', 1)
        await self.use_x(run)
        await self.conn.execute("UPDATE arena_runs SET ended_at=1300,end_reason='loss'")
        await self.x_press()
        run = (await self.start(now=65800))['run']
        self.assertEqual((run['x_attack_left'], run['x_defense_left']), (0, 0))

    async def test_x_receipts_and_ledger_carry_profile_id(self):
        await self.conn.execute('UPDATE profiles SET stardust=300 WHERE profile_id=?', (self.pid,))
        await self.buy_x()
        buy_key = f"buy:s:{self.session['revision']}"
        run = (await self.start())['run']
        await self.use_x(run)
        use_key = f"arena_use:{run['run_id']}:0"
        self.assertEqual(await self.rows("SELECT key,action,profile_id FROM action_receipts "
                                         "WHERE action IN ('buy','arena_use') ORDER BY action"), [
            dict(key=use_key, action='arena_use', profile_id=self.pid),
            dict(key=buy_key, action='buy', profile_id=self.pid)])
        self.assertEqual(await self.rows('SELECT receipt_key,profile_id,resource,resource_id,delta,reason '
                                         'FROM resource_ledger WHERE receipt_key=?', (use_key,)), [
            dict(receipt_key=use_key, profile_id=self.pid, resource='item', resource_id='x_attack',
                 delta=-1, reason='arena_use')])
        self.assertEqual(await self.scalar('SELECT count(*) FROM resource_ledger WHERE profile_id=?',
                                          (self.pid,)), 3)

    async def test_excluded_member_cannot_buy_or_use_x(self):
        run = (await self.start())['run']
        await self.inventory('x_attack', 1)
        await self.conn.execute('UPDATE profiles SET stardust=1000 WHERE profile_id=?', (self.pid,))
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
        await self.x_press()
        before = await self.snapshot()
        self.assertEqual(await self.buy_x(press=False), {'status': 'excluded'})
        self.assertEqual(await self.writer.run(lambda conn: self.service().use_x(
            conn, self.session, run['run_id'], run['revision'], 'x_attack', 1200)), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

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

    async def setting(self, name, run, value, now=1200, session=None):
        function = getattr(self.service(), f'set_{name}')
        return await self.writer.run(lambda conn: function(
            conn, session or self.session, run['run_id'], run['revision'], value, now))

    async def test_state_reports_setting_defaults(self):
        current = await self.state()
        self.assertEqual(current['stop_pct'], 50)
        self.assertIs(current['auto_order'], False)
        await self.conn.execute('UPDATE profiles SET arena_stop_pct=90,arena_auto_order=1 WHERE profile_id=?',
                                (self.other,))
        self.assertEqual((await self.state())['stop_pct'], 50)
        self.assertIs((await self.state())['auto_order'], False)

    async def test_setters_save_on_profile_and_bump_live_run_revision(self):
        run = (await self.start())['run']
        before = await self.snapshot()
        self.assertEqual(self.service().STOP_PCTS, range(10, 100, 10))
        changes = [('stop_pct', value) for value in self.service().STOP_PCTS]
        changes += [('stop_pct', 90), ('auto_order', True), ('auto_order', True), ('auto_order', False)]
        for name, value in changes:
            with self.subTest(name=name, value=value):
                result = await self.setting(name, run, value)
                self.assertEqual(result, {'status': 'set', 'run': {**run, 'revision': run['revision'] + 1}})
                run = result['run']
                current = await self.state()
                self.assertEqual(current['run'], run)
                self.assertEqual(current[name], value)
                if name == 'auto_order':
                    self.assertIs(current[name], value)
                self.assertEqual(await self.scalar(f'SELECT arena_{name} FROM profiles WHERE profile_id=?',
                                                   (self.pid,)), value)
        after = await self.snapshot()
        for table in before.keys() - {'profiles', 'arena_runs'}:
            self.assertEqual(after[table], before[table])
        self.assertEqual([row for row in after['profiles'] if row['profile_id'] == self.other],
                         [row for row in before['profiles'] if row['profile_id'] == self.other])
        for name, value in (('stop_pct', 10), ('auto_order', True)):
            with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
                await getattr(self.service(), f'set_{name}')(
                    self.conn, self.session, run['run_id'], run['revision'], value, 1200)

    async def test_settings_carry_over_to_the_next_run(self):
        run = (await self.start())['run']
        run = (await self.setting('stop_pct', run, 30))['run']
        await self.setting('auto_order', run, True)
        await self.writer.close()
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        new_run = (await self.start(now=1000 + RULES['cooldown_seconds'],
                                    session={**self.session, '_original_revision': 6}))['run']
        self.assertNotEqual(new_run['run_id'], run['run_id'])
        current = await self.state(now=new_run['started_at'])
        self.assertEqual(current['stop_pct'], 30)
        self.assertIs(current['auto_order'], True)

    async def test_setting_from_stale_screen_or_without_live_run_writes_nothing(self):
        for name, value in (('stop_pct', 20), ('auto_order', True)):
            before = await self.snapshot()
            self.assertEqual(await self.setting(name, {'run_id': 'absent', 'revision': 0}, value),
                             {'status': 'stale', 'run': None})
            self.assertEqual(await self.snapshot(), before)
        run = (await self.start())['run']
        changed = (await self.setting('stop_pct', run, 30))['run']
        for name, value in (('stop_pct', 20), ('auto_order', True)):
            for stale in (run, {**changed, 'run_id': 'other'}):
                before = await self.snapshot()
                self.assertEqual(await self.setting(name, stale, value), {'status': 'stale', 'run': changed})
                self.assertEqual(await self.snapshot(), before)
        ended = (await self.state(now=1000 + RULES['run_seconds']))['run']
        for name, value in (('stop_pct', 20), ('auto_order', True)):
            before = await self.snapshot()
            self.assertEqual(await self.setting(name, ended, value), {'status': 'stale', 'run': ended})
            self.assertEqual(await self.snapshot(), before)

    async def test_invalid_setting_values_refused_without_write(self):
        run = (await self.start())['run']
        for name, values in (('stop_pct', (55, 0, 100, 10.0, '50', True, False, None)),
                             ('auto_order', (0, 1, 'on', None, [], {}))):
            for value in values:
                with self.subTest(name=name, value=value):
                    before = await self.snapshot()
                    self.assertEqual(await self.setting(name, run, value), {'status': 'invalid'})
                    self.assertEqual(await self.snapshot(), before)

    async def test_fight_from_other_screen_is_stale_after_setting_change(self):
        run = (await self.start())['run']
        for name, value in (('stop_pct', 20), ('auto_order', True)):
            changed = (await self.setting(name, run, value))['run']
            before = await self.snapshot()
            with patch.object(battle_engine, 'simulate') as simulate:
                self.assertEqual(await self.fight(run), {'status': 'stale', 'run': changed})
                simulate.assert_not_called()
            self.assertEqual(await self.snapshot(), before)
            run = changed

    async def test_excluded_member_cannot_change_settings_paused_can(self):
        run = (await self.start())['run']
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('g','u',1)")
        for name, value in (('stop_pct', 20), ('auto_order', True)):
            result = await self.setting(name, run, value)
            self.assertEqual(result['status'], 'set')
            run = result['run']
        await self.conn.execute('UPDATE restrictions SET excluded=1')
        for name, value in (('stop_pct', 40), ('auto_order', False)):
            before = await self.snapshot()
            self.assertEqual(await self.setting(name, run, value), {'status': 'excluded'})
            self.assertEqual(await self.setting(name, run, value, session={**self.session, 'profile_id': self.other}),
                             {'status': 'stale'})
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
        stored = await self.rows("SELECT result FROM action_receipts WHERE action IN ('arena_heal','arena_start')")
        self.assertTrue(stored)
        self.assertTrue(all('run' not in json.loads(row['result']) for row in stored))  # receipts stay small

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

    async def fight(self, run, now=1300, session=None, berry=None):
        svc = self.service()
        function = getattr(svc, 'fight' if berry is None else 'heal_all_and_fight', None)
        self.assertIsNotNone(function, 'Arena fight service is absent')
        args = (session or self.session, run['run_id'], run['revision'])
        if berry is not None:
            args = (*args, berry)
        return await self.writer.run(lambda conn: function(
            conn, *args, now, random.Random(11), CONTENT, MULTIPLIERS,
            load_table('battle')['rules'], CONTENT['type_chart']))

    async def at_fight(self, floor=1, slot=0, special=False):
        if special:
            await self.conn.execute("UPDATE pokemon SET pokemon_id=144 WHERE pokemon_uid='m0'")
        run = (await self.start())['run']
        enemy = self.service()._roll_enemy(floor, slot, random.Random(19), CONTENT, MULTIPLIERS)
        await self.conn.execute('UPDATE arena_runs SET floor=?,slot=?,enemy=? WHERE run_id=?',
                                (floor, slot, json.dumps(enemy), run['run_id']))
        return (await self.state())['run']

    def outcome(self, outcome='win', hp=(3, 4, 5), finisher=0):
        return battle_engine.Result(outcome, 'defender_fainted' if outcome != 'loss' else 'party_fainted', 9,
                                    tuple(i for i, value in enumerate(hp) if value), ('private battle event',),
                                    party_hp=hp, finisher=finisher)

    async def x_fight_run(self, attack=0, defense=0, floor=1):
        run = await self.at_fight(floor=floor)
        await self.conn.execute('UPDATE arena_runs SET x_attack_left=?,x_defense_left=? WHERE run_id=?',
                                (attack, defense, run['run_id']))
        return (await self.state())['run']

    def assert_x_party(self, simulate, run, attack=1, defense=1):
        expected = [replace(battle_engine.Combatant(**member['snapshot']['combatant']),
                            hp=member['hp'], attack=member['snapshot']['combatant']['attack'] * attack,
                            defense=member['snapshot']['combatant']['defense'] * defense)
                    for member in run['team']]
        self.assertEqual(simulate.call_args.args[0], expected)

    async def test_x_attack_doubles_only_party_attack_given_to_simulate(self):
        run = await self.x_fight_run(attack=3, floor=5)
        with patch.object(battle_engine, 'simulate', wraps=battle_engine.simulate) as simulate:
            await self.fight(run)
        self.assert_x_party(simulate, run, attack=2)

    async def test_x_defense_doubles_only_party_defense_and_both_kinds_combine(self):
        for attack in (0, 3):
            with self.subTest(attack=attack):
                await self.reset_run_fixture()
                run = await self.x_fight_run(attack=attack, defense=3, floor=5)
                with patch.object(battle_engine, 'simulate', wraps=battle_engine.simulate) as simulate:
                    await self.fight(run)
                self.assert_x_party(simulate, run, attack=2 if attack else 1, defense=2)

    async def test_enemy_combatant_and_stored_snapshots_stay_unboosted(self):
        run = await self.x_fight_run(3, 3, floor=5)
        with patch.object(battle_engine, 'simulate', wraps=battle_engine.simulate) as simulate:
            await self.fight(run)
        self.assert_x_party(simulate, run, attack=2, defense=2)
        self.assertEqual(simulate.call_args.args[1:], (
            battle_engine.Combatant(**run['enemy']['snapshot']['combatant']), run['enemy']['battle_hp']))
        self.assertEqual(simulate.call_args.kwargs, {'rules': load_table('battle')['rules'],
                                                    'chart': CONTENT['type_chart']})
        after = (await self.state())['run']
        self.assertEqual([m['snapshot'] for m in after['team']], [m['snapshot'] for m in run['team']])
        self.assertEqual(after['enemy'], json.loads(json.dumps(self.service()._roll_enemy(
            5, 1, random.Random(11), CONTENT, MULTIPLIERS))))

    async def test_three_fights_boosted_fourth_not_both_counters_drop_each_fight(self):
        run = await self.x_fight_run(3, 3)
        for left in (2, 1, 0, 0):
            with patch.object(battle_engine, 'simulate', wraps=battle_engine.simulate) as simulate:
                self.assertEqual((await self.fight(run))['status'], 'won')
            self.assert_x_party(simulate, run, attack=2 if run['x_attack_left'] else 1,
                                defense=2 if run['x_defense_left'] else 1)
            run = (await self.state())['run']
            self.assertEqual((run['x_attack_left'], run['x_defense_left']), (left, left))

    async def test_loss_and_draw_count_down_and_end_the_run(self):
        for outcome in ('loss', 'draw'):
            with self.subTest(outcome=outcome):
                await self.reset_run_fixture()
                run = await self.x_fight_run(3, 1)
                inventory = await self.rows('SELECT * FROM inventory')
                with patch.object(battle_engine, 'simulate', return_value=self.outcome(outcome, (0, 0, 0), None)):
                    result = await self.fight(run)
                after = (await self.state())['run']
                self.assertEqual(result['status'], 'defeated')
                self.assertEqual((after['x_attack_left'], after['x_defense_left']), (2, 0))
                self.assertEqual((after['ended_at'], after['end_reason']), (1300, outcome))
                self.assertEqual(await self.rows('SELECT * FROM inventory'), inventory)

    async def test_expired_run_keeps_counters_and_refunds_nothing(self):
        run = await self.x_fight_run(3, 2)
        before = await self.snapshot()
        with patch.object(battle_engine, 'simulate', side_effect=AssertionError('expired boost fought')):
            self.assertEqual((await self.fight(run, now=65800))['status'], 'stale')
        before['arena_runs'][0].update(ended_at=65800, end_reason='expired', revision=run['revision'] + 1)
        self.assertEqual(await self.snapshot(), before)

    async def test_chain_step_and_heal_all_fights_are_boosted_and_counted(self):
        for action in ('chain', 'heal'):
            with self.subTest(action=action):
                await self.reset_run_fixture()
                run = await self.x_fight_run(3, 3)
                if action == 'heal':
                    run = await self.hurt(run)
                    await self.inventory('razz_berry', 3)
                with patch.object(battle_engine, 'simulate', wraps=battle_engine.simulate) as simulate:
                    result = await self.chain_step(run) if action == 'chain' else await self.fight(run, berry='razz_berry')
                self.assertEqual(result['status'], 'won')
                healed = {**run, 'team': [{**m, 'hp': m['full_hp']} for m in run['team']]}
                self.assert_x_party(simulate, healed, attack=2, defense=2)
                after = (await self.state())['run']
                self.assertEqual((after['x_attack_left'], after['x_defense_left']), (2, 2))
                self.assertEqual(after['revision'], run['revision'] + (2 if action == 'heal' else 1))

    async def test_chain_continues_when_a_boost_runs_out(self):
        run = await self.x_fight_run(1, 1)
        for left in (0, 0):
            with patch.object(battle_engine, 'simulate', wraps=battle_engine.simulate) as simulate:
                result = await self.chain_step(run)
            self.assert_x_party(simulate, run, attack=2 if run['x_attack_left'] else 1,
                                defense=2 if run['x_defense_left'] else 1)
            self.assertEqual((result['status'], result['stop']), ('won', None))
            run = result['run']
            self.assertEqual((run['x_attack_left'], run['x_defense_left']), (left, left))

    async def test_replayed_fight_counts_down_once(self):
        run = await self.x_fight_run(3, 3)
        with patch.object(battle_engine, 'simulate', wraps=battle_engine.simulate) as simulate:
            results = await asyncio.gather(self.fight(run), self.fight(run))
        self.assertEqual([r['status'] for r in results], ['won', 'stale'])
        self.assertEqual(simulate.call_count, 1)
        after = (await self.state())['run']
        self.assertEqual((after['x_attack_left'], after['x_defense_left']), (2, 2))
        # Restore the screen coordinates to reach the receipt replay guard as well.
        await self.conn.execute('UPDATE arena_runs SET floor=?,slot=?,revision=? WHERE run_id=?',
                                (run['floor'], run['slot'], run['revision'], run['run_id']))
        before = await self.snapshot()
        with patch.object(battle_engine, 'simulate', side_effect=AssertionError('receipt replay fought')):
            self.assertEqual(await self.fight(run), results[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_crash_mid_boost_keeps_count_and_rolls_back_together(self):
        run = await self.x_fight_run(3, 3)
        await self.fight(run)
        before_restart = await self.state()
        self.assertEqual((before_restart['run']['x_attack_left'], before_restart['run']['x_defense_left']), (2, 2))
        before_crash = await self.snapshot()
        with patch.object(self.conn, 'commit', side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.fight(before_restart['run'])
        await self.writer.close()
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.assertEqual(await self.state(), before_restart)
        self.assertEqual(await self.snapshot(), before_crash)
        await self.conn.execute("CREATE TRIGGER fail_boost BEFORE INSERT ON resource_ledger "
                                "BEGIN SELECT RAISE(ABORT,'boost ledger failure'); END")
        before = await self.snapshot()
        with self.assertRaisesRegex(Exception, 'boost ledger failure'):
            await self.fight(before_restart['run'])
        self.assertEqual(await self.snapshot(), before)

    async def test_fight_result_and_receipt_keys_unchanged_by_boost(self):
        for attack, defense in ((0, 0), (3, 3)):
            with self.subTest(attack=attack):
                await self.reset_run_fixture()
                run = await self.x_fight_run(attack, defense)
                result = await self.fight(run)
                self.assertEqual(set(result), {'status', 'outcome', 'reason', 'ticks', 'engine', 'floor',
                                  'slot', 'enemy', 'party_hp', 'revived', 'finisher', 'candy', 'tickets'})
                receipt = (await self.rows("SELECT * FROM action_receipts WHERE action='arena_fight'"))[0]
                self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']),
                                 (f"arena_fight:{run['run_id']}:1:0", 'arena_fight', self.pid))
                self.assertEqual(json.loads(receipt['result']), result)
                self.assertEqual(result['engine'], battle_engine.ENGINE_VERSION)
                self.assertEqual(await self.rows('SELECT profile_id,resource,resource_id,delta,reason '
                                                 'FROM resource_ledger'), [
                    dict(profile_id=self.pid, resource='candy', resource_id='1', delta=1, reason='arena_candy')])

    async def test_real_engine_boosts_cut_ticks_and_damage_taken(self):
        results = {}
        for kind in (None, 'attack', 'defense'):
            await self.reset_run_fixture()
            run = await self.x_fight_run(attack=3 if kind == 'attack' else 0,
                                         defense=3 if kind == 'defense' else 0, floor=5)
            result = await self.fight(run)
            self.assertEqual(result['status'], 'won')
            results[kind] = (result['ticks'], sum(result['party_hp']))
        self.assertGreater(results[None][0], 1)
        self.assertLess(results['attack'][0], results[None][0], results)
        self.assertGreater(results['defense'][1], results[None][1], results)

    async def reset_run_fixture(self):
        await self.conn.execute('DELETE FROM arena_runs')
        await self.conn.execute('DELETE FROM action_receipts')
        await self.conn.execute('DELETE FROM arena_tickets')
        await self.conn.execute('DELETE FROM candy')
        await self.conn.execute('UPDATE profiles SET arena_best_floor=0')

    async def skip_start(self, skip=40):
        await self.conn.execute('UPDATE profiles SET arena_best_floor=80 WHERE profile_id=?', (self.pid,))
        return await self.start(skip=skip)

    async def test_skip_starts_at_next_floor_full_hp_with_that_floors_enemy(self):
        result = await self.skip_start()
        self.assertEqual(set(result), {'status', 'run'})
        run = result['run']
        self.assertEqual((result['status'], run['floor'], run['slot']), ('started', 41, 0))
        self.assertTrue(all(member['hp'] == member['full_hp'] for member in run['team']))
        self.assertEqual(run['enemy'], json.loads(json.dumps(
            self.service()._roll_enemy(41, 0, random.Random(7), CONTENT, MULTIPLIERS))))

    async def test_skip_pays_scheduled_tickets_with_ledger_lines_at_start(self):
        await self.conn.execute('INSERT INTO arena_tickets VALUES (?,?,3)', (self.pid, 'silver'))
        await self.skip_start()
        self.assertEqual((await self.state())['tickets'], {'bronze': 2, 'silver': 7, 'gold': 2})
        self.assertEqual(await self.rows('SELECT profile_id,resource,resource_id,delta,reason FROM resource_ledger '
                                         "WHERE reason='arena_skip' ORDER BY resource_id"),
                         [{'profile_id': self.pid, 'resource': 'arena_ticket', 'resource_id': tier,
                           'delta': copies, 'reason': 'arena_skip'}
                          for tier, copies in (('bronze', 2), ('gold', 2), ('silver', 4))])
        self.assertEqual(await self.scalar('SELECT count(*) FROM arena_tickets WHERE profile_id=?', (self.other,)), 0)

    async def test_skip_pays_no_bonus_or_candy_and_keeps_best_floor(self):
        await self.skip_start()
        self.assertEqual((await self.state())['best_floor'], 80)
        self.assertEqual((await self.state())['tickets'], {'bronze': 2, 'silver': 4, 'gold': 2})
        self.assertEqual(await self.rows('SELECT * FROM candy'), [])
        self.assertEqual(await self.rows("SELECT * FROM resource_ledger WHERE reason!='arena_skip'"), [])

    async def test_skip_over_limit_or_malformed_refused_writes_nothing(self):
        await self.conn.execute('UPDATE profiles SET arena_best_floor=30 WHERE profile_id=?', (self.pid,))
        for skip in (-1, 16, 41, True, False, 1.0, '1', None, [], {}):
            with self.subTest(skip=skip):
                await self.assert_refused({'status': 'invalid'}, skip=skip)
        self.assertEqual((await self.start(skip=15))['run']['floor'], 16)

    async def test_same_start_press_pays_skip_once(self):
        first = await self.skip_start()
        before = await self.snapshot()
        self.assertEqual((await self.start(skip=40))['status'], 'live')
        self.assertEqual(await self.snapshot(), before)
        replay = await self.start(skip=40, now=1000 + RULES['cooldown_seconds'])
        self.assertEqual(replay['run']['run_id'], first['run']['run_id'])
        after = await self.snapshot()
        for table in ('arena_tickets', 'action_receipts', 'resource_ledger'):
            self.assertEqual(after[table], before[table])

    async def chain_step(self, run, now=1300, session=None):
        return await self.writer.run(lambda conn: self.service().chain_step(
            conn, session or self.session, run['run_id'], run['revision'], now, random.Random(11),
            CONTENT, MULTIPLIERS, load_table('battle')['rules'], CONTENT['type_chart']))

    async def chain_health(self, run, health):
        for member, (hp, full_hp) in zip(run['team'], health):
            member.update(hp=hp, full_hp=full_hp)
        await self.conn.execute('UPDATE arena_runs SET team=? WHERE run_id=?',
                                (json.dumps(run['team']), run['run_id']))
        return run

    async def test_chain_step_fights_once_and_continues(self):
        run = await self.chain_health((await self.start())['run'], [(100, 100)] * 3)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('g','u',1)")
        await self.conn.execute('UPDATE guilds SET arena_enabled=0')
        with patch.object(battle_engine, 'simulate', return_value=self.outcome(hp=(80, 90, 100))) as simulate:
            result = await self.chain_step(run)
            simulate.assert_called_once()
            self.assertEqual(await self.chain_step(run), {'status': 'stale', 'run': result['run']})
            simulate.assert_called_once()
        self.assertEqual((result['status'], result['stop']), ('won', None))
        self.assertEqual(result['run'], (await self.state())['run'])
        self.assertEqual((result['run']['floor'], result['run']['slot'], result['run']['revision']), (1, 1, 1))

    async def test_chain_step_hurt_member_stops_before_fighting(self):
        run = await self.chain_health((await self.start())['run'], [(100, 100), (49, 100), (90, 100)])
        await self.conn.execute('UPDATE profiles SET arena_auto_order=1 WHERE profile_id=?', (self.pid,))
        before = await self.snapshot()
        with patch.object(battle_engine, 'simulate') as simulate:
            self.assertEqual(await self.chain_step(run), {'status': 'hurt', 'position': 1, 'run': run})
            simulate.assert_not_called()
        self.assertEqual(await self.snapshot(), before)

    async def test_chain_step_stops_after_revive_or_below_threshold(self):
        for hp, full, threshold, position in (((0, 2, 2), 2, 10, 0), ((100, 49, 100), 100, 50, 1)):
            with self.subTest(hp=hp):
                await self.reset_run_fixture()
                run = await self.chain_health(await self.at_fight(floor=5, slot=2), [(full, full)] * 3)
                await self.conn.execute('UPDATE profiles SET arena_stop_pct=? WHERE profile_id=?', (threshold, self.pid))
                with patch.object(battle_engine, 'simulate', return_value=self.outcome(hp=hp, finisher=2)):
                    result = await self.chain_step(run)
                self.assertEqual((result['status'], result['stop'], result['position']), ('won', 'hurt', position))
                self.assertIsNotNone(result['tickets'])
                self.assertEqual(result['run'], (await self.state())['run'])

    async def test_chain_step_stops_after_ticket_floor_boss(self):
        run = await self.chain_health(await self.at_fight(floor=5, slot=2), [(100, 100)] * 3)
        with patch.object(battle_engine, 'simulate', return_value=self.outcome(hp=(100, 100, 100))):
            result = await self.chain_step(run)
        self.assertEqual((result['stop'], result['tickets']['tier'], result['run']['floor']), ('ticket', 'bronze', 6))

    async def test_chain_step_defeat_stale_expired_or_excluded(self):
        run = (await self.start())['run']
        with patch.object(battle_engine, 'simulate') as simulate:
            for stale in ({**run, 'revision': 9}, {**run, 'run_id': 'other'}):
                before = await self.snapshot()
                self.assertEqual(await self.chain_step(stale), {'status': 'stale', 'run': run})
                self.assertEqual(await self.snapshot(), before)
            await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
            before = await self.snapshot()
            self.assertEqual(await self.chain_step(run), {'status': 'excluded'})
            self.assertEqual(await self.chain_step(run, session={**self.session, 'profile_id': self.other}),
                             {'status': 'stale'})
            self.assertEqual(await self.snapshot(), before)
            await self.conn.execute('DELETE FROM restrictions')
            expired = await self.chain_step(run, now=1000 + RULES['run_seconds'])
            self.assertEqual((expired['status'], expired['run']['end_reason']), ('stale', 'expired'))
            simulate.assert_not_called()
        await self.reset_run_fixture()
        run = (await self.start())['run']
        with patch.object(battle_engine, 'simulate', return_value=self.outcome('loss', (0, 0, 0), None)):
            result = await self.chain_step(run)
        self.assertEqual((result['status'], result['run']['end_reason']), ('defeated', 'loss'))
        self.assertNotIn('stop', result)
        self.assertEqual(result['run'], (await self.state())['run'])

    async def test_chain_step_auto_order_by_hp_percentage_only_when_on(self):
        for auto, expected in ((False, ['m0', 'm1', 'm2']), (True, ['m2', 'm1', 'm0'])):
            with self.subTest(auto=auto):
                await self.reset_run_fixture()
                run = await self.chain_health((await self.start())['run'], [(60, 100), (8, 10), (90, 100)])
                await self.conn.execute('UPDATE profiles SET arena_auto_order=? WHERE profile_id=?', (auto, self.pid))
                with patch.object(battle_engine, 'simulate', return_value=self.outcome(hp=(5, 5, 5))) as simulate:
                    result = await self.chain_step(run)
                self.assertEqual([member['uid'] for member in result['run']['team']], expected)
                self.assertEqual([member.hp for member in simulate.call_args.args[0]], [90, 8, 60] if auto else [60, 8, 90])
                self.assertEqual(result['run']['revision'], 2 if auto else 1)
        await self.reset_run_fixture()
        run = (await self.start())['run']
        await self.conn.execute('UPDATE profiles SET arena_auto_order=1 WHERE profile_id=?', (self.pid,))
        with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
            self.assertEqual((await self.chain_step(run))['run']['revision'], 1)

    async def test_chain_step_spends_no_berries_and_keeps_receipt_shape(self):
        run = (await self.start())['run']
        await self.inventory('razz_berry', 5)
        await self.inventory('pinap_berry', 4)
        before = await self.rows('SELECT * FROM inventory ORDER BY item_id')
        with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
            result = await self.chain_step(run)
        self.assertEqual(await self.rows('SELECT * FROM inventory ORDER BY item_id'), before)
        receipt = (await self.rows("SELECT * FROM action_receipts WHERE action='arena_fight'"))[0]
        self.assertEqual(json.loads(receipt['result']), {k: v for k, v in result.items() if k not in ('run', 'stop', 'position')})
        self.assertEqual(set(json.loads(receipt['result'])), {'status', 'outcome', 'reason', 'ticks', 'engine',
                          'floor', 'slot', 'enemy', 'party_hp', 'revived', 'finisher', 'candy', 'tickets'})
        self.assertEqual((receipt['key'], receipt['profile_id']), (f"arena_fight:{run['run_id']}:1:0", self.pid))
        self.assertEqual(await self.rows("SELECT * FROM resource_ledger WHERE resource='item'"), [])

    async def test_boss_win_writes_month_score_other_fights_do_not(self):
        run = (await self.start())['run']
        self.assertEqual(await self.rows('SELECT * FROM arena_month_scores'), [])
        with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
            for _ in range(2):
                await self.fight(run)
                run = (await self.state())['run']
                self.assertEqual(await self.rows('SELECT * FROM arena_month_scores'), [])
            result = await self.fight(run)
        self.assertEqual(await self.rows('SELECT * FROM arena_month_scores'), [
            dict(guild_id='g', month='1970-01', profile_id=self.pid, floor=1, reached_at=1300)])
        self.assertEqual(result['floor'], 1)
        for outcome in ('loss', 'draw'):
            await self.reset_run_fixture()
            await self.conn.execute('DELETE FROM arena_month_scores')
            run = await self.at_fight(slot=2)
            with patch.object(battle_engine, 'simulate', return_value=self.outcome(outcome, hp=(0, 0, 0), finisher=None)):
                self.assertEqual((await self.fight(run))['status'], 'defeated')
            self.assertEqual(await self.rows('SELECT * FROM arena_month_scores'), [])

    async def test_higher_floor_replaces_score_else_floor_and_time_stay(self):
        with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
            for floor, now, expected_floor, expected_time in ((5, 1300, 5, 1300), (5, 1400, 5, 1300),
                                                            (4, 1500, 5, 1300), (6, 1600, 6, 1600)):
                with self.subTest(floor=floor, now=now):
                    await self.reset_run_fixture()
                    await self.fight(await self.at_fight(floor=floor, slot=2), now=now)
                    self.assertEqual(await self.rows('SELECT * FROM arena_month_scores'), [
                        dict(guild_id='g', month='1970-01', profile_id=self.pid,
                             floor=expected_floor, reached_at=expected_time)])

    async def test_run_crossing_utc_month_scores_in_new_month(self):
        boundary = 1735689600  # 2025-01-01 00:00 UTC.
        run = await self.at_fight(slot=2)
        await self.conn.execute('UPDATE arena_runs SET started_at=?', (boundary - 100,))
        with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
            for now in (boundary - 1, boundary, boundary + 1, boundary + 2):
                await self.fight(run, now=now)
                run = (await self.state(now=now))['run']
        self.assertEqual(await self.rows('SELECT month,floor,reached_at FROM arena_month_scores ORDER BY month'),
                         [dict(month='2024-12', floor=1, reached_at=boundary - 1),
                          dict(month='2025-01', floor=2, reached_at=boundary + 2)])
        self.assertEqual(self.service().month_key(boundary - 1), '2024-12')
        self.assertEqual(self.service().month_key(boundary), '2025-01')

    async def test_skip_writes_no_score_first_score_is_floor_41(self):
        run = (await self.skip_start())['run']
        self.assertEqual(await self.rows('SELECT * FROM arena_month_scores'), [])
        with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
            for slot in range(3):
                self.assertEqual(run['slot'], slot)
                await self.fight(run)
                run = (await self.state())['run']
                if slot < 2:
                    self.assertEqual(await self.rows('SELECT * FROM arena_month_scores'), [])
        self.assertEqual(await self.scalar('SELECT floor FROM arena_month_scores'), 41)

    async def test_chain_step_and_heal_all_boss_wins_score(self):
        for action, floor in (('chain', 1), ('heal', 2)):
            with self.subTest(action=action):
                await self.reset_run_fixture()
                run = await self.at_fight(floor=floor, slot=2)
                if action == 'heal':
                    run = await self.hurt(run)
                    await self.inventory('razz_berry', 3)
                with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
                    result = await self.chain_step(run) if action == 'chain' else await self.fight(run, berry='razz_berry')
                self.assertEqual(result['status'], 'won')
                self.assertEqual(await self.scalar('SELECT floor FROM arena_month_scores'), floor)
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='razz_berry'"), 0)

    async def test_boss_score_rolls_back_when_ledger_write_fails(self):
        run = await self.at_fight(slot=2)
        await self.conn.execute("CREATE TRIGGER fail_score BEFORE INSERT ON resource_ledger "
                                "BEGIN SELECT RAISE(ABORT,'boss ledger failure'); END")
        before = await self.snapshot()
        with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
            with self.assertRaisesRegex(Exception, 'boss ledger failure'):
                await self.fight(run)
        self.assertEqual(await self.snapshot(), before)

    async def test_replayed_boss_fight_scores_once(self):
        run = await self.at_fight(slot=2)
        with patch.object(battle_engine, 'simulate', return_value=self.outcome()) as simulate:
            results = await asyncio.gather(self.fight(run), self.fight(run))
        self.assertEqual([result['status'] for result in results], ['won', 'stale'])
        self.assertEqual(simulate.call_count, 1)
        scores = await self.rows('SELECT * FROM arena_month_scores')
        self.assertEqual(len(scores), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts WHERE action='arena_fight'"), 1)
        # Recreate the pre-fight screen to exercise receipt replay as well as the stale guard.
        await self.conn.execute('UPDATE arena_runs SET floor=1,slot=2,revision=? WHERE run_id=?',
                                (run['revision'], run['run_id']))
        before = await self.snapshot()
        with patch.object(battle_engine, 'simulate', side_effect=AssertionError('replay fought')):
            self.assertEqual(await self.fight(run, now=1400), results[0])
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.rows('SELECT * FROM arena_month_scores'), scores)

    async def test_floor_1_boss_win_advances_without_ticket(self):
        run = await self.at_fight(slot=2)
        with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
            result = await self.fight(run)
        self.assertEqual((result['status'], result['floor'], result['slot'], result['tickets']), ('won', 1, 2, None))
        current = await self.state()
        self.assertEqual((current['run']['floor'], current['run']['slot'], current['best_floor']), (2, 0, 1))
        self.assertEqual(await self.rows('SELECT * FROM arena_tickets'), [])

    async def test_win_carries_exact_hp_into_next_fight(self):
        run = await self.at_fight()
        rules, chart = load_table('battle')['rules'], CONTENT['type_chart']
        party = [battle_engine.Combatant(**m['snapshot']['combatant']) for m in run['team']]
        enemy = battle_engine.Combatant(**run['enemy']['snapshot']['combatant'])
        expected = battle_engine.simulate(party, enemy, run['enemy']['battle_hp'], rules=rules, chart=chart)
        with patch.object(battle_engine, 'simulate', wraps=battle_engine.simulate) as simulate:
            result = await self.fight(run)
            self.assertEqual(result['status'], 'won')
            self.assertEqual(simulate.call_args.args[0], party)
            self.assertEqual(simulate.call_args.args[1:], (enemy, run['enemy']['battle_hp']))
            self.assertEqual(result['party_hp'], list(expected.party_hp))
            next_run = (await self.state())['run']
            self.assertEqual([m['hp'] for m in next_run['team']], domain.revive(expected.party_hp))
            await self.fight(next_run)
            self.assertEqual([m.hp for m in simulate.call_args.args[0]], domain.revive(expected.party_hp))
        self.assertEqual(len(party), 3)
        self.assertEqual(rules['party_max'], 1)

    async def test_fainted_member_revived_at_one_hp_keeps_position(self):
        run = await self.at_fight()
        with patch.object(battle_engine, 'simulate', return_value=self.outcome(hp=(0, 2, 5))):
            result = await self.fight(run)
        self.assertEqual((result['party_hp'], result['revived']), ([0, 2, 5], [0]))
        after = (await self.state())['run']
        self.assertEqual([m['uid'] for m in after['team']], [m['uid'] for m in run['team']])
        self.assertEqual([m['hp'] for m in after['team']], [1, 2, 5])

    async def test_entry_middle_boss_order_and_next_enemy_stored_each_fight(self):
        run = await self.at_fight()
        roll_enemy = self.service()._roll_enemy
        with patch.object(battle_engine, 'simulate', return_value=self.outcome()), \
                patch.object(self.service(), '_roll_enemy', wraps=roll_enemy) as roll:
            for slot, next_floor, next_slot in ((0, 1, 1), (1, 1, 2), (2, 2, 0)):
                result = await self.fight(run)
                self.assertEqual((result['floor'], result['slot']), (1, slot))
                current = (await self.state())['run']
                self.assertEqual((current['floor'], current['slot'], current['revision']),
                                 (next_floor, next_slot, slot + 1))
                self.assertEqual(roll.call_args.args[:2], (next_floor, next_slot))
                expected = roll_enemy(next_floor, next_slot, random.Random(11), CONTENT, MULTIPLIERS)
                self.assertEqual(current['enemy'], json.loads(json.dumps(expected)))
                self.assertEqual((await self.state())['run'], current)
                run = current
            self.assertEqual(roll.call_count, 3)

    async def test_loss_ends_run_keeps_earlier_tickets(self):
        run = await self.at_fight(floor=11, slot=1)
        await self.conn.execute("INSERT INTO arena_tickets VALUES (?,'silver',2)", (self.pid,))
        await self.conn.execute('UPDATE profiles SET arena_best_floor=10')
        with patch.object(battle_engine, 'simulate', return_value=self.outcome('loss', (0, 0, 0), None)), \
                patch.object(self.service(), '_roll_enemy', side_effect=AssertionError('loss rolled enemy')):
            result = await self.fight(run)
        self.assertEqual((result['status'], result['outcome'], result['candy'], result['tickets']),
                         ('defeated', 'loss', None, None))
        current = await self.state()
        self.assertEqual(current['status'], 'ended')
        self.assertEqual((current['run']['ended_at'], current['run']['end_reason'], current['run']['revision']),
                         (1300, 'loss', 1))
        self.assertEqual([m['hp'] for m in current['run']['team']], [0, 0, 0])
        self.assertEqual((current['best_floor'], current['tickets']), (10, {'silver': 2}))
        self.assertEqual(await self.rows('SELECT * FROM candy'), [])
        self.assertEqual(await self.rows('SELECT * FROM resource_ledger'), [])

    async def test_draw_counts_as_defeat(self):
        run = await self.at_fight()
        with patch.object(battle_engine, 'simulate', return_value=self.outcome('draw', (0, 0, 0), 2)):
            result = await self.fight(run)
        self.assertEqual((result['status'], result['outcome'], result['revived']), ('defeated', 'draw', []))
        self.assertEqual((await self.state())['run']['end_reason'], 'draw')
        self.assertEqual(await self.rows('SELECT * FROM candy'), [])

    async def test_fight_after_hour_18_refused_run_expired(self):
        run = await self.hurt(await self.at_fight())
        await self.inventory('razz_berry', 3)
        before = await self.snapshot()
        with patch.object(battle_engine, 'simulate', side_effect=AssertionError('expired run fought')):
            self.assertEqual((await self.fight(run, now=65800))['status'], 'stale')
            self.assertEqual((await self.fight(run, now=65800, berry='razz_berry'))['status'], 'stale')
        before['arena_runs'][0].update(ended_at=65800, end_reason='expired', revision=1)
        self.assertEqual(await self.snapshot(), before)

    async def test_same_fight_never_resolves_twice(self):
        run = await self.at_fight()
        with patch.object(battle_engine, 'simulate', wraps=battle_engine.simulate) as simulate:
            results = await asyncio.gather(self.fight(run), self.fight(run))
            self.assertEqual([r['status'] for r in results], ['won', 'stale'])
            self.assertEqual(simulate.call_count, 1)
            before = await self.snapshot()
            self.assertEqual((await self.fight(run))['status'], 'stale')
            self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts WHERE action='arena_fight'"), 1)
        self.assertEqual(await self.scalar('SELECT quantity FROM candy WHERE profile_id=?', (self.pid,)), 1)

    async def test_regular_finisher_earns_one_candy_per_win_with_ledger_line(self):
        run = await self.at_fight()
        await self.conn.execute('INSERT INTO candy VALUES (?,1,7)', (self.pid,))
        with patch.object(battle_engine, 'simulate', return_value=self.outcome(finisher=2)):
            result = await self.fight(run)
        self.assertEqual(result['candy'], {'family_id': 1, 'quantity': 1})
        self.assertEqual(await self.scalar('SELECT quantity FROM candy WHERE profile_id=?', (self.pid,)), 8)
        self.assertEqual(await self.rows('SELECT profile_id,resource,resource_id,delta,reason FROM resource_ledger'),
                         [{'profile_id': self.pid, 'resource': 'candy', 'resource_id': '1',
                           'delta': 1, 'reason': 'arena_candy'}])

    async def test_special_finisher_earns_candy_only_on_boss(self):
        for slot in (0, 1, 2):
            with self.subTest(slot=slot):
                await self.reset_run_fixture()
                run = await self.at_fight(slot=slot, special=True)
                with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
                    result = await self.fight(run)
                amount = 1 if slot == 2 else 0
                candy = await self.rows('SELECT family_id,quantity FROM candy')
                self.assertEqual(candy, [{'family_id': run['team'][0]['family_id'], 'quantity': 1}] if amount else [])
                self.assertEqual(result['candy'], {'family_id': run['team'][0]['family_id'], 'quantity': 1}
                                 if amount else None)

    async def test_regular_nonleading_finisher_gets_candy_with_special_leader(self):
        for slot in (0, 1, 2):
            with self.subTest(slot=slot):
                await self.reset_run_fixture()
                await self.conn.execute("UPDATE pokemon SET pokemon_id=4 WHERE pokemon_uid='m2'")
                run = await self.at_fight(slot=slot, special=True)
                leader, finisher = run['team'][0], run['team'][2]
                self.assertTrue(leader['special'])
                self.assertFalse(finisher['special'])
                self.assertNotEqual(leader['family_id'], finisher['family_id'])
                for member, quantity in ((leader, 5), (finisher, 7)):
                    await self.conn.execute('INSERT INTO candy VALUES (?,?,?)',
                                            (self.pid, member['family_id'], quantity))
                with patch.object(battle_engine, 'simulate', return_value=self.outcome(finisher=2)):
                    result = await self.fight(run)
                self.assertEqual(result['finisher'], 2)
                self.assertEqual(result['candy'], {'family_id': finisher['family_id'], 'quantity': 1})
                self.assertEqual({row['family_id']: row['quantity'] for row in
                                  await self.rows('SELECT family_id,quantity FROM candy')},
                                 {leader['family_id']: 5, finisher['family_id']: 8})
                self.assertEqual(await self.rows('SELECT profile_id,resource,resource_id,delta,reason '
                                                 'FROM resource_ledger'),
                                 [{'profile_id': self.pid, 'resource': 'candy',
                                   'resource_id': str(finisher['family_id']), 'delta': 1, 'reason': 'arena_candy'}])

    async def test_special_nonleading_finisher_gets_candy_only_on_boss_with_regular_leader(self):
        for slot in (0, 1, 2):
            with self.subTest(slot=slot):
                await self.reset_run_fixture()
                await self.conn.execute("UPDATE pokemon SET pokemon_id=144 WHERE pokemon_uid='m1'")
                run = await self.at_fight(slot=slot)
                leader, finisher = run['team'][0], run['team'][1]
                self.assertFalse(leader['special'])
                self.assertTrue(finisher['special'])
                self.assertNotEqual(leader['family_id'], finisher['family_id'])
                for member, quantity in ((leader, 5), (finisher, 7)):
                    await self.conn.execute('INSERT INTO candy VALUES (?,?,?)',
                                            (self.pid, member['family_id'], quantity))
                with patch.object(battle_engine, 'simulate', return_value=self.outcome(finisher=1)):
                    result = await self.fight(run)
                amount = 1 if slot == 2 else 0
                self.assertEqual(result['finisher'], 1)
                self.assertEqual(result['candy'], {'family_id': finisher['family_id'], 'quantity': 1}
                                 if amount else None)
                self.assertEqual({row['family_id']: row['quantity'] for row in
                                  await self.rows('SELECT family_id,quantity FROM candy')},
                                 {leader['family_id']: 5, finisher['family_id']: 7 + amount})
                self.assertEqual(await self.rows('SELECT profile_id,resource,resource_id,delta,reason '
                                                 'FROM resource_ledger'),
                                 [{'profile_id': self.pid, 'resource': 'candy',
                                   'resource_id': str(finisher['family_id']), 'delta': 1, 'reason': 'arena_candy'}]
                                 if amount else [])

    async def test_candy_goes_to_snapshot_family_after_mid_run_evolution(self):
        run = await self.at_fight()
        await self.conn.execute("UPDATE pokemon SET pokemon_id=2,revision=revision+1 WHERE pokemon_uid='m0'")
        identify = storage.identify

        def frozen_only(content, pokemon):
            self.assertIsNone(pokemon['pokemon_uid'], 'battle consulted a current storage identity')
            return identify(content, pokemon)

        with patch.object(storage, 'identify', side_effect=frozen_only), \
                patch.object(battle_engine, 'simulate', return_value=self.outcome()):
            result = await self.fight(run)
        self.assertEqual(result['candy'], {'family_id': run['team'][0]['family_id'], 'quantity': 1})
        self.assertEqual((await self.state())['run']['team'][0]['snapshot'], run['team'][0]['snapshot'])

    async def test_boss_win_credits_scheduled_ticket(self):
        for floor, tier in ((5, 'bronze'), (10, 'silver'), (25, 'gold'), (50, 'platinum'), (80, 'diamond')):
            with self.subTest(floor=floor):
                await self.reset_run_fixture()
                run = await self.at_fight(floor=floor, slot=2)
                await self.conn.execute('INSERT INTO arena_tickets VALUES (?,?,3)', (self.pid, tier))
                with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
                    result = await self.fight(run)
                copies = 1 if tier == 'bronze' else 2
                self.assertEqual(result['tickets'], {'tier': tier, 'copies': copies, 'first_clear': tier != 'bronze'})
                current = await self.state()
                self.assertEqual((current['best_floor'], current['tickets'][tier]), (floor, 3 + copies))
                self.assertEqual(await self.rows("SELECT resource,resource_id,delta,reason FROM resource_ledger "
                                                 "WHERE resource='arena_ticket'"),
                                 [{'resource': 'arena_ticket', 'resource_id': tier, 'delta': copies,
                                   'reason': 'arena_floor'}])

    async def test_first_clear_bonus_once_for_silver_or_better_not_bronze(self):
        for floor, tier in ((5, 'bronze'), (10, 'silver'), (25, 'gold'), (50, 'platinum'), (80, 'diamond')):
            for best in (0, floor, floor + 5):
                with self.subTest(floor=floor, best=best):
                    await self.reset_run_fixture()
                    run = await self.at_fight(floor=floor, slot=2)
                    await self.conn.execute('UPDATE profiles SET arena_best_floor=? WHERE profile_id=?', (best, self.pid))
                    with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
                        result = await self.fight(run)
                    bonus = best < floor and tier != 'bronze'
                    self.assertEqual(result['tickets'], {'tier': tier, 'copies': 1 + bonus, 'first_clear': bonus})
                    self.assertEqual((await self.state())['best_floor'], max(best, floor))

    async def test_heal_all_and_fight_all_or_nothing_reports_short(self):
        run = await self.hurt(await self.at_fight())
        await self.inventory('razz_berry', 2)
        before = await self.snapshot()
        with patch.object(battle_engine, 'simulate', side_effect=AssertionError('short heal fought')):
            self.assertEqual(await self.fight(run, berry='razz_berry'), {'status': 'missing', 'short': 1})
        self.assertEqual(await self.snapshot(), before)
        await self.inventory('razz_berry', 3)
        with patch.object(battle_engine, 'simulate', wraps=battle_engine.simulate) as simulate:
            self.assertEqual((await self.fight(run, berry='razz_berry'))['status'], 'won')
            self.assertEqual([m.hp for m in simulate.call_args.args[0]], [m['full_hp'] for m in run['team']])
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='razz_berry'"), 0)
        self.assertEqual((await self.state())['run']['revision'], 2)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts WHERE action='arena_heal'"), 1)

    async def test_paused_member_can_fight_excluded_cannot(self):
        run = await self.at_fight()
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('g','u',1)")
        await self.conn.execute('UPDATE guilds SET arena_enabled=0')
        self.assertEqual((await self.fight(run))['status'], 'won')
        run = (await self.state())['run']
        await self.conn.execute('UPDATE restrictions SET excluded=1')
        before = await self.snapshot()
        with patch.object(battle_engine, 'simulate', side_effect=AssertionError('excluded member fought')):
            self.assertEqual(await self.fight(run), {'status': 'excluded'})
            self.assertEqual(await self.fight(run, berry='razz_berry'), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_fight_receipt_holds_no_event_text_and_has_profile_id(self):
        run = await self.at_fight()
        with patch.object(battle_engine, 'simulate', return_value=self.outcome()):
            result = await self.fight(run)
        receipt = (await self.rows("SELECT * FROM action_receipts WHERE action='arena_fight'"))[0]
        self.assertEqual((receipt['key'], receipt['profile_id']), (f"arena_fight:{run['run_id']}:1:0", self.pid))
        self.assertEqual(json.loads(receipt['result']), result)
        self.assertNotIn('events', result)
        self.assertNotIn('snapshot', receipt['result'])
        self.assertNotIn('private battle event', receipt['result'])
        self.assertEqual(set(result), {'status', 'outcome', 'reason', 'ticks', 'engine', 'floor', 'slot',
                                       'enemy', 'party_hp', 'revived', 'finisher', 'candy', 'tickets'})
        self.assertEqual(result['enemy'], {'name': run['enemy']['snapshot']['combatant']['name'],
                                          'cp': run['enemy']['snapshot']['cp'],
                                          'types': run['enemy']['snapshot']['combatant']['types']})

    async def test_heal_and_fight_engine_failure_rolls_back_everything(self):
        run = await self.hurt(await self.at_fight())
        await self.inventory('razz_berry', 3)
        before = await self.snapshot()
        with patch.object(battle_engine, 'simulate', side_effect=RuntimeError('engine failed')):
            with self.assertRaisesRegex(RuntimeError, 'engine failed'):
                await self.fight(run, berry='razz_berry')
        self.assertEqual(await self.snapshot(), before)

    async def test_full_party_heal_and_fight_skips_debit_and_stale_actions_refused(self):
        run = await self.at_fight()
        before = await self.snapshot()
        self.assertEqual(await self.fight(run, berry='golden_razz_berry'), {'status': 'invalid'})
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.fight(run, berry='razz_berry'))['status'], 'won')
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts WHERE action='arena_heal'"), 0)
        self.assertEqual(await self.rows('SELECT * FROM inventory'), [])
        current = (await self.state())['run']
        before = await self.snapshot()
        for stale in (run, {**current, 'run_id': 'other-run'}):
            self.assertEqual(await self.fight(stale), {'status': 'stale', 'run': current})
            self.assertEqual(await self.fight(stale, berry='razz_berry'), {'status': 'stale', 'run': current})
        self.assertEqual(await self.snapshot(), before)

    async def month_score(self, profile_id=None, *, month='2026-11', floor=10, reached_at=100, guild_id='g'):
        await self.conn.execute('INSERT INTO arena_month_scores VALUES (?,?,?,?,?)',
                                (guild_id, month, profile_id or self.pid, floor, reached_at))

    async def settle(self, now=MONTH_NOW, guild_id='g'):
        function = getattr(self.service(), 'settle', None)
        self.assertIsNotNone(function, 'Arena month settlement service is absent')
        return await self.writer.run(lambda conn: function(conn, guild_id, now))

    async def test_settle_pays_three_places_and_records_them(self):
        third, fourth = await self.profile('third', 'g'), await self.profile('fourth', 'g')
        ranked = [self.pid, self.other, third, fourth]
        for place, pid in enumerate(ranked, 1):
            await self.month_score(pid, floor=60 - place * 10)
        self.assertEqual(await self.settle(), ['2026-11'])
        self.assertEqual(await self.rows('SELECT * FROM arena_months'),
                         [dict(guild_id='g', month='2026-11', settled_at=MONTH_NOW)])
        self.assertEqual(await self.rows('SELECT * FROM arena_month_places ORDER BY place'), [
            dict(guild_id='g', month='2026-11', place=place, profile_id=pid, floor=60 - place * 10)
            for place, pid in enumerate(ranked[:3], 1)])
        self.assertEqual(await self.rows('SELECT profile_id,milestone_id,resource,resource_id,remaining,created_at '
                                         'FROM inbox_items ORDER BY inbox_id'), [
            dict(profile_id=pid, milestone_id=f'arena_month:2026-11:{place}', resource='item',
                 resource_id=item, remaining=1, created_at=MONTH_NOW)
            for place, pid in enumerate(ranked[:3], 1) for item in RULES['leaderboard']['rewards'][place - 1]])
        for table in ('action_receipts', 'resource_ledger', 'milestone_awards'):
            self.assertEqual(await self.scalar(f'SELECT count(*) FROM {table}'), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM arena_month_scores WHERE month='2026-11'"), 0)

    async def test_settle_repeat_or_same_month_writes_nothing(self):
        await self.month_score(month='2026-12', floor=50)
        before = await self.snapshot()
        self.assertEqual(await self.settle(), [])
        self.assertEqual(await self.snapshot(), before)
        await self.month_score()
        self.assertEqual(await self.settle(), ['2026-11'])
        before = await self.snapshot()
        self.assertEqual(await self.settle(), [])
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.scalar("SELECT count(*) FROM arena_months WHERE month='2026-12'"), 0)

    async def test_ties_rank_by_time_created_at_profile_id(self):
        a, b, high = [await self.profile(user, 'g') for user in ('a', 'b', 'high')]
        for pid, floor, reached, created in ((self.pid, 20, 30, 0), (self.other, 20, 20, 2),
                                              (a, 20, 20, 1), (b, 20, 20, 1), (high, 21, 99, 99)):
            await self.conn.execute('UPDATE profiles SET created_at=? WHERE profile_id=?', (created, pid))
            await self.month_score(pid, month='2026-12', floor=floor, reached_at=reached)
        expected = [high, *sorted((a, b)), self.other, self.pid]
        users = {self.pid: 'u', self.other: 'v', a: 'a', b: 'b', high: 'high'}
        board = await self.service().leaderboard(self.conn, 'g', self.pid, MONTH_NOW)
        self.assertEqual([row['user_id'] for row in board['rows']], [users[pid] for pid in expected])
        await self.settle(now=datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp())
        self.assertEqual([row['profile_id'] for row in await self.rows(
            'SELECT profile_id FROM arena_month_places ORDER BY place')], expected[:3])

    async def test_below_floor_10_unpaid_nobody_moves_up(self):
        await self.month_score(month='2026-10', floor=9)
        ranked = [self.pid, self.other, await self.profile('third', 'g'), await self.profile('fourth', 'g')]
        for pid, floor in zip(ranked, (11, 10, 9, 8)):
            await self.month_score(pid, floor=floor)
        self.assertEqual(await self.settle(), ['2026-10', '2026-11'])
        self.assertEqual(await self.rows('SELECT month,place,profile_id FROM arena_month_places ORDER BY place'),
                         [dict(month='2026-11', place=place, profile_id=pid)
                          for place, pid in enumerate(ranked[:2], 1)])
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 5)
        self.assertEqual(await self.scalar('SELECT count(*) FROM arena_months'), 2)

    async def test_unsettled_months_paid_oldest_first(self):
        for month in ('2026-11', '2026-09', '2026-10'):
            await self.month_score(month=month)
        expected = ['2026-09', '2026-10', '2026-11']
        self.assertEqual(await self.settle(), expected)
        self.assertEqual([row['month'] for row in await self.rows('SELECT month FROM arena_months ORDER BY rowid')],
                         expected)
        self.assertEqual([row['milestone_id'] for row in await self.rows(
            'SELECT milestone_id FROM inbox_items ORDER BY inbox_id')],
                         [f'arena_month:{month}:1' for month in expected for _ in range(3)])

    async def test_deletion_before_settlement_moves_others_up_after_leaves_gap(self):
        third, fourth = await self.profile('third', 'g'), await self.profile('fourth', 'g')
        ranked = [self.pid, self.other, third, fourth]
        for place, pid in enumerate(ranked, 1):
            await self.month_score(pid, floor=60 - place * 10)
        await self.conn.execute('DELETE FROM profiles WHERE profile_id=?', (self.pid,))
        await self.settle()
        self.assertEqual([row['profile_id'] for row in await self.rows(
            'SELECT profile_id FROM arena_month_places ORDER BY place')], ranked[1:])
        await self.conn.execute('DELETE FROM profiles WHERE profile_id=?', (self.other,))
        board = await self.service().leaderboard(self.conn, 'g', third, MONTH_NOW)
        self.assertEqual(board['last'], [dict(place=2, user_id='third', floor=30),
                                        dict(place=3, user_id='fourth', floor=20)])
        before = await self.snapshot()
        self.assertEqual(await self.settle(), [])
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.scalar('SELECT count(*) FROM arena_months'), 1)

    async def test_settle_ignores_arena_off_pause_other_guilds(self):
        foreign = await self.profile('foreign', 'h')
        await self.month_score(floor=30)
        await self.month_score(self.other, floor=20)
        await self.month_score(foreign, guild_id='h', floor=100)
        await self.conn.execute('UPDATE guilds SET arena_enabled=0')
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('g','v',1)")
        self.assertEqual(await self.settle(), ['2026-11'])
        self.assertEqual([row['profile_id'] for row in await self.rows(
            'SELECT profile_id FROM arena_month_places ORDER BY place')], [self.pid, self.other])
        self.assertEqual(await self.rows('SELECT guild_id FROM arena_months'), [dict(guild_id='g')])
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items WHERE profile_id=?', (foreign,)), 0)
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items WHERE profile_id=?', (self.other,)), 2)

    async def test_excluded_player_unranked_next_moves_up(self):
        third, fourth = await self.profile('third', 'g'), await self.profile('fourth', 'g')
        for pid, floor in zip((self.pid, self.other, third, fourth), (40, 30, 20, 10)):
            await self.month_score(pid, floor=floor)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,excluded) VALUES ('g','u',1,1)")
        active = await self.service().leaderboard(self.conn, 'g', self.pid,
                                                 datetime(2026, 11, 15, tzinfo=timezone.utc).timestamp())
        self.assertEqual(active['viewer'], None)
        self.assertEqual([row['user_id'] for row in active['rows']], ['v', 'third', 'fourth'])
        await self.settle()
        self.assertEqual([row['profile_id'] for row in await self.rows(
            'SELECT profile_id FROM arena_month_places ORDER BY place')], [self.other, third, fourth])
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items WHERE profile_id=?', (self.pid,)), 0)

    async def test_claim_holds_reward_while_rare_pocket_full(self):
        await self.month_score()
        await self.inventory('poke_ball', limits()['bag_units'])
        for item in RULES['leaderboard']['rewards'][0]:
            await self.inventory(item, 1)
        await self.settle()
        claimed = await self.writer.run(lambda conn: milestones.claim(conn, self.session, MONTH_NOW))
        self.assertEqual(claimed['moved'], dict(item=0, stardust=0, candy=0))
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 3)
        await self.inventory('master_ball', 0)
        claimed = await self.writer.run(lambda conn: milestones.claim(
            conn, {**self.session, 'revision': 6}, MONTH_NOW + 1))
        self.assertEqual(claimed['moved'], dict(item=1, stardust=0, candy=0))
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 2)
        self.assertEqual(await self.rows('SELECT resource_id,delta,reason FROM resource_ledger'),
                         [dict(resource_id='master_ball', delta=1, reason='milestone_claim')])

    async def test_leaderboard_rows_viewer_reset_and_last_month(self):
        ranked = []
        for n in range(12):
            pid = self.pid if n == 11 else await self.profile(f'rank{n}', 'g')
            ranked.append(pid)
            await self.month_score(pid, month='2026-12', floor=100 - n)
        for place, pid, floor in ((1, self.other, 20), (3, self.pid, 10)):
            await self.conn.execute("INSERT INTO arena_month_places VALUES ('g','2026-11',?,?,?)", (place, pid, floor))
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('g','u',1)")
        reader = await db.open_reader(self.path)
        self.addAsyncCleanup(reader.close)
        before = self.conn.total_changes
        board = await self.service().leaderboard(reader, 'g', self.pid, MONTH_NOW)
        self.assertEqual(set(board), {'month', 'rows', 'viewer', 'reset_at', 'last_month', 'last'})
        self.assertEqual(board['month'], '2026-12')
        self.assertEqual(board['rows'], [dict(place=n + 1, user_id=f'rank{n}', floor=100 - n) for n in range(10)])
        self.assertEqual(board['viewer'], dict(place=12, floor=89))
        self.assertEqual(board['reset_at'], datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp())
        self.assertEqual(board['last_month'], '2026-11')
        self.assertEqual(board['last'], [dict(place=1, user_id='v', floor=20), dict(place=3, user_id='u', floor=10)])
        self.assertIsNone((await self.service().leaderboard(reader, 'g', ranked[0], MONTH_NOW))['viewer'])
        self.assertEqual(self.conn.total_changes, before)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','v',1)")
        self.assertEqual((await self.service().leaderboard(reader, 'g', self.pid, MONTH_NOW))['last'],
                         [dict(place=3, user_id='u', floor=10)])
        january = await self.service().leaderboard(reader, 'g', self.pid, board['reset_at'])
        self.assertEqual(january['month'], '2027-01')
        self.assertEqual(january['last_month'], '2026-12')
        self.assertEqual(january['reset_at'], datetime(2027, 2, 1, tzinfo=timezone.utc).timestamp())
        self.assertEqual(january['rows'], [])
        self.assertIsNone(january['viewer'])

    async def test_settle_requires_writer_transaction(self):
        function = getattr(self.service(), 'settle', None)
        self.assertIsNotNone(function, 'Arena month settlement service is absent')
        await self.month_score()
        before = await self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await function(self.conn, 'g', MONTH_NOW)
        self.assertEqual(await self.snapshot(), before)

    async def test_settle_failure_rolls_back_inbox_places_and_month_guard(self):
        await self.month_score()
        await self.conn.execute("CREATE TRIGGER fail_month BEFORE INSERT ON inbox_items "
                                "WHEN NEW.resource_id='shiny_lure' BEGIN SELECT RAISE(ABORT,'month failure'); END")
        before = await self.snapshot()
        with self.assertRaisesRegex(Exception, 'month failure'):
            await self.settle()
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('DROP TRIGGER fail_month')
        self.assertEqual(await self.settle(), ['2026-11'])
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 3)

    async def ticket(self, tier, quantity=1):
        await self.conn.execute('INSERT INTO arena_tickets VALUES (?,?,?) '
                                'ON CONFLICT(profile_id,tier) DO UPDATE SET quantity=excluded.quantity',
                                (self.pid, tier, quantity))

    async def redeem(self, tier='bronze', free=3, add=None, rng=None, session=None):
        if add is None:
            count = RULES['tickets']['tiers'][tier]['encounters']
            add = free if count == 'fill' else min(free, count)
        return await self.writer.run(lambda conn: self.service().redeem(
            conn, session or self.session, tier, free, add, 1200, rng or random.Random(7), CONTENT))

    async def queue(self, count=1):
        profile = await profiles.get_profile(self.conn, 'g', 'u')
        for _ in range(count):
            await self.writer.run(lambda conn: stepping.spawn_encounter(conn, profile, CONTENT, random.Random(3), 1000))

    async def redemption_snapshot(self):
        return {**await self.snapshot(), **{table: await self.rows(f'SELECT * FROM {table} ORDER BY 1')
                                          for table in ('encounters', 'active_effects', 'inbox_items')}}

    async def test_bronze_adds_one_encounter_and_100_stardust_row(self):
        await self.ticket('bronze', 100001)
        self.assertEqual(await self.service().redeem_quote(self.conn, self.pid, 'bronze'),
                         {'held': 100001, 'free': 3, 'add': 1})
        result = await self.redeem()
        self.assertEqual((result['status'], result['encounters'], result['stardust'],
                          result['income_rolls'], result['survivor_rolls']), ('redeemed', 1, 100, 0, 0))
        encounters = await self.rows('SELECT profile_id,route_id,source_message_id FROM encounters')
        profile = await profiles.get_profile(self.conn, 'g', 'u')
        self.assertEqual(encounters, [{'profile_id': self.pid, 'route_id': profile['route_id'], 'source_message_id': None}])
        self.assertEqual(await self.rows('SELECT resource,resource_id,remaining FROM inbox_items'),
                         [{'resource': 'stardust', 'resource_id': None, 'remaining': 100}])
        self.assertEqual(await self.scalar('SELECT stardust FROM profiles WHERE profile_id=?', (self.pid,)), 0)
        self.assertEqual(await self.service().redeem_quote(self.conn, self.other, 'bronze'),
                         {'held': 0, 'free': 3, 'add': 1})

    async def test_silver_adds_up_to_two_encounters_and_gold_fills_queue(self):
        for tier, occupied, count in [('silver', 0, 2), ('silver', 2, 1), ('gold', 0, 3), ('gold', 1, 2)]:
            with self.subTest(tier=tier, occupied=occupied):
                await self.conn.execute('DELETE FROM encounters')
                await self.conn.execute('DELETE FROM action_receipts')
                await self.ticket(tier)
                await self.queue(occupied)
                quote = await self.service().redeem_quote(self.conn, self.pid, tier)
                self.assertEqual(quote, {'held': 1, 'free': 3 - occupied, 'add': count})
                result = await self.redeem(tier, free=quote['free'])
                self.assertEqual(result['encounters'], count)
                self.assertEqual(await profiles.queue_size(self.conn, self.pid), occupied + count)

    async def test_platinum_and_diamond_roll_counts_and_survivor_rows_with_500_stardust(self):
        for tier, income, survivors, dust in [('platinum', 8, 1, 1000), ('diamond', 24, 3, 3000)]:
            with self.subTest(tier=tier):
                await self.conn.execute('DELETE FROM encounters')
                await self.conn.execute('DELETE FROM action_receipts')
                await self.conn.execute('DELETE FROM inbox_items')
                await self.ticket(tier)
                result = await self.redeem(tier)
                self.assertEqual((result['encounters'], result['income_rolls'], result['survivor_rolls'],
                                  result['stardust']), (3, income, survivors, dust))
                rows = await self.rows('SELECT * FROM inbox_items')
                prefix = f"arena:{result['redeem_id']}:"
                self.assertEqual(len(rows), 1 + income + 2 * survivors)
                self.assertEqual(sum(row['milestone_id'].startswith(prefix + 'income:') for row in rows), income)
                survivor_rows = [row for row in rows if row['milestone_id'].startswith(prefix + 'survivor:')]
                self.assertEqual(len({row['milestone_id'] for row in survivor_rows}), survivors)
                self.assertEqual([row['remaining'] for row in survivor_rows if row['resource'] == 'stardust'],
                                 [500] * survivors)

    async def test_redeem_refused_when_queue_full_nothing_spent(self):
        await self.ticket('diamond')
        await self.queue(3)
        before = await self.redemption_snapshot()
        self.assertEqual(await self.redeem('diamond'), {'status': 'queue_full'})
        self.assertEqual(await self.redemption_snapshot(), before)

    async def test_quote_changed_spends_no_ticket_and_no_lure_charge(self):
        await self.ticket('silver')
        await self.conn.execute('INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,receipt_key,remaining_encounters) '
                                "VALUES ('lure',?,'shiny_lure',0,'lure-key',10)", (self.pid,))
        await self.queue()
        before = await self.redemption_snapshot()
        for free, add in [(3, 2), (2, 1)]:
            self.assertEqual(await self.redeem('silver', free=free, add=add),
                             {'status': 'quote_changed', 'free': 2, 'add': 2})
            self.assertEqual(await self.redemption_snapshot(), before)

    async def test_same_redeem_press_twice_one_redemption(self):
        await self.ticket('bronze', 2)
        results = await asyncio.gather(self.redeem(), self.redeem())
        self.assertEqual([result['status'] for result in results], ['redeemed', 'quote_changed'])
        self.assertEqual(await self.scalar('SELECT quantity FROM arena_tickets'), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM action_receipts'), 1)
        self.assertEqual(await profiles.queue_size(self.conn, self.pid), 1)
        # Once queue space matches again, the same press replays instead of spending another ticket.
        await self.conn.execute('DELETE FROM encounters')
        before = await self.redemption_snapshot()
        self.assertEqual(await self.redeem(), results[0])
        self.assertEqual(await self.redemption_snapshot(), before)

    async def test_inbox_keys_use_redeem_id_and_claim_respects_rare_pockets(self):
        await self.ticket('platinum')
        await self.inventory('master_ball', 1)
        await self.inventory('poke_ball', limits()['bag_units'])
        original_choices = random.Random.choices

        def select(rng, population, *args, **kwargs):
            if population == load_table('gym_income_table')['rows']:
                return [next(row for row in population if row['item'] == 'poke_ball')]
            if population == load_table('survivor_table')['rows']:
                return [next(row for row in population if row['item'] == 'master_ball')]
            return original_choices(rng, population, *args, **kwargs)

        with patch.object(random.Random, 'choices', select):
            result = await self.redeem('platinum')
        rows = await self.rows('SELECT * FROM inbox_items')
        self.assertEqual(len({row['milestone_id'] for row in rows}), 10)
        self.assertTrue(all(row['milestone_id'].startswith(f"arena:{result['redeem_id']}:") for row in rows))
        claimed = await self.writer.run(lambda conn: milestones.claim(conn, self.session, 1300))
        self.assertEqual(claimed['moved'], {'item': 0, 'stardust': 1500, 'candy': 0})
        waiting = await self.rows('SELECT * FROM inbox_items')
        self.assertEqual(len(waiting), 9)
        self.assertEqual(sum(row['remaining'] for row in waiting if row['resource_id'] == 'master_ball'), 1)
        await self.conn.execute("UPDATE inventory SET quantity=0 WHERE item_id='master_ball'")
        claimed = await self.writer.run(lambda conn: milestones.claim(conn, {**self.session, 'revision': 6}, 1400))
        self.assertEqual(claimed['moved']['item'], 1)

    async def test_paused_and_arena_off_can_redeem_excluded_cannot(self):
        await self.ticket('bronze', 2)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,excluded) VALUES ('g','u',1,1)")
        await self.conn.execute('UPDATE guilds SET arena_enabled=0')
        before = await self.redemption_snapshot()
        self.assertEqual(await self.redeem(), {'status': 'excluded'})
        self.assertEqual(await self.redemption_snapshot(), before)
        await self.conn.execute('UPDATE restrictions SET excluded=0')
        self.assertEqual((await self.redeem())['status'], 'redeemed')

    async def test_redeem_receipt_and_ledger_carry_profile_id(self):
        await self.ticket('bronze')
        await self.redeem()
        receipt = (await self.rows('SELECT key,action,profile_id FROM action_receipts'))[0]
        self.assertEqual(receipt, {'key': 'arena_redeem:s:4', 'action': 'arena_redeem', 'profile_id': self.pid})
        self.assertEqual(await self.rows('SELECT profile_id,resource,resource_id,delta,reason FROM resource_ledger'),
                         [{'profile_id': self.pid, 'resource': 'arena_ticket', 'resource_id': 'bronze',
                           'delta': -1, 'reason': 'arena_redeem'}])

    async def test_redeem_matches_walking_lure_mirror_and_charm(self):
        await self.conn.execute("UPDATE profiles SET companion_uid='m0' WHERE profile_id=?", (self.pid,))
        await self.conn.execute("INSERT INTO milestone_awards VALUES (?,'pokedex:100',0)", (self.pid,))
        columns = 'pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,tier,route_id,lure_id,content_version'
        for kind in (None, 'shiny_lure', 'companion_mirror'):
            with self.subTest(kind=kind):
                await self.conn.execute('DELETE FROM encounters')
                await self.conn.execute('DELETE FROM action_receipts')
                await self.conn.execute('DELETE FROM active_effects')
                await self.ticket('bronze')
                if kind:
                    await self.conn.execute('INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,'
                                            "receipt_key,remaining_encounters) VALUES ('effect',?,?,0,'effect-key',10)",
                                            (self.pid, kind))
                profile = await profiles.get_profile(self.conn, 'g', 'u')
                await self.writer.run(lambda conn: stepping.spawn_encounter(conn, profile, CONTENT, random.Random(7), 1200))
                expected = await self.rows(f'SELECT {columns} FROM encounters')
                await self.conn.execute('DELETE FROM encounters')
                await self.conn.execute('UPDATE active_effects SET remaining_encounters=10')
                await self.redeem()
                self.assertEqual(await self.rows(f'SELECT {columns} FROM encounters'), expected)
                if kind:
                    self.assertEqual(await self.scalar('SELECT remaining_encounters FROM active_effects'), 9)

    async def test_redeem_ledger_failure_rolls_back_ticket_encounters_effects_and_inbox(self):
        await self.ticket('diamond')
        await self.conn.execute('INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,receipt_key,remaining_encounters) '
                                "VALUES ('lure',?,'shiny_lure',0,'lure-key',10)", (self.pid,))
        await self.conn.execute("CREATE TRIGGER fail_redemption BEFORE INSERT ON resource_ledger "
                                "BEGIN SELECT RAISE(ABORT,'redemption ledger failure'); END")
        before = await self.redemption_snapshot()
        with self.assertRaisesRegex(Exception, 'redemption ledger failure'):
            await self.redeem('diamond')
        self.assertEqual(await self.redemption_snapshot(), before)

    async def test_redeem_stale_none_invalid_and_writer_guards(self):
        before = await self.redemption_snapshot()
        self.assertEqual(await self.redeem(session={**self.session, 'profile_id': self.other}), {'status': 'stale'})
        self.assertEqual(await self.redeem(), {'status': 'none'})
        self.assertEqual(await self.redeem(tier='unknown', add=1), {'status': 'invalid'})
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await self.service().redeem(self.conn, self.session, 'bronze', 3, 1, 1200, random.Random(7), CONTENT)
        self.assertEqual(await self.redemption_snapshot(), before)
