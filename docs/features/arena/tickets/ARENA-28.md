# ARENA-28 — `bot/arena.py`: X-item buy and use on the home and break screens; help

**Tier:** seam (interaction responses)

**Read:** PLAN D13, D16, D20; AR-43..45; ARENA-12, 24, 26, 27; `bot/arena.py` `render_home`, `render_break`, `open_break`, `break_action`, `dispatch`.

**Goal.** Buy on the Arena home and the break screen, use during a break, see what is active. C5 first.

- **Names** `X-Attack`, `X-Defense`. **Actions** `arena_buy_x_attack`, `arena_buy_x_defense`, `arena_use_x_attack`, `arena_use_x_defense`, all registered; the `use` pair joins `BREAK_ACTIONS`. Price, fights and multiplier come from `rules.x_items`.
- **Stock line** on both screens, from `state`: `Stardust <n> · X-Attack ×<held> · X-Defense ×<held>`.
- **Home** (`render_home`): the stock line, a `notice` line, and on row 1 `Buy X-Attack · 300` and `Buy X-Defense · 300`, enabled in every home state (Arena off, live run, cooldown, pause).
- **Break** (`render_break`): after the party lines the stock line, then per active kind `X-Attack: ×2 attack · <n> fights left` (`1 fight left`). Row 1, after the three heals, has one button per kind, because every other row is full:
  - counter above 0 → `X-Attack: <n> fights left`, disabled (use action);
  - else held → `Use X-Attack (<held>)` (use action);
  - else → `Buy X-Attack · 300` (buy action; stock up on the home).
- **Buy** (`dispatch`, after `settle`; it needs no run): `service.buy_x`, re-read `state`, redraw where the press came from: phase `arena_break` with a run → `open_break` (an ended run shows its defeat screen), else the home. Notices: `Bought 1 X-Attack for 300 Stardust.`; `insufficient` → `You need 300 Stardust for X-Attack. Nothing was spent.`; `bag_full` → `Your bag is full. Nothing was spent.`; `stale`, `excluded` → the existing refusals.
- **Use** (`break_action`): `service.use_x(*args, item, now)`. Notices: `X-Attack used: ×2 attack for the next 3 fights.`; `active` → `X-Attack is already active. Nothing was spent.`; `missing` → `You have no X-Attack.`; `stale` → `STALE`.
- A chain renders through `open_break`, so it shows the counters after each fight. The defeat screen has no X-item line.
- **Help** (`content/help.md`, Arena): what each item does, 3 fights, one of each kind at a time, the price, where to buy and use, unused fights lost when the run ends. Update the pin `test_approved_text_verbatim`.
- **C5:** append "Arena X items (ARENA-28)".

**Files.** Production: `pokewalker/bot/arena.py`. Docs: `content/help.md` (D16). Tests: `tests/test_arena_screens.py`, `tests/test_readme.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_arena_screens.py` (bump `session['revision']` per buy press, as the router does):
- `test_home_stock_line_and_buy_buttons_in_every_state`
- `test_home_buy_notices_bought_short_and_bag_full`
- `test_break_row_1_x_button_buy_then_use_then_fights_left`
- `test_break_buy_stays_on_break_keeps_run_revision`
- `test_use_shows_active_line_bumps_run_revision`
- `test_fights_count_lines_down_button_free_at_zero`
- `test_both_kinds_active_together`
- `test_stale_break_use_spends_nothing_and_redraws`
- `test_until_hurt_chain_shows_counters_each_fight`
- `test_buy_twice_through_router_spends_twice` (`ArenaRouterTests`)

In `tests/test_readme.py`: `test_help_describes_x_items`.

Pins move only by the new actions, buttons and lines (`test_action_names_match_router_pattern`: four actions).

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `arena_screens`, `readme`, `walker_router`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A service change is needed (ARENA-26, 27 first); another `bot/` module needs a change; a view needs a sixth row or a sixth button in a row; the 15-fight chain embed no longer fits; over 300 production lines.

**Do not touch.** `services/**`, `domain/**`, every other `bot/` module.
