What this change does: Re-anchors the amendment after M8.1c, assigns migration `0016`, and moves raid-return handling and tests into M6.8f/g. It preserves M7.7b’s deployment checks.

**Must fix:**

1. **M6.8b misses the raid migration test** ([M6.8b.md:26](<scratchpad>/amend/tickets/M6.8b.md:26)).
   - **What this is:** The ticket updates tests affected by migration `0016`.
   - **Problem:** [test_raids.py:376](<tests/test_raids.py:376>) upgrades to the latest schema but asserts version **15**. This exists at both `9840247` and current HEAD.
   - **Fix:** Add that assertion to the migration-count updates, and include `test_raids.py` in Files and Verify.
   - **If we skip it:** Following the ticket either hits its explicit stop condition or leaves a failing migration test: `16 != 15`.

**Should fix:**

2. **M6.8f omits existing raid regression checks** ([M6.8f.md:49](<scratchpad>/amend/tickets/M6.8f.md:49)).
   - **What this is:** The re-anchor adds changes to `open_encounter`’s shared raid-return branch.
   - **Problem:** Existing Master Ball/shiny confirmation, foreign-owner, deleted-raid and expiry tests live in `test_raids.py`, outside this ticket’s verification commands.
   - **Fix:** Add `python -m unittest discover -s tests -p "test_raids.py"` to M6.8f’s Verify.
   - **If we skip it:** The new shortcut tests can pass while existing raid navigation regresses unnoticed until final verification.

Other checks passed: `0016` is free; insertion after step 35 matches `9840247`; raid ownership/state/expiry checks and M7.7b guard notes match implementation. Every ticket is ≤4,096 bytes (largest: 4,069), names ≤2 production files, and retains the 300-production-line limit.

Current HEAD is **`4991a47`**, where M8.2a is also complete. Preserve that status when renumbering; the relevant implementation files above are unchanged since `9840247`.

Verdict: fix 1 first; address 2 before execution.

Not checked: runtime tests or actual implementation line counts—paper review only. No files changed; working tree remains clean.

MUST=1 SHOULD=1 NIT=0
