"""Time Gear uses the D67 gameplay resets without moderation or anti-abuse effects."""

import json
import sqlite3
import unittest

from pokewalker.services import cooldowns
import test_arena


class TimeGearTests(unittest.IsolatedAsyncioTestCase):
    _base = test_arena.ArenaTests
    profile, scalar, rows = _base.profile, _base.scalar, _base.rows
    service, start, state = _base.service, _base.start, _base.state

    async def asyncSetUp(self):
        await self._base.asyncSetUp(self)
        self.elsewhere = await self.profile('u', 'elsewhere')
        await self.conn.execute('UPDATE profiles SET last_checkin_at=10,last_battle_at=20,'
                                'last_trade_at=30,last_trade_ping_at=40,arena_cooldown_reset_at=50')
        await self.conn.execute("INSERT INTO ex_items VALUES (?,'time_gear_fragment',1)", (self.pid,))
        for index, (pid, guild) in enumerate(((self.pid, 'g'), (self.other, 'g'),
                                             (self.elsewhere, 'elsewhere'))):
            await self.conn.execute('INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,'
                                    'iv_attack,iv_defense,iv_stamina,gender,shiny,origin,content_version,caught_at) '
                                    "VALUES (?,?,1,20,10,10,10,'male',0,'catch','test',0)", (f'd{index}', pid))
            await self.conn.execute('INSERT INTO gyms(gym_id,guild_id,name,created_at) VALUES (?,?,?,0)',
                                    (f'g{index}', guild, f'Gym {index}'))
            await self.conn.execute('INSERT INTO gym_deployments(deployment_id,guild_id,gym_id,profile_id,'
                                    'pokemon_uid,deployed_at,ends_at,last_fed_at) VALUES (?,?,?,?,?,0,99999,60)',
                                    (f'dep{index}', guild, f'g{index}', pid, f'd{index}'))

    async def use(self, session=None, now=2100):
        self.assertTrue(callable(getattr(cooldowns, 'time_gear', None)), 'Time Gear service is absent')
        return await self.writer.run(lambda conn: cooldowns.time_gear(conn, session or self.session, now))

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table} ORDER BY 1') for table in
                ('profiles', 'guilds', 'gym_deployments', 'step_events', 'ex_items',
                 'action_receipts', 'resource_ledger', 'mod_audit')}

    async def test_time_gear_resets_six_cooldowns_for_this_profile_only(self):
        before = await self.rows('SELECT * FROM profiles WHERE profile_id!=? ORDER BY 1', (self.pid,))
        self.assertEqual(await self.use(), {'status': 'used', 'cooldowns': list(cooldowns.PLAYER)})
        player = (await self.rows('SELECT * FROM profiles WHERE profile_id=?', (self.pid,)))[0]
        for column in ('last_checkin_at', 'last_battle_at', 'last_trade_at', 'last_trade_ping_at'):
            self.assertIsNone(player[column])
        self.assertEqual(player['arena_cooldown_reset_at'], 2100)
        self.assertEqual(await self.rows('SELECT * FROM profiles WHERE profile_id!=? ORDER BY 1', (self.pid,)),
                         before)
        self.assertEqual(await self.rows('SELECT deployment_id,last_fed_at FROM gym_deployments ORDER BY 1'),
                         [{'deployment_id': 'dep0', 'last_fed_at': None},
                          {'deployment_id': 'dep1', 'last_fed_at': 60},
                          {'deployment_id': 'dep2', 'last_fed_at': 60}])

    async def test_time_gear_keeps_force_raid_share_and_step_limits(self):
        await self.conn.execute('UPDATE guilds SET force_raid_reset_at=123')
        await self.conn.execute('UPDATE profiles SET last_share_at=2099,encounter_meter_c=500 WHERE profile_id=?',
                                (self.pid,))
        await self.conn.execute('INSERT INTO step_events(message_id,profile_id,channel_id,eligible_words,'
                                'accepted_words,awarded_c,reason,created_at) '
                                "VALUES ('message',?,'channel',20,20,2000,'credited',2099)", (self.pid,))
        before = await self.snapshot()
        self.assertEqual((await self.use())['status'], 'used')
        after = await self.snapshot()
        self.assertEqual(after['guilds'], before['guilds'])
        self.assertEqual(after['step_events'], before['step_events'])
        for column in ('last_share_at', 'encounter_meter_c'):
            self.assertEqual([p[column] for p in after['profiles']], [p[column] for p in before['profiles']])

    async def test_time_gear_no_mod_audit_profile_receipt_and_ledger(self):
        result = await self.use()
        key = 'ex_time_gear:s:4'
        receipts = await self.rows('SELECT key,action,profile_id,result FROM action_receipts')
        self.assertEqual(receipts, [{'key': key, 'action': 'ex_time_gear', 'profile_id': self.pid,
                                     'result': json.dumps(result, separators=(',', ':'))}])
        self.assertEqual(await self.rows('SELECT receipt_key,profile_id,resource,resource_id,delta,reason '
                                         'FROM resource_ledger'),
                         [{'receipt_key': key, 'profile_id': self.pid, 'resource': 'ex_item',
                           'resource_id': 'time_gear_fragment', 'delta': -1, 'reason': 'ex_time_gear'}])
        self.assertEqual(await self.scalar('SELECT quantity FROM ex_items'), 0)
        self.assertEqual(await self.rows('SELECT * FROM mod_audit'), [])

    async def test_time_gear_missing_spends_nothing(self):
        for quantity in (None, 0):
            with self.subTest(quantity=quantity):
                await self.conn.execute('DELETE FROM ex_items')
                if quantity is not None:
                    await self.conn.execute("INSERT INTO ex_items VALUES (?,'time_gear_fragment',0)", (self.pid,))
                before = await self.snapshot()
                self.assertEqual(await self.use(), {'status': 'missing'})
                self.assertEqual(await self.snapshot(), before)

    async def test_excluded_member_refused(self):
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
        before = await self.snapshot()
        self.assertEqual(await self.use(), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_same_press_replays_used_after_stock_reaches_zero(self):
        result = await self.use()
        await self.conn.execute('UPDATE profiles SET last_checkin_at=2200 WHERE profile_id=?', (self.pid,))
        before = await self.snapshot()
        self.assertEqual(await self.use(now=2300), result)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.use({**self.session, '_original_revision': 6}), {'status': 'missing'})

    async def test_arena_cooldown_cleared_after_time_gear(self):
        await self.start()
        await self.conn.execute("UPDATE arena_runs SET ended_at=2000,end_reason='loss'")
        self.assertGreater((await self.state(now=2000))['cooldown_left'], 0)
        self.assertEqual((await self.use())['status'], 'used')
        self.assertEqual((await self.state(now=2200))['cooldown_left'], 0)

    async def test_stale_session_and_foreign_receipt_refused(self):
        await self.use()
        for session in ({**self.session, 'profile_id': self.other},
                        {**self.session, 'session_id': 'absent'}):
            with self.subTest(session=session):
                before = await self.snapshot()
                self.assertEqual(await self.use(session), {'status': 'stale'})
                self.assertEqual(await self.snapshot(), before)
        for column, value in (('profile_id', self.other), ('action', 'ex_claim')):
            with self.subTest(column=column):
                await self.conn.execute('UPDATE action_receipts SET profile_id=?,action=?',
                                        (self.pid, 'ex_time_gear'))
                await self.conn.execute(f'UPDATE action_receipts SET {column}=?', (value,))
                before = await self.snapshot()
                self.assertEqual(await self.use(), {'status': 'stale'})
                self.assertEqual(await self.snapshot(), before)

    async def test_exclusion_checked_before_replay_paused_use_allowed(self):
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,paused_until) "
                                "VALUES ('g','u',1,9999999999)")
        self.assertEqual((await self.use())['status'], 'used')
        await self.conn.execute('UPDATE restrictions SET excluded=1')
        before = await self.snapshot()
        self.assertEqual(await self.use(), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_failed_ledger_rolls_back_debit_and_cooldowns(self):
        await self.conn.execute("CREATE TRIGGER fail_time_gear BEFORE INSERT ON resource_ledger "
                                "BEGIN SELECT RAISE(ABORT,'ledger unavailable'); END")
        before = await self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'ledger unavailable'):
            await self.use()
        self.assertEqual(await self.snapshot(), before)

    async def test_time_gear_requires_writer_transaction(self):
        self.assertTrue(callable(getattr(cooldowns, 'time_gear', None)), 'Time Gear service is absent')
        with self.assertRaises(RuntimeError):
            await cooldowns.time_gear(self.conn, self.session, 2100)
