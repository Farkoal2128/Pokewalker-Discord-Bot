# EXG-7 — `/admin gift-history`

**Tier:** seam (slash commands; rate limits)

**Read:** PLAN D9, D10; SYNTHESIS R17, R19, R20; EXG-4 (`history`, `lookup`), EXG-5 (checks, `throttled`), EXG-6 (receipt text); `bot/admin.py:183-199` (command form).

**Goal.** An owner who lost an acknowledgement checks whether a send landed, by send ID or by browsing, without sending again. C5 first.

- **Command** (`bot/admin.py`): `gift-history` with optional text `send_id`; `if await self.authorize(interaction): await admin_gift.history(self, interaction, send_id)`. It takes a 5/min token through `authorize`.
- **By ID:** a `send_id` that is not 32 lowercase hex characters, or has no row (`ex_gift.lookup` in a writer job) → "No send with ID <id> was committed."; else that one entry.
- **List:** `ex_gift.history` page 1, newest first, 10 per page. Entry: send ID, UTC time, scope and server ID (`all servers` for `all`; `one user in server <id>` for a one-user send, never the user ID), slots by label, committed counts (targeted servers, servers with recipients, recipients). Every configured owner's sends are listed (D10). If the page text passes 4096 characters, slot lists shrink to `n slots`.
- **Paging:** Prev and Next in a view bound to the opening owner, timeout 900 s; each press runs the EXG-5 callback checks with the 30/min bucket (owner, admin guild, exclusion). Ephemeral, no mentions.
- **C5:** append "`/admin gift-history`" under M4.5a.

**Files.** Production: `pokewalker/bot/admin.py`, `pokewalker/bot/admin_gift.py`. Tests: `tests/test_admin_gift.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_admin_gift.py` pass, RED first:
- `test_history_parameter_optional_admin_guild_only`
- `test_history_newest_first_ten_per_page_with_counts`
- `test_history_never_shows_recipient_or_user_ids`
- `test_lookup_by_send_id_found_missing_and_malformed`
- `test_send_recovered_by_id_after_draft_is_gone` (commit, drop the draft, look up the preview's send ID)
- `test_send_recovered_by_id_after_restart` (commit, then a new bot on the same DB finds the send; the old control has no handler, EXG-6)
- `test_history_command_uses_authorize_bucket_paging_uses_callback_bucket` (shared with an open draft)
- `test_paging_refuses_other_owner_and_excluded_owner`
- `test_long_page_fits_4096`

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `admin_gift`, `admin`, `cooldown_reset`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A service change is needed; `bot/client.py` needs an edit; over 300 production lines.

**Do not touch.** `services/**`, `bot/client.py`, other `bot/` modules.
