"""C1 output contract, using authored miniature CSVs and balance definitions."""

import hashlib
import importlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch


FIXTURE = Path(__file__).parent / "fixtures" / "content_mini"


class ContentEmitTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module("content.build.emit")
        except ModuleNotFoundError:
            self.fail("M0.4 emitter absent: C1 snapshot behavior unavailable")

    def build(self, **kwargs):
        return self.module().build_content(FIXTURE / "source", FIXTURE / "balance", **kwargs)

    def identity(self, artifact, sid):
        return next(i for i in artifact["identities"] if i["species_id"] == sid)

    def copy_source(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name) / "source"
        shutil.copytree(FIXTURE / "source", directory)
        return directory

    def test_mini_rebuild_has_two_family_edges(self):
        artifact, manifest = self.build()
        self.assertEqual({(e["from_identity_id"], e["to_identity_id"], e["candy"])
                          for edges in artifact["evolutions"].values() for e in edges},
                         {("1:1", "2:2", 25), ("2:2", "3:3", 100)})
        self.assertEqual(artifact["evolution_targets"], [])
        self.assertEqual(manifest["counts"]["evolution_edges"], 2)

    def test_validation_rejects_unresolved_endpoints_and_too_many_edges(self):
        for endpoint in ("from_identity_id", "to_identity_id"):
            with self.subTest(endpoint=endpoint):
                artifact, _ = self.build()
                artifact["evolutions"]["1:1"][0][endpoint] = "missing"
                with self.assertRaisesRegex(ValueError, "endpoint"):
                    self.module().validate_artifact(artifact)
        artifact, _ = self.build()
        artifact["evolutions"]["1:1"] *= 26
        with self.assertRaisesRegex(ValueError, "25"):
            self.module().validate_artifact(artifact)

    def test_validation_rejects_target_missing_sprite_key(self):
        artifact, _ = self.build()
        target = dict(artifact["identities"][0], sprites={"normal": "present"})
        artifact["evolution_targets"] = [target]
        with self.assertRaisesRegex(ValueError, "sprite"):
            self.module().validate_artifact(artifact)

    def test_validation_limits_items_per_source_and_recipes_per_item(self):
        artifact, _ = self.build()
        edge = artifact['evolutions']['1:1'][0]
        items = [None, *[f'item-{n}' for n in range(24)]]
        artifact['evolutions']['1:1'] = [dict(edge, item=item)
                                         for item in items for _ in range(25)]
        self.module().validate_artifact(artifact)
        artifact['evolutions']['1:1'].append(dict(edge, item='item-25'))
        with self.assertRaisesRegex(ValueError, '25'):
            self.module().validate_artifact(artifact)
        for item in (None, 'stone'):
            with self.subTest(item=item):
                artifact['evolutions']['1:1'] = [dict(edge, item=item) for _ in range(26)]
                with self.assertRaisesRegex(ValueError, '25'):
                    self.module().validate_artifact(artifact)

    def test_non_default_form_sprite_uses_exact_normal_and_shiny_form_urls(self):
        directory = self.copy_source()
        form = 'ruby-cream-strawberry-sweet'
        (directory / 'pokemon_forms.csv').write_text(
            'id,form_identifier,is_default\n'
            '869,vanilla-cream-strawberry-sweet,1\n'
            f'10346,{form},0\n', encoding='utf-8')
        module = self.module()
        root = f'https://raw.githubusercontent.com/PokeAPI/sprites/{module.SPRITES_COMMIT}/sprites/pokemon/'
        for audited in (False, True):
            calls = []

            def opener(request, **kwargs):
                calls.append(request.full_url)
                return io.BytesIO(b'')

            _, sprites = module.sprite_records(directory, audited, opener)
            value = dict(pokemon_id=869, form_id=10346, has_gender_differences=False)
            with self.subTest(audited=audited):
                self.assertEqual(sprites(value), {
                    'normal': f'{root}869-{form}.png',
                    'shiny': f'{root}shiny/869-{form}.png',
                    'female': None, 'shiny_female': None})
                value['has_gender_differences'] = True
                for key, prefix in module.SPRITE_PATHS.items():
                    self.assertEqual(sprites(value)[key], f'{root}{prefix}869-{form}.png')
                value['form_id'] = 869
                for key, prefix in module.SPRITE_PATHS.items():
                    self.assertEqual(sprites(value)[key], f'{root}{prefix}869.png')
                self.assertEqual(bool(calls), audited)

    def test_gender_override_three_species_50_50(self):
        artifact, _ = self.build()
        for sid in (876, 902, 916):
            value = self.identity(artifact, sid)
            self.assertEqual(value["gender_rate"], 4)
            self.assertEqual(set(value["gender_varieties"]), {"male", "female"})
            self.assertEqual(value["pokemon_id"], value["gender_varieties"]["male"]["pokemon_id"])

    def test_gender_varieties_carry_own_stats_and_sprites(self):
        artifact, _ = self.build()
        for sid in (876, 902, 916):
            value = self.identity(artifact, sid)
            male, female = (value["gender_varieties"][g] for g in ("male", "female"))
            self.assertNotEqual(male["bst"], female["bst"])
            self.assertNotEqual(male["base_attack"], female["base_attack"])
            self.assertEqual(male["tier"], female["tier"])
            self.assertEqual(artifact["routes"]["all"]["weights"][value["identity_id"]], 1)
            self.assertNotIn(female["identity_id"], artifact["routes"]["all"]["weights"])
            self.assertEqual(set(female["sprites"]), {"normal", "shiny", "female", "shiny_female"})
            for variant in (male, female):
                self.assertTrue(variant["sprites"]["normal"].endswith(f'/{variant["pokemon_id"]}.png'))

    def test_sprite_missing_is_null_not_substitute(self):
        calls = []

        def opener(request, **kwargs):
            calls.append((request.method, request.full_url))
            if "/shiny/" in request.full_url:
                raise HTTPError(request.full_url, 404, "missing fixture sprite", {}, None)
            return io.BytesIO(b"")

        artifact, manifest = self.build(audit_sprites=True, opener=opener)
        self.assertEqual(manifest["sprite_audit"], "head")
        self.assertTrue(calls)
        self.assertTrue(all(method == "HEAD" for method, _ in calls))
        for value in artifact["identities"]:
            self.assertIsNone(value["sprites"]["shiny"])
            self.assertIsNone(value["sprites"]["shiny_female"])
            self.assertIsNotNone(value["sprites"]["normal"])

    def test_sprite_url_uses_pinned_commit_and_pokemon_id(self):
        artifact, manifest = self.build()
        self.assertEqual(manifest["sprites_commit"], "1b3b7c0a538dd2226ae08d0d2f8955125075bbd4")
        self.assertEqual(manifest["sprite_audit"], "none")
        female = self.identity(artifact, 916)["gender_varieties"]["female"]
        for key, path in {"normal": "", "shiny": "shiny/", "female": "female/",
                          "shiny_female": "shiny/female/"}.items():
            self.assertEqual(female["sprites"][key],
                             f'https://raw.githubusercontent.com/PokeAPI/sprites/{manifest["sprites_commit"]}'
                             f'/sprites/pokemon/{path}{female["pokemon_id"]}.png')

    def test_route_coverage_every_identity(self):
        artifact, _ = self.build()
        for identity in artifact["identities"]:
            self.assertTrue(any(r["weights"][identity["identity_id"]] > 0
                                for r in artifact["routes"].values()))
        bulbasaur = self.identity(artifact, 1)
        self.assertEqual(bulbasaur["habitat"], "forest")
        self.assertEqual(artifact["routes"]["all"]["weights"][bulbasaur["identity_id"]], 3)
        self.assertEqual(sum(artifact["routes"]["all"]["eligible_counts"].values()),
                         len(artifact["identities"]))

    def test_uncovered_identity_is_build_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            balance = Path(temporary)
            shutil.copytree(FIXTURE / "balance", balance, dirs_exist_ok=True)
            (balance / "routes.json").write_text(json.dumps({"routes": [{"id": "empty", "weights": {}}]}))
            with self.assertRaisesRegex(ValueError, "no route"):
                self.module().build_content(FIXTURE / "source", balance)

    def test_starters_27_base_stage(self):
        artifact, _ = self.build()
        self.assertEqual(len(artifact["starters"]), 27)
        self.assertEqual(artifact["starters"],
                         [1, 4, 7, 152, 155, 158, 252, 255, 258, 387, 390, 393,
                          495, 498, 501, 650, 653, 656, 722, 725, 728,
                          810, 813, 816, 906, 909, 912])
        self.assertTrue(all(artifact["species"][str(sid)]["role"] == "base"
                            for sid in artifact["starters"]))

    def test_starter_not_base_stage_is_build_error(self):
        artifact, _ = self.build()
        artifact["species"]["1"]["role"] = "middle"
        with self.assertRaisesRegex(ValueError, "starter"):
            self.module().validate_artifact(artifact)

    def test_evolution_line_families_exclude_phione_manaphy_and_singletons(self):
        artifact, manifest = self.build()
        lines = artifact["milestones"]["evolution_lines"]["families"]
        self.assertEqual([line["species_ids"] for line in lines], [[1, 2, 3]])
        self.assertEqual((lines[0]["family_candy"], lines[0]["ultra_ball"], lines[0]["stardust"]),
                         (25, 1, 750))
        self.assertEqual(manifest["counts"]["evolution_line_families"], 1)
        self.assertEqual(manifest["counts"]["evolution_line_species"], 3)

    def test_qualifying_family_without_milestone_is_build_error(self):
        artifact, _ = self.build()
        artifact["milestones"]["evolution_lines"]["families"] = []
        with self.assertRaisesRegex(ValueError, "milestone"):
            self.module().validate_artifact(artifact)

    def test_manifest_hashes_and_counts(self):
        artifact, manifest = self.build()
        for filename, digest in manifest["csv_sha256"].items():
            self.assertEqual(hashlib.sha256((FIXTURE / "source" / filename).read_bytes()).hexdigest(), digest)
        for filename, digest in manifest["balance_sha256"].items():
            self.assertEqual(hashlib.sha256((FIXTURE / "balance" / filename).read_bytes()).hexdigest(), digest)
        self.assertEqual(manifest["counts"]["species"], 37)
        self.assertEqual(manifest["counts"]["identities"], len(artifact["identities"]))
        self.assertEqual(manifest["counts"]["legendary_species"], 1)
        self.assertEqual(manifest["counts"]["mythical_species"], 1)
        self.assertEqual(manifest["pending"], [])
        self.assertEqual(manifest["pokeapi_commit"], "e5b79b2e15d7c50735a945936afd4cd1cfd94eae")

    def test_manifest_artifact_hash_matches_emitted_bytes(self):
        artifact, manifest = self.build()
        expected = hashlib.sha256(self.module().encode(artifact)).hexdigest()
        self.assertEqual(manifest.get("artifact_sha256"), expected)

    def test_committed_mini_snapshot_matches_rebuild(self):
        artifact, manifest = self.build()
        self.assertTrue(self.module().write_artifacts(artifact, manifest, FIXTURE, check=True))

    def test_sprite_csv_missing_fields_do_not_substitute(self):
        directory = self.copy_source()
        path = directory / "pokemon_sprites.csv"
        path.write_text("pokemon_id,front_default,front_shiny,front_female,front_shiny_female\n"
                        "1,present,,,\n", encoding="utf-8")
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["sha256"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["optional_missing"].remove("pokemon_sprites")
        manifest_path.write_text(json.dumps(manifest))
        artifact, manifest = self.module().build_content(directory, FIXTURE / "balance")
        self.assertEqual(manifest["sprite_audit"], "csv")
        sprites = self.identity(artifact, 1)["sprites"]
        self.assertIsNotNone(sprites["normal"])
        self.assertIsNone(sprites["shiny"])
        self.assertTrue(all(value is None for value in self.identity(artifact, 4)["sprites"].values()))

    def test_check_detects_drift(self):
        cli = importlib.import_module("content.build.__main__")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            argv = ["--cache", str(FIXTURE / "source")]
            self.assertEqual(cli.main(argv, output_root=root, balance_directory=FIXTURE / "balance"), 0)
            before = (root / "content/artifact/content.json").read_bytes()
            self.assertEqual(cli.main(argv + ["--check"], output_root=root,
                                      balance_directory=FIXTURE / "balance"), 0)
            path = root / "content/manifest.json"
            path.write_bytes(b"drift\n")
            self.assertEqual(cli.main(argv + ["--check"], output_root=root,
                                      balance_directory=FIXTURE / "balance"), 1)
            self.assertEqual(path.read_bytes(), b"drift\n")
            self.assertEqual((root / "content/artifact/content.json").read_bytes(), before)
            path.unlink()
            self.assertEqual(cli.main(argv + ["--check"], output_root=root,
                                      balance_directory=FIXTURE / "balance"), 1)
            self.assertFalse(path.exists())

    def test_cli_warm_cache_is_offline_and_pending_is_not_published(self):
        cli = importlib.import_module("content.build.__main__")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(cli, "fetch_csvs", side_effect=AssertionError("warm cache must stay offline")):
                self.assertEqual(cli.main(["--cache", str(FIXTURE / "source")], output_root=root,
                                          balance_directory=FIXTURE / "balance"), 0)
            before = (root / "content/artifact/content.json").read_bytes()
            artifact, manifest = self.build()
            manifest["pending"] = [{"reason": "PENDING source decision"}]
            with patch.object(cli, "build_content", return_value=(artifact, manifest)):
                self.assertEqual(cli.main(["--cache", str(FIXTURE / "source")], output_root=root), 1)
            self.assertEqual((root / "content/artifact/content.json").read_bytes(), before)

    def test_cache_corruption_is_rejected(self):
        directory = self.copy_source()
        (directory / "pokemon_species.csv").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.module().build_content(directory, FIXTURE / "balance")

    def test_sprite_audit_network_failure_does_not_claim_missing(self):
        def opener(request, **kwargs):
            raise HTTPError(request.full_url, 503, "outage", {}, None)
        with self.assertRaises(HTTPError):
            self.build(audit_sprites=True, opener=opener)

    def test_d59_flag_mismatch_is_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            balance = Path(temporary)
            shutil.copytree(FIXTURE / "balance", balance, dirs_exist_ok=True)
            path = balance / "milestones.json"
            values = json.loads(path.read_text())
            values["legendary_groups"][0]["species_ids"] = [1]
            path.write_text(json.dumps(values))
            _, manifest = self.module().build_content(FIXTURE / "source", balance)
            self.assertTrue(any("PENDING" in row["reason"] for row in manifest["pending"]))


if __name__ == "__main__":
    unittest.main()
