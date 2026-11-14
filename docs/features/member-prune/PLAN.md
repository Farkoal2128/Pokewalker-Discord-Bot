# Plan: member-prune — `/walker-admin prune` deletes game data of players who left

**Status:** MP-1 built; owner smoke PASS on the live bot 2026-11-14 (c686418 deployed, `sync-commands --global --yes` run); merged to `main`; push pending (G-F)
**Smoke:** owner, prepared server with one enrolled player who caught a Pokémon and was kicked: dry run reported 1 of 2 profiles no longer members; `confirm=True` deleted that profile only; `/walker-mod log` showed one `prune` row; a second confirmed run deleted 0.
**Review:** plan: Codex gpt-6-astra rounds 1-2 NO-GO, round 3 GO (MUST 0, SHOULD 0). Code: Codex ponytail-review on 045a620 GO, 1 SHOULD fixed in 81b9f19. Full `test_cmd` PASS on tree a173ee7 (1,695 tests, 1 skipped; guard; verify unit and contract), 2026-11-14.
**Home:** feature/member-prune · D:\Projects\Pokewalker Discord Bot\.claude\worktrees\elegant-haibt-afa2c5
**Inputs:** [README.md](README.md) (PR1–PR11, the authority) · [PIPELINE.md](../../../PIPELINE.md) · [AGENTS.md](../../../AGENTS.md)

## 1. Outcome and non-goals

**Outcome.** A Manage Server moderator runs `/walker-admin prune reason [confirm=false]`. Without `confirm` the bot counts the server's profiles whose user is no longer a member. With `confirm=True` it deletes each of those profiles through the existing D28 marker path and writes one audit row for the run.

**Non-goals** (README.md:72-78; each needs an owner decision first):
- The members intent, a member cache, or deletion when a member leaves.
- Pruning across servers, or from the owner `/admin` command.
- Arena code (see §6).
- Any change to `pokewalker/services/`, the schema or the marker format.

## 2. Verified code map — verified at 9c8aec5

**Grep evidence** (run at the repo root):
- `git grep -n "run_marker(" -- pokewalker`: callers are account.py:66, :91 and admin_channels.py:215; the definition is deletion.py:75. Prune adds a caller.
- `git grep -n "FROM mod_audit" -- pokewalker`: readers are mod.py:151 (`/walker-mod log`) and raids.py:170 (only `action='force_raid'`); 0009:12 is the migration copy.
- `git grep -n fetch_member -- pokewalker`: admin_channels.py:55 only.
- `git grep -n max_ratelimit_timeout -- pokewalker`: no hits, so the client's default rate-limit handling applies; its pace is unmeasured (§6).
- `git grep -n "WalkerAdmin(" -- pokewalker tests`: the class (admin_channels.py:20), client.py:111 and four test fixtures (test_admin_channels.py:25, test_admin_reset_sharing.py:37, test_admin_trade_channels.py:32, test_gyms.py:589).

| Anchor | Fact |
|---|---|
| bot/admin_channels.py:16, :20-27 | `_Refused`; `WalkerAdmin` is guild-only with Manage Server default permissions |
| :29-37, :39-43, :181-185 | `authorize` (entry check and excluded actor), `reply` (private, cut to 2000, no mentions), `check_actor` (raises `_Refused` inside a writer job) |
| :187-221 | `reset`, the pattern: defer :190, `authorize` :191, stripped reason :193-196, inner callback :198-204, `confirm=false` preview :207-214, `run_marker` :215-217, `_Refused` to reply :218-220 |
| :242-244 | the guild-target `mod_audit` insert to reuse |
| services/deletion.py:75-122 | `run_marker`: the callback runs first inside the job (:82-83), then the profile lookup (:84-88) and the fsynced marker (:89-90). A raise from the callback leaves no marker and no void (:103-104). Reaction cleanup follows the commit (:119-121) |
| services/deletion.py:125-150, :158-177; bot/client.py:159 | `apply` deletes `delete_ids` (:129-131) and audits only `resets` (:137-150); startup replay does the same |
| services/marker_log.py:13-15, :33-43, :86-92, :127-133 | kinds; `actor_id` and `reason` are valid on any kind; `fold` keeps them only for `reset` |
| db/__init__.py:63-83, :111-116 | one writer queue; each job is its own `BEGIN IMMEDIATE` … commit, and the commit follows the job's return |
| bot/client.py:101-103, :106, :111-113 | no members intent; injected monotonic `clock`; the group's registration |
| bot/client.py:310-322; deploy/deploy.sh:190-195; C5 :1359-1361 | a new subcommand changes the command manifest; the deploy step asks for `sync-commands --global --yes` |
| db/migrations/0001_core.sql:37-46, 0009_guild_sharing.sql:2-14 | `mod_audit.action` is free text (no CHECK); `target_kind` admits `guild`; reason must be non-blank; the same is stated in C3 :1268-1269 |
| bot/mod.py:150-163 | `/walker-mod log` prints a guild target as `server:<id>` and any action text, so `prune` rows need no reader change |
| tests/test_admin_reset_sharing.py:23-85 | the fixture to mirror: real `Writer`, in-memory DB, marker log, fake interaction |
| tests/test_admin_channels.py:209-212 | how tests build `discord.NotFound`, `Forbidden` and `HTTPException` from a fake response |
| tests/test_readme.py:41-44, :101-126; content/help.md:67-74; .gitattributes:4 | help.md sha256 pin; admin page rule (:123 pins 25 documented commands; :124-126 require the first word of every backtick span on a `- ` line to be a subcommand); LF endings |
| tests/test_prune.py | already taken by backup pruning (contracts/ops-runtime.md:112), so the new file is `tests/test_admin_prune.py` |
| C5 contracts/discord-commands.md:78-100; C3 contracts/persisted-state.md:16-28, :478-500 | the M4.3 reset contract and the `run_marker` contract; :487-488 says a commit failure after the job returns leaves a valid marker for replay |
| discord.py 2.7.1 (requirements.lock:181) | Probed in the repo virtualenv: `NotFound(response, {"code": 10007, …}).code == 10007`, and 0 when the body has no code; `RateLimited` is not an `HTTPException` |

