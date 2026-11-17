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
