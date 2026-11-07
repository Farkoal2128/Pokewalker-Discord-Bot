"""Offline M0.6 Monte Carlo; contracts/balance-tables.md defines inputs and estimates."""

import json
import math
from collections import Counter, deque
from itertools import combinations
from pathlib import Path

from content.balance import load_table
from pokewalker.domain.steps import accept_message
from scripts.measure_chat_rate import MemoryHistory

ROOT = Path(__file__).resolve().parents[2]
TIERS = dict(zip(("Common", "Uncommon", "Rare", "Evolved", "Legendary/Mythical"),
                 ("common", "uncommon", "rare", "evolved", "legendary")))


class Model:
    def __init__(self, artifact, balances, rng, style="continuous"):
        if style not in ("continuous", "hourly check"):
            raise ValueError("unknown play style")
        self.artifact, self.balances, self.rng, self.style = artifact, balances, rng, style
        self.rules, self.catch = balances["step_rules"]["rules"], balances["catch"]["rules"]
        self.limits, self.sim = balances["capacities"]["limits"], balances["simulation"]
        self.inventory, self.inbox, self.candy = Counter(), Counter(), Counter()
        self.balls_supplied, self.balls_spent, self.items_supplied = Counter(), Counter(), Counter()
        self.unmet_ball_demand, self.stockout_events = Counter(), 0
        self.dust = self.dust_in = self.candy_in = self.encounters = self.fled = self.checkins = 0
        self.encounter_meter = self.find_meter = self.companion_meter = self.accepted_words = 0
        self.max_queue = 0
        self.storage = 1
        self.fill_day = self.first_shiny_day = None
        self.find_times, self.queue, self.earned = deque(), deque(), set()
        self.favourite = next(i for i in artifact["identities"] if i["species_id"] == artifact["starters"][0])
        self.caught = {self.favourite["species_id"]}
        self.level_x2 = self.catch["starter_level"] * 2
        self.pools = {}
        chances = balances["tier_chances"]["chances"]
        for route_id in (r["id"] for r in balances["routes"]["routes"]):
            route = artifact["routes"][route_id]
            pool = {}
            for tier in chances:
                ids = [i for i in artifact["identities"] if TIERS[i["tier"]] == tier
                       and (tier == "legendary" or route["weights"][i["identity_id"]] > 0)]
                weights = [1 if tier == "legendary" else route["weights"][i["identity_id"]] for i in ids]
                if ids:
                    pool[tier] = (ids, weights, chances[tier])
            total = sum(v[2] for k, v in pool.items() if k != "legendary")
            if not total:
                raise ValueError("route has no ordinary tier")
            for tier, (ids, weights, chance) in list(pool.items()):
                pool[tier] = (ids, weights, chance if tier == "legendary" else chance * (sum(chances.values()) - chances["legendary"]) / total)
            self.pools[route_id] = pool
        self.route = next(iter(self.pools))
        for item, quantity in self.limits["starter_kit"].items():
            self.grant(item, quantity)
        self.minimum_inventory = min(self.inventory.values(), default=0)
        self.mint()
        self.award_milestones()

    def grant(self, item, quantity):
        if item == "stardust":
            self.dust += quantity
            self.dust_in += quantity
        elif item in self.limits["rare_pockets"] and self.inventory.get(item, 0) + quantity > self.limits["rare_pockets"][item]:
            self.grant("stardust", self.sim["rare_duplicate_stardust"])
        elif item not in self.limits["rare_pockets"] and self.bag_size() + quantity > self.limits["bag_units"]:
            self.grant("stardust", self.sim["overflow_stardust"])
        else:
            self.inventory[item] = self.inventory.get(item, 0) + quantity
            self.items_supplied[item] += quantity
            if item.endswith("_ball"):
                self.balls_supplied[item] += quantity

    def bag_size(self):
        return sum(n for item, n in self.inventory.items() if item not in self.limits["rare_pockets"])

    def pack(self, name):
        rows = self.balances[name]["rows"]
        row = self.rng.choices(rows, weights=[r["weight"] for r in rows])[0]
        self.grant(row["item"], row["quantity"])

    def mint(self):
        pool = self.pools[self.route]
        tier = self.rng.choices(list(pool), weights=[p[2] for p in pool.values()])[0]
        ids, weights, _ = pool[tier]
        self.queue.append({"identity": self.rng.choices(ids, weights=weights)[0],
                           "level": self.rng.randint(*self.catch["wild_level_range"]),
                           "shiny": self.rng.random() < self.catch["shiny_probability"]})
        self.encounters += 1
        self.max_queue = max(self.max_queue, len(self.queue))

    def credit_steps(self, amount, at):
        self.companion_meter += amount
        candy, self.companion_meter = divmod(self.companion_meter, self.rules["companion_candy_step_hundredths"])
        self.candy[self.favourite["family_id"]] += candy
        self.candy_in += candy
        while self.find_times and self.find_times[0] <= at - 3600:
            self.find_times.popleft()
        if len(self.find_times) < self.rules["finds_per_rolling_hour"]:
            self.find_meter += amount
            while self.find_meter >= self.rules["find_step_hundredths"]:
                self.find_meter -= self.rules["find_step_hundredths"]
                self.find_times.append(at)
                self.pack("find_table")
                if len(self.find_times) == self.rules["finds_per_rolling_hour"]:
                    self.find_meter = 0
                    break
        while amount:
            if len(self.queue) == self.limits["encounter_queue"] and self.style == "continuous":
                self.resolve(at)
            if len(self.queue) == self.limits["encounter_queue"]:
                break
            credit = min(amount, self.rules["encounter_step_hundredths"] - self.encounter_meter)
            self.encounter_meter += credit
            amount -= credit
            if self.encounter_meter == self.rules["encounter_step_hundredths"]:
                self.encounter_meter = 0
                self.mint()

    def flee_probability(self, encounter):
        return (self.catch["legendary_flee_probability"] if TIERS[encounter["identity"]["tier"]] == "legendary"
                else self.catch["shiny_flee_probability"] if encounter["shiny"] else self.catch["flee_probability"])

    def resolve(self, at):
        while self.queue and self.storage < self.limits["storage"]:
            encounter = self.queue[0]
            identity = encounter["identity"]
            tier = TIERS[identity["tier"]]
            ball = next((b for b in ("poke_ball", "great_ball", "ultra_ball", "master_ball")
                         if self.inventory.get(b, 0) > 0), None)
            if not encounter.get("started"):
                self.stockout_events += ball is None
                encounter["started"] = True
            if tier == "legendary" and self.inventory.get("master_ball", 0):
                ball = "master_ball"
            if ball is None:
                ball = "poke_ball"
                self.unmet_ball_demand[ball] += 1
            else:
                self.inventory[ball] -= 1
                self.balls_spent[ball] += 1
            berry = 1
            if tier in ("rare", "evolved", "legendary") and self.inventory.get("razz_berry", 0):
                self.inventory["razz_berry"] -= 1
                berry = self.catch["berry_multipliers"]["razz_berry"]
            self.minimum_inventory = min([self.minimum_inventory, *self.inventory.values()])
            base = min(1, self.catch["base_catch_rates"][tier] / (2 * self.balances["cpm"]["multipliers"][str(encounter["level"] * 2)]))
            probability = 1 if ball == "master_ball" else 1 - (1 - base) ** (self.catch["ball_multipliers"][ball] * berry)
            if self.rng.random() < probability:
                self.queue.popleft()
                self.storage += 1
                self.caught.add(identity["species_id"])
                self.candy[identity["family_id"]] += identity["catch_candy"]
                self.candy_in += identity["catch_candy"]
                self.grant("stardust", identity["catch_stardust"])
                if encounter["shiny"] and self.first_shiny_day is None:
                    self.first_shiny_day = at / 86400 + 1
                if self.storage == self.limits["storage"]:
                    self.fill_day = at / 86400 + 1
                self.award_milestones()
            elif self.rng.random() < self.flee_probability(encounter):
                self.queue.popleft()
                self.fled += 1
            self.claim()
        self.powerup()

    def award_milestones(self):
        table = self.artifact["milestones"]
        candidates = []
        for category in ("pokedex", "starter_trios", "regions", "legendary_groups", "mythical_sets", "ultra_beast_first_catches", "extra_bundle_lines"):
            for n, row in enumerate(table[category]):
                complete = len(self.caught) >= math.ceil(len(self.artifact["species"]) * row["percent"] / 100) if category == "pokedex" else set(row.get("species_ids", [row.get("species_id")])) <= self.caught
                candidates.append((f"{category}:{n}", complete, row["bundle"]))
        for key in ("all_starters", "all_legendaries", "all_mythicals", "first_legendary", "first_mythical"):
            row = table[key]
            complete = (any(self.artifact["species"][str(s)]["is_legendary" if key == "first_legendary" else "is_mythical"] for s in self.caught)
                        if key.startswith("first_") else set(row["species_ids"]) <= self.caught)
            candidates.append((key, complete, row["bundle"]))
        for key, complete, bundle in candidates:
            if complete and key not in self.earned:
                self.earned.add(key)
                self.inbox.update(table["bundles"][bundle])
        for line in table["evolution_lines"]["families"]:
            key = f"evolution_line:{line['family_id']}"
            if set(line["species_ids"]) <= self.caught and key not in self.earned:
                self.earned.add(key)
                self.candy[line["family_id"]] += line["family_candy"]
                self.candy_in += line["family_candy"]
                self.inbox.update({"ultra_ball": line["ultra_ball"], "stardust": line["stardust"]})
        self.claim()

    def claim(self):
        for item, quantity in list(self.inbox.items()):
            room = quantity if item == "stardust" else self.limits["rare_pockets"].get(item, self.limits["bag_units"]) - (self.inventory.get(item, 0) if item in self.limits["rare_pockets"] else self.bag_size())
            count = min(quantity, max(0, room))
            if count:
                self.grant(item, count)
                self.inbox[item] -= count
        self.inbox += Counter()

    def powerup(self):
        prices = self.balances["powerup_prices"]
        while self.level_x2 < prices["cap_level_x2"]:
            band = next(b for b in prices["bands"] if b["min_level_x2"] <= self.level_x2 < b["max_level_x2_exclusive"])
            if self.candy[self.favourite["family_id"]] < band["candy"] or self.dust < band["stardust"]:
                break
            self.candy[self.favourite["family_id"]] -= band["candy"]
            self.dust -= band["stardust"]
            self.level_x2 += 1


