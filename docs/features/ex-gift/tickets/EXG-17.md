# EXG-17 — screens: voucher start on the team screen; EX-Gift opens it

**Tier:** seam (interaction responses)

**Read:** PLAN D7; SYNTHESIS EX-16, EX-24, EX-26, R10, R12; EXG-11 (Use button rows), EXG-16; `bot/arena.py` `render_team` (:132-176: row 2 :156-158, skip rows :166-171), `team_state` (:320-335), dispatch `arena_team` (:505-507), `arena_start` (:534-555), registry (:558-561); `tests/test_arena_screens.py` `test_action_names_match_router_pattern`.

**Goal.** A voucher holder starts a run on floor 81 from the team screen, and EX-Gift's Use opens that screen. This button is also the voucher's EX-24 button (D7). C5 first.

- **`bot/arena.py`:**
  - `team_state` adds the EX inventory (`ex_gift_service.held`) and `voucher_floor` from `rules.ex_items`.
  - `render_team` row 2, after Start: `Start on floor 81 · EX-Voucher` (`arena_voucher_start`, floor from `voucher_floor + 1`), only while a voucher is held, disabled exactly when Start is (three eligible members needed). Row 2 never exceeds five buttons; rows 3-4 stay the skip selects.
  - Dispatch `arena_voucher_start` in the `arena_team` phase: `service.start(…, skip=0, voucher=True)`; the selected skip is ignored. `started` → `open_break` with `EX-Voucher used: floors 1-80 paid +2 Bronze, +8 Silver, … Tickets. Your run starts on floor 81.` (from the result's `tickets`); `no_voucher` → `You have no Arena EX-Voucher.`; every other status as `arena_start`. Register the action.
- **`bot/ex_gift.py`:** `Use Arena EX-Voucher (<n>)` (`ex_use_arena_ex_voucher`) while held → `walker.handlers['arena_team']` (the team picker; nothing is spent until a start commits).
- **C5:** the team-screen voucher button, its notices and the EX-Gift entry.

**Files.** Production: `pokewalker/bot/arena.py`, `pokewalker/bot/ex_gift.py`. Tests: `tests/test_arena_screens.py`, `tests/test_ex_gift_screens.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_arena_screens.py`:
- `test_voucher_button_only_while_held`
- `test_voucher_button_disabled_until_three_eligible`
- `test_voucher_start_opens_break_on_81_with_ticket_notice`
- `test_voucher_ignores_selected_skip`
- `test_full_team_screen_at_max_skip_with_voucher` (serialized payload: 5 rows, row 2 three buttons, two skip selects)
- `test_no_voucher_notice_spends_nothing`
- `test_voucher_cooldown_and_paused_notices`

In `tests/test_ex_gift_screens.py`: `test_use_voucher_opens_team_picker_spends_nothing`.

Pin moves only by the new action: `test_action_names_match_router_pattern`.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `arena_screens`, `ex_gift_screens`, `walker_router`, `arena`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A service change is needed (EXG-16); the team view needs a sixth row; over 300 production lines.

**Do not touch.** `services/**`, other `bot/` modules.
