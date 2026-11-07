What this change does: Closes both round 4 findings and places the amendment after completed M8.2a. It adds the missing raid-test coverage without expanding production scope.

Looks good. Ship.

Verified against `feature/pokewalker-v1.1-v2` at **4991a47**:

- **M6.8b:** Goal, Files and Verify now include `test_raids.py`. Its [line 376](<tests/test_raids.py:376>) still asserts version 15; the proposed migration-count assertion resolves the `0016` fallout.
- **M6.8f:** Verify now includes `test_raids.py`, covering existing confirmation, ownership, deletion and expiry regressions.
- **Renumbering:** M8.2a remains step 36; amendments occupy 37–45; existing 37–41 become 46–50. The implementation-row range remains correct.
- **Limits:** All nine tickets are ≤4,096 bytes and name ≤2 production files. Largest: M6.8d, **4,069 bytes**; changed tickets: M6.8b **3,999**, M6.8f **3,900**.
- Comparing the drafts with `amend-pre-r4` confirms only the three intended files changed. No new findings.

Not checked: runtime tests or eventual implementation size—paper review only. No files changed; working tree remains clean.

MUST=0 SHOULD=0 NIT=0