**Do-not-touch:** `pokewalker/services/**`, `pokewalker/db/**`, `pokewalker/bot/client.py`, the behaviour and tests of `reset` and `sharing`, existing C5/C3 sections (append only), and `D:\Projects\Pokewalker-arena`.

## 3. Decisions

### 3.1 Planner decisions

"Coordinator n" marks a decision the coordinating session made in the brief; the code evidence is the planner's.

- **D1 Shape** (coordinator 1). `prune(interaction, reason: str, confirm: bool = False)`, a direct `WalkerAdmin` subcommand that mirrors `reset` (admin_channels.py:187-214). `confirm=false` is the count-only dry run.
- **D2 Delete path** (coordinator 2). Each departed user is deleted by `deletion.run_marker(kind="delete", actor_id, reason, …)` with a gate callback: `check_actor`, then skip by raising a private `_Gone` when the profile no longer exists. The gate runs before any marker (deletion.py:82-90). `kind="reset"` is rejected because it writes one user-target audit per marker (:99-100, :137-150).
- **D3 Audit durability** (coordinator 3, resolved to "before the first deletion"). The run's one `mod_audit` row (`target_kind='guild'`, target the guild, `action='prune'`) is written in its own writer job, committed before the run's first marker is appended. That job runs the D2 gate for the first departed user, so nothing is written when that profile is already gone.
  - *Why not the same job as the first deletion:* the marker is fsynced inside the job (deletion.py:90) and the commit follows the job's return (db/__init__.py:114-116). A crash or commit failure in between keeps the marker valid (C3 :487-488). Startup replay then deletes the profile and audits only `reset` markers (deletion.py:137-150, :172-174), so the audit would be lost while the deletion commits. That breaks PR7.
  - *Cost:* the row can exist for a run that deleted nothing, when the first deletion never commits: a crash before the marker is appended, a void after a failed `apply`, or the profile vanishing between the two jobs with no later deletion. The audit can over-report; it never under-reports. PR7's two stated guarantees hold.
