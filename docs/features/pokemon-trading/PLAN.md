# Plan: pokemon-trading — player-to-player Pokémon trading (`/trade`)

**Status:** awaiting plan approval
**Review:** Review rounds 1–2 applied; see git history of this file. Round 3 (2026-11-12) has also been applied.
**Home:** none assigned. Proposed `feature/pokemon-trading · none`, cut from `main` at or after **8face5b** (router idle timeout), with these planning docs carried over from `docs/pokemon-trading-plan` (owner decision at G-A).
**Inputs:** owner requirement (§2) · owner decisions OD1–OD9 (2026-11-12, relayed by the coordinator) · [requirements D1–D61](../pokewalker-bot/README.md) (owner-only) · [v1.1/v2 plan](../pokewalker-v1.1-v2/PLAN.md) (conventions) · [PIPELINE.md](../../../PIPELINE.md)

## 0. Owner decisions (2026-11-12) — no product question is open

| ID | Decision |
|---|---|
| OD1 | `/trade` is its own top-level slash command. It is never a button, sub-screen or option of `/walker` or any other command. |
| OD2 (Q1) | 1-for-1 only; no gifts. |
| OD3 (Q2) | No Stardust or other cost. |
| OD4 (Q3) | At most **1 completed trade per profile per rolling 24 h** from its last completed trade; cancelled/expired don't count; both sides under the cap; checked at open/join/confirm and in the execution transaction; the caller sees "You can trade again in Xh Ym" |
| OD5 (Q4) | Receiving a traded Pokémon **counts** for the Pokédex (seen + caught) and milestones. The owner approves amending D15 (README.md:38) to add "receiving it in a trade"; T5 makes that edit. |
| OD6 (Q5) | Shiny, Legendary/Mythical and starter-origin Pokémon are tradable, with a "special trade" warning line. |
| OD7 (Q6) | Opening a trade posts **one** public message in the `/trade` channel, pinging only the partner. |
| OD8 | Trading only in moderator-enabled channels (none by default): `/walker-admin trade-channels add <channel> <reason> \| add-all <reason> \| remove <channel> <reason> \| list`, mirroring `channels` (C5 :212-256) |
| OD9 (Q7, amended 2026-11-12) | An offer expires after 15 min **without activity** (the owner's idle-timeout direction, relayed by the coordinator). Opening sets `expires_at=now+900`. Join, offer and confirm each set `expires_at=MAX(expires_at,now+900)`. |

## 1. Outcome and scope

In an enabled trade channel, A runs `/trade member:@B`; B is pinged once and joins with `/trade member:@A`; each offers one eligible Pokémon; both confirm what they saw; the swap commits in one writer transaction, caps both for 24 h and gives each receiver Pokédex/milestone credit. Favorited, gym-deployed and companion Pokémon never change owner: checked at offer, re-checked at execution, enforced by an SQL trigger.

**Non-goals:** cross-server trades; trading items, Candy or Stardust; trade history or mod trade tools; trade-triggered evolution (D40, README.md:152); DMs; edits to research/gym/evolution/power-up/storage services (P3); publication and deployment (§4.5).

**Help text:** follow-on feature paged-readme.

## 2. Requirements

README lists trading as "Later" (README.md:80) and is owner-only, so this section is the requirement. The only README edit is the D15 sentence (OD5, T5).

- **R0 (owner, verbatim intent):** "a trading feature between users so they can trade their pokemon. Make sure it doesn't allow for favorited, pokemon in gyms, or companion pokemon to be traded."
- **R1–R3:** not tradable if `favorite=1` (0001_core.sql:116), `gym_deployment_id IS NOT NULL` (0014_gyms.sql:45), or it is its owner's `profiles.companion_uid` (0001_core.sql:18). **R4:** checked at offer and atomically at execution. **R5–R8:** one server; all-or-nothing; confirm what you saw; only the two participants act. **R9–R13:** OD9, OD1, OD4, OD5, OD7/OD8.

## 3. Verified code map

Anchors were verified at 02d89af. Commit 8face5b changes only walker.py, C5 and tests (`git show --stat 8face5b`); the walker.py and test_capacity.py anchors below were re-verified at **8face5b**.

**Grep evidence:**
- `rg -ni trade pokewalker/` → none.
- `rg -n "UPDATE pokemon" pokewalker/` → 6 writers. None sets `profile_id`, and each bumps `revision`: storage.py:46, gyms.py:86, :152, research.py:71, evolution.py:78, powerup.py:66.
- `rg -n "SET companion_uid" pokewalker/` → profiles.py:144 and bot/storage.py:214. Neither bumps the revision.
- `rg -n "DELETE FROM pokemon" pokewalker/` → none.
- raids.py has no reads or writes of `pokemon`.
- `rg -n "UPDATE pokemon SET profile_id" tests/` → test_companion.py:211-212.
- test_capacity.py:55-79 compares full profile rows, popping later columns at :77-78.

| Anchor | Fact | Used by |
|---|---|---|
| 0001_core.sql:13-27, :104-121, :134-140; 0014_gyms.sql:10, :16, :24, :45-51 | profile per (guild,user); pokemon owner/favorite/state/revision; pokedex; guild-key index; composite FK; guard triggers (which do not cover `profile_id`) | T1 |
| db/__init__.py:34-41, :110-116 | contiguous migrations, so the next is **0018**; one job per `BEGIN IMMEDIATE`; a raise rolls back the job | T1, T4 |
| research.py:10-18; storage.py:6-50; profiles.py:58-95, :104-108, :140-144 | `protected_reason`; identify/page/detail; `session_owner`; step policy uses a thread's parent; the starter is favorite + companion | T3 |
| catching.py:30-37, :116-119; evolution.py:88-91; milestones.py:95-108 | catch recovery reads the source encounter; Pokédex upsert keeps `seen_at`; `check_and_award` | T4, T5 |
| bot/admin_channels.py:20-40, :84-147 | `WalkerAdmin` (Manage Server); authorize/exclusion; channels add/add-all/remove/list | T2 |
| bot/mod.py:90-91; bot/share.py:62-101; bot/raid.py:15-74 | `discord.Member` option with no members intent; permission → reserve → send after commit; top-level command → Walker session (:30-36) | T7 |
| bot/walker.py @8face5b :27-37, :51, :58-72, :122-190, :299-315, :329-331, :438 | `REOPEN`/`TIMED_OUT`/`OUTDATED`, `IDLE_SECONDS`=900, `DOUBLE_PRESS_SECONDS`=10; clock; handler registry; router (owner check :139, silent double press :176, refusals :178-180); recovery; ack; `pending` flag | T4, T6, T7 |
| bot/client.py:87-94, :148-156, :267-281 | registration; 60 s sweep; manifest hash | T2, T7 |
| tests/test_receipt_owner.py:46-95; test_companion.py:211-212; test_capacity.py:77-79 (@8face5b) | legacy rebuild; owner-change fixture; full-row profile compare | T1 |

**Do-not-touch:** services research, gyms, evolution, powerup, storage, catching, milestones, deletion, profiles, capacity, items (imported only); bot storage, screens, research, gyms, raid, mod, admin_channels; migrations 0001–0017 (C3 :116-119); `content/**`; `docs/features/pokewalker-bot/**` except the D15 sentence; `deploy/**`, `scripts/**`, `.github/**`.

**New files:** `db/migrations/0018_trades.sql`, `services/trading.py`, `bot/trade.py`, `bot/admin_trade_channels.py`. New tests: `test_trading_schema`, `test_trading`, `test_trade_screens`, `test_trade_command`, `test_admin_trade_channels`.

## 4. Decisions

### 4.1 Planner decisions

- **P1 Same server.** A profile is a (guild,user) pair (0001_core.sql:26); composite FKs to `profiles(profile_id,guild_id)` bind both sides to the trade's guild (0014_gyms.sql:10, :24); the owner-change trigger also requires one guild.
- **P2 Eligibility.** `tradable_reason`: `not_owned` (missing, not `owned`, other owner), else `research.protected_reason` refusing only `deployed`/`favorite`/`companion`. Shiny and Legendary/Mythical stay tradable (OD6 warning). Pending catches are encounters; raids and battle parties hold no lock (gyms.py:243-250).
- **P3 No mutation-side locks.** An offer pins `(uid, revision)`; every Pokémon writer bumps the revision, so execution refuses a changed Pokémon. Set companion bumps none, so execution checks companion explicitly.
- **P4 Atomic execution.** One writer job of the second confirmer (C3 :71-75). The guarded `last_trade_at` UPDATE must hit 2 rows and each owner UPDATE (restating eligibility) 1; otherwise it raises and the whole job rolls back (no savepoint), which T4's step-4 checks make unreachable in normal use. `pokemon_trade_guard` backs R1–R3/R5.
- **P5 Handshake.** Every offer change bumps the trade `revision`, voiding both confirmations; Confirm carries its screen's revision and refuses `changed` (R7); Offer needs none (own side only). Double-accept: the Writer serializes jobs, so the second sees `completed`.
- **P6 Joining and expiry.** The opener's side is joined (`open=1`); the partner's has `joined_at` NULL and `open=0` until they run `/trade member:@opener`, so an invitee is never blocked. A partial unique index allows one joined open trade per member. Expiry is 15 min idle (OD9), lazy on touch; the 60 s sweep (client.py:148-156) also expires idle trades and deletes ended trades older than a day.
- **P7 Cap (OD4).** `profiles.last_trade_at` survives partner deletion and pruning; checked at open/join/confirm (caller sees the wait; capped partner → "They can't trade again yet."), P4 guard as backstop; 86,400 s constant in trading.py (precedents share.py:70, gyms.py:235).
- **P8 Economy and Pokédex (OD3/OD5).** No Candy, Stardust or items move; nothing evolves. Each receiver gets the catching.py:116-118 upsert (keeps `seen_at` and any earlier `caught_at`) for the species from `storage.identify` (forms fold), then `check_and_award` for both. Milestones pay once per profile (0004_milestones.sql:1-6), so a Pokémon passed around pays each profile at most once (owner-accepted).
- **P9 No receipt.** C3 needs none for a non-resource mutation (set_favorite, Set companion); trade state is the idempotency record.
- **P10 Deletion and catch records.** Either profile's deletion cascades the trade; a given Pokémon stays with its receiver, `source_encounter_id` set to NULL (0001_core.sql:115). The swap acknowledges each traded Pokémon's unacknowledged source encounter so the giver's recovery never resurfaces it. Privacy text needs an owner edit (G-F).
- **P11 Trade channels and ping (OD7/OD8).** `trade_channels` table; `/trade` needs an exactly enabled channel; threads refused (the admin option is `TextChannel`, no parent inheritance); open trades keep working after removal. One ping on `opened` only, after commit, share.py pattern: Send Messages check, `last_trade_ping_at` reserved (one per 10 min per opener), `AllowedMentions(users=[partner])`; a failure keeps the trade and tells the opener.
- **P12 UX (OD1).** Private ephemeral screens on the presser's own Walker session through the shared `pw:v1:` router (owner check walker.py:139 @8face5b); the service also refuses non-participants; no `/walker` entry. For `trade_*` the router's outcomes read: timed out → "This window timed out. Please reopen /trade for a fresh one."; outdated → "This screen is out of date. Please reopen /trade to refresh."; handler refusal → "That option changed since this screen opened. Please reopen /trade to refresh."; double press within 10 s → silent. Refresh picks up partner changes.
- **P13 Restrictions and membership.** Excluded members cannot open, join, offer or confirm; an excluded partner blocks execution; paused members may trade. The `member` option follows mod.py:90-91 and refuses bots and self. `partner_busy` says only "They're in another trade right now."
- **P14 Capacity.** A 1-for-1 swap never changes an owned count: no storage check.

### 4.2 Contracts

| Contract | Change | Row |
|---|---|---|
| C3 persisted-state.md | Append the trading schema (0018), service, and execution/cap/Pokédex/deletion/prune rules. Additive; older binaries refuse schema 18 (db/__init__.py:40-41). | T1, T3–T5 |
| C5 discord-commands.md | Append the trade-channels admin commands, the trade screens with their four `trade_*` router outcomes, and `/trade` with its ping. Additive. | T2, T6, T7 |

### 4.3 Verification decision (Decide before dispatch)

No conflict: the owner asks for TDD and verify.py; PIPELINE.md:10 `test_cmd` runs verify.py. Rows: focused only — the ticket's named tests (`python -m unittest discover -s tests -p "test_<module>.py"`) plus `git diff --check`, RED evidence in the commit body. No source increments. G-F: independent integration GO plus one exact-tree full `test_cmd` PASS. Live Discord is owner smoke only.

### 4.4 Row bounds, order and cross-row rules

Every row is `seam` (PIPELINE.md:13): ≤ 2 production files, ≤ 300 production lines (tests, contracts, docs uncounted). Order: T1 schema → T2 admin commands (live, harmless without `/trade`) → T3–T5 service (no caller) → T6 handlers (unreachable) → T7 activates. **Precondition:** the Home contains 8face5b; T6 stops if its constants are missing. Every ticket repeats: time is `Walker.clock()` (walker.py:51 @8face5b), never `bot.clock` (client.py:78); session owner before any guard; Confirm passes its screen's trade revision; renderers do no I/O (C5 :291).

### 4.5 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` (PIPELINE.md:15); no feature exception |
| Candidate | the final accepted feature candidate on the G-A Home |
| Action scope and targets | **Unresolved.** The proposed default is local-only. Repo `Farkoal2128/Pokewalker-Discord-Bot`; remote `origin` (`git remote -v`); main branch `main`. Deploying 0018 and the one `sync-commands --global --yes` (covering `/trade` and `trade-channels`; README.md:209-222) are separate owner effects (rules/security.md). |
| Predicates and workflow | integration GO; exact-tree full `test_cmd` PASS; owner-committed privacy.md disclosure |
| Owner authority | none yet; G-A records approval, Home and scope |

**G-P.**
- **Allowlist:** `docs/features/pokemon-trading/PLAN.md` and `tickets/T1.md`–`T7.md`.
- **Effect:** a push to `main`, or a PR, runs `.github/workflows/verify.yml` (PIPELINE.md:26).
- **Proposed default:** no publication. If the owner confirms local-only, G-P does not apply. The plan author never pushes.

### 4.6 Gate record

| Gate | Decision maker | Scope | Evidence |
|---|---|---|---|
| G-A | owner | plan approval, Home, delivery scope (OD1–OD9 are already recorded) | an owner message naming G-A |
| G-F | coordinator for the technical predicates; owner for privacy, smoke and delivery effects | as named | the owner's privacy.md commit and a message naming G-F |

## 5. Step table

| Step | Ticket(s) | Kind | Tier | Effort | Status |
|---|---|---|---|---|---|
| 1 | G-A plan approval, Home, delivery scope | 🚦 | — | — | pending |
| 2 | [T1](tickets/T1.md) migration `0018_trades.sql` + test fallout; C3 | impl | seam | S | pending |
| 3 | [T2](tickets/T2.md) `/walker-admin trade-channels`; C5 | impl | seam | M | pending |
| 4 | [T3](tickets/T3.md) `services/trading.py`: eligibility, open/join/reopen, cap + ping window, offer, cancel; C3 | impl | seam | M | pending |
| 5 | [T4](tickets/T4.md) confirm + atomic swap with cap guard; deletion cases; C3 | impl | seam | M | pending |
| 6 | [T5](tickets/T5.md) Pokédex/milestone credit, D15 amendment, view, prune; C3 | impl | seam | S | pending |
| 7 | [T6](tickets/T6.md) `bot/trade.py` screens + handlers on the Walker router; C5 | impl | seam | M | pending |
| 8 | [T7](tickets/T7.md) `/trade` command, channel gate, ping, registration, sweep; C5 | impl | seam | M | pending |
| 9 | G-F final: independent GO, exact-tree full `test_cmd`, privacy disclosure, sync + owner smoke, delivery per G-A | 🚦 | — | — | pending |

## 6. Gate briefs

**G-A (owner).**
- **Asks:** approve this plan, assign the Home, and choose the delivery scope.
- **Predicate:** `git merge-base --is-ancestor 8face5b <home>`.
- **Accept:** the owner's message, recorded in row 1.
- **Stop if:** an OD is revised; re-brief the affected tickets first.

**G-F (coordinator + owner).**
- **Coordinator:** integration GO and `Tests: tree <sha> <test_cmd> PASS`.
- **Owner prerequisite:** commit a privacy.md disclosure. The runtime text is the operator's file (bot/account.py:15-23). Proposed text:

  "**Trades.** Starting a trade posts a message in that channel mentioning you and the member you invited, so others there can see who wants to trade with whom. During a trade the other member sees the Pokémon you offer (species, form, CP, appraisal). A Pokémon you trade away belongs to them; deleting your data, opting out or a reset does not remove it from their game. Trade records are deleted a day after the trade ends, or with either profile."
- **Owner sync:** `sync-commands --guild <test guild> --yes`.
- **Owner smoke (two accounts):** refused in a disabled channel, then `trade-channels add`; A opens and B is pinged once (a second open within 10 min is not); B joins; the picker hides favorites, companion and deployed; both confirm and swap; B's Pokédex marks caught and a milestone reaches the inbox; both capped ("You can trade again in …" / "They can't trade again yet."); favoriting, deploying or setting companion on an offered Pokémon before the second confirm is refused; an old screen says reopen /trade and a quick double press does nothing; `/walker` home has no trade entry.
- Record the delivery outcome.

## 7. Risks and rollback

- **Schema.** 0018 is additive, and older binaries refuse schema 18. Rollback means restoring a compatible backup (C3 :116-119).
- **Trigger reach.** The owner-change trigger blocks any future `profile_id` change, including in test fixtures (T1 fallout).
- **Pokédex lending.** One rare catch can complete milestones for many profiles, at most once each (owner-accepted, OD5).
- **Abuse:**
  - Funnelling to alt accounts is limited to one trade per day per profile.
  - Pings are limited to one per 10 min per opener, in enabled channels only.
  - Scams are limited by P5.
- **Wart.** Received Pokémon keep their original `caught_at`, so Storage sorts them by catch date (storage.py:32-33).
