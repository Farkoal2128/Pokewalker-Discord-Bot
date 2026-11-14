# Plan: arena — solo floor-climbing PvE with Arena Tickets

**Status:** approved — in execution · owner approved G-A · G-P 2026-11-13 (direct owner approval in session) · amended 2026-11-14: M3 leaderboard rows ARENA-20..23 added at owner request (AR-36..AR-41), unbriefed; owner approved ARENA-16, ARENA-17, ARENA-18, ARENA-24, ARENA-19 2026-11-14
**Home:** feature/arena · D:\Projects\Pokewalker-arena
**Review:** 2026-11-13 · Codex gpt-6-astra (independent, read-only) · GO after 3 rounds (R1 2 MUST/4 SHOULD, R2 1 MUST, R3 0/0); fixes applied by Opus · reviewed untracked tree on main 9c8aec5 · M3 amendment 2026-11-14: Codex gpt-6-astra GO after 1 round (0 MUST, 1 SHOULD fixed by Opus) · M2 brief: astra GO r2 (r1 2M/2S fixed)
**Inputs:** [REQUIREMENTS.md](REQUIREMENTS.md), owner-approved 2026-11-13: every AR-n is settled scope; §6.3 (AR-36..AR-41) added 2026-11-14, owner approval of its [R] items unverified · [PIPELINE.md](../../../PIPELINE.md) · `AGENTS.md` · `rules/*.md`

## 1. Outcome and non-goals

A profile locks a team of 3 and climbs endless floors of three 3-on-1 auto-battles, with HP carried between fights. Cleared floors pay Arena Tickets, redeemed later for encounters and gym-style inbox rewards. Three milestones, M1 and M2 as the owner phased them and M3 as requested 2026-11-14:

- **M1, core (steps 2-16, built; G-M1 ✅):** runs and lifecycle, fights with HP carry-over, heal and party order, knockout Candy, enemy generation, tickets and redemption, gym/trade/research blocks, admin on/off, deletion coverage.
- **M2, speed-ups (steps 18-22, briefed):** floor skip, Fight until hurt, auto-order toggle, stop threshold, economy report.
- **M3, monthly leaderboard (steps 23-26, one-line rows briefed when ARENA-20 is reached):** per-server monthly best-floor board, lazy month-end inbox rewards for the top 3, Leaderboard screen (REQUIREMENTS §6.3).

**Non-goals:** REQUIREMENTS §7 and AR-41; an Arena battle-log viewer (D5); a Storage-detail change; pruning old runs; any push, deploy, command sync or live Discord action (§3.4).

## 2. Verified code map (verified at 9c8aec5; M2 rows re-verified at 3ab843a)

**Trimmed to current state** (`git show 3ab843a:docs/features/arena/PLAN.md`): M1-only anchors (the manifest anchors are in ARENA-2), decisions D3, D6-D12 and D17, the G-M1 brief. M3 greps and anchors: §5, verified at 8390bfd.

| Anchor | Fact | Tickets (ARENA-n) |
|---|---|---|
| `db/__init__.py:34-47, :72-83, :110-116, :158` | contiguous migrations, next is 0026; `Writer.run` raises `RuntimeError` once closed (:78); one `BEGIN IMMEDIATE`..commit per job; `with_receipt(..., profile_id=)` | 16, 20, 24 |
| `bot/walker.py:27, :71-88, :142-215` | action names match `[a-z_]+`; handler registry; one-transaction dispatch under the session lock (:152-153); `after_commit` awaited inside it (:207-208; users `bag.py:452`, `share.py:91`) | 18, 22-24 |
| `bot/client.py:210-256` | the drain sets `_stopping`, then closes the writer | 24 |
| `services/arena.py:27-47, :66-112, :115-135, :172-246` | `state`; `start` and its receipt; stale rule `_live_run`, `set_order`; `fight`, `heal_all_and_fight` | 16, 17 |
| `domain/arena.py:101-117`; `arena.json` `rules.skip` | `ticket_for`, `first_clear_bonus`; skip divisor 2, max 40 | 17, 19 |
| `bot/arena.py:22, :87-113, :135-162, :243-295, :357-360` | `BREAK_ACTIONS`; team picker rows 0-2; break rows 0-3, three buttons in row 0; `open_break`, `break_action`; registry | 18, 24 |
| `tests/test_arena_schema.py:36-67`, `test_arena.py:93-94`, `test_receipt_owner.py:57-62`, `test_capacity.py:81-82`, `test_trading_schema.py:88-91`, `test_arena_screens.py:222-234, :294-304, :505-513`, `test_readme.py:42-60` | schema, state, action, layout and help pins | 16, 18, 20, 24 |
| `scripts/economy/model.py:288-303`; `scripts/simulate_economy.py:66-79` | gym income section of the model and report; the committed report dates from 7a5f813 | 19 |

