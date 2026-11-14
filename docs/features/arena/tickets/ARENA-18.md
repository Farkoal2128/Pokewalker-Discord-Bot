# ARENA-18 — `bot/arena.py`: skip select, auto-order toggle, stop threshold

**Tier:** seam (interaction responses)

**Read:** PLAN D4, D13, D19; AR-4a, AR-10a, AR-10b, AR-10d, AR-34; ARENA-11, 12, 16, 17; `bot/arena.py` `render_team`, `render_break`, `open_break`, `break_action`, `dispatch`.

**Goal.** M2 controls that only call existing services; Fight until hurt is ARENA-24. C5 first.

- **Team picker** (`render_team`; rows 0-2 are in use):
  - The selection gains `skip`, 0 when `arena_team` opens it; an M1 selection without it reads as 0 (`get('skip', 0)`). `S = domain.max_skip(best_floor, rules)`.
  - `S > 0`: row 3 select `arena_skip`, `k = 0..min(S, 24)`: "No skip", then "Skip k floors: start at floor k+1". `S >= 25`: row 4 select `arena_skip_more`, `k = 25..S`, because one select holds 25 options. The saved `k` is the default option of the select that holds it. `S = 0`: neither select.
  - A press must carry one value that is an integer in `0..S`, else `_Refused(REOPEN)`. It saves `skip` and redraws; picks, page and sort are kept.
  - With `skip > 0` the embed says "Skipping k floors pays now: 2 Bronze, 4 Silver, 2 Gold." from `domain.skip_tickets` ("nothing" when empty).
  - `arena_start` passes `skip=selection['skip']` to `service.start`. On `started` with a skip, the break opens with the notice "Skipped k floors: +2 Bronze, +4 Silver, +2 Gold Tickets." A `live` result shows no notice.
- **Break screen** (`render_break`; rows 1-3 unchanged):
  - Row 0: Fight, Heal all & fight, `Auto-order: off|on` (`arena_auto_order`), Back out. ARENA-24 adds Fight until hurt before the toggle, which fills the row.
  - Row 4: select `arena_stop_pct`, "Stop below 10%" .. "Stop below 90%" from `service.STOP_PCTS`, the saved value as default.
  - The break state carries `stop_pct` and `auto_order` from `service.state`.
- **Actions.** Both join `BREAK_ACTIONS`, so they use the saved `run_id` and `run_revision`:
  - `arena_stop_pct`: one value in `STOP_PCTS`, else `_Refused(REOPEN)` → `service.set_stop_pct`.
  - `arena_auto_order`: `service.set_auto_order` with the opposite of the current flag.
  - `set` → redraw, saving the new revision; `stale` → STALE redraw, nothing saved.
- The registry (`handlers` return) and the team-phase guard gain `arena_skip` and `arena_skip_more`.

**Files.** Production: `pokewalker/bot/arena.py`. Tests: `tests/test_arena_screens.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first:
- `test_skip_select_hidden_at_best_floor_below_2`
- `test_skip_select_lists_0_to_s_and_second_select_from_25`
- `test_skip_choice_persists_across_paging_and_shows_paid_tickets`
- `test_skip_value_out_of_range_or_malformed_refused`
- `test_start_with_skip_opens_break_at_next_floor_with_ticket_notice`
- `test_break_layout_has_toggle_in_row_0_and_threshold_in_row_4`
- `test_threshold_select_saves_and_marks_default`
- `test_auto_order_button_toggles_label_and_setting`
- `test_setting_from_stale_screen_redraws_without_saving`
- `test_other_open_screen_must_redraw_after_setting_change`
- `test_settings_shown_again_on_next_run`
- `test_m1_team_selection_without_skip_starts` (`ArenaRouterTests`)

Pinned tests change only by the new names and rows: `test_action_names_match_router_pattern`, `test_break_screen_layout_rows_and_disabled_heal_at_full_hp`, `test_views_within_5_rows_unique_custom_ids` (break rows 0-4; a team view with both skip selects); `test_team_picker_pages_and_sorts_favorites_first` (selection gains `skip: 0`).

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=final feature (G-F)`. Commands: `python -m unittest discover -s tests -p "test_arena_screens.py"`, `git diff --check`.

**Stop if.** A control needs a service change (ARENA-16/17 first); a view needs a sixth row or row-0 button; over 300 production lines.

**Do not touch.** `services/arena.py`, `domain/arena.py`, `bot/walker.py`, `bot/screens.py`, `content/help.md` (ARENA-24).
