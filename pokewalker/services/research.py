"""Atomic research disposition inside the caller's writer transaction."""

import json
from uuid import uuid4

from pokewalker.db import with_receipt
from pokewalker.services import forms, profiles, storage


def rare(identity):
    """Legendary, Mythical or D73 Eternal: never auto-researched, single send needs the unlock."""
    return identity["is_legendary"] or identity["is_mythical"] or identity.get("tier") == "Eternal"


def protected_reason(identity, pokemon, profile, arena_team=frozenset()):
    for reason, protected in (("in_arena", pokemon["pokemon_uid"] in arena_team),
                              ("deployed", pokemon.get("gym_deployment_id") is not None),
                              ("favorite", pokemon["favorite"]),
                              ("companion", pokemon["pokemon_uid"] == profile["companion_uid"]),
                              ("shiny", pokemon["shiny"]),
                              ("legendary_or_mythical", rare(identity))):
        if protected:
            return reason
    return None


async def candidates(conn, profile_id, content, offset, now, sort="newest", multipliers=None):
    async with conn.execute("SELECT * FROM profiles WHERE profile_id=?", (profile_id,)) as cursor:
        profile = await cursor.fetchone()
    arena_team = await profiles.arena_team(conn, profile_id, now)
    total = await storage.owned_count(conn, profile_id)
    pokemon = await storage.ordered(conn, "profile_id=? AND state='owned'", (profile_id,), offset, 5,
                                    sort, content, multipliers)
    rows = []
    for item in pokemon:
        identity, sprite = storage.identify(content, item)
        rows.append({"pokemon": item, "identity": identity, "sprite": sprite,
                     "reason": protected_reason(identity, item, profile, arena_team)})
    return rows, total


async def _checked(conn, session, picks, preview, now):
    """Shared send checks: (profile, saved selection, receipt key) or (None, result to return, None)."""
    if not conn.in_transaction:
        raise RuntimeError("Research requires an active writer transaction")
    changed = {"status": "changed"}
    profile = await profiles.get_profile(conn, session["guild_id"], session["user_id"])
    if (profile is None or profile["profile_id"] != session["profile_id"]
            or (await profiles.restrictions(conn, session["guild_id"], session["user_id"])).excluded):
        return None, changed, None
    saved = json.loads(session["selection"])
    if (not preview or saved.get("preview") != preview or saved.get("picks") != picks
            or not 1 <= len(picks) <= 20 or len({pick[0] for pick in picks}) != len(picks)):
        return None, changed, None
    key = f"research:{preview['id']}"
    async with conn.execute("SELECT profile_id,result FROM action_receipts WHERE key=? AND action='research'", (key,)) as cursor:
        receipt = await cursor.fetchone()
    if receipt is not None:
        return None, json.loads(receipt["result"]) if receipt["profile_id"] == profile["profile_id"] else changed, None
    if preview["expires_at"] <= now:
        return None, changed, None
    return profile, saved, key


async def send(conn, session, picks, preview, now, content):
    profile, saved, key = await _checked(conn, session, picks, preview, now)
    if profile is None:
        return saved
    changed = {"status": "changed"}
    rows = []
    arena_team = await profiles.arena_team(conn, profile["profile_id"], now)
    for uid, revision in picks:
        pokemon = await storage.detail(conn, profile["profile_id"], uid)
        if pokemon is None or pokemon["revision"] != revision:
            return changed
        if await forms.fusion_of(conn, uid) is not None:  # D72: a fused Pokemon holds its partner
            return changed
        identity, _ = storage.identify(content, pokemon)
        reason = protected_reason(identity, pokemon, profile, arena_team)
        if reason is not None and not (len(picks) == 1 and saved.get("single")
                                       and preview.get("unlocked") and reason in ("shiny", "legendary_or_mythical")):
            return changed
        rows.append((pokemon, identity))

    async def compute(conn):
        lines, candy = [], {}
        for pokemon, identity in rows:
            await conn.execute("UPDATE pokemon SET state='sent',revision=revision+1 WHERE pokemon_uid=?", (pokemon["pokemon_uid"],))
            family = identity["family_id"]
            await conn.execute("INSERT INTO candy VALUES (?,?,1) ON CONFLICT(profile_id,family_id) "
                               "DO UPDATE SET quantity=quantity+1", (profile["profile_id"], family))
            candy[str(family)] = candy.get(str(family), 0) + 1
            lines.append({"profile_id": profile["profile_id"], "resource": "candy", "resource_id": str(family),
                          "delta": 1, "reason": "research_send"})
        return {"status": "sent", "count": len(rows), "candy": candy, "stardust": 0}, lines

    return await with_receipt(conn, key, "research", compute, profile_id=profile["profile_id"])


