"""D61 bag conversion through the real SQLite writer and private walker router."""

import importlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from content.balance import load_table
from pokewalker.db import Writer, open_db
from pokewalker.services import items
import test_walker_router as router


class ConversionTests(unittest.IsolatedAsyncioTestCase):
    interaction = router.WalkerTests.interaction
    rows = router.WalkerTests.rows
    click = router.WalkerTests.click

    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(dir='.')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'conversion.sqlite'
        self.conn = await open_db(self.path, allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.close)
        self.bot = SimpleNamespace(writer=self.writer)
        from pokewalker.bot.walker import Walker
        self.walker = Walker(self.bot, clock=lambda: 1000)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('p','123','456',0)")
        await self.conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) "
                                "VALUES ('abcd','123','456','p',1900)")
        await self.conn.execute("INSERT INTO inventory VALUES ('p','poke_ball',20)")

    async def close(self):
        await self.writer.close()
        await self.conn.close()

    async def current(self):
        return (await self.rows())[0]

    async def screen(self, action, values=None):
        interaction = await self.click(await self.current(), action, values)
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs

    async def preview(self, item='poke_ball', quantity='5'):
        await self.screen('bag')
        rendered = await self.screen('convert_pick')
        while item not in {option.value for option in self.options(rendered)}:
            self.assertFalse(self.buttons(rendered)['Next'].disabled)
            rendered = await self.screen('convert_next')
        await self.screen('convert_qty', [item])
        return await self.screen('convert_preview', [quantity])

    async def convert(self, session=None, item='poke_ball', quantity=5):
        self.assertTrue(hasattr(items, 'convert'), 'M3.3 conversion service is absent')
        return await self.writer.run(lambda conn: items.convert(conn, session or self.session, item, quantity))

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table}') for table in
                ('profiles', 'sessions', 'inventory', 'inbox_items', 'action_receipts', 'resource_ledger')}

    def buttons(self, rendered):
        return {x.label: x for x in rendered['view'].children if hasattr(x, 'label')}

    def options(self, rendered):
        return next(x.options for x in rendered['view'].children if hasattr(x, 'options'))

    async def inbox_content(self):
        from pokewalker.bot.client import load_content
        self.bot.content = load_content(Path('tests/fixtures/bag_kinds/content/artifact/content.json'))
        self.bot.content['milestones'] = {}
        await self.conn.execute("INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) "
                                "VALUES ('p','pokedex:5','item','great_ball',5,0)")

    async def test_inbox_convert_confirm_returns_to_inbox(self):
        await self.inbox_content()
        waiting = await self.rows('SELECT * FROM inbox_items')
        for item in ('poke_ball', 'master_ball'):
            with self.subTest(item=item):
                if item in items.RARE:
                    await self.conn.execute('INSERT INTO inventory VALUES (?,?,1)', ('p', item))
                await self.screen('inbox_convert')
                await self.screen('convert_qty', [item])
                await self.screen('convert_preview', ['1' if item in items.RARE else '5'])
                rendered = await self.screen('convert_confirm')
                if item in items.RARE:
                    self.assertTrue(self.buttons(rendered)['Back'].custom_id.endswith(':inbox'))
                    rendered = await self.screen('convert_confirm_rare')
                self.assertEqual(rendered['embed'].title, 'Reward inbox')
                self.assertEqual(await self.rows('SELECT * FROM inbox_items'), waiting)
                self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='claim'"), [])
                self.assertEqual(json.loads((await self.current())['selection']), {})
        self.assertEqual(await items.bag_units(self.conn, 'p'), 15)
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'],
                         10 + load_table('conversion_rates')['stardust_per_unit']['master_ball'])

    async def test_inbox_back_cancels_conversion_current_revision_confirm(self):
        await self.inbox_content()
        await self.conn.execute("INSERT INTO inventory VALUES ('p','master_ball',1)")
        for item in ('poke_ball', 'master_ball'):
            with self.subTest(item=item):
                await self.screen('inbox_convert')
                await self.screen('convert_qty', [item])
                rendered = await self.screen('convert_preview', ['1' if item in items.RARE else '5'])
                action = 'convert_confirm'
                if item in items.RARE:
                    rendered = await self.screen(action)
                    action = 'convert_confirm_rare'
                back = self.buttons(rendered)['Back'].custom_id.rsplit(':', 1)[1]
                self.assertEqual((await self.screen(back))['embed'].title, 'Reward inbox')
                before = await self.snapshot()
                await self.click(await self.current(), action)
                after = await self.snapshot()
                for table in before.keys() - {'sessions'}:
                    self.assertEqual(after[table], before[table])

    async def test_inbox_conversion_refusal_keeps_return_and_text(self):
        await self.inbox_content()
        await self.screen('inbox_convert')
        await self.screen('convert_qty', ['poke_ball'])
        await self.screen('convert_preview', ['5'])
        await self.conn.execute("UPDATE inventory SET quantity=4 WHERE item_id='poke_ball'")
        before = await self.snapshot()
        refused = await self.click(await self.current(), 'convert_confirm')
        refused.edit_original_response.assert_not_awaited()
        self.assertEqual(refused.followup.send.await_args.args[0], 'Items changed. Reopen Bag to preview again.')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(json.loads((await self.current())['selection'])['back'], 'inbox')
        self.assertEqual((await self.screen('inbox'))['embed'].title, 'Reward inbox')

    async def test_inbox_flows_back_returns_to_inbox_nothing_spent(self):
        await self.inbox_content()
        await self.conn.execute('UPDATE profiles SET stardust=15000')
        await self.conn.executemany('INSERT INTO inventory VALUES (?,?,1)',
                                    [('p', item) for item in load_table('conversion_rates')['stardust_per_unit']
                                     if item not in ('poke_ball', 'world_legendary_ticket')])
        phases = [('inbox_expand_bag',), ('inbox_convert',),
                  ('inbox_convert', 'convert_next', 'convert_prev'),
                  ('inbox_convert', ('convert_qty', ['poke_ball'])),
                  ('inbox_convert', ('convert_qty', ['poke_ball']), ('convert_preview', ['5'])),
                  ('inbox_convert', ('convert_qty', ['master_ball']),
                   ('convert_preview', ['1']), 'convert_confirm')]
        for actions in phases:
            with self.subTest(actions=actions):
                before = await self.snapshot()
                for action in actions:
                    rendered = await self.screen(*action) if isinstance(action, tuple) else await self.screen(action)
                    self.assertTrue(self.buttons(rendered)['Back'].custom_id.endswith(':inbox'))
                    self.assertEqual(json.loads((await self.current())['selection'])['back'], 'inbox')
                rendered = await self.screen('inbox')
                self.assertEqual(rendered['embed'].title, 'Reward inbox')
                self.assertEqual(json.loads((await self.current())['selection']), {})
                after = await self.snapshot()
                for table in before.keys() - {'sessions'}:
                    self.assertEqual(after[table], before[table])

    async def test_bag_limit_comes_from_profile(self):
        await self.conn.execute('UPDATE profiles SET bag_limit=300')
        self.assertIn('20/300', (await self.screen('bag'))['embed'].description)

    async def test_bag_shows_units_rare_pockets_stardust_and_convert_button(self):
        await self.conn.execute("INSERT INTO inventory VALUES ('p','master_ball',1)")
        await self.conn.execute("UPDATE profiles SET stardust=123")
        rendered = await self.screen('bag')
        text = rendered['embed'].description
        for expected in ('20/250', 'Master Ball: 1/1', 'Shiny Lure: 0/1', '123 Stardust', 'Poké Ball ×20'):
            self.assertIn(expected, text)
        self.assertFalse(self.buttons(rendered)['Convert'].disabled)
        self.assertTrue(self.buttons(rendered)['Shiny Lure'].disabled)
        self.assertEqual(self.buttons(rendered)['Back'].custom_id.rsplit(':', 1)[1], 'home')
        self.assertIn('bag', self.walker.handlers)

    async def test_preview_total_uses_conversion_rates_table(self):
        for item, rate in load_table('conversion_rates')['stardust_per_unit'].items():
            quantity = 1 if item in items.RARE else 5
            await self.conn.execute('INSERT OR REPLACE INTO inventory VALUES (?,?,?)', ('p', item, quantity))
            rendered = await self.preview(item, str(quantity))
            self.assertIn(f'→ {rate * quantity} Stardust', rendered['embed'].description)
            self.assertIn("cannot be undone", rendered['embed'].description)
            self.assertIn('Confirm', self.buttons(rendered))

    async def test_confirm_converts_in_one_transaction_with_receipt_and_ledger(self):
        await self.preview()
        session = await self.current()
        rendered = await self.screen('convert_confirm')
        self.assertIn('5 × Poké Ball → 10 Stardust', rendered['embed'].description)
        receipt = (await self.rows("SELECT * FROM action_receipts WHERE action='convert'"))[0]
        self.assertEqual(receipt['key'], f"convert:abcd:{session['revision'] + 1}")
        self.assertEqual((receipt['profile_id'], json.loads(receipt['result'])),
                         ('p', {'item': 'poke_ball', 'quantity': 5, 'stardust': 10}))
        lines = await self.rows("SELECT * FROM resource_ledger WHERE reason='convert' ORDER BY line_key")
        self.assertEqual([(r['resource'], r['resource_id'], r['delta']) for r in lines],
                         [('item', 'poke_ball', -5), ('stardust', None, 10)])
        self.assertEqual(await items.bag_units(self.conn, 'p'), 15)

    async def test_same_conversion_confirmed_twice_with_restart_is_15_balls_plus_10_stardust(self):
        await self.preview()
        before = await self.current()
        broken = self.interaction()
        broken.edit_original_response.side_effect = RuntimeError('lost reply')
        custom_id = f"pw:v1:abcd:{before['revision']}:convert_confirm"
        with self.assertRaisesRegex(RuntimeError, 'lost reply'):
            await self.walker.route(broken, custom_id)
        saved = await self.snapshot()
        await self.close()
        self.conn = await open_db(self.path, allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.bot.writer = self.writer
        from pokewalker.bot.walker import Walker
        self.walker = Walker(self.bot, clock=lambda: 1000)
        retry = self.interaction()
        await self.walker.route(retry, custom_id)
        retry.followup.send.assert_not_awaited()
        replay_session = {**before, 'revision': before['revision'] + 1}
        self.assertEqual(await self.convert(replay_session), {'item': 'poke_ball', 'quantity': 5, 'stardust': 10})
        self.assertEqual(await self.snapshot(), saved)
        self.assertEqual(await items.bag_units(self.conn, 'p'), 15)
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 10)

    async def test_rare_item_needs_second_confirmation_naming_it(self):
        for item, name in (('master_ball', 'Master Ball'), ('shiny_lure', 'Shiny Lure')):
            await self.conn.execute('INSERT OR REPLACE INTO inventory VALUES (?,?,1)', ('p', item))
            await self.preview(item, '1')
            before = await self.rows('SELECT * FROM inventory')
            rendered = await self.screen('convert_confirm')
            self.assertIn(name, rendered['embed'].description)
            self.assertEqual(await self.rows('SELECT * FROM inventory'), before)
            self.assertEqual(self.buttons(rendered)['Confirm'].custom_id.rsplit(':', 1)[1], 'convert_confirm_rare')
            await self.screen('convert_confirm_rare')
            self.assertEqual((await self.rows('SELECT quantity FROM inventory WHERE item_id=?', (item,)))[0]['quantity'], 0)

    async def test_quantity_above_held_refused_no_change(self):
        self.session = await self.current()
        before = await self.snapshot()
        for qty in (21, 0, -1, True, 1.5, '5'):
            result = await self.convert(quantity=qty)
            self.assertIn(result['status'], ('changed', 'refused'))
            self.assertEqual(await self.snapshot(), before)
        await self.preview()
        await self.conn.execute("UPDATE inventory SET quantity=4")
        self.session = await self.current()
        before = await self.snapshot()
        self.assertEqual(await self.convert(), {'status': 'changed'})
        self.assertEqual(await self.snapshot(), before)

    async def test_item_without_rate_not_offered_and_refused(self):
        for item in ('world_legendary_ticket', 'unknown'):
            await self.conn.execute('INSERT INTO inventory VALUES (?,?,1)', ('p', item))
        rendered = await self.screen('convert_pick')
        self.assertEqual([o.value for o in self.options(rendered)], ['poke_ball'])
        self.session = await self.current()
        before = await self.snapshot()
        for item in ('world_legendary_ticket', 'unknown'):
            self.assertEqual(await self.convert(item=item, quantity=1), {'status': 'refused'})
        self.assertEqual(await self.snapshot(), before)

    async def test_inbox_items_not_convertible_until_claimed(self):
        await self.conn.execute("INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) "
                                "VALUES ('p','award','item','ultra_ball',5,0)")
        self.session = await self.current()
        before = await self.snapshot()
        self.assertEqual(await self.convert(item='ultra_ball', quantity=1), {'status': 'changed'})
        self.assertEqual(await self.snapshot(), before)
        from pokewalker.services.milestones import claim
        await self.writer.run(lambda conn: claim(conn, self.session, 1000))
        self.assertEqual((await self.convert(item='ultra_ball', quantity=1))['stardust'], 10)

    async def test_other_user_cannot_confirm(self):
        await self.preview()
        session = await self.current()
        before = await self.snapshot()
        interaction = await self.click(session, 'convert_confirm', user=999)
        self.assertIn('not yours', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.convert({**session, 'user_id': '999'}), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)

    async def test_excluded_refused_inside_transaction(self):
        self.session = await self.current()
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        before = await self.snapshot()
        self.assertEqual(await self.convert(), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_render_functions_do_no_io(self):
        try:
            module = importlib.import_module('pokewalker.bot.bag')
        except ModuleNotFoundError:
            self.fail('M3.3 detached bag renderer is absent')
        state = {'session': await self.current(), 'inventory': {'poke_ball': 20},
                 'stardust': 0, 'units': 20, 'limit': 250, 'rates': {'poke_ball': 2},
                 'selection': {'item': 'poke_ball', 'quantity': 5}}
        with patch('builtins.open', side_effect=AssertionError('file I/O')), \
             patch('aiosqlite.Connection.execute', side_effect=AssertionError('DB I/O')), \
             patch('socket.socket', side_effect=AssertionError('network I/O')):
            for mode in ('bag', 'pick', 'qty', 'preview', 'rare'):
                self.assertIsNotNone(module.render({**state, 'mode': mode})['embed'])

    async def test_fixed_quantities_capped_and_rare_only_one(self):
        rendered = await self.screen('convert_qty', ['poke_ball'])
        self.assertEqual([o.value for o in self.options(rendered)], ['1', '5', '10', '20'])
        self.assertEqual(self.options(rendered)[-1].label, 'All (20)')
        await self.conn.execute("INSERT INTO inventory VALUES ('p','master_ball',1)")
        rendered = await self.screen('convert_qty', ['master_ball'])
        self.assertEqual([o.value for o in self.options(rendered)], ['1'])

    async def test_skipped_phases_and_forged_quantity_refused(self):
        for action, values in (('convert_confirm', None), ('convert_confirm_rare', None),
                               ('convert_preview', ['5'])):
            before = await self.snapshot()
            interaction = await self.click(await self.current(), action, values)
            interaction.followup.send.assert_awaited_once()
            self.assertEqual(await self.snapshot(), before)
        await self.screen('convert_qty', ['poke_ball'])
        before = await self.snapshot()
        interaction = await self.click(await self.current(), 'convert_preview', ['3'])
        interaction.followup.send.assert_awaited_once()
        self.assertEqual(await self.snapshot(), before)

    async def test_ledger_failure_rolls_back_debit_credit_receipt_and_session(self):
        await self.preview()
        before = await self.snapshot()
        await self.conn.execute("CREATE TRIGGER fail_conversion BEFORE INSERT ON resource_ledger "
                                "BEGIN SELECT RAISE(ABORT,'ledger failed'); END")
        with self.assertRaisesRegex(Exception, 'ledger failed'):
            await self.click(await self.current(), 'convert_confirm')
        self.assertEqual(await self.snapshot(), before)

    async def test_service_requires_writer_and_durable_owner_even_for_replay(self):
        session = await self.current()
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await items.convert(self.conn, session, 'poke_ball', 5)
        await self.convert(session)
        before = await self.snapshot()
        for changes in ({'guild_id': '999'}, {'profile_id': 'foreign'}, {'session_id': 'missing'}):
            self.assertEqual(await self.convert({**session, **changes}), {'status': 'stale'})
            self.assertEqual(await self.snapshot(), before)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        self.assertEqual(await self.convert(session), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_empty_bag_has_no_select_and_no_enabled_conversion(self):
        await self.conn.execute('DELETE FROM inventory')
        rendered = await self.screen('bag')
        self.assertTrue(self.buttons(rendered)['Convert'].disabled)
        rendered = await self.screen('convert_pick')
        self.assertFalse(any(hasattr(x, 'options') for x in rendered['view'].children))
