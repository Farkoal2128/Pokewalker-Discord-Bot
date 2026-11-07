# Plan: pokewalker-bot — v1 walking loop

**Status:** awaiting plan approval
**Review:** pending — external Codex review; plan-skill Step 3 skipped on owner instruction (2026-11-04)
**Home:** docs/pokewalker-bot-plan · none
**Inputs:** [requirements D1–D61](README.md) · [ADR 0001](../../decisions/0001-application-stack.md) (proposed) · [PIPELINE.md](../../../PIPELINE.md) · [research](../../research/synthesis.md)

## 1. Outcome

The **v1: walking loop** release of D35 (README.md:77), playable in one server: enrollment and
onboarding with starter choice and kit; word steps and anti-farming; the 3-encounter queue and ❗;
`/walker` reveal and catch; CP and IV appraisal with the level hidden; 250-slot storage; send for
research; Candy and Stardust; power-up; passive finds; `/checkin`; walking companion; Pokédex with
D59 milestones; 8 type-themed routes; shiny and Shiny Lure; item-to-Stardust conversion;
hotlinked sprites; `/walker-account`; moderation tools (minus gym ones); owner `/admin`; backups
and the systemd service. The owner-ordered pre-work comes first (README.md:417-420): content
import and chat-rate measurement, then the economy simulation.

## 2. Non-goals

- **v1.1** (README.md:78): evolution and evolution items, Star Piece, storage/bag expansion,
  route unlocks. (Rendered scenes and the storage picture grid are dropped from every version, owner decision 2026-11-04, README D49.)
- **v2** (README.md:79, :106, :108): gyms, survivor roll, World Legendary Ticket, `/raid`,
  `/walker-admin raids`, `/walker-mod gym-recall`, gym income.
- **Later** (README.md:80): peer visits, dowsing presentation, interactive battles, raid battles,
  trading, Candy XL, events.
- Open questions stay out of scope until decided (README.md:404-415): Legendary pacing or a
  featured group; research send from the catch screen. The simulation only *reports* pacing.
- Message Content approval fallback (synthesis.md:171-173) and non-English counting (D43,
  README.md:170-173): recorded as risks, no rows.
- Multi-process or PostgreSQL (ADR 0001:60-63).

## 3. Verified code map — verified at d9fd63f

No application code exists. Grep `rg -l "import discord|aiosqlite|from pokewalker|app_commands"
--glob '!docs/**'` matches only `PIPELINE.md` (prose). `contracts/` holds only README.md and
`_template.md`; `tests/` only `test_framework.py`; `scripts/` only `guard.py`, `new_project.py`,
`verify.py` (Glob, 2026-11-04). Everything in §3.3 is **new**.

### 3.1 Scaffold reuse (file:line)

| Anchor | Fact | Used by |
|---|---|---|
| PIPELINE.md:10 | `test_cmd` = unittest discover + `guard.py` + `verify.py` | final checkpoints (§4.3) |
| PIPELINE.md:13 | `seam_domains` cover gateway, commands, token/intents, step rules, tables, persisted state, abuse controls, verification config | tiering: almost every app row is `seam` |
| PIPELINE.md:15, :26 | `delivery_cadence: end`; push to main runs `framework-verification` only | §4.5 |
| PIPELINE.md:36-43 | scaffold mode; activation requires configuring `.project/commands.json` and moving it to `active` | M5.1 |
| PIPELINE.md:64-71 | no ROM data; PokéAPI pin D51; balance tables authored with source/date; sprites never committed | M0.1–M0.4 |
| scripts/verify.py:29-38, :40-45 | runs each non-null check via `subprocess.run(shell=True)`; `active` stage mandates `unit` and `contract` | M5.1 fills `unit`, `contract` |
| scripts/guard.py:11-22 | refuses template mode / canonical remote; passes for this copy | unchanged |
| tests/test_framework.py:6, :61-64 | `ROOT = parents[1]` pattern; asserts stage `scaffold` and all checks `None` | pattern for new tests; M5.1 must update :61-64 deliberately (PIPELINE.md:40-43 is the requirement) |
| .project/commands.json:2-13 | `stage: scaffold`, nine null checks | M5.1 |
| .github/workflows/verify.yml:3-5, :17-21 | PR + push-to-main triggers; runs unittest and verify.py on Python 3.12, no `pip install` | M0.5 adds the install step |
| contracts/_template.md:1-22 | contract sections (purpose, producers, consumers, invariants, compatibility, verification, change policy) | every C-row in §4.2 |
| .agents/skills/tdd/SKILL.md:8-20; rules/testing.md:3-16 | RED before GREEN; lowest test level | every impl row |
| docs/decisions/0001-application-stack.md:26-53 | stack items 1–7; :80-93 restore-rehearsal cases | M1.1, M1.2, M5.2, G-5 |
| README.md (requirements) | D20 :50, D21 :51, D22 :52, D25 :55, D26 :56, D27 :57, D48 :58, D49 :59, D28 :60, D29 :61, D30 :62, D33 :65, D34 :66, D36 :68, D37 :69, D31 :98-110, D38 :118-139, D39 :140-146, D40a :156-160, D41 :163-164, D42 :167-169, D44 :176, D45 :178-183, D47 :186-190, D50 :197-203, D51 :204-207, D52 :208-216, D53 :217-224, D56–D58 :235-242, D59 :246-311, D61 :377-400 | tickets cite these |

Local toolchain (command `python --version; python -c "import sqlite3; print(sqlite3.sqlite_version)"`,
2026-11-04): Python 3.11.9, SQLite 3.45.1 — both below ADR 0001:26 and :39-41 floors. See P10.

### 3.2 Do-not-touch

`scripts/guard.py`, `scripts/verify.py`, `scripts/new_project.py`, `.template.json`, `AGENTS.md`,
`CLAUDE.md`, `rules/*`, `.agents/**`, `.codex/**`, `contracts/README.md`, `contracts/_template.md`,
`docs/research/**` (facts record), `docs/decisions/0001-application-stack.md` (owner merges it),
`docs/features/pokewalker-bot/README.md` (owner-only decisions; G-2 may trigger an owner edit).
`tests/test_framework.py` and `.github/workflows/verify.yml` change only in the rows that name them.

### 3.3 Layout (built at 3588028; later files from each ticket's Files)

```
content/build/{fetch,graph,families,stats,emit,__main__}.py   importer (M0, built)
content/balance/*.json, content/artifact/content.json, content/manifest.json   (M0, built)
pokewalker/domain/{steps,encounters,cp}.py                    pure rules (built)
pokewalker/db/__init__.py + db/migrations/000N_*.sql          WAL, single writer, receipts
                                                              (0001-0002 built; 0003 M2.2a; later rows add 000N)
pokewalker/services/{profiles,reactions,stepping,catching}.py built; new: storage M2.1,
    research M2.2, powerup M2.3, pokedex M2.5, milestones M2.6, items M3.1-M3.4,
    marker_log M4.1a, deletion M4.1b/M4.1c
pokewalker/bot/{client,messages,walker,screens,screens_catch,admin_channels}.py built; new:
    storage M2.1, research M2.2, powerup M2.3, pokedex M2.5, milestones M2.6, checkin M3.2,
    bag M3.3, route M3.5, account M4.1, mod M4.2, share M4.4, admin M4.5a, heartbeat M4.5b
pokewalker/{config,__main__}.py                               entry (built)
scripts/{measure_chat_rate,simulate_economy}.py, scripts/economy/model.py   (M0, built)
deploy/deploy.sh M5.2a; prune.sh, prune_select.py M5.2b; backup.sh, backup_alert.sh,
    backup units M5.2c; pokewalker-bot.service, *.env.example, restore-rehearsal.md M5.2d;
    build_release.sh M5.2e
tests/test_*.py, tests/fixtures/{pokeapi_mini,content_mini}/
```