Greps at 3ab843a: `git grep -n "max_skip\|skip_tickets\|hp_order\|chain_step\|arena_stop_pct\|arena_auto_order\|arena_until_hurt\|arena_skip\|'skip'" -- pokewalker scripts tests contracts` has no hit (the M2 names are free; `rules.skip` is unread). `git grep -n "service\.state(\|service\.start(\|BREAK_ACTIONS" -- pokewalker`: `bot/arena.py:22, :205, :294, :299, :304, :338, :359`.

**Do not touch:** migrations 0001-0025; `db/__init__.py`; `domain/cp.py`, `domain/encounters.py`, `domain/steps.py`; `ENGINE_VERSION`; balance tables other than `arena.json`; `content/artifact/**`, `content/build/**`; services `deletion`, `marker_log`, `stepping`, `milestones`, `items`, `storage`, `catching`, `evolution`, `powerup`, `raids`, `capacity` (imported only); `bot/storage.py`, `bot/client.py`, `bot/mod.py`; gym payout keys and seeded rng order; `deploy/**`, `.github/**`, `PIPELINE.md`, `AGENTS.md`, `rules/**`; `REQUIREMENTS.md`; other feature folders, except the generated `docs/features/pokewalker-bot/economy-report.md` in ARENA-19.

**New files:** migrations `0026` (M2) and `0027` (M3); `tests/test_economy_arena.py` (M2).

## 3. Decisions

### 3.1 Design

