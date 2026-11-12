# Plan: pokemon-trading — player-to-player Pokémon trading (`/trade`)

**Status:** awaiting plan approval
**Review:** none yet — drafted 2026-11-12 at 02d89af; independent plan review pending
**Home:** none assigned — proposed `feature/pokemon-trading · none`, cut from `docs/pokemon-trading-plan` (owner decision at G-A). Planning docs: local branch `docs/pokemon-trading-plan`.
**Inputs:** owner requirement (§2, relayed 2026-11-12) · owner decision OD1 (2026-11-12) · [requirements D1–D61](../pokewalker-bot/README.md) (owner-only) · [v1.1/v2 plan](../pokewalker-v1.1-v2/PLAN.md) (conventions) · [PIPELINE.md](../../../PIPELINE.md)

## 0. Open questions for the owner (answer at G-A)

Rows are briefed on the **default**. Any other answer re-briefs the named rows before build.

| Q | Choice | Default the rows assume | Other answers change |
|---|---|---|---|
| Q1 | 1-for-1, up to N per side, or gifts (1-for-0) | 1-for-1, no gifts | T1 offers table; P14 capacity check live (`storage_full`); T2–T4 |
| Q2 | Cost: none, flat Stardust per side, or by rarity | none | new T0 `content/balance/trade.json` + C4 + manifest rebuild; T3 debits with `trade_fee` ledger lines |
| Q3 | Limits: one open trade per member only, or also a daily cap/cooldown | one open trade | T0 value; T3 counts completed trades in a rolling 24 h (`trades.ended_at`) |
| Q4 | Receiver's Pokédex: none, seen, or seen+caught (milestones) | none — D15 (README.md:38) lists catch, starter and evolution only | owner amends D15/D59; T3 adds the evolution.py:88-91 upsert + `check_and_award` |
| Q5 | Shiny, Legendary/Mythical, starter-origin | tradable, with a "special trade" warning line | refuse with reason `special` (T2/T3) |
| Q6 | Partner notice | none: the partner runs `/trade` | new T6 (seam): one public message pinging only the partner, with a send-permission check (pattern bot/share.py) |
| Q7 | Offer lifetime | 15 min from creation (= session, walker.py:83) | constant in T2 |

**Decided — OD1 (owner, 2026-11-12, relayed by the coordinator):** trading is its own top-level slash command `/trade`. It is not a button, sub-screen or option of `/walker` or any other command.

## 1. Outcome and scope

Two enrolled members of one server each offer one eligible Pokémon in `/trade` and both confirm what they saw; the swap commits in one writer transaction. Favorited, gym-deployed and companion Pokémon never change owner. This is checked at offer, re-checked at execution, and enforced by SQL triggers.

**Non-goals:** cross-server trades; trading items, Candy or Stardust; trade history or mod tools; trade-triggered evolution (D40 makes trade conditions Candy-only, README.md:152); DMs; public trade boards; edits to the research, gym, evolution, power-up or storage services (P3); publication and deployment (§4.5).

## 2. Requirements

README lists trading as "Later" (README.md:80) and is owner-only, so this section is the requirement until the owner adds a D-number. That edit is not a row action.

- **R0 (owner, verbatim intent):** "a trading feature between users so they can trade their pokemon. Make sure it doesn't allow for favorited, pokemon in gyms, or companion pokemon to be traded."
- **R1–R3:** a Pokémon is not tradable if `favorite=1` (0001_core.sql:116), if `gym_deployment_id IS NOT NULL` (0014_gyms.sql:45), or if it is its owner's `profiles.companion_uid` (0001_core.sql:18).
- **R4:** R1–R3 are checked at offer and atomically re-checked at execution.
- **R5:** both profiles are in the same server.
- **R6:** all-or-nothing swap.
- **R7:** each side confirms exactly the offers it saw.
- **R8:** only the two participants can act.
- **R9:** offers expire.
- **R10:** OD1.

## 3. Verified code map — verified at 02d89af

