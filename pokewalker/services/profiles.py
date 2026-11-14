"""M1.4 profile queries and atomic enrollment on a writer-owned connection.

Queries return detached dicts or None. Enrollment requires an active writer job;
the receipt, starter kit and first frozen encounter commit together. ``content``
is the verified artifact dict. Its canonical JSON SHA256 identifies frozen rolls.
``now`` is an aware datetime. Restrictions use the current UTC clock on each read.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import time
from uuid import uuid4

from content.balance import limits, load_table
from pokewalker.db import with_receipt
from pokewalker.domain import encounters
from pokewalker.services.deletion import opted_out


@dataclass(frozen=True)
class Restrictions:
    paused: bool = False
    paused_until: datetime | None = None
    excluded: bool = False
    share_banned: bool = False


_FACTS = (None, None, None)


def content_facts(content):
    """(version hash, tier pools) of a content artifact, kept for the last one seen.

    Content is immutable while loaded; one slot avoids rehashing 1.3 MB per encounter.
    """
    global _FACTS
    if _FACTS[0] is not content:
        pools = defaultdict(list)
        for identity in content["identities"]:
            pools[identity["tier"]].append(identity)
        version = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"))
                                 .encode()).hexdigest()
        _FACTS = (content, version, pools)
    return _FACTS[1], _FACTS[2]


def _clear_facts():
    global _FACTS
    _FACTS = (None, None, None)


content_facts.cache_clear = _clear_facts


async def get_profile(conn, guild_id, user_id):
    async with conn.execute("SELECT * FROM profiles WHERE guild_id=? AND user_id=?",
                            (str(guild_id), str(user_id))) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row is not None else None


async def lifetime_steps_c(conn, profile_id) -> int:
    """Lifetime awarded hundredths for one server-scoped profile, including zero awards."""
    async with conn.execute("SELECT coalesce(sum(awarded_c),0) FROM step_events WHERE profile_id=?",
                            (profile_id,)) as cursor:
        return (await cursor.fetchone())[0]


async def restrictions(conn, guild_id, user_id):
    async with conn.execute("SELECT * FROM restrictions WHERE guild_id=? AND user_id=?",
                            (str(guild_id), str(user_id))) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return Restrictions()
    until = row["paused_until"]
    return Restrictions(bool(row["paused"] and (until is None or until > time.time())),
                        datetime.fromtimestamp(until, timezone.utc) if until is not None else None,
                        bool(row["excluded"]), bool(row["share_banned"]))


async def session_owner(conn, session):
    """(profile, None) while the saved session still names this unexcluded member, else (None, refusal)."""
    profile = await get_profile(conn, session['guild_id'], session['user_id'])
    async with conn.execute('SELECT profile_id,guild_id,user_id FROM sessions WHERE session_id=?',
                            (session['session_id'],)) as cursor:
        saved = await cursor.fetchone()
    if (profile is None or profile['profile_id'] != session['profile_id'] or saved is None
            or any(str(saved[key]) != str(session[key]) for key in ('profile_id', 'guild_id', 'user_id'))):
        return None, {'status': 'stale'}
    if (await restrictions(conn, session['guild_id'], session['user_id'])).excluded:
        return None, {'status': 'excluded'}
    return profile, None


async def queue_size(conn, profile_id):
    async with conn.execute("SELECT count(*) FROM encounters WHERE profile_id=? "
                            "AND state IN ('queued','revealed') AND raid_spawn_id IS NULL", (profile_id,)) as cursor:
        return (await cursor.fetchone())[0]


async def arena_team(conn, profile_id, now):
    """Return this profile's live Arena team UIDs; expiry needs no write or timer."""
    async with conn.execute("SELECT team FROM arena_runs WHERE profile_id=? AND ended_at IS NULL "
                            "AND started_at>?", (profile_id, now - load_table('arena')['rules']['run_seconds'])) as cursor:
        row = await cursor.fetchone()
    return frozenset(member['uid'] for member in json.loads(row['team'])) if row else frozenset()


async def channel_policy(conn, guild_id, channel_id, parent_id=None):
    async with conn.execute("SELECT * FROM guild_channels WHERE guild_id=? AND channel_id=?",
                            (str(guild_id), str(parent_id if parent_id is not None else channel_id))) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row is not None else None


async def enroll(conn, guild_id, user_id, starter_species_id, content, rng, now):
    if not conn.in_transaction:
        raise RuntimeError("Enrollment requires an active writer transaction")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Enrollment time must be timezone-aware")
    if (await restrictions(conn, guild_id, user_id)).excluded:
        raise ValueError("Member is excluded")
    if await opted_out(conn, str(guild_id), str(user_id)):
        raise ValueError("Run /walker-account opt-in first")

    async def compute(conn):
        if await get_profile(conn, guild_id, user_id) is not None:
            raise ValueError("Profile already exists")
        if len(content["starters"]) != 27:
            raise ValueError("Content must have 27 starters")
        if starter_species_id not in content["starters"]:
            raise ValueError("Species is not a starter")
        identity = next(i for i in content["identities"]
                        if i["species_id"] == starter_species_id and i["kind"] == "default")
        version, pools = content_facts(content)
        rules = load_table("catch")["rules"]
        level, ivs = encounters.starter_rolls(rng, rules=rules)
        gender, variety = encounters.roll_gender(identity, rng)
        profile_id, pokemon_uid = str(uuid4()), str(uuid4())
        timestamp = now.timestamp()
        await conn.execute("INSERT OR IGNORE INTO guilds(guild_id,created_at) VALUES (?,?)",
                           (str(guild_id), timestamp))
        await conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES (?,?,?,?)",
                           (profile_id, str(guild_id), str(user_id), timestamp))
        await conn.execute(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
            "gender,shiny,origin,favorite,content_version,caught_at) VALUES (?,?,?,?,?,?,?,?,0,'starter',1,?,?)",
            (pokemon_uid, profile_id, variety["pokemon_id"], level, *ivs, gender or "genderless", version, timestamp))
        await conn.execute("UPDATE profiles SET companion_uid=? WHERE profile_id=?", (pokemon_uid, profile_id))
        kit = limits()["starter_kit"]
        await conn.executemany("INSERT INTO inventory VALUES (?,?,?)",
                               [(profile_id, item, quantity) for item, quantity in kit.items()])
        await conn.execute("INSERT INTO pokedex VALUES (?,?,?,?)",
                           (profile_id, variety["pokemon_id"], timestamp, timestamp))
        encounter = encounters.generate(pools, content["routes"]["refreshing_field"], False, rng,
                                        chances=load_table("tier_chances")["chances"], rules=rules)
        await conn.execute(
            "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
            "gender,shiny,tier,route_id,content_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid4()), profile_id, encounter.pokemon_id, encounter.level_x2, *encounter.ivs,
             encounter.gender or "genderless", encounter.shiny, encounter.tier, "refreshing_field", version, timestamp))
        return await get_profile(conn, guild_id, user_id), [
            {"profile_id": profile_id, "resource": "item", "resource_id": item,
             "delta": quantity, "reason": "starter_kit"} for item, quantity in kit.items()]

    result = await with_receipt(conn, f"enroll:{guild_id}:{user_id}", "enroll", compute)
    await conn.execute("UPDATE action_receipts SET profile_id=? WHERE key=?",
                       (result["profile_id"], f"enroll:{guild_id}:{user_id}"))
    return result
