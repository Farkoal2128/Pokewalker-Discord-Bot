"""M2.1 owned storage queries and optimistic favorite updates."""

from pokewalker.domain.cp import cp, hp


def identify(content, pokemon):
    form_id = dict(pokemon).get("form_id")
    candidates = (variant for item in [*content["identities"], *content.get("evolution_targets", [])]
                  for variant in [item, *item.get("gender_varieties", {}).values()])
    identity = next(item for item in candidates if item["pokemon_id"] == pokemon["pokemon_id"]
                    and (form_id is None or item["form_id"] == form_id))
    female = pokemon["gender"] == "female" and identity["has_gender_differences"]
    key = ("shiny_female" if female else "shiny") if pokemon["shiny"] else ("female" if female else "normal")
    return identity, identity["sprites"][key]



def stats(content, pokemon, multipliers):
    """Identity, sprite, CP and HP shown for one Pokemon row."""
    identity, sprite = identify(content, pokemon)
    base = [identity[key] for key in ("base_attack", "base_defense", "base_stamina")]
    ivs = [pokemon[key] for key in ("iv_attack", "iv_defense", "iv_stamina")]
    return {"pokemon": pokemon, "identity": identity, "sprite": sprite,
            "cp": cp(base, ivs, pokemon["level_x2"], multipliers=multipliers),
            "hp": hp(base, ivs, pokemon["level_x2"], multipliers=multipliers)}


async def page(conn, profile_id, offset, favorite_only=False):
    where = "profile_id=? AND state='owned'" + (" AND favorite=1" if favorite_only else "")
    async with conn.execute(f"SELECT COUNT(*) FROM pokemon WHERE {where}", (profile_id,)) as cursor:
        total = (await cursor.fetchone())[0]
    async with conn.execute(f"SELECT * FROM pokemon WHERE {where} "
                            "ORDER BY caught_at DESC,pokemon_uid LIMIT 10 OFFSET ?",
                            (profile_id, offset)) as cursor:
        return [dict(row) for row in await cursor.fetchall()], total


async def detail(conn, profile_id, uid):
    async with conn.execute("SELECT * FROM pokemon WHERE profile_id=? AND pokemon_uid=? AND state='owned'",
                            (profile_id, uid)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row is not None else None


async def set_favorite(conn, profile_id, uid, value, expected_revision):
    async with conn.execute("UPDATE pokemon SET favorite=?,revision=revision+1 WHERE profile_id=? "
                            "AND pokemon_uid=? AND revision=? AND state='owned' RETURNING *",
                            (value, profile_id, uid, expected_revision)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row is not None else None