def group_expectation(identities, species_ids, probability):
    counts = Counter(i["species_id"] for i in identities)
    rates = [probability * counts[s] / len(identities) for s in species_ids] if identities else []
    if not rates or not all(rates):
        return None
    return sum((-1) ** (n + 1) / sum(subset) for n in range(1, len(rates) + 1) for subset in combinations(rates, n))


def run_scenario(rng, *, active_hours=1, days=30, profile="regular", measured_path=None,
                 artifact=None, balances=None, style="continuous"):
    if type(days) is not int or days <= 0 or type(active_hours) is not int or not 1 <= active_hours <= 24:
        raise ValueError("positive days and 1..24 active hours required")
    if type(profile) not in (str, dict):
        raise ValueError("invalid chat profile")
    artifact = artifact if artifact is not None else json.loads((ROOT / "content/artifact/content.json").read_text(encoding="utf-8"))
    balances = balances if balances is not None else {p.stem: load_table(p.stem) for p in (ROOT / "content/balance").glob("*.json")}
    rules = balances["step_rules"]["rules"]
    source, measured = f"fallback {profile}: daily message counts, characters/5 word estimate", None
    if profile == "measured":
        path = Path(measured_path) if measured_path is not None else ROOT / "docs/features/pokewalker-bot/measurements/chat-rate-summary.md"
        if path.exists():
            rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("| Accepted words |")]
            measured = [float(v.strip()) for v in rows[0].split("|")[2:5]] if len(rows) == 1 else []
            if len(measured) != 3 or any(not math.isfinite(v) or v < 0 or v > 60 * rules["accepted_words_per_rolling_minute"] for v in measured):
                raise ValueError("invalid measured percentiles")
            measured = [round(v) for v in measured]
            if any(0 < v < rules["min_message_words"] for v in measured):
                raise ValueError("measured total cannot be reconstructed from an eligible message")
            source = "measured percentiles"
        else:
            profile, source = "regular", "fallback regular: measured summary absent; daily messages, characters/5 word estimate"
    settings = profile if isinstance(profile, dict) else balances["simulation"]["fallback_profiles"].get(profile)
    if measured is None and (not isinstance(settings, dict) or set(settings) not in ({"messages_per_hour", "words_per_message"}, {"messages_per_day", "words_per_message"})
                             or type(settings["words_per_message"]) is not int or settings["words_per_message"] <= 0
                             or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in settings.values())):
        raise ValueError("invalid chat profile")
    model = Model(artifact, balances, rng, style)
    history = MemoryHistory()
    checkin_elapsed = 0
    for day in range(days):
        events = []
        for hour in range(active_hours):
            target = rng.choice(measured) if measured is not None else None
            words = rules["accepted_words_per_rolling_minute"] // math.ceil(rules["accepted_words_per_rolling_minute"] / rules["max_message_words"]) if measured is not None else settings["words_per_message"]
            count = (math.ceil(target / words) if measured is not None else round(settings["messages_per_hour"]) if "messages_per_hour" in settings else round((hour + 1) * settings["messages_per_day"] / active_hours) - round(hour * settings["messages_per_day"] / active_hours))
            events.extend((hour * 3600 + (i + .5) * 3600 / count, round((i + 1) * target / count) - round(i * target / count) if target is not None else words) for i in range(count))
        for hour in range(active_hours):
            model.route = list(model.pools)[(day * active_hours + hour) % len(model.pools)]
            for n, (offset, words) in enumerate(events):
                if hour * 3600 <= offset < (hour + 1) * 3600:
                    at = day * 86400 + offset
                    history.prune(at)
                    decision = accept_message([f"word{day}_{n}_{i}" for i in range(words)], at, history, model.rules)
                    history.record(at, decision)
                    model.accepted_words += decision.accepted_words
                    model.credit_steps(decision.awarded_c, at)
            at = day * 86400 + (hour + 1) * 3600
            checkin_elapsed += 3600
            while checkin_elapsed >= model.sim["checkin_seconds"]:
                for item, quantity in model.sim["checkin_guaranteed"].items():
                    model.grant(item, quantity)
                model.pack("checkin_table")
                model.checkins += 1
                checkin_elapsed -= model.sim["checkin_seconds"]
            model.resolve(at)
    costs = {str(level): {key: sum(b[key] * max(0, min(level * 2, b["max_level_x2_exclusive"]) - max(model.catch["starter_level"] * 2, b["min_level_x2"])) for b in balances["powerup_prices"]["bands"]) for key in ("candy", "stardust")} for level in (30, 40)}
    legendary = [i for i in artifact["identities"] if TIERS[i["tier"]] == "legendary"]
    probability = balances["tier_chances"]["chances"]["legendary"] / sum(balances["tier_chances"]["chances"].values())
    pacing = {i["identity_id"]: len(legendary) / probability for i in legendary}
    groups = {r["id"]: group_expectation(legendary, r["species_ids"], probability) for r in artifact["milestones"]["legendary_groups"]}
    daily = model.encounters / days
    shiny = model.catch["shiny_probability"]
    values = {k: v.get("stardust", 0) + sum(q * balances["conversion_rates"]["stardust_per_unit"].get(i, 0) for i, q in v.items() if i != "stardust") for k, v in artifact["milestones"]["bundles"].items()}
    favourite_spent = sum(b["candy"] * max(0, min(model.level_x2, b["max_level_x2_exclusive"]) - max(model.catch["starter_level"] * 2, b["min_level_x2"])) for b in balances["powerup_prices"]["bands"])
    income = model.dust_in + sum(q * balances["conversion_rates"]["stardust_per_unit"][i] for i, q in model.items_supplied.items())
    gym = balances["gym_income_table"]
    gym_hours = gym["tenure_seconds"] // 3600
    gym_items = {r["item"]: gym_hours * r["weight"] * r["quantity"] / sum(row["weight"] for row in gym["rows"]) for r in gym["rows"]}
    gym_balls = sum(quantity for item, quantity in gym_items.items() if item.endswith("_ball"))
    demand = sum(model.balls_spent.values()) + sum(model.unmet_ball_demand.values())
    return {"active_hours": active_hours, "days": days, "style": style, "profile_source": source,
            "assumptions": "routes cycle each active hour; no transfers/evolution, lure or Pinap use; starter favourite",
            "encounters": model.encounters, "encounters_per_active_hour": model.encounters / (days * active_hours),
            "accepted_words": model.accepted_words, "max_queue": model.max_queue, "checkins": model.checkins,
            "balls_supplied": dict(model.balls_supplied), "balls_spent": dict(model.balls_spent), "inventory": dict(model.inventory),
            "unmet_ball_demand": dict(model.unmet_ball_demand), "stockout_events": model.stockout_events,
            "ball_demand": demand, "deficit": max(0, demand - sum(model.balls_supplied.values())),
            "minimum_inventory": model.minimum_inventory,
            "gym_income": {"items_per_deployment": gym_items, "balls_per_deployment": gym_balls,
                           "balls_one_deployment_daily": gym_balls * days,
                           "balls_all_day": gym_balls * days * 86400 / gym["tenure_seconds"]},
            "minimum_balance": min([model.dust, *model.inventory.values(), *model.candy.values()]),
            "candy_in": model.candy_in, "favourite_candy_balance": model.candy[model.favourite["family_id"]],
            "favourite_candy_in": model.candy[model.favourite["family_id"]] + favourite_spent,
            "stardust_in": model.dust_in, "stardust_balance": model.dust, "favourite_level": model.level_x2 / 2,
            "powerup_costs": costs, "storage_fill_day": model.fill_day, "observed_first_shiny_day": model.first_shiny_day,
            "days_to_first_shiny": {"mean": 1 / (shiny * daily), "median": math.ceil(math.log(.5) / math.log1p(-shiny)) / daily, "method": "geometric expectation from generated encounter pace"},
            "bundle_value_vs_income": {k: {"stardust_equivalent": v, "month_stardust_income": model.dust_in * 30 / days, "month_income_stardust_equivalent": income * 30 / days} for k, v in values.items()},
            "legendary_expected_encounters": {"identities": pacing, "groups": groups},
            "route_tier_pool_sizes": {r: {t: len(p[0]) for t, p in pools.items()} for r, pools in model.pools.items()}}
