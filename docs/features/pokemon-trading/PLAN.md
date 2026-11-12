# Plan: pokemon-trading — player-to-player Pokémon trading (`/trade`) and paged `/readme`

**Status:** awaiting plan approval
**Review:** round 1 on 2026-11-12 (independent reviewer: MUST 5, SHOULD 4, COULD 5). All findings and the owner decisions of 2026-11-12 are applied in revision 2 (§8). Re-review pending.
**Home:** none assigned — proposed `feature/pokemon-trading · none`, cut from `docs/pokemon-trading-plan` (owner decision at G-A). Planning docs: local branch `docs/pokemon-trading-plan`.
**Inputs:** owner requirement (§2) · owner decisions OD1–OD10 (2026-11-12, relayed by the coordinator) · [requirements D1–D61](../pokewalker-bot/README.md) (owner-only) · [v1.1/v2 plan](../pokewalker-v1.1-v2/PLAN.md) (conventions) · [PIPELINE.md](../../../PIPELINE.md)

## 0. Owner decisions (2026-11-12) — no product question remains open

| ID | Decision |
|---|---|
| OD1 | `/trade` is its own top-level slash command, never a button, sub-screen or option of `/walker` or another command |
| OD2 (Q1) | 1-for-1 only; no gifts |
| OD3 (Q2) | no Stardust or other cost |
| OD4 (Q3) | At most **1 completed trade per profile per rolling 24 h**, measured from that profile's last completed trade. Cancelled and expired trades do not count. Both sides must be under the cap; it is checked at open/join/confirm and inside the execution transaction. The capped caller sees "You can trade again in Xh Ym". |
| OD5 (Q4) | Receiving a traded Pokémon **counts** for the Pokédex (seen + caught) and milestones. The owner approves amending D15 (README.md:38) to add "receiving it in a trade" (T5 step). |
| OD6 (Q5) | Shiny, Legendary/Mythical and starter-origin Pokémon are tradable, with a "special trade" warning line |
| OD7 (Q6) | Opening a trade posts **one** public message in the `/trade` channel, pinging only the partner |
| OD8 | Trading works only in moderator-enabled trade channels (none by default), managed by `/walker-admin trade-channels add <channel> <reason> \| add-all <reason> \| remove <channel> <reason> \| list`, mirroring `/walker-admin channels` (C5 :212-256) |
| OD9 (Q7) | Offers live 15 min from creation |
| OD10 | Rework `/readme` into private, flippable pages, each within the 4,096 limit. The final page covers admin/mod setup commands. The `/checkin` text is corrected. Add a trading section and the trade-channels commands. It must still work for unenrolled/excluded members and in the post-starter send. This is its own row (T8). |

## 1. Outcome and scope

In an enabled trade channel, an enrolled member opens `/trade member:@B`. B is pinged once and joins with `/trade member:@A`. Each side offers one eligible Pokémon, both confirm what they saw, and the swap commits in one writer transaction. Afterwards both members are capped for 24 h, and each receiver gains Pokédex/milestone credit. Favorited, gym-deployed and companion Pokémon never change owner: this is checked at offer, re-checked at execution, and enforced by an SQL trigger. Separately, `/readme` becomes paged help with an admin page.

**Non-goals:** cross-server trades; trading items, Candy or Stardust; trade history or mod trade tools; trade-triggered evolution (D40, README.md:152); DMs; edits to the research, gym, evolution, power-up or storage services (P3); publication and deployment (§4.5).

## 2. Requirements

README lists trading as "Later" (README.md:80) and is owner-only, so this section is the requirement. The only README edit is the owner-approved D15 sentence (OD5, T5).

- **R0 (owner, verbatim intent):** "a trading feature between users so they can trade their pokemon. Make sure it doesn't allow for favorited, pokemon in gyms, or companion pokemon to be traded."
- **R1–R3:** a Pokémon is not tradable if `favorite=1` (0001_core.sql:116), if `gym_deployment_id IS NOT NULL` (0014_gyms.sql:45), or if it is its owner's `profiles.companion_uid` (0001_core.sql:18).
- **R4:** R1–R3 are checked at offer and re-checked atomically at execution.
- **R5:** one server.
- **R6:** all-or-nothing.
- **R7:** confirm exactly what you saw.
- **R8:** only the two participants can act.
- **R9:** OD9.
- **R10:** OD1.
- **R11:** OD4.
- **R12:** OD5.
- **R13:** OD7/OD8.
- **R14:** OD10.

