# EXR-12 — `/admin ex-raid-history`

**Tier:** seam (slash commands; rate limits)

**Read:** PLAN D8; SYNTHESIS R3 (last bullet), R4, R10; EXR-4 (`ex_history`, `ex_lookup`), EXR-11 (receipt text); `bot/admin.py:101-104`; `bot/admin_gift.py:316-375` (history by ID, `HistoryView`); C5 "EX-Gift history".

**Goal.** An owner who lost an acknowledgement checks whether a send landed, by send ID or by browsing, without spawning twice. C5 first.

- **Command** (`bot/admin.py`): `ex-raid-history` with optional text `send_id`; `if await self.authorize(interaction): await admin_ex_raid.history(self, interaction, send_id)`. It takes a 5/min token through `authorize`.
- **By ID:** a `send_id` that is not 32 lowercase hex characters, or has no row (`raids.ex_lookup` in a writer job), replies "No EX-Raid send with ID <id> was committed."; else that one entry.
- **List:** `raids.ex_history`, newest first, 10 per page, every configured owner's sends. `RaidHistoryView(admin_gift.HistoryView)` overrides `page` only and sets its expiry text to "This history expired. Run /admin ex-raid-history again."; Prev and Next are inherited (owner-bound, 900 s, the shared 30/min bucket, exclusion).
- **Entry:** send ID; UTC commit time; boss (`#<dex> <name>`); locks or "all rolled per player"; duration; target (`all servers` or `server <id>`); end time UTC; `Counts (committed)`: targeted servers, servers spawned, each skip reason with its count. Embed title "EX-Raid history". If the page passes 4096 characters, entries drop their lock line. An empty history says "No EX-Raids were sent."
- History only reads: it never spawns or announces, and it survives draft discard and restart. `ex_raids` has no player ID to show.
- **C5:** add "EX-Raid history" under M4.5a.

**Files.** Production: `pokewalker/bot/admin.py`, `pokewalker/bot/admin_ex_raid.py`. Tests: `tests/test_admin_ex_raid.py`, `tests/test_client_lifecycle.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_admin_ex_raid.py` pass, RED first:
- `test_history_parameter_optional_admin_guild_only`
- `test_history_newest_first_ten_per_page_with_boss_target_and_counts`
- `test_lookup_by_send_id_found_missing_and_malformed`
- `test_lost_ack_recovered_by_send_id_after_the_draft_is_gone`
- `test_send_recovered_by_id_after_restart` (a new bot on the same database)
- `test_history_shows_no_player_or_profile_id`
- `test_history_command_uses_authorize_bucket_paging_uses_callback_bucket`
- `test_paging_refuses_other_owner_and_excluded_owner`
- `test_long_page_fits_4096`

Pins moved:
- `tests/test_client_lifecycle.py:678-680`: the exact `/admin` subcommand set gains `ex-raid-history` (after EXR-9 it reads `status`, `errors`, `restart`, `cooldown-user`, `cooldown-server`, `gift`, `gift-history`, `ex-raid`, `ex-raid-history`).
- Admin-guild manifest hash: changes again. No test holds a literal hash (`tests/test_client_lifecycle.py:717-722`, `tests/test_deploy_script.py:467-491` compute it; the `{'admin'}` scope pins stay). The global manifest and schema pins do not move.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `admin_ex_raid`, `admin_gift`, `admin`, `cooldown_reset`, `client_lifecycle`, `deploy_script`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `bot/admin_gift.py`, `bot/client.py` or a service needs an edit; over 300 production lines.

**Do not touch.** `services/**`, `bot/admin_gift.py`, `bot/client.py`.
