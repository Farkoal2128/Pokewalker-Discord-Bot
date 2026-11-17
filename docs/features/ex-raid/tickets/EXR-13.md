# EXR-13 — player help and the `/walker-admin raids` description

**Tier:** seam (slash commands: a command description changes the global manifest)

**Read:** PLAN D10; SYNTHESIS XR-5, XR-10, R8; EXR-8; `content/help.md:49-51, :98, :107`; `bot/admin_channels.py:388`; `tests/test_readme.py:18, :41-44, :94-107`; `bot/client.py:42-52` (`load_help`); C5 "M8.1b raid configuration", "Arena team EX boosts and player help (EXG-19)" (form).

**Goal.** Help explains EX-Raids and the `/raid` chooser, and the raids switch is described as covering both kinds (XR-10). C5 first. Written last among the build rows that change behavior, so it describes what exists.

- **`content/help.md`** (LF by `.gitattributes`), three edits and nothing else:
  - after the "**Join a World Legendary.**" paragraph (:51), a new paragraph: `**EX-Raids.** Bot owners can start an EX-Raid here for any Pokémon; it lasts 1 to 24 hours. Join it once with `/raid`, like a World Legendary. When both are active, `/raid` asks which one to open, and you can join each.`
  - the "**Server raids.**" paragraph (:98) keeps its text and gains the sentence `The same switch covers owner EX-Raids.`
  - the list line (:107) becomes ``- `raids on|off <channel>`: turn raids (World Legendary spawns and EX-Raids) on in a text channel, or off.``
- **`bot/admin_channels.py:388`**: the description becomes `Enable or disable raids (World Legendary and EX-Raid) in this server`. No behavior changes: `raids off` still only clears the flag (:414), so a live raid runs to its expiry.
- **C5:** amend "M8.1b raid configuration" (the switch also decides whether the server receives EX-Raids; the new description); add "EX-Raid player help" naming the three help edits.

**Files.** Production: `content/help.md`, `pokewalker/bot/admin_channels.py`. Tests: `tests/test_readme.py`, `tests/test_admin_channels.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first:
- `tests/test_readme.py` `test_help_describes_ex_raids`: a player page holds `**EX-Raids.**`, `1 to 24 hours`, `/raid`, `asks which one to open`, `join each`; the admin page holds `owner EX-Raids` and `World Legendary spawns and EX-Raids`; no player page names `/walker-admin` or `/admin`.
- `tests/test_admin_channels.py` `test_raids_description_names_both_kinds`: the serialized `raids` subcommand carries the new description.

Pins moved:
- `tests/test_readme.py:42-44`: the whole-file SHA-256 of `content/help.md` is recomputed from the committed LF bytes.
- Global manifest hash: changes with the description. No test holds a literal hash (`tests/test_deploy_script.py:467-491` computes it).

Pins that must not move: `tests/test_readme.py:18` (page-one hash, lines 1-14), `:106` (the sentence prefix `**Server raids.** Manage Server can enable World Legendary spawns`), the 4096-unit page bound (`:99`; the two pages are 1,488 and 2,063 units at `1ac1c07`), the admin-guild manifest, the subcommand set, schema versions.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `readme`, `admin_channels`, `raids`, `client_lifecycle`, `deploy_script`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** Page one or the pinned "Server raids" prefix would change; a page passes 4096 units; `help.md` would be written with CRLF; another help paragraph needs an edit.

**Do not touch.** Other help paragraphs; `bot/raid.py`; `bot/client.py`; `README.md`; `docs/features/pokewalker-bot/**` (EXR-14).
