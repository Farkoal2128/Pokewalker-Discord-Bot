# Contract: Discord command and lifecycle boundary (C5)

## C5: M8.3b private World Legendary join and reopen (additive)
Under D60 and Q12, guild-only `/raid` defers ephemerally before its writer job.
It joins using Walker.clock(), Walker.rng and the configured content artifact.
No live spawn in this guild says "No World Legendary is active here." Unenrolled,
excluded and opted-out members receive the existing private enrollment/access refusal.
`/raid` with a pending catch opens its menu without joining. After opt-out and,
for an existing profile, exclusion checks, it creates a normal Walker session and
opens the pending menu before looking for a spawn; no participation, raid encounter
or Lure use occurs. A pending World Legendary survives spawn expiry and is exempt
from auto-send, holding the catch lock until confirmed.
A saved encounter must belong to the current guild/user/profile and live spawn;
missing and foreign encounters are indistinguishable and reveal no foreign existence.
For a joined participation with NULL, missing or foreign encounter, say "You already
joined this World Legendary; it can be joined once." No reroll or replacement occurs.

Live queued/revealed encounters use render_catch with "World Legendary · ends <UTC>";
every render_catch of a raid encounter (ball/berry select and pick included) keeps that line.
Resolved caught/ran encounters use the existing recovery render_terminal: Done (plus
Send for research while the caught Pokémon is owned),
no catch controls. Each successful open persists a normal Walker session with revision
0, expiry now + 900 and selection {encounter_id, ball: poke_ball, berry: null,
encounter_revision}. Existing DynamicItem/Walker.route handles every button, including
Later to home and Done to acknowledgment. Reopening preserves encounter rolls/results.
The command is registered next to checkin and included in the command manifest.
Producer: raid command; consumers: private members, C3 join, Walker sessions/screens.
Existing commands and persisted formats remain compatible; no migration is required.
Tests: test_raids, test_walker_encounter, test_client_lifecycle, test_readme.
Focused evidence leaves G-F2 and live Discord acceptance open.

## Owner amendment: readme (2026-11-05; paged 2026-11-12, OD1)
The guild-only `/readme` command privately displays the approved `content/help.md`
text to any member, including unenrolled or excluded members, without consulting
profile state. The file holds pages separated by a line containing exactly
`<!-- page -->`. Startup loads that fixed repository-relative file and refuses it
(with an error naming help) when it is missing or unreadable, has fewer than two pages,
or any page is blank or over 4096 UTF-16 code units; check-config applies the same load.
`WalkerBot.help_page(i)` renders page i (0-based) as an embed titled
`Pokéwalker help (i+1/N)` plus Prev/Next buttons with unique stateless IDs
`pw:readme:v1:<target>`, disabled at the first and last page. Clicking one edits the
private message to that page with no writer, profile, session or restriction lookup;
an out-of-range page (for example after a help edit) gets a private "Run /readme again."
The last page, "Server setup (admins and moderators)", names every `/walker-admin`
and `/walker-mod` subcommand; the owner-only `/admin` group is not documented.
`/readme` and the one-time private send after starter confirmation both show page 1;
the normal home screen remains available. The command is part of the global command
manifest. The paging revision is compatible and does not alter persisted data.
Tests: test_readme, test_walker_router, test_account, test_client_lifecycle.

## M4.4 opt-in shares and post-commit effects (additive)
Transaction handlers may return an after_commit zero-argument async callback in
their render dictionary. Walker.route removes it and awaits it only after writer.run
successfully returns, outside the writer task; its returned dictionary becomes the
private response. The per-session lock covers that effect and edit. Refusals, job
errors and commit failures never call it. Effects may themselves queue writer jobs.
Cancellation/crash after commit can leave delivery unconfirmed and never refunds
the reservation or automatically retries a send.

Owned storage details show an enabled Share only when guild sharing is on and the
member is not share-banned; no result screen shows Share (Q22 (2)). Fled/ran/sent
Pokemon never show it. The handler rechecks current
session-profile ownership, restrictions, guild sharing, Pokemon ownership and the
minute cap in the writer transaction. Missing EMBED_LINKS plus SEND_MESSAGES (normal
channel), or EMBED_LINKS plus SEND_MESSAGES_IN_THREADS (thread), explains privately
without writing. The component interaction carries the originating /walker channel.
Each accepted fresh reservation posts one public embed there with AllowedMentions.none().
Its title is '<name> caught|shares <Name>'; text includes name, form, gender, shiny
state, CP, catcher and UTC catch date. The image uses the pinned artifact's exact
form/gender/shiny sprite, or none, with complete text in either case (D48).
Success reports Shared. HTTP/transport/rate-limit failure reports unconfirmed delivery, that
a message may already exist, and that the minute remains spent; it never retries.
Existing component IDs and handler return dictionaries remain compatible.
Producers: share handler, Walker router, catch/storage renderers; consumers: Discord
members and moderation sharing flags. Tests: tests/test_share.py and walker regressions.

## M4.3 administrator reset and sharing (additive)
`/walker-admin reset member reason [confirm=false]` accepts a Discord User option,
including a user who left the server (owner ruling 2026-11-04). The target is the
stored profile for the interaction guild and user ID; membership is not required.
`/walker-admin sharing on|off reason` changes only that guild's sharing flag.
Both defer privately before writer waits, require runtime Manage Server, refuse
an excluded actor at entry and again in the mutation job, require a stripped
nonblank reason, suppress mentions and reply after commit. Sharing accepts only
on/off and audits target_kind=guild with action sharing_on/sharing_off atomically.
Reset without confirmation names the target, collection count, Stardust and lost
profile/items/progress, warning it cannot be undone. Missing enrollment writes
nothing. Confirmation rechecks authorization and resolves the current profile
in the same writer job as the fsynced D28 reset marker, deletion and reset audit.
The marker saves actor/reason; audit uses the existing NULL-owned reset receipt.
Append/application failures attempt a durable void inside the job before rollback.
Commit-phase failure or cancellation after the job returns leaves the marker valid
for replay, as does a crash before commit. If void durability also fails (including
both marker and void fsync failures), writer admission stops and operator recovery
is required; replay may still apply the unvoided marker. Startup replay deduplicates
audit while applying deletion. Restrictions, opt-out choice and prior audit remain.
Producers: WalkerAdmin and the deletion service; consumers: server admins and
startup replay. Existing command shapes and marker formats remain compatible;
the User option deliberately permits departed targets. Tests: test_admin_reset_sharing.py.

## M4.2 member moderation (additive)
`WalkerMod` registers `/walker-mod` locally without sync, guild-only with Moderate
Members defaults. `pause <member> <reason> [duration]`, `resume`, `exclude`,
`include`, `share-ban`, and `share-unban` require a nonblank reason. Pause choices
are indefinite (default), 1h, 24h and 7d. `status <member>` and `log [member]`
require no reason and write no audit. Every handler defers ephemerally before
waiting for the writer, checks guild/Moderate Members at entry and again inside
its writer job, and refuses an excluded actor inside that same job. Targets must
belong to the interaction guild. Replies suppress mentions and fit 2000 characters
using private follow-ups as needed; failures never report success before commit.
Status returns enrollment, effective pause/until, exclusion, share ban, credited
steps (hundredths divided by 100) for the last hour and total, base steps discarded
by anti-farming in the last hour, unresolved queue size, successful catches and
last five user audit actions. Per the owner-approved metric correction, discarded
base steps sum `discarded_words` only for `minimum`, `cooldown`, `minute_cap`,
`duplicate` and `credited` (including partial repeat/message-cap discards); paused
and missing-timestamp discards are excluded. The metric uses the current profile,
includes both endpoints of `[now-3600, now]`, and applies no step multiplier.
Log returns the guild's latest 25 actions, optionally user-target filtered,
ordered by time then audit ID descending. Both serialize reads through the writer
and expose only IDs, game aggregates and moderation audit fields, never messages.
Producers: moderation handlers; consumers: Discord moderators and existing
restriction-aware services/router. No schema or existing command changes.
Tests: tests/test_mod.py and profile/router regressions. Live acceptance remains G-3.

## Producers and consumers
`pokewalker.bot.client.WalkerBot` produces Gateway/interaction adapters;
Discord, deployment CLI operators and later command handlers consume them.
M1.2 and PLAN P10/P11/P13 authorize this initial additive boundary. No existing
production clients or persisted formats change.

## Invariants
- Component IDs match `^pw:v1:(?P<session>[0-9a-f-]+):(?P<rev>\d+):(?P<action>[a-z_]+)$`.
  The interaction's guild/user and durable session authorize an action; an ID is
  never permission. M1.6 supplies routing; until then clicks get a private reopen response.
  A separate grammar is the stateless readme page ID `^pw:readme:v1:(?P<page>\d+)$`;
  it never reaches the Walker router and authorizes nothing beyond showing a help page.
- Intents are exactly guilds, guild_messages and message_content. Message caching
  is disabled. Commands are guild-only, replies ephemeral, with runtime permission
  rechecks. Later command rows define their permissions and handlers.
- Credentials prefer stripped `$CREDENTIALS_DIRECTORY/discord_token`; only an
  absent credential file falls back to stripped `DISCORD_TOKEN` with a WARNING.
  Empty tokens fail closed. Token and settings representations mask credentials.
- Settings read DB/content paths, comma-separated positive owner IDs, development
  guild ID, and the explicit `0|1` unpatched-SQLite override. No development guild
  means production: an empty owner allowlist refuses startup.
- Setup verifies the artifact's raw-byte SHA256 against its sibling content
  manifest before admitting work, opens the database, starts one writer and
  registers one dynamic component handler. Setup never synchronizes commands.
- SIGTERM/SIGINT enter one idempotent drain: stop admission, drain accepted
  writes, close Discord and DB. The shared deadline is 20 seconds. Timeout
  aborts the writer with transaction rollback and is an explicit failure, never
  a clean drain. Successful ordinary shutdown exits 0; restart drains then exits 75.
  Stopping is permanent: in-flight setup cannot restore admission, and acquired
  startup resources are cleaned before drain succeeds. Serve and sync delegate
  all final connection cleanup to this same bounded path.
  A signal that interrupts startup still exits 0 after a successful drain;
  unrelated caller cancellation, genuine startup failures and drain failures
  remain observable failures.
