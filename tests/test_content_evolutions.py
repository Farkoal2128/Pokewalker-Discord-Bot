"""M6.1a recipes use authored temporary CSVs, independently of the cache."""

import csv
import hashlib
import importlib
import io
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError

from content.build.emit import verified_inputs
from content.build.fetch import OPTIONAL_CSVS, REQUIRED_CSVS, fetch_csvs
from content.build.graph import ORDINARY_TYPES


class ContentEvolutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.identities, self.targets, self.species, self.rows = [], [], {}, []
        self.item_rows, self.name_rows = [], []

    def write(self, table, columns, rows):
        with (self.directory / (table + '.csv')).open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns.split(), lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)

    def identity(self, sid, *, parent=None, family=None, depth=0, fid=None,
                 kind='default', target=False, name=None):
        fid = sid if fid is None else fid
        value = dict(identity_id=f'{fid}:{fid}', species_id=sid, pokemon_id=fid,
                     form_id=fid, kind=kind, name_en=name or f'Pokemon {fid}')
        (self.targets if target else self.identities).append(value)
        self.species[sid] = dict(parent_species_id=parent, family_id=family or sid, depth=depth)
        return value

    def row(self, sid, **kwargs):
        row = dict(id=len(self.rows) + 1, evolved_species_id=sid, evolution_trigger_id=1,
                   is_default=1, trigger_item_id='', held_item_id='', gender_id='',
                   required_pokemon_form_id='', evolved_pokemon_form_id='', region_id='')
        row.update(kwargs)
        self.rows.append(row)

    def item(self, iid, identifier, name=None):
        self.item_rows.append(dict(id=iid, identifier=identifier))
        if name is not None:
            self.name_rows.append(dict(item_id=iid, local_language_id=9, name=name))

    def load(self):
        self.write('pokemon_evolution', 'id evolved_species_id evolution_trigger_id is_default '
                   'trigger_item_id held_item_id gender_id required_pokemon_form_id '
                   'evolved_pokemon_form_id region_id', self.rows)
        self.write('items', 'id identifier', self.item_rows)
        self.write('item_names', 'item_id local_language_id name', self.name_rows)
        types = sorted(ORDINARY_TYPES)
        self.write('types', 'id identifier', [dict(id=n, identifier=t) for n, t in enumerate(types, 1)])
        self.write('type_efficacy', 'damage_type_id target_type_id damage_factor', [
            dict(damage_type_id=a, target_type_id=b, damage_factor=(200, 100, 50, 0)[(a+b) % 4])
            for a in range(1, 19) for b in range(1, 19)])
        try:
            module = importlib.import_module('content.build.evolutions')
        except ModuleNotFoundError:
            self.fail('M6.1a evolution recipe loader is absent')
        return module.load_evolutions(self.directory, self.identities, self.targets, self.species)

    def pair(self, source=1, target=2):
        self.identity(source)
        self.identity(target, parent=source, family=source, depth=1)
        self.row(target)

    def test_required_csvs_include_items_names_efficacy_hashed(self):
        self.assertTrue({'items', 'item_names', 'type_efficacy'} <= set(REQUIRED_CSVS))

        def opener(url, **kwargs):
            if any(url.endswith('/' + name + '.csv') for name in OPTIONAL_CSVS):
                raise HTTPError(url, 404, 'absent fixture', {}, None)
            return io.BytesIO(b'id,identifier\n1,authored\n')

        fetch_csvs(self.directory, opener=opener)
        hashes = verified_inputs(self.directory)
        for name in ('items', 'item_names', 'type_efficacy'):
            self.assertEqual(hashes[name + '.csv'], hashlib.sha256(
                (self.directory / (name + '.csv')).read_bytes()).hexdigest())
        (self.directory / 'items.csv').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'hash mismatch: items.csv'):
            verified_inputs(self.directory)

    def test_default_rows_only_and_shed_dropped(self):
        self.pair(290, 291)
        self.identity(292, parent=290, family=290, depth=1)
        self.identity(489, parent=290, family=290, depth=1)
        self.identity(490, parent=290, family=290, depth=1)
        self.row(292, id=155, evolution_trigger_id=4)
        self.row(291, is_default=0, trigger_item_id=99)
        edges, items, _ = self.load()
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]['to_species_id'], 291)
        self.assertEqual(items, [])

    def test_regional_source_routes_to_regional_target_not_ordinary(self):
        self.identity(264)
        self.identity(264, fid=10235, kind='regional')
        self.identity(862, parent=264, family=264, depth=1)
        self.row(862, required_pokemon_form_id=10235)
        edges, _, _ = self.load()
        self.assertEqual([(e['from_identity_id'], e['to_identity_id']) for e in edges],
                         [('10235:10235', '862:862')])

    def test_wildcard_rows_never_attach_to_regional_sources(self):
        self.pair(52, 53)
        self.identity(52, fid=10107, kind='regional')
        edges, _, _ = self.load()
        self.assertEqual([e['from_identity_id'] for e in edges], ['52:52'])

    def test_ordinary_source_keeps_ordinary_and_regional_targets(self):
        for source, target, regional in ((25, 26, 10100), (104, 105, 10115)):
            self.pair(source, target)
            self.identity(target, parent=source, family=source, depth=1,
                          fid=regional, kind='regional')
            self.row(target, evolved_pokemon_form_id=regional, region_id=1)
        edges, _, _ = self.load()
        self.assertEqual({(e['from_identity_id'], e['to_identity_id']) for e in edges},
                         {('25:25', '26:26'), ('25:25', '10100:10100'),
                          ('104:104', '105:105'), ('104:104', '10115:10115')})

    def test_branch_forms_resolve_to_target_records(self):
        for source, target, branches in ((744, 745, (10126, 10152)), (891, 892, (10191,))):
            self.pair(source, target)
            for branch in branches:
                self.identity(target, parent=source, family=source, depth=1,
                              fid=branch, kind='form', target=True)
                self.row(target, required_pokemon_form_id=99999, evolved_pokemon_form_id=branch)
        edges, _, _ = self.load()
        self.assertEqual({e['to_identity_id'] for e in edges},
                         {'745:745', '10126:10126', '10152:10152', '892:892', '10191:10191'})

    def test_identical_recipes_deduplicated_alcremie_seven_sweets(self):
        self.identity(868)
        self.identity(869, parent=868, family=868, depth=1)
        for iid in range(1167, 1174):
            self.item(iid, f'sweet-{iid}', f'Sweet {iid}')
            for cosmetic in range(9):
                self.row(869, held_item_id=iid, evolved_pokemon_form_id=20000+cosmetic)
        edges, items, _ = self.load()
        self.assertEqual(len(edges), 7)
        self.assertEqual({e['edge_id'] for e in edges},
                         {f'868:868>869:869|sweet-{iid}|-' for iid in range(1167, 1174)})
        self.assertEqual(len(items), 7)
        self.assertEqual(len({e['label'] for e in edges}), 7)

    def test_seven_items_nine_targets_sixty_three_recipes_accepted(self):
        self.identity(868)
        self.identity(869, parent=868, family=868, depth=1)
        expected = set()
        for sweet in range(7):
            iid = 1167 + sweet
            self.item(iid, f'sweet-{iid}', f'Sweet {iid}')
            for cream in range(9):
                fid = 869 if sweet == cream == 0 else 20000 + sweet * 9 + cream
                if fid != 869:
                    target = self.identity(869, parent=868, family=868, depth=1,
                                           fid=fid, kind='form', target=True)
                    target.update(pokemon_id=869, identity_id=f'869:{fid}')
                self.row(869, held_item_id=iid, evolved_pokemon_form_id=fid)
                expected.add((f'sweet-{iid}', f'869:{fid}'))
        edges, items, _ = self.load()
        self.assertEqual(len(edges), 63)
        self.assertEqual(len(items), 7)
        self.assertEqual({(e['item'], e['to_identity_id']) for e in edges}, expected)
        self.assertEqual(set(Counter(e['item'] for e in edges).values()), {9})

    def test_over_25_recipes_for_one_item_pending(self):
        self.identity(1)
        for sid in range(2, 28):
            self.identity(sid, parent=1, family=1, depth=1)
            self.row(sid)
        self.item(1, 'stone', 'Stone')
        for item in ('', 1):
            with self.subTest(item=item or 'Candy only'):
                for row in self.rows:
                    row['trigger_item_id'] = item
                with self.assertRaisesRegex(ValueError, 'PENDING.*25'):
                    self.load()

    def test_gender_ids_mapped_to_stored_strings_combee_female_only(self):
        self.pair(415, 416)
        self.rows[0]['gender_id'] = 1
        self.pair(550, 902)
        male = self.identities[-1]
        female = dict(male, identity_id='10248:10248', pokemon_id=10248, form_id=10248)
        male['gender_varieties'] = dict(male=dict(male), female=female)
        self.rows[-1]['gender_id'] = 2
        self.row(902, gender_id=1, evolved_pokemon_form_id=10248)
        edges, _, _ = self.load()
        self.assertEqual({(e['to_identity_id'], e['gender']) for e in edges},
                         {('416:416', 'female'), ('902:902', 'male'), ('10248:10248', 'female')})

    def test_candy_by_family_depth_50_or_25_100(self):
        self.pair(133, 134)
        self.pair(840, 841)
        self.identity(1011, parent=840, family=840, depth=1)
        self.identity(1019, parent=1011, family=840, depth=2)
        self.row(1011)
        self.row(1019)
        edges, _, _ = self.load()
        self.assertEqual({e['to_species_id']: e['candy'] for e in edges},
                         {134: 50, 841: 25, 1011: 25, 1019: 100})

    def test_items_from_trigger_and_held_ids_named_and_sorted(self):
        self.pair()
        self.item(1, 'z-stone', 'Z Stone')
        self.item(2, 'a-coat', 'A Coat')
        self.rows[0]['trigger_item_id'] = 1
        self.row(2, held_item_id=2)
        self.name_rows.append(dict(item_id=1, local_language_id=1, name='Other language'))
        edges, items, _ = self.load()
        self.assertEqual(items, [dict(id='a-coat', name_en='A Coat'), dict(id='z-stone', name_en='Z Stone')])
        self.assertEqual({e['item'] for e in edges}, {'a-coat', 'z-stone'})
        self.assertTrue(all(e['gender'] is None for e in edges))
        self.assertEqual(set(edges[0]), {'edge_id', 'from_identity_id', 'to_identity_id',
                                       'to_species_id', 'candy', 'item', 'gender', 'label'})

    def test_type_chart_18x18_values_are_exactly_four_factors_including_neutral(self):
        _, _, chart = self.load()
        self.assertEqual(set(chart), ORDINARY_TYPES)
        self.assertTrue(all(set(row) == ORDINARY_TYPES for row in chart.values()))
        self.assertEqual({value for row in chart.values() for value in row.values()},
                         {1.6, 1.0, 0.625, 0.390625})
        factors = {200: 1.6, 100: 1.0, 50: 0.625, 0: 0.390625}
        for a, attacker in enumerate(sorted(ORDINARY_TYPES), 1):
            for b, defender in enumerate(sorted(ORDINARY_TYPES), 1):
                self.assertEqual(chart[attacker][defender], factors[(200, 100, 50, 0)[(a+b) % 4]])

    def test_pending_over_25_recipes_or_unnamed_item_or_orphan_species(self):
        self.pair()
        self.item(1, 'stone')
        self.rows[0]['trigger_item_id'] = 1
        with self.assertRaisesRegex(ValueError, 'PENDING.*English'):
            self.load()
        self.name_rows.append(dict(item_id=1, local_language_id=9, name='Stone'))
        self.rows.clear()
        with self.assertRaisesRegex(ValueError, 'PENDING.*incoming'):
            self.load()
        self.row(2, trigger_item_id=1)
        for iid in range(2, 27):
            self.item(iid, f'item-{iid}', f'Item {iid}')
            self.row(2, trigger_item_id=iid)
        with self.assertRaisesRegex(ValueError, 'PENDING.*25'):
            self.load()


class CommittedEvolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.artifact = json.loads((cls.root / 'content/artifact/content.json').read_bytes())
        cls.manifest = json.loads((cls.root / 'content/manifest.json').read_bytes())

    def test_targets_have_stats_family_names_and_four_sprite_keys(self):
        targets = self.artifact['evolution_targets']
        self.assertEqual({i['form_id'] for i in targets},
                         {10228, 10311, 10360, *range(10346, 10354), *range(10449, 10503)})
        for value in targets:
            with self.subTest(form=value['form_id']):
                self.assertEqual(value['kind'], 'form')
                self.assertTrue(value['name_en'])
                self.assertEqual(value['stats_source'], 'derived-d39')
                for key in ('bst', 'base_attack', 'base_defense', 'base_stamina', 'family_id'):
                    self.assertGreater(value[key], 0)
                self.assertIn(value['species_id'], self.artifact['families'][str(value['family_id'])])
                self.assertEqual(set(value['sprites']), {'normal', 'shiny', 'female', 'shiny_female'})
                key = str(value['pokemon_id'])
                if value['species_id'] == 869:
                    key += '-' + value['name_en'].removesuffix(' Alcremie').lower().replace(' ', '-')
                self.assertTrue(value['sprites']['normal'].endswith(f"/pokemon/{key}.png"))
                self.assertTrue(value['sprites']['shiny'].endswith(f"/shiny/{key}.png"))

    def test_targets_absent_from_identities_routes_and_tier_pools(self):
        from pokewalker.services.profiles import content_facts
        targets = {i['identity_id'] for i in self.artifact['evolution_targets']}
        self.assertFalse(targets & {i['identity_id'] for i in self.artifact['identities']})
        for route in self.artifact['routes'].values():
            self.assertFalse(targets & route['weights'].keys())
        _, pools = content_facts(self.artifact)
        self.assertFalse(targets & {i['identity_id'] for pool in pools.values() for i in pool})
        self.assertTrue({i['form_id'] for i in self.artifact['evolution_targets']} <=
                        {i['form_id'] for i in self.manifest['excluded']})

    def test_alcremie_62_targets_excluded_from_identities_routes_and_pools(self):
        targets = [i for i in self.artifact['evolution_targets'] if i['species_id'] == 869]
        self.assertEqual(len(targets), 62)
        self.test_targets_absent_from_identities_routes_and_tier_pools()
        excluded = {i['form_id']: i['reason'] for i in self.manifest['excluded']}
        for target in targets:
            self.assertEqual(excluded[target['form_id']], 'D52 evolution branch; no separate encounter')
        self.assertEqual(excluded[10392], 'battle transformation excluded')
        self.assertNotIn(10392, {i['form_id'] for i in targets})

    def test_milcery_63_recipes_nine_per_sweet_labels_name_exact_form(self):
        edges = self.artifact['evolutions']['868:868']
        self.assertEqual(len(edges), 63)
        sweets = {'strawberry-sweet', 'love-sweet', 'berry-sweet', 'clover-sweet',
                  'flower-sweet', 'star-sweet', 'ribbon-sweet'}
        self.assertEqual(Counter(e['item'] for e in edges), {sweet: 9 for sweet in sweets})
        records = {i['identity_id']: i for i in [*self.artifact['identities'],
                                               *self.artifact['evolution_targets']]}
        items = {i['id']: i['name_en'] for i in self.artifact['evolution_items']}
        self.assertEqual(len({e['to_identity_id'] for e in edges}), 63)
        for edge in edges:
            name = records[edge['to_identity_id']]['name_en']
            self.assertIn(items[edge['item']], name)
            self.assertEqual(edge['label'], f"{name} / {items[edge['item']]}")
        self.assertFalse([source for source, recipes in self.artifact['evolutions'].items()
                          if source != '868:868' and len(recipes) > 25])

    def test_every_edge_endpoint_resolves(self):
        records = [*self.artifact['identities'], *self.artifact['evolution_targets']]
        ids = {v['identity_id'] for i in records
               for v in [i, *i.get('gender_varieties', {}).values()]}
        reached = set()
        for source, edges in self.artifact['evolutions'].items():
            self.assertIn(source, ids)
            self.assertTrue(edges)
            self.assertEqual([e['edge_id'] for e in edges], sorted(e['edge_id'] for e in edges))
            for edge in edges:
                self.assertEqual(edge['from_identity_id'], source)
                self.assertIn(edge['to_identity_id'], ids)
                self.assertIn(edge['gender'], ('female', 'male', None))
                reached.add(edge['to_identity_id'])
        self.assertTrue({i['identity_id'] for i in self.artifact['evolution_targets']} <= reached)

    def test_max_items_per_source_and_recipes_per_item_at_most_25(self):
        self.assertTrue(self.artifact['evolutions'])
        for source, edges in self.artifact['evolutions'].items():
            with self.subTest(source=source):
                counts = Counter(edge['item'] for edge in edges)
                self.assertLessEqual(len(counts), 25)
                self.assertLessEqual(max(counts.values()), 25)

    def test_committed_pikachu_chooses_raichu_or_alolan_raichu(self):
        self.assertEqual({e['to_identity_id'] for e in self.artifact['evolutions']['25:25']},
                         {'26:26', '10100:10202'})

    def test_counts_and_importer_version_2_in_manifest(self):
        self.assertEqual(self.manifest['importer_version'], '2')
        for name, count in dict(evolution_targets=len(self.artifact['evolution_targets']),
                                evolution_edges=sum(map(len, self.artifact['evolutions'].values())),
                                evolution_items=len(self.artifact['evolution_items'])).items():
            self.assertEqual(self.manifest['counts'][name], count)
        self.assertEqual(set(self.artifact['type_chart']), ORDINARY_TYPES)
        self.assertTrue(all(set(row) == ORDINARY_TYPES for row in self.artifact['type_chart'].values()))
        self.assertEqual(self.artifact['type_chart']['normal']['ghost'], 0.390625)
        self.assertEqual(self.artifact['type_chart']['fire']['grass'], 1.6)

    def test_artifact_counts_and_hash_match_manifest(self):
        self.assertEqual(hashlib.sha256((self.root / 'content/artifact/content.json').read_bytes()).hexdigest(),
                         self.manifest['artifact_sha256'])
        self.assertEqual(self.manifest['counts']['identities'], len(self.artifact['identities']))
        self.assertEqual(self.manifest['counts']['evolution_targets'], 65)
        self.assertLessEqual((self.root / 'content/artifact/content.json').stat().st_size, 5_000_000)


if __name__ == '__main__':
    unittest.main()
