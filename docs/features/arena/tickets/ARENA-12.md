# ARENA-12 — `bot/arena.py`: break-screen actions and results

**Tier:** seam (interaction responses)

**Read:** PLAN D4, D13; REQUIREMENTS AR-3a, AR-4a, AR-10a, AR-10c, AR-11a, AR-12..AR-15; ARENA-8, ARENA-9, ARENA-11; `bot/gyms.py` `render_view` (notice pattern), `gym_feed` notices (:386-396).

**Goal.** The break screen becomes playable: berry choice, heal, fight, Heal all & fight, party order, back out. C5 first.

- **Layout** (Discord allows 5 rows; row 4 and one row-0 slot stay free for Phase 2):
  - Row 0: `Fight` (`arena_fight`), `Heal all & fight` (`arena_heal_fight`), `Back out` (`arena`).
  - Row 1: `Heal <name>` for each member in party order (`arena_heal_one`, `arena_heal_two`, `arena_heal_three`); disabled at full HP.
  - Row 2: berry select (`arena_berry`): "Razz Berry ×n", "Pinap Berry ×n".
  - Row 3: party order select (`arena_order`): the six orders written with member names, the current one as default.
- **Selection** `{'phase': 'arena_break', 'run_id', 'run_revision', 'berry'}`, saved on every render. `berry` defaults to the type the player holds more of (Razz on a tie) and changes only through `arena_berry`.
- **Every action** passes the saved `run_id` and `run_revision` to the service (AR-4a). `stale` → redraw the current state with "The run changed on another screen. This is its current state." Nothing is spent and nothing fights.
- **Heal:** `service.heal` for one position with the selected berry. `missing` → "You have no <berry>."; `full` → redraw.
- **Heal all & fight:** `service.heal_all_and_fight`. `missing` → "You need n more <berry>. Nothing was spent." and no fight.
- **Order:** `service.set_order`; it costs nothing; the screen redraws in the new order.
- **After a win:** the break screen for the next fight, headed by a result block: enemy name and CP, outcome and ticks, each member's HP, who was revived at 1 HP, the Candy line, and on a cleared floor the ticket line ("Floor 10 cleared: Silver Ticket", plus "First clear: +1 Silver Ticket").
- **Defeat screen** (`defeated`, or a run that expired): floor and fight reached and the reason (lost / double knockout or time limit / 18 hours passed); buttons `Tickets` (`arena_tickets`) and `Back` (`arena`). There is no "give up" button (AR-3a).
- **Back out** returns to the Arena home; it writes nothing to the run.
- The enemy's level and IVs never appear on any screen (AR-15).

**Files.** Production: `pokewalker/bot/arena.py`. Tests: `tests/test_arena_screens.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first:
- `test_break_screen_layout_rows_and_disabled_heal_at_full_hp`
- `test_berry_default_is_larger_stock_and_choice_persists`
- `test_heal_spends_selected_berry_and_redraws`
- `test_mixing_berry_types_between_heal_presses`
- `test_heal_all_and_fight_reports_missing_count_spends_nothing`
- `test_fight_win_shows_result_block_then_next_enemy`
- `test_cleared_floor_shows_ticket_and_first_clear_lines`
- `test_revived_member_shown_at_one_hp_in_same_position`
- `test_order_select_reorders_party_and_persists_after_back_out`
- `test_defeat_and_expiry_show_defeat_screen_without_give_up`
- `test_stale_screen_spends_nothing_and_redraws_current_state`
- `test_second_open_screen_must_redraw_before_fighting`
- `test_enemy_level_and_ivs_never_rendered`
- `test_views_within_5_rows_unique_custom_ids`

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_arena_screens.py"`, `git diff --check`.

**Stop if.** The layout needs a fifth row in Phase 1 (Phase 2 needs it); an action needs a service change (fix it in ARENA-8/9 first); the row passes 300 production lines (split the defeat screen out).

**Do not touch.** `services/arena.py`, `bot/walker.py`, `bot/screens.py`.
