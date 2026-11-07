# Pokéwalker Discord bot: implementation research

Checked **2026-11-04**. Supports the [requirements draft](../features/pokewalker-bot/README.md). This is research, not an approved implementation plan. Each topic separates sourced facts from recommendations and marks unresolved claims **UNVERIFIED**.

## Facts

- **Intent review changed in June 2026:** the threshold is **10,000 unique users with access across installed servers**, with 90 days to apply after notification and annual reapplication. **App verification remains separate, for growth past 100 servers.** The requirements draft's old intent threshold needs reconciliation before planning. [F1][F2] (checked 2026-11-04)
- **Passive words/characters require Message Content.** Counting message events alone is possible without it, but cannot reproduce length checks or content-based duplicate detection. This follows from the documented data restrictions and alternatives. Approval for this particular game is **UNVERIFIED**. [F3] (checked 2026-11-04)
- **Private screens are interaction responses.** Acknowledge within **3 seconds**; tokens last **15 minutes**. Ephemeral display lifetime is unspecified, and restoring bot handlers does not guarantee an old screen remains usable. [F4][F5] (checked 2026-11-04)
- **Removing the bot's own reaction needs no `MANAGE_MESSAGES`.** The author of the underlying message does not change this. Correct that separate assumption in the requirements draft before implementation. [F6] (checked 2026-11-04)
- **No-text storage still has privacy obligations:** an accessible privacy policy, modification/deletion request path, appropriate retention, and encryption at rest. [F7] (checked 2026-11-04)

## Recommendations

Use **Python 3.12+, pinned discord.py, `aiosqlite`, and patched SQLite in WAL mode**, on encrypted persistent storage under one Ubuntu `systemd` service. Prefer classic Catch/Run buttons initially. PostgreSQL is the next option for multiple workers or measured write contention; inspect the documented SQLite WAL fix before deployment.

Process text briefly, retain counts/game state plus essential IDs, and disable content caches/logging. Use per-server/user abuse controls across channels. One database writer owns complete transactions: steps keep accruing at the three-encounter cap, excess triggers are discarded, and only an empty-to-nonempty queue schedules ❗. Remove that indicator when checked; keep reaction work outside database transactions.

Persist encounter resolution and rewards atomically before editing the screen. Conditional state/revision updates prevent double Catch/Run awards. Reopening `/walker` reconstructs durable state after restart. Prefer player enrollment, with opt-out, privacy, and deletion commands.

## Open decisions

- Words or characters; multilingual segmentation, emoji/URL handling, minimum length, caps, duplicate window, and diminishing-return curve.
- Server-local versus global progress; counted channels and thread inheritance; reaction settings.
- Encounter trigger rules and expiry, distinct from screen expiry; catch/collection game mechanics.
- Crash-loss tolerance for buffered steps versus committing every accepted award.
- Enrollment/retention details and the fallback if Message Content approval is denied.

## Topic files

| File | Read for |
| --- | --- |
| [discord-interactions.md](discord-interactions.md) | Ephemeral lifecycle, restart recovery, components, race-safe actions |
| [discord-intents-permissions.md](discord-intents-permissions.md) | Updated intent review, permission matrix, privacy obligations |
| [discord-rate-limits-performance.md](discord-rate-limits-performance.md) | Anti-farming survey, rate limits, queues, storage, VPS operation |
| [library-comparison.md](library-comparison.md) | Library evidence, stack rationale, runtime uncertainties |

## Other research

- **[Research synthesis and review](synthesis.md): start here.** It consolidates all the topics below, lists their conflicts and the decisions still open.
- [PokéAPI forms and families](data-visuals/pokeapi-forms.md), from [this brief](briefs/pokeapi-forms.md) (PR 6). Its review is [synthesis §7](synthesis.md#7-review-of-the-pokéapi-forms-research-pr-6).

- [Pokéwalker walking and encounter loop](pokewalker/README.md), including [chat adaptation](pokewalker/adaptation.md).
- [GO progression systems](go-systems/README.md).
- [Per-server gyms](gyms/README.md).
- [Species data and visuals](data-visuals/README.md).
- [Home Ubuntu hosting](hosting/README.md).

These recommendations are proposed playtest rules, not approved requirements or an implementation plan. Reconcile task 1's step budget and encounter cadence with task 2's owner-selected hourly pacing, as well as server-local versus global ownership and passive finds versus dowsing.

Keep facts and recommendations separate, date and cite facts, and check Discord limits against official documentation. Describe mechanics in our own words; do not commit ROMs, dumps, sprites, audio or copied code. The requested Claude research review remains pending before planning and a stack ADR.

[F1]: https://support-dev.discord.com/hc/en-us/articles/40281523410967-Changes-to-Privileged-Intent-Access-for-Discord-Apps
[F2]: https://support-dev.discord.com/hc/en-us/articles/23926564536471-How-Do-I-Get-My-App-Verified
[F3]: https://docs.discord.com/developers/gateway/you-might-not-need-a-privileged-intent
[F4]: https://docs.discord.com/developers/interactions/receiving-and-responding
[F5]: https://support-apps.discord.com/hc/en-us/articles/26501839512855-Ephemeral-Messages-FAQ
[F6]: https://docs.discord.com/developers/resources/message#delete-own-reaction
[F7]: https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service
