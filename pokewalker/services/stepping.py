"""C2 message credit, meters and encounter requests in one writer transaction."""

from collections import OrderedDict
import random
import secrets
import time
from uuid import uuid4

from content.balance import limits, load_table
from pokewalker.db import with_receipt
from pokewalker.domain import encounters, steps
from pokewalker.services.items import active_lure, active_mirror, apply_finds, shiny_charm
from pokewalker.services.profiles import content_facts, get_profile, queue_size, restrictions
from pokewalker.services.storage import detail, identify


class DigestCache:
    """Bounded ephemeral per-profile LRU; cached entries never prove SQL commit."""

    def __init__(self):
        self.digest_key = secrets.token_bytes(32)
        self.profiles = OrderedDict()

    def entries(self, profile_id):
        records = self.profiles.setdefault(profile_id, OrderedDict())
        self.profiles.move_to_end(profile_id)
        if len(self.profiles) > 1024:
            self.profiles.popitem(last=False)
        return records

    def record(self, profile_id, message_id, at, digest):
        records = self.entries(profile_id)
        records[message_id] = (at, digest)
        # At most 120 credits fit the 30-minute window with a 15-second cooldown.
        while len(records) > 120:
            records.popitem(last=False)


_CACHE = DigestCache()
_RNG = random.SystemRandom()


class _History:
    def __init__(self, rows, cache, profile_id):
        self.rows = rows
        self.digest_key = cache.digest_key
        self.digests = cache.entries(profile_id)
        self.last_credit_at = max((row["created_at"] for row in rows), default=None)

    def accepted_words_since(self, since):
        return sum(row["accepted_words"] for row in self.rows if row["created_at"] > since)

    def seen_digest(self, digest, since):
        return any(self.digests.get(row["message_id"]) == (row["created_at"], digest)
                   for row in self.rows if row["created_at"] > since)


def advance_meter(current_c, awarded_c, threshold_c, frozen):
    if frozen:
        return current_c, 0
    triggers, remainder = divmod(current_c + awarded_c, threshold_c)
    return remainder, triggers


async def spawn_encounter(conn, profile, content, rng, at, channel_id=None, message_id=None):
    """Queue one wild encounter on the profile's route; callers check the queue has room."""
    pid = profile["profile_id"]
    version, pools = content_facts(content)
    chances, rules = load_table("tier_chances")["chances"], load_table("catch")["rules"]
    lure_id = await active_lure(conn, pid)
    mirror_id = None if lure_id is not None else await active_mirror(conn, pid)
    charm = await shiny_charm(conn, pid) == 'on'
    spec = None
    if mirror_id is not None and encounters.mirror_hit(rng, rules=rules):
        candidates = await companion_mirror_pools(conn, pid, content)
        if candidates:
            spec = encounters.generate_mirror(candidates, rng, chances=chances, rules=rules, charm=charm)
    if spec is None:
        spec = encounters.generate(pools, content["routes"][profile["route_id"]], lure_id is not None, rng,
                                   chances=chances, rules=rules, charm=charm)
    eid = str(uuid4())
    await conn.execute(
        "INSERT INTO encounters(encounter_id,profile_id,source_channel_id,source_message_id,"
        "pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,tier,route_id,lure_id,"
        "content_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, pid, channel_id, message_id, spec.pokemon_id, spec.level_x2, *spec.ivs,
         spec.gender or "genderless", spec.shiny, spec.tier, profile["route_id"], lure_id, version, at))
    if lure_id is not None or mirror_id is not None:
        await conn.execute('UPDATE active_effects SET remaining_encounters=remaining_encounters-1 '
                           'WHERE effect_id=?', (lure_id or mirror_id,))
    return eid


async def companion_mirror_pools(conn, profile_id, content):
    """Mirror candidates for the profile's current companion; empty without one."""
    async with conn.execute("SELECT companion_uid FROM profiles WHERE profile_id=?", (profile_id,)) as cursor:
        row = await cursor.fetchone()
    pokemon = await detail(conn, profile_id, row["companion_uid"]) if row and row["companion_uid"] else None
    if pokemon is None:
        return {}
    return encounters.mirror_pools(content["identities"], identify(content, pokemon)[0]["family_id"])


