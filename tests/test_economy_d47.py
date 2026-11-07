"""M0.8 demand estimates and analytic gym comparison; no private chat input."""

import json
import random
import unittest
from collections import Counter, deque
from pathlib import Path
from unittest.mock import patch

from content.balance import load_table
from scripts.economy.model import Model, run_scenario
from scripts.simulate_economy import render_report


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/content_mini"


class EconomyD47Tests(unittest.TestCase):
    def setUp(self):
        self.artifact = json.loads((FIXTURE / "content/artifact/content.json").read_text())
        self.balances = {p.stem: load_table(p.stem) for p in (ROOT / "content/balance").glob("*.json")}
        self.balances["routes"] = json.loads((FIXTURE / "balance/routes.json").read_text())
        self.balances["routes"]["version"] = 1

    def scenario(self, **kwargs):
        return run_scenario(random.Random(7), artifact=self.artifact, balances=self.balances, **kwargs)

    def encounter(self, tier="Legendary/Mythical"):
        return {"identity": next(i for i in self.artifact["identities"] if i["tier"] == tier),
                "level": 20, "shiny": False}

    def model(self):
        with patch.object(Model, "award_milestones"):
            model = Model(self.artifact, self.balances, random.Random(1))
        model.queue = deque([self.encounter()])
        model.inventory = Counter()
        return model

    def test_insufficient_supply_reports_positive_deficit_with_nonnegative_inventory(self):
        self.balances["step_rules"]["rules"]["finds_per_rolling_hour"] = 0
        self.balances["simulation"]["checkin_seconds"] = 10**12
        with patch.object(Model, "award_milestones"):
            for style in ("continuous", "hourly check"):
                with self.subTest(style=style):
                    result = self.scenario(days=30, style=style)
                    spent, supplied = sum(result["balls_spent"].values()), sum(result["balls_supplied"].values())
                    unmet = sum(result["unmet_ball_demand"].values())
                    self.assertGreater(unmet, 0)
                    self.assertGreater(result["deficit"], 0)
                    self.assertEqual(result["ball_demand"], spent + unmet)
                    self.assertEqual(result["deficit"], max(0, spent + unmet - supplied))
                    self.assertLessEqual(spent, supplied)
                    self.assertGreaterEqual(result["minimum_inventory"], 0)
                    self.assertTrue(all(n >= 0 for n in result["inventory"].values()))

    def test_sufficient_supply_has_zero_unmet_demand_and_deficit(self):
        self.balances["capacities"]["limits"]["starter_kit"]["poke_ball"] = 10000
        self.balances["capacities"]["limits"]["bag_units"] = 20000
        result = self.scenario(days=30)
        self.assertEqual(sum(result["unmet_ball_demand"].values()), 0)
        self.assertEqual(result["deficit"], 0)
        self.assertEqual(result["stockout_events"], 0)

    def test_virtual_throw_resolves_encounter_and_frees_slot(self):
        model = self.model()
        model.queue.append(self.encounter())
        before = dict(model.inventory)
        model.rng.random = lambda: 0
        with patch.object(model, "award_milestones"):
            model.resolve(0)
        self.assertFalse(model.queue)
        self.assertEqual(model.inventory, before)
        self.assertEqual(model.balls_spent, {})
        self.assertEqual(model.unmet_ball_demand, {"poke_ball": 2})
        self.assertEqual(model.stockout_events, 2)
        self.assertEqual(model.fled, 0)
        model.credit_steps(10000, 1)
        self.assertEqual(len(model.queue), 1)

    def test_virtual_throw_consumes_berry_then_next_attempt_uses_none(self):
        model = self.model()
        model.inventory["razz_berry"] = 1
        seeded = random.Random(15)
        rolls = [seeded.random() for _ in range(2)]
        base = self.balances["catch"]["rules"]["base_catch_rates"]["legendary"] / (2 * self.balances["cpm"]["multipliers"]["40"])
        with_berry = 1 - (1 - base) ** self.balances["catch"]["rules"]["berry_multipliers"]["razz_berry"]
        # Seed 15 fails with the berry; use a boundary roll to distinguish the second attempt.
        self.assertGreater(rolls[0], with_berry)
        second_roll = (base + with_berry) / 2
        model.rng.random = unittest.mock.Mock(side_effect=[rolls[0], rolls[1], second_roll, .5, 0])
        with patch.object(model, "award_milestones"):
            model.resolve(0)
        self.assertEqual(model.inventory["razz_berry"], 0)
        self.assertEqual(model.unmet_ball_demand, {"poke_ball": 3})
        self.assertFalse(model.queue)
        self.assertEqual(model.stockout_events, 1)

    def test_ball_fallback_order_before_virtual_throw(self):
        model = self.model()
        model.queue = deque([self.encounter("Common") for _ in range(5)])
        model.inventory.update({"poke_ball": 1, "great_ball": 1, "ultra_ball": 1, "master_ball": 1})
        order = []

        def roll():
            order.append(dict(model.balls_spent))
            return 0

        model.rng.random = roll
        with patch.object(model, "award_milestones"):
            model.resolve(0)
        self.assertEqual(list(order[0]), ["poke_ball"])
        self.assertEqual(list(order[1]), ["poke_ball", "great_ball"])
        self.assertEqual(list(order[2]), ["poke_ball", "great_ball", "ultra_ball"])
        self.assertEqual(list(order[3]), ["poke_ball", "great_ball", "ultra_ball", "master_ball"])
        self.assertEqual(model.unmet_ball_demand, {"poke_ball": 1})
        self.assertEqual(model.stockout_events, 1)

    def test_gym_income_expected_balls_per_deployment_from_d23_table(self):
        result = self.scenario(days=2)
        gym = result["gym_income"]
        table = self.balances["gym_income_table"]
        total = sum(r["weight"] for r in table["rows"])
        expected = {r["item"]: 8 * r["weight"] * r["quantity"] / total for r in table["rows"]}
        self.assertEqual(gym["items_per_deployment"], expected)
        self.assertAlmostEqual(gym["balls_per_deployment"], 24.576)
        self.assertAlmostEqual(gym["balls_one_deployment_daily"], 49.152)
        self.assertAlmostEqual(gym["balls_all_day"], 147.456)

    def test_d47_comparison_reports_both_holding_assumptions(self):
        report, results = self.report()
        self.assertIn("## D47 comparison", report)
        self.assertIn("(a) one 8-hour deployment per day", report)
        self.assertIn("(b) held all day with immediate re-deployment", report)
        for result in results:
            label = f"| {result['active_hours']} | {result['style']} |"
            self.assertIn(label, report)
        self.assertIn("Gym balls (a)", report)
        self.assertIn("Gym balls (b)", report)
        self.assertIn("(a) closes deficit?", report)

    def test_report_d47_table_labels_unmet_demand_as_estimate(self):
        self.balances["step_rules"]["rules"]["finds_per_rolling_hour"] = 0
        self.balances["simulation"]["checkin_seconds"] = 10**12
        with patch.object(Model, "award_milestones"):
            report, _ = self.report(days=30)
        self.assertIn("Unmet demand (estimate)", report)
        self.assertIn("throws the policy would have made with unlimited supply", report)
        self.assertIn("Scarcity is intended", report)
        self.assertNotIn("shortfall: not established", report)
        self.assertIn("G-1: no chat export used", report)
        self.assertIn("This run confirms a shortfall", report)
        self.assertIn("PASS — gym assumption (a)", report)

    def report(self, days=2):
        results = [self.scenario(days=days, active_hours=hours, style=style)
                   for hours in (1, 4, 8) for style in ("continuous", "hourly check")]
        return render_report(results, seed=7, days=days, profile="regular", measured=None,
                             artifact=self.artifact, balances=self.balances), results


if __name__ == "__main__":
    unittest.main()
