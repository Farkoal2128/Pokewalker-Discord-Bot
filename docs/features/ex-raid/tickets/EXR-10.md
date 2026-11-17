# EXR-10 — preview draft: target, All servers, counts, Cancel

**Tier:** seam (interaction responses; rate limits)

**Read:** PLAN D5, D8; SYNTHESIS R3 (preview, target), R6 ("Global"); EXR-4 (`ex_target`), EXR-9; `bot/admin_gift.py:35-44, :52-77, :80-139` (the pattern mirrored here); `services/raids.py:189-195`; C5 "EX-Gift manager".

**Goal.** A valid submit opens an owner-bound draft with a preview menu. The target is the given server or an explicit "All servers" press, never a default. C5 first.

- **Registry:** `admin_ex_raid.attach(admin)` sets `admin.ex_raid_drafts = {}`; `Admin.__init__` calls it (`bot/admin.py:47`).
- **Draft** (in memory, as `admin_gift.open` :71-76): owner, identity, locks, hours, `guild_id` or None, `all_servers` False, `deadline = bot.clock() + 900` (monotonic), `revision` 0, one `send_id = uuid4().hex` for its whole life, `state='editing'`, `discard_pending` False.
- **With `server_id`:** `raids.ex_target` in a writer job; `unknown_server` replies "The bot has no data for server <id>." and opens no draft.
- **View:** `RaidView(admin_gift.OwnerView)`, expiry text "This EX-Raid draft expired. Run /admin ex-raid again." Buttons: `All servers` (only while no target is chosen) and `Cancel`; Confirm arrives in EXR-11. Every press runs the inherited `interaction_check` (defer, owner, admin guild, deadline, the shared 30/min bucket `admin.gift_callbacks`, exclusion), then rechecks that the registry still holds this draft in state `editing`.
- **All servers:** sets `all_servers`, bumps `revision`, redraws with the global counts.
- **Preview** (sprite embed plus text): send ID; boss; each lock or "rolled per player"; duration; target (`server <id>`, `all servers`, or "none chosen: press All servers"); once a target exists, `Counts (provisional)`: targeted servers, servers that will get it, and one line per skip reason with its count (raids off, no raid channel, no permission or bot not in server, raid channel changed, EX-Raid already live). Nothing spawnable adds "Nothing would spawn."
- **Counts:** `raids.ex_target(conn, guild_id, bot.walker.clock(), checked)`; `checked` resolves `bot.get_guild(int(guild_id))` (absent: None) and calls `raids.checked_channel`. Gateway cache only.
- **`discard(draft)`** mirrors `admin_gift.discard` (:35-44) on `ex_raid_drafts`; Cancel, expiry and view timeout use it. Cancel leaves "EX-Raid draft cancelled." without controls.
- **C5:** extend "EX-Raid manager": draft, target rule, preview fields, callback checks, discard.

**Files.** Production: `pokewalker/bot/admin.py`, `pokewalker/bot/admin_ex_raid.py`. Tests: `tests/test_admin_ex_raid.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_admin_ex_raid.py` pass, RED first:
- `test_server_target_preview_shows_send_id_boss_locks_duration_counts`
- `test_unknown_server_refused_no_draft`
- `test_without_server_id_shows_all_servers_no_target_no_counts`
- `test_all_servers_press_bumps_revision_and_shows_global_counts`
- `test_counts_list_each_skip_reason_marked_provisional`
- `test_cancel_discards_and_leaves_text_without_controls`
- `test_draft_expires_after_900_s_and_presses_refuse`
- `test_other_owner_other_guild_and_excluded_owner_refused`
- `test_presses_share_the_30_per_minute_bucket_with_ex_gift`
- `test_press_after_restart_finds_no_handler`
- `test_view_within_discord_component_limits`
- `test_preview_writes_nothing`

No command is added: the subcommand set (`tests/test_client_lifecycle.py:678-680`), both manifests and schema pins do not move. The buttons sit on a new view that no component-count pin covers.

**Verify.** Focused (staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `admin_ex_raid`, `admin`, `admin_gift`, `client_lifecycle`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `bot/admin_gift.py` or a service needs an edit; the preview must write to count; over 300 production lines.

**Do not touch.** `services/**`, `bot/admin_gift.py`, `bot/client.py`.
