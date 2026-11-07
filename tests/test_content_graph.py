"""Executable M0.1 contract; CSV fixtures contain authored miniature rows."""

import csv
import importlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError


FIXTURES = Path(__file__).parent / "fixtures" / "pokeapi_mini"


class ContentGraphTests(unittest.TestCase):
    def module(self, name):
        try:
            return importlib.import_module("content.build." + name)
        except ModuleNotFoundError:
            self.fail(f"M0.1 {name} provider is absent: required content behavior unavailable")

    def graph(self, directory=FIXTURES):
        return self.module("graph").load_graph(directory)

    def test_filter_excludes_mega_and_battle_only(self):
        result = self.graph()
        self.assertFalse({10034, 20001} & {i["form_id"] for i in result["identities"]})
        self.assertTrue({10034, 20001} <= {i["form_id"] for i in result["excluded"]})
        self.assertIn(1, {i["pokemon_id"] for i in result["identities"]})

    def test_eternamax_false_flag_excluded(self):
        result = self.graph()
        self.assertNotIn(10190, {i["pokemon_id"] for i in result["identities"]})
        excluded = next(i for i in result["excluded"] if i["form_id"] == 10359)
        self.assertIn("transformation", excluded["reason"])

    def test_regional_variety_included_once(self):
        identities = self.graph()["identities"]
        alolan = [i for i in identities if i["pokemon_id"] == 10103]
        self.assertEqual(len(alolan), 1)
        self.assertEqual(alolan[0]["kind"], "regional")
        self.assertEqual(alolan[0]["species_id"], 37)
        self.assertEqual(alolan[0]["types"], ["ice"])
        self.assertEqual(alolan[0]["name_en"], "Alolan Vulpix")
        self.assertEqual(len({i["identity_id"] for i in identities}), len(identities))

    def test_default_only_policy_drops_alternative(self):
        result = self.graph()
        minior = [i for i in result["identities"] if i["species_id"] == 774]
        self.assertEqual([i["pokemon_id"] for i in minior], [774])
        self.assertTrue(any(i["pokemon_id"] == 10136 for i in result["excluded"]))

    def test_separate_encounter_policy_adds_form(self):
        wormadam = [i for i in self.graph()["identities"] if i["species_id"] == 413]
        self.assertEqual({i["pokemon_id"] for i in wormadam}, {413, 10004, 10005})
        self.assertEqual({i["kind"] for i in wormadam}, {"default", "form"})

    def test_branch_forms_reported_excluded_and_emitted_as_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            shutil.copytree(FIXTURES, directory, dirs_exist_ok=True)
            self.alter(directory, "pokemon_species", lambda rows: [
                dict(r, identifier="lycanroc") if r["identifier"] == "minior" else r
                for r in rows])
            result = self.graph(directory)
            self.assertEqual([i["form_id"] for i in result.get("evolution_targets", [])], [10136])
            target = result["evolution_targets"][0]
            self.assertEqual(target["kind"], "form")
            self.assertNotIn(target, result["identities"])
            self.assertTrue(any(i["form_id"] == 10136 and "no separate encounter" in i["reason"]
                                for i in result["excluded"]))

    def test_arceus_unknown_quarantined(self):
        result = self.graph()
        self.assertFalse(any(i["form_id"] == 10057 for i in result["identities"]))
        self.assertTrue(any(i["form_id"] == 10057 and "quarantin" in i["reason"]
                            for i in result["excluded"]))

    def test_gender_variety_attached_not_separate_identity(self):
        identities = [i for i in self.graph()["identities"] if i["species_id"] == 916]
        self.assertEqual(len(identities), 1)
        self.assertEqual(identities[0]["pokemon_id"], 916)
        self.assertEqual(identities[0]["gender_varieties"]["female"]["pokemon_id"], 10254)
        self.assertEqual(identities[0]["gender_varieties"]["male"]["pokemon_id"], 916)

    def alter(self, directory, name, change):
        path = directory / (name + ".csv")
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        rows = change(rows)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_missing_stat_is_build_error(self):
        for pokemon_id in (1, 10254):
            with self.subTest(pokemon_id=pokemon_id), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                shutil.copytree(FIXTURES, directory, dirs_exist_ok=True)
                self.alter(directory, "pokemon_stats", lambda rows: [
                    r for r in rows if not (r["pokemon_id"] == str(pokemon_id) and r["stat_id"] == "6")])
                with self.assertRaisesRegex(ValueError, "six stats"):
                    self.graph(directory)

    def test_unclassified_different_form_is_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            shutil.copytree(FIXTURES, directory, dirs_exist_ok=True)
            self.alter(directory, "pokemon_form_types", lambda rows: rows + [
                {"pokemon_form_id": "20101", "type_id": "11", "slot": "1"}])
            result = self.graph(directory)
            self.assertTrue(any(r["form_id"] == 20101 for r in result["pending"]))

    def test_excluded_species_default_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            shutil.copytree(FIXTURES, directory, dirs_exist_ok=True)
            self.alter(directory, "pokemon_forms", lambda rows: [
                dict(r, is_battle_only="1") if r["id"] == "1" else r for r in rows])
            with self.assertRaisesRegex(ValueError, "default"):
                self.graph(directory)

    def test_fetch_refuses_hash_mismatch(self):
        fetch = self.module("fetch")
        calls = []

        def opener(url, **kwargs):
            calls.append(url)
            return io.BytesIO(b"id,identifier\n1,authored-fixture\n")

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            manifest = fetch.fetch_csvs(directory, opener=opener)
            self.assertEqual(manifest["source_commit"], fetch.SOURCE_COMMIT)
            self.assertTrue(all(fetch.SOURCE_COMMIT in url for url in calls))
            before_manifest = (directory / "manifest.json").read_bytes()
            target = directory / "pokemon.csv"
            target.write_bytes(b"tampered\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                fetch.fetch_csvs(directory, opener=opener)
            self.assertEqual(target.read_bytes(), b"tampered\n")
            self.assertEqual((directory / "manifest.json").read_bytes(), before_manifest)

    def test_optional_missing_csv_is_reported(self):
        fetch = self.module("fetch")

        def opener(url, **kwargs):
            if url.endswith(("pokemon_sprites.csv", "pokemon_form_sprites.csv")):
                raise HTTPError(url, 404, "fixture absent", {}, None)
            return io.BytesIO(b"id,identifier\n1,authored-fixture\n")

        with tempfile.TemporaryDirectory() as tmp:
            result = fetch.fetch_csvs(Path(tmp), opener=opener)
            self.assertEqual(set(result["optional_missing"]),
                             {"pokemon_sprites", "pokemon_form_sprites"})
            self.assertEqual(json.loads((Path(tmp) / "manifest.json").read_text()), result)


if __name__ == "__main__":
    unittest.main()
