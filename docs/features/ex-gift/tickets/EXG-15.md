# EXG-15 — screens: arm from EX-Gift; EX lines and X block on the break screen

**Tier:** seam (interaction responses)

**Read:** PLAN D7; SYNTHESIS EX-14, EX-15, EX-19, R9, R10; EXG-9, EXG-11 (Use button rows), EXG-14; `bot/arena.py` `render_break` (:209-240: X lines :218-221, X buttons :235-240), `break_action` X notices (:392-397).

**Goal.** Players arm EX-Attack and EX-Defense from EX-Gift and see a run's EX boost on the break screen, where the matching X-item is blocked. The team-screen buttons come in EXG-19. C5 first.

- **`bot/ex_gift.py`:**
  - `Use EX-Attack (<n>)` (`ex_arm_ex_attack`) and `Use EX-Defense (<n>)` (`ex_arm_ex_defense`) while held and not armed; an armed kind shows `EX-Attack armed for your next Arena run.` instead of its button. Armed flags come from `profiles.get_profile`.
  - The handler calls `arena_service.arm`: `armed` → `EX-Attack armed: ×2 attack for your whole next Arena run. A run in progress does not get it.`; `armed_already` → `EX-Attack is already armed. Nothing was spent.`; `missing` → `You have no EX-Attack.`; `excluded` → `EXCLUDED`; `stale`, `invalid` → `REOPEN`. The multiplier text comes from `rules.x_items.multiplier`, the stat from `rules.ex_items`.
- **`bot/arena.py`:**
  - `render_break`: after the X lines, `EX-Attack: ×2 attack · whole run` for each EX flag set on the run.
  - The row-1 X button whose X-item an EX flag blocks is disabled with label `X-Attack: EX-Attack active`; the other kind is unchanged.
  - `break_action`: status `ex_active` → notice `EX-Attack is active for this run, so X-Attack can't be used. Nothing was spent.` and the break redraws. The defeat screen does not change.
- **C5:** EX-Gift arm buttons and notices; break-screen EX lines and the blocked X button.

**Files.** Production: `pokewalker/bot/ex_gift.py`, `pokewalker/bot/arena.py`. Tests: `tests/test_ex_gift_screens.py`, `tests/test_arena_screens.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_ex_gift_screens.py`:
- `test_arm_buttons_only_while_held_and_unarmed`
- `test_arm_notice_then_armed_line`
- `test_arm_already_and_missing_notices`
- `test_arm_with_live_run_notice_and_run_unchanged`

In `tests/test_arena_screens.py`:
- `test_break_shows_ex_lines_for_each_flag`
- `test_matching_x_button_disabled_other_kind_free`
- `test_stale_x_press_during_ex_run_spends_nothing`

Existing Arena screen tests pass unchanged (no flag set means no new line or label).

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_gift_screens`, `arena_screens`, `walker_router`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A service change is needed (EXG-14); the break view needs a sixth row or button in a row; over 300 production lines.

**Do not touch.** `services/**`, other `bot/` modules; the team screen (EXG-17, EXG-19).