async def credit_message(conn, profile, words, created_at, message_id, channel_id, *,
                         content, rng=_RNG, cache=None):
    if not conn.in_transaction:
        raise RuntimeError("Message credit requires an active writer transaction")
    current = await get_profile(conn, profile["guild_id"], profile["user_id"])
    if current is None or current["profile_id"] != profile["profile_id"]:
        return None
    flags = await restrictions(conn, current["guild_id"], current["user_id"])
    if flags.excluded:
        return None
    if created_at is not None and (created_at.tzinfo is None or created_at.utcoffset() is None):
        raise ValueError("Message time must be timezone-aware")
    at = created_at.timestamp() if created_at is not None else time.time()
    pid, mid, cid = current["profile_id"], str(message_id), str(channel_id)
    async with conn.execute(
        "INSERT OR IGNORE INTO step_events VALUES (?,?,?,?,0,?,0,?,?)",
        (mid, pid, cid, len(words), len(words), "no_timestamp" if created_at is None else "paused", at)
    ) as cursor:
        if not cursor.rowcount:
            return None
    if created_at is None or flags.paused:
        return None
    cache = _CACHE if cache is None else cache
    rules = load_table("step_rules")["rules"]
    async with conn.execute(
        "SELECT message_id,created_at,accepted_words FROM step_events WHERE profile_id=? "
        "AND created_at>? AND created_at<=? AND accepted_words>0", (pid, at - 3600, at)
    ) as cursor:
        history = _History(await cursor.fetchall(), cache, pid)
    decision = steps.accept_message(words, at, history, rules)
    await conn.execute(
        "UPDATE step_events SET accepted_words=?,discarded_words=?,awarded_c=?,reason=? WHERE message_id=?",
        (decision.accepted_words, decision.discarded_words, decision.awarded_c, decision.reason, mid))
    size = await queue_size(conn, pid)
    meter = current["encounter_meter_c"]
    first, cap = None, limits()['encounter_queue']  # the 0015 queue triggers must match this value
    if size < cap:
        meter += decision.awarded_c
        if meter >= rules["encounter_step_hundredths"]:
            while meter >= rules["encounter_step_hundredths"] and size < cap:
                eid = await spawn_encounter(conn, current, content, rng, at, cid, mid)
                first = eid if first is None else first
                meter -= rules["encounter_step_hundredths"]
                size += 1
    companion, candy = advance_meter(current["companion_meter_c"], decision.awarded_c,
        rules["companion_candy_step_hundredths"], frozen=current["companion_uid"] is None)
    if candy:
        pokemon = await detail(conn, pid, current["companion_uid"])
        family = identify(content, pokemon)[0]["family_id"]

        async def grant(conn):
            await conn.execute("INSERT INTO candy VALUES (?,?,?) ON CONFLICT(profile_id,family_id) "
                               "DO UPDATE SET quantity=quantity+excluded.quantity", (pid, family, candy))
            return {"family_id": family, "candy": candy}, [{"profile_id": pid, "resource": "candy",
                "resource_id": str(family), "delta": candy, "reason": "companion_candy"}]

        await with_receipt(conn, f"companion:{mid}", "companion_candy", grant, profile_id=pid)
    find_meter = await apply_finds(conn, current, decision.awarded_c, at, mid, rng, content)
    await conn.execute("UPDATE profiles SET encounter_meter_c=?,companion_meter_c=?,find_meter_c=? WHERE profile_id=?",
                       (meter, companion, find_meter, pid))
    if first is not None:
        await conn.execute(
            "INSERT INTO reactions(message_id,profile_id,channel_id,desired,actual,created_at,encounter_id) "
            "VALUES (?,?,?,'add','none',?,?)", (mid, pid, cid, at, first))
    if decision.accepted_words:
        cache.record(pid, mid, at, decision.digest)
    return first
