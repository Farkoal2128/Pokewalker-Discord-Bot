"""Owner amendment 2026-11-12: Bottlecap and Vitamin IV items, Vitamin purchase and details screens."""

import importlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from content.balance import load_table
from pokewalker.db import Writer, open_db
from pokewalker.domain.cp import appraisal, cp
from pokewalker.services import items, storage
import test_trading as trading_tests
import test_walker_router as router


CONTENT = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
MULTIPLIERS = load_table('cpm')['multipliers']
IVS = ('iv_attack', 'iv_defense', 'iv_stamina')


def service():
    try:
        return importlib.import_module('pokewalker.services.iv_items')
    except ModuleNotFoundError:
        raise AssertionError('Bottlecap and Vitamin service is absent') from None


class IVRuleTests(unittest.TestCase):
    def test_lowest_iv_ties_go_attack_then_defense_then_stamina(self):
        for ivs, index in (((5, 5, 5), 0), ((6, 3, 3), 1), ((4, 9, 4), 0), ((9, 9, 2), 2),
                           ((0, 15, 0), 0), ((15, 14, 14), 1), ((15, 15, 14), 2)):
            with self.subTest(ivs=ivs):
                self.assertEqual(service().lowest(ivs), index)

    def test_bottlecap_maxes_and_vitamin_adds_one_to_the_lowest(self):
        apply = service().apply
        self.assertEqual(apply('bottlecap', (1, 2, 3)), (15, 2, 3))
        self.assertEqual(apply('bottlecap', (7, 0, 0)), (7, 15, 0))
        self.assertEqual(apply('vitamin', (1, 2, 3)), (2, 2, 3))
        self.assertEqual(apply('vitamin', (15, 15, 14)), (15, 15, 15))
        self.assertEqual(apply('vitamin', (3, 3, 3)), (4, 3, 3))


