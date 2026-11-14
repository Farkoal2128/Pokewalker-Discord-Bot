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
from pokewalker.services import arena as service, gyms
import test_arena


class ArenaScreenTests(unittest.IsolatedAsyncioTestCase):
    profile = test_arena.ArenaTests.profile
    scalar = test_arena.ArenaTests.scalar
    rows = test_arena.ArenaTests.rows

    async def asyncSetUp(self):
        await test_arena.ArenaTests.asyncSetUp(self)
        await self.conn.execute("UPDATE sessions SET session_id='abcd'")
        self.session.update(session_id='abcd', revision=0, selection='{}')
        self.now = 1000
        self.walker = SimpleNamespace(bot=SimpleNamespace(content=test_arena.CONTENT),
                                      clock=lambda: self.now, rng=random.Random(7),
                                      multipliers=test_arena.MULTIPLIERS)

    def screens(self):
        try:
            return importlib.import_module('pokewalker.bot.arena')
        except ModuleNotFoundError:
            self.fail('Arena screen handlers are absent')

    async def click(self, action, values=None):
        interaction = SimpleNamespace(data={'values': values or []})
        rendered = await self.writer.run(lambda conn: self.screens().handlers(self.walker)[action](conn, self.session, interaction))
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
        self.assertTrue(self.button(ready, 'arena_tickets').disabled)
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
        self.assertEqual(self.selection(), {'phase': 'arena_break', 'run_id': run['run_id'], 'run_revision': run['revision']})
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
                    'arena_team_sort', 'arena_team_pick', 'arena_team_clear', 'arena_start'}
        self.assertEqual(set(mapping), expected)
        for action in mapping:
            self.assertIsNotNone(re.fullmatch('[a-z_]+', action))
        self.assertNotIn('arena', Walker(self.walker.bot).handlers)
        await self.click('arena')
        await self.start_run()

    async def test_render_functions_do_no_io(self):
        screens = self.screens()
        for action, function in [('arena', 'render_home'), ('arena_team', 'render_team'), ('arena_start', 'render_break')]:
            if action == 'arena_start':
                await self.picked()
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

    async def test_resume_at_hour_18_expires_and_returns_home(self):
        await self.start_run()
        self.now += test_arena.RULES['run_seconds']
        rendered = await self.click('arena_resume')
        self.assertEqual(rendered['embed'].title, 'Arena')
        self.assertIn('Your last run ended on floor 1.', rendered['embed'].description)
        self.assertEqual(await self.rows('SELECT ended_at,end_reason,revision FROM arena_runs'),
                         [{'ended_at': self.now, 'end_reason': 'expired', 'revision': 1}])
        self.assertFalse(self.button(rendered, 'arena_team').disabled)
