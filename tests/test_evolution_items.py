"""D21/D55/D61 concrete evolution-item grants and durable purchases."""
import json
from pathlib import Path
import random
import sqlite3
import unittest
from unittest.mock import patch

from pokewalker.db import Writer, open_db
from pokewalker.services import items
import test_conversion as conversion_tests


class EvolutionItemTests(unittest.IsolatedAsyncioTestCase):
    close = conversion_tests.ConversionTests.close
    rows = conversion_tests.ConversionTests.rows
    current = conversion_tests.ConversionTests.current
    snapshot = conversion_tests.ConversionTests.snapshot

    async def asyncSetUp(self):
        await conversion_tests.ConversionTests.asyncSetUp(self)
        self.content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        self.kind = self.content['evolution_items'][0]['id']
        self.session = await self.current()
        await self.conn.execute('UPDATE profiles SET stardust=500')

    async def buy(self, kind=None, session=None, content=None):
        return await self.writer.run(lambda conn: items.buy_evolution_item(
            conn, session or self.session, self.kind if kind is None else kind, 1000,
            self.content if content is None else content))

    async def test_resolve_evolution_item_uniform_kind_seeded(self):
        expected, actual = random.Random(23), random.Random(23)
        kinds = self.content['evolution_items']
        resolved = [items.resolve_item(actual, 'evolution_item', 2, self.content) for _ in range(1000)]
        self.assertEqual(resolved, [(expected.choice(kinds)['id'], 2) for _ in resolved])
        self.assertEqual({item for item, _ in resolved}, {kind['id'] for kind in kinds})

    async def test_resolve_with_no_kinds_gives_100_stardust(self):
        self.assertEqual(items.resolve_item(random.Random(1), 'evolution_item', 7,
                                            {'evolution_items': []}), ('stardust', 100))

    async def test_resolve_leaves_other_items_unchanged(self):
        for item in ('poke_ball', 'star_piece', 'stardust', 'unknown'):
            self.assertEqual(items.resolve_item(random.Random(1), item, 3, self.content), (item, 3))

    async def find(self, item, content=None):
        async def compute(conn):
            profile = (await self.rows('SELECT * FROM profiles'))[0]
            profile['find_meter_c'] = 9900
            return await items.apply_finds(conn, profile, 100, 1000, 'find', random.Random(1),
                                            self.content if content is None else content)
        with patch.object(items, 'roll_find', return_value={'item': item, 'quantity': 1}):
            await self.writer.run(compute)

    async def test_find_evolution_row_grants_named_kind_and_records_it(self):
        await self.find('evolution_item')
        found = (await self.rows('SELECT * FROM finds'))[0]
        self.assertIn(found['item_id'], {kind['id'] for kind in self.content['evolution_items']})
        self.assertEqual((found['quantity'], found['outcome']), (1, 'granted'))
        self.assertEqual((await self.rows('SELECT quantity FROM inventory WHERE item_id=?',
                                         (found['item_id'],)))[0]['quantity'], 1)
        receipt = (await self.rows("SELECT * FROM action_receipts WHERE action='find'"))[0]
        self.assertEqual(json.loads(receipt['result'])['item'], found['item_id'])
        line = (await self.rows('SELECT * FROM resource_ledger'))[0]
        self.assertEqual((line['resource_id'], line['delta'], line['reason']), (found['item_id'], 1, 'find'))

    async def test_find_star_piece_granted_as_ordinary_unit(self):
        await self.find('star_piece')
        self.assertEqual(await items.bag_units(self.conn, 'p'), 21)
        self.assertEqual((await self.rows('SELECT item_id FROM finds'))[0]['item_id'], 'star_piece')

    async def test_find_no_kinds_records_stardust_without_inventory_placeholder(self):
        await self.find('evolution_item', {'evolution_items': []})
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 600)
        self.assertEqual((await self.rows('SELECT item_id,quantity FROM finds'))[0],
                         {'item_id': 'stardust', 'quantity': 100})
        self.assertEqual(await items.bag_units(self.conn, 'p'), 20)

    async def test_buy_debits_500_grants_one_with_ledger(self):
        self.assertEqual(await self.buy(), {'item': self.kind, 'quantity': 1, 'stardust': 500})
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 0)
        self.assertEqual(await items.bag_units(self.conn, 'p'), 21)
        self.assertEqual((await self.rows('SELECT quantity FROM inventory WHERE item_id=?',
                                         (self.kind,)))[0]['quantity'], 1)
        receipt = (await self.rows('SELECT * FROM action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']), ('buy:abcd:0', 'buy', 'p'))
        lines = await self.rows('SELECT resource,resource_id,delta,reason FROM resource_ledger ORDER BY line_key')
        self.assertEqual(lines, [dict(resource='stardust', resource_id=None, delta=-500, reason='buy'),
                                dict(resource='item', resource_id=self.kind, delta=1, reason='buy')])

    async def test_buy_insufficient_stardust_refused_no_spend(self):
        await self.conn.execute('UPDATE profiles SET stardust=499')
        before = await self.snapshot()
        self.assertEqual(await self.buy(), {'status': 'insufficient'})
        self.assertEqual(await self.snapshot(), before)

    async def test_buy_full_bag_refused_no_spend_no_conversion(self):
        await self.conn.execute("UPDATE inventory SET quantity=250 WHERE item_id='poke_ball'")
        before = await self.snapshot()
        self.assertEqual(await self.buy(), {'status': 'bag_full'})
        self.assertEqual(await self.snapshot(), before)

    async def test_buy_twice_and_restart_before_reply_one_item(self):
        first = await self.buy()
        await self.conn.execute("UPDATE inventory SET quantity=249 WHERE item_id='poke_ball'")
        before = await self.snapshot()
        self.assertEqual(await self.buy(), first)
        await self.close()
        self.conn = await open_db(self.path, allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.assertEqual(await self.buy('unknown', content={'evolution_items': []}), first)
        self.assertEqual(await self.snapshot(), before)

    async def test_buy_unknown_kind_refused(self):
        before = await self.snapshot()
        for kind in ('unknown', 'star_piece', 'evolution_item', 'world_legendary_ticket'):
            self.assertEqual(await self.buy(kind), {'status': 'refused'})
        self.assertEqual(await self.snapshot(), before)

    async def test_convert_evolution_kind_100_star_piece_50_ticket_refused(self):
        self.assertEqual(items.rate_for(self.kind, self.content), 100)
        self.assertIsNone(items.rate_for(self.kind, None))
        for index, (item, rate) in enumerate(((self.kind, 100), ('star_piece', 50))):
            await self.conn.execute('INSERT INTO inventory VALUES (?,?,2)', ('p', item))
            session = {**self.session, 'revision': index}
            result = await self.writer.run(lambda conn: items.convert(conn, session, item, 2, self.content))
            self.assertEqual(result, {'item': item, 'quantity': 2, 'stardust': rate * 2})
        before = await self.snapshot()
        result = await self.writer.run(lambda conn: items.convert(
            conn, {**self.session, 'revision': 2}, 'world_legendary_ticket', 1, self.content))
        self.assertEqual(result, {'status': 'refused'})
        self.assertEqual(await self.snapshot(), before)

    async def test_excluded_refused_inside_transaction(self):
        await self.buy()
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        before = await self.snapshot()
        self.assertEqual(await self.buy(), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_other_user_cannot_buy(self):
        await self.buy()
        before = await self.snapshot()
        for change in ({'user_id': '999'}, {'guild_id': '999'}, {'profile_id': 'foreign'}, {'session_id': 'missing'}):
            self.assertEqual(await self.buy(session={**self.session, **change}), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)

    async def test_buy_requires_writer_and_rolls_back_on_ledger_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await items.buy_evolution_item(self.conn, self.session, self.kind, 1000, self.content)
        before = await self.snapshot()
        await self.conn.execute("CREATE TRIGGER fail_buy BEFORE INSERT ON resource_ledger "
                                "BEGIN SELECT RAISE(ABORT,'buy ledger unavailable'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'buy ledger unavailable'):
            await self.buy()
        self.assertEqual(await self.snapshot(), before)


class EvolutionItemScreenTests(unittest.IsolatedAsyncioTestCase):
    close = conversion_tests.ConversionTests.close
    rows = conversion_tests.ConversionTests.rows
    current = conversion_tests.ConversionTests.current
    snapshot = conversion_tests.ConversionTests.snapshot
    interaction = conversion_tests.ConversionTests.interaction
    click = conversion_tests.ConversionTests.click
    screen = conversion_tests.ConversionTests.screen
    buttons = conversion_tests.ConversionTests.buttons
    options = conversion_tests.ConversionTests.options
    preview = conversion_tests.ConversionTests.preview

    async def asyncSetUp(self):
        await conversion_tests.ConversionTests.asyncSetUp(self)
        from pokewalker.bot.client import load_content
        self.content = load_content(Path('tests/fixtures/bag_kinds/content/artifact/content.json'))
        self.bot.content = self.content
        self.kinds = self.content['evolution_items']
        self.assertEqual(len(self.kinds), 50)
        await self.conn.execute('UPDATE profiles SET stardust=500')

    async def hold_kinds(self):
        await self.conn.executemany('INSERT INTO inventory VALUES (?,?,1)',
                                    [('p', kind['id']) for kind in self.kinds])

    async def test_bag_lists_kinds_by_english_name(self):
        await self.hold_kinds()
        text = (await self.screen('bag'))['embed'].description
        self.assertIn('Fire Stone ×1', text)
        self.assertNotIn('Fire-Stone', text)
        self.assertIn('Poké Ball ×20', text)
        self.assertIn('Buy evolution item', self.buttons(await self.screen('bag')))

    async def test_buy_picker_pages_reach_kind_beyond_first_page(self):
        first = await self.screen('buy_pick')
        self.assertEqual([option.value for option in self.options(first)], [k['id'] for k in self.kinds[:10]])
        self.assertEqual(self.options(first)[0].label, 'Fire Stone · have 0')
        self.assertTrue(self.buttons(first)['Prev'].disabled)
        await self.screen('buy_next')
        third = await self.screen('buy_next')
        self.assertEqual(json.loads((await self.current())['selection'])['offset'], 20)
        self.assertEqual([o.value for o in self.options(third)], [k['id'] for k in self.kinds[20:30]])
        selected = self.kinds[25]['id']
        await self.screen('buy_preview', [selected])
        await self.screen('buy_confirm')
        self.assertEqual(await self.rows('SELECT quantity FROM inventory WHERE item_id=?', (selected,)),
                         [{'quantity': 1}])
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 0)
        await self.screen('buy_pick')
        await self.screen('buy_next')
        back = await self.screen('buy_prev')
        self.assertEqual(self.options(back)[0].value, self.kinds[0]['id'])

    async def test_convert_picker_pages_reach_held_item_beyond_first_page(self):
        await self.hold_kinds()
        first = await self.screen('convert_pick')
        self.assertEqual(len(self.options(first)), 10)
        await self.screen('convert_next')
        third = await self.screen('convert_next')
        selected = self.options(third)[-1].value
        self.assertNotIn(selected, [o.value for o in self.options(first)])
        await self.screen('convert_qty', [selected])
        preview = await self.screen('convert_preview', ['1'])
        self.assertIn('→ 100 Stardust', preview['embed'].description)
        await self.screen('convert_confirm')
        self.assertEqual(await self.rows('SELECT quantity FROM inventory WHERE item_id=?', (selected,)),
                         [{'quantity': 0}])
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 600)
        await self.screen('convert_pick')
        await self.screen('convert_next')
        back = await self.screen('convert_prev')
        self.assertEqual(self.options(back)[0].value, 'poke_ball')

    async def test_every_select_has_at_most_25_options(self):
        await self.hold_kinds()
        rendered = [await self.screen('bag')]
        for action in ('convert', 'buy'):
            page = await self.screen('convert_pick' if action == 'convert' else 'buy_pick')
            while True:
                rendered.append(page)
                self.assertLessEqual(len(self.options(page)), 10)
                self.assertEqual({self.buttons(page)[label]._rendered_row for label in ('Prev', 'Next', 'Back')}, {0})
                if self.buttons(page)['Next'].disabled:
                    break
                page = await self.screen(f'{action}_next')
        await self.screen('convert_pick')
        rendered.extend([await self.screen('convert_qty', [self.kinds[0]['id']]),
                         await self.screen('convert_preview', ['1'])])
        await self.screen('buy_pick')
        rendered.append(await self.screen('buy_preview', [self.kinds[0]['id']]))
        await self.conn.execute("INSERT INTO inventory VALUES ('p','master_ball',1)")
        rendered.append(await self.preview('master_ball', '1'))
        rendered.append(await self.screen('convert_confirm'))
        await self.conn.execute("INSERT INTO inventory VALUES ('p','shiny_lure',1)")
        rendered.append(await self.screen('shiny_lure'))
        for screen in rendered:
            self.assertLessEqual(len(screen['view'].to_components()), 5)
            for component in screen['view'].children:
                if hasattr(component, 'options'):
                    self.assertLessEqual(len(component.options), 25)

    async def test_value_not_on_current_page_refused(self):
        await self.hold_kinds()
        for pick, next_action, select in (('buy_pick', 'buy_next', 'buy_preview'),
                                           ('convert_pick', 'convert_next', 'convert_qty')):
            await self.screen(pick)
            for values in ([self.kinds[25]['id']], [], [self.kinds[0]['id'], self.kinds[1]['id']]):
                before = await self.snapshot()
                interaction = await self.click(await self.current(), select, values)
                interaction.followup.send.assert_awaited_once()
                interaction.edit_original_response.assert_not_awaited()
                self.assertEqual(await self.snapshot(), before)
            await self.screen(next_action)
            before = await self.snapshot()
            interaction = await self.click(await self.current(), select, [self.kinds[0]['id']])
            interaction.followup.send.assert_awaited_once()
            self.assertEqual(await self.snapshot(), before)

    async def test_buy_preview_then_confirm_one_item(self):
        before = await self.rows('SELECT * FROM inventory')
        interaction = await self.click(await self.current(), 'buy_confirm')
        interaction.followup.send.assert_awaited_once()
        await self.screen('buy_pick')
        rendered = await self.screen('buy_preview', ['fire-stone'])
        self.assertIn('500 Stardust → 1 × Fire Stone · have 500 Stardust', rendered['embed'].description)
        self.assertFalse(self.buttons(rendered)['Confirm'].disabled)
        self.assertEqual(await self.rows('SELECT * FROM inventory'), before)
        self.assertEqual(await self.rows('SELECT * FROM action_receipts'), [])
        session = await self.current()
        foreign = await self.click(session, 'buy_confirm', user=999)
        foreign.followup.send.assert_awaited_once()
        rendered = await self.screen('buy_confirm')
        self.assertIn('500 Stardust → 1 × Fire Stone', rendered['embed'].description)
        self.assertEqual(await self.rows("SELECT quantity FROM inventory WHERE item_id='fire-stone'"), [{'quantity': 1}])
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 0)
        retry = await self.click(session, 'buy_confirm')
        retry.followup.send.assert_not_awaited()
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='buy'")), 1)

    async def test_buy_confirm_disabled_when_unaffordable(self):
        await self.conn.execute('UPDATE profiles SET stardust=499')
        await self.screen('buy_pick')
        rendered = await self.screen('buy_preview', ['fire-stone'])
        self.assertTrue(self.buttons(rendered)['Confirm'].disabled)
        before = await self.snapshot()
        interaction = await self.click(await self.current(), 'buy_confirm')
        self.assertIn('Stardust', interaction.followup.send.await_args.args[0])
        self.assertIn('Nothing was spent', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_buy_full_bag_refusal_text_no_spend(self):
        await self.screen('buy_pick')
        await self.screen('buy_preview', ['fire-stone'])
        await self.conn.execute("UPDATE inventory SET quantity=250 WHERE item_id='poke_ball'")
        before = await self.snapshot()
        interaction = await self.click(await self.current(), 'buy_confirm')
        self.assertIn('Bag is full', interaction.followup.send.await_args.args[0])
        self.assertIn('Nothing was spent', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_rare_conversion_still_needs_second_confirmation(self):
        for item in (item for item in items.RARE if items.rate_for(item, self.content) is not None):
            await self.conn.execute('INSERT INTO inventory VALUES (?,?,1)', ('p', item))
            await self.preview(item, '1')
            before = await self.rows('SELECT * FROM inventory')
            rendered = await self.screen('convert_confirm')
            self.assertIn(item.replace('_', ' ').title(), rendered['embed'].description)
            self.assertEqual(await self.rows('SELECT * FROM inventory'), before)
            self.assertEqual(self.buttons(rendered)['Confirm'].custom_id.rsplit(':', 1)[1], 'convert_confirm_rare')
            await self.screen('convert_confirm_rare')
            self.assertEqual(await self.rows('SELECT quantity FROM inventory WHERE item_id=?', (item,)), [{'quantity': 0}])

    async def test_render_functions_do_no_io(self):
        from pokewalker.bot import bag
        state = {'session': await self.current(), 'inventory': {k['id']: 1 for k in self.kinds},
                 'stardust': 500, 'units': 50, 'limit': 250, 'rates': {k['id']: 100 for k in self.kinds},
                 'content': self.content, 'buy_price': 500,
                 'selection': {'item': 'fire-stone', 'quantity': 1, 'offset': 20}}
        with patch('builtins.open', side_effect=AssertionError('file I/O')), \
             patch('pathlib.Path.open', side_effect=AssertionError('file I/O')), \
             patch('aiosqlite.Connection.execute', side_effect=AssertionError('DB I/O')), \
             patch('socket.socket', side_effect=AssertionError('network I/O')):
            for mode in ('bag', 'pick', 'qty', 'preview', 'rare', 'buy_pick', 'buy_preview', 'lure_confirm'):
                self.assertIsNotNone(bag.render({**state, 'mode': mode})['embed'])