class IVItemTests(unittest.IsolatedAsyncioTestCase):
    interaction = router.WalkerTests.interaction
    rows = router.WalkerTests.rows
    click = router.WalkerTests.click

    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(dir='.')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'iv.sqlite'
        await self.connect()
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,stardust) "
                                "VALUES ('p','123','456',0,12000)")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('q','123','789',0)")
        await self.conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) "
                                "VALUES ('abcd','123','456','p',9000)")
        await self.conn.executemany('INSERT INTO inventory VALUES (?,?,?)',
                                    [('p', 'bottlecap', 2), ('p', 'vitamin', 3), ('q', 'vitamin', 1)])
        await self.pokemon('mon', ivs=(1, 2, 3))
        await self.conn.commit()

    async def connect(self):
        self.conn = await open_db(self.path, allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.bot = SimpleNamespace(writer=self.writer, content=CONTENT)
        from pokewalker.bot.walker import Walker
        self.now = 1000
        self.walker = Walker(self.bot, clock=lambda: self.now)
        self.addAsyncCleanup(self.close, self.conn, self.writer)

    async def close(self, conn, writer):
        if getattr(conn, 'closed_by_test', False):
            return
        conn.closed_by_test = True
        await writer.close()
        await conn.close()

    async def pokemon(self, uid, pid='p', ivs=(1, 2, 3), pokemon_id=1):
        await self.conn.execute(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
            "gender,shiny,origin,content_version,caught_at) VALUES (?,?,?,20,?,?,?,'male',0,'catch','test',5)",
            (uid, pid, pokemon_id, *ivs))

    async def current(self):
        return (await self.rows())[0]

    async def mon(self, uid='mon'):
        return (await self.rows('SELECT * FROM pokemon WHERE pokemon_uid=?', (uid,)))[0]

    async def ivs(self, uid='mon'):
        pokemon = await self.mon(uid)
        return tuple(pokemon[key] for key in IVS)

    async def held(self, item, pid='p'):
        rows = await self.rows('SELECT quantity FROM inventory WHERE profile_id=? AND item_id=?', (pid, item))
        return rows[0]['quantity'] if rows else 0

    async def use(self, item, revision=0, uid='mon', session=None):
        session = session or await self.current()
        return await self.writer.run(lambda conn: service().use(
            conn, session, uid, revision, item, CONTENT, MULTIPLIERS))

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table}') for table in
                ('pokemon', 'profiles', 'inventory', 'action_receipts', 'resource_ledger')}

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

    async def details(self, uid='mon'):
        await self.screen('storage')
        return await self.screen('storage_open', [uid])

    def shown(self, pokemon):
        identity, _ = storage.identify(CONTENT, pokemon)
        base = [identity[key] for key in ('base_attack', 'base_defense', 'base_stamina')]
        ivs = [pokemon[key] for key in IVS]
        return cp(base, ivs, pokemon['level_x2'], multipliers=MULTIPLIERS), appraisal(ivs)

    async def deploy(self, uid='mon'):
        from pokewalker.services import gyms
        session, revision = await self.current(), (await self.mon(uid))['revision']
        gym = await self.writer.run(lambda conn: gyms.create(conn, '123', 'Park', 100))
        result = await self.writer.run(lambda conn: gyms.deploy(
            conn, session, gym['gym_id'], uid, revision, 1000, CONTENT))
        self.assertEqual(result['status'], 'deployed')

    # Service

    async def test_bottlecap_sets_lowest_to_15_spends_one_with_receipt_and_ledger(self):
        result = await self.use('bottlecap')
        pokemon = await self.mon()
        self.assertEqual(result, {'status': 'used', 'pokemon': pokemon})
        self.assertEqual(tuple(pokemon[key] for key in IVS), (15, 2, 3))
        self.assertEqual((pokemon['revision'], pokemon['level_x2']), (1, 20))
        self.assertEqual((await self.held('bottlecap'), await self.held('vitamin')), (1, 3))
        receipt = (await self.rows('SELECT * FROM action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']),
                         ('bottlecap:mon:0', 'bottlecap', 'p'))
        self.assertEqual(await self.rows('SELECT receipt_key,profile_id,resource,resource_id,delta,reason '
                                         'FROM resource_ledger'),
                         [{'receipt_key': 'bottlecap:mon:0', 'profile_id': 'p', 'resource': 'item',
                           'resource_id': 'bottlecap', 'delta': -1, 'reason': 'bottlecap'}])

    async def test_vitamin_adds_one_to_lowest_until_perfect_then_refuses(self):
        await self.conn.execute('UPDATE pokemon SET iv_attack=15,iv_defense=13,iv_stamina=14')
        self.assertEqual((await self.use('vitamin'))['status'], 'used')
        self.assertEqual(await self.ivs(), (15, 14, 14))
        self.assertEqual((await self.use('vitamin', 1))['status'], 'used')
        self.assertEqual((await self.use('vitamin', 2))['status'], 'used')
        self.assertEqual(await self.ivs(), (15, 15, 15))
        self.assertEqual(await self.held('vitamin'), 0)
        self.assertEqual([(r['resource_id'], r['delta'], r['reason']) for r in
                          await self.rows('SELECT * FROM resource_ledger ORDER BY receipt_key')],
                         [('vitamin', -1, 'vitamin')] * 3)
        await self.conn.execute("UPDATE inventory SET quantity=1 WHERE item_id IN ('vitamin','bottlecap')")
        before = await self.snapshot()
        for item in ('vitamin', 'bottlecap'):
            with self.subTest(item=item):
                self.assertEqual((await self.use(item, 3))['status'], 'perfect')
        self.assertEqual(await self.snapshot(), before)

    async def test_double_use_and_restart_replay_spend_once(self):
        first = await self.use('vitamin')
        self.assertEqual(await self.use('vitamin'), first)
        await self.close(self.conn, self.writer)
        await self.connect()
        self.assertEqual(await self.use('vitamin'), first)
        self.assertEqual(await self.held('vitamin'), 2)
        self.assertEqual(await self.ivs(), (2, 2, 3))
        self.assertEqual(len(await self.rows('SELECT * FROM resource_ledger')), 1)
        self.assertEqual((await self.use('bottlecap'))['status'], 'stale')
        self.assertEqual(await self.held('bottlecap'), 2)

    async def test_refusals_write_nothing(self):
        await self.pokemon('foreign', pid='q')
        await self.pokemon('sent')
        await self.conn.execute("UPDATE pokemon SET state='sent' WHERE pokemon_uid='sent'")
        session = await self.current()
        before = await self.snapshot()
        for label, kwargs, status in (
                ('unknown item', {'item': 'rare_candy'}, 'refused'),
                ('stale revision', {'revision': 4}, 'stale'),
                ('foreign', {'uid': 'foreign'}, 'stale'),
                ('sent', {'uid': 'sent'}, 'stale'),
                ('missing', {'uid': 'nothing'}, 'stale'),
                ('stale session', {'session': {**session, 'profile_id': 'q'}}, 'stale')):
            with self.subTest(label):
                kwargs = {'item': 'bottlecap', **kwargs}
                self.assertEqual((await self.use(kwargs.pop('item'), **kwargs))['status'], status)
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute("DELETE FROM inventory WHERE item_id='bottlecap'")
        before = await self.snapshot()
        self.assertEqual((await self.use('bottlecap'))['status'], 'missing')
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        before = await self.snapshot()
        self.assertEqual((await self.use('vitamin'))['status'], 'excluded')
        self.assertEqual(await self.snapshot(), before)

    async def test_deployed_pokemon_refused_without_spending(self):
        await self.deploy()
        before = await self.snapshot()
        for item in ('bottlecap', 'vitamin'):
            with self.subTest(item=item):
                self.assertEqual((await self.use(item, 1))['status'], 'deployed')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.rows('SELECT * FROM action_receipts WHERE action IN (?,?)',
                                         ('bottlecap', 'vitamin')), [])

    async def test_quote_and_every_view_reflect_new_cp_and_stars(self):
        await self.conn.execute('UPDATE pokemon SET iv_attack=8,iv_defense=7,iv_stamina=7')
        before = await self.mon()
        quote = await service().quote(self.conn, 'p', 'mon', 'bottlecap', CONTENT, MULTIPLIERS)
        changed = {**before, 'iv_defense': 15}
        self.assertEqual((quote['cp_before'], quote['stars_before']), self.shown(before))
        self.assertEqual((quote['cp_after'], quote['stars_after']), self.shown(changed))
        self.assertEqual((quote['stars_before'], quote['stars_after']), (0, 2))
        self.assertGreater(quote['cp_after'], quote['cp_before'])
        self.assertEqual((quote['have'], quote['perfect'], quote['deployed']), (2, False, False))
        self.assertIsNone(await service().quote(self.conn, 'q', 'mon', 'bottlecap', CONTENT, MULTIPLIERS))
        await self.use('bottlecap')
        after = await self.mon()
        self.assertEqual(self.shown(after), (quote['cp_after'], quote['stars_after']))
        self.assertEqual(storage.stats(CONTENT, after, MULTIPLIERS)['cp'], quote['cp_after'])
        trading = importlib.import_module('pokewalker.services.trading')
        self.assertEqual(trading._offer(CONTENT, after, MULTIPLIERS)['cp'], quote['cp_after'])
        rendered = await self.details()
        self.assertIn(f"CP {quote['cp_after']} ·", rendered['embed'].description)
        self.assertIn(f"Appraisal: {quote['stars_after']} stars", rendered['embed'].description)

    # Details screen

    async def test_details_buttons_disabled_without_item_when_perfect_or_deployed(self):
        buttons = self.buttons(await self.details())
        for label, action in (('Use Bottlecap', 'iv_bottlecap'), ('Use Vitamin', 'iv_vitamin')):
            self.assertFalse(buttons[label].disabled, label)
            self.assertTrue(buttons[label].custom_id.endswith(':' + action))
            self.assertEqual(buttons[label]._rendered_row, 2)
        view = (await self.details())['view']
        self.assertLessEqual(len(view.children), 25)
        self.assertTrue(all(item._rendered_row in range(5) for item in view.children))
        await self.conn.execute("DELETE FROM inventory WHERE item_id='vitamin'")
        buttons = self.buttons(await self.details())
        self.assertEqual((buttons['Use Bottlecap'].disabled, buttons['Use Vitamin'].disabled), (False, True))
        await self.conn.execute('UPDATE pokemon SET iv_attack=15,iv_defense=15,iv_stamina=15')
        await self.conn.execute("INSERT INTO inventory VALUES ('p','vitamin',1)")
        buttons = self.buttons(await self.details())
        self.assertTrue(buttons['Use Bottlecap'].disabled and buttons['Use Vitamin'].disabled)
        await self.conn.execute('UPDATE pokemon SET iv_attack=1')
        await self.deploy()
        buttons = self.buttons(await self.details())
        self.assertTrue(buttons['Use Bottlecap'].disabled and buttons['Use Vitamin'].disabled)

    async def test_preview_then_confirm_returns_updated_details(self):
        await self.details()
        before = await self.snapshot()
        quote = await service().quote(self.conn, 'p', 'mon', 'bottlecap', CONTENT, MULTIPLIERS)
        rendered = await self.screen('iv_bottlecap')
        self.assertEqual(rendered['embed'].title, 'Use Bottlecap')
        self.assertEqual(rendered['embed'].description,
                         f"CP {quote['cp_before']} → {quote['cp_after']} · Appraisal "
                         f"{quote['stars_before']} → {quote['stars_after']} stars · uses 1 Bottlecap (have 2)")
        self.assertNotIn('level', rendered['embed'].description.lower())
        buttons = self.buttons(rendered)
        self.assertEqual(set(buttons), {'Confirm', 'Back'})
        self.assertTrue(buttons['Confirm'].custom_id.endswith(':iv_bottlecap_confirm'))
        self.assertTrue(buttons['Back'].custom_id.endswith(':storage_detail'))
        self.assertEqual(await self.snapshot(), before)
        rendered = await self.screen('iv_bottlecap_confirm')
        self.assertEqual(rendered['embed'].title, 'Pokémon details')
        self.assertIn(f"CP {quote['cp_after']} ·", rendered['embed'].description)
        self.assertIn(f"Appraisal: {quote['stars_after']} stars", rendered['embed'].description)
        self.assertEqual(await self.ivs(), (15, 2, 3))
        self.assertEqual(await self.held('bottlecap'), 1)
        selection = json.loads((await self.current())['selection'])
        self.assertEqual(selection['pokemon_revision'], 1)
        self.assertNotIn('iv_item', selection)

    async def test_vitamin_preview_back_and_confirm_without_preview(self):
        await self.details()
        rendered = await self.screen('iv_vitamin')
        self.assertEqual(rendered['embed'].title, 'Use Vitamin')
        self.assertTrue(rendered['embed'].description.endswith('· uses 1 Vitamin (have 3)'))
        before = await self.snapshot()
        self.assertEqual((await self.screen('storage_detail'))['embed'].title, 'Pokémon details')
        self.assertEqual(await self.refusal('iv_vitamin_confirm'), 'Preview the Vitamin before confirming.')
        await self.screen('iv_bottlecap')
        self.assertEqual(await self.refusal('iv_vitamin_confirm'), 'Preview the Vitamin before confirming.')
        self.assertEqual(await self.snapshot(), before)
        rendered = await self.screen('iv_bottlecap_confirm')
        self.assertEqual(rendered['embed'].title, 'Pokémon details')

    async def test_screen_refusals_spend_nothing(self):
        await self.details()
        await self.screen('iv_vitamin')
        await self.conn.execute("UPDATE inventory SET quantity=0 WHERE item_id='vitamin'")
        before = await self.snapshot()
        self.assertEqual(await self.refusal('iv_vitamin_confirm'), 'You have no Vitamin. Nothing was used.')
        self.assertEqual(await self.refusal('iv_vitamin'), 'You have no Vitamin. Nothing was used.')
        await self.screen('storage_detail')
        await self.screen('iv_bottlecap')
        await self.conn.execute('UPDATE pokemon SET iv_attack=15,iv_defense=15,iv_stamina=15')
        self.assertEqual(await self.refusal('iv_bottlecap_confirm'),
                         'Its IVs are already perfect. No Bottlecap was used.')
        self.assertEqual(await self.refusal('iv_bottlecap'), 'Its IVs are already perfect. No Bottlecap was used.')
        await self.conn.execute('UPDATE pokemon SET iv_attack=1,revision=revision+1')
        self.assertIn('reopen /walker', await self.refusal('iv_bottlecap'))
        self.assertEqual(await self.snapshot() | {'pokemon': None}, before | {'pokemon': None})
        await self.details()
        await self.screen('iv_bottlecap')
        await self.deploy()
        self.assertEqual(await self.refusal('iv_bottlecap_confirm'), 'Recall it from the gym first')
        await self.details()
        self.assertEqual(await self.refusal('iv_bottlecap'), 'Recall it from the gym first')
        self.assertEqual(await self.held('bottlecap'), 2)

    async def test_render_preview_does_no_io(self):
        module = importlib.import_module('pokewalker.bot.iv_items')
        state = {'session': {'session_id': 'abcd', 'revision': 3}, 'item': 'vitamin',
                 'quote': {'cp_before': 100, 'cp_after': 104, 'stars_before': 0, 'stars_after': 1, 'have': 1}}
        rendered = module.render_preview(state)
        self.assertEqual(rendered['embed'].description,
                         'CP 100 → 104 · Appraisal 0 → 1 stars · uses 1 Vitamin (have 1)')

    # Buying Vitamins

    async def buy(self, session=None):
        session = session or await self.current()
        return await self.writer.run(lambda conn: items.buy_vitamin(conn, session, self.now))

    async def test_buy_vitamin_debits_5000_once_with_ledger(self):
        session = {**await self.current(), 'revision': 7}
        result = await self.buy(session)
        self.assertEqual(result, {'item': 'vitamin', 'quantity': 1, 'stardust': 5000})
        self.assertEqual(await self.buy(session), result)
        self.assertEqual((await self.rows("SELECT stardust FROM profiles WHERE profile_id='p'"))[0]['stardust'], 7000)
        self.assertEqual(await self.held('vitamin'), 4)
        receipt = (await self.rows('SELECT * FROM action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action']), ('buy:abcd:7', 'buy'))
        self.assertEqual([(r['resource'], r['resource_id'], r['delta'], r['reason']) for r in
                          await self.rows('SELECT * FROM resource_ledger ORDER BY line_key')],
                         [('stardust', None, -5000, 'buy'), ('item', 'vitamin', 1, 'buy')])

    async def test_buy_vitamin_refuses_unaffordable_full_bag_and_stale(self):
        await self.conn.execute("UPDATE profiles SET stardust=4999 WHERE profile_id='p'")
        before = await self.snapshot()
        self.assertEqual(await self.buy(), {'status': 'insufficient'})
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute("UPDATE profiles SET stardust=5000 WHERE profile_id='p'")
        await self.conn.execute("UPDATE inventory SET quantity=247 WHERE profile_id='p' AND item_id='bottlecap'")
        before = await self.snapshot()
        self.assertEqual(await self.buy(), {'status': 'bag_full'})
        self.assertEqual(await self.buy({**await self.current(), 'profile_id': 'q'}), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)

    async def test_bag_buy_vitamin_preview_confirm_and_disabled_when_unaffordable(self):
        bag = await self.screen('bag')
        self.assertFalse(self.buttons(bag)['Buy Vitamin'].disabled)
        self.assertTrue(self.buttons(bag)['Buy Vitamin'].custom_id.endswith(':vitamin_buy_preview'))
        self.assertEqual(await self.refusal('vitamin_buy_confirm'), 'Preview the purchase before confirming.')
        rendered = await self.screen('vitamin_buy_preview')
        self.assertEqual(rendered['embed'].description, '5,000 Stardust → 1 × Vitamin · have 12,000 Stardust')
        self.assertEqual(set(self.buttons(rendered)), {'Confirm', 'Back'})
        self.assertFalse(self.buttons(rendered)['Confirm'].disabled)
        self.assertTrue(self.buttons(rendered)['Back'].custom_id.endswith(':bag'))
        rendered = await self.screen('vitamin_buy_confirm')
        self.assertEqual(rendered['embed'].title, 'Bag')
        self.assertIn('Vitamin ×4', rendered['embed'].description)
        self.assertTrue(rendered['embed'].description.endswith('5,000 Stardust → 1 × Vitamin'))
        rendered = await self.screen('vitamin_buy_preview')
        self.assertEqual(rendered['embed'].description, '5,000 Stardust → 1 × Vitamin · have 7,000 Stardust')
        await self.conn.execute("UPDATE profiles SET stardust=10 WHERE profile_id='p'")
        self.assertEqual(await self.refusal('vitamin_buy_confirm'), 'Not enough Stardust. Nothing was spent.')
        rendered = await self.screen('vitamin_buy_preview')
        self.assertTrue(self.buttons(rendered)['Confirm'].disabled)
        await self.conn.execute("UPDATE profiles SET stardust=9000 WHERE profile_id='p'")
        await self.conn.execute("UPDATE inventory SET quantity=246 WHERE profile_id='p' AND item_id='bottlecap'")
        self.assertEqual(await self.refusal('vitamin_buy_confirm'), 'Bag is full. Nothing was spent.')
        self.assertEqual(await self.held('vitamin'), 4)