## 4. Decisions

### 4.1 Planner choices (numbers the requirements leave to the planner)

- **P1 Routes (D45): 8 routes, weights 0–3.** All 18 types must have weight > 0 on at least one
  route (README.md:181-182); 8 routes named after the device's first eight courses
  (mechanics.md:21-28) give every type ≥ 2 routes while each route favours ≤ 8 types. PokéAPI
  `habitat` covers Gen 1–3 only (README.md:180), so the themes map the nine habitats onto types;
  habitat is a report column in the simulation, never an eligibility input. Weight = max over the
  identity's types (D38). Default route on enrollment: Refreshing Field; switching never rerolls
  queued encounters (adaptation.md:76). Table lives in `content/balance/routes.json` (M0.3):

  | Route | 3 | 2 | 1 |
  |---|---|---|---|
  | Refreshing Field | Normal | Grass, Flying | Bug, Fairy |
  | Noisy Forest | Bug, Grass | Poison | Flying, Ghost |
  | Rugged Road | Rock, Ground | Fighting | Fire, Steel, Dragon |
  | Beautiful Beach | Water | Electric | Flying, Ice, Fairy, Normal |
  | Suburban Area | Electric | Normal, Steel, Psychic, Fairy | Poison, Fighting, Dark |
  | Dim Cave | Ghost | Dark, Rock, Poison | Psychic, Steel, Ground |
  | Blue Lake | Water | Grass, Ice, Dragon | Bug, Fairy |
  | Volcano Path | Fire | Ground, Dragon | Rock, Dark, Psychic, Fighting |

- **P2 Channel configuration (D6):** `/walker-admin channels add|remove|list` (Manage Server, as
  D31 groups Manage Server actions, README.md:89-91), per channel flags `count` and `react`;
  `add`/`remove` take a `reason` and write a `mod_audit` entry in the same transaction (D31,
  README.md:94-96); `list` is read-only. Threads inherit their parent (intents research:62).
  Missing `ADD_REACTIONS`/`READ_MESSAGE_HISTORY` skips the ❗ and keeps the encounter
  (adaptation.md:99).
- **P3 Power-up prices:** research table cp-ivs-leveling.md:155-160 (`[1,10)` 1 Candy/100,
  `[10,20)` 2/250, `[20,30)` 3/500, `[30,40)` 4/1,000 per half level), cap level 40
  (`level_x2` ≤ 80). The simulation (M0.6) checks it; a change is a README update (G-2).
- **P4 Encounter rolls:** level uniform 1–20, IVs 0–15 (cp-ivs-leveling.md:145); starter level 10,
  IVs 10–15 (D42). Frozen at queue time (D53; synthesis.md:24). For Indeedee, Basculegion and
  Oinkologne the artifact carries both gender varieties' own stats and sprite records under the
  species-default identity; tier and route weight use the male default (D53), and the rolled
  variety's payload travels with the encounter.
- **P5 Flee:** 10 % after a failed throw for Common/Uncommon/Rare/Evolved; 0 % for shiny and
  Legendary/Mythical (D38/D47; items-and-catching.md:130).
- **P6 Duplicate window:** normalized-duplicate digest within 30 min across enabled channels,
  in-memory, reset on restart (adaptation.md:34; rate-limits research:46); message-ID dedup is
  persisted (`step_events.message_id` unique). D33 keeps this window (README.md:65).
- **P7 Sprites:** default pixel-art family `sprites/pokemon/{pokemon_id}.png` with `shiny/`,
  `female/`, `shiny/female/` at sprites commit `1b3b7c0a538dd2226ae08d0d2f8955125075bbd4`
  (sprites.md:26, :36). HGSS stops at #493 (sprites.md:43) so it cannot serve the full roster.
  **UNVERIFIED:** whether the pinned PokéAPI commit ships sprite-path CSVs; M0.4 checks and
  otherwise records `sprite_audit: none` (a 404 hotlink shows no image, which D48 allows; what is
  forbidden is substitution). Owner confirms the pin at G-0.
- **P8 Stat conversion:** cp-ivs-leveling.md:21-34 with round-half-up and the D39 fixture; no GO
  overrides (D39). CPM table 1–40 at half levels transcribed from the reference cited at
  cp-ivs-leveling.md:42 into `content/balance/cpm.json` with source and date.
- **P9 Steps storage:** hundredths integers; rolling windows by message time (D20).
- **P10 Dev SQLite:** the startup version check (ADR 0001:39-41) is always on; a logged env
  override `POKEWALKER_ALLOW_UNPATCHED_SQLITE=1` exists for tests and dev only and the systemd
  unit never sets it. CI's SQLite version is unknown; G-5 confirms the host's.
- **P11 Content artifact is committed** (`content/artifact/content.json` ~1 MB, plus manifest) so
  deploys and CI need no network and a re-pin is a reviewable diff (ADR 0001:43-45). The raw CSV
  cache under `build/` is gitignored. Tests use `tests/fixtures/pokeapi_mini/`.