- Only `sync-commands --guild ID|--global --yes` may bulk synchronize commands.
  The CLI prints the selected command manifest SHA256 before confirmation. It
  authenticates without connecting the Gateway; reconnects never synchronize.
  `run` starts the Gateway; `check-config` validates without network access.

## Compatibility and verification
M1.4b creates one `ReactionService` after database setup. The first Gateway ready
event runs its pending-reaction startup sweep once; setup itself never waits for
Gateway readiness. Shutdown cancels and awaits an active sweep before draining
the writer. Partial messages add/remove the bot's own reaction directly by saved
channel/message IDs without fetching the message or needing Manage Messages.
An uncached channel may be fetched to resolve its thread parent for add policy.

Later tickets append their command contracts.

M4.5b adds a background health loop, started once on the first Gateway ready event
and cancelled/awaited before writer shutdown. Every 60 seconds it queues a no-op
through the writer with a 5-second timeout. Only a completed probe and current
Gateway readiness establish health. With `RUNTIME_DIRECTORY` set, the loop touches
`ready` when healthy and removes it when unhealthy or stopped. Without a heartbeat
URL, the same health loop and readiness file still operate. A configured URL is a
masked `Secret`, read from `CREDENTIALS_DIRECTORY/heartbeat_url` or, only if absent,
`POKEWALKER_HEARTBEAT_URL` with a secret-free warning. Healthy loops GET the URL
with a 10-second timeout and no body; monitoring failures never block gameplay,
and sanitized failure logs occur at most once per hour. The loop owns its HTTP
session; injected sessions remain caller-owned. No persisted data changes.

Removing an ID grammar/version, changing scope or authorization, or changing
exit meanings requires an intentional contract revision and consumer tests.
`tests/test_config.py` and `tests/test_client_lifecycle.py` exercise this boundary
using synthetic credentials and fake I/O only. Live Discord acceptance remains G-3.

## M4.1 account controls (additive)
`/walker-account privacy|delete-data [confirm=false]|opt-out [confirm=false]|opt-in`
is registered locally, guild-only, without a permission gate. Every handler defers
ephemerally before waiting on the writer, then edits its original response only
after commit. Text suppresses mentions; long privacy text uses private follow-ups
of at most 2000 characters, split after a line break when one fits. Missing guild context changes nothing.
`Settings.privacy_path` reads `POKEWALKER_PRIVACY_PATH`; unset, unreadable or blank
text refuses startup before database acquisition. Setup reads UTF-8 text once;
`check-config` validates it too. The owner supplies and approves that text; loading
a draft does not approve it. Privacy returns the supplied text, including to excluded users.
Without confirmation deletion and opt-out name the lost profile, Pokémon, items
and progress and retained moderation history, restrictions and opt-out state.
Confirmed commands use `run_marker`, resolving the current server/user profile
inside its writer job. Opt-out writes a marker even without a profile; delete-data
preserves participation state. Both remain available to excluded users.
Opt-in checks current exclusion inside `run_marker` authorization before any log
append; refusal writes no marker. Otherwise its marker clears opt-out idempotently
and directs the member to `/walker` for fresh enrollment. Walker entry and enrollment
check opt-out within their transactions before creating sessions or replaying receipts,
and instruct the member to run `/walker-account opt-in` first. The component router
also checks durable opt-out inside its dispatch transaction, after owner, revision,
expiry and exclusion checks but before any handler or session write. This includes
profile-less onboarding sessions that survive opt-out; refusal is private and changes
no session or player data. Opt-in permits those otherwise valid sessions again.
Excluded members may
use privacy, delete-data and opt-out, but never opt-in. This extends the earlier C5
exclusion explanation. Other command/component permissions remain unchanged.
Failure propagates without a success reply; existing marker/void durability failures
and operator recovery requirements remain C3's responsibility. Producers: account
handlers, configuration and startup; consumers: Discord members, enrollment and
the existing deletion/replay service. Tests: tests/test_account.py and related
deletion, replay, profile, lifecycle and router regressions. No schema changes.

## M1.4 channel configuration (additive)
`WalkerAdmin` is registered on the client's local tree at construction, without
synchronizing. `/walker-admin channels add <channel> <reason> [count=true]
[react=true]`, `remove <channel> <reason>`, and `list` are guild-only and ephemeral.
The root command defaults to Manage Server and every handler rechecks the member's
`manage_guild` permission. Channels must belong to the interaction's guild.
Per P15, excluded members receive a private refusal for all three commands.
Exclusion is read at entry through a writer-serialized query, and checked again
inside each add/remove transaction before any policy or audit mutation.
Reasons are required command parameters; empty/whitespace reasons are refused.
Add upserts both flags; remove deletes the policy. Each executes as one writer
job, atomically inserting `mod_audit` with guild, actor, channel target, action
`channels_add|channels_remove`, stripped reason and UTC epoch time. List reads
only that guild's policies through a read-only writer job, rechecks exclusion in
that same job, and writes no audit. Serializing reads after pending writes keeps
uncommitted or rolled-back policies out of responses. Replies suppress mentions; large
lists use private follow-ups below the Discord message length limit.
Missing Add Reactions or Read Message History produces a skip-reactions warning;
the configured react preference is retained for later permission recovery.
`tests/test_admin_channels.py` covers schemas, runtime authorization, transaction
rollback, private responses, warning and local registration. Producers are the
channel handlers; consumers are Discord moderators and profile/counting services.
This adds commands without changing IDs, schema or existing lifecycle behavior.

Q21 adds guild-only, private `/walker-admin channels add-all <reason> [count=true]`.
It defers, applies the same entry authorization and stripped nonblank reason rule,
then fetches the actor through `guild.fetch_member` before queueing the mutation.
HTTPException (including NotFound and Forbidden) refuses with "Could not confirm
your Manage Server permission. Nothing was changed." Fresh member roles must grant
Manage Server or it refuses with "Manage Server permission is required."
Role permissions use the Guilds-intent cache. The owner accepts the residual window
where a role removed between fetch and commit is not observed; add/remove keep their
existing permission checks. One writer job rechecks exclusion, upserts the guild,
and enables only `guild.text_channels` (text and announcement, excluding threads,
forums, voice, stage and categories) where the bot has View Channel. Each newly
enabled channel gets the requested count flag, react=true and one `channels_add`
audit with the stripped reason, atomically. Existing policies are untouched and
unaudited; repeating adds nothing. The mention-suppressed reply is "Enabled N
channels; skipped M (no access); K already enabled. Channels created later are not
added automatically." ("1 channel" when N is 1). There is no reaction warning or receipt table. Registration
stays local; after delivery the owner runs `sync-commands --global --yes`.
`tests/test_admin_channels.py` covers eligibility, fresh-member refusals, exclusion
while queued, idempotence, flags and whole-batch rollback. This is additive for
moderators and profile/counting consumers; no persisted schema changes.

## M1.6 private walker sessions (additive)
`/walker` is registered locally, guild-only, and immediately defers ephemerally,
then edits its original response. Excluded members get only the account privacy /
delete-data explanation, without creating a session or changing reactions.
Other users get a UUID session for the interaction guild/user, optional profile,
revision zero and a 15-minute expiry. Opening marks every remaining profile reaction
for removal in the same writer job; reconciliation happens after commit and never
reveals or consumes an encounter. Legacy rows without an encounter ID use the public
`ReactionService.reconcile_message(message_id)` seam; completed removals remain retired.

The one generic `WalkerItem` wraps both selects and buttons with the existing ID
grammar. Each callback acknowledges the update before waiting on the writer.
The router validates ID, durable owner and guild, expiry, revision, current exclusion
and allowed action inside its writer transaction. Refused clicks change no state and
get an ephemeral explanation, except an outdated revision, which is dropped silently;
expired or unknown sessions ask the user to reopen `/walker` (see the session idle
timeout amendment). Successful handlers increment the session revision once. Edits per session are
serialized so a delayed response cannot overwrite a newer screen.

Onboarding routes before a profile exists: nine generations, three matching starters,
then confirmation. Selection is persisted in `sessions.selection`; confirmation calls
the receipt-backed profile enrollment and attaches that profile in the same transaction.
Invalid selections and repeated/stale confirmation cannot grant a second kit.
Home displays the companion name and CP, its artifact's exact gender/shiny thumbnail
or none, queue occupancy (queued plus revealed), encounter meter, and pause duration.
Only Open encounter is enabled when the queue is nonempty; Storage, Bag, Pokédex and
Route remain disabled. Pause never blocks queued encounter actions.
Home has no Claim button (Q20, M6.8o); Inbox → Claim is the claim entry.

`Walker.handlers` contains transaction callbacks `(conn, session, interaction)` that
return rendered screen dictionaries; successful handlers may update the detached
session's profile/selection. M1.7 supplies the encounter handler. Until installed,
Open encounter privately reports unavailable and changes nothing. `Walker.before_home`
is an optional transaction callback `(conn, session)` returning a recovered rendered
screen or None; M1.9 installs result recovery before home by default.
Screen functions accept detached state and return `dict(embed=..., view=...)` without I/O.
The router, render, reaction and client lifecycle tests cover this additive boundary;
no schema migration or ID version change is required. Live acceptance remains G-3.

## Owner amendment: session idle timeout (2026-11-12)
The owner reported the stale-window refusal appearing on windows in active use.
A Walker session now expires after 15 minutes without a successful action rather
than 15 minutes after opening: every committed router dispatch raises `expires_at`
to at least the router clock plus 900 seconds (never shortening it) in the same transaction as its revision.
Read-only replays keep their stored expiry. A click whose revision differs from
the stored revision on an owned, unexpired session changes no state. Within 10
seconds of the last committed action (its expiry minus 900 seconds) it is a double
press or a press racing the newer screen's edit: it sends no message and leaves the
screen to the newer response. Later, the screen really is outdated (for example a
lost edit), and it is refused with "This screen is out of date. Please reopen
/walker to refresh." Expired or unknown sessions are refused with
"This window timed out. Please reopen /walker for a fresh one." Handler-level
refusals for an option that no longer applies say "That option changed since this
screen opened. Please reopen /walker to refresh." instead of calling it stale.
Tests: tests/test_walker_router.py. No schema, ID grammar or manifest change.

