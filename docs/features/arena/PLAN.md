# Plan: arena — solo floor-climbing PvE with Arena Tickets

**Status:** approved — in execution · owner approved G-A · G-P 2026-11-13 (direct owner approval in session) · amended 2026-11-14: M3 leaderboard rows ARENA-20..23 added at owner request (AR-36..AR-41); owner approved ARENA-20, ARENA-21, ARENA-22, ARENA-23 2026-11-14
**Home:** feature/arena · D:\Projects\Pokewalker-arena
**Review:** 2026-11-13 · Codex gpt-6-astra (independent, read-only) · GO after 3 rounds (R1 2 MUST/4 SHOULD, R2 1 MUST, R3 0/0); fixes applied by Opus · reviewed untracked tree on main 9c8aec5 · M3 amendment 2026-11-14: Codex gpt-6-astra GO after 1 round (0 MUST, 1 SHOULD fixed by Opus) · M2 brief: astra GO r2 (r1 2M/2S fixed) · M3 brief: astra r2 0M/1S (fixed; r1 1M/1S fixed)
**Inputs:** [REQUIREMENTS.md](REQUIREMENTS.md), owner-approved 2026-11-13: every AR-n is settled scope; §6.3 (AR-36..AR-41) added 2026-11-14, owner approval of its [R] items unverified · [PIPELINE.md](../../../PIPELINE.md) · `AGENTS.md` · `rules/*.md`

## 1. Outcome and non-goals

A profile locks a team of 3 and climbs endless floors of three 3-on-1 auto-battles, with HP carried between fights. Cleared floors pay Arena Tickets, redeemed later for encounters and gym-style inbox rewards. Three milestones, M1 and M2 as the owner phased them and M3 as requested 2026-11-14:

- **M1, core (steps 2-16, built; G-M1 ✅):** runs and lifecycle, fights with HP carry-over, heal and party order, knockout Candy, enemy generation, tickets and redemption, gym/trade/research blocks, admin on/off, deletion coverage.
- **M2, speed-ups (steps 18-22, built):** floor skip, Fight until hurt, auto-order toggle, stop threshold, economy report.
- **M3, monthly leaderboard (steps 23-26, briefed):** per-server monthly best-floor board, lazy month-end inbox rewards for the top 3, Leaderboard screen (REQUIREMENTS §6.3).

**Non-goals:** REQUIREMENTS §7 and AR-41; an Arena battle-log viewer (D5); a Storage-detail change; pruning old runs; any push, deploy, command sync or live Discord action (§3.4).

## 2. Verified code map (verified at 9c8aec5; M3 rows re-verified at 8e6a7bf)

**Trimmed to current state.** `git show 3ab843a:docs/features/arena/PLAN.md` has the M1 anchors, decisions D3, D6-D12 and D17 and the G-M1 brief; `git show 8e6a7bf:docs/features/arena/PLAN.md` has the M2 anchors, decisions D15 and D19 and the M3 one-line anchors. Of the files below, `git diff --stat 8390bfd..HEAD` shows only `services/arena.py`, `bot/arena.py`, `scripts/simulate_economy.py`, the Arena tests and `test_readme.py` changed.

