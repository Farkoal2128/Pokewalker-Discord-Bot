# Plan: data-cleanup — cleanup clocks, space reclaim and release pruning (D74)

**Status:** revised after plan reviews 1 (NO-GO: Must 3, Should 5), 2 (NO-GO: Must 0, Should 5) 3 (NO-GO: Must 1, Should 2) 4 (NO-GO: Must 0, Should 3) 5 (NO-GO: Must 0, Should 4) 6 (GO with fixes: Must 0, Should 2) 7 (NO-GO: Must 0, Should 3) 8 (GO with fixes: Must 0, Should 4) 9 (GO with fixes: Must 0, Should 2) 10 (GO with fixes: Must 0, Should 3) 11 (GO with fixes: Must 0, Should 4) 12 (GO with fixes: Must 0, Should 3) 13 (GO with fixes: Must 0, Should 2) 14 (GO with fixes: Must 0, Should 2) 15 (NO-GO: Must 1, Should 0) 16 (GO with fixes: Must 0, Should 2) and 17 (GO with fixes: Must 0, Should 1). Plan loop
done (Must 0, Should < 2); the last fixes are applied.
**Home:** branch `data-cleanup`, cut from `main` at `a096bb3`. A first implementation exists
uncommitted on the branch; this plan is reviewed first and the code is then aligned to it.
**Inputs:** owner messages 2026-11-17 (below) · `AGENTS.md` · `contracts/persisted-state.md`
· `docs/features/pokewalker-bot/privacy.md`

## 1. Outcome and non-goals

Owner, verbatim: "Finished encounters do not need to last more than a day, much less a month.
Find an appropriate clean up clock for them. Same with throw records. Same with gym battle
logs. Same with finished arena runs. I approve of 7" (7 = give freed space back to the disk),
plus "Are you able to clean up the old releases?" and the earlier approval of the sweep index.

Outcome:
1. The database stops growing with finished encounters, throw records, gym battle logs and
   superseded Arena runs.
2. The once-a-minute research auto-send stops scanning every encounter ever made (measured
   1.1 s at 1 M rows, 3.1 s at 3 M, all inside the single writer).
3. Space freed by deletions goes back to the filesystem.
4. Deploys stop accumulating ~47 MB releases in `/opt/pokewalker/releases` (920 MB, 20 today).

Owner follow-up 2026-11-17: "Approved" for the chat-message records recommendation (a running
lifetime steps counter, then delete `step_events` rows after 24 hours).

Owner decision 2026-11-17 after review 3: "Delete them too" — throw, Run and auto-research
receipts go with their encounter, gym battle receipts after 2 days, with their ledger lines.

Under "Same with finished arena runs", the agent also deletes a pruned run's
`arena_fight`/`arena_use`/`arena_heal` receipts and their ledger lines; this extension needs the
owner's explicit approval at 🚦 G1. If refused: keep run pruning, drop the three key-range
deletes and their §5 clause, and keep those receipts and ledger lines (they stay unreachable,
since `_live_run` refuses them first).

Non-goals: all other receipts (trades, evolutions, purchases, gifts, research previews, Arena
start/redeem/arming, …) and their `resource_ledger` lines (idempotency and audit), `finds`, `mod_audit`, `world_spawns`, pre-deploy
database copies (operator cleans manually; 27-day timer unchanged), shrinking
`content_version` strings, any player-visible game rule.

## 2. Code map (verified on the branch, against main a096bb3)

