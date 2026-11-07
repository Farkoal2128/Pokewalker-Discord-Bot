"""Read-only, profile-scoped species Pokédex queries (D15)."""


async def summary(conn, profile_id, content):
    async with conn.execute("SELECT count(*),count(caught_at) FROM pokedex WHERE profile_id=?",
                            (profile_id,)) as cursor:
        seen, caught = await cursor.fetchone()
    return {"seen": seen, "caught": caught, "total": len(content["species"])}


def _entry(row, content):
    species_id = row["pokemon_id"]
    identity = next((item for item in content["identities"]
                     if item["species_id"] == species_id and item["kind"] == "default"), None)
    if identity is None:
        raise ValueError(f"Content contract: species {species_id} has no default identity")
    return {"species_id": species_id, "name": identity["name_en"], "types": list(identity["types"]),
            "generation_id": identity["generation_id"], "sprite": identity["sprites"]["normal"],
            "seen_at": row["seen_at"], "caught_at": row["caught_at"]}


async def page(conn, profile_id, content, offset):
    async with conn.execute("SELECT * FROM pokedex WHERE profile_id=? ORDER BY pokemon_id LIMIT 20 OFFSET ?",
                            (profile_id, max(0, offset))) as cursor:
        return [_entry(row, content) for row in await cursor.fetchall()]


async def entry(conn, profile_id, species_id, content):
    async with conn.execute("SELECT * FROM pokedex WHERE profile_id=? AND pokemon_id=?",
                            (profile_id, species_id)) as cursor:
        row = await cursor.fetchone()
    return _entry(row, content) if row is not None else None
