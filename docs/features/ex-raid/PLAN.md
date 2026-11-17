# Plan: ex-raid — owner-spawned EX-Raids beside World Legendaries

**Status:** approved at G-A 2026-11-16; driving
**Home:** feature/ex-raid · cut from `main` at `1ac1c07` (G-A 2026-11-16)
**Review:** 2026-11-16 · Codex `gpt-6-astra`, 3 rounds, GO (Must 0, Should 0); log in SYNTHESIS §10
**Inputs:** [SYNTHESIS.md](SYNTHESIS.md), owner-approved 2026-11-16 after three review rounds (Must 0): XR-1..XR-11 and their recorded readings are owner rulings, R1..R10 the accepted design, §7 the acceptance cases · [PIPELINE.md](../../../PIPELINE.md) · `AGENTS.md` · `rules/*.md` · precedent [ex-gift](../ex-gift/PLAN.md)

## 1. Outcome and non-goals

Owners spawn an EX-Raid from the admin server into one server or every server: any of the 1,094 identities as boss, optional locks for shiny, level and each IV, and a duration of 1-24 hours (default 1). It runs beside the World Legendary raid: neither blocks the other, and `/raid` asks which one to open when both are live. Every player-visible string of an EX spawn says "EX-Raid".

One milestone: schema and services (2-6), announcements and player screens (7-9), admin command (10-13), help and retention text (14-15).

**Non-goals:** early end (R6); options beyond R3; a cooldown or a `mod_audit` row for EX sends (R6); extra rewards, catch-rule or `auto_send` changes (R7; C4 unchanged); retrying `attempted` announcements (R9); a persisted draft; any push, deploy, command sync or live Discord action (§3.4).

## 2. Verified code map (verified at 1ac1c07)

`git status --short` at authoring: only `?? docs/features/ex-raid/`. Paths are under `pokewalker/` unless they start with `tests/`, `content/`, `docs/` or `deploy/`, or name a root file.

| Anchor | Fact | Tickets (EXR-n) |
|---|---|---|
| `services/raids.py:22-26, :29-73` | `active_spawn` returns one row; `join` uses it (`:32`), rolls gender, shiny, level and IVs (`:51-54`), stores tier `LEGENDARY` (`:62`), consumes the lure (`:63-65`), receipt `raid:<spawn_id>:<user_id>` | 2, 3 |
| `services/raids.py:76-91, :94-126` | `expire` settles by `expires_at<=now`; `_refusal` expires, then guards; its `active` check ignores kind (`:108`); `_new_spawn` 3600 s; `_insert` names 12 columns | 2, 4 |
| `services/raids.py:163-195` | force-raid cooldown from `mod_audit`; `checked_channel` reads the gateway cache only | 4, 10 |
| `services/raids.py:202-244` | `announce`: claim to `attempted`, title `World Legendary:` (`:218`), a failed post returns silently (`:228`), unguarded `sent` write (`:235`); `resume_pending` has no per-row catch | 6 |
| `db/migrations/0015_raids.sql:3-38` | `world_spawns`; unique index `(guild_id) WHERE ended=0` (`:17`); participation without a profile FK (`:18-25`); queue triggers skip raid rows (`:27-38`) | 1, 14 |
| `db/__init__.py:72-83, :110-155` | `Writer.run(after_commit=)`; rollback only on a raised exception; the observer is synchronous and runs after commit | 4, 6, 11 |
| `bot/raid.py:15, :26-65` | `/raid` description; opt-out, exclusion, pending catch, then `raids.join` (`:43`); texts `:44`, `:57` | 2, 8 |
| `bot/walker.py:29, :73-91, :183-185, :409-415, :458-465, :516-520, :587` | action grammar `[a-z_]+`; handler registry; pending-catch action list; Back reopens the selected raid encounter; raid line; "The World Legendary left."; expired notice | 7, 8 |
| `bot/screens_catch.py:23-25, :39-40` | tier line; raid line | 7 |
| `bot/admin.py:41-47, :62-104, :223-230` | `Admin`; `throttled`; `authorize` (defer, guild/owner, 5/min, exclusion); gift commands; admin-guild registration | 9-12 |
| `bot/admin_gift.py:35-44, :80-115, :268-313, :316-375` | `discard`; `OwnerView` (Confirm prefix `:105`, buckets `:106-107`); confirm and settle; history, `HistoryView` | 10-12 |
| `bot/client.py:119-133, :173-196, :236-246, :310-314` | registration; `on_ready` runs `resume_pending`; the sweep runs `expire`, `auto_send`; drain cancels owned tasks; manifest hash | 6 |
| `bot/admin_channels.py:388, :414, :431-466`; `bot/bag.py:15-19` | raids description; `raids off` clears only the flag; force-raid; shared refusal texts | 2, 13 |
| `services/research.py:114-134`; `services/catching.py:69-71`; `domain/cp.py:57-64`; `domain/encounters.py:66-88`; `content/balance/catch.json:31-32, :43-46` | auto-send is species-based; throw refuses an expired spawn; flee chance 0 for tier `Legendary/Mythical` and for shinies; roll helpers; `raid_level_range` [20, 25] | 3, 5 |
| `bot/account.py:15-24`, `bot/client.py:149`; `docs/features/pokewalker-bot/privacy.md:11`; `deploy/runtime.env.example:9`; `bot/heartbeat.py:69` | privacy text read once at startup from `POKEWALKER_PRIVACY_PATH`; "at most 60 minutes"; 5 s health probe | 4, 14 |
| `content/help.md:49-51, :98, :107`; `content/artifact/content.json` | help lines; 1,094 identities, unique `name_en`, string `identity_id` (counted by script) | 9, 13 |
| `requirements.lock:181` | `discord-py==2.7.1`; `git grep -n autocomplete pokewalker` is empty: EXR-9 adds the first autocomplete | 9 |

