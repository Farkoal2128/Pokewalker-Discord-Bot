# EXG-6 — manager Confirm, draft states, receipt

**Tier:** seam (interactions; persisted state; rate limits)

**Read:** PLAN D3, D9; SYNTHESIS EX-6, R4, R5, R16-R18, R20; EXG-4, EXG-5 (checks, `discard`); `db/__init__.py` `Writer.run` (:72-83), observer (:144-155); `tests/test_db.py:289` (a cancelled waiter does not cancel the job).

**Goal.** Confirm commits the previewed revision once, never after the deadline or a discard, and the draft learns the outcome even if its callback is cancelled. C5 first.

- **Preview row:** Confirm, Edit, Cancel; the preview remembers its revision.
- **Confirm** runs the EXG-5 checks with a 5/min token (`throttled(admin.requests, owner, 5)`, shared with `authorize`) instead of the 30/min one. Then, after those awaits, by state:
  - `sent` → the stored receipt again, whatever revision the preview shows;
  - `sending` → "This gift is being sent.";
  - not registered or `discarded` → the EXG-5 expiry refusal;
  - preview revision ≠ draft revision → "The package changed. Preview it again.";
  - else `state = 'sending'`, then `await bot.writer.run(job, after_commit=record)`.
- **`job(conn)`** first rechecks, inside the transaction, `gift_drafts.get(draft_id) is draft`, `state == 'sending'` and `bot.clock() < deadline`; any failure → `{'status': 'expired'}`, nothing written. Else `ex_gift.send(…, send_id=draft.send_id, items=list(draft.slots), now=time.time())`.
- **`record(result)`** (synchronous, no I/O): `sent` → `state = 'sent'`, keep the result; `expired` → `discard` (idempotent); any other refusal → back to `editing`, same revision and send ID. The callback then redraws: the receipt with no components (send ID, scope, target, slots, committed counts), or an ephemeral "Nothing was sent." refusal over the preview. A job exception (rolled back) → `editing`. A cancelled waiter is not a rollback: the state stays `sending` until `record` runs.
- **Other controls** after their awaits: while `sending` → "This gift is being sent."; while `sent` → the receipt, never the editor. A sent draft stays registered until its deadline; later only `/admin gift-history` finds it (EXG-7).
- **Restart:** the old View dies with the process, so a click on an old control finds no handler and is not acknowledged; it cannot send.
- **C5:** Confirm, states, receipt, the stale-control behavior.

**Files.** Production: `pokewalker/bot/admin_gift.py`. Tests: `tests/test_admin_gift.py`. Contract: `contracts/discord-commands.md`.

**Accept.** New tests in `tests/test_admin_gift.py` pass, RED first:
- `test_confirm_sends_once_receipt_has_counts_no_components`
- `test_confirm_takes_authorize_bucket_token`
- `test_lost_response_retry_and_stale_click_return_same_send`
- `test_stale_preview_revision_refused`
- `test_edit_cancel_and_picks_refused_while_sending` (a writer job held on an `asyncio.Event`)
- `test_delayed_pick_racing_confirm_keeps_package_and_receipt` (the pick's exclusion check finishes after commit)
- `test_confirm_queued_past_deadline_sends_nothing`
- `test_cancel_while_confirm_queued_sends_nothing`
- `test_rollback_keeps_revision_and_send_id`
- `test_cancelled_waiter_then_commit_then_retry_returns_receipt`
- `test_exclusion_after_preview_refused_in_transaction`, `test_zero_recipients_refused_at_commit`
- `test_two_identical_one_user_drafts_one_commits`
- `test_old_control_after_restart_cannot_send` (a new bot on the same DB: no handler, no `ex_gifts` row)

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `admin_gift`, `admin`, `db`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `db/__init__.py` or a service needs a change; over 300 production lines.

**Do not touch.** `bot/admin.py`, `services/**`, `db/**`.