**Grep evidence:**
- `rg -ni trade pokewalker/` → none.
- `rg -n "UPDATE pokemon" pokewalker/` → 6 writers, none setting `profile_id`, each bumping `revision`: storage.py:46 (favorite), gyms.py:86 (deploy), gyms.py:152 (recall), research.py:71 (send), evolution.py:78, powerup.py:66.
- `rg -n "SET companion_uid" pokewalker/` → profiles.py:144 and bot/storage.py:214, neither bumping the Pokémon revision.
- `rg -n "DELETE FROM pokemon" pokewalker/` → none (Pokémon go only via the profile cascade, 0001_core.sql:106).
- `grep -n "FROM pokemon\|UPDATE pokemon\|INTO pokemon" pokewalker/services/raids.py` → none, so raids lock no owned Pokémon.
- `limits()` is content/balance/__init__.py:31-33, imported at items.py:5.

| Anchor | Fact | Used by |
|---|---|---|
| 0001_core.sql:13-27 (:26), :104-121, :150-174 | profile unique per (guild,user); pokemon owner/favorite/state/revision; receipts, ledger, sessions | P1, T1 |
| 0014_gyms.sql:10, :16, :24, :45-51 | `profiles_guild_key`; deployment cascades with its Pokémon; composite guild FK; guard triggers (state/level/species — **not** `profile_id`) | T1 |
| 0012_capacity.sql:1-2; catching.py:72-76; walker.py:300-317 | `storage_limit` enforced at throw/Done, not in SQL | P14 |
| db/__init__.py:34-41, :110-116, :158-176 | contiguous migrations (next **0018**); one job per `BEGIN IMMEDIATE`; `with_receipt` | T1, T3 |
| services/storage.py:6-50; research.py:10-18; bot/research.py:55-92 | identify, paging, profile-scoped `detail`, `set_favorite`; `protected_reason`; picker with reasons | T2–T4 |
| services/profiles.py:58-95, :140-144 | profile/restrictions/`session_owner`; starter inserted favorite + companion | T2, P2 |
| services/gyms.py:15-17, :49-93, :243-250; evolution.py:49-94 (:88-91) | writer guard; session/receipt/stale pattern; battle re-checks its party in-job; Pokédex upsert + `check_and_award` | T2, T3 |
| milestones.py:95-108; 0004_milestones.sql:1-6; catching.py:116-134 | milestones one-time per profile from pokedex `caught_at`; catch rewards paid once at the throw | P7, P8 |
| services/deletion.py:125-131 | delete, reset and opt-out run `DELETE FROM profiles` → cascade | P10 |
| bot/walker.py:27-29, :43, :50-65, :114-157, :216-231, :282-298, :421 | ID grammar, REOPEN; `clock=time.time`; handlers; router (owner check :129-131); pending catch; recovery; `pending` flag | T4, P2 |
| bot/raid.py:15-74; bot/storage.py:178-188, :207-216 | top-level command → Walker session (:30-36); select on shown page; Set companion | T4, T5 |
| bot/client.py:87-94, :148-156, :267-281; deploy/deploy.sh:165-174; README.md:209-222 | registration; sweep; manifest hash; a manifest change prints `sync-commands --global --yes` | T5, G-F |
| content/help.md; tests/test_readme.py:17-20; client.py:43 | help hash-pinned, ≤ 4,096 UTF-16 (3,845 now, `python3` count 2026-11-12) | T5 |
| tests/test_receipt_owner.py:46-95; test_gyms.py:20-57; test_walker_router.py:39-64; test_deletion.py:256-284 | legacy-schema rebuild; harnesses | tests |

**Do-not-touch:**
- services `research`, `gyms`, `evolution`, `powerup`, `storage`, `catching`, `milestones`, `deletion`, `profiles`, `capacity`, `items`.
- bot `storage`, `screens`, `research`, `gyms`, `raid`.
- migrations 0001–0017, which are immutable (C3 :116-119).
- `content/balance/*.json` and the manifest (except T0).
- `docs/features/pokewalker-bot/**` (owner-only).
- `deploy/**`, `scripts/**`, `.github/**`.

