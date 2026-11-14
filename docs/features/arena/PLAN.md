# Plan: arena — solo floor-climbing PvE with Arena Tickets

**Status:** approved — in execution · owner approved G-A · G-P 2026-11-13 (direct owner approval in session) · amended 2026-11-14: M3 leaderboard rows ARENA-20..23 added at owner request (AR-36..AR-41), unbriefed
**Home:** feature/arena · D:\Projects\Pokewalker-arena
**Review:** 2026-11-13 · Codex gpt-6-astra (independent, read-only) · GO after 3 rounds (R1 2 MUST/4 SHOULD, R2 1 MUST, R3 0/0); fixes applied by Opus · reviewed untracked tree on main 9c8aec5 · M3 amendment 2026-11-14: Codex gpt-6-astra GO after 1 round (0 MUST, 1 SHOULD fixed by Opus)
**Inputs:** [REQUIREMENTS.md](REQUIREMENTS.md), owner-approved 2026-11-13: every AR-n is settled scope; §6.3 (AR-36..AR-41) added 2026-11-14, owner approval of its [R] items unverified · [PIPELINE.md](../../../PIPELINE.md) · `AGENTS.md` · `rules/*.md`

## 1. Outcome and non-goals

A profile locks a team of 3 and climbs endless floors of three 3-on-1 auto-battles, with HP carried between fights. Cleared floors pay Arena Tickets, redeemed later for encounters and gym-style inbox rewards. Three milestones, M1 and M2 as the owner phased them and M3 as requested 2026-11-14:

- **M1, core (steps 2-16, briefed):** runs and lifecycle, fights with HP carry-over, heal and party order, loss/draw/expiry, knockout Candy, enemy generation, tickets and redemption, gym/trade/research blocks, admin on/off, deletion and reset coverage.
- **M2, speed-ups (steps 18-21, one-line rows briefed when M1 is reached):** floor skip, Fight until hurt, auto-order toggle, stop threshold, economy report.
- **M3, monthly leaderboard (steps 22-25, one-line rows briefed when ARENA-20 is reached):** per-server monthly best-floor board, lazy month-end inbox rewards for the top 3, Leaderboard screen (REQUIREMENTS §6.3).

**Non-goals:** REQUIREMENTS §7 and AR-41; an Arena battle-log viewer (D5); a Storage-detail change (D10); pruning old runs; any push, deploy, command sync or live Discord action (§3.4).

## 2. Verified code map (verified at 9c8aec5)

**Trimmed to current state** (`git show 8390bfd:docs/features/arena/PLAN.md`): the pre-build greps, the REQUIREMENTS §10 corrections, the G-A brief and the anchor rows no pending row needs. M3 greps and anchors: §5, verified at 8390bfd.

| Anchor | Fact | Tickets (ARENA-n) |
|---|---|---|
| `db/__init__.py:34-47, :72-83, :158-176` | contiguous migrations, next is 0025; `Writer.run`; `with_receipt(..., profile_id=)` | 4, 8-10 |
| `bot/walker.py:27, :71-87, :141-214` | action names match `[a-z_]+`; handler registry; one-transaction dispatch; `after_commit` hook (:206-207; users `bag.py:452`, `share.py:91`) | 11-15, 18 |
| `content/build/emit.py:25-26, :168, :234`; `tests/test_content_integrity.py:85-91`; `tests/test_balance_tables.py:19-23, :295-320`; `.gitattributes` | manifest hashes every `content/balance/*.json`; exact table list; LF | 2 |
| `tests/test_receipt_owner.py:46-108`, `test_capacity.py:76-82`, `test_trading_schema.py:87-91`, `test_deletion.py:256-271`, `test_readme.py:17-48` | schema-, deletion- and help-pinned tests | 4, 15 |
| `scripts/economy/model.py:288-303`; `scripts/simulate_economy.py:69-86` | gym income section of the model and report | 19 |