**Pins** (each ticket repeats its own):
- Exact `/admin` subcommand set, `tests/test_client_lifecycle.py:678-680`: EXR-9, EXR-12.
- Manifest hashes: no test holds a literal; `tests/test_deploy_script.py:467-491`, `tests/test_client_lifecycle.py:717-722` and `tests/test_raids.py:1838-1840` compute them. Admin guild: EXR-9, EXR-12. Global: EXR-8, EXR-13.
- Literal `user_version` 30 (`tests/test_arena_schema.py:74, :128, :160, :220`; `tests/test_ex_gift_schema.py:67`), `legacy_schema` (`tests/test_receipt_owner.py:57-100`), the column-less insert `tests/test_raids.py:907`: EXR-1.
- `active_spawn` and `join` call sites (`tests/test_raids.py:928, :934, :984-987, :1021, :1197, :1204`): EXR-2. "No World Legendary is active here." (`:1646, :1649, :1829`): EXR-8. Help hash `tests/test_readme.py:42-44`: EXR-13.
- Not moved: home component count `tests/test_screens.py:63` (no home button is added).

**Do not touch:** migrations 0001-0030; `db/__init__.py`; `domain/**`; balance tables, `content/artifact/**`, `content/build/**`; services other than `raids`; `bot/bag.py`, `bot/account.py`, `bot/heartbeat.py`, `bot/mod.py`, `bot/trade.py`, `bot/arena.py`, `bot/ex_gift.py`; `deploy/**`, `.github/**`, `PIPELINE.md`, `AGENTS.md`, `rules/**`; `SYNTHESIS.md`; other feature folders but `docs/features/pokewalker-bot/privacy.md` (EXR-14).

**New files:** `pokewalker/db/migrations/0031_ex_raid.sql`, `pokewalker/bot/admin_ex_raid.py`; tests `test_ex_raid_schema`, `test_ex_raid`, `test_ex_raid_screens`, `test_admin_ex_raid`.

## 3. Decisions

### 3.1 Design

