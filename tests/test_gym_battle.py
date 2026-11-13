"""C3 battle settlement against real SQLite and the C7 deterministic engine."""

import copy
import json
import random
import sqlite3
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from content.balance import load_table
from pokewalker import db
from pokewalker.domain import battle as engine
import test_gyms
import test_gym_screens
import test_walker_router
from pokewalker.bot.walker import Walker, _Refused


class GymBattleTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_gyms.GymTests.scalar
    profile = test_gyms.GymTests.profile
    pokemon = test_gyms.GymTests.pokemon
    rows = test_gyms.GymTests.rows
    snapshot = test_gyms.GymTests.snapshot
    create = test_gyms.GymTests.create
    deploy = test_gyms.GymTests.deploy
    gyms = test_gyms.GymTests.gyms

    async def asyncSetUp(self):
        await test_gyms.GymTests.asyncSetUp(self)
        self.session['revision'] = 7
        self.defender = await self.profile('holder', 'g')
        await self.pokemon('defender', pid=self.defender)
        self.holder = {**self.session, 'session_id': 'holder', 'profile_id': self.defender, 'user_id': 'holder'}
        self.gym = await self.create()
        self.dep = (await self.deploy(self.gym, 'defender', session=self.holder))['deployment']
        for uid in ('two', 'three', 'four'):
            await self.pokemon(uid)
        self.party = [('mon', 0)]
        self.now = 1000 + 2 * 3600 + 500
        self.multipliers = load_table('cpm')['multipliers']
        self.rules = load_table('battle')['rules']
        self.chart = self.content['type_chart']

    async def fight(self, **changes):
        self.assertTrue(hasattr(self.gyms(), 'battle'), 'Battle settlement service is absent')
        args = dict(session=self.session, gym_id=self.gym['gym_id'],
                    expected_deployment_id=self.dep['deployment_id'], party=self.party,
                    nominee_uid=None, now=self.now, rng=self.rng, content=self.content,
                    multipliers=self.multipliers, rules=self.rules, chart=self.chart)
        args.update(changes)
        return await self.writer.run(lambda conn: self.gyms().battle(conn, **args))

    async def refused(self, status, **changes):
        before = await self.snapshot()
        self.assertEqual(await self.fight(**changes), {'status': status})
        self.assertEqual(await self.snapshot(), before)

    async def strong_party(self):
        await self.conn.execute("UPDATE pokemon SET level_x2=80 WHERE profile_id=?", (self.pid,))

    async def set_forms(self, attacker=10346, defender=10346):
        await self.writer.run(lambda conn: self.gyms().end_deployment(
            conn, 'g', self.dep['deployment_id'], 'recalled', self.now, self.rng, self.content))
        for uid, form_id in (('mon', attacker), ('defender', defender)):
            await self.conn.execute('UPDATE pokemon SET pokemon_id=869,form_id=? WHERE pokemon_uid=?',
                                    (form_id, uid))
        revision = await self.scalar("SELECT revision FROM pokemon WHERE pokemon_uid='defender'")
        self.dep = (await self.deploy(self.gym, 'defender', rev=revision,
                                      now=self.now, session=self.holder))['deployment']

    async def test_replaced_defender_between_preview_and_start_is_stale_no_fight(self):
        await self.writer.run(lambda conn: self.gyms().end_deployment(
            conn, 'g', self.dep['deployment_id'], 'recalled', self.now, self.rng, self.content))
        await self.deploy(self.gym, 'defender', rev=2, now=self.now, session=self.holder)
        await self.refused('stale')
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_battles'), 0)
        self.assertIsNone(await self.scalar('SELECT last_battle_at FROM profiles WHERE profile_id=?', (self.pid,)))

    async def test_cooldown_refused_no_fight(self):
        # D40b: 5 minutes since the owner decision 2026-11-12 (D62).
        await self.conn.execute('UPDATE profiles SET last_battle_at=? WHERE profile_id=?', (self.now - 299, self.pid))
        await self.refused('cooldown')
        await self.conn.execute('UPDATE profiles SET last_battle_at=? WHERE profile_id=?', (self.now - 300, self.pid))
        self.assertEqual((await self.fight())['status'], 'completed')

    async def test_party_is_one_owned_attacker_not_companion_not_deployed(self):
        # D62a: one attacker against the one defender.
        await self.pokemon('foreign', pid=self.other)
        for party in (None, [('mon',)], [('mon', True)], [], [('mon', 0)] * 2, [('mon', 0), ('two', 0)],
                      [('mon', 0), ('two', 0), ('three', 0)],
                      [('foreign', 0)], [('missing', 0)], [('defender', 1)]):
            with self.subTest(party=party):
                await self.refused('invalid', party=party)
        await self.refused('stale', party=[('mon', 1)])
        await self.conn.execute('UPDATE profiles SET companion_uid=? WHERE profile_id=?', ('mon', self.pid))
        await self.refused('invalid')
        await self.conn.execute('UPDATE profiles SET companion_uid=NULL WHERE profile_id=?', (self.pid,))
        other_gym = await self.create('Owned')
        await self.deploy(other_gym, 'two')
        await self.refused('invalid', party=[('two', 1)])
        result = await self.fight(session={**self.session, 'revision': 1}, party=[('three', 0)],
                                  rules={**self.rules, 'tick_limit': 1})
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['snapshot']['party']), 1)

    async def test_fed_defender_fights_with_healed_battle_hp(self):
        # D62b: 2 h held is 1.8x; a stored 0.2x feed brings the frozen battle HP back to 2.0x.
        await self.conn.execute('UPDATE gym_deployments SET heal_x10=2 WHERE deployment_id=?',
                                (self.dep['deployment_id'],))
        result = await self.fight(rules={**self.rules, 'tick_limit': 1})
        hp = result['snapshot']['defender']['combatant']['hp']
        self.assertEqual(result['snapshot']['defender_battle_hp'], hp * 2)
        self.assertEqual(result['snapshot']['heal_x10'], 2)

    async def test_legendary_attacks_but_cannot_be_nominee(self):
        for key in ('is_legendary', 'is_mythical'):
            identity = next(item for item in self.content['identities'] if item[key])
            await self.conn.execute("UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid='mon'", (identity['pokemon_id'],))
            await self.refused('invalid', nominee_uid='mon')
        await self.refused('invalid', nominee_uid='two')
        self.assertEqual((await self.fight())['status'], 'completed')

    async def test_win_ends_deployment_defeated_pays_hours_no_survivor_deploys_nominee(self):
        await self.strong_party()
        # A prechosen fainted member remains eligible; survivors do not select the claim.
        outcome = engine.Result('win', 'defender_fainted', 3, (0,), ('won',))
        with patch.object(engine, 'simulate', return_value=outcome):
            result = await self.fight(nominee_uid='mon')
        self.assertTrue(result['claimed'])
        ended = (await self.rows('SELECT * FROM gym_deployments WHERE deployment_id=?', (self.dep['deployment_id'],)))[0]
        self.assertEqual((ended['end_reason'], ended['paid_hours'], ended['survivor_rolled']), ('defeated', 2, 0))
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 2)
        self.assertIsNone(await self.scalar("SELECT gym_deployment_id FROM pokemon WHERE pokemon_uid='defender'"))
        self.assertEqual(await self.scalar("SELECT pokemon_uid FROM gym_deployments WHERE ended_at IS NULL"), 'mon')
        self.assertEqual(await self.scalar("SELECT revision FROM pokemon WHERE pokemon_uid='mon'"), 1)

    async def test_battle_rolls_income_with_caller_rng(self):
        await self.strong_party()
        rng = Mock(wraps=random.Random(5))
        outcome = engine.Result('win', 'defender_fainted', 3, (1,), ('won',))
        with patch.object(engine, 'simulate', return_value=outcome),                 patch.object(random, 'choices', side_effect=AssertionError('module random used')):
            await self.fight(rng=rng)
        self.assertTrue(rng.choices.called)

    async def test_win_with_cap_blocked_nominee_reports_cleared_gym_empty(self):
        await self.strong_party()
        owned = await self.create('Owned')
        await self.deploy(owned, 'two')
        result = await self.fight(nominee_uid='mon')
        self.assertEqual(result['outcome'], 'win')
        self.assertFalse(result['claimed'])
        self.assertEqual(await self.rows('SELECT * FROM gym_deployments WHERE gym_id=? AND ended_at IS NULL',
                                        (self.gym['gym_id'],)), [])
        self.assertIsNone(await self.scalar("SELECT gym_deployment_id FROM pokemon WHERE pokemon_uid='mon'"))

    async def test_loss_and_draw_keep_defender_set_cooldown(self):
        before = await self.rows('SELECT * FROM pokemon')
        for i, outcome in enumerate(('loss', 'draw')):
            rules = self.rules if outcome == 'loss' else {**self.rules, 'tick_limit': 1}
            result = await self.fight(rules=rules, session={**self.session, 'revision': i}, now=self.now + 600 * i)
            self.assertEqual(result['outcome'], outcome)
            self.assertFalse(result['claimed'])
            self.assertEqual(await self.scalar('SELECT last_battle_at FROM profiles WHERE profile_id=?', (self.pid,)),
                             self.now + 600 * i)
            self.assertIsNone(await self.scalar('SELECT ended_at FROM gym_deployments'))
            self.assertEqual(await self.rows('SELECT * FROM pokemon'), before)
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_battles'), 2)

    async def test_defender_hp_frozen_at_start_hours_held(self):
        configured = copy.deepcopy(self.content)
        identity = next(item for item in configured['identities'] if item['pokemon_id'] == 1)
        identity['base_stamina'] += 20
        result = await self.fight(content=configured)
        snap = result['snapshot']
        hp = engine.combat_stats([identity[k] for k in ('base_attack', 'base_defense', 'base_stamina')],
                                 [10, 10, 10], 20, self.multipliers)[2]
        self.assertEqual(snap['hours_held'], 2)
        self.assertEqual(snap['defender']['combatant']['hp'], hp)
        self.assertEqual(snap['defender_battle_hp'], engine.defender_hp(hp, 2))
        self.assertEqual(snap['defender']['revision'], 1)
        self.assertEqual(snap['party'][0]['pokemon_uid'], 'mon')
        self.assertEqual(set(snap['ruleset_hashes']), {'content', 'multipliers', 'rules', 'chart'})
        row = (await self.rows('SELECT * FROM gym_battles'))[0]
        self.assertEqual(json.loads(row['events']), result['events'])
        self.assertEqual((row['engine'], row['deployment_id']), (engine.ENGINE_VERSION, self.dep['deployment_id']))
        self.assertEqual((row['guild_id'], row['challenger_profile_id']), ('g', self.pid))

    async def test_start_twice_and_restart_before_reply_one_battle_one_outcome(self):
        await self.strong_party()
        routed = {**self.session, 'revision': 8, '_original_revision': 7}
        first = await self.fight(session=routed, nominee_uid='mon')
        self.assertEqual(first['outcome'], 'win')
        before = await self.snapshot()
        with patch.object(self.gyms(), 'settle', side_effect=AssertionError('replay must precede settle')):
            self.assertEqual(await self.fight(nominee_uid='mon'), first)
        await self.writer.close()
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.assertEqual(await self.fight(nominee_uid='mon', now=self.now + 36000), first)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_battles'), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts WHERE action='battle'"), 1)

    async def test_snapshot_keeps_form_id_for_attacker_and_defender(self):
        await self.set_forms(defender=None)
        first = await self.fight()
        self.assertEqual(first['snapshot']['party'][0]['form_id'], 10346)
        self.assertIsNone(first['snapshot']['defender']['form_id'])
        await self.set_forms(attacker=None)
        second = await self.fight(session={**self.session, 'revision': 8}, now=self.now + 600)
        self.assertIsNone(second['snapshot']['party'][0]['form_id'])
        self.assertEqual(second['snapshot']['defender']['form_id'], 10346)
        for result in (first, second):
            saved = json.loads(await self.scalar("SELECT result FROM action_receipts "
                                                  "WHERE action='battle' AND result LIKE ?",
                                                  ('%' + result['battle_id'] + '%',)))
            self.assertEqual(saved['snapshot'], result['snapshot'])

    async def test_distinct_start_revisions_are_distinct_intentions(self):
        first = await self.fight()
        second = await self.fight(session={**self.session, 'revision': 8}, now=self.now + 600)
        self.assertNotEqual(first['battle_id'], second['battle_id'])
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_battles'), 2)
        keys = await self.rows("SELECT key FROM action_receipts WHERE action='battle' ORDER BY key")
        self.assertEqual(keys, [{'key': 'battle:s:7'}, {'key': 'battle:s:8'}])

    async def test_cannot_battle_own_gym(self):
        await self.refused('invalid', session=self.holder, party=[('mon', 0)])

    async def test_foreign_guild_gym_battle_refused_nothing_written(self):
        foreign = await self.create('Foreign', 'h')
        # Settlement would otherwise expire the defender, pay hours and roll a survivor.
        queries = []
        await self.conn.set_trace_callback(queries.append)
        for gym_id in (foreign['gym_id'], 'missing'):
            await self.refused('invalid', gym_id=gym_id, now=self.dep['ends_at'])
        await self.conn.set_trace_callback(None)
        target_reads = [sql for sql in queries if sql.startswith('SELECT * FROM gyms WHERE gym_id=')]
        self.assertTrue(target_reads)
        self.assertTrue(all("guild_id='g'" in sql for sql in target_reads))

    async def test_excluded_refused_inside_transaction(self):
        await self.fight()
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
        await self.refused('excluded')

    async def test_other_user_session_refused(self):
        await self.fight()
        await self.refused('stale', session={**self.session, 'user_id': 'holder'})
        await self.refused('stale', session={**self.session, 'guild_id': 'h'})
        await self.refused('stale', session={**self.holder, 'session_id': self.session['session_id']})

    async def test_expired_deployment_stale_rolls_back_settlement(self):
        await self.refused('stale', now=self.dep['ends_at'])

    async def test_receipt_failure_rolls_back_battle_income_return_and_claim(self):
        await self.strong_party()
        before = await self.snapshot()
        await self.conn.execute("CREATE TRIGGER fail_battle_receipt BEFORE INSERT ON action_receipts "
                                "WHEN NEW.action='battle' BEGIN SELECT RAISE(ABORT,'receipt interrupted'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt interrupted'):
            await self.fight(nominee_uid='mon')
        self.assertEqual(await self.snapshot(), before)

    async def test_requires_writer_transaction(self):
        self.assertTrue(hasattr(self.gyms(), 'battle'), 'Battle settlement service is absent')
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await self.gyms().battle(self.conn, self.session, self.gym['gym_id'], self.dep['deployment_id'],
                                    self.party, None, self.now, self.rng, self.content, self.multipliers, self.rules, self.chart)

    async def saved_privacy_battle(self):
        from pokewalker.services import marker_log
        self.pid = await self.profile('3', '1')
        self.defender = await self.profile('2', '1')
        self.other = await self.profile('3', '9')
        self.session.update(session_id='privacy', profile_id=self.pid, guild_id='1', user_id='3')
        await self.pokemon('privacy-mon', pokemon_id=4)
        await self.pokemon('privacy-defender', pid=self.defender)
        self.gym = await self.create(guild='1')
        self.dep = (await self.deploy(self.gym, 'privacy-defender', session={
            **self.session, 'session_id': 'privacy-holder', 'profile_id': self.defender, 'user_id': '2'}))['deployment']
        self.party = [('privacy-mon', 0)]
        result = await self.fight()
        preserved = {}
        for guild, pid in (('9', self.other), ('1', self.pid)):
            defender = await self.profile('5', guild)
            await self.pokemon('kept-defender-' + guild, pid=defender)
            uid = 'privacy-mon' if guild == '1' else 'kept-attacker'
            if guild == '9':
                await self.pokemon(uid, pid=pid)
            gym = await self.create('Unrelated', guild=guild)
            session = {**self.session, 'session_id': 'kept-' + guild, 'profile_id': pid, 'guild_id': guild}
            dep = (await self.deploy(gym, 'kept-defender-' + guild,
                                    session={**session, 'profile_id': defender, 'user_id': '5'}))['deployment']
            preserved[guild] = await self.fight(session=session, gym_id=gym['gym_id'],
                                                expected_deployment_id=dep['deployment_id'],
                                                party=[(uid, 0)], now=self.now + 600)
        self.kept_battles = await self.rows('SELECT * FROM gym_battles WHERE battle_id!=?', (result['battle_id'],))
        self.kept_receipts = await self.rows("SELECT * FROM action_receipts WHERE action='battle' AND key!='battle:privacy:7'")
        selection = {'phase': 'gym_result', 'gym_id': self.gym['gym_id'], 'result': result}
        for sid, payload, guild, pid, user in (
                ('direct', selection, '1', self.pid, '3'),
                ('nested', {'picks': [], 'resume': {'resume': selection}}, '1', self.pid, '3'),
                ('party', {'phase': 'gym_party', 'deployment_id': self.dep['deployment_id']}, '1', self.pid, '3'),
                ('nested-party', {'picks': [], 'resume': {'deployment_id': self.dep['deployment_id']}}, '1', self.pid, '3'),
                ('foreign', {'result': preserved['9']}, '9', self.other, '3'),
                ('other-battle', {'result': preserved['1']}, '1', self.pid, '3'),
                ('unrelated', {'picks': [['two', 0]]}, '1', self.pid, '3')):
            await self.conn.execute('INSERT INTO sessions(session_id,guild_id,user_id,profile_id,revision,expires_at,selection) '
                                    'VALUES (?,?,?,?,0,999999,?)', (sid, guild, user, pid, json.dumps(payload)))
        self.marker_path = self.path.with_suffix('.markers.jsonl')
        marker_log.create_empty(self.marker_path)
        self.kept_sessions = await self.rows("SELECT * FROM sessions WHERE session_id IN ('foreign','other-battle','unrelated')")
        return result

    async def assert_private_battle_redacted(self, original):
        from pokewalker.bot import gyms as screens
        expected = copy.deepcopy(original)
        expected.update(events=[], deployment_id=None)
        expected['snapshot'].update(defender=None, deployment=None, hours_held=None, defender_battle_hp=None)
        self.assertEqual(await self.fight(), expected)
        for sid, depth in (('direct', 0), ('nested', 2)):
            saved = json.loads(await self.scalar('SELECT selection FROM sessions WHERE session_id=?', (sid,)))
            for _ in range(depth):
                saved = saved['resume']
            self.assertEqual(saved['result'], expected)
        self.assertEqual(await self.scalar("SELECT selection FROM sessions WHERE session_id='party'"), '{}')
        self.assertEqual(await self.scalar("SELECT revision FROM sessions WHERE session_id='party'"), 1)
        nested_party = json.loads(await self.scalar("SELECT selection FROM sessions WHERE session_id='nested-party'"))
        self.assertEqual(nested_party, {'picks': [], 'resume': {}})
        self.assertEqual(await self.rows("SELECT * FROM sessions WHERE session_id IN ('foreign','other-battle','unrelated')"),
                         self.kept_sessions)
        self.assertEqual(await self.rows('SELECT * FROM gym_battles WHERE battle_id!=?', (original['battle_id'],)), self.kept_battles)
        self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='battle' AND key!='battle:privacy:7'"),
                         self.kept_receipts)
        self.assertEqual(json.loads(await self.scalar('SELECT events FROM gym_battles WHERE battle_id=?', (original['battle_id'],))), [])
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_battles'), 3)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts WHERE action='battle'"), 3)
        self.assertIsNone(await self.scalar('SELECT deployment_id FROM gym_battles WHERE battle_id=?', (original['battle_id'],)))
        state = {'session': self.session, 'result': expected, 'content': self.content, 'offset': 0}
        rendered = screens.render_result(state)['embed']
        self.assertIn('Defender details deleted', rendered.description)
        self.assertIn('Charmander', rendered.description)
        self.assertNotIn('Bulbasaur', rendered.description)
        self.assertFalse(rendered.thumbnail)
        self.assertEqual(screens.render_log(state)['embed'].description, 'No events.')
        state['result'] = {**expected, 'outcome': 'loss', 'claimed': False}
        self.assertNotIn('Defender remains', screens.render_result(state)['embed'].description)

    async def delete_private_battle(self, kind):
        from pokewalker.services import deletion
        original = await self.saved_privacy_battle()
        fields = {'actor_id': '4', 'reason': 'reset'} if kind == 'reset' else {}
        await deletion.run_marker(self.writer, self.marker_path, kind=kind, guild_id='1',
                                  user_id='2', profile_id=self.defender, now=self.now, **fields)
        await self.assert_private_battle_redacted(original)
        replacement = await self.profile('2', '1')
        await self.pokemon('replacement-defender', pid=replacement)
        deployment = await self.deploy(self.gym, 'replacement-defender', session={
            **self.session, 'session_id': 'replacement', 'profile_id': replacement, 'user_id': '2'})
        await deletion.replay_markers(self.writer, self.marker_path)
        self.assertEqual(await self.scalar('SELECT profile_id FROM profiles WHERE guild_id=? AND user_id=?',
                                           ('1', '2')), replacement)
        self.assertEqual(await self.scalar('SELECT profile_id FROM gym_deployments WHERE deployment_id=?',
                                           (deployment['deployment']['deployment_id'],)), replacement)
        await self.assert_private_battle_redacted(original)

    async def test_defender_delete_redacts_saved_battle_and_replay(self):
        await self.delete_private_battle('delete')

    async def test_defender_reset_redacts_saved_battle_and_replay(self):
        await self.delete_private_battle('reset')

    async def test_defender_opt_out_redacts_saved_battle_and_replay(self):
        await self.delete_private_battle('opt_out')

    async def test_marker_replay_redacts_battle_when_profile_already_absent(self):
        from pokewalker.services import deletion, marker_log
        original = await self.saved_privacy_battle()
        marker_log.append_marker(self.marker_path, kind='delete', guild_id='1', user_id='2',
                                 profile_id=self.defender, now=self.now)
        await self.writer.run(lambda conn: conn.execute('DELETE FROM profiles WHERE profile_id=?', (self.defender,)))
        await deletion.replay_markers(self.writer, self.marker_path)
        await self.assert_private_battle_redacted(original)

    async def test_redaction_failure_rolls_back_receipt_session_history_and_profile(self):
        from pokewalker.services import deletion, marker_log
        await self.saved_privacy_battle()
        before = await self.snapshot(), await self.rows('SELECT * FROM sessions')
        await self.conn.execute("CREATE TRIGGER reject_redaction BEFORE UPDATE ON sessions "
                                "BEGIN SELECT RAISE(ABORT,'redaction interrupted'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'redaction interrupted'):
            await deletion.run_marker(self.writer, self.marker_path, kind='delete', guild_id='1',
                                      user_id='2', profile_id=self.defender, now=self.now)
        self.assertEqual((await self.snapshot(), await self.rows('SELECT * FROM sessions')), before)
        self.assertEqual(marker_log.fold(self.marker_path), {})


class GymBattleScreenTests(unittest.IsolatedAsyncioTestCase):
    scalar = GymBattleTests.scalar
    profile = GymBattleTests.profile
    pokemon = GymBattleTests.pokemon
    rows = GymBattleTests.rows
    snapshot = GymBattleTests.snapshot
    create = GymBattleTests.create
    deploy = GymBattleTests.deploy
    gyms = GymBattleTests.gyms
    set_forms = GymBattleTests.set_forms
    click = test_gym_screens.GymScreenTests.click

    async def asyncSetUp(self):
        await GymBattleTests.asyncSetUp(self)
        from pokewalker.bot import gyms
        self.screens = gyms
        self.walker = Walker(SimpleNamespace(content=self.content, writer=self.writer),
                             clock=lambda: self.now, rng=self.rng)
        self.bot = self.walker.bot
        self.session.update(session_id='abc', selection='{}')

    async def preview(self):
        await self.click('gym_view', [self.gym['gym_id']])
        self.assertIn('gym_battle', self.walker.handlers, 'Battle preparation is absent')
        return await self.click('gym_battle')

    def selection(self):
        return json.loads(self.session['selection'])

    @staticmethod
    def component(shown, action):
        return next(item for item in shown['view'].children if item.custom_id.endswith(':' + action))

    async def ready(self):
        await self.preview()
        return await self.click('gym_party_pick', ['mon'])

    async def test_party_pick_from_page_3_fills_the_one_attacker(self):
        # D62a: one attacker, so the party screen has no slot buttons and old ones are refused.
        for i in range(30):
            await self.pokemon(f'a{i:02}')
        await self.preview()
        await self.click('gym_party_next')
        shown = await self.click('gym_party_next')
        self.assertFalse([item for item in shown['view'].children if 'gym_party_slot_' in item.custom_id])
        option = self.component(shown, 'gym_party_pick').options[0]
        await self.click('gym_party_pick', [option.value])
        self.assertEqual(self.selection()['party'], [[option.value, 0]])
        with self.assertRaises(_Refused):
            await self.click('gym_party_slot_two')

    async def test_party_saved_before_one_attacker_rule_is_refused(self):
        await self.preview()
        self.session['selection'] = json.dumps({**self.selection(), 'party': [['mon', 0], ['two', 0]], 'slot': 2})
        before = await self.snapshot()
        for action in ('gym_party_next', 'gym_battle_start'):
            with self.subTest(action=action), self.assertRaises(_Refused):
                await self.click(action)
        self.assertEqual(await self.snapshot(), before)

    async def test_every_select_at_most_25_options_and_view_at_most_5_rows(self):
        for i in range(299):
            await self.pokemon(f'a{i:03}')
        await self.conn.execute("DELETE FROM pokemon WHERE pokemon_uid IN ('two','three','four')")
        shown = await self.preview()
        for page in range(30):
            self.assertLessEqual(len(shown['view'].children), 25)
            self.assertLessEqual(len({item.row for item in shown['view'].children}), 5)
            self.assertLessEqual(len(shown['view'].to_components()), 5)
            for item in shown['view'].children:
                if hasattr(item, 'options'):
                    self.assertLessEqual(len(item.options), 25)
            self.assertEqual(len(self.component(shown, 'gym_party_pick').options), 10)
            self.assertEqual(self.component(shown, 'gym_party_next').disabled, page == 29)
            if page != 29:
                shown = await self.click('gym_party_next')

    async def test_value_not_on_current_page_refused(self):
        for i in range(12):
            await self.pokemon(f'a{i:02}')
        await self.preview()
        before = await self.snapshot()
        for values in (['mon'], ['missing'], ['a00', 'a01']):
            with self.subTest(values=values), self.assertRaises(_Refused):
                await self.click('gym_party_pick', values)
        self.assertEqual(await self.snapshot(), before)

    async def test_start_disabled_until_slot_1_filled(self):
        shown = await self.preview()
        self.assertEqual(self.selection()['party'], [])
        self.assertTrue(self.component(shown, 'gym_battle_start').disabled)
        with self.assertRaises(_Refused):
            await self.click('gym_battle_start')
        shown = await self.click('gym_party_pick', ['two'])
        self.assertFalse(self.component(shown, 'gym_battle_start').disabled)
        shown = await self.click('gym_party_pick', ['mon'])  # a new pick replaces the one attacker
        self.assertEqual(self.selection()['party'], [['mon', 0]])
        self.assertFalse(self.component(shown, 'gym_battle_start').disabled)

    async def test_preview_saves_deployment_id_and_start_passes_it(self):
        await self.ready()
        self.assertEqual(self.selection()['deployment_id'], self.dep['deployment_id'])
        with patch.object(self.screens.service, 'battle', wraps=self.gyms().battle) as battle:
            await self.click('gym_battle_start')
        args = battle.call_args.args
        self.assertEqual(args[3:7], (self.dep['deployment_id'], [('mon', 0)], None, self.now))
        self.assertIs(args[7], self.walker.rng)
        self.assertIs(args[8], self.content)
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_battles'), 1)

    async def test_stale_defender_rerenders_party_with_notice(self):
        await self.ready()
        await self.writer.run(lambda conn: self.gyms().end_deployment(
            conn, 'g', self.dep['deployment_id'], 'recalled', self.now, self.rng, self.content))
        await self.deploy(self.gym, 'defender', rev=2, now=self.now, session=self.holder)
        before = await self.snapshot()
        shown = await self.click('gym_battle_start')
        self.assertIn('changed', shown['embed'].description)
        self.assertEqual(self.selection()['deployment_id'], self.dep['deployment_id'])
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_battles'), 0)

    async def test_cooldown_rerenders_party_no_fight(self):
        await self.ready()
        await self.conn.execute('UPDATE profiles SET last_battle_at=? WHERE profile_id=?', (self.now, self.pid))
        before = await self.snapshot()
        shown = await self.click('gym_battle_start')
        self.assertIn('cooldown', shown['embed'].description.lower())
        self.assertEqual(await self.snapshot(), before)

    async def test_result_screen_sprites_and_text_complete_without_images(self):
        identity = next(item for item in self.content['identities']
                        if item['kind'] != 'default' and item['sprites']['shiny'])
        await self.conn.execute("UPDATE pokemon SET pokemon_id=?,shiny=1 WHERE pokemon_uid='mon'", (identity['pokemon_id'],))
        await self.ready()
        shown = await self.click('gym_battle_start')
        self.assertEqual(shown['embed'].image.url, identity['sprites']['shiny'])
        defender = next(item for item in self.content['identities'] if item['pokemon_id'] == 1)
        self.assertEqual(shown['embed'].thumbnail.url, defender['sprites']['normal'])
        text = shown['embed'].description
        for part in ('HP', 'Survivors', 'battle HP', identity['name_en'], 'Bulbasaur',
                     'CP ', 'male', 'Shiny', identity['kind'], ' / '.join(identity['types'])):
            self.assertIn(part, text)
        events = [line for line in text.splitlines() if line.split(':', 1)[0].isdigit()]
        self.assertEqual(events, self.selection()['result']['events'][:15])
        self.assertLessEqual(len(events), 15)
        state = {'session': self.session, 'result': self.selection()['result'], 'content': self.content}
        identify = self.screens.storage.identify
        with patch.object(self.screens.storage, 'identify', side_effect=lambda content, pokemon: (identify(content, pokemon)[0], None)):
            fallback = self.screens.render_result(state)
        self.assertFalse(fallback['embed'].image)
        self.assertFalse(fallback['embed'].thumbnail)
        self.assertEqual(fallback['embed'].description, text)

    async def test_result_screen_uses_exact_form_sprites_for_attacker_and_defender(self):
        await self.set_forms()
        await self.ready()
        shown = await self.click('gym_battle_start')
        form = next(item for item in self.content['evolution_targets'] if item['identity_id'] == '869:10346')
        expected = form['sprites']['normal']
        self.assertTrue(expected.endswith('/869-ruby-cream-strawberry-sweet.png'))
        self.assertEqual(shown['embed'].image.url, expected)
        self.assertEqual(shown['embed'].thumbnail.url, expected)
        self.assertIn('Attacker 1: ' + form['name_en'], shown['embed'].description)
        self.assertIn('Defender ' + form['name_en'], shown['embed'].description)

    async def test_battle_replay_returns_saved_snapshot_with_form_id(self):
        await self.set_forms()
        await self.ready()
        first_screen = await self.click('gym_battle_start')
        first = self.selection()['result']
        await self.writer.run(lambda conn: self.gyms().end_deployment(
            conn, 'g', self.dep['deployment_id'], 'recalled', self.now, self.rng, self.content))
        await self.conn.execute("UPDATE pokemon SET form_id=NULL,revision=revision+1 "
                                "WHERE pokemon_uid IN ('mon','defender')")
        before = await self.snapshot()
        replay = await GymBattleTests.fight(self, session={**self.session, 'revision': 8, '_original_revision': 7})
        self.assertEqual(replay, first)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(replay['snapshot']['party'][0]['form_id'], 10346)
        self.assertEqual(replay['snapshot']['defender']['form_id'], 10346)
        shown = self.screens.render_result({'session': self.session, 'result': replay, 'content': self.content})
        expected = next(item['sprites']['normal'] for item in self.content['evolution_targets']
                        if item['identity_id'] == '869:10346')
        self.assertEqual(shown['embed'].image.url, expected)
        self.assertEqual(shown['embed'].thumbnail.url, expected)
        self.assertEqual(shown['embed'].image.url, first_screen['embed'].image.url)
        self.assertEqual(shown['embed'].thumbnail.url, first_screen['embed'].thumbnail.url)
        self.assertEqual(shown['embed'].description, first_screen['embed'].description)

    async def test_legacy_snapshot_without_form_id_still_renders(self):
        await self.set_forms(attacker=None, defender=None)
        await self.ready()
        await self.click('gym_battle_start')
        legacy = self.selection()['result']
        for pokemon in [*legacy['snapshot']['party'], legacy['snapshot']['defender']]:
            pokemon.pop('form_id', None)
        shown = self.screens.render_result({'session': self.session, 'result': legacy, 'content': self.content})
        default = next(item for item in self.content['identities'] if item['pokemon_id'] == 869)
        expected = default['sprites']['normal']
        self.assertTrue(expected.endswith('/869.png'))
        self.assertEqual(shown['embed'].image.url, expected)
        self.assertEqual(shown['embed'].thumbnail.url, expected)
        self.assertIn('Attacker 1: ' + default['name_en'], shown['embed'].description)
        self.assertIn('Defender ' + default['name_en'], shown['embed'].description)

    async def test_battle_log_text_only_bounded(self):
        await self.ready()
        await self.click('gym_battle_start')
        selection = self.selection()
        events = [f'{i}: ' + 'event ' * 50 for i in range(40)]
        selection['result']['events'] = events
        self.session['selection'] = json.dumps(selection)
        shown = await self.click('gym_battle_log')
        text = ''
        while True:
            self.assertLessEqual(len(shown['embed'].description), 3500)
            self.assertFalse(shown['embed'].image)
            self.assertFalse(shown['embed'].thumbnail)
            text += shown['embed'].description
            if self.component(shown, 'gym_log_next').disabled:
                break
            shown = await self.click('gym_log_next')
        self.assertEqual(text, '\n'.join(events))

    async def test_other_user_cannot_click(self):
        shown = await self.ready()
        await self.conn.execute('INSERT INTO sessions(session_id,guild_id,user_id,profile_id,revision,selection,expires_at) '
                                'VALUES (?,?,?,?,?,?,?)', ('abc', 'g', 'u', self.pid, 7, self.session['selection'], 999999))
        interaction = test_walker_router.WalkerTests.interaction(self, user='holder', guild='g')
        before = await self.snapshot()
        await self.walker.route(interaction, self.component(shown, 'gym_battle_start').custom_id)
        self.assertIn('not yours', interaction.followup.send.await_args.args[0])
        interaction.edit_original_response.assert_not_awaited()
        self.assertEqual(await self.snapshot(), before)

    async def test_router_start_and_duplicate_create_one_battle(self):
        shown = await self.ready()
        await self.conn.execute('INSERT INTO sessions(session_id,guild_id,user_id,profile_id,revision,selection,expires_at) '
                                'VALUES (?,?,?,?,?,?,?)', ('abc', 'g', 'u', self.pid, 7, self.session['selection'], 999999))
        for target, values in (('gym_party_pick', ['two']),):
            interaction = test_walker_router.WalkerTests.interaction(self, user='u', guild='g', values=values)
            await self.walker.route(interaction, self.component(shown, target).custom_id)
            interaction.followup.send.assert_not_awaited()
            shown = interaction.edit_original_response.await_args.kwargs
        action = self.component(shown, 'gym_battle_start').custom_id
        interaction = test_walker_router.WalkerTests.interaction(self, user='u', guild='g')
        await self.walker.route(interaction, action)
        interaction.followup.send.assert_not_awaited()
        self.assertEqual(interaction.edit_original_response.await_args.kwargs['embed'].title, 'Gym battle result')
        self.assertEqual(await self.scalar('SELECT revision FROM sessions'), 9)
        result = json.loads(await self.scalar('SELECT selection FROM sessions'))['result']
        self.assertEqual([item['pokemon_uid'] for item in result['snapshot']['party']], ['two'])
        before = await self.snapshot()
        duplicate = test_walker_router.WalkerTests.interaction(self, user='u', guild='g')
        await self.walker.route(duplicate, action)
        duplicate.followup.send.assert_not_awaited()
        duplicate.edit_original_response.assert_not_awaited()
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_battles'), 1)

    async def test_ineligible_marks_and_refusals_legendary_can_attack_not_claim(self):
        await self.conn.execute("UPDATE profiles SET companion_uid='two' WHERE profile_id=?", (self.pid,))
        owned = await self.create('Owned')
        await self.deploy(owned, 'three')
        legendary = next(item for item in self.content['identities'] if item['is_legendary'])
        await self.conn.execute("UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid='mon'", (legendary['pokemon_id'],))
        shown = await self.preview()
        for marker in ('unavailable: companion', 'unavailable: deployed', 'CP ', 'grass'):
            self.assertIn(marker, shown['embed'].description)
        for uid in ('two', 'three'):
            with self.assertRaises(_Refused):
                await self.click('gym_party_pick', [uid])
        shown = await self.click('gym_party_pick', ['mon'])
        self.assertFalse(self.component(shown, 'gym_battle_start').disabled)
        self.assertEqual([o.value for o in self.component(shown, 'gym_party_outcome').options], ['clear'])
        with self.assertRaises(_Refused):
            await self.click('gym_party_outcome', ['mon'])
        self.assertEqual((await self.click('gym_battle_start'))['embed'].title, 'Gym battle result')

    async def test_claim_nominee_replacement_and_cap_result(self):
        await self.conn.execute('UPDATE pokemon SET level_x2=80 WHERE profile_id=?', (self.pid,))
        await self.ready()
        await self.click('gym_party_outcome', ['mon'])
        self.assertEqual(self.selection()['nominee'], 'mon')
        await self.click('gym_party_pick', ['four'])
        self.assertIsNone(self.selection()['nominee'])
        await self.click('gym_party_outcome', ['four'])
        owned = await self.create('Owned')
        await self.deploy(owned, 'two')
        shown = await self.click('gym_battle_start')
        self.assertIn('Gym cleared — you already hold a gym, so it stays empty', shown['embed'].description)
        self.assertFalse(self.selection()['result']['claimed'])

    async def test_claimed_result_names_nominee(self):
        await self.conn.execute('UPDATE pokemon SET level_x2=80 WHERE profile_id=?', (self.pid,))
        await self.ready()
        await self.click('gym_party_outcome', ['mon'])
        shown = await self.click('gym_battle_start')
        self.assertIn('Claimed by Bulbasaur', shown['embed'].description)
        self.assertTrue(self.selection()['result']['claimed'])

    async def test_stale_party_disables_start_no_fight(self):
        await self.ready()
        await self.conn.execute("UPDATE pokemon SET revision=revision+1 WHERE pokemon_uid='mon'")
        shown = await self.click('gym_party_prev')
        self.assertTrue(self.component(shown, 'gym_battle_start').disabled)
        before = await self.snapshot()
        with self.assertRaises(_Refused):
            await self.click('gym_battle_start')
        self.assertEqual(await self.snapshot(), before)

    async def test_foreign_and_missing_battle_targets_indistinguishable_no_writes(self):
        foreign = await self.create('Foreign', 'h')
        await self.ready()
        selected = self.selection()
        self.now = self.dep['ends_at']
        queries = []
        await self.conn.set_trace_callback(queries.append)
        try:
            for action in ('gym_battle', 'gym_battle_start', 'gym_party_next', 'gym_battle_log'):
                messages = []
                for gym_id in (foreign['gym_id'], 'missing'):
                    self.session['selection'] = json.dumps({**selected, 'gym_id': gym_id})
                    before = await self.snapshot()
                    with self.assertRaises(_Refused) as caught:
                        await self.click(action)
                    messages.append(str(caught.exception))
                    self.assertEqual(await self.snapshot(), before)
                self.assertEqual(messages[0], messages[1])
        finally:
            await self.conn.set_trace_callback(None)
        reads = [sql for sql in queries if sql.startswith('SELECT * FROM gyms WHERE gym_id=')]
        self.assertTrue(reads)
        self.assertTrue(all("guild_id='g'" in sql for sql in reads))

    async def test_render_functions_do_no_io(self):
        captured = []
        for name, action, values in (('render_party', 'gym_battle', None),
                                     ('render_party', 'gym_party_pick', ['mon']),
                                     ('render_result', 'gym_battle_start', None),
                                     ('render_log', 'gym_battle_log', None)):
            if action == 'gym_battle':
                await self.click('gym_view', [self.gym['gym_id']])
            renderer = getattr(self.screens, name, None)
            self.assertIsNotNone(renderer, f'{name} is absent')
            def capture(state, renderer=renderer):
                captured.append((renderer, state))
                return renderer(state)
            with patch.object(self.screens, name, side_effect=capture):
                await self.click(action, values)
        with patch('builtins.open', side_effect=AssertionError('renderer I/O')), patch.object(
                self.conn, 'execute', side_effect=AssertionError('renderer SQL')):
            for renderer, state in captured:
                self.assertIsNotNone(renderer(state)['embed'])