**Do not touch:** migrations 0001-0024; `db/__init__.py`; `domain/cp.py`, `domain/encounters.py`, `domain/steps.py`; `ENGINE_VERSION`; balance tables other than `arena.json`; `content/artifact/**`, `content/build/**`; services `deletion`, `marker_log`, `stepping`, `milestones`, `items`, `storage`, `catching`, `evolution`, `powerup`, `raids`, `capacity` (imported only); `bot/storage.py`, `bot/client.py`, `bot/mod.py`; gym payout keys and seeded rng order; `deploy/**`, `.github/**`, `PIPELINE.md`, `AGENTS.md`, `rules/**`; `REQUIREMENTS.md`; other feature folders, except the generated `docs/features/pokewalker-bot/economy-report.md` in ARENA-19.

**New files:** migrations `0026` (M2) and `0027` (M3); the M1 files are built.

## 3. Decisions

### 3.1 Design

- **D1 Layers.** `domain/arena.py` is pure (table and rng injected); `services/arena.py` writes inside the caller's writer transaction; `bot/arena.py` renders without I/O. Same split as `domain/battle.py`, `services/gyms.py`, `bot/gyms.py`.
- **D2 Run storage.** One `arena_runs` row per run. Live means `ended_at IS NULL`, one per profile by partial unique index. Team and enemy are JSON snapshots, so a restart or a content release cannot re-roll or re-stat them. The cooldown reads the latest `started_at`; there is no separate "last start" column.
- **D3 One live-team check, in `services/profiles.py`.** `arena_team(conn, profile_id, now)`: not ended and under `run_seconds` old, so the block lifts at hour 18 with no write and no timer. It lives in `profiles` because `services/arena.py` imports `gyms` for `_battle_snapshot`, and gyms, research and trading all need the check. No trigger: SQL cannot see the injected clock.
- **D4 Revision and receipts.** Every run change bumps `arena_runs.revision`. Screens keep `run_id` and `run_revision` in the session selection, because a custom ID carries only session, revision and action. Receipt keys, all with `profile_id`: `arena_start:<session>:<rev>`, `arena_heal:<run>:<rev>`, `arena_fight:<run>:<floor>:<slot>`, `arena_redeem:<session>:<rev>`. Reordering has no receipt: no resource moves.
- **D5 Compact fight receipts.** Outcome, ticks, HP, finisher, Candy and tickets, without event text: receipts are never pruned and a deep run is 300+ fights. So the Arena has no battle log; no AR asks for one.
- **D6 C7 stays version "1".** New `Result` fields have defaults and sit after `engine_version`; no outcome changes for equal inputs.
- **D7 Enemies reuse `_battle_snapshot`** on a row built from the rolled identity (verified above). Fallback if a later content release breaks the round trip: build the `Combatant` from `battle.combat_stats`, as `gyms.py:244-249` does.
- **D8 Integer cap math.** Boss caps use `cap * pct // 100`, so floor 1 gives 345 as the requirement table says.
- **D9 One gym check covers attack and claim.** The nominee must be in the party, and the party loop refuses a team member before the battle runs.
- **D10 `protected_reason(..., arena_team=frozenset())`** reports `in_arena` first, so it is a hard refusal that never reaches the Shiny/Legendary unlock. The Storage detail screen is unchanged: its Send press is refused by the research handler, as favorites and companions are today.
- **D11 Roll helper** `income_roll` and `survivor_roll` in `services/gyms.py`, with the rng call order kept so seeded gym tests pass unedited.
- **D12 Redemption.** Every tier gets a quote, rechecked in the transaction. Paused members may redeem: AR-8 restricts only starting, and AR-35a says tickets can always be redeemed.
- **D13 Screens.** Action names use letters and underscores. The break screen uses rows 0-3 in M1; row 4 and one row-0 slot are kept for M2. Party order is one select of the six orders.
- **D14 M2 chain.** Fight until hurt returns `after_commit`; that coroutine submits one `writer.run` job per fight and renders the result. No dispatcher change is expected; the M2 briefing confirms it against the session lock and the drain path.
- **D15 M2 has its own migration `0026`** for the stop threshold and auto-order columns, so M1 ships no unused columns.
- **D16 `content/help.md` counts as docs** for row size: it is prose pinned by `tests/test_readme.py`.
- **D17 Inbox count.** Each roll is its own inbox key, as gym hours are, so one Diamond adds 28 to "Inbox (n)". Accepted; `pending_count` is unchanged.
- **D18 M3 state and payout.** `0027`: one score row per guild, UTC month and profile (composite profile FK cascade, as `0014_gyms.sql:10,24`); one settled row per guild and month with no profile reference, plus paid-place rows with a profile cascade; so a month pays once and no player data outlives deletion. `settle` in `services/arena.py` runs in the caller's transaction at Arena dispatch (`bot/arena.py:301-303`), inbox open (`bot/milestones.py:181`) and `Walker.home` before `pending_count` (`bot/walker.py:256`). The home call goes beyond AR-39: the home Inbox button is disabled at count 0 (`bot/screens.py:36-38`), so a winner with an empty inbox could not open it. Rewards, minimum floor and board sizes live in `arena.json`. Names render as `<@user_id>`, mentions off, as `bot/gyms.py:31`: the bot has no members intent (`bot/client.py:102-103`). Last month's paid places are stored by `settle` in paid-place rows with a profile FK cascade (AR-39), and the screen reads those. A deleted winner drops out, and nobody is promoted on screen.

