"""Arena screens through direct handlers and real SQLite writer transactions."""

import importlib
import inspect
import json
import random
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pokewalker.bot.walker import CUSTOM_ID, Walker, _Refused
from content.balance import limits
from pokewalker.services import arena as service, gyms
import test_arena


class ArenaScreenTests(unittest.IsolatedAsyncioTestCase):
    profile = test_arena.ArenaTests.profile
    scalar = test_arena.ArenaTests.scalar
    rows = test_arena.ArenaTests.rows
    ticket = test_arena.ArenaTests.ticket
    queue = test_arena.ArenaTests.queue
    snapshot = test_arena.ArenaTests.snapshot
    redemption_snapshot = test_arena.ArenaTests.redemption_snapshot

    async def asyncSetUp(self):
        await test_arena.ArenaTests.asyncSetUp(self)
        await self.conn.execute("UPDATE sessions SET session_id='abcd'")
        self.session.update(session_id='abcd', revision=0, selection='{}')
        self.now = 1000
        self.walker = SimpleNamespace(bot=SimpleNamespace(content=test_arena.CONTENT),
                                      clock=lambda: self.now, rng=random.Random(7),
                                      multipliers=test_arena.MULTIPLIERS)
        await self.conn.execute("UPDATE pokemon SET pokemon_id=4 WHERE pokemon_uid='m1'")
        await self.conn.execute("UPDATE pokemon SET pokemon_id=7 WHERE pokemon_uid='m2'")

    def screens(self):
        try:
            return importlib.import_module('pokewalker.bot.arena')
        except ModuleNotFoundError:
            self.fail('Arena screen handlers are absent')

    async def click(self, action, values=None):
        interaction = SimpleNamespace(data={'values': values or []})
        handlers = self.screens().handlers(self.walker)
        self.assertIn(action, handlers, 'Required Arena action is absent')
        rendered = await self.writer.run(lambda conn: handlers[action](conn, self.session, interaction))
        self.assertLessEqual(len(rendered['embed'].description), 4096)
        rows = {}
        for item in rendered['view'].children:
            row = item.row if item.row is not None else item._rendered_row
            self.assertIn(row, range(5))
            rows[row] = rows.get(row, 0) + item.width
            self.assertLessEqual(rows[row], 5)
            self.assertRegex(item.custom_id, CUSTOM_ID)
            self.assertLessEqual(len(item.custom_id), 100)
        return rendered

    def selection(self):
        return json.loads(self.session['selection'])

    def button(self, rendered, action):
        return next(item for item in rendered['view'].children if item.custom_id.endswith(':' + action))

    async def picked(self):
        await self.click('arena_team')
        for uid, _ in self.team:
            result = await self.click('arena_team_pick', [uid])
        return result

    async def start_run(self):
        await self.picked()
        return await self.click('arena_start')

    async def test_arena_home_states_off_live_cooldown_ready(self):
        await self.conn.executemany('INSERT INTO arena_tickets VALUES (?,?,?)',
                                    [(self.pid, 'bronze', 3), (self.pid, 'diamond', 12)])
        ready = await self.click('arena')
        self.assertIn('Best floor: 0', ready['embed'].description)
        self.assertIn('Bronze: 3', ready['embed'].description)
        self.assertFalse(self.button(ready, 'arena_team').disabled)
        self.assertEqual(self.button(ready, 'arena_tickets').label, 'Tickets (15)')
        self.assertFalse(self.button(ready, 'arena_tickets').disabled)
        self.assertEqual(self.button(ready, 'home').label, 'Back')
        await self.conn.execute('UPDATE guilds SET arena_enabled=0')
        off = await self.click('arena')
        self.assertIn('The Arena is turned off in this server.', off['embed'].description)
        self.assertTrue(self.button(off, 'arena_team').disabled)
        await self.conn.execute('UPDATE guilds SET arena_enabled=1')
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('g','u',1)")
        self.assertTrue(self.button(await self.click('arena'), 'arena_team').disabled)
        await self.conn.execute('UPDATE restrictions SET paused=0')
        await self.start_run()
        await self.conn.execute('UPDATE guilds SET arena_enabled=0')
        live = await self.click('arena')
        self.assertIn('Run in progress: floor 1, entry fight.', live['embed'].description)
        self.assertIn('The Arena is turned off in this server.', live['embed'].description)
        self.assertFalse(self.button(live, 'arena_resume').disabled)
        await self.conn.execute("UPDATE arena_runs SET ended_at=1001,end_reason='loss',floor=5")
        self.now = 1060
        cooldown = await self.click('arena')
        self.assertIn('Your last run ended on floor 5.', cooldown['embed'].description)
        self.assertIn('Next run in 17h 59m.', cooldown['embed'].description)
        self.assertTrue(self.button(cooldown, 'arena_team').disabled)
        self.now = 65800
        await self.conn.execute('UPDATE guilds SET arena_enabled=1')
        self.assertFalse(self.button(await self.click('arena'), 'arena_team').disabled)

    async def test_team_picker_pages_and_sorts_favorites_first(self):
        for index in range(11):
            await self.conn.execute('INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,'
                                    'iv_defense,iv_stamina,gender,shiny,origin,content_version,caught_at) '
                                    "VALUES (?,?,1,20,10,10,10,'male',0,'catch','test',?)",
                                    (f'new{index:02}', self.pid, index + 1))
        await self.conn.execute("UPDATE pokemon SET favorite=1 WHERE pokemon_uid='m0'")
        first = await self.click('arena_team')
        self.assertEqual(self.selection(), {'phase': 'arena_team', 'team': [], 'offset': 0, 'favorites_first': False})
        self.assertEqual(self.button(first, 'arena_team_sort').label, 'Favorites first')
        select = next(item for item in first['view'].children if hasattr(item, 'options'))
        self.assertEqual(select.options[0].value, 'new10')
        second = await self.click('arena_team_next')
        self.assertEqual(self.selection()['offset'], 10)
        self.assertTrue(self.button(second, 'arena_team_next').disabled)
        with self.assertRaises(_Refused):
            await self.click('arena_team_pick', ['new10'])
        await self.click('arena_team_prev')
        sorted_view = await self.click('arena_team_sort')
        select = next(item for item in sorted_view['view'].children if hasattr(item, 'options'))
        self.assertEqual(select.options[0].value, 'm0')
        self.assertEqual(self.button(sorted_view, 'arena_team_sort').label, 'Newest first')
        self.assertEqual(self.selection()['offset'], 0)

    async def test_picker_marks_gym_defender_unavailable_allows_companion(self):
        gym = await self.writer.run(lambda conn: gyms.create(conn, 'g', 'Park', 0))
        await self.writer.run(lambda conn: gyms.deploy(conn, self.session, gym['gym_id'], 'm0', 0, 0, test_arena.CONTENT))
        await self.conn.execute("UPDATE profiles SET companion_uid='m1' WHERE profile_id=?", (self.pid,))
        rendered = await self.click('arena_team')
        self.assertIn('unavailable: deployed', rendered['embed'].description)
        with self.assertRaises(_Refused):
            await self.click('arena_team_pick', ['m0'])
        await self.click('arena_team_pick', ['m1'])
        self.assertEqual(self.selection()['team'], [['m1', 0]])

    async def test_pick_three_distinct_then_start_enabled(self):
        first = await self.click('arena_team')
        self.assertTrue(self.button(first, 'arena_start').disabled)
        await self.click('arena_team_pick', ['m0'])
        for values in (['m0'], ['missing'], ['m1', 'm2'], []):
            with self.assertRaises(_Refused):
                await self.click('arena_team_pick', values)
        await self.click('arena_team_pick', ['m1'])
        full = await self.click('arena_team_pick', ['m2'])
        self.assertFalse(self.button(full, 'arena_start').disabled)
        self.assertEqual(self.selection()['team'], [['m0', 0], ['m1', 0], ['m2', 0]])
        cleared = await self.click('arena_team_clear')
        self.assertEqual(self.selection()['team'], [])
        self.assertTrue(self.button(cleared, 'arena_start').disabled)

    async def test_special_pick_shows_boss_only_candy_warning_and_does_not_block(self):
        await self.conn.execute("UPDATE pokemon SET pokemon_id=150 WHERE pokemon_uid='m2'")
        rendered = await self.picked()
        self.assertIn('Mewtwo is a special Pokémon: it only earns Candy from boss knockouts.', rendered['embed'].description)
        self.assertFalse(self.button(rendered, 'arena_start').disabled)
        self.assertEqual((await self.click('arena_start'))['embed'].title, 'Arena break')

    async def test_start_opens_break_screen_with_enemy_species_types_cp_only(self):
        rendered = await self.start_run()
        run = (await self.writer.run(lambda conn: service.state(conn, self.session, self.now)))['run']
        self.assertEqual(self.selection(), {'phase': 'arena_break', 'run_id': run['run_id'],
                                           'run_revision': run['revision'], 'berry': 'razz_berry'})
        identity, sprite = test_arena.storage.identify(test_arena.CONTENT, run['enemy']['snapshot'])
        text = rendered['embed'].description
        for fragment in (identity['name_en'], str(run['enemy']['snapshot']['cp']), *[kind.title() for kind in identity['types']]):
            self.assertIn(fragment, text)
        self.assertNotIn('Level', text)
        self.assertNotIn('IVs', text)
        self.assertEqual(rendered['embed'].image.url, sprite)
        for member in run['team']:
            self.assertIn(f"HP {member['hp']} / {member['full_hp']}", text)
        self.assertEqual(self.button(rendered, 'arena').label, 'Back out')
        with patch.object(test_arena.storage, 'identify', return_value=(identity, None)):
            missing_sprite = await self.click('arena_resume')
        self.assertFalse(missing_sprite['embed'].image)
        self.assertEqual(missing_sprite['embed'].description, text)

    async def test_start_refusals_keep_picker_with_reason(self):
        for result, notice in [({'status': 'stale'}, 'A Pokémon changed. Pick your team again.'),
                               ({'status': 'deployed'}, "A gym defender can't join an Arena team."),
                               ({'status': 'cooldown', 'seconds_left': 3660}, 'Next run in 1h 1m.'),
                               ({'status': 'paused', 'until': None}, 'Check-ins are paused indefinitely.'),
                               ({'status': 'paused', 'until': '2026-11-15T00:00:00+00:00'},
                                'Check-ins are paused until 2026-11-15T00:00:00+00:00.'),
                               ({'status': 'off'}, 'The Arena is turned off in this server.')]:
            with self.subTest(result=result):
                await self.picked()
                with patch.object(service, 'start', new=AsyncMock(return_value=result)) as starting:
                    rendered = await self.click('arena_start')
                self.assertEqual(starting.call_args.args[2], [['m0', 0], ['m1', 0], ['m2', 0]])
                self.assertEqual(self.selection()['phase'], 'arena_team')
                self.assertIn(notice, rendered['embed'].description)
        await self.start_run()
        self.session['selection'] = json.dumps({'phase': 'arena_team', 'team': self.team, 'offset': 0, 'favorites_first': False})
        self.assertEqual((await self.click('arena_start'))['embed'].title, 'Arena break')

    async def test_resume_shows_same_enemy_and_hp_after_back_out(self):
        initial = await self.start_run()
        run = (await self.writer.run(lambda conn: service.state(conn, self.session, self.now)))['run']
        run['team'][0]['hp'] = 1
        run['team'][1]['hp'] = 2
        await self.conn.execute('UPDATE arena_runs SET team=? WHERE run_id=?', (json.dumps(run['team']), run['run_id']))
        self.now += 100
        with patch.object(test_arena.domain, 'roll_enemy', side_effect=AssertionError('enemy rerolled')):
            await self.click('arena')
            resumed = await self.click('arena_resume')
        self.assertEqual(resumed['embed'].image.url, initial['embed'].image.url)
        self.assertIn(f"HP 1 / {run['team'][0]['full_hp']}", resumed['embed'].description)
        self.assertIn(f"HP 2 / {run['team'][1]['full_hp']}", resumed['embed'].description)
        saved = (await self.writer.run(lambda conn: service.state(conn, self.session, self.now)))['run']
        self.assertEqual(saved, run)

    async def test_action_names_match_router_pattern(self):
        mapping = self.screens().handlers(self.walker)
        expected = {'arena', 'arena_resume', 'arena_team', 'arena_team_prev', 'arena_team_next',
                    'arena_team_sort', 'arena_team_pick', 'arena_team_clear', 'arena_start',
                    'arena_fight', 'arena_heal_fight', 'arena_heal_one', 'arena_heal_two',
                    'arena_heal_three', 'arena_berry', 'arena_order', 'arena_tickets',
                    'arena_redeem_bronze', 'arena_redeem_silver', 'arena_redeem_gold',
                    'arena_redeem_platinum', 'arena_redeem_diamond', 'arena_redeem_confirm'}
        self.assertEqual(set(mapping), expected)
        for action in mapping:
            self.assertIsNotNone(re.fullmatch('[a-z_]+', action))
        self.assertIn('arena', Walker(self.walker.bot).handlers)
        await self.click('arena')
        await self.start_run()

    async def test_render_functions_do_no_io(self):
        screens = self.screens()
        for action, function in [('arena', 'render_home'), ('arena_team', 'render_team'),
                                  ('arena_start', 'render_break'), ('arena_resume', 'render_defeat')]:
            if action == 'arena_start':
                await self.picked()
            elif function == 'render_defeat':
                self.now += test_arena.RULES['run_seconds']
            renderer = getattr(screens, function)
            with patch.object(screens, function, wraps=renderer) as rendered:
                await self.click(action)
            self.assertFalse(inspect.iscoroutinefunction(renderer))
            with (patch('aiosqlite.Connection.execute', side_effect=AssertionError('renderer SQL')),
                  patch('builtins.open', side_effect=AssertionError('renderer file I/O'))):
                view = renderer(rendered.call_args.args[0])
            self.assertIn('embed', view)
            self.assertIn('view', view)

    async def test_excluded_and_stale_owners_cannot_open_or_mutate_arena(self):
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
        for action in ('arena', 'arena_resume', 'arena_team', 'arena_start'):
            with self.subTest(action=action), self.assertRaises(_Refused):
                await self.click(action)
        await self.conn.execute('UPDATE restrictions SET excluded=0')
        self.session['profile_id'] = self.other
        with self.assertRaises(_Refused):
            await self.click('arena')
        self.assertEqual(await self.scalar('SELECT count(*) FROM arena_runs'), 0)
        self.assertEqual(self.session['selection'], '{}')

    async def test_resume_at_hour_18_expires_and_returns_defeat(self):
        await self.start_run()
        self.now += test_arena.RULES['run_seconds']
        rendered = await self.click('arena_resume')
        self.assertEqual(rendered['embed'].title, 'Arena defeat')
        self.assertIn('18 hours passed', rendered['embed'].description)
        self.assertEqual(await self.rows('SELECT ended_at,end_reason,revision FROM arena_runs'),
                         [{'ended_at': self.now, 'end_reason': 'expired', 'revision': 1}])
        self.assertEqual(self.button(rendered, 'arena').label, 'Back')

    inventory = test_arena.ArenaTests.inventory
    outcome = test_arena.ArenaTests.outcome

    async def run_state(self):
        return (await self.writer.run(lambda conn: service.state(conn, self.session, self.now)))['run']

    async def hurt_team(self, hp=(1, 2, 3)):
        run = await self.run_state()
        for member, health in zip(run['team'], hp):
            member['hp'] = health
        await self.conn.execute('UPDATE arena_runs SET team=? WHERE run_id=?', (json.dumps(run['team']), run['run_id']))
        return run

    async def resource_snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table} ORDER BY 1') for table in
                ('arena_runs', 'profiles', 'inventory', 'arena_tickets', 'action_receipts', 'resource_ledger', 'candy')}

    async def test_break_screen_layout_rows_and_disabled_heal_at_full_hp(self):
        rendered = await self.start_run()
        self.assertIn('arena_fight', [item.custom_id.rsplit(':', 1)[-1] for item in rendered['view'].children])
        rows = {action: self.button(rendered, action).row for action in
                ('arena_fight', 'arena_heal_fight', 'arena', 'arena_heal_one', 'arena_heal_two',
                 'arena_heal_three', 'arena_berry', 'arena_order')}
        self.assertEqual(rows, {'arena_fight': 0, 'arena_heal_fight': 0, 'arena': 0,
                                'arena_heal_one': 1, 'arena_heal_two': 1, 'arena_heal_three': 1,
                                'arena_berry': 2, 'arena_order': 3})
        for word in ('one', 'two', 'three'):
            self.assertTrue(self.button(rendered, 'arena_heal_' + word).disabled)

    async def test_berry_default_is_larger_stock_and_choice_persists(self):
        await self.inventory('razz_berry', 2)
        await self.inventory('pinap_berry', 3)
        rendered = await self.start_run()
        self.assertEqual(self.selection()['berry'], 'pinap_berry')
        self.assertEqual([option.label for option in self.button(rendered, 'arena_berry').options],
                         ['Razz Berry ×2', 'Pinap Berry ×3'])
        await self.click('arena_berry', ['razz_berry'])
        await self.inventory('pinap_berry', 10)
        await self.click('arena')
        resumed = await self.click('arena_resume')
        self.assertEqual(self.selection()['berry'], 'razz_berry')
        self.assertTrue(next(option for option in self.button(resumed, 'arena_berry').options
                             if option.value == 'razz_berry').default)
        for values in (['golden_razz_berry'], [], ['razz_berry', 'pinap_berry']):
            with self.assertRaises(_Refused):
                await self.click('arena_berry', values)

    async def test_heal_spends_selected_berry_and_redraws(self):
        await self.inventory('pinap_berry', 2)
        await self.start_run()
        await self.hurt_team()
        healed = await self.click('arena_heal_two')
        run = await self.run_state()
        self.assertEqual([member['hp'] for member in run['team']], [1, run['team'][1]['full_hp'], 3])
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='pinap_berry'"), 1)
        self.assertEqual(self.selection()['run_revision'], run['revision'])
        self.assertTrue(self.button(healed, 'arena_heal_two').disabled)
        before = await self.resource_snapshot()
        await self.click('arena_heal_two')
        self.assertEqual(await self.resource_snapshot(), before)
        await self.inventory('pinap_berry', 0)
        missing = await self.click('arena_heal_one')
        self.assertIn('You have no Pinap Berry.', missing['embed'].description)

    async def test_mixing_berry_types_between_heal_presses(self):
        await self.inventory('razz_berry', 2)
        await self.inventory('pinap_berry', 2)
        await self.start_run()
        await self.hurt_team()
        self.assertEqual(self.selection()['berry'], 'razz_berry')
        await self.click('arena_heal_one')
        await self.click('arena_berry', ['pinap_berry'])
        await self.click('arena_heal_three')
        self.assertEqual(await self.rows('SELECT item_id,quantity FROM inventory ORDER BY item_id'),
                         [{'item_id': 'pinap_berry', 'quantity': 1}, {'item_id': 'razz_berry', 'quantity': 1}])
        self.assertEqual([line['resource_id'] for line in await self.rows("SELECT resource_id FROM resource_ledger WHERE reason='arena_heal'")],
                         ['razz_berry', 'pinap_berry'])

    async def test_heal_all_and_fight_reports_missing_count_spends_nothing(self):
        await self.inventory('razz_berry', 1)
        await self.start_run()
        await self.hurt_team()
        before = await self.resource_snapshot()
        with patch.object(test_arena.battle_engine, 'simulate', side_effect=AssertionError('unexpected fight')):
            rendered = await self.click('arena_heal_fight')
        self.assertIn('You need 2 more Razz Berry. Nothing was spent.', rendered['embed'].description)
        self.assertEqual(await self.resource_snapshot(), before)

    async def test_heal_all_and_fight_success_commits_once_and_preserves_choice(self):
        await self.inventory('razz_berry', 4)
        await self.inventory('pinap_berry', 3)
        await self.start_run()
        await self.hurt_team()
        await self.click('arena_berry', ['pinap_berry'])
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome()) as simulated:
            rendered = await self.click('arena_heal_fight')
        simulated.assert_called_once()
        run = await self.run_state()
        self.assertEqual([member.hp for member in simulated.call_args.args[0]],
                         [member['full_hp'] for member in run['team']])
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='pinap_berry'"), 0)
        self.assertEqual(await self.rows("SELECT resource_id,delta FROM resource_ledger WHERE reason='arena_heal'"),
                         [{'resource_id': 'pinap_berry', 'delta': -3}])
        self.assertEqual(run['revision'], 2)
        self.assertEqual(self.selection()['berry'], 'pinap_berry')
        self.assertIn('Win · 9 ticks', rendered['embed'].description)

    async def test_fight_win_shows_result_block_then_next_enemy(self):
        await self.start_run()
        before = await self.run_state()
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome(hp=(3, 4, 5))):
            rendered = await self.click('arena_fight')
        run = await self.run_state()
        text = rendered['embed'].description
        self.assertIn(f"{before['enemy']['snapshot']['combatant']['name']} · CP {before['enemy']['snapshot']['cp']}", text)
        for fragment in ('Win · 9 ticks', 'Candy: +1', 'HP 3', 'HP 4', 'HP 5', 'middle fight', 'Next enemy:'):
            self.assertIn(fragment, text)
        self.assertLess(text.index('Win · 9 ticks'), text.index('Next enemy:'))
        self.assertEqual(run['slot'], 1)
        self.assertEqual(self.selection()['run_revision'], run['revision'])

    async def test_cleared_floor_shows_ticket_and_first_clear_lines(self):
        await self.start_run()
        await self.conn.execute('UPDATE arena_runs SET floor=10,slot=2')
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome()):
            rendered = await self.click('arena_fight')
        self.assertIn('Floor 10 cleared: Silver Ticket', rendered['embed'].description)
        self.assertIn('First clear: +1 Silver Ticket', rendered['embed'].description)
        self.assertEqual(await self.scalar('SELECT quantity FROM arena_tickets'), 2)

    async def test_revived_member_shown_at_one_hp_in_same_position(self):
        await self.start_run()
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome(hp=(0, 4, 5), finisher=1)):
            rendered = await self.click('arena_fight')
        run = await self.run_state()
        self.assertEqual([member['uid'] for member in run['team']], ['m0', 'm1', 'm2'])
        self.assertEqual(run['team'][0]['hp'], 1)
        self.assertIn('Bulbasaur revived at 1 HP.', rendered['embed'].description)
        self.assertIn(f"1: Bulbasaur · HP 1 / {run['team'][0]['full_hp']}", rendered['embed'].description)

    async def test_order_select_reorders_party_and_persists_after_back_out(self):
        rendered = await self.start_run()
        options = self.button(rendered, 'arena_order').options
        self.assertEqual(len(options), 6)
        self.assertEqual(len({option.value for option in options}), 6)
        self.assertEqual([option.value for option in options if option.default], ['012'])
        self.assertTrue(all(name in options[0].label for name in ('Bulbasaur', 'Charmander', 'Squirtle')))
        await self.click('arena_order', ['210'])
        run = await self.run_state()
        self.assertEqual([member['uid'] for member in run['team']], ['m2', 'm1', 'm0'])
        self.assertEqual(await self.rows('SELECT * FROM resource_ledger'), [])
        await self.click('arena')
        resumed = await self.click('arena_resume')
        self.assertIn('1: Squirtle', resumed['embed'].description)
        self.assertEqual(await self.run_state(), run)
        for values in (['000'], ['abc'], [], ['012', '210']):
            with self.assertRaises(_Refused):
                await self.click('arena_order', values)

    async def test_defeat_and_expiry_show_defeat_screen_without_give_up(self):
        await self.start_run()
        for outcome, reason, message in [('loss', 'party_fainted', 'lost'), ('draw', 'tick_limit', 'time limit'),
                                          ('draw', 'double_ko', 'double knockout')]:
            with self.subTest(outcome=outcome, reason=reason):
                await self.conn.execute('UPDATE arena_runs SET ended_at=NULL,end_reason=NULL')
                await self.hurt_team()
                await self.click('arena_resume')
                result = test_arena.battle_engine.Result(outcome, reason, 9, (), (), party_hp=(0, 0, 0))
                with patch.object(test_arena.battle_engine, 'simulate', return_value=result):
                    rendered = await self.click('arena_fight')
                self.assertEqual(rendered['embed'].title, 'Arena defeat')
                self.assertIn('Floor 1', rendered['embed'].description)
                self.assertIn('entry fight', rendered['embed'].description)
                self.assertIn(message, rendered['embed'].description)
                self.assertEqual(self.button(rendered, 'arena_tickets').label, 'Tickets')
                self.assertEqual(self.button(rendered, 'arena').label, 'Back')
                self.assertFalse(any('give up' in getattr(item, 'label', '').lower() for item in rendered['view'].children))
                await self.conn.execute('DELETE FROM action_receipts')
        await self.conn.execute('UPDATE arena_runs SET ended_at=NULL,end_reason=NULL')
        await self.click('arena_resume')
        self.now += test_arena.RULES['run_seconds']
        expired = await self.click('arena_fight')
        self.assertIn('18 hours passed', expired['embed'].description)
        home = await self.click('arena')
        self.assertEqual(home['embed'].title, 'Arena')

    async def test_stale_screen_spends_nothing_and_redraws_current_state(self):
        await self.inventory('razz_berry', 10)
        await self.start_run()
        run = await self.hurt_team()
        old = dict(self.selection())
        await self.writer.run(lambda conn: service.set_order(conn, self.session, run['run_id'], run['revision'], [2, 1, 0], self.now))
        before = await self.resource_snapshot()
        for action, values in [('arena_fight', []), ('arena_heal_fight', []), ('arena_heal_one', []),
                                ('arena_order', ['012']), ('arena_berry', ['pinap_berry'])]:
            with self.subTest(action=action):
                self.session['selection'] = json.dumps(old)
                with patch.object(test_arena.battle_engine, 'simulate', side_effect=AssertionError('stale fight')):
                    rendered = await self.click(action, values)
                self.assertIn('The run changed on another screen. This is its current state.', rendered['embed'].description)
                self.assertEqual(await self.resource_snapshot(), before)
                self.assertEqual(self.selection()['run_revision'], 1)
                self.assertEqual(self.selection()['berry'], 'razz_berry')

    async def test_second_open_screen_must_redraw_before_fighting(self):
        await self.start_run()
        first = self.session
        await self.conn.execute('INSERT INTO sessions(session_id,guild_id,user_id,profile_id,revision,expires_at) '
                                "VALUES ('abce','g','u',?,0,1e12)", (self.pid,))
        self.session = {**first, 'session_id': 'abce', 'selection': '{}'}
        await self.click('arena_resume')
        await self.click('arena_order', ['210'])
        self.session = first
        before = await self.resource_snapshot()
        with patch.object(test_arena.battle_engine, 'simulate', side_effect=AssertionError('stale fight')):
            rendered = await self.click('arena_fight')
        self.assertIn('The run changed on another screen.', rendered['embed'].description)
        self.assertEqual(await self.resource_snapshot(), before)
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome()):
            self.assertIn('Win · 9 ticks', (await self.click('arena_fight'))['embed'].description)

    async def test_enemy_level_and_ivs_never_rendered(self):
        await self.start_run()
        for outcome in ('win', 'loss'):
            with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome(outcome)):
                rendered = await self.click('arena_fight')
            self.assertNotRegex(rendered['embed'].description, r'(?i)\blevel\b|\bivs?\b|iv_attack|level_x2')

    async def test_views_within_5_rows_unique_custom_ids(self):
        views = [await self.click('arena'), await self.click('arena_team'), await self.start_run()]
        self.now += test_arena.RULES['run_seconds']
        views.append(await self.click('arena_resume'))
        for rendered in views:
            ids = [item.custom_id for item in rendered['view'].children]
            self.assertEqual(len(ids), len(set(ids)))
            if rendered['embed'].title == 'Arena break':
                self.assertEqual({item.row for item in rendered['view'].children}, {0, 1, 2, 3})

    async def test_tickets_screen_lists_five_tiers_with_counts_and_contents(self):
        await self.ticket('silver', 2)
        rendered = await self.click('arena_tickets')
        self.assertEqual(rendered['embed'].title, 'Arena tickets')
        self.assertEqual(rendered['embed'].description.splitlines(), [
            'Bronze ×0: 1 encounter, 100 Stardust, 0 gym income rolls, 0 survivor rewards',
            'Silver ×2: up to 2 encounters, 200 Stardust, 2 gym income rolls, 0 survivor rewards',
            'Gold ×0: fill encounter queue, 400 Stardust, 4 gym income rolls, 0 survivor rewards',
            'Platinum ×0: fill encounter queue, 1000 Stardust, 8 gym income rolls, 1 survivor reward',
            'Diamond ×0: fill encounter queue, 3000 Stardust, 24 gym income rolls, 3 survivor rewards'])
        self.assertEqual(self.button(rendered, 'arena').label, 'Back')
        rules = json.loads(json.dumps(test_arena.RULES))
        rules['tickets']['tiers']['silver'].update(encounters=1, stardust=321, income_rolls=7)
        screens = self.screens()
        with patch.object(screens, 'load_table', return_value={'rules': rules}), \
                patch.object(screens, 'render_tickets', wraps=screens.render_tickets) as render:
            changed = await self.click('arena_tickets')
        self.assertIn('Silver ×2: 1 encounter, 321 Stardust, 7 gym income rolls', changed['embed'].description)
        with patch('builtins.open', side_effect=AssertionError('renderer I/O')), \
                patch.object(self.conn, 'execute', side_effect=AssertionError('renderer SQL')):
            self.assertEqual(screens.render_tickets(render.call_args.args[0])['embed'].description,
                             changed['embed'].description)

    async def test_redeem_buttons_disabled_at_zero(self):
        await self.ticket('gold', 1)
        rendered = await self.click('arena_tickets')
        for tier in test_arena.RULES['tickets']['tiers']:
            self.assertEqual(self.button(rendered, 'arena_redeem_' + tier).disabled, tier != 'gold')
        before = await self.redemption_snapshot()
        none = await self.click('arena_redeem_bronze')
        self.assertIn('You have no Bronze Tickets.', none['embed'].description)
        self.assertEqual(await self.redemption_snapshot(), before)

    async def test_confirm_screen_quotes_free_slots_and_added_encounters(self):
        await self.ticket('silver')
        await self.queue()
        screens = self.screens()
        with patch.object(service, 'redeem_quote', wraps=service.redeem_quote) as quoting, \
                patch.object(screens, 'render_redeem', wraps=screens.render_redeem) as render:
            rendered = await self.click('arena_redeem_silver')
        quoting.assert_awaited_once_with(self.conn, self.pid, 'silver')
        self.assertIn('2 of 3 slots free: +2 encounters', rendered['embed'].description)
        self.assertIn('200 Stardust, 2 gym income rolls', rendered['embed'].description)
        self.assertEqual(self.selection(), {'phase': 'arena_redeem', 'tier': 'silver', 'free': 2, 'add': 2})
        self.assertEqual(self.button(rendered, 'arena_redeem_confirm').label, 'Confirm')
        self.assertEqual(self.button(rendered, 'arena_tickets').label, 'Back')
        with patch('builtins.open', side_effect=AssertionError('renderer I/O')), \
                patch.object(self.conn, 'execute', side_effect=AssertionError('renderer SQL')):
            self.assertEqual(screens.render_redeem(render.call_args.args[0])['embed'].description,
                             rendered['embed'].description)
        with patch.object(screens, 'limits', return_value={'encounter_queue': 9}):
            changed_cap = await self.click('arena_redeem_silver')
        self.assertIn('2 of 9 slots free: +2 encounters', changed_cap['embed'].description)

    async def test_queue_full_explains_and_spends_nothing(self):
        await self.ticket('diamond')
        await self.click('arena_redeem_diamond')
        preview = self.session['selection']
        await self.queue(limits()['encounter_queue'])
        before = await self.redemption_snapshot()
        for action in ('arena_redeem_diamond', 'arena_redeem_confirm'):
            self.session['selection'] = preview
            shown = await self.click(action)
            self.assertEqual(shown['embed'].title, 'Arena tickets')
            self.assertIn('Your encounter queue is full (3/3). Open an encounter first. Nothing was spent.',
                          shown['embed'].description)
            self.assertEqual(await self.redemption_snapshot(), before)
        with patch.object(self.screens(), 'limits', return_value={'encounter_queue': 9}):
            shown = await self.click('arena_redeem_diamond')
        self.assertIn('full (9/9)', shown['embed'].description)

    async def test_quote_changed_between_confirm_and_press_shows_new_quote(self):
        await self.ticket('silver')
        await self.click('arena_redeem_silver')
        await self.queue()
        before = await self.redemption_snapshot()
        changed = await self.click('arena_redeem_confirm')
        self.assertIn('Your queue changed. Nothing was spent.', changed['embed'].description)
        self.assertIn('2 of 3 slots free: +2 encounters', changed['embed'].description)
        self.assertEqual(self.selection(), {'phase': 'arena_redeem', 'tier': 'silver', 'free': 2, 'add': 2})
        self.assertEqual(await self.redemption_snapshot(), before)

    async def test_confirm_without_preview_refused(self):
        await self.ticket('bronze')
        for selection in ({}, {'phase': 'arena_team'}, {'phase': 'arena_redeem', 'tier': 'invalid'}):
            self.session['selection'] = json.dumps(selection)
            before = await self.redemption_snapshot()
            with patch.object(service, 'redeem', wraps=service.redeem) as redeeming:
                with self.assertRaises(_Refused):
                    await self.click('arena_redeem_confirm')
            redeeming.assert_not_awaited()
            self.assertEqual(await self.redemption_snapshot(), before)

    async def test_redeemed_notice_and_count_drops_by_one(self):
        await self.ticket('silver', 2)
        await self.click('arena_redeem_silver')
        with patch.object(service, 'redeem', wraps=service.redeem) as redeeming:
            rendered = await self.click('arena_redeem_confirm')
        redeeming.assert_awaited_once_with(self.conn, self.session, 'silver', expected_free=3, expected_add=2,
                                          now=self.now, rng=self.walker.rng, content=test_arena.CONTENT)
        self.assertIn('Redeemed a Silver Ticket: +2 encounters. Rewards are in your Inbox.', rendered['embed'].description)
        self.assertIn('Silver ×1:', rendered['embed'].description)
        self.assertEqual(await self.scalar('SELECT quantity FROM arena_tickets'), 1)
        self.assertEqual(await self.scalar('SELECT COUNT(*) FROM encounters'), 2)
        self.assertEqual(self.button(await self.click('arena'), 'arena_tickets').label, 'Tickets (1)')
        await self.conn.execute('DELETE FROM encounters')
        await self.click('arena_redeem_silver')
        await self.conn.execute('UPDATE arena_tickets SET quantity=0')
        before = await self.redemption_snapshot()
        none = await self.click('arena_redeem_confirm')
        self.assertIn('You have no Silver Tickets.', none['embed'].description)
        self.assertEqual(await self.redemption_snapshot(), before)

    async def test_tickets_redeemable_with_arena_off_and_during_live_run(self):
        await self.ticket('bronze', 2)
        await self.conn.execute('UPDATE guilds SET arena_enabled=0')
        for live in (False, True):
            # Direct handlers bypass the router's new revision for each press.
            self.session['_original_revision'] += 1
            if live:
                await self.conn.execute('UPDATE guilds SET arena_enabled=1')
                await self.start_run()
                await self.conn.execute('UPDATE guilds SET arena_enabled=0')
            home = await self.click('arena')
            self.assertFalse(self.button(home, 'arena_tickets').disabled)
            await self.click('arena_tickets')
            await self.click('arena_redeem_bronze')
            shown = await self.click('arena_redeem_confirm')
            self.assertIn('Redeemed a Bronze Ticket: +1 encounters.', shown['embed'].description)
        self.assertEqual(await self.scalar('SELECT quantity FROM arena_tickets'), 0)
        self.assertIsNone((await self.run_state())['ended_at'])

    async def test_diamond_counts_each_reward_as_inbox_entry(self):
        from pokewalker.services import milestones
        await self.ticket('diamond')
        await self.click('arena_redeem_diamond')
        await self.click('arena_redeem_confirm')
        self.assertEqual(await milestones.pending_count(self.conn, self.pid), 28)