## 3. Verified code map — verified at 02d89af

**Grep evidence:**
- `rg -ni trade pokewalker/` → none.
- `rg -n "UPDATE pokemon" pokewalker/` → 6 writers, none setting `profile_id`, each bumping `revision`: storage.py:46, gyms.py:86, :152, research.py:71, evolution.py:78, powerup.py:66.
- `rg -n "SET companion_uid" pokewalker/` → profiles.py:144 and bot/storage.py:214, neither bumping the Pokémon revision.
- `rg -n "DELETE FROM pokemon" pokewalker/` → none.
- `grep -n "FROM pokemon\|UPDATE pokemon\|INTO pokemon" services/raids.py` → none.
- `rg -n "UPDATE pokemon SET profile_id" tests/` → tests/test_companion.py:211-212, which T1 must handle.
- `rg -n "help_text" tests/ pokewalker/` → client.py:55, :123, walker.py:169, test_walker_router.py:34, :135, :152, test_account.py:41, test_readme.py:46. These are T8's fallout.

| Anchor | Fact | Used by |
|---|---|---|
| 0001_core.sql:13-27, :104-121, :134-140; 0014_gyms.sql:10, :16, :24, :45-51 | profile per (guild,user); pokemon owner/favorite/state/revision; pokedex; guild-key index, composite FK, guard triggers (not `profile_id`) | T1 |
| db/__init__.py:34-41, :110-116 | contiguous migrations (next **0018**); one job per `BEGIN IMMEDIATE` | T1, T4 |
| services/research.py:10-18; storage.py:6-50 | `protected_reason` (deployed, favorite, companion first); identify/page/detail | T3 |
| services/profiles.py:58-95, :104-108, :140-144 | profile/restrictions/`session_owner`; step policy uses a thread's parent; starter favorite + companion | T3, P13 |
| services/gyms.py:215-221 | SAVEPOINT refusal precedent | T4 |
| services/catching.py:116-119; evolution.py:88-91; milestones.py:95-108 | Pokédex upsert keeps `seen_at`; `check_and_award` | T5 |
| services/items.py:20-43, :106-146; checkin_table.json; bot/checkin.py:25-46 | check-in: 3600 s; 1 Poké Ball + 1 roll (Great Ball 35, Razz 30, 2 Poké Balls 20, Pinap 15); bag full → 10 Stardust; encounter if queue < 3, else "Queue is full"; paused/excluded/unenrolled refusals | T8 |
| bot/admin_channels.py:20-32, :84-147 | `WalkerAdmin` (Manage Server), authorize/exclusion, channels add/add-all/remove/list | T2 |
| admin_channels.py:84-334; mod.py:19, :87-213; admin.py:154-161 | every admin/mod command; `/admin` admin guild only | T8 |
| bot/mod.py:90-91 | a `member: discord.Member` option works in production with no members intent | T7 |
| bot/share.py:62-100 | permission check → reserve in writer → send after commit; failure text; no retry | T7 |
| bot/walker.py:27-29, :43, :50-65, :114-170 | ID grammar, REOPEN; clock; handlers; router (owner check :129-131); post-starter help send :168-170 | T6, T8 |
| bot/raid.py:15-74 | top-level command → Walker session :30-36 | T7 |
| bot/client.py:38-57, :87-94, :134, :148-156, :267-281, :297-299 | `load_help`, `/readme`; registration; dynamic items; sweep; manifest; check-config | T2, T7, T8 |
| content/help.md; tests/test_readme.py:17-20, :58-75 | one approved text, hash-pinned; 3,845 UTF-16 units / 3,862 bytes (`python3` 2026-11-12) | T8 |
| tests/test_receipt_owner.py:46-95; test_companion.py:211-212, :232-239 | legacy rebuild; owner-change fixture; trigger create/drop precedent | T1 |

**Do-not-touch:**
- services `research`, `gyms`, `evolution`, `powerup`, `storage`, `catching`, `milestones`, `deletion`, `profiles`, `capacity`, `items`. They are imported, never edited.
- bot `storage`, `screens`, `research`, `gyms`, `raid`, `mod`, `admin_channels`.
- migrations 0001–0017 (C3 :116-119).
- `content/balance/**` and the manifest.
- `docs/features/pokewalker-bot/**`, except the D15 sentence (OD5).
- `deploy/**`, `scripts/**`, `.github/**`.

