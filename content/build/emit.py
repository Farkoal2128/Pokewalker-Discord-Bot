"""Produce the C1 deterministic snapshot from verified, pinned CSV inputs."""

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .evolutions import load_evolutions
from .families import CATCH_RATES, add_families, load_families
from .fetch import CACHE_DIR, OPTIONAL_CSVS, REQUIRED_CSVS, SOURCE_COMMIT
from .graph import GENDER, _index, _read, load_graph
from .stats import add_stats


ROOT = Path(__file__).resolve().parents[2]
SPRITES_COMMIT = "1b3b7c0a538dd2226ae08d0d2f8955125075bbd4"
IMPORTER_VERSION = "2"
SPRITE_PATHS = {"normal": "", "shiny": "shiny/", "female": "female/", "shiny_female": "shiny/female/"}
SPRITE_COLUMNS = {"normal": "front_default", "shiny": "front_shiny",
                  "female": "front_female", "shiny_female": "front_shiny_female"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def verified_inputs(directory):
    source = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if source["source_commit"] != SOURCE_COMMIT:
        raise ValueError("cache source commit differs from D51 pin")
    hashes = {}
    for name in REQUIRED_CSVS + OPTIONAL_CSVS:
        path = directory / (name + ".csv")
        if name in OPTIONAL_CSVS and not path.exists():
            if name not in source["optional_missing"]:
                raise ValueError(f"unrecorded missing optional CSV: {name}")
            continue
        actual = digest(path)
        if source["sha256"].get(path.name) != actual:
            raise ValueError(f"hash mismatch: {path.name}")
        hashes[path.name] = actual
    return hashes


def sprite_records(directory, audit_sprites, opener):
    forms = _index(_read(directory, "pokemon_forms", "id form_identifier is_default"))
    tables = {}
    for table, key in (("pokemon_sprites", "pokemon_id"), ("pokemon_form_sprites", "pokemon_form_id")):
        if (directory / (table + ".csv")).exists():
            tables[table] = _index(_read(directory, table, key + " " + " ".join(SPRITE_COLUMNS.values())), key)
    audit = "head" if audit_sprites else "csv" if tables else "none"
    checked = {}

    def records(value):
        form = forms[value["form_id"]]
        sprite_key = str(value["pokemon_id"])
        if form["is_default"] != "1":
            sprite_key += "-" + form["form_identifier"]
        row = None
        if tables:
            row = tables.get("pokemon_form_sprites", {}).get(value["form_id"])
            if row is None:
                row = tables.get("pokemon_sprites", {}).get(value["pokemon_id"])
        result = {}
        for key, prefix in SPRITE_PATHS.items():
            url = f"https://raw.githubusercontent.com/PokeAPI/sprites/{SPRITES_COMMIT}/sprites/pokemon/{prefix}{sprite_key}.png"
            if "female" in key and not value["has_gender_differences"]:
                result[key] = None
            elif audit_sprites:
                if url not in checked:
                    try:
                        with opener(Request(url, method="HEAD"), timeout=30):
                            checked[url] = url
                    except HTTPError as error:
                        if error.code not in (404, 410):
                            raise
                        checked[url] = None
                result[key] = checked[url]
            elif tables and (row is None or not row[SPRITE_COLUMNS[key]]):
                result[key] = None
            else:
                result[key] = url
        return result

    return audit, records


def qualifying_families(artifact):
    return {fid: members for fid, members in artifact["families"].items()
            if len(members) >= 2 and any(artifact["species"][str(sid)]["parent_species_id"] is not None
                                         for sid in members)}


def validate_artifact(artifact):
    records = [*artifact["identities"], *artifact["evolution_targets"]]
    endpoints = {value["identity_id"] for identity in records
                 for value in [identity, *identity.get("gender_varieties", {}).values()]}
    for target in artifact["evolution_targets"]:
        if set(target.get("sprites", {})) != set(SPRITE_PATHS):
            raise ValueError(f"target {target['identity_id']} missing sprite keys")
    for source, edges in artifact["evolutions"].items():
        counts = Counter(edge["item"] for edge in edges)
        if len(counts) > 25 or (counts and max(counts.values()) > 25):
            raise ValueError(f"source {source} exceeds 25 items or recipes per item")
        for edge in edges:
            if (source != edge["from_identity_id"] or source not in endpoints
                    or edge["to_identity_id"] not in endpoints):
                raise ValueError(f"unresolved evolution endpoint: {edge['edge_id']}")
    for identity in artifact["identities"]:
        if identity["tier"] != "Legendary/Mythical" and not any(
                route["weights"][identity["identity_id"]] > 0 for route in artifact["routes"].values()):
            raise ValueError(f"identity {identity['identity_id']} has no route; update routes.json")
    starters = artifact["starters"]
    if len(starters) != 27 or len(set(starters)) != 27 or any(
            str(sid) not in artifact["species"] or artifact["species"][str(sid)]["role"] != "base"
            for sid in starters):
        raise ValueError("starters must be 27 existing base-stage species")
    lines = artifact["milestones"]["evolution_lines"]["families"]
    observed = {str(line["family_id"]): line["species_ids"] for line in lines}
    if len(observed) != len(lines) or observed != qualifying_families(artifact):
        raise ValueError("qualifying family missing or incorrect evolution-line milestone")


def build_content(directory=CACHE_DIR, balance_directory=ROOT / "content/balance", *,
                  audit_sprites=False, opener=urlopen):
    directory, balance_directory = Path(directory), Path(balance_directory)
    hashes = verified_inputs(directory)
    graph = load_graph(directory)
    identities = graph["identities"]
    targets = graph["evolution_targets"]
    add_stats(identities + targets, directory)
    add_families(identities + targets, directory)
    species = load_families(directory)
    rows = _index(_read(directory, "pokemon_species",
                        "id identifier gender_rate has_gender_differences habitat_id generation_id"))
    habitats = _index(_read(directory, "pokemon_habitats", "id identifier"))
    families = defaultdict(list)
    audit, sprites = sprite_records(directory, audit_sprites, opener)
    for sid, metadata in species.items():
        row = rows[sid]
        rate = int(row["gender_rate"])
        if rate not in range(-1, 9) or row["has_gender_differences"] not in {"0", "1"}:
            raise ValueError(f"invalid gender data for species {sid}")
        habitat_id = int(row["habitat_id"]) if row["habitat_id"] else None
        if habitat_id is not None and habitat_id not in habitats:
            raise ValueError(f"unresolved habitat for species {sid}")
        metadata.update(generation_id=int(row["generation_id"]),
                        habitat=habitats[habitat_id]["identifier"] if habitat_id is not None else None,
                        gender_rate=4 if row["identifier"] in GENDER else rate,
                        has_gender_differences=row["has_gender_differences"] == "1")
        families[str(metadata["family_id"])].append(sid)
    for identity in identities + targets:
        for value in [identity, *identity.get("gender_varieties", {}).values()]:
            value.update(species[value["species_id"]])
            value["sprites"] = sprites(value)

    edges, evolution_items, type_chart = load_evolutions(directory, identities, targets, species)
    evolutions = defaultdict(list)
    for edge in edges:
        evolutions[edge["from_identity_id"]].append(edge)

    balance_paths = sorted(balance_directory.glob("*.json"))
    balances = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in balance_paths}
    milestones = balances["milestones"]
    routes = {}
    for route in balances["routes"]["routes"]:
        if route["id"] in routes:
            raise ValueError("duplicate route id")
        weights = {i["identity_id"]: max(route["weights"].get(t, 0) for t in i["types"]) for i in identities}
        counts = Counter(i["tier"] for i in identities if weights[i["identity_id"]] > 0)
        routes[route["id"]] = {"weights": weights, "eligible_counts": {tier: counts[tier] for tier in CATCH_RATES}}
    artifact = {"schema_version": 1, "identities": identities,
                "evolution_targets": targets, "evolutions": dict(evolutions),
                "evolution_items": evolution_items, "type_chart": type_chart,
                "species": {str(sid): value for sid, value in species.items()},
                "families": {fid: sorted(members) for fid, members in families.items()},
                "routes": routes, "starters": milestones["all_starters"]["species_ids"],
                "milestones": milestones}
    if sorted(s for trio in milestones["starter_trios"] for s in trio["species_ids"]) != sorted(artifact["starters"]):
        raise ValueError("starter trios differ from all-starter milestone")
    line_rules = milestones["evolution_lines"]
    line_rules["families"] = [{"family_id": int(fid), "species_ids": members,
                               "family_candy": line_rules["family_candy"],
                               "ultra_ball": line_rules["ultra_ball"],
                               "stardust": line_rules["stardust_per_species"] * len(members)}
                              for fid, members in sorted(qualifying_families(artifact).items(), key=lambda pair: int(pair[0]))]
    pending = list(graph["pending"])

    def check_set(label, ids, flag=None):
        for sid in ids:
            if sid not in species or (flag and not species[sid][flag]):
                pending.append({"species_id": sid, "reason": f"PENDING {label}: missing species or inconsistent flags"})

    for group, flag in (("legendary_groups", "is_legendary"), ("mythical_sets", "is_mythical")):
        for entry in milestones[group]:
            check_set(group, entry["species_ids"], flag)
    for entry in milestones["extra_bundle_lines"]:
        flag = "is_mythical" if entry["id"] == "meltan" else None if entry["id"] == "poipole" else "is_legendary"
        check_set(entry["id"], entry["species_ids"], flag)
    for entry in milestones["ultra_beast_first_catches"]:
        sid = entry["species_id"]
        check_set("ultra_beast_first_catches", [sid])
        if sid in species and (species[sid]["is_legendary"] or species[sid]["is_mythical"]):
            pending.append({"species_id": sid, "reason": "PENDING Ultra Beast has Legendary/Mythical flags"})
    for entry in milestones["regions"]:
        entry["species_ids"] = sorted(sid for sid, value in species.items() if value["generation_id"] == entry["generation"])
    for key, flag in (("all_legendaries", "is_legendary"), ("all_mythicals", "is_mythical")):
        entry = milestones[key]
        entry["species_ids"] = sorted(sid for sid, value in species.items() if value[flag])
        if len(entry["species_ids"]) != entry["species_count"]:
            pending.append({"reason": f"PENDING {key}: expected flag count differs"})
    validate_artifact(artifact)
    counts = {"species": len(species), "identities": len(identities),
              "evolution_targets": len(targets), "evolution_edges": len(edges),
              "evolution_items": len(evolution_items),
              "regional_identities": sum(i["kind"] == "regional" for i in identities),
              "legendary_species": sum(i["is_legendary"] for i in species.values()),
              "mythical_species": sum(i["is_mythical"] for i in species.values()),
              "evolution_line_families": len(line_rules["families"]),
              "evolution_line_species": sum(len(line["species_ids"]) for line in line_rules["families"])}
    for count_key, rule_key in (("evolution_line_families", "expected_family_count"),
                               ("evolution_line_species", "expected_species_count")):
        if counts[count_key] != line_rules[rule_key]:
            raise ValueError(f"evolution-line count differs: {count_key}={counts[count_key]}")
    manifest = {"schema_version": 1, "importer_version": IMPORTER_VERSION,
                "artifact_sha256": hashlib.sha256(encode(artifact)).hexdigest(),
                "pokeapi_commit": SOURCE_COMMIT, "sprites_commit": SPRITES_COMMIT,
                "csv_sha256": hashes, "balance_sha256": {path.name: digest(path) for path in balance_paths},
                "counts": counts, "excluded": graph["excluded"], "pending": pending, "sprite_audit": audit}
    return artifact, manifest


def write_artifacts(artifact, manifest, output_root=ROOT, *, check=False):
    outputs = {Path(output_root) / "content/artifact/content.json": encode(artifact),
               Path(output_root) / "content/manifest.json": encode(manifest)}
    if len(next(iter(outputs.values()))) > 5_000_000:
        raise ValueError("artifact exceeds 5 MB; compressed storage requires reconciliation")
    if check:
        return all(path.exists() and path.read_bytes() == data for path, data in outputs.items())
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
    return True
