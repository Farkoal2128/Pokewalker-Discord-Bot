"""Route choices through the durable router, real SQLite and seeded minting."""

from collections import defaultdict
import copy
from datetime import datetime, timezone
import importlib
import random
import unittest
from unittest.mock import patch

from content.balance import load_table
from pokewalker.domain import encounters
from pokewalker.services import stepping
import test_walker_encounter as encounter_tests


class RouteTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = encounter_tests.EncounterTests.asyncSetUp
    interaction = encounter_tests.EncounterTests.interaction
    rows = encounter_tests.EncounterTests.rows
    open = encounter_tests.EncounterTests.open
    click = encounter_tests.EncounterTests.click
    enroll = encounter_tests.EncounterTests.enroll
    exclude = encounter_tests.EncounterTests.exclude
    ready = encounter_tests.EncounterTests.ready
    current = encounter_tests.EncounterTests.current
    reveal = encounter_tests.EncounterTests.reveal

    async def act(self, session, action, values=None):
        interaction = await self.click(session, action, values)
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs, await self.current(session)

    async def seed_steps(self, awarded_c=1_800_000, profile_id=None, message_id='route-history'):
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO step_events VALUES (?,?, '789',18000,18000,0,?,'credited',0)",
            (message_id, profile_id or self.profile['profile_id'], awarded_c)))

    async def snapshot(self):
        tables = await self.rows("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return {row['name']: await self.rows(f"SELECT * FROM {row['name']}") for row in tables}

    async def test_route_screen_lists_eight_routes_with_weights_and_current(self):
        session = await self.ready()
        await self.seed_steps()
        home, _ = await self.open()
        button = next(item for item in home.edit_original_response.await_args.kwargs['view'].children
                      if getattr(item, 'label', None) == 'Route')
        self.assertFalse(button.disabled)
        rendered, session = await self.act(session, 'route')
        routes = load_table('routes')['routes']
        self.assertEqual(len(rendered['embed'].fields), 8)
        for field, route in zip(rendered['embed'].fields, routes):
            self.assertEqual(field.name, route['name'] + (' · Current' if route['id'] == 'refreshing_field' else ''))
            self.assertEqual(field.value.splitlines(), [
                f"{weight}: " + ', '.join(kind.title() for kind, value in route['weights'].items() if value == weight)
                for weight in (3, 2, 1)])
        select = next(item for item in rendered['view'].children if hasattr(item, 'options'))
        self.assertEqual([option.value for option in select.options], [route['id'] for route in routes])
        self.assertEqual([option.value for option in select.options if option.default], ['refreshing_field'])
        self.assertTrue(select.custom_id.endswith(':route_pick'))
        back = next(item for item in rendered['view'].children if getattr(item, 'label', None) == 'Back')
        self.assertTrue(back.custom_id.endswith(':home'))
        rendered, _ = await self.act(session, 'home')
        self.assertEqual(rendered['embed'].title, 'Walker')

    async def test_default_route_is_refreshing_field(self):
        await self.enroll()
        self.assertEqual((await self.rows('SELECT route_id FROM profiles'))[0]['route_id'], 'refreshing_field')

    async def test_pick_updates_profile_and_next_encounter_uses_new_route_seeded(self):
        session = await self.ready()
        await self.seed_steps()
        await self.writer.run(lambda conn: conn.execute('UPDATE profiles SET encounter_meter_c=9900'))
        rendered, _ = await self.act(session, 'route_pick', ['volcano_path'])
        profile = (await self.rows('SELECT * FROM profiles'))[0]
        self.assertEqual(profile['route_id'], 'volcano_path')
        self.assertIn('Volcano Path · Current', [field.name for field in rendered['embed'].fields])
        pools = defaultdict(list)
        for identity in self.bot.content['identities']:
            pools[identity['tier']].append(identity)
        expected = encounters.generate(pools, self.bot.content['routes']['volcano_path'], False, random.Random(18),
                                       chances=load_table('tier_chances')['chances'], rules=load_table('catch')['rules'])
        # Deliberately pass the old profile snapshot; minting must re-read route_id.
        eid = await self.writer.run(lambda conn: stepping.credit_message(
            conn, self.profile, ['fresh', 'route', 'choice', 'words'], datetime.fromtimestamp(1000, timezone.utc),
            'mint-route', '789', content=self.bot.content, rng=random.Random(18), cache=stepping.DigestCache()))
        minted = (await self.rows('SELECT * FROM encounters WHERE encounter_id=?', (eid,)))[0]
        self.assertEqual(minted['route_id'], 'volcano_path')
        self.assertEqual((minted['pokemon_id'], minted['level_x2'], minted['iv_attack'], minted['iv_defense'],
                          minted['iv_stamina'], minted['gender'], minted['shiny'], minted['tier']),
                         (expected.pokemon_id, expected.level_x2, *expected.ivs,
                          expected.gender or 'genderless', expected.shiny, expected.tier))

    async def test_switch_never_rerolls_queued_or_revealed_encounters(self):
        session = await self.ready()
        await self.seed_steps()
        _, session = await self.reveal(session)
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO encounters(encounter_id,profile_id,source_channel_id,source_message_id,pokemon_id,"
            "level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,tier,route_id,lure_id,state,"
            "attempt_ordinal,revision,content_version,created_at,resolved_at,acknowledged_at) "
            "SELECT 'queued-copy',profile_id,source_channel_id,source_message_id,pokemon_id,"
            "level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,tier,route_id,lure_id,'queued',"
            "attempt_ordinal,revision,content_version,2,NULL,NULL FROM encounters LIMIT 1"))
        before = await self.rows('SELECT * FROM encounters')
        self.assertEqual({row['state'] for row in before}, {'queued', 'revealed'})
        with patch.object(self.walker.rng, 'random', side_effect=AssertionError('switch rerolled')):
            await self.act(session, 'route_pick', ['dim_cave'])
        self.assertEqual(await self.rows('SELECT * FROM encounters'), before)

    async def test_switch_changes_no_meter_and_grants_nothing(self):
        session = await self.ready()
        await self.seed_steps()
        await self.writer.run(lambda conn: conn.execute(
            'UPDATE profiles SET encounter_meter_c=7123,find_meter_c=3412,companion_meter_c=9988,stardust=55'))
        before = await self.snapshot()
        _, session = await self.act(session, 'route_pick', ['blue_lake'])
        after = await self.snapshot()
        expected = copy.deepcopy(before)
        expected['profiles'][0]['route_id'] = 'blue_lake'
        expected['sessions'][0]['revision'] += 1
        self.assertEqual(after, expected)
        before = after
        await self.act(session, 'route_pick', ['blue_lake'])
        before['sessions'][0]['revision'] += 1
        self.assertEqual(await self.snapshot(), before)

    async def test_invalid_route_refused_no_change(self):
        session = await self.ready()
        # A table-only ID is invalid when absent from the installed artifact.
        self.bot.content['routes'].pop('dim_cave')
        for values in ([], ['unknown'], ['dim_cave'], ['refreshing_field', 'blue_lake'], [None], [{}], 3,
                       {'0': 'blue_lake'}, 'blue_lake'):
            before = await self.snapshot()
            interaction = await self.click(session, 'route_pick', values)
            interaction.edit_original_response.assert_not_awaited()
            interaction.followup.send.assert_awaited_once()
            self.assertEqual(await self.snapshot(), before)

    async def test_all_eight_routes_selectable_after_18000_steps(self):
        session = await self.ready()
        await self.seed_steps()
        for route in load_table('routes')['routes']:
            rendered, session = await self.act(session, 'route_pick', [route['id']])
            self.assertEqual((await self.rows('SELECT route_id FROM profiles'))[0]['route_id'], route['id'])
            select = next(item for item in rendered['view'].children if hasattr(item, 'options'))
            self.assertEqual(len(select.options), 8)
            self.assertEqual([option.value for option in select.options if option.default], [route['id']])

    async def test_other_user_cannot_switch(self):
        session = await self.ready()
        for action in ('route', 'route_pick'):
            before = await self.snapshot()
            interaction = await self.click(session, action, ['blue_lake'], user=999)
            self.assertIn('not yours', interaction.followup.send.await_args.args[0])
            self.assertEqual(await self.snapshot(), before)

    async def test_excluded_refused_in_router(self):
        session = await self.ready()
        await self.exclude()
        for action in ('route', 'route_pick'):
            before = await self.snapshot()
            interaction = await self.click(session, action, ['blue_lake'])
            self.assertIn('excluded', interaction.followup.send.await_args.args[0])
            self.assertEqual(await self.snapshot(), before)

    async def test_render_functions_do_no_io(self):
        session = await self.ready()
        module = importlib.import_module('pokewalker.bot.route')
        state = {'session': session, 'routes': load_table('routes')['routes'], 'route_id': 'refreshing_field'}
        before = copy.deepcopy(state)
        with patch('builtins.open', side_effect=AssertionError('render file I/O')), \
                patch('pathlib.Path.open', side_effect=AssertionError('render path I/O')), \
                patch('aiosqlite.connect', side_effect=AssertionError('render DB I/O')), \
                patch.object(module, 'load_table', side_effect=AssertionError('render balance I/O')):
            rendered = module.render(state)
        ids = [item.custom_id for item in rendered['view'].children]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(state, before)


if __name__ == '__main__':
    unittest.main()
