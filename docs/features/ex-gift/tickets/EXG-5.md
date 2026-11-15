# EXG-5 — `/admin gift`: manager editor and preview

**Tier:** seam (slash commands, interactions; rate limits)

**Read:** PLAN D5, D9; SYNTHESIS EX-7..EX-10, EX-27, R5, R14-R18; EXG-4; `bot/admin.py:60-80, :160-199`; `tests/test_admin.py` `AdminTests`.

**Goal.** An owner opens a draft, builds 1-10 slots, previews it (Confirm: EXG-6). C5 first.

- **`bot/admin.py`:** `Admin.__init__` calls `admin_gift.attach(self)` (sets `gift_drafts`, `gift_callbacks`). The deque of `authorize` (:66-73) moves into `throttled(bucket, user_id, limit)` → seconds left or None; `authorize` keeps limit 5. Command `gift` (`scope` choices `all`, `server`; optional text `server_id`, `user_id`): `if await self.authorize(interaction): await admin_gift.open(self, interaction, …)`.
- **`open`** (new `bot/admin_gift.py`) refuses, writing nothing: `all` with an ID, `server` without `server_id`, a non-snowflake ID, then `unknown_server` or `no_profile` from `ex_gift.target` (D67 texts). Else a draft in `gift_drafts`: owner, scope (`user` if `user_id`), IDs, `deadline = bot.clock() + 900`, slots, revision, `send_id` (uuid4 hex), category, `ex`, page, `picked`, `state` `editing`.
- **Editor** (R15): row 0 Balls, Berries, Rare, IV items, Arena; row 1 Evolution, EX toggle, Prev, Next; row 2 item select (`ex_gift.page`, `ex_gift.label`; disabled at 10 slots); row 3 slot select `1. <label>` (omitted at 0 slots); row 4 Remove (needs a picked slot), Clear, Preview (needs a slot), Cancel.
- **Callbacks:** a pick fills the next slot (duplicates allowed); category or EX change → page 1; a slot pick sets `picked`; Remove, Clear. A package change makes a new revision and `send_id`, `picked` None.
- **Checks** (`interaction_check`, D9): `defer()`; owner = `draft.owner_id`, admin guild, configured owner; past `deadline` → `discard`, "This gift draft expired. Run /admin gift again."; `throttled(gift_callbacks, owner, 30)`; exclusion (`admin.excluded`, writer job). **After these awaits**, every callback rechecks `gift_drafts.get(draft_id) is draft`, and every mutation or editor redraw (picks, Remove, Clear, paging, Edit) runs only while `state == 'editing'`. Refusals: ephemeral, no mentions, no change.
- **`discard(draft)`**, the only removal (Cancel, expiry, `on_timeout`; EXG-20 adds deletion): `state = 'discarded'`, pop it if still registered, `view.stop()`, clear `guild_id` and `user_id`. Cancel leaves text only. View timeout = time left.
- **Preview** (R18): send ID, scope, server ID, user ID for a one-user send, every slot, the three provisional `ex_gift.target` counts; zero recipients adds "No enrolled recipients: nothing can be sent." Buttons Edit (same revision) and Cancel.
- **C5:** "EX-Gift manager" under M4.5a.

**Files.** Production: `pokewalker/bot/admin.py`, `pokewalker/bot/admin_gift.py` (new). Tests: `tests/test_admin_gift.py` (new). Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first, on serialized payloads (`view.to_components()`): `test_parameters_admin_guild_only`, `test_bad_scope_id_combos_write_nothing` (all + ID, server without ID, bad ID, unknown server, unenrolled user, user only elsewhere), `test_rows_4_14_at_0_and_5_15_at_10_slots`, `test_clear_and_last_remove_omit_slot_select`, `test_duplicate_picks`, `test_category_and_ex_reset_page`, `test_largest_page_25_labels`, `test_change_new_revision_and_send_id`, `test_forged_callback_changes_nothing`, `test_exclusion_after_open_refuses`, `test_bucket_30_shared_by_drafts`, `test_deadline_absolute`, `test_preview_contents_and_zero_line`, `test_retained_controls_after_discard_change_nothing`.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `admin_gift`, `admin`, `cooldown_reset`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A layout needs a sixth row or 26 options; `bot/client.py` or a service needs a change; over 300 production lines.

**Do not touch.** `services/**`, `bot/client.py`, other `bot/` modules.