- **D1 Modules.** EX send, guards and history reads sit in `services/raids.py` beside `force_spawn` (SYNTHESIS §5); the admin command and its draft in new `bot/admin_ex_raid.py`. Services write inside the caller's writer transaction; renderers do no I/O.
- **D2 Schema 0031.** `ex_raids`: send ID as key, sending owner, identity, five nullable locks, hours, target server or NULL for all, counts (`servers`, `spawned` >= 1, `skipped` JSON by reason), commit time; never a player ID. `world_spawns.kind` (default `world`) and `ex_raid_id`; the unique index becomes `(guild_id, kind) WHERE ended=0`.
- **D3 Service API.** `live_spawns(conn, guild_id, now)` replaces `active_spawn` and lists the live rows, `world` first. `join` takes a `spawn_id` and joins it only while live in that server. `_refusal`'s `active` counts `kind='world'` only. Callers (`git grep -n "active_spawn\|raids()\.join(\|raids\.join(" -- pokewalker tests`): `services/raids.py:32`, `bot/raid.py:43` and the EXR-2 pins.
- **D4 Locks.** The draw sequence never changes: gender, shiny, one `roll_level_ivs`; each lock then overwrites its field. With `shiny` locked the lure is neither read nor consumed. Tier stays `Legendary/Mythical`.
- **D5 EX send** (`raids.ex_commit`), one writer job, in order: the sending owner's exclusion in the admin guild; the send-ID lookup (found: the recorded result; another owner's: `invalid`); validation; one set-based read of the target guild rows with a live-EX flag (`ended=0 AND expires_at>now`); guards per server in R6 order (`raids_off`, `no_channel`, `no_permission`, `channel_changed`, `active`); nothing to spawn: a refusal with the reasons, **nothing written**; else set-based settlement of the targets' overdue spawns (`expire`'s effects), `INSERT ex_raids`, one `executemany` of spawns sharing `expires_at = now + hours*3600`. The channel check is a callable from the bot (`bot.get_guild` plus `checked_channel`). `ex_target` gives the preview its provisional counts from the same guards.
- **D6 Announcements.** `announce` titles by kind. `resume_pending(bot, ex_raid_id=None)` catches per row; with an ID it announces only that send's pending live rows: that is the fan-out. `WalkerBot.announce_ex_raid` owns the task and drain cancels it. Confirm schedules it from the writer's `after_commit` observer, so it precedes the receipt and survives a cancelled callback.
- **D7 `/raid`.** No live spawn: "No raid is active here."; one: open it; two: a session saving both spawn IDs, with buttons `raid_pick_world` and `raid_pick_ex`. A click joins the **saved** ID; not live: "That raid has ended." Both actions join the pending-catch list.
- **D8 Admin draft.** `bot/admin_ex_raid.py` mirrors `admin_gift`'s draft (`discard`, Confirm, settle; about 60 lines) with its own registry; its views subclass `admin_gift.OwnerView` and `HistoryView`. `admin_gift.py` changes one line: Confirm is `gift_confirm:` or `ex_raid_confirm:`. Both features share `admin.requests` (5/min) and `admin.gift_callbacks` (30/min). One send ID per draft; "All servers" bumps only the revision. The draft deadline uses `bot.clock()` (monotonic); spawn times use `bot.walker.clock()` (UTC).
- **D9 Picker.** `suggest(content, text)`: exact Dex number, name prefix, substring, then `difflib`; case- and accent-insensitive; at most 25; label `#006 Charizard`, value `identity_id`. The autocomplete callback checks admin guild and owner in memory and returns `[]` otherwise.
- **D10 Wording.** EX strings per R8, chosen by `world_spawns.kind`. Help and the privacy text land last.

**Synthesis readings.** XR and R intent unchanged.
- R6 settlement: the outcome is kept (a refusal writes nothing; an overdue EX-Raid never blocks; a live World Legendary is untouched), the mechanism differs. Guards read liveness by `expires_at`, and `expire` runs only when a spawn will be inserted. `Writer.run` rolls back only on an exception (`db/__init__.py:110-131`), so settle-then-return-a-refusal would have committed the settlement.
- §3 cites `bot/walker.py:184-186` for the pending-catch list (it is `:183-185`) and `0015_raids.sql:20-31` for queue isolation (the triggers are `:27-38`).
- §5 "both command-manifest pins": no test pins a literal hash (Pins above); the exact pin is the subcommand set.
- R4/§6 "`active_spawn` returns live spawns": renamed `live_spawns` (D3). R3 "or EX-Raid gets its own" registry: its own (D8).
- R6 `channel_changed` stays in guard order for parity with `_refusal`; with the in-transaction check it fires only if the callable returns another channel.
- R6 benchmark: evidence with a stop threshold in EXR-4, since Accept cannot be a wall-clock bound; the owner-held part is G-B.
- R7 and parts of R6, R10 claim "no change needed": EXR-5, EXR-7 and EXR-14 pin those claims with tests expected to pass on first run; a failure there is a stop, not a fix.

### 3.2 Contracts (each lands with its row, contract and tests before code)

| Contract | Change | Tickets (EXR-n) |
|---|---|---|
| C3 `persisted-state.md` | schema 0031; M8.1a (one live spawn per kind); M8.2a and the force-raid amendment (`active` per kind); M8.3a (`live_spawns`, `join` by spawn, locks); new "EX-Raid send"; M8.4 (EX participation kept up to 24 h). Additive; older binaries refuse schema 31 | 1-4, 14 |
| C5 `discord-commands.md` | M8.2a (EX title, isolation, fan-out); M8.1c and M8.3b (wording, chooser, description); "EX-Raid manager" and "EX-Raid history" under M4.5a; M8.1b and player help | 6-13 |
| C1, C2, C4 | unchanged | none |

