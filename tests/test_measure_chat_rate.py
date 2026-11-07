"""Offline measurement output privacy, shared credit rules and CLI contract."""

import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        try:
            self.measure = importlib.import_module("scripts.measure_chat_rate")
        except ModuleNotFoundError:
            self.fail("M0.5 measurement provider absent: private totals unavailable")

    def message(self, at=0, author="123456789012345678", text="alpha bravo charlie delta",
                channel="987654321098765432", bot=False):
        return {"author_id": author, "channel_id": channel, "created_at": at,
                "content": text, "is_bot": bot}

    def test_summary_has_no_member_ids(self):
        totals = self.measure.measure([self.message(), self.message(15, author="other")])
        summary = self.measure.render_summary(totals)
        for private in ("123456789012345678", "987654321098765432", "other"):
            self.assertNotIn(private, summary)
        self.assertIn("p50", summary)
        self.assertIn("p90", summary)
        self.assertIn("p99", summary)
        self.assertIn("4.00", summary)

    def test_measure_never_writes_content(self):
        secret = "privateword anotherword thirdword fourthword"
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.jsonl"
            output = Path(folder) / "totals.json"
            source.write_text(json.dumps(self.message(text=secret)) + "\n", encoding="utf-8")
            run = subprocess.run([sys.executable, str(ROOT / "scripts/measure_chat_rate.py"),
                                  str(source), "--output", str(output)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), [{
                "author_id": "123456789012345678", "hour": "1970-01-01T00:00:00+00:00",
                "accepted_words": 4, "awarded_c": 400,
            }])
            self.assertNotIn(secret, output.read_text(encoding="utf-8") + run.stdout + run.stderr)

    def test_shared_rules_cross_channels_and_bots(self):
        messages = [self.message(bot=True), self.message(1),
                    self.message(16, channel="other"),
                    self.message(17, text="new words are eligible"),
                    self.message(3600, author="second", text="hello hello hello hello")]
        totals = self.measure.measure(messages)
        self.assertEqual([(r["accepted_words"], r["awarded_c"]) for r in totals], [(8, 800)])

    def test_minute_buckets_and_hourly_split(self):
        messages = [self.message(i * 61, text=f"alpha{i} bravo charlie delta")
                    for i in range(61)]
        totals = self.measure.measure(messages)
        self.assertEqual([r["accepted_words"] for r in totals], [240, 4])
        history = self.measure.MemoryHistory()
        self.assertEqual(history.accepted_words_since(0), 0)

    def test_invalid_input_never_echoes_content(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "bad.jsonl"
            output = Path(folder) / "out.json"
            source.write_text('{"private raw words": broken}\n', encoding="utf-8")
            run = subprocess.run([sys.executable, str(ROOT / "scripts/measure_chat_rate.py"),
                                  str(source), "--output", str(output)],
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("line 1", run.stderr)
            self.assertNotIn("private raw words", run.stdout + run.stderr)
            self.assertFalse(output.exists())

    def test_invalid_fields_and_order(self):
        for patch in ({"created_at": float("nan")}, {"created_at": "2026-01-01T00:00:00"},
                      {"is_bot": "false"}, {"content": []}, {"author_id": ""}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.measure.measure([self.message() | patch])
        with self.assertRaises(ValueError):
            self.measure.measure([self.message(100), self.message(99)])

    def test_empty_summary_and_aware_timestamps(self):
        self.assertIn("0.00", self.measure.render_summary([]))
        totals = self.measure.measure([self.message("2026-11-04T01:01:00+01:00")])
        self.assertEqual(totals[0]["hour"], "2026-11-04T00:00:00+00:00")

    def test_summary_flag_writes_only_aggregate_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.jsonl"
            output = Path(folder) / "totals.json"
            summary = Path(folder) / "measurements" / "summary.md"
            source.write_text(json.dumps(self.message()) + "\n", encoding="utf-8")
            with patch.object(self.measure, "SUMMARY_PATH", summary):
                self.assertEqual(self.measure.main([str(source), "--output", str(output),
                                                    "--summary"]), 0)
            self.assertEqual(summary.read_text(encoding="utf-8"),
                             self.measure.render_summary(json.loads(output.read_text())))
            self.assertNotIn("123456789012345678", summary.read_text())

    def test_invalid_utf8_never_echoes_raw_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "bad.jsonl"
            output = Path(folder) / "out.json"
            source.write_bytes(b'private words \xff never log these')
            run = subprocess.run([sys.executable, str(ROOT / "scripts/measure_chat_rate.py"),
                                  str(source), "--output", str(output)],
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertNotIn("0xff", run.stderr)
            self.assertIn("line 1", run.stderr)

    def test_input_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.jsonl"
            original = json.dumps(self.message()) + "\n"
            source.write_text(original, encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.measure.main([str(source), "--output", str(source)])
            self.assertEqual(source.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
