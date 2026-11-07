"""D38/D40a species topology and encounter classification.

``load_families`` returns species_id -> family_id, parent_species_id, depth,
role (base/middle/final), family_size, is_legendary and is_mythical. Only genuine
species-parent edges count, including separate roots in Phione/Manaphy's chain.
``add_families`` enriches identities in place with that metadata, tier,
base_catch_rate, catch_candy and catch_stardust, using each identity's own BST.
Attached gender varieties inherit the default identity's classification (D53).
Invalid topology or an undecided depth/flag raises ValueError with PENDING.
Run as a module to report pinned-cache species flags and per-tier identity counts.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .fetch import CACHE_DIR
from .graph import _index, _read, load_graph
from .stats import add_stats


CATCH_RATES = {"Common": 0.50, "Uncommon": 0.30, "Rare": 0.15,
               "Evolved": 0.15, "Legendary/Mythical": 0.05}
REWARDS = {0: (3, 100), 1: (5, 300), 2: (10, 500)}


def load_families(directory=CACHE_DIR):
    species = _index(_read(Path(directory), "pokemon_species",
                           "id evolution_chain_id evolves_from_species_id is_legendary is_mythical"))
    result, families, children = {}, defaultdict(list), defaultdict(list)
    for sid, row in species.items():
        if not row["evolution_chain_id"]:
            raise ValueError(f"PENDING species {sid} missing chain id")
        if any(row[key] not in {"0", "1"} for key in ("is_legendary", "is_mythical")):
            raise ValueError(f"PENDING species {sid} invalid legendary/mythical flags")
        family_id = int(row["evolution_chain_id"])
        parent = int(row["evolves_from_species_id"]) if row["evolves_from_species_id"] else None
        result[sid] = {"family_id": family_id, "parent_species_id": parent,
                       "is_legendary": row["is_legendary"] == "1",
                       "is_mythical": row["is_mythical"] == "1"}
        families[family_id].append(sid)
        if parent is not None:
            children[parent].append(sid)
    for sid, value in result.items():
        parent = value["parent_species_id"]
        if parent is not None:
            if parent not in result:
                raise ValueError(f"PENDING species {sid} unresolved parent {parent}")
            if result[parent]["family_id"] != value["family_id"]:
                raise ValueError(f"PENDING species {sid} and parent must share same chain")

    visiting = set()

    def depth(sid):
        value = result[sid]
        if "depth" in value:
            return value["depth"]
        if sid in visiting:
            raise ValueError(f"PENDING species parent cycle at {sid}")
        visiting.add(sid)
        parent = value["parent_species_id"]
        value["depth"] = 0 if parent is None else depth(parent) + 1
        visiting.remove(sid)
        return value["depth"]

    for sid, value in result.items():
        depth(sid)
        value["role"] = ("base" if value["parent_species_id"] is None else
                         "middle" if children[sid] else "final")
        value["family_size"] = len(families[value["family_id"]])
    return result


def add_families(identities, directory=CACHE_DIR):
    species = load_families(directory)
    for identity in identities:
        sid = identity["species_id"]
        if sid not in species:
            raise ValueError(f"PENDING identity has unresolved species {sid}")
        metadata = species[sid]
        legendary = metadata["is_legendary"] or metadata["is_mythical"]
        if legendary:
            tier = "Legendary/Mythical"
        elif metadata["role"] == "final" and metadata["family_size"] >= 2:
            tier = "Evolved"
        elif identity["bst"] >= 500:
            tier = "Rare"
        elif metadata["role"] == "middle" or identity["bst"] >= 400:
            tier = "Uncommon"
        else:
            tier = "Common"
        if metadata["depth"] not in REWARDS:
            raise ValueError(f"PENDING undefined catch rewards at depth {metadata['depth']}")
        candy, stardust = (10, 500) if legendary else REWARDS[metadata["depth"]]
        classification = dict(metadata, tier=tier, base_catch_rate=CATCH_RATES[tier],
                              catch_candy=candy, catch_stardust=stardust)
        for value in [identity, *identity.get("gender_varieties", {}).values()]:
            value.update(classification)


if __name__ == "__main__":
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else CACHE_DIR
    graph = load_graph(directory)
    add_stats(graph["identities"], directory)
    add_families(graph["identities"], directory)
    species = load_families(directory)
    print(json.dumps({"legendary_species": sum(i["is_legendary"] for i in species.values()),
                      "mythical_species": sum(i["is_mythical"] for i in species.values()),
                      "tiers": Counter(i["tier"] for i in graph["identities"]),
                      "pending": graph["pending"]}, indent=2))
    sys.exit(bool(graph["pending"]))