## M1.7 encounter screens (additive)
The registered `open_encounter` handler reveals the oldest unresolved encounter by
`created_at` (including older revealed rows). A first reveal marks its species seen;
reopens preserve the encounter's frozen identity, rolls and revision. Session
selection stores `encounter_id`, `encounter_revision`, `ball` and nullable `berry`.
Ball/Berry open a small selector listing only items currently in stock; the Berry
selector also always offers `none`. Ball is disabled when no balls are in stock.
Choosing an allowed item updates only selection, without inventory consumption;
the catch transaction rechecks inventory for stale screens. Opening buttons use `select_ball` / `select_berry`;
their selectors use distinct `pick_ball` / `pick_berry` IDs routed to the same handlers.
Later returns home without changing the encounter.
Catch screens show name, form, gender, shiny text, CP, types, tier, exact sprite or
none, bag counts and choices. Levels remain hidden. M1.8 supplies the Throw handler.

Run on a shiny first stores a session confirmation and shows the named target.
Confirming requires that prior confirmation. Ordinary Run needs no confirmation,
including Legendary/Mythical encounters. The action checks ownership, exclusion,
unresolved state and the session's encounter revision inside the writer transaction
before any receipt or mutation. A stale encounter returns current persisted state;
a terminal encounter shows its saved caught/fled/ran result, with the caught Pokemon
when applicable. Unauthorized ownership/exclusion is privately refused without data
disclosure. Success atomically stores `run:<encounter_id>:<expected_revision>`, sets
`ran`, timestamps resolution and increments the encounter revision once. Pokédex and
inventory are untouched. Repeated competing screens cannot overwrite resolution.
`render_catch`, `render_run_confirm` and `render_terminal` consume detached state.
These additive C5 consumers use existing IDs, sessions, writer and receipt contracts;
no schema or content format changes. `tests/test_walker_encounter.py` covers them.
Failed Run guards leave every table unchanged, including sessions: the handler marks
its detached session `_read_only` and restores `_original_revision` supplied by the
router before rendering. The router skips its session update for this result. These
private routing keys are never persisted; the returned controls keep the saved session
revision. Successful handlers retain the existing single session revision increment.

## M1.8 Throw and Master Ball (additive)
`throw` invokes the catch service inside the existing writer job, then renders only
after commit. Selecting Master Ball first renders a separate confirmation naming
the target; `master_confirm` requires the saved confirmation for that encounter and
revision. Changing items or reopening clears confirmation. Confirmation repeats all
service guards and consumes the rare item once. Terminal/stale guard results leave
the session unchanged as in M1.7. Missing inventory/capacity responses explain the
refusal and retain current controls. Full storage shows "Storage is full (owned/limit).
A catch will wait for Send for research or Upgrade storage." with only Confirm throw
and Back. The warning saves `storage_confirm` for this encounter revision; Confirm
throw uses `master_confirm` after Master Ball confirmation, otherwise `throw`. Back
and reopening clear the flag, and every new encounter revision warns again. A confirmed
catch opens the pending Send for research / Upgrade storage menu directly.
Failed surviving throws say it broke free and refresh bag counts and encounter
revision for another throw. Caught results show exact sprite, CP, appraisal stars,
Candy and Stardust gained. Done routes to M1.9's `ack` handler when installed;
Share remains disabled until M4.4. Catch renders live in `screens_catch.py` and
remain re-exported by `screens.py`, preserving existing renderer consumers.
No custom-ID format or schema change is introduced. Fake Discord and SQLite tests
cover response failure after commit and Catch/Run ordering; live acceptance is G-3.
The M1.6 stale component-ID contract still applies: replaying an old session revision
is privately refused with the reopen explanation. Saved terminal outcomes are returned
by the catch service and by a competing screen with a valid session revision. The
ticket's broad "second click" wording does not bypass session authorization/versioning.

## M1.9 terminal recovery and acknowledgment (additive)
The default `before_home` callback checks the profile's terminal encounters with
NULL `acknowledged_at`, ordered by `resolved_at` then encounter ID. `/walker` and
`home` show the oldest result before the home/queue screen. Recovery uses the
Pokemon linked by `source_encounter_id` and the successful catch attempt's receipt
ledger reward lines, never cached session data, current balances or receipt reward
snapshots. Its controls are Done (`ack`) and, while the Pokémon is owned or pending, Send for
research (`catch_send`); normal result screens dispatch the
same action. The recovered encounter ID is persisted in session selection.

The router's existing owner/guild, exclusion, expiry and revision checks apply.
`ack` validates the selected encounter belongs to the profile and is terminal,
then sets its acknowledgment time only while NULL, in the same writer transaction
as the session update. Repeated acknowledgment from another valid screen retains
the original timestamp and cannot acknowledge the next result. It renders the next
unacknowledged result, else home with Open encounter enabled for a nonempty queue.
Commit precedes the Discord edit, so failed edits and fresh Walker instances recover
without another catch, reward or roll. `tests/test_walker_ack.py` covers this boundary.
No ID grammar, renderer export or schema change is required; live acceptance is G-3.

M6.8s replaces M6.8k's overflow choice with a pending-catch menu. With room it shows
exactly Done (`ack`) and Send for research (`catch_send`); Done stores the encounter,
acknowledges and saves the session in one transaction. At full storage it says
"Storage is full (owned/limit). Choose one:" and shows exactly Send for research and
Upgrade storage space (+50, 5,000 Stardust) (`catch_upgrade`). The menu saves the
encounter ID and quoted storage limit, without disabled catch controls or Share.
Upgrade is disabled with "Not enough Stardust." or "Storage is at the maximum
capacity." It rechecks pending status and the quoted limit, then expands, stores,
acknowledges and saves the session in one transaction using the existing expansion
receipt. Refusals show "Nothing was spent." A stale Done at full storage shows the
menu with "Nothing was stored." Recovery renders pending results with this menu;
a throw leaving a pending catch responds with it directly, including read-only
replays. Stored legacy results retain their existing Done and Send behavior.
Recovery prioritizes pending catches before other unacknowledged results, then
uses oldest resolved time and encounter ID. Fresh `/walker` and Home open the menu
directly. While a catch is pending, `open_encounter`, `select_ball`, `select_berry`,
`pick_ball`, `pick_berry`, `throw`, `master_confirm`, `run` and `run_confirm` open
that menu without changing another encounter or spending resources. Storage, Bag,
gyms, research and Pokédex remain usable; the pending catch is invisible there.
If the session already holds that pending catch's saved menu selection (encounter
ID and quoted storage limit), interception is read-only: no revision or session
write. Otherwise, including an older screen whose throw selection names the same
encounter, it saves the pending selection and advances the revision normally, so
the menu buttons resolve the pending catch.
Tests: test_capacity.py. Catch creation remains unchanged until M6.8u.

## M2.1 private storage (additive)
Home enables its Storage, Bag, Pokédex and Route buttons only when their action is
registered in `Walker.handlers`; Storage is now registered, including the catch
capacity notice's Storage link. Direct renderer callers omitting `available` retain
the prior disabled placeholder behavior. Existing session owner/guild, exclusion, expiry
and revision guards apply to every storage action before reads or writes.
`storage` opens offset zero; `storage_page` advances ten and `storage_prev` moves
back ten. The offset stays in `sessions.selection`. Pages list only that profile's
owned Pokémon, ordered by descending catch time then UID, ten per page, with the
owned count out of 250, name, CP, shiny/favorite markers and no image. Navigation
is disabled at bounds; an empty page has no open selector. `storage_open` accepts
only a UID on the current page, and owned detail queries repeat the profile guard.

The `Favorites only` / `Show all` toggle stores its mode beside the offset in
session selection and resets paging to zero. New `/walker` sessions start in All.
Filtered pages query only owned favorites, show `n favorites`, and display `No
favorites yet` when empty. Opening details and returning with Back preserve the
filter; unfavoriting removes the row when returning to the page. Research selection
continues to use its independent all-owned candidate query.

Details show name, form, gender, shiny state, CP, HP, appraisal stars, types,
UTC catch date and favorite state, never level. The embed image uses the exact
identity/gender/shiny sprite key or no image, without substitution. Favorite and
Back occupy the first action row; research and power-up are enabled by M2.2/M2.3,
companion is enabled by M2.4 and share remains disabled on the second. Back from details returns to the saved
page; Back from a page returns home. Render functions consume detached state
without database, file or network I/O.

`storage_favorite` toggles only an owned row matching the profile, UID and
`pokemon_revision` saved in selection, increments the Pokémon revision once and
returns the updated detail. A stale revision, sent row or different owner returns
no service row and writes nothing; the handler privately requests reopening.
Competing valid sessions cannot toggle from the same Pokémon revision twice.
The shared `services.storage.identify` lookup preserves home and encounter sprite
behavior, including gender varieties. These additive boundaries use existing
schema and component IDs; `tests/test_storage.py` plus the walker suites cover
them with synthetic Discord I/O. Live Discord acceptance remains G-3.

## M2.2 research screens (additive)
The storage page exposes Send for research. Research pages show five owned rows
with protection reasons and disabled protected toggles. Each displayed toggle is
bound in session selection to its exact Pokémon UID and revision, independently
of later query ordering; removed or revised targets are refused without writing.
Selection persists across pages with a maximum of twenty picks. Review checks
the selected revisions before storing exact UID/revision picks, a
UUID and now+120 expiry, displays names/forms, CP, appraisal, identifiers, Candy
by family, count, zero Stardust and irreversible removal, then Send N Pokémon.
Confirmation rechecks all service guards. Changed/expired picks send none and ask
for a new review; cancellation returns to storage unless entered from a catch.
A repeated displayed
confirm after commit, including a lost reply and restart, retains M1.6's stale
revision refusal without a handler call or write. Reopening /walker then storage
shows the sent Pokémon absent and their Candy credited once. Service duplicates
with the same reviewed selection return the receipt.
Details enable storage_send only for non-favorites other than the companion.
Ordinary single sends require a review/confirm. Shiny or Legendary/Mythical singles
first show a named status warning and Unlock, then a second status warning and
storage_send_confirm. The shared protection predicate guards both flows; the
companion and favorites are never overridable. Single-Pokémon warnings include
the exact sprite or none. Existing session authorization and component ID grammar
apply; research_toggle_a through research_toggle_e resolve the five saved UID /
revision bindings rather than current page positions. No live Discord effects
or migrations are introduced.

M6.8g: Superseded by Q22 (M6.8v); M6.8w deletes the handlers.

