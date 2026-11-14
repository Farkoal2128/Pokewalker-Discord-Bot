# ARENA-10 — ticket redemption and the shared gym roll helper

**Tier:** seam (persisted player state; item and encounter tables)

**Read:** PLAN D11, D12; REQUIREMENTS AR-25..AR-30, AR-35a; ARENA-4, ARENA-8; `gyms.py` `pay_hours` :107, `end_deployment` :137; `stepping.spawn_encounter` :65; `items.checkin` :137-143; `milestones.claim` :131.

**Goal.** Redeem a ticket for encounters and inbox rewards, reusing the gym rolls. C3 "Arena tickets and redemption" first.

- **Roll helper in `services/gyms.py`** (no behavior change):
  - `income_roll(conn, profile_id, key, now, rng, content)`: one weighted `gym_income_table` roll, `items.resolve_item`, one `inbox_items` row under `key`. Extracted from `pay_hours` :119-127.
  - `survivor_roll(conn, profile_id, key, now, rng)`: one `survivor_table` roll plus `stardust_flat`, two rows under `key`. Extracted from `end_deployment` :151-158.
  - `pay_hours` and `end_deployment` call them with their existing keys. The order of rng calls is unchanged, so the seeded gym tests pass without edits.
- **`arena.redeem_quote(conn, profile_id, tier)`** → `{'held', 'free', 'add'}`: `free = limits()['encounter_queue'] - profiles.queue_size(...)`; `add = min(free, n)`, `n` being the tier's `encounters` (`"fill"` = the queue size).
- **`arena.redeem(conn, session, tier, expected_free, expected_add, now, rng, content)`**:
  1. `session_owner` → `stale` / `excluded`. Paused members may redeem, as may members of a server with the Arena off (AR-35a, D12).
  2. `held < 1` → `none`; `free < 1` → `queue_full`; `free != expected_free` or `add != expected_add` → `{'status': 'quote_changed', 'free', 'add'}` (a Silver quote at 3 free is refused at 2 free). Each spends nothing, not even a Lure/Mirror charge (AR-28).
  3. Receipt `arena_redeem:<session_id>:<_original_revision>` with `profile_id`: `redeem_id = uuid4()`; decrement the ticket; ledger line `arena_ticket` / tier / `-1` / `arena_redeem`; `spawn_encounter(...)` `add` times (as walking, AR-27); inbox rows `arena:<redeem_id>:stardust` (flat Stardust), `arena:<redeem_id>:income:<n>` via `income_roll`, `arena:<redeem_id>:survivor:<n>` via `survivor_roll` → `redeemed` with the counts.
- `milestones.claim` still delivers: rare pockets and a full bag keep rows in the inbox (AR-29a). No ticket cap (AR-30).

**Callers** (`git grep -n "pay_hours\|end_deployment" -- pokewalker`): `services/gyms.py:148,183,194,344`, `bot/gyms.py:385,398`, `bot/mod.py:75,137`. None changes.

**Files.** Production: `pokewalker/services/gyms.py`, `pokewalker/services/arena.py`. Tests: `tests/test_arena.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests in `tests/test_arena.py` pass, RED first:
- `test_bronze_adds_one_encounter_and_100_stardust_row`
- `test_silver_adds_up_to_two_encounters_and_gold_fills_queue`
- `test_platinum_and_diamond_roll_counts_and_survivor_rows_with_500_stardust`
- `test_redeem_refused_when_queue_full_nothing_spent`
- `test_quote_changed_spends_no_ticket_and_no_lure_charge`
- `test_same_redeem_press_twice_one_redemption`
- `test_inbox_keys_use_redeem_id_and_claim_respects_rare_pockets`
- `test_paused_and_arena_off_can_redeem_excluded_cannot`
- `test_redeem_receipt_and_ledger_carry_profile_id`

Existing `test_gyms`, `test_gym_mod`, `test_gym_screens`, `test_milestones` pass unchanged.

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_arena.py"`, `-p "test_gyms.py"`, `-p "test_gym_mod.py"`, `-p "test_gym_screens.py"`, `-p "test_milestones.py"`, `git diff --check`.

**Stop if.** A seeded gym test changes outcome after the extraction (restore the rng order, never edit the test); `spawn_encounter` or `claim` needs an edit; over 300 production lines.

**Do not touch.** `services/stepping.py`, `services/milestones.py`, `services/items.py`, gym payout keys.
