"""Normalize pinned D40/D54-D56 evolution recipes without changing encounters.

load_evolutions(directory, identities, targets, species) returns sorted edges,
item kinds ({id, name_en}) and an attacking-type -> defending-type factor map.
Species metadata comes from load_families; targets have the graph identity shape.
Only gender and trigger/held items survive condition stripping. Invalid or
incomplete retained recipes raise ValueError with PENDING; inputs are not mutated.
"""

from collections import Counter, defaultdict
from pathlib import Path

from .graph import ORDINARY_TYPES, _index, _read


def load_evolutions(directory, identities, targets, species):
    directory = Path(directory)
    defaults = {i['species_id']: i for i in identities if i['kind'] == 'default'}
    forms = {}
    for identity in [*targets, *identities]:
        for value in [identity, *identity.get('gender_varieties', {}).values()]:
            forms[value['form_id']] = value
    max_depth = defaultdict(int)
    for metadata in species.values():
        family = metadata['family_id']
        max_depth[family] = max(max_depth[family], metadata['depth'])

    item_rows = _index(_read(directory, 'items', 'id identifier'))
    names = {int(row['item_id']): row['name'] for row in _read(
        directory, 'item_names', 'item_id local_language_id name')
        if row['local_language_id'] == '9'}
    kinds, edges = {}, {}
    rows = _read(directory, 'pokemon_evolution',
                 'id evolved_species_id evolution_trigger_id is_default trigger_item_id '
                 'held_item_id gender_id required_pokemon_form_id evolved_pokemon_form_id')
    for row in rows:
        if row['is_default'] != '1' or row['evolution_trigger_id'] == '4':
            continue
        sid = int(row['evolved_species_id'])
        if sid not in defaults:
            continue
        parent = species[sid]['parent_species_id']
        if parent not in defaults:
            continue
        source_form = row['required_pokemon_form_id']
        source = forms.get(int(source_form), defaults[parent]) if source_form else defaults[parent]
        target_form = row['evolved_pokemon_form_id']
        target = forms.get(int(target_form), defaults[sid]) if target_form else defaults[sid]
        if source['species_id'] != parent or target['species_id'] != sid:
            raise ValueError(f'PENDING evolution {row["id"]} has inconsistent form species')
        gender = {'1': 'female', '2': 'male'}.get(row['gender_id'])
        item_id = row['trigger_item_id'] or row['held_item_id']
        item = None
        if item_id:
            iid = int(item_id)
            if iid not in item_rows or not names.get(iid):
                raise ValueError(f'PENDING item {iid} missing identifier or English name')
            item = item_rows[iid]['identifier']
            kinds[item] = {'id': item, 'name_en': names[iid]}
        metadata = species[parent]
        candy = 50 if max_depth[metadata['family_id']] == 1 else 25 if metadata['depth'] == 0 else 100
        source_id, target_id = source['identity_id'], target['identity_id']
        edge_id = f'{source_id}>{target_id}|{item or "-"}|{gender or "-"}'
        label = ' / '.join([target['name_en'], *([names[int(item_id)]] if item else []),
                            *([gender] if gender else [])])
        edges[edge_id] = dict(edge_id=edge_id, from_identity_id=source_id,
                              to_identity_id=target_id, to_species_id=sid, candy=candy,
                              item=item, gender=gender, label=label)
    incoming = {edge['to_species_id'] for edge in edges.values()}
    for sid in defaults:
        if species[sid]['parent_species_id'] is not None and sid not in incoming | {292, 489, 490}:
            raise ValueError(f'PENDING retained species {sid} has no incoming edge')
    recipes = defaultdict(Counter)
    for edge in edges.values():
        recipes[edge['from_identity_id']][edge['item']] += 1
    for source, counts in recipes.items():
        if len(counts) > 25 or max(counts.values()) > 25:
            raise ValueError(f'PENDING source {source} exceeds 25 items or recipes per item')

    types = {tid: row['identifier'] for tid, row in _index(
        _read(directory, 'types', 'id identifier')).items() if row['identifier'] in ORDINARY_TYPES}
    if set(types.values()) != ORDINARY_TYPES:
        raise ValueError('PENDING missing ordinary types')
    chart = {name: {} for name in sorted(ORDINARY_TYPES)}
    factors = {200: 1.6, 100: 1.0, 50: 0.625, 0: 0.390625}
    for row in _read(directory, 'type_efficacy', 'damage_type_id target_type_id damage_factor'):
        attack, defense = int(row['damage_type_id']), int(row['target_type_id'])
        if attack not in types or defense not in types:
            continue
        factor = int(row['damage_factor'])
        if factor not in factors or types[defense] in chart[types[attack]]:
            raise ValueError('PENDING invalid or duplicate type efficacy')
        chart[types[attack]][types[defense]] = factors[factor]
    if any(set(row) != ORDINARY_TYPES for row in chart.values()):
        raise ValueError('PENDING incomplete 18x18 type chart')
    return [edges[key] for key in sorted(edges)], [kinds[key] for key in sorted(kinds)], chart
