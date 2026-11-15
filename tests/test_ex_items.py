"""Time Gear uses the D67 gameplay resets without moderation or anti-abuse effects."""

import json
import sqlite3
import unittest

from pokewalker.services import cooldowns
import test_arena
import test_iv_items


class EXBoostTests(unittest.IsolatedAsyncioTestCase):
    _base = test_arena.ArenaTests
    asyncSetUp = _base.asyncSetUp
    profile, scalar, rows = _base.profile, _base.scalar, _base.rows
    service, start, state, x_press = _base.service, _base.start, _base.state, _base.x_press

    async def stock(self, item='ex_attack', quantity=2):
        await self.conn.execute('INSERT INTO ex_items VALUES (?,?,?)', (self.pid, item, quantity))

    async def arm(self, item='ex_attack', session=None):
        self.assertTrue(callable(getattr(self.service(), 'arm', None)), 'Arena EX arming service is absent')
        return await self.writer.run(lambda conn: self.service().arm(conn, session or self.session, item, 1100))

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table} ORDER BY 1') for table in
                ('profiles', 'ex_items', 'arena_runs', 'action_receipts', 'resource_ledger')}

    async def test_arm_spends_one_sets_flag_with_ledger(self):
        await self.stock()
        self.assertEqual(await self.arm(), {'status': 'armed', 'item': 'ex_attack'})
        self.assertEqual(await self.scalar('SELECT quantity FROM ex_items'), 1)
        self.assertEqual(await self.rows('SELECT ex_attack_armed,ex_defense_armed FROM profiles WHERE profile_id=?',
                                         (self.pid,)), [{'ex_attack_armed': 1, 'ex_defense_armed': 0}])
        self.assertEqual(await self.rows('SELECT key,action,profile_id FROM action_receipts'),
                         [{'key': 'ex_arm:s:4', 'action': 'ex_arm', 'profile_id': self.pid}])
        self.assertEqual(await self.rows('SELECT receipt_key,profile_id,resource,resource_id,delta,reason '
                                         'FROM resource_ledger'),
                         [{'receipt_key': 'ex_arm:s:4', 'profile_id': self.pid, 'resource': 'ex_item',
                           'resource_id': 'ex_attack', 'delta': -1, 'reason': 'ex_arm'}])

    async def test_arm_twice_refused_other_kind_independent(self):
        await self.stock()
        await self.stock('ex_defense')
        await self.arm()
        await self.x_press()
        before = await self.snapshot()
        self.assertEqual(await self.arm(), {'status': 'armed_already'})
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.arm('ex_defense'), {'status': 'armed', 'item': 'ex_defense'})
        self.assertEqual(await self.rows('SELECT ex_attack_armed,ex_defense_armed FROM profiles WHERE profile_id=?',
                                         (self.pid,)), [{'ex_attack_armed': 1, 'ex_defense_armed': 1}])
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items ORDER BY item_id'),
                         [{'quantity': 1}, {'quantity': 1}])

    async def test_arm_missing_or_excluded_refused_paused_allowed(self):
        before = await self.snapshot()
        self.assertEqual(await self.arm(), {'status': 'missing'})
        for item in ('time_gear_fragment', 'x_attack', 'unknown'):
            self.assertEqual(await self.arm(item), {'status': 'invalid'})
        self.assertEqual(await self.snapshot(), before)
        await self.stock()
        await self.start()
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,excluded) VALUES ('g','u',1,1)")
        await self.conn.execute('UPDATE guilds SET arena_enabled=0')
        before = await self.snapshot()
        self.assertEqual(await self.arm(), {'status': 'excluded'})
        self.assertEqual(await self.arm(session={**self.session, 'profile_id': self.other}), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('UPDATE restrictions SET excluded=0')
        self.assertEqual((await self.arm())['status'], 'armed')

    async def test_arm_replay_returns_armed_after_flag_set(self):
        await self.stock()
        result = await self.arm()
        for change in ('DELETE FROM ex_items', 'UPDATE profiles SET ex_attack_armed=0'):
            await self.conn.execute(change)
            before = await self.snapshot()
            self.assertEqual(await self.arm(), result)
            self.assertEqual(await self.snapshot(), before)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','u',1)")
        self.assertEqual(await self.arm(), {'status': 'excluded'})

    async def test_restart_while_armed_keeps_flag(self):
        await self.stock()
        await self.arm()
        before = await self.snapshot()
        await self.writer.close()
        await self.conn.close()
        self.conn = await self.db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = self.db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.arm(), {'status': 'armed', 'item': 'ex_attack'})
        self.assertEqual(await self.snapshot(), before)

    async def test_arm_atomic_failure_and_receipt_owner(self):
        await self.stock()
        await self.conn.execute("CREATE TRIGGER fail_arm BEFORE INSERT ON resource_ledger "
                                "WHEN NEW.reason='ex_arm' BEGIN SELECT RAISE(ABORT,'arm ledger'); END")
        before = await self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'arm ledger'):
            await self.arm()
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('DROP TRIGGER fail_arm')
        session = {key: value for key, value in self.session.items() if key != '_original_revision'}
        await self.arm(session=session)
        self.assertEqual(await self.scalar('SELECT key FROM action_receipts'), 'ex_arm:s:5')
        for column, value in (('profile_id', self.other), ('action', 'ex_claim')):
            await self.conn.execute("UPDATE action_receipts SET profile_id=?,action='ex_arm'", (self.pid,))
            await self.conn.execute(f'UPDATE action_receipts SET {column}=?', (value,))
            before = await self.snapshot()
            self.assertEqual(await self.arm(session=session), {'status': 'stale'})
            self.assertEqual(await self.snapshot(), before)


