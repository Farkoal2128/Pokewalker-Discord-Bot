"""D15/D40/D54 evolution recipes and atomic C3 transitions against pinned content."""
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
import random

from content.balance import load_table
from pokewalker.db import Writer, open_db
from pokewalker.domain.cp import cp
from pokewalker.services import profiles, storage

import test_storage as storage_tests


class EvolutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'evolution.db'
        self.conn = await open_db(self.path, allow_unpatched=True)
        self.addAsyncCleanup(self.conn.close)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        self.multipliers = load_table('cpm')['multipliers']
        self.profile = await self.writer.run(lambda c: profiles.enroll(
            c, 123, 456, 1, self.content, random.Random(8), datetime.now(timezone.utc)))
        self.uid = self.profile['companion_uid']
        self.session = dict(guild_id='123', user_id='456', profile_id=self.profile['profile_id'])

    def service(self):
        try:
            return importlib.import_module('pokewalker.services.evolution')
        except ModuleNotFoundError:
            self.fail('Evolution service is absent')

    async def rows(self, sql, args=()):
        async with self.conn.execute(sql, args) as cursor:
            return [dict(r) for r in await cursor.fetchall()]

    async def pokemon(self):
        return (await self.rows('SELECT * FROM pokemon WHERE pokemon_uid=?', (self.uid,)))[0]

    async def prepare(self, pokemon_id=1, gender='female'):
        await self.writer.run(lambda c: c.execute(
            'UPDATE pokemon SET pokemon_id=?,form_id=NULL,gender=? WHERE pokemon_uid=?', (pokemon_id, gender, self.uid)))
        identity, _ = storage.identify(self.content, await self.pokemon())
        await self.writer.run(lambda c: c.execute('INSERT OR REPLACE INTO candy VALUES (?,?,1000)',
                                                (self.profile['profile_id'], identity['family_id'])))
        return self.service().options(self.content, await self.pokemon())

    async def confirm(self, edge, revision=0, session=None):
        return await self.writer.run(lambda c: self.service().evolve(
            c, session or self.session, self.uid, edge['edge_id'], revision, self.content, self.multipliers, 1000))

    async def snapshot(self):
        return {t: await self.rows(f'SELECT * FROM {t}') for t in
                ('pokemon', 'profiles', 'candy', 'inventory', 'pokedex', 'milestone_awards',
                 'inbox_items', 'resource_ledger', 'action_receipts')}

    async def deploy(self):
        from pokewalker.services import gyms
        await self.writer.run(lambda c: c.execute(
            'UPDATE profiles SET companion_uid=NULL WHERE profile_id=?', (self.profile['profile_id'],)))
        gym = await self.writer.run(lambda c: gyms.create(c, '123', 'Park', 100))
        pokemon = await self.pokemon()
        result = await self.writer.run(lambda c: gyms.deploy(
            c, {**self.session, 'session_id': 'deploy'}, gym['gym_id'], self.uid,
            pokemon['revision'], 1000, self.content))
        self.assertEqual(result['status'], 'deployed')
        return result['deployment']

    async def test_evolve_deployed_stale_no_spend_trigger_not_reached(self):
        edge = next(e for e in await self.prepare(25) if e['item'] is not None)
        await self.writer.run(lambda c: c.execute('INSERT INTO inventory VALUES (?,?,1)',
                                                (self.profile['profile_id'], edge['item'])))
        await self.deploy()
        before = await self.snapshot()
        with patch.object(self.service(), 'quote', wraps=self.service().quote) as quote:
            result = await self.confirm(edge, (await self.pokemon())['revision'])
        self.assertEqual(result, dict(status='stale', pokemon=await self.pokemon()))
        quote.assert_not_awaited()
        self.assertEqual(await self.snapshot(), before)

    async def test_options_unchanged_while_deployed(self):
        options = await self.prepare()
        await self.deploy()
        self.assertEqual(self.service().options(self.content, await self.pokemon()), options)

    async def test_evolve_then_deploy_then_replay_returns_saved_result_no_extra_spend(self):
        edge = (await self.prepare())[0]
        saved = await self.confirm(edge)
        self.assertEqual(saved['status'], 'evolved')
        await self.deploy()
        before = await self.snapshot()
        self.assertEqual(await self.confirm(edge), saved)
        self.assertEqual(await self.snapshot(), before)

    async def test_recalled_pokemon_powers_up_and_evolves_again(self):
        from pokewalker.services import gyms, powerup
        edge = (await self.prepare())[0]
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET stardust=10000'))
        deployment = await self.deploy()
        ended = await self.writer.run(lambda c: gyms.end_deployment(
            c, '123', deployment['deployment_id'], 'recalled', 1000, random.Random(3), self.content))
        self.assertEqual(ended['status'], 'ended')
        pokemon = await self.pokemon()
        self.assertIsNone(pokemon['gym_deployment_id'])
        quote = await powerup.quote(self.conn, self.profile['profile_id'], self.uid, self.content, self.multipliers)
        powered = await self.writer.run(lambda c: powerup.power_up(
            c, self.session, self.uid, pokemon['revision'], self.content, self.multipliers))
        self.assertEqual(powered['status'], 'powered_up')
        self.assertEqual(powered['pokemon']['level_x2'], pokemon['level_x2'] + 1)
        evolved = await self.confirm(edge, powered['pokemon']['revision'])
        self.assertEqual(evolved['status'], 'evolved')
        self.assertEqual(evolved['pokemon']['pokemon_id'], int(edge['to_identity_id'].split(':')[0]))
        balance = await powerup.balances(self.conn, self.profile['profile_id'])
        self.assertEqual(balance, dict(stardust=10000 - quote['stardust_cost'],
                                      candy={quote['family_id']: 1000 - quote['candy_cost'] - edge['candy']}))

    async def test_identify_resolves_each_evolution_target_record(self):
        for target in self.content['evolution_targets']:
            for gender in ('male', 'female'):
                for shiny in (0, 1):
                    pokemon = dict(pokemon_id=target['pokemon_id'], form_id=target['form_id'],
                                   gender=gender, shiny=shiny)
                    identity, sprite = storage.identify(self.content, pokemon)
                    self.assertEqual(identity, target)
                    self.assertEqual(sprite, target['sprites']['shiny' if shiny else 'normal'])

    async def test_options_filter_by_identity_and_gender(self):
        for gender, targets in [('male', {414}), ('female', {413, 10004, 10005})]:
            edges = await self.prepare(412, gender)
            self.assertEqual({int(e['to_identity_id'].split(':')[0]) for e in edges}, targets)
        self.assertEqual(await self.prepare(3), [])

    async def test_emitted_combee_recipe_matches_female_through_options(self):
        self.assertEqual(await self.prepare(415, 'male'), [])
        self.assertEqual(await self.prepare(415, 'female'), self.content['evolutions']['415:415'])

    async def test_options_one_per_recipe_alcremie_sixty_three(self):
        edges = await self.prepare(868)
        self.content['evolutions']['868:868'] += edges
        self.assertEqual(len(self.service().options(self.content, await self.pokemon())), 63)
        self.assertEqual(len({e['item'] for e in edges}), 7)

    async def test_quote_cp_after_uses_target_stats_same_ivs_level(self):
        edge = (await self.prepare())[0]
        before = await self.snapshot()
        q = await self.service().quote(self.conn, self.profile['profile_id'], self.uid,
                                      edge['edge_id'], self.content, self.multipliers)
        p = await self.pokemon()
        for field, identity in [('cp_before', storage.identify(self.content, p)[0]), ('cp_after', q['target'])]:
            self.assertEqual(q[field], cp([identity[k] for k in ('base_attack', 'base_defense', 'base_stamina')],
                [p[k] for k in ('iv_attack', 'iv_defense', 'iv_stamina')], p['level_x2'], multipliers=self.multipliers))
        self.assertEqual((q['edge_id'], q['candy_cost'], q['candy_have'], q['item'], q['affordable']),
                         (edge['edge_id'], edge['candy'], 1000, None, True))
        self.assertEqual(await self.snapshot(), before)

    async def test_evolve_to_each_branch_target_then_detail_and_identify_work(self):
        for source, targets in [(744, {745, 10126, 10152}), (891, {892, 10191})]:
            edges = await self.prepare(source)
            self.assertEqual({int(e['to_identity_id'].split(':')[0]) for e in edges}, targets)
            for edge in edges:
                await self.prepare(source)
                if edge['item']:
                    await self.writer.run(lambda c: c.execute('INSERT OR REPLACE INTO inventory VALUES (?,?,1)',
                        (self.profile['profile_id'], edge['item'])))
                result = await self.confirm(edge, (await self.pokemon())['revision'])
                self.assertEqual(result['status'], 'evolved')
                p = await storage.detail(self.conn, self.profile['profile_id'], self.uid)
                self.assertEqual(storage.identify(self.content, p)[0]['identity_id'], edge['to_identity_id'])

    async def test_confirm_updates_pokemon_id_keeps_uid_ivs_level_shiny_favorite_caught_at(self):
        edge = (await self.prepare())[0]
        await self.writer.run(lambda c: c.execute('UPDATE pokemon SET shiny=1'))
        before = await self.pokemon()
        self.assertEqual((await self.confirm(edge))['pokemon'],
                         {**before, 'pokemon_id': 2, 'form_id': 2, 'revision': 1})

    async def test_evolve_writes_target_form_id(self):
        for source, source_form, target, target_form in (
                (1, 1, 2, 2), (10175, 10334, 862, 862), (915, 915, 10254, 10423)):
            with self.subTest(source=source):
                edges = await self.prepare(source)
                await self.writer.run(lambda c: c.execute(
                    'UPDATE pokemon SET form_id=? WHERE pokemon_uid=?', (source_form, self.uid)))
                revision = (await self.pokemon())['revision']
                result = await self.confirm(edges[0], revision)
                self.assertEqual(result['status'], 'evolved')
                pokemon = await storage.detail(self.conn, self.profile['profile_id'], self.uid)
                self.assertEqual(result['pokemon'], pokemon)
                self.assertEqual((pokemon['pokemon_id'], pokemon['form_id']), (target, target_form))
                self.assertEqual(storage.identify(self.content, pokemon)[0]['form_id'], target_form)

    async def test_holding_only_one_sweet_confirm_consumes_that_sweet(self):
        edges = await self.prepare(868)
        edge = next(e for e in edges if e['item'] != edges[0]['item'])
        await self.writer.run(lambda c: c.execute('INSERT INTO inventory VALUES (?,?,1)',
            (self.profile['profile_id'], edge['item'])))
        before = await self.snapshot()
        self.assertEqual((await self.confirm(edges[0]))['status'], 'insufficient')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.confirm(edge))['status'], 'evolved')
        self.assertEqual((await self.rows('SELECT quantity FROM inventory WHERE item_id=?', (edge['item'],)))[0]['quantity'], 0)

    async def test_unheld_recipe_refused_no_spend(self):
        edge = (await self.prepare(868))[0]
        before = await self.snapshot()
        self.assertEqual((await self.confirm(edge))['status'], 'insufficient')
        self.assertEqual(await self.snapshot(), before)

    async def test_candy_and_item_debited_with_ledger_lines(self):
        edge = (await self.prepare(868))[0]
        await self.writer.run(lambda c: c.execute('INSERT INTO inventory VALUES (?,?,1)',
            (self.profile['profile_id'], edge['item'])))
        await self.confirm(edge)
        self.assertEqual((await self.rows('SELECT quantity FROM candy'))[0]['quantity'], 1000 - edge['candy'])
        lines = await self.rows("SELECT resource,resource_id,delta,reason FROM resource_ledger WHERE reason='evolve'")
        family = storage.identify(self.content, await self.pokemon())[0]['family_id']
        self.assertEqual(lines, [dict(resource='candy', resource_id=str(family), delta=-edge['candy'], reason='evolve'),
                                dict(resource='item', resource_id=edge['item'], delta=-1, reason='evolve')])

    async def test_pokedex_marks_target_caught_and_milestone_awarded(self):
        edge = (await self.prepare())[0]
        await self.writer.run(lambda c: c.execute('INSERT INTO pokedex VALUES (?,3,10,10)', (self.profile['profile_id'],)))
        await self.writer.run(lambda c: c.execute('INSERT INTO pokedex VALUES (?,2,20,NULL)', (self.profile['profile_id'],)))
        await self.confirm(edge)
        self.assertEqual((await self.rows('SELECT seen_at,caught_at FROM pokedex WHERE pokemon_id=2'))[0],
                         dict(seen_at=20, caught_at=1000))
        self.assertTrue(await self.rows("SELECT * FROM milestone_awards WHERE milestone_id='evolution_lines:1'"))
        self.assertTrue(await self.rows("SELECT * FROM inbox_items WHERE milestone_id='evolution_lines:1'"))

    async def test_regional_source_evolves_to_regional_target(self):
        source = next(i for i in self.content['identities'] if i['species_id'] == 264 and i['kind'] == 'regional')
        edge = (await self.prepare(source['pokemon_id']))[0]
        self.assertEqual((await self.confirm(edge))['pokemon']['pokemon_id'], 862)
        self.assertEqual(await self.prepare(264), [])

    async def test_gender_variety_target_by_pokemon_gender(self):
        edge = (await self.prepare(915, 'female'))[0]
        self.assertEqual((await self.confirm(edge))['pokemon']['pokemon_id'], 10254)

    async def test_confirm_twice_and_restart_before_reply_one_evolution(self):
        edge = (await self.prepare())[0]
        saved = await self.confirm(edge)
        before = await self.snapshot()
        self.assertEqual(await self.confirm(edge), saved)
        await self.writer.close()
        await self.conn.close()
        self.conn = await open_db(self.path, allow_unpatched=True)
        self.addAsyncCleanup(self.conn.close)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.assertEqual(await self.confirm(edge), saved)
        self.assertEqual(await self.snapshot(), before)

    async def test_stale_revision_refused(self):
        edge = (await self.prepare())[0]
        before = await self.snapshot()
        self.assertEqual((await self.confirm(edge, 1))['status'], 'stale')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.confirm({**edge, 'edge_id': 'invalid'}))['status'], 'invalid')
        self.assertEqual(await self.snapshot(), before)
        await self.writer.run(lambda c: c.execute('DELETE FROM candy'))
        before_empty = await self.snapshot()
        self.assertEqual((await self.confirm(edge))['status'], 'insufficient')
        self.assertEqual(await self.snapshot(), before_empty)
        self.assertEqual(before['pokemon'], before_empty['pokemon'])

    async def test_sent_or_other_owner_refused(self):
        edge = (await self.prepare())[0]
        for override in ({'user_id': '999'}, {'guild_id': '999'}, {'profile_id': 'other'}):
            before = await self.snapshot()
            self.assertEqual((await self.confirm(edge, session={**self.session, **override}))['status'], 'stale')
            self.assertEqual(await self.snapshot(), before)
        await self.writer.run(lambda c: c.execute("UPDATE pokemon SET state='sent'"))
        before = await self.snapshot()
        self.assertEqual((await self.confirm(edge))['status'], 'stale')
        self.assertEqual(await self.snapshot(), before)

    async def test_excluded_refused_inside_transaction(self):
        edge = (await self.prepare())[0]
        await self.confirm(edge)
        await self.writer.run(lambda c: c.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)"))
        before = await self.snapshot()
        self.assertEqual((await self.confirm(edge))['status'], 'excluded')
        self.assertEqual(await self.snapshot(), before)

    async def test_companion_stays_companion(self):
        edge = (await self.prepare())[0]
        await self.confirm(edge)
        self.assertEqual((await profiles.get_profile(self.conn, '123', '456'))['companion_uid'], self.uid)

    async def test_ledger_failure_rolls_back_and_transaction_required(self):
        edge = (await self.prepare())[0]
        await self.writer.run(lambda c: c.execute('INSERT INTO pokedex VALUES (?,3,10,10)', (self.profile['profile_id'],)))
        with self.assertRaisesRegex(RuntimeError, 'active writer transaction'):
            await self.service().evolve(self.conn, self.session, self.uid, edge['edge_id'], 0, self.content, self.multipliers, 1000)
        before, execute = await self.snapshot(), self.conn.execute
        def fail(sql, args=()):
            if 'INSERT INTO resource_ledger' in sql:
                raise RuntimeError('ledger unavailable')
            return execute(sql, args)
        with patch.object(self.conn, 'execute', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'ledger unavailable'):
                await self.confirm(edge)
        self.assertEqual(await self.snapshot(), before)

    async def test_quote_unavailable_and_receipt_owner_scope(self):
        edge = (await self.prepare())[0]
        for uid, edge_id in [('missing', edge['edge_id']), (self.uid, 'invalid')]:
            self.assertIsNone(await self.service().quote(self.conn, self.profile['profile_id'], uid,
                edge_id, self.content, self.multipliers))
        await self.confirm(edge)
        other = await self.writer.run(lambda c: profiles.enroll(
            c, 123, 999, 1, self.content, random.Random(8), datetime.now(timezone.utc)))
        before = await self.snapshot()
        result = await self.confirm(edge, session={**self.session, 'user_id': '999', 'profile_id': other['profile_id']})
        self.assertEqual(result, dict(status='stale', pokemon=None))
        self.assertEqual(await self.snapshot(), before)


class EvolutionScreenTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = storage_tests.StorageTests.asyncSetUp
    interaction = storage_tests.StorageTests.interaction
    rows = storage_tests.StorageTests.rows
    open = storage_tests.StorageTests.open
    click = storage_tests.StorageTests.click
    enroll = storage_tests.StorageTests.enroll
    ready = storage_tests.StorageTests.ready
    current = storage_tests.StorageTests.current
    prepared = storage_tests.StorageTests.prepared
    storage = storage_tests.StorageTests.storage
    details = storage_tests.StorageTests.details
    buttons = storage_tests.StorageTests.buttons

    async def pokemon(self):
        return (await self.rows('SELECT * FROM pokemon WHERE pokemon_uid=?', (self.uid,)))[0]

    async def source(self, session, pokemon_id, gender='female', shiny=0):
        await self.writer.run(lambda c: c.execute(
            'UPDATE pokemon SET pokemon_id=?,form_id=NULL,gender=?,shiny=? WHERE pokemon_uid=?',
            (pokemon_id, gender, shiny, self.uid)))
        identity, _ = storage.identify(self.bot.content, await self.pokemon())
        await self.writer.run(lambda c: c.execute('INSERT OR REPLACE INTO candy VALUES (?,?,1000)',
            (self.profile['profile_id'], identity['family_id'])))
        return (await self.details(await self.current(session)))[1]

    async def start(self, pokemon_id=1, **kwargs):
        return await self.source(await self.prepared(), pokemon_id, **kwargs)

    def edges(self, pokemon):
        from pokewalker.services.evolution import options
        return options(self.bot.content, pokemon)

    async def screen(self, session, action='evolve', values=None):
        interaction = await self.click(session, action, values)
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs, await self.current(session)

    async def snapshot(self):
        return {t: await self.rows(f'SELECT * FROM {t}') for t in
                ('sessions', 'pokemon', 'profiles', 'candy', 'inventory', 'pokedex',
                 'milestone_awards', 'inbox_items', 'resource_ledger', 'action_receipts')}

    async def stock(self, item, quantity=1):
        await self.writer.run(lambda c: c.execute('INSERT OR REPLACE INTO inventory VALUES (?,?,?)',
            (self.profile['profile_id'], item, quantity)))

    async def test_details_shows_evolve_only_when_options_exist(self):
        session = await self.prepared()
        for pokemon_id, gender in ((1, 'male'), (3, 'male'), (415, 'male'), (415, 'female')):
            with self.subTest(pokemon_id=pokemon_id, gender=gender):
                session = await self.source(session, pokemon_id, gender=gender)
                rendered, session = await self.details(session)
                self.assertEqual('Evolve' in self.buttons(rendered), bool(self.edges(await self.pokemon())))
                self.assertLessEqual(len(rendered['view'].children), 25)
                self.assertTrue(all(i.row is None or i.row < 5 for i in rendered['view'].children))

    async def test_details_evolve_opens_evolve_screen(self):
        session = await self.start()
        rendered, session = await self.details(session)
        action = self.buttons(rendered)['Evolve'].custom_id.rsplit(':', 1)[-1]
        self.assertEqual(action, 'evolve')
        rendered, _ = await self.screen(session, action)
        self.assertEqual(rendered['embed'].title, 'Evolve')
        self.assertIn('Confirm', self.buttons(rendered))

    async def test_branch_select_only_with_multiple_options(self):
        session = await self.start()
        rendered, session = await self.screen(session)
        self.assertFalse(any(hasattr(i, 'options') for i in rendered['view'].children))
        self.assertIn('Confirm', self.buttons(rendered))
        for source in (133, 744):
            with self.subTest(source=source):
                session = await self.source(session, source)
                rendered, session = await self.screen(session)
                selectors = [i for i in rendered['view'].children if hasattr(i, 'options')]
                self.assertEqual(len(selectors), 1)
                edges = self.edges(await self.pokemon())
                self.assertEqual([i.value for i in selectors[0].options], [e['edge_id'] for e in edges])
                for option, edge in zip(selectors[0].options, edges):
                    target, _ = storage.identify(self.bot.content,
                        {**await self.pokemon(), 'pokemon_id': int(edge['to_identity_id'].split(':')[0])})
                    item = next((i['name_en'] for i in self.bot.content['evolution_items']
                                 if i['id'] == edge['item']), 'Candy only')
                    self.assertEqual(option.label, f"{target['name_en']} · {item}")
                self.assertNotIn('Confirm', self.buttons(rendered))
                self.assertIsNone(rendered['embed'].image.url)

    def select(self, rendered):
        return next(i for i in rendered['view'].children if hasattr(i, 'options'))

    async def test_milcery_lists_seven_sweets_then_nine_creams(self):
        session = await self.start(868)
        rendered, session = await self.screen(session)
        selector = self.select(rendered)
        edges = self.edges(await self.pokemon())
        sweets = {e['item'] for e in edges}
        self.assertEqual(len(selector.options), 7)
        self.assertEqual({i.value for i in selector.options}, sweets)
        self.assertTrue(selector.custom_id.endswith(':evolve_group'))
        items = {i['id']: i['name_en'] for i in self.bot.content['evolution_items']}
        self.assertEqual({i.label for i in selector.options},
                         {f"{items[sweet]} · 9 forms" for sweet in sweets})
        for sweet in sorted(sweets):
            rendered, session = await self.screen(session, 'evolve_group', [sweet])
            options = self.select(rendered).options
            recipes = [e for e in edges if e['item'] == sweet]
            self.assertEqual(len(options), 9)
            self.assertEqual([i.value for i in options], [e['edge_id'] for e in recipes])
            from pokewalker.services.evolution import target
            for option, edge in zip(options, recipes):
                name = target(self.bot.content, await self.pokemon(), edge)['name_en']
                self.assertEqual(option.label, f"{name} · {items[sweet]}")
            self.assertEqual(json.loads(session['selection'])['evolve_item'], sweet)
            self.assertNotIn('edge_id', json.loads(session['selection']))

    async def test_group_value_outside_groups_refused(self):
        session = await self.start(868)
        _, session = await self.screen(session)
        for values in ([], ['invalid'], ['love-sweet', 'berry-sweet'], ['-'],
                       [self.edges(await self.pokemon())[0]['edge_id']]):
            before = await self.snapshot()
            interaction = await self.click(session, 'evolve_group', values)
            interaction.edit_original_response.assert_not_awaited()
            self.assertIn('reopen /walker', interaction.followup.send.await_args.args[0])
            self.assertEqual(await self.snapshot(), before)

    async def test_pick_from_another_sweet_refused_after_choosing_love_sweet(self):
        session = await self.start(868)
        _, session = await self.screen(session)
        _, session = await self.screen(session, 'evolve_group', ['love-sweet'])
        edge = next(e for e in self.edges(await self.pokemon()) if e['item'] != 'love-sweet')
        before = await self.snapshot()
        interaction = await self.click(session, 'evolve_pick', [edge['edge_id']])
        interaction.edit_original_response.assert_not_awaited()
        self.assertIn('reopen /walker', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_pick_without_group_refused_for_milcery(self):
        session = await self.start(868)
        _, session = await self.screen(session)
        before = await self.snapshot()
        interaction = await self.click(session, 'evolve_pick', [self.edges(await self.pokemon())[0]['edge_id']])
        interaction.edit_original_response.assert_not_awaited()
        self.assertIn('reopen /walker', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_cream_back_returns_to_sweets(self):
        session = await self.start(868)
        _, session = await self.screen(session)
        _, session = await self.screen(session, 'evolve_group', ['love-sweet'])
        edge = next(e for e in self.edges(await self.pokemon()) if e['item'] == 'love-sweet')
        _, session = await self.screen(session, 'evolve_pick', [edge['edge_id']])
        rendered, session = await self.screen(session, 'evolve_group', ['love-sweet'])
        self.assertNotIn('edge_id', json.loads(session['selection']))
        action = self.buttons(rendered)['Back'].custom_id.rsplit(':', 1)[-1]
        self.assertEqual(action, 'evolve')
        rendered, session = await self.screen(session, action)
        self.assertEqual(len(self.select(rendered).options), 7)
        self.assertNotIn('evolve_item', json.loads(session['selection']))
        self.assertNotIn('edge_id', json.loads(session['selection']))

    async def test_each_of_63_forms_evolves_and_details_show_exact_name_and_sprite(self):
        from content.build.emit import SPRITES_COMMIT
        from pokewalker.services.evolution import target
        session = await self.start(868)
        edges = self.edges(await self.pokemon())
        self.assertEqual(len(edges), 63)
        for shiny in (0, 1):
            for edge in edges:
                with self.subTest(edge=edge['edge_id'], shiny=shiny):
                    session = await self.source(session, 868, shiny=shiny)
                    await self.stock(edge['item'])
                    expected = target(self.bot.content, await self.pokemon(), edge)
                    key = '869' if expected['form_id'] == 869 else (
                        '869-' + expected['name_en'].removesuffix(' Alcremie').lower().replace(' ', '-'))
                    prefix = 'shiny/' if shiny else ''
                    sprite = (f'https://raw.githubusercontent.com/PokeAPI/sprites/{SPRITES_COMMIT}'
                              f'/sprites/pokemon/{prefix}{key}.png')
                    _, session = await self.screen(session)
                    _, session = await self.screen(session, 'evolve_group', [edge['item']])
                    rendered, session = await self.screen(session, 'evolve_pick', [edge['edge_id']])
                    self.assertIn(expected['name_en'], rendered['embed'].description)
                    self.assertEqual(rendered['embed'].image.url, sprite)
                    rendered, session = await self.screen(session, 'evolve_confirm')
                    self.assertEqual((await self.pokemon())['form_id'], expected['form_id'])
                    self.assertIn(expected['name_en'], rendered['embed'].description)
                    self.assertEqual(rendered['embed'].image.url, sprite)

    async def test_pick_value_outside_options_refused(self):
        session = await self.start(868)
        _, session = await self.screen(session)
        _, session = await self.screen(session, 'evolve_group', ['strawberry-sweet'])
        for values in ([], ['invalid'], [e['edge_id'] for e in self.edges(await self.pokemon())[:2]],
                       [self.bot.content['evolutions']['1:1'][0]['edge_id']]):
            before = await self.snapshot()
            interaction = await self.click(session, 'evolve_pick', values)
            interaction.edit_original_response.assert_not_awaited()
            self.assertIn('reopen /walker', interaction.followup.send.await_args.args[0])
            self.assertEqual(await self.snapshot(), before)

    async def test_confirm_consumes_previewed_recipe_item_not_another(self):
        session = await self.start(868)
        edges = self.edges(await self.pokemon())
        other = edges[0]
        chosen = next(e for e in edges if e['item'] != other['item'])
        await self.stock(chosen['item'])
        await self.stock(other['item'])
        _, session = await self.screen(session)
        _, session = await self.screen(session, 'evolve_group', [chosen['item']])
        _, session = await self.screen(session, 'evolve_pick', [chosen['edge_id']])
        self.assertEqual(json.loads(session['selection'])['edge_id'], chosen['edge_id'])
        await self.screen(session, 'evolve_confirm')
        stock = {r['item_id']: r['quantity'] for r in await self.rows('SELECT * FROM inventory')}
        self.assertEqual((stock[chosen['item']], stock[other['item']]), (0, 1))
        lines = await self.rows("SELECT resource_id FROM resource_ledger WHERE reason='evolve' AND resource='item'")
        self.assertEqual(lines, [{'resource_id': chosen['item']}])

    async def test_quote_shows_target_sprite_and_text_complete_without_it(self):
        from pokewalker.services.evolution import quote
        session = await self.start(915, gender='female', shiny=1)
        edge = self.edges(await self.pokemon())[0]
        q = await quote(self.conn, self.profile['profile_id'], self.uid, edge['edge_id'],
                        self.bot.content, self.walker.multipliers)
        pokemon = {**await self.pokemon(), 'pokemon_id': q['target']['pokemon_id']}
        target, sprite = storage.identify(self.bot.content, pokemon)
        rendered, session = await self.screen(session)
        self.assertEqual(rendered['embed'].image.url, sprite)
        text = rendered['embed'].description
        for value in (target['name_en'], f"CP {q['cp_before']} → {q['cp_after']}",
                      f"{q['candy_cost']} Candy (have 1000)", 'Candy only'):
            self.assertIn(value, text)
        for key in target['sprites']:
            target['sprites'][key] = None
        rendered, _ = await self.screen(session)
        self.assertIsNone(rendered['embed'].image.url)
        self.assertEqual(rendered['embed'].description, text)

    async def test_confirm_disabled_when_unaffordable_and_buy_button_shown(self):
        session = await self.start(868)
        edge = self.edges(await self.pokemon())[0]
        _, session = await self.screen(session)
        _, session = await self.screen(session, 'evolve_group', [edge['item']])
        rendered, session = await self.screen(session, 'evolve_pick', [edge['edge_id']])
        item = next(i['name_en'] for i in self.bot.content['evolution_items'] if i['id'] == edge['item'])
        self.assertIn(item + ' (have 0)', rendered['embed'].description)
        self.assertIn('Buy & evolve (500 Stardust)', self.buttons(rendered))
        self.assertTrue(self.buttons(rendered)['Confirm'].disabled)
        before = await self.snapshot()
        await self.click(session, 'evolve_confirm')
        self.assertEqual(await self.snapshot(), before)
        await self.stock(edge['item'])
        await self.writer.run(lambda c: c.execute('UPDATE candy SET quantity=0'))
        rendered, session = await self.screen(session, 'evolve_pick', [edge['edge_id']])
        self.assertTrue(self.buttons(rendered)['Confirm'].disabled)
        self.assertNotIn('Buy & evolve (500 Stardust)', self.buttons(rendered))
        before = await self.snapshot()
        await self.click(session, 'evolve_confirm')
        self.assertEqual(await self.snapshot(), before)

    async def buy_preview(self):
        session = await self.start(95)
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET stardust=500'))
        return await self.screen(session)

    async def test_buy_and_evolve_spends_500_buys_one_consumes_it_and_evolves(self):
        _, session = await self.buy_preview()
        edge = self.edges(await self.pokemon())[0]
        self.assertEqual(edge['item'], 'metal-coat')
        family = storage.identify(self.bot.content, await self.pokemon())[0]['family_id']
        rendered, session = await self.screen(session, 'evolve_buy_confirm')
        self.assertEqual((await self.pokemon())['pokemon_id'], 208)
        self.assertEqual(rendered['embed'].title, 'Pok\u00e9mon details')
        self.assertIn('Steelix', rendered['embed'].description)
        self.assertEqual(json.loads(session['selection'])['pokemon_revision'], 1)
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 0)
        self.assertEqual((await self.rows("SELECT quantity FROM inventory WHERE item_id='metal-coat'"))[0]['quantity'], 0)
        self.assertEqual((await self.rows('SELECT quantity FROM candy WHERE family_id=?', (family,)))[0]['quantity'],
                         1000 - edge['candy'])
        lines = await self.rows("SELECT resource,resource_id,delta,reason FROM resource_ledger "
                                "WHERE reason IN ('buy','evolve') ORDER BY rowid")
        self.assertEqual(lines, [dict(resource=r, resource_id=i, delta=d, reason=why) for r, i, d, why in
            [('stardust', None, -500, 'buy'), ('item', 'metal-coat', 1, 'buy'),
             ('candy', str(family), -edge['candy'], 'evolve'), ('item', 'metal-coat', -1, 'evolve')]])
        receipts = await self.rows("SELECT action,profile_id FROM action_receipts WHERE action IN ('buy','evolve')")
        self.assertEqual({r['action'] for r in receipts}, {'buy', 'evolve'})
        self.assertTrue(all(r['profile_id'] == self.profile['profile_id'] for r in receipts))

    async def test_buy_and_evolve_button_only_when_item_missing(self):
        rendered, session = await self.buy_preview()
        button = self.buttons(rendered)['Buy & evolve (500 Stardust)']
        self.assertTrue(button.custom_id.endswith(':evolve_buy_confirm'))
        self.assertFalse(button.disabled)
        self.assertTrue(self.buttons(rendered)['Confirm'].disabled)
        self.assertNotIn('Buy in Bag', rendered['embed'].description)
        await self.stock('metal-coat')
        rendered, session = await self.screen(session)
        self.assertNotIn('Buy & evolve (500 Stardust)', self.buttons(rendered))
        self.assertFalse(self.buttons(rendered)['Confirm'].disabled)
        session = await self.source(session, 1)
        rendered, _ = await self.screen(session)
        self.assertNotIn('Buy & evolve (500 Stardust)', self.buttons(rendered))

    async def test_buy_and_evolve_disabled_when_candy_or_stardust_short(self):
        _, session = await self.buy_preview()
        for candy, dust in ((0, 500), (1000, 499)):
            with self.subTest(candy=candy, dust=dust):
                await self.writer.run(lambda c: c.execute('UPDATE candy SET quantity=?', (candy,)))
                await self.writer.run(lambda c: c.execute('UPDATE profiles SET stardust=?', (dust,)))
                rendered, session = await self.screen(session)
                self.assertTrue(self.buttons(rendered)['Buy & evolve (500 Stardust)'].disabled)
                before = await self.snapshot()
                interaction = await self.click(session, 'evolve_buy_confirm')
                self.assertIn('Nothing was spent.', interaction.followup.send.await_args.args[0])
                self.assertEqual(await self.snapshot(), before)

    async def test_buy_and_evolve_insufficient_or_bag_full_refused_nothing_written(self):
        _, session = await self.buy_preview()
        for dust, held, text in ((499, 0, 'Not enough Stardust.'), (500, 250, 'Bag is full.')):
            with self.subTest(text=text):
                await self.writer.run(lambda c: c.execute(
                    'UPDATE profiles SET stardust=?,bag_limit=250', (dust,)))
                await self.stock('poke_ball', held)
                before = await self.snapshot()
                interaction = await self.click(session, 'evolve_buy_confirm')
                self.assertEqual(interaction.followup.send.await_args.args[0], text + ' Nothing was spent.')
                self.assertEqual(await self.snapshot(), before)

    async def test_buy_and_evolve_rolls_back_purchase_when_evolve_refuses(self):
        _, session = await self.buy_preview()
        from pokewalker.services import evolution
        before = await self.snapshot()
        async def refuse(conn, *args):
            self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 0)
            self.assertEqual((await self.rows("SELECT quantity FROM inventory WHERE item_id='metal-coat'"))[0]['quantity'], 1)
            return {'status': 'stale'}
        with patch.object(evolution, 'evolve', side_effect=refuse) as evolve:
            interaction = await self.click(session, 'evolve_buy_confirm')
        evolve.assert_awaited_once()
        self.assertIn('reopen /walker', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_buy_and_evolve_stale_revision_or_item_now_held_refused(self):
        _, session = await self.buy_preview()
        for change, message in (
                ("UPDATE pokemon SET revision=revision+1", 'reopen /walker'),
                ("UPDATE candy SET quantity=0", 'Your items changed. Preview again. Nothing was spent.'),
                ("INSERT INTO inventory VALUES (?,?,1)", 'Your items changed. Preview again. Nothing was spent.')):
            with self.subTest(change=change):
                args = (self.profile['profile_id'], 'metal-coat') if change.startswith('INSERT') else ()
                await self.writer.run(lambda c: c.execute(change, args))
                before = await self.snapshot()
                interaction = await self.click(session, 'evolve_buy_confirm')
                self.assertIn(message, interaction.followup.send.await_args.args[0])
                self.assertEqual(await self.snapshot(), before)
                await self.writer.run(lambda c: c.execute('UPDATE pokemon SET revision=0'))
                await self.writer.run(lambda c: c.execute('UPDATE candy SET quantity=1000'))

    async def test_buy_and_evolve_invalid_saved_recipe_refused(self):
        _, session = await self.buy_preview()
        selection = json.loads(session['selection'])
        selection['edge_id'] = 'invalid'
        await self.writer.run(lambda c: c.execute('UPDATE sessions SET selection=?', (json.dumps(selection),)))
        session = await self.current(session)
        before = await self.snapshot()
        interaction = await self.click(session, 'evolve_buy_confirm')
        self.assertIn('reopen /walker', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_buy_and_evolve_repeat_click_one_charge(self):
        _, session = await self.buy_preview()
        await self.screen(session, 'evolve_buy_confirm')
        before = await self.snapshot()
        self.walker = self.module.Walker(self.bot, clock=lambda: 1001)
        interaction = await self.click(session, 'evolve_buy_confirm')
        self.assertIn('reopen /walker', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_other_user_cannot_buy_and_evolve(self):
        _, session = await self.buy_preview()
        before = await self.snapshot()
        interaction = await self.click(session, 'evolve_buy_confirm', user=999)
        self.assertIn('not yours', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_buy_and_evolve_deployed_purchase_rolls_back(self):
        _, session = await self.buy_preview()
        await self.writer.run(lambda c: c.execute('UPDATE profiles SET companion_uid=NULL'))
        from pokewalker.services import gyms
        gym = await self.writer.run(lambda c: gyms.create(c, '123', 'Park', 900))
        result = await self.writer.run(lambda c: gyms.deploy(
            c, session, gym['gym_id'], self.uid, 0, 1000, self.bot.content))
        self.assertEqual(result['status'], 'deployed')
        _, session = await self.details(session)
        _, session = await self.screen(session)
        before = await self.snapshot()
        interaction = await self.click(session, 'evolve_buy_confirm')
        self.assertIn('reopen /walker', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_confirm_renders_evolved_details(self):
        session = await self.start(744)
        edge = self.edges(await self.pokemon())[1]
        _, session = await self.screen(session)
        _, session = await self.screen(session, 'evolve_pick', [edge['edge_id']])
        rendered, session = await self.screen(session, 'evolve_confirm')
        pokemon = await self.pokemon()
        target, sprite = storage.identify(self.bot.content, pokemon)
        self.assertEqual(target['identity_id'], edge['to_identity_id'])
        self.assertEqual(rendered['embed'].title, 'Pokémon details')
        self.assertIn(target['name_en'], rendered['embed'].description)
        self.assertEqual(rendered['embed'].image.url, sprite)
        self.assertEqual(json.loads(session['selection'])['pokemon_revision'], pokemon['revision'])

    async def test_evolve_twice_through_screens_after_form_written(self):
        session = await self.start(4)
        for pokemon_id in (5, 6):
            with self.subTest(target=pokemon_id):
                rendered, session = await self.screen(session)
                self.assertIn('Confirm', self.buttons(rendered))
                rendered, session = await self.screen(session, 'evolve_confirm')
                pokemon = await self.pokemon()
                self.assertEqual((pokemon['pokemon_id'], pokemon['form_id']), (pokemon_id, pokemon_id))
                target, sprite = storage.identify(self.bot.content, pokemon)
                self.assertIn(target['name_en'], rendered['embed'].description)
                self.assertEqual(rendered['embed'].image.url, sprite)

    async def test_same_pokemon_id_target_resolved_by_form_in_quote_and_screen(self):
        from pokewalker.services.evolution import quote
        content = self.bot.content
        default = next(i for i in content['identities'] if i['identity_id'] == '869:869')
        target = {**default, 'identity_id': '869:10346', 'form_id': 10346,
                  'name_en': 'Exact form Alcremie',
                  'sprites': {key: 'https://example.com/exact-form.png' for key in default['sprites']}}
        content['evolution_targets'] = [i for i in content['evolution_targets']
                                        if i['identity_id'] != target['identity_id']] + [target]
        original = content['evolutions']['868:868'][0]
        edge = {**original, 'to_identity_id': target['identity_id'], 'edge_id': 'exact-form'}
        content['evolutions']['868:868'] = [original, edge]
        session = await self.start(868)
        await self.stock(edge['item'])
        q = await quote(self.conn, self.profile['profile_id'], self.uid, edge['edge_id'],
                        content, self.walker.multipliers)
        self.assertEqual(q['target'], target)
        rendered, session = await self.screen(session)
        selector = next(i for i in rendered['view'].children if hasattr(i, 'options'))
        self.assertIn(target['name_en'], selector.options[1].label)
        rendered, session = await self.screen(session, 'evolve_pick', [edge['edge_id']])
        self.assertIn(target['name_en'], rendered['embed'].description)
        self.assertEqual(rendered['embed'].image.url, target['sprites']['normal'])
        rendered, _ = await self.screen(session, 'evolve_confirm')
        self.assertEqual((await self.pokemon())['form_id'], target['form_id'])
        self.assertIn(target['name_en'], rendered['embed'].description)
        self.assertEqual(rendered['embed'].image.url, target['sprites']['normal'])

    async def test_stale_click_after_confirm_reopens_no_second_spend(self):
        session = await self.start()
        _, session = await self.screen(session)
        await self.screen(session, 'evolve_confirm')
        before = await self.snapshot()
        self.walker = self.module.Walker(self.bot, clock=lambda: 1001)
        interaction = await self.click(session, 'evolve_confirm')
        interaction.edit_original_response.assert_not_awaited()
        self.assertIn('reopen /walker', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_other_user_cannot_click(self):
        session = await self.start(868)
        for action, values in (('evolve', []), ('evolve_group', ['love-sweet']),
                               ('evolve_pick', ['invalid']), ('evolve_confirm', [])):
            before = await self.snapshot()
            interaction = await self.click(session, action, values, user=999)
            interaction.edit_original_response.assert_not_awaited()
            self.assertIn('not yours', interaction.followup.send.await_args.args[0])
            self.assertEqual(await self.snapshot(), before)

    async def test_stale_or_invalid_recipe_confirmation_refused(self):
        session = await self.start()
        _, session = await self.screen(session)
        selection = json.loads(session['selection'])
        selection['edge_id'] = 'invalid'
        await self.writer.run(lambda c: c.execute('UPDATE sessions SET selection=?', (json.dumps(selection),)))
        session = await self.current(session)
        before = await self.snapshot()
        interaction = await self.click(session, 'evolve_confirm')
        self.assertIn('reopen /walker', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)
        _, session = await self.screen(session)
        await self.writer.run(lambda c: c.execute('UPDATE pokemon SET revision=revision+1'))
        for action in ('evolve', 'evolve_group', 'evolve_pick', 'evolve_confirm'):
            before = await self.snapshot()
            interaction = await self.click(session, action, [self.edges(await self.pokemon())[0]['edge_id']])
            self.assertIn('reopen /walker', interaction.followup.send.await_args.args[0])
            self.assertEqual(await self.snapshot(), before)

    async def test_render_functions_do_no_io(self):
        session = await self.start(868)
        choices, session = await self.screen(session)
        edge = self.edges(await self.pokemon())[0]
        module = importlib.import_module('pokewalker.bot.evolve')
        with patch.object(module, 'render_options', wraps=module.render_options) as render:
            await self.screen(session)
            options_state = render.call_args.args[0]
        _, session = await self.screen(await self.current(session), 'evolve_group', [edge['item']])
        with patch.object(module, 'render_quote', wraps=module.render_quote) as render:
            await self.screen(session, 'evolve_pick', [edge['edge_id']])
            quote_state = render.call_args.args[0]
        with patch.object(self.conn, 'execute', side_effect=AssertionError('database I/O')), \
                patch.object(self.writer, 'run', side_effect=AssertionError('writer I/O')), \
                patch('builtins.open', side_effect=AssertionError('file I/O')), \
                patch('socket.socket', side_effect=AssertionError('network I/O')):
            self.assertEqual(module.render_options(options_state)['embed'].description,
                             choices['embed'].description)
            self.assertIn('Confirm', self.buttons(module.render_quote(quote_state)))

    async def test_registration_reads_no_bot_attributes(self):
        from types import SimpleNamespace
        walker = self.module.Walker(SimpleNamespace())
        self.assertTrue({'evolve', 'evolve_group', 'evolve_pick', 'evolve_confirm'} <= walker.handlers.keys())
