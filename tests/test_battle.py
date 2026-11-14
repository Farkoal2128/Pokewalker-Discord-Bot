"""C7 deterministic battle behavior, timing and arithmetic."""

import copy
import importlib
import json
import math
from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest
from unittest.mock import patch

from content.balance import load_table


class BattleTests(unittest.TestCase):
    def setUp(self):
        try:
            self.battle = importlib.import_module("pokewalker.domain.battle")
        except ModuleNotFoundError:
            self.fail("C7 battle provider absent")
        self.rules = load_table("battle")["rules"]
        self.chart = json.loads((Path(__file__).parents[1] /
                                "content/artifact/content.json").read_bytes())["type_chart"]

    def fighter(self, name="A", **changes):
        fields = dict(name=name, types=("normal",), attack=100, defense=100,
                      hp=1000, fast_type="normal", charged_type="normal")
        fields.update(changes)
        return self.battle.Combatant(**fields)

    def run_battle(self, party=None, defender=None, hp=10000, **rules):
        return self.battle.simulate(
            party if party is not None else [self.fighter()],
            defender if defender is not None else self.fighter("D"), hp,
            rules=dict(self.rules, **rules), chart=self.chart)

    def test_party_hp_lists_end_hp_in_party_order_with_zero_for_fainted(self):
        party = [self.fighter(hp=4), self.fighter("B", hp=13), self.fighter("C", hp=29)]
        result = self.run_battle(party, tick_limit=3)
        self.assertEqual(result.party_hp, (0, 5, 29))
        self.assertEqual(result.survivors, (1, 2))

    def test_bench_member_keeps_starting_hp(self):
        party = [self.fighter(hp=10), self.fighter("B", hp=23), self.fighter("C", hp=41)]
        result = self.run_battle(party, hp=4)
        self.assertEqual(result.outcome, "win")
        self.assertEqual(result.party_hp, (6, 23, 41))

    def test_starting_hp_below_canonical_is_used_as_given(self):
        multipliers = load_table("cpm")["multipliers"]
        attack, defense, canonical_hp = self.battle.combat_stats(
            (100, 100, 100), (0, 0, 0), 80, multipliers)
        self.assertLess(5, canonical_hp)
        fighter = self.fighter(attack=attack, defense=defense, hp=5)
        defender = self.fighter("D", attack=attack, defense=defense)
        result = self.run_battle([fighter], defender, tick_limit=2)
        self.assertEqual((result.outcome, result.reason, result.ticks),
                         ("loss", "party_fainted", 2))
        self.assertEqual(result.party_hp, (0,))
        full = self.run_battle([self.fighter(attack=attack, defense=defense, hp=canonical_hp)],
                               defender, tick_limit=2)
        self.assertEqual((full.outcome, full.party_hp), ("draw", (canonical_hp - 8,)))
        self.assertEqual(fighter.hp, 5)

    def test_finisher_is_position_of_the_knockout_hit_after_substitution(self):
        party = [self.fighter(hp=4), self.fighter("B", hp=4), self.fighter("C", hp=100)]
        result = self.run_battle(party, hp=12)
        self.assertEqual((result.outcome, result.ticks, result.finisher), ("win", 3, 2))
        self.assertEqual(result.party_hp, (0, 0, 96))
        result = self.run_battle([self.fighter(hp=4), self.fighter("B", hp=23)], hp=4)
        self.assertEqual((result.outcome, result.finisher, result.party_hp),
                         ("win", 0, (0, 23)))

    def test_finisher_set_on_double_knockout_draw(self):
        result = self.run_battle([self.fighter(hp=4)], hp=4)
        self.assertEqual((result.outcome, result.reason, result.finisher, result.party_hp),
                         ("draw", "defender_fainted", 0, (0,)))

    def test_finisher_none_on_loss_and_tick_limit(self):
        loss = self.run_battle([self.fighter(hp=4)], hp=5)
        limit = self.run_battle([self.fighter(hp=100000)], hp=100000)
        pending = self.run_battle([self.fighter(hp=100000)], hp=57, tick_limit=6)
        for result, reason in ((loss, "party_fainted"), (limit, "tick_limit"),
                               (pending, "tick_limit")):
            with self.subTest(reason=reason, ticks=result.ticks):
                self.assertEqual(result.reason, reason)
                self.assertIsNone(result.finisher)
        self.assertEqual(loss.party_hp, (0,))
        self.assertEqual(pending.party_hp, (99980,))

    def test_result_positional_constructor_still_valid(self):
        for version in ((), ("legacy",)):
            with self.subTest(version=version):
                result = self.battle.Result("win", "defender_fainted", 1, (0,), ("event",),
                                            *version)
                self.assertEqual((result.outcome, result.reason, result.ticks,
                                  result.survivors, result.events, result.engine_version),
                                 ("win", "defender_fainted", 1, (0,), ("event",),
                                  version[0] if version else "1"))
                self.assertEqual(result.party_hp, ())
                self.assertIsNone(result.finisher)

    def test_damage_equal_stats_fast_4_charged_37(self):
        self.assertEqual(self.battle.damage(6, 100, 100, 1.2, 1), 4)
        self.assertEqual(self.battle.damage(60, 100, 100, 1.2, 1), 37)
        self.assertEqual(self.battle.damage(0, 100, 100, 1, 1), 1)

    def test_seven_tick_cycle_deals_57_and_is_deterministic(self):
        result = self.run_battle(tick_limit=7)
        self.assertEqual(result, self.run_battle(tick_limit=7))
        hits = [line for line in result.events if "A " in line and "hits D" in line]
        self.assertEqual(len(hits), 6)
        self.assertEqual(sum(int(line.split(" for ")[1].rstrip(".")) for line in hits), 57)
        self.assertTrue(any(line.startswith("7:") and "A charged" in line for line in hits))
        self.assertEqual(result.engine_version, "1")

    def test_stab_only_when_move_type_in_user_types(self):
        attacker = self.fighter(types=("water",), fast_type="normal", charged_type="water")
        result = self.run_battle([attacker], tick_limit=7)
        self.assertIn("1: A fast hits D for 4.", result.events)
        self.assertIn("7: A charged hits D for 37.", result.events)
        # STAB boundary is visible at power 6 with unequal stats.
        attacker = self.fighter(types=("water",), attack=150)
        result = self.run_battle([attacker], tick_limit=1)
        self.assertIn("1: A fast hits D for 5.", result.events)
        attacker = self.fighter(types=("normal", "water"), attack=150)
        self.assertIn("1: A fast hits D for 6.",
                      self.run_battle([attacker], tick_limit=1).events)

    def test_effectiveness_products_double_weakness_2_56(self):
        self.assertAlmostEqual(self.battle.effectiveness("ice", ("grass", "flying"),
                                                       self.chart), 2.56)
        self.assertEqual(self.battle.effectiveness("normal", ("ghost",), self.chart),
                         .390625)
        self.assertEqual(self.battle.effectiveness("fire", ("water", "dragon"), self.chart),
                         .625 * .625)

    def test_neutral_matchup_factor_1(self):
        self.assertEqual(self.battle.effectiveness("normal", ("normal",), self.chart), 1)

    def test_defender_hp_d32_hours_0_to_7_and_clamp(self):
        for hour, expected in enumerate((202, 192, 182, 172, 162, 152, 142, 132)):
            self.assertEqual(self.battle.defender_hp(101, hour), expected)
        self.assertEqual(self.battle.defender_hp(101, -1), 202)
        self.assertEqual(self.battle.defender_hp(101, 8), 132)
        self.assertEqual(self.battle.defender_hp(10**20 + 1, 7),
                         130000000000000000002)

    def test_simultaneous_ko_is_draw(self):
        result = self.run_battle([self.fighter(hp=4)], hp=4)
        self.assertEqual((result.outcome, result.reason, result.ticks, result.survivors),
                         ("draw", "defender_fainted", 1, ()))
        self.assertIn("1: A fast hits D for 4.", result.events)
        self.assertIn("1: D fast hits A for 4.", result.events)

    def test_fainted_attacker_pending_move_cancelled(self):
        party = [self.fighter(hp=4), self.fighter("B", hp=20), self.fighter("C")]
        result = self.run_battle(party, tick_limit=8)
        self.assertIn("7: B fainted.", result.events)
        self.assertFalse(any("B charged hits" in line for line in result.events))
        self.assertIn("8: C fast hits D for 4.", result.events)

    def test_substitution_immediate_zero_energy(self):
        party = [self.fighter(hp=4), self.fighter("B")]
        result = self.run_battle(party, tick_limit=8)
        self.assertIn("1: B enters with 0 energy.", result.events)
        self.assertIn("2: B fast hits D for 4.", result.events)
        self.assertIn("7: D charged hits B for 37.", result.events)
        self.assertIn("8: B charged hits D for 37.", result.events)
        self.assertFalse(any("6: B charged" in line for line in result.events))

    def test_pending_hit_strikes_replacement(self):
        party = [self.fighter(hp=4), self.fighter("B", hp=20), self.fighter("C")]
        result = self.run_battle(party, tick_limit=8)
        self.assertIn("7: C enters with 0 energy.", result.events)
        self.assertIn("8: D fast hits C for 4.", result.events)
        self.assertFalse(any("8: D fast hits B" in line for line in result.events))

    def test_tick_limit_120_draw_reason(self):
        result = self.run_battle([self.fighter(hp=100000)], hp=100000)
        self.assertEqual((result.outcome, result.reason, result.ticks),
                         ("draw", "tick_limit", 120))
        # A completion at the limit counts; a pending completion beyond it does not.
        result = self.run_battle([self.fighter(hp=100000)], hp=57, tick_limit=6)
        self.assertEqual((result.outcome, result.ticks), ("draw", 6))
        result = self.run_battle([self.fighter(hp=100000)], hp=57, tick_limit=7)
        self.assertEqual((result.outcome, result.ticks), ("win", 7))
        result = self.run_battle([self.fighter(hp=100000)], hp=17 * 57 + 4)
        self.assertEqual((result.outcome, result.ticks), ("win", 120))

    def test_win_requires_healthy_survivor_after_tick(self):
        result = self.run_battle([self.fighter(hp=4), self.fighter("B")], hp=4)
        self.assertEqual((result.outcome, result.survivors), ("win", (1,)))
        result = self.run_battle([self.fighter(hp=5)], hp=4)
        self.assertEqual((result.outcome, result.survivors), ("win", (0,)))
        result = self.run_battle([self.fighter(hp=4)], hp=5)
        self.assertEqual((result.outcome, result.reason, result.survivors),
                         ("loss", "party_fainted", ()))

    def test_events_bounded_and_text_only(self):
        result = self.run_battle([self.fighter(hp=100000)], hp=100000)
        self.assertEqual(len(result.events), 40)
        self.assertTrue(all(isinstance(line, str) and "\n" not in line and "\r" not in line
                            for line in result.events))
        self.assertIn("draw", result.events[-1])

    def test_same_inputs_same_result_no_rng(self):
        types = ["normal"]
        party = [self.fighter(types=types)]
        types.append("water")
        self.assertEqual(party[0].types, ("normal",))
        defender = self.fighter("D")
        before = copy.deepcopy((party, defender, self.rules, self.chart))
        with patch("random.random", side_effect=AssertionError("RNG forbidden")):
            one = self.run_battle(party, defender)
            two = self.run_battle(party, defender)
        self.assertEqual(one, two)
        self.assertEqual((party, defender, self.rules, self.chart), before)
        with self.assertRaises(FrozenInstanceError):
            party[0].hp = 1
        with self.assertRaises(FrozenInstanceError):
            one.outcome = "win"

    def test_combat_stats_reuses_cp_validation_and_unrounded_values(self):
        multipliers = load_table("cpm")["multipliers"]
        self.assertEqual(self.battle.combat_stats((118, 111, 128), (3, 7, 11), 37,
                                                 multipliers),
                         (121 * multipliers["37"], 118 * multipliers["37"],
                          math.floor(139 * multipliers["37"])))
        self.assertEqual(self.battle.combat_stats((1, 1, 1), (0, 0, 0), 2,
                                                 multipliers)[2], 10)
        for base, ivs, level in (((0, 1, 1), (0, 0, 0), 2),
                                  ((1, 1, 1), (16, 0, 0), 2),
                                  ((1, 1, 1), (0, 0, 0), True)):
            with self.assertRaises(ValueError):
                self.battle.combat_stats(base, ivs, level, multipliers)

    def test_energy_cap_and_no_energy_from_incoming_damage(self):
        rules = dict(self.rules["fast"], energy=1000)
        result = self.run_battle(tick_limit=6, fast=rules)
        for event in ("1: A fast hits D for 4.", "3: A charged hits D for 37.",
                      "5: A charged hits D for 37.", "6: A fast hits D for 4."):
            self.assertIn(event, result.events)
        # Under the real templates incoming hits must not fund an early charge.
        result = self.run_battle(tick_limit=7)
        self.assertFalse(any("charged" in line and not line.startswith("7:")
                             for line in result.events))

    def test_defender_hp_is_retained_across_substitution(self):
        result = self.run_battle([self.fighter(hp=4), self.fighter("B")], hp=24)
        self.assertEqual((result.outcome, result.ticks), ("win", 6))

    def test_invalid_inputs_raise(self):
        for party in ([], [self.fighter()] * 4):
            with self.assertRaises(ValueError):
                self.run_battle(party)
        for hp in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                self.fighter(hp=hp)
            with self.assertRaises(ValueError):
                self.run_battle(hp=hp)
            with self.assertRaises(ValueError):
                self.battle.defender_hp(hp, 0)
        for changes in (dict(attack=0), dict(defense=math.inf), dict(attack=math.nan),
                        dict(types=()), dict(types=("normal", "normal")),
                        dict(name="bad\nname")):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.fighter(**changes)
        with self.assertRaises(ValueError):
            self.run_battle([self.fighter(fast_type="unknown")])
        for args in ((6, 1, 0, 1, 1), (6, math.nan, 1, 1, 1), (-1, 1, 1, 1, 1)):
            with self.assertRaises(ValueError):
                self.battle.damage(*args)
        with self.assertRaises(ValueError):
            self.battle.defender_hp(10, 1.5)


if __name__ == "__main__":
    unittest.main()
