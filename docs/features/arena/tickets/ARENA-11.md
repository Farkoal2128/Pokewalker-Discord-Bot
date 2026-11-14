# ARENA-11 — `bot/arena.py`: Arena home, team picker, run start

**Tier:** seam (interaction responses)

**Read:** PLAN D13; REQUIREMENTS AR-1..AR-8, AR-14a (picker warning), AR-15, AR-35a; ARENA-8; `bot/gyms.py` `render_deploy`, `render_party`, `sort_label`, `handlers`; `bot/walker.py` `CUSTOM_ID` (:27), `_Refused`; `bot/screens_catch.py` `custom_id`.

**Goal.** New screen module in the `bot/gyms.py` shape: pure renderers (no I/O) plus `handlers(walker)` returning the action map. The map is **not registered** until ARENA-15; tests call it directly. Action names use letters and underscores only (`CUSTOM_ID` is `[a-z_]+`). C5 "Arena screens" first.

- **`arena` (Arena home):** `service.state`. Lines: status, best floor, tickets.
  - off: "The Arena is turned off in this server." A live run stays playable.
  - live: "Run in progress: floor N, entry|middle|boss fight." Button `Resume` (`arena_resume`).
  - cooldown: "Next run in Xh Ym." Ready: `Start run` (`arena_team`), enabled only when on, not paused, with no live run and no cooldown.
  - Always: `Tickets (n)` (`arena_tickets`; disabled until ARENA-13) and `Back` (`home`).
- **Team picker:** actions `arena_team`, `arena_team_prev`, `arena_team_next`, `arena_team_sort`, `arena_team_pick`, `arena_team_clear`, `arena_start`. Selection `{'phase': 'arena_team', 'team': [[uid, revision], ...], 'offset', 'favorites_first'}`.
  - Pages come from `storage.page(conn, profile_id, offset, favorites_first=...)` with the gym toggle label (`gyms.sort_label`, `bot/gyms.py:89`), as the gym pickers do (:220, :344).
  - Each row: name · CP · types; gym defenders read `unavailable: deployed`. The companion and special Pokémon are selectable.
  - A pick must be on the page, eligible and distinct; picks fill up to 3. `Clear` empties the team.
  - Each picked special Pokémon (`domain.is_special`) adds one line: "<name> is a special Pokémon: it only earns Candy from boss knockouts." It never blocks (AR-6).
  - `Start` is disabled until 3 are picked.
- **`arena_start`:** `service.start` with the saved list. `started` → the break screen. Refusals keep the picker with a notice: `stale` → "A Pokémon changed. Pick your team again."; `deployed` → "A gym defender can't join an Arena team."; `cooldown` → the wait; `paused` → the check-in wording; `off` → the off line; `live` → that run's break screen.
- **Break screen, read-only part** (`arena_resume`, and after `started`): the next enemy's species, types, CP and sprite (never level or IVs, AR-15), each member in party order with HP / full HP, and `Back out` (`arena`). Selection `{'phase': 'arena_break', 'run_id', 'run_revision'}`. ARENA-12 adds the actions.
- An ended run reads "Your last run ended on floor N." on the Arena home; ARENA-12 adds the defeat screen.

**Files.** Production: `pokewalker/bot/arena.py`. Tests: `tests/test_arena_screens.py` (new). Contract: `contracts/discord-commands.md`.

**Accept.** Tests pass, RED first:
- `test_arena_home_states_off_live_cooldown_ready`
- `test_team_picker_pages_and_sorts_favorites_first`
- `test_picker_marks_gym_defender_unavailable_allows_companion`
- `test_pick_three_distinct_then_start_enabled`
- `test_special_pick_shows_boss_only_candy_warning_and_does_not_block`
- `test_start_opens_break_screen_with_enemy_species_types_cp_only`
- `test_start_refusals_keep_picker_with_reason`
- `test_resume_shows_same_enemy_and_hp_after_back_out`
- `test_action_names_match_router_pattern`
- `test_render_functions_do_no_io`

**Verify.** `Verification: phase=implementation; scope=focused; coverage=tests above; receipt=Tests-Focused on staged tree; boundary=increment M1 (G-M1)`. Commands: `python -m unittest discover -s tests -p "test_arena_screens.py"`, `git diff --check`.

**Stop if.** The screens need a change to `bot/walker.py`, `bot/screens.py` or `services/storage.py`; a view needs more than 5 rows; over 300 production lines (move the read-only break screen to ARENA-12).

**Do not touch.** `bot/gyms.py`, `bot/walker.py`, `bot/screens.py`.
