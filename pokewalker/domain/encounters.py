"""D38/D50/D53/P4 pure encounter generation from reviewed, injected tables.

Additive M1.3 boundary: pools map artifact tier names to identity records; route is
an artifact route with identity-ID weights. ``chances`` is tier_chances.json's
lowercase-keyed payload; ``rules`` is catch.json rules. No I/O occurs here.
The selected default identity controls tier/route; gender picks the payload.
EncounterSpec detaches its immutable sprite map from the input artifact.
Invalid empty eligible pools raise ValueError; no legendary chance is redistributed.
"""

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType


LEGENDARY = "Legendary/Mythical"
MIRROR_TIERS = ("Common", "Uncommon", "Evolved")


@dataclass(frozen=True)
class EncounterSpec:
    identity_id: str
    species_id: int
    family_id: int
    pokemon_id: int
    form_id: int
    tier: str
    gender: str | None
    shiny: bool
    level_x2: int
    ivs: tuple[int, int, int]
    base_attack: int
    base_defense: int
    base_stamina: int
    sprites: Mapping[str, str | None]
    base_catch_rate: float
    catch_candy: int
    catch_stardust: int


def roll_tier(route_pools: Mapping[str, Sequence], chances: Mapping[str, float],
              rng: random.Random) -> str:
    """Reserve the 1% legendary draw, then renormalize nonempty ordinary tiers."""
    if rng.random() < chances["legendary"] / sum(chances.values()):
        return LEGENDARY
    tiers = [tier for tier, pool in route_pools.items() if pool and tier != LEGENDARY]
    if not tiers:
        raise ValueError("route has no eligible non-legendary identities")
    return rng.choices(tiers, weights=[chances[tier.lower()] for tier in tiers], k=1)[0]


def pick_identity(pool: Sequence[Mapping], weights: Mapping[str, float],
                  rng: random.Random) -> Mapping:
    if not pool:
        raise ValueError("identity pool is empty")
    if pool[0]["tier"] == LEGENDARY:
        return rng.choice(pool)
    values = [weights.get(identity["identity_id"], 0) for identity in pool]
    if any(not math.isfinite(w) or w < 0 for w in values) or sum(values) <= 0:
        raise ValueError("identity weights must be finite, nonnegative and have a positive total")
    return rng.choices(pool, weights=values, k=1)[0]


def roll_gender(identity: Mapping, rng: random.Random) -> tuple[str | None, Mapping]:
    if "gender_varieties" in identity:
        gender = "female" if rng.random() < .5 else "male"
        return gender, identity["gender_varieties"][gender]
    rate = identity["gender_rate"]
    if rate == -1:
        return None, identity
    return ("female" if rng.random() < rate / 8 else "male"), identity


def roll_shiny(rng: random.Random, lure_active: bool, *, rules: Mapping) -> bool:
    probability = rules["shiny_probability"]
    if lure_active:
        probability *= rules["lure_probability_multiplier"]
    return rng.random() < probability


def roll_level_ivs(rng: random.Random, *, rules: Mapping) -> tuple[int, tuple[int, int, int]]:
    return (2 * rng.randint(*rules["wild_level_range"]),
            tuple(rng.randint(*rules["wild_iv_range"]) for _ in range(3)))


def starter_rolls(rng: random.Random, *, rules: Mapping) -> tuple[int, tuple[int, int, int]]:
    return (2 * rules["starter_level"],
            tuple(rng.randint(*rules["starter_iv_range"]) for _ in range(3)))


def generate(identity_pools: Mapping[str, Sequence[Mapping]], route: Mapping,
             lure_active: bool, rng: random.Random, *, chances: Mapping,
             rules: Mapping) -> EncounterSpec:
    weights = route["weights"]
    eligible = {tier: [i for i in pool if tier == LEGENDARY or weights.get(i["identity_id"], 0) > 0]
                for tier, pool in identity_pools.items()}
    tier = roll_tier(eligible, chances, rng)
    identity = pick_identity(eligible.get(tier, []), weights, rng)
    return _spec(identity, tier, lure_active, rng, rules)


def mirror_hit(rng: random.Random, *, rules: Mapping) -> bool:
    """One Companion Mirror draw per generated encounter."""
    return rng.random() < rules["mirror_probability"]


def mirror_pools(identities: Sequence[Mapping], family_id: int) -> dict[str, list[Mapping]]:
    """Encounter identities of one family the mirror may attract, by tier.

    Only Common, Uncommon and Evolved tiers qualify; Legendary/Mythical and Rare tiers
    and any Legendary- or Mythical-flagged identity are skipped. Empty means none.
    """
    pools: dict[str, list[Mapping]] = {}
    for identity in identities:
        if (identity["family_id"] == family_id and identity["tier"] in MIRROR_TIERS
                and not identity["is_legendary"] and not identity["is_mythical"]):
            pools.setdefault(identity["tier"], []).append(identity)
    return pools


def generate_mirror(pools: Mapping[str, Sequence[Mapping]], rng: random.Random, *,
                    chances: Mapping, rules: Mapping) -> EncounterSpec:
    """Tier by roll_tier without the Legendary draw, then uniform; routes are ignored."""
    tier = roll_tier(pools, {**chances, "legendary": 0}, rng)
    return _spec(rng.choice(pools[tier]), tier, False, rng, rules)


def _spec(identity: Mapping, tier: str, lure_active: bool, rng: random.Random,
          rules: Mapping) -> EncounterSpec:
    gender, variety = roll_gender(identity, rng)
    shiny = roll_shiny(rng, lure_active, rules=rules)
    level_x2, ivs = roll_level_ivs(rng, rules=rules)
    return EncounterSpec(
        identity_id=identity["identity_id"], species_id=identity["species_id"],
        family_id=identity["family_id"], pokemon_id=variety["pokemon_id"],
        form_id=variety["form_id"], tier=tier, gender=gender, shiny=shiny,
        level_x2=level_x2, ivs=ivs, base_attack=variety["base_attack"],
        base_defense=variety["base_defense"], base_stamina=variety["base_stamina"],
        sprites=MappingProxyType(dict(variety["sprites"])),
        base_catch_rate=identity["base_catch_rate"], catch_candy=identity["catch_candy"],
        catch_stardust=identity["catch_stardust"])
