What this change does: These 25 tickets specify the remaining v1 collection, rewards, inventory, account, moderation, sharing, monitoring, and deployment work.

**MUST FIX**

1. **A torn log tail can swallow the next successful deletion marker** — [M4.1a.md:17](<docs/features/pokewalker-bot/tickets/M4.1a.md:17>)

   **What this is:** Markers append as JSON lines; replay skips malformed lines.

   **Problem:** After a crash leaves an unterminated partial line, the next append joins valid JSON onto that tail. Replay skips the combined invalid line, losing the successfully fsynced marker. An in-memory probe confirmed zero valid records after this sequence.

   **Suggested fix:** Specify append recovery that preserves record boundaries after a torn tail without truncating valid history. Test crash-tail → restart → successful delete → restore/replay, including void records.

   **If skipped:** Restoring a backup can resurrect a profile whose deletion succeeded.

2. **REPEAT — Cancellation can leave a rolled-back deletion replayable** — [M4.1b.md:21](<docs/features/pokewalker-bot/tickets/M4.1b.md:21>)

   **What this is:** `run_marker` writes a void when `writer.run` raises `Exception`.

   **Problem:** The built writer separates caller cancellation from transaction completion ([test_db.py:210](<tests/test_db.py:210>)). Cancel the caller after append, then let the job fail: the writer rolls back, but the cancelled caller never receives that failure and writes no void. Worker abort also reports `CancelledError`, outside `Exception`. An in-memory probe using the actual writer produced `rollback=True log=['marker']`. Round 11 finding 1 remains incomplete.

   **Suggested fix:** Track the admitted job through actual completion despite caller cancellation; write a void after confirmed rollback. Do not simply void on caller cancellation—the job may commit. Test cancelled-waiter rollback, cancelled-waiter commit, and writer abort.

   **If skipped:** Startup can execute a deletion or participation change that rolled back.

**SHOULD FIX**

3. **REPEAT — Existing logs can leave initialization unrecorded** — [M4.1b.md:30](<docs/features/pokewalker-bot/tickets/M4.1b.md:30>)

   **What this is:** First-use detection combines log existence with `marker_log_init`.

   **Problem:** Initialization is recorded only when the log is absent. A crash between creating the log and recording initialization—or restoring an older database alongside the newest log—leaves an existing log without that record. Subsequent log loss is then mistaken for a fresh installation. Round 11 finding 5’s safeguard remains incomplete.

   **Suggested fix:** Record initialization when startup successfully adopts an existing log and the database lacks the record. Test interrupted initialization and restoration, followed by log loss and startup refusal.

   **If skipped:** Lost recovery metadata can silently become an empty log.

4. **Deployment omits the required unprivileged build step** — [M5.2a.md:27](<docs/features/pokewalker-bot/tickets/M5.2a.md:27>)

   **What this is:** The deployment script runs as root and builds the release environment.

   **Problem:** No privilege handoff separates `pip install` from the root operator context. The cited [deployment research:36](<docs/research/hosting/deploy-and-security.md:36>) explicitly requires an unprivileged deployment identity without the bot token.

   **Suggested fix:** Specify the build identity and credential-free environment, with privileged ownership and service operations handled separately. Add a harness assertion for the build identity and environment.

   **If skipped:** Dependency installation runs with unnecessary host privileges.

**NIT**

None.

Verdict: **NO-GO.** All 25 tickets and rounds 8–11 dispositions were reviewed. Other prior fixes are represented; unresolved findings are marked **REPEAT**. Owner-approved scope and supervisor rulings were respected. All tickets meet the 4,096-byte bound; `git diff --check` passed.

Not checked: Full runtime suites, live Discord, systemd deployment, or Google Drive recovery. No files were edited; the probes used in-memory state. Recovery and privilege risks remain as described.
MUST=2 SHOULD=2 NIT=0