# Plan: arena — solo floor-climbing PvE with Arena Tickets

**Status:** approved — in execution · owner approved G-A · G-P 2026-11-13 (direct owner approval in session) · amended 2026-11-14 at owner request: M3 leaderboard rows ARENA-20..23 (AR-36..AR-41) and M4 X-item rows ARENA-25..28 (AR-42..AR-46) added; owner approved ARENA-25, ARENA-26, ARENA-27, ARENA-28 2026-11-14 (in advance)
**Home:** feature/arena · D:\Projects\Pokewalker-arena
**Review:** 2026-11-13 · Codex gpt-6-astra (independent, read-only) · GO after 3 rounds (R1 2 MUST/4 SHOULD, R2 1 MUST, R3 0/0); fixes applied by Opus · reviewed untracked tree on main 9c8aec5 · M3 amendment 2026-11-14: Codex gpt-6-astra GO after 1 round (0 MUST, 1 SHOULD fixed by Opus) · M2 brief: astra GO r2 (r1 2M/2S fixed) · M3 brief: astra r2 0M/1S (fixed; r1 1M/1S fixed) · M4: astra GO r1 (1S fixed)
**Inputs:** [REQUIREMENTS.md](REQUIREMENTS.md), owner-approved 2026-11-13: every AR-n is settled scope; §6.3 (AR-36..AR-41) and §6.4 (AR-42..AR-46; uncommitted, `git status --short`) added 2026-11-14 at owner request; owner pre-approved the M4 briefs 2026-11-14 · [PIPELINE.md](../../../PIPELINE.md) · `AGENTS.md` · `rules/*.md`

## 1. Outcome and non-goals

A profile locks a team of 3 and climbs endless floors of three 3-on-1 auto-battles, with HP carried between fights. Cleared floors pay Arena Tickets, redeemed later for encounters and gym-style inbox rewards. Four milestones: M1 and M2 as the owner phased them, M3 and M4 as requested 2026-11-14.

- **M1 core, M2 speed-ups, M3 monthly leaderboard (steps 2-26, built; G-M1 ✅):** runs, fights with HP carry-over, heals, tickets and redemption, the gym/trade/research blocks and the admin switch; floor skip and Fight until hurt; the per-server monthly board with inbox rewards.
- **M4, X items (steps 27-30, briefed):** X-Attack and X-Defense, bought for Stardust on the Arena home and the break screen and used during a break: ×2 attack or defense for the whole party for 3 fights (REQUIREMENTS §6.4).

**Non-goals:** REQUIREMENTS §7 and AR-41; an Arena battle-log viewer (D5); a Storage-detail change; pruning old runs; for M4, an engine or C7 change, a Bag, capacity or conversion change, and modelling the X-item Stardust sink in the economy report; any push, deploy, command sync or live Discord action (§3.4).

## 2. Verified code map (verified at e230414)

**Trimmed to current state: M4 anchors only.** `git show <sha>:docs/features/arena/PLAN.md` has the earlier text: `3ab843a` (M1 anchors, D3, D6-D12, D17, the G-M1 brief), `8e6a7bf` (M2 anchors, D15, D19), `e230414` (M3 anchors, greps and brief notes, D14, D18).