| Anchor | Fact |
|---|---|
| `db/migrations/0001_core.sql:59-82` | `encounters`: state queued/revealed/caught/fled/ran; `resolved_at`, `acknowledged_at`; index (profile_id,state,created_at) only |
| `db/migrations/0001_core.sql:92-100` | `catch_attempts.encounter_id REFERENCES encounters ON DELETE CASCADE`; has `created_at` |
| `db/migrations/0001_core.sql:115`, `0015:22` | `pokemon.source_encounter_id` (UNIQUE) and `raid_participation.encounter_id` ON DELETE SET NULL |
| `db/migrations/0002_reaction_encounter.sql:1` | `reactions.encounter_id` ON DELETE CASCADE |
| `db/migrations/0014_gyms.sql:29-44` | `gym_battles` with `events` JSON and `created_at`; nothing references it |
| `services/research.py:123-140` | `auto_send` scans `state='caught' AND acknowledged_at IS NULL AND resolved_at+900<=?` |
| `services/catching.py:39-41, :107-116`; `bot/walker.py:463-467` | `current_result` and result-screen reward lines read `catch_attempts` of the encounter being shown; the throw writes the attempt |
| `bot/walker.py:95, :341-355` | `recover_terminal` (every home) re-shows caught/fled/ran with `acknowledged_at IS NULL` across sessions (M1.9, persisted-state.md:106, :231-235) |
| `services/catching.py:95, :136-142`; `bot/walker.py:545-551`; `services/research.py:138` | receipt keys `throw:<encounter>:<ordinal>`, `run:<encounter>:<revision>`, `research:auto:<encounter>`; results hold the full encounter row |
| `services/gyms.py:288-289, :373-378`; `bot/gyms.py:153, :166, :254`; `services/deletion.py:41` | battle receipt `battle:<session>:<revision>` holds events, survivors and both snapshots; it is the battle log players see (session lifetime); D28 redacts it |
| `db/migrations/0001_core.sql:100, :157` | `catch_attempts.receipt_key` SET NULL; `resource_ledger.receipt_key` CASCADE; the only ledger reader is the current result screen (`bot/walker.py:464`) |
| `bot/client.py:205` | sessions are deleted 1 day after expiry |
| `contracts/ops-runtime.md:5-11, :94-108`; `README.md:195-211`; `deploy/restore-rehearsal.md:49-61` | C6 operations contract (retention and deploy changes need review); operator deploy description and G-5 checklist |
| `bot/walker.py:118-121`; `services/reactions.py:46-57, :120-125`; `services/deletion.py:100` | ❗ reaction rows: marked for removal on `/walker`, retired only after Discord removal succeeds, retried by `startup_sweep`, read by D28 delete-data |
| `bot/walker.py:272-290, :414-425`; `bot/share.py:52-60` | pending-catch store/ack (unacknowledged only); raid reselection (queued/revealed only); share from the catch screen (session lifetime) |
| `services/trading.py:228`; `services/forms.py:254-258`; `services/profiles.py:100` | safe with a NULL/missing encounter link; queue size counts queued/revealed only |
| `bot/client.py:197-207` | `_sweep_once`: gyms.settle, raids.expire, research.auto_send, trading.prune, session delete, every 60 s, one writer transaction |
| `services/arena.py:81-90, :101-115`; `services/profiles.py:107` | only `_latest_run` and the live-team read use `arena_runs` |
| `services/raids.py:48-52`; `bot/raid.py:23-33` | `join` returns the participation's encounter while the spawn is live |
| `bot/mod.py:174-206` | mod lookup "Catches: N" = all successful throws ever (lifetime); "Steps last hour" and "Steps total" from `step_events` (`:175-181`) |
| `services/profiles.py:64-69`; `bot/route.py:41, :52` | `lifetime_steps_c` sums every `step_events.awarded_c`; it decides route unlocks |
| `services/stepping.py:117-140` | `INSERT OR IGNORE` on `message_id` dedupes a redelivered message; anti-farming reads the last hour; the award is written by one UPDATE per message |
| `bot/messages.py:30-34` | reads the message's own row right after crediting it (dedupe/credited count) |
| `services/deletion.py:36-66` | D28 redaction of `gym_battles.events`; a missing row is a no-op |
| `db/__init__.py:23-60` | `open_db`: PRAGMAs (journal_mode=WAL first), then migrations in `BEGIN IMMEDIATE` scripts |
| `db/__init__.py` `Writer._work` | commits after the callback; any still-open statement makes the commit fail |
| `deploy/deploy.sh:41-66, :108-121, :139-145, :150-188` | `$previous`/`$release`; 60 s readiness wait; rollback exits 50 when the schema is newer than the previous release; stop + snapshot before activation |
| `deploy/pokewalker-bot.service:10-11` | the bot runs as `pokewalker:pokewalker` |

