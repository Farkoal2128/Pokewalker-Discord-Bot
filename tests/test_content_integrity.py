"""Offline C1 checks against the committed snapshot, without rebuilding CSVs."""

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pokewalker.bot.client import load_content


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "content/artifact/content.json"
MANIFEST = ROOT / "content/manifest.json"


class ContentIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = json.loads(ARTIFACT.read_bytes())
        cls.manifest = json.loads(MANIFEST.read_bytes())

    def test_artifact_hash_matches_manifest(self):
        self.assertEqual(hashlib.sha256(ARTIFACT.read_bytes()).hexdigest(),
                         self.manifest["artifact_sha256"])
        self.assertEqual(load_content(ARTIFACT), self.artifact)

    def test_no_name_en_contains_replacement_character(self):
        def check(value):
            if isinstance(value, dict):
                if 'name_en' in value:
                    self.assertNotIn('\ufffd', value['name_en'])
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)

        check(self.artifact)
        kings_rock = next(item for item in self.artifact['evolution_items']
                          if item['id'] == 'kings-rock')
        self.assertEqual(kings_rock['name_en'], 'King\u2019s Rock')

    def test_schema_and_counts_match_manifest_and_d51(self):
        artifact = self.artifact
        species = artifact["species"].values()
        lines = artifact["milestones"]["evolution_lines"]["families"]
        counts = {
            "evolution_targets": len(artifact["evolution_targets"]),
            "evolution_edges": sum(map(len, artifact["evolutions"].values())),
            "evolution_items": len(artifact["evolution_items"]),
            "species": len(artifact["species"]),
            "identities": len(artifact["identities"]),
            "regional_identities": sum(i["kind"] == "regional" for i in artifact["identities"]),
            "legendary_species": sum(s["is_legendary"] for s in species),
            "mythical_species": sum(s["is_mythical"] for s in species),
            "evolution_line_families": len(lines),
            "evolution_line_species": len({sid for line in lines for sid in line["species_ids"]}),
        }
        self.assertEqual(artifact["schema_version"], 1)
        self.assertEqual(self.manifest["schema_version"], 1)
        self.assertEqual(counts, self.manifest["counts"])
        self.assertEqual(counts, {
            "evolution_targets": 65, "evolution_edges": 587, "evolution_items": 50,
            "species": 1025, "identities": 1094, "regional_identities": 57,
            "legendary_species": 71, "mythical_species": 23,
            "evolution_line_families": 340, "evolution_line_species": 824,
        })
        self.assertEqual(len(artifact["starters"]), 27)
        self.assertEqual(len(artifact["routes"]), 8)
        for identity in artifact["identities"]:
            with self.subTest(identity=identity["identity_id"]):
                self.assertEqual(set(identity["sprites"]),
                                 {"normal", "shiny", "female", "shiny_female"})

    def test_every_non_legendary_identity_routable(self):
        for identity in self.artifact["identities"]:
            if identity["is_legendary"] or identity["is_mythical"]:
                continue
            with self.subTest(identity=identity["identity_id"]):
                self.assertTrue(any(route["weights"].get(identity["identity_id"], 0) > 0
                                    for route in self.artifact["routes"].values()))

    def test_balance_hashes_match(self):
        directory = ROOT / "content/balance"
        self.assertEqual({path.name for path in directory.glob("*.json")},
                         set(self.manifest["balance_sha256"]))
        for filename, digest in self.manifest["balance_sha256"].items():
            with self.subTest(filename=filename):
                self.assertEqual(hashlib.sha256((directory / filename).read_bytes()).hexdigest(), digest)

    def test_tampered_artifact_byte_fails(self):
        with tempfile.TemporaryDirectory(prefix=".m51-", dir=ROOT) as temporary:
            content = Path(temporary) / "content"
            path = content / "artifact/content.json"
            path.parent.mkdir(parents=True)
            shutil.copyfile(MANIFEST, content / "manifest.json")
            raw = bytearray(ARTIFACT.read_bytes())
            raw[-1] ^= 1
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "hash differs"):
                load_content(path)


if __name__ == "__main__":
    unittest.main()