- **P12 Dependencies (G-0):** `discord.py==2.7.1` (ADR 0001:27), `aiosqlite` (exact pin chosen at
  G-0), `regex` (UAX #29 default word boundaries via its `WORD` flag, for D33). Hash-locked
  `requirements.lock`; stdlib only for the importer.
- **P13 Interaction ids:** `pw:v1:<session_id>:<revision>:<action>` (discord-interactions.md:57);
  sessions persisted; the owner check uses the interaction's user, never the id payload.
- **P14 Onboarding selector:** Discord selects hold 25 options, so starter choice is a generation
  select (9) then a starter select (3), then confirm (D34). Sessions are keyed by
  `(guild_id, user_id)` with an optional `profile_id`, so onboarding buttons route through the
  same authorized router before a profile exists.
- **P15 Restrictions:** independent fields `paused`, `paused_until` (`None` while `paused`
  means indefinite, README.md:101), `excluded`, `share_banned`, keyed by `(guild_id, user_id)`
  (D28, README.md:60). Checked on every command entry, in the
  component router, and again inside every mutating transaction; an excluded member gets only
  `/walker-account privacy` and `delete-data` (README.md:103); a paused member still resolves
  encounters (README.md:101). "Unresolved" encounters are `queued` or `revealed`; reopening
  `/walker` shows the oldest unresolved one without rerolling (items-and-catching.md:134).
  Catch, Run and Master Ball each check owner, unresolved state and the expected encounter
  revision inside their transaction and return the persisted result when another action won. **Extension (supervisor ruling, review Round 9):** an excluded member may also
  run `/walker-account opt-out` (a deletion path with the same standing as delete-data) but
  **not** `opt-in` (re-entry); C5 records the extended exception (M4.1). **Marker actions
  (review Rounds 10–11):** delete-data, opt-out, opt-in and reset check authorization,
  fsync the D28 marker and apply it in **one** writer job (M4.1b `run_marker`), so a
  refused invocation leaves no marker; a failure after the append writes a `void`
  record, written inside the job itself (review Round 12). The log is write-ahead,
  with torn-tail repair before each append; startup (M4.1c) folds it per member
  (M4.1a), ignores voided markers and applies the final state without re-checking or
  consulting receipts; the last valid participation marker wins and deletions only
  accumulate.
- **P16 ❗ lifecycle (D3):** `reactions` rows carry `desired` (`add|remove`) and `actual`
  (`none|added`); one idempotent `reconcile_reaction` (M1.4b) runs after each commit on both
  the add side (message credit) and the remove side (opening `/walker`, not opening an
  encounter). `actual` is a hint, not a guarantee: whenever `desired='remove'` the removal is
  attempted regardless of `actual` (deleting an absent own reaction is harmless), so a crash
  between Discord accepting an add and the DB write cannot leave a stale ❗. A successful
  removal retires (deletes) the row, so only pending rows exist and `/walker` and the startup
  sweep make no calls for completed removals; reconciliation is serialized per encounter with
  an in-process lock that re-reads the row after acquiring it, so an in-flight add cannot
  recreate a ❗ after its record is retired. **Amendment (README.md:19 D3, owner edit 54a0cb5,
  merged c3c0de7):** the ❗ goes on **every** message that queues one or more encounters; a
  full queue produces no encounter and no ❗; opening `/walker` still removes all of the
  profile's pending ❗s (walker.py:64-68). Implemented as an M1.5 amendment in `stepping.py`
  (90a467c); no M2–M5 row depends on the old rule.
- **P17 Unacknowledged terminal results:** every terminal transition (`caught`, `fled`, `ran`)
  leaves `encounters.acknowledged_at NULL`; `/walker` and `home` show the oldest unacknowledged
  result first, rebuilt from `pokemon` and `resource_ledger`, and `Done` acknowledges (M1.9).
  This is how a catch that committed before a failed Discord edit reaches a fresh session.

### 4.2 Contracts (new files under `contracts/`, written by the producing row, template :1-22)

| Contract | Boundary | Producer → consumers (all new; grep in §3) | Row |
|---|---|---|---|
| C1 `content-artifact.md` | artifact + manifest schema, counts, pending report | importer → bot loader, simulation | M0.4 |
| C2 `step-rules.md` | D33/D20 as invariants; measurement JSONL input and summary output | `domain/steps.py` → bot, measurement, simulation | M0.5 |
| C3 `persisted-state.md` | schema invariants: profile keys, receipts, ledger, hundredths, queue ≤ 3 | `db/` → services | M1.1 |
| C4 `balance-tables.md` | table files, sums, source/date fields | `content/balance` → domain, simulation | M0.3 |
| C5 `discord-commands.md` | command manifest, permissions, ephemerality, custom_id grammar | `bot/` → Discord, moderators | M1.2 (+ later rows append) |
| C6 `ops-runtime.md` | unit, paths incl. deploy handoff, credentials, exit codes, backup/marker/prune | `deploy/` → host | M5.2c (M5.2a/b/d/e rows feed it) |

### 4.3 Verification decision (Decide before dispatch)

Owner/repo reconciliation: PIPELINE.md:10 `test_cmd` and AGENTS.md:12-25 (RED → GREEN →
applicable checks) do not conflict; no owner exception exists. `lint_cmd: none`. Focused row
coverage = the row's named tests via `python -m unittest discover -s tests -p "test_<module>.py"`
plus `git diff --check`. RED evidence is recorded in the row's commit/PR body
(docs/verification/README.md:3-12). Full `test_cmd` runs only at the two boundaries below.

- **SI-0 (explicit source increment):** rows M0.1–M0.8. Usable outcome: committed content
  artifact + manifest, measurement CLI, simulation report. Audience: owner (G-2 review) and
  reviewer. Reason: owner-ordered pre-work whose results gate application rows
  (README.md:417-420). Checkpoint: independent GO + exact-tree full `test_cmd` at G-2.
- **Final feature:** all rows; checkpoint at G-F. After M5.1 `verify.py` also runs the configured
  checks, so `test_cmd` is heavier from then on; that is intended.

Themes M1–M5 are not increments. Live Discord checks need G-3 and are never a row Accept.

### 4.4 Milestones and briefing

Every milestone is briefed: each impl row M0.1–M5.2e has a ticket file. M0 and M1 are done;
M2–M5 were briefed from this code map and the decisions above after G-3 and revised
through review Rounds 8–12. A row needing a new owner decision or package ends its
batch at a new 🚦.

### 4.5 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` — PIPELINE.md:15; plugin default agrees; no owner feature exception. |
| Candidate | Final accepted v1 feature. One explicit source increment SI-0 (§4.3) for owner review, not for delivery. |
| Action scope and targets | Source integration: PR from the implementation branch to `main` on `origin` = `https://github.com/Farkoal2128/Pokewalker-Discord-Bot.git` (`git remote -v`); feature-branch policy. Release/tag: none. Installation: none. Activation/native trust: none. Application deployment: home host via owner-run script (deploy.check/ship `none`, PIPELINE.md:23-24, :73-76) at G-5. Consumer migration: none. |
| Predicates and workflow | Independent integration GO; exact-tree full `test_cmd` PASS on the final candidate; ancestry on freshly fetched `origin/main`; `--no-ff` integration; CI `framework-verification` green (verify.yml:3-5). |
| Owner authority | **Unresolved** for integration, deployment and any live Discord action; G-F and G-5 ask. Plan-doc publication: G-P below. |

**G-P (pre-build plan publication):** repository `Farkoal2128/Pokewalker-Discord-Bot`, remote
`origin` (above), main target `main`. Allowlist: `docs/features/pokewalker-bot/PLAN.md`,
`docs/features/pokewalker-bot/tickets/*.md`. Push effect: a PR/push runs `framework-verification`
(unittest + verify.py), unaffected by docs. Proposed default: after Codex GO, open a PR from
`docs/pokewalker-bot-plan` to `main`, as the owner's workflow does (README.md:433-446; PRs #7, #8).
The plan author never pushes; explicit owner approval is required. Implementation Home is
proposed as a fresh `feature/pokewalker-bot-v1` from freshly fetched `origin/main`; the owner
confirms or renames it at G-P.

### 4.6 Gate record

Decision maker is `owner` for every 🚦 except G-F's technical predicates (`coordinator`
verifies, `owner` authorizes delivery). Delegated scope per gate is in its brief (§6). Evidence
must be an owner message naming the gate; silence, review GO and headers grant nothing.

## 5. Step table

