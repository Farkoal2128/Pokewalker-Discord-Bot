What this change does: The amendment adds research sending to caught results, replaces full-storage refusal with a forced Send/Upgrade choice and timed fallback, removes Home’s Claim button, and adds bulk channel configuration. I reviewed all eight tickets against pinned HEAD `fd40c3efdde3ce7b8a8a0d3cc02223e14fd12674`, assuming one database writer and multiple concurrent sessions.

**Must fix:**

1. **The fresh permission check still happens before the queue wait** ([M6.8p.md:19](<scratchpad>/amend2/tickets/M6.8p.md:19), [M6.8p.md:31](<scratchpad>/amend2/tickets/M6.8p.md:31)).
   - **What this is:** `fetch_member` replaces the stale interaction member, but runs before submitting the mutation.
   - **Problem:** Fetch succeeds; another writer job delays the batch; the actor loses their Manage Server role; the batch then enables channels. The new test removes permission **before fetching**, so it misses the original queued-revocation case. Naming this a residual window does not close round-2 finding 2.
   - **Fix:** Check fresh membership when the queued mutation starts, with a bounded lookup that refuses on failure. Restore the queued-role-removal regression; otherwise explicitly obtain owner acceptance of the weaker authorization rule.
   - **If we skip it:** A former administrator can still enable channels after losing permission while queued.

**Should fix:**

2. **The new fallback’s atomic cleanup lacks a failure test** ([M6.8q.md:38](<scratchpad>/amend2/tickets/M6.8q.md:38)).
   - **What this is:** The fallback combines research disposition, Candy, receipt, encounter acknowledgment and overflow clearing in one transaction.
   - **Problem:** Named tests cover successful sending, repetition and exclusion, but none fails **after `send` succeeds**. Existing research rollback coverage fails inside `send`; the sweep rollback test fails at raid expiry, before this new work ([test_research.py:431](<tests/test_research.py:431>), [test_raids.py:1756](<tests/test_raids.py:1756>)).
   - **Fix:** Name one test that makes acknowledgment or overflow clearing fail after sending. Assert that Pokémon state, Candy, receipt, ledger and pending record all roll back; retry then succeeds once.
   - **If we skip it:** The newly promised transaction boundary has no regression test against partial completion.

The prior-finding audit is:

| Finding | Round-3 result |
|---|---|
| R1 #1: wrong Pokémon selected | Fixed: `overflow_uid` identifies the crossing catch; A-at-limit/B-over-limit regression retained. |
| R1 #2: lock bypasses | Fixed: router-wide guard binds allowed actions to the pending encounter; `/raid` checks before joining. |
| R1 #3: New review opens bulk picker | Fixed: `caught` survives and rebuilds the same Pokémon’s single review. |
| R1 #4: fresh recovery loses selection | Fixed: choice explicitly persists `sessions.selection`; both buttons are tested. |
| R1 #5: warning precedes terminal/stale/expiry checks | Fixed: warning follows the service refusal; raid Back and Master Ball cases are named. |
| R1 #6: recovery omits Send | Fixed: shared renderer covers all seven callers and updates existing label assertions. |
| R1 #7: broken intermediate rows | Fixed on paper: record → lock → fallback → activate → remove old handlers. |
| R1 #8: contradictory active rules | Fixed: Q4, Q16, C3/C5 and final smoke replacements are assigned. |
| R1 #9: authorization recheck | Still open through finding 1 above. |
| R1 #10: blanket test deletion | Fixed: ordinary Storage/Expand coverage and mixed access checks remain. |
| R2 #1: lazy fallback misses deadline | Fixed: session-free sweep, restart catch-up and no-interaction tests are specified. |
| R2 #2: stale member roles | Partially fixed; queue-time revocation remains. |

**A lazy next-interaction fallback does not satisfy the confirmed 15-minute requirement.** An idle player might never interact again. The proposed sweep addresses that, with its documented allowance of approximately one minute plus writer delay and restart catch-up.

I found no additional receipt or raid-state defect: the synthetic selection fits unchanged `research.send`, the UID receipt carries its owner, and raid expiry preserves caught encounters needed by fallback.

All tickets fit 4,096 bytes: **j–q = 4,086 / 4,037 / 3,501 / 4,081 / 2,570 / 2,160 / 4,078 / 4,076**. Production scopes are **2 / 2 / 2 / 2 / 2 / 1 / 1 / 2 files**. Named tests and inherited RED requirements are present; actual 300-line compliance remains an implementation check.

**Verdict: fix 1 first; add the failure test in 2.**

Not checked: executable tests, live Discord or implementation line counts. Nothing changed; this is paper review evidence only.

MUST=1 SHOULD=1 NIT=0
