What this change does: The amendment keeps caught Pokémon in their encounter until Done, Upgrade, or research resolves them. It adds recovery, encounter blocking, and a timed research fallback while preserving catch-time rewards and Pokédex progress.

Reviewed the six individual tickets M6.8r–w against `feature/pokewalker-v1.1-v2` at `3e56b30`. The tree is clean. Assumed the repository’s single-process, serialized-writer deployment.

**Must fix**

1. **A fresh full-storage catch bypasses the new menu** ([M6.8u.md:15](<scratchpad>/amend3/tickets/M6.8u.md:15)).

   - **What this is:** The new `pending_menu` owns the Send/Upgrade choice.
   - **Problem:** Successful throws still return `screens.render_terminal` directly at [walker.py:481](<pokewalker/bot/walker.py:481>). Neither M6.8s nor M6.8v redirects that result, so a confirmed catch at full storage shows Done/Send instead of Send/Upgrade.
   - **Fix:** Include the successful-catch dispatch to `pending_menu` in M6.8s’s existing walker.py scope. Test the actual throw response without reopening Home first.
   - **If we skip it:** Players must press an invalid Done button or reopen `/walker` to discover Upgrade.

2. **The send service uses the wrong return shape from `identify`** ([M6.8r.md:14](<scratchpad>/amend3/tickets/M6.8r.md:14)).

   - **What this is:** Pending research needs the Pokémon’s family and protection flags.
   - **Problem:** The draft assigns `identity = storage.identify(...)`, but [storage.py:12](<pokewalker/services/storage.py:12>) returns `(identity, sprite)`. Reading `identity["family_id"]` from that pair fails.
   - **Fix:** Specify `identity, _ = storage.identify(...)`, matching existing callers.
   - **If we skip it:** Pending research fails; an automatic send failure also rolls back that tick’s gym settlement and raid expiry.

3. **M6.8s requires behavior that only M6.8t implements** ([M6.8s.md:50](<scratchpad>/amend3/tickets/M6.8s.md:50)).

   - **What this is:** M6.8s requires both pending-menu buttons to resolve the catch.
   - **Problem:** At that row, [research.py:89](<pokewalker/bot/research.py:89>) still rejects a catch without an owned Pokémon row. Pending Send support arrives in M6.8t.
   - **Fix:** Keep menu rendering and Done/Upgrade tests in M6.8s; move the both-buttons interaction test to M6.8t.
   - **If we skip it:** M6.8s cannot finish green without prematurely editing a third production file.

4. **The activation fallout instructions retain failing tests and erase legacy fixture assumptions** ([M6.8u.md:29](<scratchpad>/amend3/tickets/M6.8u.md:29)).

   - **What this is:** M6.8u removes immediate storage and changes shared catch fixtures.
   - **Problem:** The explicitly “unchanged” [test_capacity.py:282](<tests/test_capacity.py:282>) requires the owned count to increase immediately. Other omitted fallout includes [test_star_piece.py:337](<tests/test_star_piece.py:337>) dereferencing `caught.pokemon`, and [test_walker_ack.py:99](<tests/test_walker_ack.py:99>) expecting an older Run result before the now-pending catch.
   - **Fix:** Correct the fallout list and retain separate pending and legacy stored-result fixtures. Preserve the valid owned-result protection checks at [test_capacity.py:782](<tests/test_capacity.py:782>) instead of converting every M6.8j test to pending.
   - **If we skip it:** Activation fails its full-unit check, or valid “existing owned Pokémon unaffected” coverage gets weakened during repair.

5. **The proposed lookup helper cannot distinguish batch selections** ([M6.8t.md:14](<scratchpad>/amend3/tickets/M6.8t.md:14)).

   - **What this is:** `_pick(conn, session, selection)` replaces both single and batch Pokémon lookups.
   - **Problem:** The review loop fetches a different `uid` on every iteration at [research.py:99](<pokewalker/bot/research.py:99>). Passing the same complete selection to `_pick` supplies no current UID; a two-Pokémon review cannot reliably resolve each member.
   - **Fix:** Give `_pick` an explicit UID argument. Pass the loop UID from `review` and the selected UID from `single`, retaining revision checks.
   - **If we skip it:** Ordinary owned-Pokémon research can fail or review the wrong member of a batch.

