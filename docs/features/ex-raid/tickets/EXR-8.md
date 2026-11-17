# EXR-8 — `/raid` with two raids: chooser, wording, description

**Tier:** seam (slash commands and interaction responses)

**Read:** PLAN D7; SYNTHESIS XR-6, R5, R8; EXR-2, EXR-7; `bot/raid.py`; `bot/walker.py:29, :73-91, :145-217`; `bot/bag.py:183-186`; C5 "M8.3b".

**Goal.** `/raid` opens the only live raid directly and asks which one when a World Legendary and an EX-Raid are both live. C5 first.

- **Command:** description `Join or reopen an active raid`. Opt-out, exclusion and the pending-catch menu stay first and unchanged (:28-42).
- **By `raids.live_spawns`:** none: "No raid is active here."; unenrolled: today's enroll text; one: open it as today; two: the chooser.
- **Chooser:** a normal Walker session whose selection is `{'raid_choices': {'world': <spawn_id>, 'ex': <spawn_id>}}`. Text: "Two raids are active here. Choose one." Buttons `World Legendary: <name> · ends <UTC>` (action `raid_pick_world`) and `EX-Raid: <name> · ends <UTC>` (action `raid_pick_ex`). Actions must match `[a-z_]+` (`bot/walker.py:29`): no digits. The longest label today is 79 characters; cut at Discord's 80.
- **`handlers(walker)`** in `bot/raid.py` returns the two pick handlers. A pick reads the **saved** ID for its kind (none saved: `REOPEN`) and enters that spawn; the client never names a spawn ID.
- **Enter** (shared by the command and the picks): `raids.join` with that `spawn_id`; `none`: "That raid has ended." (also when a newer spawn of that kind is live); the encounter read of :48-55; a joined participation without a readable encounter: "You already joined this EX-Raid; it can be joined once." or today's World Legendary text, by kind; else the catch screen or the recovery result, with selection `{encounter_id, ball: poke_ball, berry: null, encounter_revision}`.
- **`bot/walker.py`:** registers `raid.handlers(self)`; both actions join the pending-catch list (:183-184). `bot/raid.py` imports walker names inside its functions, as `bot/bag.py:185` does, so no import cycle opens.
- **C5:** amend "M8.3b": description, refusal text, chooser, pick rules, EX already-joined text.

**Files.** Production: `pokewalker/bot/raid.py`, `pokewalker/bot/walker.py`. Tests: `tests/test_ex_raid_screens.py`, `tests/test_raids.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_ex_raid_screens.py` pass, RED first:
- `test_no_live_raid_says_no_raid_is_active`
- `test_one_live_raid_of_either_kind_opens_directly`
- `test_two_live_raids_show_chooser_labels_within_80`
- `test_pick_joins_that_spawn_and_player_can_join_both`
- `test_pick_after_its_spawn_ended_says_that_raid_has_ended`
- `test_pick_after_a_replacement_spawn_never_joins_it`
- `test_pick_without_saved_choices_is_refused`
- `test_double_click_joins_once`
- `test_pending_catch_made_elsewhere_shows_its_menu_first`
- `test_already_joined_text_names_the_kind`
- `test_unenrolled_excluded_and_opted_out_see_no_chooser`
- `test_description_changes_the_global_manifest_only`

Pins moved:
- `tests/test_raids.py:1646, :1649, :1829`: "No World Legendary is active here." becomes "No raid is active here."
- Global manifest hash: changes with the description. No test holds a literal hash (`tests/test_raids.py:1838-1840`, `tests/test_deploy_script.py:467-491` compute it).

Not moved: the admin-guild manifest, the subcommand set (`tests/test_client_lifecycle.py:678-680`), schema versions, the home component count (`tests/test_screens.py:63`).

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_raid_screens`, `raids`, `walker_router`, `walker_encounter`, `client_lifecycle`, `deploy_script`, `readme`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** Importing `bot.raid` from `bot.walker` fails; a pick could join a spawn not saved in the session; another World Legendary text must change; over 300 production lines.

**Do not touch.** `services/**`, `bot/screens_catch.py`, `bot/client.py`, `content/help.md` (EXR-13).
