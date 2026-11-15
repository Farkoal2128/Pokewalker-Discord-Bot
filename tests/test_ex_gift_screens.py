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

    async def shiny_picker(self, count=1):
        session = await self.seed([['shiny_patch']])
        _, session = await self.press(session, 'ex_claim')
        await self.conn.execute('DELETE FROM pokemon')
        for index in range(count):
            await self.conn.execute(
                'INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,'
                'iv_stamina,gender,shiny,origin,content_version,caught_at) '
                "VALUES (?,?,1,20,10,10,10,'male',0,'catch','test',?)",
                (f'p{index:02}', session['profile_id'], index))
        return await self.press(session, 'ex_use_shiny_patch')

    async def shiny_preview(self):
        _, session = await self.shiny_picker()
        return await self.press(session, 'ex_pick', ['p00'])

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
