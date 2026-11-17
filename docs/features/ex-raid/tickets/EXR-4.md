# EXR-4 — service: EX send (targets, guards, commit, history reads)

**Tier:** seam (persisted state; abuse controls)

**Read:** PLAN D5; SYNTHESIS XR-7, -9, -10, R3, R6; EXR-1, -2; `services/raids.py:76-126, :163-195`; `services/ex_gift.py:85-130`; `db/__init__.py:110-131`.

**Goal.** New `services/raids.py` functions beside `force_spawn`, in the caller's writer transaction. C3 first.

- **Plan helper** (preview and commit): one read of the target `guilds` rows (one server or all) with a live-EX flag (`kind='ex' AND ended=0 AND expires_at>now`). Per server, in order: `raids_off` (also a one-server target with no row), `no_channel`, `no_permission` (`checked(guild_id, raid_channel_id)` gave None), `channel_changed` (it gave another ID), `active` (EX live). A live World Legendary is no guard.
- **`ex_target(conn, guild_id, now, checked)`**: `{'status': 'ok', 'servers', 'spawning', 'skipped': {reason: n}}`, or `unknown_server` for a one-server target with no row. Writes nothing.
- **`ex_commit(conn, *, send_id, owner_id, admin_guild_id, identity_id, locks, hours, guild_id, now, content, checked)`**, in order:
  1. owner excluded in the admin guild: `excluded`;
  2. an `ex_raids` row for `send_id`: its stored result, `replayed: True` (another owner's: `invalid`); no targeting, no spawns;
  3. unknown `identity_id`, a lock of the wrong type or range, `hours` not an int 1-24: `invalid`;
  4. the plan; nothing to spawn: `{'status': 'nothing', 'servers', 'skipped'}`, nothing written;
  5. settle the targets' overdue spawns set-based (`expire`'s effects in three statements, not per spawn), `INSERT ex_raids`, one `executemany` of spawns (`kind='ex'`, `ex_raid_id`, checked channel, `pending`, `spawned_by_profile_id` NULL, one `expires_at = now + hours*3600`): `{'status': 'sent', 'replayed': False}` plus the stored row.
- No `mod_audit`/`action_receipts` row, cooldown read or Discord I/O.
- **`ex_lookup(conn, send_id)`**, **`ex_history(conn, offset)`**: (10 newest, total), `skipped` decoded.
- **C3:** new "EX-Raid send": the above.

**Files.** Production: `pokewalker/services/raids.py`. Tests: `tests/test_ex_raid.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests in `tests/test_ex_raid.py` pass, RED first:
- `test_one_server_send_spawns_ex_row_ordinary_mythical_form`
- `test_hours_1_and_24_ok_0_25_bool_text_invalid`
- `test_global_send_shares_one_expires_at`
- `test_global_send_counts_each_skip_reason` (all five, and bot absent)
- `test_one_server_skipped_writes_nothing_returns_reason`
- `test_global_send_all_skipped_writes_nothing`
- `test_live_world_legendary_is_no_guard_and_is_untouched`
- `test_overdue_unswept_ex_raid_is_settled_and_replaced` (same rows as `expire`)
- `test_refused_send_with_overdue_rows_writes_nothing`
- `test_settings_changed_after_preview_judged_at_commit`
- `test_same_send_id_returns_recorded_result_spawns_nothing`
- `test_other_owners_send_id_invalid`, `test_excluded_owner_refused_before_lookup`
- `test_unknown_identity_or_bad_lock_invalid_nothing_written`
- `test_insert_failure_part_way_rolls_back_everything`
- `test_no_mod_audit_and_force_raid_cooldown_ignored`
- `test_history_newest_first_paged_and_lookup`
- `test_requires_writer_transaction`

**Benchmark** (evidence, not a test): an uncommitted script times one global `ex_commit` at 1,000 and 10,000 guilds (and any owner count), fresh and replacing an expired, unswept global send with 5 players joined per server; `checked` is a stub. The commit body records method and holds. Live count: G-B.

**Verify.** Focused (staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_raid`, `raids`, `admin_force_raid`, `ex_raid_schema`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** The hold is >= 1 s (a fifth of the 5 s probe) at 1,000 guilds or the owner's count: report it. `spawn`, `force_spawn` or `expire` must change; over 300 production lines.

**Do not touch.** `bot/**`, migrations, other services.