**New files:** `db/migrations/0018_trades.sql`, `services/trading.py`, `bot/trade.py`, and tests `test_trading_schema.py`, `test_trading.py`, `test_trade_screens.py`, `test_trade_command.py`.

## 4. Decisions

### 4.1 Planner decisions

- **P1 Same server.**
  - A profile is a (guild,user) pair (0001_core.sql:15-16, :26), and every Pokémon has one profile (:106).
  - Composite FKs to `profiles(profile_id,guild_id)` bind both sides to the trade's guild (0014_gyms.sql:10, :24).
  - The owner-change trigger also requires the old and new owner to share a guild.
- **P2 Eligibility.** Offer and execution use one ordered rule, `tradable_reason`:
  - `not_owned`: not `owned`, or another owner. This covers `sent` Pokémon; pending catches are encounters, not Pokémon rows (walker.py:216-231).
  - `deployed` (R2), `favorite` (R1), `companion` (R3).
  - `unacknowledged_catch`: the source encounter is unacknowledged. Otherwise the giver's recovery would read it as `pending` (walker.py:282-298, :421). Live count, unverified: `sqlite3 <db> "SELECT count(*) FROM pokemon p JOIN encounters e ON e.encounter_id=p.source_encounter_id WHERE p.state='owned' AND e.acknowledged_at IS NULL"`.
  - The starter starts favorited and as companion (profiles.py:141-144), so it needs no extra rule; Q5 covers starters, shinies and Legendary/Mythical.
  - Raids and battle parties hold no lock (§3 grep; gyms.py:243-250).
- **P3 No mutation-side locks.** An offer pins `(uid, revision)`. Every Pokémon writer bumps the revision, so execution refuses a changed Pokémon. Set companion does not bump it, so execution checks companion explicitly. The do-not-touch services stay unchanged.
- **P4 Atomic execution.**
  - All checks and both owner updates run in the second confirmer's single writer job, on the only write connection (C3 :67, :71-75).
  - Each `UPDATE` restates the predicate and must change exactly one row, otherwise the job rolls back.
  - The 0018 triggers back R1–R3 and R5 on every owner change and every offer row.
- **P5 Handshake.**
  - Every offer change bumps the trade `revision`, which voids both confirmations.
  - A screen carries the revision it rendered. Offer and Confirm refuse `changed` when it differs, which gives R7.
  - The trade executes when both confirmations equal the current revision.
  - Double-accept: the Writer serializes jobs (db/__init__.py:110-116), so the second job sees `completed`, or replays receipt `trade:<trade_id>`.
- **P6 Open trades and expiry.** One open trade per member, enforced by a partial unique index. Expiry is lazy (on touch), so the sweep (client.py:148-156) is untouched. Lifetime is Q7.
- **P7 Closed economy.** Trades move no Candy, Stardust or items and never evolve a Pokémon.
  - Catch rewards are paid once at the throw (catching.py:120-134). Research Candy is paid once, because `sent` is terminal (research.py:71).
  - A Pokémon therefore yields its value exactly once however often it is traded, and ping-pong creates nothing. A trade reward would be the only farmable source.
- **P8 Pokédex.** By default (Q4), receiving changes nothing. Milestones are one-time per profile (0004_milestones.sql:1-6). Evolving a received Pokémon registers its target under D15 (evolution.py:88-91), paid with the receiver's own Candy; this is accepted.
- **P9 Receipt.** `trade:<trade_id>`, action `trade`, owned by the executor. The result holds only status, trade_id and the two UIDs, with no user or profile IDs and no ledger lines at the defaults.
- **P10 Deletion.**
  - Deleting either profile cascades the trade and both sides. A given Pokémon stays with its receiver, with `source_encounter_id` set to NULL (0001_core.sql:115).
  - The giver's ended deployment rows reference the traded UID and cascade if the receiver is later deleted (0014_gyms.sql:16, :33). This is benign: inbox labels fall back (test_milestones.py:426).
  - Privacy text needs an owner edit (G-F).