class ShinyPatchTests(unittest.IsolatedAsyncioTestCase):
    _base = test_iv_items.IVItemTests
    asyncSetUp, connect, close = _base.asyncSetUp, _base.connect, _base.close
    rows, pokemon, current, mon = _base.rows, _base.pokemon, _base.current, _base.mon
    deploy = _base.deploy

    async def use(self, revision=0, uid='mon', session=None):
        from pokewalker.services import iv_items
        return await self.writer.run(lambda conn: iv_items.use(
            conn, session or self.session, uid, revision, 'shiny_patch',
            self.bot.content, self.walker.multipliers))

    async def stock(self):
        self.session = await self.current()
        await self.conn.execute("INSERT INTO ex_items VALUES ('p','shiny_patch',1)")

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table} ORDER BY 1') for table in
                ('pokemon', 'ex_items', 'inventory', 'action_receipts', 'resource_ledger')}

    async def test_shiny_patch_makes_shiny_bumps_revision_spends_one(self):
        from pokewalker.services import iv_items
        await self.stock()
        before = await self.mon()
        quote = await iv_items.quote(self.conn, 'p', 'mon', 'shiny_patch',
                                     self.bot.content, self.walker.multipliers)
        self.assertEqual(quote, {'have': 1, 'shiny': False})
        result = await self.use()
        self.assertEqual(result, {'status': 'used', 'pokemon': {**before, 'shiny': 1, 'revision': 1}})
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 0}])
        self.assertEqual(await self.rows('SELECT key,action,profile_id FROM action_receipts'),
                         [{'key': 'shiny_patch:mon:0', 'action': 'shiny_patch', 'profile_id': 'p'}])
        self.assertEqual(await self.rows('SELECT resource,resource_id,delta,reason FROM resource_ledger'),
                         [{'resource': 'ex_item', 'resource_id': 'shiny_patch', 'delta': -1,
                           'reason': 'shiny_patch'}])

    async def test_already_shiny_refused_item_kept(self):
        await self.stock()
        await self.conn.execute('UPDATE pokemon SET shiny=1')
        before = await self.snapshot()
        self.assertEqual((await self.use())['status'], 'shiny')
        self.assertEqual(await self.snapshot(), before)

    async def test_stale_after_trade_research_or_evolution_refused(self):
        from pokewalker.services import trading, research, evolution
        await self.stock()
        other = {**self.session, 'session_id': 'other', 'user_id': '789', 'profile_id': 'q'}
        await self.conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) "
                                "VALUES ('other','123','789','q',9000)")
        await self.pokemon('theirs', pid='q')
        trade = await self.writer.run(lambda c: trading.open_or_join(c, self.session, '789', 1000, False))
        tid = trade['trade_id']
        await self.writer.run(lambda c: trading.open_or_join(c, other, '456', 1001, False))
        await self.writer.run(lambda c: trading.offer(c, self.session, tid, 'mon', 1002))
        await self.writer.run(lambda c: trading.offer(c, other, tid, 'theirs', 1003))
        await self.writer.run(lambda c: trading.confirm(c, self.session, tid, 2, 1004, self.bot.content))
        swapped = await self.writer.run(lambda c: trading.confirm(c, other, tid, 2, 1005, self.bot.content))
        self.assertEqual(swapped['status'], 'completed')
        await self.pokemon('research')
        picks, preview = [['research', 0]], {'id': 'exg-research', 'expires_at': 2000}
        session = {**self.session, 'selection': json.dumps({'picks': picks, 'preview': preview})}
        sent = await self.writer.run(lambda c: research.send(c, session, picks, preview, 1000, self.bot.content))
        self.assertEqual(sent['status'], 'sent')
        await self.pokemon('evolution')
        await self.conn.execute("INSERT OR REPLACE INTO candy VALUES ('p',1,1000)")
        edge = evolution.options(self.bot.content, await self.mon('evolution'))[0]
        evolved = await self.writer.run(lambda c: evolution.evolve(
            c, self.session, 'evolution', edge['edge_id'], 0, self.bot.content, self.walker.multipliers, 1000))
        self.assertEqual(evolved['status'], 'evolved')
        for uid in ('mon', 'research', 'evolution'):
            with self.subTest(service=uid):
                before = await self.snapshot()
                self.assertEqual((await self.use(uid=uid))['status'], 'stale')
                self.assertEqual(await self.snapshot(), before)

    async def test_gym_deployed_allowed_arena_snapshot_unchanged(self):
        await self.stock()
        await self.deploy()
        self.assertEqual((await self.use(revision=(await self.mon())['revision']))['status'], 'used')
        for uid in ('arena', 'arena2', 'arena3'):
            await self.pokemon(uid)
        from pokewalker.services import arena
        import random
        run = await self.writer.run(lambda c: arena.start(
            c, self.session, [('arena', 0), ('arena2', 0), ('arena3', 0)], 1000,
            random.Random(7), self.bot.content, self.walker.multipliers))
        self.assertEqual(run['status'], 'started')
        before = await self.rows('SELECT * FROM arena_runs')
        await self.conn.execute('UPDATE ex_items SET quantity=1')
        self.assertEqual((await self.use(uid='arena'))['status'], 'used')
        self.assertEqual(await self.rows('SELECT * FROM arena_runs'), before)

    async def test_replay_returns_used_after_revision_and_stock_change(self):
        await self.stock()
        result = await self.use()
        for change in ("UPDATE pokemon SET revision=revision+1", "UPDATE pokemon SET profile_id='q'",
                       "UPDATE pokemon SET state='sent'", 'DELETE FROM ex_items'):
            await self.conn.execute(change)
            before = await self.snapshot()
            self.assertEqual(await self.use(), result)
            self.assertEqual(await self.snapshot(), before)

    async def test_other_profile_receipt_stale(self):
        await self.stock()
        await self.use()
        for column, value in (('profile_id', 'q'), ('action', 'ex_claim')):
            with self.subTest(column=column):
                await self.conn.execute("UPDATE action_receipts SET profile_id='p',action='shiny_patch'")
                await self.conn.execute(f'UPDATE action_receipts SET {column}=?', (value,))
                before = await self.snapshot()
                self.assertEqual((await self.use())['status'], 'stale')
                self.assertEqual(await self.snapshot(), before)

    async def test_missing_spends_nothing(self):
        self.session = await self.current()
        before = await self.snapshot()
        self.assertEqual((await self.use())['status'], 'missing')
        self.assertEqual(await self.snapshot(), before)

    async def test_shiny_patch_authorization_before_replay_and_atomic_failure(self):
        await self.stock()
        await self.conn.execute("CREATE TRIGGER fail_patch BEFORE INSERT ON resource_ledger "
                                "WHEN NEW.resource='ex_item' BEGIN SELECT RAISE(ABORT,'patch ledger'); END")
        before = await self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'patch ledger'):
            await self.use()
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('DROP TRIGGER fail_patch')
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,paused_until) "
                                "VALUES ('123','456',1,9999999999)")
        self.assertEqual((await self.use())['status'], 'used')
        await self.conn.execute('UPDATE restrictions SET excluded=1')
        before = await self.snapshot()
        self.assertEqual((await self.use())['status'], 'excluded')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.use(session={**self.session, 'profile_id': 'q'}))['status'], 'stale')