M6.8j adds row-1 Send for research (`catch_send`) after Done on every caught result,
including `/walker` recovery and `/raid` reopen, while its linked Pokémon is owned or pending.
On a pending catch the same flow sends through `send_pending_reviewed`; the Pokémon
is inserted as `sent`, never owned.
Fled, ran, sent and legacy states without a Pokémon keep their existing controls.
The handler rechecks encounter ownership and caught/owned-or-pending state, then opens the
existing Details single-send flow for that exact UID/revision, retaining
`caught: {encounter_id}`. Existing protections, shiny/legendary Unlock warnings,
120-second preview expiry and research receipts apply unchanged. With `caught`,
New review rebuilds the same Pokémon's single review, never the bulk picker;
successful confirm restores `{encounter_id}` and shows the existing sent/Candy
text with only Done (`ack`). Cancel restores that encounter selection and returns
through home, whose recovery shows the result again. Done acknowledges the result
before the next result or home; recovery still shows no Share or catch controls.
The storage-full Send-for-research `resume` flow and `catch_research`,
`catch_expand_storage`, and `catch_return` are superseded by Q22 and removed in M6.8w.
Research without `caught` returns to Storage on success or cancellation; storage
expansion Back and success always return to Storage. Producers: terminal renderer
and research handlers; consumers: private sessions, existing research service and acknowledgment.
No schema, receipt or component ID grammar change. Tests: test_capacity,
test_walker_ack and test_raids; live Discord acceptance remains a separate gate.

M7.7a research pages label the deployed protection as "deployed at a gym" and
disable its toggle. Single-send refuses with "Recall it from the gym first";
deployed Pokemon never enter the Shiny/Legendary unlock flow. Review, unlock and
confirmation recheck deployment protection, including picks deployed after selection.

## M2.4 companion selection (additive)
The details `companion` action calls `set_companion`: the selected UID must be
owned by the session profile, in owned state, and match its saved Pokemon revision.
It changes only `profiles.companion_uid`, preserving the profile's Candy meter
and the Pokemon revision. Selecting the current companion succeeds idempotently.
Details show a Companion badge when selected; the next home render shows its
name, CP and exact thumbnail. Legendary/Mythical companions are allowed (D41).
Stale/sent/foreign picks refuse privately without writes. Existing session owner,
guild, expiry, revision and exclusion checks apply. No gym rules are added.

## M2.3 power-up screens (additive)
Details enable `power_up`. It quotes the selected owned UID/revision as
CP before → after · Candy cost (have quantity) · Stardust cost (have quantity),
without visible levels. Confirm (`power_up_confirm`) is disabled at cap or when
unaffordable; Back (`storage_detail`) returns to the same owned details.
Confirmation uses the saved Pokemon revision and service transaction guards;
success returns details with recalculated CP and saved updated revision. Refusals
privately request reopening. Existing stale-session, owner/guild and exclusion
guards apply, including after a lost response and restart; receipts prevent
service retries spending twice. Rendering consumes detached state with no I/O.

## M2.5 private species Pokédex (additive)
Home enables Pokédex when its handler is registered. Existing session owner/guild,
exclusion, expiry and revision guards apply before any Pokédex read. Summary counts
seen and caught species for the profile, with total from the installed `species` map.
Pages list only persisted Pokédex species, ordered by species ID, twenty per page;
queued but unrevealed encounters are absent. Each text line carries the species ID,
default name, seen/caught status and UTC date. Lists have no image or thumbnail.
Prev/Next navigate pages; the selector accepts only one species on the current page.
Entry reads repeat the profile/species guard and return None for unseen species.
Entries show the default identity's name, types, generation, seen/caught UTC dates
and its normal sprite or no image, even when only a regional form was seen.
Missing default identities are content-contract errors, never substituted forms.
Back from an entry restores its page; Back from a page returns home. Renderers
consume detached state without I/O. Reads never change Pokédex dates or entries;
Run, flee and research sending preserve them (D15). No schema or ID grammar change.

Owner amendment (2026-11-05): Pokédex adds a read-only Milestones list containing
every compiled milestone, grouped and paged ten per page. Each entry shows its
inbox-readable name, bundle tier, and either its earned UTC date or missing status
with progress computed by the same predicates as milestone awards. Completed,
Missing and All filters reset to the first page; Back returns to the prior Pokédex
page. The list only reads caught species and milestone_awards; it never awards or
claims rewards. Reads do not mutate profile, inbox or award state.

## M3.1 private find summary (additive)
Home displays the profile's last three finds, newest first, including the selected
pack and outcome. Overflow is labeled as 10 Stardust; duplicate rare as 500
Stardust; direct Stardust shows the amount; granted packs show their item count.
There is no public find message and no Bag interaction in this slice. Reads are
profile-scoped and do not award items or change find history.

## M3.2 private check-in (additive)
`/checkin` is registered locally, guild-only, ephemeral and takes no options.
It defers ephemerally before waiting on the writer, then edits that original
response after the writer completes. Replies suppress all mentions.
Unenrolled users are directed to `/walker`;
excluded and paused members are refused, with the pause end or indefinite state.
Cooldown refusals show the remaining seconds until the next check-in.

`services.items.checkin(conn, guild_id, user_id, now, rng)` requires a writer
transaction; `now` is UTC epoch seconds. It re-reads the guild/user profile and
current restrictions in that job, returning `status` unenrolled, excluded,
paused (with ISO UTC `until`, or None), or too_early (with `seconds_left`).
Refusals perform no mutation or random roll. A non-NULL last_checkin_at strictly
greater than now minus 3,600 refuses; equality succeeds, independently of clock hours.

Success returns status granted and two ordered `outcomes`, each containing item,
quantity, outcome and dust. It grants one poke_ball first, then rolls exactly one
whole checkin_table pack using `roll_checkin(rng)`: 35/30/20/15 for Great Ball,
Razz Berry, two Poke Balls and Pinap Berry, respectively, never rare items.
Each pack independently uses the remaining bag space or converts to 10 Stardust.
Even if both convert, success stores last_checkin_at=now. The grants, timer,
profile-owned `checkin:<profile_id>:<now>` receipt (action checkin), and two
resource ledger lines (reason checkin, actual item or Stardust deltas) commit
atomically. Competing jobs re-read the timer; only one grants at the same instant.

Producers are the check-in command and item service; consumers are Discord users,
receipt/ledger readers and existing inventory/profile storage. This adds a command
and service without changing schema, existing grants, IDs or persisted formats.
`tests/test_checkin.py` uses real SQLite writer transactions and fake Discord I/O.
Live Discord acceptance remains G-3.

### Check-in encounter (additive)

`items.checkin(..., content=None)` takes the loaded content artifact as an optional
keyword. With content, a granted check-in also queues one wild encounter after
both item packs, generated exactly like a step encounter on the profile's current
route (same tier chances, catch rules, and active Shiny Lure use), with NULL source
channel/message IDs, no ❗ reaction, and no change to the encounter meter. The result
then carries `encounter`: `queued` (with `encounter_id`) or `queue_full` when the
non-raid queue already holds 3; a full queue grants the items and timer as before
and creates no encounter. Without content the result and writes are unchanged.
The encounter commits in the same transaction and receipt as the grants; refusals
still create nothing. The command passes the bot's content and adds one line under
the item lines: "+1 wild encounter queued — open /walker." or "Queue is full — no
encounter added." No schema or persisted-format change; `tests/test_checkin.py`.

## M3.3 private bag conversion (additive)
Home enables Bag through handler registration. The bag shows ordinary units out
of 250, separate Master Ball/Shiny Lure pockets and Stardust. Convert selects only
held items in the v1 rates table, then a fixed quantity from 1/5/10/25/50/100/all,
capped at current held stock (rare pockets offer one). Preview names the item and
total Stardust and warns that conversion cannot be undone. Confirm on rare items
opens a second confirmation naming the item; only its confirm performs conversion.
Selections and preview phase persist in sessions.selection; invalid picks or skipped
preview/rare confirmation phases refuse without mutation. Success returns the
updated bag with a result line. M3.4 defines the Shiny Lure button below;
Back returns home. Existing durable owner/guild, expiry, exclusion and stale-revision
router guards apply. A repeated component click remains stale after commit/restart;
authorized service replay returns the saved C3 receipt without another debit.
Pure rendering accepts detached state without I/O. No schema, ID or command changes.

## M3.4 private lure activation (owner amendment 2026-11-04)
Bag enables Shiny Lure only with a held item and no active effect. Its shiny_lure
action opens lure_confirm with: "4× shiny odds for the next 10 generated encounters;
existing queued encounters are unchanged." Only the lure_activate
confirmation consumes the item. Skipped confirmation is refused without mutation.
Active Bag state shows "N encounters remaining". A held item
during an active effect has the disabled label "Stored — available after the
current effect ends". Activation, exhaustion, owner, exclusion, stale revisions,
and duplicate clicks are checked against durable state through C3 and the existing
router. Rendering remains detached and performs no I/O; no new slash command.

## M3.5 private route selection (additive)
Home enables Route through handler registration. `route` lists the eight authored
routes from `load_table("routes")`, showing display names and favoured types grouped
by weight 3/2/1, the current route, a route selector and Back to home. Authored
names/type groups are presentation data; encounter generation continues to consume
the installed artifact's identity weights and eligible counts.

`route_pick` accepts exactly one string ID present in the installed artifact's
`routes` map. Invalid values refuse privately without changing any table. Route
availability follows C5 below (v1.1 lifetime-step unlocks). Success updates only
the authorized profile's `route_id` and re-renders the current choice, alongside
the router's normal session revision update. No steps, items, currency or meter
changes are granted. Queued and revealed encounters retain every persisted field;
only future minting uses the new route, by re-reading the profile in message credit.

The durable router's owner/guild, expiry, revision and exclusion checks apply before
reads or writes. The renderer consumes detached state without I/O. Producers are
the route handlers; consumers are private Discord screens and existing profile /
message-credit services. This adds handlers without changing custom IDs, schema,
artifact format or existing persisted data. `tests/test_route.py` covers the boundary
using SQLite, seeded generation and synthetic Discord I/O; live acceptance is G-3.