class ArenaRouterTests(unittest.IsolatedAsyncioTestCase):
    from test_walker_router import WalkerTests as _Fixture
    asyncSetUp = _Fixture.asyncSetUp
    interaction = _Fixture.interaction
    rows = _Fixture.rows
    open = _Fixture.open
    click = _Fixture.click
    enroll = _Fixture.enroll

    async def test_home_button_opens_arena_through_router(self):
        await self.enroll()
        opened, session = await self.open()
        home = opened.edit_original_response.await_args.kwargs
        buttons = [button for button in home['view'].children if button.label == 'Arena']
        self.assertEqual(len(buttons), 1)
        self.assertFalse(buttons[0].disabled)
        pressed = self.interaction()
        await self.walker.route(pressed, buttons[0].custom_id)
        pressed.edit_original_response.assert_awaited_once()
        self.assertEqual(pressed.edit_original_response.await_args.kwargs['embed'].title, 'Arena')
        current = (await self.rows('SELECT * FROM sessions WHERE session_id=?', (session['session_id'],)))[0]
        self.assertEqual(current['revision'], session['revision'] + 1)

    async def test_every_arena_action_is_registered(self):
        from pokewalker.bot import arena
        expected = set(arena.handlers(self.walker))
        self.assertTrue(expected)
        self.assertEqual({action for action in self.walker.handlers if action.startswith('arena')}, expected)