- **D1 Layers.** `domain/arena.py` is pure (table and rng injected); `services/arena.py` writes inside the caller's writer transaction; `bot/arena.py` renders without I/O. Same split as `domain/battle.py`, `services/gyms.py`, `bot/gyms.py`.
- **D2 Run storage.** One `arena_runs` row per run. Live means `ended_at IS NULL`, one per profile by partial unique index. Team and enemy are JSON snapshots, so a restart or a content release cannot re-roll or re-stat them. The cooldown reads the latest `started_at`; there is no separate "last start" column.
- **D4 Revision and receipts.** Every run change bumps `arena_runs.revision`. Screens keep `run_id` and `run_revision` in the session selection, because a custom ID carries only session, revision and action. Receipt keys, all with `profile_id`: `arena_start:<session>:<rev>`, `arena_heal:<run>:<rev>`, `arena_fight:<run>:<floor>:<slot>`, `arena_redeem:<session>:<rev>`. Reordering has no receipt: no resource moves.
- **D5 Compact fight receipts.** Outcome, ticks, HP, finisher, Candy and tickets, without event text: receipts are never pruned and a deep run is 300+ fights. So the Arena has no battle log; no AR asks for one.
- **D3, D6-D12, D17** are M1-only and built; their text is in the trim commit named in §2.
- **D13 Screens.** Action names use letters and underscores. Break screen: row 0 is Fight, Heal all & fight, Fight until hurt, Auto-order, Back out; rows 1-3 the heals, berry select and party order (one select of the six orders); row 4 the stop threshold. Team picker rows 3-4: the skip selects, two because a select holds 25 options and a skip reaches 40.
- **D14 M2 chain.** `arena_until_hurt` returns only `after_commit` (`bot/walker.py:207-208`). That coroutine runs under the session lock (`:152-153`), submits one `writer.run` job per fight and renders the result; `bot/walker.py` does not change (confirmed at 3ab843a). The handler does not redraw first, or a stale screen could fight. After a drain closes the writer (`bot/client.py:256`), `writer.run` raises (`db/__init__.py:78`) and the chain returns the last committed screen with the restart text.
- **D15 M2 has its own migration `0026`** for the stop threshold and auto-order columns, so M1 ships no unused columns.
- **D16 `content/help.md` counts as docs** for row size: it is prose pinned by `tests/test_readme.py`.
- **D18 M3 state and payout.** `0027`: one score row per guild, UTC month and profile (composite profile FK cascade, as `0014_gyms.sql:10,24`); one settled row per guild and month with no profile reference, plus paid-place rows with a profile cascade; so a month pays once and no player data outlives deletion. `settle` in `services/arena.py` runs in the caller's transaction at Arena dispatch (`bot/arena.py:301-303`), inbox open (`bot/milestones.py:181`) and `Walker.home` before `pending_count` (`bot/walker.py:256`). The home call goes beyond AR-39: the home Inbox button is disabled at count 0 (`bot/screens.py:36-38`), so a winner with an empty inbox could not open it. Rewards, minimum floor and board sizes live in `arena.json`. Names render as `<@user_id>`, mentions off, as `bot/gyms.py:31`: the bot has no members intent (`bot/client.py:102-103`). Last month's paid places are stored by `settle` in paid-place rows with a profile FK cascade (AR-39), and the screen reads those. A deleted winner drops out, and nobody is promoted on screen.
- **D19 M2 rules.** (a) The setters need the live run and its revision, as `set_order` does: their only controls are on the break screen. The values 10-90 are a SQL CHECK plus one Python constant, not `arena.json`, so the manifest stays. (b) A member already below the threshold stops the chain before its first fight (AR-10b: "a break where any member is below"). A pause does not stop it (AR-8). (c) Economy: an analytic table from `arena.json` and the gym tables at the REQUIREMENTS §6.1/§8 reference floors; no fight simulation, no new PASS/FAIL check. (d) ARENA-18 is split for ticket size; the chain coordinator is ARENA-24.

### 3.2 Contracts (each lands with its row, contract and tests before code)

| Contract | Change | Tickets (ARENA-n) |
|---|---|---|
| C7 `gym-battle.md` | `Combatant.hp` is starting HP; `Result.party_hp`, `Result.finisher`. Compatible. | 1 |
| C4 `balance-tables.md` | Append the `arena.json` table. M2: the economy output. M3: the `leaderboard` rules. | 2, 19, 21 |
| C3 `persisted-state.md` | Append schema 0025, the run service, tickets and redemption, `in_arena` refusals, audit actions. M2: schema 0026, the settings setters, the skip at start, the chain step. M3: schema 0027, the monthly score write, settlement and its `arena_month:` inbox keys. Additive; older binaries refuse a newer schema. | 4-10, 14, 16, 17, 20, 22 |
| C5 `discord-commands.md` | Append Arena screens, `in_arena` texts, `/walker-admin arena on\|off reason`, the home button. M2: the skip selects, threshold, auto-order and Fight until hurt. M3: the Leaderboard screen and button, the inbox label, the settlement call sites. | 5-7, 11-15, 18, 22-24 |

### 3.3 Verification decision (Decide before dispatch)

No owner/repo conflict: AGENTS.md asks for RED → GREEN and the applicable checks; PIPELINE.md:10 is the full command (`python scripts/guard.py && python scripts/verify.py` since 2026-11-14). Rows run **focused** checks only: the modules their ticket names (`python -m unittest discover -s tests -p "test_<module>.py"`) plus `git diff --check`, with RED evidence in the commit body. The full `test_cmd` runs twice, uncached (`FP_RESULT_CACHE=0`):

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
| 20 | [ARENA-18](tickets/ARENA-18.md) M2 screens: skip select, auto-order toggle, stop threshold | build | seam | M | pending |
| 21 | [ARENA-24](tickets/ARENA-24.md) M2 screens: Fight until hurt coordinator and result; help | build | seam | M | pending |
| 22 | [ARENA-19](tickets/ARENA-19.md) economy model and report: Arena ticket income | build | seam | M | pending |
| 23 | ARENA-20 M3 state: migration 0027 and the monthly score write in the boss-win transaction | build | seam | M | pending |
| 24 | ARENA-21 M3 balance: `leaderboard` rules in `arena.json` and the manifest hash | build | seam | S | pending |
| 25 | ARENA-22 M3 settlement: lazy month payout, ranking read, home-open call | build | seam | M | pending |
| 26 | ARENA-23 M3 screens: Leaderboard, Arena and inbox settlement calls, inbox label; help | build | seam | M | pending |
| 27 | G-F final verification and delivery decisions | 🚦 | — | — | pending |