## M4.5a owner administration (additive)
`Settings.admin_guild_id` reads `POKEWALKER_ADMIN_GUILD_ID` (unset disables
registration with a warning); `release` reads `POKEWALKER_RELEASE`, default dev.
`/admin status|errors|restart` is registered only in that guild, never globally.
Owner-decided guild-sync correction (2026-11-05) supersedes the earlier v1
copy-global requirement: global manifests and global sync contain only global
commands; guild manifests and explicit guild sync contain only commands registered
for that guild. Guild-only commands are retained even when a global command has the
same name. No global commands are copied into a guild. Setup never syncs.
The CLI, deployment manifest comparison and status prefix consume the same
scope-specific hash: SHA256 of canonical JSON (sorted keys, compact separators)
with scope (guild ID or "global") and name-sorted command payloads.
This intentionally changes guild registration compatibility: the next explicit
guild sync replaces previously copied globals with the guild's own commands;
global registration is unchanged. Existing recorded guild hashes must be
regenerated; no database migration is needed. Deployment compares old/new release
hashes and prints the required sync command, but never performs it. Rolling back
to an older release and explicitly syncing its guild restores its old copied-global
behavior. Producers are the client's command tree and serializer; consumers are
Discord bulk registration, the sync CLI, deployment and owner status.
Every admin entry and restart confirmation defers ephemerally before writer
waits and checks the configured guild, immutable owner IDs and current exclusion.
Discord roles grant no access. Replies suppress mentions and fit 2000 characters.
Status exposes release, monotonic uptime, latency/readiness, writer queue/closed/
failure flags, guild count, received/credited/rejected message counts and a
manifest hash prefix. A credited message means a newly committed step event with
accepted_words > 0, independently of encounter minting; repeats do not count.
The process-owned error handler retains at most ten time/logger/level/exception
summaries, never message text, exception text, paths, environment or credentials.
Restart stores one owner-bound confirmation expiring after 60 seconds. A second
call by that owner before expiry rechecks exclusion in the writer transaction,
refuses a restart receipt newer than now minus 300 seconds, and atomically writes
an unowned restart receipt. Confirmation/cooldown refusals never restart. After
commit it acknowledges restarting, then uses the existing bounded drain and exits
75 only on success; drain failure remains a failure. Cooldown survives new bot
instances and needs no schema change. Producers are Admin, WalkerBot and the
message adapter; consumers are configured owners and explicit command-sync CLI.
Existing command shapes, persisted data and lifecycle exit meanings are compatible.
Tests: test_admin.py, test_client_lifecycle.py and affected adapter/config regressions.
Live Discord, systemd restart handling and host acceptance remain unverified.

### M4.5a owner correction after review (2026-11-04)
All configured-owner requests in the admin guild, across status/errors/restart
including restart confirmations, share an in-memory per-owner limit: five requests
in a rolling 60 seconds measured by the monotonic clock. Requests exactly 60
seconds old expire; throttled requests do not extend the window or change action,
confirmation, receipt or audit state. They reply privately "Slow down, try again
in N s" with the remaining wait rounded upward. Owners have independent windows;
process restart resets these windows, preserving the durable restart cooldown.
Status is the sole owner-authorized read-only diagnostic exception: after config
owner/guild authorization and throttling, it reads exclusion with a separate
read-only database connection, independently of writer availability. A readable
exclusion still refuses. A read failure permits bounded read-only status and
reports exclusion-read failure without error details, secrets or paths. Other
commands retain their writer-backed exclusion checks and fail closed.
Credited message counters advance only from the writer's post-COMMIT observer,
including when the waiting Gateway caller was cancelled. Failed commits, rolled
back jobs and replayed message IDs never increment the credited count.

## M6.3b private evolution screens (additive)
`evolve` reads the details selection's owned Pokemon UID/revision. One available
recipe opens its quote directly; 2–25 recipes open one text-only select with
at most 25 options, labelled "<target> · <item or Candy only>", valued by edge_id.
More than 25 recipes first list items as "<item or Candy only> · <n> forms",
valued by item identifier (null = `-`). `evolve_group` accepts exactly one current
group, saves `evolve_item` and clears `edge_id`, then lists only that group's
recipes with the same target/item labels. Groups and recipes per group each have
at most 25 options. Back from creams returns to `evolve` and clears the group.
`evolve_pick` accepts exactly one current recipe edge_id after checking ownership
and Pokemon revision; grouped sources require the edge to belong to the saved
current group, otherwise REOPEN without writes. It saves that edge_id in
sessions.selection for confirmation.
The quote names the target, CP before → after, Candy cost/current quantity and
recipe item/current quantity (or Candy only). It hotlinks the target's exact-form,
gender/shiny artifact sprite as the embed image; a missing sprite has no fallback
and text retains all information. Unaffordable Confirm is disabled; a missing item
adds "Buy & evolve (<price> Stardust)" using evolution.json's purchase price.
This button uses `evolve_buy_confirm` and is disabled when Candy or Stardust is
short. Back returns to the selected Pokemon's details.
`evolve_confirm` passes the saved edge_id and Pokemon revision to C3 evolution;
success reopens evolved details and saves its new revision. Refusals request
reopening privately without spending. Existing owner/guild, expiry, exclusion and
stale-session guards apply; repeated clicks cannot spend again, including after
restart. Renderers consume detached state without database, file or network I/O.
`evolve_buy_confirm` rechecks the owned Pokemon revision, saved recipe membership,
and a fresh quote inside the router's writer transaction. If the recipe no longer
needs a missing item or Candy is short, it refuses "Your items changed. Preview
again. Nothing was spent." It calls the existing item purchase and then evolution;
any evolution refusal (including deployment) raises and rolls the purchase back.
Purchase refusals use Bag's full/insufficient messages, otherwise REOPEN. Success
opens evolved details. A full bag refuses even though evolution would consume the
item. Existing buy and evolve receipts and owner/exclusion ordering are unchanged.
Producer: evolution handlers; consumers: private Discord screens and C3 evolution.
Names and recipe/item text use only installed artifact data. Registration reads
no bot attributes. Existing custom IDs, commands and persisted formats are unchanged.
Tests: tests/test_evolution.py and tests/test_walker_router.py. The Details Evolve
button is added by M6.6d; live Discord acceptance remains G-6.

## M6.4b private Bag kind pickers and purchases (additive)
Bag lists evolution kinds by installed artifact name_en; other item names retain
v1 spelling. Convert uses C3 rate_for and passes installed content to conversion.
convert_pick, convert_prev and convert_next page held convertible items ten at a
time, with sessions.selection.offset and a select containing only that page.
convert_qty refuses values outside the current page; fixed quantities, preview,
and the second named confirmation for rare items remain required.

Buy evolution item opens buy_pick. buy_prev/buy_next page artifact kinds ten at a
time; options show "<name> · have n". buy_preview accepts exactly one kind on the
current page and previews "500 Stardust → 1 × <name> · have x Stardust". Confirm is
disabled when unaffordable. buy_confirm requires that preview and invokes C3
buy_evolution_item in the existing writer transaction; success returns Bag with
a purchase notice. bag_full and insufficient refuse privately without spending.
Prev/Next/Back share a row; each Bag view fits at most five rows and every select
has at most 25 options. Pure renderers use detached state and do no I/O; missing
new state keys retain legacy rendering. Existing owner/guild, revision, exclusion
and expiry checks still apply. No public output, slash commands or persisted
formats change. Producers are Bag handlers; consumers are private Discord screens
and C3 item services. Tests: test_evolution_items.py, test_conversion.py and
test_lure.py; live Discord acceptance remains G-6.

## M6.5b private Star Piece activation (additive)
Bag enables Star Piece with at least one held item and no active Star Piece.
star_piece_confirm previews "1.5× Stardust on your next 10 catch or find Stardust
rewards"; only star_piece_activate consumes one through C3 activate_star_piece.
Skipped confirmation is refused; already_active refuses without consuming.
The Bag shows "Star Piece: n boosted Stardust rewards left" alongside any Lure
line. The button is disabled while active or when none is held. New renderer
state keys use optional defaults for legacy detached callers. Existing private
owner/guild, exclusion, revision and expiry guards apply to both handlers.
Catch success invokes C3 boost in the granting transaction; the persisted reward,
ledger and receipt carry the boosted amount. Failed throws and research sends do
not consume rewards; replay returns the saved catch amount without decrementing.
Producers: catch service and Bag handlers; consumers: private Discord screens and
C3 item service. No schema or slash command changes. Tests: test_star_piece,
test_catching and test_lure. Live Discord acceptance remains G-6.

## M6.6d private Storage expansion and evolution entry (additive)
Owned Pokemon details show Evolve exactly when C3 evolution.options returns at
least one recipe. It opens the existing evolve handler with the selected UID and
revision. Storage's text-only page header uses the profile's storage_limit and
adds Expand storage on row 2. Both views remain within five rows / 25 components.
New renderer keys are optional and missing keys preserve legacy detached output.

expand_storage_preview reads C3 capacity.quote and shows cost, next capacity and
current Stardust. Confirm is disabled at the cap or when unaffordable. The preview
saves its current limit in sessions.selection. expand_storage_confirm passes that
saved limit and Walker.clock() to C3 capacity.expand in the writer transaction;
success returns Storage with the new header and a purchase notice. A missing or
stale preview reopens the current quote with a notice and spends nothing. At-cap
and insufficient refusals also re-preview without spending; C3 saves their refusal
receipts. Old component IDs
retain the router's stale-session refusal; repeated clicks cannot charge twice.
M6.8f: Superseded by Q22 (M6.8v); M6.8w deletes the handlers.
Storage-originated expansion retains its existing destination and capacity receipts.
Tests: test_capacity, test_storage, test_evolution, test_walker_encounter and
test_readme. Live Discord acceptance remains G-6.

## M6.6e private Bag capacity expansion (additive)
Bag's units line uses C3 capacity.limits_for's profile bag_units. Expand bag opens
expand_bag_preview, which shows cost, next units and current Stardust from C3
capacity.quote; Confirm is disabled at cap or when unaffordable. The preview saves
the current bag limit in sessions.selection. expand_bag_confirm passes that saved
limit and Walker.clock() to C3 capacity.expand in the writer transaction. Success
returns Bag with the new units limit and a purchase notice. Missing or stale
previews reopen the current quote with a notice and spend nothing. At-cap and
insufficient refusals also re-preview without spending; C3 saves refusal receipts.
Old component IDs retain the router's stale-session refusal; repeated clicks cannot
charge twice. Existing private owner, guild, exclusion, expiry and revision guards
apply. Bag remains within five rows / 25 components. New renderer keys are optional
and missing keys preserve legacy detached output; renderers perform no I/O.
Producers: Bag handlers; consumers: private Discord screens and C3 capacity.
Existing slash commands, persisted formats and rare pockets remain compatible.
Tests: test_capacity, test_conversion, test_evolution_items and test_star_piece.
Live Discord acceptance remains G-6.

