"""Owner-amended ten-encounter lure activation, exhaustion and migration."""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from content.balance import load_table
from pokewalker.db import Writer, open_db
from pokewalker.domain import encounters
from pokewalker.services import items, stepping
import test_walker_router as router


class LureTests(unittest.IsolatedAsyncioTestCase):
    interaction = router.WalkerTests.interaction
    rows = router.WalkerTests.rows
    click = router.WalkerTests.click

    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(dir='.')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'lure.sqlite'
        self.conn = await open_db(self.path, allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.close)
        self.content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        self.bot = SimpleNamespace(writer=self.writer)
        from pokewalker.bot.walker import Walker
        self.now = 1000
        self.walker = Walker(self.bot, clock=lambda: self.now)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('p','123','456',0)")
        await self.conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) "
                                "VALUES ('abcd','123','456','p',9000)")
        await self.conn.execute("INSERT INTO inventory VALUES ('p','shiny_lure',1)")

    async def close(self):
        await self.writer.close()
        await self.conn.close()

    async def current(self):
        return (await self.rows())[0]

    async def activate(self, session=None, now=1000):
        self.assertTrue(hasattr(items, 'activate_lure'), 'M3.4 activation service is absent')
        session = session or await self.current()
        return await self.writer.run(lambda conn: items.activate_lure(conn, session, now))

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table}') for table in
                ('profiles', 'inventory', 'sessions', 'active_effects', 'action_receipts', 'resource_ledger')}

    async def screen(self, action):
        interaction = await self.click(await self.current(), action)
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs

    def buttons(self, rendered):
        return {x.label: x for x in rendered['view'].children if hasattr(x, 'label')}

    async def credit(self, at, mid='m', pid='p', seed=8):
        await self.conn.execute('UPDATE profiles SET encounter_meter_c=9900 WHERE profile_id=?', (pid,))
        profile = (await self.rows('SELECT * FROM profiles WHERE profile_id=?', (pid,)))[0]
        await self.writer.run(lambda conn: stepping.credit_message(
            conn, profile, ['fresh', 'valid', 'words', mid], datetime.fromtimestamp(at, timezone.utc), mid, '789',
            content=self.content, rng=random.Random(seed), cache=stepping.DigestCache()))
        return (await self.rows('SELECT * FROM encounters WHERE source_message_id=?', (mid,)))[0]

    async def test_activate_consumes_one_and_creates_ten_encounter_effect(self):
        effect = await self.activate()
        row = (await self.rows('SELECT * FROM active_effects'))[0]
        self.assertEqual(effect, row)
        self.assertEqual((row['profile_id'], row['kind'], row['starts_at'], row['expires_at'], row['remaining_encounters']),
                         ('p', 'shiny_lure', 1000, None, 10))
        self.assertEqual((await self.rows('SELECT quantity FROM inventory'))[0]['quantity'], 0)
        receipt = (await self.rows('SELECT * FROM action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']), ('lure:abcd:0', 'lure', 'p'))
        self.assertEqual(json.loads(receipt['result']), effect)
        line = (await self.rows('SELECT * FROM resource_ledger'))[0]
        self.assertEqual((line['resource'], line['resource_id'], line['delta'], line['reason']),
                         ('item', 'shiny_lure', -1, 'lure_activate'))
        self.assertEqual(await items.active_lure(self.conn, 'p'), row['effect_id'])

    async def test_activate_while_active_refused_without_consuming(self):
        await self.activate()
        await self.writer.run(lambda conn: items.grant(conn, 'p', 'shiny_lure', 1))
        session = {**await self.current(), 'revision': 1}
        self.assertEqual(await self.activate(session, 1200), {'status': 'already_active'})
        self.assertEqual((await self.rows('SELECT quantity FROM inventory'))[0]['quantity'], 1)
        self.assertEqual(len(await self.rows('SELECT * FROM active_effects')), 1)
        self.assertEqual(len(await self.rows("SELECT * FROM resource_ledger WHERE reason='lure_activate'")), 1)
        # Refused attempts cannot become a new activation when replayed after exhaustion.
        await self.exhaust()
        self.assertEqual(await self.activate(session, 4600), {'status': 'already_active'})

    async def test_held_plus_active_permitted_find_refills_pocket_while_active(self):
        effect = await self.activate()
        await self.conn.execute('UPDATE profiles SET find_meter_c=9900')
        selected = {'item': 'shiny_lure', 'quantity': 1}
        with patch.object(items, 'roll_find', return_value=selected):
            await self.credit(1100)
            await self.conn.execute('UPDATE profiles SET find_meter_c=9900')
            await self.credit(1200, 'next')
        self.assertEqual((await self.rows('SELECT quantity FROM inventory'))[0]['quantity'], 1)
        self.assertEqual((await self.rows('SELECT stardust FROM profiles'))[0]['stardust'], 500)
        self.assertEqual(await items.active_lure(self.conn, 'p'), effect['effect_id'])
        self.assertEqual([r['outcome'] for r in await self.rows('SELECT * FROM finds ORDER BY find_id')],
                         ['granted', 'duplicate_rare'])

    async def test_next_generated_encounter_rolls_4x_seeded_and_stores_effect_id(self):
        effect = await self.activate()
        rules = load_table('catch')['rules']
        seed = next(s for s in range(10000)
                    if rules['shiny_probability'] <= random.Random(s).random()
                    < rules['shiny_probability'] * rules['lure_probability_multiplier'])
        shiny_rng = random.Random(seed)
        original = encounters.roll_shiny

        def seeded(rng, active, *, rules):
            self.assertTrue(active)
            return original(shiny_rng, active, rules=rules)

        with patch.object(encounters, 'roll_shiny', side_effect=seeded):
            row = await self.credit(1000)
        self.assertTrue(row['shiny'])
        self.assertEqual(row['lure_id'], effect['effect_id'])
        self.assertFalse(original(random.Random(seed), False, rules=rules))

    async def exhaust(self):
        for i in range(10):
            await self.conn.execute("UPDATE encounters SET state='ran'")
            row = await self.credit(1100 + 60 * i, f'exhaust-{i}')
            self.assertIsNotNone(row['lure_id'])
            self.assertEqual((await self.rows('SELECT remaining_encounters FROM active_effects'))[0]
                             ['remaining_encounters'], 9 - i)

    async def test_tenth_boosted_eleventh_ordinary_and_reactivation(self):
        effect = await self.activate()
        await self.exhaust()
        self.assertIsNone(await items.active_lure(self.conn, 'p'))
        await self.conn.execute("UPDATE encounters SET state='ran'")
        with patch.object(encounters, 'roll_shiny', wraps=encounters.roll_shiny) as roll:
            row = await self.credit(2000, 'eleventh')
        self.assertFalse(roll.call_args.args[1])
        self.assertIsNone(row['lure_id'])
        await self.writer.run(lambda conn: items.grant(conn, 'p', 'shiny_lure', 1))
        second = await self.activate({**await self.current(), 'revision': 1}, 2001)
        self.assertNotEqual(second['effect_id'], effect['effect_id'])
        self.assertEqual(second['remaining_encounters'], 10)

    async def test_existing_queued_encounters_unchanged(self):
        before = await self.credit(900)
        await self.activate()
        await self.credit(1100, 'after')
        self.assertEqual((await self.rows('SELECT * FROM encounters WHERE encounter_id=?',
                                        (before['encounter_id'],)))[0], before)

    async def test_waiting_does_not_expire_unused_encounters(self):
        effect = await self.activate()
        row = await self.credit(100000)
        self.assertEqual(row['lure_id'], effect['effect_id'])

    async def test_restart_keeps_remaining_count_without_deadline(self):
        effect = await self.activate()
        await self.credit(1100)
        await self.close()
        self.conn = await open_db(self.path, allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.bot.writer = self.writer
        self.assertEqual(await items.active_lure(self.conn, 'p'), effect['effect_id'])
        row = await self.credit(100000, 'after-restart')
        self.assertEqual(row['lure_id'], effect['effect_id'])
        saved = (await self.rows('SELECT * FROM active_effects'))[0]
        self.assertEqual(saved['remaining_encounters'], 8)
        self.assertIsNone(saved['expires_at'])

    async def test_double_click_stale_restart_and_receipt_replay_consume_once(self):
        await self.screen('bag')
        await self.screen('shiny_lure')
        before = await self.current()
        clicks = await asyncio.gather(self.click(before, 'lure_activate'), self.click(before, 'lure_activate'))
        self.assertEqual(sum(c.edit_original_response.await_count for c in clicks), 1)
        self.assertEqual(sum(c.followup.send.await_count for c in clicks), 1)
        effect = (await self.rows('SELECT * FROM active_effects'))[0]
        await self.credit(1100)
        await self.close()
        self.conn = await open_db(self.path)
        self.writer = Writer(self.conn)
        self.bot.writer = self.writer
        saved = await self.snapshot()
        stale = await self.click(before, 'lure_activate')
        stale.followup.send.assert_awaited_once()
        stale.edit_original_response.assert_not_awaited()
        self.assertEqual(await self.activate({**before, 'revision': before['revision'] + 1}, 8000), effect)
        self.assertEqual(await self.snapshot(), saved)

    async def test_generation_order_replaces_message_time_eligibility(self):
        effect = await self.activate()
        with patch('pokewalker.services.stepping.time.time', return_value=8000):
            delayed = await self.credit(980, 'delayed')
            earlier = await self.credit(1001, 'earlier')
            later = await self.credit(100000, 'later')
        for row in (delayed, earlier, later):
            self.assertEqual(row['lure_id'], effect['effect_id'])
        self.assertEqual((await self.rows('SELECT remaining_encounters FROM active_effects'))[0]
                         ['remaining_encounters'], 7)

    async def test_bag_shows_remaining_encounters_and_stored_label(self):
        rendered = await self.screen('bag')
        self.assertFalse(self.buttons(rendered)['Shiny Lure'].disabled)
        preview = await self.screen('shiny_lure')
        self.assertIn('4× shiny odds for the next 10 generated encounters; existing queued encounters are unchanged.',
                      preview['embed'].description)
        self.assertTrue(self.buttons(preview)['Activate'].custom_id.endswith(':lure_activate'))
        self.assertEqual((await self.rows('SELECT quantity FROM inventory'))[0]['quantity'], 1)
        rendered = await self.screen('lure_activate')
        self.assertIn('10 encounters remaining', rendered['embed'].description)
        self.assertTrue(self.buttons(rendered)['Shiny Lure'].disabled)
        await self.writer.run(lambda conn: items.grant(conn, 'p', 'shiny_lure', 1))
        self.now = 1100
        rendered = await self.screen('bag')
        label = 'Stored — available after the current effect ends'
        self.assertTrue(self.buttons(rendered)[label].disabled)
        self.assertIn('10 encounters remaining', rendered['embed'].description)
        await self.exhaust()
        self.now = 4600
        rendered = await self.screen('bag')
        self.assertFalse(self.buttons(rendered)['Shiny Lure'].disabled)
        self.assertNotIn('encounters remaining', rendered['embed'].description)

    async def test_effect_in_one_guild_does_not_apply_in_another(self):
        await self.activate()
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('999')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('other','999','456',0)")
        row = await self.credit(1100, pid='other')
        self.assertIsNone(row['lure_id'])
        self.assertIsNone(await items.active_lure(self.conn, 'other'))

    async def test_other_user_cannot_activate(self):
        session = await self.current()
        self.assertEqual(await self.activate({**session, 'user_id': '999'}), {'status': 'stale'})
        await self.screen('shiny_lure')
        before = await self.snapshot()
        interaction = await self.click(await self.current(), 'lure_activate', user=999)
        self.assertIn('not yours', interaction.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_excluded_refused_inside_transaction(self):
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        before = await self.snapshot()
        self.assertEqual(await self.activate(), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_missing_item_forged_owner_and_skipped_confirmation_refused(self):
        self.assertTrue(hasattr(items, 'activate_lure'), 'M3.4 activation service is absent')
        session = await self.current()
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await items.activate_lure(self.conn, session, 1000)
        for change in ({'guild_id': '999'}, {'profile_id': 'other'}, {'session_id': 'missing'}):
            self.assertEqual(await self.activate({**session, **change}), {'status': 'stale'})
        before = await self.snapshot()
        click = await self.click(session, 'lure_activate')
        click.followup.send.assert_awaited_once()
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('UPDATE inventory SET quantity=0')
        self.assertEqual(await self.activate(), {'status': 'missing'})
        self.assertEqual(await self.rows('SELECT * FROM active_effects'), [])

    async def test_ledger_failure_rolls_back_consumption_effect_and_receipt(self):
        self.assertTrue(hasattr(items, 'activate_lure'), 'M3.4 activation service is absent')
        before = await self.snapshot()
        await self.conn.execute("CREATE TRIGGER fail_lure BEFORE INSERT ON resource_ledger "
                                "BEGIN SELECT RAISE(ABORT,'ledger failed'); END")
        with self.assertRaisesRegex(Exception, 'ledger failed'):
            await self.activate()
        self.assertEqual(await self.snapshot(), before)

    async def test_migration_kind_index_counter_constraints_and_profile_cascade(self):
        await self.activate()
        self.assertEqual([r['name'] for r in await self.rows('PRAGMA index_info(active_effects_profile_remaining)')],
                         ['profile_id', 'remaining_encounters'])
        for column, value in (('kind', 'another'), ('remaining_encounters', -1),
                              ('remaining_encounters', 11), ('remaining_encounters', 1.5)):
            with self.subTest(column=column, value=value), self.assertRaises(sqlite3.IntegrityError):
                await self.conn.execute(f'UPDATE active_effects SET {column}=?', (value,))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute('INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,expires_at,'
                                    'receipt_key,remaining_encounters) '
                                    "SELECT effect_id||'-duplicate',profile_id,kind,"
                                    'starts_at,expires_at,receipt_key,remaining_encounters FROM active_effects')
        await self.conn.execute("DELETE FROM profiles WHERE profile_id='p'")
        self.assertEqual(await self.rows('SELECT * FROM active_effects'), [])

    async def test_multiple_mints_cross_exhaustion_per_encounter(self):
        effect = await self.activate()
        await self.conn.execute('UPDATE active_effects SET remaining_encounters=1')
        await self.conn.execute('UPDATE profiles SET encounter_meter_c=29900')
        profile = (await self.rows('SELECT * FROM profiles'))[0]
        await self.writer.run(lambda conn: stepping.credit_message(
            conn, profile, ['multiple', 'fresh', 'valid', 'words'], datetime.fromtimestamp(1100, timezone.utc),
            'multi', '789', content=self.content, rng=random.Random(8), cache=stepping.DigestCache()))
        rows = await self.rows("SELECT * FROM encounters WHERE source_message_id='multi' ORDER BY rowid")
        self.assertEqual([r['lure_id'] for r in rows], [effect['effect_id'], None, None])
        self.assertEqual((await self.rows('SELECT remaining_encounters FROM active_effects'))[0]
                         ['remaining_encounters'], 0)

    async def test_concurrent_duplicate_and_full_queue_do_not_overspend(self):
        await self.activate()
        await self.conn.execute('UPDATE active_effects SET remaining_encounters=1')
        await self.conn.execute('UPDATE profiles SET encounter_meter_c=9900')
        profile = (await self.rows('SELECT * FROM profiles'))[0]
        async def credit(mid, at):
            return await self.writer.run(lambda conn: stepping.credit_message(
                conn, profile, ['concurrent', 'fresh', 'words', mid], datetime.fromtimestamp(at, timezone.utc),
                mid, '789', content=self.content, rng=random.Random(8), cache=stepping.DigestCache()))
        await asyncio.gather(credit('same', 1100), credit('same', 1100))
        self.assertEqual(len(await self.rows('SELECT * FROM encounters')), 1)
        self.assertEqual((await self.rows('SELECT remaining_encounters FROM active_effects'))[0]
                         ['remaining_encounters'], 0)
        await self.conn.execute('UPDATE active_effects SET remaining_encounters=2')
        await self.conn.execute('UPDATE profiles SET encounter_meter_c=19900')
        await asyncio.gather(credit('a', 1200), credit('b', 1300))
        self.assertEqual(len(await self.rows('SELECT * FROM encounters')), 3)
        self.assertEqual((await self.rows('SELECT remaining_encounters FROM active_effects'))[0]
                         ['remaining_encounters'], 0)
        await self.conn.execute('UPDATE active_effects SET remaining_encounters=1')
        await credit('full', 1400)
        self.assertEqual((await self.rows('SELECT remaining_encounters FROM active_effects'))[0]
                         ['remaining_encounters'], 1)

    async def test_failure_after_mint_rolls_back_counter_and_encounter(self):
        await self.activate()
        await self.conn.execute('UPDATE profiles SET encounter_meter_c=9900')
        before = await self.snapshot()
        profile = (await self.rows('SELECT * FROM profiles'))[0]
        with patch.object(stepping, 'apply_finds', side_effect=RuntimeError('find failed')):
            with self.assertRaisesRegex(RuntimeError, 'find failed'):
                await self.writer.run(lambda conn: stepping.credit_message(
                    conn, profile, ['rollback', 'fresh', 'valid', 'words'], datetime.fromtimestamp(1100, timezone.utc),
                    'retry', '789', content=self.content, rng=random.Random(8), cache=stepping.DigestCache()))
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.rows('SELECT * FROM encounters'), [])
        self.assertEqual(await self.rows('SELECT * FROM step_events'), [])
        await self.credit(1100, 'retry')
        self.assertEqual((await self.rows('SELECT remaining_encounters FROM active_effects'))[0]
                         ['remaining_encounters'], 9)

    async def test_replay_rechecks_owner_and_exclusion(self):
        session = await self.current()
        await self.activate(session)
        before = await self.snapshot()
        self.assertEqual(await self.activate({**session, 'user_id': '999'}), {'status': 'stale'})
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        self.assertEqual(await self.activate(session), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_upgrade_preserves_history_counts_active_and_never_revives_expired(self):
        path = Path(self.temp.name) / 'legacy.sqlite'
        legacy = sqlite3.connect(path)
        try:
            for migration in sorted(Path('pokewalker/db/migrations').glob('*.sql'))[:6]:
                legacy.executescript(migration.read_text(encoding='utf-8'))
            legacy.execute('PRAGMA user_version=6')
            legacy.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
            for pid, used, expiry in (('active', 3, 9999999999), ('expired', 0, 1), ('spent', 11, 9999999999)):
                legacy.execute('INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES (?,123,?,0)',
                               (pid, pid))
                key = 'lure:abcd:0' if pid == 'active' else 'lure:' + pid
                legacy.execute('INSERT INTO active_effects VALUES (?, ?, ?, 0, ?, ?)',
                               (pid, pid, 'shiny_lure', expiry, key))
                for i in range(used):
                    legacy.execute("INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,"
                                   "iv_defense,iv_stamina,gender,shiny,tier,route_id,lure_id,state,content_version,"
                                   "created_at) VALUES (?,?,1,2,0,0,0,'male',1,'common','meadow',?,'ran','old',0)",
                                   (f'{pid}-{i}', pid, pid))
            historical = {'effect_id': 'active', 'profile_id': 'active', 'kind': 'shiny_lure',
                          'starts_at': 0, 'expires_at': 9999999999, 'receipt_key': 'lure:abcd:0'}
            legacy.execute("INSERT INTO action_receipts(key,action,result,created_at,profile_id) "
                           "VALUES ('lure:abcd:0','lure',?,0,'active')", (json.dumps(historical),))
            legacy.execute("INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) "
                           "VALUES ('abcd','123','active','active',9999999999)")
            legacy.execute("INSERT INTO inventory VALUES ('active','shiny_lure',1)")
            legacy.commit()
            old_effects = legacy.execute('SELECT * FROM active_effects ORDER BY effect_id').fetchall()
            old_encounters = legacy.execute('SELECT * FROM encounters ORDER BY encounter_id').fetchall()
            old_receipts = legacy.execute('SELECT * FROM action_receipts').fetchall()
        finally:
            legacy.close()
        conn = await open_db(path)
        try:
            async with conn.execute('SELECT * FROM active_effects ORDER BY effect_id') as cursor:
                effects = await cursor.fetchall()
            self.assertEqual([tuple(row)[:6] for row in effects], old_effects)
            self.assertEqual({row['effect_id']: row['remaining_encounters'] for row in effects},
                             {'active': 7, 'expired': 0, 'spent': 0})
            for table, expected in (('encounters ORDER BY encounter_id',
                                     [row + (None,) for row in old_encounters]),
                                    ('action_receipts', old_receipts)):
                async with conn.execute(f'SELECT * FROM {table}') as cursor:
                    self.assertEqual([tuple(row) for row in await cursor.fetchall()], expected)
            async with conn.execute('SELECT * FROM sessions') as cursor:
                session = dict(await cursor.fetchone())
            writer = Writer(conn)
            try:
                self.assertEqual(await writer.run(lambda c: items.activate_lure(c, session, 1000)), historical)
            finally:
                await writer.close()
            self.assertEqual(await items.active_lure(conn, 'active'), 'active')
            self.assertIsNone(await items.active_lure(conn, 'expired'))
            self.assertIsNone(await items.active_lure(conn, 'spent'))
            async with conn.execute("SELECT quantity FROM inventory WHERE profile_id='active'") as cursor:
                self.assertEqual((await cursor.fetchone())[0], 1)
        finally:
            await conn.close()
        conn = await open_db(path)
        try:
            async with conn.execute("SELECT remaining_encounters FROM active_effects WHERE effect_id='active'") as cursor:
                self.assertEqual((await cursor.fetchone())[0], 7)
        finally:
            await conn.close()

    async def test_upgrade_backward_clock_keeps_only_latest_activation_active(self):
        from pokewalker import db

        path = Path(self.temp.name) / 'backward-clock.sqlite'
        legacy = sqlite3.connect(path)
        try:
            for migration in sorted(Path('pokewalker/db/migrations').glob('*.sql'))[:6]:
                legacy.executescript(migration.read_text(encoding='utf-8'))
            legacy.execute('PRAGMA user_version=6')
            legacy.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
            legacy.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('p','123','456',0)")
            for effect_id, starts_at, expires_at in (('earlier', 0, 3600), ('latest', 3601, 7201)):
                effect = {'effect_id': effect_id, 'profile_id': 'p', 'kind': 'shiny_lure',
                          'starts_at': starts_at, 'expires_at': expires_at, 'receipt_key': f'lure:{effect_id}:0'}
                legacy.execute('INSERT INTO active_effects VALUES (?,?,?,?,?,?)', tuple(effect.values()))
                legacy.execute('INSERT INTO action_receipts(key,action,result,created_at,profile_id) '
                               "VALUES (?,'lure',?,?,'p')", (effect['receipt_key'], json.dumps(effect), starts_at))
            legacy.commit()
            old_effects = legacy.execute('SELECT * FROM active_effects ORDER BY rowid').fetchall()
            old_receipts = legacy.execute('SELECT * FROM action_receipts ORDER BY rowid').fetchall()
        finally:
            legacy.close()

        connect = db.aiosqlite.connect

        async def connect_with_backward_clock(*args, **kwargs):
            conn = await connect(*args, **kwargs)
            await conn.create_function('unixepoch', -1, lambda *args: 1000)
            return conn

        with patch.object(db.aiosqlite, 'connect', side_effect=connect_with_backward_clock):
            conn = await open_db(path)
        try:
            async with conn.execute('SELECT * FROM active_effects ORDER BY rowid') as cursor:
                effects = await cursor.fetchall()
            self.assertEqual([tuple(row)[:6] for row in effects], old_effects)
            self.assertEqual({row['effect_id']: row['remaining_encounters'] for row in effects},
                             {'earlier': 0, 'latest': 10})
            self.assertEqual(await items.active_lure(conn, 'p'), 'latest')
            async with conn.execute('SELECT * FROM action_receipts ORDER BY rowid') as cursor:
                self.assertEqual([tuple(row) for row in await cursor.fetchall()], old_receipts)
            await conn.execute("UPDATE active_effects SET remaining_encounters=0 WHERE effect_id='latest'")
            self.assertIsNone(await items.active_lure(conn, 'p'))
        finally:
            await conn.close()
