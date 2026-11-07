"""D38/D40a/D54 family topology, tier precedence and rewards."""

import csv
import importlib
import tempfile
import unittest
from pathlib import Path

from content.build.graph import load_graph


FIXTURES = Path(__file__).parent / "fixtures" / "pokeapi_mini"


class ContentFamiliesTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module("content.build.families")
        except ModuleNotFoundError:
            self.fail("M0.2 families provider absent: family tiers unavailable")

    def species(self, sid, chain, parent="", legendary=0, mythical=0):
        return dict(id=sid, evolution_chain_id=chain, evolves_from_species_id=parent,
                    is_legendary=legendary, is_mythical=mythical)

    def directory(self, rows):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        with (directory / "pokemon_species.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return directory

    def apply(self, rows, identities):
        self.module().add_families(identities, self.directory(rows))
        return identities

    def test_tier_order_legendary_first(self):
        rows = [self.species(1, 1), self.species(2, 1, 1, legendary=1),
                self.species(3, 2, mythical=1)]
        identities = self.apply(rows, [{"species_id": s, "bst": 600} for s in (1, 2, 3)])
        self.assertEqual([i["tier"] for i in identities],
                         ["Rare", "Legendary/Mythical", "Legendary/Mythical"])
        self.assertTrue(identities[1]["is_legendary"])
        self.assertTrue(identities[2]["is_mythical"])

    def test_evolved_requires_final_and_multi_member(self):
        rows = [self.species(1, 1), self.species(2, 1, 1), self.species(3, 1, 2),
                self.species(4, 2)]
        identities = self.apply(rows, [{"species_id": s, "bst": 300} for s in range(1, 5)])
        self.assertEqual([i["role"] for i in identities], ["base", "middle", "final", "base"])
        self.assertEqual([i["tier"] for i in identities], ["Common", "Uncommon", "Evolved", "Common"])
        self.assertEqual([i["depth"] for i in identities], [0, 1, 2, 0])

    def test_single_stage_bst_tier(self):
        identities = self.apply([self.species(1, 1)],
                                [{"species_id": 1, "bst": bst} for bst in (399, 400, 499, 500)])
        self.assertEqual([i["tier"] for i in identities], ["Common", "Uncommon", "Uncommon", "Rare"])
        self.assertEqual([i["base_catch_rate"] for i in identities], [0.5, 0.3, 0.3, 0.15])

    def test_shedinja_is_evolved_tier(self):
        rows = [self.species(290, 141), self.species(291, 141, 290), self.species(292, 141, 290)]
        shedinja = self.apply(rows, [{"species_id": 292, "bst": 236}])[0]
        self.assertEqual((shedinja["role"], shedinja["tier"], shedinja["depth"]),
                         ("final", "Evolved", 1))
        self.assertEqual(shedinja["base_catch_rate"], 0.15)

    def test_koraidon_legendary_by_flag_ultra_beast_not(self):
        rows = [self.species(1007, 536, legendary=1), self.species(1008, 537, legendary=1),
                self.species(793, 408)]
        identities = self.apply(rows, [{"species_id": s, "bst": 600} for s in (1007, 1008, 793)])
        self.assertEqual([i["tier"] for i in identities],
                         ["Legendary/Mythical", "Legendary/Mythical", "Rare"])
        self.assertEqual(identities[0]["base_catch_rate"], 0.05)

    def test_regional_form_uses_own_bst(self):
        identities = self.apply([self.species(37, 18)],
                                [{"species_id": 37, "pokemon_id": 37, "bst": 399},
                                 {"species_id": 37, "pokemon_id": 10103, "bst": 500}])
        self.assertEqual([i["tier"] for i in identities], ["Common", "Rare"])
        self.assertEqual([i["family_id"] for i in identities], [18, 18])

    def test_gender_variety_own_stats_tier_from_default(self):
        identities = load_graph(FIXTURES)["identities"]
        stats = importlib.import_module("content.build.stats")
        stats.add_stats(identities, FIXTURES)
        oinkologne = next(i for i in identities if i["species_id"] == 916)
        oinkologne["bst"] = oinkologne["gender_varieties"]["male"]["bst"] = 399
        oinkologne["gender_varieties"]["female"]["bst"] = 500
        self.apply([self.species(916, 489)], [oinkologne])
        self.assertEqual(oinkologne["tier"], "Common")
        self.assertEqual(oinkologne["gender_varieties"]["female"]["bst"], 500)

    def test_rewards_by_depth_and_legendary(self):
        rows = [self.species(1, 1), self.species(2, 1, 1), self.species(3, 1, 2),
                self.species(4, 2, legendary=1)]
        identities = self.apply(rows, [{"species_id": s, "bst": 300} for s in range(1, 5)])
        self.assertEqual([(i["catch_candy"], i["catch_stardust"]) for i in identities],
                         [(3, 100), (5, 300), (10, 500), (10, 500)])

    def test_phione_manaphy_no_edge_two_roots(self):
        result = self.module().load_families(self.directory([self.species(489, 250), self.species(490, 250)]))
        self.assertEqual(set(result), {489, 490})
        for value in result.values():
            self.assertEqual((value["family_id"], value["parent_species_id"], value["depth"],
                              value["role"], value["family_size"]), (250, None, 0, "base", 2))

    def test_cross_chain_parent_is_error(self):
        rows = [self.species(1, 1), self.species(2, 2, 1)]
        with self.assertRaisesRegex(ValueError, "same chain"):
            self.module().load_families(self.directory(rows))

    def test_missing_chain_parent_or_cycle_is_error(self):
        cases = [([self.species(1, "")], "chain"), ([self.species(1, 1, 2)], "parent"),
                 ([self.species(1, 1, 2), self.species(2, 1, 1)], "cycle")]
        for rows, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.module().load_families(self.directory(rows))


if __name__ == "__main__":
    unittest.main()
