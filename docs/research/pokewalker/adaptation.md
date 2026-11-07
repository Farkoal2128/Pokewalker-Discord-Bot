# Adapting walking to chat

Checked: **2026-11-04**. Scope: earning steps, scheduling encounters, and resolving them privately. All values under **Recommendations** are proposed playtest defaults, not Pokéwalker, Pokémon GO, or Discord rules.

## Decided inputs and existing repository context

The owner's current brief fixes chat-earned steps; a quiet ❗ reaction; a per-user encounter queue; ephemeral `/walker` buttons; shinies; collection storage; GO-style CP; catch/research-transfer candy; stored rare items capped at one of each; a deliberately activated, one-hour Shiny Lure; and server-owned gyms. Resource formulas, item tables, CP and gym mechanics belong to separate research tasks.

The [existing requirements draft](../../features/pokewalker-bot/README.md) proposes about three queued encounters and continued step credit when full. Its first-queued-only reaction rule is narrower than the current brief's reaction on the triggering message; the recommendation below follows the current brief. Reconcile that draft during planning. This research does not itself amend requirements or constitute an implementation plan.

## Facts: constraints that affect this loop

| Verified constraint | Source; checked |
| --- | --- |
| Default word boundaries need additional language-specific handling for languages including Chinese, Japanese and Thai; grapheme clusters approximate user-perceived characters. | [Unicode UAX #29](https://www.unicode.org/reports/tr29/), 2026-11-04 |
| Reading ordinary guild-message content requires the privileged Message Content intent, subject to Discord's configuration/approval rules. Slash commands do not grant general access to channel text. | [Discord Gateway](https://docs.discord.com/developers/events/gateway#message-content-intent), 2026-11-04 |
| Slash commands and component clicks produce interactions. An initial response/defer is required within **3 seconds**; an interaction token lasts **15 minutes**. An ephemeral response is visible to its recipient. | [Discord interactions](https://docs.discord.com/developers/interactions/receiving-and-responding), 2026-11-04 |
| Adding ❗ requires Read Message History and, if that emoji is not already present, Add Reactions. Deleting the bot's **own** reaction does not require Manage Messages; deleting somebody else's does. | [Discord message endpoints](https://docs.discord.com/developers/resources/message#create-reaction), 2026-11-04 |

**Repository correction for the next planning pass:** the existing requirements' statement about needing Manage Messages to remove the bot's reaction from another person's message confuses the message author with the reaction author. Use Delete Own Reaction. The **15-minute token lifetime is not an encounter-expiration rule**.

## Recommendations

### B1. Count characters; tune for conversation

Use **five eligible characters = one chat step**. Count normalized extended grapheme clusters containing a letter or number; exclude whitespace, punctuation-only clusters, emoji, mentions, URLs, quoted text and code blocks. Normalize consistently and cap repeated identical character runs before counting. This avoids making whitespace the definition of a word, but does not guarantee equal effort across languages. Test the actual community's languages before changing rates.

Recommended pipeline and initial settings:

| Rule | Proposed v1 default |
| --- | --- |
| Scope | Opted-in users' new messages in explicitly enabled guild channels; no bots, webhooks, edits, forwarded content or historical backfill |
| Minimum | At least **20** eligible characters after filtering |
| Repetition | Count at most **3** consecutive identical characters; reject normalized duplicate messages from the same player within **30 minutes**, across all enabled channels |
| Duplicate storage | Short-lived keyed digests, not saved message bodies; process every message ID at most once |
| Message credit | At most **100** eligible characters, hence **20** base steps per message |
| Cooldown | At most one credited message per **15 seconds** |
| Rate cap | At most **30 base steps** in any rolling **60 seconds**, before diminishing returns; excess is discarded, not deferred |
| Diminishing returns | First **500 base steps/day** at full value, later base steps at **50%**, maximum **1,000 awarded steps/day** |
| Encounter cadence | One Pokémon encounter per **100 awarded steps** while queue space exists |

Caps and duplicate detection apply across channels, not independently to each channel. Preserve fractions in fixed-point units so message boundaries do not change rewards. If `B` is the day's accepted base steps after message/cooldown/rate filtering, use this **proposed formula**:

```text
awarded_today(B) = min(1000, min(B, 500) + max(0, B - 500) / 2)
new_credit = awarded_today(B_after) - awarded_today(B_before)
```

Use one fixed reset timezone per economy, initially UTC, and show it to players. A timezone setting change must not reset the budget immediately. There is no daily reset of lifetime progress, queued encounters, or partial encounter progress.

Illustrative pacing, assuming messages are spaced enough to pass rate/cooldown checks, do not repeat, and the queue is regularly cleared:

| Chatter scenario (assumptions, not measured behavior) | Base steps/day | Awarded steps/day | Encounter opportunities/day |
| --- | ---: | ---: | ---: |
| Casual: 10 eligible messages × 50 counted characters | 100 | 100 | 1 |
| Regular: 25 × 60 | 300 | 300 | 3 |
| Active: 60 × 75 | 900 | 700 | 7 |
| Very active: 100 × 100 | 2,000 | 1,000 | 10 |

These are opportunities, not guaranteed catches. A queue left full reduces them. The rolling cap gives a theoretical minimum of **100/30 ≈ 3.33 minutes** of sustained credited activity per encounter over long periods before diminishing returns; it is not an exact minimum between individual encounters because meters can already be partly filled.

Do not promise spam detection from length checks alone: varied nonsense and copied text can bypass simple duplicates. Start with these deterministic limits and moderation controls; defer similarity scoring. Measure credited steps, queue saturation and completed encounters in aggregate. Change cadence after playtesting rather than rewarding increasingly long messages.

### B2. Drop spendable watts in v1

Keep steps as non-spendable progress. Let the step meter directly earn an encounter; use the separately researched candy/resource economy for power-ups. Charging watts as well as requiring chat progress would add another budget between an earned encounter and playing it.

Do not merge watts into candy: their functions differ, and walking would then compete with catching/research transfers as a source of power. An optional future watt cosmetic/stat is harmless if it cannot buy extra encounter rolls. Original-device costs remain historical facts in [mechanics](mechanics.md), not bot requirements.

### B3. Personal route choice within server policy

For v1, recommend **server-scoped player profiles** keyed by `(guild_id, user_id)`: each player chooses a route from the server's enabled catalogue. Progress, queues and collection ownership must use the same scope. Cross-server collections are an open product decision; if selected instead, move anti-farming budgets and deduplication to the global user at the same time.

Start with **Refreshing Field and Noisy Forest unlocked**, then optionally unlock Rugged Road at **1,000 lifetime awarded chat steps**. These are proposed bot unlocks; the original catalogue is in [mechanics](mechanics.md). Avoid weekly mandatory rotation initially; a later featured server route can coexist with personal choice.

Maintain separate lifetime steps, progress accumulated on each route, and the encounter meter. Persist per-route progress across switching. Route changes affect future triggers only: pending species, rarity, shiny state and outcomes never reroll. Switching is not an encounter and grants no steps.

For a simple bot rarity model, use all six listed slots on the selected route rather than selecting a hidden pair member per stroll. **Proposed** availability: C immediately, B after **100 route steps**, A after **500 route steps**. Among available groups, normalize **A:B:C weights 10:30:60**, then choose one of the two slots uniformly within the group. Thus C-only gives 100% C; B/C gives 1/3 B and 2/3 C; all groups give 10%/30%/60%. These are intentionally new weights, not reinterpretations of historical conditional chances. Preserve repeated-species slots as distinct variants. Do not execute the original physical-step thresholds from the example schema as chat thresholds.

### B4. Short private minigames

Use the bounded flows in [minigames](minigames.md): a reveal/catch interaction for v1; optional preparation and a short dowsing search. Avoid a reflex deadline. Handle each click as a state transition and edit the private view; a fresh `/walker` reconstructs the current state after a restart or dismissed message.

Dowsing can be added after the item task defines a reward table. **Proposed later cadence:** one separate item-search opportunity per **300 awarded steps**, with one pending item search per profile; freeze its meter when full. Do not replace a promised Pokémon encounter with an item. The exact item cadence is an open balance decision, not necessary for the first Pokémon-loop prototype.

### B5. Keep a three-encounter queue, without copying storage semantics

Keep **3 unresolved encounters** for the initial playtest, including any currently revealed/active encounter. The reason is a short, manageable backlog, not a device restriction. Caught collection capacity is a separate setting.

On each credited message, atomically:

1. Deduplicate the message and update lifetime/day/route counters using awarded steps.
2. If the unresolved queue is full, leave the encounter meter unchanged. New steps still count toward progress, but earn no deferred encounter debt.
3. Otherwise add awarded steps to the meter; at **100**, subtract **100** and create an encounter. Retain the sub-threshold remainder. Never derive pending encounters later from lifetime steps.
4. Persist the route/configuration version, species/variant, trigger time, origin message/channel, and hidden encounter randomness. Only after commit, schedule the quiet notification.

The message cap means a normal message cannot generate multiple Pokémon encounters. Still enforce the queue limit transactionally so concurrent channel messages cannot overfill it. **No automatic expiration or replacement** in v1; Run deliberately discards the chosen encounter. If collection storage is full, preserve the encounter and offer storage management before a catch or ball consumption.

**Notification policy:** add ❗ only to each message that actually creates a new queued encounter, following the current brief. Remove the bot's own reaction when `/walker` acknowledges that encounter. Ordinary messages and blocked triggers while full get no reaction. Failed/missing reactions must not delete an encounter. Store notification state separately and retry idempotently; no public messages, pings or DMs. The earlier first-queued-only policy is an optional quieter alternative, not the default here.

**Resolution invariants:** authorize the owner and guild on every action; allow one current encounter transition at a time; store action/interaction IDs and version checks. Catch, collection insertion, ball consumption and catch-candy grant must commit once together. A duplicate click returns the saved result. Closing a view or timing out never rerolls a species, shiny state, catch attempt or hidden dowsing location.

**Connections to later research:** determine shiny state at **enqueue time**, using whether a deliberately activated lure is active at that timestamp. Reopening an older encounter cannot apply a newly activated lure. Store the policy version and immutable random seed/result; CP generation can attach to that same encounter identity after its separate design is approved. Do not invent a shiny rate or lure multiplier here. Use the item subsystem's atomic grant/consume interface, respecting the owner's **one of each rare item** limit. Sending a catch away for research is a separate, explicit action and must not happen automatically when storage is full.

### B6. Peer play: later, mutual, and bounded

Add `/walker peer @user` after the solo loop is enjoyable. An ephemeral invitation cannot be viewed by the other user; instead, write a pending request to their walker inbox for acceptance on their own `/walker`. No unsolicited public ping or DM is necessary.

Require both users in the same server, non-bot accounts, and mutual acceptance. **Proposed limits:** one rewarded interaction per unordered pair per UTC day; no self-pairing; at most **3** rewarded peer interactions per player per day. Record the pair/day once and grant both rewards transactionally. Reject/expire requests without a reward. Pair-only limits are insufficient against many alternate accounts, hence the per-player ceiling. Use a common item or cosmetic benefit from the item policy; no rare items, shiny rerolls, trading, or extra encounter rolls in v1.

### B7. Fun-to-effort priority

| Rank | Scope | Recommendation and reason |
| --- | --- | --- |
| 1 | v1 | Quiet earning → three queued encounters → private reveal/catch → collection; the complete reward loop |
| 2 | v1 | Reliable persistence, anti-farming, idempotent catch and meaningful shiny reveal; protects earned outcomes |
| 3 | v1 | Two personal routes, simple explicit rarity weights and progress display; small implementation cost for choice |
| 4 | v1 / next | Catch candy and item/ball hooks, with numeric policies supplied by their separate research; necessary boundaries |
| 5 | Next | Dowsing and earned item opportunities; short additional activity once item tables exist |
| 6 | Later | Third route/unlock progression, optional preparation, collection goals and featured routes |
| 7 | Later | Mutual peer visits; social value but extra notification, abuse and concurrency work |
| 8 | Cut initially | Exact timed bush chasing, four-HP battle replication, daily rarity resets, hidden per-stroll slot selection and separate watt spending |

Before implementation, resolve collection/profile scope, capture and shiny policies, ball supply, item-search pacing, and whether to accept the proposed rates/route model. Keep CP formulas, transfer resource amounts, rare-item probabilities and gyms in their own research tasks.
