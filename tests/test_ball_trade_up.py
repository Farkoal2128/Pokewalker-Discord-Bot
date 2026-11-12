"""Owner amendment 2026-11-12: Bag ball trade-up (2 Poké Balls → 1 Great Ball, 2 Great Balls → 1 Ultra Ball)."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import discord

from pokewalker.db import Writer, open_db
from pokewalker.services import items
import test_walker_router as router


CONTENT = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))


class TradeUpTests(unittest.IsolatedAsyncioTestCase):
    interaction = router.WalkerTests.interaction
    rows = router.WalkerTests.rows
    click = router.WalkerTests.click

    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(dir='.')
        self.addCleanup(self.temp.cleanup)
        self.conn = await open_db(Path(self.temp.name) / 'tradeup.sqlite', allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.close)
        self.bot = SimpleNamespace(writer=self.writer, content=CONTENT)
        from pokewalker.bot.walker import Walker
        self.walker = Walker(self.bot, clock=lambda: 1000)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('p','123','456',0)")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('q','123','789',0)")
        await self.conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) "
                                "VALUES ('abcd','123','456','p',9000)")
        await self.conn.executemany('INSERT INTO inventory VALUES (?,?,?)',
                                    [('p', 'poke_ball', 7), ('p', 'great_ball', 1), ('q', 'poke_ball', 9)])

    async def close(self):
        await self.writer.close()
        await self.conn.close()

    async def current(self):
        return (await self.rows())[0]

    async def inventory(self, pid='p'):
        return {row['item_id']: row['quantity'] for row in
                await self.rows('SELECT * FROM inventory WHERE profile_id=?', (pid,))}

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table}') for table in
                ('profiles', 'inventory', 'action_receipts', 'resource_ledger')}

    async def trade_up(self, item, outputs, session=None):
        self.assertTrue(hasattr(items, 'trade_up'), 'Ball trade-up service is absent')
        session = session or await self.current()
        return await self.writer.run(lambda conn: items.trade_up(conn, session, item, outputs))

    async def screen(self, action, values=None):
        interaction = await self.click(await self.current(), action, values)
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs

    async def refusal(self, action, values=None):
        interaction = await self.click(await self.current(), action, values)
        interaction.edit_original_response.assert_not_awaited()
        return interaction.followup.send.await_args.args[0]

    def buttons(self, rendered):
        return {x.label: x for x in rendered['view'].children if hasattr(x, 'label')}

    def select(self, rendered):
        selects = [x for x in rendered['view'].children if isinstance(x, discord.ui.Select)]
        self.assertEqual(len(selects), 1)
        return selects[0]

    # Service

    async def test_trade_up_consumes_two_per_output_atomically_with_ledger_and_receipt(self):
        session = {**await self.current(), 'revision': 5}
        result = await self.trade_up('poke_ball', 3, session)
        self.assertEqual(result, {'from': 'poke_ball', 'to': 'great_ball', 'consumed': 6, 'produced': 3})
        self.assertEqual(await self.trade_up('poke_ball', 3, session), result)
        self.assertEqual(await self.inventory(), {'poke_ball': 1, 'great_ball': 4})
        self.assertEqual(await self.inventory('q'), {'poke_ball': 9})
        receipt = (await self.rows('SELECT * FROM action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']),
                         ('tradeup:abcd:5', 'trade_up', 'p'))
        self.assertEqual([(r['resource'], r['resource_id'], r['delta'], r['reason']) for r in
                          await self.rows('SELECT * FROM resource_ledger ORDER BY line_key')],
                         [('item', 'poke_ball', -6, 'trade_up'), ('item', 'great_ball', 3, 'trade_up')])
        result = await self.trade_up('great_ball', 2, {**session, 'revision': 6})
        self.assertEqual(result, {'from': 'great_ball', 'to': 'ultra_ball', 'consumed': 4, 'produced': 2})
        self.assertEqual(await self.inventory(), {'poke_ball': 1, 'great_ball': 0, 'ultra_ball': 2})

    async def test_trade_up_refusals_change_nothing(self):
        await self.conn.execute("INSERT INTO inventory VALUES ('p','ultra_ball',4),('p','master_ball',1)")
        session = await self.current()
        before = await self.snapshot()
        for item, outputs, status in (('ultra_ball', 1, 'refused'), ('master_ball', 1, 'refused'),
                                      ('razz_berry', 1, 'refused'), ('poke_ball', 0, 'refused'),
                                      ('poke_ball', -1, 'refused'), ('poke_ball', True, 'refused'),
                                      ('poke_ball', '2', 'refused'), ('poke_ball', 4, 'insufficient'),
                                      ('great_ball', 1, 'insufficient')):
            with self.subTest(item=item, outputs=outputs):
                self.assertEqual(await self.trade_up(item, outputs), {'status': status})
        self.assertEqual(await self.trade_up('poke_ball', 1, {**session, 'profile_id': 'q'}), {'status': 'stale'})
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        self.assertEqual(await self.trade_up('poke_ball', 1), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    # Bag

    async def test_bag_trade_up_pick_quantity_preview_confirm(self):
        bag = await self.screen('bag')
        button = self.buttons(bag)['Trade up']
        self.assertFalse(button.disabled)
        self.assertTrue(button.custom_id.endswith(':tradeup_pick'))
        rendered = await self.screen('tradeup_pick')
        select = self.select(rendered)
        self.assertTrue(select.custom_id.endswith(':tradeup_qty'))
        self.assertEqual([(o.label, o.value) for o in select.options],
                         [('Poké Ball → Great Ball (2:1)', 'poke_ball')])
        self.assertTrue(self.buttons(rendered)['Back'].custom_id.endswith(':bag'))
        rendered = await self.screen('tradeup_qty', ['poke_ball'])
        select = self.select(rendered)
        self.assertTrue(select.custom_id.endswith(':tradeup_preview'))
        self.assertEqual([(o.label, o.value) for o in select.options], [('1', '1'), ('All (3)', '3')])
        before = await self.snapshot()
        rendered = await self.screen('tradeup_preview', ['3'])
        self.assertEqual(rendered['embed'].description, '6 × Poké Ball → 3 × Great Ball\nThis cannot be undone.')
        self.assertEqual(set(self.buttons(rendered)), {'Confirm', 'Back'})
        self.assertTrue(self.buttons(rendered)['Confirm'].custom_id.endswith(':tradeup_confirm'))
        self.assertTrue(self.buttons(rendered)['Back'].custom_id.endswith(':bag'))
        self.assertEqual(await self.snapshot(), before)
        rendered = await self.screen('tradeup_confirm')
        self.assertEqual(rendered['embed'].title, 'Bag')
        self.assertTrue(rendered['embed'].description.endswith('\n6 × Poké Ball → 3 × Great Ball'))
        self.assertEqual(await self.inventory(), {'poke_ball': 1, 'great_ball': 4})
        rendered = await self.screen('tradeup_pick')
        self.assertEqual([o.label for o in self.select(rendered).options], ['Great Ball → Ultra Ball (2:1)'])
        rendered = await self.screen('tradeup_qty', ['great_ball'])
        self.assertEqual([o.label for o in self.select(rendered).options], ['1', 'All (2)'])
        rendered = await self.screen('tradeup_preview', ['2'])
        self.assertTrue(rendered['embed'].description.startswith('4 × Great Ball → 2 × Ultra Ball\n'))
        await self.screen('tradeup_confirm')
        self.assertEqual(await self.inventory(), {'poke_ball': 1, 'great_ball': 0, 'ultra_ball': 2})
        bag = await self.screen('bag')
        self.assertTrue(self.buttons(bag)['Trade up'].disabled)

    async def test_quantity_choices_follow_the_convert_picker(self):
        await self.conn.execute("UPDATE inventory SET quantity=250 WHERE profile_id='p' AND item_id='poke_ball'")
        await self.screen('tradeup_pick')
        rendered = await self.screen('tradeup_qty', ['poke_ball'])
        self.assertEqual([o.label for o in self.select(rendered).options],
                         ['1', '5', '10', '25', '50', '100', 'All (125)'])

    async def test_bag_trade_up_refusals(self):
        before = await self.snapshot()
        self.assertEqual(await self.refusal('tradeup_confirm'), 'Preview the trade-up before confirming.')
        await self.screen('tradeup_pick')
        self.assertEqual(await self.refusal('tradeup_qty', ['great_ball']), 'Choose one of the displayed trade-ups.')
        self.assertEqual(await self.refusal('tradeup_qty', ['master_ball']), 'Choose one of the displayed trade-ups.')
        await self.screen('tradeup_qty', ['poke_ball'])
        self.assertEqual(await self.refusal('tradeup_preview', ['2']), 'Choose one of the displayed quantities.')
        self.assertEqual(await self.refusal('tradeup_confirm'), 'Preview the trade-up before confirming.')
        await self.screen('tradeup_preview', ['3'])
        await self.conn.execute("UPDATE inventory SET quantity=5 WHERE profile_id='p' AND item_id='poke_ball'")
        self.assertEqual(await self.refusal('tradeup_confirm'), 'Not enough balls held. Nothing was traded.')
        await self.conn.execute("UPDATE inventory SET quantity=7 WHERE profile_id='p' AND item_id='poke_ball'")
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute("UPDATE inventory SET quantity=1 WHERE profile_id='p'")
        self.assertTrue(self.buttons(await self.screen('bag'))['Trade up'].disabled)
        self.assertEqual(await self.refusal('tradeup_pick'),
                         'You need at least 2 Poké Balls or 2 Great Balls to trade up.')


if __name__ == '__main__':
    unittest.main()
