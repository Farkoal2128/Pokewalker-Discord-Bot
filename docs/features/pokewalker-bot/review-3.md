What this change does: The plan defines the v1 walking loop and its content-import and economy prerequisites. I reviewed all 16 tickets against the requirements and previous findings, assuming one process serving a few hobby servers.

All five round-2 findings are **resolved at the planning level**. None was rejected; no **REPEAT** findings remain.

| Previous finding | Resolution |
|---|---|
| 1 — Indefinite pauses | M1.4 adds an independent `paused` flag and indefinite-pause, expiry and resume tests. |
| 2 — Completed-catch recovery | M1.9 adds unacknowledged results, fresh-session recovery and acknowledgement tests. |
| 3 — Channel moderation audit | M1.4 requires reasons and commits policy changes with audit entries. |
| 4 — Gender-variety payloads | M0.1–M0.4 carry both varieties’ stats and sprites; M1.3/M1.7 test female selection and rendering. |
| 5 — Gym-income comparison | M0.3 supplies the gym table; M0.6/M0.7 compare gym income against the shortfall under explicit holding assumptions. |

**SHOULD FIX**

1. **Define ball demand separately from stock-limited spending** — [M0.6.md:14](<docs/features/pokewalker-bot/tickets/M0.6.md:14>), [M0.7.md:15](<docs/features/pokewalker-bot/tickets/M0.7.md:15>)

   **What this is:** The simulation supplies the shortfall used to judge D47 and the gym-income comparison.

   **Problem:** It requires nonnegative balances and reports “balls in vs out,” but never defines unmet demand or what happens when balls run out. For example, a Legendary remains uncaught with zero balls: actual spending stops, and occupied queue slots can suppress further encounters. Spending alone therefore understates the demand the report is supposed to measure.

   **Suggested fix:** Specify the stockout behavior and report unmet ball demand separately from actual spending, using an explicitly labelled demand estimate. Add a deterministic insufficient-supply test that reports a positive deficit while inventory stays nonnegative.

   **If skipped:** G-2 could conclude that gym income closes a shortfall that the simulation has understated.

**NIT**

2. **The balance-table file count is stale** — [M0.3.md:30](<docs/features/pokewalker-bot/tickets/M0.3.md:30>)

   **What this is:** The ticket’s file list summarizes its write scope.

   **Problem:** It says “11 JSON files,” but the table now names 12, including `gym_income_table.json`.

   **Suggested fix:** Change 11 to 12, or omit the redundant count.

   **If skipped:** The stated file scope disagrees with the required outputs.

Verdict: Fix finding 1 before relying on the economy report at G-2.

Not checked: runtime behavior, live Discord or external APIs; no files changed or tests run. These are planning findings, not observed application failures.
MUST=0 SHOULD=1 NIT=1