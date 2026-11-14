# Plan: arena — solo floor-climbing PvE with Arena Tickets

**Status:** approved — in execution · owner approved G-A · G-P 2026-11-13 (direct owner approval in session)
**Home:** feature/arena · D:\Projects\Pokewalker-arena
**Review:** 2026-11-13 · Codex gpt-6-astra (independent, read-only) · GO after 3 rounds (R1 2 MUST/4 SHOULD, R2 1 MUST, R3 0/0); fixes applied by Opus · reviewed untracked tree on main 9c8aec5
**Inputs:** [REQUIREMENTS.md](REQUIREMENTS.md), owner-approved 2026-11-13: every AR-n is settled scope · [PIPELINE.md](../../../PIPELINE.md) · `AGENTS.md` · `rules/*.md`

## 1. Outcome and non-goals

A profile locks a team of 3 and climbs endless floors of three 3-on-1 auto-battles, with HP carried between fights. Cleared floors pay Arena Tickets, redeemed later for encounters and gym-style inbox rewards. Two milestones, as the owner phased them:

- **M1, core (steps 2-16, briefed):** runs and lifecycle, fights with HP carry-over, heal and party order, loss/draw/expiry, knockout Candy, enemy generation, tickets and redemption, gym/trade/research blocks, admin on/off, deletion and reset coverage.
- **M2, speed-ups (steps 18-21, one-line rows briefed when M1 is reached):** floor skip, Fight until hurt, auto-order toggle, stop threshold, economy report.

**Non-goals:** REQUIREMENTS §7; an Arena battle-log viewer (D5); a Storage-detail change (D10); pruning old runs; any push, deploy, command sync or live Discord action (§3.4).

## 2. Verified code map (verified at 9c8aec5)

**Grep and command evidence**
- `git grep -n -i arena -- pokewalker content contracts tests scripts` → none: no sibling work owns this capability.
- `git grep -n "Result(\|simulate(\|\.survivors" -- pokewalker` → producer `battle.py:168`, sole consumer `gyms.py:333-351`.
- `git grep -n "protected_reason\|tradable_reason\|eligible_page(\|_recheck(\|candidates(" -- pokewalker` → the call sites named in ARENA-6 and ARENA-7.
- `git grep -n "pay_hours\|end_deployment" -- pokewalker` → `gyms.py:148,183,194,344`, `bot/gyms.py:385,398`, `bot/mod.py:75,137`.
- `git grep -n "DELETE FROM action_receipts" -- pokewalker` → only the one-time cleanup in `0003_receipt_owner.sql:19`: no runtime code prunes receipts.
- Scratch checks on `content/artifact/content.json` (not committed; ARENA-2, ARENA-3 and ARENA-8 turn them into tests): a row built from each identity's `pokemon_id`/`form_id` resolves to that identity through `storage.identify` and `gyms._battle_snapshot`, 0 mismatches of 1094; the AR-20 counts (128/966) and the AR-22 cap and pool table reproduce.

