# EXG-6 — manager Confirm, draft states, receipt; deletion drops drafts

**Tier:** seam (interactions; persisted state; rate limits)

**Read:** PLAN D3, D9; SYNTHESIS EX-6, R4, R5, R16-R18, R20; EXG-4, EXG-5; `bot/admin.py:141-151` (exclusion recheck in the writer job); `services/deletion.py` `apply` (:125-131), `run_marker` (:75).

**Goal.** Confirm commits the previewed revision once; a deleted profile leaves no draft naming it. C5, C3 first.

- **Preview row:** Confirm, Edit, Cancel. The preview remembers the revision it shows.
- **Confirm** runs the EXG-5 checks but takes its token from the 5/min bucket (`throttled(admin.requests, owner, 5)`, shared with `authorize`), not the 30/min one. Then by `draft.state`:
  - `sent` → the stored receipt again, whatever revision the preview shows (lost response, retry, stale click);
  - `sending` → "This gift is being sent.";
  - preview revision ≠ draft revision → "The package changed. Preview it again.";
  - past `deadline` → the EXG-5 expiry refusal;
  - else `state = 'sending'` before awaiting `bot.writer.run(ex_gift.send(…, send_id=draft.send_id, items=list(draft.slots), now=time.time()))`.
- **Outcomes:** `sent` → `state = 'sent'`, keep the result; the message becomes the receipt with no components: send ID, scope, target, slots, committed counts. A refusal (`excluded`, `unknown_server`, `no_profile`, `no_recipients`, `invalid`) or an exception (rolled back) → `state = 'editing'` with the same revision and send ID, an ephemeral refusal ("Nothing was sent."), and the preview stays. A sent draft stays in `gift_drafts` until its deadline, then only `/admin gift-history` finds the send (EXG-7).
- **Edit, Cancel** while `sending` → "This gift is being sent."; while `sent` → the receipt.
- **Deletion:** `services/deletion.py` gains `listen(obj)` (a `weakref.WeakSet`); `apply` calls `obj.profile_deleted(guild_id, user_id)` on each listener after each profile delete (:129-131), inside the job (an early drop is harmless). `attach` makes `gift_drafts` a `Drafts(dict)` whose `profile_deleted` drops every draft targeting that `(guild, user)`, and calls `deletion.listen(gift_drafts)`.
- **C5:** Confirm, states, receipt. **C3:** M4.1b notes the listener.

**Files.** Production: `pokewalker/bot/admin_gift.py`, `pokewalker/services/deletion.py`. Tests: `tests/test_admin_gift.py`, `tests/test_deletion.py`. Contracts: `contracts/discord-commands.md`, `contracts/persisted-state.md`.

**Accept.** New tests pass, RED first. In `tests/test_admin_gift.py`:
- `test_confirm_sends_once_receipt_has_counts_no_components`
- `test_confirm_takes_authorize_bucket_token`
- `test_lost_response_retry_and_stale_click_return_same_send`
- `test_stale_preview_revision_refused`
- `test_edit_and_cancel_refused_while_sending` (a writer job held on an `asyncio.Event`)
- `test_rollback_keeps_revision_and_send_id`
- `test_exclusion_after_preview_refused_in_transaction`
- `test_zero_recipients_refused_at_commit`
- `test_expired_draft_cannot_confirm`
- `test_restart_before_or_after_commit` (a new bot on the same DB: no send, or exactly one)
- `test_two_identical_one_user_drafts_one_commits`
- `test_deleted_recipient_id_absent_owner_id_kept` (after the one-user recipient's deletion: no EX-Gift table, receipt, ledger or captured log line holds the user ID; `ex_gifts.owner_id` stays)

In `tests/test_deletion.py`: `test_profile_delete_drops_matching_gift_drafts_only`, `test_replay_calls_listeners_harmlessly`.

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `admin_gift`, `deletion`, `replay`, `account`, `admin_prune`, `admin`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** `deletion.apply` cannot call listeners without changing its callers; a service other than `deletion` needs a change; over 300 production lines.

**Do not touch.** `bot/admin.py`, `bot/account.py`, `bot/admin_channels.py`, `services/marker_log.py`, other services.
