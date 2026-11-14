"""Pure Arena rules from AR-14a, AR-16..24 and AR-32..33.

Callers inject reviewed arena.json rules, catalog identities and an RNG. Floors
are positive integers; slots 0/1/2 mean entry/middle/boss. Rolls choose an identity
before rolling Attack/Defense/Stamina IVs. No table loading, clock or global RNG.
Enemy dictionaries retain the chosen identity; callers own snapshots/persistence.
"""

from fractions import Fraction


def _positive_integer(value, label):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")


def _slot_name(slot):
    if type(slot) is not int or not 0 <= slot <= 2:
        raise ValueError("slot must be 0, 1 or 2")
    return ("entry", "middle", "boss")[slot]


def level_x2(floor, rules):
    _positive_integer(floor, "floor")
    return 2 * min(floor, rules["level_cap"])


def late_steps(floor, rules):
    _positive_integer(floor, "floor")
    late = rules["late"]
    return min(late["iv_steps_max"], max(0, (floor - late["after_floor"]) // late["step_floors"]))


def iv_bounds(slot, floor, rules):
    low, high = rules["iv_ranges"][_slot_name(slot)]
    steps = late_steps(floor, rules)
    return tuple((min(high, low + (steps + 2 - i) // 3), high) for i in range(3))


def roll_ivs(slot, floor, rng, rules):
    return tuple(rng.randint(low, high) for low, high in iv_bounds(slot, floor, rules))


def hp_factor_x10(floor, rules):
    _positive_integer(floor, "floor")
    late = rules["late"]
    if floor > late["uncapped_after_floor"]:
        return late["hp_cap_x10"] + (floor - late["uncapped_after_floor"]) * late["uncapped_step_x10"]
    return 10 + min(late["hp_cap_x10"] - 10, late_steps(floor, rules) * late["hp_step_x10"])


def enemy_hp(canonical_hp, factor_x10):
    _positive_integer(canonical_hp, "canonical_hp")
    _positive_integer(factor_x10, "factor_x10")
    return -(-canonical_hp * factor_x10 // 10)


def bst_cap(floor, rules):
    _positive_integer(floor, "floor")
    bst = rules["bst"]
    if floor >= bst["full_floor"]:
        return bst["full"]
    return round(bst["base"] + bst["span"] * (floor - 1) / bst["span_floors"])


def boss_cap(floor, rules):
    cap = bst_cap(floor, rules)
    bst = rules["bst"]
    percent = bst["decade_boss_pct"] if floor % 10 == 0 else bst["boss_pct"]
    return min(bst["full"], cap * percent // 100)


def is_special(identity, rules):
    special = rules["special"]
    return (identity["is_legendary"] or identity["is_mythical"] or
            identity["species_id"] in special["ultra_beast_species"] or
            identity["species_id"] in special["paradox_species"])


def pick_identity(floor, slot, identities, rng, rules):
    _slot_name(slot)
    cap = boss_cap(floor, rules) if slot == 2 else bst_cap(floor, rules)
    eligible = [identity for identity in identities if identity["bst"] <= cap]
    if slot == 2:
        key = "decade_boss_chance_pct" if floor % 10 == 0 else "boss_chance_pct"
        if rng.randrange(100) < rules["special"][key]:
            special = [identity for identity in eligible if is_special(identity, rules)]
            if special:
                return rng.choice(special)
    regular = [identity for identity in eligible if not is_special(identity, rules)]
    if not regular:
        raise ValueError("no eligible regular Arena identities")
    return rng.choice(regular)


def roll_enemy(floor, slot, identities, rng, rules):
    identity = pick_identity(floor, slot, identities, rng, rules)
    return {"identity": identity, "level_x2": level_x2(floor, rules),
            "ivs": roll_ivs(slot, floor, rng, rules),
            "factor_x10": hp_factor_x10(floor, rules), "special": is_special(identity, rules)}


def ticket_for(floor, rules):
    _positive_integer(floor, "floor")
    for tier, schedule in rules["tickets"]["schedule"].items():
        if "floors" in schedule:
            due = floor in schedule["floors"]
        else:
            due = floor >= schedule["from"] and (floor - schedule["from"]) % schedule["every"] == 0
        if due:
            return tier
    return None


def max_skip(best_floor, rules):
    return min(best_floor // rules['skip']['divisor'], rules['skip']['max'])


def skip_tickets(skip, rules):
    tickets = {}
    for floor in range(1, skip + 1):
        tier = ticket_for(floor, rules)
        if tier is not None:
            tickets[tier] = tickets.get(tier, 0) + 1
    return tickets


def hurt(health, pct):
    return next((i for i, (hp, full_hp) in enumerate(health) if hp * 100 < pct * full_hp), None)


def hp_order(health):
    return sorted(range(len(health)), key=lambda i: Fraction(*health[i]), reverse=True)


def first_clear_bonus(floor, best_floor, rules):
    if type(best_floor) is not int or best_floor < 0:
        raise ValueError("best_floor must be a nonnegative integer")
    tier = ticket_for(floor, rules)
    return floor > best_floor and tier in rules["tickets"]["first_clear_tiers"]


def candy_for(special, slot, rules):
    _slot_name(slot)
    candy = rules["candy"]
    return 0 if special and slot != 2 and candy["special_boss_only"] else candy["per_knockout"]


def revive(party_hp):
    return [max(1, hp) for hp in party_hp]
