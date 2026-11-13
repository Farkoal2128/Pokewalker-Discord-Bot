"""C3 database contract: real SQLite transactions, no Discord or network."""

import asyncio
import importlib
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, patch


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.db = importlib.import_module("pokewalker.db")
        except ModuleNotFoundError:
            self.fail("M1.1 provider absent: durable transactions unavailable")
        cache = Path(__file__).resolve().parents[1] / "build" / "test-db"
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "game.sqlite3"
        self.conn = await self.db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)

    async def scalar(self, sql, args=(), conn=None):
        async with (conn or self.conn).execute(sql, args) as cursor:
            return (await cursor.fetchone())[0]

    async def profile(self, user="user", guild="guild"):
        await self.conn.execute("INSERT OR IGNORE INTO guilds(guild_id) VALUES (?)", (guild,))
        profile_id = str(uuid.uuid4())
        await self.conn.execute(
            "INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES (?,?,?,0)",
            (profile_id, guild, user))
        return profile_id

    async def test_queue_triggers_match_the_configured_encounter_queue(self):
        # Audit fix: stepping, check-in and the home screen read the cap; SQL triggers cannot.
        from content.balance import limits
        sql = await self.conn.execute_fetchall(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'encounter_queue_%'")
        self.assertEqual(len(sql), 2)
        for (text,) in sql:
            self.assertTrue(text.split("BEGIN")[0].rstrip().endswith(f")>={limits()['encounter_queue']}"), text)

    async def test_deletion_cascade_lookups_use_indexes(self):
        # Audit fix: a delete-data cascade must not scan whole child tables per deleted row.
        for table, column in (("catch_attempts", "receipt_key"), ("gym_deployments", "pokemon_uid"),
                              ("resource_ledger", "profile_id")):
            plan = await self.conn.execute_fetchall(f"EXPLAIN QUERY PLAN SELECT 1 FROM {table} WHERE {column}='x'")
            with self.subTest(table=table):
                self.assertIn("USING", " ".join(row[-1] for row in plan))

    async def test_owned_pokemon_counts_use_the_profile_index(self):
        # Audit fix: per-throw storage counts must not scan every server's Pokemon.
        plan = await self.conn.execute_fetchall(
            "EXPLAIN QUERY PLAN SELECT count(*) FROM pokemon WHERE profile_id='p' AND state='owned'")
        self.assertIn("pokemon_profile_state", " ".join(row[-1] for row in plan))

    async def test_version_check_table(self):
        for version, expected in [
            ((3, 44, 5), False), ((3, 44, 6), True), ((3, 44, 99), True),
            ((3, 45, 0), False), ((3, 50, 6), False), ((3, 50, 7), True),
            ((3, 50, 99), True), ((3, 51, 0), False), ((3, 51, 2), False),
            ((3, 51, 3), True), ((3, 52, 0), True), ((4, 0, 0), True),
        ]:
            with self.subTest(version=version):
                self.assertIs(self.db.check_sqlite_version(version), expected)

    async def test_open_refuses_old_sqlite(self):
        absent = Path(self.temp.name) / "refused.sqlite3"
        with patch.object(self.db.sqlite3, "sqlite_version_info", (3, 45, 1)):
            with self.assertRaisesRegex(RuntimeError, "SQLite"):
                await self.db.open_db(absent)
        self.assertFalse(absent.exists())

    async def test_allow_unpatched_warns(self):
        with patch.object(self.db.sqlite3, "sqlite_version_info", (3, 45, 1)):
            with self.assertLogs("pokewalker.db", level="WARNING") as logs:
                conn = await self.db.open_db(self.path, allow_unpatched=True)
            await conn.close()
        self.assertIn("unpatched", " ".join(logs.output).lower())

    async def test_pragmas_applied(self):
        for pragma, expected in {"journal_mode": "wal", "synchronous": 2,
                                 "secure_delete": 1, "foreign_keys": 1,
                                 "busy_timeout": 5000}.items():
            with self.subTest(pragma=pragma):
                self.assertEqual(await self.scalar(f"PRAGMA {pragma}"), expected)

    async def test_migrations_apply_once(self):
        supported = len(list(self.db.MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")))
        profile_id = await self.profile()
        conn = await self.db.open_db(self.path)
        try:
            self.assertEqual(await self.scalar("PRAGMA user_version", conn=conn), supported)
            self.assertEqual(await self.scalar("SELECT profile_id FROM profiles", conn=conn),
                             profile_id)
            self.assertEqual(await self.scalar("SELECT count(*) FROM pragma_foreign_key_check"), 0)
            for table in ("guilds", "guild_channels", "profiles", "restrictions", "mod_audit",
                          "step_events", "encounters", "catch_attempts", "pokemon", "inventory",
                          "candy", "pokedex", "reactions", "action_receipts", "resource_ledger",
                          "sessions"):
                await conn.execute(f"SELECT * FROM {table} LIMIT 0")
        finally:
            await conn.close()

    async def test_newer_database_refused(self):
        supported = len(list(self.db.MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")))
        await self.conn.execute(f"PRAGMA user_version={supported + 1}")
        with self.assertRaisesRegex(RuntimeError, "newer"):
            await self.db.open_db(self.path)

    async def test_failed_migration_rolls_back_schema_and_version(self):
        migrations = Path(self.temp.name) / "migrations"
        migrations.mkdir()
        (migrations / "0001_broken.sql").write_text(
            "CREATE TABLE partial(value); INSERT INTO absent VALUES(1);", encoding="utf-8")
        broken_path = Path(self.temp.name) / "broken.sqlite3"
        with patch.object(self.db, "MIGRATIONS", migrations):
            with self.assertRaises(sqlite3.OperationalError):
                await self.db.open_db(broken_path)
        with closing(sqlite3.connect(broken_path)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master").fetchall(), [])

    async def test_migration_numbering_gap_refused(self):
        migrations = Path(self.temp.name) / "gap"
        migrations.mkdir()
        (migrations / "0002_gap.sql").write_text("CREATE TABLE unexpected(value);", encoding="utf-8")
        with patch.object(self.db, "MIGRATIONS", migrations):
            with self.assertRaisesRegex(RuntimeError, "numbering"):
                await self.db.open_db(Path(self.temp.name) / "gap.sqlite3")

    async def test_writer_serializes_jobs_no_interleave(self):
        writer = self.db.Writer(self.conn)
        self.addAsyncCleanup(writer.close)
        order = []

        async def job(conn, number):
            self.assertTrue(conn.in_transaction)
            order.append((number, "start"))
            await conn.execute("INSERT INTO guilds(guild_id) VALUES (?)", (str(number),))
            await asyncio.sleep(0.01)
            order.append((number, "end"))
            return number

        results = await asyncio.gather(*(writer.run(lambda conn, i=i: job(conn, i))
                                         for i in range(4)))
        self.assertEqual(results, [0, 1, 2, 3])
        self.assertEqual(order, [(i, phase) for i in range(4) for phase in ("start", "end")])
        self.assertFalse(self.conn.in_transaction)

    async def test_writer_rolls_back_on_exception(self):
        writer = self.db.Writer(self.conn)
        self.addAsyncCleanup(writer.close)

        async def fail(conn):
            await conn.execute("INSERT INTO guilds(guild_id) VALUES ('failed')")
            raise ValueError("job failed")

        with self.assertRaisesRegex(ValueError, "job failed"):
            await writer.run(fail)
        self.assertEqual(await writer.run(lambda conn: self.scalar(
            "SELECT count(*) FROM guilds", conn=conn)), 0)

    async def test_post_commit_observer_is_synchronous_and_failure_never_changes_commit(self):
        writer = self.db.Writer(self.conn)
        self.addAsyncCleanup(writer.close)
        observed = []
        async def job(conn):
            await conn.execute("INSERT OR REPLACE INTO guilds(guild_id) VALUES ('observed')")
            return 42
        def observe(result):
            self.assertFalse(self.conn.in_transaction)
            observed.append(result)
        self.assertEqual(await writer.run(job, after_commit=observe), 42)
        self.assertEqual(observed, [42])
        for error in (ValueError('private'), asyncio.CancelledError(), SystemExit(75)):
            def fail(result):
                raise error
            with self.assertLogs('pokewalker.db', 'ERROR') as logged:
                self.assertEqual(await writer.run(job, after_commit=fail), 42)
            self.assertEqual(logged.output, ['ERROR:pokewalker.db:Post-commit observer failed'])
            self.assertEqual(await writer.run(lambda conn: self.scalar('SELECT count(*) FROM guilds', conn=conn)), 1)
        observer = AsyncMock()
        with self.assertRaisesRegex(TypeError, 'synchronous'):
            await writer.run(job, after_commit=observer)
        observer.assert_not_called()

    async def test_post_commit_observer_awaitable_is_closed_without_awaiting(self):
        writer = self.db.Writer(self.conn)
        self.addAsyncCleanup(writer.close)
        invoked = []
        async def observer():
            invoked.append(True)
        async def job(conn):
            return 'committed'
        with self.assertLogs('pokewalker.db', 'ERROR') as logged:
            self.assertEqual(await writer.run(job, after_commit=lambda result: observer()), 'committed')
        self.assertEqual(invoked, [])
        self.assertEqual(logged.output, ['ERROR:pokewalker.db:Post-commit observer failed'])
        self.assertEqual(await writer.run(job), 'committed')

    async def test_post_commit_observer_not_called_on_job_or_commit_failure(self):
        writer = self.db.Writer(self.conn)
        self.addAsyncCleanup(writer.close)
        observed = []
        async def fail(conn):
            raise ValueError('job failed')
        with self.assertRaisesRegex(ValueError, 'job failed'):
            await writer.run(fail, after_commit=observed.append)
        async def job(conn):
            await conn.execute("INSERT INTO guilds(guild_id) VALUES ('failed')")
        with patch.object(self.conn, 'commit', AsyncMock(side_effect=RuntimeError('commit failed'))):
            with self.assertRaisesRegex(RuntimeError, 'commit failed'):
                await writer.run(job, after_commit=observed.append)
        self.assertEqual(observed, [])
        self.assertEqual(await self.scalar('SELECT count(*) FROM guilds'), 0)

    async def test_writer_close_drains_and_refuses_new_jobs(self):
        writer = self.db.Writer(self.conn)
        started, release = asyncio.Event(), asyncio.Event()

        async def job(conn):
            started.set()
            await release.wait()
            await conn.execute("INSERT INTO guilds(guild_id) VALUES ('done')")

        pending = asyncio.create_task(writer.run(job))
        await started.wait()
        closing = asyncio.create_task(writer.close())
        await asyncio.sleep(0)
        self.assertFalse(closing.done())
        with self.assertRaisesRegex(RuntimeError, "closed"):
            await writer.run(job)
        release.set()
        await pending
        await closing
        await writer.close()
        self.assertEqual(await self.scalar("SELECT count(*) FROM guilds"), 1)

    async def test_writer_rollback_failure_fails_current_queued_and_future_jobs(self):
        writer = self.db.Writer(self.conn)

        async def cleanup():
            await asyncio.gather(writer.close(), return_exceptions=True)

        self.addAsyncCleanup(cleanup)
        started, release = asyncio.Event(), asyncio.Event()
        job_failure = ValueError("job failed before rollback")
        rollback_failure = sqlite3.OperationalError("rollback unavailable")
        queued_job = AsyncMock(return_value="must not execute")

        async def fail(conn):
            await conn.execute("INSERT INTO guilds(guild_id) VALUES ('uncommitted')")
            started.set()
            await release.wait()
            raise job_failure

        with patch.object(self.conn, "rollback", AsyncMock(side_effect=rollback_failure)):
            current = asyncio.create_task(writer.run(fail))
            await started.wait()
            queued = asyncio.create_task(writer.run(queued_job))
            await asyncio.sleep(0)
            release.set()
            results = await asyncio.wait_for(
                asyncio.gather(current, queued, return_exceptions=True), timeout=1)
            for result in results:
                self.assertIs(result, rollback_failure)
                self.assertIs(result.__cause__, job_failure)
            queued_job.assert_not_awaited()
            with self.assertRaisesRegex(RuntimeError, "closed") as refused:
                await writer.run(queued_job)
            self.assertIs(refused.exception.__cause__, rollback_failure)
            await asyncio.wait_for(writer.close(), timeout=1)
            await writer.close()
        with self.assertRaises(ValueError):
            await self.conn.execute("SELECT 1")
        reader = await self.db.open_reader(self.path)
        try:
            self.assertEqual(await self.scalar("SELECT count(*) FROM guilds", conn=reader), 0)
        finally:
            await reader.close()

    async def test_cancelled_waiter_does_not_cancel_committed_job(self):
        writer = self.db.Writer(self.conn)
        started, release = asyncio.Event(), asyncio.Event()

        async def job(conn):
            started.set()
            await release.wait()
            await conn.execute("INSERT INTO guilds(guild_id) VALUES ('committed')")

        pending = asyncio.create_task(writer.run(job))
        await started.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        release.set()
        await writer.close()
        self.assertEqual(await self.scalar("SELECT count(*) FROM guilds"), 1)

    async def test_writer_abort_rolls_back_and_fails_queued_jobs(self):
        writer = self.db.Writer(self.conn)
        started = asyncio.Event()
        queued_job = AsyncMock()

        async def active(conn):
            await conn.execute("INSERT INTO guilds(guild_id) VALUES ('aborted')")
            started.set()
            await asyncio.Future()

        current = asyncio.create_task(writer.run(active))
        await started.wait()
        queued = asyncio.create_task(writer.run(queued_job))
        await asyncio.sleep(0)
        await writer.abort()
        await writer.abort()
        results = await asyncio.gather(current, queued, return_exceptions=True)
        self.assertIsInstance(results[0], asyncio.CancelledError)
        self.assertIsInstance(results[1], RuntimeError)
        queued_job.assert_not_awaited()
        self.assertEqual(await self.scalar("SELECT count(*) FROM guilds"), 0)
        self.assertFalse(self.conn.in_transaction)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            await writer.run(queued_job)
        await writer.close()

    async def test_writer_abort_idle_is_safe_to_close(self):
        writer = self.db.Writer(self.conn)
        await asyncio.sleep(0)
        await writer.abort()
        await writer.abort()
        await writer.close()
        self.assertEqual(await self.scalar("SELECT 1"), 1)

    async def test_writer_concurrent_aborts_do_not_interrupt_rollback(self):
        writer = self.db.Writer(self.conn)
        started, rolling_back, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        rollback = self.conn.rollback

        async def job(conn):
            await conn.execute("INSERT INTO guilds(guild_id) VALUES ('aborted')")
            started.set()
            await asyncio.Future()

        async def delayed_rollback():
            rolling_back.set()
            await release.wait()
            await rollback()

        current = asyncio.create_task(writer.run(job))
        await started.wait()
        with patch.object(self.conn, "rollback", side_effect=delayed_rollback):
            first = asyncio.create_task(writer.abort())
            await rolling_back.wait()
            second = asyncio.create_task(writer.abort())
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(first, second)
        await asyncio.gather(current, return_exceptions=True)
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(await self.scalar("SELECT count(*) FROM guilds"), 0)

    async def test_reader_is_separate_read_only_and_sees_only_commits(self):
        reader = await self.db.open_reader(self.path)
        self.addAsyncCleanup(reader.close)
        self.assertIsNot(reader, self.conn)
        await self.conn.execute("BEGIN IMMEDIATE")
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('pending')")
        self.assertEqual(await self.scalar("SELECT count(*) FROM guilds", conn=reader), 0)
        await self.conn.commit()
        self.assertEqual(await self.scalar("SELECT count(*) FROM guilds", conn=reader), 1)
        with self.assertRaises(sqlite3.OperationalError):
            await reader.execute("DELETE FROM guilds")

    async def test_receipt_replay_returns_saved_result(self):
        profile_id = await self.profile()
        writer = self.db.Writer(self.conn)
        self.addAsyncCleanup(writer.close)
        calls = []

        async def compute(conn):
            calls.append(True)
            await conn.execute("UPDATE profiles SET stardust=stardust+100 WHERE profile_id=?",
                               (profile_id,))
            return {"dust": 100}, [{"profile_id": profile_id, "resource": "stardust",
                                    "delta": 100, "reason": "catch"}]

        async def action(conn):
            return await self.db.with_receipt(conn, "catch:one", "catch", compute)

        self.assertEqual(await writer.run(action), {"dust": 100})
        self.assertEqual(await writer.run(action), {"dust": 100})
        self.assertEqual(calls, [True])
        self.assertEqual(await self.scalar("SELECT stardust FROM profiles"), 100)
        self.assertEqual(await self.scalar("SELECT count(*) FROM resource_ledger"), 1)
        with self.assertRaisesRegex(ValueError, "action"):
            await writer.run(lambda conn: self.db.with_receipt(conn, "catch:one", "run", compute))

    async def test_receipt_failure_rolls_back_mutation_and_receipt(self):
        profile_id = await self.profile()
        writer = self.db.Writer(self.conn)
        self.addAsyncCleanup(writer.close)

        async def compute(conn):
            await conn.execute("UPDATE profiles SET stardust=99 WHERE profile_id=?", (profile_id,))
            return {"ok": True}, [{"profile_id": "missing", "resource": "dust",
                                   "delta": 99, "reason": "fixture"}]

        with self.assertRaises(sqlite3.IntegrityError):
            await writer.run(lambda conn: self.db.with_receipt(conn, "bad", "catch", compute))
        self.assertEqual(await self.scalar("SELECT stardust FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts"), 0)
        with self.assertRaisesRegex(RuntimeError, "transaction"):
            await self.db.with_receipt(self.conn, "outside", "catch", compute)

    async def test_profile_guild_user_unique(self):
        await self.profile()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.profile()
        await self.profile(guild="other")
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 2)

    async def test_restrictions_survive_profile_deletion(self):
        profile_id = await self.profile()
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,excluded,share_banned) "
                                "VALUES ('guild','user',1,1,1)")
        await self.conn.execute("DELETE FROM profiles WHERE profile_id=?", (profile_id,))
        new_id = await self.profile()
        self.assertNotEqual(profile_id, new_id)
        self.assertEqual(await self.scalar("SELECT paused+excluded+share_banned FROM restrictions"), 3)

    async def encounter(self, profile_id, state="queued"):
        encounter_id = str(uuid.uuid4())
        await self.conn.execute(
            "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,"
            "iv_defense,iv_stamina,gender,shiny,tier,route_id,content_version,created_at,state) "
            "VALUES (?,?,1,2,0,0,0,'male',0,'common','refreshing_field','fixture',0,?)",
            (encounter_id, profile_id, state))
        return encounter_id

    async def test_queue_limit_on_insert_and_update(self):
        profile_id = await self.profile()
        for state in ("queued", "revealed", "queued"):
            await self.encounter(profile_id, state)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.encounter(profile_id)
        terminal = await self.encounter(profile_id, "ran")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("UPDATE encounters SET state='revealed' WHERE encounter_id=?",
                                    (terminal,))
        other = await self.profile("other")
        source = await self.encounter(other)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("UPDATE encounters SET profile_id=? WHERE encounter_id=?",
                                    (profile_id, source))

    async def test_meters_require_integer_hundredths(self):
        profile_id = await self.profile()
        for meter in ("encounter_meter_c", "find_meter_c", "companion_meter_c"):
            for value in (-1, 0.5):
                with self.subTest(meter=meter, value=value), self.assertRaises(sqlite3.IntegrityError):
                    await self.conn.execute(f"UPDATE profiles SET {meter}=? WHERE profile_id=?",
                                            (value, profile_id))
        await self.conn.execute("UPDATE profiles SET encounter_meter_c=25 WHERE profile_id=?",
                                (profile_id,))
        self.assertEqual(await self.scalar("SELECT encounter_meter_c FROM profiles"), 25)

    async def test_catch_attempt_and_source_encounter_unique(self):
        profile_id = await self.profile()
        encounter_id = await self.encounter(profile_id)
        attempt = (encounter_id, 0, "poke_ball", 0.25, 1, 0, 0)
        sql = ("INSERT INTO catch_attempts(encounter_id,ordinal,ball,p,success,fled,created_at) "
               "VALUES (?,?,?,?,?,?,?)")
        await self.conn.execute(sql, attempt)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute(sql, attempt)
        sql = ("INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
               "iv_stamina,gender,shiny,origin,source_encounter_id,content_version,caught_at) "
               "VALUES (?,?,1,2,0,0,0,'male',0,'catch',?,'fixture',0)")
        pokemon_uid = str(uuid.uuid4())
        await self.conn.execute(sql, (pokemon_uid, profile_id, encounter_id))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute(sql, (str(uuid.uuid4()), profile_id, encounter_id))
        await self.conn.execute("UPDATE profiles SET companion_uid=? WHERE profile_id=?",
                                (pokemon_uid, profile_id))
        await self.conn.execute("DELETE FROM profiles WHERE profile_id=?", (profile_id,))
        for table in ("profiles", "pokemon", "encounters", "catch_attempts"):
            self.assertEqual(await self.scalar(f"SELECT count(*) FROM {table}"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM pragma_foreign_key_check"), 0)

    async def test_secure_delete_removes_fixture_bytes_after_checkpoint(self):
        marker = "private-fixture-6b03dc23-" * 50
        await self.profile(user=marker)
        await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.assertIn(marker.encode(), self.path.read_bytes())
        await self.conn.execute("DELETE FROM profiles")
        await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.assertNotIn(marker.encode(), self.path.read_bytes())
        backup_path = Path(self.temp.name) / "backup.sqlite3"
        with closing(sqlite3.connect(backup_path)) as backup:
            await self.conn.backup(backup)
        self.assertNotIn(marker.encode(), backup_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