**New files:**
- `db/migrations/0018_trades.sql`, `services/trading.py`, `bot/trade.py`, `bot/admin_trade_channels.py`.
- Tests `test_trading_schema.py`, `test_trading.py`, `test_trade_screens.py`, `test_trade_command.py`, `test_admin_trade_channels.py`.

## 4. Decisions

### 4.1 Planner decisions

- **P1 Same server.** A profile is a (guild,user) pair (0001_core.sql:26). Composite FKs to `profiles(profile_id,guild_id)` bind both sides to the trade's guild (0014_gyms.sql:10, :24). The owner-change trigger also requires the old and new owner to share a guild.
- **P2 Eligibility.** `tradable_reason` returns `not_owned` (missing, not `owned`, or another owner). Otherwise it reuses `research.protected_reason` (research.py:10-18) and refuses only `deployed`, `favorite` or `companion`. Shiny and Legendary/Mythical are tradable with the OD6 warning. Pending catches are encounters, not Pokémon rows. Raids and battle parties hold no lock (§3; gyms.py:243-250).
- **P3 No mutation-side locks.** An offer pins `(uid, revision)`. Every Pokémon writer bumps the revision, so execution refuses a changed Pokémon. Set companion does not bump it, so execution checks companion explicitly.
- **P4 Atomic execution.** Everything runs in the second confirmer's single writer job (C3 :71-75). The guarded `last_trade_at` UPDATE runs first and must hit 2 rows inside SAVEPOINT `trade_execute` (precedent gyms.py:215-221); then each owner `UPDATE` restates eligibility with rowcount 1. `pokemon_trade_guard` (0018) backs R1–R3/R5. SQL is in T4.
- **P5 Handshake.** Every offer change bumps the trade `revision`, which voids both confirmations. Confirm carries the revision its screen showed and refuses `changed` on a mismatch (R7). Offer needs no seen revision, because it only changes your own side. Double-accept: the Writer serializes jobs, so the second job sees `completed` and shows the result.
- **P6 Joining and limits.**
  - The opener's side is joined and `open=1`. The partner's side has `joined_at` NULL and `open=0` until the partner runs `/trade member:@opener`, so an uninvited member is never blocked.
  - A partial unique index allows one open (joined) trade per member.
  - Expiry is lazy on touch. The 60 s sweep also expires stale trades and deletes ended trades more than a day old (client.py:148-156).
- **P7 Cap (OD4).** `profiles.last_trade_at` survives the partner's deletion and pruning. It is checked at open/join/confirm (the caller sees the wait; a capped partner gives "They can't trade again yet."), with the P4 guard as backstop. The 86,400 s constant is in trading.py (precedents share.py:70, gyms.py:235). Deleting your own data resets your cap but loses every Pokémon.
- **P8 Economy and Pokédex (OD3/OD5).**
  - No Candy, Stardust or items move, and nothing evolves.
  - Each receiver gets the catching.py:116-118 upsert (`caught_at` COALESCE keeps any earlier `caught_at`; `seen_at` is kept), keyed by the species from `storage.identify` (forms fold). Then `check_and_award` runs for both receivers (milestones.py:95-108).
  - Milestones pay once per profile (0004_milestones.sql:1-6). One Pokémon passed around many profiles pays each profile at most once; this is owner-accepted. The giver's Pokédex entries are never removed (D15).
