"""M1.3 CP, appraisal, catch and flee contracts (D36, P5/P8)."""

import importlib
import math
import random
import unittest

from content.balance import load_table


class CpTests(unittest.TestCase):
    def setUp(self):
        try:
            self.domain = importlib.import_module("pokewalker.domain.cp")
        except ModuleNotFoundError:
            self.fail("M1.3 CP/catch provider absent")
        self.multipliers = load_table("cpm")["multipliers"]
        self.rules = load_table("catch")["rules"]

    def test_cp_min_10_and_floor_from_unrounded_inputs(self):
        self.assertEqual(self.domain.cp((1, 1, 1), (0, 0, 0), 2,
                                        multipliers=self.multipliers), 10)
        base, ivs, m = (118, 111, 128), (3, 7, 11), self.multipliers["37"]
        expected = math.floor(121 * math.sqrt(118) * math.sqrt(139) * m ** 2 / 10)
        self.assertEqual(self.domain.cp(base, ivs, 37, multipliers=self.multipliers), expected)
        self.assertEqual(self.domain.hp(base, ivs, 37, multipliers=self.multipliers),
                         math.floor(139 * m))
        self.assertEqual(self.domain.hp((1, 1, 1), (0, 0, 0), 2,
                                       multipliers=self.multipliers), 10)

    def test_cp_example_100_100_100_level20_is_356(self):
        self.assertEqual(self.domain.cpm(40, multipliers=self.multipliers), .5974)
        self.assertEqual(self.domain.cp((100, 100, 100), (0, 0, 0), 40,
                                        multipliers=self.multipliers), 356)
        self.assertEqual(self.domain.cpm(3, multipliers=self.multipliers), .1351374318)
        for level in (True, 40.0, 1, 81):
            with self.subTest(level=level), self.assertRaises(ValueError):
                self.domain.cpm(level, multipliers=self.multipliers)

    def test_appraisal_bands(self):
        for total, stars in ((0, 0), (22, 0), (23, 1), (29, 1), (30, 2),
                             (36, 2), (37, 3), (44, 3), (45, 4)):
            ivs = (min(15, total), min(15, max(0, total - 15)), max(0, total - 30))
            with self.subTest(total=total):
                self.assertEqual(self.domain.appraisal(ivs), stars)
        for ivs in ((16, 0, 0), (-1, 0, 0), (True, 0, 0), (1, 2)):
            with self.subTest(ivs=ivs), self.assertRaises(ValueError):
                self.domain.appraisal(ivs)

    def test_catch_probability_examples(self):
        for ball, berry, expected in ((1, 1, .251), (2, 1.5, .580)):
            self.assertAlmostEqual(self.domain.catch_probability(.3, 40, ball, berry,
                                   multipliers=self.multipliers), expected, delta=.002)
        for bcr, expected in ((-1, 0), (0, 0), (2, 1)):
            self.assertEqual(self.domain.catch_probability(bcr, 2, 1, 1,
                             multipliers=self.multipliers), expected)
        for args in ((math.nan, 1, 1), (.3, 0, 1), (.3, 1, math.inf)):
            with self.assertRaises(ValueError):
                self.domain.catch_probability(args[0], 40, *args[1:],
                                               multipliers=self.multipliers)

    def test_flee_rules(self):
        for tier in ("Common", "Uncommon", "Rare", "Evolved"):
            rng = random.Random(35)
            observed = sum(self.domain.flees_after_failure(tier, False, rng,
                           rules=self.rules) for _ in range(20000)) / 20000
            self.assertAlmostEqual(observed, .1, delta=.01)
            self.assertFalse(self.domain.flees_after_failure(tier, True, rng,
                                                            rules=self.rules))
        for shiny in (False, True):
            self.assertFalse(self.domain.flees_after_failure("Legendary/Mythical", shiny,
                             random.Random(1), rules=self.rules))

    def test_tables_are_injected(self):
        self.assertEqual(self.domain.cp((100, 100, 100), (0, 0, 0), 40,
                                        multipliers={"40": .5}), 250)
        rules = dict(self.rules, flee_probability=1)
        self.assertTrue(self.domain.flees_after_failure("Common", False,
                                                        random.Random(3), rules=rules))


if __name__ == "__main__":
    unittest.main()