| Anchor | Fact | Tickets (ARENA-n) |
|---|---|---|
| `db/__init__.py:34-41`; `0025_arena.sql:6-18`; `0026_arena_settings.sql:1-4`; `0001_core.sql:122-127` | contiguous migrations, a newer schema is refused, the last is 0027 (`ls pokewalker/db/migrations`); `arena_runs`; the `ADD COLUMN … CHECK` form; `inventory.item_id` is free text | 26 |
| `services/arena.py:79-88, :91-112, :188-194, :235-266` | `_latest_run` reads `SELECT *`; `state` loads the profile row (`:94`) and returns a pinned dict; the `_live_run` stale rule; `heal`: debit `:255`, revision bump `:257`, ledger line `:261-262`, receipt `:264` | 26 |
| `services/arena.py:269-332, :349, :372` | `fight`: party combatants `:279-280`, enemy `:281`, the only Arena `simulate` call `:282`, the run UPDATE `:321-324`, result `:325-330`, receipt `:332`; `chain_step` and `heal_all_and_fight` fight through `fight` | 27 |
| `services/items.py:10, :13-17, :199-226` | `RARE`; `bag_units` sums every non-rare `inventory` row; `_buy`: key `:206`, `insufficient` `:213`, `bag_full` `:215`, reason `buy` `:222`, a success result without `status` `:224` | 26 |
| `domain/battle.py:10, :21-43, :142` | `ENGINE_VERSION`; `Combatant` accepts any positive finite `attack` and `defense`; damage reads `user.attack` and `target.defense` | 27 |
| `bot/arena.py:22-23, :37-57, :184-216, :301-316, :318-360, :397, :417-440, :493-496` | `BREAK_ACTIONS`; `render_home` (buttons `:53-54`, no notice line); `render_break`: row 0 full `:198-201`, three heals on row 1 `:202-204`, selects on rows 2-4 `:205-215`; `open_break`; `break_action`; the chain renders through `open_break`; `dispatch`; the registry | 28 |
| `bot/bag.py:26, :33-34, :66`; `bot/walker.py:178-179` | the Bag lists every non-rare row under its title-cased id and converts only items with a rate; the router bumps `session['revision']` on every press | 26, 28 |
| `content/balance/arena.json:4, :164-181`; `capacities.json:7-12`; `conversion_rates.json:5-24`; `scripts/simulate_economy.py:29, :38-39` | `version` 2, `rules` ends with `leaderboard`; `bag_units` and the rare pockets; rates and `purchase_stardust`; the report prints the manifest hash and the table versions | 25 |
| `tests/test_balance_tables.py:76-123, :397-399`; `test_arena_schema.py:69, :113-114, :146-148`; `test_arena.py:96-98`; `test_arena_screens.py:505-516`; `test_readme.py:41-44` | moving pins: exact Arena payload and version dict; schema version and `arena_runs` row comparisons; exact `state` dict; action set; help hash | 25-28 |

Greps at e230414. Over `pokewalker scripts tests contracts content`: `git grep -nw "x_attack\|x_defense\|x_items\|buy_x\|use_x"` and `git grep -n "arena_buy\|arena_use"` have no hit (the M4 names are free). Over `pokewalker scripts`: `_buy(` → `services/items.py:191, :196, :199`; `\.simulate(` → `services/arena.py:282`, `services/gyms.py:347`. **Unverified:** that the committed economy report equals the CLI output at e230414 (this shell lacks `regex`); `git log 8e5b862..HEAD -- content scripts docs/features/pokewalker-bot` shows only `content/help.md` changed since ARENA-21 regenerated it.

**Do not touch:** migrations 0001-0027; `db/__init__.py`; `domain/**`; `ENGINE_VERSION`; balance tables other than `arena.json`; `content/artifact/**`, `content/build/**`; every service but `arena` (`items` is imported only); every `bot/` module but `arena.py`; gym payout keys and seeded rng order; `deploy/**`, `.github/**`, `PIPELINE.md`, `AGENTS.md`, `rules/**`; `REQUIREMENTS.md`; other feature folders, except the generated `docs/features/pokewalker-bot/economy-report.md` in ARENA-25.

**New files:** migration `0028_arena_x_items.sql` (M4).

## 3. Decisions

### 3.1 Design