## 3. Design

**3.1 Cleanup clocks (`services/cleanup.py`: `sweep(conn, now, resume, batch=1000)` deletes,
`resume` being the leftover sweep's in-memory position, returned by `sweep` and kept by the
client only after the `writer.run` commits, and `reclaim(conn)` runs the
incremental vacuum; both run in one `writer.run` job called from `_gym_sweep_loop` right after
`_sweep_once` returns (not inside it), with its own try/except so a cleanup failure never rolls
back the other sweep steps and a sweep failure never skips cleanup; `_sweep_once` and its tests
are unchanged).**
An encounter is deleted when it is not tied to a live raid (`raid_spawn_id` naming a
`world_spawns` row with `ended=0`), and one of:
- acknowledged (any of caught/fled/ran, `acknowledged_at` set) and `resolved_at <= now - 3600`;
  1 hour covers the result screens (sessions expire after 15 idle minutes, `walker.py:38`);
- never acknowledged, `resolved_at <= now - 86400`, and either fled/ran or caught with a
  Pokémon row already made from it (`EXISTS pokemon WHERE source_encounter_id=…`, e.g. sent
  to research from the pending screen but never closed): M1.9 recovery shows the result on
  the player's next home for one day (owner: "not more than a day").
Unacknowledged caught encounters with no Pokémon row (a catch waiting for storage) and
queued/revealed ones are never deleted. Throw records go with their encounter (cascade).
Pokémon keep everything but the encounter link (SET NULL); raid participation rows (deleted
when their spawn ends) keep a NULL link.
- The batch size is 1,000 (measured ~0.85 s per 5,000-encounter batch with receipts and
  step_events on a workstation, so ~0.2 s per run; a 1 M-encounter backlog drains in about
  17 hours of minute runs).
- Each run first picks the batch of encounter IDs once (a list), then, for that batch only:
  `UPDATE reactions SET encounter_id=NULL` (a ❗ row is never lost: rows with a NULL encounter
  are already reconciled by message on `/walker`, by `startup_sweep` and by D28,
  `bot/walker.py:131-134`, `services/reactions.py:44-56`, `persisted-state.md:155-157`);
  deletes the batch's receipts while the IDs are in hand — throw keys read from
  `catch_attempts.receipt_key` (indexed) before the cascade, run keys by the range
  `key > 'run:<id>:' AND key < 'run:<id>;'`, and the exact key `research:auto:<id>`; then
  deletes the encounters. Ledger lines cascade from their receipts.
- Leftover receipts (raid expiry deletes queued/revealed raid encounters directly,
  `services/raids.py:98, :289`, and the existing backlog): a resumable sweep walks the
  `throw:`, `run:` and `research:auto:` key ranges in key order from its in-memory `resume` position
  (`key > :last`, at most 1,000 keys examined per kind per run, wrapping to the start at the
  end; a restart starts over), deleting keys whose encounter no longer exists. Encounter IDs are
  always `str(uuid4())` (`stepping.py:83`, `raids.py:70`, `profiles.py:164`), so only keys of
  the exact shape are considered: the GLOB pattern (`'throw:' + U + ':*'`, `'run:' + U + ':*'`,
  `'research:auto:' + U`, U the 36-character uuid pattern) is built in Python and bound as a
  single parameter so SQLite uses the key index; the ID is `substr(key, 7, 36)` /
  `substr(key, 5, 36)` / `substr(key, 15, 36)`, checked with `NOT EXISTS` on the encounter's
  primary key. Keys of any other shape are never touched. No replay can reach these receipts
  once the encounter is gone (`bot/walker.py:450-452`, `services/catching.py:55`).
- Gym battle logs: delete `gym_battles` rows when `created_at <= now - 3600` (an unread
  duplicate; only D28 redaction touches them). Delete `battle` receipts (and their ledger
  lines) with `key GLOB 'battle:*' AND created_at <= now - 2 days` (an index range on the key,
  up to 1,000 per run): result and log screens read the session's
  `selection['result']` (`bot/gyms.py:249-256`), and the receipt is read only when the same
  `battle:<session>:<revision>` key is replayed (`services/gyms.py:288-293`), which needs a live
  session; sessions are gone 1 day after they expire.
