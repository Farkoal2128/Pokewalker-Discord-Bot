"""C3 atomic catching; call only inside a transaction owned by Writer."""

from dataclasses import dataclass
import json
from types import MappingProxyType

from content.balance import load_table
from pokewalker.db import with_receipt
from pokewalker.domain.cp import catch_probability, flees_after_failure
from pokewalker.services.profiles import restrictions
from pokewalker.services.milestones import check_and_award
from pokewalker.services.items import boost
from pokewalker.services.storage import owned_count


@dataclass(frozen=True)
class CatchResult:
    status: str
    encounter: MappingProxyType
    pokemon: MappingProxyType | None = None
    candy: int = 0
    stardust: int = 0


def _freeze(saved):
    return CatchResult(saved["status"], MappingProxyType(saved["encounter"]),
                       MappingProxyType(saved["pokemon"]) if saved.get("pokemon") else None,
                       saved.get("candy", 0), saved.get("stardust", 0))


async def current_result(conn, encounter):
    """Detached persisted outcome for authorized service/renderer callers."""
    pokemon, candy, stardust = None, 0, 0
    if encounter["state"] == "caught":
        async with conn.execute("SELECT * FROM pokemon WHERE source_encounter_id=?",
                                (encounter["encounter_id"],)) as cursor:
            row = await cursor.fetchone()
            pokemon = dict(row) if row is not None else None
        async with conn.execute("SELECT result FROM action_receipts JOIN catch_attempts "
                                "ON key=receipt_key WHERE encounter_id=? ORDER BY ordinal DESC LIMIT 1",
                                (encounter["encounter_id"],)) as cursor:
            row = await cursor.fetchone()
        if row is not None:
            saved = json.loads(row["result"])
            candy, stardust = saved["candy"], saved["stardust"]
    return {"status": encounter["state"], "encounter": encounter, "pokemon": pokemon,
            "candy": candy, "stardust": stardust}


