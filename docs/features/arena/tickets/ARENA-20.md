# ARENA-20 — migration `0027_arena_months.sql` and the monthly score write

**Tier:** seam (persisted player state and migrations)

**Read:** PLAN D5, D18; REQUIREMENTS AR-36, AR-37, AR-39, AR-40; ARENA-9; `0014_gyms.sql`; `services/arena.py` `fight`.

**Goal.** Three tables hold the month's scores, the settled months and the paid places; a boss win writes the score. C3 first.

- **Migration `0027_arena_months.sql`** (0026 is the last at 8e6a7bf). `month` is UTC `'YYYY-MM'` text, `GLOB`-checked; floors and places are integers ≥ 1; times are epoch seconds.
  - `arena_month_scores(guild_id, month, profile_id, floor, reached_at)`: primary key `(profile_id, month)`; `FOREIGN KEY(profile_id, guild_id) REFERENCES profiles(profile_id, guild_id) ON DELETE CASCADE`; an index on `(guild_id, month)`.
  - `arena_months(guild_id REFERENCES guilds ON DELETE CASCADE, month, settled_at)`: primary key `(guild_id, month)`; no profile column, so it outlives a deleted player (AR-40).
  - `arena_month_places(guild_id, month, place, profile_id, floor)`: primary key `(guild_id, month, place)`; `UNIQUE(profile_id, month)`, also the cascade index; the same profile FK.
- **`services/arena.py`:**
  - `month_key(now)` → the UTC `'YYYY-MM'` of epoch `now`.
  - `fight`'s `compute`, boss-win branch, beside the `arena_best_floor` credit: upsert the score row of `(session['guild_id'], month_key(now), profile)` with this `floor` and `reached_at = now`, only when no row exists or `floor` is higher. An equal or lower floor keeps the stored floor and time (AR-37).
  - Nothing else writes scores. `start` with a skip writes none: after a 40-floor skip the first score is 41. `chain_step` and `heal_all_and_fight` score through `fight`. A run crossing 00:00 UTC on the 1st scores its later floors in the new month.
  - The fight result, its receipt (D5), the ledger and `state` do not change; a replayed fight writes nothing.
- **C3:** append "Arena monthly leaderboard schema (0027)"; older binaries refuse schema 27.

**Files.** Production: `pokewalker/db/migrations/0027_arena_months.sql`, `pokewalker/services/arena.py`. Tests: `tests/test_arena_schema.py`, `tests/test_arena.py`, `tests/test_deletion.py`, `tests/test_admin_reset_sharing.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests pass, RED first. In `tests/test_arena_schema.py`:
- `test_migration_0027_adds_month_tables_preserving_rows` (from schema 26)
- `test_month_tables_reject_bad_rows` (bad month; floor 0; a profile twice in a month)
- `test_profile_delete_cascades_scores_places_guild_delete_months`

In `tests/test_arena.py`:
- `test_boss_win_writes_month_score_other_fights_do_not`
- `test_higher_floor_replaces_score_else_floor_and_time_stay`
- `test_run_crossing_utc_month_scores_in_new_month`
- `test_skip_writes_no_score_first_score_is_floor_41`
- `test_chain_step_and_heal_all_boss_wins_score`
- `test_replayed_boss_fight_scores_once`

Deletion, real service: `populate_arena` makes its one fight a floor-1 boss win and inserts a settled month and a paid place; the three Arena table lists in `test_deletion.py` and `test_admin_reset_sharing.py` gain the score and place tables; the settled month stays. The `test_arena_schema.py` version pins become 27.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=final feature (G-F)`. Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `arena_schema`, `arena`, `arena_screens`, `deletion`, `admin_reset_sharing`, `db`, `pokemon_forms`, `route_unlocks`; `git -c core.whitespace=cr-at-eol diff --cached --check` (keep CR line ends in both deletion test files and the contract).

**Stop if.** `0027` is taken on the Home (renumber, report it); an existing migration or `db/__init__.py` needs an edit; the score needs a new result key or receipt field; over 300 production lines.

**Do not touch.** Migrations 0001-0026; `db/__init__.py`; `services/deletion.py`; `domain/arena.py`; `bot/**`; `arena.json`.
