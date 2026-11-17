"""C3 EXR-2: coexistence and explicit, server-scoped raid joins on real SQLite."""

import unittest
from unittest.mock import Mock

import test_raids


class ExRaidTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_raids.RaidSpawnTests.asyncSetUp
    profile = test_raids.RaidSpawnTests.profile
    scalar = test_raids.RaidSpawnTests.scalar
    rows = test_raids.RaidSpawnTests.rows
    raids = test_raids.RaidSpawnTests.raids
    use = test_raids.RaidSpawnTests.use
    ticket = test_raids.RaidSpawnTests.ticket
    snapshot = test_raids.RaidJoinTests.snapshot

    async def spawn(self, spawn_id='ex', *, kind='ex', guild='g', ended=0, expires_at=4600):
        identity = next(i for i in self.content['identities'] if i['pokemon_id'] == 144)
        await self.conn.execute(
            'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,'
            'spawned_at,expires_at,post_state,ended,content_version,kind) '
            "VALUES (?,?,'789',?,?,0,?,'sent',?,'fixture',?)",
            (spawn_id, guild, identity['pokemon_id'], identity['identity_id'], expires_at, ended, kind))

    async def join(self, spawn_id, *, user='u', rng=None):
        return await self.writer.run(lambda conn: self.raids().join(
            conn, 'g', user, spawn_id, self.now, self.rng if rng is None else rng, self.content))

    async def test_ticket_spawns_world_legendary_while_ex_raid_live(self):
        await self.spawn()
        ex = (await self.rows("SELECT * FROM world_spawns WHERE spawn_id='ex'"))[0]
        result = await self.use()
        self.assertEqual(result['status'], 'spawned')
        self.assertEqual(await self.ticket(), 0)
        self.assertEqual(await self.rows("SELECT * FROM world_spawns WHERE spawn_id='ex'"), [ex])
        world = (await self.rows("SELECT * FROM world_spawns WHERE spawn_id=?",
                                 (result['spawn']['spawn_id'],)))[0]
        self.assertEqual((world['kind'], world['ex_raid_id']), ('world', None))
        self.assertEqual(await self.scalar("SELECT count(*) FROM resource_ledger WHERE "
                                          "reason='wlt_use' AND delta=-1"), 1)

    async def test_live_world_legendary_still_refuses_a_second_ticket_as_active(self):
        await self.spawn('world', kind='world')
        await self.spawn()
        before = await self.snapshot()
        self.assertEqual(await self.use(), {'status': 'active'})
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.ticket(), 1)

    async def test_live_spawns_lists_world_then_ex_skips_ended_expired_foreign(self):
        self.assertEqual(await self.raids().live_spawns(self.conn, 'g', self.now), [])
        await self.spawn('ended', kind='world', ended=1)
        await self.spawn('expired', guild='h', expires_at=self.now)
        await self.spawn('foreign', kind='world', guild='h')
        # Insert EX first so insertion order cannot stand in for the required kind order.
        await self.spawn()
        await self.spawn('world', kind='world')
        expected = await self.rows("SELECT * FROM world_spawns WHERE spawn_id IN ('world','ex') "
                                   "ORDER BY CASE kind WHEN 'world' THEN 0 ELSE 1 END")
        self.assertEqual(await self.raids().live_spawns(self.conn, 'g', self.now), expected)
        self.assertEqual([row['spawn_id'] for row in expected], ['world', 'ex'])
        await self.conn.execute("UPDATE world_spawns SET expires_at=? WHERE spawn_id='ex'", (self.now,))
        self.assertEqual(await self.raids().live_spawns(self.conn, 'g', self.now), [expected[0]])

    async def test_join_named_spawn_only_when_live_in_this_server(self):
        await self.spawn()
        await self.spawn('foreign', guild='h')
        await self.spawn('ended', kind='world', ended=1)
        await self.spawn('expired', kind='world', expires_at=self.now)
        for spawn_id in ('foreign', 'ended', 'expired', 'unknown'):
            for user in ('u', 'missing'):
                with self.subTest(spawn_id=spawn_id, user=user):
                    before = await self.snapshot()
                    writes = self.conn.total_changes
                    rng = Mock()
                    self.assertEqual(await self.join(spawn_id, user=user, rng=rng), {'status': 'none'})
                    self.assertEqual(await self.snapshot(), before)
                    self.assertEqual(self.conn.total_changes, writes)
                    self.assertEqual(rng.mock_calls, [])
        self.assertEqual((await self.join('ex'))['status'], 'new')

    async def test_player_joins_both_kinds_one_encounter_each(self):
        await self.spawn()
        await self.spawn('world', kind='world')
        joined = {}
        for spawn_id in ('world', 'ex'):
            result = await self.join(spawn_id)
            self.assertEqual(result['status'], 'new')
            joined[spawn_id] = result['encounter_id']
            before = await self.snapshot()
            rng = Mock()
            self.assertEqual(await self.join(spawn_id, rng=rng), {**result, 'status': 'joined'})
            self.assertEqual(await self.snapshot(), before)
            self.assertEqual(rng.mock_calls, [])
        self.assertNotEqual(joined['world'], joined['ex'])
        self.assertEqual(await self.scalar('SELECT count(*) FROM encounters'), 2)
        self.assertEqual(await self.rows('SELECT spawn_id,encounter_id FROM raid_participation ORDER BY spawn_id'),
                         [dict(spawn_id=s, encounter_id=joined[s]) for s in ('ex', 'world')])
        self.assertEqual(await self.rows("SELECT key,action FROM action_receipts ORDER BY key"),
                         [dict(key=f'raid:{s}:u', action='raid_join') for s in ('ex', 'world')])

    async def test_expiry_of_one_kind_leaves_the_other_live(self):
        await self.spawn()
        await self.spawn('world', kind='world')
        for spawn_id in ('world', 'ex'):
            await self.join(spawn_id)
        for expired, live in (('world', 'ex'), ('ex', 'world-2')):
            with self.subTest(expired=expired):
                if live == 'world-2':
                    await self.spawn(live, kind='world')
                    await self.join(live)
                await self.conn.execute('UPDATE world_spawns SET expires_at=? WHERE spawn_id=?',
                                        (self.now, expired))
                other = (await self.rows('SELECT * FROM world_spawns WHERE spawn_id=?', (live,)))[0]
                counts = await self.writer.run(lambda conn: self.raids().expire(conn, self.now))
                self.assertEqual(counts, {'spawns': 1, 'encounters': 1, 'participation': 1})
                self.assertEqual(await self.raids().live_spawns(self.conn, 'g', self.now), [other])
                self.assertEqual(await self.join(expired), {'status': 'none'})
                self.assertEqual((await self.join(live))['status'], 'joined')


class ExRaidLockTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = ExRaidTests.asyncSetUp
    profile = ExRaidTests.profile
    scalar = ExRaidTests.scalar
    rows = ExRaidTests.rows
    raids = ExRaidTests.raids
    join = ExRaidTests.join
    snapshot = ExRaidTests.snapshot

    fields = ('shiny', 'level_x2', 'iv_attack', 'iv_defense', 'iv_stamina', 'gender')

    async def locked_spawn(self, **locks):
        self.identity = next(i for i in self.content['identities'] if i['pokemon_id'] == 25)
        await self.conn.execute(
            'INSERT INTO ex_raids(ex_raid_id,owner_id,identity_id,shiny,level,iv_attack,'
            'iv_defense,iv_stamina,hours,servers,spawned,skipped,created_at) '
            "VALUES ('send','owner',?,?,?,?,?,?,1,1,1,'{}',0)",
            (self.identity['identity_id'], *(locks.get(k) for k in
             ('shiny', 'level', 'iv_attack', 'iv_defense', 'iv_stamina'))))
        await self.conn.execute(
            'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,'
            'spawned_at,expires_at,post_state,content_version,kind,ex_raid_id) '
            "VALUES ('ex','g','789',?,?,0,4600,'sent','fixture','ex','send')",
            (self.identity['pokemon_id'], self.identity['identity_id']))

    async def encounter(self, spawn_id='ex', *, user='u', rng=None):
        result = await self.join(spawn_id, user=user, rng=rng)
        self.assertEqual(result['status'], 'new')
        return (await self.rows('SELECT * FROM encounters WHERE encounter_id=?',
                                (result['encounter_id'],)))[0]

    def rolled_fields(self, seed):
        import random
        from content.balance import load_table
        from pokewalker.domain import encounters
        rng = random.Random(seed)
        gender, _ = encounters.roll_gender(self.identity, rng)
        shiny = encounters.roll_shiny(rng, False, rules=load_table('catch')['rules'])
        level, ivs = encounters.roll_level_ivs(rng, rules=load_table('catch')['rules'],
                                               level_range='raid_level_range')
        return dict(zip(self.fields, (shiny, level, *ivs, gender)))

    async def lure(self):
        await self.conn.execute(
            'INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,expires_at,'
            "receipt_key,remaining_encounters) VALUES ('lure',?,'shiny_lure',0,1,'fixture',2)",
            (self.pid,))

    async def test_no_locks_rolls_like_a_world_legendary(self):
        import random
        from pokewalker.services import profiles
        await self.locked_spawn()
        await self.conn.execute(
            'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,'
            'spawned_at,expires_at,post_state,content_version) '
            "VALUES ('world','g','789',?,?,0,4600,'sent','fixture')",
            (self.identity['pokemon_id'], self.identity['identity_id']))
        world = await self.encounter('world', rng=random.Random(6))
        ex = await self.encounter(rng=random.Random(6))
        self.assertEqual({k: ex[k] for k in self.fields}, {k: world[k] for k in self.fields})
        self.assertEqual({k: ex[k] for k in self.fields}, self.rolled_fields(6))
        self.assertIn(ex['level_x2'], range(40, 51, 2))
        profile = await profiles.get_profile(self.conn, 'g', 'u')
        self.assertEqual((ex['tier'], ex['route_id'], ex['content_version']),
                         ('Legendary/Mythical', profile['route_id'], profiles.content_facts(self.content)[0]))
        self.assertEqual(await self.rows('SELECT pokemon_id,seen_at FROM pokedex WHERE profile_id=?',
                                         (self.pid,)), [dict(pokemon_id=25, seen_at=self.now)])

    async def test_each_lock_alone_overrides_only_its_field(self):
        import random
        await self.locked_spawn()
        locks = dict(shiny=1, level=1, iv_attack=15, iv_defense=0, iv_stamina=15)
        for field, value in locks.items():
            with self.subTest(field=field):
                await self.conn.execute('UPDATE ex_raids SET shiny=NULL,level=NULL,iv_attack=NULL,'
                                        'iv_defense=NULL,iv_stamina=NULL')
                await self.conn.execute(f'UPDATE ex_raids SET {field}=?', (value,))
                await self.profile(field, 'g')
                row = await self.encounter(user=field, rng=random.Random(6))
                expected = self.rolled_fields(6)
                expected['level_x2' if field == 'level' else field] = value * 2 if field == 'level' else value
                self.assertEqual({k: row[k] for k in self.fields}, expected)

    async def test_all_five_locks_fix_shiny_level_ivs_gender_still_rolls(self):
        import random
        await self.locked_spawn(shiny=1, level=40, iv_attack=15, iv_defense=0, iv_stamina=7)
        genders = set()
        for seed in range(8):
            user = f'player-{seed}'
            await self.profile(user, 'g')
            row = await self.encounter(user=user, rng=random.Random(seed))
            self.assertEqual(tuple(row[k] for k in self.fields[:-1]), (1, 80, 15, 0, 7))
            self.assertEqual(row['gender'], self.rolled_fields(seed)['gender'])
            genders.add(row['gender'])
        self.assertEqual(genders, {'female', 'male'})

    async def test_level_1_and_40_and_iv_0_and_15_store_and_give_a_cp(self):
        from content.balance import load_table
        from pokewalker.services import storage
        await self.locked_spawn()
        for level in (1, 40):
            for iv in (0, 15):
                with self.subTest(level=level, iv=iv):
                    await self.conn.execute('UPDATE ex_raids SET level=?,iv_attack=?,iv_defense=?,iv_stamina=?',
                                            (level, iv, iv, iv))
                    user = f'player-{level}-{iv}'
                    await self.profile(user, 'g')
                    row = await self.encounter(user=user)
                    self.assertEqual((row['level_x2'], row['iv_attack'], row['iv_defense'], row['iv_stamina']),
                                     (2 * level, iv, iv, iv))
                    stats = storage.stats(self.content, row, load_table('cpm')['multipliers'])
                    self.assertIsInstance(stats['cp'], int)
                    self.assertGreaterEqual(stats['cp'], 10)

    async def test_shiny_false_and_iv_zero_are_locks_not_unset(self):
        import random
        await self.locked_spawn(shiny=0, iv_attack=0, iv_defense=0, iv_stamina=0)
        rng = Mock(wraps=random.Random(6))
        rng.random.return_value = 0
        row = await self.encounter(rng=rng)
        self.assertEqual((row['shiny'], row['iv_attack'], row['iv_defense'], row['iv_stamina']), (0, 0, 0, 0))

    async def test_shiny_locked_keeps_the_lure_and_stores_no_lure_id(self):
        from unittest.mock import patch
        await self.locked_spawn(shiny=0)
        await self.lure()
        for shiny in (0, 1):
            with self.subTest(shiny=shiny):
                await self.conn.execute('UPDATE ex_raids SET shiny=?', (shiny,))
                user = f'locked-{shiny}'
                pid = await self.profile(user, 'g')
                await self.conn.execute('UPDATE active_effects SET profile_id=?', (pid,))
                with patch.object(self.raids(), 'active_lure', side_effect=AssertionError('lure read')):
                    row = await self.encounter(user=user)
                self.assertEqual((row['shiny'], row['lure_id']), (shiny, None))
                self.assertEqual(await self.scalar('SELECT remaining_encounters FROM active_effects'), 2)

    async def test_shiny_open_consumes_one_lure_encounter(self):
        import random
        await self.locked_spawn(level=1)
        await self.lure()
        rng = Mock(wraps=random.Random(6))
        rng.random.return_value = .01
        row = await self.encounter(rng=rng)
        self.assertEqual((row['shiny'], row['lure_id']), (1, 'lure'))
        self.assertEqual(await self.scalar('SELECT remaining_encounters FROM active_effects'), 1)

    async def test_draw_sequence_is_the_same_whatever_is_locked(self):
        import random
        from unittest.mock import call
        await self.locked_spawn()
        locks = dict(shiny=1, level=1, iv_attack=15, iv_defense=0, iv_stamina=15)
        variants = [{}, *({key: value} for key, value in locks.items()), locks]
        for index, selected in enumerate(variants):
            with self.subTest(locks=selected):
                await self.conn.execute('UPDATE ex_raids SET shiny=?,level=?,iv_attack=?,iv_defense=?,iv_stamina=?',
                                        tuple(selected.get(key) for key in locks))
                user = f'player-{index}'
                await self.profile(user, 'g')
                rng = Mock(wraps=random.Random(6))
                await self.encounter(user=user, rng=rng)
                self.assertEqual(rng.mock_calls,
                                 [call.random(), call.random(), call.randint(20, 25),
                                  call.randint(0, 15), call.randint(0, 15), call.randint(0, 15)])

    async def test_partial_locks_two_players_share_locked_fields_and_roll_the_rest(self):
        import random
        await self.locked_spawn(level=40, iv_defense=0)
        for user, seed in (('u', 6), ('second', 1)):
            if user != 'u':
                await self.profile(user, 'g')
            row = await self.encounter(user=user, rng=random.Random(seed))
            expected = {**self.rolled_fields(seed), 'level_x2': 80, 'iv_defense': 0}
            self.assertEqual({k: row[k] for k in self.fields}, expected)

    async def test_rejoin_returns_the_same_encounter_no_reroll_no_second_lure(self):
        import json
        await self.locked_spawn(iv_attack=0)
        await self.lure()
        first = await self.join('ex')
        before = await self.snapshot()
        await self.conn.execute('UPDATE ex_raids SET shiny=1,level=40,iv_attack=15')
        rng = Mock()
        self.assertEqual(await self.join('ex', rng=rng), {**first, 'status': 'joined'})
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(rng.mock_calls, [])
        self.assertEqual(await self.scalar('SELECT remaining_encounters FROM active_effects'), 1)
        receipt = (await self.rows("SELECT * FROM action_receipts WHERE action='raid_join'"))[0]
        self.assertEqual((receipt['key'], receipt['profile_id'], json.loads(receipt['result'])),
                         ('raid:ex:u', self.pid, first))

    async def test_rolled_back_join_leaves_nothing(self):
        import sqlite3
        from unittest.mock import patch
        await self.locked_spawn(level=1, iv_attack=0)
        await self.lure()
        before = await self.snapshot()
        with patch.object(self.conn, 'commit', side_effect=sqlite3.IntegrityError('commit failed')):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'commit failed'):
                await self.join('ex')
        self.assertEqual(await self.snapshot(), before)
        for table in ('encounters', 'pokedex', 'raid_participation', 'action_receipts'):
            self.assertEqual(await self.scalar(f'SELECT count(*) FROM {table}'), 0)
        self.assertEqual(await self.scalar('SELECT remaining_encounters FROM active_effects'), 2)
        self.assertEqual((await self.join('ex'))['status'], 'new')


class ExRaidSendTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = ExRaidTests.asyncSetUp
    scalar = ExRaidTests.scalar
    rows = ExRaidTests.rows
    raids = ExRaidTests.raids
    profile = ExRaidTests.profile
    spawn = ExRaidTests.spawn
    join = ExRaidTests.join
    encounter = test_raids.RaidSpawnTests.encounter

    def arguments(self, **changes):
        identity = next(i for i in self.content['identities'] if i['pokemon_id'] == 25)
        return dict(dict(send_id='send', owner_id='owner', admin_guild_id='admin',
                         identity_id=identity['identity_id'], locks={}, hours=1,
                         guild_id='g', now=self.now, content=self.content,
                         checked=lambda guild, channel: channel), **changes)

    async def send(self, **changes):
        args = self.arguments(**changes)
        return await self.writer.run(lambda conn: self.raids().ex_commit(conn, **args))

    async def target(self, guild='g', checked=None):
        return await self.raids().ex_target(
            self.conn, guild, self.now, checked or (lambda guild, channel: channel))

    async def snapshot(self):
        tables = await self.rows("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return {t['name']: await self.rows(f"SELECT * FROM {t['name']}") for t in tables}

    async def unchanged_send(self, expected, **changes):
        before, writes = await self.snapshot(), self.conn.total_changes
        self.assertEqual(await self.send(**changes), expected)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(self.conn.total_changes, writes)

    async def test_one_server_send_spawns_ex_row_ordinary_mythical_form(self):
        identities = [next(i for i in self.content['identities'] if i['pokemon_id'] == n)
                      for n in (25, 151)]
        identities.append(next(i for i in self.content['identities'] if i['pokemon_id'] != i['species_id']))
        locks = dict(shiny=False, level=40, iv_attack=0, iv_defense=15, iv_stamina=7)
        for index, identity in enumerate(identities):
            with self.subTest(identity=identity['identity_id']):
                await self.conn.execute('UPDATE world_spawns SET ended=1')
                result = await self.send(send_id=f'send-{index}', identity_id=identity['identity_id'], locks=locks)
                self.assertEqual((result['status'], result['replayed']), ('sent', False))
                self.assertEqual({k: result[k] for k in locks}, locks)
                self.assertEqual((result['owner_id'], result['guild_id'], result['servers'],
                                  result['spawned'], result['skipped']), ('owner', 'g', 1, 1, {}))
                row, = await self.rows('SELECT * FROM world_spawns WHERE ex_raid_id=?', (result['ex_raid_id'],))
                from pokewalker.services import profiles
                self.assertEqual((row['kind'], row['identity_id'], row['pokemon_id'], row['guild_id'],
                                  row['channel_id'], row['spawned_at'], row['expires_at'], row['post_state'],
                                  row['spawned_by_profile_id'], row['message_id'], row['ended'], row['content_version']),
                                 ('ex', identity['identity_id'], identity['pokemon_id'], 'g', '789', self.now,
                                  self.now + 3600, 'pending', None, None, 0, profiles.content_facts(self.content)[0]))

    async def test_hours_1_and_24_ok_0_25_bool_text_invalid(self):
        for hours in (0, 25, True, False, '1', 1.0, None):
            with self.subTest(hours=hours):
                await self.unchanged_send({'status': 'invalid'}, hours=hours)
        for hours in (1, 24):
            await self.conn.execute('UPDATE world_spawns SET ended=1')
            self.assertEqual((await self.send(send_id=str(hours), hours=hours))['hours'], hours)
            self.assertEqual(await self.scalar('SELECT expires_at FROM world_spawns WHERE ended=0'),
                             self.now + hours * 3600)

    async def test_global_send_shares_one_expires_at(self):
        await self.conn.execute("UPDATE guilds SET raids_enabled=1,raid_channel_id='456'")
        result = await self.send(guild_id=None, hours=24)
        self.assertEqual((result['guild_id'], result['servers'], result['spawned'], result['skipped']),
                         (None, 2, 2, {}))
        self.assertEqual(await self.rows('SELECT DISTINCT expires_at FROM world_spawns'),
                         [dict(expires_at=self.now + 24 * 3600)])
        self.assertEqual(await self.rows('SELECT DISTINCT ex_raid_id FROM world_spawns'), [dict(ex_raid_id='send')])

    async def test_global_send_counts_each_skip_reason(self):
        for guild in ('off', 'missing', 'permission', 'changed', 'active', 'absent'):
            await self.conn.execute("INSERT INTO guilds(guild_id,raids_enabled,raid_channel_id) VALUES (?,1,'789')", (guild,))
            await self.spawn(f'ex-{guild}', guild=guild)
        await self.conn.execute("UPDATE guilds SET raids_enabled=0,raid_channel_id=NULL WHERE guild_id='off'")
        await self.conn.execute("UPDATE guilds SET raid_channel_id=NULL WHERE guild_id='missing'")
        def checked(guild, channel):
            return None if guild in ('permission', 'absent') else '999' if guild == 'changed' else channel
        checked = Mock(side_effect=checked)
        expected = dict(status='ok', servers=8, spawning=1,
                        skipped=dict(raids_off=2, no_channel=1, no_permission=2, channel_changed=1, active=1))
        before, writes = await self.snapshot(), self.conn.total_changes
        self.assertEqual(await self.target(None, checked), expected)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(self.conn.total_changes, writes)
        self.assertEqual({c.args[0] for c in checked.call_args_list},
                         {'g', 'permission', 'absent', 'changed', 'active'})
        result = await self.send(guild_id=None, checked=checked)
        self.assertEqual((result['servers'], result['spawned'], result['skipped']),
                         (expected['servers'], expected['spawning'], expected['skipped']))
        self.assertEqual(await self.scalar("SELECT count(*) FROM world_spawns WHERE ex_raid_id='send'"), 1)

    async def test_one_server_skipped_writes_nothing_returns_reason(self):
        for sql, checked, reason in (
                ("UPDATE guilds SET raids_enabled=0,raid_channel_id=NULL WHERE guild_id='g'", '789', 'raids_off'),
                ("UPDATE guilds SET raids_enabled=1 WHERE guild_id='g'", '789', 'no_channel'),
                ("UPDATE guilds SET raid_channel_id='789' WHERE guild_id='g'", None, 'no_permission'),
                ("UPDATE guilds SET raid_channel_id='789' WHERE guild_id='g'", '999', 'channel_changed')):
            await self.conn.execute(sql)
            await self.unchanged_send(dict(status='nothing', servers=1, skipped={reason: 1}),
                                      checked=lambda g, c: checked)
        await self.spawn()
        await self.unchanged_send(dict(status='nothing', servers=1, skipped={'active': 1}))
        before = await self.snapshot()
        self.assertEqual(await self.target('unknown'), {'status': 'unknown_server'})
        await self.unchanged_send({'status': 'unknown_server'}, guild_id='unknown')
        self.assertEqual(await self.snapshot(), before)

    async def test_global_send_all_skipped_writes_nothing(self):
        await self.conn.execute('UPDATE guilds SET raids_enabled=0')
        await self.unchanged_send(dict(status='nothing', servers=2, skipped={'raids_off': 2}), guild_id=None)
        await self.conn.execute('DELETE FROM profiles')
        await self.conn.execute('DELETE FROM guilds')
        await self.unchanged_send(dict(status='nothing', servers=0, skipped={}), guild_id=None)

    async def test_live_world_legendary_is_no_guard_and_is_untouched(self):
        await self.spawn('world', kind='world')
        await self.join('world')
        before = await self.snapshot()
        self.assertEqual((await self.send())['status'], 'sent')
        after = await self.snapshot()
        self.assertEqual([r for r in after['world_spawns'] if r['kind'] == 'world'], before['world_spawns'])
        for table in ('encounters', 'raid_participation', 'action_receipts', 'inventory'):
            self.assertEqual(after[table], before[table])

    async def overdue(self):
        for spawn_id, kind, guild in (('ex', 'ex', 'g'), ('world', 'world', 'g'), ('foreign', 'ex', 'h')):
            await self.spawn(spawn_id, kind=kind, guild=guild, expires_at=self.now)
            for index, state in enumerate(('queued', 'revealed', 'caught', 'ran')):
                user = f'{spawn_id}-{index}'
                pid = await self.profile(user, guild)
                eid = f'enc-{user}'
                await self.encounter(pid, eid, state, spawn_id)
                await self.conn.execute('INSERT INTO raid_participation VALUES (?,?,?,?,0)',
                                        (guild, user, spawn_id, eid))

    async def test_overdue_unswept_ex_raid_is_settled_and_replaced(self):
        await self.overdue()
        await self.conn.execute('SAVEPOINT reference_expiry')
        await self.raids().expire(self.conn, self.now, 'g')
        expected = await self.snapshot()
        await self.conn.execute('ROLLBACK TO reference_expiry')
        await self.conn.execute('RELEASE reference_expiry')
        result = await self.send()
        self.assertEqual(result['status'], 'sent')
        actual = await self.snapshot()
        actual['world_spawns'] = [r for r in actual['world_spawns'] if r['ex_raid_id'] != 'send']
        actual['ex_raids'] = []
        self.assertEqual(actual, expected)

    async def test_refused_send_with_overdue_rows_writes_nothing(self):
        await self.overdue()
        await self.conn.execute("UPDATE guilds SET raids_enabled=0 WHERE guild_id='g'")
        await self.unchanged_send(dict(status='nothing', servers=1, skipped={'raids_off': 1}))

    async def test_settings_changed_after_preview_judged_at_commit(self):
        self.assertEqual(await self.target(), dict(status='ok', servers=1, spawning=1, skipped={}))
        await self.conn.execute("UPDATE guilds SET raid_channel_id='999' WHERE guild_id='g'")
        await self.unchanged_send(dict(status='nothing', servers=1, skipped={'channel_changed': 1}),
                                  checked=lambda g, c: '789')
        await self.conn.execute("UPDATE guilds SET raids_enabled=0 WHERE guild_id='g'")
        await self.unchanged_send(dict(status='nothing', servers=1, skipped={'raids_off': 1}))
        await self.conn.execute("UPDATE guilds SET raids_enabled=1 WHERE guild_id='g'")
        await self.conn.execute("INSERT INTO guilds(guild_id,raids_enabled,raid_channel_id) VALUES ('new',1,'123')")
        self.assertEqual((await self.send(guild_id=None))['spawned'], 2)

    async def test_same_send_id_returns_recorded_result_spawns_nothing(self):
        result = await self.send()
        await self.conn.execute('UPDATE world_spawns SET ended=1')
        await self.conn.execute('UPDATE guilds SET raids_enabled=0')
        await self.unchanged_send(dict(result, replayed=True), identity_id='unknown', locks={'level': 0},
                                  hours=0, guild_id='unknown', checked=Mock(side_effect=AssertionError('targeted')))

    async def test_other_owners_send_id_invalid(self):
        await self.send()
        await self.unchanged_send({'status': 'invalid'}, owner_id='other', checked=Mock(side_effect=AssertionError('targeted')))

    async def test_excluded_owner_refused_before_lookup(self):
        from unittest.mock import patch
        await self.send()
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('admin')")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('admin','owner',1)")
        with patch.object(self.raids(), 'ex_lookup', side_effect=AssertionError('looked up')):
            await self.unchanged_send({'status': 'excluded'})
            await self.unchanged_send({'status': 'excluded'}, send_id='new')

    async def test_unknown_identity_or_bad_lock_invalid_nothing_written(self):
        await self.unchanged_send({'status': 'invalid'}, identity_id='unknown')
        for locks in (None, [], {'unexpected': 1}):
            await self.unchanged_send({'status': 'invalid'}, locks=locks)
        for field, bad in (('shiny', (2, -1, '1', 1.0)), ('level', (0, 41, True, '1', 1.0)),
                           ('iv_attack', (-1, 16, True, '0', 0.0)),
                           ('iv_defense', (-1, 16, False, '0', 0.0)),
                           ('iv_stamina', (-1, 16, True, '0', 0.0))):
            for value in bad:
                with self.subTest(field=field, value=value):
                    await self.unchanged_send({'status': 'invalid'}, locks={field: value})
        result = await self.send(locks=dict(shiny=1, level=1, iv_attack=15, iv_defense=None, iv_stamina=0))
        self.assertEqual((result['shiny'], result['level'], result['iv_defense']), (1, 1, None))

    async def test_insert_failure_part_way_rolls_back_everything(self):
        import sqlite3
        await self.overdue()
        await self.conn.execute("UPDATE guilds SET raids_enabled=1,raid_channel_id='789'")
        await self.conn.execute("CREATE TRIGGER fail_second BEFORE INSERT ON world_spawns "
                                "WHEN NEW.kind='ex' AND NEW.guild_id='h' "
                                "BEGIN SELECT RAISE(ABORT,'second spawn failed'); END")
        before = await self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'second spawn failed'):
            await self.send(guild_id=None)
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('DROP TRIGGER fail_second')
        self.assertEqual((await self.send(guild_id=None))['spawned'], 2)

    async def test_no_mod_audit_and_force_raid_cooldown_ignored(self):
        await self.conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                                "VALUES ('g','mod','guild','g','force_raid','fixture',?)", (self.now,))
        statements = []
        await self.conn.set_trace_callback(statements.append)
        try:
            self.assertEqual((await self.send())['status'], 'sent')
        finally:
            await self.conn.set_trace_callback(None)
        self.assertFalse(any('mod_audit' in s or 'action_receipts' in s or 'force_raid_reset_at' in s for s in statements))
        self.assertEqual(await self.scalar('SELECT count(*) FROM mod_audit'), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM action_receipts'), 0)

    async def test_history_newest_first_paged_and_lookup(self):
        self.assertIsNone(await self.raids().ex_lookup(self.conn, 'unknown'))
        self.assertEqual(await self.raids().ex_history(self.conn, 0), ([], 0))
        results = []
        for index in range(13):
            await self.conn.execute('UPDATE world_spawns SET ended=1')
            result = await self.send(send_id=f'send-{index:02}', now=self.now + index // 2, guild_id=None)
            self.assertEqual(result['skipped'], {'raids_off': 1})
            results.append({k: v for k, v in result.items() if k not in ('status', 'replayed')})
        expected = list(reversed(results))
        self.assertEqual(await self.raids().ex_history(self.conn, 0), (expected[:10], 13))
        self.assertEqual(await self.raids().ex_history(self.conn, 10), (expected[10:], 13))
        self.assertEqual(await self.raids().ex_history(self.conn, 20), ([], 13))
        self.assertEqual(await self.raids().ex_lookup(self.conn, 'send-04'), results[4])

    async def test_requires_writer_transaction(self):
        with self.assertRaisesRegex(RuntimeError, 'transaction'):
            await self.raids().ex_commit(self.conn, **self.arguments())


class ExRaidCatchTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = ExRaidTests.asyncSetUp
    profile = ExRaidTests.profile
    scalar = ExRaidTests.scalar
    rows = ExRaidTests.rows
    raids = ExRaidTests.raids
    join = ExRaidTests.join
    use = ExRaidTests.use
    ticket = ExRaidTests.ticket
    arguments = ExRaidSendTests.arguments
    send = ExRaidSendTests.send
    snapshot = ExRaidSendTests.snapshot
    throw = test_raids.RaidJoinTests.throw
    client = test_raids.RaidSweepTests.client

    async def prepare(self, identity_id='25:25', *, locks=None, hours=1, rng=None):
        import json
        send_id = f"send-{await self.scalar('SELECT count(*) FROM ex_raids')}"
        result = await self.send(send_id=send_id, identity_id=identity_id,
                                 locks={'shiny': False} if locks is None else locks, hours=hours)
        self.assertEqual(result['status'], 'sent')
        self.spawn_row, = await self.rows('SELECT * FROM world_spawns WHERE ex_raid_id=?', (send_id,))
        joined = await self.join(self.spawn_row['spawn_id'], rng=rng)
        self.assertEqual(joined['status'], 'new')
        encounter, = await self.rows('SELECT * FROM encounters WHERE encounter_id=?', (joined['encounter_id'],))
        await self.conn.executemany('INSERT OR IGNORE INTO inventory VALUES (?,?,?)',
                                    [(self.pid, 'poke_ball', 10), (self.pid, 'razz_berry', 3)])
        session = {**self.session, 'selection': json.dumps(dict(
            encounter_id=encounter['encounter_id'], encounter_revision=0,
            ball='poke_ball', berry='razz_berry'))}
        return encounter, session

    async def assert_boss(self, identity_id, *, gender=None, locks=None):
        import random
        from content.balance import load_table
        from pokewalker.domain.cp import cp, catch_probability
        from pokewalker.services import storage
        rng = Mock(wraps=random.Random(6))
        rng.random.return_value = .25 if gender == 'female' else .75
        encounter, session = await self.prepare(identity_id, locks=locks, rng=rng)
        selected = next(i for i in self.content['identities'] if i['identity_id'] == identity_id)
        identity = selected['gender_varieties'][gender] if gender else selected
        self.assertEqual(self.spawn_row['identity_id'], identity_id)
        self.assertEqual(encounter['pokemon_id'], identity['pokemon_id'])
        if gender:
            self.assertEqual(encounter['gender'], gender)
        self.assertEqual(encounter['tier'], 'Legendary/Mythical')
        multipliers = load_table('cpm')['multipliers']
        shown = storage.stats(self.content, encounter, multipliers)
        self.assertEqual(shown['identity']['identity_id'], identity['identity_id'])
        self.assertEqual(shown['cp'], cp(
            [identity[k] for k in ('base_attack', 'base_defense', 'base_stamina')],
            [encounter[k] for k in ('iv_attack', 'iv_defense', 'iv_stamina')],
            encounter['level_x2'], multipliers=multipliers))
        self.assertEqual(await self.rows('SELECT * FROM pokedex WHERE profile_id=?', (self.pid,)),
                         [dict(profile_id=self.pid, pokemon_id=identity['species_id'],
                               seen_at=self.now, caught_at=None)])
        rules = load_table('catch')['rules']
        self.assertEqual(rules['legendary_flee_probability'], 0)
        failed, rolls = await self.throw(session, 1)
        self.assertEqual(failed.status, 'revealed')
        rolls.random.assert_called_once_with()
        attempt, = await self.rows('SELECT p,success,fled FROM catch_attempts')
        self.assertEqual(attempt, dict(p=catch_probability(
            identity['base_catch_rate'], encounter['level_x2'], rules['ball_multipliers']['poke_ball'],
            rules['berry_multipliers']['razz_berry'], multipliers=multipliers), success=0, fled=0))
        dust = await self.scalar('SELECT stardust FROM profiles WHERE profile_id=?', (self.pid,))
        result, _ = await self.throw(session)
        self.assertEqual(result.status, 'caught')
        self.assertEqual(result.encounter['pokemon_id'], identity['pokemon_id'])
        self.assertEqual((result.candy, result.stardust), (identity['catch_candy'], identity['catch_stardust']))
        self.assertEqual(await self.scalar('SELECT quantity FROM candy WHERE profile_id=? AND family_id=?',
                                          (self.pid, identity['family_id'])), identity['catch_candy'])
        self.assertEqual(await self.scalar('SELECT stardust FROM profiles WHERE profile_id=?', (self.pid,)),
                         dust + identity['catch_stardust'])
        self.assertEqual(await self.rows('SELECT pokemon_id,seen_at,caught_at FROM pokedex WHERE profile_id=?',
                                        (self.pid,)),
                         [dict(pokemon_id=identity['species_id'], seen_at=self.now, caught_at=self.now)])
        return encounter

    async def test_ordinary_boss_join_catch_rewards_pokedex_never_flees(self):
        await self.assert_boss('25:25')

    async def test_mythical_boss_end_to_end(self):
        await self.assert_boss('151:151')

    async def test_regional_form_boss_keeps_its_form(self):
        await self.assert_boss('10100:10202')

    async def test_gender_variety_boss_stores_the_rolled_variety(self):
        await self.assert_boss('876:876', gender='female')

    async def test_locked_level_sets_cp_and_catch_chance(self):
        encounter = await self.assert_boss('25:25', locks=dict(
            shiny=False, level=40, iv_attack=0, iv_defense=15, iv_stamina=7))
        self.assertEqual((encounter['level_x2'], encounter['iv_attack'], encounter['iv_defense'],
                          encounter['iv_stamina']), (80, 0, 15, 7))

    async def test_master_ball_catches_and_full_storage_waits_like_any_catch(self):
        import json
        from pokewalker.services import catching
        encounter, session = await self.prepare()
        await self.conn.execute('UPDATE profiles SET storage_limit=250 WHERE profile_id=?', (self.pid,))
        await self.conn.executemany(
            'INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,'
            'iv_stamina,gender,shiny,origin,content_version,caught_at) '
            "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,"
            "'starter',content_version,0 FROM encounters WHERE encounter_id=?",
            [(f'full-{i}', encounter['encounter_id']) for i in range(250)])
        await self.conn.execute("INSERT INTO inventory VALUES (?,'master_ball',1)", (self.pid,))
        selection = json.loads(session['selection'])
        selection.update(ball='master_ball', berry=None)
        session['selection'] = json.dumps(selection)
        rolls = Mock()
        async def master():
            return await self.writer.run(lambda conn: catching.throw(
                conn, encounter['encounter_id'], session, selection['encounter_revision'],
                rolls, self.now, content=self.content, guaranteed=True))
        before = await self.snapshot()
        self.assertEqual((await master()).status, 'storage_full')
        self.assertEqual(await self.snapshot(), before)
        rolls.random.assert_not_called()
        selection['storage_confirm'] = encounter['revision']
        session['selection'] = json.dumps(selection)
        result = await master()
        self.assertEqual(result.status, 'caught')
        self.assertIsNone(result.pokemon)
        self.assertEqual(await self.scalar("SELECT quantity FROM inventory WHERE item_id='master_ball'"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM pokemon WHERE state='owned'"), 250)
        self.assertEqual(await self.rows('SELECT * FROM pokemon WHERE source_encounter_id=?',
                                        (encounter['encounter_id'],)), [])
        self.assertEqual(await self.rows('SELECT p,success,fled FROM catch_attempts'),
                         [dict(p=1.0, success=1, fled=0)])
        rolls.random.assert_not_called()

    async def test_unconfirmed_ordinary_ex_catch_is_auto_sent_after_900_s(self):
        from pokewalker.services import research
        encounter, session = await self.prepare()
        self.assertEqual((await self.throw(session))[0].status, 'caught')
        before = await self.snapshot()
        async def auto(now):
            return await self.writer.run(lambda conn: research.auto_send(conn, now, self.content))
        self.assertEqual(await auto(self.now + 899), 0)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await auto(self.now + 900), 1)
        pokemon, = await self.rows('SELECT * FROM pokemon WHERE source_encounter_id=?',
                                   (encounter['encounter_id'],))
        self.assertEqual((pokemon['state'], pokemon['pokemon_id']), ('sent', encounter['pokemon_id']))
        self.assertEqual(await self.scalar('SELECT acknowledged_at FROM encounters'), self.now + 900)
        family = next(i['family_id'] for i in self.content['identities'] if i['identity_id'] == '25:25')
        candy = next(r['quantity'] for r in before['candy'] if r['family_id'] == family)
        self.assertEqual(await self.scalar('SELECT quantity FROM candy WHERE family_id=?', (family,)), candy + 1)
        self.assertEqual(await self.rows('SELECT delta,reason FROM resource_ledger WHERE receipt_key=?',
                                        (f"research:auto:{encounter['encounter_id']}",)),
                         [dict(delta=1, reason='research_send')])
        after = await self.snapshot()
        self.assertEqual(await auto(self.now + 901), 0)
        self.assertEqual(await self.snapshot(), after)

    async def test_shiny_legendary_and_mythical_ex_catches_are_never_auto_sent(self):
        from pokewalker.services import research
        for identity_id, shiny in (('25:25', True), ('144:144', False), ('151:151', False)):
            with self.subTest(identity=identity_id, shiny=shiny):
                encounter, session = await self.prepare(identity_id, locks={'shiny': shiny})
                self.assertEqual((await self.throw(session))[0].status, 'caught')
                before = await self.snapshot()
                for elapsed in (900, 86400, 172800):
                    self.assertEqual(await self.writer.run(lambda conn: research.auto_send(
                        conn, self.now + elapsed, self.content)), 0)
                    self.assertEqual(await self.snapshot(), before)
                self.now = self.spawn_row['expires_at']
                await self.writer.run(lambda conn: self.raids().expire(conn, self.now))

    async def test_catch_committed_before_expiry_stays_readable_after_cleanup(self):
        encounter, session = await self.prepare('151:151')
        self.now = self.spawn_row['expires_at'] - 1
        result, _ = await self.throw(session)
        self.assertEqual(result.status, 'caught')
        before = await self.snapshot()
        self.now += 1
        await self.client()._sweep_once()
        for table in ('encounters', 'pokemon', 'catch_attempts', 'pokedex', 'candy', 'resource_ledger'):
            self.assertEqual(await self.rows(f'SELECT * FROM {table}'), before[table], table)
        self.assertEqual(await self.scalar('SELECT ended FROM world_spawns'), 1)
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])
        before = await self.snapshot()
        replay, rolls = await self.throw(session)
        self.assertEqual(replay, result)
        self.assertEqual(replay.encounter['encounter_id'], encounter['encounter_id'])
        self.assertEqual(await self.snapshot(), before)
        rolls.random.assert_not_called()

    async def test_throw_at_expiry_is_refused_and_spends_nothing(self):
        _, session = await self.prepare()
        self.now = self.spawn_row['expires_at']
        before, writes = await self.snapshot(), self.conn.total_changes
        result, rolls = await self.throw(session)
        self.assertEqual(result.status, 'expired')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(self.conn.total_changes, writes)
        rolls.random.assert_not_called()

    async def test_world_legendary_spawns_expires_and_respawns_beside_a_24_h_ex_raid(self):
        await self.prepare(hours=24)
        ex = dict(self.spawn_row)
        bot = self.client()
        first = await self.use()
        self.assertEqual(first['status'], 'spawned')
        self.assertEqual(await self.ticket(), 0)
        world = first['spawn']
        self.assertEqual(world['expires_at'], self.now + 3600)
        self.assertEqual((await self.join(world['spawn_id']))['status'], 'new')
        self.now = world['expires_at']
        await bot._sweep_once()
        self.assertEqual(await self.rows('SELECT ended FROM world_spawns WHERE spawn_id=?',
                                        (world['spawn_id'],)), [dict(ended=1)])
        self.assertEqual(await self.rows('SELECT * FROM world_spawns WHERE spawn_id=?', (ex['spawn_id'],)), [ex])
        second = await self.writer.run(lambda conn: self.raids().force_spawn(
            conn, 'g', 'moderator', 'coverage', self.now, self.rng, self.content, '789'))
        self.assertEqual(second['status'], 'spawned')
        self.assertNotEqual(second['spawn']['spawn_id'], world['spawn_id'])
        self.assertEqual([s['kind'] for s in await self.raids().live_spawns(self.conn, 'g', self.now)], ['world', 'ex'])
        self.assertEqual(await self.rows('SELECT * FROM world_spawns WHERE spawn_id=?', (ex['spawn_id'],)), [ex])
        self.now = second['spawn']['expires_at']
        await bot._sweep_once()
        self.assertEqual(await self.raids().live_spawns(self.conn, 'g', self.now), [ex])
        self.assertEqual((await self.join(ex['spawn_id']))['status'], 'joined')

    async def test_sweep_ends_ex_raid_at_exactly_expires_at(self):
        encounter, _ = await self.prepare(hours=24)
        bot = self.client()
        self.now = self.spawn_row['expires_at'] - 1
        await bot._sweep_once()
        self.assertEqual(await self.raids().live_spawns(self.conn, 'g', self.now), [self.spawn_row])
        self.assertEqual(await self.scalar('SELECT encounter_id FROM raid_participation'), encounter['encounter_id'])
        self.assertEqual(await self.scalar('SELECT state FROM encounters'), 'revealed')
        self.now += 1
        await bot._sweep_once()
        self.assertEqual(await self.scalar('SELECT ended FROM world_spawns'), 1)
        self.assertEqual(await self.raids().live_spawns(self.conn, 'g', self.now), [])
        self.assertEqual(await self.rows('SELECT * FROM encounters'), [])
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])
        self.assertEqual(await self.join(self.spawn_row['spawn_id']), {'status': 'none'})

    async def test_raids_off_mid_raid_keeps_the_live_ex_raid_and_skips_new_ones(self):
        await self.prepare(hours=24)
        await self.conn.execute("UPDATE guilds SET raids_enabled=0 WHERE guild_id='g'")
        self.now += 7200
        bot = self.client()
        await bot._sweep_once()
        self.assertEqual(await self.raids().live_spawns(self.conn, 'g', self.now), [self.spawn_row])
        self.assertEqual((await self.join(self.spawn_row['spawn_id']))['status'], 'joined')
        before = await self.snapshot()
        result = await self.send(send_id='off-send')
        self.assertEqual((result['status'], result['skipped']), ('nothing', {'raids_off': 1}))
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.use(), {'status': 'raids_off'})
        self.assertEqual(await self.ticket(), 1)
        self.assertEqual(await self.rows('SELECT * FROM world_spawns'), [self.spawn_row])
        self.now = self.spawn_row['expires_at']
        await bot._sweep_once()
        self.assertEqual(await self.scalar('SELECT ended FROM world_spawns'), 1)

    async def test_ex_encounter_stays_outside_the_three_encounter_queue(self):
        import sqlite3
        from pokewalker.services import profiles
        for n in range(3):
            await test_raids.RaidSchemaTests.encounter(self, self.pid, f'queued-{n}')
        encounter, _ = await self.prepare(hours=24)
        self.assertEqual(await profiles.queue_size(self.conn, self.pid), 3)
        self.assertEqual(await self.scalar('SELECT count(*) FROM encounters'), 4)
        self.assertEqual(encounter['raid_spawn_id'], self.spawn_row['spawn_id'])
        with self.assertRaises(sqlite3.IntegrityError):
            await test_raids.RaidSchemaTests.encounter(self, self.pid, 'fourth')
        self.assertEqual(await profiles.queue_size(self.conn, self.pid), 3)
