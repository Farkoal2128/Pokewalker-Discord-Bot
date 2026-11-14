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
        self.walker = SimpleNamespace(bot=SimpleNamespace(content=test_arena.CONTENT, writer=self.writer, _stopping=False),
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
        if after_commit := rendered.pop('after_commit', None):
            rendered = await after_commit()
        if 'embed' not in rendered:
            return rendered
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
        self.assertEqual(self.selection(), {'phase': 'arena_team', 'team': [], 'offset': 0, 'favorites_first': False, 'skip': 0})
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

    async def test_skip_select_hidden_at_best_floor_below_2(self):
        for best in (0, 1):
            await self.conn.execute('UPDATE profiles SET arena_best_floor=? WHERE profile_id=?', (best, self.pid))
            view = await self.click('arena_team')
            actions = {item.custom_id.rsplit(':', 1)[-1] for item in view['view'].children}
            self.assertFalse({'arena_skip', 'arena_skip_more'} & actions)
            self.assertEqual(self.selection()['skip'], 0)

    async def test_skip_select_lists_0_to_s_and_second_select_from_25(self):
        for best, maximum in ((2, 1), (48, 24), (50, 25), (79, 39), (80, 40)):
            with self.subTest(best=best):
                await self.conn.execute('UPDATE profiles SET arena_best_floor=? WHERE profile_id=?', (best, self.pid))
                view = await self.click('arena_team')
                first = self.button(view, 'arena_skip')
                self.assertEqual((first.row, [o.value for o in first.options]),
                                 (3, [str(k) for k in range(min(maximum, 24) + 1)]))
                self.assertEqual([o.label for o in first.options],
                                 ['No skip'] + [f'Skip {k} floors: start at floor {k + 1}'
                                                for k in range(1, min(maximum, 24) + 1)])
                self.assertEqual([o.value for o in first.options if o.default], ['0'])
                if maximum >= 25:
                    second = self.button(view, 'arena_skip_more')
                    self.assertEqual((second.row, [o.value for o in second.options]),
                                     (4, [str(k) for k in range(25, maximum + 1)]))
                    chosen = await self.click('arena_skip_more', [str(maximum)])
                    self.assertEqual([o.value for o in self.button(chosen, 'arena_skip_more').options if o.default],
                                     [str(maximum)])
                    self.assertFalse(any(o.default for o in self.button(chosen, 'arena_skip').options))
                else:
                    self.assertFalse(any(item.custom_id.endswith(':arena_skip_more') for item in view['view'].children))

    async def test_skip_choice_persists_across_paging_and_shows_paid_tickets(self):
        await self.conn.execute('UPDATE profiles SET arena_best_floor=80 WHERE profile_id=?', (self.pid,))
        await self.picked()
        for index in range(11):
            await self.conn.execute('INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,'
                                    'iv_defense,iv_stamina,gender,shiny,origin,content_version,caught_at) '
                                    "VALUES (?,?,1,20,10,10,10,'male',0,'catch','test',?)",
                                    (f'new{index:02}', self.pid, index + 1))
        await self.click('arena_team_next')
        before = self.selection()
        chosen = await self.click('arena_skip_more', ['40'])
        self.assertEqual(self.selection(), {**before, 'skip': 40})
        self.assertIn('Skipping 40 floors pays now: 2 Bronze, 4 Silver, 2 Gold.', chosen['embed'].description)
        await self.click('arena_team_prev')
        await self.click('arena_team_sort')
        self.assertEqual(self.selection()['skip'], 40)
        self.assertEqual(self.selection()['team'], before['team'])
        self.assertTrue(self.selection()['favorites_first'])
        self.assertIn('Skipping 1 floors pays now: nothing.', (await self.click('arena_skip', ['1']))['embed'].description)

    async def test_skip_value_out_of_range_or_malformed_refused(self):
        await self.conn.execute('UPDATE profiles SET arena_best_floor=30 WHERE profile_id=?', (self.pid,))
        await self.click('arena_team')
        for action in ('arena_skip', 'arena_skip_more'):
            for values in ([], ['16'], ['-1'], ['1.0'], ['x'], ['1', '2'], [None], [1], [True], [{}]):
                with self.subTest(action=action, values=values):
                    before = await self.resource_snapshot()
                    selected = self.session['selection']
                    with self.assertRaises(_Refused):
                        await self.click(action, values)
                    self.assertEqual(self.session['selection'], selected)
                    self.assertEqual(await self.resource_snapshot(), before)
        self.session['selection'] = '{}'
        for action in ('arena_skip', 'arena_skip_more'):
            with self.assertRaises(_Refused):
                await self.click(action, ['1'])

    async def test_start_with_skip_opens_break_at_next_floor_with_ticket_notice(self):
        await self.conn.execute('UPDATE profiles SET arena_best_floor=80 WHERE profile_id=?', (self.pid,))
        await self.picked()
        await self.click('arena_skip_more', ['40'])
        old = self.session['selection']
        started = await self.click('arena_start')
        self.assertIn('Floor 41', started['embed'].description)
        self.assertIn('Skipped 40 floors: +2 Bronze, +4 Silver, +2 Gold Tickets.', started['embed'].description)
        self.assertEqual((await self.writer.run(lambda c: service.state(c, self.session, self.now)))['tickets'],
                         {'bronze': 2, 'silver': 4, 'gold': 2})
        self.session['selection'] = old
        before = await self.resource_snapshot()
        self.assertNotIn('Skipped', (await self.click('arena_start'))['embed'].description)
        self.assertEqual(await self.resource_snapshot(), before)

    async def test_break_layout_has_toggle_in_row_0_and_threshold_in_row_4(self):
        view = await self.start_run()
        row = [item.label for item in view['view'].children if item.row == 0]
        self.assertEqual(row, ['Fight', 'Heal all & fight', 'Fight until hurt', 'Auto-order: off', 'Back out'])
        threshold = self.button(view, 'arena_stop_pct')
        self.assertEqual(threshold.row, 4)
        self.assertEqual([o.label for o in threshold.options], [f'Stop below {pct}%' for pct in service.STOP_PCTS])
        self.assertEqual([o.value for o in threshold.options], [str(pct) for pct in service.STOP_PCTS])
        self.assertEqual([o.value for o in threshold.options if o.default], ['50'])

    async def test_threshold_select_saves_and_marks_default(self):
        await self.start_run()
        for pct in (30, 90):
            before = await self.run_state()
            view = await self.click('arena_stop_pct', [str(pct)])
            self.assertEqual([o.value for o in self.button(view, 'arena_stop_pct').options if o.default], [str(pct)])
            self.assertEqual(await self.scalar('SELECT arena_stop_pct FROM profiles WHERE profile_id=?', (self.pid,)), pct)
            self.assertEqual(self.selection()['run_revision'], before['revision'] + 1)
        for values in ([], ['55'], ['0'], ['100'], ['30', '40'], ['30.0'], [30], [None], [{}]):
            before = await self.resource_snapshot()
            with self.assertRaises(_Refused):
                await self.click('arena_stop_pct', values)
            self.assertEqual(await self.resource_snapshot(), before)

    async def test_auto_order_button_toggles_label_and_setting(self):
        await self.start_run()
        for on in (True, False):
            before = await self.run_state()
            view = await self.click('arena_auto_order')
            self.assertEqual(self.button(view, 'arena_auto_order').label, 'Auto-order: ' + ('on' if on else 'off'))
            self.assertEqual(await self.scalar('SELECT arena_auto_order FROM profiles WHERE profile_id=?', (self.pid,)), on)
            self.assertEqual(self.selection()['run_revision'], before['revision'] + 1)

    async def test_setting_from_stale_screen_redraws_without_saving(self):
        await self.start_run()
        old = self.session['selection']
        run = await self.run_state()
        await self.writer.run(lambda c: service.set_stop_pct(c, self.session, run['run_id'], run['revision'], 30, self.now))
        for action, values in (('arena_stop_pct', ['90']), ('arena_auto_order', [])):
            self.session['selection'] = old
            before = await self.resource_snapshot()
            view = await self.click(action, values)
            self.assertIn(self.screens().STALE, view['embed'].description)
            self.assertEqual(await self.resource_snapshot(), before)
            self.assertEqual(self.selection()['run_revision'], 1)
            self.assertEqual(self.button(view, 'arena_auto_order').label, 'Auto-order: off')
            self.assertEqual([o.value for o in self.button(view, 'arena_stop_pct').options if o.default], ['30'])

    async def test_other_open_screen_must_redraw_after_setting_change(self):
        await self.start_run()
        first = self.session
        await self.conn.execute('INSERT INTO sessions(session_id,guild_id,user_id,profile_id,revision,expires_at) '
                                "VALUES ('abce','g','u',?,0,1e12)", (self.pid,))
        self.session = {**first, 'session_id': 'abce', 'selection': '{}'}
        await self.click('arena_resume')
        await self.click('arena_auto_order')
        self.session = first
        before = await self.resource_snapshot()
        with patch.object(test_arena.battle_engine, 'simulate', side_effect=AssertionError('stale fight')):
            view = await self.click('arena_fight')
        self.assertIn(self.screens().STALE, view['embed'].description)
        self.assertEqual(await self.resource_snapshot(), before)
        self.assertEqual(self.button(view, 'arena_auto_order').label, 'Auto-order: on')

    async def test_settings_shown_again_on_next_run(self):
        await self.start_run()
        await self.click('arena_stop_pct', ['20'])
        await self.click('arena_auto_order')
        old_id = self.selection()['run_id']
        self.now += test_arena.RULES['cooldown_seconds']
        self.session['_original_revision'] += 1
        view = await self.start_run()
        self.assertNotEqual(self.selection()['run_id'], old_id)
        self.assertEqual(self.button(view, 'arena_auto_order').label, 'Auto-order: on')
        self.assertEqual([o.value for o in self.button(view, 'arena_stop_pct').options if o.default], ['20'])

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
                    'arena_skip', 'arena_skip_more', 'arena_auto_order', 'arena_stop_pct', 'arena_until_hurt',
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
                 'arena_heal_three', 'arena_berry', 'arena_order', 'arena_auto_order', 'arena_stop_pct', 'arena_until_hurt')}
        self.assertEqual(rows, {'arena_fight': 0, 'arena_heal_fight': 0, 'arena': 0,
                                'arena_heal_one': 1, 'arena_heal_two': 1, 'arena_heal_three': 1,
                                'arena_berry': 2, 'arena_order': 3, 'arena_auto_order': 0, 'arena_stop_pct': 4, 'arena_until_hurt': 0})
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
        await self.conn.execute('UPDATE profiles SET arena_best_floor=80 WHERE profile_id=?', (self.pid,))
        views = [await self.click('arena'), await self.click('arena_team'), await self.start_run()]
        self.now += test_arena.RULES['run_seconds']
        views.append(await self.click('arena_resume'))
        for rendered in views:
            ids = [item.custom_id for item in rendered['view'].children]
            self.assertEqual(len(ids), len(set(ids)))
            if rendered['embed'].title == 'Arena break':
                self.assertEqual({item.row for item in rendered['view'].children}, {0, 1, 2, 3, 4})
            if rendered['embed'].title == 'Arena team':
                self.assertEqual({item.row if item.row is not None else item._rendered_row
                                  for item in rendered['view'].children}, {0, 1, 2, 3, 4})

    async def test_until_hurt_one_writer_job_per_fight_lists_each_fight(self):
        await self.start_run()
        run = await self.run_state()
        healthy = self.outcome(hp=tuple(m['full_hp'] for m in run['team']))
        with patch.object(self.writer, 'run', wraps=self.writer.run) as jobs:
            with patch.object(test_arena.battle_engine, 'simulate', side_effect=[healthy, self.outcome()]):
                rendered = await self.click('arena_until_hurt')
        self.assertEqual(jobs.await_count, 3)  # Dispatch, then one transaction per fight.
        text = rendered['embed'].description
        self.assertRegex(text, r'Floor 1 entry: .+ · CP \d+ · Win · 9 ticks · Candy \+1 Bulbasaur')
        self.assertRegex(text, r'Floor 1 middle: .+ · CP \d+ · Win · 9 ticks · Candy \+1 Bulbasaur')
        self.assertLess(text.index('Floor 1 entry:'), text.index('Floor 1 middle:'))
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM action_receipts WHERE action='arena_fight'"), 2)
        saved = json.loads((await self.rows('SELECT selection FROM sessions'))[0]['selection'])
        self.assertEqual(saved['run_revision'], 2)
        self.assertEqual(self.selection()['run_revision'], 2)

    async def test_until_hurt_stop_notices_threshold_revive_ticket(self):
        await self.start_run()
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome()):
            text = (await self.click('arena_until_hurt'))['embed'].description
        self.assertIn('Stopped: Bulbasaur is below 50%.', text)
        run = await self.run_state()
        await self.hurt_team(tuple(m['full_hp'] for m in run['team']))
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome(hp=(0, 4, 5), finisher=1)):
            text = (await self.click('arena_until_hurt'))['embed'].description
        self.assertIn('Stopped: Bulbasaur was revived at 1 HP.', text)
        await self.hurt_team(tuple(m['full_hp'] for m in run['team']))
        await self.conn.execute('UPDATE arena_runs SET floor=10,slot=2')
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome(hp=tuple(m['full_hp'] for m in run['team']))):
            text = (await self.click('arena_until_hurt'))['embed'].description
        self.assertIn('Stopped: floor 10 paid a ticket.', text)
        self.assertIn('Floor 10 cleared: Silver Ticket', text)
        self.assertIn('First clear: +1 Silver Ticket', text)

    async def test_hurt_member_or_stale_screen_fights_nothing(self):
        await self.start_run()
        run = await self.hurt_team()
        before = await self.resource_snapshot()
        with patch.object(test_arena.battle_engine, 'simulate', side_effect=AssertionError('unexpected fight')):
            text = (await self.click('arena_until_hurt'))['embed'].description
        self.assertIn('Bulbasaur is below 50%. Heal first, or use Fight.', text)
        self.assertEqual(await self.resource_snapshot(), before)
        await self.writer.run(lambda conn: service.set_order(conn, self.session, run['run_id'], run['revision'], [2, 1, 0], self.now))
        before = await self.resource_snapshot()
        with patch.object(test_arena.battle_engine, 'simulate', side_effect=AssertionError('stale fight')):
            text = (await self.click('arena_until_hurt'))['embed'].description
        self.assertIn(self.screens().STALE, text)
        self.assertEqual(await self.resource_snapshot(), before)
        self.session['selection'] = '{}'
        with self.assertRaises(_Refused):
            await self.click('arena_until_hurt')

    async def test_until_hurt_defeat_shows_defeat_screen_with_fights(self):
        await self.start_run()
        run = await self.run_state()
        for outcome, reason in [('loss', 'party_fainted'), ('draw', 'tick_limit')]:
            with self.subTest(outcome=outcome):
                await self.conn.execute('UPDATE arena_runs SET ended_at=NULL,end_reason=NULL')
                await self.conn.execute('DELETE FROM action_receipts')
                await self.hurt_team(tuple(m['full_hp'] for m in run['team']))
                await self.click('arena_resume')
                result = test_arena.battle_engine.Result(outcome, reason, 9, (), (), party_hp=(0, 0, 0))
                with patch.object(test_arena.battle_engine, 'simulate', return_value=result):
                    rendered = await self.click('arena_until_hurt')
                self.assertEqual(rendered['embed'].title, 'Arena defeat')
                self.assertRegex(rendered['embed'].description, r'Floor 1 entry: .+ · CP \d+ · (Loss|Draw) · 9 ticks')
                self.assertIn('time limit' if outcome == 'draw' else 'lost', rendered['embed'].description)
                self.assertNotIn('Candy +', rendered['embed'].description)

    async def test_setting_change_elsewhere_stops_chain(self):
        await self.start_run()
        run = await self.run_state()
        original = self.writer.run
        changed = False
        async def writer_job(job):
            nonlocal changed
            result = await original(job)
            if not changed and await self.scalar("SELECT COUNT(*) FROM action_receipts WHERE action='arena_fight'"):
                changed = True
                current = (await original(lambda conn: service.state(conn, self.session, self.now)))['run']
                await original(lambda conn: service.set_stop_pct(conn, self.session, current['run_id'], current['revision'], 70, self.now))
            return result
        with patch.object(self.writer, 'run', side_effect=writer_job):
            with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome(hp=tuple(m['full_hp'] for m in run['team']))) as simulated:
                text = (await self.click('arena_until_hurt'))['embed'].description
        simulated.assert_called_once()
        self.assertIn(self.screens().STALE, text)
        self.assertIn('Floor 1 entry:', text)
        self.assertEqual(self.selection()['run_revision'], 2)

    async def test_auto_order_chain_shows_order_left(self):
        await self.start_run()
        await self.click('arena_auto_order')
        run = await self.run_state()
        hp = (run['team'][0]['full_hp'] * 3 // 4, run['team'][1]['full_hp'], run['team'][2]['full_hp'])
        await self.hurt_team(hp)
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome()) as simulated:
            text = (await self.click('arena_until_hurt'))['embed'].description
        self.assertEqual([m.name for m in simulated.call_args.args[0]], ['Charmander', 'Squirtle', 'Bulbasaur'])
        self.assertIn('Candy +1 Charmander', text)
        self.assertLess(text.index('1: Charmander'), text.index('3: Bulbasaur'))

    async def test_crash_mid_chain_keeps_finished_fights_repeats_none(self):
        await self.start_run()
        run = await self.run_state()
        with patch.object(test_arena.battle_engine, 'simulate', side_effect=[self.outcome(hp=tuple(m['full_hp'] for m in run['team'])), OSError('crash')]):
            with self.assertRaisesRegex(OSError, 'crash'):
                await self.click('arena_until_hurt')
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM action_receipts WHERE action='arena_fight'"), 1)
        saved = json.loads((await self.rows('SELECT selection FROM sessions'))[0]['selection'])
        self.assertEqual(saved['run_revision'], 1)
        self.session['selection'] = json.dumps(saved)
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome()) as simulated:
            text = (await self.click('arena_until_hurt'))['embed'].description
        simulated.assert_called_once()
        self.assertIn('Floor 1 middle:', text)
        self.assertNotIn('Floor 1 entry:', text)
        self.assertEqual(await self.scalar("SELECT COUNT(*) FROM action_receipts WHERE action='arena_fight'"), 2)

    async def test_drain_mid_chain_returns_last_committed_screen(self):
        from pokewalker.bot.walker import RESTARTING
        await self.start_run()
        run = await self.run_state()
        original = self.writer.run
        async def draining(job):
            result = await original(job)
            if await self.scalar("SELECT COUNT(*) FROM action_receipts WHERE action='arena_fight'"):
                self.walker.bot._stopping = True
                await self.writer.close()
            return result
        with patch.object(self.writer, 'run', side_effect=draining):
            with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome(hp=tuple(m['full_hp'] for m in run['team']))) as simulated:
                rendered = await self.click('arena_until_hurt')
        simulated.assert_called_once()
        self.assertEqual(rendered['content'], RESTARTING)
        self.assertIn('Floor 1 entry:', rendered['embed'].description)
        self.assertEqual(json.loads((await self.rows('SELECT selection FROM sessions'))[0]['selection'])['run_revision'], 1)

    async def test_chain_without_run_leaves_session_untouched(self):
        from pokewalker.bot.walker import REOPEN, EXCLUDED
        await self.start_run()
        for excluded in (False, True):
            self.session['profile_id'] = self.other if not excluded else self.pid
            if excluded:
                await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
            before = await self.rows('SELECT * FROM sessions')
            selection = self.session['selection']
            with patch.object(test_arena.battle_engine, 'simulate', side_effect=AssertionError('refused fight')):
                result = await self.click('arena_until_hurt')
            self.assertEqual(result, {'content': EXCLUDED if excluded else REOPEN})
            self.assertEqual(await self.rows('SELECT * FROM sessions'), before)
            self.assertEqual(self.session['selection'], selection)

    async def test_chain_closed_writer_before_first_fight_and_unexpected_runtime_error(self):
        from pokewalker.bot.walker import RESTARTING
        await self.start_run()
        handler = self.screens().handlers(self.walker)['arena_until_hurt']
        before = self.session['selection']
        with patch.object(service, 'chain_step', side_effect=AssertionError('dispatch must not fight')):
            pending = await self.writer.run(lambda conn: handler(conn, self.session, SimpleNamespace(data={})))
        self.assertEqual(set(pending), {'after_commit'})
        self.assertEqual(self.session['selection'], before)
        with patch.object(self.writer, 'run', side_effect=RuntimeError('unexpected failure')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected failure'):
                await pending['after_commit']()
        self.walker.bot._stopping = True
        await self.writer.close()
        self.assertEqual(await pending['after_commit'](), {'content': RESTARTING})

    async def test_fifteen_fight_chain_fits_embed_without_level_or_ivs(self):
        await self.start_run()
        run = await self.run_state()
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome(hp=tuple(m['full_hp'] for m in run['team']))) as simulated:
            text = (await self.click('arena_until_hurt'))['embed'].description
        self.assertEqual(simulated.call_count, 15)
        self.assertEqual(len(re.findall(r'^Floor \d+ (entry|middle|boss):', text, re.M)), 15)
        self.assertIn('Stopped: floor 5 paid a ticket.', text)
        self.assertLessEqual(len(text.encode('utf-16-le')) // 2, 4096)
        self.assertNotRegex(text, r'(?i)level|ivs?|iv_attack|level_x2')

    async def test_chain_rechecks_expiry_and_exclusion_between_fights(self):
        for stop in ('expiry', 'exclusion'):
            with self.subTest(stop=stop):
                await self.conn.execute('DELETE FROM restrictions')
                await self.conn.execute('DELETE FROM arena_runs')
                await self.conn.execute('DELETE FROM action_receipts')
                self.now = 1000
                await self.start_run()
                run = await self.run_state()
                original = self.writer.run
                async def stopping(job):
                    result = await original(job)
                    if await self.scalar("SELECT COUNT(*) FROM action_receipts WHERE action='arena_fight'"):
                        if stop == 'expiry':
                            self.now += test_arena.RULES['run_seconds']
                        else:
                            await self.conn.execute("INSERT OR IGNORE INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
                    return result
                with patch.object(self.writer, 'run', side_effect=stopping):
                    with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome(hp=tuple(m['full_hp'] for m in run['team']))) as simulated:
                        rendered = await self.click('arena_until_hurt')
                simulated.assert_called_once()
                self.assertEqual(await self.scalar("SELECT COUNT(*) FROM action_receipts WHERE action='arena_fight'"), 1)
                self.assertEqual(await self.scalar('SELECT quantity FROM candy WHERE profile_id=?', (self.pid,)), 1 if stop == 'expiry' else 2)
                if stop == 'expiry':
                    self.assertEqual(rendered['embed'].title, 'Arena defeat')
                    self.assertIn('18 hours passed', rendered['embed'].description)
                else:
                    from pokewalker.bot.walker import EXCLUDED
                    self.assertEqual(rendered['content'], EXCLUDED)
                    self.assertEqual(self.selection()['run_revision'], 1)

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

    async def test_m1_team_selection_without_skip_starts(self):
        await self.enroll()
        _, session = await self.open()
        pid = session['profile_id']
        for uid in ('router1', 'router2'):
            await self.conn.execute('INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,'
                                    'iv_defense,iv_stamina,gender,shiny,origin,content_version,caught_at) '
                                    "VALUES (?,?,1,20,10,10,10,'male',0,'catch','test',0)", (uid, pid))
        members = await self.rows('SELECT pokemon_uid,revision FROM pokemon WHERE profile_id=?', (pid,))
        selection = {'phase': 'arena_team', 'team': [[m['pokemon_uid'], m['revision']] for m in members],
                     'offset': 0, 'favorites_first': False}
        await self.conn.execute('UPDATE sessions SET selection=? WHERE session_id=?',
                                (json.dumps(selection), session['session_id']))
        interaction = await self.click(session, 'arena_start')
        rendered = interaction.edit_original_response.await_args.kwargs
        self.assertEqual(rendered['embed'].title, 'Arena break')
        self.assertIn('Floor 1', rendered['embed'].description)
        self.assertNotIn('Skipped', rendered['embed'].description)
        self.assertEqual(await self.rows('SELECT * FROM arena_tickets'), [])
        saved = (await self.rows('SELECT * FROM sessions WHERE session_id=?', (session['session_id'],)))[0]
        self.assertEqual(json.loads(saved['selection'])['phase'], 'arena_break')
        self.assertEqual(saved['revision'], session['revision'] + 1)

    async def test_until_hurt_through_router_saves_run_revision(self):
        await self.test_m1_team_selection_without_skip_starts()
        session = (await self.rows('SELECT * FROM sessions'))[-1]
        team = json.loads((await self.rows('SELECT team FROM arena_runs'))[0]['team'])
        healthy = test_arena.battle_engine.Result('win', 'defender_fainted', 9, (0, 1, 2), (),
                                                party_hp=tuple(m['full_hp'] for m in team), finisher=0)
        hurt = test_arena.battle_engine.Result('win', 'defender_fainted', 9, (0, 1, 2), (), party_hp=(3, 4, 5), finisher=0)
        with patch.object(test_arena.battle_engine, 'simulate', side_effect=[healthy, hurt]):
            pressed = await self.click(session, 'arena_until_hurt')
        pressed.edit_original_response.assert_awaited_once()
        self.assertIn('Floor 1 middle:', pressed.edit_original_response.await_args.kwargs['embed'].description)
        saved = (await self.rows('SELECT * FROM sessions'))[-1]
        run = (await self.rows('SELECT * FROM arena_runs'))[0]
        self.assertEqual(json.loads(saved['selection'])['run_revision'], run['revision'])
        self.assertEqual(run['revision'], 2)
        self.assertEqual(saved['revision'], session['revision'] + 1)

    async def test_every_arena_action_is_registered(self):
        from pokewalker.bot import arena
        expected = set(arena.handlers(self.walker))
        self.assertTrue(expected)
        self.assertEqual({action for action in self.walker.handlers if action.startswith('arena')}, expected)
