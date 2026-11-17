"""C5 EXR-7: kind-specific catch wording and selected-raid Back on real SQLite."""

import json
import unittest
from unittest.mock import patch

from pokewalker.services import raids
import test_raids


class ExRaidScreenTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_raids.RaidWalkerTests.asyncSetUp
    interaction = test_raids.RaidWalkerTests.interaction
    rows = test_raids.RaidWalkerTests.rows
    open = test_raids.RaidWalkerTests.open
    click = test_raids.RaidWalkerTests.click
    enroll = test_raids.RaidWalkerTests.enroll
    ready = test_raids.RaidWalkerTests.ready
    current = test_raids.RaidWalkerTests.current
    encounter_row = test_raids.RaidWalkerTests.encounter_row

    async def both_raids(self, selected='ex', *, ordinary=True):
        self.walker.clock = lambda: 1000
        if not hasattr(self, 'session'):
            self.session = await self.ready()
        identity = next(i for i in self.bot.content['identities'] if i['species_id'] == 144)

        async def seed(conn):
            await conn.execute('DELETE FROM encounters')
            await conn.execute('DELETE FROM world_spawns')
            await conn.execute('UPDATE profiles SET storage_limit=300')
            if ordinary:
                columns = ','.join(self.encounter)
                await conn.execute(f'INSERT INTO encounters({columns}) VALUES '
                                   f"({','.join('?' for _ in self.encounter)})", tuple(self.encounter.values()))
            for kind in ('world', 'ex'):
                await conn.execute(
                    'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,'
                    'spawned_at,expires_at,post_state,content_version,kind) '
                    "VALUES (?,'123','channel',?,?,900,1200,'sent','fixture',?)",
                    (kind, identity['pokemon_id'], identity['identity_id'], kind))
            self.ids = {}
            for kind in ('world', 'ex'):
                result = await raids.join(conn, 123, 456, kind, 1000, self.walker.rng, self.bot.content)
                self.assertEqual(result['status'], 'new')
                self.ids[kind] = result['encounter_id']
            await conn.execute('UPDATE encounters SET shiny=1 WHERE raid_spawn_id IS NOT NULL')
            for item in ('poke_ball', 'great_ball', 'master_ball', 'razz_berry'):
                await conn.execute('INSERT INTO inventory VALUES (?,?,5) '
                                   'ON CONFLICT(profile_id,item_id) DO UPDATE SET quantity=5',
                                   (self.session['profile_id'], item))
            selection = {'encounter_id': self.ids[selected], 'encounter_revision': 0,
                         'ball': 'great_ball', 'berry': 'razz_berry'}
            await conn.execute('UPDATE sessions SET selection=? WHERE session_id=?',
                               (json.dumps(selection), self.session['session_id']))
        await self.writer.run(seed)
        return await self.current(self.session)

    async def screen(self, session, action, values=None):
        interaction = await self.click(session, action, values)
        return interaction.edit_original_response.await_args.kwargs, await self.current(session)

    async def confirmation(self, session, kind):
        if kind == 'master':
            _, session = await self.screen(session, 'pick_ball', ['master_ball'])
        if kind == 'storage':
            # The enrolled starter fills a one-slot fixture capacity.
            await self.writer.run(lambda c: c.execute('UPDATE profiles SET storage_limit=1'))
        rendered, session = await self.screen(session, 'run' if kind == 'shiny' else 'throw')
        expected = {'master': 'Confirm Master Ball', 'shiny': 'Confirm Run', 'storage': 'Wild encounter'}[kind]
        self.assertEqual(rendered['embed'].title, expected)
        if kind == 'storage':
            self.assertIn('Storage is full', rendered['embed'].description)
        return rendered, session

    async def assert_kind(self, session, kind):
        state = await self.writer.run(lambda c: self.walker.encounter_state(
            c, session, json.loads(session['selection'])['encounter_id']))
        self.assertEqual(state.get('raid_kind'), kind)
        return state

    def assert_ex_tier(self, rendered):
        description = rendered['embed'].description
        self.assertIn(' · EX-Raid', description)
        self.assertNotIn('Legendary', description)

    async def test_ex_catch_screen_shows_ex_raid_line_and_tier_for_a_legendary_boss(self):
        session = await self.both_raids()
        state = await self.assert_kind(session, 'ex')
        self.assertEqual(state['encounter']['tier'], 'Legendary/Mythical')
        rendered = self.module.screens.render_catch(state)
        self.assertIn('Articuno', rendered['embed'].description)
        self.assertIn('EX-Raid · ends 1970-01-01 00:20:00 UTC', rendered['embed'].description)
        self.assert_ex_tier(rendered)

    async def test_ball_and_berry_rerenders_keep_the_ex_raid_line(self):
        session = await self.both_raids()
        for action, values in (('select_ball', None), ('pick_ball', ['poke_ball']),
                               ('select_berry', None), ('pick_berry', ['none'])):
            with self.subTest(action=action):
                rendered, session = await self.screen(session, action, values)
                self.assertIn('EX-Raid · ends 1970-01-01 00:20:00 UTC', rendered['embed'].description)
                self.assert_ex_tier(rendered)

    async def test_confirm_and_result_screens_show_ex_raid_tier(self):
        for kind in ('master', 'shiny', 'storage'):
            with self.subTest(kind=kind):
                session = await self.both_raids()
                rendered, session = await self.confirmation(session, kind)
                self.assert_ex_tier(rendered)
                if kind != 'storage':
                    rendered, session = await self.screen(session, 'master_confirm' if kind == 'master' else 'run_confirm')
                    self.assertEqual(rendered['embed'].title, 'Encounter result')
                    self.assert_ex_tier(rendered)
                    if kind == 'master':
                        reopened, _ = await self.open()
                        self.assert_ex_tier(reopened.edit_original_response.await_args.kwargs)
                        await self.writer.run(lambda c: c.execute('DELETE FROM pokemon WHERE source_encounter_id IS NOT NULL'))

    async def test_run_after_ex_expiry_says_the_ex_raid_left(self):
        for confirmed in (False, True):
            with self.subTest(confirmed=confirmed):
                session = await self.both_raids()
                if confirmed:
                    _, session = await self.confirmation(session, 'shiny')
                self.walker.clock = lambda: 1200
                before = await self.rows('SELECT * FROM encounters')
                refused = await self.click(session, 'run_confirm' if confirmed else 'run')
                self.assertEqual(refused.followup.send.await_args.args[0], 'The EX-Raid left.')
                self.assertEqual(await self.rows('SELECT * FROM encounters'), before)

    async def test_throw_after_ex_expiry_says_this_ex_raid_ended(self):
        session = await self.both_raids()
        self.walker.clock = lambda: 1200
        before = await self.rows('SELECT * FROM inventory')
        with patch.object(self.walker.rng, 'random', side_effect=AssertionError('expired roll')):
            rendered, _ = await self.screen(session, 'throw')
        self.assertIn('This EX-Raid ended; this encounter expired.', rendered['embed'].description)
        self.assert_ex_tier(rendered)
        self.assertEqual(await self.rows('SELECT * FROM inventory'), before)

    async def test_world_legendary_screens_and_refusals_unchanged(self):
        session = await self.both_raids('world')
        state = await self.writer.run(lambda c: self.walker.encounter_state(c, session, self.ids['world']))
        self.assertEqual(state['raid_line'], 'World Legendary · ends 1970-01-01 00:20:00 UTC')
        for render in (self.module.screens.render_catch, self.module.screens.render_master_confirm,
                       self.module.screens.render_run_confirm, self.module.screens.render_terminal):
            description = render(state)['embed'].description
            self.assertIn(' · Legendary/Mythical', description)
            self.assertNotIn('EX-Raid', description)
        self.walker.clock = lambda: 1200
        refused = await self.click(session, 'run')
        self.assertEqual(refused.followup.send.await_args.args[0], 'The World Legendary left.')
        rendered, _ = await self.screen(session, 'throw')
        self.assertIn('The World Legendary left; this encounter expired.', rendered['embed'].description)

    async def test_back_from_master_ball_shiny_run_and_storage_confirm_returns_to_selected_raid(self):
        for selected in ('world', 'ex'):
            for kind in ('master', 'shiny', 'storage'):
                with self.subTest(selected=selected, kind=kind):
                    session = await self.both_raids(selected)
                    _, session = await self.confirmation(session, kind)
                    before = await self.rows('SELECT * FROM encounters ORDER BY encounter_id')
                    inventory = await self.rows('SELECT * FROM inventory')
                    selection = json.loads(session['selection'])
                    with patch.object(self.walker.rng, 'random', side_effect=AssertionError('Back rerolled')):
                        _, session = await self.screen(session, 'open_encounter')
                    after = json.loads(session['selection'])
                    self.assertEqual(after['encounter_id'], self.ids[selected])
                    self.assertEqual((after['ball'], after['berry']), (selection['ball'], selection['berry']))
                    for flag in ('master_confirm', 'run_confirm', 'storage_confirm'):
                        self.assertNotIn(flag, after)
                    self.assertEqual(await self.rows('SELECT * FROM encounters ORDER BY encounter_id'), before)
                    self.assertEqual(await self.rows('SELECT * FROM inventory'), inventory)
                    self.assertEqual(len(await self.rows('SELECT * FROM raid_participation')), 2)

    async def test_back_after_selected_spawn_expired_follows_the_m81c_fallback(self):
        for selected in ('world', 'ex'):
            for cleanup in (False, True):
                for ordinary in (False, True):
                    for kind in ('master', 'shiny', 'storage'):
                        with self.subTest(selected=selected, cleanup=cleanup, ordinary=ordinary, kind=kind):
                            session = await self.both_raids(selected, ordinary=ordinary)
                            _, session = await self.confirmation(session, kind)
                            await self.writer.run(lambda c: c.execute(
                                'UPDATE world_spawns SET expires_at=1100 WHERE spawn_id=?', (selected,)))
                            self.walker.clock = lambda: 1100
                            other = 'ex' if selected == 'world' else 'world'
                            before = await self.rows('SELECT * FROM encounters WHERE encounter_id=?', (self.ids[other],))
                            if cleanup:
                                await self.writer.run(lambda c: raids.expire(c, 1100))
                            rendered, session = await self.screen(session, 'open_encounter')
                            selection = json.loads(session['selection'])
                            if ordinary:
                                self.assertEqual(selection['encounter_id'], self.encounter['encounter_id'])
                                self.assertEqual(rendered['embed'].title, 'Wild encounter')
                            else:
                                self.assertEqual(rendered['embed'].title, 'Walker')
                            for flag in ('master_confirm', 'run_confirm', 'storage_confirm'):
                                self.assertNotIn(flag, selection)
                            self.assertEqual(await self.rows('SELECT * FROM encounters WHERE encounter_id=?',
                                                             (self.ids[other],)), before)
