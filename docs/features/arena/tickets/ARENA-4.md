# ARENA-4 — migration `0025_arena.sql` and the live-team check

**Tier:** seam (persisted player state and migrations)

**Read:** PLAN D2, D3; REQUIREMENTS AR-1..AR-4b, AR-6a, AR-25, AR-33, AR-35, §10 deletion row; `pokewalker/db/__init__.py` `open_db`; migrations `0014_gyms.sql`, `0023_gym_legendary_setting.sql`; `services/profiles.py` `queue_size`.

**Goal.** The Phase 1 schema plus the one shared "on a live Arena team" query. C3 section first.

- **Migration `pokewalker/db/migrations/0025_arena.sql`** (0024 is the last at 9c8aec5; numbering must stay contiguous, `db/__init__.py:34-37`):
  - `guilds.arena_enabled INTEGER NOT NULL DEFAULT 1 CHECK(arena_enabled IN (0,1))`.
  - `profiles.arena_best_floor INTEGER NOT NULL DEFAULT 0`, integer and `>= 0`.
  - `arena_runs`: `run_id TEXT PRIMARY KEY`; `profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE`; `started_at REAL NOT NULL`; `ended_at REAL`; `end_reason TEXT` in (`loss`, `draw`, `expired`), set exactly when `ended_at` is; `revision INTEGER NOT NULL DEFAULT 0`; `floor INTEGER NOT NULL` >= 1; `slot INTEGER NOT NULL` in (0,1,2); `team TEXT NOT NULL` and `enemy TEXT NOT NULL`, both `json_valid`.
  - Unique index `arena_runs_live ON arena_runs(profile_id) WHERE ended_at IS NULL` (pattern `0014_gyms.sql:27`); index `arena_runs_profile ON arena_runs(profile_id, started_at)` for the cooldown lookup and the cascade.
  - `arena_tickets`: `profile_id` (same cascade), `tier` in the five tier names, `quantity` integer >= 0, primary key `(profile_id, tier)`.
- **`team` JSON** (party order): `[{"uid", "family_id", "special", "full_hp", "hp", "snapshot"}]`, where `snapshot` is the `gyms._battle_snapshot` dict. **`enemy` JSON:** `{"snapshot", "battle_hp", "special"}`. ARENA-8 and ARENA-9 write them; this row fixes the shapes in C3.
- **`profiles.arena_team(conn, profile_id, now)`** → `frozenset` of the `uid`s in the row with `ended_at IS NULL AND started_at > now - rules.run_seconds` (`load_table('arena')`), else an empty set. Read-only.
- **C3:** append "Arena schema (0025)": tables, JSON shapes, cascade, the live rule, `arena_team`, and that older binaries refuse schema 25 (`db/__init__.py:40-41`).

**Files.** Production: `pokewalker/db/migrations/0025_arena.sql`, `pokewalker/services/profiles.py`. Tests: `tests/test_arena_schema.py` (new), plus the deliberate fallout edits below. Contract: `contracts/persisted-state.md`.

**Accept.** `tests/test_arena_schema.py` passes, RED first:
- `test_migration_0025_adds_tables_columns_preserving_rows` (upgrade a schema-24 database; defaults 1 and 0; `foreign_key_check` clean)
- `test_one_live_run_per_profile`
- `test_run_and_ticket_checks_reject_bad_rows`
- `test_profile_delete_cascades_runs_and_tickets`
- `test_arena_team_live_until_hour_18_then_empty_without_any_write`
- `test_arena_team_empty_after_run_ended_and_for_other_profile`

Schema-pinned tests change only by naming the new columns and tables: `tests/test_receipt_owner.py` `legacy_schema` (drop both tables and both columns), `tests/test_capacity.py` (profile-row pops near :81), `tests/test_trading_schema.py` (guild and profile pops near :87-91).

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above + migration-pinned modules; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `arena_schema`, `receipt_owner`, `capacity`, `trading_schema`, `db`, `deletion`, `gyms`, `raids`, `milestones`, `companion_mirror`, `pokemon_forms`, `lure`, `finds`, `route_unlocks`, `admin_reset_sharing`; `git diff --check`.

**Stop if.** `0025` is taken on the Home (renumber and report it); a pinned test fails for a reason other than the new columns and tables; an existing migration needs an edit.

**Do not touch.** Migrations 0001-0024; `services/deletion.py`; `db/__init__.py`.
