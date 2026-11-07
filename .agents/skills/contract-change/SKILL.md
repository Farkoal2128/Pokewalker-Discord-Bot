---
name: contract-change
description: Safely change a public/domain boundary with explicit compatibility analysis and contract tests.
---

# Contract Change

1. Find the existing authoritative contract.
2. Confirm the requirement actually requires a contract change.
3. Identify producers, consumers, persisted data, and clients.
4. Classify compatible or breaking.
5. Update the requirement first when expected behavior changes.
6. Change the contract intentionally.
7. Add/update contract tests before provider/consumer implementation.
8. Implement affected producers/consumers.
9. Run compatibility and regression verification.
10. Record an ADR when format, boundary, or compatibility policy changes materially.

Never modify a contract just because current implementation fails it.
