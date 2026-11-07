"""D36/P5/P8 pure calculations; no loading or rounding before the final floor.

Additive M1.3 boundary: base and IV triples are ordered Attack, Defense, Stamina.
``multipliers`` is the decoded cpm.json payload; ``rules`` is catch.json rules.
Callers inject these trusted, reviewed tables. Invalid levels/IVs raise ValueError.
No persisted formats or existing consumers change.
"""

import math
import random
from collections.abc import Mapping, Sequence


def cpm(level_x2: int, *, multipliers: Mapping[str, float]) -> float:
    if type(level_x2) is not int or not 2 <= level_x2 <= 80:
        raise ValueError("level_x2 must be an integer from 2 to 80")
    return multipliers[str(level_x2)]


def _validate_ivs(ivs: Sequence[int]) -> None:
    if len(ivs) != 3 or any(type(v) is not int or not 0 <= v <= 15 for v in ivs):
        raise ValueError("IVs must be three integers from 0 to 15")


def _stats(base: Sequence[int], ivs: Sequence[int]) -> tuple[int, int, int]:
    _validate_ivs(ivs)
    if len(base) != 3 or any(type(v) is not int or v <= 0 for v in base):
        raise ValueError("base stats must be three positive integers")
    return tuple(b + v for b, v in zip(base, ivs))


def cp(base: Sequence[int], ivs: Sequence[int], level_x2: int, *,
       multipliers: Mapping[str, float]) -> int:
    attack, defense, stamina = _stats(base, ivs)
    m = cpm(level_x2, multipliers=multipliers)
    return max(10, math.floor(attack * math.sqrt(defense) * math.sqrt(stamina) * m ** 2 / 10))


def hp(base: Sequence[int], ivs: Sequence[int], level_x2: int, *,
       multipliers: Mapping[str, float]) -> int:
    return max(10, math.floor(_stats(base, ivs)[2] * cpm(level_x2, multipliers=multipliers)))


def appraisal(ivs: Sequence[int]) -> int:
    _validate_ivs(ivs)
    return sum(sum(ivs) >= boundary for boundary in (23, 30, 37, 45))


def catch_probability(bcr: float, level_x2: int, ball: float, berry: float, *,
                      multipliers: Mapping[str, float]) -> float:
    if not all(math.isfinite(v) for v in (bcr, ball, berry)) or ball <= 0 or berry <= 0:
        raise ValueError("catch inputs must be finite; ball and berry must be positive")
    chance = max(0, min(1, bcr / (2 * cpm(level_x2, multipliers=multipliers))))
    return 1 - (1 - chance) ** (ball * berry)


def flees_after_failure(tier: str, shiny: bool, rng: random.Random, *, rules: Mapping) -> bool:
    """Only call after an ordinary failed throw; Master Ball bypasses this path."""
    if tier not in {"Common", "Uncommon", "Rare", "Evolved", "Legendary/Mythical"}:
        raise ValueError("unknown encounter tier")
    probability = (rules["shiny_flee_probability"] if shiny else
                   rules["legendary_flee_probability"] if tier == "Legendary/Mythical" else
                   rules["flee_probability"])
    return probability > 0 and rng.random() < probability
