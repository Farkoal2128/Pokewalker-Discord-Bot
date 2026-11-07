"""D28 startup replay using real SQLite transactions and marker files."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pokewalker.db import Writer, open_db
from pokewalker.services import deletion, marker_log


class ReplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache = Path("build/test-replay")
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "markers.jsonl"
        self.conn = await open_db(Path(self.temp.name) / "game.db")
        self.addAsyncCleanup(self.conn.close)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('1')")
        self.profile_id = await self.profile()

    async def scalar(self, sql, args=()):
        async with self.conn.execute(sql, args) as cursor:
            return (await cursor.fetchone())[0]

    async def profile(self, profile_id=None, user="2"):
        profile_id = profile_id or str(uuid4())
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES (?,'1',?,0)", (profile_id, user))
        return profile_id

    def marker(self, kind="delete", **fields):
        if not self.path.exists():
            marker_log.create_empty(self.path)
        return marker_log.append_marker(self.path, kind, "1", "2", 100,
                                        profile_id=self.profile_id, **fields)

    async def replay(self):
        self.assertTrue(callable(getattr(deletion, "replay_markers", None)),
                        "startup replay must initialize and apply the external log")
        await deletion.replay_markers(self.writer, self.path)

    async def test_first_startup_creates_log_and_init_row(self):
        create = marker_log.create_empty
        order = []

        def observe(path):
            order.append("durable log")
            create(path)

        commit = self.conn.commit

        async def observe_commit():
            self.assertEqual(order, ["durable log"])
            self.assertTrue(self.path.exists())
            await commit()

        with patch.object(marker_log, "create_empty", side_effect=observe), \
                patch.object(self.conn, "commit", side_effect=observe_commit):
            await self.replay()
        self.assertEqual(self.path.read_bytes(), b"")
        self.assertGreater(await self.scalar("SELECT at FROM marker_log_init WHERE id=1"), 0)
        before = await self.scalar("SELECT at FROM marker_log_init")
        await self.replay()
        self.assertEqual(await self.scalar("SELECT at FROM marker_log_init"), before)

    async def test_crash_between_create_and_record_then_startup_records_then_log_loss_refuses(self):
        marker_log.create_empty(self.path)
        await self.replay()
        self.assertEqual(await self.scalar("SELECT count(*) FROM marker_log_init"), 1)
        self.path.unlink()
        with self.assertRaisesRegex(RuntimeError, "marker log missing.*newest.*D28"):
            await self.replay()

    async def test_old_db_beside_newer_log_records_init_then_log_loss_refuses(self):
        self.marker()
        await self.replay()
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM marker_log_init"), 1)
        self.path.unlink()
        with self.assertRaisesRegex(RuntimeError, "marker log missing"):
            await self.replay()

    async def test_missing_log_with_init_row_refuses_startup(self):
        await self.conn.execute("INSERT INTO marker_log_init VALUES (1,0)")
        with self.assertRaisesRegex(RuntimeError, "marker log missing.*newest.*D28"):
            await self.replay()
        self.assertFalse(self.path.exists())
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)

    async def test_failed_opt_out_then_successful_opt_in_replay_ends_opted_in_profile_kept(self):
        marker_log.create_empty(self.path)
        with patch.object(deletion, "apply", side_effect=ValueError("failed mutation")):
            with self.assertRaisesRegex(ValueError, "failed mutation"):
                await deletion.run_marker(self.writer, self.path, kind="opt_out", guild_id="1",
                                          user_id="2", now=100, profile_id=self.profile_id)
        await deletion.run_marker(self.writer, self.path, kind="opt_in", guild_id="1",
                                  user_id="2", now=101)
        await self.replay()
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertFalse(await deletion.opted_out(self.conn, "1", "2"))

    async def test_crash_between_append_and_commit_replay_applies_it(self):
        self.marker("opt_out")
        await self.replay()
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertTrue(await deletion.opted_out(self.conn, "1", "2"))

    async def test_replay_finishes_interrupted_deletion_and_skips_reenrolled_profile(self):
        self.marker()
        other = await self.profile(user="3")
        marker_log.append_marker(self.path, "delete", "1", "3", 101, profile_id=other)
        apply = deletion.apply
        calls = 0

        async def interrupt(conn, states, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("interrupted replay")
            await apply(conn, states, **kwargs)

        with patch.object(deletion, "apply", side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, "interrupted replay"):
                await self.replay()
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles WHERE profile_id=?",
                                           (self.profile_id,)), 0)
        new_profile = await self.profile()
        await self.replay()
        self.assertEqual(await self.scalar("SELECT profile_id FROM profiles"), new_profile)

    async def test_opt_out_without_profile_survives_restore(self):
        await self.conn.execute("DELETE FROM profiles")
        self.profile_id = None
        self.marker("opt_out")
        await self.replay()
        self.assertTrue(await deletion.opted_out(self.conn, "1", "2"))
        await self.conn.execute("DELETE FROM opt_outs")
        await self.replay()
        self.assertTrue(await deletion.opted_out(self.conn, "1", "2"))

    async def test_restore_predating_opt_out_then_opt_in_ends_opted_in(self):
        self.marker("opt_out")
        self.marker("opt_in")
        await self.replay()
        self.assertFalse(await deletion.opted_out(self.conn, "1", "2"))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)

    async def test_reset_exactly_one_audit_across_interruption_and_replay(self):
        marker = self.marker("reset", actor_id="3", reason="moderation")
        apply = deletion.apply

        async def interrupt(conn, states, **kwargs):
            await apply(conn, states, **kwargs)
            if next(iter(states.values())).resets:
                raise RuntimeError("interrupted audit")

        with patch.object(deletion, "apply", side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, "interrupted audit"):
                await self.replay()
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 0)
        await self.replay()
        await self.profile(self.profile_id)
        await self.replay()
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 1)
        self.assertEqual(await self.scalar("SELECT key FROM action_receipts"), "reset:" + marker["marker_id"])

    async def test_refused_reset_audit_logged_skipped_startup_continues(self):
        self.marker("reset", actor_id="3", reason=" ")
        self.marker("reset", actor_id="3", reason="valid")
        with self.assertLogs("pokewalker.services.deletion", "WARNING") as logs:
            await self.replay()
        self.assertIn("constraint", " ".join(logs.output))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts"), 2)

    async def test_corrupt_log_refuses_without_deleting_profiles(self):
        self.marker()
        with self.path.open("ab") as stream:
            stream.write(b"{}\n")
        with self.assertRaisesRegex(ValueError, "corrupt marker log"):
            await self.replay()
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)

    async def test_first_use_fsync_failure_refuses_without_init_record(self):
        with patch("os.fsync", side_effect=OSError("fsync failed")):
            with self.assertRaisesRegex(OSError, "fsync failed"):
                await self.replay()
        self.assertEqual(await self.scalar("SELECT count(*) FROM marker_log_init"), 0)

    async def test_init_commit_failure_leaves_log_for_next_startup(self):
        with patch.object(self.conn, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                await self.replay()
        self.assertTrue(self.path.exists())
        self.assertEqual(await self.scalar("SELECT count(*) FROM marker_log_init"), 0)
        await self.replay()
        self.assertEqual(await self.scalar("SELECT count(*) FROM marker_log_init"), 1)
