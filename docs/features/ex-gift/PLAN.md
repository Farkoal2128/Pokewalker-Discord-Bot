# Plan: ex-gift — owner event gifts and EX-items

**Status:** approved — in execution · owner approved G-A · G-P 2026-11-15 (owner pre-authorized approval in session once the audit loop reached 0 MUST)
**Home:** feature/ex-gift · none
**Review:** 2026-11-15 · Codex gpt-6-astra ponytail-audit, read-only, fixes by Opus: r1 of c7bcc1f (7 MUST, 4 SHOULD), r2 of 1dcf6aa (1 MUST, 1 SHOULD, 1 NIT), r3 of 3b3bb74 clean (0/0/0); all fixed
**Inputs:** [SYNTHESIS.md](SYNTHESIS.md), intake closed 2026-11-15: EX-1..EX-27 and its recorded readings are approved requirements, R1..R20 the approved design, §6 the acceptance cases · [PIPELINE.md](../../../PIPELINE.md) · `AGENTS.md` · `rules/*.md`

## 1. Outcome and non-goals

Owners build packages of 1-10 slots (quantity 1 each) in the admin server and send them to every server, one server, or one enrolled user of a server. Players enrolled at send open them from a new `/walker` **EX-Gift** screen. Claim moves ordinary items and Arena Tickets to the reward inbox and keeps the six EX-items in an uncapped EX inventory. EX-items are used from EX-Gift and, per EX-24, from Pokémon details and the Arena team screen.

One milestone, every row briefed. Order: balance, schema, inbox and send service (steps 2-5); admin manager, deletion of drafts and history (6-9); claim, EX-Gift screen and home button (10-12); one row per EX-item, services before screens (13-19); cross-menu buttons and help (20-21).

**Non-goals:** revoking a sent gift (R19); notifications (EX-23); Stardust or candy in gifts (EX-17); expiry (EX-18); a player gift history; Time Gear on share or step limits (EX-25); trading EX-items needs no block (EX-22: `services/trading.py:15-16` trades Pokémon rows only); any push, deploy, command sync or live Discord action (§3.4).

## 2. Verified code map (verified at 8c5fa33)

`8c5fa33` only adds `SYNTHESIS.md` to base `5a68d79` (`git diff --stat 5a68d79 8c5fa33`).

**Grep and command evidence**
- `git grep -n -i "ex_gift\|ex_items\|ex_attack\|ex_defense\|shiny_patch\|golden_bottlecap\|time_gear\|voucher\|EX-Gift" -- pokewalker scripts tests contracts content` → none: names free, no sibling work owns this.
- `ls pokewalker/db/migrations` → last is `0029_cooldown_resets.sql`; the new one is `0030`.
- `git grep -n "inbox_items" -- pokewalker` → writers `services/milestones.py:106`, `services/arena.py:48, :480`, `services/gyms.py:114, :126`; readers `services/milestones.py:111-178`, `bot/milestones.py`; no FK references the table.
- `git grep -n "run_marker(" -- pokewalker` → `bot/account.py:66, :91`, `bot/admin_channels.py:227, :304`; all reach `deletion.apply` (`services/deletion.py:125-131`).
- `git grep -n "cooldowns\." -- pokewalker` → only `bot/admin.py:166, :174, :185, :194`.
- Python over `conversion_rates.json`, `capacities.json`, `arena.json`, `content/artifact/content.json`: 14 rate items (no `evolution_item`) + `world_legendary_ticket` + 50 evolution items + 2 X-items = 67 ids, + 5 ticket tiers = **72**; every item in `find_table`, `checkin_table`, `milestones`, `gym_income_table`, `survivor_table`, `arena` is among them.
- `domain.skip_tickets(80, rules)` → bronze 2, silver 4, gold 6, platinum 3, diamond 1; 14 of floors 1-80 earn a first-clear copy from best floor 0; `max_skip(80)` = 40.

