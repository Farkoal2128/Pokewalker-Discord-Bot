What this change does: The amendment adds all 63 Alcremie forms, contextual purchase and capacity actions, and a U+FFFD guard. I reviewed it against `1ac0157` and branch HEAD `7871aab`, assuming the documented single-writer deployment serving a few hobby servers.

1. **MUST FIX — Assign the remaining content-test changes to M6.8d** — [M6.8d.md:33](<scratchpad>/amend/tickets/M6.8d.md:33)
   **Problem:** The rebuild changes the target count and sprite filenames, but this ticket omits `tests/test_content_evolutions.py`. Its assertions at lines 231 and 294 require exactly three targets; lines 241–242 require every target’s sprites to end in `/<pokemon_id>.png`. A read-only, in-memory probe confirmed these assertions reject the prescribed 65 targets and Alcremie form URLs. M6.8a only assigns the recipe-limit update in that file.
   **Suggested fix:** Add this test file to M6.8d’s scope. Deliberately update the expected target set/count and exact sprite expectations while retaining the existing stats, family, exclusion, and original-branch checks. This adds no production files.
   **If skipped:** M6.8d’s required content suite cannot pass without unbriefed test changes.

2. **SHOULD FIX — Explicitly replace Q1’s superseded recipe rule** — [PLAN-insert.md:64](<scratchpad>/amend/PLAN-insert.md:64)
   **Problem:** The amendment appends Q15 but leaves the current [PLAN.md:180](<docs/features/pokewalker-v1.1-v2/PLAN.md:180>) saying Alcremie has seven recipes and more than 25 recipes per source makes the build PENDING. The required 63-recipe result therefore satisfies Q15 while violating Q1’s active wording.
   **Suggested fix:** Include an explicit Q1 replacement for those sentences, referring to Q15’s sweet-first selection and per-item limits. Historical review records can remain unchanged.
   **If skipped:** Implementers and reviewers receive contradictory acceptance rules.

Round 1 verification:

| Finding | Result |
|---|---|
| SQLite row `.get()` crash | Addressed; `dict(row).get()` also verified with real in-memory SQLite rows. |
| Gym receipts discard forms | Addressed by M6.8i; current snapshot producers and renderer support the proposed one-file change. |
| Raid shortcuts lose encounters | Addressed by preserved selection and explicit M8.1c return/expiry tests. |
| Migration-test fallout | Addressed by M6.8b’s fixture/assertion updates and M8.1a’s numbering assignment. |
| Cross-sweet recipe acceptance | Addressed by group-bound validation and negative tests. |
| Obsolete verification blockers | Addressed; supplied sprite and encoding evidence is incorporated. |

No round 1 finding remains **REPEAT**. M7.7b’s replay-before-deployment order remains compatible. All nine tickets meet the 4,096-byte limit and declare at most two production files.

**Verdict: fix 1 before implementation; reconcile 2 in the same revision.**

Not checked: full application tests, live Discord, or implementation line counts. No files edited; the missing test assignment blocks the promised green sequence.
MUST=1 SHOULD=1 NIT=0