| Anchor | Fact | Tickets (ARENA-n) |
|---|---|---|
| `domain/battle.py:21-45, :47-54, :96-169` | `Combatant.hp` is any positive int (:44); `Result` has 5 fields plus `engine_version`; `simulate` takes 1..3 (:98) and tracks `health`/`active` | 1, 9 |
| `services/gyms.py:242-253, :332-351` | `_battle_snapshot` → `(Combatant, snapshot with cp)`; the only engine consumer | 1, 8, 9 |
| `services/gyms.py:60-104, :256-355` | deploy refusals (:80-89); battle savepoint refusal (:273-279), party loop (:301-312), nominee must be in the party (:313-318) | 5 |
| `services/gyms.py:107-134, :137-168` | income roll (:119-127); survivor roll plus flat Stardust (:151-158) | 10 |
| `db/__init__.py:34-47, :72-83, :158-176` | contiguous migrations, next is 0025; `Writer.run`; `with_receipt(..., profile_id=)` | 4, 8-10 |
| migrations `0003`, `0004:7-15`, `0014:26-28`, `0018:42`, `0023` | receipt-owner cascade; `inbox_items` free-text key; partial unique "active" indexes; trade trigger; guild flag | 4, 7 |
| `services/profiles.py:72-101` | `restrictions`, `session_owner`, `queue_size` | 4, 8, 10 |
| `services/stepping.py:65-91, :154-158` | `spawn_encounter` (caller checks room; Lure, Mirror, Charm apply); candy upsert and ledger line | 9, 10 |
| `services/items.py:106-145` | check-in paused refusal (:113-114); queue guard (:139) | 8, 10 |
| `services/milestones.py:125-178`; `bot/milestones.py:83-104, :174, :194` | `pending_count` counts distinct keys; lossless `claim`; `_gym_labels` | 10, 13 |
| `services/storage.py:6-14, :35-43` | `identify`; `page(..., favorites_first=)` | 8, 11 |
| `services/research.py:10-88`; `bot/research.py:55-158`; `bot/storage.py:56-80, :184` | `protected_reason` and its 7 call sites; single send is `bot/research.py:140` | 6 |
| `services/trading.py:11-39, :164-200, :260-262`; `bot/trade.py:18-19, :127-165` | `REFUSED`, `_TRADABLE`; eligibility at offer (:169) and acceptance (:196) | 7 |
| `bot/gyms.py:62-91, :99-166, :209-240, :290-305, :339-374` | pickers with `favorites_first`, `sort_label` (:89), `reason()`, result text (:154) | 5, 11 |
| `bot/walker.py:27, :71-87, :141-214` | action names match `[a-z_]+`; handler registry; one-transaction dispatch; `after_commit` hook (:206-207; users `bag.py:452`, `share.py:91`) | 11-15, 18 |
| `bot/screens.py:11-39`; `tests/test_screens.py:33` | home buttons enabled by `available`; label list pinned | 15 |
| `bot/admin_channels.py:223-250, :385-418` | `sharing` (command shape), `gyms legendary` (semantics) | 14 |
| `content/build/emit.py:25-26, :168, :234`; `tests/test_content_integrity.py:85-91`; `tests/test_balance_tables.py:19-23, :295-320`; `.gitattributes` | manifest hashes every `content/balance/*.json`; exact table list; LF | 2 |
| `tests/test_receipt_owner.py:46-108`, `test_capacity.py:76-82`, `test_trading_schema.py:87-91`, `test_deletion.py:256-271`, `test_readme.py:17-48` | schema-, deletion- and help-pinned tests | 4, 15 |
| `scripts/economy/model.py:288-303`; `scripts/simulate_economy.py:69-86` | gym income section of the model and report | 19 |

**REQUIREMENTS §10, corrected at HEAD**
- The Fight-until-hurt coordinator needs no new dispatcher: handlers already return `after_commit`, awaited after the commit (`walker.py:206-207`). See D14.
- `bot/storage.py` holds no send refusal; the single send is `bot/research.py:140-158`. See D10.
- ADR 0001 has no balance-table provenance text (unverified claim in AR-20 and PIPELINE.md). The binding envelope is `contracts/balance-tables.md:27-34` plus `tests/test_balance_tables.py:295-320`.
- `milestones.json` already lists the Ultra Beast species; ARENA-2 tests the two lists against each other.
- Not in §10: the `[a-z_]+` action pattern, the pinned help hash, the pinned home label list, and the schema-pinned tests above.

**Do not touch:** migrations 0001-0024; `db/__init__.py`; `domain/cp.py`, `domain/encounters.py`, `domain/steps.py`; `ENGINE_VERSION`; balance tables other than `arena.json`; `content/artifact/**`, `content/build/**`; services `deletion`, `marker_log`, `stepping`, `milestones`, `items`, `storage`, `catching`, `evolution`, `powerup`, `raids`, `capacity` (imported only); `bot/storage.py`, `bot/client.py`, `bot/mod.py`; gym payout keys and seeded rng order; `deploy/**`, `.github/**`, `PIPELINE.md`, `AGENTS.md`, `rules/**`; `REQUIREMENTS.md`; other feature folders, except the generated `docs/features/pokewalker-bot/economy-report.md` in ARENA-19.

