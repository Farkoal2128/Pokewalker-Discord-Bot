What this change does: The amendment adds all 63 Alcremie forms with exact sprites, contextual purchase and capacity actions, and a U+FFFD guard. Reviewed against `1ac0157`, branch HEAD `036d339`, and the staged M7.7b changes, assuming the documented single-writer deployment serving a few hobby servers.

**No findings. No unresolved REPEAT items.**

| Prior finding | Round 3 verification |
|---|---|
| SQLite row lookup | M6.8b uses `dict(row).get()`; in-memory checks passed for missing, NULL and explicit `form_id`. |
| Gym snapshots lose forms | M6.8i assigns snapshot persistence, exact attacker/defender sprites, replay and legacy-receipt tests. |
| Raid shortcut returns | M6.8f/g preserve encounter selection; the M8.1c amendment specifies ownership, state, expiry and return tests. |
| Migration-test fallout | M6.8b assigns affected fixtures and assertions. `0015` remains free; M8.1a explicitly moves to `0016`. |
| Cross-sweet recipe acceptance | M6.8d requires group-bound validation and rejection tests. |
| Obsolete verification blockers | Supplied sprite and encoding evidence is incorporated; redundant network blockers are removed. |
| Missing content-test changes | M6.8d now assigns target counts and exact sprite assertions while retaining existing checks. |
| Conflicting Q1 rules | Explicit replacements reconcile target membership, 63 recipes and per-item limits. |

The atomic purchase reuses the existing transaction and receipts. M7.7b’s staged deployment guard remains after receipt replay; its refusal rolls back the combined purchase. Form persistence covers subsequent evolutions and gender varieties.

All nine tickets satisfy the 4,096-byte limit; the largest is **4,069 bytes**. Each declares at most two production files and retains the 300-line bound.

**Verdict: Ship the plan amendment, including its specified pending-ticket updates.**

Not checked: implementation line counts, application suites or live Discord. No files edited; moving branch anchors still need the prescribed adoption checks.

MUST=0 SHOULD=0 NIT=0
