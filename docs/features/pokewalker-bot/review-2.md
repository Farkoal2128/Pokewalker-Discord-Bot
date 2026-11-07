What this change does: The plan defines the v1 walking loop and its content-import and economy prerequisites. I reviewed all 15 tickets against the requirements and linked local research, assuming one process serving a few hobby servers.

All 11 previous findings are resolved **at the planning level**; none was rejected. No REPEAT findings remain.

| Previous finding | Resolution |
|---|---|
| 1 — Onboarding authorization | Sessions now support an absent profile and authenticate by guild/user. |
| 2 — Reopening encounters | Selection includes both `queued` and `revealed`, with reopen tests. |
| 3 — Exclusion | P15 requires checks at entry, routing and mutation boundaries. |
| 4 — Simultaneous restrictions | Restrictions now have independent fields. |
| 5 — Run overwriting Catch | Run checks state/revision; tests cover both execution orders. |
| 6 — Reaction cleanup | `/walker` acknowledges the indicator; delayed additions are reconciled. |
| 7 — Milestone omissions | All categories, five extra bundles and completeness checks are included. |
| 8 — Simulation queue clearing | Continuous and hourly-check styles are separate. |
| 9 — Companion progress | Progress pauses without a companion; swap verification is assigned. |
| 10 — Invalid threshold fixture | Uses four eligible words and expects 175 hundredths. |
| 11 — Dependency contradiction | Offline execution permits locked dependencies and retains shared step logic. |

**MUST FIX**

1. **Indefinite pauses have no defined representation** — [M1.4.md:14](<docs/features/pokewalker-bot/tickets/M1.4.md:14>)

   **Problem:** D31 permits indefinite pauses, but the restriction result exposes only `paused_until: datetime|None`; expired pauses also become `None`. Nothing distinguishes an indefinite pause from no pause, so handlers cannot reliably enforce the required restriction.

   **Suggested fix:** Add an explicit pause-active field, with `paused_until=None` meaning indefinite only while active. Test indefinite pause, timed expiry and resume through the earning checks.

2. **Fresh `/walker` sessions cannot recover a completed catch result** — [M1.8.md:30](<docs/features/pokewalker-bot/tickets/M1.8.md:30>), [M1.6.md:16](<docs/features/pokewalker-bot/tickets/M1.6.md:16>)

   **Problem:** M1.8 promises recovery when a catch commits before the Discord edit fails. But `/walker` creates a fresh session and renders home, while M1.7 selects only unresolved encounters. If the catch completed, neither path retrieves its terminal result. Reopening revealed encounters fixes previous finding 2; this completed-catch case remains a separate gap.

   **Suggested fix:** Define how `/walker` retrieves and displays an unacknowledged terminal result. Extend the recovery test through the actual fresh-session router, including a completed catch followed by another queued encounter.

3. **Channel configuration bypasses the required moderation audit** — [M1.4.md:29](<docs/features/pokewalker-bot/tickets/M1.4.md:29>)

   **Problem:** The new administrator commands specify neither a reason argument nor an audit write for `channels add` and `remove`. D31 requires both for moderation commands that change state. Counting policy could therefore change without the required explanation or record.

   **Suggested fix:** Require a reason on both mutations and commit the configuration change and audit entry together. Keep `list` read-only; test missing reasons and successful audit creation.

4. **Gender-selected varieties lack a complete artifact payload** — [M0.4.md:12](<docs/features/pokewalker-bot/tickets/M0.4.md:12>), [M1.3.md:20](<docs/features/pokewalker-bot/tickets/M1.3.md:20>)

   **Problem:** The importer specifies the default identity plus alternate Pokémon IDs for Indeedee, Basculegion and Oinkologne. Stats and sprite records are otherwise generated per encounter identity. Rolling a female ID therefore has no specified corresponding stat/sprite payload in the runtime artifact; merely changing the ID can leave male stats or artwork attached.

   **Suggested fix:** Include both varieties’ derived stats and exact sprite records in the artifact. Keep tier and route weight based on the male default as D53 requires. Test a forced female roll through import, encounter generation and rendering.

**SHOULD FIX**

5. **The economy report omits half of D47’s required comparison** — [M0.6.md:22](<docs/features/pokewalker-bot/tickets/M0.6.md:22>), [M0.7.md:15](<docs/features/pokewalker-bot/tickets/M0.7.md:15>)

   **Problem:** D47 asks the simulation to confirm both the walking/check-in shortfall and whether gym income closes it. The ticket explicitly excludes gym income and checks only the shortfall, leaving G-2 without evidence for the proposed remedy.

   **Suggested fix:** Add a labelled comparison using D23’s item distribution and D24’s tenure limit. This needs only a simulation calculation, with explicit holding-time assumptions; it does not require implementing v2 gyms.

Verdict: Fix 1–4 before implementation and complete the D47 comparison before G-2.

Not checked: runtime behavior, live Discord or external APIs; no files changed. These are plan defects, not observed application failures.

MUST=4 SHOULD=1 NIT=0