# ARENA-16 — migration `0026_arena_settings.sql` and the settings setters

**Tier:** seam (persisted player state and migrations)

**Read:** PLAN D4, D15, D19; REQUIREMENTS AR-4a, AR-10b, AR-10d; ARENA-4, ARENA-8; `0024_shiny_charm.sql`; `services/arena.py` `state`, `_live_run`, `set_order`.

**Goal.** Two per-profile Fight-until-hurt settings, and setters that make every other open screen redraw. C3 first.

- **Migration `pokewalker/db/migrations/0026_arena_settings.sql`** (0025 is the last at 3ab843a; numbering stays contiguous, `db/__init__.py:34-37`):
  - `profiles.arena_stop_pct INTEGER NOT NULL DEFAULT 50 CHECK(arena_stop_pct IN (10,20,30,40,50,60,70,80,90))`.
  - `profiles.arena_auto_order INTEGER NOT NULL DEFAULT 0 CHECK(arena_auto_order IN (0,1))`.
- **`services/arena.py`:**
  - `STOP_PCTS = range(10, 100, 10)`: the one Python copy of the allowed values; the screens import it. Not in `arena.json` (D19).
  - `state` adds `'stop_pct'` and `'auto_order'` (a bool) from the profile row it already loads.
  - `set_stop_pct(conn, session, run_id, revision, pct, now)` and `set_auto_order(conn, session, run_id, revision, on, now)`, shaped like `set_order`: `state`, then the `_live_run` stale rule (no live run, another `run_id` or `revision` → `{'status': 'stale', 'run'}`, nothing written). `pct` not an `int` in `STOP_PCTS`, or `on` not a `bool` → `invalid`. Otherwise update the profile column and bump `arena_runs.revision` in the same transaction → `{'status': 'set', 'run'}` with the new revision. Setting the current value again still bumps. No receipt or ledger line: no resource moves (D4).
  - Paused members may change them; `session_owner` refuses excluded members.
- **C3:** append "Arena settings (0026)": columns, defaults, checks, `state` keys, setters, stale rule, revision bump; older binaries refuse schema 26 (`db/__init__.py:40-41`).

**Files.** Production: `pokewalker/db/migrations/0026_arena_settings.sql`, `pokewalker/services/arena.py`. Tests: `tests/test_arena_schema.py`, `tests/test_arena.py`, plus the fallout edits below. Contract: `contracts/persisted-state.md`.

**Accept.** New tests pass, RED first. In `tests/test_arena_schema.py`:
- `test_migration_0026_adds_settings_preserving_rows` (from schema 25; defaults 50 and 0; `user_version` 26; `foreign_key_check` clean)
- `test_settings_checks_reject_bad_values` (55, 0, 100; flag 2)

In `tests/test_arena.py`:
- `test_state_reports_setting_defaults`
- `test_setters_save_on_profile_and_bump_live_run_revision`
- `test_settings_carry_over_to_the_next_run`
- `test_setting_from_stale_screen_or_without_live_run_writes_nothing`
- `test_invalid_setting_values_refused_without_write`
- `test_fight_from_other_screen_is_stale_after_setting_change`
- `test_excluded_member_cannot_change_settings_paused_can`

Pinned tests change only by the new columns, keys and version: `test_arena_schema.py` `test_migration_0025_adds_tables_columns_preserving_rows` (pop both columns; version 26), `test_arena.py` `test_start_snapshots_and_rolls_enemy` (exact `state` dict), `test_receipt_owner.py` `legacy_schema` (drop both columns), `test_capacity.py` and `test_trading_schema.py` (pops beside `arena_best_floor`).

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above + migration-pinned modules; receipt=Tests-Focused on staged tree; boundary=final feature (G-F)`. Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `arena_schema`, `arena`, `arena_screens`, `arena_admin`, `receipt_owner`, `capacity`, `trading_schema`, `db`, `deletion`, `admin_reset_sharing`, `companion_mirror`, `gyms`, `raids`, `milestones`, `pokemon_forms`, `lure`, `finds`, `route_unlocks`, `star_piece`; `git diff --check`.

**Stop if.** `0026` is taken on the Home (renumber and report it); a pinned test fails for another reason than the new columns, keys or version; an existing migration needs an edit.

**Do not touch.** Migrations 0001-0025; `db/__init__.py`; `services/profiles.py`; `bot/arena.py` (ARENA-18).