async def send_pending(conn, profile_id, encounter, key, content):
    if not conn.in_transaction:
        raise RuntimeError("Research requires an active writer transaction")
    identity, _ = storage.identify(content, encounter)

    async def compute(conn):
        await conn.execute("INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                           "iv_stamina,gender,shiny,origin,source_encounter_id,content_version,caught_at,state,revision,"
                           "look_id) "
                           "SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,"
                           "'catch',encounter_id,content_version,resolved_at,'sent',1,look_id FROM encounters "
                           "WHERE encounter_id=?", (str(uuid4()), encounter["encounter_id"]))
        await forms.unlock(conn, profile_id, dict(encounter).get("look_id"), encounter["resolved_at"])
        family = identity["family_id"]
        await conn.execute("INSERT INTO candy VALUES (?,?,1) ON CONFLICT(profile_id,family_id) "
                           "DO UPDATE SET quantity=quantity+1", (profile_id, family))
        lines = [{"profile_id": profile_id, "resource": "candy", "resource_id": str(family),
                  "delta": 1, "reason": "research_send"}]
        return {"status": "sent", "count": 1, "candy": {str(family): 1}, "stardust": 0}, lines

    return await with_receipt(conn, key, "research", compute, profile_id=profile_id)


async def auto_send(conn, now, content):
    # D74: `resolved_at<=?-900` lets this use the partial encounters_unclaimed index.
    async with conn.execute("SELECT encounters.*,profiles.guild_id,profiles.user_id FROM encounters "
                            "JOIN profiles ON profiles.profile_id=encounters.profile_id "
                            "WHERE encounters.state='caught' AND acknowledged_at IS NULL AND shiny=0 "
                            "AND resolved_at<=?-900 AND NOT EXISTS "
                            "(SELECT 1 FROM pokemon WHERE source_encounter_id=encounters.encounter_id)", (now,)) as cursor:
        rows = await cursor.fetchall()
    count = 0
    for row in rows:
        if (await profiles.restrictions(conn, row["guild_id"], row["user_id"])).excluded:
            continue
        identity, _ = storage.identify(content, row)
        if rare(identity):
            continue
        result = await send_pending(conn, row["profile_id"], row, f"research:auto:{row['encounter_id']}", content)
        if result["status"] == "sent":
            await conn.execute("UPDATE encounters SET acknowledged_at=? WHERE encounter_id=? AND acknowledged_at IS NULL",
                               (now, row["encounter_id"]))
            count += 1
    return count


async def send_pending_reviewed(conn, session, picks, preview, now, content):
    profile, saved, key = await _checked(conn, session, picks, preview, now)
    if profile is None:
        return saved
    changed = {"status": "changed"}
    if len(picks) != 1 or not picks[0][0].startswith("pending:"):
        return changed
    async with conn.execute("SELECT * FROM encounters WHERE encounter_id=? AND profile_id=? AND state='caught' "
                            "AND acknowledged_at IS NULL AND NOT EXISTS "
                            "(SELECT 1 FROM pokemon WHERE source_encounter_id=encounters.encounter_id)",
                            (picks[0][0][8:], profile["profile_id"])) as cursor:
        encounter = await cursor.fetchone()
    if encounter is None or picks != [[f"pending:{encounter['encounter_id']}", encounter["revision"]]]:
        return changed
    identity, _ = storage.identify(content, encounter)
    if ((encounter["shiny"] or rare(identity))
            and not (saved.get("single") and preview.get("unlocked"))):
        return changed
    return await send_pending(conn, profile["profile_id"], encounter, key, content)
