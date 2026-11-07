"""D28 deletion: real writer transactions and external write-ahead durability."""

import asyncio
from contextlib import closing
import importlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from pokewalker.config import Secret, Settings
from pokewalker.db import MIGRATIONS, Writer, open_db, with_receipt
from pokewalker.services import marker_log


class DeletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache = Path("build/test-deletion")
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "game.sqlite3"
        self.path = Path(self.temp.name) / "markers.jsonl"
        marker_log.create_empty(self.path)
        self.conn = await open_db(self.db_path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('1'),('9')")
        self.profile_id = await self.profile()

    def service(self):
        self.assertIsNotNone(importlib.util.find_spec("pokewalker.services.deletion"),
                             "M4.1b deletion service must exist")
        return importlib.import_module("pokewalker.services.deletion")

    async def scalar(self, sql, args=()):
        async with self.conn.execute(sql, args) as cursor:
            return (await cursor.fetchone())[0]

    async def profile(self, guild="1", user="2"):
        profile_id = str(uuid4())
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES (?,?,?,0)", (profile_id, guild, user))
        return profile_id

    async def run_marker(self, kind="delete", authorize=None, **fields):
        return await self.service().run_marker(
            self.writer, self.path, authorize, kind=kind, guild_id="1", user_id="2",
            profile_id=self.profile_id, now=100, **fields)

    def records(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    async def test_marker_fsynced_before_delete_and_has_marker_id(self):
        service = self.service()
        apply = service.apply
        synced = []
        fsync = os.fsync

        def observe_sync(fd):
            synced.append(self.path.read_bytes())
            fsync(fd)

        async def observe(conn, states):
            self.assertEqual(len(synced), 1)
            self.assertEqual(json.loads(synced[0]), self.records()[0])
            self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
            return await apply(conn, states)

        with patch("os.fsync", side_effect=observe_sync), \
                patch.object(service, "apply", side_effect=observe):
            marker = await self.run_marker()
        self.assertEqual(UUID(marker["marker_id"]).version, 4)
        self.assertEqual(self.records(), [marker])
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)

    async def test_delete_removes_own_reactions_after_commit(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        import discord
        from pokewalker.services.reactions import EMOJI, ReactionService
        other = await self.profile("9", "2")
        await self.conn.executemany(
            "INSERT INTO reactions(message_id,profile_id,channel_id,desired,actual,created_at) VALUES (?,?,?,?,?,0)",
            [("11", self.profile_id, "21", "add", "added"), ("12", self.profile_id, "22", "remove", "added"),
             ("13", other, "23", "add", "added")])
        removed = []

        def message(channel_id):
            async def remove(emoji, user):
                self.assertFalse(self.conn.in_transaction, "Discord I/O must follow commit")
                removed.append((channel_id, int(target.id), emoji, user))
                if channel_id == 22:
                    raise discord.NotFound(Mock(status=404), "gone")
            target = Mock()
            target.remove_reaction = remove
            return SimpleNamespace(get_partial_message=lambda message_id: target.configure_mock(id=message_id) or target)

        bot = SimpleNamespace(writer=self.writer, user=object(), get_partial_messageable=message)
        await self.service().run_marker(self.writer, self.path, kind="delete", guild_id="1", user_id="2",
                                        profile_id=self.profile_id, now=100, reactions=ReactionService(bot))
        self.assertEqual(sorted(removed), [(21, 11, EMOJI, bot.user), (22, 12, EMOJI, bot.user)])
        self.assertEqual(await self.scalar("SELECT group_concat(message_id) FROM reactions"), "13")

    async def test_omitted_profile_id_resolves_current_member_after_authorization(self):
        service = self.service()

        async def authorize(conn):
            await conn.execute("DELETE FROM profiles")
            self.profile_id = await self.profile()

        marker = await service.run_marker(self.writer, self.path, authorize,
                                          kind="delete", guild_id="1", user_id="2", now=100)
        self.assertEqual(marker["profile_id"], self.profile_id)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)

    async def test_explicit_null_profile_id_retains_existing_profile(self):
        marker = await self.service().run_marker(self.writer, self.path, kind="opt_out", guild_id="1",
                                                 user_id="2", profile_id=None, now=100)
        self.assertIsNone(marker["profile_id"])
        self.assertEqual(await self.scalar("SELECT profile_id FROM profiles"), self.profile_id)
        self.assertTrue(await self.service().opted_out(self.conn, "1", "2"))

    async def test_refusal_appends_nothing_changes_nothing(self):
        async def refuse(conn):
            self.assertTrue(conn.in_transaction)
            await conn.execute("UPDATE profiles SET stardust=99")
            raise PermissionError("refused")

        with self.assertRaisesRegex(PermissionError, "refused"):
            await self.run_marker(authorize=refuse)
        self.assertEqual(self.path.read_bytes(), b"")
        self.assertEqual(await self.scalar("SELECT stardust FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM opt_outs"), 0)

    async def test_job_error_after_append_voids_before_rollback(self):
        service = self.service()
        apply, rollback = service.apply, self.conn.rollback

        async def fail(conn, states):
            await apply(conn, states)
            raise ValueError("compute failed")

        async def observe_rollback():
            self.assertEqual(self.records()[1]["void"], self.records()[0]["marker_id"])
            self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
            await rollback()

        with patch.object(service, "apply", side_effect=fail), \
                patch.object(self.conn, "rollback", side_effect=observe_rollback):
            with self.assertRaisesRegex(ValueError, "compute failed"):
                await self.run_marker("opt_out")
        self.assertEqual(marker_log.fold(self.path), {})
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM opt_outs"), 0)
        self.assertEqual(await self.writer.run(lambda conn: self.scalar("SELECT 1")), 1)

    async def cancelled_job(self, *, fail=False, abort=False):
        service = self.service()
        apply = service.apply
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed(conn, states):
            await apply(conn, states)
            started.set()
            await release.wait()
            if fail:
                raise ValueError("delayed failure")

        with patch.object(service, "apply", side_effect=delayed):
            pending = asyncio.create_task(self.run_marker("opt_out"))
            await asyncio.wait_for(started.wait(), 2)
            if abort:
                await self.writer.abort()
            else:
                pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            if not abort:
                self.assertEqual(len(self.records()), 1)
                release.set()
            await self.writer.close()

    async def test_cancelled_waiter_then_job_rollback_still_voids(self):
        await self.cancelled_job(fail=True)
        self.assertEqual(self.records()[1]["void"], self.records()[0]["marker_id"])
        self.assertEqual(marker_log.fold(self.path), {})
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM opt_outs"), 0)

    async def test_cancelled_waiter_then_commit_writes_no_void_and_applies(self):
        await self.cancelled_job()
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertTrue(await self.service().opted_out(self.conn, "1", "2"))

    async def test_writer_abort_mid_job_voids(self):
        await self.cancelled_job(abort=True)
        self.assertEqual(self.records()[1]["void"], self.records()[0]["marker_id"])
        self.assertEqual(marker_log.fold(self.path), {})
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM opt_outs"), 0)

    async def populate(self):
        profile = self.profile_id
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,excluded,share_banned) "
                                "VALUES ('1','2',1,1,1)")
        await self.conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                                "VALUES ('1','3','user','2','exclude','kept',0)")
        statements = [
            ("INSERT INTO step_events VALUES ('message',?,'4',4,4,0,400,'fixture',0)", (profile,)),
            ("INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
             "iv_stamina,gender,shiny,tier,route_id,content_version,created_at) "
             "VALUES ('encounter',?,1,2,0,0,0,'male',0,'common','refreshing_field','fixture',0)", (profile,)),
            ("INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
             "iv_stamina,gender,shiny,origin,source_encounter_id,content_version,caught_at) "
             "VALUES ('pokemon',?,1,2,0,0,0,'male',0,'catch','encounter','fixture',0)", (profile,)),
            ("UPDATE profiles SET companion_uid='pokemon' WHERE profile_id=?", (profile,)),
            ("INSERT INTO inventory VALUES (?,'poke_ball',3)", (profile,)),
            ("INSERT INTO candy VALUES (?,1,3)", (profile,)),
            ("INSERT INTO pokedex VALUES (?,1,0,0)", (profile,)),
            ("INSERT INTO reactions(message_id,profile_id,channel_id,desired,created_at,encounter_id) "
             "VALUES ('reaction',?,'4','add',0,'encounter')", (profile,)),
            ("INSERT INTO sessions VALUES ('session','1','2',?,0,500,'{}')", (profile,)),
            ("INSERT INTO milestone_awards VALUES (?,'first',0)", (profile,)),
            ("INSERT INTO inbox_items(profile_id,milestone_id,resource,remaining,created_at) "
             "VALUES (?,'first','stardust',20,0)", (profile,)),
            ("INSERT INTO finds(profile_id,message_id,item_id,quantity,outcome,created_at) "
             "VALUES (?,'find','poke_ball',1,'granted',0)", (profile,)),
            ("INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,receipt_key,remaining_encounters) "
             "VALUES ('effect',?,'shiny_lure',0,'lure',10)", (profile,)),
        ]
        for sql, args in statements:
            await self.conn.execute(sql, args)

        async def receipts(conn):
            async def with_line(conn):
                return {"private": profile}, [{"profile_id": profile, "resource": "item",
                                              "delta": 1, "reason": "fixture"}]

            async def no_line(conn):
                return {"private": profile}, []

            await with_receipt(conn, "throw:encounter:0", "throw", with_line, profile_id=profile)
            await with_receipt(conn, "run:encounter:1", "run", no_line, profile_id=profile)
            await conn.execute("INSERT INTO catch_attempts VALUES "
                               "('encounter',0,'poke_ball',NULL,0.5,1,0,'throw:encounter:0',0)")

        await self.writer.run(receipts)

    async def test_delete_cascades_all_rows_and_receipts_incl_run_keeps_restrictions_audit(self):
        await self.populate()
        other = await self.profile("9", "2")
        await self.run_marker("opt_out")
        for table in ("step_events", "encounters", "catch_attempts", "pokemon", "inventory",
                      "candy", "pokedex", "reactions", "sessions", "action_receipts",
                      "resource_ledger", "milestone_awards", "inbox_items", "finds", "active_effects"):
            with self.subTest(table=table):
                self.assertEqual(await self.scalar(f"SELECT count(*) FROM {table}"), 0)
        self.assertEqual(await self.scalar("SELECT profile_id FROM profiles"), other)
        self.assertEqual(await self.scalar("SELECT paused+excluded+share_banned FROM restrictions"), 3)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM opt_outs"), 1)
        new_id = await self.profile()
        self.assertNotEqual(new_id, self.profile_id)
        self.assertEqual(await self.scalar("SELECT paused+excluded+share_banned FROM restrictions"), 3)

    async def holder(self):
        await self.conn.execute(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,content_version,caught_at) "
            "VALUES ('holder',?,1,20,10,10,10,'male',0,'catch','fixture',0)", (self.profile_id,))
        await self.conn.execute("INSERT INTO gyms(gym_id,guild_id,name,created_at) VALUES ('park','1','Park',0)")
        await self.conn.execute("INSERT INTO gym_deployments(deployment_id,guild_id,gym_id,profile_id,pokemon_uid,"
                                "deployed_at,ends_at) VALUES ('deployment','1','park',?,'holder',0,28800)",
                                (self.profile_id,))
        await self.conn.execute("UPDATE pokemon SET gym_deployment_id='deployment' WHERE pokemon_uid='holder'")

    async def test_reset_holder_cascades_deployment_nothing_paid_gym_empty(self):
        await self.holder()
        await self.run_marker('reset', actor_id='3', reason='Test')
        for table in ('profiles', 'pokemon', 'gym_deployments', 'inbox_items'):
            self.assertEqual(await self.scalar(f"SELECT count(*) FROM {table}"), 0)
        self.assertEqual(await self.scalar("SELECT name FROM gyms"), 'Park')
        self.assertEqual(await self.scalar("SELECT action FROM mod_audit"), 'reset')
        self.assertEqual(await self.conn.execute_fetchall('PRAGMA foreign_key_check'), [])

    async def test_delete_data_holder_then_reenroll_nothing_credited(self):
        import random
        from pokewalker.services import gyms
        await self.holder()
        await self.run_marker('delete')
        new_id = await self.profile()
        self.assertNotEqual(new_id, self.profile_id)
        content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        await self.writer.run(lambda conn: gyms.settle(conn, 40000, random.Random(3), content))
        for table in ('pokemon', 'gym_deployments', 'inbox_items', 'inventory', 'resource_ledger'):
            self.assertEqual(await self.scalar(f"SELECT count(*) FROM {table}"), 0)
        self.assertEqual(await self.scalar("SELECT stardust FROM profiles WHERE profile_id=?", (new_id,)), 0)
        self.assertEqual(await self.scalar("SELECT name FROM gyms"), 'Park')
        self.assertEqual(await self.conn.execute_fetchall('PRAGMA foreign_key_check'), [])

    async def test_deleted_bytes_absent_after_checkpoint(self):
        await self.populate()
        await self.run_marker()
        await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for path in self.db_path.parent.glob("game.sqlite3*"):
            self.assertNotIn(self.profile_id.encode(), path.read_bytes(), path)
        backup = self.db_path.parent / "backup.sqlite3"
        with closing(sqlite3.connect(backup)) as destination:
            await self.conn.backup(destination)
        self.assertNotIn(self.profile_id.encode(), backup.read_bytes())

    async def test_opt_out_without_profile_inserts_row_only(self):
        await self.conn.execute("DELETE FROM profiles")
        service = self.service()
        await service.run_marker(self.writer, self.path, kind="opt_out", guild_id="1", user_id="2", now=100)
        self.assertTrue(await service.opted_out(self.conn, "1", "2"))
        self.assertFalse(await service.opted_out(self.conn, "9", "2"))
        created = await self.scalar("SELECT created_at FROM opt_outs")
        await service.run_marker(self.writer, self.path, kind="opt_out", guild_id="1", user_id="2", now=101)
        self.assertEqual(await self.scalar("SELECT created_at FROM opt_outs"), created)
        await service.run_marker(self.writer, self.path, kind="delete", guild_id="1", user_id="2", now=102)
        self.assertTrue(await service.opted_out(self.conn, "1", "2"))
        await service.run_marker(self.writer, self.path, kind="opt_in", guild_id="1", user_id="2", now=103)
        self.assertFalse(await service.opted_out(self.conn, "1", "2"))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)

    async def test_reset_inserts_one_audit_under_receipt(self):
        marker = await self.run_marker("reset", actor_id="3", reason="moderation")
        states = marker_log.fold(self.path)
        await self.writer.run(lambda conn: self.service().apply(conn, states))
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 1)
        async with self.conn.execute("SELECT * FROM mod_audit") as cursor:
            audit = dict(await cursor.fetchone())
        self.assertEqual({key: audit[key] for key in audit if key != "audit_id"},
                         dict(guild_id="1", actor_id="3", target_kind="user", target_id="2",
                              action="reset", reason="moderation", created_at=100))
        self.assertEqual(await self.scalar("SELECT key FROM action_receipts"), "reset:" + marker["marker_id"])
        self.assertIsNone(await self.scalar("SELECT profile_id FROM action_receipts"))
        # Even an audit receipt from a restored DB cannot suppress deletion.
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES (?,'1','2',0)", (self.profile_id,))
        await self.writer.run(lambda conn: self.service().apply(conn, states))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 1)

    async def test_invalid_reset_audit_logged_skipped_deletion_applies(self):
        marker_log.append_marker(self.path, "reset", "1", "2", 100,
                                 profile_id=self.profile_id, actor_id="3", reason=" ")
        with self.assertLogs("pokewalker.services.deletion", "WARNING"):
            await self.writer.run(lambda conn: self.service().apply(conn, marker_log.fold(self.path), replay=True))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts"), 1)

    async def test_live_reset_invalid_audit_voids_and_rolls_back(self):
        with self.assertRaises(sqlite3.IntegrityError):
            await self.run_marker("reset", actor_id="3", reason=" ")
        self.assertEqual(self.records()[1]["void"], self.records()[0]["marker_id"])
        self.assertEqual(marker_log.fold(self.path), {})
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts"), 0)

    async def test_marker_fsync_failure_voids_written_identity_before_later_opt_in_and_replay(self):
        fsync = os.fsync
        attempted = []

        def fail_first(fd):
            attempted.append(self.path.read_bytes())
            if len(attempted) == 1:
                self.assertTrue(attempted[0].endswith(b"\n"))
                self.assertEqual(json.loads(attempted[0])["profile_id"], self.profile_id)
                raise OSError("marker fsync failed after complete write")
            fsync(fd)

        with patch("os.fsync", side_effect=fail_first):
            with self.assertRaisesRegex(OSError, "marker fsync failed"):
                await self.run_marker("opt_out")
        self.assertEqual(len(self.records()), 2, "failed fsync needs a durable void for its written marker")
        self.assertEqual(self.records()[1]["void"], self.records()[0]["marker_id"])
        self.assertEqual(marker_log.fold(self.path), {})
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM opt_outs"), 0)
        await self.run_marker("opt_in")
        await self.writer.run(lambda conn: self.service().apply(conn, marker_log.fold(self.path), replay=True))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertFalse(await self.service().opted_out(self.conn, "1", "2"))

    async def void_failure(self, abort):
        service = self.service()
        apply = service.apply
        started, release = asyncio.Event(), asyncio.Event()
        queued_job = AsyncMock()
        rolling_back, allow_rollback = asyncio.Event(), asyncio.Event()
        rollback = self.conn.rollback

        async def delayed_rollback():
            rolling_back.set()
            await allow_rollback.wait()
            await rollback()

        async def delayed(conn, states):
            await apply(conn, states)
            started.set()
            await release.wait()
            raise ValueError("compute failed")

        async def outcome():
            try:
                return await self.run_marker("opt_out")
            except BaseException as error:
                return error

        with patch.object(service, "apply", side_effect=delayed), \
                patch.object(service, "append_void", side_effect=OSError("void disk failed")), \
                patch.object(self.conn, "rollback", side_effect=delayed_rollback):
            pending = asyncio.create_task(outcome())
            await asyncio.wait_for(started.wait(), 2)
            queued = asyncio.create_task(self.writer.run(queued_job))
            await asyncio.sleep(0)
            try:
                with self.assertLogs("pokewalker.services.deletion", "CRITICAL") as logs:
                    if abort:
                        stopping = asyncio.create_task(self.writer.abort())
                    else:
                        release.set()
                    await asyncio.wait_for(rolling_back.wait(), 1)
                    with self.assertRaisesRegex(RuntimeError, "closed"):
                        await asyncio.wait_for(self.writer.run(queued_job), 1)
                    allow_rollback.set()
                    if abort:
                        await asyncio.wait_for(asyncio.shield(stopping), 1)
                    results = await asyncio.wait_for(asyncio.gather(pending, queued, return_exceptions=True), 1)
            finally:
                allow_rollback.set()
                # A broken abort must not hang the test process's cleanup.
                if not self.writer._task.done():
                    self.writer._task.cancel()
                    await asyncio.gather(self.writer._task, return_exceptions=True)
                await asyncio.gather(pending, queued, return_exceptions=True)
            self.assertIn("recovery required", " ".join(logs.output).lower())
        self.assertIsInstance(results[0], asyncio.CancelledError)
        self.assertIn("recovery required", str(results[0]).lower())
        self.assertIsInstance(results[0].__cause__, OSError)
        self.assertIsInstance(results[1], RuntimeError)
        queued_job.assert_not_awaited()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            await self.writer.run(queued_job)
        await asyncio.wait_for(self.writer.close(), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM opt_outs"), 0)
        # Failed void durability is unresolved: restart can still replay deletion.
        states = marker_log.fold(self.path)
        self.assertEqual(states[("1", "2")].delete_ids, {self.profile_id})
        reopened = await open_db(self.db_path)
        self.addAsyncCleanup(reopened.close)
        restarted = Writer(reopened)
        self.addAsyncCleanup(restarted.close)
        await restarted.run(lambda conn: service.apply(conn, states, replay=True))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)

    async def test_void_failure_during_abort_closes_writer_and_resolves_waiters(self):
        await self.void_failure(abort=True)

    async def test_void_failure_after_compute_error_closes_writer_and_resolves_waiters(self):
        await self.void_failure(abort=False)

    async def test_marker_and_void_fsync_failure_closes_writer_with_unresolved_recovery(self):
        async def outcome():
            try:
                await self.run_marker("opt_out")
            except BaseException as error:
                return error

        with patch("os.fsync", side_effect=OSError("storage fsync unavailable")), \
                self.assertLogs("pokewalker.services.deletion", "CRITICAL") as logs:
            failure = await outcome()
        self.assertIsInstance(failure, asyncio.CancelledError)
        self.assertIsInstance(failure.__cause__, OSError)
        self.assertIn("recovery required", str(failure).lower())
        self.assertIn("durability unknown", " ".join(logs.output).lower())
        with self.assertRaisesRegex(RuntimeError, "closed"):
            await self.writer.run(AsyncMock())
        await asyncio.wait_for(self.writer.close(), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM opt_outs"), 0)
        # Simulate losing the unsynced void while its earlier marker survives.
        self.path.write_bytes(self.path.read_bytes().splitlines(keepends=True)[0])
        self.assertEqual(marker_log.fold(self.path)[("1", "2")].delete_ids, {self.profile_id})

    async def test_commit_failure_leaves_valid_marker_replay_applies(self):
        with patch.object(self.conn, "commit", AsyncMock(side_effect=sqlite3.OperationalError("commit failed"))):
            with self.assertRaisesRegex(sqlite3.OperationalError, "commit failed"):
                await self.run_marker("opt_out")
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        await self.writer.run(lambda conn: self.service().apply(conn, marker_log.fold(self.path)))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertTrue(await self.service().opted_out(self.conn, "1", "2"))

    async def test_writer_abort_during_commit_leaves_valid_marker_replay_applies(self):
        started = asyncio.Event()

        async def pending_commit():
            started.set()
            await asyncio.Future()

        with patch.object(self.conn, "commit", side_effect=pending_commit):
            pending = asyncio.create_task(self.run_marker("opt_out"))
            await asyncio.wait_for(started.wait(), 2)
            await self.writer.abort()
            with self.assertRaises(asyncio.CancelledError):
                await pending
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        recovery_writer = Writer(self.conn)
        self.addAsyncCleanup(recovery_writer.close)
        await recovery_writer.run(lambda conn: self.service().apply(conn, marker_log.fold(self.path)))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertTrue(await self.service().opted_out(self.conn, "1", "2"))

    async def test_folded_members_apply_final_participation_independent_of_receipts(self):
        other = await self.profile("9", "2")
        marker_log.append_marker(self.path, "opt_out", "1", "2", 100, profile_id=self.profile_id)
        marker_log.append_marker(self.path, "opt_in", "1", "2", 101)
        marker_log.append_marker(self.path, "opt_out", "9", "2", 102, profile_id=other)
        states = marker_log.fold(self.path)
        await self.writer.run(lambda conn: self.service().apply(conn, states))
        await self.writer.run(lambda conn: self.service().apply(conn, states))
        self.assertFalse(await self.service().opted_out(self.conn, "1", "2"))
        self.assertTrue(await self.service().opted_out(self.conn, "9", "2"))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts"), 0)

    async def test_marker_append_failure_does_not_delete(self):
        service = self.service()
        with patch.object(service, "append_marker", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                await self.run_marker()
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(set(self.records()[0]), {"void", "at"})
        self.assertEqual(marker_log.fold(self.path), {})
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)

    async def test_apply_requires_writer_transaction(self):
        with self.assertRaisesRegex(RuntimeError, "transaction"):
            await self.service().apply(self.conn, {})

    async def test_marker_log_init_singleton_and_migration_preserves_data(self):
        legacy = self.db_path.parent / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy)) as conn:
            for migration in sorted(MIGRATIONS.glob("*.sql")):
                if migration.name.startswith("0008_"):
                    break
                conn.executescript(migration.read_text(encoding="utf-8"))
                conn.execute(f"PRAGMA user_version={int(migration.name[:4])}")
            conn.execute("INSERT INTO guilds(guild_id) VALUES ('7')")
            conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                         "VALUES ('legacy-profile','7','8',0)")
            conn.commit()
        upgraded = await open_db(legacy)
        try:
            async with upgraded.execute("SELECT profile_id FROM profiles") as cursor:
                self.assertEqual((await cursor.fetchone())[0], "legacy-profile")
            for table in ("opt_outs", "marker_log_init"):
                await upgraded.execute(f"SELECT * FROM {table}")
        finally:
            await upgraded.close()
        await self.conn.execute("INSERT INTO marker_log_init VALUES (1,100)")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("INSERT INTO marker_log_init VALUES (2,101)")
        reopened = await open_db(self.db_path)
        try:
            async with reopened.execute("SELECT profile_id FROM profiles") as cursor:
                self.assertEqual((await cursor.fetchone())[0], self.profile_id)
            async with reopened.execute("SELECT at FROM marker_log_init") as cursor:
                self.assertEqual((await cursor.fetchone())[0], 100)
        finally:
            await reopened.close()

    async def test_marker_log_path_outside_db(self):
        settings = Settings(Secret("synthetic"), self.db_path, owner_ids=frozenset({3}))
        self.assertEqual(settings.marker_log_path, self.db_path.with_name("game.sqlite3.markers.jsonl"))
        with patch.dict(os.environ, {"DISCORD_TOKEN": "synthetic", "POKEWALKER_OWNER_IDS": "3",
                                    "POKEWALKER_DB_PATH": str(self.db_path),
                                    "POKEWALKER_MARKER_LOG": str(self.path)}, clear=True):
            self.assertEqual(Settings.from_env().marker_log_path, self.path)
        for suffix in ("", "-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, "marker log"):
                Settings(Secret("synthetic"), self.db_path, owner_ids=frozenset({3}),
                         marker_log_path=Path(str(self.db_path) + suffix))
        alias = self.db_path.parent / "db-alias"
        os.link(self.db_path, alias)
        with self.assertRaisesRegex(ValueError, "marker log"):
            Settings(Secret("synthetic"), self.db_path, owner_ids=frozenset({3}), marker_log_path=alias)
