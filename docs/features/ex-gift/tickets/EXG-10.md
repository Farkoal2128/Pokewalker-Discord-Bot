# EXG-10 — `/walker` home EX-Gift button and (!)

**Tier:** seam (interaction responses)

**Read:** PLAN D6; SYNTHESIS EX-1, EX-23 and its recorded reading; EXG-8 (`has_unclaimed`), EXG-9; `bot/screens.py` `home` (:11-39, buttons :34-38); `bot/walker.py` `home` (:231-261, state :256-261); `tests/test_screens.py:33`; `contracts/discord-commands.md` "C5: M7.4b home reward count".

**Goal.** The home screen opens EX-Gift and shows (!) while any gift is unclaimed. C5 first.

- **`bot/walker.py` `home`:** the state adds `'ex_gift_new': await ex_gift_service.has_unclaimed(conn, profile['profile_id'])`.
- **`bot/screens.py` `home`:** after the Inbox button, `EX-Gift (!)` while `ex_gift_new`, else `EX-Gift`; action `ex_gift`; disabled only when `ex_gift` is not in `available`. No count, ever (EX-23): stored and armed EX-items never bring the badge back. Nine buttons fit two rows.
- **C5:** amend the home screen: the EX-Gift button and its (!) rule.

**Files.** Production: `pokewalker/bot/screens.py`, `pokewalker/bot/walker.py`. Tests: `tests/test_screens.py`, `tests/test_ex_gift_screens.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first:
- `tests/test_screens.py`: `test_home_ex_gift_label_with_and_without_badge`, `test_home_ex_gift_enabled_when_registered`
- `tests/test_ex_gift_screens.py`: `test_badge_shows_while_unclaimed_clears_after_claim`, `test_badge_ignores_held_and_armed_ex_items`, `test_badge_per_server_profile` (a user enrolled in two servers sees each server's own state)

Pin moves only by the new button: `tests/test_screens.py:33` gains `"EX-Gift"` after `"Inbox (0)"`, and `:63`'s total moves from 8 to 9 (supervisor fix 2026-11-15; the row-and-width checks stay).

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `screens`, `ex_gift_screens`, `walker_router`, `milestones`, `route`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** Another home pin moves; the home view needs a sixth row; a service change is needed.

**Do not touch.** `services/**`; other `bot/` modules.
