"""D59 pure completion and atomic, lossless reward-inbox contracts."""

import asyncio
import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from content.balance import load_table
import test_catching as catching_tests
from pokewalker import db
from pokewalker.services import items


def fixture():
    return json.loads(Path('tests/fixtures/content_mini/content/artifact/content.json').read_text(encoding='utf-8'))


class DueTests(unittest.TestCase):
    def service(self):
        return importlib.import_module('pokewalker.services.milestones')

    def test_due_covers_every_category_from_fixture(self):
        content = fixture()
        actual = dict(self.service().due(set(map(int, content['species'])), set(), content))
        expected = {'pokedex:' + str(p) for p in (5, 10, 25, 50, 75, 90, 100)}
        expected |= {f'{category}:{g}' for category in ('starter_trios', 'regions') for g in range(1, 10)}
        expected |= {'all_starters:all', 'all_legendaries:all', 'all_mythicals:all',
                     'first_legendary:first', 'first_mythical:first', 'legendary_groups:fixture_legendary',
                     'mythical_sets:1', 'ultra_beast_first_catches:793', 'evolution_lines:1'}
        self.assertEqual(set(actual), expected)
        self.assertEqual(self.service().due(set(map(int, content['species'])), set(actual), content), [])
        self.assertEqual(self.service().due(set(), set(), content), [])

    def test_pokedex_percent_uses_installed_species_count(self):
        content = fixture()
        content['species'] = {str(i): {} for i in range(1, 1026)}
        content['milestones'] = {'bundles': content['milestones']['bundles'],
                                 'pokedex': [{'percent': 5, 'species_count': 1, 'bundle': 'bronze'}]}
        self.assertEqual(self.service().due(set(range(1, 52)), set(), content), [])
        self.assertEqual(self.service().due(set(range(1, 53)), set(), content)[0][0], 'pokedex:5')

    def test_earned_stays_earned_when_species_count_changes(self):
        content = fixture()
        earned = {key for key, _ in self.service().due(set(map(int, content['species'])), set(), content)}
        content['species']['9999'] = {'is_legendary': False, 'is_mythical': False}
        self.assertEqual(self.service().due(set(map(int, content['species'])), earned, content), [])

    def test_evolution_line_pays_25_candy_1_ultra_250_per_species(self):
        rewards = dict(self.service().due({1, 2, 3}, set(), fixture()))['evolution_lines:1']
        self.assertEqual(rewards, [{'resource': 'candy', 'resource_id': '1', 'quantity': 25},
                                  {'resource': 'item', 'resource_id': 'ultra_ball', 'quantity': 1},
                                  {'resource': 'stardust', 'resource_id': None, 'quantity': 750}])

    def test_extra_bundle_lines_pay_line_reward_plus_bundle(self):
        content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        for extra in content['milestones']['extra_bundle_lines']:
            rewards = dict(self.service().due(set(extra['species_ids']), set(), content))
            family = content['species'][str(extra['species_ids'][0])]['family_id']
            self.assertIn('evolution_lines:' + str(family), rewards)
            lines = rewards['extra_bundle_lines:' + extra['id']]
            self.assertEqual(sum(line['quantity'] for line in lines),
                             sum(content['milestones']['bundles'][extra['bundle']].values()))

    def test_galarian_form_completes_birds_group(self):
        content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        bird = next(i for i in content['identities'] if i['pokemon_id'] == 10169)
        self.assertIn('legendary_groups:birds', dict(self.service().due({bird['species_id'], 145, 146}, set(), content)))


class MilestoneTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache = Path('build/test-milestones')
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'game.sqlite3'
        async def open_fixture(*args, **kwargs):
            return await db.open_db(self.path)
        with patch('test_walker_router.open_db', new=open_fixture):
            await catching_tests.CatchingTests.asyncSetUp(self)
    interaction = catching_tests.CatchingTests.interaction
    rows = catching_tests.CatchingTests.rows
    open = catching_tests.CatchingTests.open
    click = catching_tests.CatchingTests.click
    enroll = catching_tests.CatchingTests.enroll
    exclude = catching_tests.CatchingTests.exclude
    ready = catching_tests.CatchingTests.ready
    current = catching_tests.CatchingTests.current
    reveal = catching_tests.CatchingTests.reveal
    prepared = catching_tests.CatchingTests.prepared
    encounter_row = catching_tests.CatchingTests.encounter_row
    throw = catching_tests.CatchingTests.throw
    inventory = catching_tests.CatchingTests.inventory

    def service(self):
        return importlib.import_module('pokewalker.services.milestones')

    async def award(self):
        return await self.writer.run(lambda conn: self.service().check_and_award(
            conn, self.profile['profile_id'], self.bot.content, 1000))

    async def claim(self, session):
        return await self.writer.run(lambda conn: self.service().claim(conn, session, 1000))

    async def completing_catch(self):
        session = await self.prepared(pokemon_id=7)
        await self.writer.run(lambda c: c.execute('INSERT INTO pokedex VALUES (?,4,0,0)', (self.profile['profile_id'],)))
        return session

    async def restart(self):
        await self.writer.close()
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.bot.conn, self.bot.writer = self.conn, self.writer
        self.walker = self.module.Walker(self.bot, clock=lambda: 1001)
        self.bot.walker = self.walker

    async def seed_gold(self):
        session = await self.ready()
        async def seed(conn):
            await conn.execute('DELETE FROM inventory')
            await conn.execute('INSERT INTO milestone_awards VALUES (?,?,?)',
                               (self.profile['profile_id'], 'pokedex:50', 1000))
            await conn.executemany('INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) VALUES (?,?,?,?,?,?)',
                                  [(self.profile['profile_id'], 'pokedex:50', 'stardust' if k == 'stardust' else 'item',
                                    None if k == 'stardust' else k, v, 1000)
                                   for k, v in self.bot.content['milestones']['bundles']['gold'].items()])
        await self.writer.run(seed)
        return session

    async def snapshot(self):
        return {t: await self.rows('SELECT * FROM ' + t) for t in
                ('profiles', 'inventory', 'candy', 'milestone_awards', 'inbox_items', 'action_receipts', 'resource_ledger')}

    async def test_catch_completing_milestone_awards_once_with_inbox_in_same_commit(self):
        session = await self.completing_catch()
        await self.award()
        self.assertEqual(await self.rows('SELECT * FROM milestone_awards'), [])
        execute = self.conn.execute
        def fail(sql, parameters=()):
            if 'INSERT INTO inbox_items' in sql:
                raise RuntimeError('inbox unavailable')
            return execute(sql, parameters)
        before = await self.snapshot()
        with patch.object(self.conn, 'execute', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'inbox unavailable'):
                await self.throw(session)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.encounter_row())['state'], 'revealed')
        await self.throw(session)
        awards = await self.rows('SELECT * FROM milestone_awards')
        self.assertTrue(awards)
        self.assertTrue(await self.rows('SELECT * FROM inbox_items'))
        await self.award()
        self.assertEqual(await self.rows('SELECT * FROM milestone_awards'), awards)

    async def test_restart_after_award_commit_then_recheck_exactly_one_award(self):
        session = await self.completing_catch()
        await self.throw(session)
        before = await self.snapshot()
        self.assertEqual(len(before['milestone_awards']), 1)
        await self.restart()
        await self.award()
        self.assertEqual(await self.snapshot(), before)

    async def seed_pocket_rewards(self, *rewards):
        session = await self.ready()
        async def seed(conn):
            await conn.execute('DELETE FROM inventory')
            await conn.executemany(
                'INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) '
                "VALUES (?,'survivor:test','item',?,?,1000)",
                [(self.profile['profile_id'], item, quantity) for item, quantity in rewards])
        await self.writer.run(seed)
        return session

    async def test_claim_ordinary_at_999_of_1000_plus_held_ticket_moves_one(self):
        session = await self.seed_pocket_rewards(('poke_ball', 1))
        await self.writer.run(lambda conn: conn.execute(
            'UPDATE profiles SET bag_limit=1000 WHERE profile_id=?', (self.profile['profile_id'],)))
        await self.inventory(poke_ball=999, world_legendary_ticket=1)
        self.assertEqual((await self.claim(session))['moved'], {'item': 1, 'stardust': 0, 'candy': 0})
        self.assertEqual(await items.bag_units(self.conn, self.profile['profile_id']), 1000)
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), [])
        self.assertEqual(await self.rows("SELECT resource_id,delta FROM resource_ledger WHERE reason='milestone_claim'"),
                         [{'resource_id': 'poke_ball', 'delta': 1}])

    async def test_claim_ticket_waits_for_empty_pocket_then_moves_one(self):
        session = await self.seed_pocket_rewards(('world_legendary_ticket', 1))
        await self.inventory(poke_ball=250, world_legendary_ticket=1)
        self.assertEqual((await self.claim(session))['moved']['item'], 0)
        self.assertEqual(await self.rows('SELECT resource_id,remaining FROM inbox_items'),
                         [{'resource_id': 'world_legendary_ticket', 'remaining': 1}])
        self.assertEqual(await self.rows("SELECT * FROM resource_ledger WHERE reason='milestone_claim'"), [])
        await self.restart()
        await self.inventory(world_legendary_ticket=0)
        # Replay stays the original no-op, even after space becomes available.
        self.assertEqual((await self.claim(session))['moved']['item'], 0)
        _, other = await self.open()
        self.assertEqual((await self.claim(other))['moved']['item'], 1)
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), [])
        self.assertEqual(await self.rows("SELECT quantity FROM inventory WHERE item_id='world_legendary_ticket'"),
                         [{'quantity': 1}])
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 0)

    async def test_claim_two_tickets_in_inbox_moves_one_keeps_one(self):
        session = await self.seed_pocket_rewards(('world_legendary_ticket', 1), ('world_legendary_ticket', 1))
        result = await self.claim(session)
        self.assertEqual(result['moved'], {'item': 1, 'stardust': 0, 'candy': 0})
        self.assertEqual(await self.rows('SELECT resource_id,remaining FROM inbox_items'),
                         [{'resource_id': 'world_legendary_ticket', 'remaining': 1}])
        self.assertEqual(await self.rows('SELECT item_id,quantity FROM inventory'),
                         [{'item_id': 'world_legendary_ticket', 'quantity': 1}])
        before = await self.snapshot()
        self.assertEqual(await self.claim(session), result)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.rows("SELECT resource_id,delta FROM resource_ledger WHERE reason='milestone_claim'"),
                         [{'resource_id': 'world_legendary_ticket', 'delta': 1}])
        _, other = await self.open()
        self.assertEqual((await self.claim(other))['moved']['item'], 0)
        after = await self.snapshot()
        for table in ('profiles', 'inventory', 'inbox_items', 'resource_ledger'):
            self.assertEqual(after[table], before[table])

    async def test_ticket_never_converts(self):
        session = await self.seed_pocket_rewards()
        await self.inventory(world_legendary_ticket=1)
        before = await self.snapshot()
        self.assertIsNone(items.rate_for('world_legendary_ticket', self.bot.content))
        for quantity in (1, 2):
            result = await self.writer.run(lambda conn: items.convert(
                conn, session, 'world_legendary_ticket', quantity, self.bot.content))
            self.assertEqual(result, {'status': 'refused'})
        self.assertEqual(await self.snapshot(), before)

    async def test_bag_shows_three_rare_lines_without_bag_edit(self):
        session = await self.seed_pocket_rewards()
        await self.inventory(poke_ball=250, master_ball=1, world_legendary_ticket=1)
        shown = await self.click(session, 'bag')
        description = shown.edit_original_response.await_args.kwargs['embed'].description
        for line in ('250/250 units', 'Master Ball: 1/1', 'Shiny Lure: 0/1',
                     'World Legendary Ticket: 1/1'):
            self.assertIn(line, description)
        self.assertNotIn('World Legendary Ticket \u00d7', description)

    async def test_claim_caps_bag_at_profile_bag_limit(self):
        session = await self.seed_gold()
        await self.writer.run(lambda conn: conn.execute(
            'UPDATE profiles SET bag_limit=300 WHERE profile_id=?', (self.profile['profile_id'],)))
        await self.inventory(poke_ball=280)
        await self.claim(session)
        self.assertEqual(await items.bag_units(self.conn, self.profile['profile_id']), 300)
        self.assertTrue(await self.rows("SELECT * FROM inbox_items WHERE resource='item'"))

    async def test_claim_gold_with_full_lure_pocket_credits_rest_lure_waits(self):
        session = await self.seed_gold()
        await self.inventory(shiny_lure=1)
        result = await self.claim(session)
        self.assertEqual(result['moved'], {'item': 35, 'stardust': 5000, 'candy': 0})
        waiting = await self.rows('SELECT resource_id,remaining FROM inbox_items')
        self.assertEqual(waiting, [{'resource_id': 'shiny_lure', 'remaining': 1}])
        self.assertEqual(await self.service().pending_count(self.conn, self.profile['profile_id']), 1)
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 5000)
        lines = await self.rows("SELECT * FROM resource_ledger WHERE reason='milestone_claim'")
        self.assertEqual(sum(r['delta'] for r in lines), 5035)
        self.assertEqual((await self.rows("SELECT profile_id FROM action_receipts WHERE action='claim'"))[0]['profile_id'], self.profile['profile_id'])

    async def test_claim_twice_at_once_and_restart_before_reply_sums_to_award_no_double_pay(self):
        session = await self.seed_gold()
        _, other = await self.open()
        results = await asyncio.gather(self.claim(session), self.claim(other))
        self.assertEqual(sum(r['moved']['stardust'] for r in results), 5000)
        before = await self.snapshot()
        await self.restart()
        self.assertEqual(await self.claim(session), results[0])
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(sum(r['quantity'] for r in before['inventory']) + sum(r['remaining'] for r in before['inbox_items']), 36)
        # A lost Discord reply is after commit; its original button becomes stale.
        session = await self.current(session)
        interaction = self.interaction()
        interaction.edit_original_response.side_effect = RuntimeError('reply lost')
        with self.assertRaisesRegex(RuntimeError, 'reply lost'):
            await self.walker.route(interaction, f"pw:v1:{session['session_id']}:{session['revision']}:claim")
        retry = await self.click(session, 'claim')
        retry.edit_original_response.assert_not_awaited()
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 5000)

    async def test_claim_partial_ordinary_items_then_rest_after_space(self):
        session = await self.seed_gold()
        await self.inventory(poke_ball=245, master_ball=1)
        await self.claim(session)
        self.assertEqual(sum(r['quantity'] for r in await self.rows("SELECT quantity FROM inventory WHERE item_id NOT IN ('master_ball','shiny_lure')")), 250)
        self.assertEqual(sum(r['remaining'] for r in await self.rows('SELECT remaining FROM inbox_items')), 30)
        await self.inventory(poke_ball=0)
        _, other = await self.open()
        await self.claim(other)
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), [])
        self.assertEqual(sum(r['delta'] for r in await self.rows("SELECT delta FROM resource_ledger WHERE reason='milestone_claim' AND resource='item'")), 36)

    async def seed_gym_deployment(self, deployment_id, name='Park', guild='123', profile_id=None):
        from test_db import DatabaseTests
        profile_id = profile_id or self.profile['profile_id']
        if guild != '123':
            profile_id = await DatabaseTests.profile(self, 'neighbor', guild)
        await self.writer.run(lambda conn: conn.execute(
            'INSERT INTO gyms(gym_id,guild_id,name,created_at,retired_at) VALUES (?,?,?,0,1000)',
            (deployment_id, guild, name)))
        await self.writer.run(lambda conn: conn.execute(
            'INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,'
            'iv_stamina,gender,shiny,origin,content_version,caught_at) '
            "VALUES (?,?,1,20,10,10,10,'male',0,'catch','test',0)", (deployment_id, profile_id)))
        await self.writer.run(lambda conn: conn.execute(
            'INSERT INTO gym_deployments(deployment_id,guild_id,gym_id,profile_id,pokemon_uid,'
            'deployed_at,ends_at,ended_at,end_reason) VALUES (?,?,?,?,?,0,28800,28800,\'expired\')',
            (deployment_id, guild, deployment_id, profile_id, deployment_id)))

    async def seed_gym_inbox(self, rewards):
        await self.writer.run(lambda conn: conn.executemany(
            'INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) '
            'VALUES (?,?,?,?,?,1000)', [(self.profile['profile_id'], *row) for row in rewards]))

    async def test_inbox_items_waiting_offers_expand_bag_and_convert(self):
        session = await self.ready()
        await self.seed_gym_inbox([('pokedex:5', 'item', 'great_ball', 5)])
        rules = load_table('capacities')
        rules['expansion']['bag'].update(step=75, stardust=4321)
        before = await self.snapshot()
        module = importlib.import_module('pokewalker.bot.milestones')
        with patch.object(module, 'load_table', return_value=rules), \
                patch.object(module, 'render', wraps=module.render) as render:
            shown = await self.click(session, 'inbox')
            state = render.call_args.args[0]
        with patch('builtins.open', side_effect=AssertionError('file I/O')), \
                patch.object(self.conn, 'execute', side_effect=AssertionError('renderer SQL')):
            self.assertIsNotNone(module.render(state, self.bot.content)['embed'])
        buttons = {b.label: b.custom_id.rsplit(':', 1)[1]
                   for b in shown.edit_original_response.await_args.kwargs['view'].children}
        self.assertEqual(buttons, {'Claim': 'claim', 'Back': 'home',
                                  'Expand bag (+75, 4,321 Stardust)': 'inbox_expand_bag',
                                  'Convert items': 'inbox_convert'})
        self.assertEqual(await self.snapshot(), before)

    async def test_inbox_preserves_unrelated_encounter_selection(self):
        session = await self.prepared()
        selection = json.loads(session['selection'])
        self.assertIn('encounter_id', selection)
        await self.click(session, 'inbox')
        self.assertEqual(json.loads((await self.current(session))['selection']), selection)

    async def test_inbox_no_offer_for_stardust_candy_rare_or_empty(self):
        session = await self.ready()
        for reward in [None, ('stardust', None), ('candy', '1'),
                       *(('item', item) for item in items.RARE)]:
            with self.subTest(reward=reward):
                await self.writer.run(lambda conn: conn.execute('DELETE FROM inbox_items'))
                if reward:
                    await self.seed_gym_inbox([('pokedex:5', *reward, 1)])
                shown = await self.click(await self.current(session), 'inbox')
                self.assertEqual([b.label for b in shown.edit_original_response.await_args.kwargs['view'].children],
                                 ['Claim', 'Back'])

    async def test_claim_result_with_waiting_items_offers_both(self):
        session = await self.ready()
        await self.writer.run(lambda conn: conn.execute('DELETE FROM inventory'))
        await self.inventory(poke_ball=249)
        await self.seed_gym_deployment('waiting-uuid')
        await self.seed_gym_inbox([('gym_income:waiting-uuid:1', 'item', 'great_ball', 5)])
        shown = await self.click(session, 'claim')
        rendered = shown.edit_original_response.await_args.kwargs
        self.assertIn('Moved: 1\nWaiting: 4', rendered['embed'].description)
        self.assertIn('Gym income: Park hour 1', rendered['embed'].description)
        rules = load_table('capacities')['expansion']['bag']
        self.assertEqual({b.label for b in rendered['view'].children},
                         {'Claim', 'Back', 'Convert items',
                          f"Expand bag (+{rules['step']}, {rules['stardust']:,} Stardust)"})

    async def test_inbox_shows_gym_income_name_and_hour_without_deployment_id(self):
        session = await self.ready()
        deployment_id = 'private-deployment-uuid'
        await self.seed_gym_deployment(deployment_id)
        await self.seed_gym_inbox([(f'gym_income:{deployment_id}:{hour}', 'item', 'great_ball', 1)
                                  for hour in (1, 2)])
        queries = []
        await self.conn.set_trace_callback(queries.append)
        before = await self.snapshot()
        shown = await self.click(session, 'inbox')
        await self.conn.set_trace_callback(None)
        description = shown.edit_original_response.await_args.kwargs['embed'].description
        for hour in (1, 2):
            self.assertIn(f'Gym income: Park hour {hour}: Great Ball ×1', description)
        self.assertNotIn(deployment_id, description)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(len([sql for sql in queries if 'JOIN gyms' in sql]), 1)

    async def test_inbox_survivor_reward_labelled_with_gym_name(self):
        session = await self.ready()
        await self.seed_gym_deployment('survivor-uuid')
        await self.seed_gym_inbox([('survivor:survivor-uuid', 'stardust', None, 500)])
        shown = await self.click(session, 'inbox')
        description = shown.edit_original_response.await_args.kwargs['embed'].description
        self.assertIn('Gym survivor reward: Park: Stardust ×500', description)
        self.assertNotIn('survivor-uuid', description)

    async def test_claim_moved_lines_use_same_gym_labels(self):
        session = await self.ready()
        await self.seed_gym_deployment('claim-uuid')
        await self.writer.run(lambda conn: conn.execute('DELETE FROM inventory'))
        await self.inventory(poke_ball=249)
        await self.seed_gym_inbox([('gym_income:claim-uuid:3', 'item', 'great_ball', 2),
                                  ('survivor:claim-uuid', 'stardust', None, 500)])
        shown = await self.click(session, 'claim')
        description = shown.edit_original_response.await_args.kwargs['embed'].description
        moved, waiting = description.split('Still waiting:\n')
        self.assertIn('Gym income: Park hour 3: Great Ball ×1', moved)
        self.assertIn('Gym survivor reward: Park: Stardust ×500', moved)
        self.assertIn('Gym income: Park hour 3: Great Ball ×1', waiting)
        self.assertNotIn('claim-uuid', description)

    async def test_gym_labels_missing_foreign_and_other_profile_are_indistinguishable(self):
        from test_db import DatabaseTests
        session = await self.ready()
        await self.seed_gym_deployment('foreign-uuid', 'Foreign secret', guild='foreign')
        neighbor = await DatabaseTests.profile(self, 'neighbor', '123')
        await self.seed_gym_deployment('neighbor-uuid', 'Neighbor secret', profile_id=neighbor)
        await self.seed_gym_inbox([(f'{category}:{deployment_id}{suffix}', 'stardust', None, 1)
                                  for category, suffix in (('gym_income', ':1'), ('survivor', ''))
                                  for deployment_id in ('missing-uuid', 'foreign-uuid', 'neighbor-uuid')])
        for action in ('inbox', 'claim'):
            shown = await self.click(await self.current(session), action)
            description = shown.edit_original_response.await_args.kwargs['embed'].description
            self.assertEqual(description.count('Gym income: a gym hour 1: Stardust ×1'), 3)
            self.assertEqual(description.count('Gym survivor reward: a gym: Stardust ×1'), 3)
            for secret in ('Foreign secret', 'Neighbor secret', '-uuid'):
                self.assertNotIn(secret, description)

    async def assert_malformed_gym_labels(self, action):
        session = await self.ready()
        deployment_id = 'private-malformed-uuid'
        await self.seed_gym_deployment(deployment_id)
        ids = [f'gym_income:{deployment_id}{suffix}'
               for suffix in ('', ':', ':not-an-hour', ':0', ':9', ':01', f':1:{deployment_id}')]
        ids += ['gym_income::1', 'survivor:', f'survivor:{deployment_id}:extra']
        for milestone_id in ids:
            with self.subTest(action=action, milestone_id=milestone_id):
                await self.writer.run(lambda conn: conn.execute('DELETE FROM inbox_items'))
                await self.writer.run(lambda conn: conn.execute('DELETE FROM inventory'))
                await self.inventory(poke_ball=249)
                await self.seed_gym_inbox([(milestone_id, 'item', 'great_ball', 2)])
                queries = []
                await self.conn.set_trace_callback(queries.append)
                try:
                    shown = await self.click(await self.current(session), action)
                finally:
                    await self.conn.set_trace_callback(None)
                self.assertFalse(any('JOIN gyms' in sql for sql in queries))
                description = shown.edit_original_response.await_args.kwargs['embed'].description
                label = 'Gym income reward' if milestone_id.startswith('gym_income:') else 'Gym survivor reward'
                self.assertEqual(description.count(label + ': Great Ball ×'), 2 if action == 'claim' else 1)
                for secret in (deployment_id, 'not-an-hour', 'extra', 'Park', milestone_id):
                    self.assertNotIn(secret, description)
                if action == 'claim':
                    self.assertIn('Moved: 1\nWaiting: 1', description)
                else:
                    self.assertIn('Moved: 0\nWaiting: 2', description)

    async def test_inbox_malformed_gym_ids_use_safe_generic_labels(self):
        await self.assert_malformed_gym_labels('inbox')

    async def test_claim_malformed_gym_ids_use_safe_generic_labels(self):
        await self.assert_malformed_gym_labels('claim')

    async def test_gym_label_renderer_uses_detached_labels_without_io(self):
        screen = importlib.import_module('pokewalker.bot.milestones')
        state = {'session': {'session_id': 's', 'revision': 1}, 'waiting': {'stardust': 500},
                 'waiting_details': [{'milestone_id': 'survivor:uuid', 'resource': 'stardust',
                                      'resource_id': None, 'remaining': 500}],
                 'labels': {'survivor:uuid': 'Gym survivor reward: Park'}}
        with patch('builtins.open', side_effect=AssertionError('renderer I/O')), \
                patch.object(self.conn, 'execute', side_effect=AssertionError('renderer SQL')):
            description = screen.render(state, self.bot.content)['embed'].description
        self.assertIn('Gym survivor reward: Park: Stardust ×500', description)
        self.assertNotIn('uuid', description)

    async def test_inbox_and_claim_label_arena_rows_without_raw_keys(self):
        session = await self.ready()
        keys = ['arena:private-redemption:income:0', 'arena:private-redemption:survivor:1',
                'arena:private-redemption:stardust']
        await self.seed_gym_inbox([(key, 'stardust', None, 100) for key in keys])
        queries = []
        await self.conn.set_trace_callback(queries.append)
        for action in ('inbox', 'claim'):
            shown = await self.click(await self.current(session), action)
            description = shown.edit_original_response.await_args.kwargs['embed'].description
            for label in ('Arena ticket: income roll', 'Arena ticket: survivor reward', 'Arena ticket: Stardust'):
                self.assertIn(label + ': Stardust ×100', description)
            self.assertNotIn('arena:', description)
            self.assertNotIn('private-redemption', description)
        await self.conn.set_trace_callback(None)
        self.assertFalse(any('JOIN gyms' in sql for sql in queries))
        screen = importlib.import_module('pokewalker.bot.milestones')
        with patch.object(self.conn, 'execute', side_effect=AssertionError('Arena label lookup')):
            labels = await screen._gym_labels(self.conn, session, [{'milestone_id': key} for key in keys])
        self.assertEqual(set(labels), set(keys))

    async def test_malformed_arena_key_gets_generic_label(self):
        session = await self.ready()
        keys = ['arena:', 'arena:private', 'arena:private:unknown', 'arena::income:0',
                'arena:private:income', 'arena:private:survivor:-1', 'arena:private:income:bad',
                'arena:private:stardust:0', 'arena:private:income:0:extra']
        await self.seed_gym_inbox([(key, 'stardust', None, 1) for key in keys])
        for action in ('inbox', 'claim'):
            shown = await self.click(await self.current(session), action)
            description = shown.edit_original_response.await_args.kwargs['embed'].description
            self.assertEqual(description.count('Arena ticket reward: Stardust ×1'), len(keys))
            self.assertNotIn('arena:', description)
            self.assertNotIn('private', description)

    async def test_gym_labels_unchanged(self):
        session = await self.ready()
        await self.seed_gym_deployment('mixed-uuid')
        await self.seed_gym_inbox([('gym_income:mixed-uuid:1', 'item', 'great_ball', 1),
                                  ('survivor:mixed-uuid', 'stardust', None, 500),
                                  ('arena:private:income:0', 'stardust', None, 100)])
        for action in ('inbox', 'claim'):
            shown = await self.click(await self.current(session), action)
            description = shown.edit_original_response.await_args.kwargs['embed'].description
            for line in ('Gym income: Park hour 1: Great Ball ×1',
                         'Gym survivor reward: Park: Stardust ×500',
                         'Arena ticket: income roll: Stardust ×100'):
                self.assertIn(line, description)

    async def test_home_rewards_waiting_line_has_no_milestones_word(self):
        await self.seed_gold()
        before = await self.snapshot()
        await self.restart()
        self.assertEqual(await self.snapshot(), before)
        interaction, session = await self.open()
        rendered = interaction.edit_original_response.await_args.kwargs
        self.assertIn('Rewards waiting: 1', rendered['embed'].description.splitlines())
        self.assertNotIn('milestones', rendered['embed'].description)
        self.assertNotIn('Claim', [i.label for i in rendered['view'].children])
        inbox = next(i for i in rendered['view'].children if i.label == 'Inbox (1)')
        self.assertFalse(inbox.disabled)
        self.assertEqual(inbox.custom_id.rsplit(':', 1)[1], 'inbox')
        shown = await self.click(session, 'inbox')
        self.assertIn('Waiting', shown.edit_original_response.await_args.kwargs['embed'].description)
        claimed = await self.click(await self.current(session), 'claim')
        description = claimed.edit_original_response.await_args.kwargs['embed'].description
        self.assertIn('Moved', description)
        self.assertIn('Waiting: 0', description)
        self.assertIn('Still waiting:\nnone', description)

    async def test_home_has_no_claim_button_inbox_claim_still_claims_once(self):
        await self.seed_gold()
        opened, _ = await self.open()
        home = opened.edit_original_response.await_args.kwargs
        self.assertNotIn('Claim', [button.label for button in home['view'].children])
        inbox_button = next(button for button in home['view'].children if button.label == 'Inbox (1)')
        self.assertFalse(inbox_button.disabled)
        inbox = self.interaction()
        await self.walker.route(inbox, inbox_button.custom_id)
        claim_button = next(button for button in inbox.edit_original_response.await_args.kwargs['view'].children
                            if button.label == 'Claim')
        self.assertFalse(claim_button.disabled)
        before = await self.snapshot()
        claimed = self.interaction()
        await self.walker.route(claimed, claim_button.custom_id)
        self.assertIn('Waiting: 0', claimed.edit_original_response.await_args.kwargs['embed'].description)
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), [])
        after = await self.snapshot()
        self.assertEqual(after['profiles'][0]['stardust'] - before['profiles'][0]['stardust'],
                         self.bot.content['milestones']['bundles']['gold']['stardust'])
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='claim'")), 1)
        await self.walker.route(self.interaction(), claim_button.custom_id)
        self.assertEqual(await self.snapshot(), after)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='claim'")), 1)

    async def test_inbox_lists_named_milestones_and_partial_claim_details(self):
        session = await self.ready()
        profile_id = self.profile['profile_id']
        milestones = self.bot.content['milestones']
        async def seed(conn):
            await conn.execute('DELETE FROM inventory')
            awards = [('pokedex:5', 1000), ('ultra_beast_first_catches:794', 1001),
                      ('evolution_lines:1', 1002)]
            await conn.executemany('INSERT INTO milestone_awards VALUES (?,?,?)',
                                   [(profile_id, key, at) for key, at in awards])
            rewards = [
                ('pokedex:5', 'item', 'great_ball', 10),
                ('pokedex:5', 'item', 'razz_berry', 5),
                ('pokedex:5', 'stardust', None, 500),
                ('ultra_beast_first_catches:794', 'item', 'ultra_ball', 10),
                ('ultra_beast_first_catches:794', 'item', 'golden_razz_berry', 3),
                ('ultra_beast_first_catches:794', 'item', 'rare_candy', 2),
                ('ultra_beast_first_catches:794', 'stardust', None, 2000),
                ('evolution_lines:1', 'candy', '1', 25),
                ('evolution_lines:1', 'item', 'ultra_ball', 1),
                ('evolution_lines:1', 'stardust', None, 750),
            ]
            await conn.executemany(
                'INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) '
                'VALUES (?,?,?,?,?,1000)', [(profile_id, *reward) for reward in rewards])
            await conn.executemany('INSERT INTO inventory VALUES (?,?,?)',
                                   [(profile_id, f'test_item_{i}', 1) for i in range(245)])
        await self.writer.run(seed)
        shown = await self.click(session, 'inbox')
        description = shown.edit_original_response.await_args.kwargs['embed'].description
        waiting_lines = description.split('Still waiting:\n', 1)[1].splitlines()
        self.assertEqual(waiting_lines, [
            'Pok\u00e9dex 5% [Bronze]: Great Ball \u00d710, Razz Berry \u00d75, Stardust \u00d7500',
            'First Ultra Beast catch: Buzzwole [Silver]: Ultra Ball \u00d710, Golden Razz Berry \u00d73, Rare Candy \u00d72, Stardust \u00d72000',
            'Evolution line: Bulbasaur: Bulbasaur Candy \u00d725, Ultra Ball \u00d71, Stardust \u00d7750',
        ])

        claimed = await self.click(await self.current(session), 'claim')
        description = claimed.edit_original_response.await_args.kwargs['embed'].description
        moved_lines = description.split('Moved milestones:\n', 1)[1].split('\nStill waiting:', 1)[0].splitlines()
        waiting_lines = description.split('Still waiting:\n', 1)[1].splitlines()
        self.assertEqual(moved_lines, [
            'Pok\u00e9dex 5% [Bronze]: Great Ball \u00d75, Stardust \u00d7500',
            'First Ultra Beast catch: Buzzwole [Silver]: Stardust \u00d72000',
            'Evolution line: Bulbasaur: Bulbasaur Candy \u00d725, Stardust \u00d7750',
        ])
        self.assertEqual(waiting_lines, [
            'Pok\u00e9dex 5% [Bronze]: Great Ball \u00d75, Razz Berry \u00d75',
            'First Ultra Beast catch: Buzzwole [Silver]: Ultra Ball \u00d710, Golden Razz Berry \u00d73, Rare Candy \u00d72',
            'Evolution line: Bulbasaur: Ultra Ball \u00d71',
        ])

    async def test_milestone_screen_caps_moved_and_waiting_lists(self):
        screen = importlib.import_module('pokewalker.bot.milestones')
        details = [{'milestone_id': f'pokedex:{i}', 'resource': 'stardust', 'resource_id': None,
                    'remaining': 1} for i in range(20)]
        rendered = screen.render({'session': {'session_id': 's', 'revision': 1},
                                  'waiting': {'stardust': 20}, 'moved': {'stardust': 20},
                                  'moved_details': details, 'waiting_details': details}, self.bot.content)
        description = rendered['embed'].description
        self.assertIn('And 5 more moved milestones.', description)
        self.assertIn('And 5 more waiting milestones.', description)
        self.assertLessEqual(len(description), 4096)

        bundle = self.bot.content['milestones']['bundles']['diamond']
        diamond = [{'milestone_id': 'all_legendaries:all',
                    'resource': 'stardust' if item == 'stardust' else 'item',
                    'resource_id': None if item == 'stardust' else item, 'remaining': quantity}
                   for item, quantity in bundle.items()]
        description = screen.render({'session': {'session_id': 's', 'revision': 1},
                                     'waiting': {'item': 98, 'stardust': 50000},
                                     'waiting_details': diamond}, self.bot.content)['embed'].description
        self.assertIn('Diamond', description)
        for item, quantity in bundle.items():
            label = 'Stardust' if item == 'stardust' else item.replace('_', ' ').title()
            self.assertIn(f'{label} ×{quantity}', description)

        named = [{'milestone_id': milestone_id, 'resource': 'stardust', 'resource_id': None, 'remaining': 1}
                 for milestone_id in ('legendary_groups:calyrex_and_steeds',
                                      'legendary_groups:swords_of_justice',
                                      'extra_bundle_lines:type_null')]
        description = screen.render({'session': {'session_id': 's', 'revision': 1},
                                     'waiting': {'stardust': 3}, 'waiting_details': named}, self.bot.content)['embed'].description
        waiting_lines = description.split('Still waiting:\n', 1)[1].splitlines()
        self.assertEqual(waiting_lines, [
            'Legendary group: Calyrex and Steeds [Platinum]: Stardust \u00d71',
            'Legendary group: Swords of Justice [Platinum]: Stardust \u00d71',
            'Type: Null evolution line [Gold]: Stardust \u00d71',
        ])

    async def test_duplicate_claim_receipt_screen_does_not_report_a_second_move(self):
        from pokewalker.bot import milestones as screen
        session = await self.seed_gold()
        handler = screen.handlers(self.walker)['claim']
        await self.writer.run(lambda conn: handler(conn, session, None))
        after_first = await self.snapshot()
        replay = await self.writer.run(lambda conn: handler(conn, session, None))
        self.assertEqual(await self.snapshot(), after_first)
        self.assertIn('Moved: 0', replay['embed'].description)
        self.assertNotIn('Moved milestones:', replay['embed'].description)

    async def test_other_user_cannot_claim(self):
        session = await self.seed_gold()
        before = await self.snapshot()
        for change in ({'user_id': '999'}, {'guild_id': '999'}, {'profile_id': 'wrong'}, {'session_id': 'wrong'}):
            self.assertEqual((await self.claim({**session, **change}))['status'], 'stale')
        result = await self.click(session, 'claim', user=999)
        result.edit_original_response.assert_not_awaited()
        self.assertEqual(await self.snapshot(), before)

    async def test_excluded_refused_inside_transaction(self):
        session = await self.seed_gold()
        await self.claim(session)
        await self.exclude()
        before = await self.snapshot()
        self.assertEqual((await self.claim(session))['status'], 'excluded')
        self.assertEqual(await self.snapshot(), before)

    async def test_migration_applies_once_cascade_on_delete(self):
        await self.seed_gold()
        before = await self.snapshot()
        await self.restart()
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.rows('PRAGMA user_version'))[0]['user_version'],
                         len(list(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.writer.run(lambda c: c.execute('INSERT INTO milestone_awards SELECT * FROM milestone_awards'))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.writer.run(lambda c: c.execute('UPDATE inbox_items SET remaining=-1'))
        await self.writer.run(lambda c: c.execute('DELETE FROM profiles'))
        self.assertEqual(await self.rows('SELECT * FROM milestone_awards'), [])
        self.assertEqual(await self.rows('SELECT * FROM inbox_items'), [])

    async def test_candy_claim_and_ledger_failure_rollback(self):
        session = await self.seed_gold()
        await self.writer.run(lambda c: c.execute("INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) VALUES (?,'line','candy','1',25,0)", (self.profile['profile_id'],)))
        before = await self.snapshot()
        execute = self.conn.execute
        def fail(sql, parameters=()):
            if 'INSERT INTO resource_ledger' in sql:
                raise RuntimeError('ledger unavailable')
            return execute(sql, parameters)
        with patch.object(self.conn, 'execute', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'ledger unavailable'):
                await self.claim(session)
        self.assertEqual(await self.snapshot(), before)
        await self.claim(session)
        self.assertEqual(await self.rows('SELECT family_id,quantity FROM candy'), [{'family_id': 1, 'quantity': 25}])