6. **Pending recovery loses the flag that suppresses dead catch controls** ([M6.8s.md:17](<scratchpad>/amend3/tickets/M6.8s.md:17)).

   - **What this is:** Recovery now returns through `pending_menu`.
   - **Problem:** The described room branch calls `render_terminal` without setting `recovery`. [screens_catch.py:74](<pokewalker/bot/screens_catch.py:74>) therefore adds five disabled catch controls, contradicting Done/Send-only and the explicitly preserved assertions at [test_walker_ack.py:56](<tests/test_walker_ack.py:56>).
   - **Fix:** Explicitly suppress those controls for pending menus, either through the existing recovery flag or a pending-aware renderer condition.
   - **If we skip it:** Fresh `/walker` recovery violates the specified menu and fails its named tests.

**Should fix**

7. **Upgrade lacks a failure-after-payment rollback test** ([M6.8s.md:48](<scratchpad>/amend3/tickets/M6.8s.md:48)).

   - **What this is:** Upgrade now combines payment, expansion, Pokémon insertion, and acknowledgment.
   - **Problem:** Existing capacity rollback coverage fails during expansion, before the new store operation. The proposed success/stale tests do not exercise failure after payment but before storing or acknowledging.
   - **Fix:** Add `test_pending_upgrade_store_failure_rolls_back_then_retries_once`: fail the Pokémon insert or acknowledgment, assert every write rolled back, then retry successfully once.
   - **If we skip it:** The new payment-to-storage transaction boundary remains unverified.

8. **The destructive fallback has no Mythical exemption test** ([M6.8r.md:47](<scratchpad>/amend3/tickets/M6.8r.md:47)).

   - **What this is:** Shiny, Legendary, and Mythical catches must remain pending indefinitely.
   - **Problem:** The exemption test specifies only shiny and Legendary cases. A non-shiny species with `is_mythical=True` and `is_legendary=False` exercises a separate condition.
   - **Fix:** Add that case to the exemption test, asserting no Pokémon row, receipt, Candy, or acknowledgment after repeated overdue sweeps.
   - **If we skip it:** Omitting the Mythical check could permanently send those catches while all named exemption tests pass.

9. **Reviewed pending-send replay is not tested past expiry** ([M6.8r.md:39](<scratchpad>/amend3/tickets/M6.8r.md:39)).

   - **What this is:** An authorized receipt must replay before checking expiry or whether the catch remains pending.
   - **Problem:** The draft tests replay of the lower-level `send_pending`, while the duplicate-click UI test can stop at router revision validation. Neither proves replay ordering in the new `send_pending_reviewed`.
   - **Fix:** Add `test_send_pending_reviewed_replays_after_expiry_and_restart`, calling that service with the original saved preview after the successful send.
   - **If we skip it:** A misplaced pending/expiry guard could reject a legitimate replay without failing the planned tests.

**Nice to have**

10. **The explanation for retaining `overflow_uid` makes a false SQLite claim** ([PLAN-insert.md:21](<scratchpad>/amend3/PLAN-insert.md:21)).

   - **What this is:** The draft says SQLite cannot drop this foreign-key column.
   - **Problem:** [test_receipt_owner.py:48](<tests/test_receipt_owner.py:48>) already drops it. An in-memory probe using all 17 real migrations also succeeded with foreign keys enabled.
   - **Fix:** Keep the column if desired, but justify that as avoiding an unnecessary migration. Remove the claim that a destructive table rebuild is required.
   - **If we skip it:** The plan preserves incorrect guidance for future schema work.

The encounter-held predicate otherwise fits the current schema. Owned-only readers exclude pending catches; catch-time Pokédex/milestone updates remain intact; delete-data, opt-out, and admin reset cascade through profile deletion; raid expiry preserves caught encounters. I found no separate runtime retention path that deletes them.

Ticket sizes r–w are **4,091 / 4,094 / 4,096 / 3,999 / 3,997 / 2,598 bytes**. Listed production scopes meet the two-file cap. TDD and named verification are present, subject to the corrections above.

**Verdict: fix 1–6 first.**

Not checked: application tests, live Discord, or implemented 300-line bounds; only source review and memory-only probes ran. Nothing changed.
Remaining risk: the draft’s Share-after-Done owner hold is still unresolved.

MUST=6 SHOULD=3 NIT=1