- **P9 No receipt.** C3 needs no receipt for a non-resource mutation (set_favorite storage.py:45-50 and Set companion write none). Trade state is the idempotency record.
- **P10 Deletion.** Either profile's deletion cascades the trade and both sides. A given Pokémon stays with its receiver, with `source_encounter_id` set to NULL (0001_core.sql:115). The privacy text needs an owner edit (G-F).
- **P11 Trade channels and ping (OD7/OD8).** `trade_channels` is its own table (0018). Every `/trade` needs an exactly enabled channel; threads are refused (the admin option is `TextChannel`, unlike step counting's parent rule, profiles.py:104-108). Open trades keep working after removal. One ping on `opened` only, sent after commit following share.py: Send Messages check, `last_trade_ping_at` reserved (one per 10 min per opener), `AllowedMentions(users=[partner])`; a failure keeps the trade and tells the opener.
- **P12 UX (OD1).** Private ephemeral screens run on the presser's own Walker session (raid.py:30-36) through the shared `pw:v1:` router, which owner-checks presses (walker.py:129-131); the service also refuses non-participants. There is no `/walker` entry, stale `trade_*` presses say "reopen /trade", and a Refresh button covers partner changes.
- **P13 Restrictions and membership.** Excluded members cannot open, join, offer or confirm, and an excluded partner blocks execution. Paused members may trade, because pause only stops earning. The `member` option follows mod.py:90-91 and refuses bots and self. `partner_busy` says only "They're in another trade right now."
- **P14 Capacity.** A 1-for-1 swap never changes an owned count, so there is no storage check and the bag is untouched.
- **P15 Paged help (OD10).** `content/help.md` holds pages split by `<!-- page -->`, each ≤ 4,096 UTF-16 units. Stateless `pw:readme:v1:<page>` buttons (a `ReadmeItem` DynamicItem; no DB or session) work for unenrolled and excluded members. `bot.help_page(i)` serves `/readme` and the post-starter send. The final page lists `/walker-admin` (Manage Server) and `/walker-mod` (Moderate Members). `/admin` is omitted (owner-only, admin guild only, admin.py:154-161).

### 4.2 Contracts

| Contract | Change | Row |
|---|---|---|
| C3 persisted-state.md | append trading schema (0018), service, execution/cap/Pokédex/deletion/prune — additive; older binaries refuse schema 18 (db/__init__.py:40-41) | T1, T3–T5 |
| C5 discord-commands.md | append trade-channels admin, trade screens, `/trade` + ping. **Revise** the readme amendment (:32-38) and the component-ID invariant (:122) for the second `pw:readme:v1:` grammar. This is a compatible revision: `pw:v1` is unchanged. | T2, T6–T8 |

### 4.3 Verification decision (Decide before dispatch)

- **No conflict:** the owner asks for TDD and `scripts/verify.py`; PIPELINE.md:10 `test_cmd` runs verify.py.
- **Rows:** focused coverage — the ticket's named tests via `python -m unittest discover -s tests -p "test_<module>.py"` plus `git diff --check`, with RED evidence in the commit body.
- **No source increments.**
- **Final checkpoint (G-F):** independent integration GO plus one exact-tree full `test_cmd` PASS.
- **Live Discord** is owner smoke only.

### 4.4 Row bounds, order and cross-row rules

**Bounds.** Every row is `seam` (PIPELINE.md:13). Limits are ≤ 2 production files and ≤ 300 production lines per row; tests, contracts and docs are uncounted.

**Order.**
- T1 adds the schema.
- T2 adds the admin commands, which are live but harmless without `/trade`.
- T3–T5 add the service, with no caller yet.
- T6 adds handlers that are unreachable until T7 activates them.
- T8 runs last, so the admin page can be tested against the final command tree.

**Rules every ticket repeats:**
- Time is `Walker.clock()` (walker.py:43), never `bot.clock` (client.py:78).
- Check the session owner before any guard.
- Confirm passes its screen's trade revision.
- Renderers do no I/O (C5 :291).

### 4.5 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` (PIPELINE.md:15); no feature exception |
| Candidate | final accepted feature candidate on the G-A Home |
| Action scope and targets | **Unresolved; proposed default local-only.** Repo `Farkoal2128/Pokewalker-Discord-Bot`; remote `origin` https://github.com/Farkoal2128/Pokewalker-Discord-Bot.git (`git remote -v`); main `main`. Deploying 0018 and the single `sync-commands --global --yes` (covering `/trade` and `trade-channels`; README.md:209-222) are separate owner effects (rules/security.md). |
| Predicates and workflow | integration GO; exact-tree full `test_cmd` PASS; owner-committed privacy.md disclosure; owner-approved help pages |
| Owner authority | none yet; G-A records approval, Home and scope |

**G-P.** The allowlist is `docs/features/pokemon-trading/PLAN.md` and `tickets/T1.md`–`T8.md`. A push to `main` or a PR runs `.github/workflows/verify.yml` (PIPELINE.md:26). Proposed default: no publication. If the owner confirms local-only, G-P is inapplicable. The plan author never pushes.

### 4.6 Gate record

| Gate | Decision maker | Scope | Evidence |
|---|---|---|---|
| G-A | owner | plan approval, Home, delivery scope (product decisions OD1–OD10 already recorded) | an owner message naming G-A |
| G-F | coordinator for the technical predicates; owner for privacy, help wording, smoke and delivery effects | as named | the owner's privacy.md commit and a message naming G-F |

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
| 9 | [T8](tickets/T8.md) paged `/readme` with admin page and corrected check-in text; C5 | impl | seam | M | pending |
| 10 | G-F final: independent GO, exact-tree full `test_cmd`, privacy disclosure, help approval, sync + owner smoke, delivery per G-A | 🚦 | — | — | pending |

## 6. Gate briefs

**G-A (owner).**
- Approve this revised plan (OD1–OD10 recorded), assign the Home and choose the delivery scope.
- **Accept:** that owner message, recorded in row 1.
- **Stop if:** the owner revises an OD — re-brief the affected tickets before any row starts.

**G-F (coordinator + owner).**
- **Coordinator:** integration GO plus `Tests: tree <sha> <test_cmd> PASS`.
- **Owner prerequisites:**
  - Approve the help pages.
  - Commit a privacy.md disclosure (the runtime text is the operator file, bot/account.py:15-23). Proposed text:
    "**Trades.** Starting a trade posts a message in that channel mentioning you and the member you invited, so others there can see who wants to trade with whom. During a trade the other member sees the Pokémon you offer (species, form, CP, appraisal). A Pokémon you trade away belongs to them; deleting your data, opting out or a reset does not remove it from their game. Trade records are deleted a day after the trade ends, or with either profile."
- **Owner command sync:** `sync-commands --guild <test guild> --yes`.
- **Owner smoke with two accounts:**
  - `/trade` is refused in a disabled channel; enable the channel with `trade-channels add`.
  - A opens the trade and B is pinged once; a second open within 10 min is not pinged.
  - B joins. The picker hides favorites, the companion and deployed Pokémon.
  - Both confirm and the Pokémon swap.
  - B's Pokédex marks the species caught and a milestone reaches the inbox.
  - Both are capped ("You can trade again in …"; "They can't trade again yet.").
  - Favoriting, deploying or setting companion on an offered Pokémon before the second confirm is refused.
  - Stale buttons say "reopen /trade". `/walker` home has no trade entry.
  - `/readme` pages flip, including for an excluded member, and the last page is admin setup.
- Record the delivery outcome.

## 7. Risks and rollback

- **Schema.** 0018 is additive; older binaries refuse schema 18. Rollback means restoring a compatible backup (C3 :116-119).
- **Trigger reach.** The owner-change trigger blocks any future `profile_id` change (§3), including test fixtures (T1 fallout).
- **Pokédex lending.** One rare catch can complete milestones for many profiles, at most once each (owner-accepted, OD5).
- **Abuse.** Alt funnelling is limited to 1 trade/day per profile. Ping spam is limited to 1 per 10 min per opener, and only to enabled channels. Scams are limited by P5.
- **Legacy catches.** A legacy pre-M6.8u Pokémon whose catch is still unacknowledged can be traded. Afterwards the giver may see that encounter's result screen once (walker.py:282-298, :421), and its Done only acknowledges. This is cosmetic. Unverified live count: `sqlite3 <db> "SELECT count(*) FROM pokemon p JOIN encounters e ON e.encounter_id=p.source_encounter_id WHERE p.state='owned' AND e.acknowledged_at IS NULL"`.
- **Warts.** Received Pokémon keep their `caught_at`, so Storage sorts them by catch date (storage.py:32-33).

## 8. Review responses — round 1 (2026-11-12) and owner decisions

| Finding | Applied |
|---|---|
| MUST 1 test_companion.py:211-212 fixture | T1 fallout: drop and recreate `pokemon_trade_guard` around that UPDATE |
| MUST 2 cap must survive deletion | `profiles.last_trade_at` (0018); P4/P7; T3/T4 tests |
| MUST 3 Q4 credit path | P8; T5 (`confirm` takes `content`) |
| MUST 4 trade channels and ping | `trade_channels` table (T1); T2; P11; T7; privacy text |
| MUST 5 griefing | P6 unjoined partner `open=0`; `last_trade_ping_at` (T1/T3/T7) |
| SHOULD 6 `unacknowledged_catch` | removed (P2); the residual legacy case is in §7 |
| SHOULD 7 reuse `protected_reason` | P2, T3 |
| SHOULD 8 offer seen revision | removed (P5) |
| SHOULD 9 `partner_busy` wording | P13 |
| COULD 10 offer triggers | removed |
| COULD 11 redundant columns | `initiator_profile_id`/`partner_profile_id` kept, because they cascade the whole trade on either deletion; the self-trade CHECK is dropped (`UNIQUE(trade_id,profile_id)` covers it) |
| COULD 12 receipt | removed (P9) |
| COULD 13 Member option | mod.py:90-91 cited; the stop condition is removed |
| COULD 14 prune | sweep prune (P6, T5/T7); privacy text |