class IVItemTradeTests(unittest.IsolatedAsyncioTestCase):
    """A Bottlecap or Vitamin used on an offered Pokemon makes the offer `changed` at execution."""

    asyncSetUp = trading_tests.TradingTests.asyncSetUp
    scalar = trading_tests.TradingTests.scalar
    profile = trading_tests.TradingTests.profile
    svc = trading_tests.TradingTests.svc
    session = trading_tests.TradingTests.session
    pokemon = trading_tests.TradingTests.pokemon
    rows = trading_tests.TradingTests.rows
    open = trading_tests.TradingTests.open
    offer = trading_tests.TradingTests.offer
    confirm = trading_tests.TradingTests.confirm
    ready = trading_tests.TradingTests.ready
    owners = trading_tests.TradingTests.owners
    sides = trading_tests.TradingTests.sides
    trade = trading_tests.TradingTests.trade
    invalid = trading_tests.TradingTests.invalid
    last_trade = trading_tests.TradingTests.last_trade

    async def test_offered_pokemon_changed_by_item_is_refused_at_execution(self):
        for item in ('vitamin', 'bottlecap'):
            with self.subTest(item=item):
                await self.conn.execute('DELETE FROM trades')
                trade_id = await self.ready(mine='u_' + item, theirs='v_' + item)
                await self.conn.execute('INSERT OR REPLACE INTO inventory VALUES (?,?,1)', (self.ids['v'], item))
                result = await self.writer.run(lambda conn: service().use(
                    conn, self.session('v'), 'v_' + item, 0, item, trading_tests.CONTENT, MULTIPLIERS))
                self.assertEqual(result['status'], 'used')
                await self.invalid(trade_id, 1, 'changed')


if __name__ == '__main__':
    unittest.main()