### 3.2 Contracts (each lands with its row, contract and tests before code)

| Contract | Change | Tickets (ARENA-n) |
|---|---|---|
| C7 `gym-battle.md` | `Combatant.hp` is starting HP; `Result.party_hp`, `Result.finisher`. Compatible. | 1 |
| C4 `balance-tables.md` | Append the `arena.json` table. M2: the economy output. M3: the `leaderboard` rules. | 2, 19, 21 |
| C3 `persisted-state.md` | Append schema 0025, the run service, tickets and redemption, `in_arena` refusals, audit actions. M3: schema 0027, the monthly score write, settlement and its `arena_month:` inbox keys. Additive; older binaries refuse a newer schema. | 4-10, 14, 20, 22 |
| C5 `discord-commands.md` | Append Arena screens, `in_arena` texts, `/walker-admin arena on\|off reason`, the home button. M3: the Leaderboard screen and button, the inbox label, the settlement call sites. | 5-7, 11-15, 22, 23 |

### 3.3 Verification decision (Decide before dispatch)

No owner/repo conflict: AGENTS.md asks for RED → GREEN and the applicable checks; PIPELINE.md:10 names the full matrix. Rows run **focused** checks only: the modules their ticket names (`python -m unittest discover -s tests -p "test_<module>.py"`) plus `git diff --check`, with RED evidence in the commit body. The full `test_cmd` runs twice, uncached (`FP_RESULT_CACHE=0`):

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
| G-M1 | coordinator | qualify increment M1; then request the M2 briefing (ARENA-16..19) | integration GO; `Tests:` receipt for the M1 tree |
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
| 17 | G-M1 qualify increment M1 | 🚦 | — | — | pending |
| 18 | ARENA-16 M2 settings: migration 0026 and setters that bump the live run revision | build | seam | S | pending |
| 19 | ARENA-17 M2 backend: floor skip with tickets at run start; chain step | build | seam | M | pending |
| 20 | ARENA-18 M2 screens: skip select, Fight until hurt, auto-order toggle, threshold; help | build | seam | M | pending |
| 21 | ARENA-19 economy model and report: Arena income | build | seam | M | pending |
| 22 | ARENA-20 M3 state: migration 0027 and the monthly score write in the boss-win transaction | build | seam | M | pending |
| 23 | ARENA-21 M3 balance: `leaderboard` rules in `arena.json` and the manifest hash | build | seam | S | pending |
| 24 | ARENA-22 M3 settlement: lazy month payout, ranking read, home-open call | build | seam | M | pending |
| 25 | ARENA-23 M3 screens: Leaderboard, Arena and inbox settlement calls, inbox label; help | build | seam | M | pending |
| 26 | G-F final verification and delivery decisions | 🚦 | — | — | pending |

## 5. Briefs

**G-M1 (coordinator).** Predicates: steps 2-16 are ✅; independent integration GO over the M1 diff; one exact-tree full `test_cmd` PASS. Then request the M2 briefing for ARENA-16..19 only (`; briefed <IDs> await owner approval`); M3 is its own milestone, briefed when drive reaches ARENA-20 (plan `SKILL.md` Step 1: one milestone, at most five rows). Technical failure blocks M2; it is not an owner question.

