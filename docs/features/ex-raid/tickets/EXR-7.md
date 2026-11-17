# EXR-7 — catch screens say EX-Raid; Back with both raids

**Tier:** seam (interaction responses)

**Read:** PLAN D10; SYNTHESIS XR-5, R8, §7 (Back cases); EXR-2, EXR-3; `bot/walker.py:400-436, :438-472, :505-520, :580-590`; `bot/screens_catch.py:17-40`; C5 "M8.1c raid encounter Back and Run", "M8.3b private World Legendary join and reopen"; `tests/test_raids.py` `RaidWalkerTests` (:19-292, fixtures).

**Goal.** Every catch-path string of an EX encounter says EX-Raid, also for a Legendary boss; World Legendary strings do not change. Back keeps returning to the **selected** raid encounter when a player holds both. C5 first.

- **`encounter_state`** (:458-465): the spawn read takes `expires_at, kind`; state gains `raid_kind` (`world`, `ex` or None). The raid line is `EX-Raid · ends <UTC>` for `ex`, else `World Legendary · ends <UTC>`.
- **`screens_catch._embed`** (:23-25): the tier text is `EX-Raid` when `state.get('raid_kind') == 'ex'`, else `encounter['tier'].title()` as today. This covers the catch, confirm and result screens.
- **`run`** (:516-520): the expiry check also reads the kind; an expired EX spawn refuses with "The EX-Raid left.", a World Legendary with today's text.
- **`throw`** (:587): the `expired` notice is "This EX-Raid ended; this encounter expired." for `ex`, else today's text.
- No button, custom ID or selection key is added. `open_encounter` (:409-415) already reopens the selected raid encounter by its own spawn; it is not edited.
- **C5:** amend "M8.1c" and "M8.3b": the wording by kind; Back with two raid encounters returns to the selected one and never to the other.

**Files.** Production: `pokewalker/bot/walker.py`, `pokewalker/bot/screens_catch.py`. Tests: `tests/test_ex_raid_screens.py` (new). Contract: `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_ex_raid_screens.py` pass, RED first:
- `test_ex_catch_screen_shows_ex_raid_line_and_tier_for_a_legendary_boss`
- `test_ball_and_berry_rerenders_keep_the_ex_raid_line`
- `test_confirm_and_result_screens_show_ex_raid_tier`
- `test_run_after_ex_expiry_says_the_ex_raid_left`
- `test_throw_after_ex_expiry_says_this_ex_raid_ended`
- `test_world_legendary_screens_and_refusals_unchanged`

Coverage of existing behavior (expected to pass on first run; a failure is a finding, stop):
- `test_back_from_master_ball_shiny_run_and_storage_confirm_returns_to_selected_raid` (both raids joined, an ordinary encounter queued; items and rolls kept; the other raid's encounter untouched; both directions)
- `test_back_after_selected_spawn_expired_follows_the_m81c_fallback` (before and after cleanup: the ordinary queue, or Home with an empty queue; confirmation flags cleared; the other raid untouched)

`tests/test_raids.py`, `tests/test_walker_encounter.py`, `tests/test_screens.py`, `tests/test_share.py` and `tests/test_capacity.py` pass unchanged: the World Legendary strings pinned at `tests/test_raids.py:199, :237, :1659, :1678` stay. No command or button is added: no manifest, subcommand-set, component-count or schema pin moves.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_raid_screens`, `raids`, `walker_encounter`, `walker_router`, `screens`, `share`, `capacity`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A Back coverage test fails (report it; a fix to `open_encounter` is a new row); an ordinary encounter's screen changes; `services/**` needs an edit; over 300 production lines.

**Retry ruling (owner, 2026-11-16).** Fixture-only first-run errors may be repaired; use storage limit 250 with 250 owned. A production Back failure still stops immediately; no production fix is authorized for coverage-only tests.

**Do not touch.** `services/**`, `bot/raid.py`, `bot/bag.py`, other `bot/` screens.
