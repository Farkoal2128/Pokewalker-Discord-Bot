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
