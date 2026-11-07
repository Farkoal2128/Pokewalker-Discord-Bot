What this change does: These 18 tickets specify the remaining v1 collection, rewards, inventory, moderation, privacy, and deployment work after M1.9.

**MUST FIX**

1. **Deletion leaves saved Run results behind** — [M4.1.md:22](<docs/features/pokewalker-bot/tickets/M4.1.md:22>)

   **What this is:** The deletion service identifies receipts through enrollment, resource-ledger entries, and catch attempts.

   **Problem:** Built `walker.py:337–343` saves Run receipts containing the encounter, including profile and source-message IDs, with **no ledger entries or catch attempt**. The proposed deletion misses them. An in-memory probe confirmed that the profile disappears while its Run receipt remains, violating D28 and C3.

   **Suggested fix:** Define complete receipt ownership and deletion, including Run and later actions without resource deltas. Test deletion and startup replay after Run, including absence of the saved fixture bytes.

   **If skipped:** Deleted player data remains in the live database and subsequent backups.

2. **The pruning commands do not enforce 28-day retention** — [M5.2.md:35](<docs/features/pokewalker-bot/tickets/M5.2.md:35>)

   **What this is:** Local and off-machine cleanup implements D28’s age-only deletion promise.

   **Problem:** `restic --keep-within 28d` measures from the **latest snapshot**, so uploads stopping also stops that cutoff advancing. Its default grouping by paths additionally conflicts with backing up uniquely named snapshot files. Locally, `-mtime +28` waits until 29 complete days. These behaviors contradict deletion after 28 days regardless of upload success. [Restic documentation](https://restic.readthedocs.io/en/stable/060_forget.html), [GNU Findutils documentation](https://www.gnu.org/software/findutils/manual/html_node/find_html/Age-Ranges.html).

   **Suggested fix:** Select backup files and remote snapshot IDs against an explicit current-time cutoff, scoped to this application. Test stale-only repositories, unique backup paths, and the 28-day boundary with failed uploads.

   **If skipped:** Backups can retain deleted data indefinitely despite successful prune commands.

3. **Share has no supported after-commit execution path** — [M4.4.md:23](<docs/features/pokewalker-bot/tickets/M4.4.md:23>)

   **What this is:** Sharing reserves the rate limit transactionally, then posts to Discord.

   **Problem:** Every registered handler runs inside `Walker.route`’s writer transaction (`walker.py:97–122`) and returns a rendered response. There is no after-commit callback. Implementing the prescribed handler literally either posts before commit or recursively queues a writer job, which C3 rejects. The three wiring lines are already allocated to registration and button changes.

   **Suggested fix:** Explicitly scope a small router extension for post-commit effects and update C5. Test through the real router that rollback sends nothing and a slow channel send does not hold the writer.

   **If skipped:** Public posts can precede failed commits, or sharing blocks/fails other database work.

4. **Guild-only admin registration breaks the existing sync manifest** — [M4.5.md:24](<docs/features/pokewalker-bot/tickets/M4.5.md:24>)

   **What this is:** `/admin` is registered separately in the configured development guild.

   **Problem:** Built `client.py:187–193` copies global commands into a guild only when that guild has **no commands**. Adding `/admin` prevents that copy. A mocked probe produced a guild manifest containing only `admin`, omitting `walker` and `walker-admin`. The alternative global registration also contradicts the cited research’s restricted-discovery requirement.

   **Suggested fix:** Define the complete manifest for each scope, preserving gameplay commands alongside guild-only administration. Test the actual sync path with both command kinds present.

   **If skipped:** Guild synchronization removes or omits gameplay commands, while production configuration can expose admin discovery globally.

5. **Mythical Pokémon are missing from the operative transfer protections** — [M2.2.md:26](<docs/features/pokewalker-bot/tickets/M2.2.md:26>)

   **What this is:** Research-send guards protect collectible Pokémon from bulk removal.

   **Problem:** The operative checks, single-send warning, and acceptance cases name shiny and Legendary Pokémon but omit Mythicals. The artifact distinguishes these flags: Mew has `is_legendary=False`, `is_mythical=True`. Checking the listed Legendary flag therefore permits bulk disposal contrary to D41.

   **Suggested fix:** Specify `is_legendary or is_mythical` explicitly throughout candidate protection, transaction validation, and single-send warnings. Add a non-shiny Mythical test.

   **If skipped:** A protected Mythical can be irreversibly sent without its required safeguards.

6. **The shared grant helper contradicts milestone preservation** — [M3.1.md:24](<docs/features/pokewalker-bot/tickets/M3.1.md:24>)

   **What this is:** `items.grant` handles full bags and duplicate rare items.

   **Problem:** The ticket explicitly makes this helper shared with M2.6, but it converts oversized ordinary packs to Stardust and duplicate rare items to 500 Stardust. M2.6 and D59 require partial ordinary claims and retention of blocked rewards in the inbox.

   **Suggested fix:** Restrict this conversion helper to finds/check-ins. Keep milestone claiming’s existing “move what fits, retain the remainder” behavior, with a regression test after M3.1 integration.

   **If skipped:** Later integration can convert or destroy rewards that D59 promises never to lose.

7. **Interrupted moderator reset can delete without an audit entry** — [M4.3.md:23](<docs/features/pokewalker-bot/tickets/M4.3.md:23>)

   **What this is:** Reset writes a deletion marker before atomically deleting and auditing.

   **Problem:** A crash after marker synchronization but before the writer job leaves startup replay to perform the deletion. M4.1 replay only calls `delete_profile`; its marker contains no actor or reason. The reset completes without the D31 audit record.

   **Suggested fix:** Durably preserve the reset intent’s audit information before deletion becomes recoverable, and make normal execution and replay complete the same idempotent deletion-and-audit operation. Assert exactly one audit entry in the interrupted-reset test.

   **If skipped:** A moderator can permanently erase a profile without the required attribution and reason.

8. **REPEAT — Owner commands omit the exclusion check** — [M4.5.md:25](<docs/features/pokewalker-bot/tickets/M4.5.md:25>)

   **What this is:** `/admin` authorizes callers solely through the owner-ID allowlist.

   **Problem:** P15 and D31 permit an excluded member only privacy and delete-data in that server. No exception is defined for an allowlisted owner, but this ticket allows that owner to invoke status, errors, and restart. This repeats review-1 finding 3’s missing command-entry restriction check.

   **Suggested fix:** Check current guild exclusion on every admin invocation and restart confirmation. Test an allowlisted owner excluded in that guild.

   **If skipped:** Exclusion does not enforce the plan’s stated command boundary.

**SHOULD FIX**

9. **The bulk research screen has no navigation entry** — [M2.2.md:31](<docs/features/pokewalker-bot/tickets/M2.2.md:31>)

   **What this is:** The ticket builds a paged, 20-Pokémon research workflow.

   **Problem:** M2.1’s storage page offers pagination, selection, and Back. M2.2 only enables the details button leading to **single** send; nothing opens the `research` handler. Handler registration alone does not create a visible control.

   **Suggested fix:** Add Storage → Send for research and an acceptance test navigating from `/walker` through a multi-page batch.

   **If skipped:** The bulk workflow can pass direct-handler tests while remaining inaccessible to players.

10. **Share-ban does not remove Share buttons** — [M4.4.md:38](<docs/features/pokewalker-bot/tickets/M4.4.md:38>)

   **What this is:** The ticket enables Share on catch and storage screens.

   **Problem:** D31 explicitly requires share-ban/unban to remove/restore those buttons. The ticket enables them unconditionally and checks the ban only after clicking. The existing terminal renderer also includes its placeholder for fled and ran encounters.

   **Suggested fix:** Render Share only for an eligible owned Pokémon and an unbanned player; retain transaction checks for already-open screens. Test ban/unban and non-catch terminal results.

   **If skipped:** The interface contradicts moderation requirements and presents actions that cannot succeed.

11. **Restart cooldown is not specified across process replacement** — [M4.5.md:33](<docs/features/pokewalker-bot/tickets/M4.5.md:33>)

   **What this is:** Owner restart requires confirmation and a five-minute cooldown.

   **Problem:** Successful restart exits the process, but no durable cooldown state or startup rule is specified. The named test can pass against one object while the replacement process immediately permits another restart.

   **Suggested fix:** Define how the cooldown survives restart and test a fresh bot instance after the first exit. Keep the pending confirmation owner-bound and expiring.

   **If skipped:** Repeated confirmations can cause restart loops despite the promised cooldown.

12. **Heartbeat health checks cannot detect a stalled writer** — [M4.5.md:36](<docs/features/pokewalker-bot/tickets/M4.5.md:36>)

   **What this is:** Heartbeats should confirm that gameplay persistence remains healthy.

   **Problem:** An open writer with `_failure is None` can still be stuck indefinitely awaiting a job. The specified checks continue sending success while all later transactions queue, contrary to the cited monitoring requirement.

   **Suggested fix:** Require bounded evidence of writer progress, and suppress successful heartbeats when that evidence expires. Test a writer job that never completes while Gateway readiness remains true.

   **If skipped:** Monitoring reports healthy service during a gameplay outage.

13. **The configured contract check is described as testing the wrong artifact** — [M5.1.md:20](<docs/features/pokewalker-bot/tickets/M5.1.md:20>)

   **What this is:** Verification activation selects `test_content_emit.py` as the contract command.

   **Problem:** That suite rebuilds and checks `tests/fixtures/content_mini`; it does not validate the committed production artifact as claimed. Other unit tests consume production content, but that is not equivalent to checking its complete C1 integrity and manifest.

   **Suggested fix:** Correct the coverage description and explicitly add an offline check of the committed artifact’s schema, hash, and required invariants. Keep raw-CSV rebuild verification separately identified.

   **If skipped:** Verification evidence overstates what protects the deployed content.

14. **Deployment and backup work is oversized and only statically verified** — [M5.2.md:42](<docs/features/pokewalker-bot/tickets/M5.2.md:42>)

   **What this is:** One seam row owns deployment/rollback, backup/upload, pruning, service configuration, and recovery documentation.

   **Problem:** These are separate executable failure paths across three scripts, beyond the plan workflow’s two-production-file seam bound. Static assertions and `bash -n` cannot establish failure ordering, safe rollback, or that pruning actually executes after upload failure. `systemctl is-active` also does not establish the Gateway/database readiness required by the cited deployment research.

   **Suggested fix:** Split deployment from backup/retention. Add offline behavioral tests using fake external commands for failure ordering, readiness failure, and explicit database-restore authorization.

   **If skipped:** A row can satisfy every listed acceptance check while its operational scripts mishandle failures or discard later writes.

**NIT**

15. **Two citations do not support their accompanying statements** — [M2.4.md:5](<docs/features/pokewalker-bot/tickets/M2.4.md:5>), [M5.1.md:23](<docs/features/pokewalker-bot/tickets/M5.1.md:23>)

   **What this is:** Tickets cite requirement and verification-policy anchors.

   **Problem:** D14 is at README line 37, not 38. PIPELINE lines 30–31 explain using `&&`; they do not prohibit it inside configured checks.

   **Suggested fix:** Correct the D14 anchor and remove the unsupported attribution for the additional command restriction.

   **If skipped:** Implementers receive misleading source-of-truth pointers.

Verdict: **NO-GO.** Resolve the MUST FIX findings before implementation. G-4 and the explicitly deferred opt-out decision remain open.

Not checked: Full test suites, live Discord, or host deployment/restore. Source inspection and two synthetic probes were performed; no files were edited. Privacy and data-loss risks remain as described above.

MUST=8 SHOULD=6 NIT=1