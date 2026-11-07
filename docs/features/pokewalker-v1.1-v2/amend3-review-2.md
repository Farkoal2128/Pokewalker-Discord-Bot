What this change does: Catches remain in their encounters until Done, Upgrade, or research resolves them. The amendment adds recovery, encounter blocking, and automatic research after 15 minutes, while preserving catch-time rewards and Pokédex/milestone progress.

Reviewed the eight draft tickets against clean branch `feature/pokewalker-v1.1-v2`, HEAD `3e56b307c625baf17b0492a46bc2afd867d0be3c`. Assumed the documented single-process, serialized-writer deployment. Nothing changed.

**Must fix**

1. **The `/raid` pending check dereferences a missing profile** ([M6.8y.md:22](<scratchpad>/amend3/tickets/M6.8y.md:22)).

   - **What this is:** `/raid` checks for a pending catch before calling the existing join service.
   - **Problem:** The draft passes `profile["profile_id"]` without first handling `get_profile()` returning `None`. An unenrolled member—or someone invoking `/raid` in another server—therefore fails before receiving the existing enrollment/no-active-spawn response. These cases already exist at [test_raids.py:1532](<tests/test_raids.py:1532>) and [test_raids.py:1734](<tests/test_raids.py:1734>).
   - **Fix:** Explicitly run the pending lookup only when a profile exists; otherwise continue through `raids.join`. Keep both existing tests in M6.8y’s acceptance criteria.
   - **If we skip it:** Following the ticket literally breaks `/raid` for unenrolled users and prevents that row from finishing green.

2. **Older encounter screens can still produce Share outside Storage** ([PLAN-insert.md:171](<scratchpad>/amend3/PLAN-insert.md:171)).

   - **What this is:** Q22 makes Share available only from Storage details after Done.
   - **Problem:** Open the same encounter in two sessions; catch and press Done in the first, then press Throw in the second. There is no pending catch anymore, so the router allows it; [walker.py:481](<pokewalker/bot/walker.py:481>) returns the ordinary result renderer, which adds Share at [screens_catch.py:80](<pokewalker/bot/screens_catch.py:80>). The supposedly producer-free result-sharing branch remains reachable.
   - **Fix:** Remove Share from the terminal renderer in M6.8s’s existing file scope. Move the affected Share assertions into that row and add `test_stored_catch_replayed_from_older_screen_has_no_share`, preserving Storage-details sharing.
   - **If we skip it:** The implementation contradicts the owner’s Share decision and the final smoke requirement that no result screen shows Share.

3. **The contract edit leaves immediate-storage guarantees intact** ([M6.8u.md:15](<scratchpad>/amend3/tickets/M6.8u.md:15)).

   - **What this is:** M6.8u updates C3’s catch contract only at lines 198–208.
   - **Problem:** [persisted-state.md:213](<contracts/persisted-state.md:213>) still requires the Pokémon row to commit with the throw, and [line 227](<contracts/persisted-state.md:227>) says the receipt retains its UID. [Line 224](<contracts/persisted-state.md:224>) also permits only `ack` to acknowledge encounters, contradicting M6.8x’s automatic acknowledgment.
   - **Fix:** Extend the explicit contract edits through the catch and acknowledgment paragraphs. Distinguish legacy receipts from new pending results, and name both manual and automatic resolution transactions.
   - **If we skip it:** The authoritative contract simultaneously requires immediate storage and forbids it, leaving implementation and review with conflicting acceptance rules.

**Round-1 disposition verification**

All ten original corrections are present and match the referenced code. These are paper confirmations:

| Round-1 finding | Verification |
|---|---|
| #1 Throw bypasses menu | M6.8s:21–22 redirects pending results; :50–52 tests the actual response. |
| #2 `identify` return shape | M6.8r:16 and M6.8x:15 explicitly unpack the pair. |
| #3 Cross-row Send dependency | Both-buttons test moved to M6.8t:39–41. |
| #4 Activation fallout/legacy fixtures | M6.8u:22–43 corrects the cited fallout and separates pending from legacy fixtures. |
| #5 Batch lookup loses UID | M6.8t:14–20 passes each UID explicitly and preserves revision checks. |
| #6 Disabled catch controls | M6.8s:17 sets recovery; :39 names the exact-menu test. |
| #7 Upgrade rollback | M6.8s:47–49 tests failure after payment and successful retry. |
| #8 Mythical exemption | M6.8x:35–38 includes non-shiny Mew independently of Legendary protection. |
| #9 Reviewed replay after expiry | M6.8r:21–26 orders replay correctly; :41–44 tests it after restart. |
| #10 Dropping `overflow_uid` | PLAN-insert:22–30 corrects the claim; the existing migration test does drop it. |

The Share owner hold is resolved in Q22; finding 2 concerns implementing that decision.

The pending predicate otherwise fits the current lifecycle. Owned-only readers exclude pending catches; catch-time Pokédex/milestone writes remain intact; delete-data, opt-out, and admin reset cascade through profile deletion; raid expiry preserves caught encounters. I found no runtime retention path that deletes individual caught Pokémon rows and accidentally recreates pending status.

Ticket sizes r–y are **3,513 / 4,078 / 3,437 / 4,077 / 4,046 / 2,594 / 3,609 / 3,801 bytes**. Listed production scopes satisfy the two-file cap. The service → sweep → menu → send → lock → activation → warning → cleanup order is coherent, subject to the fixes above.

**Verdict: fix 1, 2, and 3 first.**

Not checked: no implementation, tests, or author-probe reproduction; actual 300-line bounds and green intermediate trees remain unproven.

MUST=3 SHOULD=0 NIT=0
