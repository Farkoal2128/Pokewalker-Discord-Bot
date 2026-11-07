What this change does: These 21 tickets specify the remaining collection, rewards, inventory, moderation, privacy, and deployment work after M1.9.

**MUST FIX**

1. **REPEAT — Existing receipts still survive profile deletion** — [M2.2a.md:18](<docs/features/pokewalker-bot/tickets/M2.2a.md:18>)

   **What this is:** The new owner column makes receipts cascade with their profile.

   **Problem:** The migration never backfills existing receipts. Updating producers protects future actions only. An in-memory probe using the built migrations plus the proposed migration confirmed that a legacy Run receipt remains after deleting its profile, with `profile_id=NULL`. Round 8 finding 1 remains unresolved for existing data.

   **Suggested fix:** Backfill ownership for existing enrollment, Throw, and Run receipts before relying on cascade deletion. Test upgrading a populated pre-M2.2a database, then deleting and replaying deletion.

   **If skipped:** Existing player data remains in receipts and subsequent backups.

2. **Opt-in does not supersede durable opt-out markers** — [M4.1.md:23](<docs/features/pokewalker-bot/tickets/M4.1.md:23>)

   **What this is:** Opt-out persists an external marker; opt-in deletes the database flag.

   **Problem:** After opt-out → opt-in → re-enrollment, restoring a database predating the opt-out receipt causes replay to insert `opt_outs` again. The new profile survives, but its owner becomes opted out again. Conversely, opting out without a profile writes no external marker, so that preference can disappear during restoration.

   **Suggested fix:** Define a replayable opt-out/opt-in lifecycle with durable ordering or supersession. Test both restoration scenarios using the newest marker log.

   **If skipped:** Restore can reverse the owner-approved participation choice.

3. **The account group grants excluded members extra commands** — [M4.1.md:30](<docs/features/pokewalker-bot/tickets/M4.1.md:30>)

   **What this is:** The entire `/walker-account` group is described as usable by excluded members.

   **Problem:** That includes `opt-out` and `opt-in`, while P15, D31, and built C5 explicitly permit only `privacy` and `delete-data`. The approved addition of opt-out/opt-in does not record a change to that exclusion exception.

   **Suggested fix:** Apply exclusion checks per subcommand, allowing only the two specified exceptions. Add acceptance cases for excluded callers invoking both new commands.

   **If skipped:** Implementation contradicts the established moderation boundary.

4. **Backup failures and stale copies have no alerting path** — [M5.2b.md:27](<docs/features/pokewalker-bot/tickets/M5.2b.md:27>)

   **What this is:** Backup writes `last-success`; failures produce nonzero exits.

   **Problem:** D28 requires failed-prune alerts and monitoring the age of the last successful off-machine marker copy. Nothing consumes `last-success` or turns backup/prune failures into alerts. M4.5b checks Gateway/writer health, so its heartbeat can remain healthy throughout a backup outage.

   **Suggested fix:** Specify the backup monitor and failure-alert path, including stale/missing success records and prune failures. Add offline behavioral tests.

   **If skipped:** Backup exposure and failed deletion retention can grow without notifying the owner.

**SHOULD FIX**

5. **Deployment does not define recovery from backup failure after stopping** — [M5.2a.md:29](<docs/features/pokewalker-bot/tickets/M5.2a.md:29>)

   **What this is:** Deployment stops the service before invoking `backup.sh`.

   **Problem:** M5.2b makes that command fail on snapshot, upload, or pruning failure. M5.2a specifies recovery for readiness failure, but no outcome for backup failure after stopping. Its acceptance tests omit this branch; a fail-fast implementation can leave the previous release stopped.

   **Suggested fix:** Define cleanup that restarts the unchanged previous release and reports deployment failure. Test snapshot failure and upload failure after a successful local snapshot.

   **If skipped:** An unsuccessful deployment can unnecessarily take the bot offline.

6. **Optional heartbeat configuration is not reconciled with mandatory readiness** — [M4.5b.md:41](<docs/features/pokewalker-bot/tickets/M4.5b.md:41>)

   **What this is:** Heartbeat acceptance includes “disabled without URL,” while deployment waits for its readiness file.

   **Problem:** The ticket does not distinguish disabling remote pings from disabling the health loop that creates `ready`. M5.2a requires that marker regardless of monitoring configuration. The isolated acceptance cases do not establish that deployment works without a heartbeat URL.

   **Suggested fix:** Explicitly keep local readiness checks active without remote monitoring. Add a healthy, no-URL test that produces the readiness marker and satisfies deployment.

   **If skipped:** A supported configuration can fail deployment readiness.

7. **Share’s router-size stop condition is already exceeded** — [M4.4.md:64](<docs/features/pokewalker-bot/tickets/M4.4.md:64>)

   **What this is:** The ticket conditionally moves router helpers when `walker.py` exceeds 300 lines.

   **Problem:** Built `walker.py` already has 396 lines, before the preceding tickets or post-commit hook. The fallback therefore introduces a foreseeable third production file beyond the declared two-file scope.

   **Suggested fix:** Resolve the scope before dispatch: explicitly include the bounded extraction, split it into a prerequisite, or revise the size condition deliberately.

   **If skipped:** Implementation immediately encounters an avoidable scope contradiction.

**NIT**

8. **Verification wording incorrectly says G-3 was skipped** — [M5.1.md:38](<docs/features/pokewalker-bot/tickets/M5.1.md:38>)

   **What this is:** The proposed PIPELINE wording distinguishes offline checks from live evidence.

   **Problem:** It labels G-3 “skipped,” but PLAN row 23 records owner-authorized live M1 smoke tests and fixes.

   **Suggested fix:** Say these commands do not establish live Discord acceptance; preserve the separately recorded G-3 evidence.

   **If skipped:** The verification documentation misstates completed work.

Verdict: **NO-GO.** Round 8 finding 1 remains unresolved. The other Round 8 remedies are represented in the revised tickets; the additional gaps above need reconciliation.

Not checked: Full test suites, live Discord, or host/systemd/Google Drive deployment and restore. This was source inspection plus an in-memory SQLite migration probe; no files were edited. Privacy and operational risks remain as described.

MUST=4 SHOULD=3 NIT=1