**New files:** `content/balance/arena.json`, `pokewalker/domain/arena.py`, `pokewalker/services/arena.py`, `pokewalker/bot/arena.py`, `pokewalker/db/migrations/0025_arena.sql` (M2: `0026`); tests `test_arena_domain`, `test_arena_schema`, `test_arena_gym_block`, `test_arena`, `test_arena_screens`, `test_arena_admin`.

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

### 3.2 Contracts (each lands with its row, contract and tests before code)

| Contract | Change | Tickets (ARENA-n) |
|---|---|---|
| C7 `gym-battle.md` | `Combatant.hp` is starting HP; `Result.party_hp`, `Result.finisher`. Compatible. | 1 |
| C4 `balance-tables.md` | Append the `arena.json` table. M2: the economy output. | 2, 19 |
| C3 `persisted-state.md` | Append schema 0025, the run service, tickets and redemption, `in_arena` refusals, audit actions. Additive; older binaries refuse schema 25. | 4-10, 14 |
| C5 `discord-commands.md` | Append Arena screens, `in_arena` texts, `/walker-admin arena on\|off reason`, the home button. | 5-7, 11-15 |

### 3.3 Verification decision (Decide before dispatch)

No owner/repo conflict: AGENTS.md asks for RED → GREEN and the applicable checks; PIPELINE.md:10 names the full matrix. Rows run **focused** checks only: the modules their ticket names (`python -m unittest discover -s tests -p "test_<module>.py"`) plus `git diff --check`, with RED evidence in the commit body. The full `test_cmd` runs twice, uncached (`FP_RESULT_CACHE=0`):

- **Source increment M1** (rows ARENA-1..ARENA-15, at G-M1). Outcome: a complete playable Arena on the feature branch, for the owner's smoke test. Reason: M2 changes the fight path, and a qualified M1 baseline localizes regressions. It is not a delivery.
- **Final feature** (G-F).

The owner's code review loop (global CLAUDE.md) is review, not tests; the coordinator applies it.

