# EXG-5 — `/admin gift`: manager editor and preview

**Tier:** seam (slash commands, interactions; rate limits)

**Read:** PLAN D3, D5, D9; SYNTHESIS EX-7..EX-10, EX-27, R5, R14-R18; EXG-4; `bot/admin.py:60-80, :160-199`; `tests/test_admin.py` `AdminTests`; `tests/test_cooldown_reset.py` `CooldownCommandTests`.

**Goal.** An owner opens a draft, builds 1-10 slots, previews it (Confirm: EXG-6). C5 first.

- **`bot/admin.py`:** `Admin.__init__` calls `admin_gift.attach(self)` (sets `gift_drafts`, `gift_callbacks` dicts). The deque of `authorize` (:66-73) moves into `throttled(bucket, user_id, limit)` → seconds left or None; `authorize` keeps its behavior with limit 5. Command `gift` (`scope` choices `all`, `server`; optional text `server_id`, `user_id`): `if await self.authorize(interaction): await admin_gift.open(self, interaction, …)`.
- **`open`** (new `bot/admin_gift.py`) refuses, writing nothing: `all` with an ID, `server` without `server_id`, a non-snowflake ID, then `unknown_server` or `no_profile` from `ex_gift.target` (D67 texts, `bot/admin.py:164-173`). Else a draft in `gift_drafts`: owner, scope (`user` if `user_id`), IDs, `deadline = bot.clock() + 900`, slots, revision, `send_id` (uuid4 hex), category, `ex`, page, `picked`, `state` `editing`.
- **Editor** (R15): row 0 Balls, Berries, Rare, IV items, Arena; row 1 Evolution, EX toggle (`EX-items` ⇄ `Ordinary items`), Prev, Next; row 2 item select (`ex_gift.page`, `ex_gift.label`; disabled at 10 slots); row 3 slot select `1. <label>` (omitted at 0 slots); row 4 Remove (disabled until a slot is picked), Clear, Preview (disabled at 0 slots), Cancel.
- **Callbacks:** an item pick fills the next slot (duplicates allowed); category or EX change → page 1; a slot pick sets `picked`; Remove, Clear. Each package change: new revision and `send_id`, `picked` None. Cancel drops the draft and leaves text without components.
- **Checks** (`interaction_check`, D9): `defer()` first; then owner = `draft.owner_id`, admin guild, configured owner; past `deadline` → drop the draft, "This gift draft expired. Run /admin gift again."; `throttled(gift_callbacks, owner, 30)`; exclusion (`admin.excluded` in a writer job). Refusals: ephemeral followups, no mentions, no change. View timeout = time left; `on_timeout` drops the draft.
- **Preview** (R18): send ID, scope, server ID, user ID for a one-user send, every slot, and provisional counts from `ex_gift.target` (targeted servers, servers with recipients, recipients). Zero recipients adds "No enrolled recipients: nothing can be sent." Buttons Edit (editor, same revision) and Cancel.
- **C5:** "EX-Gift manager" under M4.5a.

**Files.** Production: `pokewalker/bot/admin.py`, `pokewalker/bot/admin_gift.py` (new). Tests: `tests/test_admin_gift.py` (new). Contract: `contracts/discord-commands.md`.

**Accept.** New tests pass, RED first, on serialized payloads (`view.to_components()`): `test_parameters_admin_guild_only`, `test_bad_scope_id_combos_write_nothing` (all + ID, server without ID, bad ID, unknown server, unenrolled user, user only elsewhere), `test_open_4_rows_14_components`, `test_ten_slots_5_rows_15_components`, `test_clear_and_last_remove_omit_slot_select`, `test_duplicate_picks`, `test_remove_needs_pick`, `test_category_and_ex_reset_page`, `test_largest_page_25_labels`, `test_change_new_revision_and_send_id`, `test_forged_callback_changes_nothing`, `test_exclusion_after_open_refuses`, `test_bucket_30_shared_by_drafts`, `test_deadline_absolute`, `test_preview_contents_and_zero_line`, `test_cancel_discards`.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `admin_gift`, `admin`, `cooldown_reset`, `ex_gift`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A layout needs a sixth row or 26 options; `bot/client.py` needs an edit; a service change is needed; over 300 production lines.

**Do not touch.** `services/**`, `bot/client.py`, other `bot/` modules.
