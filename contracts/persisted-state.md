# Contract: persisted state (C3)

## M4.4 share reservation (additive)
Migration 0010 adds nullable profiles.last_share_at REAL, preserving existing rows.
It stores the UTC epoch time of the latest committed share reservation, not proof
of Discord delivery. A reservation requires an owned Pokemon of the session profile,
current sharing enabled, no share ban, channel permissions, and at least 60 seconds
since the prior reservation. It updates the timestamp under the owner-bearing
share:<session_id>:<revision> receipt (action share), atomically with session revision.
Refusal/rollback spends nothing. Failed, interrupted or indeterminate delivery after
commit spends the minute; receipt replay never retries the public send. No outbox or
delivery guarantee is introduced. Older binaries refuse the newer schema; rollback
requires a compatible backup. Producer: share handler/migration; consumers: sharing
screens and rate limiting. Tests: tests/test_share.py.

## M4.3 guild sharing and reset (additive)
Migration 0009 adds guilds.sharing INTEGER NOT NULL DEFAULT 1, constrained to 0/1,
and rebuilds mod_audit to admit user/channel/guild targets, preserving every
existing column value and audit_id. Sharing updates and guild-target audits commit
together. Reset uses the existing marker/receipt schema; run_marker now resolves
the current profile for reset as well as delete/opt_out after its authorization
callback inside the writer job. Existing explicitly supplied profile IDs retain
their meaning. Target lookups are scoped by guild and user; deletion cascades
profile-owned state, retaining restrictions, opt-outs and prior audit.
This is an additive schema migration with unchanged marker format;
older applications cannot open the newer schema version. Producers: WalkerAdmin,
deletion and migration 0009; consumers: sharing screens and startup replay.
Tests: test_admin_reset_sharing.py and deletion/replay/storage regressions.

## M4.2 member restrictions (additive)
Member moderation upserts the existing `(guild_id,user_id)` restriction row and
inserts its user-targeted audit in one writer transaction, including without a
profile. Pause sets paused=1 and a UTC epoch deadline or NULL; resume sets paused=0
and clears the deadline. Exclude/include and share-ban/share-unban change only
their independent flag. Audit stores guild, actor, target, action (the subcommand
name), stripped reason and UTC epoch time. Failure rolls back both effects.
Status/log use writer-serialized reads to avoid exposing uncommitted changes.
The owner-approved status correction sums `step_events.discarded_words` for the
current profile within inclusive `[now-3600, now]` only when reason is `minimum`,
`cooldown`, `minute_cap`, `duplicate` or `credited`. `credited` can include partial
repeat/message-cap discards. Paused and missing-timestamp discards do not count.
Each discarded word counts as one discarded base step without a multiplier;
persisted events and credited-step calculations are unchanged.
No inventory, Candy, Pokémon or Stardust mutation or migration is introduced;
existing deletion retention and timed-pause expiry rules remain unchanged.
Producers: bot/mod.py; consumers: existing restriction checks and moderators.
Tests: tests/test_mod.py. Compatibility is additive; rollback removes commands.

## Purpose
Own the SQLite boundary required by D10, D20, D28 and ADR 0001 item 4.
This is a new boundary with no existing persisted application databases to migrate.

## Producers
- `pokewalker/db`: startup, ordered migrations, one transaction-owning writer, receipts.

## Consumers
- Profile, counting, encounter, catching and UI services; the bot lifecycle.

