What this change does: These 23 tickets specify the remaining v1 collection, rewards, inventory, account, moderation, sharing, monitoring, and deployment work.

**MUST FIX**

1. **REPEAT — Opt-in can persist an instruction that authorization rejects** — [M4.1.md:28](<docs/features/pokewalker-bot/tickets/M4.1.md:28>)

   **What this is:** Opt-in fsyncs its marker before applying it, while exclusion must be checked inside the writer transaction.

   **Problem:** An exclusion job can already be queued when the handler appends the marker. Exclusion commits first, so the live opt-in must refuse—but startup replay subsequently applies its saved marker without authorization checks. This leaves Round 9 finding 3 unresolved at the transactional boundary and contradicts `test_excluded_opt_in_refused_no_marker_no_change`.

   **Suggested fix:** Specify one serialized ordering for authoritative authorization, marker fsync, and application. Rejected invocations must leave no replayable intent. Test the queued-exclusion interleaving.

   **If skipped:** Restart can execute an opt-in that P15 required refusing.

2. **REPEAT — Combined backup failures can bypass the verified-snapshot prerequisite** — [M5.2b.md:30](<docs/features/pokewalker-bot/tickets/M5.2b.md:30>), [M5.2a.md:32](<docs/features/pokewalker-bot/tickets/M5.2a.md:32>)

   **What this is:** Backup always attempts pruning; deployment treats exits 2 and 3 as evidence of a verified local snapshot.

   **Problem:** Snapshot failure specifies exit 1, but subsequent prune failure specifies exit 3. No precedence resolves that combination. Returning 3 permits deployment without its recovery snapshot. Acceptance tests cover failures separately, leaving Round 9 finding 5 incompletely resolved.

   **Suggested fix:** Keep snapshot failure deployment-fatal regardless of cleanup failures. Define combined-error precedence and marker-copy failure handling; test snapshot-plus-prune failure through the deploy/backup boundary.

   **If skipped:** Deployment can change the release and database without the required recovery copy.

**SHOULD FIX**

3. **Companion acceptance requires an obsolete assertion to remain unchanged** — [M2.4.md:46](<docs/features/pokewalker-bot/tickets/M2.4.md:46>)

   **What this is:** M2.4 adds Candy payment and remainder handling at 15,000 hundredths.

   **Problem:** The explicitly preserved test seeds 14,900, awards 400, and asserts **15,300** at [test_stepping.py:106](<tests/test_stepping.py:106>). Correct new behavior produces **300 plus one Candy**. Both acceptance conditions cannot hold.

   **Suggested fix:** Explicitly authorize the D25-driven assertion revision, preserving the no-companion freeze coverage and asserting the Candy credit and remainder.

   **If skipped:** Implementation must violate either the new behavior or the unchanged-test requirement.

4. **REPEAT — The router-only extraction cannot meet its acceptance limit** — [M4.4a.md:31](<docs/features/pokewalker-bot/tickets/M4.4a.md:31>)

   **What this is:** Extraction must reduce `walker.py` to at most 300 lines without moving handlers.

   **Problem:** Built `walker.py` has 396 lines. `route` and `refuse` account for 41; the other named pieces remove roughly another dozen. M2.1’s lookup extraction does not close the gap, and preceding tickets add wiring. The move therefore encounters its own stop condition, leaving Round 9 finding 7 unresolved.

   **Suggested fix:** Define a feasible bounded extraction or deliberately revise the whole-file limit while retaining the production-change scope limit.

   **If skipped:** Dispatch stops on a predictable scope contradiction before Share proceeds.

5. **REPEAT — Backup remains oversized after the split** — [M5.2b.md:50](<docs/features/pokewalker-bot/tickets/M5.2b.md:50>)

   **What this is:** M5.2b owns snapshot/upload, failure notification, pruning, and retention selection.

   **Problem:** It introduces four executable files—`backup.sh`, `backup_alert.sh`, `prune.sh`, and `prune_select.py`—against the two-production-file seam bound. Its ticket is 5,442 bytes, above 4 KB. M2.2a, M4.4, M5.1, and M5.2a also exceed the ticket limit. Round 8 finding 14’s behavioral-test remedy is present, but its scope remedy remains incomplete.

   **Suggested fix:** Finish the bounded decomposition with explicit cross-row exit-code and retention contracts, and bring affected briefs within the required size bound.

   **If skipped:** Execution starts with work orders outside the selected workflow’s reviewable limits.

6. **M5.1 contradicts the focused-verification boundary** — [M5.1.md:51](<docs/features/pokewalker-bot/tickets/M5.1.md:51>)

   **What this is:** M5.1 labels verification focused but requires full `test_cmd`; its `verify.py` command also invokes every unit test.

   **Problem:** PLAN §4.3 reserves full qualification for SI-0 and G-F. M5.1 is neither boundary, and M5.2 follows it.

   **Suggested fix:** Use focused activation/configuration checks and retain full execution at G-F, or explicitly establish an authorized source increment in the canonical plan.

   **If skipped:** Dispatch instructions conflict and can produce a misleading focused receipt.

**NIT**

None.

Verdict: **NO-GO.** All 23 tickets and both prior rounds’ remedies were reviewed. Remaining earlier issues are marked **REPEAT**; no rejected finding was reopened. Owner-approved scope and the supervisor’s opt-out exception were respected.

Not checked: Runtime tests, live Discord, systemd deployment, or Google Drive recovery. No files were edited; authorization and recovery risks remain as described.

MUST=2 SHOULD=4 NIT=0