- **D1 Layers.** `domain/arena.py` is pure (table and rng injected); `services/arena.py` writes inside the caller's writer transaction; `bot/arena.py` renders without I/O.
- **D2 Run storage.** One `arena_runs` row per run. Live means `ended_at IS NULL`, one per profile by partial unique index. Team and enemy are JSON snapshots, so a restart or a content release cannot re-roll or re-stat them.
- **D4 Revision and receipts.** Every run change bumps `arena_runs.revision`. Screens keep `run_id` and `run_revision` in the session selection, because a custom ID carries only session, revision and action. Receipt keys, all with `profile_id`: `arena_start:<session>:<rev>`, `arena_heal:<run>:<rev>`, `arena_fight:<run>:<floor>:<slot>`, `arena_redeem:<session>:<rev>`; M4 adds `arena_use:<run>:<rev>` and reuses the Bag's `buy:<session>:<rev>` (D20). Reordering has no receipt: no resource moves.
- **D5 Compact fight receipts.** Outcome, ticks, HP, finisher, Candy and tickets, without event text: receipts are never pruned and a deep run is 300+ fights. So the Arena has no battle log.
- **D3, D6-D12, D17** (M1), **D14, D15, D19** (M2) and **D18** (M3) are built; their text is in the trim commits named in §2.
- **D13 Screens.** Action names use letters and underscores. Break screen: row 0 is Fight, Heal all & fight, Fight until hurt, Auto-order, Back out; row 1 the three heals and, in M4, one X-item button per kind (D20); rows 2-4 the berry select, the party order (one select of the six orders) and the stop threshold.
- **D16 `content/help.md` counts as docs** for row size: it is prose pinned by `tests/test_readme.py`.
- **D20 M4 X items (AR-42..AR-46).** Recommendations where §6.4 is silent.
  - **Items.** `x_attack` and `x_defense` are plain `inventory` rows, so each counts one bag unit (`services/items.py:13-17`). They get no rare pocket and no conversion rate: `capacities.json` and `conversion_rates.json` do not change. The Bag lists them as `X Attack ×n` (`bot/bag.py:26, :66`) and cannot convert them (AR-45).
  - **Table.** `arena.json` `rules.x_items` (`version` 3): `fights` 3, `multiplier` 2, and per item its `stat` and its `stardust` price, 300.
  - **Buy.** `buy_x(conn, session, item)` calls `items._buy`, the helper behind Vitamins: one item per press with no confirm step; `insufficient`, then `bag_full`, refuse with nothing spent; receipt `buy:<session>:<session revision>`, ledger reason `buy`. It needs the walker session and its profile, never a run: no run-revision bump, and no check of Arena off, cooldown or pause.
  - **Use.** `use_x`, shaped like `heal`: a live run at the pressed revision; the same kind active → refused; else item −1, counter = `fights`, revision +1, receipt `arena_use:<run>:<rev>`, ledger reason `arena_use`.
  - **State.** `0028` adds `arena_runs.x_attack_left` and `x_defense_left` (integers ≥ 0, default 0), so an effect ends with its run.
  - **Fight.** `fight` multiplies the stat on the party `Combatant`s it passes to `battle.simulate`, and lowers both counters by one (not below 0) in the UPDATE that stores the fight, whatever the outcome. A loss or draw also ends the run, so what is left is never read. Snapshots, the enemy, the result and receipt (D5), the engine and C7 do not change. Chained fights go through `fight`; a chain does not stop when a boost runs out.
  - **Screens.** The break screen has two free slots, on row 1 (Discord allows 5 rows of 5), so each kind gets one button: `Buy` with none held, `Use` when held, disabled `n fights left` while active. The home has two Buy buttons. Both show Stardust and the held counts; the break also lists each active boost.

### 3.2 Contracts (each lands with its row, contract and tests before code)

| Contract | Change | Tickets (ARENA-n) |
|---|---|---|
| C7 `gym-battle.md` | `Combatant.hp` is starting HP; `Result.party_hp`, `Result.finisher`. Compatible. M4 changes nothing here (D20). | 1 |
| C4 `balance-tables.md` | Append the `arena.json` table. M2: the economy output. M3: the `leaderboard` rules. M4: the `x_items` rules. | 2, 19, 21, 25 |
| C3 `persisted-state.md` | Append schema 0025, the run service, tickets and redemption, `in_arena` refusals, audit actions. M2: schema 0026, the settings setters, the skip at start, the chain step. M3: schema 0027, the monthly score write, settlement and its `arena_month:` inbox keys. M4: schema 0028, the `state` keys, `buy_x` and `use_x`, the boosted fight and its countdown. Additive; older binaries refuse a newer schema. | 4-10, 14, 16, 17, 20, 22, 26, 27 |
| C5 `discord-commands.md` | Append Arena screens, `in_arena` texts, `/walker-admin arena on\|off reason`, the home button. M2: the skip selects, threshold, auto-order and Fight until hurt. M3: the Leaderboard screen and button, the inbox label, the settlement call sites. M4: the X-item buttons, lines and notices on the home and break screens. | 5-7, 11-15, 18, 22-24, 28 |

