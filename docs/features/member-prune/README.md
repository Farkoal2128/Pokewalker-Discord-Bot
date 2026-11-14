# member-prune: remove game data of players who left the server

Canonical plan and row status: [PLAN.md](PLAN.md). This file holds the requirements only.

## Outcome

A moderator with Manage Server runs `/walker-admin prune reason [confirm=false]` and the bot
deletes the game data of every profile in that server whose Discord user is no longer a
member. Deletion reuses the existing D28 path, so it is durable, replayable after a crash,
and removes the player from everything that cascades from `profiles` (collection, items,
gym deployments, and on `feature/arena` the Arena runs, tickets and monthly leaderboard rows).

## Owner request

2026-11-14, relayed by the coordinating session: add a `/prune` that removes players who
left the server; removing a player must also remove them from the Arena monthly leaderboard.

## Grounding (verified at 9c8aec5)

- `pokewalker/bot/client.py:102-103`: the bot uses `Intents.none()` plus guilds,
  guild messages and message content. It has no members intent and no member cache.
- Per-member reset already exists: `/walker-admin reset member reason [confirm=false]`,
  `pokewalker/bot/admin_channels.py:187-221`, through `deletion.run_marker`
  (`pokewalker/services/deletion.py:75-122`) and `deletion.apply` (:125-150), which
  redacts gym battles and deletes the profile in one writer job after an fsynced marker.
- Marker kinds are `delete`, `opt_out`, `opt_in`, `reset` (`services/marker_log.py:13`).
  `delete` and `reset` both delete the profile; only `reset` also writes a per-user
  `mod_audit` row. A `delete` marker can carry `actor_id` and `reason`.

## Requirements

- **PR1 Command.** `/walker-admin prune reason [confirm=false]` under the existing
  `walker-admin` group: server only, Manage Server (default permissions plus the runtime
  check in `authorize`), excluded actors refused at entry and again inside each writer job
  (`check_actor`), stripped non-blank reason required, private replies, mentions suppressed.
- **PR2 Membership test.** Membership is checked one profile at a time over REST with
  `guild.fetch_member(user_id)`. A profile is "departed" only when Discord answers
  `discord.NotFound` with error code 10007 (Unknown Member). A returned member is kept.
  Any other outcome (other NotFound codes such as 10004 Unknown Guild, Forbidden, 5xx,
  rate-limit exhaustion, transport errors, timeouts) stops the run at once; nothing more
  is deleted, and the reply says how many were deleted before the stop.
- **PR3 Count first.** `confirm=false` (the default) is the dry run: it checks every
  profile in the server and replies "N of M profiles are no longer members", with the
  instruction to rerun with `confirm=True`. It writes nothing: no marker, no audit, no
  deletion.
- **PR4 Deferred.** Both modes defer the interaction privately before any writer wait or
  REST call, because REST checks are rate-limited and may take minutes.
- **PR5 Delete path.** With `confirm=True`, each departed user is deleted through
  `deletion.run_marker` exactly as reset does (authorization callback, fsynced marker,
  `apply`, reaction cleanup). No new delete SQL. Each user's deletion is its own writer
  job, so one failure never rolls back earlier, completed deletions.
- **PR6 Fresh check before delete.** The confirmed run re-checks membership itself; it
  never trusts an earlier dry-run count. A user is deleted only right after their own
  NotFound 10007 answer in that run.
- **PR7 Audit.** Exactly one `mod_audit` row per confirmed run that deletes at least one
  profile (`target_kind='guild'`, `action` naming prune, the reason, the actor). No
  per-user reset audit rows. The row must exist whenever any of that run's deletions
  committed, including after a crash or restart mid-run. The dry run writes no audit.
- **PR8 Idempotent and restart-safe.** A second run, or a run after a restart mid-prune,
  finds only the remaining departed profiles and deletes those. Profiles already deleted
  are skipped without error. Startup marker replay completes any deletion whose marker was
  written but whose transaction did not commit (existing D28 behaviour).
- **PR9 Never delete on uncertainty.** No deletion without a NotFound 10007 for that
  exact user in the same run (PR2, PR6).
- **PR10 Long runs.** A run that would outlive the interaction token stops checking
  before the 15-minute limit, reports how far it got, and tells the moderator to run it
  again; PR8 makes the rerun continue the work.
- **PR11 Retention.** As with reset: moderation audit, active restrictions and opt-out
  choices of pruned users remain (D28 retention exceptions). A pruned user who rejoins
  can enroll fresh.

## Out of scope (owner decision needed before any of these)

- The privileged members intent, a member cache, or automatic deletion on member leave.
- Pruning across servers or from the owner `/admin` command.
- Arena-specific leaderboard code: Arena rows cascade from `profiles`, so prune needs
  none. Once `feature/arena` is on main, a test should assert a pruned player's Arena
  leaderboard rows are gone.

## Contract impact

- C5 `contracts/discord-commands.md`: additive subcommand under `/walker-admin`.
- `contracts/persisted-state.md`: no schema change; new audit action value; marker format
  unchanged.
- `content/help.md` admin page lists the new subcommand.
