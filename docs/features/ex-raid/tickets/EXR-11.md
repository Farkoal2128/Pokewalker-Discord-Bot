# EXR-11 — Confirm: states, commit, fan-out, receipt

**Tier:** seam (interactions; persisted state; rate limits)

**Read:** PLAN D5, D6, D8; SYNTHESIS R3, R9; EXR-4, -6, -10; `bot/admin_gift.py:93-115, :141-151, :268-313`; `db/__init__.py:72-83, :144-155`; C5 "EX-Gift manager".

**Goal.** Confirm commits the draft once, schedules announcements before the receipt, always settles. C5 first.

- **`bot/admin_gift.py:105`** (the only edit there): Confirm is a custom ID starting with `gift_confirm:` or `ex_raid_confirm:`, so it takes the shared 5/min token (`admin.requests`); other presses keep the 30/min bucket.
- **Button:** `Confirm`, `custom_id=f'ex_raid_confirm:{draft_id}:{revision}'`, disabled until a target is chosen.
- **Confirm**, after the inherited checks, by state: `sent`: the stored receipt; `sending`: "This EX-Raid is being sent."; unregistered or `discarded`: the expiry refusal; no target, or not the draft's revision: "This preview is out of date. Nothing was sent."; else `state='sending'` and a shielded `settle()` task, as `admin_gift` :307-309.
- **`live()`**, **`job`**, **`settle`**: as `admin_gift` :276-306. `job`: not live returns `expired`; else `raids.ex_commit(conn, send_id=draft.send_id, ..., now=bot.walker.clock(), content=bot.content, checked=<EXR-10 resolver>)`; then not live raises (rollback). A refusal or rollback restores `editing` with the same revision and send ID; `expired` or a pending discard completes the discard.
- **`record(result)`** (`after_commit`, synchronous): `sent` sets `state='sent'` and keeps the result; unless `replayed`, it calls `bot.announce_ex_raid(result['ex_raid_id'])`: the fan-out is scheduled right after commit, before the receipt, even if the callback was cancelled.
- **Reply** from a snapshot local to Confirm: `sent`: a component-free receipt (send ID, boss, locks, duration, target, end UTC, committed counts incl. each skip reason); `nothing`: "Nothing was sent: no server could get this EX-Raid." plus the skip reasons; else "Nothing was sent."
- Other presses: `sending` refuses; `sent` shows the receipt.
- **C5:** extend "EX-Raid manager" with the above.

**Files.** Production: `pokewalker/bot/admin_ex_raid.py`, `pokewalker/bot/admin_gift.py`. Tests: `tests/test_admin_ex_raid.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_admin_ex_raid.py` pass, RED first:
- `test_confirm_disabled_until_target_then_sends_once_with_counts`
- `test_confirm_takes_5_per_minute_token_shared_with_ex_gift`
- `test_stale_confirm_from_before_all_servers_is_refused`
- `test_retried_confirm_and_lost_ack_return_the_same_receipt`
- `test_replay_after_expiry_or_server_changes_spawns_nothing`
- `test_send_spawning_nowhere_lists_skip_reasons_writes_nothing`
- `test_insert_failure_restores_editing_with_same_send_id`
- `test_owner_excluded_after_preview_or_while_confirm_waits`
- `test_confirm_queued_past_deadline_sends_nothing`
- `test_cancel_during_commit_keeps_the_committed_send`
- `test_deadline_during_commit_rolls_back_settlement_send_spawns`
- `test_discard_before_final_live_check_rolls_back_and_cleans_up`
- `test_cancel_then_rollback_restores_revision_and_send_id`
- `test_cancelled_callback_still_commits_and_schedules_fanout`
- `test_fanout_scheduled_before_receipt_survives_failed_reply`
- `test_confirm_through_drain_leaves_rows_pending`
- `test_forged_and_other_owner_confirm_refused`
- `test_old_control_after_restart_cannot_send`

`tests/test_admin_gift.py` passes unchanged. No command added: no pin moves.

**Verify.** Focused (staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `admin_ex_raid`, `admin_gift`, `admin`, `ex_raid`, `db`, `client_lifecycle`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `bot/admin_gift.py` needs more than the prefix line; `db/__init__.py`, `bot/client.py` or a service needs a change; an EX-Gift test must change; >300 production lines.

**Do not touch.** `bot/admin.py`, `bot/client.py`, `services/**`, `db/**`.