| Anchor | Fact | Tickets (EXG-n) |
|---|---|---|
| `db/__init__.py:34-46, :72-83, :144-155, :158-176`; `0009_guild_sharing.sql:2-14`; `0004_milestones.sql:7-16` | contiguous migrations; `Writer.run(after_commit=)`, a synchronous observer called only after commit; a cancelled waiter does not cancel the job (`tests/test_db.py:289`); `with_receipt`; rebuild precedent; `inbox_items.resource` lacks `arena_ticket` | 2, 3, 6 |
| `0001_core.sql:13-27, :104-121, :150-165`; `0025_arena.sql:6-27` | profiles UNIQUE(guild,user); `pokemon.shiny`, `revision`; receipts; ledger `resource` is free text; `arena_runs`, `arena_tickets` | 2, 8, 12-16 |
| `services/milestones.py:131-178`; `bot/milestones.py:75-81, :84-126, :144-150` | Claim branches item, stardust, else candy (`int(resource_id)` fails on a tier); reward names; labels; per-resource lines | 3 |
| `bot/admin.py:60-80, :141-151, :160-199, :202-209`; `config.py:22-25` | `authorize`: defer, guild/owner, 5/min deque `:66-73`, exclusion; restart rechecks exclusion in its writer job; D67 commands; `snowflake`; admin-guild registration | 5-7 |
| `services/cooldowns.py:3-49` | `PLAYER` six kinds; `reset` updates `:34-44`, then `mod_audit` `:45-48` | 11 |
| `services/iv_items.py:21-88`; `bot/iv_items.py:15-23, :45-52`; `bot/storage.py:77-82, :173-195` | lowest-IV `apply`; `quote`; `use` with receipt-owner check `:66-71`; preview layout; preview guard (`iv_item` recorded, exact match at confirm); details row 2 | 12, 13, 18 |
| `services/arena.py:93-120, :139-193, :253-279, :339-344, :366-383` | `state`; `start`: skip check `:153`, insert `:178-180`, skip tickets `:182-186`, key `:189-191`; `use_x`; boosted stats; boss win | 14, 16 |
| `domain/arena.py:103-125, :141-145` | `ticket_for`, `max_skip`, `skip_tickets`, `first_clear_bonus` | 1, 16 |
| `bot/arena.py:132-176, :209-240, :320-335, :392-397, :465-561` | team screen: row 2 Clear/Start `:156-158`, skip rows 3-4 `:166-171`; break X lines and buttons; `team_state`; X notices; dispatch, start `:534-555`; resume opens the break `:496-498` | 15, 17, 19 |
| `bot/walker.py:72-89, :171-179, :231-261`; `bot/screens.py:34-38` | registry; excluded and opted-out refusals; revision bump; home state; home buttons | 9, 10 |
| `bot/heartbeat.py:69` | health probe: `writer.run(noop)` within 5 s | 4 |
| `tests/test_deletion.py:336-349` | restore fixture: back up, delete, replay twice on the restored copy | 8 |
| `tests/test_arena_schema.py:62-72, :110-122, :150-161, :195-206`; `test_capacity.py:72-86`; `test_trading_schema.py:85-100`; `test_receipt_owner.py:57-100`; `test_screens.py:33`; `test_readme.py:41-44`; `test_balance_tables.py:79-123` | moving pins: user_version 29 and popped columns; old-schema rebuild; home labels; help hash; Arena payload | 1, 2, 10, 19 |

**Do not touch:** migrations 0001-0029; `db/__init__.py`; `domain/**`; `ENGINE_VERSION`; balance tables but `arena.json`; `content/artifact/**`, `content/build/**`; services `items`, `trading`, `gyms`, `profiles`, `storage` (imported only); `bot/client.py`, `bot/account.py`, `bot/admin_channels.py`, `bot/mod.py`, `bot/trade.py`, `bot/bag.py` (imported only); `deploy/**`, `.github/**`, `PIPELINE.md`, `AGENTS.md`, `rules/**`; `SYNTHESIS.md`; other feature folders but the generated economy report (EXG-1).

**New files:** `pokewalker/db/migrations/0030_ex_gift.sql`, `pokewalker/services/ex_gift.py`, `pokewalker/bot/admin_gift.py`, `pokewalker/bot/ex_gift.py`; tests `test_ex_gift_schema`, `test_ex_gift`, `test_admin_gift`, `test_ex_gift_screens`, `test_ex_items`.

## 3. Decisions

### 3.1 Design