- Arena runs: delete ended runs that are not their profile's latest (`started_at`, then
  `run_id`). The latest is always kept, ended or not. With each pruned run, its receipts
  `arena_fight:<run>:…`, `arena_use:<run>:…` and `arena_heal:<run>:…` (`services/arena.py:338,
  :383, :459`) are deleted by key range (`key > 'arena_fight:<run>:' AND key < 'arena_fight:<run>;'`
  and likewise), their ledger lines cascading. Nothing reads them except replay of the same key,
  which `_live_run` refuses once the run is not the latest; month scores are separate. At most
  100 Arena runs are pruned per run (a run has dozens of receipts; measured 1,000 runs × 60
  receipts ≈ 0.67 s).
- The cap (`batch`, 1,000) applies to the encounter pick and to each `step_events`,
  `gym_battles` and battle-receipt delete (Arena runs: 100 per run, above), written as
  `DELETE … WHERE <key> IN (SELECT <key> … LIMIT ?)` (SQLite here lacks DELETE … LIMIT). A
  batch's own receipt deletes are bounded by that batch's keys (a few per encounter), not by the
  cap; cascades follow their parents.

**3.2 Lifetime catch count.** Migration 0034 adds `profiles.catch_total INTEGER NOT NULL
DEFAULT 0`, backfilled from successful `catch_attempts` joined to `encounters`; a successful
throw increments it in the same transaction. The mod lookup reads it, so "Catches: N" keeps its
meaning and text.

**3.2b Chat-message records.** Migration 0034 adds `profiles.steps_total_c INTEGER NOT NULL
DEFAULT 0` (CHECK integer ≥ 0), backfilled with each profile's `sum(step_events.awarded_c)`.
`stepping` adds the message's `awarded_c` to it in the same transaction as the award UPDATE.
`lifetime_steps_c` and the mod lookup's "Steps total" read the counter, so route unlocks and the
shown total are unchanged. Cleanup deletes `step_events` rows with `created_at <= now - 86400`
(1,000 per run): every other reader looks back at most an hour (anti-farming, "Steps last hour")
or minutes (redelivery dedupe), and a day is a safety margin.

**3.3 Sweep index.** Migration 0034 adds `encounters(resolved_at)` (cleanup),
`gym_battles(created_at)`, `step_events(created_at)`, and a partial index
`encounters_unclaimed ON encounters(resolved_at) WHERE state='caught' AND acknowledged_at IS NULL`
so `auto_send` is fast at once, before the backlog drains (measured on 1 M rows: under 0.1 ms
versus 0.19-2.0 s with the plain index). `auto_send` compares `resolved_at<=?-900` so it can
use it.

**3.3c Done after cleanup.** `ack` (`bot/walker.py:359-361, :450-453`) treats a selected
encounter that no longer exists as already acknowledged and returns home instead of refusing:
a recovery screen opened near the 24-hour mark, or a pending catch sent to research and then
cleaned up before Done, ends normally.


**3.3b Reactions by message.** All reaction work locks by the row's text message ID
(`message_id` is the `reactions` primary key; a row's message ID never changes and its
`encounter_id` only ever becomes NULL). `reconcile_reaction(encounter_id)` reads the row's
`message_id` and delegates to `reconcile_message`, so the message handler (`bot/messages.py:41`,
a brand-new encounter cleanup cannot touch) keeps calling it unchanged. `/walker` open
(`bot/walker.py:118-135`) and `startup_sweep` (`services/reactions.py:55-59`), which handle
older rows that cleanup may detach between their read and their reconcile, call
`reconcile_message(message_id)` directly. D28 `remove_own` (`services/reactions.py:96-107`, called
from `services/deletion.py:127` and `bot/admin_channels.py:280-281`) locks
`("message_id", row["message_id"])` for every row. The lock key is always the text message ID:
every caller reaches the lock with the TEXT ID stored in `reactions` (the handler passes the
encounter ID and `reconcile_reaction` reads the stored message ID; `/walker`, `startup_sweep`
and D28 read stored rows), so all share one lock. A row is then always handled under one lock whether or not cleanup has detached
it, and the D28 race test (`tests/test_reactions.py:248-249`) keeps its meaning.

