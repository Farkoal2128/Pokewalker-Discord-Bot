"""C7 pure, deterministic bot-template battles; injected rules, no I/O or RNG."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .cp import cpm, hp


ENGINE_VERSION = "1"


def _positive(value, label, *, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or value <= 0 or
            (integer and type(value) is not int)):
        raise ValueError(f"{label} must be finite and positive" +
                         (" integer" if integer else ""))


@dataclass(frozen=True)
class Combatant:
    name: str
    types: tuple[str, ...]
    attack: float
    defense: float
    hp: int
    fast_type: str
    charged_type: str

    def __post_init__(self):
        if (not isinstance(self.name, str) or not self.name.strip() or
                "\n" in self.name or "\r" in self.name):
            raise ValueError("name must be nonempty and single-line")
        if (not isinstance(self.types, (tuple, list)) or not 1 <= len(self.types) <= 2 or
                any(not isinstance(t, str) or not t for t in self.types) or
                len(set(self.types)) != len(self.types)):
            raise ValueError("types must contain one or two distinct type names")
        if any(not isinstance(t, str) or not t for t in (self.fast_type, self.charged_type)):
            raise ValueError("move types must be nonempty type names")
        object.__setattr__(self, "types", tuple(self.types))
        _positive(self.attack, "attack")
        _positive(self.defense, "defense")
        _positive(self.hp, "hp", integer=True)


@dataclass(frozen=True)
class Result:
    outcome: str
    reason: str
    ticks: int
    survivors: tuple[int, ...]
    events: tuple[str, ...]
    engine_version: str = ENGINE_VERSION


def combat_stats(base: Sequence[int], ivs: Sequence[int], level_x2: int,
                 multipliers: Mapping[str, float]) -> tuple[float, float, int]:
    canonical_hp = hp(base, ivs, level_x2, multipliers=multipliers)
    multiplier = cpm(level_x2, multipliers=multipliers)
    return ((base[0] + ivs[0]) * multiplier,
            (base[1] + ivs[1]) * multiplier, canonical_hp)


def defender_factor_x10(hours_held: int, heal_x10: int = 0) -> int:
    """D32 weakening (2.0x less 0.1x per full hour, 0-7) offset by D62b feeding, capped at 2.0x."""
    if type(hours_held) is not int or type(heal_x10) is not int or heal_x10 < 0:
        raise ValueError("hours_held and heal_x10 must be integers")
    return min(20, 20 - min(7, max(0, hours_held)) + heal_x10)


def defender_hp(canonical_hp: int, hours_held: int, heal_x10: int = 0) -> int:
    _positive(canonical_hp, "canonical_hp", integer=True)
    if type(hours_held) is not int:
        raise ValueError("hours_held must be integer full hours")
    return -(-canonical_hp * defender_factor_x10(hours_held, heal_x10) // 10)


def effectiveness(move_type: str, defender_types: Sequence[str], chart: Mapping) -> float:
    try:
        return math.prod(chart[move_type][t] for t in defender_types)
    except KeyError as exc:
        raise ValueError("unknown combatant or move type") from exc


def damage(power: float, attack: float, defense: float, stab: float, eff: float) -> int:
    if (isinstance(power, bool) or not isinstance(power, (int, float)) or
            not math.isfinite(power) or power < 0):
        raise ValueError("power must be finite and nonnegative")
    for value, label in ((attack, "attack"), (defense, "defense"),
                         (stab, "stab"), (eff, "effectiveness")):
        _positive(value, label)
    return math.floor(0.5 * power * attack / defense * stab * eff) + 1


def simulate(party: Sequence[Combatant], defender: Combatant, defender_battle_hp: int,
             *, rules: Mapping, chart: Mapping) -> Result:
    if not 1 <= len(party) <= 3:  # the engine fights 1..3; the gym service applies rules["party_max"]
        raise ValueError("party must contain one to three combatants")
    _positive(defender_battle_hp, "defender_battle_hp", integer=True)
    for user in (*party, defender):
        if not isinstance(user, Combatant):
            raise ValueError("participants must be Combatants")
        for move_type in (user.fast_type, user.charged_type):
            effectiveness(move_type, user.types, chart)

    health = [user.hp for user in party]
    defender_health = defender_battle_hp
    active = tick = 0
    energy = [0, 0]
    pending = [None, None]
    events = []

    def log(line):
        if len(events) < 39:
            events.append(line)

    log(f"0: {party[0].name} faces {defender.name}.")
    while True:
        users = (party[active], defender)
        for side in (0, 1):
            if pending[side] is None:
                move = "charged" if energy[side] >= rules["charged"]["energy_cost"] else "fast"
                if move == "charged":
                    energy[side] -= rules[move]["energy_cost"]
                pending[side] = (tick + rules[move]["ticks"], move)
        completion = min(action[0] for action in pending)
        if completion > rules["tick_limit"]:
            tick = rules["tick_limit"]
            outcome, reason = "draw", "tick_limit"
            break
        tick = completion
        hits = [0, 0]
        for side in (0, 1):
            if pending[side][0] != tick:
                continue
            move = pending[side][1]
            user, target = users[side], users[1 - side]
            move_type = user.charged_type if move == "charged" else user.fast_type
            hits[side] = damage(rules[move]["power"], user.attack, target.defense,
                                rules["stab"] if move_type in user.types else 1,
                                effectiveness(move_type, target.types, chart))
            if move == "fast":
                energy[side] = min(rules["energy_cap"], energy[side] + rules[move]["energy"])
            pending[side] = None
            log(f"{tick}: {user.name} {move} hits {target.name} for {hits[side]}.")
        health[active] = max(0, health[active] - hits[1])
        defender_health = max(0, defender_health - hits[0])
        if not health[active]:
            log(f"{tick}: {party[active].name} fainted.")
        if not defender_health:
            log(f"{tick}: {defender.name} fainted.")
            outcome = "win" if any(health) else "draw"
            reason = "defender_fainted"
            break
        if not any(health):
            outcome, reason = "loss", "party_fainted"
            break
        if not health[active]:
            active += 1
            energy[0] = 0
            pending[0] = None
            log(f"{tick}: {party[active].name} enters with 0 energy.")
        if tick == rules["tick_limit"]:
            outcome, reason = "draw", "tick_limit"
            break
    events.append(f"{tick}: {outcome} ({reason}).")
    return Result(outcome, reason, tick, tuple(i for i, value in enumerate(health) if value > 0),
                  tuple(events))
