# Contract: step credit and chat-rate measurement (C2)

## Purpose
Implement [D20/D33/D43](../docs/features/pokewalker-bot/README.md) and PLAN P6/P9
once for the bot, measurement and simulation, without storing message content.

## Producers
- `pokewalker/domain/steps.py`: `eligible_words` and pure `accept_message`.
- `scripts/measure_chat_rate.py`: in-memory history adapter and JSONL measurement CLI.

## Consumers
- The future bot's per-server, per-player SQL adapter and economy simulation.
- The owner keeps private per-member totals and reviews the anonymised summary.

## Invariants
- Remove fenced code, lines starting with optional whitespace and `>`, URLs,
  Discord mentions/custom emoji and Unicode emoji before UAX #29 default word
  segmentation (`regex.WORD`). Removed spans separate words. Keep segments with
  at least two Unicode letters or digits; single CJK ideographs do not qualify.
- `accept_message(words, at, history, rules)` takes filtered words, finite seconds,
  a player-scoped history and the authored `step_rules.json` rules mapping.
  Casefold repetition cap 3 precedes minimum 4, message cap 20, cooldown 15 seconds,
  rolling-minute capacity 30 accepted words, then duplicate check (1,800 seconds).
  Excess words are discarded immediately; a positive minute remainder may credit
  fewer than four words after the message has passed its minimum.
- History exposes `accepted_words_since(since)`, `last_credit_at`,
  `seen_digest(digest, since)` and `digest_key: bytes`. Queries exclude the lower
  boundary and include earlier credits through the current message time. Callers
  process messages chronologically and record only credited decisions afterward.
  Histories cover all enabled channels for one `(guild_id, user_id)`.
- Duplicate identity is HMAC-SHA256 of casefolded, whitespace-normalized eligible
  segments **before** repetition/message caps. The key is random, secret, ephemeral
  per process and at least 32 bytes; no normalized words are returned or persisted.
  Bot adapters keep duplicate digests in memory only and reset them on restart.
- Immutable `Decision` carries `accepted_words`, integer `awarded_c` (hundredths),
  `discarded_words` (all input words minus accepted count), `reason` and `digest`.
  Reasons are `credited`, `minimum`, `cooldown`, `minute_cap`, `duplicate`.
  Rejections award zero. D20 counts prior accepted words in `(at-3600, at]`, then
  splits the new words: below 300 awards 100 hundredths each, otherwise 25.
- CLI: `python scripts/measure_chat_rate.py INPUT --output PRIVATE_JSON [--summary]`.
  JSONL requires `author_id`, `channel_id` (nonempty strings or integers),
  `created_at` (finite Unix seconds or timezone-aware ISO 8601), `content` (string),
  `is_bot` (boolean). Input must be chronological; invalid input exits nonzero with
  a line number, never content or member IDs. Bots receive no credit.
- Private JSON is a list of `{author_id, hour, accepted_words, awarded_c}` for UTC
  calendar hours with at least one credited message. Neither output includes
  message bodies, channel IDs, words or digests. Input cannot be an output path.
  `--summary` writes only aggregate active-hour count and p50/p90/p99 of accepted
  words and awarded steps to
  `docs/features/pokewalker-bot/measurements/chat-rate-summary.md`.
  Percentiles linearly interpolate sorted member-hour totals; empty input yields
  zero percentiles. Private JSON must never be committed by the operator.

## Compatibility
New additive API and offline formats; no existing clients or persisted data change.
Changes to counting, windows, decision fields or formats require consumer review.

## M1.5 SQL and Gateway adapter (additive)
`services.stepping.credit_message(conn, profile, words, created_at, message_id,
channel_id, *, content, rng, cache=None)` requires
the caller's writer transaction and returns the first newly minted encounter ID
for any message that mints an encounter, otherwise None. The profile is refreshed inside
the job and restrictions are checked again. Message IDs deduplicate durably.
Accepted history uses SQL message times in `(at-window, at]`, across channels;
future records never contribute. Duplicate digests live only in a bounded
per-profile in-process LRU with a random ephemeral HMAC key. Only committed,
credited SQL events matching cached IDs/times contribute duplicate history.
Paused events store discarded counts and reason `paused`; excluded users produce
no event. Missing timestamps store a zero-award `no_timestamp` event using receipt
time for diagnostics, never for credit. Timestamps otherwise must be aware.

`advance_meter(current_c, awarded_c, threshold_c, frozen)` returns remainder and
trigger count; frozen meters preserve their value. Full encounter queues preserve
the encounter meter and accrue no debt. Partial progress survives; minted rolls,
route, source IDs, lure ID and semantic content hash are saved atomically. Only a
non-null companion permits companion-meter increments. D25 consumes every 15,000
hundredths for one Candy to the current companion's exact artifact family,
including gender varieties. The profile meter keeps its remainder across swaps
and freezes without a companion while steps still credit. The same writer job
stores an owner-bearing `companion:<message_id>` receipt (action
`companion_candy`) and a positive Candy ledger line with reason `companion_candy`.
The existing message key prevents duplicate credits; receipt or ledger failures
roll back the step credit, meters and Candy together. No schema change is needed.
The 2026-11-04 owner amendment replaces M3.4's time window with the next ten
generated encounters. Before each mint, stepping reads the durable active effect,
uses its single ×4 shiny probability roll, freezes its ID and decrements its
remaining_encounters in the same writer transaction. Zero ends the effect; a
multi-mint message may cross exhaustion and generate ordinary encounters thereafter.
Message timestamps do not determine lure eligibility. Existing queued encounters,
duplicate messages and messages that mint nothing do not spend charges. Failure
rolls back encounters and charges together. Explicit lure_active/lure_id overrides
are removed (breaking internal API; only its test used them) so callers cannot
bypass durable exhaustion. Bag, item activation and stepping consume C3's counter.

## M3.1 passive finds (additive)
The same message-credit writer calls `items.apply_finds(conn, profile, awarded_c,
at, message_id, rng, content)` after encounter progress and before saving profile meters.
It returns the new find meter in hundredths. One find triggers at 10,000; message
awards are at most 2,000, so there is at most one find per message. Count all find
outcomes for this profile in `(at-3600, at]`; future rows do not count. At three
finds the meter is frozen without adding steps or backlog. The third triggering
find sets the meter to zero, discarding the rest of that message (D21's 99 + 20
example). Earlier finds keep the remainder. The freeze lifts by message time
when the oldest row leaves the rolling hour. Paused/excluded messages add none.
`find:<message_id>` receipts, grant, find row, ledger and step credit commit or
roll back together. Replaying a find receipt never rolls or grants again.

`bot.messages.on_message(bot, message)` ignores bots, webhooks, DMs, unconfigured
or disabled guild/channels (threads inherit the parent), unenrolled and excluded
members. It segments content in memory and discards the message before queuing
the content-free writer job. Each message commits independently. Each message that
mints one or more encounters writes one pending reaction in the same transaction;
full queues mint nothing and write no reaction. Reconciliation
runs after the writer returns, outside the transaction. WalkerBot delegates only
while admission is open. No raw message text or digests enter persistent storage.
Verification: `tests/test_stepping.py`, `tests/test_messages.py`, and Gateway
admission coverage in `tests/test_client_lifecycle.py`.

## Verification
`python -m unittest discover -s tests -p "test_steps.py"` and
`python -m unittest discover -s tests -p "test_measure_chat_rate.py"`.

## Change policy
Requirements take precedence over research proposals. Counting/balance revisions
require a deliberate D20/D33 requirement change and contract tests before implementation.
