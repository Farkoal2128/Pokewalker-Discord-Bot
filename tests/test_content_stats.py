"""D39 stat conversion and D53 attached-variety contract."""

import csv
import importlib
import shutil
import tempfile
import unittest
from pathlib import Path

from content.build.graph import load_graph


FIXTURES = Path(__file__).parent / "fixtures" / "pokeapi_mini"


class ContentStatsTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module("content.build.stats")
        except ModuleNotFoundError:
            self.fail("M0.2 stats provider absent: D39 conversion unavailable")

    def stats(self, **changes):
        return dict(dict.fromkeys(("hp", "attack", "defense", "special-attack",
                                   "special-defense", "speed"), 50), **changes)

    def test_d39_fixture_rounds_half_up(self):
        result = self.module().derive_stats(self.stats(attack=5, **{"special-attack": 35}))
        self.assertEqual(result["base_attack"], 60)
        self.assertEqual(result["stats_source"], "derived-d39")
        self.assertEqual(result["bst"], 240)

    def test_stamina_floors(self):
        result = self.module().derive_stats(self.stats(hp=3))
        self.assertEqual(result["base_stamina"], 55)

    def test_defense_blends_high_low_then_speed(self):
        result = self.module().derive_stats(self.stats(defense=5, **{"special-defense": 35}))
        self.assertEqual(result["base_defense"], 46)
        self.assertEqual(self.module().derive_stats(self.stats(speed=75))["base_attack"], 100)

    def test_gender_variety_own_stats_tier_from_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            shutil.copytree(FIXTURES, directory, dirs_exist_ok=True)
            path = directory / "pokemon_stats.csv"
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                fields, rows = reader.fieldnames, list(reader)
            for row in rows:
                if row["pokemon_id"] == "10254" and row["stat_id"] == "2":
                    row["base_stat"] = "100"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            identities = load_graph(directory)["identities"]
            self.module().add_stats(identities, directory)
        oinkologne = next(i for i in identities if i["species_id"] == 916)
        male, female = (oinkologne["gender_varieties"][g] for g in ("male", "female"))
        self.assertEqual(oinkologne["bst"], male["bst"])
        self.assertEqual((male["bst"], female["bst"]), (336, 380))
        self.assertNotEqual(male["base_attack"], female["base_attack"])
        for value in identities + [male, female]:
            self.assertEqual(value["stats_source"], "derived-d39")
            self.assertGreater(value["base_attack"], 0)
            self.assertGreater(value["base_defense"], 0)
            self.assertGreater(value["base_stamina"], 0)

    def test_outer_round_also_rounds_half_up(self):
        result = self.module().derive_stats(self.stats(attack=5, speed=100, **{"special-attack": 5}))
        self.assertEqual(result["base_attack"], 11)

    def test_invalid_main_series_stats_are_build_error(self):
        for stats in ({"hp": 3}, self.stats(hp=0), self.stats(hp=-2), self.stats(hp=1.5)):
            with self.subTest(stats=stats), self.assertRaises(ValueError):
                self.module().derive_stats(stats)


if __name__ == "__main__":
    unittest.main()
