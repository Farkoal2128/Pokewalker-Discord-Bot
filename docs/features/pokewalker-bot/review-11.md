What this change does: These 23 tickets specify the remaining v1 collection, rewards, inventory, account, moderation, sharing, monitoring, and deployment work.

**MUST FIX**

1. **REPEAT — Replay can reverse a later successful opt-in** — [M4.1a.md:35](<docs/features/pokewalker-bot/tickets/M4.1a.md:35>)

   **What this is:** Marker replay processes the log in order but skips markers with existing receipts.

   **Problem:** The built writer rolls back a failed job and continues accepting jobs. If opt-out appends its marker but its transaction fails, a subsequent opt-in can commit successfully. Startup then applies the earlier opt-out and skips the already-receipted opt-in. An in-memory probe reproduced this reversal. Round 9 finding 2 remains unresolved for this failure sequence.

   **Suggested fix:** Ensure a post-fsync application failure cannot leave an unapplied marker behind later committed participation changes. Resolve pending intent before admitting subsequent changes, or define replay that preserves the latest participation choice while keeping deletion/audit idempotent. Test failure → successful opt-in → restart.

   **If skipped:** Restart can opt out—and potentially delete the profile of—a player whose later opt-in succeeded.

2. **Blank reset reasons can leave an unreplayable marker** — [M4.3.md:26](<docs/features/pokewalker-bot/tickets/M4.3.md:26>)

   **What this is:** Reset validates authorization, appends its durable marker, then inserts its audit record.

   **Problem:** The pre-marker checks specify exclusion and enrollment, but omit blank-reason validation. The built audit table rejects whitespace-only reasons through `CHECK(length(trim(reason))>0)`. Consequently, reset can append a marker and then roll back; startup repeatedly fails on the same audit insertion before admitting work. An in-memory probe confirmed both failures.

   **Suggested fix:** Validate and normalize the required reason before appending any reset marker. Add a whitespace-reason test asserting no marker, no mutation, and successful subsequent startup.

   **If skipped:** An invalid moderator command can prevent the bot from starting.

3. **REPEAT — Failed pruning is not reliably retried after snapshots are forgotten** — [M5.2b.md:23](<docs/features/pokewalker-bot/tickets/M5.2b.md:23>)

   **What this is:** Remote cleanup invokes `restic forget <ids> --prune` only when stale snapshot IDs exist.

   **Problem:** Forgetting snapshots and removing their underlying data are separate operations. If forgetting succeeds but pruning fails, the next run can find no stale IDs and perform no cleanup; line 40 explicitly accepts that branch as success. The data remains despite D28’s retry requirement. This leaves Round 8 finding 2 incompletely resolved. [Restic documentation](https://restic.readthedocs.io/en/stable/060_forget.html) confirms the two-stage behavior.

   **Suggested fix:** Retry repository pruning independently of whether this invocation finds snapshots to forget. Test successful forgetting followed by failed pruning, then a second run with no stale snapshots but remaining unreferenced data.

   **If skipped:** Deleted player data can remain off-machine beyond retention while subsequent runs report success.

**SHOULD FIX**

4. **Receipt migration acceptance requires incompatible tests to remain unchanged** — [M2.2a.md:51](<docs/features/pokewalker-bot/tickets/M2.2a.md:51>)

   **What this is:** Migration 0003 must pass the existing database suite unchanged.

   **Problem:** [test_db.py:75](<tests/test_db.py:75>) explicitly expects schema version 2. Its newer-database test at line 88 sets version 3 and expects rejection. Both assertions contradict installing migration 0003.

   **Suggested fix:** Explicitly authorize requirement-driven updates to those two tests. Preserve the assertions that migrations apply once and genuinely newer schemas are refused; use the current supported version and a version above it.

   **If skipped:** The ticket’s stated acceptance conditions cannot all pass.

5. **The marker log has no first-use initialization contract** — [M5.2c.md:25](<docs/features/pokewalker-bot/tickets/M5.2c.md:25>)

   **What this is:** Every backup requires a marker-log copy; a missing log is snapshot failure.

   **Problem:** M4.1a specifies appending markers and replaying an existing log, but no initialization of a valid empty log. Before the first account action, a fresh installation can therefore have no log and fail every backup. Deployment also treats that failure as fatal.

   **Suggested fix:** Define where a fresh installation creates and durably initializes its empty marker log. Distinguish first initialization from unexpectedly missing recovery metadata. Test startup and backup before any deletion or participation change.

   **If skipped:** Backup protection depends on somebody first executing an account mutation.

6. **Operator deployment lacks an explicit configuration handoff** — [M5.2a.md:26](<docs/features/pokewalker-bot/tickets/M5.2a.md:26>)

   **What this is:** An operator shell runs `check-config`, directly invokes `backup.sh`, and waits on `$RUNTIME_DIRECTORY/ready`.

   **Problem:** The configuration providers described elsewhere are service-local: bot `LoadCredential`/`EnvironmentFile`, backup `EnvironmentFile`/`StateDirectory`, and bot `RuntimeDirectory`. Those do not populate the invoking operator shell. No handoff supplies the direct backup invocation’s required monitor/repository configuration or the deployment script’s credential and readiness paths. PATH shims alone will not test this integration.

   **Suggested fix:** Specify how operator-run deployment obtains protected configuration, invokes the backup with its required environment, and resolves the readiness path. Add a clean-environment test with service-only variables absent.

   **If skipped:** Scripts can pass isolated tests yet fail during the documented operator-run deployment.

**NIT**

7. **PLAN summaries still describe the pre-split layout** — [PLAN.md:70](<docs/features/pokewalker-bot/PLAN.md:70>)

   **What this is:** Sections 3.3, 4.2, and 6 summarize implementation locations and ticket ownership.

   **Problem:** Section 3.3 retains obsolete domain/layout estimates and `M5.2`; the C6 row still assigns ownership to `M5.2`; section 6 omits the newly briefed rows. Section 4.4 also still says M2–M5 will be briefed on reach.

   **Suggested fix:** Reconcile these summaries with the current ticket files and M5.2c’s C6 ownership.

   **If skipped:** Readers receive stale navigation and ownership information.

8. **Some built-code anchors have drifted** — [M3.4.md:17](<docs/features/pokewalker-bot/tickets/M3.4.md:17>), [M2.2a.md:13](<docs/features/pokewalker-bot/tickets/M2.2a.md:13>)

   **What this is:** Tickets provide exact anchors for existing tests and receipt producers.

   **Problem:** `test_lure_and_generated_roll_are_frozen` starts at `test_stepping.py:162`, whereas line 157 starts the missing-timestamp test. Run’s `with_receipt` call is at `walker.py:344`; line 343 is blank.

   **Suggested fix:** Refresh those anchors against the reviewed tree.

   **If skipped:** Implementers land on unrelated or empty lines.

Verdict: **NO-GO.** All 23 tickets and the rounds 8–10 dispositions were reviewed. Other prior remedies are represented; all tickets satisfy the 4,096-byte bound. Owner-approved scope and the supervisor’s opt-out exception were respected. Read-only artifact checks passed, and `git diff --check` reported no whitespace errors.

Not checked: Full runtime suites, live Discord, systemd deployment, or Google Drive recovery. No files were edited; the probes used in-memory state. Replay, startup, and retention risks remain as described.

MUST=3 SHOULD=3 NIT=2