## C5: M6.7a private route unlocks (intentional v1.1 restriction)

Supersedes M3.5's immediate selection of all eight routes. Lifetime progress is
`coalesce(sum(step_events.awarded_c),0)` for the authorized profile only, in
hundredths; profiles and their steps remain isolated by server (D10, D20, D45).
Refreshing Field and Noisy Forest are free. Rugged Road, Beautiful Beach,
Suburban Area, Dim Cave, Blue Lake and Volcano Path unlock at 1,000 / 2,500 /
5,000 / 8,000 / 12,000 / 18,000 lifetime awarded steps respectively, from the
authored routes table. Zero-award events, including paused messages, add nothing.

All eight fields retain their name and optional ` · Current` suffix; locked
fields append ` · Locked — n steps`, rounding the remaining hundredths up to a
whole step. The selector includes unlocked routes and the current route. The
writer job re-reads lifetime progress on every pick, refusing a locked target
privately with `Walk n more steps to unlock <route>`; a displayed or forged
option never authorizes selection. Refusal changes no persisted state.
Successful selection grants no steps, items, currency or meter changes and never
rerolls queued or revealed encounters. Existing locked current routes remain
unchanged in this row; M6.7b owns their move to Refreshing Field.

Producers: route handlers and profiles.lifetime_steps_c. Consumers: private
Discord screens and profile route selection. This deliberately restricts prior
choices without changing schema, custom IDs or encounter artifacts. Renderers
do no I/O; missing new state keys retain v1 output. Tests: test_route_unlocks,
test_route and test_stepping. Live Discord acceptance remains G-6.


## C5: M7.4b home reward count (compatible label revision)
Home renders the exact line "Rewards waiting: N", dropping the historical
"milestones" suffix because gym hours and survivor rewards share the inbox.
N remains milestones.pending_count: distinct inbox milestone_id values with
remaining rewards. The Inbox button and private session guards are unchanged; home has
no Claim button (Q20, M6.8o) — Inbox → Claim claims.
Producer: bot.screens.home; consumers: private Walker screens. Tests:
test_home_rewards_waiting_line_has_no_milestones_word and test_screens.


## M7.4c gym administration and expiry sweep (additive)
Approved PLAN Q7/Q10 and D31 add guild-only `/walker-admin gyms create name reason`,
`remove name reason` and `list`. Every command defers ephemerally before writer
waits, checks runtime Manage Server and exclusion at entry and inside the writer
job, and suppresses mentions. Mutations require a stripped nonblank reason;
names are stripped before the existing name checks, so a blank name is refused.
All target reads use interaction.guild_id; remove resolves only that guild's
active gym by name. Missing and foreign names receive the same refusal.
Before gym reads/mutations the job settles expiry. Creation and retirement use
Walker.clock() UTC epoch seconds, Walker.rng and the configured bot.content.
Successful create/remove atomically audit target_kind=guild, target_id=guild_id,
action gym_create:<name>/gym_remove:<name> and the reason; refusals and list do
not audit. List returns text only. The existing ten-gym/name limits apply.
Retirement pays completed hours to the inbox without a survivor reward.

The first ready event starts one process-owned gym sweep beside reaction cleanup.
Each tick serializes gyms.settle(conn, walker.clock(), walker.rng, bot.content)
then raids.expire and research.auto_send through the writer with the same now,
deletes sessions whose expires_at is at least 86400 seconds before that now,
then sleeps 60 seconds. Reconnects never start a second task;
errors are logged and the loop continues. Drain cancels and awaits the sweep
before writer close, retaining the shared shutdown deadline and failure semantics.
Persisted deployment deadlines never extend on restart. Bot.clock is monotonic
and remains reserved for lifecycle deadlines. Producers: WalkerAdmin and WalkerBot;
consumers: server admins and existing C3 gym/inbox services. No schema changes.
Tests: test_gyms, test_admin_channels, test_client_lifecycle and test_readme.
Focused source evidence does not close G-F2 or live Discord acceptance.


## C5: M7.5a private player gym screens (additive)
Approved Q7/Q8/Q10 and D23/D24/D30/D32/D49 add private gyms, gym_view,
gym_deploy, gym_deploy_select, gym_deploy_confirm, gym_recall,
gym_recall_confirm and gym_rewards handlers. Lists are text only; defender
views use the exact sprite as an embed image, with complete name, CP, types,
canonical/battle HP, hours held, weakening, remaining time and holder in text
(the holder as a `<@user_id>` mention in the embed, which never pings).
Empty/mine/other views offer Deploy, Recall+Rewards, or Battle respectively,
plus Back. Battle remains refused until M7.6b registers it; Home entry is M7.5b.
Deploy pages contain ten owned Pokemon labelled "<name> · CP <cp>", mark companion, Legendary/Mythical and
deployed entries ineligible, and revalidate page membership and eligibility in
the writer job. Confirm passes walker.bot.content explicitly to C3 deploy,
with the saved Pokemon revision. Stale confirms say "This gym changed. Reopen it."
Recall previews say "Income for full hours is paid; the survivor roll is forfeited".
Recall confirm and Rewards recheck both the saved active deployment_id and its
profile holder inside the job. Rewards pays only unpaid full hours to Inbox and
reports "n hours of gym income added to your Inbox". Recall pays completed hours
and forfeits the survivor roll. All jobs use Walker.clock(), session.guild_id,
and C3 settlement before authorized reads/mutations. Missing and foreign target
IDs receive the same private refusal, without cross-guild existence queries or
writes; invalid holder/preview checks precede settlement. Exclusion refuses all
actions; pause permits them. Renderers do no I/O. No public messages, schema,
slash commands or stored Pokemon stats change. Producer: bot.gyms; consumers:
private Walker router and C3 gyms/storage. Tests: test_gym_screens, test_gyms,
test_walker_router, test_readme and bare Walker receipt-owner construction.
Focused evidence does not close G-F2 or live Discord acceptance.

## C5: M7.7c deployed Pokemon details and companion refusal (additive)
Details show "Deployed at <gym> — recall it to send, power up, evolve or set companion"
when the owned Pokemon has a deployment reference. The joined gym-name lookup
filters by deployment_id, session guild_id and profile_id. Missing, foreign-guild
and other-profile references all display "a gym", with no cross-guild existence
lookup or exposed IDs. Send for research, Power up and Set companion stay visible
but disabled while deployed; Evolve is also visible and disabled whenever evolution
options exist. Favorite and Back retain their behavior. A forged companion click
refuses privately with "Recall it from the gym first" before the profile UPDATE
or deployed SQL trigger, preserving the companion and Candy meter. Existing
ownership/revision/session guards still apply. Recall restores each action's
normal eligibility and removes the deployment explanation. New renderer state
uses optional defaults preserving existing literal-state output; renderers do no
I/O. Producer: bot.storage; consumers: private Walker details and companion action.
No schema, service signature or component-ID changes. Tests: test_storage,
test_companion and test_gym_screens. Focused evidence leaves G-F2/native gates open.

## C5: M7.6b private gym battle preparation and results (additive)
Battle opens from another holder's gym view and preserves that view's deployment_id.
The selection stores gym_id, deployment_id, party (initially [], up to three ordered
optional uid/revision slots), active slot 1..3, offset and nominee. Slot 1 is required; empty later slots
are omitted in order on Start. Ten owned Pokemon per page show CP/types and mark
companions/deployed Pokemon unavailable; Legendary/Mythical Pokemon may attack.
Page selections must belong to the current page, remain eligible and be distinct.
Five rows contain navigation, Pokemon select, slot buttons, Clear only/eligible
Claim with slot n select, and Start. Start is disabled for incomplete/stale parties
or invalid nominees. Replacing a nominated member clears the nomination.
Start passes the saved defender id, ordered uid/revisions, nominee, configured
content/rules/chart and Walker.clock() to C3 battle inside the writer. Stale and
cooldown return preparation with a notice and no fight; stale never silently
adopts a new defender. Reopen the gym to preview a replacement defender.
Results show outcome/reason, names, forms, gender/shiny state, CP/types,
canonical starting party HP and defender canonical/
battle HP, survivors, at most 15 events, and the committed claim/clear outcome.
The exact defender sprite is the thumbnail and first attacker sprite the image;
missing sprites leave complete text with no substitute. Battle log pages preserve
all saved events as text only, at most 3500 characters each, with navigation/Back.
The existing router enforces actor/guild/session/revision/exclusion boundaries.
Foreign/missing targets receive identical refusals before settlement and without
cross-guild existence queries. Renderers perform no I/O. No schema, engine, slash
command or stored-stat changes. Producer: bot.gyms; consumers: private Walker,
C3 battle and C7 snapshots. Tests: test_gym_battle, test_gym_screens,
test_walker_router and test_readme. Focused evidence leaves G-F2/native gates open.

## C5: M7.5b home gym entry and readable inbox labels (additive)
Home includes Gyms, enabled exactly when Walker.handlers registers gyms. Its
custom ID routes through the existing private session guards; the view stays
within Discord's five rows. Missing available state keeps the button disabled.
Inbox and Claim resolve gym_income:<deployment_id>:<n> and survivor:<deployment_id>
to "Gym income: <gym> hour n" and "Gym survivor reward: <gym>" for both waiting
and moved details. One joined query resolves the relevant deployments, filtered
by session guild_id and profile_id. Missing, foreign-guild and other-profile
deployments all use "a gym", without a cross-guild existence query or exposed IDs.
Income IDs require a nonempty deployment ID and exactly one hour from 1 through 8;
survivor IDs require exactly one nonempty deployment ID. Malformed IDs display
"Gym income reward" or "Gym survivor reward" without a deployment lookup or raw ID.
Ended deployments and retired gyms retain their names while their rows exist.
Handlers supply detached labels; renderers do no I/O and optional labels default
to the existing milestone output. No schema, payout or claim semantics change.
Producers: bot.screens.home and bot.milestones handlers; consumers: private Walker
screens. Tests: test_screens, test_gym_screens and test_milestones.
Focused evidence does not close G-F2 or live Discord acceptance.


