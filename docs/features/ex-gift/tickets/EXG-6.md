# EXG-6 — manager Confirm, draft states, receipt

**Tier:** seam (interactions; persisted state; rate limits)

**Read:** PLAN D3, D9; SYNTHESIS R4, R5, R16-R18, R20; EXG-4, EXG-5; `db/__init__.py` `Writer.run` (:72-83, :113-155).

**Goal.** Confirm commits the previewed revision once. The job's last `live()` authorizes the commit, which may finish after the deadline; a discard or expiry before it sends nothing. The draft always settles. C5 first.

- **Preview row:** Confirm, Edit, Cancel; the preview remembers its revision.
- **Confirm** runs the EXG-5 checks with a 5/min token (`throttled(admin.requests, owner, 5)`). After those awaits, by state:
  - `sent` → the stored receipt again, whatever revision the preview shows;
  - `sending` → "This gift is being sent.";
  - not registered or `discarded` → the EXG-5 expiry refusal;
  - preview revision ≠ draft revision → "The package changed. Preview it again.";
  - else `state = 'sending'` and `draft.task = asyncio.create_task(settle())`; the callback awaits `asyncio.shield(draft.task)`.
- **`live()`**: registry holds this draft, `state == 'sending'`, not `discard_pending`, and `bot.clock() < deadline`.
- **`job(conn)`**: not `live()` → `{'status': 'expired'}`, nothing written. Else `ex_gift.send(…, send_id=draft.send_id, items=list(draft.slots), now=time.time())`; then not `live()` → raise `_Expired` (rollback).
- **Discard while `sending`** (ruling 2026-11-15; Cancel, expiry, timeout, EXG-20) sets `discard_pending` and returns; `live()` turns false.
- **`record(result)`** (`after_commit`, sync, no I/O): `sent` → `state = 'sent'`, keep the aggregate result.
- **`settle()`**, shielded: `await bot.writer.run(job, after_commit=record)`. Then it leaves `sending` in every outcome: refusal or rollback → `editing` (same revision, send ID); `expired`/`_Expired` or `discard_pending` → final discard (unregister, stop View, clear IDs, drop stored receipt). A cancelled callback is not a rollback.
- The callback renders the component-free receipt (send ID, scope, target, slots, counts) from a snapshot local to Confirm, released when it returns, or "Nothing was sent."
- **Other controls:** `sending` → "This gift is being sent."; `sent` → the receipt, until the deadline; then EXG-7 history.
- **Restart:** an old control finds no handler and cannot send.

**Files.** Production: `pokewalker/bot/admin_gift.py`. Tests: `tests/test_admin_gift.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_admin_gift.py` pass, RED first:
- `test_confirm_sends_once_receipt_has_counts_no_components`, `test_confirm_takes_authorize_bucket_token`
- `test_lost_response_retry_and_stale_click_return_same_send`, `test_stale_preview_revision_refused`
- `test_edit_cancel_and_picks_refused_while_sending`
- `test_delayed_pick_racing_confirm_keeps_package_and_receipt`
- `test_confirm_queued_past_deadline_sends_nothing`, `test_expiry_during_send_rolls_back` (the clock passes the deadline inside `send`), `test_timeout_during_commit_keeps_send_and_receipt_target` (replaces WIP `4c8bc24`), `test_pending_discard_or_expiry_cleans_up_any_outcome`
- `test_cancel_while_job_queued_sends_nothing`, `test_rollback_keeps_revision_and_send_id`
- `test_cancelled_callback_then_commit_then_retry_returns_receipt`
- `test_cancelled_callback_then_rollback_restores_editing` (stays `discarded` if discarded meanwhile)
- `test_exclusion_after_preview_refused`, `test_zero_recipients_refused_at_commit`
- `test_two_identical_one_user_drafts_one_commits`
- `test_old_control_after_restart_cannot_send` (a new bot on the same DB)

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `admin_gift`, `admin`, `db`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `db/__init__.py` or a service needs a change; over 300 production lines.

**Do not touch.** `bot/admin.py`, `services/**`, `db/**`.