**3.4 Space reclaim.**
- New databases: `open_db` sets `auto_vacuum=INCREMENTAL` before `journal_mode=WAL` (it only
  takes effect before WAL on an empty file). `journal_size_limit` is set to 64 MiB so the WAL
  file shrinks after checkpoints.
- Upgrades run with the bot stopped: a new CLI subcommand `python -m pokewalker migrate` opens
  the configured database (`open_db`, which applies pending migrations including 0034's index
  builds and backfills), then, if `PRAGMA auto_vacuum` is not 2, runs
  `PRAGMA wal_checkpoint(TRUNCATE)` and, when the filesystem has at least 3× (database + any
  `-wal`) free, `PRAGMA auto_vacuum=INCREMENTAL; VACUUM; PRAGMA wal_checkpoint(TRUNCATE)`,
  printing what it did. `deploy.sh` does not silence its output (unlike `check-config`). Too little space or a VACUUM failure prints a warning and exits 0 (the
  bot works in either mode; the next deploy retries); a migration failure exits non-zero.
- `deploy.sh` runs it only when `$previous` is set and the database exists (never on a first
  install), with the bot stopped, after the snapshot/backup and after the `--restore-db`
  block, through `as_bot "$release" -m pokewalker migrate` (the release's own Python, whose
  sqlite3 module is the patched SQLite; the system `sqlite3` CLI is the refused 3.45.1), with
  `SQLITE_TMPDIR=$root/var/lib/pokewalker` passed by `as_bot` (it runs under `env -i`, so
  `as_bot` gains a `-p Environment=` for it). A non-zero exit takes the existing `rollback`
  path. Migrations and VACUUM therefore never count against the 60 s readiness wait
  (`deploy.sh:108-121`); measured: 0034 takes about 28 s on a 1 GB database with 3 M chat
  rows. A mode-2 file opens fine under the previous release.
- `cleanup.reclaim(conn)` runs `PRAGMA incremental_vacuum(N)` with N = min(1000, freelist_count), stepped to
  completion (fetch all rows, cursor closed) so the writer can commit.

**3.5 Releases.** After a successful activation, `deploy.sh` keeps `$release`, `$previous` and
the newest other release directory that has `.complete` (by mtime), and removes every other
entry of `releases/` whose name is a 40-hex sha (either case) or such a sha plus `.root`
(incomplete builds and orphaned `.root` copies included), never the `.root` of a kept one's
build in progress. When `$previous` equals `$release` (redeploy), that is two kept. A failed
removal warns and never fails the deploy.