- **D4 Membership test** (coordinator 4). Departed means `discord.NotFound` with `.code == 10007`, nothing else. A returned member is kept. Any other `Exception` from the check stops the run; the catch is `Exception` (not `BaseException`), because `RateLimited` and transport errors are not `HTTPException` (bot/share.py:97 lists them separately). *Unverified here:* that live Discord answers 404/10007 for a departed user (Discord API documentation; exercised only at the G-F smoke).
- **D5 Time budget** (coordinator 5; review-1 #1, review-2 #1 #4). `PRUNE_BUDGET_SECONDS = 13 * 60` on the monotonic `self.bot.clock` (client.py:101-106), from handler entry, leaving 2 minutes for the reply; persisted timestamps stay on wall time. The two HTTP waits are bounded **without cancelling** them, because discord.py's `Ratelimit.__aexit__` sleeps again on cancellation and a cancelled global-limit sleep can leave `_global_over` set (discord/http.py:439-497, :750-760). Helper `_within(coro, remaining)`: start the coroutine as a task kept in a group-level set, with a done callback that drops it and consumes its exception; `asyncio.wait({task}, timeout=remaining)`; return the task if done, else None. (a) `fetch_member` goes through `_within`; None is a time stop, and the late result is discarded, never acted on. (b) `run_marker` gets a `reactions` wrapper whose `remove_own` goes through `_within` and returns either way, so the committed deletion is counted while cleanup may finish in the background. At most one fetch and one cleanup outlive a stopped run. The handler is never wrapped in a timeout. Writer jobs are short and stay unbounded, so the deadline bounds REST work, not the whole handler.
- **D6 No per-guild lock** (coordinator 6, verified). The writer runs one job at a time in its own transaction (db/__init__.py:63-83, :111-116), and the D2 gate re-reads the profile inside the deleting job (deletion.py:82-83). The slower of two runs therefore skips the profile and writes no marker. Each run that reaches its audit job writes its own audit row (the D3 cost).
- **D7 Resume point** (planner addition). Profiles are checked in a fixed order and present members stay in the list, so after a D5 stop a rerun would re-check the same leading members and never reach the rest. PR10 requires the rerun to continue. On a time stop the group keeps the last checked user ID per guild in memory; a stop before any check leaves the incoming cursor unchanged (review-1 #2), and a cursor whose profile has gone still orders correctly because it is compared by value, not looked up; the next run in that guild starts after it and wraps to the start. A restart loses it and the next run starts from the beginning. If the coordinator strikes D7, a server that needs more than one budget window cannot be fully pruned.
- **D8 Failures.** A writer or marker failure propagates unhandled, as in `reset` (test_admin_reset_sharing.py:257-263). Earlier deletions stay, since each is its own transaction (PR5).
- **D9 One row** (coordinator 7). Inside the row the order is contract paragraphs, RED tests, command, help line. AGENTS.md:16-22 puts the contract before the test; the brief listed tests first.
- **D10 Replies.** One private reply per run, from the table below. `{m}` is the server's profile count, `{k}` the profiles checked, `{n}` those found departed and `{d}` those deleted.

| Ending | Text |
|---|---|
| dry run, all checked | `{n} of {m} profiles are no longer members. Nothing was deleted. Use confirm=True to delete their game data; this cannot be undone.` |
| confirmed, all checked | `Deleted the game data of {d} of {m} profiles whose users left this server.` |
| stopped | `<why> Checked {k} of {m} profiles; {n} no longer members; {d} deleted. Run it again to continue.` |

`<why>` is `Stopped: Discord could not confirm a member (<error class name>).`, `Stopped: time limit reached.` or the `_Refused` text.

### 3.2 Contracts

| Contract | Change | Compatibility |
|---|---|---|
| C5 contracts/discord-commands.md | Append `## Owner amendment: member prune (2026-11-14)`: shape, entry and in-job checks, membership test, D10 replies, budget and resume, audit, sync note. M4.3 (:78-100) is unchanged. | Additive subcommand. The manifest changes, so one `sync-commands --global --yes` follows delivery (C5 :1359-1361). |
| C3 contracts/persisted-state.md | Append the same heading: no schema or marker-format change; new `mod_audit.action` value `prune` on a guild target, committed before the run's first marker; prune's `delete` markers carry `actor_id` and `reason`. Producer: WalkerAdmin. Consumers: `/walker-mod log`, startup replay. | Additive; older readers ignore the new action text (mod.py:160-162). |
| content/help.md | One admin-page line after `reset`: ``- `prune <reason>`: count the players who left this server; run it again with confirm set to True to delete their game data.`` | Pinned by tests/test_readme.py:41-44 and :123; exactly one backtick span (:124-126). |

### 3.3 Verification decision (Decide before dispatch)

- **Conflicts:** one, resolved (review-1 #3). the owner ruled on 2026-11-14 that `test_cmd` is `python scripts/guard.py && python scripts/verify.py` (PIPELINE.md:10), which runs the unit suite once through `verify.py`. The row therefore runs focused checks only, and the full `test_cmd` runs exactly once at G-F. No mandated command is omitted.
- **MP-1, focused:**
  - A: `python -m unittest discover -s tests -p "test_admin_*.py"`. It runs the new prune tests and every existing `WalkerAdmin` command file (channels, force-raid, reset/sharing, trade-channels).
  - B: `python -m unittest discover -s tests -p "test_readme.py"` (help pins).
  - C: `git diff --check`.
  - RED before production code: A fails on the missing `prune` command and B on the count pin.
- **Interpreter:** the PATH `python` here lacks discord.py (`python -c "import discord"` raises ModuleNotFoundError). Use the repo virtualenv, `D:\Projects\Pokewalker Discord Bot\.venv`, where the same import reports 2.7.1.
- **Final (G-F):** independent integration GO, then one exact-tree full `test_cmd` (PIPELINE.md:10) with `FP_RESULT_CACHE=0`. There are no source increments; the boundary is the feature.
- **Outside every test:** live Discord behaviour (PIPELINE.md:41-43), covered only by the owner smoke at G-F.

### 3.4 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` (PIPELINE.md:15); one row, nothing to stage |
| Candidate | the final accepted candidate on Home |
| Action scope and targets | **Unresolved; proposed:** local implementation on Home; push of `feature/member-prune` to `origin` (`git remote -v`: `Farkoal2128/Pokewalker-Discord-Bot`) as a backup branch, which runs no workflow unless a pull request is open (.github/workflows/verify.yml:3-6); `main` integration, deployment and the global command sync stay owner actions. `deploy.ship` is `none` (PIPELINE.md:23-25), so this plan performs no deployment. |
| Predicates and workflow | independent integration GO; exact-tree full `test_cmd` PASS; clean tree; coordinator delivery path |
| Owner authority | none seen by the planner. The README's owner request (README.md:13-16) asks for the feature; it grants no push, merge or deploy. |

### 3.5 Gate record

| Gate | Decision maker | Scope and evidence |
|---|---|---|
| G-A | owner | approves this plan, Home and the §3.4 scope; evidence is an owner message naming G-A |
| G-P | owner (coordinator executes) | publication of the plan docs; proposed none, which makes G-P inapplicable once the owner confirms local-only |
| G-F | coordinator: technical. Owner: smoke and each delivery effect | integration GO and the `Tests:` receipt; an owner message per effect |

## 4. Step table

| Step | Ticket(s) | Kind | Tier | Effort | Status |
|---|---|---|---|---|---|
| 1 | 🚦 G-A plan approval, Home and delivery scope | 🚦 | — | — | pending |
| 2 | 🚦 G-P approved-plan publication (proposed: none) | 🚦 | — | — | pending |
| 3 | [MP-1](tickets/MP-1.md) `/walker-admin prune`: contracts, tests, command, help line | build | seam | M | pending |
| 4 | 🚦 G-F final checkpoint, owner smoke and delivery | 🚦 | — | — | smoke PASS, deployed, synced, merged; push pending |

## 5. Briefs

**G-A (owner).**
- **Decide:** the plan (D3's audit cost and D7 in particular), Home, and the §3.4 scope.
- **Home evidence:** `git rev-parse --show-toplevel --git-common-dir` and `git branch --show-current` match the header; the branch satisfies `branch_policy: feature-branch` (PIPELINE.md:14). The coordinating session assigned it; the planner saw no owner message, so owner confirmation is part of G-A.
- **Stop if:** the owner wants no audit row without a deletion. That needs a marker or replay change, which is outside this plan.

**G-P (owner).**
- **Allowlist:** `docs/features/member-prune/README.md`, `PLAN.md`, `tickets/MP-1.md`.
- **Target and effects:** `origin`, branch `main`; a push to `main` or a pull request runs verify.yml (PIPELINE.md:26).
- **Proposed:** no publication before the build. The docs travel with the feature branch.

**MP-1 (build, seam).** Detail is in [tickets/MP-1.md](tickets/MP-1.md).
- **Tier:** seam, because it touches slash commands and persisted player state (PIPELINE.md:13).
- **Bounds:** 2 production files (`pokewalker/bot/admin_channels.py`, `content/help.md`), well under 300 production lines.
- `Verification: phase=implementation; scope=focused; coverage=§3.3 A, B, C (prune tests, WalkerAdmin regressions, help pins); receipt=Tests-Focused on the staged tree; boundary=feature final (G-F)`.

**G-F (coordinator, then owner).**
- **Coordinator:** independent integration GO, then `Tests: tree <tree> <test_cmd> PASS` with `FP_RESULT_CACHE=0`.
- **Arena check:** if `git merge-base --is-ancestor feature/arena <candidate>` succeeds, stop and brief the §6 follow-up test before the full run.
- **Owner smoke** (live Discord; owner scope, PIPELINE.md:76-79): a dry run in a server with one enrolled test user who has left reports that user; `confirm=True` deletes only that profile; `/walker-mod log` shows one `prune` row.
- **Owner delivery:** each of push, `main` integration, deployment and `sync-commands --global --yes` needs its own owner message.

## 6. Risks, follow-ups and rollback

- **Arena follow-up (not a row here).** README.md:76-78 says Arena runs, tickets and leaderboard rows cascade from `profiles`. That is unverified in this checkout: `feature/arena` is not on `main` (`git branch -a --list "*arena*"`), and the planner was told not to read it. Once Arena is on `main`, add a test that a pruned player's Arena rows are gone.
- **Rejoin race.** A user who rejoins in the moment between their 10007 answer and their writer job is still deleted. PR6 accepts deletion right after the user's own answer.
- **Check rate is unmeasured.** Nothing depends on it: D5 bounds a run and D7 lets reruns finish the list.
- **Rollback.** Revert the row. Deletions already made are permanent by design (D28). No schema, marker or stored-data format changes.
