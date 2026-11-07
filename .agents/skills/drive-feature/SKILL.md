---
name: drive-feature
description: Continuously execute eligible tasks in a selected feature plan without stopping at routine checkpoints.
---

# Drive Feature

Use `implement-feature` for each bounded task.

## Loop
1. Reconcile recorded status with current code and evidence.
2. Resume interrupted work first when safe.
3. Select the earliest eligible incomplete task in authorized scope.
4. Execute it through implementation and relevant validation.
5. Update canonical plan/progress with actual results.
6. Continue immediately to the next eligible task.

Do not stop merely because a test fails, one child task completes, or an external gate blocks a different independent task. Investigate in-scope failures and continue independent authorized work.

Stop only when selected required scope is verified, the user pauses/cancels, an explicit limit is reached, or no in-scope task can be advanced. Never bypass a gate, invent evidence, self-approve independent review, or infer authorization for external/destructive actions.
