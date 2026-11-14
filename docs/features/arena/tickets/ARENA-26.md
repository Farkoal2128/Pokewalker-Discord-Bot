# ARENA-26 — migration `0028_arena_x_items.sql`; `state` keys, `buy_x`, `use_x`

**Tier:** seam (persisted player state and migrations)

**Read:** PLAN D4, D20; AR-43..45; ARENA-8, 16, 25; `0026_arena_settings.sql`; `services/arena.py` `state`, `heal`; `services/items.py` `_buy`.

**Goal.** Buy X items; start a countdown on a live run. Fights ignore the counters until ARENA-27. C3 first.

- **Migration `0028_arena_x_items.sql`** (0027 is the last): `arena_runs.x_attack_left` and `x_defense_left`, each `INTEGER NOT NULL DEFAULT 0 CHECK(typeof(c)='integer' AND c>=0)`, as `0026` adds columns. `_latest_run` reads `SELECT *`, so `run` carries both.
- **`state`** adds `'stardust'` (the profile row it already loads) and `'x_items'`: `{item id: held}` for every `rules.x_items.items` key, 0 when none.
- **`buy_x(conn, session, item)`** (D20 Buy): an id outside `rules.x_items.items` → `{'status': 'invalid'}`. Else call `items._buy(conn, session, item, price)` unchanged (import `items`):
  - its key uses `session['revision']`, already bumped by the router: do not pass `_original_revision`;
  - its refusals pass through, nothing spent: `stale`, `excluded`, `insufficient` (checked first), `bag_full`;
  - its success has no `status`: return `{'status': 'bought', 'item', 'stardust'}`.
- **`use_x(conn, session, run_id, revision, item, now)`**, shaped like `heal`:
  - `state`, the `_live_run` stale rule, then an unknown id → `invalid`;
  - `run['<item>_left'] > 0` → `{'status': 'active', 'left': n}`; none held → `{'status': 'missing'}`; neither writes;
  - else in `with_receipt` (key `arena_use:<run_id>:<revision>`, action `arena_use`, `profile_id`): inventory −1, that counter = `rules.x_items.fights`, `revision + 1` → `{'status': 'used', 'run'}`; ledger `item / <item> / -1 / arena_use`;
  - the other counter is untouched. Paused members may use; excluded ones may not.
- **C3:** append "Arena X items (0028)"; older binaries refuse schema 28.

**Files.** Production: `pokewalker/db/migrations/0028_arena_x_items.sql`, `pokewalker/services/arena.py`. Tests: `tests/test_arena_schema.py`, `tests/test_arena.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests pass, RED first. In `tests/test_arena_schema.py`:
- `test_migration_0028_adds_x_counters_preserving_rows` (from schema 27; both 0; `user_version` 28)
- `test_x_counter_checks_reject_bad_values` (−1, 1.5)

In `tests/test_arena.py` (bump `session['revision']` per press, as `Walker.route` does):
- `test_state_reports_stardust_and_held_x_items`
- `test_buy_x_moves_stardust_to_bag_with_buy_ledger_lines`
- `test_buy_x_refuses_insufficient_then_bag_full`
- `test_buy_x_needs_no_run_ignores_off_cooldown_pause`
- `test_same_buy_press_buys_once`
- `test_use_x_sets_counter_spends_item_bumps_revision`
- `test_use_x_active_kind_refused_other_kind_allowed`
- `test_use_x_missing_stale_invalid_write_nothing`
- `test_new_run_starts_both_counters_at_zero`
- `test_x_receipts_and_ledger_carry_profile_id`
- `test_excluded_member_cannot_buy_or_use_x`

Pins move only by the columns, keys and version: `test_arena_schema.py` (version 28; pop both counters from the `arena_runs` rows in the 0026 and 0027 tests); `test_arena.py` `test_start_snapshots_and_rolls_enemy` (exact `state`). The deletion tests stay: no new table.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `arena_schema`, `arena`, `arena_screens`, `arena_admin`, `receipt_owner`, `deletion`, `admin_reset_sharing`, `db`; `git -c core.whitespace=cr-at-eol diff --cached --check` (keep the contract's CR line ends).

**Stop if.** `0028` is taken (renumber, report it); an existing migration, `db/__init__.py` or `services/items.py` needs an edit; a pinned test fails for another reason; over 300 production lines.

**Do not touch.** Migrations 0001-0027; `db/__init__.py`; `services/items.py`; `fight`, `chain_step` (ARENA-27); `bot/**`; `domain/**`; `content/**`.
