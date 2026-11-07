"""Offline CLI/report acceptance for M0.7; no chat export or network required."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/simulate_economy.py"
FOOTER = "Numbers above change approved settings only through a README edit by the owner (G-2)"


class SimulateEconomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.output = Path(cls.temp.name) / "economy.md"
        cls.process = subprocess.run(
            [sys.executable, str(CLI), "--seed", "1", "--days", "30", "--profile",
             "regular", "--out", str(cls.output)], cwd=ROOT, capture_output=True, text=True)
        cls.report = cls.output.read_text(encoding="utf-8") if cls.output.exists() else ""

    def assert_success(self):
        self.assertEqual(self.process.returncode, 0, self.process.stderr)
        self.assertTrue(self.report, "CLI must write its markdown report")

    def test_cli_writes_report_with_three_scenarios_and_two_styles(self):
        self.assert_success()
        for hours in (1, 4, 8):
            section = self.report.split(f"## {hours} active hours/day\n", 1)[1].split("\n## ", 1)[0]
            self.assertIn("| Metric | continuous | hourly check |", section)
            for metric in ("Encounters / active hour", "Balls supplied", "Balls spent",
                           "Candy in", "Stardust in", "Power-up cost to level 30",
                           "Power-up cost to level 40", "First shiny mean / median",
                           "Storage fill day"):
                self.assertIn(metric, section)
        self.assertIn("## Legendary pacing", self.report)
        self.assertIn("open question, not a decision", self.report)
        self.assertIn("birds", self.report.lower())
        self.assertTrue(self.report.rstrip().endswith(FOOTER))

    def test_report_contains_inputs_block_with_manifest_hash(self):
        self.assert_success()
        inputs = self.report.split("## Inputs\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn(hashlib.sha256((ROOT / "content/manifest.json").read_bytes()).hexdigest(), inputs)
        self.assertIn("Seed: 1", inputs)
        self.assertIn("Days: 30", inputs)
        self.assertIn("fallback regular", inputs)
        self.assertIn("G-1: no chat export", inputs)
        for path in (ROOT / "content/balance").glob("*.json"):
            version = json.loads(path.read_text())["version"]
            self.assertIn(f"{path.name}: v{version}", inputs)

    def test_checks_section_lists_pass_fail(self):
        self.assert_success()
        checks = self.report.split("## Checks\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("PASS", checks)
        self.assertIn("FAIL", checks)
        self.assertIn("8-hour continuous", checks)
        self.assertIn("Scarcity is intended", checks)
        self.assertIn("stock-limited", checks)
        self.assertIn("M0.8", checks)
        self.assertIn("Planner expectation", checks)
        self.assertIn("4 hours/day", checks)
        for hours in (1, 4, 8):
            for bundle in ("bronze", "silver", "gold", "platinum", "diamond"):
                self.assertIn(f"D59 {bundle}, {hours} hours/day", checks)
        self.assertIn("stardust equivalent", checks)

    def test_missing_measured_file_falls_back_and_says_so(self):
        output = Path(self.temp.name) / "missing-measured.md"
        process = subprocess.run(
            [sys.executable, str(CLI), "--seed", "1", "--days", "1", "--profile",
             "measured", "--measured", str(Path(self.temp.name) / "absent.md"),
             "--out", str(output)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = output.read_text(encoding="utf-8")
        self.assertIn("fallback regular: measured summary absent", report)
        self.assertIn("assumptions, not measured behavior", report)

    def test_invalid_days_fail_without_creating_output(self):
        output = Path(self.temp.name) / "invalid.md"
        process = subprocess.run(
            [sys.executable, str(CLI), "--days", "0", "--out", str(output)],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
