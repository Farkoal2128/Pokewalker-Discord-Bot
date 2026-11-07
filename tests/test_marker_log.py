"""D28 write-ahead log durability, corruption and final replay state."""

import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID


class MarkerLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=".")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "markers.jsonl"

    def service(self):
        self.assertIsNotNone(importlib.util.find_spec("pokewalker.services.marker_log"),
                             "D28 requires the marker log implementation")
        return importlib.import_module("pokewalker.services.marker_log")

    def marker(self, kind, profile_id=None, **fields):
        return self.service().append_marker(self.path, kind, "1", "2", 100,
                                            profile_id=profile_id, **fields)

    def initialize(self):
        self.service().create_empty(self.path)

    def state(self):
        return self.service().fold(self.path)[("1", "2")]

    def test_append_is_one_fsynced_json_line_with_marker_id(self):
        self.initialize()
        synced = []
        original = os.fsync
        def sync(fd):
            synced.append(self.path.read_bytes())
            original(fd)
        with patch("os.fsync", side_effect=sync):
            marker = self.marker("reset", "old", actor_id="3", reason="moderation")
        self.assertEqual(len(synced), 1)
        self.assertEqual(synced[0], self.path.read_bytes())
        self.assertEqual(len(synced[0].splitlines()), 1)
        self.assertTrue(synced[0].endswith(b"\n"))
        self.assertEqual(json.loads(synced[0]), marker)
        self.assertEqual(UUID(marker["marker_id"]).version, 4)
        self.assertEqual({k: v for k, v in marker.items() if k != "marker_id"},
                         dict(kind="reset", guild_id="1", user_id="2", profile_id="old",
                              at=100, actor_id="3", reason="moderation"))

    def test_caller_supplied_marker_identity_is_validated_and_preserved(self):
        from uuid import uuid4
        self.initialize()
        marker_id = str(uuid4())
        marker = self.service().append_marker(self.path, "delete", "1", "2", 100, marker_id=marker_id)
        self.assertEqual(marker["marker_id"], marker_id)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.service().append_marker(self.path, "delete", "1", "2", 100, marker_id="bad")
        self.assertEqual(self.path.read_bytes(), before)

    def test_void_excludes_its_marker_wherever_it_appears(self):
        self.initialize()
        marker = self.marker("delete", "old")
        with patch("os.fsync", wraps=os.fsync) as sync:
            self.service().append_void(self.path, marker["marker_id"], 101)
        sync.assert_called_once()
        lines = self.path.read_bytes().splitlines(keepends=True)
        self.assertEqual(json.loads(lines[1]), {"void": marker["marker_id"], "at": 101})
        for ordered in (lines, lines[::-1]):
            self.path.write_bytes(b"".join(ordered))
            self.assertEqual(self.service().fold(self.path), {})

    def test_last_valid_participation_marker_wins_per_member(self):
        self.initialize()
        self.marker("opt_in")
        self.marker("opt_out")
        self.assertTrue(self.state().opted_out)
        failed = self.marker("opt_in")
        self.service().append_void(self.path, failed["marker_id"], 101)
        self.assertTrue(self.state().opted_out)
        self.marker("opt_in")
        self.assertFalse(self.state().opted_out)
        self.assertEqual(self.state().delete_ids, set())

    def test_failed_opt_out_voided_then_opt_in_folds_opted_in_nothing_deleted(self):
        self.initialize()
        marker = self.marker("opt_out", "retained")
        self.service().append_void(self.path, marker["marker_id"], 101)
        self.marker("opt_in")
        self.assertFalse(self.state().opted_out)
        self.assertEqual(self.state().delete_ids, set())

    def test_unvoided_marker_counts_as_applied_intent(self):
        self.initialize()
        self.marker("opt_out", "old")
        self.assertTrue(self.state().opted_out)
        self.assertEqual(self.state().delete_ids, {"old"})

    def test_deletions_accumulate_across_later_opt_in_and_reenrolment(self):
        self.initialize()
        self.marker("delete", "first")
        reset = self.marker("reset", "second", actor_id="3", reason="reason")
        self.marker("opt_out", "third")
        self.marker("opt_in", "reenrolled")
        self.assertEqual(self.state().delete_ids, {"first", "second", "third"})
        self.assertFalse(self.state().opted_out)
        self.assertEqual(self.state().resets, [{k: reset[k] for k in
                         ("marker_id", "profile_id", "actor_id", "reason", "at")}])
        self.assertNotIn("reenrolled", self.state().delete_ids)

    def test_members_fold_independently(self):
        self.initialize()
        self.marker("delete", "old")
        self.service().append_marker(self.path, "opt_out", "1", "3", 100)
        self.service().append_marker(self.path, "opt_in", "9", "2", 100)
        states = self.service().fold(self.path)
        self.assertEqual(len(states), 3)
        self.assertIsNone(states[("1", "2")].opted_out)
        self.assertTrue(states[("1", "3")].opted_out)
        self.assertFalse(states[("9", "2")].opted_out)

    def test_torn_tail_repaired_then_marker_and_void_survive_fold(self):
        self.initialize()
        for prefix in (b"", b'{"void":"00000000-0000-4000-8000-000000000001","at":100}\n'):
            self.path.write_bytes(prefix + b'{"partial":')
            with self.assertLogs("pokewalker.services.marker_log", level="WARNING") as logs:
                with patch("os.fsync", wraps=os.fsync) as sync:
                    deleted = self.marker("delete", "old")
            self.assertEqual(sync.call_count, 2)
            self.assertIn("11", " ".join(logs.output))
            self.assertTrue(self.path.read_bytes().startswith(prefix))
            self.marker("opt_out")
            with self.path.open("ab") as stream:
                stream.write(b"broken")
            with self.assertLogs("pokewalker.services.marker_log", level="WARNING"):
                self.service().append_void(self.path, deleted["marker_id"], 102)
            self.assertEqual(self.state().delete_ids, set())
            self.assertTrue(self.state().opted_out)

    def test_unparseable_final_line_skipped_earlier_bad_line_raises(self):
        self.initialize()
        self.marker("delete", "old")
        valid = self.path.read_bytes()
        for invalid in (b'{"partial":', b"\xff"):
            self.path.write_bytes(valid + invalid)
            with self.assertLogs("pokewalker.services.marker_log", level="WARNING"):
                self.assertEqual(self.state().delete_ids, {"old"})
            for suffix in (valid, valid[:-1]):
                self.path.write_bytes(invalid + b"\n" + suffix)
                with self.assertRaisesRegex(ValueError, "line 1"):
                    self.service().fold(self.path)

    def test_unterminated_complete_marker_ignored_then_truncated_before_append(self):
        self.initialize()
        self.marker("opt_out", "uncommitted")
        tail = self.path.read_bytes()[:-1]
        self.assertEqual(json.loads(tail)["kind"], "opt_out")
        self.path.write_bytes(tail)
        with self.assertLogs("pokewalker.services.marker_log", level="WARNING"):
            self.assertEqual(self.service().fold(self.path), {})
        with self.assertLogs("pokewalker.services.marker_log", level="WARNING"):
            committed = self.marker("opt_in")
        self.assertEqual(self.path.read_bytes().splitlines(),
                         [json.dumps(committed).encode("utf-8")])
        self.assertFalse(self.state().opted_out)
        self.assertEqual(self.state().delete_ids, set())

    def test_unterminated_complete_void_ignored_then_truncated_before_append(self):
        self.initialize()
        deleted = self.marker("delete", "committed")
        prefix = self.path.read_bytes()
        self.service().append_void(self.path, deleted["marker_id"], 101)
        unterminated = self.path.read_bytes()[:-1]
        self.assertEqual(json.loads(unterminated[len(prefix):])["void"], deleted["marker_id"])
        self.path.write_bytes(unterminated)
        with self.assertLogs("pokewalker.services.marker_log", level="WARNING"):
            states = self.service().fold(self.path)
            self.assertIn(("1", "2"), states, "an unterminated void must not cancel deletion")
            self.assertEqual(states[("1", "2")].delete_ids, {"committed"})
        with self.assertLogs("pokewalker.services.marker_log", level="WARNING"):
            self.marker("opt_in")
        self.assertTrue(self.path.read_bytes().startswith(prefix))
        self.assertEqual(len(self.path.read_bytes().splitlines()), 2)
        self.assertEqual(self.state().delete_ids, {"committed"})
        self.assertFalse(self.state().opted_out)

    def test_create_empty_fsyncs_and_never_truncates_existing(self):
        with patch("os.fsync", wraps=os.fsync) as sync:
            self.initialize()
        self.assertEqual(sync.call_count, 2 if os.name == "posix" else 1)
        self.assertEqual(self.path.read_bytes(), b"")
        self.assertEqual(self.service().fold(self.path), {})
        self.path.write_bytes(b"existing data")
        with self.assertRaises(FileExistsError):
            self.initialize()
        self.assertEqual(self.path.read_bytes(), b"existing data")

    def test_unknown_or_malformed_record_is_corruption_even_at_end(self):
        self.initialize()
        marker = self.marker("delete", "old")
        for bad in ({"unknown": 1}, [], dict(marker, kind="surprise"),
                    dict(marker, guild_id="private name"), dict(marker, at=True),
                    dict(marker, marker_id="invalid"), {"void": 7, "at": 100}):
            self.path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
            with self.subTest(record=bad), self.assertRaisesRegex(ValueError, "line 1"):
                self.service().fold(self.path)

    def test_invalid_append_or_missing_file_does_not_create_or_change_log(self):
        with self.assertRaises(FileNotFoundError):
            self.marker("delete", "old")
        self.assertFalse(self.path.exists())
        self.initialize()
        for kind, fields in (("unknown", {}), ("delete", {"reason": object()}),
                             ("opt_in", {"actor_id": "private name"})):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.marker(kind, **fields)
        with self.assertRaises(ValueError):
            self.service().append_void(self.path, "id", float("nan"))
        self.assertEqual(self.path.read_bytes(), b"")

    def test_fsync_failure_propagates(self):
        self.initialize()
        with patch("os.fsync", side_effect=OSError("disk failed")):
            with self.assertRaisesRegex(OSError, "disk failed"):
                self.marker("delete", "old")


if __name__ == "__main__":
    unittest.main()
