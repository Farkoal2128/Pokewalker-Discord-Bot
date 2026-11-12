"""Q3 count-model Star Piece effects and C3 migration compatibility."""

import asyncio
from contextlib import closing
import json
import random
import sqlite3
import unittest
from unittest.mock import patch

from pokewalker import db
from pokewalker.services import items
import test_db
import test_catching as catching_tests
import test_lure as lure_tests


class StarPieceTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_db.DatabaseTests.scalar

    async def asyncSetUp(self):
        await test_db.DatabaseTests.asyncSetUp(self)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('p','123','456',0)")
        await self.conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) "
                                "VALUES ('abcd','123','456','p',9000)")
        await self.conn.execute("INSERT INTO inventory VALUES ('p','star_piece',2)")
        self.session = {'session_id': 'abcd', 'profile_id': 'p', 'guild_id': '123',
                        'user_id': '456', 'revision': 0}

    async def rows(self, sql, args=()):
        return [dict(row) for row in await self.conn.execute_fetchall(sql, args)]

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table}') for table in
                ('profiles', 'inventory', 'active_effects', 'action_receipts', 'resource_ledger', 'finds')}

    async def activate(self, session=None):
        self.assertTrue(callable(getattr(items, 'activate_star_piece', None)),
                        'Star Piece activation service is absent')
        return await self.writer.run(lambda conn: items.activate_star_piece(conn, session or self.session, 1000))

    async def remaining(self):
        return await self.scalar("SELECT remaining_rewards FROM active_effects WHERE kind='star_piece'")

    async def find(self, mid='find', item='stardust', quantity=100):
        async def apply(conn):
            profile = (await self.rows("SELECT * FROM profiles WHERE profile_id='p'"))[0]
            return await items.apply_finds(conn, profile, 10000, 1000 + int(mid) * 3601,
                                           mid, random.Random(1), {'evolution_items': []})
        with patch.object(items, 'roll_find', return_value={'item': item, 'quantity': quantity}):
            return await self.writer.run(apply)

    async def test_activate_consumes_one_and_sets_10_rewards(self):
        effect = await self.activate()
        self.assertEqual(effect, (await self.rows('SELECT * FROM active_effects'))[0])
        self.assertEqual((effect['profile_id'], effect['kind'], effect['starts_at'], effect['expires_at'],
                          effect['remaining_encounters'], effect['remaining_rewards']),
                         ('p', 'star_piece', 1000, None, 0, 10))
        self.assertEqual(await items.active_star_piece(self.conn, 'p'), effect['effect_id'])
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='star_piece'"), 1)
        receipt = (await self.rows('SELECT * FROM action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']),
                         ('star_piece:abcd:0', 'star_piece', 'p'))
        self.assertEqual(json.loads(receipt['result']), effect)
        line = (await self.rows('SELECT * FROM resource_ledger'))[0]
        self.assertEqual((line['resource'], line['resource_id'], line['delta'], line['reason']),
                         ('item', 'star_piece', -1, 'star_piece_activate'))

    async def test_activate_while_active_refused_without_consuming(self):
        await self.activate()
        session = {**self.session, 'revision': 1}
        self.assertEqual(await self.activate(session), {'status': 'already_active'})
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='star_piece'"), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM active_effects'), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM resource_ledger'), 1)
        await self.conn.execute('UPDATE active_effects SET remaining_rewards=0')
        self.assertEqual(await self.activate(session), {'status': 'already_active'})
        effect = await self.activate({**self.session, 'revision': 2})
        self.assertEqual(effect['remaining_rewards'], 10)

    async def test_boost_floor_300_450_100_150_and_inactive_unchanged(self):
        await self.activate()
        for amount, expected in ((300, 450), (100, 150), (101, 151)):
            self.assertEqual(await self.writer.run(lambda conn: items.boost(conn, 'p', amount)), expected)
        self.assertEqual(await self.remaining(), 7)
        await self.conn.execute('UPDATE active_effects SET remaining_rewards=0')
        self.assertEqual(await self.writer.run(lambda conn: items.boost(conn, 'p', 101)), 101)
        self.assertEqual(await self.remaining(), 0)

    async def test_ten_stardust_finds_boosted_eleventh_not_effect_ends_at_0(self):
        await self.activate()
        for i in range(11):
            await self.find(str(i))
            self.assertEqual(await self.remaining(), max(0, 9 - i))
            self.assertEqual(await self.scalar("SELECT stardust FROM profiles WHERE profile_id='p'"),
                             min(i + 1, 10) * 150 + (100 if i == 10 else 0))
        self.assertIsNone(await items.active_star_piece(self.conn, 'p'))
        self.assertEqual([r['quantity'] for r in await self.rows('SELECT quantity FROM finds ORDER BY find_id')],
                         [150] * 10 + [100])
        self.assertEqual([r['delta'] for r in await self.rows("SELECT delta FROM resource_ledger "
                                                           "WHERE reason='find' ORDER BY rowid")],
                         [150] * 10 + [100])

    async def test_find_item_bundle_not_boosted_counter_unchanged(self):
        await self.activate()
        await self.find('0', 'poke_ball', 5)
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='poke_ball'"), 5)
        self.assertEqual(await self.remaining(), 10)
        # Overflow and duplicate conversions are excluded Stardust sources too.
        await self.conn.execute("UPDATE inventory SET quantity=250 WHERE item_id='poke_ball'")
        await self.find('1', 'poke_ball', 5)
        await self.conn.execute("INSERT INTO inventory VALUES ('p','master_ball',1)")
        await self.find('2', 'master_ball', 1)
        self.assertEqual(await self.scalar("SELECT stardust FROM profiles WHERE profile_id='p'"), 510)
        self.assertEqual(await self.remaining(), 10)

    async def test_find_replay_does_not_decrement_twice(self):
        await self.activate()
        meter = await self.find('0')
        before = await self.snapshot()
        self.assertEqual(await self.find('0'), meter)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.remaining(), 9)

    async def test_rolled_back_grant_keeps_counter(self):
        await self.activate()
        before = await self.snapshot()
        await self.conn.execute("CREATE TRIGGER fail_find BEFORE INSERT ON resource_ledger "
                                "WHEN NEW.reason='find' BEGIN SELECT RAISE(ABORT,'grant failed'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'grant failed'):
            await self.find('0')
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('DROP TRIGGER fail_find')
        await self.find('0')
        self.assertEqual(await self.remaining(), 9)

    async def test_lure_and_star_piece_coexist_both_activatable(self):
        for star_first in (True, False):
            with self.subTest(star_first=star_first):
                await self.conn.execute('DELETE FROM active_effects')
                await self.conn.execute('DELETE FROM action_receipts')
                await self.conn.execute("INSERT OR REPLACE INTO inventory VALUES ('p','shiny_lure',1)")
                if star_first:
                    star = await self.activate()
                lure = await self.writer.run(lambda conn: items.activate_lure(conn, self.session, 1000))
                if not star_first:
                    star = await self.activate()
                self.assertEqual(await items.active_lure(self.conn, 'p'), lure['effect_id'])
                self.assertEqual(await items.active_star_piece(self.conn, 'p'), star['effect_id'])
                self.assertEqual(await self.remaining(), 10)
                self.assertEqual(lure['remaining_encounters'], 10)

    async def test_double_click_and_receipt_replay_consume_once(self):
        first, second = await asyncio.gather(self.activate(), self.activate())
        self.assertEqual(first, second)
        await self.find('0')
        await self.writer.close()
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        before = await self.snapshot()
        self.assertEqual(await self.activate(), first)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.remaining(), 9)

    async def test_migration_keeps_lure_rows_and_one_active_lure_index(self):
        path = self.path.with_name('v10.sqlite')
        with closing(sqlite3.connect(path)) as old:
            for migration in sorted(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))[:10]:
                old.executescript(migration.read_text(encoding='utf-8'))
            old.executescript("PRAGMA user_version=10; INSERT INTO guilds(guild_id) VALUES ('123'); "
                              "INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('p','123','456',0);")
            for eid, remaining in (('active', 7), ('spent', 0)):
                old.execute("INSERT INTO active_effects VALUES (?, 'p','shiny_lure',1,NULL,?,?)",
                            (eid, eid, remaining))
            before = old.execute('SELECT * FROM active_effects ORDER BY effect_id').fetchall()
            old.commit()
        upgraded = await db.open_db(path)
        try:
            columns = await upgraded.execute_fetchall('PRAGMA table_info(active_effects)')
            self.assertIn('remaining_rewards', [row['name'] for row in columns])
            rows = await upgraded.execute_fetchall('SELECT * FROM active_effects ORDER BY effect_id')
            self.assertEqual([tuple(row)[:7] for row in rows], before)
            self.assertEqual([row['remaining_rewards'] for row in rows], [0, 0])
            indexes = await upgraded.execute_fetchall('PRAGMA index_list(active_effects)')
            self.assertTrue({'active_effects_profile_remaining', 'active_effects_one_active',
                             'active_effects_one_star_piece'} <= {row['name'] for row in indexes})
            with self.assertRaises(sqlite3.IntegrityError):
                await upgraded.execute("INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,receipt_key,"
                                       "remaining_encounters) VALUES ('duplicate','p','shiny_lure',2,'key',1)")
        finally:
            await upgraded.close()

    async def test_effect_in_one_guild_does_not_apply_in_another(self):
        await self.activate()
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('999')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('other','999','456',0)")
        self.assertIsNone(await items.active_star_piece(self.conn, 'other'))
        self.assertEqual(await self.writer.run(lambda conn: items.boost(conn, 'other', 100)), 100)
        self.assertEqual(await self.remaining(), 10)

    async def test_excluded_refused_inside_transaction(self):
        await self.activate()
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        before = await self.snapshot()
        self.assertEqual(await self.activate(), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_activation_owner_missing_transaction_and_rollback_guards(self):
        await self.activate()
        before = await self.snapshot()
        for changes in ({'user_id': '999'}, {'guild_id': '999'}, {'profile_id': 'other'}, {'session_id': 'absent'}):
            self.assertEqual(await self.activate({**self.session, **changes}), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await items.activate_star_piece(self.conn, self.session, 1000)
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await items.boost(self.conn, 'p', 100)
        await self.conn.execute('UPDATE active_effects SET remaining_rewards=0')
        await self.conn.execute("UPDATE inventory SET quantity=0 WHERE item_id='star_piece'")
        session = {**self.session, 'revision': 1}
        self.assertEqual(await self.activate(session), {'status': 'missing'})
        await self.conn.execute("UPDATE inventory SET quantity=1 WHERE item_id='star_piece'")
        self.assertEqual(await self.activate(session), {'status': 'missing'})
        await self.conn.execute("CREATE TRIGGER fail_activation BEFORE INSERT ON resource_ledger "
                                "BEGIN SELECT RAISE(ABORT,'activation failed'); END")
        before = await self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'activation failed'):
            await self.activate({**self.session, 'revision': 2})
        self.assertEqual(await self.snapshot(), before)

    async def test_effect_counter_constraints_uniqueness_and_cascade(self):
        await self.activate()
        for column, value in (('remaining_rewards', -1), ('remaining_rewards', 11),
                              ('remaining_rewards', 1.5), ('remaining_rewards', None),
                              ('remaining_encounters', 1), ('kind', 'unknown')):
            with self.subTest(column=column, value=value), self.assertRaises(sqlite3.IntegrityError):
                await self.conn.execute(f'UPDATE active_effects SET {column}=?', (value,))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("INSERT INTO active_effects SELECT effect_id||'-copy',profile_id,kind,starts_at,"
                                    'expires_at,receipt_key,remaining_encounters,remaining_rewards FROM active_effects')
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("UPDATE active_effects SET kind='shiny_lure'")
        await self.conn.execute("DELETE FROM profiles WHERE profile_id='p'")
        self.assertEqual(await self.rows('SELECT * FROM active_effects'), [])
        self.assertEqual(await self.rows('SELECT * FROM action_receipts'), [])


class StarPieceCatchTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = catching_tests.CatchingTests.asyncSetUp
    interaction = catching_tests.CatchingTests.interaction
    rows = catching_tests.CatchingTests.rows
    open = catching_tests.CatchingTests.open
    click = catching_tests.CatchingTests.click
    enroll = catching_tests.CatchingTests.enroll
    ready = catching_tests.CatchingTests.ready
    current = catching_tests.CatchingTests.current
    reveal = catching_tests.CatchingTests.reveal
    encounter_row = catching_tests.CatchingTests.encounter_row
    prepared = catching_tests.CatchingTests.prepared
    throw = catching_tests.CatchingTests.throw
    scalar = test_db.DatabaseTests.scalar

    async def activate(self, session):
        await self.conn.execute('INSERT INTO inventory VALUES (?,\'star_piece\',2)',
                                (session['profile_id'],))
        return await self.writer.run(lambda conn: items.activate_star_piece(conn, session, 1000))

    async def remaining(self):
        return await self.scalar("SELECT remaining_rewards FROM active_effects WHERE kind='star_piece'")

    async def test_successful_catch_with_and_without_star_piece_stays_pending(self):
        for active in (False, True):
            with self.subTest(active=active):
                await self.conn.execute('DELETE FROM profiles')
                session = await self.prepared()
                if active:
                    await self.activate(session)
                result, _ = await self.throw(session)
                self.assertEqual((result.status, result.stardust), ('caught', 450 if active else 300))
                self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE origin='catch'"), [])
                self.assertEqual(result.encounter['encounter_id'], self.encounter['encounter_id'])
                self.assertEqual(result.encounter['state'], 'caught')
                self.assertIsNone(result.pokemon)

    async def test_catch_stardust_boosted_floor_at_reward_time(self):
        for amount, expected in ((300, 450), (100, 150), (500, 750), (101, 151)):
            with self.subTest(amount=amount):
                await self.conn.execute('DELETE FROM profiles')
                session = await self.prepared()
                await self.activate(session)
                identity = next(i for i in self.bot.content['identities']
                                if i['pokemon_id'] == self.encounter['pokemon_id'])
                with patch.dict(identity, catch_stardust=amount):
                    result, _ = await self.throw(session)
                self.assertEqual(result.stardust, expected)
                self.assertEqual(await self.scalar('SELECT stardust FROM profiles'), expected)
                self.assertEqual(await self.remaining(), 9)

    async def test_failed_throw_does_not_use_a_reward(self):
        session = await self.prepared()
        await self.activate(session)
        result, _ = await self.throw(session, (0.99, 0.99))
        self.assertEqual((result.status, result.stardust), ('revealed', 0))
        self.assertEqual(await self.remaining(), 10)

    async def test_catch_after_counter_0_not_boosted(self):
        session = await self.prepared()
        await self.activate(session)
        await self.conn.execute('UPDATE active_effects SET remaining_rewards=0')
        result, _ = await self.throw(session)
        self.assertEqual(result.stardust, 300)
        self.assertEqual(await self.remaining(), 0)

    async def test_throw_replay_no_second_decrement(self):
        session = await self.prepared()
        await self.activate(session)
        first, _ = await self.throw(session)
        replay, rng = await self.throw(session, ())
        self.assertEqual(replay, first)
        rng.random.assert_not_called()
        self.assertEqual(await self.remaining(), 9)
        self.assertEqual(await self.scalar("SELECT count(*) FROM pokemon WHERE origin='catch'"), 0)
        self.assertEqual(await self.scalar('SELECT count(*) FROM catch_attempts'), 1)

    async def test_research_send_not_boosted(self):
        from pokewalker.services import research

        session = await self.prepared()
        caught, _ = await self.throw(session)
        stored = await catching_tests.store_legacy(self.writer, caught.encounter['encounter_id'], 1000)
        await self.activate(session)
        picks = [[stored['pokemon_uid'], stored['revision']]]
        preview = {'id': 'research-star', 'expires_at': 2000}
        session['selection'] = json.dumps({'picks': picks, 'preview': preview})
        result = await self.writer.run(lambda conn: research.send(
            conn, session, picks, preview, 1000, self.bot.content))
        self.assertEqual((result['status'], result['stardust']), ('sent', 0))
        self.assertEqual(await self.remaining(), 10)
        self.assertEqual(await self.scalar('SELECT stardust FROM profiles'), 300)
        self.assertEqual(await self.scalar("SELECT sum(delta) FROM resource_ledger WHERE reason='research_send'"), 1)

    async def test_ledger_and_receipt_carry_boosted_amount(self):
        session = await self.prepared()
        await self.activate(session)
        result, _ = await self.throw(session)
        self.assertEqual(result.stardust, 450)
        self.assertEqual(await self.scalar("SELECT delta FROM resource_ledger WHERE reason='catch_reward' "
                                           "AND resource='stardust'"), 450)
        receipt = json.loads(await self.scalar("SELECT result FROM action_receipts WHERE action='throw'"))
        self.assertEqual(receipt['stardust'], 450)

    async def test_catch_grant_rollback_restores_reward_counter(self):
        session = await self.prepared()
        await self.activate(session)
        await self.conn.execute("CREATE TRIGGER fail_catch BEFORE INSERT ON resource_ledger "
                                "WHEN NEW.reason='catch_reward' BEGIN SELECT RAISE(ABORT,'catch failed'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'catch failed'):
            await self.throw(session)
        self.assertEqual(await self.remaining(), 10)
        self.assertEqual(await self.scalar("SELECT count(*) FROM pokemon WHERE origin='catch'"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts WHERE action='throw'"), 0)
        await self.conn.execute('DROP TRIGGER fail_catch')
        self.assertEqual((await self.throw(session))[0].stardust, 450)
        self.assertEqual(await self.remaining(), 9)


class StarPieceBagTests(unittest.IsolatedAsyncioTestCase):
    interaction = lure_tests.LureTests.interaction
    rows = lure_tests.LureTests.rows
    click = lure_tests.LureTests.click
    close = lure_tests.LureTests.close
    current = lure_tests.LureTests.current
    snapshot = lure_tests.LureTests.snapshot
    screen = lure_tests.LureTests.screen
    buttons = lure_tests.LureTests.buttons

    async def asyncSetUp(self):
        await lure_tests.LureTests.asyncSetUp(self)
        await self.conn.execute("INSERT INTO inventory VALUES ('p','star_piece',2)")

    async def test_bag_shows_both_effects(self):
        session = await self.current()
        await self.writer.run(lambda conn: items.activate_star_piece(conn, session, 1000))
        await self.writer.run(lambda conn: items.activate_lure(conn, session, 1000))
        await self.conn.execute("UPDATE active_effects SET remaining_rewards=7 WHERE kind='star_piece'")
        rendered = await self.screen('bag')
        self.assertIn('Star Piece: 7 boosted Stardust rewards left', rendered['embed'].description)
        self.assertIn('10 encounters remaining', rendered['embed'].description)

    async def test_star_piece_confirm_then_activate_consumes_one(self):
        rendered = await self.screen('bag')
        self.assertFalse(self.buttons(rendered)['Star Piece'].disabled)
        self.assertTrue(self.buttons(rendered)['Star Piece'].custom_id.endswith(':star_piece_confirm'))
        preview = await self.screen('star_piece_confirm')
        self.assertEqual(preview['embed'].description, '1.5× Stardust on your next 10 catch or find Stardust rewards')
        self.assertTrue(self.buttons(preview)['Activate'].custom_id.endswith(':star_piece_activate'))
        self.assertEqual((await self.rows("SELECT quantity FROM inventory WHERE item_id='star_piece'"))[0]['quantity'], 2)
        session = await self.current()
        rendered = await self.screen('star_piece_activate')
        self.assertIn('Star Piece: 10 boosted Stardust rewards left', rendered['embed'].description)
        before = await self.snapshot()
        duplicate = await self.click(session, 'star_piece_activate')
        duplicate.followup.send.assert_not_awaited()
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.rows("SELECT quantity FROM inventory WHERE item_id='star_piece'"))[0]['quantity'], 1)

    async def test_activate_button_disabled_while_active(self):
        await self.screen('star_piece_confirm')
        session = await self.current()
        await self.writer.run(lambda conn: items.activate_star_piece(conn, session, 1000))
        rendered = await self.screen('bag')
        self.assertTrue(self.buttons(rendered)['Star Piece'].disabled)
        # A previously previewed confirmation must also recheck the live effect.
        await self.conn.execute('UPDATE sessions SET selection=?', (json.dumps({'phase': 'star_piece_confirm'}),))
        before = await self.rows('SELECT * FROM inventory')
        refused = await self.click(await self.current(), 'star_piece_activate')
        self.assertIn('already active', refused.followup.send.await_args.args[0])
        self.assertEqual(await self.rows('SELECT * FROM inventory'), before)
        await self.conn.execute('UPDATE active_effects SET remaining_rewards=0')
        self.assertFalse(self.buttons(await self.screen('bag'))['Star Piece'].disabled)
        await self.conn.execute("UPDATE inventory SET quantity=0 WHERE item_id='star_piece'")
        self.assertTrue(self.buttons(await self.screen('bag'))['Star Piece'].disabled)

    async def test_other_user_cannot_click(self):
        await self.screen('star_piece_confirm')
        before = await self.snapshot()
        for action in ('star_piece_confirm', 'star_piece_activate'):
            refused = await self.click(await self.current(), action, user=999)
            self.assertIn('not yours', refused.followup.send.await_args.args[0])
            self.assertEqual(await self.snapshot(), before)

    async def test_skipped_confirmation_and_missing_item_refused(self):
        before = await self.snapshot()
        refused = await self.click(await self.current(), 'star_piece_activate')
        self.assertIn('Preview', refused.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)
        await self.screen('star_piece_confirm')
        await self.conn.execute("UPDATE inventory SET quantity=0 WHERE item_id='star_piece'")
        refused = await self.click(await self.current(), 'star_piece_activate')
        refused.followup.send.assert_awaited_once()
        self.assertEqual(await self.rows('SELECT * FROM active_effects'), [])

    async def test_render_functions_do_no_io(self):
        from pokewalker.bot.bag import render

        state = {'session': await self.current(), 'inventory': {'star_piece': 1},
                 'stardust': 0, 'units': 1, 'limit': 250, 'rates': {'star_piece': 50},
                 'selection': {}, 'star_piece': {'remaining_rewards': 8},
                 'lure': {'remaining_encounters': 3}}
        with patch('builtins.open', side_effect=AssertionError('file I/O')), \
             patch('aiosqlite.Connection.execute', side_effect=AssertionError('DB I/O')), \
             patch('socket.socket', side_effect=AssertionError('network I/O')):
            for mode in ('bag', 'star_piece_confirm'):
                self.assertIsNotNone(render({**state, 'mode': mode})['embed'])