| Step | Ticket(s) | Kind | Tier | Effort | Status |
|---|---|---|---|---|---|
| 1 | G-P plan approval and docs publication | 🚦 | — | — | ✅ owner approved local build; publication excluded |
| 2 | G-0 ADR 0001 accepted; dependency manifest; sprite pin; Home | 🚦 | — | — | ✅ owner delegated: ADR accepted for build, sprite P7, local branch; pins in requirements.lock |
| 3 | [M0.1](tickets/M0.1.md) PokéAPI fetch at D51 pin, graph, exact filter | impl | seam | M | ✅ done · 6181d23 · GO review_m01 r1 |
| 4 | [M0.2](tickets/M0.2.md) families, depth, tiers, GO-style stats, rewards | impl | seam | M | ✅ done · aed2da0 · GO review_m02 r1 |
| 5 | [M0.3](tickets/M0.3.md) balance tables incl. routes, CPM, milestones | impl | seam | M | ✅ done · fcae1a0 · GO review_m03 r2 |
| 6 | [M0.4](tickets/M0.4.md) gender, sprites, route coverage, manifest, CLI | impl | seam | M | ✅ done · 8a2ee4b · GO review_m04 r1 |
| 7 | [M0.5](tickets/M0.5.md) steps domain (D33/D20) + chat-rate measurement | impl | seam | M | ✅ done · 1f9ca03 · GO review_m05 r2 |
| 8 | G-1 owner supplies chat export; approves anonymised summary | 🚦 | — | — | ✅ owner: no export; use adaptation.md profiles fallback |
| 9 | [M0.6](tickets/M0.6.md) economy model | impl | seam | M | ✅ done · f770763 · GO review_m06 r3 |
| 10 | [M0.7](tickets/M0.7.md) simulation CLI + report | impl | routine | S | ✅ done · fedc34d · GO review_m07 r2 |
| 11 | [M0.8](tickets/M0.8.md) D47 accounting: stockout, unmet ball demand, gym-income comparison | impl | seam | S | ✅ done · a57d3eb · GO review_m08 r1 |
| 12 | G-2 owner reviews report; SI-0 checkpoint | 🚦 | — | — | ✅ owner accepts report as-is; SI-0 review GO and full PASS tree f429c38 |
| 13 | [M1.1](tickets/M1.1.md) DB foundation: WAL, version check, migrations, writer, receipts | impl | seam | M | ✅ done · ae7440d · GO review_m11 r2 |
| 14 | [M1.2](tickets/M1.2.md) bot process: config, token, intents, lifecycle, command sync | impl | seam | M | ✅ done · 7ca3be8 · GO review_m12 r3 |
| 15 | [M1.3](tickets/M1.3.md) encounter + CP + catch domain | impl | seam | M | ✅ done · 391204a · GO review_m13 r1 |
| 16 | [M1.4](tickets/M1.4.md) profiles, restrictions, enrollment txn, channel config | impl | seam | M | ✅ done · 1715840 · GO review_m14 r2 |
| 17 | [M1.4b](tickets/M1.4b.md) ❗ reaction reconcile: crash-safe removal, startup sweep | impl | seam | S | ✅ done · c81ed16 · GO review_m14b r1 |
| 18 | [M1.5](tickets/M1.5.md) step credit pipeline, encounter mint, ❗ request row | impl | seam | L | ✅ done · 5f19b3f · GO review_m15 r1 |
| 19 | [M1.6](tickets/M1.6.md) `/walker` sessions, router, home, onboarding, ❗ removal | impl | seam | L | ✅ done · 891846e · GO review_m16 r1 |
| 20 | [M1.7](tickets/M1.7.md) reveal, reopen, Later, Run, Pokédex seen | impl | seam | M | ✅ done · c54289e · GO review_m17 r1 |
| 21 | [M1.8](tickets/M1.8.md) Throw transaction, Master Ball, rewards | impl | seam | L | ✅ done · b8355e4 · GO review_m18 r1 |
| 22 | [M1.9](tickets/M1.9.md) unacknowledged terminal results, `/walker` recovery, `ack` | impl | seam | S | ✅ done · 8a316b6 · GO review_m19 r1 |
| 23 | G-3 owner: Discord app, token, intents, test-guild install | 🚦 | — | — | ✅ owner 2026-11-04: app + MESSAGE_CONTENT + test-guild install + dev token; live M1 smoke passed (anti-farming rules, onboarding, ❗ add/remove incl. per-message rule, full queue, Throw/berry/Master Ball confirm, Later/reopen, Run + shiny confirm, Done, restart recovery, channel add/react-off/list/remove); fixes e93d049, c3c0de7, 3588028 |
| 24 | [M2.1](tickets/M2.1.md) storage list (text pages) + details view with sprite, favorite (D44, D49) | impl | seam | M | ✅ done · 1fbbcdb · GO review_m21 r1 |
| 25 | [M2.2a](tickets/M2.2a.md) receipt ownership: `action_receipts.profile_id`, `with_receipt(profile_id=)`, cascade (C3; split from M2.2, review-8 #1) | impl | seam | S | ✅ done · 1a802ba · GO review_m22a r1
| 26 | [M2.2](tickets/M2.2.md) send for research: preview/confirm, protections (D30, D41, D42; candy-transfer:123-138) | impl | seam | M | ✅ done · 21d9ba7 · GO review_m22 r2 |
| 27 | [M2.3](tickets/M2.3.md) Candy/Stardust ledger + power-up (P3, D36) | impl | seam | M | ✅ done · da9b9af · GO review_m23 r2 |
| 28 | [M2.4](tickets/M2.4.md) companion: pick/swap, Candy meter 150, `/walker` thumbnail (D14, D25, D30) | impl | seam | M | ✅ done · c2dc39d · GO review_m24 r1 |
| 29 | [M2.5](tickets/M2.5.md) Pokédex list + entry with sprite (D15, D49) | impl | seam | S | ✅ done · 50ca38f · GO review_m25 r1 |
| 30 | [M2.6](tickets/M2.6.md) D59 milestones, reward inbox, Claim (README.md:246-311 acceptance cases) | impl | seam | L | ✅ done · 30836f7 · GO review_m26 r1 |
| 31 | [M3.1](tickets/M3.1.md) bag (250 units), rare pockets, passive finds + frozen meter (D21, D29 overflow rule) | impl | seam | M | ✅ done · 27ce437 · GO review_m31 r1 |
| 32 | [M3.2](tickets/M3.2.md) `/checkin` (D12, D22, D29) | impl | seam | S | ✅ done · 4d549c6 · GO review_m32 r2 |
| 33 | [M3.3](tickets/M3.3.md) item conversion (D61 acceptance case) | impl | seam | M | ✅ done · a5cc720 · GO review_m33 r1 |
| 34 | [M3.4](tickets/M3.4.md) Shiny Lure activation + active effect (shinies-and-lures:72-82) | impl | seam | S | ✅ done · 03f45cf · GO review_m34 r1 |
| 35 | [M3.5](tickets/M3.5.md) route selection screen (P1) | impl | seam | S | ✅ done · 1b871c0 · GO review_m35 r1 |
| 36 | [M4.1a](tickets/M4.1a.md) write-ahead marker log: append, void, per-member fold, first-use creation (D28; split, review-9 #2, review-11 #1) | impl | seam | S | ✅ done · f61c543 · GO review_m41a r2 |
| 37 | [M4.1b](tickets/M4.1b.md) deletion service: `run_marker` (void written inside the job), `apply`, opt-out state (D28; split from M4.1a, review-11 #1, review-12 #2) | impl | seam | M | ✅ done · 52bf510 · GO review_m41b r2 |
| 38 | [M4.1c](tickets/M4.1c.md) startup: marker-log initialization record and replay (D28; split from M4.1b, review-11 #2/#5, review-12 #3) | impl | seam | S | ✅ done · 8902414 · GO review_m41c r1 |
| 39 | G-4 owner approves privacy text (`docs/features/pokewalker-bot/privacy.md`) | 🚦 | — | — | ✅ owner approved revised privacy text 2026-11-04 (deletion path: self-service → server admins via `/walker-admin reset` → bot instance operator) |
| 40 | [M4.1](tickets/M4.1.md) `/walker-account privacy\|opt-out\|opt-in\|delete-data` on M4.1b `run_marker` (D28) | impl | seam | L | ✅ done · 5a1f0ea · GO review_m41 r2 |
| 41 | [M4.2](tickets/M4.2.md) `/walker-mod` status/pause/resume/exclude/include/share-ban/unban/log + audit (D31) | impl | seam | L | ✅ done · 15c116a · GO review_m42 r2 |
| 42 | [M4.3](tickets/M4.3.md) `/walker-admin reset\|sharing` (D31) | impl | seam | M | ✅ done · d186b3c · GO review_m43 r2 |
| 43 | [M4.4](tickets/M4.4.md) share button and embeds, per-minute cap, permission explanation; `after_commit` hook in `Walker.route` (D19, D27, D48; M4.4a withdrawn, review-10 #4) | impl | seam | M | ✅ done · 8b11034 · GO review_m44 r1 |
| 44 | [M4.5a](tickets/M4.5a.md) owner `/admin status\|errors\|restart` exit 75, admin-guild manifest (monitoring-and-admin:58-66; split, review-8 #4/#8/#11) | impl | seam | M | ✅ done · 7fd6f2b · GO review_m45a r2 |
| 45 | [M4.5b](tickets/M4.5b.md) heartbeat with writer-progress probe, readiness marker (monitoring-and-admin:37-39; split, review-8 #12) | impl | seam | S | ✅ done · d37f1ac · GO review_m45b r2 |
| 46 | [M5.1](tickets/M5.1.md) `.project/commands.json` → active; test_framework.py:61-64; PIPELINE.md matrix | impl | seam | S | ✅ done · 6aa490e · GO review_m51 r1 |
| 47 | [M5.2a](tickets/M5.2a.md) `deploy/deploy.sh`: root orchestration, build/check-config identities, first deploy, schema-checked rollback (split, review-8 #14, review-11 #6, review-12 #4, review-13 #2) | impl | seam | M | ✅ done · a5870c1 · GO review_m52a r2 |
| 48 | [M5.2b](tickets/M5.2b.md) `deploy/`: 28-day prune by explicit cutoff, `restic prune` every run (split, review-8 #2/#14, review-10 #5, review-11 #3) | impl | seam | S | ✅ done · 06c664f · GO review_m52b r2 |
| 49 | [M5.2c](tickets/M5.2c.md) `deploy/`: hourly backup to Google Drive (restic/rclone), marker copy, exit precedence, monitor, C6 (split from M5.2b, review-10 #2/#5; owner decision 2026-11-04) | impl | seam | M | ✅ done · 1914074 · GO review_m52c r2 |
| 50 | [M5.2d](tickets/M5.2d.md) `deploy/`: bot unit, env templates, rehearsal doc, handoff path check (split from M5.2a/M5.2c, review-11 #6) | impl | seam | S | ✅ done · 98289ce · GO review r1 |
| 51 | [M5.2e](tickets/M5.2e.md) `deploy/build_release.sh`: unprivileged, token-free venv build in place, `.complete` marker (split from M5.2a, review-12 #4, review-13 #1) | impl | seam | S | ✅ done · 68165ba · GO review r1 |
| 52 | G-5 owner: host bring-up, SQLite/Python versions, restore rehearsal (ADR 0001:80-93), deploy | 🚦 | — | — | ✅ done · files only; host checks deferred |
| 53 | G-F final: independent integration GO, exact-tree full `test_cmd`, delivery authority | 🚦 | — | — | ✅ done · full test_cmd PASS; no integration |

## 6. Briefs

Every impl row (3–7, 9–11, 13–22, 24–38 and 40–51) has its brief in `tickets/<ID>.md`. Gate briefs:

- **G-P:** decision maker `owner`. Scope: approve this plan and the docs-only publication in
  §4.5. Predicates: Codex plan GO; allowlist unchanged since review. Stop if: the owner narrows
  scope (local-only) — then record it here and skip publication.
- **G-0:** decision maker `owner`. Scope: merge ADR 0001 (or amend it); approve P12 pins and the
  P7 sprite pin; confirm the implementation Home branch. Accept: ADR status line reads Accepted;
  `requirements.lock` content named in the approval. Stop if: the owner picks another stack —
  this plan is then withdrawn.
- **G-1:** `owner`. Scope: provide a JSONL message export of the target server (personal data;
  live Discord access needs owner scope, PIPELINE.md:74-76) and approve committing the
  anonymised summary only. Accept: `docs/features/pokewalker-bot/measurements/chat-rate-summary.md`
  with no member ids. Stop if: no export — M0.7 runs on the adaptation.md:53-58 profiles and
  says so in the report.
- **G-2:** `owner` + `coordinator`. Scope: read `docs/features/pokewalker-bot/economy-report.md`;
  any changed number is a README edit by the owner before M1 starts; the Legendary-pacing
  figures are reported, not decided. Technical predicates: SI-0 independent GO and
  `Tests: tree <sha> <test_cmd> PASS` on the M0.8 candidate.
- **G-3:** `owner`. Scope: create the Discord application, enable `MESSAGE_CONTENT`, install the
  bot in a test guild, place the token in the dev credentials path. No row depends on it for
  Accept; manual smoke of M1 happens here. Stop if: intent not granted — fallback is a non-goal.
- **G-4:** `owner`. Scope: approve the privacy text (what is processed, retained, 28-day backup
  expiry, deletion path; intents research:52-54, D28). M4.1 embeds it.
- **G-5:** `owner`. Scope: host inventory, Python ≥ 3.12 and SQLite ≥ 3.51.3 (or backports)
  confirmed by `python3 -c "import sqlite3,sys;print(sys.version, sqlite3.sqlite_version)"` on
  the host; restore rehearsal with the two D28 marker cases, interrupted deletion and byte-absence
  check (ADR 0001:84-91); owner-run deploy. Nothing here is automated by the pipeline.
- **G-F:** `coordinator` verifies predicates in §4.5; `owner` authorizes main integration and any
  publication. Accept: receipt line and merge SHA recorded in this cell.

## Review responses

- **Round 1** ([review-1.md](review-1.md), MUST 7 / SHOULD 4): all 11 fixed in place, none
  rejected. 1 → P14 + M1.6 (sessions keyed by guild/user, profile attached at confirm);
  2 → P15 + M1.7 (oldest `queued|revealed`, M1.4 `queue_size` is the one occupancy definition);
  3 → P15 + M1.4/M1.6/M1.7/M1.8 (restriction checks at entry, in the router and inside
  transactions); 4 → M1.4 (independent flags); 5 → M1.7/M1.8 (owner, unresolved state and
  expected revision inside Run/Throw; persisted result returned); 6 → P16 + M1.5/M1.6
  (removal on `/walker` open; desired/actual reconcile); 7 → M0.3/M0.4 (every D59 category,
  five extra-bundle lines, 340/824 and Phione/Manaphy assertions); 8 → M0.6/M0.7 (continuous
  vs hourly-check styles, D47 uses continuous); 9 → M1.5 (companion meter only with a
  companion); 10 → M0.5 (299 + 4 words → 175); 11 → M0.6 (offline run with locked deps,
  shared `steps.py` kept).
- **Round 2** ([review-2.md](review-2.md), MUST 4 / SHOULD 1): all 5 fixed, none rejected.
  1 → P15 + M1.4 (`paused` flag; `paused_until=None` means indefinite while paused; expiry
  and resume tests); 2 → P17 + new row M1.9 (`acknowledged_at`, recovery screen through the
  fresh-session router; M1.1 column, M1.6 entry hook, M1.8 `Done` → `ack`) — split out as a
  row because M1.6/M1.8 sit at the ticket size bound; 3 → P2 + M1.4 (`reason` on `channels
  add|remove`, policy row + `mod_audit` in one transaction, `list` unaudited); 4 → P4 +
  M0.1/M0.2/M0.4/M1.3/M1.7 (both D53 varieties carry their own stats and sprites in the
  artifact; the rolled variety's payload travels with the encounter; forced-female test
  through import, generation and rendering); 5 → M0.3 (`gym_income_table.json`, D23/D24) +
  M0.6/M0.7 (analytic gym-ball comparison under two labelled holding assumptions, reported
  next to the shortfall for G-2).
- **Round 3** ([review-3.md](review-3.md), SHOULD 1 / NIT 1; owner asked for both): both fixed,
  none rejected. 1 → new row M0.8 (split out because M0.6 sits near the size bound): stockout
  behaviour (no balls → no spend; virtual throws resolve the encounter so slots are not
  stuck), `unmet_ball_demand` reported as a labelled estimate separately from `balls_spent`,
  a deterministic insufficient-supply test with a positive deficit and nonnegative inventory;
  the gym-income comparison moved there from M0.6/M0.7 so both halves of D47 sit in one row.
  2 → M0.3 file count corrected to 12.
- **Round 4** ([review-4.md](review-4.md), SHOULD 1; owner asked for the fix): fixed, none
  rejected. 1 → M0.8: a virtual throw exempts only the missing ball from consumption; a
  selected berry is consumed from stock as on a real throw, and later attempts use no berry
  once stock is gone; new deterministic test (zero balls, one Razz Berry, failed virtual
  throw → next attempt has no berry). M0.6 unchanged (its throw policy was not the defect).
- **Round 5** ([review-5.md](review-5.md), MUST 1): fixed, none rejected. 1 → P16 + new row
  M1.4b (split out because M1.5 sits at the size bound): `reconcile_reaction` moves to
  `services/reactions.py`; removal is attempted whenever `desired='remove'` regardless of
  `actual` (404 counts as removed); a startup sweep repairs rows left mid-flight; test
  `test_crash_after_discord_add_before_db_write_then_walker_open_clears`. M1.5 now only writes
  the request row and calls the reconciler after commit; M1.1 schema unchanged.
- **Round 6** ([review-6.md](review-6.md), SHOULD 1; owner asked for the fix): fixed, none
  rejected. 1 → P16 + M1.4b: a successful removal (incl. 404) retires the row by deleting it;
  `/walker` (M1.6) and the startup sweep touch only remaining rows; `reconcile_reaction` holds
  a per-encounter in-process lock and re-reads the row after acquiring it, so an in-flight add
  cannot recreate the ❗ after retirement; new tests for zero calls on a second `/walker` and
  on startup, for the delete-then-crash retry, and for the lock; the crash and delayed-add
  tests are kept. M1.1 schema unchanged.
- **Round 7 (NIT) — crash test asserted a deleted row's field:** fixed. M1.4b's crash test now
  asserts the fake shows no reaction and the reaction row is gone.
- **Round 8** ([review-8.md](review-8.md), MUST 8 / SHOULD 6 / NIT 1): all 15 fixed, none
  rejected. 1 → new row M2.2a (split from M2.2): `action_receipts.profile_id` with cascade,
  `with_receipt(profile_id=)`, Run/Throw/enroll receipts owned; M4.1 deletion relies on the
  cascade and tests the ledger-less Run receipt and its bytes. 2 → M5.2b: prune by an explicit
  now−28 d cutoff (`prune_select.py` over `restic snapshots --json`, then `restic forget <ids>
  --prune`; local files by the same cutoff); tests for stale-only repositories, unique paths and
  the boundary with failed uploads. 3 → M4.4: `Walker.route` gains an `after_commit` hook
  awaited outside the writer job (C5 appended); real-router tests that rollback sends nothing
  and a slow send does not hold the writer. 4 → M4.5a: `scope_commands(guild)` = global +
  guild-only, `sync_commands` always copies global commands, `/admin` registered only to
  `POKEWALKER_ADMIN_GUILD_ID`, never global; sync-path test with both kinds. 5 → M2.2: one
  `protected_reason` predicate with `legendary_or_mythical = is_legendary or is_mythical` for
  candidates, transaction and single-send warning; non-shiny Mythical test. 6 → M3.1/M2.6:
  `items.grant` restricted to finds and `/checkin`; Claim never converts or drops; regression
  test. 7 → M4.3/M4.1: markers carry `kind`, actor and reason; `apply_marker` runs under receipt
  `reset:<profile_id>` whose compute inserts the audit and deletes the profile, so normal
  execution and startup replay are one idempotent operation; exactly-one-audit test. 8 → M4.5a:
  `authorize` rechecks guild exclusion on every subcommand and the restart confirmation. 9 →
  M2.2: `Send for research` button on the storage page; two-page navigation test. 10 → M4.4:
  Share rendered only for caught/owned, unbanned, sharing-on; never for fled/ran; ban/unban
  tests; in-transaction recheck kept. 11 → M4.5a: durable cooldown via `restart:<now>` receipts;
  fresh-instance test. 12 → M4.5b (split): success ping only after a bounded writer progress
  probe; stalled-writer test. 13 → M5.1: new offline `tests/test_content_integrity.py` (hash,
  schema, counts, routability, balance hashes) is the `contract` check; coverage wording
  corrected. 14 → M5.2 split into M5.2a (unit, env, deploy script with readiness wait on M4.5b's
  ready file, rollback, explicit `--restore-db`) and M5.2b (backup/prune/marker/rehearsal/C6),
  both with offline behavioural tests over fake commands on `PATH`. 15 → M2.4 cites README.md:37
  for D14; M5.1 no longer attributes a `&&` prohibition to PIPELINE.md:30-31. Owner decisions
  2026-11-04 folded: opt-out = deletion through the same path plus a minimal
  `(guild_id,user_id)` marker and `/walker-account opt-in` (M4.1; Stop-if removed, G-4 kept);
  off-machine backups = Google Drive via restic's rclone backend with `--drive-use-trash=false`
  as an Accept check and no new Python packages (M5.2b; the owner's `--keep-within 28d` is
  realised as the explicit cutoff because `--keep-within` is relative to the latest snapshot,
  review-8 #2 — the timer, 28 days and `--prune` stand); row splits approved. ❗ amendment
  recorded in P16 from README.md:19 D3 (owner edit 54a0cb5, merged c3c0de7; implemented in
  `stepping.py` by 90a467c); no M2–M5 ticket restates the old rule (grep `❗|non-empty` over
  `tickets/M[2-5]*.md`), so none changed. Steps 25–47 renumbered for the three added rows.
- **Round 9** ([review-9.md](review-9.md), MUST 4 / SHOULD 3 / NIT 1): all 8 fixed, none
  rejected. 1 → M2.2a: migration `0003_receipt_owner.sql` backfills `profile_id` for existing
  receipts by ledger line, by encounter (`throw:`/`run:` keys) and by enrollment key; receipts
  still unattributable afterwards are residue of already-deleted profiles and are deleted, any
  other action name aborts the migration; test upgrades a populated 0001–0002 database, deletes
  and replays. 2 → new row M4.1a (split from M4.1): every marker carries a `marker_id`; opt-in
  is itself a marker; `apply_marker` keys receipts `<kind>:<marker_id>`; startup replay applies
  the newest log **in order**, so a restored database predating an opt-out/opt-in pair ends
  opted in and an opt-out without a profile survives restore; both restore scenarios are named
  tests. 3 → P15 extension recorded (supervisor ruling): excluded members may run `opt-out`
  (deletion path, same standing as delete-data) but not `opt-in`; M4.1 checks exclusion per
  subcommand, appends the extended exception to C5, and tests both excluded invocations. 4 →
  M5.2b: backups get their own dead-man monitor (`BACKUP_MONITOR_URL`, required): success ping
  only after snapshot, marker copy, upload and prune all succeed; `OnFailure=` unit pings the
  fail endpoint with a stage word; exit codes 1/2/3 by stage; offline tests with fake `curl`. 5
  → M5.2a: backup exit 1 after stop restarts the unchanged previous release (exit 40); exit 2/3
  warns and continues on the verified local snapshot; both branches tested. 6 → M4.5b: the
  health loop and the ready file always run; only the remote ping needs a URL; no-URL readiness
  test. 7 → new row M4.4a (split from M4.4): the router (`route`, `refuse`, `CUSTOM_ID`, session
  lock) moves to `bot/router.py` with no behaviour change and no test edits; M4.4's hook lands
  in `router.py`, keeping its two-file scope. 8 → M5.1 PIPELINE wording: the commands do not
  establish live Discord acceptance; G-3's smoke evidence (PLAN row 23) is recorded separately.
  M4.3 now uses `reset:<marker_id>`. Steps 36–49 renumbered for the two added rows.
- **Round 10** ([review-10.md](review-10.md), MUST 2 / SHOULD 4): all 6 fixed, none
  rejected; four were REPEATs, so each fix removes the cause. 1 (REPEAT) → P15 +
  M4.1a/M4.1/M4.3. Cause: the marker was fsynced *before* the writer job that checks
  authorization, so a refused opt-in left a replayable intent. `run_marker` now checks,
  fsyncs and applies in **one** serialized writer job (db/__init__.py:105-111, the
  admin_channels.py:42-44 recheck pattern). A refusal writes no marker, and replay
  applies logged markers without re-authorizing; re-checking against a restored DB would
  re-decide past choices. Tests: `test_run_marker_refusal_appends_nothing_changes_nothing`
  (M4.1a), `test_queued_exclusion_then_opt_in_refused_no_marker_replay_keeps_opted_out`
  (M4.1), and `test_actor_excluded_while_reset_queued_writes_no_marker` (M4.3, the same
  race on reset). 2 (REPEAT) → M5.2c + M5.2a: `backup.sh` exits with the **first failed
  stage**. Snapshot = 1 and dominates upload and prune; a failed marker-log copy is a
  snapshot failure and deletes both partials. Prune always runs, every failed stage is
  logged, and the alert sends the dominant stage. `deploy.sh` continues only on 0/2/3,
  so 1 or any other status means no snapshot: restart the previous release, exit 40.
  Tests: `test_snapshot_and_prune_failure_exit_1_prune_attempted_both_logged`, and the
  boundary test `test_deploy_with_real_backup_snapshot_and_prune_failure_exit_40` (real
  `backup.sh` under M5.2a's harness). 3 → M2.4 names
  `test_companion_meter_only_with_companion_keeps_partial` (test_stepping.py:99-106) as
  intentionally updated (D25, AGENTS.md:29-32). Its freeze assertion stays; :106's 15,300
  becomes meter 300 + 1 Candy + one ledger line. 4 (REPEAT) → cause: the seam bound
  (feature-pipeline `skills/plan/plan-structure.md:22`, "≤300 production lines and ≤2
  production files") limits a row's change, not a file's length. M4.4a's
  `walker.py ≤ 300` Accept therefore had no basis, so M4.4a is **withdrawn** (ticket
  removed, row dropped). M4.4 adds `after_commit` in `Walker.route` (walker.py:122-127):
  `share.py` + `walker.py`, 2 production files. 5 (REPEAT) → M5.2b split again: M5.2b =
  prune (`prune_select.py`, `prune.sh`; exit 0/1, local then remote, both always tried)
  and new M5.2c = backup (`backup.sh`, `backup_alert.sh`). Each row has 2 production
  scripts. Unit, env, doc and contract files count as configuration/docs, as M5.2a now
  states. Every ticket is ≤ 4,096 bytes (`wc -c tickets/*.md`), including trimmed M2.2a,
  M4.4, M5.1 and M5.2a. 6 → M5.1 Accept/Verify are focused: the content-integrity and
  framework suites + `git diff --check`. Active-mode `verify.py`, which runs the whole
  unit suite, and full `test_cmd` stay at G-F (§4.3). Rows: M4.4a removed, M5.2c added;
  steps 41–47 renumbered (G-5 = 48, G-F = 49 unchanged).
- **Round 11** ([review-11.md](review-11.md), MUST 3 / SHOULD 3 / NIT 2): all 8 fixed,
  none rejected. 1 (REPEAT, third round on the marker log) → **supervisor ruling: fix the
  model.** M4.1a is split into M4.1a (log) and M4.1b (deletion service), and P15 is
  updated. The log is write-ahead. `run_marker` appends `void <marker_id>` before
  re-raising any compute or commit failure after the append; the writer rolls back and
  keeps serving jobs (db/__init__.py:105-141). Replay folds the log per member in order
  and ignores voided markers. It applies only the final state, independent of receipts:
  the last valid opt-out/opt-in wins, and deletions only accumulate. Receipts now only
  dedupe the reset audit. Tests:
  `test_failed_opt_out_then_successful_opt_in_replay_ends_opted_in_profile_kept`, and
  `test_crash_between_append_and_commit_replay_applies_it` (no void: deletion-safe, as
  intended), plus their fold-level twins in M4.1a. 2 → M4.3 trims the reason and refuses
  a blank one before any marker (admin_channels.py:38-41; the CHECK is at
  0001_core.sql:44): `test_whitespace_reason_refused_no_marker_no_change_next_startup_ok`.
  In M4.1b, a reset audit refused by a constraint at replay is logged and skipped. Its
  deletion still applies, and startup never fails forever. 3 (REPEAT) → M5.2b: `restic
  forget <ids>` only when ids exist, then `restic prune` on every run, and prune success
  is the completion criterion. Test:
  `test_forget_ok_prune_fails_exit_1_then_rerun_without_stale_ids_prunes_exit_0`. The
  owner's forget+prune timer stands. 4 → M2.2a names test_db.py:75 and :88 as
  intentional updates (AGENTS.md:29-32). They now derive the supported version from the
  migration count (db/__init__.py:33-40) and use it and +1, so later migrations need no
  test_db.py edit. 5 → M4.1b: first startup creates and fsyncs an empty log and records
  `marker_log_init`. A missing log after initialization refuses startup, because
  recovery metadata was lost. In M5.2c a missing log is a snapshot failure, and an empty
  log backs up with exit 0. 6 → M5.2a: an explicit operator handoff. `check-config` and
  the backup run under `env -i` with only their unit's `runtime.env` + credentials
  directory, or `backup.env` + state directory. The ready file is
  `/run/pokewalker/ready`, and `backup.sh` takes a `flock`. Tests: a clean-environment
  test, and M5.2d's unit-path equality tests. The unit, env templates and rehearsal doc
  moved to the new row M5.2d to keep M5.2a/M5.2c within 4 KB. 7 → §3.3, §4.2 (C6 →
  M5.2c), §4.4 and §6 reconciled with the ticket files. 8 → M3.4 cites
  test_stepping.py:162; M2.2a cites walker.py:344. Rows: M4.1b and M5.2d added; steps
  37–51 renumbered (G-4 = 38, G-5 = 50, G-F = 51).
- **Round 12** ([review-12.md](review-12.md), MUST 2 / SHOULD 2): all 4 fixed per the
  supervisor's minimal rulings, none rejected. 1 → M4.1a: before each append, a log
  whose last byte is not a newline is truncated to just after its last newline, fsynced,
  and the repair logged. Such a tail never completed its fsync, so it was never applied.
  `fold` skips only an unparseable **final** line; a bad earlier record refuses startup.
  Test: `test_torn_tail_repaired_then_marker_and_void_survive_fold`. 2 (REPEAT) → M4.1b:
  the void is written by the job itself (`except BaseException`, synchronous
  `append_void`) before the writer rolls back, never by the caller. A cancelled waiter
  leaves its job to commit or void itself (test_db.py:210-225); writer abort cancels the
  job at an await (db/__init__.py:90-103). A failure inside the writer's own commit is
  the Round 11 crash case. Tests:
  - `test_cancelled_waiter_then_job_rollback_still_voids`
  - `test_cancelled_waiter_then_commit_writes_no_void_and_applies`
  - `test_writer_abort_mid_job_voids`
  3 (REPEAT) → new row M4.1c. Every startup records `marker_log_init` when the log
  exists and the row is missing, and refuses only when the row exists and the log is
  missing. Tests:
  `test_crash_between_create_and_record_then_startup_records_then_log_loss_refuses`
  and `test_old_db_beside_newer_log_records_init_then_log_loss_refuses`. 4 → new row
  M5.2e `build_release.sh` refuses root and credential variables and builds venv + `pip
  --require-hashes` into a `.partial` release. M5.2a runs it through `runuser -u
  pokewalker-deploy -- env -i …` and runs `check-config` as the bot user via `systemd-run`
  with the unit's properties (exit status UNVERIFIED until G-5). Root does only unit
  install, `systemctl`, the `current` switch and `backup.sh`, which runs as root exactly
  as its unit does. First deploy is defined: with no release link and no DB, there is no
  stop, backup or rollback; with exactly one of them present, deploy exits 10. Tests:
  `test_build_as_deploy_user_clean_env_no_credentials` and
  `test_first_deploy_skips_stop_backup_and_rollback`. M5.2d adds `User=pokewalker` and
  the two users to the rehearsal doc. Rows: M4.1c and M5.2e added; steps 38–53
  renumbered (G-4 = 39, G-5 = 52, G-F = 53).
- **Round 13** ([review-13.md](review-13.md), SHOULD 2): both fixed per the supervisor's
  minimal rulings, none rejected. 1 → M5.2e builds the venv **in place** at
  `releases/<sha>/` (deploy-and-security.md:53) and writes a fsynced `.complete` marker
  last; a directory without the marker is deleted and rebuilt, and nothing is renamed.
  M5.2a never uses a release without the marker. Tests:
  `test_venv_created_at_final_path_marker_written_last`,
  `test_complete_release_reused_incomplete_one_deleted_and_rebuilt` and M5.2a's
  `test_incomplete_release_never_used`. 2 → M5.2a's rollback first stops the service,
  then compares the DB's `PRAGMA user_version` with the previous release's migration
  count (db/__init__.py:33-40). If compatible, it rolls back (exit 20). If the DB is
  newer, it never starts the old release: it stays stopped, prints this run's snapshot
  path and exits 50, so restoring the DB still needs an explicit `--restore-db`. Test:
  `test_migration_then_readiness_failure_newer_schema_stays_stopped_exit_50`. C6 gains
  deploy exit 50 (M5.2c). No rows added.
- **Build-time ruling (supervisor, 2026-11-04):** M2.1 wiring allowance raised from ≤ 4 to
  ≤ 20 lines in `walker.py`/`screens.py` (still inside the 300-line seam bound); the builder
  found registration, two identity lookups, home availability and the storage-full button
  need ~8+ lines. Other tickets that cap wiring lines may be raised the same way on request.
- **Build-time ruling (supervisor, 2026-11-04), M2.2:** `test_confirm_twice_and_restart_before_reply_one_credit`
  means exactly one credit, not that a stale click returns the saved receipt. A second confirm
  on a stale session revision gets the M1.6 router's normal stale/reopen reply (no handler
  call, no write); reopening `/walker` → storage shows the Pokémon gone and its Candy credited.
  Same-revision duplicates still return the receipt. Research toggles and picks identify a
  Pokémon by `pokemon_uid` (+ revision), never by page position.
- **Build-time ruling (supervisor, 2026-11-04), M4.1a:** every unterminated final tail is
  uncommitted, in `fold` **and** before append, even if it parses as JSON (append writes and
  fsyncs the record with its newline, so a record without one was never acknowledged).
  Regressions: complete marker JSON and complete void JSON without a newline are both ignored
  by fold and truncated by the next append.
- **Owner decision 2026-11-04, Shiny Lure (amends built M3.4):** a Lure applies 4× odds to the
  player's next **10 generated encounters**, not 1 hour. Persisted counter decremented in the
  stepping transaction per minted encounter; ends at 0; restart-safe; one active, re-activation
  refused without consuming, one held + one active unchanged. `catch.json`
  `lure_duration_seconds: 3600` → `lure_encounters: 10` (C4, test_balance_tables.py).
