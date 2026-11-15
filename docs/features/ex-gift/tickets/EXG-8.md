# EXG-8 — `services/ex_gift.py`: claim and EX inventory

**Tier:** seam (persisted player state)

**Read:** PLAN D1, D4, D6; SYNTHESIS EX-2..EX-6, EX-18, EX-22, R4, R13, R20; EXG-2..EXG-4; `services/milestones.py` `claim` (:131-178, key form); `services/profiles.py` `session_owner` (:84); `services/deletion.py:125-131`; `services/storage.py:88-93` (`RETURNING` form).

**Goal.** Claim moves every unclaimed gift at once; the EX inventory has read and debit helpers for the item rows. C3 first.

- **`held(conn, profile_id)`** → `{id: quantity}` for all six `EX_ITEMS`, 0 when absent.
- **`take(conn, profile_id, item)`** → True after `UPDATE ex_items SET quantity=quantity-1 WHERE profile_id=? AND item_id=? AND quantity>0` changed a row, else False. Callers run it inside their own receipt.
- **`unclaimed(conn, profile_id, limit=10)`** → (oldest gifts first as `{gift_id, created_at, items}`, total); **`has_unclaimed(conn, profile_id)`** → bool (`EXISTS`, the `(profile_id, claimed_at)` index).
- **`claim(conn, session, now)`**: `session_owner` first (`stale`, `excluded`); then `with_receipt(conn, f"ex_claim:{session_id}:{rev}", 'ex_claim', compute, profile_id=…)`, `rev` per D4. `compute`: `UPDATE ex_gift_recipients SET claimed_at=? WHERE profile_id=? AND claimed_at IS NULL RETURNING gift_id`; for each claimed gift, oldest first, each slot: an ordinary id → `inbox_items(profile, 'ex_gift:<gift_id>', 'item', id, 1, now)`; `arena_ticket:<tier>` → `(…, 'arena_ticket', tier, 1, now)`; an EX id → `ex_items` upsert +1. Ledger: one `ex_item / <id> / +n / ex_claim` line per EX id. Result `{'status': 'claimed', 'gifts', 'inbox', 'ex': {id: n}}`; with no unclaimed gift, `gifts` 0 and nothing moves.
- Every write to `ex_items` lives in this module (EX-2: no gameplay grant); trading never sees the table (EX-22).
- **C3:** append "EX-Gift claim and EX inventory": the transition, routing, keys, retention through deletion, re-enrolment and replay.

**Files.** Production: `pokewalker/services/ex_gift.py`. Tests: `tests/test_ex_gift.py`. Contract: `contracts/persisted-state.md`.

**Accept.** New tests in `tests/test_ex_gift.py` pass, RED first:
- `test_claim_routes_items_tickets_and_ex_items` (a 10-slot mixed package with duplicates: inbox rows under one `ex_gift:` key, `ex_items` counts, ledger lines)
- `test_claim_takes_every_unclaimed_gift_once`
- `test_second_session_claims_nothing` (two sessions of one profile)
- `test_same_press_replays_without_effect`
- `test_failure_mid_claim_rolls_back_everything` (a trigger fails the third inbox insert in a writer job)
- `test_excluded_or_stale_session_claims_nothing`
- `test_unclaimed_oldest_first_limit_and_total`, `test_has_unclaimed_false_after_claim`
- `test_held_and_take_never_below_zero`
- `test_ex_items_has_no_cap` (claim 1,000 EX slots)
- `test_delete_reenrol_and_replay_leave_no_gift_or_ex_item` (`deletion.apply`, then `profiles.enroll`, then replay; member prune uses the same `apply`, `bot/admin_channels.py:304`)
- `test_only_this_module_writes_ex_items` (scan `pokewalker/**/*.py` for `INTO ex_items` and `UPDATE ex_items`)

**Verify.** Focused (`Tests-Focused` on the staged tree; boundary G-F). `python -m unittest discover -s tests -p "test_<m>.py"` for `ex_gift`, `ex_gift_schema`, `milestones`, `deletion`, `replay`; `git -c core.whitespace=cr-at-eol diff --cached --check`.

**Stop if.** A migration or another service needs a change; `RETURNING` is unavailable on the patched SQLite (`db/__init__.py:18-20`); over 300 production lines.

**Do not touch.** Migrations; other services; `bot/**`.