| Anchor | Fact | Tickets (ARENA-n) |
|---|---|---|
| `db/__init__.py:34-47, :110-116`; `0014_gyms.sql:10, :24`; `0004_milestones.sql:7-16`; `0001_core.sql:24` | contiguous migrations, next is 0027; one `BEGIN IMMEDIATE`..commit per job, so a refused press rolls back; `profiles_guild_key` and the composite profile FK cascade; `inbox_items.milestone_id` is free text; `profiles.created_at` | 20, 22 |
| `services/arena.py:30-51, :70-124, :208-266, :269-291, :344-345` | `state`; `start` pays skip tickets only; `fight`: boss-win branch `:241-253`, sole `arena_best_floor` write `:243`, receipt `:266`; `chain_step` fights through `fight` (`:283`); the inbox insert | 20, 22 |
| `services/milestones.py:125-128, :131-178`; `services/deletion.py:131` | `pending_count` counts distinct `milestone_id`; the sole claim holds a rare item with no free pocket (`:145-156`); deletion and reset are one profile delete | 20, 22 |
| `bot/walker.py:18-24, :130, :139, :207-209, :230-259` | `arena` is the bot module; `home` runs in a writer job for `/walker` and the `home` action, `pending_count` at `:256`; every edit sends `AllowedMentions.none()` | 22, 23 |
| `bot/arena.py:37-56, :395-414, :467-470`; `bot/gyms.py:19-23, :31`; `bot/client.py:102-103` | `render_home` opens with the Arena off; `dispatch`: `arena_until_hurt` returns first, state check `:398-401`; registry; `buttons`; the `<@user_id>` mention; no members intent | 23 |
| `bot/milestones.py:83-96, :181-187, :209`; `bot/screens.py:36-38`; `bot/bag.py:256, :309` | the `arena:` label branch, which `arena_month:` misses; the `inbox` handler; the home Inbox button is disabled at 0; inbox re-entry | 22, 23 |
| `content/balance/arena.json:4, :160-163`; `capacities.json:8-12`; `scripts/simulate_economy.py:29` | `version` 1, `rules` ends with `skip`; three rare pockets, cap 1; the report prints the manifest hash and table versions | 21 |
| `tests/test_arena_schema.py:69, :114`, `test_deletion.py:21-55, :299-302, :313-316`, `test_admin_reset_sharing.py:232`, `test_balance_tables.py:76-116`, `test_arena_screens.py:385-417, :1051-1118`, `test_milestones.py:491-523`, `test_readme.py:41-44` | version pins; `populate_arena` and the deletion table lists; exact payload; action, renderer and router pins; Arena label tests; help hash | 20-23 |