class GoldenBottlecapTests(unittest.IsolatedAsyncioTestCase):
    _base = test_iv_items.IVItemTests
    asyncSetUp, connect, close = _base.asyncSetUp, _base.connect, _base.close
    rows, pokemon, current, mon = _base.rows, _base.pokemon, _base.current, _base.mon
    deploy, shown = _base.deploy, _base.shown
    snapshot = ShinyPatchTests.snapshot

    async def stock(self):
        self.session = await self.current()
        await self.conn.execute("INSERT INTO ex_items VALUES ('p','golden_bottlecap',1)")

    async def use(self, revision=0, uid='mon', session=None):
        from pokewalker.services import iv_items
        return await self.writer.run(lambda conn: iv_items.use(
            conn, session or self.session, uid, revision, 'golden_bottlecap',
            self.bot.content, self.walker.multipliers))

    async def test_golden_bottlecap_maxes_all_three_ivs_bumps_revision(self):
        await self.stock()
        before = await self.mon()
        result = await self.use()
        self.assertEqual(result, {'status': 'used', 'pokemon': {
            **before, 'iv_attack': 15, 'iv_defense': 15, 'iv_stamina': 15, 'revision': 1}})
        self.assertEqual(await self.rows('SELECT quantity FROM ex_items'), [{'quantity': 0}])
        self.assertEqual(await self.rows('SELECT key,action,profile_id FROM action_receipts'),
                         [{'key': 'golden_bottlecap:mon:0', 'action': 'golden_bottlecap', 'profile_id': 'p'}])
        self.assertEqual(await self.rows('SELECT resource,resource_id,delta,reason FROM resource_ledger'),
                         [{'resource': 'ex_item', 'resource_id': 'golden_bottlecap', 'delta': -1,
                           'reason': 'golden_bottlecap'}])
        self.assertEqual(await self.rows('SELECT * FROM inventory'),
                         [{'profile_id': 'p', 'item_id': 'bottlecap', 'quantity': 2},
                          {'profile_id': 'p', 'item_id': 'vitamin', 'quantity': 3},
                          {'profile_id': 'q', 'item_id': 'vitamin', 'quantity': 1}])

    async def test_golden_bottlecap_quote_cp_and_appraisal_after(self):
        from pokewalker.services import iv_items
        await self.stock()
        pokemon = await self.mon()
        before, after = self.shown(pokemon), self.shown({**pokemon, **dict.fromkeys(iv_items.IVS, 15)})
        self.assertEqual(await iv_items.quote(self.conn, 'p', 'mon', 'golden_bottlecap',
                                              self.bot.content, self.walker.multipliers),
                         {'cp_before': before[0], 'cp_after': after[0], 'stars_before': before[1],
                          'stars_after': after[1], 'have': 1, 'perfect': False, 'deployed': False})
        self.assertGreater(after[0], before[0])
        self.assertEqual(after[1], 4)

    async def test_perfect_target_refused_item_kept(self):
        await self.stock()
        await self.conn.execute('UPDATE pokemon SET iv_attack=15,iv_defense=15,iv_stamina=15')
        before = await self.snapshot()
        self.assertEqual((await self.use())['status'], 'perfect')
        self.assertEqual(await self.snapshot(), before)

    async def test_gym_deployed_target_refused(self):
        await self.stock()
        await self.deploy()
        # Deployed wins over stale, perfect and missing, just as the ordinary Bottlecap.
        await self.conn.execute('UPDATE pokemon SET iv_attack=15,iv_defense=15,iv_stamina=15')
        await self.conn.execute('DELETE FROM ex_items')
        before = await self.snapshot()
        self.assertEqual((await self.use())['status'], 'deployed')
        self.assertEqual(await self.snapshot(), before)

    async def test_golden_stale_and_missing_spend_nothing(self):
        await self.stock()
        for sql, uid, expected in (
                ('UPDATE pokemon SET revision=1,iv_attack=15,iv_defense=15,iv_stamina=15', 'mon', 'stale'),
                ("UPDATE pokemon SET profile_id='q'", 'mon', 'stale'),
                ("UPDATE pokemon SET profile_id='p',revision=0,iv_attack=1", 'absent', 'stale'),
                ("UPDATE pokemon SET state='sent'", 'mon', 'stale'),
                ("UPDATE pokemon SET state='owned'", 'absent', 'stale'),
                ('DELETE FROM ex_items', 'mon', 'missing')):
            with self.subTest(sql=sql, uid=uid):
                await self.conn.execute(sql)
                before = await self.snapshot()
                self.assertEqual((await self.use(uid=uid))['status'], expected)
                self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('UPDATE pokemon SET iv_attack=15')
        self.assertEqual((await self.use())['status'], 'perfect')

    async def test_golden_replay_returns_used_after_ivs_and_stock_change(self):
        await self.stock()
        result = await self.use()
        for change in ('UPDATE pokemon SET iv_attack=1,revision=revision+1',
                       "UPDATE pokemon SET profile_id='q'", "UPDATE pokemon SET state='sent'",
                       'DELETE FROM ex_items'):
            await self.conn.execute(change)
            before = await self.snapshot()
            self.assertEqual(await self.use(), result)
            self.assertEqual(await self.snapshot(), before)
        for column, value in (('profile_id', 'q'), ('action', 'ex_claim')):
            await self.conn.execute("UPDATE action_receipts SET profile_id='p',action='golden_bottlecap'")
            await self.conn.execute(f'UPDATE action_receipts SET {column}=?', (value,))
            before = await self.snapshot()
            self.assertEqual((await self.use())['status'], 'stale')
            self.assertEqual(await self.snapshot(), before)

    async def test_golden_authorization_and_ledger_failure_are_atomic(self):
        await self.stock()
        await self.conn.execute("CREATE TRIGGER fail_golden BEFORE INSERT ON resource_ledger "
                                "WHEN NEW.resource='ex_item' BEGIN SELECT RAISE(ABORT,'golden ledger'); END")
        before = await self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'golden ledger'):
            await self.use()
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('DROP TRIGGER fail_golden')
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,paused_until) "
                                "VALUES ('123','456',1,9999999999)")
        self.assertEqual((await self.use())['status'], 'used')
        await self.conn.execute('UPDATE restrictions SET excluded=1')
        before = await self.snapshot()
        self.assertEqual((await self.use())['status'], 'excluded')
        self.assertEqual((await self.use(session={**self.session, 'profile_id': 'q'}))['status'], 'stale')
        self.assertEqual(await self.snapshot(), before)


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
