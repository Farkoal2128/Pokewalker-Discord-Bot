"""D74 (owner 2026-11-17): delete finished data nothing reads, in capped batches each minute.

Call only inside a Writer transaction. The clocks, and why each is safe, are in
contracts/persisted-state.md (migration 0034); tests pin the privacy text to these values.
"""

import json


ACKNOWLEDGED_KEEP = 3600  # result screens: a session expires after 15 idle minutes
UNACKNOWLEDGED_KEEP = 86400  # M1.9 recovery re-shows an unclosed result for one day
STEP_EVENT_KEEP = 86400  # readers look back an hour at most (anti-farming, mod lookup)
GYM_BATTLE_KEEP = 3600  # an unread copy of the log held in the battle receipt
BATTLE_RECEIPT_KEEP = 2 * 86400  # replay needs a live session; sessions go a day after expiry
BATCH = 1000
ARENA_BATCH = 100
RECLAIM_PAGES = 1000

_UUID = "-".join("[0-9a-f]" * width for width in (8, 4, 4, 4, 12))
# Encounter IDs are always str(uuid4()); only keys of exactly these shapes are ever touched.
# kind: (range start, range end, shape, 1-based position of the encounter ID in the key)
_LEFTOVERS = {
    "throw": ("throw:", "throw;", f"throw:{_UUID}:*", 7),
    "run": ("run:", "run;", f"run:{_UUID}:*", 5),
    "research": ("research:auto:", "research:auto;", f"research:auto:{_UUID}", 15),
}
_IDS = "SELECT value FROM json_each(?)"


def _require(conn):
    if not conn.in_transaction:
        raise RuntimeError("Cleanup requires an active writer transaction")


async def _key_ranges(conn, prefixes):
    """Delete every receipt keyed `<prefix>…`; `;` is the character after `:`."""
    await conn.executemany("DELETE FROM action_receipts WHERE key>? AND key<?",
                           [(prefix, prefix[:-1] + ";") for prefix in prefixes])


async def _encounters(conn, now, batch):
    rows = await conn.execute_fetchall(
        "SELECT encounter_id FROM encounters e WHERE resolved_at<=? AND state IN ('caught','fled','ran') "
        "AND (acknowledged_at IS NOT NULL OR (resolved_at<=? AND (state<>'caught' OR EXISTS "
        "(SELECT 1 FROM pokemon WHERE source_encounter_id=e.encounter_id)))) "
        "AND (raid_spawn_id IS NULL OR NOT EXISTS "
        "(SELECT 1 FROM world_spawns WHERE spawn_id=e.raid_spawn_id AND ended=0)) LIMIT ?",
        (now - ACKNOWLEDGED_KEEP, now - UNACKNOWLEDGED_KEEP, batch))
    ids = [row[0] for row in rows]
    if not ids:
        return
    batch_ids = json.dumps(ids)
    # A detached reaction row stays reconcilable by its message ID; it is never lost.
    await conn.execute(f"UPDATE reactions SET encounter_id=NULL WHERE encounter_id IN ({_IDS})", (batch_ids,))
    await conn.execute(f"DELETE FROM action_receipts WHERE key IN (SELECT receipt_key FROM catch_attempts "
                       f"WHERE encounter_id IN ({_IDS}) AND receipt_key IS NOT NULL)", (batch_ids,))
    await _key_ranges(conn, [f"run:{encounter_id}:" for encounter_id in ids])
    await conn.execute(f"DELETE FROM action_receipts WHERE key IN (SELECT 'research:auto:'||value "
                       f"FROM json_each(?))", (batch_ids,))
    await conn.execute(f"DELETE FROM encounters WHERE encounter_id IN ({_IDS})", (batch_ids,))


async def _leftovers(conn, resume, batch):
    """Receipts whose encounter is already gone (raid expiry, the pre-D74 backlog)."""
    position = dict(resume or {})
    for kind, (start, end, shape, offset) in _LEFTOVERS.items():
        keys = [row[0] for row in await conn.execute_fetchall(
            "SELECT key FROM action_receipts WHERE key>? AND key<? ORDER BY key LIMIT ?",
            (position.get(kind) or start, end, batch))]
        if keys:
            await conn.execute(
                f"DELETE FROM action_receipts WHERE key IN ({_IDS}) AND key GLOB ? AND NOT EXISTS "
                f"(SELECT 1 FROM encounters WHERE encounter_id=substr(key,{offset},36))",
                (json.dumps(keys), shape))
        position[kind] = keys[-1] if len(keys) == batch else None  # wrap at the end
    return position


async def _arena(conn):
    rows = await conn.execute_fetchall(
        "SELECT old.run_id FROM arena_runs old WHERE old.ended_at IS NOT NULL AND EXISTS "
        "(SELECT 1 FROM arena_runs newer WHERE newer.profile_id=old.profile_id AND "
        "(newer.started_at>old.started_at OR (newer.started_at=old.started_at AND newer.run_id>old.run_id))) "
        "LIMIT ?", (ARENA_BATCH,))
    runs = [row[0] for row in rows]
    if runs:
        await _key_ranges(conn, [f"{kind}:{run}:" for run in runs
                                 for kind in ("arena_fight", "arena_use", "arena_heal")])
        await conn.execute(f"DELETE FROM arena_runs WHERE run_id IN ({_IDS})", (json.dumps(runs),))


async def sweep(conn, now, resume, batch=BATCH):
    """One capped cleanup pass; returns the leftover-receipt position for the next pass.

    The caller keeps the returned position only after its writer job commits.
    """
    _require(conn)
    await _encounters(conn, now, batch)
    position = await _leftovers(conn, resume, batch)
    # SQLite here lacks DELETE ... LIMIT, so each capped delete selects its keys first.
    await conn.execute("DELETE FROM step_events WHERE message_id IN (SELECT message_id FROM step_events "
                       "WHERE created_at<=? LIMIT ?)", (now - STEP_EVENT_KEEP, batch))
    await conn.execute("DELETE FROM gym_battles WHERE battle_id IN (SELECT battle_id FROM gym_battles "
                       "WHERE created_at<=? LIMIT ?)", (now - GYM_BATTLE_KEEP, batch))
    await conn.execute("DELETE FROM action_receipts WHERE key IN (SELECT key FROM action_receipts "
                       "WHERE key GLOB 'battle:*' AND created_at<=? LIMIT ?)", (now - BATTLE_RECEIPT_KEEP, batch))
    await _arena(conn)
    return position


async def reclaim(conn):
    """Return up to RECLAIM_PAGES free pages to the filesystem (a no-op outside incremental mode)."""
    _require(conn)
    async with conn.execute("PRAGMA freelist_count") as cursor:
        pages = min(RECLAIM_PAGES, (await cursor.fetchone())[0])
    if pages:
        # Each step frees one page; run it to completion so the writer can commit.
        async with conn.execute(f"PRAGMA incremental_vacuum({int(pages)})") as cursor:
            await cursor.fetchall()
