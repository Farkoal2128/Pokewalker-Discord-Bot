"""One half-step with owner checks, atomic resource debits and durable replay."""

import json

from content.balance import load_table
from pokewalker.db import with_receipt
from pokewalker.domain.cp import cp
from pokewalker.services import profiles, storage


async def balances(conn, profile_id):
    async with conn.execute("SELECT stardust FROM profiles WHERE profile_id=?", (profile_id,)) as cursor:
        profile = await cursor.fetchone()
    async with conn.execute("SELECT family_id,quantity FROM candy WHERE profile_id=?", (profile_id,)) as cursor:
        candy = {row["family_id"]: row["quantity"] for row in await cursor.fetchall()}
    return {"stardust": profile["stardust"] if profile else 0, "candy": candy}


async def quote(conn, profile_id, pokemon_uid, content, multipliers):
    pokemon = await storage.detail(conn, profile_id, pokemon_uid)
    if pokemon is None:
        return None
    identity, _ = storage.identify(content, pokemon)
    base = [identity[key] for key in ("base_attack", "base_defense", "base_stamina")]
    ivs = [pokemon[key] for key in ("iv_attack", "iv_defense", "iv_stamina")]
    level = pokemon["level_x2"]
    prices = load_table("powerup_prices")
    at_cap = level >= prices["cap_level_x2"]
    band = None if at_cap else next(item for item in prices["bands"]
                                    if item["min_level_x2"] <= level < item["max_level_x2_exclusive"])
    have = await balances(conn, profile_id)
    candy_have, dust_have = have["candy"].get(identity["family_id"], 0), have["stardust"]
    async with conn.execute("SELECT quantity FROM inventory WHERE profile_id=? AND item_id='rare_candy'",
                            (profile_id,)) as cursor:
        held = await cursor.fetchone()
    rare_have = held["quantity"] if held else 0
    return {"level_x2": level, "cp_before": cp(base, ivs, level, multipliers=multipliers),
            "cp_after": None if at_cap else cp(base, ivs, level + 1, multipliers=multipliers),
            "candy_cost": None if at_cap else band["candy"],
            "stardust_cost": None if at_cap else band["stardust"],
            "candy_have": candy_have, "stardust_have": dust_have, "family_id": identity["family_id"],
            "at_cap": at_cap, "affordable": not at_cap and candy_have >= band["candy"] and dust_have >= band["stardust"],
            "rare_candy_have": rare_have, "rare_affordable": not at_cap and rare_have >= 1}


async def power_up(conn, session, pokemon_uid, expected_revision, content, multipliers, use_rare_candy=False):
    if not conn.in_transaction:
        raise RuntimeError("Power-up requires an active writer transaction")
    profile = await profiles.get_profile(conn, session["guild_id"], session["user_id"])
    if profile is None or profile["profile_id"] != session["profile_id"]:
        return {"status": "stale", "pokemon": None}
    pokemon = await storage.detail(conn, profile["profile_id"], pokemon_uid)
    if (await profiles.restrictions(conn, session["guild_id"], session["user_id"])).excluded:
        return {"status": "excluded", "pokemon": pokemon}
    if pokemon is None:
        return {"status": "stale", "pokemon": None}
    key = f"powerup:{pokemon_uid}:{expected_revision}"
    async with conn.execute("SELECT profile_id,result FROM action_receipts WHERE key=? AND action='powerup'", (key,)) as cursor:
        receipt = await cursor.fetchone()
    if receipt is not None:
        return json.loads(receipt["result"]) if receipt["profile_id"] == profile["profile_id"] else {"status": "stale", "pokemon": pokemon}
    if pokemon["gym_deployment_id"] is not None:
        return {"status": "stale", "pokemon": pokemon}
    if pokemon["revision"] != expected_revision:
        return {"status": "stale", "pokemon": pokemon}
    price = await quote(conn, profile["profile_id"], pokemon_uid, content, multipliers)
    if price["at_cap"] or not price["rare_affordable" if use_rare_candy else "affordable"]:
        return {"status": "at_cap" if price["at_cap"] else "insufficient", "pokemon": pokemon}

    async def compute(conn):
        await conn.execute("UPDATE pokemon SET level_x2=level_x2+1,revision=revision+1 WHERE pokemon_uid=?", (pokemon_uid,))
        if use_rare_candy:
            await conn.execute("UPDATE inventory SET quantity=quantity-1 WHERE profile_id=? AND item_id='rare_candy'",
                               (profile["profile_id"],))
            lines = [{"profile_id": profile["profile_id"], "resource": "item", "resource_id": "rare_candy",
                      "delta": -1, "reason": "powerup"}]
            return {"status": "powered_up", "pokemon": await storage.detail(conn, profile["profile_id"], pokemon_uid)}, lines
        await conn.execute("UPDATE candy SET quantity=quantity-? WHERE profile_id=? AND family_id=?",
                           (price["candy_cost"], profile["profile_id"], price["family_id"]))
        await conn.execute("UPDATE profiles SET stardust=stardust-? WHERE profile_id=?",
                           (price["stardust_cost"], profile["profile_id"]))
        lines = [{"profile_id": profile["profile_id"], "resource": resource, "resource_id": resource_id,
                  "delta": -cost, "reason": "powerup"} for resource, resource_id, cost in
                 (("candy", str(price["family_id"]), price["candy_cost"]), ("stardust", None, price["stardust_cost"]))]
        return {"status": "powered_up", "pokemon": await storage.detail(conn, profile["profile_id"], pokemon_uid)}, lines

    return await with_receipt(conn, key, "powerup", compute, profile_id=profile["profile_id"])