## Invariants
- `await open_db(path, allow_unpatched=False)` returns an aiosqlite write connection
  in autocommit mode, with row-name access. It refuses unpatched SQLite before opening
  a file; an explicit development override logs a WARNING. Patched versions are
  >= 3.51.3, 3.50.7 through 3.50.x, or 3.44.6 through 3.44.x.
  These ranges were checked against SQLite's [WAL-reset notes](https://www.sqlite.org/wal.html#walresetbug)
  and [3.51.3 release](https://www.sqlite.org/releaselog/3_51_3.html) on 2026-11-04.
- Write connections use WAL, FULL synchronous, secure deletion, foreign keys and
  a 5000 ms busy timeout. `await open_reader(path)` opens a separate `mode=ro`
  connection for screens; it never runs migrations or changes persistent settings.
- Numbered SQL migrations and their `user_version` advance atomically, once, in order.
  A database newer than this application or a gap in migration numbering is refused.
- `Writer(conn)` exclusively owns that write connection. `await writer.run(fn)` queues
  an async `fn(conn)` inside BEGIN IMMEDIATE / COMMIT. A failure rolls back before
  the next job. `await writer.close()` stops admission and drains admitted jobs;
  the lifecycle then closes the connections. Cancelling a waiting caller does not
  cancel an admitted transaction. Jobs must not commit/rollback or recursively queue
  another job; compose helpers on the supplied connection instead.
- If rollback itself fails, the writer stops admission, attempts to close the
  compromised connection and fails the current and all queued jobs with that rollback error,
  chained to the original job error. Later admissions are refused with the stored
  failure as their cause. `close()` still terminates; that connection is never reused.
- `await writer.abort()` stops admission, cancels the worker, rolls back an active
  transaction, and fails queued callers without running them. It is idempotent;
  a deadline-aborted drain is a failure, not successful write completion. This
  additive lifecycle API is reserved for shutdown failure recovery (M1.2).
- `await with_receipt(conn, key, action, compute)` requires an active writer transaction.
  `await compute(conn)` returns `(result, ledger_lines)`. The result is a JSON value;
  each line has `profile_id`, `resource`, `delta`, `reason` and optional `resource_id`.
  The helper stores the result and ordered ledger lines atomically with the mutation.
  Replaying a key returns its saved JSON result without invoking compute. Reusing a
  key for a different action is refused. Receipt errors roll back the enclosing job.
- Profile IDs are random UUID4 strings generated by enrollment, never reused. Profile
  deletion and restore replay use the external D28 deletion marker log; SQL alone
  cannot prove historical non-reuse. `(guild_id,user_id)` is unique. Discord IDs are
  decimal text; timestamps are UTC epoch seconds. No content or interaction tokens.
- Server/user restrictions survive profile deletion and are keyed by `(guild_id,user_id)`.
  Pause, exclusion and share ban are independent. Audit targets are users or channels.
- Encounter, find and companion meters are nonnegative integer hundredths (`*_meter_c`).
  Balances and quantities are nonnegative integers. Unresolved encounters are exactly
  `queued` and `revealed`, with at most three per profile, enforced on insert and update.
  Frozen rolls and content versions are retained for encounters and Pokemon.
- Catch attempt `(encounter_id,ordinal)` and Pokemon `source_encounter_id` are unique.
  Terminal encounters retain nullable `acknowledged_at` for M1.9 recovery.
- Receipt keys are unique; ledger `(receipt_key,line_key)` is unique and stores signed
  integer deltas. Ledger lines reference a profile and disappear with its deletion.
  The account-deletion service must also remove receipts holding that profile's data.
- Sessions belong to a server/user and may have no profile during onboarding.

## Schema v1
The authoritative column definitions, defaults, foreign keys, CHECK constraints and
indexes are in `pokewalker/db/migrations/0001_core.sql`. Tables: guilds, guild_channels,
profiles, restrictions, mod_audit, step_events, encounters, catch_attempts, pokemon,
inventory, candy, pokedex, reactions, action_receipts, resource_ledger and sessions.
Profile-owned records cascade on deletion; restrictions and moderation audit do not.
Deleting a companion Pokemon clears the companion reference.

## Compatibility
New additive boundary. Later schema changes use a new numbered migration; deployed
migrations are immutable. Backward schema downgrades are refused. Restore a compatible
backup for rollback; never decrement user_version on a live database.

## M1.4 profile service (additive)
`services.profiles` produces detached profile/channel dicts (or None), immutable
`Restrictions`, and integer queue sizes for later commands/counting/catching.
`get_profile(conn,guild_id,user_id)` is guild-scoped. `channel_policy` uses the
parent channel whenever supplied, including when the parent has no policy.
`restrictions` reads independent flags on every call: indefinite pause has no end;
a timed pause is inactive at/after its UTC expiry. The returned expiry is an aware
UTC datetime or None; expiry reads do not mutate stored flags. Missing rows mean
all restrictions false. `queue_size` counts only queued and revealed encounters.

`enroll(conn,guild_id,user_id,starter_species_id,content,rng,now)` runs inside the
caller's writer transaction. `now` must be timezone-aware; `content` is the verified
artifact dict with 27 starters. Exclusion is checked before receipt replay. Receipt
`enroll:<guild>:<user>` atomically creates a UUID4 profile, default route, non-shiny
favorited level-10 starter with independently rolled 10–15 IVs and species gender,
companion assignment, 30 Poké Balls, 5 Razz Berries, seen/caught dex entry, and the
first generated queued encounter. The kit produces two item ledger entries.
It rejects a non-starter or an existing profile without that receipt. Replays return
the saved profile without new grants or rolls. Frozen content versions are SHA256
of UTF-8 JSON with sorted keys and compact separators (the loaded artifact's
semantic content, distinct from the manifest's raw-byte artifact hash).
Account deletion must remove its enrollment receipt as already required above;
otherwise replay returns the original saved result. Re-enrollment after account
deletion generates fresh UUID4 identifiers; restrictions remain keyed by user.
No schema change or migration is introduced. Tests in `tests/test_profiles.py`
cover these service contracts and enrollment rollback when generation fails.

## M1.4b reaction reconciliation (additive)
Migration `0002_reaction_encounter.sql` adds nullable, unique `encounter_id`, a
foreign key to encounters with cascade deletion. New producers supply it; existing
rows retain NULL rather than guessing an encounter association. Pending legacy
rows remain reconcilable by their saved message ID. Migration 0001 is unchanged.

`ReactionService(bot).reconcile_reaction(encounter_id)` serializes each reaction
through an in-process lock and re-reads after acquiring it. Database reads and
compare-and-set writes use the single writer; Discord I/O happens outside its
transactions. Calling the reconciler from a writer job is rejected. Adds require
the guild/channel react policy (thread parent policy applies), desired add and
actual none. Actual becomes added only if desired and revision still match.
Desired remove always deletes the bot's own reaction, including when actual is
none; success or HTTP 404 retires the reaction row. Other Discord errors preserve
the row and encounter; permission errors warn once per channel per service.
`startup_sweep()` reconciles pending removes and incomplete adds, including legacy
rows. Completed removals produce no further Discord calls. This boundary changes
no encounter state and never stores message content or credentials.
M1.6 adds `reconcile_message(message_id)` for saved legacy rows without an encounter
coordinate. It shares the same writer guard, locks and reconciliation logic; callers
must use `reconcile_reaction` for rows with an encounter ID so add/remove share one lock.

## Verification
M1.5 adds no migration: the existing `(profile_id,created_at)` step-event index
supports accepted rolling history. Step events, all meter changes, frozen encounter
rolls and their optional pending reaction row commit in one writer job per message.
The M1.5 producer supplies the M1.4b `encounter_id` foreign key; reaction I/O follows
commit. C2 documents its additive credit and Gateway interfaces.

`python -m unittest discover -s tests -p "test_db.py"` exercises version boundaries,
pragmas, migration atomicity/idempotence, serialized transactions across awaits,
rollback, read-only screens, receipt replay/rollback, uniqueness, queue constraints,
integer meters, deletion scope and absence of deleted fixture bytes after checkpoint
and a fresh SQLite backup. This does not qualify host encryption or backup retention.

## M1.7 reveal and Run (additive)
M1.7 uses the existing `pokedex.pokemon_id` column as the species key required by
D15: regional forms and gender varieties map through C1's `species_id` before the
seen upsert. Its legacy column name does not mean an encounter variety ID. Existing
starter enrollment selects only base starters, whose Pokemon and species IDs agree;
later catch/evolution producers must apply the same species mapping. Reveal inserts
`seen_at` only when absent and never removes or replaces existing seen/caught dates.
Run's failed owner/exclusion/state/revision guards write no encounter or receipt;
success and its receipt commit together in the caller's writer transaction. Terminal
state reads include the Pokemon linked by `source_encounter_id` when caught.
This adds no migration and preserves all existing rows and receipt compatibility.

## M1.8 catching (additive)
`services.catching.throw(conn, encounter_id, session, expected_revision, rng, now,
content=verified_artifact, guaranteed=False)` composes inside the caller's active
writer transaction. `now` is UTC epoch seconds. Content supplies the frozen variety's
species/family and authored catch rewards; no upstream I/O occurs. It returns an
immutable detached `CatchResult(status, encounter, pokemon, candy, stardust)`.
The encounter and optional Pokemon snapshots are read-only mappings.
`CatchResult.pokemon` is None for a new catch.
`current_result(conn, encounter)` provides an authorized caller with a detached
persisted outcome dictionary, including the original caught rewards for render reuse.
Callers must validate encounter ownership before using this internal service seam.
Unauthorized ownership raises ValueError without disclosing another profile's encounter. Exclusion,
stale revision, non-revealed state, full storage without a confirmed storage warning
and missing selected items spend nothing; terminal state returns its persisted result and catch rewards. A stale
revealed result describes current state without repeating an attempt.

Each accepted throw consumes one selected ball and at most one selected berry,
clears berry selection, and increments attempt ordinal and encounter revision once.
`throw:<encounter_id>:<ordinal>` identifies its receipt. The unique attempt, signed
item ledger deltas, outcome, species caught date, family Candy
and Stardust reward deltas commit together. Rewards use C1's catch_candy/stardust;
Pinap doubles Candy and Silver Pinap floors 7b/3. A successful catch is pending (Q22);
its one row (frozen rolls, content version, not favorited, `caught_at=resolved_at`)
is written later, manually by Done/Upgrade (owned) or Send (`sent`), or by the
M6.8x sweep (`sent`). Capacity counts only owned Pokemon.
Guaranteed throws require the selected Master Ball, store probability 1 and success,
and draw neither capture nor flee RNG. Ordinary throws cannot spend a Master Ball.
No schema change or migration is required; pre-M6.8u receipts and stored results
stay valid, never pending.
`tests/test_catching.py` exercises guards, races, uniqueness, rollback and rewards.

## M1.9 terminal acknowledgment (additive)
M1.9 uses the existing nullable `encounters.acknowledged_at`: caught/fled/ran
transitions leave it NULL. An authorized `ack` (Done, post-send Done, Upgrade) or
`research.auto_send` — which sends and acknowledges in the sweep's transaction,
no session — sets it once. Recovery shows the linked Pokémon row, or the pending
encounter when no row exists, and joins the successful `catch_attempts.receipt_key` to
`resource_ledger` catch_reward lines for Candy/Stardust, scoped to the same profile.
Pre-M6.8u throw receipts keep the Pokémon UID; later ones hold none. No receipt/schema
migration is needed. Done stores a pending catch with `caught_at=resolved_at`,
acknowledges and saves session selection/revision in one writer transaction.
Upgrade includes its capacity expansion in that same transaction.
Send on a pending catch writes its `sent` row, Candy, ledger line and receipt in
one transaction (M6.8r); its Done (`ack`) then acknowledges.

## Change policy
Requirements D10/D20/D28 and ADR 0001 govern changes. Alter schema only through an
intentional contract revision, contract tests and a migration; preserve saved rolls.

## M2.2a receipt ownership (additive)
`with_receipt(conn, key, action, compute, *, profile_id=None)` stores the supplied
owner on insertion; replay still returns the saved result without computing or
changing ownership. Every receipt for a profile action carries that profile's ID
and cascades when the profile is deleted, including enrollment, Throw and Run.
Enrollment attaches ownership after its compute creates the profile, in the same
writer transaction. Process receipts (`reset:<marker_id>` audit dedupe and
`restart:*`) carry NULL and hold no player data beyond marker-log IDs.

Migration `0003_receipt_owner.sql` adds the nullable foreign key and owner index,
then backfills legacy receipts by ledger, encounter key, or enrollment key, in that
order. Unattributable legacy enroll/throw/run receipts are deleted; any other
unattributable action aborts the entire migration. Receipt keys and saved results
are unchanged. Older application versions refuse this newer schema; rollback
requires a compatible backup, never decrementing the live schema version.

## M2.2 research send (additive)
M6.8k adds migration `0017_storage_overflow.sql`: nullable `profiles.overflow_uid`
references `pokemon(pokemon_uid)` with `ON DELETE SET NULL`. The column is unused
since Q22 and always NULL. Pending means a caught, unacknowledged encounter with
no Pokémon row linked by `source_encounter_id`; existing stored catches are not pending.

`services.research.protected_reason(identity,pokemon,profile)` returns the first
applicable deployed, favorite, companion, shiny or legendary_or_mythical protection, else
None. `candidates(conn,profile_id,content,offset)` returns five owned rows with
their identities and protection reasons, plus the owned total. `send(conn,session,
picks,preview,now,content)` requires an active writer transaction; picks are UID /
revision pairs bound at display/selection and checked at review, with a UUID
preview ID and 120-second expiry in session selection. Review never silently
refreshes a selected revision. The send service returns a detached JSON result
with status sent or changed.
Owner/guild and exclusion are checked before receipt replay. Missing/changed rows,
revisions, expired reviews, empty/duplicate/over-20 batches or protected picks
return changed without any mutation or receipt. Only a single reviewed pick with
the explicit unlock flag may bypass shiny/Legendary/Mythical protection; deployed
Pokemon, favorites and the companion cannot be bypassed. Every candidate is checked before writing.
Success atomically marks each pick sent, increments its revision, adds one Candy
to its artifact family and a research_send ledger line, and stores owner-bearing
receipt research:<preview UUID> with action research. `send_pending` uses the same
owner-bearing receipt and inserts its row as sent, never owned. Stardust and the Pokédex
remain unchanged. Authorized receipt replay returns the original outcome even
after expiry or restart. Existing owned-only storage/capacity queries exclude sent
rows. No schema, content format or prior receipt changes are required.

M6.8r pending send: `send_pending(conn,profile_id,encounter,key,content)` requires
an active writer transaction. It copies the caught encounter into a new UUID Pokemon
row with state sent, revision 1 and caught_at equal to resolved_at, grants one family
Candy and writes one research_send ledger line atomically with the research receipt.
It returns `{status: sent, count: 1, candy: {<family ID string>: 1}, stardust: 0}`;
the same key replays that result without another row or credit.
`send_pending_reviewed(conn,session,picks,preview,now,content)` checks the current
profile owner, exclusion and saved preview/picks exactly as send, then replays an
owner-matching research receipt before expiry or pending checks. For a new send,
picks must equal `[["pending:<encounter_id>", encounters.revision]]` for that
profile's caught, unacknowledged encounter with no source Pokemon row. Shiny or
Legendary/Mythical encounters require saved single and preview unlocked. A refused
guard returns changed without writes. Success delegates to send_pending with key
research:<preview UUID>. This additive service has no caller until M6.8t/M6.8x;
existing send, receipts, rows and owned-only queries are unchanged. Tests: test_research.

M6.8x auto-send: `research.auto_send(conn,now,content)` scans caught encounters with
NULL acknowledged_at, no Pokemon row with the same source_encounter_id, shiny=0
and resolved_at+900<=now. It joins profiles for the guild/user owner, skips excluded
profiles (retrying next tick) and exempts Legendary/Mythical species forever.
Each eligible catch delegates to send_pending with receipt
research:auto:<encounter_id>, action research and the profile owner; its encounter
is acknowledged at now in the same writer transaction. It returns the sent count,
reads no clock, needs no session and sends no notice. A failed tick rolls back and
retries next tick; the first tick after restart catches up. Tests: test_research,
test_raids. Existing stored or acknowledged catches are never swept.

M7.7a adds `deployed` when `pokemon.gym_deployment_id` is non-null, ahead of all
other protections. A deployed pick returns changed for the entire send, including
an explicitly unlocked single; no Pokemon, Candy, ledger or receipt is changed.
Recall clears this protection; other protections and revision checks still apply.

## M2.3 power-up (additive)
`services.powerup.balances(conn, profile_id)` returns Stardust and Candy keyed by
integer family ID. `quote(conn, profile_id, pokemon_uid, content, multipliers)`
returns current hidden `level_x2`, canonical `cp_before`/`cp_after`, family ID,
costs and available balances, `at_cap` and `affordable`; absent owned rows return
None. Prices use the current hidden level in C4's lower-inclusive,
upper-exclusive bands. At 80, CP after and both costs are None and affordable is
false. No level is displayed to users.
`power_up(conn, session, pokemon_uid, expected_revision, content, multipliers)`
requires the caller's writer transaction. It rechecks guild/user/profile ownership,
exclusion, owned state, revision, cap and affordability. Refusals return status
stale, excluded, at_cap or insufficient with current owned Pokemon (or None),
without writes or receipts. Authorized duplicates return the owner-bearing
`powerup:<uid>:<expected_revision>` receipt (action powerup). Success returns
powered_up and the updated Pokemon, increments hidden level and revision by one,
debits family Candy and universal Stardust, and writes two negative powerup ledger
lines atomically. IVs, shiny, gender and other instance fields remain unchanged.
No schema or prior receipt formats change; C3 receipts remain compatible.

## M2.6 milestone inbox (additive)
D59 is produced by the catch job and consumed by private Walker rewards screens.
`services.milestones.due(caught_species_ids, earned_ids, content)` is pure and
returns `(milestone_id, lines)` pairs with resource/resource_id/quantity lines.
IDs are category:key: percent for pokedex, generation for starter_trios/regions/
mythical_sets, authored id for legendary_groups/extra_bundle_lines, species_id
for ultra_beast_first_catches, family_id for evolution_lines, and `all` for
all_starters/all_legendaries/all_mythicals or `first` for first flags.
Only caught installed species count; percentage thresholds round up using the
installed species total. Existing earned IDs remain earned across content changes.
`check_and_award(conn, profile_id, content, now)` requires the catch writer's
transaction: unique `(profile_id,milestone_id)` awards and all corresponding inbox
lines commit together. Enrollment does not trigger an award. Evolution-line
rewards and extra difficulty bundles are independent one-time milestones.
`claim(conn, session, now)` checks persisted session/profile/guild/user ownership
and exclusion inside the writer transaction before replay. Refusals return stale
or excluded without mutation. Success returns claimed with moved quantities by
resource and writes owner-bearing `claim:<session_id>:<revision>` receipts and
positive milestone_claim ledger lines. Stardust and family Candy move fully;
ordinary items fill the shared 250-unit bag excluding master_ball/shiny_lure.
Each rare pocket holds one; blocked quantities stay in the inbox unchanged.
Remaining rows decrement by exactly the credited amount and delete only at zero.
`waiting(conn, profile_id)` totals remaining quantities by resource for rendering.
`pending_count(conn, profile_id)` counts distinct milestones with any remaining
reward; Home labels this unit as milestones, so a partial claim still counts one.
Owner-approved screen amendment (2026-11-04): the private reward inbox lists each
milestone with remaining rewards by readable name, bundle tier when present, and
exact remaining item, Stardust, or family-Candy quantities. After Claim, the result
lists milestones and quantities moved during that invocation and milestones still
waiting, including partial movement when the bag or a rare pocket is full. The
screen derives movement from the before/after inbox rows around the existing claim
operation; claim mutation, owner-bearing receipts, and replay semantics do not change.
Both lists are capped at 15 milestone lines with a remaining-count indicator, within
Discord embed limits. Producers: milestone screen and content artifact; consumer:
private Walker reward inbox. Tests: tests/test_milestones.py.
Migration 0004 adds profile-cascading milestone_awards and inbox_items, preserving
existing data/receipts. Older binaries refuse the newer schema; rollback requires
a compatible backup, never a live schema-version decrement.

## M3.1 finds and bag grants (additive)
Migration 0005 adds `finds`: integer primary key find_id, profile_id referencing
profiles with cascade deletion, message_id, item_id, positive integer quantity,
outcome in granted/overflow/duplicate_rare/stardust, and UTC created_at. Index
`(profile_id,created_at)` supports the rolling hour. Existing rows and receipts
are preserved; older binaries refuse the new schema. Rollback restores a backup.

`services.items.bag_units(conn, profile_id)` sums ordinary inventory quantities,
excluding master_ball/shiny_lure. `grant(conn, profile_id, item_id, quantity)`
requires a writer transaction and returns `(outcome, stardust_delta)`. Quantity
must be a positive integer, and rare packs must contain exactly one. Rare items
fill a separate max-one pocket regardless of the 250-unit ordinary bag; a held
duplicate grants 500 Stardust instead. An ordinary pack fits wholly or grants
10 Stardust without any items. A stardust row grants its quantity without bag
units. These conversions are only for finds and check-in; milestone Claim keeps
its lossless inbox behavior and never calls grant. `roll_find(rng)` selects one
whole authored `find_table.json` row using its 9,750 relative weights, no rerolls.
Each find stores its selected item/quantity and actual outcome with an owner-
bearing `find:<message_id>` receipt (action find). Its positive item or Stardust
ledger line uses reason find, find_overflow or find_duplicate_rare respectively.
`recent_finds(conn, profile_id)` returns the last three detached rows ordered by
created_at descending, then find_id descending, only for that profile.

## M3.3 item conversion (additive)
D61's `services.items.convert(conn, session, item_id, quantity)` requires the writer
transaction and verifies persisted session ownership, profile and current exclusion
before replay or mutation. Only positive integer quantities of held inventory items
in C4's v1 conversion_rates table may convert; inbox rows are never debited.
Invalid/foreign/excluded requests return refused/stale/excluded status; insufficient
held quantity returns changed. These refusals write no receipt or resource change.
Success atomically debits inventory, credits rate times quantity Stardust, and writes
negative item and positive Stardust ledger lines with reason convert, using the
owner-bearing `convert:<session_id>:<revision>` receipt (action convert). It returns
`{item, quantity, stardust}`; authorized receipt replay returns that saved result even
after inventory changes or a restart. Existing schema and receipt formats remain
compatible. Producers are the conversion service; consumers are C5 bag handlers.

## M3.4 Shiny Lure (owner amendment 2026-11-04)
Migration 0006 is immutable historical time-window storage. Migration 0007 rebuilds
active_effects preserving every effect ID, profile, kind, starts_at, expires_at and
receipt_key, adds integer remaining_encounters constrained to 0..10, and indexes
(profile_id,remaining_encounters), with a partial unique index allowing at most one
positive counter per profile. New effects have NULL expires_at and ten charges.
Only the latest legacy activation per profile may retain charges, and only when
unexpired at migration time: max(0,10 - count of persisted encounters with that
lure_id). Latest means descending starts_at, then insertion order for ties. All
earlier effects and all expired effects receive zero, so a backward wall-clock
change cannot revive earlier activations alongside the latest. Encounters are retained
for the profile lifetime, so this uses durable consumption evidence without inventing
historical counts. Exhausted/expired effects never revive. Old receipts, inventory
and frozen encounters are unchanged; legacy receipt replay still returns its original
historical result. This intentionally breaks time-window behavior and the activation
result shape for new receipts. Rollback restores a compatible backup; older binaries
refuse the newer schema. Producers are migrations, item activation and stepping;
consumers are Bag, receipt readers and encounter generation.

`services.items.active_lure(conn, profile_id)` returns the effect ID or None
using remaining_encounters > 0, independent of wall-clock or message time.
`activate_lure(conn, session, now)` requires a
writer transaction and rechecks durable profile/session/guild/user ownership and
exclusion before receipt replay. Invalid ownership returns stale; exclusion returns
excluded. Inside the owner-bearing lure:<session_id>:<revision> receipt (action
lure), an existing effect with remaining_encounters > 0 returns already_active, otherwise
an empty pocket returns missing. Neither refusal consumes an item. Success returns
the effect dict and atomically consumes one shiny_lure, inserts ten remaining encounters, and
records one item delta -1 with reason lure_activate. Replays return the same result
without resetting its current counter. Each minted encounter decrements once inside
the stepping transaction; rollback and message deduplication preserve charges.
One held plus one active is permitted; duplicate finds still convert
to 500 Stardust. Producers are the item service and stepping; consumers are Bag and
encounter storage. Tests: tests/test_lure.py and tests/test_stepping.py.

## M4.1a write-ahead marker log (additive)
`services.marker_log` produces the external D28 JSON-lines log; deletion, startup
replay and restore consume it. No SQLite schema or existing caller changes.
`append_marker(path,kind,guild_id,user_id,now,*,profile_id=None,actor_id=None,
reason=None,marker_id=None)` returns its UUID4-bearing dict; kinds are delete/opt_out/opt_in/reset.
An optional pre-generated UUID4 lets the deletion job retain its identity even if
the append writes a full record but fsync fails. Omitted IDs are generated as before.
`append_void(path,marker_id,now)` invalidates that marker regardless of log position.
Both synchronous operations flush and fsync before returning, and first repair an
unterminated tail by truncating after the last newline, fsyncing and logging its
dropped byte count. They require an existing log; `create_empty(path)` exclusively
creates and fsyncs it (and the directory on POSIX), never truncating an existing log.
Guild/user/actor IDs are decimal text, optional profile IDs/reasons are text, and `at` is finite UTC
epoch seconds. Every unterminated final tail is uncommitted, even if valid JSON:
`fold` logs and ignores it, and the next append truncates it as described above.
For newline-terminated records, malformed/unknown records raise ValueError naming
their line; only an unparseable final line is logged and ignored. Filesystem failures
propagate. This corrects replay compatibility to match the owner-approved record
boundary: neither an unterminated marker nor an unterminated void has any effect.
`fold(path)` returns `(guild_id,user_id)` keys and `State` values: `delete_ids` is a
set of every non-null profile from valid delete/reset/opt_out markers; `opted_out`
is the last valid opt_out/opt_in boolean or None; `resets` is an ordered list of
dicts with marker_id/profile_id/actor_id/reason/at. Voids are collected before
folding, deletions accumulate, and receipts never determine replay validity.
This new file format is additive; no rotation, retention or old-format conversion
is introduced. Tests: tests/test_marker_log.py. Final feature qualification remains
separate from these focused file-format and durability checks.

## M4.1b deletion service (additive)
`services.deletion.run_marker(writer,path,authorize=None,**fields)` accepts the
`append_marker` fields except marker_id (generated by the job), and returns the
appended marker dict after commit. One writer
job awaits `authorize(conn)` when supplied; authorization refuses by raising, before
any marker or mutation. Before attempting append, the job retains a UUID4 identity;
it appends/fsyncs its marker, then applies its singleton state. Any BaseException
from append or application synchronously appends/fsyncs a void for that identity
before re-raising for rollback. A cancelled waiter never writes a void or cancels its job.
Writer abort during the job delivers cancellation into this handler. Commit failures
after the job returns leave a valid marker, the deletion-safe crash case for replay.
If void durability also fails, the job logs a critical recovery-required error,
stops writer admission, resolves queued callers without running them and terminates
with CancelledError chained to the void failure. This is an unresolved log failure,
not a durable cancellation: restart/replay may still apply the unvoided marker.
Operator recovery is required; the service never claims the log is safe to reuse.

M4.1 adds atomic current-profile selection: when `profile_id` is omitted for
`delete` or `opt_out`, `run_marker` looks up the current `(guild_id,user_id)` profile
inside that same writer job after authorization and before append. No profile
resolves to null. Explicit profile IDs, including explicit null, retain their
existing meaning; opt-in and reset are unchanged. Account commands consume this
additive behavior so queued enrollment cannot escape their deletion marker.

`apply(conn,states,*,replay=False)` requires an active writer transaction and accepts the
`{(guild_id,user_id): State}` mapping returned by `marker_log.fold`. It deletes exact
profile IDs with cascading rows/receipts, leaving restrictions and moderation audit.
D28 also redacts the deleted defender from other players' gym battle receipts and
session selections in that guild, including nested research `resume` selections.
Matching results retain their receipt key/owner, battle ID, terminal outcome,
attacker snapshots, survivors and claim, but set deployment_id and snapshot
deployment/defender/hours_held/defender_battle_hp to null and clear mixed-player
events (including gym_battles.events). Result/log renderers accept that redaction.
Stale view/party selections referencing the deleted deployment are invalidated.
Redaction and deletion share the transaction for delete, reset, opt-out and marker
replay, even when the marked profile is already absent. Other guilds, unrelated
results, later profile IDs and the D28/D60 raid participation exception are preserved.
This intentionally narrows immutable replay snapshots for privacy; replay of the
retained terminal receipt cannot simulate or reward another battle. No migration.
For each member, opted_out True inserts the minimal membership row if absent, False
removes it, and None preserves it. `opted_out(conn,guild_id,user_id)` returns a bool.
Each reset writes a user-targeted reset audit with its saved actor/reason/time under
NULL-owned `reset:<marker_id>` receipt, action reset. Only audit insertion is deduped;
deletion and participation always apply even if that receipt exists. Live audit
constraint failures propagate, so run_marker voids and rolls back the whole reset.
Only explicit `replay=True` tolerates an audit insert refused by a SQLite integrity
constraint: it logs and skips without losing deletion or blocking replay, and the
receipt records that audit attempt.

Migration 0008 adds `opt_outs(guild_id,user_id,created_at)` with a composite primary
key and no profile foreign key, plus `marker_log_init(id,at)` constrained to id=1
for M4.1c. Existing data is preserved; older binaries refuse the newer schema and
rollback requires a compatible backup. Opt-out insertion time is UTC epoch seconds;
an existing row's timestamp is retained. `Settings.marker_log_path` reads
POKEWALKER_MARKER_LOG, defaulting to the database's filename plus `.markers.jsonl`
beside it. It rejects the database path and its WAL/SHM/journal paths, including
existing file aliases. Producers are the deletion service/configuration; consumers
are account and moderator commands and startup replay. Tests: tests/test_deletion.py.

## M4.1c startup replay (additive)
`await services.deletion.replay_markers(writer,path)` runs on every bot startup,
after writer acquisition and before admission. In a writer job, a missing log with
no `marker_log_init` row is created and synced before recording id=1 and UTC epoch
time. A present log without that row records it (including restored older DBs);
an initialized DB with a missing log refuses startup with instructions to restore
the newest copy (D28). Initialization and filesystem failures propagate.
The existing `fold` corruption/tail rules apply. Each folded member gets one job
for exact-profile deletions and final participation, then one job per reset audit,
all through `apply(..., replay=True)`. Receipts only deduplicate audit insertion.
Audit constraint failures are logged and skipped; other failures refuse startup.
Interrupted replay is repeatable. Startup failure/cancellation drains the writer
and closes its connection without admitting events. Failed void durability still
requires operator recovery; automatic restart does not establish a safe log.
No schema or marker format changes. Producers: startup lifecycle and deletion;
consumers: account/moderation services and restored databases. Existing live-reset
audit strictness is unchanged. Tests: tests/test_replay.py and lifecycle regressions.

## M4.5a post-commit process observation (additive)
`Writer.run(fn, *, after_commit=None)` accepts an optional synchronous observer
of the detached job result. The writer calls it exactly once after COMMIT succeeds
and before resolving the waiter, including if that waiter has been cancelled.
It never calls the observer after a job/commit failure or rollback. Observers
perform bounded synchronous process-only bookkeeping; they cannot await or queue
writer jobs. Async observers are rejected before admission. Observer failures are
isolated from transaction outcome, emit only fixed privacy-safe diagnostic text,
and do not roll back committed work, fail its waiter or stop the writer.
Existing callers omit the argument and retain their previous behavior. Producers:
Writer; consumer: message aggregate counters. No schema/receipt format change.
Tests: test_db.py and message cancellation/commit/duplicate regressions.

## M6.8b persisted Pokemon forms (additive)
PLAN Q15 adds migration 0016: `pokemon.form_id` is nullable INTEGER, constrained
to NULL or a positive integer. NULL means the default form of `pokemon_id`;
all existing rows retain NULL and every other column value. Existing catch and
enrollment inserts leave it NULL. Evolution writes the target form from M6.8c.
`services.storage.identify(content,pokemon)` accepts dicts and SQLite rows,
including encounter rows without a form column. Missing/NULL forms retain the
existing first matching `pokemon_id` result (identities before evolution targets).
A non-NULL form matches both `pokemon_id` and `form_id`, including sprite selection.
Owned-Pokemon dicts include the nullable field; existing receipts are not rewritten.
Delete/reset cascades, receipt keys/replay and caller signatures are unchanged. Producers:
migration 0016 and, from M6.8c, evolution; consumers: storage, encounter/companion
screens and existing identity callers. Older binaries refuse the newer schema;
rollback requires a compatible backup. Tests: test_pokemon_forms.py and migration,
storage, evolution and walker regressions.

## M6.3a evolution transition (additive)
`services.evolution.options(content,pokemon)` returns unique source-identity recipes
whose gender is null or matches the stored gender. `quote(conn,profile_id,uid,edge_id,
content,multipliers)` returns edge_id, target identity, cp_before/cp_after, candy_cost,
candy_have, item, item_have and affordable, or None for an unavailable owned recipe.
Target gender variety, source IVs and level determine preview CP; no writes occur.
`target(content,pokemon,edge)` resolves both ids in `to_identity_id`, then the
stored gender's target variety. Quotes and recipe labels share this resolver;
preview sprites use the resolved target's own pokemon_id and form_id.
`evolve(conn,session,uid,edge_id,expected_revision,content,multipliers,now)` requires
an active writer transaction. Owner and exclusion checks precede authorized replay of
`evolve:<uid>:<revision>` (action `evolve`); owned state, revision, recipe and costs
are then checked. Refusals return stale, excluded, invalid or insufficient without
writes. Success returns status evolved and the updated Pokemon, changes only its
pokemon_id, form_id (the target record's form) and revision, spends Candy and exactly
the selected recipe item, writes evolve ledger debits, upserts target species caught
and checks milestone awards.
All changes and the receipt commit or roll back together. Companion identity and
catch provenance remain unchanged; no Stardust charge, Candy refund or XP is granted.
Producer: evolution service; consumers: evolution screens and owned-Pokemon callers.
No migration or existing receipt changes. Tests: tests/test_evolution.py.


## M6.4a evolution-item grants, purchases and conversion (additive)
D21/D55/D61 and PLAN Q2 extend the item service without a schema change.
`resolve_item(rng, item_id, quantity, content)` resolves `evolution_item` uniformly
among distinct `content["evolution_items"]` ids, preserving quantity; with no kinds
it returns `("stardust", 100)`. Other items pass through. Finds use the resolver
before grant and persist the concrete kind in the find, receipt and item ledger.
`rate_for(item_id, content)` returns the authored conversion rate, or the generic
`evolution_item` rate for a retained kind, or None. `convert(..., content=None)`
retains existing callers; absent content adds no named kinds. Star Piece converts
for 50 and named evolution items for 100; the World Legendary Ticket is refused.
`buy_evolution_item(conn, session, kind, now, content)` requires the writer and
persisted session/profile ownership; stale or excluded requests cannot replay.
An authorized `buy:<session_id>:<revision>` receipt (action buy) returns its saved
`{item, quantity: 1, stardust}` result before kind, balance or capacity checks.
Only retained kinds may be purchased (`refused` otherwise), at evolution.json's
500-Stardust price (`insufficient` if short). Full ordinary bags return `bag_full`;
refusals spend nothing, grant nothing, write no receipt and never convert overflow.
Success debits the price, adds one ordinary unit and writes negative Stardust and
positive item ledger lines with reason buy atomically with its owner-bearing receipt.
Producers: item service; consumers: stepping and the subsequent bag/gym handlers.
Compatibility: the new apply_finds argument is wired to both existing callers;
no persisted data migration or receipt-format change. Tests: test_evolution_items,
test_conversion, test_finds and test_stepping. UI purchase wiring is M6.4b.

## M6.5a Star Piece count model (additive)
D35 and the owner-decided PLAN Q3 replace the research time window with ten
Stardust rewards. Migration 0011 rebuilds active_effects, preserving all existing
columns, rows and both lure indexes; kind admits shiny_lure and star_piece.
remaining_rewards is an integer NOT NULL DEFAULT 0 constrained to 0..10.
Lures require remaining_rewards=0; Star Pieces require remaining_encounters=0.
The partial unique active_effects_one_star_piece index permits at most one positive
reward counter per profile. The independent counters let both kinds coexist.
New Star Pieces have NULL expires_at and never expire by time. Older binaries
refuse the newer schema; rollback requires a compatible backup.

`services.items.active_star_piece(conn, profile_id)` returns the active effect ID
or None, filtering kind=star_piece and remaining_rewards>0.
`activate_star_piece(conn, session, now)` requires the caller's writer transaction,
checks durable session/profile/guild/user ownership and exclusion before replay,
and returns stale/excluded without mutation when invalid. Its owner-bearing
star_piece:<session_id>:<revision> receipt (action star_piece) returns the saved
result before active-effect or held-item checks. Inside compute, an active Star
Piece returns already_active; an empty inventory returns missing. These saved
refusals consume nothing. Success returns the effect dict, consumes one item,
inserts ten remaining_rewards and zero remaining_encounters, and records an item
delta -1 with reason star_piece_activate, atomically. New lure result dictionaries
also include remaining_rewards=0; historical receipts retain their original shape.

`boost(conn, profile_id, amount)` requires the granting writer transaction. When
active it decrements once and returns amount*3//2; otherwise it returns amount.
Only catch Stardust and find stardust bundles qualify. apply_finds boosts such a
bundle before grant, persisting the boosted quantity in find history and its
ledger; item bundles, overflow and duplicate conversions never spend a reward.
Grant rollback restores the counter, and receipt replay never invokes boost again.
At zero the effect ends and another activation may consume a held Star Piece.
Producer: migration/item service; consumers: finds and the subsequent catch/Bag
row M6.5b. Profile scope preserves guild isolation. Tests: test_star_piece,
test_lure, test_finds, test_db and test_receipt_owner.

## M6.6a profile capacity expansion (additive)
D44 and PLAN Q4 add migration 0012: profiles.storage_limit and bag_limit are
INTEGER NOT NULL DEFAULT 250, with integer-type CHECKs and inclusive bounds
250..1000. Existing profiles receive 250 for both; other state is preserved.
Older binaries refuse this schema; rollback requires a compatible backup.

`services.capacity.limits_for(conn, profile_id)` returns storage, bag_units and
the authored rare_pockets, scoped to that profile. Missing profiles raise ValueError.
`quote(conn, profile_id, kind)` accepts storage or bag and returns current, next,
price, max, at_cap and affordable. Next is capped at max; price is the flat authored
5000/2500 Stardust for +50, and affordable is false at cap. Invalid kinds raise
ValueError for quotes; expansion returns refused without mutation.
`expand(conn, session, kind, expected_limit, now)` requires an active writer
transaction and verifies durable session/profile/guild/user ownership and exclusion
before replay (stale/excluded return without mutation). The owner-bearing receipt
expand:<session_id>:<revision>, action expand, returns its saved result before
current-limit, cap or balance checks. Inside compute, stale (current differs from
the previewed expected_limit), at_cap, or insufficient are saved without charging.
Success atomically debits Stardust, adds 50 to the selected limit, and returns
limits_for's new limits. Ledger lines record stardust -price and capacity +50
(resource_id storage or bag), both with reason expand_storage or expand_bag.
Failure rolls back limits, currency, receipt and ledger together. Rare pockets and
the other guild's profile are unchanged. Producers: migration/capacity service;
consumers: subsequent M6.6b-e callers/screens. Existing receipts stay compatible.
Tests: test_capacity.py, test_db.py and test_receipt_owner.py.

## M6.6b catch and grant capacity (compatible correction)
Storage and bag capacity are `profiles.storage_limit` / `bag_limit`. Catching
refuses only when the owned count is at least that profile's storage limit without
a confirmed storage warning (`selection.storage_confirm` equals the encounter revision),
before spending a ball or berry. Exclusion, terminal/stale and raid expiry checks stay
first. A confirmed catch stays pending without a Pokemon row or any storage overflow.
Ordinary find/check-in packs use that profile's bag limit;
overflow still converts the whole pack to 10 Stardust, and rare pockets are unchanged.
Evolution-item purchases use the same profile bag limit and refuse full bags without
spending or conversion. Producers: catching and item services; consumers: catch,
passive finds, check-in and evolution-item purchases. Existing receipts and persisted
formats remain compatible; capacities are isolated by guild profile.
Tests: test_capacity.py and catching/finds/checkin/evolution_items/storage regressions.

## M6.6c Claim profile capacity (compatible correction)
Claim uses `services.items.bag_units(conn, profile_id)` for ordinary units and
`services.capacity.limits_for(conn, profile_id)['bag_units']` for the profile's
`bag_limit`. It moves only the quantity that fits, leaving the remainder in the
inbox without conversion or loss. Master Ball and Shiny Lure retain their authored
rare-pocket limits. Ownership, exclusion, receipt replay and atomic ledger behavior
are unchanged; another guild's profile is unaffected. Producer: milestone service;
consumer: the existing private Claim handler. No schema, receipt format or caller
signature changes. Tests: test_capacity.py and test_milestones.py.


## M6.7b route-unlock backfill (intentional v1.1 data migration)
D45 and owner-approved PLAN Q5 add immutable migration 0013. On the first open
of a pre-0013 database, each profile whose current route requires more than its
own lifetime `coalesce(sum(step_events.awarded_c),0)` is moved to Refreshing Field.
Awards are integer hundredths, scoped by profile and therefore server (D10).
Refreshing Field and Noisy Forest are free; Rugged Road, Beautiful Beach,
Suburban Area, Dim Cave, Blue Lake and Volcano Path require 100000, 250000,
500000, 800000, 1200000 and 1800000 hundredths respectively. These ship-time
thresholds are copied deliberately into the migration and pinned to routes.json
by tests. At the exact threshold the current route is retained.

Only `profiles.route_id` changes: queued and revealed encounters keep every
frozen field, including their original route. Meters, items, receipts and all
other persisted values and schema remain unchanged. Running the SQL again
changes nothing; the ordered loader advances user_version to 13 atomically
and does not reapply it on reopen. No player notification is introduced.
Producer: migration 0013 through db.open_db; consumers: profile route selection
and future encounter minting. This deliberately changes locked existing route
choices without adding a schema or receipt format. Older binaries refuse the
newer version; rollback requires a compatible backup, never a version decrement.
Tests: test_route_unlocks.py, test_db.py, test_route.py and test_receipt_owner.py.


## M7.3 table-driven rare pockets (additive correction)
Rare kinds are the keys of `limits.rare_pockets` in `capacities.json`, captured
by `services.items.RARE` at import. These trusted release inputs include Master
Ball, Shiny Lure and World Legendary Ticket. All rare kinds are excluded from
ordinary bag units; their pockets remain separate from the profile bag limit.
Claim uses each rare kind's authored pocket cap, moving only what fits and
leaving the rest in the inbox without conversion or loss. A held World Legendary
Ticket blocks another ticket; two waiting tickets move one into an empty pocket.
Generic grants retain the one-per-rare-pack rule and duplicate-rare 500 Stardust
behavior; D60 ticket rewards use Claim, never the generic duplicate conversion.
The ticket has no conversion rate and cannot be converted. The bag renderer
consumes `items.RARE` and shows all three pockets. Producers: item and milestone
services; consumers: Claim and bag/conversion screens. Existing Master Ball and
Shiny Lure behavior, ownership, receipts and atomic ledger writes are unchanged.
No schema, signature or receipt format changes; existing rows remain readable.
Rollback to the old service would count tickets as ordinary inventory and must
therefore retain compatible rare-pocket handling. Tests: test_finds.py,
test_milestones.py and existing conversion/lure/capacity regressions.

## M7.4a gym schema and lifecycle (additive)
Requirements D10/D23/D24/D28/D30/D41 and approved PLAN Q7/Q10/Q13 add migration
0014, preserving existing rows. Gyms have a guild, unique guild-local name of
1..32 characters, UTC creation and optional retirement time. The authored
capacities.gyms.per_guild limit is 10 active gyms. Retired names remain reserved.
Deployments persist their original deployed_at and ends_at; tenure comes from
gym_income_table.tenure_seconds (28,800), never from process uptime. Composite
foreign keys bind each deployment and battle to the gym and profile in the same
guild. Partial unique indexes permit one active deployment per gym, profile and
Pokemon. Deleting a profile cascades its deployments, Pokemon and action receipts,
paying nothing. Battle defender references become NULL on deployment deletion.
Profiles gain nullable last_battle_at; Pokemon gain nullable gym_deployment_id.
SQL triggers abort state/level/species updates to deployed Pokemon and companion
assignment to any deployed Pokemon, including direct SQL bypasses of UI guards.

Producer: migration 0014 and services.gyms; consumers: future gym UI, admin,
income and battle services. Mutations require the caller's active writer
transaction. get_gym(conn,guild_id,gym_id) returns a detached row or None;
list_gyms(conn,guild_id) lists active gyms. create(conn,guild_id,name,now) returns
the created row or status invalid/duplicate/full. retire(conn,guild_id,gym_id,
now,rng,content) retires the gym and ends its active deployment as retired.
All UTC times are epoch seconds. No admin authorization or audit is introduced
here; the future admin caller supplies those checks in the same writer job.

Owner decision on 2026-11-05 deliberately extends the ticket signature to
`deploy(conn,session,gym_id,pokemon_uid,rev,now,content)`, following research.send's
explicit-content pattern. M7.5a passes walker.bot.content, respecting the configured
artifact instead of loading a hardcoded path. Exclusion and current profile owner
are checked before authorized `deploy:<session_id>:<gym_id>:<pokemon_uid>:<rev>`
receipt replay. The key identifies the target gym and Pokemon at its expected
Pokemon revision, so selecting another revision-0 Pokemon in the same session is
a new intent; incidental session revisions do not change replay identity. New deploys
require a current nonretired guild gym, owned Pokemon at revision rev, neither
companion nor Legendary/Mythical, and no active deployment for gym/profile/Pokemon.
Success returns status deployed and its deployment snapshot; failures write no
receipt or state. Deploy refusals are stale, excluded, companion,
legendary_or_mythical or occupied. Replay returns the saved result even after
retirement or return, without rerunning guards for a new deployment.

end_deployment(conn,guild_id,deployment_id,reason,now,rng,content) stamps the first
end, clears the Pokemon deployment reference and increments its revision; repeated
ends are no-ops. settle(conn,now,rng,content) ends expired deployments using their
stored deadlines. Callers settle before gym reads/mutations; the future sweep
runs it through the writer. Income and survivor rolls remain assigned to M7.4b.
Older binaries refuse schema 14; rollback requires a compatible backup, never
lowering user_version. Tests: test_gyms.py plus the database, catching, storage,
walker-encounter, receipt-owner and capacity migration regressions.

Owner decision on 2026-11-05 overrides the foreign-invalid ticket wording: a
missing or foreign gym/deployment returns stale, with no writes. No cross-guild
existence lookup distinguishes them. All target lookups and mutations use the
supplied guild; the process-wide settle scan dispatches each expiry with its
persisted guild. The caller therefore learns no foreign gym existence.


## M7.4b gym income and survivor inbox (additive)
Requirements D13/D23/D24/D59/D60 and approved PLAN Q2/Q8/Q9/Q13 extend
services.gyms without a migration. Producers are pay_hours and end_deployment;
consumers are the existing lossless milestones.claim and future gym handlers.
All mutations require the caller's active writer transaction and guild-scoped
lookups. Missing or foreign deployment IDs return stale without writes.

pay_hours(conn,guild_id,deployment_id,now,rng,content) pays active deployments
only, returning status paid and paid_hours. Completed hours are capped at 8 and
at ends_at. Each hour n has one owner-bearing gym_hour:<deployment_id>:<n>
receipt with action gym_hour. Its computation rolls gym_income_table, uses
items.resolve_item, inserts exactly one inbox_items row under
milestone_id gym_income:<deployment_id>:<n>, and updates paid_hours atomically.
Resource is item (named resource_id) or stardust (NULL resource_id), with remaining
set to the resolved quantity. It never calls items.grant or credits a resource
ledger; Claim records the move with milestone_claim. Full bags and held rare
pockets leave rewards waiting, never converted. Each hour adds one pending entry.
Ended deployments return status ended and cannot receive further income.

end_deployment pays completed hours before the first return except for excluded,
which permanently forfeits unpaid hours. Retired, recalled, mod_recall and defeated
ends pay hours but earn no survivor. Only expired at or after ends_at earns one
survivor_table roll plus its flat 500 Stardust, as two inbox rows sharing
survivor:<deployment_id>. survivor_rolled, both rows, completed hourly receipts,
ended_at/end_reason and the Pokemon return commit or roll back together. Retrying
a committed return (including after restart or a lost response) performs no roll,
award or second revision increment. Profile deletion cascades deployments, receipts
and inbox rows, crediting nothing. No existing schema or Claim semantics change.
Tests: test_gyms, test_milestones and test_screens. Full G-F2 and live gates remain.

## M7.6a gym battle settlement (additive)
D10/D23/D30/D32/D40b/D41 and PLAN Q6/Q7 add
`battle(conn,session,gym_id,expected_deployment_id,party,nominee_uid,now,rng,content,
multipliers,rules,chart)` in services.gyms; settlement and defeat payouts roll with rng. The caller owns the active writer
transaction; party is an ordered list of `(pokemon_uid,revision)` pairs. The
session's Start revision (`_original_revision` when the router has incremented
`revision`, otherwise `revision`) identifies the logical intention in the
owner-bearing `battle:<session_id>:<Start revision>` receipt, action battle.
Different Start revisions are different intentions, never Pokemon revisions.
Current guild/user/profile ownership and exclusion precede receipt replay;
authorized replay returns the saved result before settlement or any new guard,
including after defeat, replacement, cooldown, changed Pokemon or restart.

For a new intention, settle expired deployments, then require a nonretired gym
in the session guild, the exact active expected deployment, another holder,
and at least 600 seconds since the challenger's last completed battle. Missing
and foreign gym IDs are indistinguishable (status invalid), with no cross-guild
existence lookup. A replaced/ended/absent deployment or changed Pokemon revision
returns stale; own gym, invalid party or nominee returns invalid; cooldown and
exclusion return cooldown and excluded. Profile mismatch returns stale. Every
refusal leaves all state unchanged, including settlement, receipts and cooldown.
Party has 1..3 distinct owned Pokemon, none companion or deployed. Legendary and
Mythical Pokemon may attack but cannot be nominees; a nominee must be in party.

Combatant snapshots use C7 combat_stats, first-type fast and charged templates,
canonical CP/HP and frozen full hours held at Start for defender_hp. The receipt
retains ordered Pokemon IDs/form_id/revisions/content versions, combatants, deployment,
nominee, frozen HP and hashes of configured content, multipliers, rules and chart.
PLAN Q15 snapshots carry nullable form_id for each attacker and defender so result
names and sprites resolve the exact form. Legacy snapshots without form_id keep
the default form; receipt replay retains the saved snapshot after Pokemon changes.
Simulation runs synchronously inside the writer job. gym_battles stores its UUID,
guild/gym/deployment/challenger, outcome, reason, ticks, ordered events and engine.
Result status completed includes these fields, survivors, snapshot and claimed.
Every completed outcome sets last_battle_at=now. Win returns the defender as
defeated, pays completed hours with no survivor reward, and deploys the preselected
nominee even if it fainted, provided the challenger holds no other gym. Otherwise
claimed=false means cleared; loss/draw retain the defender and party unchanged.
Settlement, history, cooldown, return/income, optional claim and receipt commit
or roll back together. No new schema or existing API change; producer is the
service, consumer is the future M7.6b handler. Tests: test_gym_battle.py,
test_gyms.py and test_battle.py; final G-F2 and live acceptance remain separate.

## M7.7b deployed progression protection (additive)
D30 and discord-gym-design section 1 protect deployed Pokemon from power-up and
evolution. Both services check current ownership and exclusion, then return any
authorized saved receipt before checking gym_deployment_id. For a new operation,
a non-null deployment reference returns stale with the current Pokemon, before
revision, recipe, cap, affordability or mutation; no resources, ledger or receipt
change, and the SQL protection trigger is not reached. Receipt replay after a
later deployment returns the original saved success without spending again.
Evolution options remain unchanged while deployed. After recall clears the
reference, power-up and evolution work at the current revision. The direct SQL
state/level/species protection remains in force throughout deployment.
Producers: powerup and evolution services; consumers: their existing private
confirmation handlers, which already handle stale. No schema, signature or receipt
format changes; existing receipts remain compatible. Tests: test_powerup,
test_evolution and test_gyms. Full G-F2 and live acceptance remain separate.

## M8.1a raid schema and queue isolation (additive)
D28/D60 and Q11/Q12 add migration 0015. Guilds default raids_enabled to 0
(constrained to 0/1), with nullable raid_channel_id. world_spawns stores spawn_id,
guild_id (guild deletion cascades), the checked channel_id, pokemon_id, identity_id,
spawned_at/expires_at UTC epoch times, content_version, nullable message_id,
post_state (pending/attempted/sent), and ended (0/1, default 0). A partial unique
index permits only one ended=0 spawn per guild. spawned_by_profile_id references
profiles ON DELETE SET NULL: deleting its creator preserves the complete spawn,
including its destination, expiry and announcement state; it never cancels/refunds it.

raid_participation has primary key (guild_id,user_id,spawn_id), joined_at and nullable
encounter_id. It has no profile FK; deleting a profile retains participation while
its encounter FK becomes NULL. Re-enrollment cannot acquire another participation
for the same user/server/spawn. Participation is retained only until spawn expiry;
the later expiry service removes it. Deleting a spawn cascades participation and
the encounters referencing it through nullable encounters.raid_spawn_id.

Both queue triggers count only queued/revealed encounters whose raid_spawn_id IS
NULL, and guard only incoming ordinary rows. Insert and updates to state,
profile_id or raid_spawn_id preserve the three-ordinary-encounter limit, including
conversion of a raid row to ordinary. queue_size uses the same predicate. Existing
ordinary rows and their rolls are unchanged; raid rows are outside this queue.
Producers: migration 0015 and profiles.queue_size; consumers: stepping, home and
moderation queue counts, and later raid services. No cross-guild lookup is added.
Older binaries refuse schema 15; rollback requires a compatible backup, never
lowering user_version. Tests: test_raids and database/profile/stepping/fixture
migration regressions. G-F2 and live Discord acceptance remain separate.

## M8.2a spawn and expiry service (additive)
D60/Q11 adds `raids.spawn(conn,session,now,rng,content,checked_channel_id)` within
an active writer transaction. Durable session/profile/guild/user ownership and
current exclusion authorize the owner-bearing `wlt:<session_id>:<revision>` receipt
(action wlt_use). Authorized replay returns the saved `{status: spawned, spawn}`
before expiry, configuration, active-spawn or inventory guards. Missing and foreign
session/profile requests both return stale. No cross-guild existence lookup occurs.
New attempts first expire their guild's overdue spawn, then refuse raids_off,
no_channel, no_permission, channel_changed, active, or missing in that order. Each
refusal keeps the ticket. Success uniformly selects one Legendary identity,
excluding Mythicals and ignoring routes, consumes one world_legendary_ticket and
inserts a pending spawn with checked channel, content version and now+3600 expiry,
plus one item -1 ledger line with reason wlt_use. Rollback restores every effect.
`expire(conn,now,guild_id=None)` is the sole settlement helper: at expires_at<=now
it deletes queued/revealed raid encounters and participation, retaining terminal
encounters and ordinary encounters, and marks the spawn ended. It returns counts
under spawns, encounters and participation; repeated calls return zero counts.
Producers: raids service; consumers: later ticket UI, raid command and sweep.
Existing schema and ordinary encounter rules are unchanged. Tests: test_raids.

## M8.3a raid join and catch deadline (additive)
D60/Q12 adds `raids.active_spawn(conn,guild_id,now)`, returning the server's
unended spawn only while expires_at>now, otherwise None. No foreign-server
existence lookup occurs. `raids.join(conn,guild_id,user_id,now,rng,content)` requires
an active writer transaction. It returns status none without an active spawn,
not_enrolled without a server/user profile, or excluded for an excluded member.
These checks precede participation/replay. Existing participation returns joined
and its encounter_id, including NULL after profile deletion/re-enrollment, with
no new rolls or writes. New participation uses the owner-bearing
`raid:<spawn_id>:<user_id>` receipt (action raid_join), returning new and encounter_id.
It rolls the spawn's exact identity with the existing gender, shiny, level and IV
helpers, consumes one remaining active Lure encounter, and saves a revealed
Legendary/Mythical encounter with raid_spawn_id, the profile's route and the loaded
content version. Species seen_at is inserted only when absent. Encounter, Lure,
Pokédex, participation and receipt commit or roll back together; ordinary queue
capacity does not apply. Producers: raids service; consumers: private raid command
and normal catching. No migration or existing receipt-format change is required.
`catching.throw` returns expired for an owned, currently revealed raid encounter
whose spawn expires_at<=now, before item checks or spending, even before cleanup.
Terminal outcomes take precedence, so a catch committed before expiry remains
readable after expiry settlement. Ordinary catching is unchanged.
Tests: test_raids, test_catching and test_lure. G-F2/live acceptance remain separate.


## M8.4 raid expiry sweep and retention (additive)
D28/D60 and Q10/Q12 schedule `raids.expire(conn,now)` after `gyms.settle`,
then `research.auto_send`, in the same writer transaction on each existing
60-second sweep. All receive
one UTC epoch `now` from `walker.clock`; the bot monotonic clock is not used.
Expiry deletes queued/revealed raid encounters and participation, including the
server/user/spawn record retained after delete-data. A deleted spender leaves
NULL attribution on the preserved spawn history; species, times, channel and
announcement state remain. Ended history no longer blocks a new spawn.
Deleting unfinished encounters cascades catch attempts, but preserves previously
spent items and their action receipts/resource ledger. An expired panel cannot
spend before cleanup; Run and shiny Confirm Run refuse it, leaving it eligible
for cleanup with no terminal recovery result. Ordinary queue entries are unchanged.
A catch committed before expiry keeps its Pokemon, rewards, terminal encounter
and recovery/acknowledgement path. No schema or receipt format changes.
Producer: client sweep and raids.expire; consumers: catching, walker recovery,
queue and deletion. Tests: test_raids plus walker acknowledgement, deletion and
gym regressions. G-F2 remains pending until the owner commits the privacy
retention disclosure; this contract is not runtime privacy text or live evidence.

## Trading schema (0018, additive)
The owner's trading requirement (R0-R5, docs/features/pokemon-trading/PLAN.md
P1/P4/P6/P7/P11) adds migration 0018, preserving existing rows. trades has
trade_id, guild_id (guild deletion cascades), initiator_profile_id and
partner_profile_id, state open/completed/cancelled/expired (default open),
revision (default 0), created_at, expires_at (must exceed created_at) and
nullable ended_at, all UTC epoch seconds. Composite foreign keys bind both
profiles to the trade's guild through profiles(profile_id,guild_id); deleting
either profile deletes the trade and its sides.

trade_sides has primary key (trade_id,side), side 0 or 1, the side's profile_id,
nullable joined_at, pokemon_uid, pokemon_revision and confirmed_revision, and
open 0/1 (default 0). open=1 requires joined_at. (trade_id,profile_id) is unique,
so one profile never fills both sides. Composite foreign keys bind each side to
its trade and to a profile in the same guild, cascading deletes. pokemon_uid has
no foreign key: a Pokemon is deleted only with its profile, which cascades the
trade. The partial unique index trade_sides_one_open allows at most one open=1
side per profile; unjoined sides (open=0) are unlimited, so an invitee is never
blocked. The trade_close_sides trigger sets open=0 on both sides whenever a
trade's state is updated to anything other than open.

trade_channels has guild_id (guild deletion cascades) and channel_id, primary key
(guild_id,channel_id); no channel is enabled by default. Profiles gain nullable
last_trade_at and last_trade_ping_at REAL.

The pokemon_trade_guard trigger aborts with "Pokemon is not tradable" any update
that changes pokemon.profile_id while the Pokemon is not owned (sent), is
favorited, is gym-deployed, is any profile's companion_uid, or would move to a
profile in another guild, including direct SQL bypasses of service checks.
Updates leaving profile_id unchanged are unaffected.

Producer: migration 0018; consumers: the later trading service, trade-channel
admin commands, sweep and deletion. No existing writer changes pokemon.profile_id.
Older binaries refuse schema 18; rollback requires a compatible backup, never
lowering user_version. Tests: test_trading_schema plus the receipt-owner,
companion, capacity, database, form, route-unlock, gym and deletion regressions.

## Trading service (additive)
docs/features/pokemon-trading/PLAN.md OD4/OD9 and P2/P5-P7/P11/P13 add
pokewalker/services/trading.py. Every mutator requires the caller's writer
transaction, checks the Walker session owner (session_owner: stale/excluded)
before any other guard, and takes one UTC epoch `now` from Walker.clock.
Constants: TRADE_SECONDS=900, CAP_SECONDS=86400, PING_SECONDS=600. Activity is
`expires_at=MAX(expires_at,now+900)` (15 minutes idle); join and offer run it.
Expiry is lazy on touch: an open trade with expires_at<=now becomes expired
with ended_at=now, and the trade_close_sides trigger frees both members.

tradable_reason(identity,pokemon,profile) returns not_owned for a missing,
sent or foreign Pokemon, else deployed/favorite/companion from
research.protected_reason, else None; Shiny and Legendary/Mythical stay
tradable. eligible_page(conn,profile_id,offset) returns ten tradable owned
Pokemon ordered caught_at DESC,pokemon_uid (filtered in SQL) with the eligible
and owned totals. cap_left(profile,now) is the whole seconds left until
last_trade_at+86400, else 0; cancelled and expired trades never set
last_trade_at.

open_or_join(conn,session,partner_user_id,now,can_ping) refuses, in order:
stale/excluded; partner_not_enrolled (no profile in this guild); self;
partner_unavailable (partner excluded). It then expires either member's due
trades. If an open trade between the pair exists: a caller already joined gets
reopened; an invited caller gets capped (with seconds_left), partner_capped,
busy (joined elsewhere) or joined (joined_at=now, open=1, activity). Otherwise a
new trade refuses busy (the caller's own trade partner as partner_user_id),
capped, partner_capped or partner_busy (no partner identity or time revealed),
and else inserts the trade (expires_at=now+900) with exactly two sides: side 0
the caller (joined, open=1) and side 1 the named partner (joined_at NULL,
open=0, so an invitee is never blocked); you can never open a trade with
yourself. Only opened carries ping: reserved when can_ping and the opener's
last_trade_ping_at is NULL or <=now-600 (then set to now), else no_permission
or rate_limited. Joined and reopened never ping.

current(conn,session,now) returns the caller's joined open trade with its
sides, expiring it first when due, or None. offer(conn,session,trade_id,
pokemon_uid,now) refuses a non-participant or unjoined caller as stale, an
expired trade as expired and a completed/cancelled one as ended; a Pokemon
failing storage.detail or tradable_reason at offer time returns ineligible with
its reason and writes nothing; otherwise it pins the caller's
(pokemon_uid,pokemon_revision), clears both confirmed_revision values, bumps
the trade revision, runs activity and returns offered. cancel(conn,session,
trade_id,now) lets a joined participant move an open trade to cancelled with
ended_at=now. No receipts, items or resources are written. Producers: trading
service; consumers: later trade execution, screens and /trade (T4-T7). No
schema change. Tests: test_trading and test_trading_schema.

## Trade execution, cap and deletion (additive)
docs/features/pokemon-trading/PLAN.md OD4/OD9 and P3-P5/P7/P9/P10/P14 add
confirm(conn,session,trade_id,seen_revision,now,content) to
pokewalker/services/trading.py, run as one writer job. It refuses, in order: a
non-participant or unjoined caller as stale (after session_owner
stale/excluded); a completed trade as {status: completed, trade_id} (so a
double accept is idempotent), a cancelled one as ended and an expired one as
expired; a trade revision other than seen_revision as changed; a side not yet
joined or without an offer as incomplete; capped (with seconds_left) or
partner_capped under the 24 h cap; and partner_unavailable when the partner is
excluded, which also clears the caller's confirmation. Apart from lazy expiry
and that cleared confirmation, these refusals write nothing.

Otherwise it sets the caller's confirmed_revision to the trade revision and
runs activity (expires_at=MAX(expires_at,now+900)). If the partner has not
confirmed this revision it returns waiting with the trade_id. When both have,
it re-checks each side in side order: the pinned Pokemon must still pass
storage.detail for its owner, tradable_reason with its storage.identify
identity, and the pinned revision (a revision change reports changed, a sent
or moved Pokemon not_owned). Set companion bumps no revision, so the companion
check is explicit. The first failing side gets
{status: offer_invalid, side, reason}: that offer is cleared, both
confirmations are cleared and the trade revision is bumped, and only that
cleanup, together with the confirm's activity extension, commits; nothing
moves.

The swap then, in the same job: sets last_trade_at=now on both profiles where
it is NULL or <=now-86400 and requires exactly two rows; moves each offered
Pokemon to the other member with revision+1, restating owner, pinned revision,
owned, not favorite and not deployed, and requires exactly one row each;
acknowledges each moved Pokemon's unacknowledged source encounter (none when
NULL) so the giver's catch recovery never resurfaces it; and marks the trade
completed with ended_at=now and revision+1, which closes both sides. A guard
miss raises and the writer rolls back the whole job, including the
confirmation and activity; pokemon_trade_guard is the second backstop. A
completed trade caps both members until last_trade_at+86400; exactly 86400 s
later they may trade again. No receipt is written, and no Candy, Stardust or
items move. A 1-for-1 swap leaves each owned count unchanged, so a full Storage
does not block it. A traded Pokemon is no longer the old owner's, so their
later actions on it find nothing (stale).

Deleting either profile cascades its trades and sides, so the partner is free
to trade again. A received Pokemon stays with its receiver after the giver's
deletion, with source_encounter_id set to NULL, and the receiver's
last_trade_at survives. Producers: trading service; consumers: trade screens
and /trade (T6-T7). No schema change. Tests: test_trading, test_deletion,
test_trading_schema.

## Trade Pokédex credit, view and prune (additive)
docs/features/pokemon-trading/PLAN.md OD5/OD6 and P6/P8 (D15 amended by owner
decision 2026-11-12: receiving a Pokemon in a trade counts as seen and caught)
extend pokewalker/services/trading.py. Inside confirm's swap job, after both
owner UPDATEs, each receiver gets the received Pokemon's species from
storage.identify (regional and other forms fold to their species) through the
catch upsert: INSERT INTO pokedex(profile_id,pokemon_id,seen_at,caught_at)
VALUES (receiver,species,now,now) ON CONFLICT(profile_id,pokemon_id) DO UPDATE
SET caught_at=COALESCE(caught_at,excluded.caught_at), which keeps seen_at and
any earlier caught_at. check_and_award then runs for both receivers in the same
job, so newly completed milestones are awarded to milestone_awards and the
inbox in the trade's commit, or not at all when the job rolls back. The giver's
Pokedex entries are never touched. Milestones pay once per profile, so one
Pokemon passed around pays each profile at most once (owner-accepted). A
refused confirm (waiting, offer_invalid, any refusal or a rolled-back swap)
writes no Pokedex entry and no award.

view(conn,session,trade_id,now,content,multipliers) is read-only and
participant-only: after session_owner, a caller who is not a joined side of the
trade in the session's guild gets None. Otherwise it returns a detached dict
(plain values, no rows): trade_id, state (an open trade with expires_at<=now
reads expired; view itself writes nothing), revision, expires_at, my_side,
partner_user_id, partner_joined, mine and theirs (each None without an offer,
else storage.stats of the pinned Pokemon plus special flags shiny, legendary,
mythical and starter for origin starter, OD6), my_confirmed and
partner_confirmed (confirmed_revision equals the trade revision), and received
({name, cp} of the partner's Pokemon once completed, else None).

prune(conn,now) runs in the writer: it marks every open trade with
expires_at<=now expired with ended_at=now, then deletes every trade that is
not open and ended at or before now-86400 (sides cascade). Ended trades are
thus deleted a day after they end; profiles.last_trade_at is untouched, so the
24 h cap survives pruning. The 60 s sweep calls it (T7).

Return shapes clarified for the trading service above: both busy outcomes of
open_or_join (new trade, or an invited caller joined elsewhere) carry the
caller's own current trade partner as partner_user_id; offer returns
{status: offered, trade_id, revision} with the new trade revision; current
returns None on a session refusal (stale or excluded) as well as when there is
no joined open trade. Producers: trading service; consumers: trade screens,
/trade and the sweep (T6-T7). No schema change. Tests: test_trading,
test_milestones, test_pokedex.

## Owner amendment: Rare Candy power-up (2026-11-12)
The owner directed that one Rare Candy powers up a Pokemon one step. `quote` also
returns `rare_candy_have` (the profile's `rare_candy` inventory quantity) and
`rare_affordable` (not at cap and at least one held). `power_up(...,
use_rare_candy=False)` keeps every existing guard; with `use_rare_candy=True` the
affordability check is `rare_affordable` instead of Candy and Stardust, and refusals
are the same statuses (`insufficient` when none is held). Success increments hidden
level and revision by one exactly like an ordinary step, removes one `rare_candy`
inventory unit, leaves family Candy and Stardust unchanged and writes one
`item`/`rare_candy` ledger line of -1 with reason powerup. It shares the
`powerup:<uid>:<expected_revision>` receipt, so one Pokemon revision can be powered
up once by either method. No schema change. Tests: tests/test_powerup.py.

## Owner amendment: Companion Mirror (2026-11-12)
The owner added a Companion Mirror to the gym survivor roll (C4). `companion_mirror`
is an ordinary stackable Bag item, not a rare pocket, and converts at 500 Stardust.
Migration 0019 rebuilds active_effects, preserving every column, row and effect ID
and recreating the active_effects_profile_remaining, active_effects_one_active and
active_effects_one_star_piece indexes. kind also admits `companion_mirror`, which,
like shiny_lure, requires remaining_rewards=0; remaining_encounters stays 0..10.
Lures and Mirrors are both encounter effects under active_effects_one_active, so a
profile has at most one positive remaining_encounters counter. Older binaries
refuse schema 19; rollback requires a compatible backup.

`services.items.active_mirror(conn, profile_id)` returns the effect ID or None,
filtering kind=companion_mirror and remaining_encounters>0.
`activate_mirror(conn, session, now)` follows activate_lure: it requires a writer
transaction and rechecks durable ownership (stale) and exclusion (excluded) before
receipt replay. Inside the owner-bearing `mirror:<session_id>:<revision>` receipt
(action mirror), any effect with remaining_encounters>0 (Lure or Mirror) returns
already_active; otherwise an empty pocket returns missing. Neither refusal consumes
an item. Success returns the effect dict (kind companion_mirror, NULL expires_at,
remaining_encounters = catch rules `mirror_encounters` (10), remaining_rewards 0),
atomically consumes one companion_mirror and records one item delta -1 with reason
mirror_activate. Replays return the saved result. activate_lure is unchanged and so
returns already_active while a Mirror is active.

`stepping.spawn_encounter` (message steps and /checkin) decrements an active
Mirror's remaining_encounters once for every generated encounter, in the generating
transaction, so the effect ends after ten encounters; a full queue generates none
and spends nothing. For each generated encounter `encounters.mirror_hit` draws
`rng.random() < mirror_probability` (0.2). On a hit the profile's companion_uid is
read at generation time; its family (via storage.identify) selects
`encounters.mirror_pools(content identities, family_id)`: identities of that family
whose tier is Common, Uncommon or Evolved and that are neither Legendary nor
Mythical, so the Legendary/Mythical and Rare (for example Ultra Beast) tiers never
qualify. Non-empty pools go to `encounters.generate_mirror`, which picks the tier
with roll_tier over the candidate tiers with the Legendary draw set to zero, then
an identity uniformly within that tier. Route weights are ignored. Gender, shiny
(ordinary odds), level and IVs roll as for any encounter. A miss, no companion or
empty pools generate the ordinary route encounter. The encounter keeps the
profile's route_id and a NULL lure_id; queued encounters never change. Producers:
migration, item service and stepping; consumers: Bag, receipt readers and
encounter generation. Tests: tests/test_companion_mirror.py, tests/test_lure.py,
tests/test_star_piece.py.

## Owner amendment: admin force raid (2026-11-12)
`raids.force_spawn(conn,guild_id,actor_user_id,reason,now,rng,content,
checked_channel_id)` runs within an active writer transaction and shares `spawn`'s
guards and insert. It first applies the per-server cooldown: it reads the newest
mod_audit row with this guild_id and action force_raid; while now is less than that
row's created_at+86400 it returns `{status: cooldown, remaining}` (seconds until the
next allowed force) before any other read or write. Exactly 86400 seconds later is
allowed. The cooldown is shared by every administrator of the server, is independent
per server and starts only at a successful force. Then, like `spawn`, it expires the
guild's overdue spawn and refuses raids_off (also when the guild has no row),
no_channel, no_permission, channel_changed and active in that order; a refusal
inserts no spawn and no audit. Success selects one Legendary identity, excluding
Mythicals and ignoring routes, exactly as `spawn` does, inserts one pending
world_spawns row with the checked channel, content version, now+3600 expiry and
spawned_by_profile_id NULL, and in the same transaction one mod_audit row (target_kind
guild, target_id the guild ID, actor_id, action force_raid, the caller's stripped
reason, created_at now). It consumes no item and writes no ledger line or action
receipt, returning `{status: spawned, spawn}`. Rollback removes both rows. The ticket
path's receipt, guards, order and effects are unchanged. No schema change: mod_audit
already admits target_kind guild and has no action constraint. mod_audit rows survive
member reset, account deletion and opt-out; only deleting the guilds row cascades
them, and no application path deletes it, so those paths cannot bypass the cooldown.
Producers: raids service and WalkerAdmin; consumers: `/walker-mod log`, announce and
resume_pending, raid join. Tests: tests/test_admin_force_raid.py and test_raids.

## Owner amendment: raid boss minimum level (2026-11-12)
The owner found sub-100 CP World Legendaries underwhelming and set a hidden minimum
of level 20 (half the level-40 cap, roughly half of maximum CP). `raids.join` rolls
each participant's level from catch rule `raid_level_range` [20, 25] (whole levels,
stored as `level_x2` 40-50) instead of `wild_level_range`; IVs, gender and shiny roll
as before, and no level is displayed. Existing raid encounters keep their rolls.
Ordinary wild encounters are unchanged. Tests: tests/test_raids.py, tests/test_encounters.py.
