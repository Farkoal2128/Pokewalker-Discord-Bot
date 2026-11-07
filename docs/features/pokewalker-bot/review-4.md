What this change does: The plan defines the v1 walking loop and its content and economy prerequisites. I reviewed all 17 tickets against the requirements, assuming one process serving a few hobby servers.

Both round-3 findings are resolved at the planning level; neither was rejected. No **REPEAT** findings remain.

| Previous finding | Resolution |
|---|---|
| 1 — Unmet ball demand | M0.8 defines stockouts, separately reports estimated unmet demand, and requires a deterministic insufficient-supply test. |
| 2 — Balance-file count | M0.3 now correctly lists 12 JSON files. |

**SHOULD FIX**

1. **Virtual throws can reuse the same berry indefinitely** — [M0.8.md:12](<docs/features/pokewalker-bot/tickets/M0.8.md:12>), [M0.6.md:18](<docs/features/pokewalker-bot/tickets/M0.6.md:18>)

   **What this is:** M0.8 estimates missing balls through virtual throws, retaining M0.6’s policy of using Razz Berries on Rare-or-higher encounters.

   **Problem:** It explicitly says inventory never changes on virtual throws. With zero balls and one Razz Berry, every virtual attempt can therefore receive that berry’s bonus. For a level-20 Legendary, the documented formula gives approximately 6.21% capture probability with Razz versus 4.18% without. After the first failed throw, subsequent attempts should lose the bonus when that sole berry is exhausted.

   **Suggested fix:** Exempt only the missing ball from inventory consumption; continue consuming available berries in the simulation. Add a deterministic test starting with zero balls and one berry: after a failed virtual throw, the next attempt uses no berry.

   **If skipped:** Ball demand can remain understated, making the gym-income comparison too optimistic.

Verdict: Fix finding 1 before relying on the G-2 economy report.

Not checked: runtime behavior or live services; no files changed or application tests run. The probability example passed a local arithmetic assertion.
MUST=0 SHOULD=1 NIT=0