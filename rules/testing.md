# Testing Rules

Behavior changes follow RED → GREEN → REFACTOR → VERIFY.

RED must fail for the intended missing/incorrect behavior, not because of syntax, fixtures, setup, or unrelated failures.
GREEN should result from the smallest reasonable implementation change.

Prefer the lowest test level that proves the behavior:
1. unit/domain;
2. contract;
3. integration;
4. e2e/render/system.

Do not mock the exact behavior under test so completely that the test becomes tautological.
Never weaken a valid assertion solely because implementation disagrees.
Record exact commands and results for meaningful changes.
