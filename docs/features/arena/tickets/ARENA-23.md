# ARENA-23 — Leaderboard screen, Arena and inbox settlement calls, inbox label; help

**Tier:** seam (interaction responses)

**Read:** PLAN D16, D18; AR-35a, AR-38..41; ARENA-13, 22; `bot/arena.py` `render_home`, `dispatch`; `bot/milestones.py` `_gym_labels`, `inbox`.

**Goal.** Arena home opens a private Leaderboard; Arena and inbox settle when opened; inbox names the payout. C5 first.

- **Button** `Leaderboard` (`arena_leaderboard`) on the Arena home, between Tickets and Back. Never disabled: Arena off, live run, cooldown and pause included.
- **Dispatch** (`bot/arena.py`): after the stale/excluded check, `await service.settle(conn, session['guild_id'], now)`, for every action that reaches it (`arena_until_hurt` returns first). A later refusal in that press rolls the payout back; the next open pays.
- **Action `arena_leaderboard`:** keeps the selection and renders `render_leaderboard(state)` (pure) from `service.leaderboard` and `rules.leaderboard`. Title `Arena leaderboard`, then:
  - `Month <YYYY-MM> · resets in <d>d <h>h <m>m` (minutes rounded up);
  - `<place>. <@user_id> · floor <n>` per row, or `No floors cleared this month yet.`;
  - `Your place: <place> · floor <n>` when the read returns `viewer`;
  - `1st: Master Ball, Shiny Lure, World Legendary Ticket` and the `2nd:` and `3rd:` lines, then `Rewards need floor 10 or higher.` (names and floor from the table);
  - `Last month (<YYYY-MM>):` and its paid places in the row format (a deleted or excluded winner's place stays empty), or `Last month (<YYYY-MM>): no rewards paid.`;
  - Back (`arena`).
- **Mentions:** `<@user_id>` as `bot/gyms.py` `render_list`; the router sends every edit with `AllowedMentions.none()`, so nobody is pinged.
- **Inbox** (`bot/milestones.py`): `inbox` calls `settle(conn, session['guild_id'], walker.clock())` before reading the waiting rows. `_gym_labels`: `arena_month:<YYYY-MM>:<1|2|3>` → `Arena leaderboard <YYYY-MM>: 1st place` (`2nd`, `3rd`); any other `arena_month:` key → `Arena leaderboard reward`. No query; no raw key shows; the `arena:` branch is unchanged.
- **Help** (`content/help.md`, Arena rewards): the monthly server leaderboard, best floor, UTC months, the tie rule, the floor-10 minimum, the three rewards, the Inbox payout. Update the pin `test_approved_text_verbatim`.
- **C5:** append "Arena leaderboard (ARENA-23)".

**Files.** Production: `pokewalker/bot/arena.py`, `pokewalker/bot/milestones.py`. Docs: `content/help.md` (D16). Tests: `tests/test_arena_screens.py`, `tests/test_milestones.py`, `tests/test_readme.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_arena_screens.py`:
- `test_home_leaderboard_button_enabled_in_every_state`
- `test_leaderboard_lists_top_ten_mentions_and_viewer_below`
- `test_leaderboard_shows_reset_rewards_and_minimum`
- `test_last_month_skips_deleted_winner`
- `test_empty_month_and_unpaid_last_month_texts`
- `test_arena_actions_settle_once_also_with_arena_off`
- `test_leaderboard_through_router_sends_no_pings` (`ArenaRouterTests`)
- `test_refused_press_rolls_back_payout_next_open_pays_once` (no payout rows after `_Refused`)

In `tests/test_milestones.py`:
- `test_inbox_open_settles_and_lists_reward`
- `test_arena_month_keys_get_place_labels_else_generic`

In `tests/test_readme.py`: `test_help_describes_monthly_leaderboard`.

Pinned tests change only by the new action, button and renderer.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). Commands: `python -m unittest discover -s tests -p "test_<m>.py"` for `arena_screens`, `milestones`, `readme`, `walker_router`; `git -c core.whitespace=cr-at-eol diff --cached --check` (keep CR line ends in `bot/milestones.py` and `tests/test_milestones.py`).

**Stop if.** A service change is needed (ARENA-22 first); `bot/walker.py`, `bot/screens.py` or `services/milestones.py` needs a change; over 300 production lines.

**Do not touch.** `services/**`, `bot/walker.py`, `bot/screens.py`, `bot/bag.py`, `domain/arena.py`.
