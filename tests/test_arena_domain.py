"""Pure Arena rules from AR-14a, AR-16..24 and AR-32..33."""

import copy
import importlib
import json
from pathlib import Path
import random
import unittest
from unittest.mock import Mock, call, patch

from content.balance import load_table


class ArenaDomainTests(unittest.TestCase):
    def setUp(self):
        try:
            self.arena = importlib.import_module("pokewalker.domain.arena")
        except ModuleNotFoundError:
            self.fail("Arena domain provider absent")
        self.rules = load_table("arena")["rules"]
        artifact = Path(__file__).parents[1] / "content/artifact/content.json"
        self.identities = json.loads(artifact.read_bytes())["identities"]

    def test_level_is_floor_until_40_then_flat(self):
        for floor in range(1, 201):
            with self.subTest(floor=floor):
                self.assertEqual(self.arena.level_x2(floor, self.rules), 2 * min(floor, 40))
        self.rules["level_cap"] = 20
        self.assertEqual(self.arena.level_x2(30, self.rules), 40)

    def test_iv_bounds_match_requirement_table(self):
        cases = ((1, 0, (0, 0, 0)), (45, 1, (1, 0, 0)), (50, 2, (1, 1, 0)),
                 (55, 3, (1, 1, 1)), (60, 4, (2, 1, 1)), (90, 10, (4, 3, 3)),
                 (100, 12, (4, 4, 4)), (115, 15, (5, 5, 5)), (125, 15, (5, 5, 5)))
        for floor, steps, gains in cases:
            self.assertEqual(self.arena.late_steps(floor, self.rules), steps)
            for slot, offset in enumerate((0, 5, 10)):
                with self.subTest(floor=floor, slot=slot):
                    self.assertEqual(self.arena.iv_bounds(slot, floor, self.rules),
                                     tuple((offset + gain, offset + 5) for gain in gains))

    def test_hp_factor_matches_requirement_table(self):
        cases = ((1, 10), (40, 10), (41, 10), (42, 10), (43, 10), (44, 10),
                 (45, 11), (50, 12), (60, 14), (90, 20), (115, 20), (116, 21), (125, 30))
        for floor, factor in cases:
            with self.subTest(floor=floor):
                self.assertEqual(self.arena.hp_factor_x10(floor, self.rules), factor)
        for hp, factor, expected in ((101, 10, 101), (101, 11, 112), (101, 21, 213),
                                     (10**20 + 1, 13, 130000000000000000002)):
            self.assertEqual(self.arena.enemy_hp(hp, factor), expected)
        self.rules["late"]["uncapped_after_floor"] = 120
        self.rules["late"]["uncapped_step_x10"] = 2
        self.assertEqual(self.arena.hp_factor_x10(121, self.rules), 22)

    def test_bst_caps_match_requirement_table(self):
        for floor, base, boss in ((1, 300, 345), (5, 354, 407), (10, 422, 633),
                                  (20, 557, 720), (30, 693, 720), (32, 720, 720), (40, 720, 720)):
            with self.subTest(floor=floor):
                self.assertEqual(self.arena.bst_cap(floor, self.rules), base)
                self.assertEqual(self.arena.boss_cap(floor, self.rules), boss)

    def test_pool_sizes_match_requirement_table(self):
        for floor, entry, regular_boss, special_boss in ((1, 177, 328, 2), (5, 344, 438, 4),
                                                        (10, 484, 965, 105), (20, 952, 966, 128)):
            for slot, draw, size in ((0, 99, entry), (1, 99, entry),
                                     (2, 99, regular_boss), (2, 0, special_boss)):
                with self.subTest(floor=floor, slot=slot, draw=draw):
                    rng = Mock()
                    rng.randrange.return_value = draw
                    rng.choice.side_effect = lambda pool: pool[-1]
                    self.arena.pick_identity(floor, slot, self.identities, rng, self.rules)
                    pool = rng.choice.call_args.args[0]
                    self.assertEqual(len(pool), size)
                    self.assertTrue(all(self.arena.is_special(i, self.rules) == (slot == 2 and draw == 0)
                                        for i in pool))

    def test_entry_and_middle_never_special(self):
        for floor in (1, 5, 10, 20, 40, 125):
            for slot in (0, 1):
                rng = Mock()
                rng.choice.side_effect = lambda pool: pool[-1]
                chosen = self.arena.pick_identity(floor, slot, self.identities, rng, self.rules)
                self.assertFalse(self.arena.is_special(chosen, self.rules))
                self.assertLessEqual(chosen["bst"], self.arena.bst_cap(floor, self.rules))
                rng.randrange.assert_not_called()
        for species, expected in ((1, False), (150, True), (151, True), (793, True), (984, True)):
            identity = next(i for i in self.identities if i["species_id"] == species)
            self.assertIs(self.arena.is_special(identity, self.rules), expected)

    def test_boss_special_reserved_draw_5_and_25_percent(self):
        for floor, chance in ((5, 5), (10, 25)):
            special_count = 0
            for draw in range(100):
                rng = Mock()
                rng.randrange.return_value = draw
                rng.choice.side_effect = lambda pool: pool[-1]
                chosen = self.arena.pick_identity(floor, 2, self.identities, rng, self.rules)
                self.assertEqual(self.arena.is_special(chosen, self.rules), draw < chance)
                special_count += self.arena.is_special(chosen, self.rules)
                rng.randrange.assert_called_once_with(100)
                rng.choice.assert_called_once()
            self.assertEqual(special_count, chance)

    def test_boss_falls_back_to_regular_when_no_special_fits(self):
        identities = [next(i for i in self.identities if i["species_id"] == sid) for sid in (1, 150)]
        rng = Mock()
        rng.randrange.return_value = 0
        rng.choice.side_effect = lambda pool: pool[0]
        self.assertIs(self.arena.pick_identity(1, 2, identities, rng, self.rules), identities[0])
        rng.choice.assert_called_once_with([identities[0]])

    def test_max_skip_half_best_floor_capped_at_40(self):
        for best, expected in ((0, 0), (1, 0), (30, 15), (79, 39), (80, 40), (200, 40)):
            self.assertEqual(self.arena.max_skip(best, self.rules), expected)
        self.rules['skip'] = {'divisor': 3, 'max': 8}
        self.assertEqual(self.arena.max_skip(30, self.rules), 8)

    def test_skip_tickets_follow_schedule(self):
        self.assertEqual(self.arena.skip_tickets(0, self.rules), {})
        self.assertEqual(self.arena.skip_tickets(40, self.rules), {'bronze': 2, 'silver': 4, 'gold': 2})
        self.rules['tickets']['schedule']['bronze']['floors'] = [3]
        self.assertEqual(self.arena.skip_tickets(3, self.rules), {'bronze': 1})

    def test_hurt_is_strictly_below_and_hp_order_keeps_ties(self):
        self.assertIsNone(self.arena.hurt([(50, 100), (1, 2)], 50))
        self.assertEqual(self.arena.hurt([(50, 100), (49, 100), (1, 10)], 50), 1)
        self.assertEqual(self.arena.hp_order([(60, 100), (8, 10), (90, 100), (4, 5)]), [2, 1, 3, 0])
        huge = 10 ** 20
        self.assertEqual(self.arena.hp_order([(huge - 1, huge), (huge, huge)]), [1, 0])

    def test_ticket_schedule_floors_1_to_100(self):
        expected = {5: "bronze", 10: "silver", 15: "bronze", 20: "silver", 25: "gold",
                    30: "silver", 35: "gold", 40: "silver", 45: "gold", 50: "platinum",
                    55: "gold", 60: "platinum", 65: "gold", 70: "platinum", 75: "gold",
                    80: "diamond", 85: "gold", 90: "diamond", 95: "gold", 100: "diamond"}
        for floor in range(1, 101):
            with self.subTest(floor=floor):
                self.assertEqual(self.arena.ticket_for(floor, self.rules), expected.get(floor))
        self.rules["tickets"]["schedule"]["bronze"]["floors"] = [3]
        self.assertEqual(self.arena.ticket_for(3, self.rules), "bronze")
        self.assertIsNone(self.arena.ticket_for(5, self.rules))

    def test_first_clear_bonus_only_silver_or_better_above_best_floor(self):
        for floor in range(1, 101):
            tier = self.arena.ticket_for(floor, self.rules)
            for best in (0, floor - 1, floor, floor + 1):
                with self.subTest(floor=floor, best=best):
                    expected = floor > best and tier in ("silver", "gold", "platinum", "diamond")
                    self.assertIs(self.arena.first_clear_bonus(floor, best, self.rules), expected)

    def test_special_finisher_earns_candy_only_from_boss(self):
        for special in (False, True):
            for slot in range(3):
                self.assertEqual(self.arena.candy_for(special, slot, self.rules),
                                 int(not special or slot == 2))
        self.rules["candy"] = {"per_knockout": 2, "special_boss_only": False}
        self.assertEqual(self.arena.candy_for(True, 0, self.rules), 2)

    def test_revive_lifts_fainted_to_one_hp(self):
        original = [0, 1, 57]
        self.assertEqual(self.arena.revive(original), [1, 1, 57])
        self.assertEqual(original, [0, 1, 57])
        self.assertEqual(self.arena.revive((0, 0, 0)), [1, 1, 1])

    def test_roll_ivs_uses_inclusive_bounds_in_stat_order(self):
        rng = Mock()
        rng.randint.side_effect = [2, 5, 1]
        self.assertEqual(self.arena.roll_ivs(0, 60, rng, self.rules), (2, 5, 1))
        self.assertEqual(rng.mock_calls, [call.randint(2, 5), call.randint(1, 5), call.randint(1, 5)])

    def test_same_seed_same_enemy(self):
        before = copy.deepcopy((self.identities, self.rules))
        with patch("builtins.open", side_effect=AssertionError("I/O forbidden")), \
                patch("time.time", side_effect=AssertionError("clock forbidden")), \
                patch("random.choice", side_effect=AssertionError("global RNG forbidden")):
            first = self.arena.roll_enemy(45, 2, self.identities, random.Random(204), self.rules)
            second = self.arena.roll_enemy(45, 2, self.identities, random.Random(204), self.rules)
        self.assertEqual(first, second)
        self.assertEqual((self.identities, self.rules), before)
        rng = Mock()
        rng.randrange.return_value = 0
        rng.choice.side_effect = lambda pool: pool[0]
        rng.randint.side_effect = [11, 12, 13]
        enemy = self.arena.roll_enemy(45, 2, self.identities, rng, self.rules)
        self.assertEqual([c[0] for c in rng.mock_calls],
                         ["randrange", "choice", "randint", "randint", "randint"])
        self.assertEqual(rng.randint.call_args_list,
                         [call(11, 15), call(10, 15), call(10, 15)])
        self.assertEqual(enemy, {"identity": rng.choice.call_args.args[0][0], "level_x2": 80,
                                "ivs": (11, 12, 13), "factor_x10": 11, "special": True})

    def test_invalid_floor_slot_and_hp_rejected(self):
        for floor in (0, -1, True, 1.5):
            for name in ("level_x2", "late_steps", "hp_factor_x10", "bst_cap", "boss_cap", "ticket_for"):
                with self.subTest(floor=floor, function=name), self.assertRaises(ValueError):
                    getattr(self.arena, name)(floor, self.rules)
        for slot in (-1, 3, True, 1.5):
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                self.arena.iv_bounds(slot, 1, self.rules)
            with self.assertRaises(ValueError):
                self.arena.pick_identity(1, slot, self.identities, random.Random(1), self.rules)
            with self.assertRaises(ValueError):
                self.arena.candy_for(False, slot, self.rules)
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                self.arena.enemy_hp(value, 10)
            with self.assertRaises(ValueError):
                self.arena.enemy_hp(100, value)
        for best_floor in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                self.arena.first_clear_bonus(10, best_floor, self.rules)
        with self.assertRaises(ValueError):
            self.arena.pick_identity(1, 0, [], random.Random(1), self.rules)


if __name__ == "__main__":
    unittest.main()
