"""EX-Gift private screens through the durable router and real gift service."""

import copy
from datetime import datetime, timezone
import importlib
import json
import re
import unittest
from unittest.mock import patch

from pokewalker.services import ex_gift as service


class ExGiftScreenTests(unittest.IsolatedAsyncioTestCase):
    from test_walker_router import WalkerTests as _Fixture
    asyncSetUp = _Fixture.asyncSetUp
    interaction = _Fixture.interaction
    rows = _Fixture.rows
    open = _Fixture.open
    click = _Fixture.click
    enroll = _Fixture.enroll

    async def seed(self, packages):
        await self.enroll()
        _, session = await self.open()
        for index, items in enumerate(packages):
            await self.conn.execute(
                'INSERT INTO ex_gifts VALUES (?,?,?,?,?,?,?,?,?)',
                (f'gift-{index:03}', 'owner', 'all', None, json.dumps(items), 1, 1, 1, 86400 * index))
            await self.conn.execute('INSERT INTO ex_gift_recipients(gift_id,profile_id) VALUES (?,?)',
                                    (f'gift-{index:03}', session['profile_id']))
        return session

    async def press(self, session, action, values=None):
        interaction = await self.click(session, action, values)
        interaction.edit_original_response.assert_awaited_once()
        interaction.followup.send.assert_not_awaited()
        saved = (await self.rows('SELECT * FROM sessions WHERE session_id=?', (session['session_id'],)))[0]
        self.assertEqual(saved['revision'], session['revision'] + 1)
        return interaction.edit_original_response.await_args.kwargs, saved

    def buttons(self, rendered):
        return {button.label: button for button in rendered['view'].children if hasattr(button, 'label')}

    async def voucher_snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table} ORDER BY 1') for table in
                ('profiles', 'pokemon', 'ex_items', 'inventory', 'arena_runs', 'arena_tickets',
                 'action_receipts', 'resource_ledger', 'arena_month_scores')}

    async def test_use_voucher_opens_team_picker_spends_nothing(self):
        session = await self.seed([list(service.EX_ITEMS)])
        rendered, session = await self.press(session, 'ex_gift')
        self.assertNotIn('Use Arena EX-Voucher (1)', self.buttons(rendered))
        rendered, session = await self.press(session, 'ex_claim')
        button = self.buttons(rendered)['Use Arena EX-Voucher (1)']
        match = re.fullmatch(self.module.CUSTOM_ID, button.custom_id)
        self.assertIsNotNone(match)
        self.assertEqual(match['action'], 'ex_use_arena_ex_voucher')
        payload = rendered['view'].to_components()
        self.assertEqual([len(row['components']) for row in payload], [4, 5, 1])
        self.assertEqual(button.row, 2)
        before = await self.voucher_snapshot()
        rendered, session = await self.press(session, 'ex_use_arena_ex_voucher')
        self.assertEqual(rendered['embed'].title, 'Arena team')
        self.assertEqual(json.loads(session['selection']),
                         {'phase': 'arena_team', 'team': [], 'offset': 0, 'sort': 'newest', 'skip': 0})
        self.assertTrue(self.buttons(rendered)['Start on floor 81 · EX-Voucher'].disabled)
        self.assertEqual(await self.voucher_snapshot(), before)

    async def test_use_voucher_during_live_run_spends_nothing(self):
        session = await self.seed([['arena_ex_voucher']])
        _, session = await self.press(session, 'ex_claim')
        for index in range(2):
            await self.conn.execute('INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,'
                                    'iv_defense,iv_stamina,gender,shiny,origin,content_version,caught_at) '
                                    "VALUES (?,?,1,20,10,10,10,'male',0,'catch','test',0)",
                                    (f'voucher{index}', session['profile_id']))
        _, session = await self.press(session, 'arena_team')
        for row in await self.rows('SELECT pokemon_uid FROM pokemon'):
            _, session = await self.press(session, 'arena_team_pick', [row['pokemon_uid']])
        _, session = await self.press(session, 'arena_start')
        before = await self.voucher_snapshot()
        for action in ('arena_start', 'arena_voucher_start'):
            _, session = await self.press(session, 'ex_gift')
            rendered, session = await self.press(session, 'ex_use_arena_ex_voucher')
            self.assertEqual(rendered['embed'].title, 'Arena team')
            self.assertEqual(await self.voucher_snapshot(), before)
            rendered, session = await self.press(session, action)
            self.assertEqual(rendered['embed'].title, 'Arena break')
            self.assertIn('Floor 1', rendered['embed'].description)
            self.assertNotIn('EX-Voucher used:', rendered['embed'].description)
            self.assertEqual(await self.voucher_snapshot(), before)

    async def test_arm_buttons_only_while_held_and_unarmed(self):
        session = await self.seed([list(service.EX_ITEMS)])
        rendered, session = await self.press(session, 'ex_gift')
        for name in ('EX-Attack', 'EX-Defense'):
            self.assertFalse(any(label.startswith(f'Use {name}') for label in self.buttons(rendered)))
        _, session = await self.press(session, 'ex_claim')
        for attack, defense in ((0, 0), (1, 0), (0, 1), (1, 1)):
            await self.conn.execute('UPDATE profiles SET ex_attack_armed=?,ex_defense_armed=?', (attack, defense))
            rendered, session = await self.press(session, 'ex_gift')
            for item, armed in (('ex_attack', attack), ('ex_defense', defense)):
                name = service.EX_ITEMS[item]
                self.assertEqual(f'Use {name} (1)' in self.buttons(rendered), not armed)
                self.assertEqual(f'{name} armed for your next new Arena run.' in rendered['embed'].description,
                                 bool(armed))
                if not armed:
                    button = self.buttons(rendered)[f'Use {name} (1)']
                    self.assertTrue(button.custom_id.endswith(f':ex_arm_{item}'))
                    self.assertIsNotNone(re.fullmatch(self.module.CUSTOM_ID, button.custom_id))
            use_buttons = [b for b in rendered['view'].children if b.label.startswith('Use ')]
            self.assertEqual(len(use_buttons), 6 - attack - defense)
            self.assertTrue(all(b.row == (2 if b.custom_id.endswith(':ex_use_arena_ex_voucher') else 1)
                                for b in use_buttons))
        await self.conn.execute('UPDATE ex_items SET quantity=0')
        rendered, _ = await self.press(session, 'ex_gift')
        for name in ('EX-Attack', 'EX-Defense'):
            self.assertIn(f'{name} armed for your next new Arena run.', rendered['embed'].description)

    async def test_arm_notice_then_armed_line(self):
        session = await self.seed([['ex_attack', 'ex_attack', 'ex_defense', 'ex_defense']])
        _, session = await self.press(session, 'ex_claim')
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('123','456',1)")
        for item, stat in (('ex_attack', 'attack'), ('ex_defense', 'defense')):
            name = service.EX_ITEMS[item]
            rendered, session = await self.press(session, f'ex_arm_{item}')
            self.assertIn(f'{name} armed: ×2 {stat} for your whole next new Arena run. '
                          'A run in progress does not get it.', rendered['embed'].description)
            self.assertIn(f'{name} armed for your next new Arena run.', rendered['embed'].description)
            self.assertNotIn(f'Use {name} (1)', self.buttons(rendered))
            self.assertEqual(await self.rows('SELECT quantity FROM ex_items WHERE item_id=?', (item,)),
                             [{'quantity': 1}])
            self.assertEqual(await self.rows(f'SELECT {item}_armed FROM profiles'), [{f'{item}_armed': 1}])
        self.assertEqual(len(await self.rows("SELECT * FROM resource_ledger WHERE reason='ex_arm'")), 2)

    async def test_arm_already_and_missing_notices(self):
        session = await self.seed([['ex_attack', 'ex_attack', 'ex_defense', 'ex_defense']])
        _, session = await self.press(session, 'ex_claim')
        for item in ('ex_attack', 'ex_defense'):
            name = service.EX_ITEMS[item]
            _, session = await self.press(session, f'ex_arm_{item}')
            before = await self.rows('SELECT * FROM ex_items')
            receipts = await self.rows("SELECT * FROM action_receipts WHERE action='ex_arm'")
            rendered, session = await self.press(session, f'ex_arm_{item}')
            self.assertIn(f'{name} is already armed. Nothing was spent.', rendered['embed'].description)
            self.assertEqual(await self.rows('SELECT * FROM ex_items'), before)
            self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='ex_arm'"), receipts)
            await self.conn.execute(f'UPDATE profiles SET {item}_armed=0')
            await self.conn.execute('UPDATE ex_items SET quantity=0 WHERE item_id=?', (item,))
            rendered, session = await self.press(session, f'ex_arm_{item}')
            self.assertIn(f'You have no {name}.', rendered['embed'].description)
            self.assertEqual(await self.rows(f'SELECT {item}_armed FROM profiles'), [{f'{item}_armed': 0}])
            self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='ex_arm'"), receipts)

    async def test_arm_with_live_run_notice_and_run_unchanged(self):
        session = await self.seed([['ex_attack', 'ex_defense']])
        _, session = await self.press(session, 'ex_claim')
        await self.conn.execute("INSERT INTO arena_runs(run_id,profile_id,started_at,floor,slot,team,enemy) "
                                "VALUES ('live',?,1000,1,0,'[]','{}')", (session['profile_id'],))
        before = await self.rows('SELECT * FROM arena_runs')
        for item in ('ex_attack', 'ex_defense'):
            rendered, session = await self.press(session, f'ex_arm_{item}')
            self.assertIn('A run in progress does not get it.', rendered['embed'].description)
            self.assertEqual(await self.rows('SELECT * FROM arena_runs'), before)
            self.assertEqual(await self.rows(f'SELECT {item}_armed FROM profiles'), [{f'{item}_armed': 1}])

    async def test_arm_service_refusals_and_rule_driven_notice(self):
        from content.balance import load_table
        from pokewalker.services import arena
        screens = importlib.import_module('pokewalker.bot.ex_gift')
        session = await self.seed([['ex_attack']])
        _, session = await self.press(session, 'ex_claim')
        for status, message in (('excluded', self.module.EXCLUDED), ('stale', self.module.REOPEN),
                                ('invalid', self.module.REOPEN)):
            with self.subTest(status=status), patch.object(arena, 'arm', return_value={'status': status}):
                refused = await self.click(session, 'ex_arm_ex_attack')
                refused.edit_original_response.assert_not_awaited()
                self.assertEqual(refused.followup.send.await_args.args[0], message)
        rules = copy.deepcopy(load_table('arena')['rules'])
        rules['x_items']['multiplier'] = 3
        rules['ex_items']['items']['ex_attack']['stat'] = 'defense'
        with patch.object(screens, 'load_table', return_value={'rules': rules}):
            rendered, _ = await self.press(session, 'ex_arm_ex_attack')
        self.assertIn('EX-Attack armed: ×3 defense', rendered['embed'].description)

    async def shiny_picker(self, count=1, item='shiny_patch'):
        session = await self.seed([[item]])
        _, session = await self.press(session, 'ex_claim')
        await self.conn.execute('DELETE FROM pokemon')
        for index in range(count):
            await self.conn.execute(
                'INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,'
                'iv_stamina,gender,shiny,origin,content_version,caught_at) '
                "VALUES (?,?,1,20,10,10,10,'male',0,'catch','test',?)",
                (f'p{index:02}', session['profile_id'], index))
        return await self.press(session, f'ex_use_{item}')

    async def shiny_preview(self):
        _, session = await self.shiny_picker()
        return await self.press(session, 'ex_pick', ['p00'])

    async def details_ex_item(self, item='shiny_patch'):
        _, session = await self.shiny_picker(item=item)
        _, session = await self.press(session, 'storage')
        return await self.press(session, 'storage_open', ['p00'])

    async def test_details_shiny_patch_preview_back_returns_to_details(self):
        _, session = await self.details_ex_item()
        before = await self.voucher_snapshot()
        preview, session = await self.press(session, 'ex_preview_shiny_patch')
        self.assertEqual(preview['embed'].title, 'Use Shiny Patch')
        self.assertEqual(preview['embed'].description, 'Bulbasaur becomes shiny. Uses 1 Shiny Patch (have 1).')
        back = self.buttons(preview)['Back'].custom_id.rsplit(':', 1)[-1]
        self.assertEqual(back, 'storage_detail')
        rendered, session = await self.press(session, back)
        self.assertEqual(rendered['embed'].title, 'Pokémon details')
        self.assertNotIn('ex_preview', json.loads(session['selection']))
        self.assertEqual(await self.voucher_snapshot(), before)
        refused = await self.click(session, 'ex_shiny_patch_confirm')
        self.assertEqual(refused.followup.send.await_args.args[0], 'Preview the Shiny Patch before confirming.')
        self.assertEqual(await self.voucher_snapshot(), before)
        # Details also clear a picker preview's return target and item.
        _, session = await self.press(session, 'ex_use_shiny_patch')
        _, session = await self.press(session, 'ex_pick', ['p00'])
        self.assertEqual(json.loads(session['selection'])['ex_back'], 'ex_pick')
        _, session = await self.press(session, 'storage_detail')
        for key in ('ex_back', 'ex_item', 'ex_preview'):
            self.assertNotIn(key, json.loads(session['selection']))
        preview, _ = await self.press(session, 'ex_preview_shiny_patch')
        self.assertTrue(self.buttons(preview)['Back'].custom_id.endswith(':storage_detail'))

    async def test_details_shiny_patch_confirm_redraws_details_shiny(self):
        rendered, session = await self.details_ex_item()
        before_image = rendered['embed'].image.url
        await self.conn.execute('UPDATE ex_items SET quantity=2')
        _, session = await self.press(session, 'ex_preview_shiny_patch')
        rendered, session = await self.press(session, 'ex_shiny_patch_confirm')
        self.assertEqual(rendered['embed'].title, 'Pokémon details')
        self.assertIn(' · Shiny', rendered['embed'].description)
        self.assertNotEqual(rendered['embed'].image.url, before_image)
        self.assertEqual(await self.rows('SELECT shiny,revision FROM pokemon'), [{'shiny': 1, 'revision': 1}])
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 1}])
        self.assertFalse(self.buttons(rendered)['Use Shiny Patch'].disabled)
        self.assertEqual(json.loads(session['selection'])['pokemon_revision'], 1)
        self.assertNotIn('ex_preview', json.loads(session['selection']))
        before = await self.voucher_snapshot()
        refused = await self.click(session, 'ex_shiny_patch_confirm')
        self.assertEqual(refused.followup.send.await_args.args[0], 'Preview the Shiny Patch before confirming.')
        self.assertEqual(await self.voucher_snapshot(), before)

    async def test_details_golden_bottlecap_confirm_redraws_perfect_ivs(self):
        from pokewalker.domain.cp import cp
        from pokewalker.services import storage
        _, session = await self.details_ex_item('golden_bottlecap')
        preview, session = await self.press(session, 'ex_preview_golden_bottlecap')
        self.assertEqual(preview['embed'].title, 'Use Golden Bottlecap')
        self.assertTrue(self.buttons(preview)['Back'].custom_id.endswith(':storage_detail'))
        rendered, session = await self.press(session, 'ex_golden_bottlecap_confirm')
        pokemon = (await self.rows("SELECT * FROM pokemon WHERE pokemon_uid='p00'"))[0]
        self.assertEqual(tuple(pokemon[key] for key in ('iv_attack', 'iv_defense', 'iv_stamina')), (15, 15, 15))
        self.assertEqual(pokemon['revision'], 1)
        identity, _ = storage.identify(self.bot.content, pokemon)
        base = [identity[key] for key in ('base_attack', 'base_defense', 'base_stamina')]
        expected_cp = cp(base, (15, 15, 15), pokemon['level_x2'], multipliers=self.walker.multipliers)
        self.assertEqual(rendered['embed'].title, 'Pokémon details')
        self.assertIn(f'CP {expected_cp} ·', rendered['embed'].description)
        self.assertIn('Appraisal: 4 stars', rendered['embed'].description)
        self.assertNotIn('15 / 15 / 15', rendered['embed'].description)
        self.assertNotIn('Use Golden Bottlecap', self.buttons(rendered))
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 0}])
        self.assertEqual(json.loads(session['selection'])['pokemon_revision'], 1)
        self.assertNotIn('ex_preview', json.loads(session['selection']))

    async def test_details_refusals_shiny_perfect_and_deployed_with_messages(self):
        from pokewalker.services import gyms
        _, session = await self.details_ex_item()
        await self.conn.execute("INSERT INTO ex_items VALUES (?,'golden_bottlecap',1)", (session['profile_id'],))
        for condition, item, message in (
                ('shiny', 'shiny_patch', 'It is already shiny. No Shiny Patch was used.'),
                ('perfect', 'golden_bottlecap', 'Its IVs are already perfect. No Golden Bottlecap was used.'),
                ('deployed', 'golden_bottlecap', 'Recall it from the gym first')):
            with self.subTest(condition=condition):
                await self.conn.execute('UPDATE pokemon SET shiny=?,iv_attack=?,iv_defense=?,iv_stamina=?',
                                        (int(condition == 'shiny'), *((15,) * 3 if condition == 'perfect' else (10,) * 3)))
                if condition == 'deployed':
                    gym = await self.writer.run(lambda conn: gyms.create(conn, session['guild_id'], 'Park', 100))
                    deployed = await self.writer.run(lambda conn: gyms.deploy(
                        conn, session, gym['gym_id'], 'p00', 0, 1000, self.bot.content))
                    self.assertEqual(deployed['status'], 'deployed')
                rendered, session = await self.press(session, 'storage_detail')
                for label in ('Use Shiny Patch', 'Use Golden Bottlecap'):
                    self.assertFalse(self.buttons(rendered)[label].disabled)
                before = await self.voucher_snapshot()
                refused = await self.click(session, f'ex_preview_{item}')
                refused.edit_original_response.assert_not_awaited()
                self.assertEqual(refused.followup.send.await_args.args[0], message)
                self.assertTrue(refused.followup.send.await_args.kwargs['ephemeral'])
                self.assertEqual(await self.voucher_snapshot(), before)
        # Shininess has no combat-stat restriction, even for a gym defender (D8).
        _, session = await self.press(session, 'ex_preview_shiny_patch')
        rendered, _ = await self.press(session, 'ex_shiny_patch_confirm')
        self.assertIn(' · Shiny', rendered['embed'].description)
        self.assertIn('Deployed at Park', rendered['embed'].description)

    async def test_details_stale_preview_after_trade_refused(self):
        import random
        from pokewalker.services import profiles, trading
        _, session = await self.details_ex_item()
        _, session = await self.press(session, 'ex_preview_shiny_patch')
        partner = await self.writer.run(lambda conn: profiles.enroll(
            conn, 123, 789, 1, self.bot.content, random.Random(9), datetime.now(timezone.utc)))
        await self.conn.execute('UPDATE profiles SET companion_uid=NULL WHERE profile_id=?', (partner['profile_id'],))
        await self.conn.execute('UPDATE pokemon SET favorite=0 WHERE profile_id=?', (partner['profile_id'],))
        other = {**session, 'session_id': 'other', 'user_id': '789', 'profile_id': partner['profile_id']}
        await self.conn.execute('INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) '
                                "VALUES ('other','123','789',?,9000)", (partner['profile_id'],))
        trade = await self.writer.run(lambda conn: trading.open_or_join(conn, session, '789', 1000, False))
        tid = trade['trade_id']
        await self.writer.run(lambda conn: trading.open_or_join(conn, other, '456', 1001, False))
        await self.writer.run(lambda conn: trading.offer(conn, session, tid, 'p00', 1002))
        await self.writer.run(lambda conn: trading.offer(conn, other, tid, partner['companion_uid'], 1003))
        await self.writer.run(lambda conn: trading.confirm(conn, session, tid, 2, 1004, self.bot.content))
        swapped = await self.writer.run(lambda conn: trading.confirm(conn, other, tid, 2, 1005, self.bot.content))
        self.assertEqual(swapped['status'], 'completed')
        before = await self.voucher_snapshot()
        refused = await self.click(session, 'ex_shiny_patch_confirm')
        self.assertEqual(refused.followup.send.await_args.args[0], 'That Pokémon changed. Pick it again.')
        self.assertEqual(await self.voucher_snapshot(), before)

    async def test_details_confirm_without_preview_spends_nothing(self):
        _, session = await self.details_ex_item()
        before = await self.voucher_snapshot()
        refused = await self.click(session, 'ex_shiny_patch_confirm')
        refused.edit_original_response.assert_not_awaited()
        self.assertEqual(refused.followup.send.await_args.args[0], 'Preview the Shiny Patch before confirming.')
        self.assertTrue(refused.followup.send.await_args.kwargs['ephemeral'])
        self.assertEqual(await self.voucher_snapshot(), before)

    async def test_shiny_patch_button_only_while_held(self):
        session = await self.seed([['shiny_patch', 'shiny_patch']])
        rendered, session = await self.press(session, 'ex_gift')
        self.assertFalse(any('Use Shiny Patch' in label for label in self.buttons(rendered)))
        rendered, session = await self.press(session, 'ex_claim')
        button = self.buttons(rendered)['Use Shiny Patch (2)']
        self.assertEqual(button.row, 1)
        self.assertTrue(button.custom_id.endswith(':ex_use_shiny_patch'))
        await self.conn.execute('UPDATE ex_items SET quantity=0')
        rendered, _ = await self.press(session, 'ex_gift')
        self.assertNotIn('Use Shiny Patch (2)', self.buttons(rendered))

    async def test_picker_pages_and_pick_opens_preview(self):
        rendered, session = await self.shiny_picker(11)
        self.assertEqual(json.loads(session['selection']),
                         {'phase': 'ex_pick', 'ex_item': 'shiny_patch', 'offset': 0})
        select = next(child for child in rendered['view'].children if hasattr(child, 'options'))
        self.assertEqual([option.value for option in select.options], [f'p{i:02}' for i in range(10, 0, -1)])
        self.assertRegex(select.options[0].label, r'Bulbasaur · CP \d+')
        self.assertTrue(select.custom_id.endswith(':ex_pick'))
        self.assertTrue(self.buttons(rendered)['Prev'].disabled)
        rendered, session = await self.press(session, 'ex_pick_next')
        select = next(child for child in rendered['view'].children if hasattr(child, 'options'))
        self.assertEqual([option.value for option in select.options], ['p00'])
        self.assertTrue(self.buttons(rendered)['Next'].disabled)
        rendered, session = await self.press(session, 'ex_pick_prev')
        preview, session = await self.press(session, 'ex_pick', ['p10'])
        self.assertEqual(preview['embed'].title, 'Use Shiny Patch')
        self.assertEqual(preview['embed'].description, 'Bulbasaur becomes shiny. Uses 1 Shiny Patch (have 1).')
        self.assertEqual(json.loads(session['selection'])['ex_back'], 'ex_pick')
        self.assertEqual(json.loads(session['selection'])['ex_preview'], 'shiny_patch')
        back, session = await self.press(session, 'ex_pick')
        self.assertNotIn('ex_preview', json.loads(session['selection']))
        self.assertTrue(self.buttons(back)['Back'].custom_id.endswith(':ex_gift'))
        for child in back['view'].children:
            self.assertIsNotNone(re.fullmatch(self.module.CUSTOM_ID, child.custom_id))

    async def test_confirm_returns_to_ex_gift_with_notice(self):
        _, session = await self.shiny_preview()
        rendered, session = await self.press(session, 'ex_shiny_patch_confirm')
        self.assertEqual(rendered['embed'].title, 'EX-Gift')
        self.assertIn('Bulbasaur is now shiny.', rendered['embed'].description)
        self.assertEqual(await self.rows('SELECT shiny,revision FROM pokemon'), [{'shiny': 1, 'revision': 1}])
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 0}])

    async def test_preview_refuses_shiny_target(self):
        _, session = await self.shiny_picker()
        await self.conn.execute('UPDATE pokemon SET shiny=1')
        refused = await self.click(session, 'ex_pick', ['p00'])
        self.assertEqual(refused.followup.send.await_args.args[0],
                         'It is already shiny. No Shiny Patch was used.')
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 1}])
        rendered, session = await self.press(session, 'ex_use_shiny_patch')
        select = next(child for child in rendered['view'].children if hasattr(child, 'options'))
        self.assertTrue(select.options[0].label.endswith(' · Shiny'))

    async def test_confirm_without_or_with_other_preview_spends_nothing(self):
        _, session = await self.shiny_picker()
        for preview in (None, 'golden_bottlecap'):
            selection = json.loads(session['selection'])
            if preview:
                selection['ex_preview'] = preview
            await self.conn.execute('UPDATE sessions SET selection=?', (json.dumps(selection),))
            refused = await self.click(session, 'ex_shiny_patch_confirm')
            self.assertEqual(refused.followup.send.await_args.args[0], 'Preview the Shiny Patch before confirming.')
            self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 1}])
            self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='shiny_patch'"), [])

    async def test_stale_confirm_refused(self):
        _, session = await self.shiny_preview()
        await self.conn.execute('UPDATE pokemon SET revision=revision+1')
        refused = await self.click(session, 'ex_shiny_patch_confirm')
        self.assertEqual(refused.followup.send.await_args.args[0], 'That Pokémon changed. Pick it again.')
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 1}])

    async def test_shiny_preview_missing_and_stale_and_details_return(self):
        _, session = await self.shiny_preview()
        await self.conn.execute('UPDATE ex_items SET quantity=0')
        refused = await self.click(session, 'ex_preview_shiny_patch')
        self.assertEqual(refused.followup.send.await_args.args[0], 'You have no Shiny Patch. Nothing was used.')
        refused = await self.click(session, 'ex_shiny_patch_confirm')
        self.assertEqual(refused.followup.send.await_args.args[0], 'You have no Shiny Patch. Nothing was used.')
        await self.conn.execute('UPDATE ex_items SET quantity=1')
        selection = json.loads(session['selection'])
        selection.pop('ex_back')
        await self.conn.execute('UPDATE sessions SET selection=?', (json.dumps(selection),))
        rendered, session = await self.press(session, 'ex_preview_shiny_patch')
        self.assertTrue(self.buttons(rendered)['Back'].custom_id.endswith(':storage_detail'))
        rendered, session = await self.press(session, 'ex_shiny_patch_confirm')
        self.assertNotEqual(rendered['embed'].title, 'EX-Gift')
        await self.conn.execute('UPDATE pokemon SET revision=revision+1')
        refused = await self.click(session, 'ex_preview_shiny_patch')
        self.assertEqual(refused.followup.send.await_args.args[0], self.module.REOPEN)

    async def test_shiny_picker_rejects_off_page_values_and_clamps_after_removal(self):
        _, session = await self.shiny_picker(11)
        for values in (['p00'], ['missing'], ['p10', 'p09']):
            refused = await self.click(session, 'ex_pick', values)
            self.assertEqual(refused.followup.send.await_args.args[0], self.module.REOPEN)
            self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 1}])
        _, session = await self.press(session, 'ex_pick_next')
        await self.conn.execute("DELETE FROM pokemon WHERE pokemon_uid='p00'")
        rendered, session = await self.press(session, 'ex_pick_next')
        self.assertEqual(json.loads(session['selection'])['offset'], 0)
        self.assertTrue(self.buttons(rendered)['Next'].disabled)
        await self.conn.execute('DELETE FROM pokemon')
        rendered, session = await self.press(session, 'ex_use_shiny_patch')
        self.assertFalse(any(hasattr(child, 'options') for child in rendered['view'].children))
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 1}])

    async def test_golden_bottlecap_button_only_while_held(self):
        session = await self.seed([['golden_bottlecap', 'golden_bottlecap']])
        rendered, session = await self.press(session, 'ex_gift')
        self.assertFalse(any('Use Golden Bottlecap' in label for label in self.buttons(rendered)))
        rendered, session = await self.press(session, 'ex_claim')
        button = self.buttons(rendered)['Use Golden Bottlecap (2)']
        self.assertEqual(button.row, 1)
        self.assertTrue(button.custom_id.endswith(':ex_use_golden_bottlecap'))
        await self.conn.execute('UPDATE ex_items SET quantity=0')
        rendered, _ = await self.press(session, 'ex_gift')
        self.assertFalse(any('Use Golden Bottlecap' in label for label in self.buttons(rendered)))

    async def test_golden_preview_shows_cp_and_appraisal_change(self):
        from pokewalker.domain.cp import cp
        _, session = await self.shiny_picker(11, item='golden_bottlecap')
        self.assertEqual(json.loads(session['selection']),
                         {'phase': 'ex_pick', 'ex_item': 'golden_bottlecap', 'offset': 0})
        rendered, session = await self.press(session, 'ex_pick_next')
        self.assertEqual(rendered['embed'].title, 'Use Golden Bottlecap')
        select = next(child for child in rendered['view'].children if hasattr(child, 'options'))
        self.assertEqual([option.value for option in select.options], ['p00'])
        preview, session = await self.press(session, 'ex_pick', ['p00'])
        from pokewalker.services import storage
        pokemon = (await self.rows("SELECT * FROM pokemon WHERE pokemon_uid='p00'"))[0]
        identity, _ = storage.identify(self.walker.bot.content, pokemon)
        base = [identity[key] for key in ('base_attack', 'base_defense', 'base_stamina')]
        before = cp(base, (10, 10, 10), 20, multipliers=self.walker.multipliers)
        after = cp(base, (15, 15, 15), 20, multipliers=self.walker.multipliers)
        self.assertEqual(preview['embed'].title, 'Use Golden Bottlecap')
        self.assertEqual(preview['embed'].description,
                         f'CP {before} → {after} · Appraisal 2 → 4 stars · uses 1 Golden Bottlecap (have 1)')
        self.assertEqual(json.loads(session['selection'])['ex_preview'], 'golden_bottlecap')
        self.assertTrue(self.buttons(preview)['Confirm'].custom_id.endswith(':ex_golden_bottlecap_confirm'))
        self.assertTrue(self.buttons(preview)['Back'].custom_id.endswith(':ex_pick'))
        back, session = await self.press(session, 'ex_pick')
        self.assertNotIn('ex_preview', json.loads(session['selection']))
        _, session = await self.press(session, 'ex_pick', ['p00'])
        rendered, session = await self.press(session, 'ex_golden_bottlecap_confirm')
        self.assertEqual(rendered['embed'].title, 'EX-Gift')
        self.assertIn("Bulbasaur's IVs are now 15 / 15 / 15.", rendered['embed'].description)
        self.assertEqual(await self.rows("SELECT iv_attack,iv_defense,iv_stamina,revision FROM pokemon WHERE pokemon_uid='p00'"),
                         [{'iv_attack': 15, 'iv_defense': 15, 'iv_stamina': 15, 'revision': 1}])
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 0}])

    async def test_golden_preview_refusals(self):
        _, session = await self.shiny_picker(item='golden_bottlecap')
        _, session = await self.press(session, 'ex_pick', ['p00'])
        for sql, message in (
                ('UPDATE pokemon SET iv_attack=15,iv_defense=15,iv_stamina=15',
                 'Its IVs are already perfect. No Golden Bottlecap was used.'),
                ('UPDATE pokemon SET iv_attack=10,iv_defense=10,iv_stamina=10; UPDATE ex_items SET quantity=0',
                 'You have no Golden Bottlecap. Nothing was used.')):
            await self.conn.executescript(sql)
            before = await self.rows('SELECT * FROM pokemon')
            refused = await self.click(session, 'ex_preview_golden_bottlecap')
            self.assertEqual(refused.followup.send.await_args.args[0], message)
            refused = await self.click(session, 'ex_golden_bottlecap_confirm')
            self.assertEqual(refused.followup.send.await_args.args[0], message)
            self.assertEqual(await self.rows('SELECT * FROM pokemon'), before)
            self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='golden_bottlecap'"), [])
        await self.conn.execute('UPDATE pokemon SET revision=1')
        refused = await self.click(session, 'ex_preview_golden_bottlecap')
        self.assertEqual(refused.followup.send.await_args.args[0], self.module.REOPEN)
        refused = await self.click(session, 'ex_golden_bottlecap_confirm')
        self.assertEqual(refused.followup.send.await_args.args[0], 'That Pokémon changed. Pick it again.')
        await self.conn.execute('UPDATE pokemon SET revision=0')
        await self.conn.execute('UPDATE ex_items SET quantity=1')
        _, session = await self.press(session, 'ex_pick', ['p00'])
        from pokewalker.services import gyms
        gym = await self.writer.run(lambda conn: gyms.create(conn, session['guild_id'], 'Park', 100))
        deployed = await self.writer.run(lambda conn: gyms.deploy(
            conn, session, gym['gym_id'], 'p00', 0, 1000, self.walker.bot.content))
        self.assertEqual(deployed['status'], 'deployed')
        refused = await self.click(session, 'ex_golden_bottlecap_confirm')
        self.assertEqual(refused.followup.send.await_args.args[0], 'Recall it from the gym first')
        _, session = await self.press(session, 'ex_use_golden_bottlecap')
        refused = await self.click(session, 'ex_pick', ['p00'])
        self.assertEqual(refused.followup.send.await_args.args[0], 'Recall it from the gym first')
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 1}])

    async def test_golden_confirm_after_shiny_preview_or_none_spends_nothing(self):
        _, session = await self.shiny_picker(item='golden_bottlecap')
        await self.conn.execute("INSERT INTO ex_items VALUES (?,'shiny_patch',1)", (session['profile_id'],))
        before = await self.rows('SELECT * FROM pokemon')
        for preview in (None, 'shiny_patch'):
            if preview:
                _, session = await self.press(session, 'ex_use_shiny_patch')
                _, session = await self.press(session, 'ex_pick', ['p00'])
            refused = await self.click(session, 'ex_golden_bottlecap_confirm')
            self.assertEqual(refused.followup.send.await_args.args[0], 'Preview the Golden Bottlecap before confirming.')
            self.assertEqual(await self.rows('SELECT * FROM pokemon'), before)
            self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 1}, {'quantity': 1}])
            self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='golden_bottlecap'"), [])

    async def test_time_gear_button_only_while_held(self):
        session = await self.seed([['time_gear_fragment', 'time_gear_fragment']])
        rendered, session = await self.press(session, 'ex_gift')
        self.assertFalse(any('Use Time Gear' in label for label in self.buttons(rendered)))
        rendered, session = await self.press(session, 'ex_claim')
        button = self.buttons(rendered)['Use Time Gear Fragment (2)']
        self.assertEqual(button.row, 1)
        self.assertTrue(button.custom_id.endswith(':ex_use_time_gear_fragment'))
        self.assertIsNotNone(re.fullmatch(self.module.CUSTOM_ID, button.custom_id))
        await self.conn.execute('UPDATE ex_items SET quantity=0')
        rendered, _ = await self.press(session, 'ex_gift')
        self.assertFalse(any('Use Time Gear' in label for label in self.buttons(rendered)))

    async def test_time_gear_confirm_then_notice(self):
        from pokewalker.services.cooldowns import PLAYER
        session = await self.seed([['time_gear_fragment']])
        _, session = await self.press(session, 'ex_claim')
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,paused_until) "
                                "VALUES ('123','456',1,9999999999)")
        preview, session = await self.press(session, 'ex_use_time_gear_fragment')
        self.assertEqual(json.loads(session['selection']), {'phase': 'ex_time_gear'})
        self.assertEqual(preview['embed'].title, 'Use Time Gear Fragment')
        text = preview['embed'].description
        for line in ('Reset your cooldowns in this server?', *PLAYER.values(),
                     'Share and message limits stay.', 'Uses 1 Time Gear Fragment (have 1).'):
            self.assertIn(line, text)
        self.assertEqual({label: button.custom_id.rsplit(':', 1)[1]
                          for label, button in self.buttons(preview).items()},
                         {'Confirm': 'ex_time_gear_confirm', 'Back': 'ex_gift'})
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 1}])
        back, session = await self.press(session, 'ex_gift')
        self.assertEqual(back['embed'].title, 'EX-Gift')
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 1}])
        _, session = await self.press(session, 'ex_use_time_gear_fragment')
        confirmed, session = await self.press(session, 'ex_time_gear_confirm')
        self.assertIn('Time Gear Fragment used: your cooldowns in this server are reset.',
                      confirmed['embed'].description)
        self.assertEqual(json.loads(session['selection']), {'phase': 'ex_gift', 'offset': 0})
        self.assertFalse(any('Use Time Gear' in label for label in self.buttons(confirmed)))
        missing, session = await self.press(session, 'ex_use_time_gear_fragment')
        self.assertIn('You have no Time Gear Fragment.', missing['embed'].description)
        # Stock can disappear after preview in another session.
        await self.conn.execute('UPDATE ex_items SET quantity=1')
        _, session = await self.press(session, 'ex_use_time_gear_fragment')
        await self.conn.execute('UPDATE ex_items SET quantity=0')
        missing, _ = await self.press(session, 'ex_time_gear_confirm')
        self.assertIn('You have no Time Gear Fragment.', missing['embed'].description)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='ex_time_gear'")), 1)

    async def test_time_gear_confirm_without_phase_refused(self):
        session = await self.seed([['time_gear_fragment']])
        _, session = await self.press(session, 'ex_claim')
        refused = await self.click(session, 'ex_time_gear_confirm')
        refused.edit_original_response.assert_not_awaited()
        self.assertEqual(refused.followup.send.await_args.args[0], self.module.REOPEN)
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 1}])
        self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='ex_time_gear'"), [])

    async def test_badge_shows_while_unclaimed_clears_after_claim(self):
        session = await self.seed([['poke_ball'], ['shiny_patch']])
        home, session = await self.press(session, 'home')
        self.assertIn('EX-Gift (!)', self.buttons(home))
        self.assertFalse(self.buttons(home)['EX-Gift (!)'].disabled)
        gift, session = await self.press(session, 'ex_gift')
        self.assertEqual(gift['embed'].title, 'EX-Gift')
        await self.conn.execute("UPDATE ex_gift_recipients SET claimed_at=999 WHERE gift_id='gift-000'")
        home, session = await self.press(session, 'home')
        self.assertIn('EX-Gift (!)', self.buttons(home))
        _, session = await self.press(session, 'ex_claim')
        home, _ = await self.press(session, 'home')
        self.assertIn('EX-Gift', self.buttons(home))
        self.assertNotIn('EX-Gift (!)', self.buttons(home))
        self.assertFalse(self.buttons(home)['EX-Gift'].disabled)

    async def test_badge_ignores_held_and_armed_ex_items(self):
        session = await self.seed([list(service.EX_ITEMS)])
        _, session = await self.press(session, 'ex_claim')
        for quantity, attack, defense in ((5, 0, 0), (0, 1, 0), (0, 0, 1), (5, 1, 1)):
            with self.subTest(quantity=quantity, attack=attack, defense=defense):
                await self.conn.execute('UPDATE ex_items SET quantity=?', (quantity,))
                await self.conn.execute('UPDATE profiles SET ex_attack_armed=?,ex_defense_armed=?',
                                        (attack, defense))
                home, session = await self.press(session, 'home')
                labels = [button.label for button in home['view'].children
                          if button.custom_id.endswith(':ex_gift')]
                self.assertEqual(labels, ['EX-Gift'])

    async def test_badge_per_server_profile(self):
        session = await self.seed([['shiny_patch']])
        other = await self.writer.run(lambda conn: self.module.profiles.enroll(
            conn, 789, 456, 1, self.bot.content, self.walker.rng, datetime.now(timezone.utc)))
        await self.conn.execute('INSERT INTO ex_gift_recipients(gift_id,profile_id) VALUES (?,?)',
                                ('gift-000', other['profile_id']))
        for guild in (123, 789):
            interaction = self.interaction(guild=guild)
            await self.walker.open(interaction)
            self.assertIn('EX-Gift (!)', self.buttons(interaction.edit_original_response.await_args.kwargs))
        _, session = await self.press(session, 'ex_claim')
        for guild, label in ((123, 'EX-Gift'), (789, 'EX-Gift (!)')):
            interaction = self.interaction(guild=guild)
            await self.walker.open(interaction)
            rendered = interaction.edit_original_response.await_args.kwargs
            labels = [button.label for button in rendered['view'].children
                      if button.custom_id.endswith(':ex_gift')]
            self.assertEqual(labels, [label])

    async def test_gift_list_pages_ten_with_prev_and_next(self):
        session = await self.seed([['poke_ball']] * 10 + [['shiny_patch']])
        first, session = await self.press(session, 'ex_gift')
        self.assertEqual(first['embed'].title, 'EX-Gift')
        self.assertIn('New gifts: 11 · page 1/2', first['embed'].description)
        self.assertEqual(first['embed'].description.count(' UTC:'), 10)
        self.assertIn('1970-01-01 UTC: Poké Ball', first['embed'].description)
        self.assertNotIn('Shiny Patch', first['embed'].description)
        self.assertTrue(self.buttons(first)['Prev'].disabled)
        self.assertFalse(self.buttons(first)['Next'].disabled)
        self.assertEqual(json.loads(session['selection']), {'phase': 'ex_gift', 'offset': 0})
        second, session = await self.press(session, 'ex_gift_next')
        self.assertIn('New gifts: 11 · page 2/2', second['embed'].description)
        self.assertIn('1970-01-11 UTC: Shiny Patch', second['embed'].description)
        self.assertEqual(second['embed'].description.count(' UTC:'), 1)
        self.assertFalse(self.buttons(second)['Prev'].disabled)
        self.assertTrue(self.buttons(second)['Next'].disabled)
        end, session = await self.press(session, 'ex_gift_next')
        self.assertIn('page 2/2', end['embed'].description)
        previous, session = await self.press(session, 'ex_gift_prev')
        self.assertIn('page 1/2', previous['embed'].description)
        start, _ = await self.press(session, 'ex_gift_prev')
        self.assertIn('page 1/2', start['embed'].description)
        self.assertEqual(await self.rows('SELECT claimed_at FROM ex_gift_recipients WHERE claimed_at IS NOT NULL'), [])
        session = (await self.rows('SELECT * FROM sessions'))[0]
        claimed, _ = await self.press(session, 'ex_claim')
        self.assertIn('Claimed 11 gifts: 10 items went to your Inbox.', claimed['embed'].description)
        self.assertIn('EX items added: Shiny Patch ×1', claimed['embed'].description)
        self.assertEqual(len(await self.rows('SELECT * FROM inbox_items')), 10)
        self.assertEqual(len(await self.rows('SELECT * FROM ex_gift_recipients WHERE claimed_at IS NOT NULL')), 11)

    async def test_offset_past_end_falls_back_after_claim_elsewhere(self):
        session = await self.seed([['poke_ball']] * 11)
        _, session = await self.press(session, 'ex_gift')
        _, session = await self.press(session, 'ex_gift_next')
        _, other = await self.open()
        await self.writer.run(lambda conn: service.claim(conn, other, 1000))
        rendered, session = await self.press(session, 'ex_gift_next')
        self.assertEqual(json.loads(session['selection'])['offset'], 0)
        self.assertIn('No new gifts.', rendered['embed'].description)
        self.assertTrue(self.buttons(rendered)['Prev'].disabled)
        self.assertTrue(self.buttons(rendered)['Next'].disabled)

    async def test_claim_disabled_without_gifts_ex_items_still_listed(self):
        session = await self.seed([['shiny_patch', 'shiny_patch', 'ex_attack']])
        _, session = await self.press(session, 'ex_claim')
        rendered, session = await self.press(session, 'ex_gift')
        self.assertIn('No new gifts.\nEX items:\n', rendered['embed'].description)
        self.assertIn('Shiny Patch ×2', rendered['embed'].description)
        self.assertIn('EX-Attack ×1', rendered['embed'].description)
        self.assertNotIn('Time Gear Fragment', rendered['embed'].description)
        self.assertTrue(self.buttons(rendered)['Claim'].disabled)
        empty, _ = await self.press(session, 'ex_claim')
        self.assertIn('No new gifts to claim.', empty['embed'].description)

    async def test_claim_notice_counts_inbox_items_and_ex_items(self):
        session = await self.seed([['poke_ball', 'arena_ticket:bronze', 'shiny_patch'],
                                   ['shiny_patch', 'ex_defense']])
        rendered, session = await self.press(session, 'ex_claim')
        self.assertIn('Claimed 2 gifts: 2 items went to your Inbox.', rendered['embed'].description)
        self.assertIn('EX items added: Shiny Patch ×2, EX-Defense ×1', rendered['embed'].description)
        self.assertEqual(json.loads(session['selection']), {'phase': 'ex_gift', 'offset': 0})
        self.assertEqual(len(await self.rows('SELECT * FROM inbox_items')), 2)
        self.assertEqual(await self.rows('SELECT * FROM inventory WHERE item_id=\'shiny_patch\''), [])

    async def test_claimed_ordinary_items_and_tickets_appear_in_inbox(self):
        session = await self.seed([['poke_ball', 'arena_ticket:bronze']])
        rendered, session = await self.press(session, 'ex_claim')
        self.assertIn('Claimed 1 gifts: 2 items went to your Inbox.', rendered['embed'].description)
        self.assertNotIn('EX items added:', rendered['embed'].description)
        self.assertIn('No EX items yet.', rendered['embed'].description)
        inbox, _ = await self.press(session, 'inbox')
        self.assertEqual(inbox['embed'].title, 'Reward inbox')
        self.assertIn('Poke Ball', inbox['embed'].description)
        self.assertIn('Bronze Arena Ticket', inbox['embed'].description)
        self.assertIn('EX-Gift', inbox['embed'].description)
        self.assertNotIn('gift-000', inbox['embed'].description)

    async def test_claim_twice_through_router_claims_once(self):
        session = await self.seed([['poke_ball', 'shiny_patch']])
        _, session = await self.press(session, 'ex_gift')
        _, saved = await self.press(session, 'ex_claim')
        duplicate = await self.click(session, 'ex_claim')
        duplicate.edit_original_response.assert_not_awaited()
        duplicate.followup.send.assert_not_awaited()
        self.assertEqual(await self.rows('SELECT * FROM sessions'), [saved])
        self.assertEqual(len(await self.rows('SELECT * FROM inbox_items')), 1)
        self.assertEqual(await self.rows('SELECT item_id,quantity FROM ex_items'),
                         [{'item_id': 'shiny_patch', 'quantity': 1}])
        receipts = await self.rows("SELECT key FROM action_receipts WHERE action='ex_claim'")
        self.assertEqual(receipts, [{'key': f"ex_claim:{session['session_id']}:{session['revision']}"}])

    async def test_paused_member_may_claim_excluded_member_refused(self):
        session = await self.seed([['poke_ball']])
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,paused_until) "
                                "VALUES ('123','456',1,9999999999)")
        rendered, session = await self.press(session, 'ex_claim')
        self.assertIn('Claimed 1 gifts:', rendered['embed'].description)
        await self.conn.execute('UPDATE ex_gift_recipients SET claimed_at=NULL')
        await self.conn.execute('UPDATE restrictions SET excluded=1')
        refused = await self.click(session, 'ex_claim')
        refused.edit_original_response.assert_not_awaited()
        self.assertEqual(refused.followup.send.await_args.args[0], self.module.EXCLUDED)
        self.assertEqual(await self.rows('SELECT claimed_at FROM ex_gift_recipients'), [{'claimed_at': None}])
        self.assertEqual(len(await self.rows('SELECT * FROM inbox_items')), 1)

    async def test_description_fits_4096_with_ten_full_gifts(self):
        module = importlib.import_module('pokewalker.bot.ex_gift')
        longest = max((key for values in service.catalog(self.bot.content).values() for key in values),
                      key=lambda key: len(service.label(key, self.bot.content)))
        state = {'session': {'session_id': 'abcd', 'revision': 3}, 'content': self.bot.content,
                 'selection': {'phase': 'ex_gift', 'offset': 0}, 'total': 11,
                 'gifts': [{'created_at': 0, 'items': [longest] * 10} for _ in range(10)],
                 'held': {key: 1000 for key in service.EX_ITEMS},
                 'notice': 'Claimed 11 gifts: 110 items went to your Inbox.'}
        before = copy.deepcopy(state)
        rendered = module.render(state)
        self.assertLessEqual(len(rendered['embed'].description), 4096)
        self.assertEqual(rendered['embed'].description.count(service.label(longest, self.bot.content)), 100)
        self.assertIn(state['notice'], rendered['embed'].description)
        self.assertEqual(state, before)

    async def test_action_names_match_router_pattern(self):
        session = await self.seed([])
        rendered, session = await self.press(session, 'ex_gift')
        self.assertEqual([button.label for button in rendered['view'].children], ['Claim', 'Prev', 'Next', 'Back'])
        actions = []
        for button in rendered['view'].children:
            match = re.fullmatch(self.module.CUSTOM_ID, button.custom_id)
            self.assertIsNotNone(match)
            actions.append(match['action'])
            self.assertEqual(button.row, 0)
            self.assertIn(match['action'], self.walker.handlers)
        self.assertEqual(actions, ['ex_claim', 'ex_gift_prev', 'ex_gift_next', 'home'])
        home, _ = await self.press(session, 'home')
        self.assertNotEqual(home['embed'].title, 'EX-Gift')

    async def test_service_refusals_map_to_private_router_messages(self):
        session = await self.seed([])
        for status, message in [('excluded', self.module.EXCLUDED), ('stale', self.module.REOPEN)]:
            with self.subTest(status=status), patch.object(service, 'claim', return_value={'status': status}):
                refused = await self.click(session, 'ex_claim')
                refused.edit_original_response.assert_not_awaited()
                self.assertEqual(refused.followup.send.await_args.args[0], message)
