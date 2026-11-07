What this change does: The plan defines the v1 walking loop and its content and economy prerequisites. I reviewed all 17 tickets against the requirements, assuming one process serving a few hobby servers.

**Review-4 finding 1 is resolved at the planning level.** [M0.8:16](<docs/features/pokewalker-bot/tickets/M0.8.md:16>) now consumes berries during virtual throws, and [its acceptance test](<docs/features/pokewalker-bot/tickets/M0.8.md:42>) checks that subsequent attempts lose the bonus. No findings were rejected; no **REPEAT** findings remain.

**MUST FIX**

1. **A crash can leave an encounter reaction permanently uncleared** — [M1.5:35](<docs/features/pokewalker-bot/tickets/M1.5.md:35>)

   **What this is:** The reaction reconciler adds and removes the bot’s ❗ using persisted desired and actual states.

   **Problem:** Discord can accept the addition before the process crashes while saving `actual='added'`. After restart, `/walker` sets `desired='remove'`, but the database still says `actual='none'`. The specified removal condition therefore skips cleanup on every subsequent reconciliation, violating D3.

   **Suggested fix:** When removal is desired, attempt removal even if the stored actual state says none; an interrupted addition makes that state uncertain. Add a test that simulates Discord accepting the addition, crashes before the database update, then opens `/walker` after restart and verifies cleanup.

   **If skipped:** An obsolete ❗ can remain after the player has checked and resolved the encounter.

Verdict: Fix finding 1 before implementation.

Not checked: runtime behavior or live Discord; no files changed or application tests run. This is a planning defect, not an observed application failure.

MUST=1 SHOULD=0 NIT=0