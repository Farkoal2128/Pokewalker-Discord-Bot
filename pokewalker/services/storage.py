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


async def owned_count(conn, profile_id):
    """Pokemon that take a storage slot; every storage-full check uses this one rule."""
    async with conn.execute("SELECT count(*) FROM pokemon WHERE profile_id=? AND state='owned'",
                            (profile_id,)) as cursor:
        return (await cursor.fetchone())[0]


SORTS = ("newest", "favorites", "cp")
SORT_LABELS = {"newest": "Newest first", "favorites": "Favorites first", "cp": "Highest CP",
               "cp_low": "Lowest CP"}  # cp_low: research picker only (D68)


def sort_of(selection, choices=SORTS):
    """The picker order saved in a screen selection; a pre-CP selection used favorites_first."""
    sort = selection.get("sort")
    if sort in choices:
        return sort
    return "favorites" if selection.get("favorites_first") else "newest"


def next_sort(sort, choices=SORTS):
    return choices[(choices.index(sort) + 1) % len(choices)] if sort in choices else choices[0]


def sort_label(sort, choices=SORTS):
    """A sort button names the order a press switches to."""
    return SORT_LABELS[next_sort(sort, choices)]


async def ordered(conn, where, args, offset, limit, sort="newest", content=None, multipliers=None):
    """One page of pokemon rows matching where: newest first, favorites then newest, or highest CP
    then newest, or lowest CP then newest (cp_low, D68). CP is computed, not stored, so the CP
    orders rank every matching row in Python."""
    newest = "caught_at DESC,pokemon_uid"
    if sort not in ("cp", "cp_low"):
        order = ("favorite DESC," if sort == "favorites" else "") + newest
        async with conn.execute(f"SELECT * FROM pokemon WHERE {where} ORDER BY {order} "
                                f"LIMIT {int(limit)} OFFSET {int(offset)}", args) as cursor:
            return [dict(row) for row in await cursor.fetchall()]
    async with conn.execute(f"SELECT * FROM pokemon WHERE {where} ORDER BY {newest}", args) as cursor:
        rows = [dict(row) for row in await cursor.fetchall()]
    sign = -1 if sort == "cp" else 1
    rows.sort(key=lambda row: sign * stats(content, row, multipliers)["cp"])  # stable: ties stay newest first
    return rows[int(offset):int(offset) + int(limit)]


async def page(conn, profile_id, offset, favorite_only=False, *, sort="newest", content=None, multipliers=None):
    where = "profile_id=? AND state='owned'" + (" AND favorite=1" if favorite_only else "")
    async with conn.execute(f"SELECT COUNT(*) FROM pokemon WHERE {where}", (profile_id,)) as cursor:
        total = (await cursor.fetchone())[0]
    return await ordered(conn, where, (profile_id,), offset, 10, sort, content, multipliers), total


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
