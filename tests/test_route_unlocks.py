"""C5 lifetime route authorization through the real writer and durable router."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from content.balance import load_table
from pokewalker import db
from pokewalker.services import profiles, stepping
import test_route as route_tests


class RouteUnlockTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = route_tests.RouteTests.asyncSetUp
    interaction = route_tests.RouteTests.interaction
    rows = route_tests.RouteTests.rows
    open = route_tests.RouteTests.open
    click = route_tests.RouteTests.click
    enroll = route_tests.RouteTests.enroll
    ready = route_tests.RouteTests.ready
    current = route_tests.RouteTests.current
    act = route_tests.RouteTests.act
    snapshot = route_tests.RouteTests.snapshot
    seed_steps = route_tests.RouteTests.seed_steps

    def options(self, rendered):
        return [option.value for item in rendered['view'].children
                if hasattr(item, 'options') for option in item.options]

    async def test_two_free_routes_and_six_locked_at_zero_steps(self):
        session = await self.ready()
        rendered, _ = await self.act(session, 'route')
        self.assertEqual(self.options(rendered), ['refreshing_field', 'noisy_forest'])
        self.assertEqual([field.name for field in rendered['embed'].fields], [
            'Refreshing Field · Current', 'Noisy Forest',
            'Rugged Road · Locked — 1000 steps', 'Beautiful Beach · Locked — 2500 steps',
            'Suburban Area · Locked — 5000 steps', 'Dim Cave · Locked — 8000 steps',
            'Blue Lake · Locked — 12000 steps', 'Volcano Path · Locked — 18000 steps'])

    async def test_threshold_boundary_999_99_locked_1000_00_unlocked(self):
        session = await self.ready()
        await self.seed_steps(99_999)
        rendered, session = await self.act(session, 'route')
        self.assertNotIn('rugged_road', self.options(rendered))
        self.assertIn('Rugged Road · Locked — 1 steps', [f.name for f in rendered['embed'].fields])
        refused = await self.click(session, 'route_pick', ['rugged_road'])
        self.assertEqual(refused.followup.send.await_args.args[0], 'Walk 1 more steps to unlock Rugged Road')
        await self.seed_steps(1, message_id='last-hundredth')
        rendered, session = await self.act(session, 'route_pick', ['rugged_road'])
        self.assertIn('rugged_road', self.options(rendered))
        self.assertIn('Rugged Road · Current', [f.name for f in rendered['embed'].fields])

    async def test_locked_route_absent_from_select_and_refused_in_transaction(self):
        session = await self.ready()
        rendered, session = await self.act(session, 'route')
        self.assertNotIn('dim_cave', self.options(rendered))
        before = await self.snapshot()
        refused = await self.click(session, 'route_pick', ['dim_cave'])
        refused.edit_original_response.assert_not_awaited()
        self.assertEqual(refused.followup.send.await_args.args[0], 'Walk 8000 more steps to unlock Dim Cave')
        self.assertTrue(refused.followup.send.await_args.kwargs['ephemeral'])
        self.assertEqual(await self.snapshot(), before)
        # Progress committed after rendering must be re-read by the selection job.
        await self.seed_steps(800_000)
        rendered, _ = await self.act(session, 'route_pick', ['dim_cave'])
        self.assertIn('Dim Cave · Current', [f.name for f in rendered['embed'].fields])

    async def test_volcano_path_locked_at_17999_99_unlocked_at_18000(self):
        session = await self.ready()
        await self.seed_steps(1_799_999)
        rendered, session = await self.act(session, 'route')
        self.assertNotIn('volcano_path', self.options(rendered))
        self.assertIn('Volcano Path · Locked — 1 steps', [f.name for f in rendered['embed'].fields])
        refused = await self.click(session, 'route_pick', ['volcano_path'])
        self.assertEqual(refused.followup.send.await_args.args[0], 'Walk 1 more steps to unlock Volcano Path')
        await self.seed_steps(1, message_id='last-hundredth')
        rendered, _ = await self.act(session, 'route_pick', ['volcano_path'])
        self.assertEqual(len(self.options(rendered)), 8)
        self.assertIn('Volcano Path · Current', [f.name for f in rendered['embed'].fields])

    async def test_unlock_counts_only_this_servers_steps(self):
        session = await self.ready()
        other = await self.writer.run(lambda conn: profiles.enroll(
            conn, 999, 456, 1, self.bot.content, random.Random(8), datetime.now(timezone.utc)))
        await self.seed_steps(profile_id=other['profile_id'], message_id='other-server')
        rendered, session = await self.act(session, 'route')
        self.assertEqual(self.options(rendered), ['refreshing_field', 'noisy_forest'])
        refused = await self.click(session, 'route_pick', ['rugged_road'])
        self.assertIn('Walk 1000 more steps', refused.followup.send.await_args.args[0])
        self.assertEqual(await profiles.lifetime_steps_c(self.conn, self.profile['profile_id']), 0)
        self.assertEqual(await profiles.lifetime_steps_c(self.conn, other['profile_id']), 1_800_000)

    async def test_paused_profile_lifetime_unchanged_by_zero_award_events(self):
        session = await self.ready()
        await self.seed_steps(99_999)
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('123','456',1)"))
        await self.writer.run(lambda conn: stepping.credit_message(
            conn, self.profile, ['fresh', 'paused', 'message', 'words'],
            datetime.fromtimestamp(1000, timezone.utc), 'paused-message', '789',
            content=self.bot.content, cache=stepping.DigestCache()))
        event = (await self.rows("SELECT * FROM step_events WHERE message_id='paused-message'"))[0]
        self.assertEqual((event['reason'], event['awarded_c']), ('paused', 0))
        self.assertEqual(await profiles.lifetime_steps_c(self.conn, self.profile['profile_id']), 99_999)
        rendered, _ = await self.act(session, 'route')
        self.assertNotIn('rugged_road', self.options(rendered))

    async def test_locked_current_route_remains_visible_without_backfill(self):
        session = await self.ready()
        await self.writer.run(lambda conn: conn.execute("UPDATE profiles SET route_id='volcano_path'"))
        rendered, _ = await self.act(session, 'route')
        self.assertEqual(self.options(rendered), ['refreshing_field', 'noisy_forest', 'volcano_path'])
        self.assertIn('Volcano Path · Current · Locked — 18000 steps',
                      [f.name for f in rendered['embed'].fields])
        self.assertEqual((await self.rows('SELECT route_id FROM profiles'))[0]['route_id'], 'volcano_path')

    async def test_every_authored_threshold_rechecks_inside_pick(self):
        session = await self.ready()
        for index, route in enumerate(load_table('routes')['routes'][2:]):
            with self.subTest(route=route['id']):
                await self.writer.run(lambda conn: conn.execute('DELETE FROM step_events'))
                await self.seed_steps(route['unlock_steps'] * 100 - 1, message_id=f'boundary-{index}')
                refused = await self.click(session, 'route_pick', [route['id']])
                self.assertIn('Walk 1 more steps', refused.followup.send.await_args.args[0])
                await self.seed_steps(1, message_id=f'unlock-{index}')
                _, session = await self.act(session, 'route_pick', [route['id']])
                self.assertEqual((await self.rows('SELECT route_id FROM profiles'))[0]['route_id'], route['id'])


class RouteUnlockBackfillTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache = Path('build/test-db')
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'v12.sqlite3'
        self.legacy = sqlite3.connect(self.path)
        self.addCleanup(self.legacy.close)
        for migration in sorted(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))[:12]:
            self.legacy.executescript(migration.read_text(encoding='utf-8'))
        self.legacy.execute('PRAGMA user_version=12')
        self.legacy.commit()

    def profile(self, profile_id, route, awards=(), guild='guild'):
        self.legacy.execute('INSERT OR IGNORE INTO guilds(guild_id) VALUES (?)', (guild,))
        self.legacy.execute(
            'INSERT INTO profiles(profile_id,guild_id,user_id,route_id,created_at) VALUES (?,?,?,?,0)',
            (profile_id, guild, 'same-user', route))
        for index, award in enumerate(awards):
            self.legacy.execute(
                "INSERT INTO step_events VALUES (?,?,'channel',1,1,0,?,'credited',0)",
                (f'{profile_id}-{index}', profile_id, award))
        self.legacy.commit()

    async def upgrade(self):
        self.legacy.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)

    async def routes(self):
        rows = await self.conn.execute_fetchall('SELECT profile_id,route_id FROM profiles')
        return dict(rows)

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as conn:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            return {name: conn.execute(f'SELECT * FROM {name} ORDER BY rowid').fetchall()
                    for name, in tables.fetchall()}

    async def test_backfill_moves_locked_existing_player_to_refreshing_field(self):
        self.profile('locked', 'volcano_path', (1_799_999,))
        await self.upgrade()
        self.assertEqual(await self.routes(), {'locked': 'refreshing_field'})

    async def test_backfill_keeps_unlocked_existing_player(self):
        self.profile('unlocked', 'dim_cave', (400_000, 400_000, 0))
        await self.upgrade()
        self.assertEqual(await self.routes(), {'unlocked': 'dim_cave'})

    async def test_backfill_keeps_free_route_players(self):
        self.profile('field', 'refreshing_field')
        self.profile('forest', 'noisy_forest', guild='other')
        await self.upgrade()
        self.assertEqual(await self.routes(), {'field': 'refreshing_field', 'forest': 'noisy_forest'})

    async def test_backfill_leaves_queued_and_revealed_encounters_route_id_frozen(self):
        self.profile('locked', 'volcano_path', (100,))
        for state in ('queued', 'revealed'):
            self.legacy.execute(
                "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,"
                "iv_defense,iv_stamina,gender,shiny,tier,route_id,content_version,created_at,state) "
                "VALUES (?,'locked',1,2,0,0,0,'male',0,'Common','volcano_path','fixture',0,?)",
                (state, state))
        self.legacy.execute('UPDATE profiles SET encounter_meter_c=123,find_meter_c=456,'
                            'companion_meter_c=789,stardust=42,revision=7')
        self.legacy.execute("INSERT INTO inventory VALUES ('locked','poke_ball',3)")
        self.legacy.execute("INSERT INTO action_receipts(key,action,result,created_at,profile_id) "
                            "VALUES ('fixture','fixture','{}',0,'locked')")
        self.legacy.execute("INSERT INTO resource_ledger VALUES ('fixture',0,'locked','item',"
                            "'poke_ball',3,'fixture')")
        # Construct the expected full database with only the current route changed.
        self.legacy.execute("UPDATE profiles SET route_id='refreshing_field'")
        self.legacy.commit()
        expected = self.snapshot()
        schema = self.legacy.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name').fetchall()
        self.legacy.execute("UPDATE profiles SET route_id='volcano_path'")
        self.legacy.commit()
        migrations = Path(self.temp.name) / 'migrations'
        migrations.mkdir()
        for migration in sorted(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))[:13]:
            (migrations / migration.name).write_bytes(migration.read_bytes())
        with patch.object(db, 'MIGRATIONS', migrations):
            await self.upgrade()
        self.assertEqual((await self.conn.execute_fetchall('PRAGMA user_version'))[0][0], 13)
        self.assertEqual(self.snapshot(), expected)
        rows = await self.conn.execute_fetchall('SELECT type,name,sql FROM sqlite_master ORDER BY name')
        self.assertEqual([tuple(row) for row in rows], schema)
        frozen = await self.conn.execute_fetchall('SELECT state,route_id FROM encounters ORDER BY state')
        self.assertEqual([tuple(row) for row in frozen],
                         [('queued', 'volcano_path'), ('revealed', 'volcano_path')])
        self.assertEqual(await self.conn.execute_fetchall('PRAGMA foreign_key_check'), [])

    async def test_backfill_counts_only_this_servers_steps(self):
        self.profile('here', 'volcano_path', (1_799_999,))
        self.profile('there', 'volcano_path', (1_800_000,), guild='other')
        await self.upgrade()
        self.assertEqual(await self.routes(), {'here': 'refreshing_field', 'there': 'volcano_path'})

    async def test_backfill_second_run_changes_nothing(self):
        self.profile('locked', 'volcano_path')
        self.profile('unlocked', 'dim_cave', (800_000,), guild='other')
        await self.upgrade()
        self.assertEqual(await self.routes(), {'locked': 'refreshing_field', 'unlocked': 'dim_cave'})
        before = self.snapshot()
        await self.conn.executescript(
            (db.MIGRATIONS / '0013_route_unlock_backfill.sql').read_text(encoding='utf-8'))
        self.assertEqual(self.snapshot(), before)
        changes = await self.conn.execute_fetchall('SELECT changes()')
        self.assertEqual(changes[0][0], 0)

    async def test_backfill_thresholds_equal_routes_json_unlock_steps(self):
        expected = {}
        for route in load_table('routes')['routes']:
            threshold = route['unlock_steps'] * 100
            for label, awarded in (('below', max(0, threshold - 1)), ('exact', threshold)):
                profile_id = f"{route['id']}-{label}"
                self.profile(profile_id, route['id'], (awarded,), guild=profile_id)
                expected[profile_id] = 'refreshing_field' if awarded < threshold else route['id']
        await self.upgrade()
        self.assertEqual(await self.routes(), expected)

    async def test_migration_applies_once_and_user_version_advances(self):
        supported = len(list(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql')))
        self.profile('locked', 'volcano_path')
        await self.upgrade()
        version = await self.conn.execute_fetchall('PRAGMA user_version')
        self.assertEqual(version[0][0], supported)
        self.assertEqual(await self.routes(), {'locked': 'refreshing_field'})
        await self.conn.execute("UPDATE profiles SET route_id='volcano_path'")
        await self.conn.close()
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.assertEqual(await self.routes(), {'locked': 'volcano_path'})
        version = await self.conn.execute_fetchall('PRAGMA user_version')
        self.assertEqual(version[0][0], supported)
