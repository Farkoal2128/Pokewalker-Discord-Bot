# EXR-1 — migration `0031_ex_raid.sql`

**Tier:** seam (persisted state and migrations)

**Read:** PLAN D2; SYNTHESIS R4, R10, §6; `0015_raids.sql:3-17`; `0030_ex_gift.sql:1-13` (table and CHECK form); `db/__init__.py:34-46`; `tests/test_ex_gift_schema.py:25-52` (prior-schema fixture).

**Goal.** The schema for two live raids per server and the owner-side send record. Existing rows become `world` and behave as today. C3 first.

- **`ex_raids`**: `ex_raid_id TEXT PRIMARY KEY NOT NULL` (the send ID); `owner_id TEXT NOT NULL`; `identity_id TEXT NOT NULL`; five nullable locks, NULL = rolled: `shiny` in (0,1), `level` 1-40, `iv_attack`, `iv_defense`, `iv_stamina` 0-15, each `CHECK(c IS NULL OR (typeof(c)='integer' AND c BETWEEN lo AND hi))`; `hours` integer 1-24; `guild_id TEXT` (NULL = all servers; no FK); `servers` integer >= 1; `spawned` integer >= 1; `skipped TEXT NOT NULL CHECK(json_valid(skipped))` (object: reason to count); `created_at REAL NOT NULL`. Index on `created_at`. No player, profile or participant column (R4, R10).
- **`world_spawns`**: `ADD COLUMN kind TEXT NOT NULL DEFAULT 'world' CHECK(kind IN ('world','ex'))`; `ADD COLUMN ex_raid_id TEXT REFERENCES ex_raids`.
- **Index**: `DROP INDEX world_spawns_active_guild`; `CREATE UNIQUE INDEX world_spawns_active_guild_kind ON world_spawns(guild_id,kind) WHERE ended=0`.
- `raid_participation`, `encounters.raid_spawn_id` and the queue triggers are untouched.
- **C3:** amend "M8.1a raid schema and queue isolation" (one unended spawn per server **and kind**); add "EX-Raid schema (0031)": table, columns, defaults; `ex_raids` keeps the sender's ID and aggregate counts, never a player's; additive; older code refuses schema 31; rollback needs a compatible backup.

**Files.** Production: `pokewalker/db/migrations/0031_ex_raid.sql`. Tests: `tests/test_ex_raid_schema.py` (new), `tests/test_arena_schema.py`, `tests/test_ex_gift_schema.py`, `tests/test_receipt_owner.py`, `tests/test_raids.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests in `tests/test_ex_raid_schema.py` pass, RED first:
- `test_migration_0031_existing_spawns_become_world` (from schema 30 with a live and an ended spawn; `user_version` 31; `ex_raid_id` NULL; `PRAGMA foreign_key_check` empty; a second open changes nothing)
- `test_one_live_spawn_per_guild_and_kind` (second live `world` refused; second live `ex` refused; one of each allowed; an ended row frees its slot)
- `test_kind_check_rejects_unknown`
- `test_ex_raids_lock_hours_and_count_checks` (shiny 2, level 0 and 41, IV -1 and 16, hours 0 and 25, text values, `spawned` 0: each refused; all-NULL locks, `shiny` 0 and IV 0 accepted)
- `test_ex_raids_has_no_player_column`
- `test_spawn_ex_raid_id_must_reference_a_send`
- `test_guild_delete_cascades_ex_spawns_keeps_ex_raids`

Pins moved, and only as stated:
- literal `user_version` 30 to 31: `tests/test_arena_schema.py:74, :128, :160, :220`; `tests/test_ex_gift_schema.py:67`.
- `tests/test_receipt_owner.py` `legacy_schema` (:57-100): `DROP TABLE ex_raids` after `world_spawns` (:83).
- `tests/test_raids.py:907`: the column-less `INSERT INTO world_spawns SELECT` names the 12 columns of `services/raids.py:124-125`. It is the only column-less insert (`git grep -n "INTO world_spawns" tests | grep -v "world_spawns("`).
- Tests that compute the version (`len(MIGRATIONS glob)`) need no edit.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_raid_schema`, `raids`, `admin_force_raid`, `arena_schema`, `ex_gift_schema`, `receipt_owner`, `db`, `deletion`, `capacity`, `pokemon_forms`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `0031` is taken (renumber, report it); an existing migration or `db/__init__.py` needs an edit; `ALTER TABLE` refuses a column under `foreign_keys=ON`; a pin fails for another reason.

**Do not touch.** Migrations 0001-0030; `db/__init__.py`; `services/**`; `bot/**`.