**M2 rows (unbriefed; requirement anchors for the briefing).**
- **ARENA-16:** AR-10b, AR-10d. `profiles` gains a stop threshold (10-90 in tens, default 50) and an auto-order flag (default off). Changing either bumps a live run's revision in the same transaction.
- **ARENA-17:** AR-34 skip `k <= min(best_floor // 2, 40)` from `arena.json`; skipped floors pay their scheduled tickets in the transaction that creates the run, with no first-clear bonus and no Candy; `best_floor` rises only from fought floors. AR-10b chain step: one writer job rechecks revision, restrictions and the 18-hour limit, reorders by HP percentage when auto-order is on, fights once, and reports the stop reason.
- **ARENA-18:** AR-10a, AR-10b, AR-15. D13 row budget, D14 coordinator; the result screen lists every fight and the order left.
- **ARENA-19:** REQUIREMENTS §10 economy row; add Arena ticket income, with and without a skip, to `scripts/economy/model.py`, `scripts/simulate_economy.py` and the regenerated report.
- A row that needs a third production file is split at briefing.

**M3 rows (unbriefed; requirement anchors for the briefing; code verified at 8390bfd).**
- Greps (`git grep -n <pattern> -- pokewalker`): `inbox_items` → inserts `services/arena.py:280`, `services/gyms.py:114,126`, `services/milestones.py:106`; sole claim `services/milestones.py:131-178`. `arena_best_floor` → sole writer `services/arena.py:204`. `["']inbox["']` → handler `bot/milestones.py:181` (registered `:209`), home button `bot/screens.py:37`, re-entry `bot/bag.py:256,309`.
- **ARENA-20:** AR-36, AR-37, AR-40. The score upsert sits beside the `arena_best_floor` credit (`services/arena.py:202-205`) inside the fight receipt (`:227`); it stores floor and `now` only when the floor beats the month's score. Skipped floors never reach it. The UTC month key is computed in `services/arena.py` (two-file limit). Deletion and reset are the profile delete (`services/deletion.py:131`): extend the ARENA-15 lists (`tests/test_deletion.py:302,314`, `tests/test_admin_reset_sharing.py:232`) and the version pin (`tests/test_arena_schema.py:67`).
- **ARENA-21:** AR-38, AR-40. `rules.leaderboard`: minimum floor 10; items per place, all rare pockets capped at 1 (`content/balance/capacities.json:8-12`); 10 rows shown, 3 for last month. Manifest hash, C4 and the exact-payload test (`tests/test_balance_tables.py:76`), as ARENA-2.
- **ARENA-22:** AR-37, AR-38, AR-39. `settle` pays each unsettled past month, oldest first: rank by floor, win time, `profiles.created_at` (`0001_core.sql:24`), `profile_id`; places 1-3 at or above the minimum floor get `inbox_items` rows `arena_month:<YYYY-MM>:<place>` (`resource='item'`; free-text key, `0004_milestones.sql:10-11`); then the month is recorded. No receipt: the settled row is the guard. The claim already holds back a rare item with no free pocket (`services/milestones.py:146-156`). A ranking read returns the top rows, the viewer's place and the next reset. The `Walker.home` call lands here.
- **ARENA-23:** AR-39, AR-40, AR-41. Action `arena_leaderboard` (registry `bot/arena.py:361-364`; pinned set `tests/test_arena_screens.py:224-229`); its button joins the Arena home (`:52`), which opens with the Arena off (`:38-39`). The Arena and inbox calls land here. `arena_month:` keys miss the `arena:` label branch (`bot/milestones.py:87`) and get their own. Help and its hash (`tests/test_readme.py:42-44`, D16).
- Split rule as M2.

**G-F (coordinator; owner for effects).** Predicates: every row ✅; independent integration GO; one exact-tree full `test_cmd` PASS on the settled final tree, skips recorded. `test_cmd` does not prove live Discord behavior. Each effect of §3.4 needs its own owner message: push, main integration, host deploy with migrations, command sync, live smoke.
