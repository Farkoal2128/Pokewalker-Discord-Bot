"""M0.6 offline economy behavior, using the authored miniature content snapshot."""

import copy
import importlib
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content.balance import load_table


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/content_mini/content"


class EconomyModelTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module("scripts.economy.model")
        except ModuleNotFoundError:
            self.fail("M0.6 offline economy model is absent")
        self.artifact = json.loads((FIXTURE / "artifact/content.json").read_text())
        self.balances = {p.stem: load_table(p.stem) for p in (ROOT / "content/balance").glob("*.json")}
        self.balances["routes"] = json.loads((FIXTURE.parent / "balance/routes.json").read_text())

    def model(self, **kwargs):
        return self.module.Model(self.artifact, self.balances, random.Random(1), **kwargs)

    def run_model(self, **kwargs):
        return self.module.run_scenario(random.Random(7), artifact=self.artifact,
                                        balances=self.balances, **kwargs)

    def test_seeded_run_is_deterministic(self):
        self.assertEqual(self.run_model(days=3), self.run_model(days=3))

    def test_no_negative_balances(self):
        result = self.run_model(days=30, active_hours=8, profile="active")
        self.assertGreaterEqual(result["minimum_balance"], 0)
        self.assertTrue(all(v >= 0 for v in result["inventory"].values()))
        self.assertLessEqual(sum(result["balls_spent"].values()), sum(result["balls_supplied"].values()))

    def test_queue_never_exceeds_three(self):
        result = self.run_model(days=3, profile={"messages_per_hour": 120, "words_per_message": 20})
        self.assertLessEqual(result["max_queue"], 3)

    def test_find_freeze_three_per_hour(self):
        model = self.model()
        model.find_meter = 9900
        model.find_times.extend([1, 2])
        model.credit_steps(2000, 3)
        self.assertEqual(model.find_meter, 0)
        self.assertEqual(list(model.find_times), [1, 2, 3])
        model.credit_steps(20000, 4)
        self.assertEqual(model.find_meter, 0)
        model.credit_steps(9900, 3603)
        self.assertEqual(model.find_meter, 9900)

    def test_checkin_every_60_minutes_of_activity(self):
        result = self.run_model(days=3, active_hours=4)
        self.assertEqual(result["checkins"], 12)

    def test_legendary_never_flees(self):
        model = self.model()
        legendary = next(i for i in self.artifact["identities"] if i["is_legendary"])
        encounter = {"identity": legendary, "shiny": False, "level": 20}
        self.assertEqual(model.flee_probability(encounter), 0)
        model.inventory = {"ultra_ball": 1000}
        model.queue.clear()
        model.queue.append(encounter)
        model.resolve(0)
        self.assertEqual(model.fled, 0)
        self.assertIn(legendary["species_id"], model.caught)

    def test_milestone_awards_once(self):
        model = self.model()
        model.caught.update([1, 4, 7])
        model.award_milestones()
        first = (copy.deepcopy(model.inbox), copy.deepcopy(model.inventory), model.dust_in)
        model.award_milestones()
        self.assertEqual(first, (model.inbox, model.inventory, model.dust_in))
        self.assertIn("starter_trios:0", model.earned)

    def test_uses_measured_profile_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.md"
            path.write_text("| Accepted words | 600.00 | 600.00 | 600.00 |\n")
            result = self.run_model(days=1, profile="measured", measured_path=path)
        self.assertEqual(result["profile_source"], "measured percentiles")
        self.assertEqual(result["accepted_words"], 600)

    def test_fallback_profile_when_absent(self):
        result = self.run_model(days=1, profile="measured", measured_path=ROOT / "absent-summary.md")
        self.assertIn("fallback regular", result["profile_source"])
        self.assertEqual(result["accepted_words"], 300)

    def test_fallback_daily_totals_do_not_multiply_by_active_hours(self):
        self.assertEqual(self.run_model(days=1, active_hours=8)["accepted_words"], 300)

    def test_continuous_style_exceeds_three_encounters_per_hour_with_enough_steps(self):
        self.balances["capacities"]["limits"]["starter_kit"]["poke_ball"] = 10000
        self.balances["capacities"]["limits"]["bag_units"] = 20000
        result = self.run_model(days=1, profile={"messages_per_hour": 120, "words_per_message": 20})
        self.assertGreater(result["encounters_per_active_hour"], 3)

    def test_hourly_style_caps_at_three_per_hour(self):
        result = self.run_model(days=1, style="hourly check",
                                profile={"messages_per_hour": 120, "words_per_message": 20})
        self.assertLessEqual(result["encounters"], 3)

    def test_overflow_and_rare_duplicate_convert_without_overfilling(self):
        model = self.model()
        model.inventory = {"poke_ball": 250, "master_ball": 1}
        before = model.dust_in
        model.grant("poke_ball", 5)
        model.grant("master_ball", 1)
        self.assertEqual(model.dust_in - before, 510)
        self.assertEqual(model.inventory, {"poke_ball": 250, "master_ball": 1})

    def test_milestone_items_wait_in_inbox(self):
        model = self.model()
        model.inventory = {"poke_ball": 250, "shiny_lure": 1}
        model.inbox.update({"ultra_ball": 20, "shiny_lure": 1})
        model.claim()
        self.assertEqual(model.inbox, {"ultra_ball": 20, "shiny_lure": 1})

    def test_missing_route_tiers_redistribute_without_raising_legendary_odds(self):
        model = self.model()
        for pool in model.pools.values():
            self.assertAlmostEqual(sum(p[2] for p in pool.values()), 100)
            self.assertEqual(pool["legendary"][2], 1)

    def test_powerup_prices_candy_is_family_scoped_and_output_covers_report(self):
        result = self.run_model(days=1)
        self.assertEqual(result["powerup_costs"]["30"], {"candy": 100, "stardust": 15000})
        self.assertEqual(result["powerup_costs"]["40"], {"candy": 180, "stardust": 35000})
        self.assertIn("legendary_expected_encounters", result)
        self.assertIn("route_tier_pool_sizes", result)
        self.assertIn("bundle_value_vs_income", result)
        self.assertGreaterEqual(result["favourite_candy_in"], result["favourite_candy_balance"])
        self.assertGreaterEqual(result["bundle_value_vs_income"]["bronze"]["month_income_stardust_equivalent"], result["stardust_in"] * 30)
        self.assertEqual(result["days_to_first_shiny"]["method"], "geometric expectation from generated encounter pace")

    def test_legendary_group_pacing_counts_completion_and_form_multiplicity(self):
        identities = [{"species_id": 144}, {"species_id": 144}, {"species_id": 145}]
        expectation = self.module.group_expectation(identities, [144, 145], .01)
        self.assertAlmostEqual(expectation, 350)
        self.assertIsNone(self.module.group_expectation(identities, [144, 146], .01))

    def test_present_invalid_measured_file_does_not_silently_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.md"
            path.write_text("wrong schema")
            with self.assertRaises(ValueError):
                self.run_model(profile="measured", measured_path=path)

    def test_route_cycle_continues_across_days_after_default_enrollment(self):
        route = next(iter(self.artifact["routes"].values()))
        authored = load_table("routes")["routes"][:3]
        self.balances["routes"] = {"routes": authored}
        self.artifact["routes"] = {name: copy.deepcopy(route) for name in sorted(r["id"] for r in authored)}
        seen, enrollment = {}, []
        credit, mint = self.module.Model.credit_steps, self.module.Model.mint

        def observe_credit(model, amount, at):
            seen.setdefault((int(at // 86400), int(at % 86400 // 3600)), model.route)
            return credit(model, amount, at)

        def observe_mint(model):
            enrollment.append(model.route)
            return mint(model)

        with patch.object(self.module.Model, "credit_steps", observe_credit), patch.object(self.module.Model, "mint", observe_mint):
            self.run_model(days=2, active_hours=2)
        self.assertEqual(enrollment[0], "refreshing_field")
        self.assertEqual(list(seen.values()), ["refreshing_field", "noisy_forest", "rugged_road", "refreshing_field"])

    def test_authored_route_order_overrides_sorted_artifact(self):
        route = next(iter(self.artifact["routes"].values()))
        self.balances["routes"] = load_table("routes")
        expected = [r["id"] for r in self.balances["routes"]["routes"]]
        self.artifact["routes"] = {name: copy.deepcopy(route) for name in sorted(expected)}
        model = self.model()
        self.assertEqual(model.route, "refreshing_field")
        self.assertEqual(list(model.pools), expected)

    def test_measured_high_rate_preserves_1800_accepted_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.md"
            path.write_text("| Accepted words | 1800 | 1800 | 1800 |\n")
            self.assertEqual(self.run_model(days=1, profile="measured", measured_path=path)["accepted_words"], 1800)

    def test_consecutive_measured_hours_preserve_totals_and_d20(self):
        awards = []
        credit = self.module.Model.credit_steps

        def observe(model, amount, at):
            awards.append(amount)
            return credit(model, amount, at)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.md"
            path.write_text("| Accepted words | 1800 | 1800 | 1800 |\n")
            with patch.object(self.module.Model, "credit_steps", observe):
                result = self.run_model(days=1, active_hours=2, profile="measured", measured_path=path)
        self.assertEqual(result["accepted_words"], 3600)
        self.assertEqual(sum(awards), 300 * 100 + 3300 * 25)

    def test_impossible_measured_hour_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.md"
            path.write_text("| Accepted words | 1801 | 1801 | 1801 |\n")
            with self.assertRaises(ValueError):
                self.run_model(days=1, profile="measured", measured_path=path)

    def test_varying_consecutive_measured_hours_preserve_sampled_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.md"
            path.write_text("| Accepted words | 300 | 1800 | 1800 |\n")
            with patch.object(random.Random, "choice", side_effect=[1800, 300, 1800]):
                result = self.run_model(days=1, active_hours=3, profile="measured", measured_path=path)
        self.assertEqual(result["accepted_words"], 3900)

    def test_malformed_explicit_profiles_raise_value_error(self):
        for profile in ({"words_per_message": 12}, {"messages_per_hour": "many", "words_per_message": 12},
                        {"messages_per_hour": True, "words_per_message": 12},
                        {"messages_per_hour": 10, "words_per_message": True},
                        {"messages_per_hour": float("nan"), "words_per_message": 12},
                        {"messages_per_hour": 10, "messages_per_day": 25, "words_per_message": 12}, [], 12):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                self.run_model(days=1, profile=profile)


if __name__ == "__main__":
    unittest.main()
