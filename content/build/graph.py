"""Build D51/D52/D53 encounter identities from one pinned CSV directory.

``load_graph(directory)`` returns identities, evolution_targets, excluded, and pending lists. IDs
remain distinct: identity_id is ``pokemon_id:form_id``. types are identifiers;
gender_varieties maps male/female to the same identity fields without recursion.
Excluded/pending rows retain source IDs and a reason. Missing columns, broken
foreign keys/defaults, or incomplete retained stats/types raise ValueError.
Unknown mechanical alternatives are pending and the CLI refuses promotion.
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from .fetch import CACHE_DIR


REGIONAL = {"alola", "galar", "hisui", "paldea", "galar-standard",
            "paldea-combat-breed", "paldea-blaze-breed", "paldea-aqua-breed"}
DEFAULT_ONLY = {
    "deoxys", "dialga", "palkia", "giratina", "tornadus", "thundurus", "landorus",
    "enamorus", "kyurem", "necrozma", "calyrex", "hoopa", "shaymin", "zygarde",
    "arceus", "silvally", "ogerpon", "floette", "pikachu", "eevee", "rotom",
    "gimmighoul", "minior",
}
SEPARATE = {"wormadam", "oricorio", "pumpkaboo", "gourgeist", "ursaluna"}
EVOLUTION_ONLY = {"lycanroc", "urshifu", "alcremie"}  # Q15: sweets and creams are evolution-only.
GENDER = {"indeedee", "basculegion", "oinkologne"}
ORDINARY_TYPES = {
    "normal", "fighting", "flying", "poison", "ground", "rock", "bug", "ghost",
    "steel", "fire", "water", "grass", "electric", "psychic", "ice", "dragon",
    "dark", "fairy",
}


def _read(directory, name, columns):
    with (directory / (name + ".csv")).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(columns.split()) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"PENDING missing CSV columns in {name}: {sorted(missing)}")
        return list(reader)


def _index(rows, key="id"):
    result = {}
    for row in rows:
        value = int(row[key])
        if value in result:
            raise ValueError(f"duplicate {key}: {value}")
        result[value] = row
    return result


def load_graph(directory=CACHE_DIR):
    directory = Path(directory)
    species = _index(_read(directory, "pokemon_species", "id identifier"))
    pokemon = _index(_read(directory, "pokemon", "id identifier species_id is_default"))
    forms = _index(_read(directory, "pokemon_forms",
                         "id identifier form_identifier pokemon_id is_default is_battle_only is_mega"))
    stat_names = _index(_read(directory, "stats", "id identifier"))
    type_names = _index(_read(directory, "types", "id identifier"))
    varieties, pokemon_forms = defaultdict(list), defaultdict(list)
    for row in pokemon.values():
        sid = int(row["species_id"])
        if sid not in species:
            raise ValueError(f"unresolved species foreign key: {sid}")
        varieties[sid].append(row)
    for form in forms.values():
        pid = int(form["pokemon_id"])
        if pid not in pokemon:
            raise ValueError(f"unresolved pokemon foreign key: {pid}")
        pokemon_forms[pid].append(form)
    stats = defaultdict(dict)
    for row in _read(directory, "pokemon_stats", "pokemon_id stat_id base_stat"):
        pid, stat_id = int(row["pokemon_id"]), int(row["stat_id"])
        if pid not in pokemon or stat_id not in stat_names:
            raise ValueError("unresolved stat foreign key")
        if stat_id in stats[pid]:
            raise ValueError(f"duplicate stat for pokemon {pid}")
        stats[pid][stat_id] = int(row["base_stat"])
    effective_types = {}
    for table, key, owners in (("pokemon_types", "pokemon_id", pokemon),
                               ("pokemon_form_types", "pokemon_form_id", forms)):
        rows = defaultdict(dict)
        for row in _read(directory, table, f"{key} type_id slot"):
            owner, tid, slot = int(row[key]), int(row["type_id"]), int(row["slot"])
            if owner not in owners or tid not in type_names:
                raise ValueError("unresolved type foreign key")
            if slot in rows[owner]:
                raise ValueError(f"duplicate type slot in {table}: {owner}")
            rows[owner][slot] = type_names[tid]["identifier"]
        effective_types[table] = {key: [slots[s] for s in sorted(slots)]
                                  for key, slots in rows.items()}
    names = {int(row["pokemon_species_id"]): row["name"] for row in _read(
        directory, "pokemon_species_names", "pokemon_species_id local_language_id name")
        if row["local_language_id"] == "9"}
    form_names = {int(row["pokemon_form_id"]): row for row in _read(
        directory, "pokemon_form_names", "pokemon_form_id local_language_id form_name pokemon_name")
        if row["local_language_id"] == "9"}
    result = {"identities": [], "evolution_targets": [], "excluded": [], "pending": []}
    blocked = set()

    def report(category, form, reason):
        pid = int(form["pokemon_id"])
        result[category].append({"species_id": int(pokemon[pid]["species_id"]),
                                 "pokemon_id": pid, "form_id": int(form["id"]), "reason": reason})

    for fid, form in forms.items():
        tokens = form["identifier"].split("-")
        descriptor_tokens = form["form_identifier"].split("-")
        reason = None
        if (form["is_mega"] == "1" or form["is_battle_only"] == "1"
                or "mega" in tokens + descriptor_tokens
                or {tokens[-1], descriptor_tokens[-1]} & {"gmax", "primal", "eternamax"}
                or (int(form["pokemon_id"]), fid) == (10190, 10359)):
            reason = "battle transformation excluded"
        elif "totem" in tokens + descriptor_tokens:
            reason = "Totem duplicate excluded"
        elif fid == 10057:
            reason = "Arceus Unknown quarantined (D58)"
        if reason:
            blocked.add(fid)
            report("excluded", form, reason)

    six_stats = {sid for sid, row in stat_names.items() if row["identifier"] in {
        "hp", "attack", "defense", "special-attack", "special-defense", "speed"}}

    def identity(form, kind):
        pid, fid = int(form["pokemon_id"]), int(form["id"])
        sid = int(pokemon[pid]["species_id"])
        if len(six_stats) != 6 or set(stats[pid]) != six_stats:
            raise ValueError(f"pokemon {pid} must have exactly six stats")
        types = effective_types["pokemon_form_types"].get(fid,
                    effective_types["pokemon_types"].get(pid, []))
        if not types:
            raise ValueError(f"pokemon {pid}/form {fid} missing type")
        if not set(types) <= ORDINARY_TYPES:
            raise ValueError(f"pokemon {pid}/form {fid} unsupported type")
        localized = form_names.get(fid, {})
        name = localized.get("pokemon_name") or names.get(sid)
        if not name:
            raise ValueError(f"species {sid} missing English name")
        if not localized.get("pokemon_name") and localized.get("form_name"):
            name += " (" + localized["form_name"] + ")"
        return {"identity_id": f"{pid}:{fid}", "species_id": sid, "pokemon_id": pid,
                "form_id": fid, "kind": kind, "types": types, "name_en": name}

    def default_form(pid):
        defaults = [f for f in pokemon_forms[pid] if f["is_default"] == "1"]
        if len(defaults) != 1 or int(defaults[0]["id"]) in blocked:
            raise ValueError(f"pokemon {pid} requires one surviving default form")
        return defaults[0]

    defaults = {}
    included = set()
    for sid in species:
        choices = [p for p in varieties[sid] if p["is_default"] == "1"]
        if len(choices) != 1:
            raise ValueError(f"species {sid} requires one default variety")
        form = default_form(int(choices[0]["id"]))
        value = identity(form, "default")
        defaults[sid] = value
        included.add(int(form["id"]))
        result["identities"].append(value)

    for fid, form in forms.items():
        if fid in blocked or fid in included:
            continue
        pid = int(form["pokemon_id"])
        sid = int(pokemon[pid]["species_id"])
        group = species[sid]["identifier"]
        descriptor = form["form_identifier"]  # API form_name is CSV form_identifier.
        if descriptor in REGIONAL and pokemon[pid]["is_default"] != "1":
            if default_form(pid) != form:
                raise ValueError(f"regional form {fid} is not its variety default")
            result["identities"].append(identity(form, "regional"))
        elif group in GENDER and descriptor == "female":
            if default_form(pid) != form:
                raise ValueError(f"female form {fid} is not its variety default")
            base = defaults[sid]
            base["gender_varieties"] = {
                "male": {key: value for key, value in base.items() if key != "gender_varieties"},
                "female": identity(form, "form"),
            }
        elif group in DEFAULT_ONLY:
            report("excluded", form, "D52 default-only policy")
        elif group in EVOLUTION_ONLY:
            report("excluded", form, "D52 evolution branch; no separate encounter")
            result["evolution_targets"].append(identity(form, "form"))
        elif group in SEPARATE and pokemon[pid]["is_default"] != "1":
            if default_form(pid) != form:
                raise ValueError(f"encounter form {fid} is not its variety default")
            result["identities"].append(identity(form, "form"))
        else:
            candidate = identity(form, "form")
            base = defaults[sid]
            if (stats[pid] == stats[base["pokemon_id"]] and candidate["types"] == base["types"]):
                report("excluded", form, "cosmetic-equivalent; source form provenance retained")
            else:
                report("pending", form, "PENDING unclassified mechanical form")
    for sid, base in defaults.items():
        if species[sid]["identifier"] in GENDER and "gender_varieties" not in base:
            raise ValueError(f"species {sid} missing reachable female variety (D53)")
    return result


if __name__ == "__main__":
    report = load_graph(Path(sys.argv[1]) if len(sys.argv) > 1 else CACHE_DIR)
    print(json.dumps({"identity_count": len(report["identities"]),
                      "excluded": report["excluded"], "pending": report["pending"]}, indent=2))
    sys.exit(bool(report["pending"]))