### 3.3 Verification decision (Decide before dispatch)

AGENTS.md asks for RED, GREEN and the applicable checks; PIPELINE.md:10 is the full `test_cmd`. Rows run **focused** ticket checks: the modules named (`python -m unittest discover -s tests -p "test_<module>.py"`) and `git -c core.whitespace=cr-at-eol diff --cached --check` (keep existing line endings). RED evidence goes in each commit body. Ticket line: `Verification: phase=implementation; scope=focused; coverage=<ticket tests>; receipt=Tests-Focused on staged tree; boundary=final feature (G-F)`.

No source increment: no separate audience. The full `test_cmd` runs once, uncached (`FP_RESULT_CACHE=0`), on the settled tree at G-F. The supervisor runs the owner's code review loop before G-F (global CLAUDE.md).

### 3.4 Delivery

| Field | Decision |
|---|---|
| Cadence | `end` (PIPELINE.md:15); no feature exception |
| Candidate | the final accepted feature candidate on Home |
| Action scope and targets | Repo `Farkoal2128/Pokewalker-Discord-Bot`, remote `origin` (`git remote -v`), main branch `main`. Separate owner effects: feature-branch backup pushes of `feature/ex-raid` (never main, never force; proposed for G-A as the owner's standing drive preference); main integration and push; host deploy applying 0031 (`deploy.*: none`, by the owner's hand); command sync of **both** scopes, admin guild and global (`deploy/deploy.sh:189-198` prints the lines); the host privacy file (G-V); live smoke (G-L) |
| Predicates and workflow | independent integration GO and one exact-tree full `test_cmd` PASS per pushed or deployed candidate; G-B before the host deploy |
| Owner authority | unresolved until G-A; nothing is inferred from this plan |

**G-P.** Allowlist: this `PLAN.md`, `tickets/EXR-1.md`..`EXR-14.md`, `SYNTHESIS.md` (all untracked today; the author commits nothing). A push to `main` or a pull request runs `.github/workflows/verify.yml` (PIPELINE.md:26). Proposed default: no publication to main; the coordinator commits the docs on Home once G-A assigns it, pushed with it only if G-A grants backup pushes. Local-only makes G-P inapplicable.

### 3.5 Gate record

| Gate | Decision maker | Scope | Evidence |
|---|---|---|---|
| G-A · G-P | owner | plan approval, Home (`branch_policy: feature-branch`), delivery and push scope | an owner message naming G-A |
| G-F | coordinator for the technical predicates; owner for push and main integration | §3.4 | integration GO; final `Tests:` receipt; owner messages per effect |
| G-B | owner | the live guild count against EXR-4's benchmark; releases the host deploy | EXR-4 commit body; the owner's count |
| G-V | owner | the host's privacy file and the running bot's reply | owner message after deploy |
| G-L | owner | live Discord acceptance | owner message with what was exercised |

## 4. Step table

Build rows are `seam`: at most 2 production files and 300 production lines; tests, contracts and docs do not count. Rows run serially.