## C5: M7.8 gym moderation (additive)
Approved D23/D28/D31/D60 and PLAN Q13 add guild-only `/walker-mod gym-recall gym reason`
under the existing Moderate Members defaults. Entry defers ephemerally; the writer job
rechecks permission and actor exclusion before settling expiry with Walker.clock().
A nonblank reason is required. Lookup uses only active gyms in the interaction guild;
missing and foreign names both return "No such gym". An unoccupied gym returns
"Gym is empty". Refusals write no audit. Recall ends that gym's active deployment
with mod_recall, pays completed hours into its holder's inbox, forfeits the survivor
roll, and audits actor, user-target holder ID, gym_recall, stripped reason and time.
The reply names the gym and holder ID only after commit and suppresses mentions.
Exclusion ends the member's active deployment in this guild in the restriction/audit
transaction, with excluded and no unpaid-hour or survivor payment. Include never
redeploys. Reset/delete-data cascade the holder's deployment and Pokemon, paying
nothing; a later profile receives no old deployment rewards. No schema change.
Status adds "Holds gym: <name> since <UTC> (h hours)" or "Holds gym: none", scoped
to the current guild and profile; status first settles expiry, and elapsed time uses
Walker.clock(). Unknown/empty recall retains the preceding expiry settlement without
a moderator-recall audit. Restriction
and moderation timestamps continue to use time.time(). Audit renders guild targets
as server:<id>, retaining user:<id> and channel mentions. Existing private reply,
authorization, log filtering and reason validation rules apply.
Producer: bot.mod; consumers: Discord moderators and C3 gyms/restrictions/inbox.
Compatibility: additive command and status output, corrected guild audit label;
existing command arguments and persisted formats remain compatible.
Tests: test_gym_mod, test_mod, test_deletion. G-F2 and live acceptance remain open.


## C5: M8.1b raid configuration (additive)
`/walker-admin raids on|off reason [channel]` is guild-only with Manage Server
defaults and runtime checks. On requires a text channel in the interaction guild;
missing and foreign channels receive the same refusal without cross-guild lookup.
Off clears raids_enabled while retaining raid_channel_id; on sets both. New guilds
remain off with no channel until configured. A stripped nonblank reason is required.
The command defers privately before writer waits, rechecks Manage Server and actor
exclusion inside its mutation job, and atomically audits target_kind=guild, the
guild ID, actor, raids_on/raids_off, stripped reason and time. Refusals write nothing;
audit failure rolls back configuration. Replies suppress mentions and follow commit.
On warns when EMBED_LINKS or SEND_MESSAGES is missing in the selected channel,
without refusing configuration or sending an announcement. Ticket spending later
rechecks permissions (M8.2b). Producer: WalkerAdmin; consumers: administrators and
raid spawning. Existing commands and persisted formats remain compatible; uses
M8.1a guild fields. Tests: test_raids and test_admin_channels. G-F2/live gates stay open.

## C5: M8.1c raid encounter Back and Run (additive)
Under D60 and Q12, home Open encounter selects only ordinary queued/revealed rows.
Back from Master Ball, shiny Run confirmation or the storage warning instead reopens
the selected queued/revealed raid encounter owned by this profile, while its spawn in this guild
is unexpired. It preserves the frozen encounter and selected items, uses the normal
reveal handling and clears the Run, Master Ball and storage confirmation flags.
A deleted, expired, foreign or missing selection falls through to the ordinary queue
or home without revealing another profile's encounter. Later and the empty-queue
home fallback clear the Run, Master Ball and storage flags, including after a
read-only failed confirmed throw or a confirmed throw that broke free. Ordinary Back is unchanged.
Every home entry clears only these confirmation flags before normal terminal recovery,
preserving unrelated selection values; a fabricated home action cannot carry them onward.
Run and shiny Confirm Run recheck raid spawn expiry using Walker.clock() in the
writer transaction before any resolution or receipt. At expires_at <= now they
privately refuse with "The World Legendary left.", preserving every table and the
revealed encounter for cleanup. A throw that catching.throw refuses as expired
shows "The World Legendary left; this encounter expired." on the catch screen.
A live raid can still use the normal Run flow.
Producer: Walker; consumers: home/catch/confirmation screens and saved session
selection. Existing buttons, custom IDs, schema and ordinary catch semantics stay
compatible. Tests: test_raids, test_walker_encounter and test_walker_router.
Focused evidence leaves G-F2 and live Discord acceptance open.

## C5: M8.2a at-most-once World Legendary announcement (additive)
D60 deliberately excepts D2 with one public embed, no pings and no DMs. The embed
names the exact identity, shows its normal D48 sprite when available, and gives
the UTC despawn time. `raids.announce(bot,spawn)` uses bot.writer and bot.walker.clock;
its first writer job atomically claims only a live pending spawn in its stored
guild, marking attempted before any Discord call. Sending is outside the writer,
to the persisted channel only, with AllowedMentions.none() and
`nonce(spawn_id)=spawn_id.replace('-', '')[:25]`. Pinned discord.py 2.7.1 adds
enforce_nonce=true to that payload. A successful third job stores sent/message_id.
A failure or cancellation after claiming leaves attempted, with no retry/refund,
including a crash after Discord accepts and before its ID is saved.
`resume_pending(bot)` announces only live, unended pending rows; attempted/sent
rows are never sent again. Concurrent/repeated calls cannot claim twice. No live
Discord acceptance is implied by mocked tests. Producer: raids; consumers: later
startup recovery and ticket UI. Existing commands remain compatible. Tests:
test_raids, test_share. G-F2 and live gates remain separate.

Supervisor ruling: announce uses direct channel.send with no application deadline
or cancellation wrapper. The application starts at most one send per spawn;
pinned discord.py may internally retry that call using the same nonce and
enforce_nonce. The owner explicitly accepts that an internal retry delayed beyond
Discord's unspecified "past few minutes" nonce-deduplication window could produce
a duplicate announcement. No guard against that accepted risk is implemented.
Any exception after sending starts retains attempted, with no application retry
or refund. The superseded five-second deadline and its transport tests are removed
by explicit owner authority; shared transport and dependency behavior are unchanged.


## C5: M6.8h inbox bag shortcuts (additive)
Inbox and partial Claim show "Expand bag (+<step>, <stardust:,> Stardust)"
(inbox_expand_bag) and "Convert items" (inbox_convert) exactly when non-rare
items remain waiting. Numbers come from capacities.json expansion.bag in detached
handler state; renderers perform no I/O and optional state preserves literal renders.
Stardust, Candy, rare-only and empty inboxes do not offer these shortcuts.
Both actions reuse existing Bag previews and services, keeping back='inbox' through
paging, quantities, previews, rare confirmation and expansion refusals. Every Back
returns to Inbox without spending and cancels its pending Bag preview: a forged
current-revision Confirm after Back cannot spend or create a receipt. Inbox clears
only the selection marked back='inbox', preserving unrelated selection state.
Successful expansion or conversion also returns
to Inbox without claiming rewards. Only a separate Claim moves waiting items.
Bag-origin flows retain their Bag return and notices; refusal texts and router
owner/guild, expiry, exclusion and revision guards remain unchanged. Gym labels
keep their guild/profile-scoped lookup and safe missing/foreign fallback.
Producers: bot.milestones and bot.bag; consumers: private Walker screens and existing
C3 capacity/items/inbox services. No schema, price, slash command or receipt changes.
Tests: test_milestones, test_capacity, test_conversion and test_walker_router.
Focused evidence does not close G-F2 or live Discord acceptance.

## C5: M8.2b private World Legendary Ticket use and startup recovery (additive)
Bag shows Use World Legendary Ticket only while one is held. `wlt_confirm`
previews "Spawns a World Legendary in <#raid_channel_id> for 60 minutes; cannot be undone"
(the configured raid channel as a channel mention; "the raid channel" when unset);
only `wlt_use` after this preview calls C3 raids.spawn inside the writer job.
The handler reads the configured raid_channel_id in that job, resolves it through
interaction.guild.get_channel, and checks EMBED_LINKS and SEND_MESSAGES for
guild.me. Missing or foreign channels and missing permissions pass None;
otherwise the exact checked channel ID is passed. Spawn uses walker.clock UTC.
Refusals keep the ticket: "Raids are turned off in this server.", "No raid channel
is configured.", "Missing raid channel permission: EMBED_LINKS and SEND_MESSAGES
are required.", "The raid channel changed; try again.", "A World Legendary is
already active in this server.", or "No World Legendary Ticket is available to
use." Stale/forged owners and excluded users retain existing router refusals.
Skipping confirmation refuses "Preview the World Legendary Ticket before confirming."
Success returns Bag with "Spawned <species> until <YYYY-MM-DD HH:MM:SS UTC>";
its after_commit callback awaits raids.announce and returns that same Bag response.
Commit failures never announce. On the first on_ready, after the awaited reaction
sweep, startup awaits raids.resume_pending once unless stopping (including shutdown
during the sweep). Recovery uses walker.clock and the existing persisted pending
state; no retry/deadline/transport behavior changes. Producers: Bag and client;
consumers: private session router and C3 raids. Existing render states use defaults,
Bag remains within five rows, and existing commands/schema remain compatible.
Tests: test_raids, test_client_lifecycle, test_heartbeat, test_lure, test_readme.
G-F2 and live Discord gates remain separate; M8.2a's accepted retry-window risk remains.

