What this change does: Catches remain pending in their encounters until Done, Upgrade, or research resolves them. The amendment adds recovery, encounter blocking, and automatic research after 15 minutes while preserving catch-time rewards and Pokédex/milestone progress.

Reviewed all nine tickets against clean branch `feature/pokewalker-v1.1-v2`, HEAD `3e56b307c625baf17b0492a46bc2afd867d0be3c`. Assumed the documented single-process, serialized-writer deployment. Nothing changed.

**No must-fix or should-fix findings.**

**Nice to have**

1. **Activation leaves an unused import** ([M6.8u.md:12](<scratchpad>/amend3/tickets/M6.8u.md:12)).

   - **What this is:** M6.8u permits only the five-line catch INSERT deletion.
   - **Problem:** That removes the only use of `uuid4`, leaving its import at [catching.py:6](<pokewalker/services/catching.py:6>) unused.
   - **Fix:** Include deletion of that import in M6.8u and adjust its “five-line deletion” restriction.
   - **If we skip it:** One harmless dead import remains.

**Earlier fixes verified**

All thirteen earlier findings are addressed in the current draft. These are paper confirmations, not executed test results.

| Finding | Current verification |
|---|---|
| R1 #1: throw bypasses menu | `M6.8s.md:20–21,49–51` redirects pending results and tests the immediate response. |
| R1 #2: wrong `identify` return shape | `M6.8r.md:16` and `M6.8x.md:15` unpack `(identity, sprite)`. |
| R1 #3: cross-row Send dependency | Both-buttons test belongs to `M6.8t.md:41–43`. |
| R1 #4: activation fallout and legacy fixtures | `M6.8u.md:24–44` maps the cited failures and preserves separate legacy fixtures. |
| R1 #5: batch lookup loses UID | `M6.8t.md:14–20,43–44` passes each UID and retains batch regression checks. |
| R1 #6: disabled catch controls | `M6.8s.md:16,38` sets recovery and requires the exact menu. |
| R1 #7: Upgrade rollback | `M6.8s.md:46–48` tests failure after payment, complete rollback, and retry. |
| R1 #8: Mythical exemption | `M6.8x.md:38–41` independently covers non-shiny Mew. |
| R1 #9: reviewed replay after expiry | `M6.8r.md:21–26,41–44` places replay before expiry/pending checks and tests restart. |
| R1 #10: dropping `overflow_uid` | `PLAN-insert.md:22–30` correctly justifies retention as avoiding a migration. |
| R2 #1: `/raid` without a profile | `M6.8y.md:22–27,45–47` guards the lookup and preserves existing refusal cases. |
| R2 #2: Share on replayed results | `M6.8z.md:15–23,28–36` removes the renderer’s Share producer, preserves Storage sharing, and tests older-screen replay. |
| R2 #3: contradictory C3 paragraphs | `M6.8u.md:14–19`, `M6.8x.md:22–28`, `M6.8s.md:27–30`, and `M6.8t.md:26–29` cover deferred storage, legacy receipts, and manual/automatic acknowledgment. |

The owner’s Share decision is recorded in `PLAN-insert.md:167–176,302`; no Share decision remains unresolved.

The encounter-held predicate fits the current lifecycle. Profile deletion covers delete-data, opt-out, and administrator reset through cascades. Raid expiry preserves caught encounters. I found no separate runtime retention path deleting caught encounters or individual Pokémon rows that would accidentally recreate pending status. Catch-time Pokédex and milestone writes remain in the throw transaction.

The row order establishes services, sweep, menu, Send, and entry-point blocking before activation; the full-storage warning follows activation. Listed scopes satisfy the two-production-file limit. Ticket sizes **r–z** are **3,513 / 4,076 / 3,680 / 4,075 / 4,046 / 2,594 / 3,843 / 4,064 / 2,808 bytes**, all within 4,096.

**Verdict: Ship the plan amendment.**
Lean: −1 line possible.

Not checked: implementation tests, the author’s probe reproduction, or live Discord. Actual 300-line bounds and green intermediate trees remain unproven until implementation.

MUST=0 SHOULD=0 NIT=1
