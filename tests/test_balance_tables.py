"""Executable balance contract from D20–D61 and PLAN P1/P3/P5/P6/P8."""

import importlib
import json
import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path


def override_limits(case, **limits):
    """Change capacities limits for one test through the cached balance table."""
    balance = importlib.import_module("content.balance")
    balance.load_table.cache_clear()
    case.addCleanup(balance.load_table.cache_clear)
    balance._parsed("capacities")["limits"].update(limits)


TABLES = (
    "step_rules", "tier_chances", "catch", "find_table", "checkin_table",
    "powerup_prices", "cpm", "conversion_rates", "capacities", "milestones",
    "routes", "gym_income_table", "simulation", "evolution", "battle", "survivor_table",
)


class BalanceTableTests(unittest.TestCase):
    def test_simulation_inputs_preserve_documented_units_and_rules(self):
        table = self.load("simulation")
        self.assertEqual(table["fallback_profiles"], {
            "casual": {"messages_per_day": 10, "words_per_message": 10},
            "regular": {"messages_per_day": 25, "words_per_message": 12},
            "active": {"messages_per_day": 60, "words_per_message": 15},
        })
        self.assertEqual(table["checkin_seconds"], 3600)
        self.assertEqual(table["checkin_guaranteed"], {"poke_ball": 1})
        self.assertEqual(table["overflow_stardust"], 10)
        self.assertEqual(table["rare_duplicate_stardust"], 500)
        self.assertEqual(table["poke_ball_reserve"], 5)

    def load(self, name):
        try:
            module = importlib.import_module("content.balance")
        except ModuleNotFoundError:
            self.fail("M0.3 balance provider absent: authored rules unavailable")
        return module.load_table(name)

    def rows(self, name):
        rows = self.load(name)["rows"]
        self.assertEqual(len(rows), len({row["item"] for row in rows}))
        for row in rows:
            self.assertIs(type(row["weight"]), int)
            self.assertGreater(row["weight"], 0)
            self.assertGreater(row["quantity"], 0)
        return {row["item"]: (row["quantity"], row["weight"]) for row in rows}

    def test_find_table_v11_totals_10000_with_star_piece_50_and_evolution_200(self):
        rows = self.rows("find_table")
        self.assertEqual(rows, {
            "poke_ball": (5, 5000), "great_ball": (3, 1800),
            "ultra_ball": (1, 600), "razz_berry": (1, 800),
            "pinap_berry": (1, 800), "golden_razz_berry": (1, 150),
            "silver_pinap_berry": (1, 100), "rare_candy": (1, 200),
            "star_piece": (1, 50), "evolution_item": (1, 200),
            "stardust": (100, 240), "shiny_lure": (1, 50), "master_ball": (1, 10),
        })
        self.assertEqual(sum(w for _, w in rows.values()), 10000)

    def test_checkin_total_100(self):
        # Owner amendment 2026-11-12: Vitamin 1, Great Ball 35 -> 34.
        rows = self.rows("checkin_table")
        self.assertEqual(rows, {"great_ball": (1, 34), "razz_berry": (1, 30),
                                "poke_ball": (2, 20), "pinap_berry": (1, 15),
                                "vitamin": (1, 1)})
        self.assertEqual(sum(w for _, w in rows.values()), 100)

    def test_battle_rules_match_research_template_values(self):
        self.assertEqual(self.load("battle")["rules"], {
            "fast": {"power": 6, "energy": 10, "ticks": 1},
            "charged": {"power": 60, "energy_cost": 50, "ticks": 2},
            "stab": 1.2, "energy_cap": 100, "tick_limit": 120,
            "damage": "floor(0.5 * power * attack / defense * stab * effectiveness) + 1",
            "defender_hp": {"base_factor_x10": 20, "per_hour_x10": 1, "rounding": "ceil"},
            # D62 (owner decision 2026-11-12): one attacker, 5-minute cooldown, Razz Berry feeding.
            "party_max": 1, "cooldown_seconds": 300,
            "defender_feed": {"item": "razz_berry", "heal_x10": 5, "cooldown_seconds": 600},
            "type_factors": {"super": 1.6, "neutral": 1.0, "resisted": 0.625, "immune": 0.390625},
        })

    def test_type_chart_values_equal_battle_json_four_factors(self):
        path = Path(__file__).parents[1] / "content/artifact/content.json"
        chart = json.loads(path.read_bytes())["type_chart"]
        factors = set(self.load("battle")["rules"]["type_factors"].values())
        self.assertEqual(factors, {1.6, 1.0, 0.625, 0.390625})
        self.assertEqual({value for row in chart.values() for value in row.values()}, factors)

    def test_survivor_table_totals_10000_and_flat_500(self):
        # Owner amendments 2026-11-12: Companion Mirror 500, Ultra Ball 2500 -> 2000;
        # then Bottlecap 400, Ultra Ball 2000 -> 1600.
        rows = self.rows("survivor_table")
        self.assertEqual(rows, {
            "ultra_ball": (5, 1600), "golden_razz_berry": (3, 2000),
            "silver_pinap_berry": (3, 1500), "rare_candy": (5, 1500),
            "star_piece": (2, 1000), "shiny_lure": (1, 800),
            "master_ball": (1, 600), "companion_mirror": (1, 500),
            "bottlecap": (1, 400), "world_legendary_ticket": (1, 100),
        })
        self.assertEqual(sum(w for _, w in rows.values()), 10000)
        self.assertEqual(self.load("survivor_table")["stardust_flat"], 500)

    def test_rare_pockets_include_ticket_and_gyms_limits(self):
        table = self.load("capacities")
        self.assertEqual(table["limits"]["rare_pockets"], {
            "master_ball": 1, "shiny_lure": 1, "world_legendary_ticket": 1,
        })
        self.assertEqual(table["gyms"], {"per_guild": 10, "name_max": 32})

    def test_gym_income_table_d23_values_with_owner_vitamin(self):
        # Owner amendment 2026-11-12: Vitamin 100, Poke Ball 4940 -> 4840.
        rows = self.rows("gym_income_table")
        expected = self.rows("find_table") | {
            "master_ball": (1, 20), "shiny_lure": (1, 100), "poke_ball": (5, 4840),
            "vitamin": (1, 100),
        }
        self.assertEqual(rows, expected)
        self.assertEqual(len(rows), 14)
        self.assertEqual(sum(w for _, w in rows.values()), 10000)
        self.assertEqual(self.load("gym_income_table")["tenure_seconds"], 28800)

    def test_tier_chances_total_100(self):
        chances = self.load("tier_chances")["chances"]
        self.assertEqual(chances, {"common": 60, "uncommon": 30, "rare": 3,
                                   "evolved": 6, "legendary": 1})
        self.assertEqual(sum(chances.values()), 100)

    def test_routes_cover_all_18_types_each_on_two(self):
        routes = self.load("routes")["routes"]
        expected = {
            "Refreshing Field": {3: "normal", 2: "grass flying", 1: "bug fairy"},
            "Noisy Forest": {3: "bug grass", 2: "poison", 1: "flying ghost"},
            "Rugged Road": {3: "rock ground", 2: "fighting", 1: "fire steel dragon"},
            "Beautiful Beach": {3: "water", 2: "electric", 1: "flying ice fairy normal"},
            "Suburban Area": {3: "electric", 2: "normal steel psychic fairy", 1: "poison fighting dark"},
            "Dim Cave": {3: "ghost", 2: "dark rock poison", 1: "psychic steel ground"},
            "Blue Lake": {3: "water", 2: "grass ice dragon", 1: "bug fairy"},
            "Volcano Path": {3: "fire", 2: "ground dragon", 1: "rock dark psychic fighting"},
        }
        self.assertEqual(len(routes), 8)
        self.assertEqual(len({r["id"] for r in routes}), 8)
        self.assertEqual({r["name"] for r in routes}, set(expected))
        types = set("normal fire water electric grass ice fighting poison ground flying psychic bug rock ghost dragon dark steel fairy".split())
        for route in routes:
            weights = {t: w for w, names in expected[route["name"]].items() for t in names.split()}
            self.assertEqual(route["weights"], weights)
        self.assertEqual(set().union(*(r["weights"] for r in routes)), types)
        for kind in types:
            self.assertGreaterEqual(sum(r["weights"].get(kind, 0) > 0 for r in routes), 2)

    def test_cpm_has_79_entries_strictly_increasing(self):
        values = self.load("cpm")["multipliers"]
        self.assertEqual(set(values), {str(n) for n in range(2, 81)})
        ordered = [values[str(n)] for n in range(2, 81)]
        self.assertTrue(all(0 < a < b < 1 for a, b in zip(ordered, ordered[1:])))
        for key, value in {2: .094, 3: .1351374318, 4: .16639787, 20: .4225,
                           30: .51739395, 40: .5974, 41: .6048236651,
                           60: .7317, 61: .7347410093, 80: .7903}.items():
            self.assertEqual(values[str(key)], value)

    def test_milestone_thresholds_match_d59(self):
        rows = self.load("milestones")["pokedex"]
        self.assertEqual([(r["percent"], r["species_count"], r["bundle"]) for r in rows], [
            (5, 52, "bronze"), (10, 103, "bronze"), (25, 257, "silver"),
            (50, 513, "gold"), (75, 769, "platinum"), (90, 923, "platinum"),
            (100, 1025, "diamond"),
        ])

    def test_milestones_include_every_d59_category(self):
        table = self.load("milestones")
        self.assertEqual(len(table["pokedex"]), 7)
        trios = [[1, 4, 7], [152, 155, 158], [252, 255, 258], [387, 390, 393],
                 [495, 498, 501], [650, 653, 656], [722, 725, 728],
                 [810, 813, 816], [906, 909, 912]]
        self.assertEqual([(r["generation"], r["species_ids"], r["bundle"])
                          for r in table["starter_trios"]],
                         [(g, ids, "bronze") for g, ids in enumerate(trios, 1)])
        self.assertEqual(table["all_starters"], {"species_ids": sum(trios, []), "bundle": "gold"})
        self.assertEqual(table["regions"], [{"generation": g, "bundle": "platinum"} for g in range(1, 10)])
        self.assertEqual(table["first_legendary"], {"bundle": "silver"})
        self.assertEqual(table["first_mythical"], {"bundle": "silver"})
        self.assertEqual(len(table["legendary_groups"]), 19)
        self.assertTrue(all(r["bundle"] == "platinum" for r in table["legendary_groups"]))
        sets = {3: [385, 386], 4: [489, 490, 491, 492, 493],
                5: [494, 647, 648, 649], 6: [719, 720, 721], 7: [801, 802, 807, 808, 809]}
        self.assertEqual(table["mythical_sets"], [{"generation": g, "species_ids": ids, "bundle": "platinum"}
                                                for g, ids in sets.items()])
        self.assertEqual(table["all_legendaries"], {"species_count": 71, "bundle": "diamond"})
        self.assertEqual(table["all_mythicals"], {"species_count": 23, "bundle": "diamond"})
        beasts = list(range(793, 800)) + list(range(803, 807))
        self.assertEqual(table["ultra_beast_first_catches"], [{"species_id": n, "bundle": "silver"} for n in beasts])
        self.assertEqual(table["evolution_lines"], {
            "minimum_species": 2, "requires_real_evolution": True,
            "family_candy": 25, "ultra_ball": 1, "stardust_per_species": 250,
            "expected_family_count": 340, "expected_species_count": 824,
        })
        self.assertEqual(table["bundles"], {
            "bronze": {"great_ball": 10, "razz_berry": 5, "stardust": 500},
            "silver": {"ultra_ball": 10, "golden_razz_berry": 3, "rare_candy": 2, "stardust": 2000},
            "gold": {"ultra_ball": 20, "golden_razz_berry": 5, "silver_pinap_berry": 5,
                     "rare_candy": 5, "stardust": 5000, "shiny_lure": 1},
            "platinum": {"ultra_ball": 30, "golden_razz_berry": 10, "rare_candy": 10,
                         "stardust": 15000, "master_ball": 1},
            "diamond": {"ultra_ball": 50, "golden_razz_berry": 20, "rare_candy": 25,
                        "stardust": 50000, "master_ball": 1, "shiny_lure": 1},
        })

    def test_extra_bundle_lines_are_five_including_poipole(self):
        rows = self.load("milestones")["extra_bundle_lines"]
        self.assertEqual({r["id"]: (r["species_ids"], r["bundle"]) for r in rows}, {
            "type_null": ([772, 773], "gold"), "kubfu": ([891, 892], "gold"),
            "meltan": ([808, 809], "gold"), "cosmog": ([789, 790, 791, 792], "platinum"),
            "poipole": ([803, 804], "silver"),
        })
        self.assertEqual(len(rows), 5)

    def test_legendary_group_ids_match_d59_list(self):
        rows = self.load("milestones")["legendary_groups"]
        expected = {
            "birds": [144, 145, 146], "beasts": [243, 244, 245], "tower_duo": [249, 250],
            "regis": [377, 378, 379, 486, 894, 895], "eon_duo": [380, 381],
            "weather_trio": [382, 383, 384], "lake_trio": [480, 481, 482],
            "creation_trio": [483, 484, 487], "swords_of_justice": [638, 639, 640],
            "forces_of_nature": [641, 642, 645, 905], "tao_trio": [643, 644, 646],
            "aura_trio": [716, 717, 718], "guardian_deities": [785, 786, 787, 788],
            "light_trio": [791, 792, 800], "hero_duo": [888, 889],
            "calyrex_and_steeds": [896, 897, 898], "treasures_of_ruin": [1001, 1002, 1003, 1004],
            "paradox_duo": [1007, 1008], "loyal_three": [1014, 1015, 1016],
        }
        self.assertEqual({r["id"]: r["species_ids"] for r in rows}, expected)
        self.assertEqual(len(rows), len(expected))

    def test_conversion_rates_v11_star_piece_50_evolution_100_no_ticket(self):
        self.assertEqual(self.load("conversion_rates")["stardust_per_unit"], {
            "poke_ball": 2, "great_ball": 5, "ultra_ball": 10, "razz_berry": 5,
            "pinap_berry": 5, "golden_razz_berry": 25, "silver_pinap_berry": 25,
            "rare_candy": 20, "master_ball": 500, "shiny_lure": 500,
            "star_piece": 50, "evolution_item": 100, "companion_mirror": 500,
            "vitamin": 500, "bottlecap": 2500,
        })
        for item in ("companion_mirror", "vitamin", "bottlecap"):
            self.assertNotIn(item, self.load("capacities")["limits"]["rare_pockets"])

    def test_vitamin_price_and_ball_trade_up_rules(self):
        # Owner amendments 2026-11-12: Vitamin purchase and ball trade-up.
        table = self.load("conversion_rates")
        self.assertEqual(table["purchase_stardust"], {"vitamin": 5000})
        self.assertEqual(table["trade_up"], [
            {"from": "poke_ball", "to": "great_ball", "input_per_output": 2},
            {"from": "great_ball", "to": "ultra_ball", "input_per_output": 2},
        ])

    def test_evolution_table_costs_and_item_price(self):
        table = self.load("evolution")
        self.assertEqual(table["candy"], {"single_step": 50, "two_step": [25, 100]})
        self.assertEqual(table["item_price_stardust"], 500)
        self.assertEqual(table["star_piece"], {
            "multiplier_numerator": 3, "multiplier_denominator": 2,
            "rewards": 10, "rounding": "floor",
        })

    def test_expansion_limits_steps_caps_prices(self):
        self.assertEqual(self.load("capacities")["expansion"], {
            "storage": {"step": 50, "max": 1000, "stardust": 5000},
            "bag": {"step": 50, "max": 1000, "stardust": 2500},
        })

    def test_route_unlock_steps_two_free_then_increasing(self):
        routes = self.load("routes")["routes"]
        self.assertEqual([(r["id"], r["unlock_steps"]) for r in routes], [
            ("refreshing_field", 0), ("noisy_forest", 0), ("rugged_road", 1000),
            ("beautiful_beach", 2500), ("suburban_area", 5000), ("dim_cave", 8000),
            ("blue_lake", 12000), ("volcano_path", 18000),
        ])

    def test_powerup_bands_contiguous_to_80(self):
        table = self.load("powerup_prices")
        self.assertEqual(table["cap_level_x2"], 80)
        self.assertEqual(table["bands"], [
            {"min_level_x2": 2, "max_level_x2_exclusive": 20, "candy": 1, "stardust": 100},
            {"min_level_x2": 20, "max_level_x2_exclusive": 40, "candy": 2, "stardust": 250},
            {"min_level_x2": 40, "max_level_x2_exclusive": 60, "candy": 3, "stardust": 500},
            {"min_level_x2": 60, "max_level_x2_exclusive": 80, "candy": 4, "stardust": 1000},
        ])
        covered = [n for b in table["bands"] for n in range(b["min_level_x2"], b["max_level_x2_exclusive"])]
        self.assertEqual(covered, list(range(2, 80)))

    def test_every_table_has_source_checked_version(self):
        for name in TABLES:
            with self.subTest(name=name):
                table = self.load(name)
                self.assertIsInstance(table, dict)
                self.assertTrue(table["source"])
                date.fromisoformat(table["checked"])
                versions = {"find_table": 2, "conversion_rates": 4, "capacities": 3, "routes": 2,
                            "survivor_table": 3, "catch": 3, "gym_income_table": 2, "checkin_table": 2,
                            "battle": 2}
                self.assertEqual(table["version"], versions.get(name, 1))
                amended = {"survivor_table", "conversion_rates", "catch", "gym_income_table", "checkin_table"}
                if name in amended:
                    self.assertEqual(table["checked"], "2026-11-12")
                    if name != "catch":
                        self.assertIn("owner amendment Bottlecap and Vitamin (owner decision 2026-11-12)",
                                      table["source"])
                elif name == "battle":
                    self.assertEqual(table["checked"], "2026-11-12")
                    self.assertIn("D62 (owner decision 2026-11-12)", table["source"])
                elif name in versions.keys() | {"evolution"}:
                    self.assertEqual(table["checked"], "2026-11-05")
        root = Path(__file__).parents[1] / "content" / "balance"
        self.assertEqual({p.stem for p in root.glob("*.json")}, set(TABLES))

    def test_steps_catch_and_capacities_match_requirements(self):
        self.assertEqual(self.load("step_rules")["rules"], {
            "full_words_per_rolling_hour": 300, "full_step_hundredths": 100,
            "later_step_hundredths": 25, "min_message_words": 4,
            "max_message_words": 20, "repeat_word_cap": 3, "cooldown_seconds": 15,
            "accepted_words_per_rolling_minute": 30, "duplicate_window_seconds": 1800,
            "encounter_step_hundredths": 10000, "find_step_hundredths": 10000,
            "finds_per_rolling_hour": 3, "companion_candy_step_hundredths": 15000,
        })
        self.assertEqual(self.load("catch")["rules"], {
            "base_catch_rates": {"common": .5, "uncommon": .3, "rare": .15, "evolved": .15, "legendary": .05},
            "ball_multipliers": {"poke_ball": 1, "great_ball": 1.5, "ultra_ball": 2},
            "berry_multipliers": {"razz_berry": 1.5, "golden_razz_berry": 2.5, "silver_pinap_berry": 1.8, "pinap_berry": 1},
            "pinap_candy_multiplier": 2, "silver_pinap_candy": {"numerator": 7, "denominator": 3, "rounding": "floor"},
            "flee_probability": .1, "shiny_flee_probability": 0, "legendary_flee_probability": 0,
            "shiny_probability": 1 / 256, "lure_probability_multiplier": 4, "lure_encounters": 10,
            "mirror_encounters": 10, "mirror_probability": .2,
            "wild_level_range": [1, 20], "raid_level_range": [20, 25], "wild_iv_range": [0, 15], "starter_level": 10, "starter_iv_range": [10, 15],
        })
        self.assertEqual(self.load("capacities")["limits"], {
            "storage": 250, "bag_units": 250,
            "rare_pockets": {"master_ball": 1, "shiny_lure": 1, "world_legendary_ticket": 1},
            "encounter_queue": 3, "starter_kit": {"poke_ball": 30, "razz_berry": 5},
        })

    def test_loader_reads_each_table_from_disk_once_per_process(self):
        module = importlib.import_module("content.balance")
        module.load_table.cache_clear()
        self.addCleanup(module.load_table.cache_clear)
        self.load("catch")
        with patch.object(module, "Path", side_effect=AssertionError("re-read from disk")):
            self.assertEqual(self.load("catch")["rules"], self.load("catch")["rules"])
            module.load_table.cache_clear()
            with self.assertRaises(AssertionError):
                self.load("catch")

    def test_loader_rejects_paths_and_returns_fresh_tables(self):
        table = self.load("tier_chances")
        table["chances"]["common"] = -1
        self.assertEqual(self.load("tier_chances")["chances"]["common"], 60)
        for invalid in ("../step_rules", "..\\step_rules", "/step_rules", "step_rules.json", ""):
            with self.subTest(name=invalid), self.assertRaises(ValueError):
                self.load(invalid)
        with self.assertRaises(FileNotFoundError):
            self.load("missing")


if __name__ == "__main__":
    unittest.main()
