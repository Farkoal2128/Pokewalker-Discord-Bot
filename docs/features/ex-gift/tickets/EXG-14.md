# EXG-14 — service: EX-Attack/EX-Defense arming, run flags, boosted fights, X block

**Tier:** seam (persisted player state; progression rules)

**Read:** PLAN D1, D4, D8; SYNTHESIS EX-14, EX-15, EX-19, R9; EXG-1 (`rules.ex_items`), EXG-2, EXG-8 (`held`, `take`, `recorded`); `services/arena.py` `start` (:139-193, insert :178-180), `use_x` (:253-279), `fight` (:339-344), `chain_step` (:405); `tests/test_arena.py` X-item tests (:688-825).

**Goal.** Arming spends one EX boost; the next new run carries it for every fight; the matching X-item cannot stack on it. Screens come in EXG-15 and EXG-19. C3 first.

- **`arm(conn, session, item, now)`**, key `ex_arm:{session_id}:{rev}` (`rev` per D4): `item` not in `rules.ex_items.items` → `invalid`; `profiles.session_owner` refusal; `ex_gift.recorded(conn, key, 'ex_arm', pid)` returned as is when found (D4); then `profile['<item>_armed']` → `armed_already`; none held → `missing`; neither writes. Else `with_receipt(conn, key, 'ex_arm', compute, profile_id=…)`: `ex_gift.take`, `UPDATE profiles SET <item>_armed=1`, ledger `ex_item / <item> / -1 / ex_arm` → `{'status': 'armed', 'item'}`. Paused members, a live run and Arena off do not block arming.
- **`start`** (inside `compute`): read both armed flags, insert the run with `ex_attack` and `ex_defense` set from them, then clear both flags. Any refusal before `compute` leaves them armed; resuming a live run never reads them (EX-19); a restart keeps them (persisted). The result shape does not change.
- **`fight`**: `boosted_stats` becomes a set: the X-item stats with a counter above 0, plus `rules.ex_items.items[i].stat` for each `i` with `run[i]` set, so exactly one ×2 (`x_items.multiplier`) applies per stat. Counters, receipt and result do not change; an ended run's flags are never refunded.
- **`use_x`**: after the stale and invalid checks, a run whose EX flag names this item as `x_item` → `{'status': 'ex_active'}`, nothing spent. `buy_x` stays allowed (R9).
- **C3:** append "Arena EX boosts": arming, the hand-over at start, the fight rule, the X block.

**Files.** Production: `pokewalker/services/arena.py`. Tests: `tests/test_ex_items.py`, `tests/test_arena.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests pass, RED first. In `tests/test_ex_items.py`:
- `test_arm_spends_one_sets_flag_with_ledger`
- `test_arm_twice_refused_other_kind_independent`
- `test_arm_missing_or_excluded_refused_paused_allowed`
- `test_arm_replay_returns_armed_after_flag_set` (result equal to the first, nothing spent twice)
- `test_restart_while_armed_keeps_flag` (reopen the DB)

In `tests/test_arena.py`:
- `test_new_run_takes_armed_flags_and_clears_them`
- `test_refused_start_keeps_flags` (cooldown, paused, off, invalid team)
- `test_live_run_not_boosted_flag_waits_for_next_new_run`
- `test_ex_flag_doubles_stat_every_fight_of_the_run` (past a floor change and through `chain_step`)
- `test_ex_and_x_on_same_stat_apply_one_double`
- `test_matching_x_item_refused_ex_active_other_kind_allowed`
- `test_buy_x_allowed_during_ex_run`

Existing `tests/test_arena.py` X-item tests pass unchanged.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_items`, `arena`, `arena_screens`, `arena_schema`, `receipt_owner`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `domain/**`, the engine or a balance table needs a change; an existing Arena test must change for another reason; over 300 production lines.

**Do not touch.** `domain/**`, `bot/**`, other services.