- **P11 UX (OD1).**
  - `/trade [member]` opens a private ephemeral screen on the presser's own Walker session (pattern raid.py:30-36).
  - Buttons use the shared `pw:v1:` router (C5 :122), which limits presses to the session's user (walker.py:129-131). The service also refuses non-participants.
  - No `/walker` screen links to trading, and stale `trade_*` presses say "reopen /trade".
  - A Refresh button exists because one member's action cannot update the other's ephemeral screen.
- **P12 Restrictions.** An excluded member cannot open, offer or confirm, and an excluded partner blocks execution. Paused members may trade, because pause only stops earning (stepping.py:105, items.py:115).
- **P13 Membership.** There is no members intent (C5 :125). `/trade` checks the resolved `member` option once and refuses bots and self.
- **P14 Capacity.** A 1-for-1 swap never changes an owned count, so there is no storage check and full members may trade. Q1 alternatives add a check (post-count ≤ `storage_limit`) at offer and at execution. The bag is untouched.

### 4.2 Contracts

| Contract | Change | Row |
|---|---|---|
| C3 contracts/persisted-state.md | append trading schema (0018), service, execution + deletion — additive; older binaries refuse schema 18 (db/__init__.py:40-41) | T1, T2, T3 |
| C5 contracts/discord-commands.md | append private trade screens; `/trade` top-level command (OD1); new global manifest → `sync-commands --global --yes` | T4, T5 |
| C4 contracts/balance-tables.md | only if Q2/Q3 are numeric | T0 |

### 4.3 Verification decision (Decide before dispatch)

- **No conflict.** The owner brief asks for TDD and `scripts/verify.py`; PIPELINE.md:10 `test_cmd` runs verify.py, and AGENTS.md:12-25 agrees. `lint_cmd: none`.
- **Rows:** focused only — the ticket's named tests via `python -m unittest discover -s tests -p "test_<module>.py"`, plus `git diff --check`, with RED evidence in the commit body.
- **No source increments.**
- **Final checkpoint (G-F):** independent integration GO plus one exact-tree full `test_cmd` PASS.
- **Live Discord** is owner smoke, never a row Accept.

### 4.4 Row bounds, order and cross-row rules

**Bounds.** Every row is `seam` (PIPELINE.md:13: trading, migrations, slash commands). Limits are ≤ 2 production files and ≤ 300 production lines per row (`git diff --numstat`); tests, contracts and docs are uncounted.

**Order.** Each row is green and stays inert until T5: T1 schema; T2/T3 service with no caller; T4 handlers that no session can reach yet; T5 the command.

**Rules every ticket repeats:**
- Time is `Walker.clock()` (walker.py:43), never `bot.clock` (client.py:78).
- Order: session owner → receipt replay → guards.
- Every mutating handler passes its screen's trade revision.
- Renderers do no I/O (C5 :291).

### 4.5 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` (PIPELINE.md:15); the plugin default agrees; no feature exception |
| Candidate | final accepted feature candidate on the G-A Home; no milestones |
| Action scope and targets | **Unresolved; proposed default local-only** (precedent v1.1 PLAN §4.5). Repo `Farkoal2128/Pokewalker-Discord-Bot` (.template.json); remote `origin` = https://github.com/Farkoal2128/Pokewalker-Discord-Bot.git (`git remote -v`); main branch `main`. Deploying migration 0018 to production and running `sync-commands --global --yes` are separate owner-authorized effects (rules/security.md). |
| Predicates and workflow | integration GO; exact-tree full `test_cmd` PASS; owner-committed privacy.md disclosure; owner-approved help line; coordinator delivery path for any granted effect |
| Owner authority | none yet; G-A records approval, Home and scope. Silence, review GO and this header grant nothing. |

**G-P (planning-doc publication).** The allowlist is `docs/features/pokemon-trading/PLAN.md` and `tickets/T1.md`–`T5.md`. A push to `main` or a PR runs `.github/workflows/verify.yml` (PIPELINE.md:26). Proposed default: no publication. If the owner confirms local-only at G-A, G-P is inapplicable. The plan author never pushes.