### 3.3 Verification decision (Decide before dispatch)

No owner/repo conflict: AGENTS.md asks for RED → GREEN and the applicable checks; PIPELINE.md:10 is the full command (`python scripts/guard.py && python scripts/verify.py` since 2026-11-14). Rows run **focused** checks only: the modules their ticket names (`python -m unittest discover -s tests -p "test_<module>.py"`) plus a diff check, with RED evidence in the commit body. M3 and M4 rows touch files committed with CR line ends; those stay as they are, so the check is `git -c core.whitespace=cr-at-eol diff --cached --check`. The full `test_cmd` runs twice, uncached (`FP_RESULT_CACHE=0`):

- **Source increment M1** (rows ARENA-1..ARENA-15, qualified at G-M1): a complete playable Arena on the feature branch, for the owner's smoke test. It is not a delivery.
- **Final feature** (G-F). M2, M3 and M4 are not source increments; their rows run focused checks.

The owner's code review loop (global CLAUDE.md) is review, not tests; the supervising Claude session runs it once after the last build row, before G-F. Drives use the per-row seam review only.

### 3.4 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` (PIPELINE.md:15); no feature exception. M1 is a verification increment only. |
| Candidate | the final accepted feature candidate on the Home assigned at G-A |
| Action scope and targets | **Set at G-A 2026-11-13:** feature-branch backup pushes of `feature/arena` to `origin` are authorized (never main, never force; owner standing preference for drives, confirmed at G-A). Main integration and push, host deploy, command sync and live smoke stay separate owner effects at G-F. Repo `Farkoal2128/Pokewalker-Discord-Bot`, remote `origin` (`git remote -v`), main branch `main`. Separate owner effects: feature-branch backup pushes (never main, never force); main integration and push; host deploy applying 0025-0028 (`deploy.*: none`, so by the owner's hand); a Discord command sync for the new admin subcommand (`deploy/deploy.sh:193-195`); live smoke. |
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
| 25 | [ARENA-22](tickets/ARENA-22.md) M3 settlement: lazy month payout, ranking read, home-open call | build | seam | M | ✅ done · 2203f0b · GO review r1 |
| 26 | [ARENA-23](tickets/ARENA-23.md) M3 screens: Leaderboard, Arena and inbox settlement calls, inbox label; help | build | seam | M | ✅ done · 5672447 · GO review r1 |
| 27 | [ARENA-25](tickets/ARENA-25.md) M4 balance: `x_items` rules in `arena.json` and the manifest hash | build | seam | S | pending |
| 28 | [ARENA-26](tickets/ARENA-26.md) M4 state: migration 0028, `state` keys, buy and use | build | seam | M | pending |
| 29 | [ARENA-27](tickets/ARENA-27.md) M4 fights: boosted party combatants and the per-fight countdown | build | seam | S | pending |
| 30 | [ARENA-28](tickets/ARENA-28.md) M4 screens: buy and use on the home and break screens; help | build | seam | M | pending |
| 31 | G-F final verification and delivery decisions | 🚦 | — | — | pending |

## 5. Briefs

**Built rows (M1-M3).** Each brief is its ticket, linked in §4; decisions and brief notes are in the trim commits (§2).

**M4 rows (tickets verified at e230414).** [ARENA-25](tickets/ARENA-25.md), [ARENA-26](tickets/ARENA-26.md), [ARENA-27](tickets/ARENA-27.md), [ARENA-28](tickets/ARENA-28.md), in step order. Each runs the focused checks its ticket names; the full `test_cmd` waits for G-F (§3.3). Decisions: D4, D5, D13, D16, D20.
- No row needs a third production file, a package change or a new owner decision, so M4 has no new 🚦 row. The table and the migration are separate rows: `arena.json`, `content/manifest.json` and `0028` are three production files.
- D20 decides what §6.4 leaves open; approving the briefed rows accepts it.

**G-F (coordinator; owner for effects).** Predicates: every row ✅; independent integration GO; one exact-tree full `test_cmd` PASS on the settled final tree, skips recorded. `test_cmd` does not prove live Discord behavior. Each effect of §3.4 needs its own owner message: push, main integration, host deploy with migrations, command sync, live smoke.
