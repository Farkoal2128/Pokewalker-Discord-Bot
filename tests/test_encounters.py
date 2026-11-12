"""M1.3 artifact-to-frozen-encounter contract (D38, D50/D53, P4)."""

from collections import Counter, defaultdict
from dataclasses import FrozenInstanceError
import importlib
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from content.balance import load_table


class FixedRandom(random.Random):
    def __init__(self, value):
        super().__init__(1)
        self.value = value

    def random(self):
        return self.value


class EncounterTests(unittest.TestCase):
    def setUp(self):
        try:
            self.domain = importlib.import_module("pokewalker.domain.encounters")
        except ModuleNotFoundError:
            self.fail("M1.3 encounter provider absent")
        self.artifact = json.loads((Path(__file__).parent / "fixtures/content_mini/content/artifact/content.json")
                                   .read_text(encoding="utf-8"))
        self.pools = defaultdict(list)
        for identity in self.artifact["identities"]:
            self.pools[identity["tier"]].append(identity)
        self.chances = load_table("tier_chances")["chances"]
        self.rules = load_table("catch")["rules"]
        self.route = self.artifact["routes"]["all"]

    def test_legendary_exactly_one_percent_seeded(self):
        rng = random.Random(9)
        rolls = Counter(self.domain.roll_tier(self.pools, self.chances, rng)
                        for _ in range(100000))
        self.assertTrue(.009 <= rolls["Legendary/Mythical"] / 100000 <= .011, rolls)
        self.assertEqual(self.domain.roll_tier(self.pools, self.chances, FixedRandom(.009999)),
                         "Legendary/Mythical")
        self.assertNotEqual(self.domain.roll_tier(self.pools, self.chances, FixedRandom(.01)),
                            "Legendary/Mythical")

    def test_empty_tier_redistributes_to_non_legendary_only(self):
        pools = {tier: self.pools["Common"] for tier in ("Common", "Uncommon")}
        pools["Legendary/Mythical"] = self.pools["Legendary/Mythical"]
        rng = random.Random(42)
        rolls = Counter(self.domain.roll_tier(pools, self.chances, rng) for _ in range(50000))
        self.assertEqual(set(rolls), set(pools))
        self.assertAlmostEqual(rolls["Common"] / rolls["Uncommon"], 2, delta=.06)
        self.assertAlmostEqual(rolls["Legendary/Mythical"] / 50000, .01, delta=.001)
        with self.assertRaises(ValueError):
            self.domain.roll_tier({"Legendary/Mythical": [1]}, self.chances, FixedRandom(.5))

    def test_weight_zero_never_picked(self):
        pool = self.pools["Common"][:2]
        weights = {pool[0]["identity_id"]: 0, pool[1]["identity_id"]: 1}
        rng = random.Random(2)
        self.assertTrue(all(self.domain.pick_identity(pool, weights, rng) is pool[1]
                            for _ in range(1000)))
        with self.assertRaises(ValueError):
            self.domain.pick_identity(pool, {}, rng)
        with self.assertRaises(ValueError):
            self.domain.pick_identity(pool, {pool[0]["identity_id"]: -1,
                                            pool[1]["identity_id"]: 2}, rng)

    def test_weight_proportional_seeded(self):
        pool = self.pools["Common"][:2]
        weights = {pool[0]["identity_id"]: 1, pool[1]["identity_id"]: 3}
        rng = random.Random(5)
        first = sum(self.domain.pick_identity(pool, weights, rng) is pool[0]
                    for _ in range(30000))
        self.assertAlmostEqual(first / 30000, .25, delta=.01)

    def test_legendary_ignores_route(self):
        pool = self.pools["Legendary/Mythical"]
        weights = {pool[0]["identity_id"]: 100, pool[1]["identity_id"]: 0}
        rng = random.Random(4)
        counts = Counter(self.domain.pick_identity(pool, weights, rng)["identity_id"]
                         for _ in range(20000))
        self.assertEqual(set(counts), {i["identity_id"] for i in pool})
        self.assertAlmostEqual(counts[pool[0]["identity_id"]] / 20000, .5, delta=.02)
        encounter = self.domain.generate(self.pools, {"weights": {}}, False,
                                         FixedRandom(.001), chances=self.chances, rules=self.rules)
        self.assertEqual(encounter.tier, "Legendary/Mythical")

    def test_gender_rate_and_genderless(self):
        identity = dict(self.pools["Common"][0], gender_rate=1)
        rng = random.Random(3)
        count = sum(self.domain.roll_gender(identity, rng)[0] == "female" for _ in range(20000))
        self.assertAlmostEqual(count / 20000, .125, delta=.01)
        for rate, expected in ((-1, None), (0, "male"), (8, "female")):
            identity["gender_rate"] = rate
            gender, variety = self.domain.roll_gender(identity, FixedRandom(.5))
            self.assertEqual(gender, expected)
            self.assertIs(variety, identity)

    def test_three_species_50_50_forced_female_uses_female_variety_stats_and_sprite(self):
        for species in (876, 902, 916):
            identity = next(i for i in self.pools["Common"] if i["species_id"] == species)
            identity["gender_rate"] = 0
            for draw, gender in ((.49999, "female"), (.5, "male")):
                selected, variety = self.domain.roll_gender(identity, FixedRandom(draw))
                self.assertEqual(selected, gender)
                self.assertIs(variety, identity["gender_varieties"][gender])
            encounter = self.domain.generate({"Common": [identity]}, self.route, False,
                                             FixedRandom(.25), chances=self.chances, rules=self.rules)
            female = identity["gender_varieties"]["female"]
            self.assertEqual(encounter.pokemon_id, female["pokemon_id"])
            self.assertEqual((encounter.base_attack, encounter.base_defense, encounter.base_stamina),
                             tuple(female[k] for k in ("base_attack", "base_defense", "base_stamina")))
            self.assertEqual(encounter.sprites, female["sprites"])
            self.assertEqual(encounter.tier, identity["tier"])
            self.assertEqual(encounter.identity_id, identity["identity_id"])
            self.assertEqual(encounter.gender, "female")

    def test_shiny_lure_quadruples_seeded(self):
        rates = []
        for lure in (False, True):
            rng = random.Random(10)
            rates.append(sum(self.domain.roll_shiny(rng, lure, rules=self.rules)
                             for _ in range(100000)) / 100000)
        self.assertAlmostEqual(rates[0], 1 / 256, delta=.0005)
        self.assertAlmostEqual(rates[1], 1 / 64, delta=.001)
        self.assertTrue(self.domain.roll_shiny(FixedRandom(.01), True, rules=self.rules))
        self.assertFalse(self.domain.roll_shiny(FixedRandom(.01), False, rules=self.rules))

    def test_level_iv_ranges(self):
        rng = random.Random(7)
        rolls = [self.domain.roll_level_ivs(rng, rules=self.rules) for _ in range(10000)]
        self.assertEqual({level for level, _ in rolls}, set(range(2, 41, 2)))
        self.assertEqual({v for _, ivs in rolls for v in ivs}, set(range(16)))
        self.assertTrue(all(len(ivs) == 3 for _, ivs in rolls))
        for index in range(3):
            self.assertEqual({ivs[index] for _, ivs in rolls}, set(range(16)))
        self.assertTrue(any(len(set(ivs)) > 1 for _, ivs in rolls))
        counts = Counter(level for level, _ in rolls)
        self.assertTrue(all(400 <= n <= 600 for n in counts.values()), counts)

    def test_starter_rolls(self):
        rng = random.Random(8)
        rolls = [self.domain.starter_rolls(rng, rules=self.rules) for _ in range(1000)]
        self.assertEqual({level for level, _ in rolls}, {20})
        self.assertEqual({v for _, ivs in rolls for v in ivs}, set(range(10, 16)))

    def test_raid_level_range_is_20_to_25_while_wild_stays_1_to_20(self):
        rng = random.Random(4)
        raid = {self.domain.roll_level_ivs(rng, rules=self.rules, level_range="raid_level_range")[0]
                for _ in range(600)}
        self.assertEqual(raid, set(range(40, 51, 2)))
        wild = {self.domain.roll_level_ivs(rng, rules=self.rules)[0] for _ in range(2000)}
        self.assertEqual(wild, set(range(2, 41, 2)))

    def test_tables_are_injected(self):
        rules = dict(self.rules, shiny_probability=1, wild_level_range=[7, 7],
                     wild_iv_range=[9, 9], starter_level=3, starter_iv_range=[12, 12])
        self.assertTrue(self.domain.roll_shiny(random.Random(1), False, rules=rules))
        self.assertEqual(self.domain.roll_level_ivs(random.Random(1), rules=rules),
                         (14, (9, 9, 9)))
        self.assertEqual(self.domain.starter_rolls(random.Random(1), rules=rules),
                         (6, (12, 12, 12)))

    def test_generate_frozen_detached_reproducible_and_no_io(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("domain I/O")):
            first = self.domain.generate(self.pools, self.route, True, random.Random(6),
                                          chances=self.chances, rules=self.rules)
            second = self.domain.generate(self.pools, self.route, True, random.Random(6),
                                           chances=self.chances, rules=self.rules)
        self.assertEqual(first, second)
        with self.assertRaises(FrozenInstanceError):
            first.level_x2 = 80
        with self.assertRaises(TypeError):
            first.sprites["normal"] = "changed"
        selected = next(i for i in self.artifact["identities"] if i["identity_id"] == first.identity_id)
        selected["sprites"]["normal"] = "changed"
        self.assertNotEqual(first.sprites["normal"], "changed")


if __name__ == "__main__":
    unittest.main()
