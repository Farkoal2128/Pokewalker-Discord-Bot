"""D39 conversion, without GO exceptions.

``derive_stats`` accepts the six main-series stat identifiers and positive ints;
it returns bst, base_attack, base_defense, base_stamina and stats_source.
``add_stats`` enriches identities and attached gender varieties in place from
their own pokemon_id's CSV stats. Missing/invalid stats raise ValueError.
"""

from collections import defaultdict
from pathlib import Path

from .fetch import CACHE_DIR
from .graph import _index, _read


SIX_STATS = {"hp", "attack", "defense", "special-attack", "special-defense", "speed"}


def derive_stats(stats):
    if set(stats) != SIX_STATS or any(type(v) is not int or v <= 0 for v in stats.values()):
        raise ValueError("PENDING main-series stats must be six positive integers")
    ah, al = sorted((stats["attack"], stats["special-attack"]), reverse=True)
    dh, dl = sorted((stats["defense"], stats["special-defense"]), reverse=True)
    # Integer fractions implement floor(x + 0.5) exactly at both rounding steps.
    attack = (7 * ah + al + 2) // 4
    defense = (5 * dh + 3 * dl + 2) // 4
    speed_factor = stats["speed"] + 425
    return {"bst": sum(stats.values()),
            "base_attack": (attack * speed_factor + 250) // 500,
            "base_defense": (defense * speed_factor + 250) // 500,
            "base_stamina": 7 * stats["hp"] // 4 + 50,
            "stats_source": "derived-d39"}


def add_stats(identities, directory=CACHE_DIR):
    directory = Path(directory)
    names = _index(_read(directory, "stats", "id identifier"))
    stats = defaultdict(dict)
    for row in _read(directory, "pokemon_stats", "pokemon_id stat_id base_stat"):
        pid, stat_id = int(row["pokemon_id"]), int(row["stat_id"])
        if stat_id not in names:
            raise ValueError("unresolved stat foreign key")
        name = names[stat_id]["identifier"]
        if name in stats[pid]:
            raise ValueError(f"duplicate stat for pokemon {pid}")
        stats[pid][name] = int(row["base_stat"])
    for identity in identities:
        for value in [identity, *identity.get("gender_varieties", {}).values()]:
            value.update(derive_stats(stats[value["pokemon_id"]]))
