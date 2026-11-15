"""EX-Gift private screens through the durable router and real gift service."""

import copy
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

    async def press(self, session, action):
        interaction = await self.click(session, action)
        interaction.edit_original_response.assert_awaited_once()
        interaction.followup.send.assert_not_awaited()
        saved = (await self.rows('SELECT * FROM sessions WHERE session_id=?', (session['session_id'],)))[0]
        self.assertEqual(saved['revision'], session['revision'] + 1)
        return interaction.edit_original_response.await_args.kwargs, saved

    def buttons(self, rendered):
        return {button.label: button for button in rendered['view'].children}

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