async def throw(conn, encounter_id, session, expected_revision, rng, now, *, content, guaranteed=False):
    if not conn.in_transaction:
        raise RuntimeError("Catching requires an active writer transaction")
    async with conn.execute("SELECT * FROM encounters WHERE encounter_id=?", (encounter_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None or row["profile_id"] != session["profile_id"]:
        raise ValueError("Encounter owner does not match session")
    async with conn.execute("SELECT guild_id,user_id,storage_limit FROM profiles WHERE profile_id=?",
                            (session["profile_id"],)) as cursor:
        owner = await cursor.fetchone()
    if (owner is None or owner["guild_id"] != str(session["guild_id"])
            or owner["user_id"] != str(session["user_id"])):
        raise ValueError("Profile owner does not match session")
    encounter = dict(row)
    current = await current_result(conn, encounter)
    if (await restrictions(conn, session["guild_id"], session["user_id"])).excluded:
        return _freeze({**current, "status": "excluded"})
    if encounter["state"] != "revealed" or encounter["revision"] != expected_revision:
        return _freeze(current)
    if encounter["raid_spawn_id"] is not None and await conn.execute_fetchall(
            "SELECT 1 FROM world_spawns WHERE spawn_id=? AND guild_id=? AND expires_at<=?", (encounter["raid_spawn_id"], str(session["guild_id"]), now)):
        return _freeze({**current, "status": "expired"})
    selection = json.loads(session["selection"])
    if (await owned_count(conn, session["profile_id"]) >= owner["storage_limit"]
            and selection.get("storage_confirm") != expected_revision):
        return _freeze({**current, "status": "storage_full"})
    ball, berry = selection.get("ball"), selection.get("berry")
    rules = load_table("catch")["rules"]
    if (ball not in rules["ball_multipliers"] and ball != "master_ball"
            or berry is not None and berry not in rules["berry_multipliers"]
            or guaranteed != (ball == "master_ball")):
        raise ValueError("Invalid catch item selection")
    if guaranteed and berry not in ("pinap_berry", "silver_pinap_berry"):
        berry = None  # A catch-rate berry cannot help a guaranteed catch; only Pinaps change the reward.
    items = [ball, *([berry] if berry else [])]
    for item in items:
        async with conn.execute("SELECT quantity FROM inventory WHERE profile_id=? AND item_id=?",
                                (session["profile_id"], item)) as cursor:
            row = await cursor.fetchone()
        if row is None or row["quantity"] < 1:
            return _freeze({**current, "status": "no_ball" if item == ball else "no_berry"})
    candidates = [variant for identity in content["identities"]
                  for variant in [identity, *identity.get("gender_varieties", {}).values()]]
    identity = next(item for item in candidates if item["pokemon_id"] == encounter["pokemon_id"])
    ordinal = encounter["attempt_ordinal"]
    key = f"throw:{encounter_id}:{ordinal}"

    async def compute(conn):
        lines = []
        for item in items:
            await conn.execute("UPDATE inventory SET quantity=quantity-1 WHERE profile_id=? AND item_id=?",
                               (session["profile_id"], item))
            lines.append({"profile_id": session["profile_id"], "resource": "item", "resource_id": item,
                          "delta": -1, "reason": "catch_spend"})
        p = 1 if guaranteed else catch_probability(
            identity["base_catch_rate"], encounter["level_x2"], rules["ball_multipliers"][ball],
            rules["berry_multipliers"].get(berry, 1), multipliers=load_table("cpm")["multipliers"])
        success = guaranteed or rng.random() < p
        fled = not success and flees_after_failure(encounter["tier"], bool(encounter["shiny"]), rng, rules=rules)
        state = "caught" if success else "fled" if fled else "revealed"
        await conn.execute("INSERT INTO catch_attempts(encounter_id,ordinal,ball,berry,p,success,fled,created_at) "
                           "VALUES (?,?,?,?,?,?,?,?)", (encounter_id, ordinal, ball, berry, p, success, fled, now))
        await conn.execute("UPDATE encounters SET state=?,attempt_ordinal=attempt_ordinal+1,revision=revision+1,"
                           "resolved_at=? WHERE encounter_id=?",
                           (state, now if state != "revealed" else None, encounter_id))
        candy, stardust = 0, 0
        if success:
            await conn.execute("INSERT INTO pokedex(profile_id,pokemon_id,seen_at,caught_at) VALUES (?,?,?,?) "
                               "ON CONFLICT(profile_id,pokemon_id) DO UPDATE SET caught_at=COALESCE(caught_at,excluded.caught_at)",
                               (session["profile_id"], identity["species_id"], now, now))
            await check_and_award(conn, session['profile_id'], content, now)
            candy, stardust = identity["catch_candy"], identity["catch_stardust"]
            stardust = await boost(conn, session["profile_id"], stardust)
            if berry == "pinap_berry":
                candy *= rules["pinap_candy_multiplier"]
            elif berry == "silver_pinap_berry":
                ratio = rules["silver_pinap_candy"]
                candy = candy * ratio["numerator"] // ratio["denominator"]
            await conn.execute("INSERT INTO candy VALUES (?,?,?) ON CONFLICT(profile_id,family_id) "
                               "DO UPDATE SET quantity=quantity+excluded.quantity",
                               (session["profile_id"], identity["family_id"], candy))
            await conn.execute("UPDATE profiles SET stardust=stardust+? WHERE profile_id=?",
                               (stardust, session["profile_id"]))
            lines.extend([{"profile_id": session["profile_id"], "resource": resource, "resource_id": resource_id,
                           "delta": delta, "reason": "catch_reward"} for resource, resource_id, delta in
                          (("candy", str(identity["family_id"]), candy), ("stardust", None, stardust))])
        async with conn.execute("SELECT * FROM encounters WHERE encounter_id=?", (encounter_id,)) as cursor:
            updated = dict(await cursor.fetchone())
        saved = await current_result(conn, updated)
        saved.update(candy=candy, stardust=stardust)
        return saved, lines

    saved = await with_receipt(conn, key, "throw", compute, profile_id=session["profile_id"])
    await conn.execute("UPDATE catch_attempts SET receipt_key=? WHERE encounter_id=? AND ordinal=?",
                       (key, encounter_id, ordinal))
    selection.update(encounter_revision=saved["encounter"]["revision"])
    selection.pop("master_confirm", None)
    session["selection"] = json.dumps(selection)
    session["_catch_applied"] = True
    return _freeze(saved)