## 5. Briefs

**M2 rows (tickets verified at 3ab843a).** [ARENA-16](tickets/ARENA-16.md), [ARENA-17](tickets/ARENA-17.md), [ARENA-18](tickets/ARENA-18.md), [ARENA-24](tickets/ARENA-24.md), [ARENA-19](tickets/ARENA-19.md), in step order. Each runs the focused checks its ticket names; the full `test_cmd` waits for G-F (§3.3). Decisions: D13, D14, D19.

**M3 rows (unbriefed; requirement anchors for the briefing; code verified at 8390bfd).**
- Greps (`git grep -n <pattern> -- pokewalker`): `inbox_items` → inserts `services/arena.py:280`, `services/gyms.py:114,126`, `services/milestones.py:106`; sole claim `services/milestones.py:131-178`. `arena_best_floor` → sole writer `services/arena.py:204`. `["']inbox["']` → handler `bot/milestones.py:181` (registered `:209`), home button `bot/screens.py:37`, re-entry `bot/bag.py:256,309`.
- **ARENA-20:** AR-36, AR-37, AR-40. The score upsert sits beside the `arena_best_floor` credit (`services/arena.py:202-205`) inside the fight receipt (`:227`); it stores floor and `now` only when the floor beats the month's score. Skipped floors never reach it. The UTC month key is computed in `services/arena.py` (two-file limit). Deletion and reset are the profile delete (`services/deletion.py:131`): extend the ARENA-15 lists (`tests/test_deletion.py:302,314`, `tests/test_admin_reset_sharing.py:232`) and the version pin (`tests/test_arena_schema.py:67`).
- **ARENA-21:** AR-38, AR-40. `rules.leaderboard`: minimum floor 10; items per place, all rare pockets capped at 1 (`content/balance/capacities.json:8-12`); 10 rows shown, 3 for last month. Manifest hash, C4 and the exact-payload test (`tests/test_balance_tables.py:76`), as ARENA-2. It stales the report's manifest hash (`scripts/simulate_economy.py:29`): regenerate as ARENA-19.
- **ARENA-22:** AR-37, AR-38, AR-39. `settle` pays each unsettled past month, oldest first: rank by floor, win time, `profiles.created_at` (`0001_core.sql:24`), `profile_id`; places 1-3 at or above the minimum floor get `inbox_items` rows `arena_month:<YYYY-MM>:<place>` (`resource='item'`; free-text key, `0004_milestones.sql:10-11`); then the month is recorded. No receipt: the settled row is the guard. The claim already holds back a rare item with no free pocket (`services/milestones.py:146-156`). A ranking read returns the top rows, the viewer's place and the next reset. The `Walker.home` call lands here.
- **ARENA-23:** AR-39, AR-40, AR-41. Action `arena_leaderboard` (registry `bot/arena.py:361-364`; pinned set `tests/test_arena_screens.py:224-229`); its button joins the Arena home (`:52`), which opens with the Arena off (`:38-39`). The Arena and inbox calls land here. `arena_month:` keys miss the `arena:` label branch (`bot/milestones.py:87`) and get their own. Help and its hash (`tests/test_readme.py:42-44`, D16).
- A row that needs a third production file, or a ticket over 4 KB, is split at briefing.

**G-F (coordinator; owner for effects).** Predicates: every row ✅; independent integration GO; one exact-tree full `test_cmd` PASS on the settled final tree, skips recorded. `test_cmd` does not prove live Discord behavior. Each effect of §3.4 needs its own owner message: push, main integration, host deploy with migrations, command sync, live smoke.