## Trade channel configuration (additive)
Pokemon-trading OD8/P11 adds the `trade-channels` subgroup under the existing
`/walker-admin` root, attached on the client's local tree at construction without
synchronizing: `add <channel> <reason>`, `add-all <reason>`, `remove <channel>
<reason>` and `list`. The subgroup inherits the root's guild-only and Manage Server
defaults; every handler defers ephemerally and rechecks `manage_guild` and P15
exclusion through `WalkerAdmin.authorize`, so non-managers and excluded members get
a private refusal. The default is no trade channels: a guild trades nowhere until a
moderator enables a channel. The channel option is a `TextChannel`; threads are not
enabled through a parent. Add/remove refuse a channel from another guild ("Choose a
channel in this server.") and a stripped-empty reason ("A reason is required.").
Each runs as one writer job that rechecks exclusion, upserts the guild, then
`INSERT OR IGNORE`s or deletes the `trade_channels` row and inserts one `mod_audit`
row (guild, actor, target kind `channel`, channel target, action
`trade_channels_add|trade_channels_remove`, stripped reason, UTC epoch time),
atomically; repeating add or remove changes no row but audits each call. Replies are
"Trade channel added." and "Trade channel removed."; add appends "Missing Send
Messages; trade pings will fail until permissions recover." when the bot lacks Send
Messages in that channel. `add-all` mirrors `channels add-all`: the same reason
rule, `guild.fetch_member` with the same HTTPException and Manage Server refusals,
then one writer job that rechecks exclusion and enables each `guild.text_channels`
entry where the bot has View Channel and Send Messages. Existing trade channels are
untouched and unaudited; each newly enabled channel gets one audit row; any failure
rolls back the whole batch. The mention-suppressed reply is "Enabled N channels;
skipped M (no access); K already enabled. Channels created later are not added
automatically." ("1 channel" when N is 1). `list` reads only this guild's trade
channels in a read-only writer job with an exclusion recheck, writes no audit, and
replies with channel mentions under `AllowedMentions.none()`, chunked below the
2,000-character limit in private follow-ups ("No trade channels configured." when
empty). Per P11, removal never closes a trade already open there; the later `/trade`
handlers own that behavior.
Producers: `bot.admin_trade_channels`; consumers: Discord moderators and the later
`/trade` channel check. Schema: migration 0018 `trade_channels` (no further change).
Registration stays local; after delivery the owner runs one
`sync-commands --global --yes`. Tests: `tests/test_admin_trade_channels.py`;
`tests/test_admin_channels.py` and `tests/test_client_lifecycle.py` stay green.

## Private trade screens (additive)
Pokemon-trading T6 (OD1, OD6, P5, P12) adds `pokewalker.bot.trade`: pure renderers
`render_trade`, `render_picker` and `render_result` over the detached `trading.view`
state plus the session (no I/O), and `handlers(walker)` registering seven actions on
the shared `pw:v1:` router: `trade_pick`, `trade_offer`, `trade_confirm`,
`trade_refresh`, `trade_cancel`, `trade_prev` and `trade_next`. Every handler needs
`selection.trade_id` and saves `{trade_id, trade_revision, phase, offset}` (phase
`trade`, `pick` or `result`); Confirm works only from a trade screen (phase `trade`), and
the offer select and paging work only from a picker
(`phase=pick`), and an offered value must be on the eligible page at the saved
offset. Time is `Walker.clock()`. The service refuses non-participants, and the
router's session owner check runs first ("This screen is not yours. Open /walker
for your own screen."). Buttons never check `trade_channels`, so they keep working
after a channel is removed (P11).
The trade screen reads "Trade with <@partner>", "Waiting for them to join: they run
/trade member:@you" until the partner joins, "You offer: …" and "They offer: …"
(name · kind · CP · appraisal stars, or "nothing yet"), a "Special trade: your X
(Shiny, Legendary, Mythical, starter) · their Y (…). A trade can't be undone." line
when either offer has a flag (OD6), "You: confirmed|not confirmed · Them: …",
"Expires 15 min after the last join, offer or confirm (now <expiry, UTC>)." and an
optional notice, with the partner's offered Pokémon's sprite. Buttons: Choose
Pokémon (`trade_pick`), Confirm (`trade_confirm`, disabled unless both sides joined
and offered and the viewer has not confirmed this revision), Refresh
(`trade_refresh`) and Cancel trade (`trade_cancel`). Confirm passes the screen's
`trade_revision` and `walker.bot.content` (P5). The picker reads "N tradable of M
owned · favorites, your companion and gym defenders can't be traded" with a
`trade_offer` select of at most 10 options "#n Name · CP x" and Prev
(`trade_prev`), Next (`trade_next`) and Back (`trade_refresh`).
Notices: `changed` "The offer changed — review it and confirm again.";
`ineligible` "That Pokémon can't be traded: <reason>."; `offer_invalid` "Your
Pokémon can't be traded: <reason>." when the refused side is the viewer's, else
"Their Pokémon can't be traded: <reason>." (reasons: it is a favorite, it is a
companion, it is defending a gym, it is no longer in storage, it changed after it
was offered); `capped` "You can trade again in Xh Ym." (minutes
rounded up); `partner_capped` "They can't trade again yet."; `partner_unavailable`
"They can't trade right now."; `waiting` "Confirmed. Waiting for them." A trade that
is no longer open shows the result screen, chosen by its `state` alone (completion
clears both confirmations): completed → "You received <name> (CP x). It counts for
your Pokédex. Open /walker → Storage to see it." (or "Trade complete. It counts for
your Pokédex. Open /walker → Storage to see it." when the received Pokémon is no
longer found); cancelled or expired → "This trade ended. Use /trade member to start
again." The result has no buttons; no trade screen has a Home or `/walker` button,
and Home has no trade entry (OD1).
Router outcomes for `trade_*` actions: an expired or unknown session → "This window
timed out. Please reopen /trade for a fresh one."; an outdated revision more than 10
seconds after the last committed action → "This screen is out of date. Please reopen
/trade to refresh."; a handler refusal (missing or foreign trade, wrong phase, value
not shown, unknown status) → "That option changed since this screen opened. Please
reopen /trade to refresh."; a double press within 10 seconds → no message. Other
actions keep the `/walker` texts. Producers: `bot.trade`, `bot.walker`; consumers:
trade participants and the later `/trade` command. No schema, ID grammar or
manifest change. Tests: `tests/test_trade_screens.py`; `tests/test_walker_router.py`
and `tests/test_screens.py` stay green.

## `/trade` command and partner ping (additive)
Pokemon-trading T7 (OD1, OD7, OD8, P6, P11–P13) adds the top-level guild-only
`/trade [member]` command ("Trade a Pokémon with a member of this server"), registered
after `/raid`; `member` is an optional Discord Member option (mod.py pattern). It is
never a button, option or sub-screen of `/walker` or any other command, and `/walker`
gains no option. It defers ephemerally; without a guild it says "Use /trade in a
server.". Before the writer job it records whether the bot can Send Messages in the
interaction channel. One writer job, using Walker.clock(), applies in order:
1. the interaction channel ID is not exactly a `trade_channels` row of this guild
   (threads never match their parent) → "Trading isn't enabled in this channel. A
   moderator can enable it with /walker-admin trade-channels add."; nothing is written;
2. opted out → "Run /walker-account opt-in first"; 3. no profile → "Open /walker to
   enroll before trading."; 4. excluded → the existing exclusion text; 5. a bot member
   → "You can't trade with a bot.";
6. no member: the caller's joined open trade (`trading.current`) is reopened, else "Use
   /trade member:@someone to start or join a trade.";
7. otherwise `trading.open_or_join` with the permission flag. Refusals read: `self`
   "You can't trade with yourself."; `partner_not_enrolled` "They haven't started
   walking in this server."; `partner_unavailable` "They can't trade right now.";
   `busy` "You're already in a trade with <@X>; finish or cancel it first.";
   `partner_busy` "They're in another trade right now."; `capped` "You can trade again
   in Xh Ym." (minutes rounded up); `partner_capped` "They can't trade again yet.".
A refusal leaves no session. Success (opened, joined, reopened, or a bare reopen)
persists a normal Walker session (revision 0, expiry now + `IDLE_SECONDS`, selection
`{trade_id, trade_revision, phase: trade}`) and shows `render_trade` over `trading.view`, all
replies under `AllowedMentions.none()`.

Only `opened` with ping `reserved` posts, after commit and outside the writer job, one
public message in the interaction channel: "<@partner>, <@opener> wants to trade a
Pokémon with you. Run /trade and choose them to join." with
`AllowedMentions(everyone=False, roles=False, users=[partner])`. The opener's screen
adds "Pinged them here." when sent; an HTTP, rate-limit or transport failure (the
share.py set) keeps the trade open and adds "Couldn't ping them; ask them to run
/trade."; `rate_limited` adds "Opened without a ping (one per 10 minutes). Ask them to
run /trade."; `no_permission` adds "Couldn't ping them; ask them to run /trade.".
Joining and reopening never ping and never retry. The 60 s sweep also calls
`trading.prune` (expire idle open trades; delete trades ended over a day ago).
Producers: `bot.trade.command`, `bot.client`; consumers: Discord members and the
trade screens. No schema or ID grammar change. The global command manifest changes:
delivery needs one `sync-commands --global --yes`. Tests:
`tests/test_trade_command.py`; `tests/test_client_lifecycle.py`,
`tests/test_trade_screens.py` and `tests/test_share.py` stay green.

## Owner amendment: Rare Candy power-up button (2026-11-12)
The power-up quote also shows "Rare Candy (have N)" and a `Use Rare Candy` button
(`power_up_rare`) beside Confirm and Back. It is disabled at cap or when no Rare
Candy is held. Pressing it applies one power-up step paid with one Rare Candy instead
of Candy and Stardust, through the same saved Pokemon revision, guards and receipt as
Confirm, and returns the updated details. Refusals privately request reopening.
Rendering stays free of I/O. Tests: tests/test_powerup.py.

## Owner amendment: Companion Mirror Bag button (2026-11-12)
The Bag shows a `Companion Mirror` button (`mirror_confirm`). It is disabled when
none is held or while an encounter booster (Shiny Lure or Companion Mirror) is
active; the Shiny Lure button is likewise disabled while a Mirror is active. An
active Mirror adds "Companion Mirror: N encounters remaining". mirror_confirm warns
before use: "For your next 10 generated encounters, each has a 20% chance to be a
Pokémon from your companion's family line, on any route. ⚠ The mirror never
attracts Legendary, Mythical or Rare Pokémon — those family members are skipped,
and if none qualify the encounter is a normal one. Existing queued encounters are
unchanged." When there is no companion, or the current companion's family has no
eligible candidate (C3 mirror_pools), it adds "⚠ Your current companion's family
has no Pokémon the mirror can attract." Activate (`mirror_activate`) and Back
follow. Only mirror_activate consumes the item, through C3 activate_mirror.
Skipped confirmation is refused without mutation; already_active and missing
refuse without consuming. Existing owner/guild, exclusion, revision and expiry
guards apply. The Bag stays within Discord's 5 buttons per row and 25 components.
Rendering stays free of I/O; no slash command or ID grammar change. Tests:
tests/test_companion_mirror.py, tests/test_capacity.py.
