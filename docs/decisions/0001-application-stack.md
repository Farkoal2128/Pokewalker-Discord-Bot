# ADR 0001: Application stack and runtime shape

Status: Proposed (2026-11-04). The owner accepts it by merging.

## Context

The bot is a hobby, single-owner Discord app, hosted on one home Ubuntu machine shared with
other services ([hosting research](../research/hosting/README.md)). The requirements
([pokewalker-bot](../features/pokewalker-bot/README.md), D1–D58) need:

- passive counting of chat messages (Message Content intent), with anti-farming state kept
  across channels in a server;
- private `/walker` screens built from durable state, with race-safe Catch/Run and resource
  transactions (each action applies once, all or nothing);
- every feature isolated per server: a player is `(guild_id, user_id)`;
- a full-roster content build from a pinned PokéAPI commit (D51), never fetched during play;
- hotlinked sprites in v1 (D48–D49), and locally rendered scenes and gym images from v1.1/v2.

The [library comparison](../research/library-comparison.md),
[Discord performance research](../research/discord-rate-limits-performance.md) and
[hosting research](../research/hosting/README.md) all converge on one stack. No
application code exists yet, and the framework already requires Python 3.11+.

## Decision

1. **Language and library:** Python **3.12+** and **discord.py**, pinned to an exact release
   (2.7.1 was current on 2026-11-04) with a hash-locked dependency file. Classic buttons and
   embeds, not Components V2.
2. **Process shape:** **one process, one Gateway connection, no inbound port.** Interactions
   arrive over the Gateway. Intents are `GUILDS`, `GUILD_MESSAGES` and `MESSAGE_CONTENT` only,
   and the message cache is disabled (`max_messages=None`).
3. **Layers:** a thin Discord adapter turns events into content-free inputs. A domain layer
   holds the game rules as pure functions with injected time and randomness. A persistence
   layer owns transactions. Screens are rebuilt from stored state; views and collectors hold
   no game state.
4. **Storage:** **SQLite** through **aiosqlite**, in WAL mode with `synchronous=FULL` and
   `secure_delete=ON`, on local encrypted disk. SQLite otherwise leaves deleted bytes in free
   pages, and the backup API copies them into new snapshots, which would break D28's
   28-day deletion promise. **One writer task owns every write transaction** end to end. The linked
   SQLite version must include the WAL-reset fix (3.51.3+, or the 3.50.7 / 3.44.6 backports),
   and startup refuses to run otherwise. Every accepted step award is committed (no in-memory
   step buffer), so a crash loses no credited steps.
5. **Content:** a build-time importer reads the PokéAPI CSVs at the D51 commit and writes one
   versioned content artifact: species, forms, stats, tiers, families, routes and items. The
   bot only reads that artifact. Rebuilding it from a new pin is a reviewed change.
6. **Images:** v1 embeds hotlink PokéAPI sprites at a pinned sprites-repository commit
   (D48–D49). From v1.1, **Pillow** renders scenes in one bounded worker off the event loop,
   from a local sprite cache that is never committed.
7. **Hosting:** one hardened **systemd** service on the home Ubuntu machine, using the unit,
   paths, credentials and backup plan in the hosting research. Hourly SQLite `.backup` with an
   encrypted off-machine copy. **Override:** backup retention follows requirement D28, not the
   hosting research. Backups are pruned by age (over 28 days) locally and off-machine even when
   new uploads fail, and a pruning check with failing uploads is part of the restore rehearsal.

## Consequences

- Easier: a single runtime and a single database file, no message broker or extra service.
  Transactions plus a single writer make "applies once" rules straightforward to enforce and
  test. Pure domain functions can be tested without Discord.
- Harder: a single writer caps write throughput. That is fine for a few hobby servers, but a
  move to multiple processes means moving to PostgreSQL. A crash or restart drops
  in-flight interactions; players reopen `/walker`.
- Constrained: no sharding (not needed below 2,500 servers). No web dashboard in this stack.
  Content changes only through the importer, never at runtime.

## Alternatives considered

- **discord.js / TypeScript.** Equally capable; rejected only because the repository tooling
  is already Python and nothing in the requirements needs Node.
- **disnake.** A credible fork; no feature here needs it.
- **PostgreSQL from day one.** Its row locks suit multiple writers. It costs an extra service
  and its own backups, with no benefit to one process. It is the documented next step.
- **Buffered step deltas** (flushed every few seconds). Fewer writes, but a crash loses
  credited steps. Rejected until measurement shows commit-per-message is too slow.
- **Docker or PM2 instead of systemd.** Each adds a second supervisor or daemon on a shared
  host for no gain here.

## Verification / follow-up

- The first plan rows (chat-rate measurement, economy simulation, content import) use this
  stack: Python scripts with tests under the repository's TDD rules.
- Before the first deploy: confirm the host's Python and SQLite versions, measure write
  latency with `synchronous=FULL` at the measured chat rate, and rehearse backup/restore
  and SIGTERM drain as listed in the hosting checklist. The restore rehearsal must include
  D28's deletion markers in two cases. (1) Restore a snapshot taken **before** profile P1 was
  deleted: replaying P1's marker removes P1. (2) Restore a snapshot taken **after** P1 was
  deleted and the same player re-enrolled as P2: replaying P1's marker leaves P2 untouched.
  Also interrupt a deletion after its marker is saved, and check that the next startup
  finishes it. Finally, delete a profile holding a unique fixture string, take a fresh
  backup, and check that the string's **bytes** are absent from the backup file, not just
  its rows. From v2, the restore fixture also holds an occupied gym with unpaid hours. After
  marker replay the gym is empty, old battle controls are refused, and no income reaches a
  re-enrolled profile.
- Supersede this ADR if a measured limit (writer latency, memory or render time) forces a
  change.