| Step | Ticket(s) | Kind | Tier | Effort | Status |
|---|---|---|---|---|---|
| 1 | G-A · G-P plan approval, Home, delivery scope | 🚦 | — | — | ✅ 2026-11-16 owner approved; Home feature/ex-raid; backup pushes of Home (standing rule); benchmark 1,000/10,000 |
| 2 | [EXR-1](tickets/EXR-1.md) migration 0031: `ex_raids`, spawn kind, per-kind index | build | seam | M | ✅ done · 2a1f632 · GO review r1 |
| 3 | [EXR-2](tickets/EXR-2.md) spawn rules per kind; `live_spawns`; `join` by spawn | build | seam | M | ✅ done · 2c66972 · GO review r1 |
| 4 | [EXR-3](tickets/EXR-3.md) locks at join | build | seam | S | ✅ done · 79d1b7c · GO review r1 |
| 5 | [EXR-4](tickets/EXR-4.md) service: EX send, guards, history reads; benchmark evidence | build | seam | L | ✅ done · 875b154 · GO review r1 |
| 6 | [EXR-5](tickets/EXR-5.md) EX catch coverage | build | seam | M | ✅ done · 7fb5b16 · GO review r1 after fixture fix |
| 7 | [EXR-6](tickets/EXR-6.md) announcements: EX title, failure isolation, bot-owned fan-out | build | seam | M | ✅ done · 3ec402e · GO review r1 |
| 8 | [EXR-7](tickets/EXR-7.md) catch and Back | build | seam | S | ✅ done · ace1378 · GO review r1 after fixture fix |
| 9 | [EXR-8](tickets/EXR-8.md) `/raid` chooser, wording, description | build | seam | M | ✅ done · 6d79405 · GO review r1 after fixture fix |
| 10 | [EXR-9](tickets/EXR-9.md) `/admin ex-raid`: options, autocomplete, validation | build | seam | M | ✅ done · 1d505ca · GO review r1 after fixture fix |
| 11 | [EXR-10](tickets/EXR-10.md) preview draft: target, All servers, counts, Cancel | build | seam | M | ✅ done · f46709c · GO review r1 after fixture fix |
| 12 | [EXR-11](tickets/EXR-11.md) Confirm: states, commit, fan-out, receipt | build | seam | M | ✅ done · 6f7a87a · GO review r1 after fixture fix |
| 13 | [EXR-12](tickets/EXR-12.md) `/admin ex-raid-history` | build | seam | S | ✅ done · d7ba24c · GO review r1; fixture fix |
| 14 | [EXR-13](tickets/EXR-13.md) help and raids | build | seam | S | ✅ done · 41bbee5 · GO review r1; fixture fix |
| 15 | [EXR-14](tickets/EXR-14.md) retention disclosure: privacy text, C3 M8.4, coverage | build | seam | S | ✅ done · 1b78be0 · GO review r1 |
| 16 | G-F final verification and delivery decisions | 🚦 | — | — | ✅ 32f7b65 test_cmd PASS; main 11-17 |
| 17 | G-B writer benchmark against the live guild count | 🚦 | — | — | pending |
| 18 | G-V deployed privacy file | 🚦 | — | — | pending |
| 19 | G-L live Discord acceptance | 🚦 | — | — | pending |

## 5. Briefs

SYNTHESIS §7 by ticket: Autocomplete, Submit, omitted duration: EXR-9. Target: EXR-10 (Confirm side: EXR-11). Bosses, pending catches, expiry of one kind, long-duration overlap, sweep expiry, raids off mid-raid: EXR-5 (and EXR-2). Locks: EXR-3. Duration bounds, shared `expires_at`, global send, settlement, coexistence: EXR-4 (ticket and force-raid beside an EX-Raid: EXR-2). Wording: EXR-6, EXR-7, EXR-8, EXR-13. Benchmark: EXR-4, G-B. Retention: EXR-14, G-V. Migration: EXR-1.

**G-A · G-P (owner).** Asks: approve this plan; assign Home `feature/ex-raid`, cut from `main` at `1ac1c07` (`git branch --list feature/ex-raid` is empty today); choose the delivery and push scope of §3.4; optionally give the expected guild count for EXR-4's benchmark (default 1,000 and 10,000). Stop if: `git rev-parse --short main` is no longer `1ac1c07` (re-verify the map with `git diff 1ac1c07..main -- pokewalker tests contracts content/help.md`).

**G-F (coordinator; owner for effects).** Predicates: every build row ✅; independent integration GO; one exact-tree uncached full `test_cmd` PASS on the settled final tree, skips recorded. `test_cmd` does not prove live Discord behavior. The technical predicates wait for no owner message. Push and main integration each need their own owner message here; the host deploy with 0031 and both command syncs are the owner's own hand and wait for G-B.

**G-B (owner-held input).** EXR-4 measures and stops on its own threshold; this gate is not a re-measurement. Only the owner can read the live count: `sqlite3 <host db> "SELECT count(*) FROM guilds"`. Decision: that count lies within the benchmarked range where the writer hold stayed under 1 s in both EXR-4 scenarios (fresh, and replacing an expired unswept send) (probe: 5 s, `bot/heartbeat.py:69`). Above the range, the coordinator repeats EXR-4's benchmark at that count (its commit body holds the method); 1 s or more there is a stop and a batching follow-up. Blocks the host deploy, the command syncs and the first global send.

**G-V (owner-held host access).** After deploy and restart: the file at the unit's `POKEWALKER_PRIVACY_PATH` carries EXR-14's sentence and `/walker-account privacy` shows it (the text loads once at startup, `bot/client.py:149`). Until then no EX-Raid longer than 60 minutes is sent. The repository tests cannot see the host.

**G-L (owner-held accounts and devices).** After deploy with 0031 and both syncs: in the admin server, autocomplete, preview, "All servers", Confirm, the receipt and history; in a test server, the "EX-Raid" announcement, `/raid` with one raid and with two, a catch, and expiry. Mocked tests prove none of this.
