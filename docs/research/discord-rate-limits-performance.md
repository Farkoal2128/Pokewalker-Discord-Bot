# Discord rate limits, performance, storage, and hosting

Checked **2026-11-04**. Facts describe documented behavior; recommendations are proposed implementation choices. Source links and check dates are listed below.

## Facts

### Discord traffic limits

- HTTP limits are per route and global; routes can share a bucket. Discord says not to hardcode route quotas: observe `X-RateLimit-Bucket`, remaining/reset headers, and a `429` response's `Retry-After`/`retry_after`. Major resources such as channel IDs affect bucket identity. The documented default bot global ceiling is **50 HTTP requests/second**. Interaction endpoints are exempt from that bot global limit, but are not unlimited. [D1](https://docs.discord.com/developers/topics/rate-limits)
- The invalid-request threshold is **10,000 per 10 minutes per IP**, covering `401`, `403`, and `429`; `429` responses with `X-RateLimit-Scope: shared` are excluded. [D1](https://docs.discord.com/developers/topics/rate-limits)
- Creating a reaction, deleting the bot's own reaction, and editing a message are separate HTTP operations. There is no documented universal fixed “reactions/second” or “edits/second” allowance to build around. The emoji-management route exception concerns emoji resources, not a license to treat message reactions as unmetered. [D1](https://docs.discord.com/developers/topics/rate-limits)[D2](https://docs.discord.com/developers/resources/message)
- Gateway applications may **send 120 events per connection per 60 seconds**. This is an outbound Gateway limit, not a 120-incoming-messages counting allowance. The ordinary app limit is **1,000 IDENTIFY calls per 24 hours across all shards**; RESUME calls do not count. Respect the returned session-start limits and `max_concurrency`. Sharding is required at **2,500 guilds or more**; use `/gateway/bot`'s recommended shard count. [D3](https://docs.discord.com/developers/events/gateway)

### Established leveling-bot anti-farming patterns

| Bot | Documented behavior | Source |
| --- | --- | --- |
| Arcane | Message XP defaults to a one-minute cooldown. Its alternative per-word mode counts words of at least three characters and applies an additional text-content qualification. | [A1](https://docs.arcane.bot/plugins/leveling/setup/xp-options) |
| Lurkr | Defaults to 15–40 XP per eligible message, followed by a one-minute period in which additional messages receive no XP. Cooldown and award range are configurable. | [A2](https://lurkr.gg/docs/guides/customize-leveling-speed) |
| MEE6 | Administrators can exclude designated “No-XP” roles and channels. | [A3](https://mee6bot.freshdesk.com/support/solutions/articles/101000469306-how-to-fix-server-members-not-getting-xp) |

Arcane documents decreasing **voice** XP during prolonged sessions; that does not establish text-message diminishing returns. **UNVERIFIED:** these sources do not establish the bots' current duplicate-message detection or semantic anti-spam algorithms. Do not copy undocumented numeric rules from community guides. [A1](https://docs.arcane.bot/plugins/leveling/setup/xp-options)[A2](https://lurkr.gg/docs/guides/customize-leveling-speed)[A3](https://mee6bot.freshdesk.com/support/solutions/articles/101000469306-how-to-fix-server-members-not-getting-xp)

### Storage and process behavior

- SQLite WAL permits readers alongside a writer, but still permits only **one writer at a time** and requires the participating processes to be on the same machine. `BEGIN IMMEDIATE` starts a write transaction and can fail with `SQLITE_BUSY` if another writer exists. [S1](https://sqlite.org/wal.html)[S2](https://sqlite.org/lang_transaction.html)
- In WAL mode, `synchronous=FULL` adds commit synchronization for durability. `NORMAL` can lose recent committed transactions after an operating-system crash or power failure, although it preserves consistency and application-crash durability. [S3](https://sqlite.org/pragma.html#pragma_synchronous)
- **Recently changed / deployment verification required:** SQLite documents a rare WAL-reset corruption bug fixed in **3.51.3**, with fixes also in **3.50.7** and **3.44.6**. Its described trigger involves concurrent connections writing/checkpointing. **UNVERIFIED:** the actual SQLite engine and backported fixes on the eventual VPS; inspect them before adopting WAL. [S1](https://sqlite.org/wal.html)
- `aiosqlite` runs a shared request queue on one worker thread per connection. That serializes individual operations; transaction ownership must still be designed by the application. [S4](https://aiosqlite.omnilib.dev/en/stable/)
- PostgreSQL supports row-level locks and an atomic `INSERT ... ON CONFLICT DO UPDATE` outcome under concurrency. A row locked using `FOR UPDATE` prevents competing modification until the transaction ends. [S5](https://www.postgresql.org/docs/current/sql-insert.html)[S6](https://www.postgresql.org/docs/current/explicit-locking.html)
- SQLite's online backup API supports incremental backups while the source remains accessible. `systemd` supports `Restart=on-failure`; stopping normally sends `SIGTERM`, with forced termination after `TimeoutStopSec` if the service does not exit. [S7](https://sqlite.org/backup.html)[H1](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)

## Recommendations

### Count cheaply; bound abuse across channels

Use one Gateway client and a bounded processing queue. For each `MESSAGE_CREATE`, first check guild configuration, allowed channel/thread policy, author/bot/webhook status, and participation/opt-out. Then inspect text in memory, calculate a small eligibility record, and discard the text. Avoid fetching the message through REST. Disable the library's message cache; never enqueue whole message objects or log raw payloads. See [intents, permissions, and privacy](discord-intents-permissions.md).

Use nonblocking admission such as `put_nowait()` and an explicit overflow policy. Awaiting a full queue inside every event callback can leave unbounded waiting tasks holding message objects. Return promptly, measure dropped/unaccepted work, and choose whether overload may discard awards or must first commit a minimal durable record. A bounded queue alone is not end-to-end backpressure.

Maintain abuse state by **`(guild_id, user_id)` across all counted channels** so switching channels cannot bypass the cap. Server-local progression is the recommended default; global progression remains a product decision.

Use layered, configurable rules:

1. Reject short/empty messages and cap the contribution of one message. Define how URLs, mentions, emoji, code, punctuation, and repeated characters count.
2. Detect recent exact/normalized duplicates with a bounded in-memory HMAC digest set and expiry. Normalize case/whitespace consistently; do not persist text. Treat digests as user-related metadata, and do not promise semantic spam detection. A restart resets an in-memory duplicate window.
3. Apply a per-user token bucket, then a rolling activity-based diminishing multiplier. Example tuning targets are a modest per-message cap and a per-minute budget; choose values after playtesting, not from Discord API limits. Record integer awards with defined rounding.
4. Count new messages once; initially award nothing for edits and avoid delete/repost refunds. Keep bounded message-ID deduplication separately from content duplicate detection.

A token bucket permits a burst and then replenishes; it does **not** enforce an exact maximum in every rolling 60-second window. If the product promises a strict rolling-minute maximum, use timestamped award buckets. Use monotonic time for live rate calculations. Word segmentation must account for languages without spaces; character counting must explicitly choose code points or grapheme clusters. These are game rules, not settled API requirements.

### Commit steps and queue transitions together

Start with **SQLite on local persistent disk, WAL, `synchronous=FULL`, bounded busy timeout, and one database writer actor**. Confirm the installed engine contains the WAL fix above. An `aiosqlite` connection alone does not make several awaited statements one indivisible application operation: let the actor own each entire transaction, including catches/configuration changes, or use an equivalent transaction lock.

Store at least guild configuration, user progress, encounters/status, caught Pokémon, and notification state. Use `(guild_id,user_id)` keys and SQL integer counters. Apply increments in SQL:

```sql
UPDATE walker_users
SET steps = steps + :delta
WHERE guild_id = :guild_id AND user_id = :user_id;
```

Avoid reading an absolute total and later overwriting it. Within a short transaction:

- Apply accepted steps and advance encounter progress.
- Check pending count and insert only until the cap of **three** is reached.
- Continue accumulating steps while full. Consume/discard triggers that occur while full and advance the encounter cursor; **do not bank missed encounters** for the next free slot.
- Persist the encounter's outcome inputs and notification record before commit.

Only the **zero-pending → nonzero-pending** transition schedules an indicator reaction on its triggering message. Persist its channel/message ID, queue generation, and desired visible/checked state. When `/walker` checks that queue, mark the indicator checked and enqueue removal; cancel stale additions and reconcile an addition already in flight so it cannot leave an obsolete ❗. Cleanup must reference its original message/generation. Reactions are best-effort delivery: failure must not undo the encounter. Commit Catch/Run and collection changes before reporting success; use the conditional state-transition pattern in [interactions](discord-interactions.md). Never hold a database transaction across a Discord request or user interaction.

For multiple writers/processes or measured sustained write contention, migrate to **PostgreSQL**. Lock the parent user-progress row with `FOR UPDATE` before checking/inserting encounters; locking existing encounter rows alone cannot protect an empty queue. Use a consistent lock order and retry bounded transient transaction failures. Redis can later provide expiring counters/coordination, but is unnecessary initially and should not be the sole game-state store. JSON files are a poor fit for concurrent updates and relational constraints.

### Batch without hiding durability tradeoffs

A writer may group accepted message records into short transactions. Preserve event order where threshold/trigger attribution matters; merging everything into a delta must not misidentify the message that earned the first encounter.

If using **RAM-only deltas with a periodic flush**, set a flush target, for example 1–5 seconds, and monitor the oldest uncommitted event; backlog extends the actual loss window. This is an optimization proposal, not a persistence guarantee: process crashes, forced stops, and power failures can lose everything not committed. Flushing on shutdown does not eliminate that risk. Flush a user's pending deltas before presenting progress or committing an encounter derived from those deltas.

If every accepted award must survive a crash, commit a minimal event record or its aggregate transaction before treating it as accepted. Persist message IDs for the chosen replay window; retain no content. For retriable aggregate batches, store a unique batch ID in the same transaction as its increments, so an uncertain commit cannot be blindly applied twice. Keep failed batches until reconciled; do not clear dirty state before commit. Define behavior for unavailable storage and bot downtime explicitly; Gateway reconnect is not a promise to recover every message sent while offline.

### Limit visible work and operate predictably

Use the library's rate-limit handling, with a separate bounded reaction/cleanup queue. Prioritize interaction acknowledgments; defer promptly before database work. Debounce repeated display refreshes, serialize edits per interaction session, and coalesce unnecessary edits. Discord has no bulk add-reaction endpoint here: batching reduces application/DB work, not the number of required reaction calls. Respect retry delays, add backoff for transient failures, and abandon stale `403`/`404` reaction jobs after recording metadata-only diagnostics. Do not retry permission failures indefinitely.

Run one non-root `systemd` service on Ubuntu, with a virtual environment, restricted token file, `Restart=on-failure`, restart backoff, and a stop timeout long enough to drain the writer. On `SIGTERM`, stop accepting new work, drain bounded writes, close the Gateway/database, and exit. Rehydrate command/component handlers before accepting traffic after restart. Receive interactions over the Gateway initially, avoiding a separate public HTTP interaction endpoint.

Keep the database outside disposable deployment directories. Verify encryption at rest for the data volume and backups, with keys protected separately; this implements the privacy obligations described in [intents and privacy](discord-intents-permissions.md). Test restore from scheduled online backups; do not copy only the live `.db` file while ignoring WAL state.

A small VPS is a reasonable starting deployment, but **UNVERIFIED:** capacity in messages/second or RAM for this bot without measurement. Track event-loop lag, writer latency/backlog, flush age, pending reactions, `429`/`403` rates, and database size. Scale from these measurements; guild count alone does not predict load. Add shards when Discord requires/recommends them or operational measurements justify them, preserving one owner for each guild's processing and shared durable state.

## Sources

All sources checked **2026-11-04**.

- **D1**: [Discord rate limits](https://docs.discord.com/developers/topics/rate-limits).
- **D2**: [Discord message resource: reactions and editing](https://docs.discord.com/developers/resources/message).
- **D3**: [Discord Gateway: rate limits, sessions, and sharding](https://docs.discord.com/developers/events/gateway).
- **A1**: [Arcane XP options](https://docs.arcane.bot/plugins/leveling/setup/xp-options).
- **A2**: [Lurkr: customize leveling speed](https://lurkr.gg/docs/guides/customize-leveling-speed).
- **A3**: [MEE6 official support: members not getting XP](https://mee6bot.freshdesk.com/support/solutions/articles/101000469306-how-to-fix-server-members-not-getting-xp).
- **S1**: [SQLite WAL, including WAL-reset fix](https://sqlite.org/wal.html).
- **S2**: [SQLite transactions](https://sqlite.org/lang_transaction.html).
- **S3**: [SQLite synchronous pragma](https://sqlite.org/pragma.html#pragma_synchronous).
- **S4**: [aiosqlite: implementation details](https://aiosqlite.omnilib.dev/en/stable/).
- **S5**: [PostgreSQL INSERT / ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html).
- **S6**: [PostgreSQL explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html).
- **S7**: [SQLite online backup API](https://sqlite.org/backup.html).
- **H1**: [systemd service settings](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).
