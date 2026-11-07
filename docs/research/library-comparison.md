# Discord library comparison

Checked: **2026-11-04**. Scope: Gateway message counting, private slash-command screens, buttons, and durable game state. Version numbers below are the observed documentation snapshot, not an instruction to float dependencies.

## Facts

| Library | Maintenance evidence and runtime | Relevant APIs and typing |
| --- | --- | --- |
| **discord.py** | Stable changelog includes **2.7.1**, with interaction/view fixes; Components V2 support arrived in 2.6. Its package declares Python >=3.8 and typed-package metadata. [P1][P2] | `app_commands.CommandTree`, `InteractionResponse`, `ui.View`, and `ui.LayoutView`; persistent dispatch through `Client.add_view()` / `add_dynamic_items()`. Public API signatures carry Python types. [P3][P4] |
| **discord.js** | Releases and stable docs show **14.28.0**. It is a Node.js library with bundled TypeScript declarations. See runtime uncertainty below. [J1][J2][J3] | `interactionCreate`, slash/component builders, typed interaction guards, `reply`, `deferReply`, `update`, `deferUpdate`, and `editReply`. Collectors offer time-limited interaction handling. [J4][J5][J6] |
| **disnake** — alternative | Stable changelog includes **2.12.2** and recent maintenance fixes; V2 support arrived in 2.11. [N1] | Python async API, `InteractionBot`, application commands, typed UI components, and interaction response helpers. [N2][N3] |

- **Persistence is application work.** discord.py registers views/dynamic items for dispatch; it does not turn their Python fields into database records. A normal persistent view requires explicit component IDs and `timeout=None`; sending it ephemerally substitutes a 15-minute timeout when none is set. See the full restart caveats in [discord-interactions.md](discord-interactions.md). [P3][P4]
- **discord.js collectors are scoped listeners.** They have time/end conditions. A global `interactionCreate` listener can route by `customId`; neither mechanism stores encounter state. [J4][J5][J6]
- **Caches affect both footprint and privacy.** discord.py defaults to caching 1,000 messages; `max_messages=None` disables that cache. discord.js exposes `makeCache` and sweepers, with specific core-manager caches that must not be overridden. [P4][J7]
- **Async database access is available in Python.** `aiosqlite` runs queued operations on a worker thread per connection. This protects the event loop from synchronous query waits; whole-transaction ownership remains the application's responsibility. [D1]

### UNVERIFIED / version-sensitive

- **Exact effective Node minimum for the deployment:** discord.js's current installation page says **24.17.0+**, while the tagged 14.28.0 package manifest declares **>=18**. Transitive dependencies and support policy also matter. Resolve and lock the chosen release, inspect all engine requirements, and test on a currently supported Node LTS; do not take the root manifest as sufficient. [J2][J3]
- **Comparative memory, throughput, and maximum server count:** no workload-specific benchmark was performed. Claims that either runtime uses a particular amount of RAM or is intrinsically sufficient for a given guild count are **UNVERIFIED**. Published API features and release activity do not guarantee future maintenance.

## Recommendations

### Choose discord.py for this project

Use **Python 3.12+ on a supported Ubuntu release, a pinned discord.py release, `aiosqlite`, and SQLite WAL**, in one long-running process. Pin and test the linked SQLite runtime too; see [storage and hosting](discord-rate-limits-performance.md). The repository's Python framework checks are not evidence that the application stack is already decided.

Reasons for this recommendation:

| Decision factor | Judgment for this bot |
| --- | --- |
| Interaction ergonomics | View/button classes and decorators make the small device-screen flow easy to express. Use registered dynamic handlers when dispatch must be rebuilt after restart. |
| Complexity | One Python process plus an embedded database is a compact operational starting point. No voice package, dashboard, Redis, or additional service is necessary for the initial scope. |
| Type safety | Add a strict project type checker and typed domain records. TypeScript with discord.js offers an equally strong option if the maintainer already prefers that ecosystem; runtime ownership/state validation is still required in either language. |
| Ecosystem | Python fits small state machines, tests, and data processing; JavaScript/TypeScript becomes more attractive if a substantial web dashboard will share types and tooling. This is a workflow judgment, not a popularity ranking. |
| Alternative | disnake is credible, especially with existing team expertise, but none of the requested behaviors requires choosing a fork. Avoid mixing examples from incompatible Python wrappers. |

Keep the Discord adapter thin: message events produce content-free counting inputs; a domain service owns progression and encounters; a transaction-owning persistence layer owns rewards and queue mutations. Reconstruct screens from stored state. Never make a view, collector, or in-memory lock the only record of a catch.

Use classic buttons initially. Add a small application-specific validation suite during implementation: simultaneous Catch/Run, queue-full counting, crash/retry idempotency, denied reaction permissions, and reopening `/walker` after restart. These determine reliability more than the language choice. Register/sync commands deliberately during deployment; avoid repeated bulk registration on every reconnect.

## Sources

Each linked fact above uses the corresponding source below; all were checked **2026-11-04**.

- [P1] discord.py changelog — checked 2026-11-04.
- [P2] discord.py v2.7.1 package metadata — checked 2026-11-04.
- [P3] discord.py interactions reference — checked 2026-11-04.
- [P4] discord.py client/API reference — checked 2026-11-04.
- [J1] discord.js releases — checked 2026-11-04.
- [J2] discord.js stable installation documentation — checked 2026-11-04.
- [J3] discord.js 14.28.0 package metadata — checked 2026-11-04.
- [J4] discord.js command handling guide — checked 2026-11-04.
- [J5] discord.js ButtonInteraction API — checked 2026-11-04.
- [J6] discord.js collectors guide — checked 2026-11-04.
- [J7] discord.js ClientOptions API (versioned 14.25.1 reference) — checked 2026-11-04.
- [N1] disnake changelog — checked 2026-11-04.
- [N2] disnake bot APIs — checked 2026-11-04.
- [N3] disnake components reference — checked 2026-11-04.
- [D1] aiosqlite documentation — checked 2026-11-04.

[P1]: https://discordpy.readthedocs.io/en/stable/whats_new.html
[P2]: https://github.com/Rapptz/discord.py/blob/v2.7.1/pyproject.toml
[P3]: https://discordpy.readthedocs.io/en/stable/interactions/api.html
[P4]: https://discordpy.readthedocs.io/en/stable/api.html
[J1]: https://github.com/discordjs/discord.js/releases
[J2]: https://discord.js.org/docs/packages/discord.js/stable
[J3]: https://github.com/discordjs/discord.js/blob/14.28.0/packages/discord.js/package.json
[J4]: https://discordjs.guide/legacy/app-creation/handling-commands
[J5]: https://discord.js.org/docs/packages/discord.js/main/ButtonInteraction%3Aclass
[J6]: https://discordjs.guide/legacy/popular-topics/collectors
[J7]: https://discord.js.org/docs/packages/discord.js/14.25.1/ClientOptions%3AInterface
[N1]: https://docs.disnake.dev/en/stable/whats_new.html
[N2]: https://docs.disnake.dev/en/stable/ext/commands/api/bots.html
[N3]: https://docs.disnake.dev/en/stable/api/components.html
[D1]: https://aiosqlite.omnilib.dev/en/stable/