**3.6 Contract and privacy text.** Amend the C3 connection invariant
(`contracts/persisted-state.md:69-71`) to add incremental auto-vacuum on new files and the 64 MiB
`journal_size_limit`. Add `migrate` to the C5 CLI surface
(`contracts/discord-commands.md:176-179`). In C6 (`contracts/ops-runtime.md`) amend: upgrade
migrations run in the pre-start `migrate` step, before bot start (bot start still applies any
pending migrations, e.g. on a first install where `migrate` is skipped); a `migrate` failure maps
to exits 20/50 in the exit table (`:99`), and an `activate`/start failure exits 50 when
`migrate` applied a migration the previous release lacks (otherwise still 20); the configuration-check paragraph (`:14-18`) now also
covers a step that writes the database as `pokewalker` with `SQLITE_TMPDIR` set. Amend `contracts/step-rules.md:63` (C2, "Message IDs
deduplicate durably") and `contracts/discord-commands.md:928-929` (replayed message IDs never
increment the credited count) to "for 24 hours": safe because the gateway never redelivers a
MESSAGE_CREATE a day later and `step_events.created_at` is the message's own time
(`stepping.py:118-122`). Add a `persisted-state.md` section for migration 0034
(both counters, backfills and increments, the four indexes — `encounters(resolved_at)`,
`gym_battles(created_at)`, `step_events(created_at)` and the partial `encounters_unclaimed`
`WHERE state='caught' AND acknowledged_at IS NULL` — `services/cleanup.py` as producer
and the minute sweep as consumer). Amend `contracts/ops-runtime.md` (C6) for release retention
(keep 3) and the warn-and-continue VACUUM step, and the operator deploy description in
`README.md:195-211` and `deploy/restore-rehearsal.md:49-61`. Amend `persisted-state.md:2007`
(Arena run history is pruned to each profile's latest run) and `:1615` with the
`services/arena.py:221` "receipts never pruned" note (a pruned run's fight/use/heal receipts go
with it) and any receipt-retention wording
for the pruned throw/Run/auto-research/battle receipts. Amend, not only append: every contract statement that a
lifetime step total is `sum(step_events.awarded_c)` (route unlocks, mod "Steps total"; migration
0013's one-time backfill stays as written since it runs before 0034), and `persisted-state.md:104` (frozen
rolls retained only while the encounter exists), `:155-156` (NULL `encounter_id` is no longer legacy-only: cleanup
detaches rows), `:158` (callers with a message ID use `reconcile_message`),
`:164-166` (cleanup detaches a reaction row from its encounter instead of deleting it),
`:170-172` (add/remove share one lock: the message lock), `:107-108` (throw, Run, auto-research, battle and pruned-Arena-run fight/use/heal ledger
lines also disappear through cleanup), `:516-525` (D28's retained battle receipt exists for at most 2 days),
`discord-commands.md:293-294` (rows without an encounter ID are legacy or detached), `persisted-state.md:434-435` (encounters no longer kept for the profile lifetime);
the M1.9 sections `discord-commands.md:400-412` and `persisted-state.md:106, :230-238`
(recovery of an unacknowledged result lasts one day for fled/ran and for catches already
stored or sent; a catch waiting for storage stays recoverable); `privacy.md:5`, `:7` and `:9`, pinned to the real clocks (backup copies keep everything for up to 28 days, see Backups):
step-count records (message ID, channel ID, time, word counts) are kept 24 hours; a message
that produced a find or companion candy keeps its message ID and time with your game data until
deletion; one that produced an encounter keeps its message ID, channel ID and time until the
encounter is deleted; and the ❗ reaction record (message and channel ID) stays
until the player next opens `/walker`, or longer if the bot cannot remove the reaction yet; a finished encounter and its throw records go about an hour after its result
once it is closed (at the next sweep if closed later), or 24 hours after a fled/ran result or an
already stored/sent catch that was never closed, while a catch not yet stored or sent (for
example a shiny waiting for you) is kept until you handle it; raid encounters are kept at least until their raid ends (a World Legendary lasts at most
60 minutes, an EX-Raid at most 24 hours), and the clocks above then apply; gym battle logs and
results 2 days (the log players see lives in the battle receipt; the internal `gym_battles` copy
goes after 1 hour); only the latest Arena run is kept, with its fight, item and heal records (game data kept until deletion; challengers' battle results "saved in
their game data") are amended to disclose the short-lived records — this text is shown by
`/walker-account privacy` (`bot/account.py:15-24`); README D74. No game screen text changes;
the visible changes are the privacy text and that an unacknowledged result older than a day
no longer reappears.

**3.7 Owner gates.**

- 🚦 G1 before merge: the owner approves the amended `privacy.md` wording (shown by
  `/walker-account privacy`), the C6 retention/deploy/`migrate` text, the C5 CLI addition, and
  deleting a pruned Arena run's fight/use/heal receipts and ledger lines.
- 🚦 G2: the owner approves merging to `main` and pushing; after the owner runs the installer,
  the owner runs `/walker-account privacy` (live Discord is owner scope) and reports the reply,
  and reports the deploy's `migrate` line (database converted to incremental vacuum, or skipped
  and why) and the remaining `/opt/pokewalker/releases` entries — these host-only outcomes are
  not established by offline tests (`contracts/ops-runtime.md:112-115`). The stated clocks hold
  only once the backlog has drained (about 17 hours per million encounters and 50 hours per 3
  million chat rows at 1,000 a minute); the report notes this.

## 4. Steps

1. Contracts and docs (3.6).
2. RED evidence: the uncommitted draft code from before this plan (`services/cleanup.py`,
   migration 0034 and edits to `bot/client.py`, `bot/mod.py`, `services/research.py`,
   `db/__init__.py`, `deploy/deploy.sh`, plus its tests) is the agent's own work; it is set
   aside with a path-limited `git stash push -- <those code and test paths>` (not the contract,
   README or privacy edits, which step 1 owns) so the branch's code equals `main`, then the tests
   are written and run RED. The stash is reference only and is dropped, not popped. Existing
   tests changed deliberately as contract-driven updates (AGENTS.md test integrity):
   `tests/test_walker_router.py:366-373` (`/walker` open now calls `reconcile_message`; patch
   it); `tests/test_reactions.py:209-253` keep their meaning under the message lock;
   fixtures that seed `step_events` or `catch_attempts` directly also seed the new counters —
   `tests/test_route.py:34-37` `seed_steps` (used by `tests/test_route_unlocks.py`) and
   `tests/test_mod.py:150-164, :365-374, :377-405`; `tests/test_route_unlocks.py:122-131` (its
   per-subtest reset also sets `steps_total_c=0`); `tests/test_mod.py:351-363` (seed
   `steps_total_c=9000` on the two other profiles so the scoping check still means something);
   upgrade tests that compare whole `profiles` rows pop `catch_total` and `steps_total_c`
   (expected 0) — `tests/test_capacity.py:73-88`, `tests/test_arena_schema.py:75, :131, :178,
   :227`, `tests/test_trading_schema.py:84-103`, `tests/test_ex_gift_schema.py:88-97` — and the
   `user_version` pins move to 34 (`tests/test_arena_schema.py:76, :132, :164, :228`,
   `tests/test_ex_gift_schema.py:67`); the deploy harness (`tests/test_deploy_script.py:92-95`
   fake `stat`, `:141-147` fake `systemd-run`) gains per-release mtimes and a `migrate` call with
   a failure fixture; `tests/test_receipt_owner.py:57-131` `legacy_schema()` also drops
   `profiles.catch_total`, `profiles.steps_total_c` and the `encounters(resolved_at)`,
   `encounters_unclaimed` and `step_events(created_at)` indexes so the rerun of 0034 succeeds;
   the loop-driving tests `tests/test_gyms.py:754-808`, `tests/test_raids.py:1461-1473` and
   `tests/test_heartbeat.py:208-224` patch the cleanup entry point so they stay deterministic.
   Tests first: `tests/test_cleanup.py` (all of §5 except the deploy cases), mod lookup count from
   `catch_total`, deploy cases in `tests/test_deploy_script.py`, pinned schema tests to
   user_version 34: RED.
3. Migration 0034, `services/cleanup.py`, sweep hook, catch counter, `auto_send` comparison,
   `open_db` pragmas, deploy vacuum and release pruning: GREEN.
4. Full suite + guard + verify; ponytail-review loop until Must 0 and Should < 2.
5. 🚦 G1, then commit; 🚦 G2, then merge to main and push. Operator runs the installer; check
   the privacy reply.

## 5. Acceptance cases

- Acknowledged caught/fled/ran encounters older than an hour are deleted with their throws;
  unacknowledged fled/ran and unacknowledged caught-with-a-Pokémon after 24 h but not at 23 h;
  unacknowledged caught with no Pokémon never; sub-hour, queued/revealed and live-raid ones
  stay.
- A cleanup error leaves the rest of the minute sweep committed; a sweep error does not skip
  cleanup.
- The mod lookup shows "Steps total: 0" and "Catches: 0" for an unenrolled member.
- An acknowledged raid encounter older than an hour stays while its spawn is live and goes at
  the first run after the spawn ends.
- A repository test (like `tests/test_account.py:92-97`) pins the privacy text's clock wording
  to the code's constants.
- `open_db` sets `journal_size_limit` to 64 MiB.
- Throw, Run and auto-research receipts of a deleted encounter, and their ledger lines, are
  deleted with it; battle receipts go after 2 days, not at 1 day; other receipts stay.
- An encounter with a reaction row is deleted after its clock and the row stays with a NULL
  `encounter_id`, still removable on the player's next `/walker`.
- A raid encounter deleted by raid expiry after failed throws leaves no `throw:` receipts after the
  next cleanup run; receipts of a live encounter, and keys of other shapes, are never deleted.
- The batch, per-batch receipt, leftover-receipt, battle-receipt and `auto_send` queries use an index
  (EXPLAIN QUERY PLAN shows SEARCH, not SCAN); a leftover sweep run examines at most 1,000 keys
  per kind and resumes from its cursor.
- `/walker` open, `startup_sweep`, the message handler (via `reconcile_reaction`) and D28
  `remove_own` all lock by the stored message ID; the D28 race test holds; a detached row is
  still removed on the next `/walker`.
- Done on a recovery or "Sent" screen whose encounter was cleaned up returns home.
- A replayed or refused throw does not increment `catch_total`.
- `cleanup.reclaim` on a mode-0 database runs and frees nothing without error.
- `cleanup.reclaim` through `Writer.run` with free pages commits, and `freelist_count` drops.
- Gym battles older than an hour are deleted; newer stay.
- Only each profile's latest Arena run remains; a single ended run stays; a pruned run's
  `arena_fight`, `arena_use` and `arena_heal` receipts and their ledger lines go with it, the
  latest run's stay.
- The encounter pick and the step_events, gym_battles and battle-receipt deletes each cap at
  `batch` rows per run, and Arena at 100 runs per run; a batch's receipt deletes cover exactly
  that batch.
- Worst case, every stage at its cap in one job (encounters with receipts, step_events,
  gym_battles, battle receipts, 100 Arena runs, the leftover scans and a 1,000-page
  incremental vacuum) is measured once and recorded; it must stay under 2 s.
  Recorded 2026-11-17 on the bot's host (Intel i5-4590, 4 cores, SATA SSD), seed
  `tests/test_cleanup.py` `seed_worst_case` plus 1,203 free pages, sweep + reclaim in one
  `writer.run` including the commit: 0.22-0.30 s over six runs (script
  `worst_case.py`, 1,000 pages reclaimed). Code review 1 measured the sweep alone at 1.37 s on
  its workstation; both are under the 2 s limit.
- A new database is in auto_vacuum mode 2 after `open_db`.
- Migration 0034 backfills `steps_total_c` to the old sum; a credited message adds exactly its
  `awarded_c`; `lifetime_steps_c` (route unlocks) and "Steps total" equal the old values after
  `step_events` older than a day are pruned; rows under a day stay.
- Migration 0034 backfills `catch_total`; a successful throw increments it; the mod lookup shows
  the lifetime count after the attempts are pruned.
- `migrate` applies pending migrations; converts a mode-0 database to mode 2 when space allows;
  warns and exits 0 when space is short; exits non-zero when a migration fails.
- Deploy: an upgrade runs `migrate` via the release Python as `pokewalker` after the snapshot
  (and restore) and before start, with `SQLITE_TMPDIR` set; its non-zero exit rolls back; a
  first install skips it.
- Deploy with 5 extra old releases (one incomplete and newest), an upper-case sha directory and
  an orphaned `.root` leaves NEW, the previous release and the newest complete other one; a
  redeploy of the same sha keeps two; rollback/failure exits (20/40/50) prune nothing; a failed
  removal warns and the deploy still exits 0.

## 6. Risks

- Migrations and the one-time VACUUM run while the bot is stopped (outside the readiness wait);
  the VACUUM uses about 2× the live data extra at peak (temporary copy + WAL); the 3× (database +
  WAL) free-space threshold is deliberately conservative. The first VACUUM is the costliest: it
  runs before any cleanup, rewriting the full pre-cleanup database, which `incremental_vacuum`
  then frees gradually; it is skipped with a warning when
  space is short or it fails, and retried on the next deploy. The hourly backup may hold a read
  during it, so the TRUNCATE checkpoint can come back busy; the bot's own checkpoints and
  `journal_size_limit` then shrink the WAL.
- Deleting a fused partner's or traded Pokémon's source encounter only nulls the link.
- D28 deletion redaction of battles becomes a no-op for battles already pruned.
