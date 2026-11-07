What this change does: These 27 tickets specify the remaining v1 collection, inventory, account, moderation, sharing, monitoring, and deployment work.

**MUST FIX**

None.

**SHOULD FIX**

1. **Release construction relocates an already-created virtual environment** — [M5.2e.md:21](<docs/features/pokewalker-bot/tickets/M5.2e.md:21>)

   **What this is:** The build creates `.venv` inside `<sha>.partial`, installs dependencies, then renames the directory.

   **Problem:** The cited [deployment research:53](<docs/research/hosting/deploy-and-security.md:53>) requires creating the environment at its final path. Generated console-script and activation paths retain `.partial`. The planned `python -m pokewalker` entry point may still work, but the environment contains stale paths.

   **Suggested fix:** Build the venv at the final release path, distinguish completed releases from interrupted builds, and test that installed script paths reference the final directory.

   **If skipped:** Mocked build checks can pass while installed executable entry points are broken.

2. **Rollback omits the schema-compatibility check** — [M5.2a.md:36](<docs/features/pokewalker-bot/tickets/M5.2a.md:36>)

   **What this is:** Readiness failure switches back to the previous release and starts it.

   **Problem:** Candidate startup applies migrations before Gateway readiness. Built [open_db:39](<pokewalker/db/__init__.py:39>) rejects schemas newer than the application supports. Rollback after migration can therefore start an incompatible release and fail. The cited [deployment research:58](<docs/research/hosting/deploy-and-security.md:58>) requires checking compatibility first.

   **Suggested fix:** Check compatibility before restarting the previous release. Define a stopped, recovery-required outcome when incompatible, retaining explicit authorization for database restoration. Add a migration-then-readiness-failure acceptance case.

   **If skipped:** Deployment attempts a doomed rollback and leaves recovery unclear. The existing database guard prevents silent downgrade.

**NIT**

None.

Verdict: **NO-GO pending these two corrections.** Reviewed all 27 tickets against P1–P17, scope boundaries, requirements, research, and relevant built code/contracts/tests. All accepted fixes from rounds 8–12 are represented; no unresolved **REPEAT** findings remain. Owner-approved scope and supervisor rulings were respected. All tickets meet the 4,096-byte bound; `git diff --check` passed.

Not checked: Runtime suites, live Discord, systemd/Drive recovery, or the unavailable installed `discord.py tree.py:249` anchor. No files edited; deployment risks remain as described.
MUST=0 SHOULD=2 NIT=0