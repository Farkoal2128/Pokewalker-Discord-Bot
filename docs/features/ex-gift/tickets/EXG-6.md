# EXG-6 — manager Confirm, draft states, receipt

**Tier:** seam (interactions; persisted state; rate limits)

**Read:** PLAN D3, D9; SYNTHESIS EX-6, R4, R5, R16-R18, R20; EXG-4, EXG-5 (checks, `discard`); `db/__init__.py` `Writer.run` (:72-83), rollback and observer (:113-155).

**Goal.** Confirm commits the previewed revision once, never after the deadline or a discard, and the draft always settles even if its callback is cancelled. C5 first.

- **Preview row:** Confirm, Edit, Cancel; the preview remembers its revision.
- **Confirm** runs the EXG-5 checks with a 5/min token (`throttled(admin.requests, owner, 5)`). Then, after those awaits, by state:
  - `sent` → the stored receipt again, whatever revision the preview shows;
  - `sending` → "This gift is being sent.";
  - not registered or `discarded` → the EXG-5 expiry refusal;
  - preview revision ≠ draft revision → "The package changed. Preview it again.";
  - else `state = 'sending'` and `draft.task = asyncio.create_task(settle())`; the callback awaits `asyncio.shield(draft.task)`.
- **`live()`**: `gift_drafts.get(draft_id) is draft`, `state == 'sending'` and `bot.clock() < deadline`.
- **`job(conn)`**: not `live()` → `{'status': 'expired'}`, nothing written. Else `ex_gift.send(…, send_id=draft.send_id, items=list(draft.slots), now=time.time())`; after it returns `sent`, not `live()` → raise `_Expired`, so its writes roll back.
- **`record(result)`** (`after_commit`, synchronous, no I/O): `sent` → `state = 'sent'`, keep the result; `expired` → `discard` (idempotent); other refusals → `editing`, same revision and send ID.
- **`settle()`** owns completion, shielded from callback cancellation: `await bot.writer.run(job, after_commit=record)`; `_Expired` → `discard`; any other exception (rolled back) → `editing` only while the draft is still registered and `sending`. A cancelled callback is not a rollback; `settle` still runs to the end.
- The callback then shows the component-free receipt (send ID, scope, target, slots, committed counts) or an ephemeral "Nothing was sent."
- **Other controls** after their awaits: while `sending` → "This gift is being sent."; while `sent` → the receipt, never the editor. A sent draft stays registered until its deadline; then `/admin gift-history` finds it (EXG-7).
- **Restart:** the old View dies with the process; a click on an old control finds no handler, is not acknowledged and cannot send.
- **C5:** Confirm, states, receipt, stale controls.

**Files.** Production: `pokewalker/bot/admin_gift.py`. Tests: `tests/test_admin_gift.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_admin_gift.py` pass, RED first:
- `test_confirm_sends_once_receipt_has_counts_no_components`, `test_confirm_takes_authorize_bucket_token`
- `test_lost_response_retry_and_stale_click_return_same_send`, `test_stale_preview_revision_refused`
- `test_edit_cancel_and_picks_refused_while_sending`
- `test_delayed_pick_racing_confirm_keeps_package_and_receipt`
- `test_confirm_queued_past_deadline_sends_nothing`, `test_expiry_during_send_rolls_back` (the clock passes the deadline inside `send`)
- `test_cancel_while_confirm_queued_sends_nothing`, `test_rollback_keeps_revision_and_send_id`
- `test_cancelled_callback_then_commit_then_retry_returns_receipt`
- `test_cancelled_callback_then_rollback_restores_editing` (stays `discarded` if discarded meanwhile)
- `test_exclusion_after_preview_refused`, `test_zero_recipients_refused_at_commit`
- `test_two_identical_one_user_drafts_one_commits`
- `test_old_control_after_restart_cannot_send` (a new bot on the same DB)

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `admin_gift`, `admin`, `db`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `db/__init__.py` or a service needs a change; over 300 production lines.

**Do not touch.** `bot/admin.py`, `services/**`, `db/**`.
