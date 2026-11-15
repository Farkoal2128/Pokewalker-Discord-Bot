# EXG-19 — Arena team screen: EX-Attack/EX-Defense buttons, armed lines; help

**Tier:** seam (interaction responses)

**Read:** PLAN D7, D11; SYNTHESIS EX-14, EX-15, EX-19, EX-23, EX-24, R10; EXG-14, EXG-15 (arm notices), EXG-17 (team state, row 2); `bot/arena.py` `render_team` (:132-176), dispatch `arena_team` phase (:505-556), registry (:558-561); `tests/test_readme.py` `test_approved_text_verbatim` (:41), `test_pages_within_limit_last_is_admin` (:84).

**Goal.** The team screen arms EX boosts for the run about to start and says when one is armed; the help explains EX-Gift. Last row. C5 first.

- **`bot/arena.py`:**
  - `team_state` adds both armed flags (`profiles.get_profile`).
  - `render_team` row 2, after the voucher button: `EX-Attack` (`arena_arm_ex_attack`) and `EX-Defense` (`arena_arm_ex_defense`), each only while held and not armed. An armed kind shows the line `EX-Attack armed: ×2 attack for this whole run.` instead (R10). Row 2 holds at most Clear, Start, voucher, EX-Attack, EX-Defense; rows 3-4 stay the skip selects.
  - Dispatch both actions in the `arena_team` phase: `service.arm`, the EXG-15 notices, then redraw the team screen with the same team and skip. Register them. Resume never shows the team screen (`:496-498`), so a live run never offers them.
- **Help** (`content/help.md`, a player page before the admin page; counted as docs): EX-Gift receives owner event gifts, shows (!) while a gift waits, never expires; Claim sends ordinary items and Arena Tickets to the Inbox and keeps EX-items with no limit; EX-items cannot be traded; one line per EX-item with where it is used (EX-Gift; details for Shiny Patch and Golden Bottlecap; the team screen for EX-Attack, EX-Defense and the voucher); EX boosts arm for the next new run only; the voucher pays floors 1-80 and starts on 81. If the page passes 4096 units, add a page before the admin page, keeping the gym sentence on page 3.
- **C5:** team-screen EX buttons and armed lines; help text.

**Files.** Production: `pokewalker/bot/arena.py`. Docs: `content/help.md`. Tests: `tests/test_arena_screens.py`, `tests/test_readme.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first. In `tests/test_arena_screens.py`:
- `test_team_arm_buttons_only_while_held_and_unarmed`
- `test_team_armed_line_replaces_button`
- `test_team_arm_keeps_team_and_skip_and_notices`
- `test_full_team_screen_with_every_ex_button` (serialized: row 2 five buttons, max-skip rows 3-4)
- `test_armed_from_team_screen_applies_to_started_run`

In `tests/test_readme.py`: `test_help_describes_ex_gift` (phrases: `EX-Gift`, `(!)`, `Inbox`, `no limit`, `cannot be traded`, each EX-item name, `next new run`, `floor 81`).

Pins move only by the new actions and text: `test_action_names_match_router_pattern` (two actions), `test_approved_text_verbatim` (new hash).

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `arena_screens`, `readme`, `ex_gift_screens`, `walker_router`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A service change is needed; row 2 would need a sixth button; another help pin moves; over 300 production lines.

**Do not touch.** `services/**`, other `bot/` modules.