Greps at 8e6a7bf (`git grep -n <pattern> -- pokewalker`): `inbox_items` → inserts `services/arena.py:344`, `services/gyms.py:114,126`, `services/milestones.py:106`; sole claim `services/milestones.py:131-178`. `arena_best_floor` → sole writer `services/arena.py:243`. `["']inbox["']` → handler `bot/milestones.py:181` (registered `:209`), home button `bot/screens.py:37`, re-entry `bot/bag.py:256,309`. `\.home(` → `bot/walker.py:130` (a writer job) and handler calls at `:358, :393, :414, :498`, `bot/pokedex.py:128`, `bot/research.py:190`, `bot/storage.py:231`. `git grep -n "arena_month\|leaderboard\|month_key" -- pokewalker scripts tests contracts content` has no hit (the M3 names are free). The committed economy report equals the CLI output at 8e6a7bf (ARENA-19's `git diff --no-index` check exits 0).

**Do not touch:** migrations 0001-0026; `db/__init__.py`; `domain/cp.py`, `domain/encounters.py`, `domain/steps.py`; `ENGINE_VERSION`; balance tables other than `arena.json`; `content/artifact/**`, `content/build/**`; services `deletion`, `marker_log`, `stepping`, `milestones`, `items`, `storage`, `catching`, `evolution`, `powerup`, `raids`, `capacity` (imported only); `bot/storage.py`, `bot/client.py`, `bot/mod.py`; gym payout keys and seeded rng order; `deploy/**`, `.github/**`, `PIPELINE.md`, `AGENTS.md`, `rules/**`; `REQUIREMENTS.md`; other feature folders, except the generated `docs/features/pokewalker-bot/economy-report.md` in ARENA-21.

**New files:** migration `0027_arena_months.sql` (M3).

## 3. Decisions

### 3.1 Design

- **D1 Layers.** `domain/arena.py` is pure (table and rng injected); `services/arena.py` writes inside the caller's writer transaction; `bot/arena.py` renders without I/O. Same split as `domain/battle.py`, `services/gyms.py`, `bot/gyms.py`.
- **D2 Run storage.** One `arena_runs` row per run. Live means `ended_at IS NULL`, one per profile by partial unique index. Team and enemy are JSON snapshots, so a restart or a content release cannot re-roll or re-stat them. The cooldown reads the latest `started_at`; there is no separate "last start" column.
- **D4 Revision and receipts.** Every run change bumps `arena_runs.revision`. Screens keep `run_id` and `run_revision` in the session selection, because a custom ID carries only session, revision and action. Receipt keys, all with `profile_id`: `arena_start:<session>:<rev>`, `arena_heal:<run>:<rev>`, `arena_fight:<run>:<floor>:<slot>`, `arena_redeem:<session>:<rev>`. Reordering has no receipt: no resource moves.
- **D5 Compact fight receipts.** Outcome, ticks, HP, finisher, Candy and tickets, without event text: receipts are never pruned and a deep run is 300+ fights. So the Arena has no battle log; no AR asks for one.
- **D3, D6-D12, D17** (M1) and **D15, D19** (M2) are built; their text is in the trim commits named in §2.
- **D13 Screens.** Action names use letters and underscores. Break screen: row 0 is Fight, Heal all & fight, Fight until hurt, Auto-order, Back out; rows 1-3 the heals, berry select and party order (one select of the six orders); row 4 the stop threshold. Team picker rows 3-4: the skip selects, two because a select holds 25 options and a skip reaches 40.
- **D14 M2 chain.** `arena_until_hurt` returns only `after_commit` (`bot/walker.py:207-208`). That coroutine runs under the session lock (`:152-153`), submits one `writer.run` job per fight and renders the result; `bot/walker.py` does not change (confirmed at 3ab843a). The handler does not redraw first, or a stale screen could fight. After a drain closes the writer (`bot/client.py:256`), `writer.run` raises (`db/__init__.py:78`) and the chain returns the last committed screen with the restart text.
- **D16 `content/help.md` counts as docs** for row size: it is prose pinned by `tests/test_readme.py`.
- **D18 M3 state and payout.** `0027`: `arena_month_scores`, one row per profile and UTC month (composite profile FK cascade, as `0014_gyms.sql:10,24`); `arena_months`, one settled row per guild and month with no profile reference (guild cascade); `arena_month_places`, the paid places, with the profile cascade. So a month pays once and no player data outlives deletion. `settle(conn, guild_id, now)` in `services/arena.py` runs in the caller's transaction, with no receipt (the settled row is the guard), at `Walker.home` before `pending_count` (`bot/walker.py:256`; the home Inbox button is disabled at count 0, `bot/screens.py:36-38`), at Arena dispatch after the state check (`bot/arena.py:398-401`; this covers the Leaderboard) and at inbox open (`bot/milestones.py:181`). Neither `settle` nor the screen reads `arena_enabled`. One ranking helper, in the AR-37 order, serves `settle` and the screen read. It leaves out profiles `excluded` in `restrictions`; paused ones stay ranked (AR-40, ruling 2026-11-14). Rewards, minimum floor and board size live in `arena.json` `rules.leaderboard` (`version` 2); the paid places are `len(rewards)`. Names render as `<@user_id>`, as `bot/gyms.py:31`: the bot has no members intent (`bot/client.py:102-103`), and every walker edit already sends `AllowedMentions.none()` (`bot/walker.py:209`). Last month's list reads the paid-place rows: a deleted or now-excluded winner drops out, and nobody is promoted on screen.
### 3.2 Contracts (each lands with its row, contract and tests before code)

| Contract | Change | Tickets (ARENA-n) |
|---|---|---|
| C7 `gym-battle.md` | `Combatant.hp` is starting HP; `Result.party_hp`, `Result.finisher`. Compatible. | 1 |
| C4 `balance-tables.md` | Append the `arena.json` table. M2: the economy output. M3: the `leaderboard` rules. | 2, 19, 21 |
| C3 `persisted-state.md` | Append schema 0025, the run service, tickets and redemption, `in_arena` refusals, audit actions. M2: schema 0026, the settings setters, the skip at start, the chain step. M3: schema 0027, the monthly score write, settlement and its `arena_month:` inbox keys. Additive; older binaries refuse a newer schema. | 4-10, 14, 16, 17, 20, 22 |
| C5 `discord-commands.md` | Append Arena screens, `in_arena` texts, `/walker-admin arena on\|off reason`, the home button. M2: the skip selects, threshold, auto-order and Fight until hurt. M3: the Leaderboard screen and button, the inbox label, the settlement call sites. | 5-7, 11-15, 18, 22-24 |

### 3.3 Verification decision (Decide before dispatch)

No owner/repo conflict: AGENTS.md asks for RED → GREEN and the applicable checks; PIPELINE.md:10 is the full command (`python scripts/guard.py && python scripts/verify.py` since 2026-11-14). Rows run **focused** checks only: the modules their ticket names (`python -m unittest discover -s tests -p "test_<module>.py"`) plus a diff check, with RED evidence in the commit body. M3 rows touch files committed with CR line ends; those stay as they are, so the check is `git -c core.whitespace=cr-at-eol diff --cached --check`. The full `test_cmd` runs twice, uncached (`FP_RESULT_CACHE=0`):

- **Source increment M1** (rows ARENA-1..ARENA-15, at G-M1). Outcome: a complete playable Arena on the feature branch, for the owner's smoke test. Reason: M2 changes the fight path, and a qualified M1 baseline localizes regressions. It is not a delivery.
- **Final feature** (G-F). M2 and M3 are not source increments; their rows run focused checks.

The owner's code review loop (global CLAUDE.md) is review, not tests; the coordinator applies it.

### 3.4 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` (PIPELINE.md:15); no feature exception. M1 is a verification increment only. |
| Candidate | the final accepted feature candidate on the Home assigned at G-A |
| Action scope and targets | **Set at G-A 2026-11-13:** feature-branch backup pushes of `feature/arena` to `origin` are authorized (never main, never force; owner standing preference for drives, confirmed at G-A). Main integration and push, host deploy, command sync and live smoke stay separate owner effects at G-F. Repo `Farkoal2128/Pokewalker-Discord-Bot`, remote `origin` (`git remote -v`), main branch `main`. Separate owner effects: feature-branch backup pushes (never main, never force); main integration and push; host deploy applying 0025/0026/0027 (`deploy.*: none`, so by the owner's hand); a Discord command sync for the new admin subcommand (`deploy/deploy.sh:193-195`); live smoke. |
| Predicates and workflow | independent integration GO and one exact-tree full `test_cmd` PASS per pushed or deployed candidate |
| Owner authority | G-A 2026-11-13: plan approval, Home, docs commit on Home, feature-branch backup pushes |

**G-P.** Allowlist: this `PLAN.md`, `REQUIREMENTS.md`, `tickets/ARENA-1.md`..`ARENA-15.md`. Effect of a push to `main` or a pull request: `.github/workflows/verify.yml` runs (PIPELINE.md:26). **Decided at G-A: no publication to main**; the docs are committed on the Home branch `feature/arena` and pushed with it. If the owner confirms local-only, G-P does not apply. The plan author never pushes.

### 3.5 Gate record

| Gate | Decision maker | Scope | Evidence |
|---|---|---|---|
| G-A · G-P | owner | plan approval, Home (`branch_policy: feature-branch`), delivery and push scope | an owner message naming G-A |
| G-M1 | coordinator | qualify increment M1 | integration GO; `Tests:` receipt for the M1 tree |
| G-F | coordinator for the technical predicates; owner for every delivery effect | as named in §3.4 | integration GO; final `Tests:` receipt; owner messages per effect |

## 4. Step table

Every build row is `seam` (PIPELINE.md:13): at most 2 production files and 300 production lines; tests, contracts and docs are not counted. Rows run in order.

| Step | Ticket(s) | Kind | Tier | Effort | Status |
|---|---|---|---|---|---|
| 1 | G-A · G-P plan approval, Home, delivery scope | 🚦 | — | — | ✅ owner approved 2026-11-13 |
| 2 | [ARENA-1](tickets/ARENA-1.md) C7 engine: starting HP, party HP, finisher | build | seam | S | ✅ done · 0c39b93 · GO review r1 |
| 3 | [ARENA-2](tickets/ARENA-2.md) balance table `arena.json` and manifest hash | build | seam | S | ✅ done · 97201cc · GO review r1 |
| 4 | [ARENA-3](tickets/ARENA-3.md) pure rules `domain/arena.py` | build | seam | M | ✅ done · 35f9308 · GO review r1 |
| 5 | [ARENA-4](tickets/ARENA-4.md) migration 0025 and the live-team check | build | seam | M | ✅ done · 3d6414b · GO review r1 |
| 6 | [ARENA-5](tickets/ARENA-5.md) gym deploy, claim and attack blocks | build | seam | M | ✅ done · 6d83edc · GO review r1 |
| 7 | [ARENA-6](tickets/ARENA-6.md) research send block | build | seam | S | ✅ done · 232f735 · GO review r1 |
| 8 | [ARENA-7](tickets/ARENA-7.md) trade block | build | seam | S | ✅ done · 416497d · GO review r1 |
| 9 | [ARENA-8](tickets/ARENA-8.md) service: start, expiry, order, heal | build | seam | L | ✅ done · 5e645db · GO review r1 |
| 10 | [ARENA-9](tickets/ARENA-9.md) service: fight, Heal all and fight, Candy, ticket credit | build | seam | L | ✅ done · b1d47f4 · GO review r2 |
| 11 | [ARENA-10](tickets/ARENA-10.md) service: redemption and the gym roll helper | build | seam | M | ✅ done · 992b663 · GO review r1 |
| 12 | [ARENA-11](tickets/ARENA-11.md) screens: Arena home, team picker, start | build | seam | M | ✅ done · 6fbe971 · GO review r2 |
| 13 | [ARENA-12](tickets/ARENA-12.md) screens: break actions and results | build | seam | M | ✅ done · a1040b4 · GO review r1 |
| 14 | [ARENA-13](tickets/ARENA-13.md) screens: tickets, redemption, inbox labels | build | seam | M | ✅ done · 46c0c0e · GO review r1 |
| 15 | [ARENA-14](tickets/ARENA-14.md) admin on/off command | build | seam | S | ✅ done · 493c2b2 · GO review r1 |
| 16 | [ARENA-15](tickets/ARENA-15.md) go live: registration, home button, help, deletion coverage | build | seam | M | ✅ done · 2b7b431 · GO review r1 |
| 17 | G-M1 qualify increment M1 | 🚦 | — | — | ✅ done 2026-11-14 · candidate 4308d1d tree 9736355 · Tests: full test_cmd PASS uncached (1847 OK, 1 skip; guard OK; contract 6 OK) · integration GO Codex gpt-6-astra r1 · audit Fable r1 (1 SHOULD fixed, 1 NICE fixed, 1 NICE rejected per C5) |
| 18 | [ARENA-16](tickets/ARENA-16.md) M2 settings: migration 0026 and setters that bump the live run revision | build | seam | S | ✅ done · 113df42 · GO review r1 |
| 19 | [ARENA-17](tickets/ARENA-17.md) M2 service: floor skip paid at run start; the chain step | build | seam | M | ✅ done · 0c9f95a · GO review r1 |
| 20 | [ARENA-18](tickets/ARENA-18.md) M2 screens: skip select, auto-order toggle, stop threshold | build | seam | M | ✅ done · dd3a72d · GO review r1 |
| 21 | [ARENA-24](tickets/ARENA-24.md) M2 screens: Fight until hurt coordinator and result; help | build | seam | M | ✅ done · f54856f · GO review r2 |
| 22 | [ARENA-19](tickets/ARENA-19.md) economy model and report: Arena ticket income | build | seam | M | ✅ done · fbb45ca · GO review r1 |
| 23 | [ARENA-20](tickets/ARENA-20.md) M3 state: migration 0027 and the monthly score write in the boss-win transaction | build | seam | M | ✅ done · c8404a4 · GO review r1 |
| 24 | [ARENA-21](tickets/ARENA-21.md) M3 balance: `leaderboard` rules in `arena.json` and the manifest hash | build | seam | S | ✅ done · 8e5b862 · GO review r1 |
| 25 | [ARENA-22](tickets/ARENA-22.md) M3 settlement: lazy month payout, ranking read, home-open call | build | seam | M | in progress · WIP 6409345 |
| 26 | [ARENA-23](tickets/ARENA-23.md) M3 screens: Leaderboard, Arena and inbox settlement calls, inbox label; help | build | seam | M | pending |
| 27 | G-F final verification and delivery decisions | 🚦 | — | — | pending |

## 5. Briefs

**M2 rows (built).** [ARENA-16](tickets/ARENA-16.md), [ARENA-17](tickets/ARENA-17.md), [ARENA-18](tickets/ARENA-18.md), [ARENA-24](tickets/ARENA-24.md), [ARENA-19](tickets/ARENA-19.md). Decisions: D13, D14, and D15, D19 in the trim commit (§2).

**M3 rows (tickets verified at 8e6a7bf).** [ARENA-20](tickets/ARENA-20.md), [ARENA-21](tickets/ARENA-21.md), [ARENA-22](tickets/ARENA-22.md), [ARENA-23](tickets/ARENA-23.md), in step order. Each runs the focused checks its ticket names; the full `test_cmd` waits for G-F (§3.3). Decisions: D5, D16, D18.
- No row needs a third production file, a package change or a new owner decision, so the batch has no new 🚦 row.
- AR-36 interactions, both in ARENA-20: a floor skip writes no score (`start` never reaches the boss-win branch), and a chained boss win scores (`chain_step` fights through `fight`).
- AR-39 triggers: the walker home in ARENA-22; the Arena, the Leaderboard and inbox open in ARENA-23.

**G-F (coordinator; owner for effects).** Predicates: every row ✅; independent integration GO; one exact-tree full `test_cmd` PASS on the settled final tree, skips recorded. `test_cmd` does not prove live Discord behavior. Each effect of §3.4 needs its own owner message: push, main integration, host deploy with migrations, command sync, live smoke.