- **D1 Modules.** `services/ex_gift.py` owns the catalog, send, history, claim and the EX inventory (`held`, `take`). Each effect stays with the state it changes: Time Gear in `cooldowns`, Shiny Patch and Golden Bottlecap in `iv_items`, arming and the voucher in `arena`. `bot/admin_gift.py` holds the manager and history, `bot/ex_gift.py` the player screens. Services write inside the caller's writer transaction; renderers do no I/O.
- **D2 Schema 0030** (one migration; new flags default off). `ex_gifts`: send ID as key, sending owner, scope `all|server|user`, server (NULL only for `all`), items, committed counts, time; never a recipient ID (R20). `ex_gift_recipients(gift_id, profile_id, claimed_at)`, cascading on profile delete. `ex_items(profile_id, item_id, quantity)`, no cap (EX-4). `profiles.ex_attack_armed`, `ex_defense_armed`; `arena_runs.ex_attack`, `ex_defense`. `inbox_items` rebuilt with `arena_ticket` as 0009 rebuilt `mod_audit` (R8).
- **D3 Send** (R4, R5, R13). One writer job: sending owner's exclusion in the admin guild; then the send-ID lookup (a committed send returns its stored result); then items, target, counts, `INSERT ex_gifts` and one `INSERT … SELECT` of recipients (the EX-6 snapshot). The `ex_gifts` row is the aggregate send receipt: no `action_receipts` or `mod_audit` row, no Discord I/O inside.
- **D4 Player operation keys** (R4): each receipt carries `profile_id`, its ledger lines commit with the effect, `session_owner` runs first, then the receipt lookup, then any refusal that reads mutable state, so a replay returns the recorded result (normal Arena start keeps its order). `ex_claim:<session>:<rev>`, `ex_time_gear:<session>:<rev>`, `ex_arm:<session>:<rev>`; `shiny_patch:<uid>:<pokemon rev>` and `golden_bottlecap:…` in the `iv_items.use` form; the voucher reuses `arena_start:<session>:<rev>`. `<rev>` = `session.get('_original_revision', session['revision'])`. EX-inventory ledger lines use resource `ex_item`.
- **D5 Catalog** (R1, EX-9, EX-17). Slot keys: ordinary item id, `arena_ticket:<tier>`, EX id (six, disjoint from ordinary ids). Categories by rule: Balls (`*_ball`, not a rare pocket), Berries (`*_berry`), IV items (`bottlecap`, `vitamin`; a test pins them to `iv_items.ITEMS`, which imports `ex_gift` from EXG-12, so no import cycle), Arena (X-items, tickets), Evolution (`content['evolution_items']`), Rare (everything else: rare pockets, `rare_candy`, `star_piece`, `companion_mirror`). Today 3, 4, 2, 7, 50, 6 items; pages of 25.
- **D6 Claim** (R4, EX-3, EX-4). Claim takes every unclaimed gift of the profile in one transaction, each through its own `claimed_at IS NULL` update. Ordinary slot → one `inbox_items` row keyed `ex_gift:<gift_id>`, ticket → an `arena_ticket` row, EX slot → `ex_items` +1. The screen pages unclaimed gifts 10 at a time, oldest first, with Prev and Next (R4).
- **D7 Use flows** (R10). EX-Gift has one Use button per held kind. Time Gear: a confirm screen. Shiny Patch, Golden Bottlecap: an EX-Gift Pokémon picker (10 per page via `storage.page`), then the preview and confirm that the details buttons also open (EXG-18); confirm needs a matching recorded preview, as `iv_item` does (`bot/iv_items.py:45-52`). EX-Attack, EX-Defense: one press arms. Voucher: opens the Arena team screen; its row-2 voucher button lands with the voucher (EXG-17) because the EX-Gift path needs it.
- **D8 Restrictions.** The router refuses excluded and opted-out members (`bot/walker.py:171-174`). Paused members may claim and use EX-items; the voucher keeps `start`'s paused, off, live and cooldown refusals. Shiny Patch has no gym-deployed refusal: R11 names only the Golden Bottlecap, and shininess is no combat stat (`services/gyms.py:261-266`).
- **D9 Manager** (R14-R18). Drafts live on the `Admin` instance, one `discord.ui.View` each, timeout = time left to the 15-minute deadline. Every callback defers, then checks owner, admin guild, deadline, the 30/min bucket and exclusion; after those awaits it rechecks that the registry still holds this draft and that its state allows the action (editor changes only while `editing`). One `discard` (Cancel, expiry, timeout, profile deletion) marks the draft dead, unregisters it, stops its View and clears its target IDs. Every package change is a new revision with a new send ID. Confirm takes a 5/min `authorize` token; its writer job rechecks draft identity, state and deadline before and after sending (a failure after sending raises, so the writes roll back), and a task shielded from callback cancellation settles the draft on commit (`after_commit`) or rollback. After a restart the old View is gone: a click finds no handler and gets no acknowledgement, so it cannot send; `/admin gift-history` finds committed sends.
- **D10 History** (R19). `/admin gift-history [send_id]` lists every configured owner's sends, newest first, 10 per page, or exactly one by send ID.
- **D11 Help.** One EX-Gift paragraph in `content/help.md` (prose pinned by `tests/test_readme.py`, counted as docs), written in the last row once every item works.

