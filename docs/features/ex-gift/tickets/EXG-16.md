# EXG-16 — service: Arena EX-Voucher start

**Tier:** seam (persisted player state; progression rules)

**Read:** PLAN D4, D8; SYNTHESIS EX-16, EX-20, EX-26 and its recorded reading, the Q4 reading, R7, R12; EXG-1 (`voucher_floor`), EXG-8 (`recorded`), EXG-14 (flag hand-over in `start`); `services/arena.py` `start` (:139-193), boss win (:366-383); `domain/arena.py` `ticket_for` (:103), `first_clear_bonus` (:141).

**Goal.** The voucher starts a run on floor 81 and pays floors 1-80 as real first clears, in the run-start transaction. Normal skips stay validated as today. C3 first.

- **`start(…, skip=0, voucher=False)`**: with `voucher`, right after the `stale`/`excluded` check, `ex_gift.recorded(conn, <start key>, 'arena_start', pid)` is returned when found, with `run` attached as `start` does (D4): a replay reports `started`, not `live`. The existing refusals then run unchanged (paused, off, live, cooldown: the voucher obeys the new-run cooldown). Then with `voucher`: `skip != 0` → `invalid`; none held (`ex_gift.held`) → `no_voucher`; then the team checks. Without `voucher` nothing changes: a normal replay still returns `live`, and `start(skip=79)` stays `invalid` (`:153`).
- **Voucher `compute`** (same receipt key `arena_start:<session>:<rev>`):
  - the run starts on `voucher_floor + 1` (81), its entry enemy rolled for that floor;
  - for each floor 1..`voucher_floor` with a ticket: 1 + `first_clear_bonus(floor, current['best_floor'], rules)` copies, upserted into `arena_tickets` as `start` does, ledger `arena_ticket / <tier> / +n / arena_voucher`;
  - `UPDATE profiles SET arena_best_floor=MAX(arena_best_floor, voucher_floor)` (unlocks the 40-floor skip);
  - `ex_gift.take(…, 'arena_ex_voucher')`, ledger `ex_item / arena_ex_voucher / -1 / arena_voucher`;
  - the EXG-14 armed-flag hand-over;
  - no `arena_month_scores` write: scores come from boss wins, first on floor 81 (EX-20).
  - Result `{'status': 'started', 'voucher': True, 'tickets': {tier: copies}}` plus `run` as today.
- **C3:** amend the Arena lifecycle with "EX-Voucher start".

**Files.** Production: `pokewalker/services/arena.py`. Tests: `tests/test_arena.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests in `tests/test_arena.py` pass, RED first:
- `test_voucher_from_best_0_pays_first_clears_starts_floor_81` (bronze 2, silver 8, gold 12, platinum 6, diamond 2)
- `test_voucher_from_best_50_pays_first_clear_only_above_it` (2, 4, 9, 5, 2)
- `test_voucher_at_max_skip_best_100_pays_base_keeps_best` (2, 4, 6, 3, 1; best stays 100)
- `test_voucher_raises_best_to_80_max_skip_40`
- `test_voucher_refusals_keep_voucher_and_write_nothing` (none held, cooldown, paused, off, live run, skip 1, invalid team)
- `test_voucher_run_first_boss_win_scores_floor_81`
- `test_voucher_replay_returns_started_after_run_is_live` (equal result, spent once)
- `test_normal_start_replay_unchanged`
- `test_voucher_start_moves_armed_flags`
- `test_voucher_run_obeys_next_cooldown`
- `test_normal_skip_still_capped` (`skip=79` → `invalid`)

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `arena`, `arena_domain`, `arena_screens`, `ex_items`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `domain/arena.py` or a balance table needs a change; a normal-start test must change; over 300 production lines.

**Do not touch.** `domain/**`, `bot/**`, other services.