### 4.6 Gate record

| Gate | Decision maker | Scope | Evidence |
|---|---|---|---|
| G-A | owner | Q1–Q7, help line, Home, delivery scope | an owner message naming G-A |
| G-F | coordinator for the §4.5 technical predicates; owner for privacy, smoke and delivery effects | as named | the owner's privacy.md commit and a message naming G-F |

## 5. Step table

| Step | Ticket(s) | Kind | Tier | Effort | Status |
|---|---|---|---|---|---|
| 1 | G-A plan approval: Q1–Q7, help line, Home, delivery scope | 🚦 | — | — | pending |
| 2 | [T1](tickets/T1.md) migration `0018_trades.sql`: trades, sides, guard triggers; C3 | impl | seam | S | pending |
| 3 | [T2](tickets/T2.md) `services/trading.py`: eligibility, open/reopen, offer, cancel; C3 | impl | seam | M | pending |
| 4 | [T3](tickets/T3.md) confirm + atomic swap, view, deletion cases; C3 | impl | seam | M | pending |
| 5 | [T4](tickets/T4.md) `bot/trade.py` screens + handlers on the Walker router; C5 | impl | seam | M | pending |
| 6 | [T5](tickets/T5.md) `/trade` top-level command, registration, help line; C5 | impl | seam | S | pending |
| 7 | G-F final: independent GO, exact-tree full `test_cmd`, privacy disclosure, command sync + owner smoke, delivery per G-A | 🚦 | — | — | pending |

Conditional rows are added at G-A only if needed: T0 (Q2/Q3 numeric, before T1) and T6 (Q6 ping, after T5).

## 6. Gate briefs

**G-A (owner).**
- Approve the plan and answer Q1–Q7, or accept the defaults.
- Approve the help line (182 UTF-16 units; the total becomes 4,027/4,096): "**Trading.** Use `/trade member` to swap one Pokémon with a member of this server: each of you picks one, both confirm. Favorites, your companion and gym defenders can't be traded."
- Assign the Home and choose the delivery scope.
- **Accept:** that owner message, recorded in row 1.
- **Stop if:** a non-default answer — re-brief the affected tickets and add T0/T6 before any row starts.

**G-F (coordinator + owner).**
- **Coordinator:** integration GO plus `Tests: tree <sha> <test_cmd> PASS` on the final candidate.
- **Owner prerequisite:** a committed privacy.md disclosure (the runtime text is the operator file, bot/account.py:15-23). Proposed text: "**Trades.** During a trade the other member sees the Pokémon you offer (species, form, CP, appraisal). A Pokémon you trade away belongs to them; deleting your data, opting out or a reset does not remove it from their game. Records of your trades are deleted with either profile."
- **Owner command sync:** `python -m pokewalker sync-commands --guild <test guild> --yes` (README.md:209-222).
- **Owner smoke with two accounts:**
  - A runs `/trade member:@B`, then B runs `/trade member:@A`.
  - The picker hides favorites, the companion and deployed Pokémon.
  - Both confirm and the Pokémon swap.
  - Favoriting, deploying or setting companion on an offered Pokémon before the second confirm is refused.
  - A changed offer needs re-confirmation.
  - Cancel and expiry work.
  - A stale button says "reopen /trade".
  - `/walker` home has no trade entry.
- Record the delivery outcome per G-A.

## 7. Risks and rollback

- **Schema.** 0018 is additive. Older binaries refuse schema 18. Rollback means restoring a compatible backup, never lowering `user_version` (C3 :116-119).
- **Trigger reach.** The owner-change trigger blocks any future `profile_id` change; none exists today (§3).
- **Abuse.** Alt accounts can funnel Pokémon to a main (Q3 mitigates). Scams are mitigated by P5: you confirm exactly what you saw, with the partner's CP and appraisal shown.
- **Warts.** Received Pokémon keep their original `caught_at`, so Storage sorts them by catch date (storage.py:32-33). The help text is near its limit.