**Readings and corrections of the synthesis.** None changes an [O] item or the intent of an [R] item.
- R10 cites `bot/iv_items.py:34` for the Bottlecap and Vitamin buttons; that line is the preview handler. The buttons are `bot/storage.py:79-82`. Placement is unchanged.
- R4 "receipt keyed by the send ID": the `ex_gifts` row (D3). R19 "owner-visible": every configured owner (D10).
- R4 benchmark: recorded as evidence with a stop threshold in EXG-4, since Accept cannot be a wall-clock bound.
- Gaps filled as coordinator-level choices: D5 catch-all category, D8 paused and deployed rules, Time Gear confirm without a "nothing to reset" check (EXG-11).

### 3.2 Contracts (each lands with its row, contract and tests before code)

| Contract | Change | Tickets (EXG-n) |
|---|---|---|
| C4 `balance-tables.md` | `arena.json` v5 `rules.ex_items`; the giftable catalog rule | 1, 4 |
| C3 `persisted-state.md` | schema 0030; inbox `arena_ticket`; send, history, claim, EX inventory; Time Gear (D67 updates, no audit); Pokémon EX effects; arming, run flags, X block; voucher start; deletion, restore and replay coverage; the deletion listener. Additive; older binaries refuse schema 30 | 2-4, 8, 11-14, 16, 20 |
| C5 `discord-commands.md` | inbox labels; `/admin gift` and `/admin gift-history` under M4.5a; EX-Gift screen and (!); item screens; break, team and details buttons; drafts end on profile deletion | 3, 5-7, 9-13, 15, 17-20 |
| C1, C2 | unchanged | — |

### 3.3 Verification decision (Decide before dispatch)

No owner/repo conflict: AGENTS.md asks for RED → GREEN and the applicable checks; PIPELINE.md:10 is the full `test_cmd`. Rows run **focused** checks only: the modules their ticket names (`python -m unittest discover -s tests -p "test_<module>.py"`) and `git -c core.whitespace=cr-at-eol diff --cached --check` (several files are committed with CRLF or mixed line ends, `git ls-files --eol`; keep them). RED evidence goes in each commit body. Ticket line: `Verification: phase=implementation; scope=focused; coverage=<ticket tests>; receipt=Tests-Focused on staged tree; boundary=final feature (G-F)`.

No source increment: no row group serves a separate audience. The full `test_cmd` runs once, uncached (`FP_RESULT_CACHE=0`), on the settled tree at G-F. The owner's review loop (global CLAUDE.md) runs before G-F, by the supervising session.

### 3.4 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` (PIPELINE.md:15); no feature exception |
| Candidate | the final accepted feature candidate on Home `feature/ex-gift` |
| Action scope and targets | Repo `Farkoal2128/Pokewalker-Discord-Bot`, remote `origin` (`git remote -v`), main branch `main`. Separate owner effects: feature-branch backup pushes of `feature/ex-gift` (never main, never force; proposed for G-A as the owner's standing drive preference); main integration and push; host deploy applying 0030 (`deploy.*: none`, by the owner's hand); admin-guild command sync for `/admin gift` and `/admin gift-history` (`deploy/deploy.sh:189-198` prints it); live smoke |
| Predicates and workflow | independent integration GO and one exact-tree full `test_cmd` PASS per pushed or deployed candidate |
| Owner authority | G-A 2026-11-15: plan approval, Home `feature/ex-gift`, docs commit on Home, feature-branch backup pushes of `feature/ex-gift` to `origin` (never main, never force). Main integration and push, host deploy, command sync and live smoke stay separate owner effects at G-F. |

**G-P.** Allowlist: this `PLAN.md`, `tickets/EXG-1.md`..`EXG-20.md` (`SYNTHESIS.md` is in `8c5fa33`). A push to `main` or a pull request runs `.github/workflows/verify.yml` (PIPELINE.md:26). **Decided at G-A: no publication to main**; the docs stay on `feature/ex-gift`, pushed with it if G-A authorizes backup pushes. Local-only makes G-P inapplicable. The plan author never pushes.

### 3.5 Gate record

| Gate | Decision maker | Scope | Evidence |
|---|---|---|---|
| G-A · G-P | owner | plan approval, Home (`branch_policy: feature-branch`), delivery and push scope | an owner message naming G-A |
| G-F | coordinator for the technical predicates; owner for every delivery effect | §3.4 | integration GO; final `Tests:` receipt; owner messages per effect |