### 3.4 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` (PIPELINE.md:15); no feature exception. M1 is a verification increment only. |
| Candidate | the final accepted feature candidate on the Home assigned at G-A |
| Action scope and targets | **Set at G-A 2026-11-13:** feature-branch backup pushes of `feature/arena` to `origin` are authorized (never main, never force; owner standing preference for drives, confirmed at G-A). Main integration and push, host deploy, command sync and live smoke stay separate owner effects at G-F. Repo `Farkoal2128/Pokewalker-Discord-Bot`, remote `origin` (`git remote -v`), main branch `main`. Separate owner effects: feature-branch backup pushes (never main, never force); main integration and push; host deploy applying 0025/0026 (`deploy.*: none`, so by the owner's hand); a Discord command sync for the new admin subcommand (`deploy/deploy.sh:193-195`); live smoke. |
| Predicates and workflow | independent integration GO and one exact-tree full `test_cmd` PASS per pushed or deployed candidate |
| Owner authority | G-A 2026-11-13: plan approval, Home, docs commit on Home, feature-branch backup pushes |

**G-P.** Allowlist: this `PLAN.md`, `REQUIREMENTS.md`, `tickets/ARENA-1.md`..`ARENA-15.md`. Effect of a push to `main` or a pull request: `.github/workflows/verify.yml` runs (PIPELINE.md:26). **Decided at G-A: no publication to main**; the docs are committed on the Home branch `feature/arena` and pushed with it. If the owner confirms local-only, G-P does not apply. The plan author never pushes.

### 3.5 Gate record

| Gate | Decision maker | Scope | Evidence |
|---|---|---|---|
| G-A · G-P | owner | plan approval, Home (`branch_policy: feature-branch`), delivery and push scope | an owner message naming G-A |
| G-M1 | coordinator | qualify increment M1; then request the M2 briefing | integration GO; `Tests:` receipt for the M1 tree |
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
| 9 | [ARENA-8](tickets/ARENA-8.md) service: start, expiry, order, heal | build | seam | L | pending |
| 10 | [ARENA-9](tickets/ARENA-9.md) service: fight, Heal all and fight, Candy, ticket credit | build | seam | L | pending |
| 11 | [ARENA-10](tickets/ARENA-10.md) service: redemption and the gym roll helper | build | seam | M | pending |
| 12 | [ARENA-11](tickets/ARENA-11.md) screens: Arena home, team picker, start | build | seam | M | pending |
| 13 | [ARENA-12](tickets/ARENA-12.md) screens: break actions and results | build | seam | M | pending |
| 14 | [ARENA-13](tickets/ARENA-13.md) screens: tickets, redemption, inbox labels | build | seam | M | pending |
| 15 | [ARENA-14](tickets/ARENA-14.md) admin on/off command | build | seam | S | pending |
| 16 | [ARENA-15](tickets/ARENA-15.md) go live: registration, home button, help, deletion coverage | build | seam | M | pending |
| 17 | G-M1 qualify increment M1 | 🚦 | — | — | pending |
| 18 | ARENA-16 M2 settings: migration 0026 and setters that bump the live run revision | build | seam | S | pending |
| 19 | ARENA-17 M2 backend: floor skip with tickets at run start; chain step | build | seam | M | pending |
| 20 | ARENA-18 M2 screens: skip select, Fight until hurt, auto-order toggle, threshold; help | build | seam | M | pending |
| 21 | ARENA-19 economy model and report: Arena income | build | seam | M | pending |
| 22 | G-F final verification and delivery decisions | 🚦 | — | — | pending |

## 5. Briefs

**G-A · G-P (owner).** Asks: approve this plan; assign the Home (a feature branch cut from `main` at or after 9c8aec5, carrying this folder); choose the delivery and push scope of §3.4. Stop if: the Home lacks 9c8aec5 (`git merge-base --is-ancestor 9c8aec5 <home>`).

**G-M1 (coordinator).** Predicates: steps 2-16 are ✅; independent integration GO over the M1 diff; one exact-tree full `test_cmd` PASS. Then request the M2 briefing (`; briefed <IDs> await owner approval`). Technical failure blocks M2; it is not an owner question.

**M2 rows (unbriefed; requirement anchors for the briefing).**
- **ARENA-16:** AR-10b, AR-10d. `profiles` gains a stop threshold (10-90 in tens, default 50) and an auto-order flag (default off). Changing either bumps a live run's revision in the same transaction.
- **ARENA-17:** AR-34 skip `k <= min(best_floor // 2, 40)` from `arena.json`; skipped floors pay their scheduled tickets in the transaction that creates the run, with no first-clear bonus and no Candy; `best_floor` rises only from fought floors. AR-10b chain step: one writer job rechecks revision, restrictions and the 18-hour limit, reorders by HP percentage when auto-order is on, fights once, and reports the stop reason.
- **ARENA-18:** AR-10a, AR-10b, AR-15. D13 row budget, D14 coordinator; the result screen lists every fight and the order left.
- **ARENA-19:** REQUIREMENTS §10 economy row; add Arena ticket income, with and without a skip, to `scripts/economy/model.py`, `scripts/simulate_economy.py` and the regenerated report.
- A row that needs a third production file is split at briefing.

**G-F (coordinator; owner for effects).** Predicates: every row ✅; independent integration GO; one exact-tree full `test_cmd` PASS on the settled final tree, skips recorded. `test_cmd` does not prove live Discord behavior. Each effect of §3.4 needs its own owner message: push, main integration, host deploy with migrations, command sync, live smoke.
