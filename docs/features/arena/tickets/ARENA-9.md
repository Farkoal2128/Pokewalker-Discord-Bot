# ARENA-9 — `services/arena.py`: fight, Heal all & fight, Candy, ticket credit

**Tier:** seam (persisted player state; progression rules)

**Read:** PLAN D4-D6; REQUIREMENTS AR-3, AR-4a, AR-9..AR-11b, AR-13, AR-14, AR-14a, AR-31..AR-33; ARENA-1, ARENA-3, ARENA-8; `services/gyms.py` `battle` (:332-351); `services/stepping.py` candy upsert (:154-158).

**Goal.** Resolve one fight per press with HP carry-over. C3 first.

- **`fight(conn, session, run_id, revision, now, rng, content, multipliers, battle_rules, chart)`**:
  1. `session_owner`; `state` (an over-time run ends first, so the fight is refused); the ARENA-8 stale rule.
  2. Receipt `arena_fight:<run_id>:<floor>:<slot>` (AR-4a), so one fight never resolves twice. Inside it:
     - Party: each member's snapshot `Combatant` with `hp` replaced by the current `hp` (`dataclasses.replace`), in team order. Enemy `Combatant` and `battle_hp` come from the stored enemy.
     - `battle.simulate(party, enemy, battle_hp, rules=battle_rules, chart=chart)`; `party_max` is not applied (`battle.py:98`).
     - **Not a win** (`loss` or `draw`): `hp ← party_hp`, `ended_at = now`, `end_reason = outcome`, bump `revision` → `defeated`. No Candy, no ticket.
     - **Win:** `hp ← domain.revive(party_hp)`. Candy: `domain.candy_for(finisher.special, slot)` to the finisher's snapshot `family_id` with the stepping upsert; ledger line `candy` / family / `+n` / `arena_candy`.
     - **Boss win** (slot 2): always `arena_best_floor = max(best, floor)`, next `floor + 1, slot 0`. **Only if** `tier = domain.ticket_for(floor)` is not `None`: copies = 1 (+1 if `first_clear_bonus(floor, best_floor)`), upsert `arena_tickets`, ledger `arena_ticket` / tier / `+copies` / `arena_floor`. Else next is `slot + 1`.
     - Roll and store the next enemy (ARENA-8 helper); bump `revision`.
     - Result (D5): `status`, `outcome`, `reason`, `ticks`, `engine`, `floor`, `slot`, enemy name/CP/types, `party_hp` before revive, `revived`, `finisher`, `candy`, `tickets` (`tier`, `copies`, `first_clear`). No `events`.
- **`heal_all_and_fight(..., berry, ...)`** (fight's arguments plus `berry`): positions = members below full HP. Short of berries → `missing` with `short`, nothing spent, no fight. Otherwise `heal` (skipped when nobody is hurt), then `fight` at the bumped revision, in the same transaction.
- Paused members may fight; excluded members are refused by `session_owner` (AR-8).

**Files.** Production: `pokewalker/services/arena.py`. Tests: `tests/test_arena.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests pass, RED first:
- `test_floor_1_boss_win_advances_without_ticket`
- `test_win_carries_exact_hp_into_next_fight`
- `test_fainted_member_revived_at_one_hp_keeps_position`
- `test_entry_middle_boss_order_and_next_enemy_stored_each_fight`
- `test_loss_ends_run_keeps_earlier_tickets`
- `test_draw_counts_as_defeat`
- `test_fight_after_hour_18_refused_run_expired`
- `test_same_fight_never_resolves_twice`
- `test_regular_finisher_earns_one_candy_per_win_with_ledger_line`
- `test_special_finisher_earns_candy_only_on_boss`
- `test_candy_goes_to_snapshot_family_after_mid_run_evolution`
- `test_boss_win_credits_scheduled_ticket`
- `test_first_clear_bonus_once_for_silver_or_better_not_bronze`
- `test_heal_all_and_fight_all_or_nothing_reports_short`
- `test_paused_member_can_fight_excluded_cannot`
- `test_fight_receipt_holds_no_event_text_and_has_profile_id`

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_arena.py"`, `-p "test_battle.py"`, `git diff --check`.

**Stop if.** Carried HP differs from `Result.party_hp` (never rebuild HP from events); the engine needs a change beyond ARENA-1; over 300 production lines (split `heal_all_and_fight` out).

**Do not touch.** `domain/battle.py`, `services/gyms.py`, `services/stepping.py`.
