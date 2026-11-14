"""C3 Arena lifecycle: real SQLite transactions, frozen snapshots and berry debits."""

import asyncio
import importlib
import json
from pathlib import Path
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

    async def reset_run_fixture(self):
        await self.conn.execute('DELETE FROM arena_runs')
        await self.conn.execute('DELETE FROM action_receipts')
        await self.conn.execute('DELETE FROM arena_tickets')
        await self.conn.execute('DELETE FROM candy')
        await self.conn.execute('UPDATE profiles SET arena_best_floor=0')

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
