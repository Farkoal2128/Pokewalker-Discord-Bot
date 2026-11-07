What this change does: The plan defines the v1 walking loop and its content and economy prerequisites. I reviewed all 18 tickets against the requirements, assuming one process serving a few hobby servers.

**Round-5 finding 1 is resolved at the planning level.** [M1.4b:19](<docs/features/pokewalker-bot/tickets/M1.4b.md:19>) removes reactions regardless of `actual`, and its acceptance cases include the reported crash. No findings were rejected; no **REPEAT** findings remain.

**SHOULD FIX**

1. **Successfully removed reactions are retried forever** — [M1.4b:19](<docs/features/pokewalker-bot/tickets/M1.4b.md:19>), [M1.6:17](<docs/features/pokewalker-bot/tickets/M1.6.md:17>)

   **What this is:** Opening `/walker` reconciles the profile’s reaction rows; startup reconciles every row marked `remove`.

   **Problem:** Successful removal leaves `desired='remove', actual='none'`, which remains eligible forever. After a player accumulates 500 cleared indicators, every subsequent `/walker` attempts 500 unnecessary deletions before rendering home. Startup repeats this across all players.

   **Suggested fix:** Retire successfully completed removal requests and sweep only pending work. Serialize reconciliation per reaction before retirement so an in-flight addition cannot recreate an indicator after its recovery record disappears. Add a test proving that a second `/walker` and startup make no calls for completed removals, while retaining the crash and delayed-add tests.

   **If skipped:** Normal play steadily increases redundant API traffic and screen-opening delays.

Verdict: Fix finding 1 before implementing the reaction workflow.

Not checked: runtime behavior or live Discord; no files changed or tests run. This is a planning defect, not an observed application failure.

MUST=0 SHOULD=1 NIT=0