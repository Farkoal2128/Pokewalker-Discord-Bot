---
name: implement-feature
description: Implement and verify one bounded task from a canonical feature plan using contract-first TDD.
---

# Implement Feature

Read `AGENTS.md`, the feature README/plan/progress, relevant requirements, contracts, and local rules.

Resolve one eligible task. The canonical plan controls scope, dependencies, acceptance, and rollback. Current user instructions may intentionally change scope; record that rather than silently drifting.

For the task:
1. inspect current state and preserve unrelated work;
2. identify affected contracts and observable acceptance;
3. use TDD for behavior changes—meaningful RED before production implementation;
4. implement the smallest complete slice;
5. run focused GREEN and applicable broader verification;
6. update plan/progress with commands, results, blockers, and next eligible work;
7. report contract impact, implementation, evidence, and remaining gaps.

Existing code is not proof of acceptance. A task awaiting required independent review or environment validation is not Verified. Do not commit, merge, deploy, publish, spend money, or perform destructive operations unless separately authorized.