## 4. Step table

Every build row is `seam` (PIPELINE.md:13: slash commands and interactions, persisted state and migrations, item tables, rate limits): at most 2 production files and 300 production lines; tests, contracts and docs are not counted. Rows run in order.

| Step | Ticket(s) | Kind | Tier | Effort | Status |
|---|---|---|---|---|---|
| 1 | G-A · G-P plan approval, Home, delivery scope | 🚦 | — | — | ✅ owner approved 2026-11-15 |
| 2 | [EXG-1](tickets/EXG-1.md) balance: `arena.json` `rules.ex_items` and the manifest hash | build | seam | S | ✅ done · 286aea7 · GO review-seam r1 |
| 3 | [EXG-2](tickets/EXG-2.md) migration 0030: gifts, recipients, EX inventory, flags, inbox `arena_ticket` | build | seam | M | ✅ done · 0282cb0 · GO review-seam r1 |
| 4 | [EXG-3](tickets/EXG-3.md) reward inbox: ticket rows claim into `arena_tickets`; EX-Gift labels | build | seam | S | ✅ done · b2b6cbe · GO review-seam r2 |
| 5 | [EXG-4](tickets/EXG-4.md) service: giftable catalog, send fan-out, history reads | build | seam | M | pending |
| 6 | [EXG-5](tickets/EXG-5.md) `/admin gift`: manager editor and preview | build | seam | L | pending |
| 7 | [EXG-6](tickets/EXG-6.md) manager Confirm, draft states, receipt | build | seam | M | pending |
| 8 | [EXG-20](tickets/EXG-20.md) profile deletion discards drafts targeting it | build | seam | S | pending |
| 9 | [EXG-7](tickets/EXG-7.md) `/admin gift-history` | build | seam | S | pending |
| 10 | [EXG-8](tickets/EXG-8.md) service: claim and EX inventory | build | seam | M | pending |
| 11 | [EXG-9](tickets/EXG-9.md) EX-Gift screen with Claim | build | seam | M | pending |
| 12 | [EXG-10](tickets/EXG-10.md) `/walker` home EX-Gift button and (!) | build | seam | S | pending |
| 13 | [EXG-11](tickets/EXG-11.md) Time Gear Fragment | build | seam | S | pending |
| 14 | [EXG-12](tickets/EXG-12.md) Shiny Patch: EX-Gift picker, preview, confirm | build | seam | M | pending |
| 15 | [EXG-13](tickets/EXG-13.md) Golden Bottlecap | build | seam | S | pending |
| 16 | [EXG-14](tickets/EXG-14.md) service: EX-Attack/EX-Defense arming, run flags, boosted fights, X block | build | seam | M | pending |
| 17 | [EXG-15](tickets/EXG-15.md) screens: arm from EX-Gift; EX lines and X block on the break screen | build | seam | S | pending |
| 18 | [EXG-16](tickets/EXG-16.md) service: Arena EX-Voucher start | build | seam | M | pending |
| 19 | [EXG-17](tickets/EXG-17.md) screens: voucher start on the team screen; EX-Gift opens it | build | seam | S | pending |
| 20 | [EXG-18](tickets/EXG-18.md) Pokémon details: Shiny Patch and Golden Bottlecap buttons | build | seam | S | pending |
| 21 | [EXG-19](tickets/EXG-19.md) Arena team screen: EX-Attack/EX-Defense buttons, armed lines; help | build | seam | M | pending |
| 22 | G-F final verification and delivery decisions | 🚦 | — | — | pending |

## 5. Briefs

Each build row's brief is its ticket, linked in §4. §6 acceptance cases are distributed over the tickets' named tests; no row needs a package change or a new owner decision, so the plan has no other 🚦 row.

**G-A · G-P (owner).** Asks: approve this plan; confirm Home `feature/ex-gift` (current checkout, cut from `main` at `5a68d79`); choose the delivery and push scope of §3.4. Stop if: the Home lacks `8c5fa33` (`git merge-base --is-ancestor 8c5fa33 feature/ex-gift`).

**G-F (coordinator; owner for effects).** Predicates: every row ✅; independent integration GO; one exact-tree full `test_cmd` PASS on the settled final tree, skips recorded. `test_cmd` does not prove live Discord behavior. Each §3.4 effect needs its own owner message: push, main integration, host deploy with 0030, admin-guild command sync, live smoke.
