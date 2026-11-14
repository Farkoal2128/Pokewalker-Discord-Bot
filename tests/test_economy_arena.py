"""Arena analytic ticket payouts, using live balances and miniature scenario fixtures."""

import copy
import importlib
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from content.balance import load_table
from scripts.economy.model import run_scenario
from scripts.simulate_economy import render_report


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/content_mini"
RUNS = ((0, 10), (0, 20), (0, 30), (0, 40), (40, 40), (40, 60), (40, 80), (40, 100))


class EconomyArenaTests(unittest.TestCase):
    def setUp(self):
        self.artifact = json.loads((FIXTURE / "content/artifact/content.json").read_text())
        self.balances = {p.stem: load_table(p.stem) for p in (ROOT / "content/balance").glob("*.json")}
        self.balances["routes"] = json.loads((FIXTURE / "balance/routes.json").read_text())
        self.balances["routes"]["version"] = 1

    def income(self):
        function = getattr(importlib.import_module("scripts.economy.model"), "arena_income", None)
        self.assertIsNotNone(function, "Arena analytic income is absent")
        return function(self.balances)

    def report(self):
        results = [run_scenario(random.Random(7), artifact=self.artifact, balances=self.balances,
                                days=2, active_hours=hours, style=style)
                   for hours in (1, 4, 8) for style in ("continuous", "hourly check")]
        return render_report(results, seed=7, days=2, profile="regular", measured=None,
                             artifact=self.artifact, balances=self.balances), results

    def test_arena_income_reproduces_requirement_payout_rows(self):
        income = self.income()
        self.assertEqual([(r["skip"], r["floor"]) for r in income["runs"]], list(RUNS))
        expected = {
            40: ({"bronze": 2, "silver": 4, "gold": 2}, 16, 1800, 16, 0),
            80: ({"bronze": 2, "silver": 4, "gold": 6, "platinum": 3, "diamond": 1}, 40, 9400, 80, 6),
            100: ({"bronze": 2, "silver": 4, "gold": 8, "platinum": 3, "diamond": 3}, 52, 16200, 136, 12),
        }
        for run in income["runs"]:
            if run["floor"] in expected:
                self.assertEqual(tuple(run[key] for key in ("tickets", "encounters_max", "stardust", "income_rolls", "survivor_rolls")),
                                 expected[run["floor"]])
        with patch("pokewalker.domain.battle.simulate", side_effect=AssertionError("no Arena battle simulation")):
            _, results = self.report()
        self.assertTrue(all(result["arena_income"] == income for result in results))

    def test_skip_rows_split_start_paid_tickets_and_fights(self):
        runs = {(r["skip"], r["floor"]): r for r in self.income()["runs"]}
        baseline, start, deep = (runs[key] for key in ((0, 40), (40, 40), (40, 80)))
        self.assertEqual(start["fights"], 0)
        self.assertEqual(start["tickets"], start["at_start"])
        self.assertEqual(start["stardust_equivalent"], start["at_start_stardust_equivalent"])
        self.assertEqual(baseline["at_start"], {})
        self.assertEqual(baseline["at_start_stardust_equivalent"], 0)
        self.assertEqual(baseline["fights"], 120)
        self.assertEqual(start["tickets"], baseline["tickets"])
        self.assertEqual(deep["fights"], 120)
        self.assertEqual(deep["at_start"], baseline["tickets"])
        self.assertEqual(deep["at_start_stardust_equivalent"], baseline["stardust_equivalent"])

    def test_roll_values_follow_live_tables_and_name_unpriced_items(self):
        income = self.income()
        self.assertAlmostEqual(income["income_roll_value"], 25.615)
        self.assertAlmostEqual(income["survivor_roll_value"], 754.25)
        self.assertEqual(income["unpriced"], ["world_legendary_ticket"])
        # Adversarial rows exercise weights, quantities, direct Stardust and missing prices.
        self.balances["gym_income_table"]["rows"] = [
            {"item": "poke_ball", "quantity": 3, "weight": 2},
            {"item": "stardust", "quantity": 10, "weight": 1},
            {"item": "unpriced_income", "quantity": 20, "weight": 1}]
        self.balances["survivor_table"] = {"stardust_flat": 7, "rows": [
            {"item": "ultra_ball", "quantity": 2, "weight": 3},
            {"item": "unpriced_survivor", "quantity": 9, "weight": 1}]}
        self.balances["conversion_rates"]["stardust_per_unit"]["poke_ball"] = 4
        changed = self.income()
        self.assertAlmostEqual(changed["income_roll_value"], 8.5)
        self.assertAlmostEqual(changed["survivor_roll_value"], 22)
        self.assertEqual(changed["unpriced"], ["unpriced_income", "unpriced_survivor"])
        self.balances["arena"]["rules"]["tickets"]["tiers"]["gold"]["encounters"] = "fill"
        self.balances["capacities"]["limits"]["encounter_queue"] = 5
        self.assertEqual(next(r for r in self.income()["runs"] if r["floor"] == 40)["encounters_max"], 20)

    def test_stardust_equivalent_and_daily_rate_use_cooldown(self):
        income = self.income()
        self.assertAlmostEqual(income["runs_per_day"], 4 / 3)
        for run in income["runs"]:
            expected = run["stardust"] + run["income_rolls"] * 25.615 + run["survivor_rolls"] * 754.25
            self.assertAlmostEqual(run["stardust_equivalent"], expected)
        self.balances["arena"]["rules"]["cooldown_seconds"] = 43200
        changed = self.income()
        self.assertEqual(changed["runs_per_day"], 2)
        self.assertEqual(changed["runs"], income["runs"])
        report, _ = self.report()
        row = next(r for r in changed["runs"] if (r["skip"], r["floor"]) == (40, 100))
        self.assertIn(f"{row['stardust_equivalent'] * 2:,.2f}", report)

    def test_report_arena_section_states_assumptions_and_lists_every_run(self):
        report, results = self.report()
        self.assertIn("## Arena ticket income", report)
        self.assertLess(report.index("| Gym item |"), report.index("## Arena ticket income"))
        self.assertLess(report.index("## Arena ticket income"), report.index("## Checks"))
        section = report.split("## Arena ticket income\n", 1)[1].split("## Checks", 1)[0]
        for phrase in ("assumptions, not predictions", "no fights are simulated", "first-clear bonuses excluded",
                       "upper bounds", "start and back out", "25.61", "754.25", "world_legendary_ticket",
                       "Skip", "Floor cleared", "Fights", "Tickets", "At start", "Encounters (max)",
                       "Stardust", "Income rolls", "Survivor rolls", "Stardust-equivalent", "At-start Stardust-equivalent", "Stardust-equivalent/day"):
            self.assertIn(phrase, section)
        for skip, floor in RUNS:
            self.assertIn(f"| {skip} | {floor} | {3 * (floor - skip)} |", section)
        self.assertEqual(len([line for line in section.splitlines() if line.startswith("| ")]), 9)
        self.assertNotRegex(section, r"PASS|FAIL")
        self.assertEqual(results[0]["arena_income"], self.income())

    def test_existing_report_sections_unchanged_by_arena_section(self):
        before, original = self.report()
        self.balances = copy.deepcopy(self.balances)
        for tier in self.balances["arena"]["rules"]["tickets"]["tiers"].values():
            tier["stardust"] *= 7
        after, changed = self.report()
        def without_arena(report):
            prefix, rest = report.split("## Arena ticket income\n", 1)
            return prefix + "## Checks" + rest.split("## Checks", 1)[1]
        self.assertEqual(without_arena(before), without_arena(after))
        self.assertNotEqual(before, after)
        self.assertEqual([{k: v for k, v in r.items() if k != "arena_income"} for r in original],
                         [{k: v for k, v in r.items() if k != "arena_income"} for r in changed])


if __name__ == "__main__":
    unittest.main()
