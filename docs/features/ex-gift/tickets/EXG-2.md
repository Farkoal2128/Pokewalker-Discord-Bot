# EXG-2 — migration `0030_ex_gift.sql`

**Tier:** seam (persisted player state and migrations)

**Read:** PLAN D2, D3, D6; SYNTHESIS EX-4, EX-6, R4, R8, R9, R13, R20; `0009_guild_sharing.sql` (rebuild form); `0004_milestones.sql:7-16`; `0025_arena.sql`, `0028_arena_x_items.sql` (column form); `db/__init__.py:34-46`.

**Goal.** Every table and column the feature needs; existing data kept, flags off. C3 first.

- **`ex_gifts`**: `gift_id TEXT PRIMARY KEY NOT NULL` (the send ID); `owner_id TEXT NOT NULL`; `scope TEXT NOT NULL CHECK(scope IN ('all','server','user'))`; `guild_id TEXT` with `CHECK((scope='all')=(guild_id IS NULL))`, no FK; `items TEXT NOT NULL CHECK(json_valid(items) AND json_array_length(items) BETWEEN 1 AND 10)`; `servers`, `servers_with_recipients` integers ≥0, `recipients` integer ≥1; `created_at REAL NOT NULL`. Index on `created_at`. No recipient or user ID column (R20).
- **`ex_gift_recipients`**: `gift_id` → `ex_gifts ON DELETE CASCADE`, `profile_id` → `profiles ON DELETE CASCADE`, `claimed_at REAL`; `PRIMARY KEY(gift_id,profile_id)`; index `(profile_id,claimed_at)`.
- **`ex_items`**: `profile_id` → `profiles ON DELETE CASCADE`; `item_id TEXT NOT NULL CHECK(item_id IN ('time_gear_fragment','shiny_patch','golden_bottlecap','ex_attack','ex_defense','arena_ex_voucher'))`; `quantity INTEGER NOT NULL CHECK(typeof(quantity)='integer' AND quantity>=0)`; `PRIMARY KEY(profile_id,item_id)`. No cap (EX-4).
- **Columns**, each `INTEGER NOT NULL DEFAULT 0 CHECK(c IN (0,1))`: `profiles.ex_attack_armed`, `profiles.ex_defense_armed`, `arena_runs.ex_attack`, `arena_runs.ex_defense`.
- **`inbox_items` rebuild** (R8), as 0009: `inbox_items_new` with the 0004 columns and `resource IN ('item','stardust','candy','arena_ticket')`; `INSERT … SELECT *`; drop; rename; recreate `inbox_items_profile_id`. `inbox_id` values are kept.
- **C3:** "EX-Gift schema (0030)": tables; retention (recipients, EX inventory, inbox rows cascade with the profile; `ex_gifts` keeps the sender's ID, never a recipient's); older code refuses schema 30.

**Files.** Production: `pokewalker/db/migrations/0030_ex_gift.sql`. Tests: `tests/test_ex_gift_schema.py` (new) and the pins below. Contract: `contracts/persisted-state.md`.

**Accept.** New tests in `tests/test_ex_gift_schema.py` pass, RED first:
- `test_migration_0030_preserves_inbox_rows_and_ids` (from schema 29 with item, stardust and candy rows; `user_version` 30; `PRAGMA foreign_key_check` empty)
- `test_inbox_accepts_arena_ticket_rejects_unknown_resource`
- `test_new_flags_default_off_on_existing_profiles_and_runs`
- `test_flag_checks_reject_2_and_text`
- `test_ex_items_rejects_unknown_id_and_negative_quantity`
- `test_ex_gifts_scope_guild_and_count_checks` (all with a server, server without one, 0 recipients, 11 items: each refused)
- `test_ex_gifts_has_no_user_or_recipient_column`
- `test_profile_delete_cascades_recipients_ex_items_inbox_keeps_ex_gifts`
- `test_recipient_pair_unique`

Pins move only by version 30 and the new tables and columns: `tests/test_arena_schema.py` (version at :72, :122, :154, :206; pop the four columns in the upgrade comparisons), `tests/test_capacity.py:72-86` and `tests/test_trading_schema.py:85-100` (pop the profile flags), `tests/test_receipt_owner.py` `legacy_schema` (:57-100; drop the new tables and columns when rebuilding the old schema).

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_gift_schema`, `arena_schema`, `capacity`, `trading_schema`, `receipt_owner`, `db`, `deletion`, `milestones`, `pokemon_forms`, `route_unlocks`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `0030` is taken (renumber, report it); an existing migration or `db/__init__.py` needs an edit; the rebuild fails under `foreign_keys=ON`; a pin fails for another reason.

**Do not touch.** Migrations 0001-0029; `db/__init__.py`; `services/**`; `bot/**`.
