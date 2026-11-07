# Discord intents, permissions, and privacy

Checked **2026-11-04**. Scope: server message counting and private encounter interactions. Source keys link to primary documentation; dates appear below.

## Facts

### Message Content access and verification

**RECENT CHANGE — verified:** Discord changed privileged intent review on **June 10, 2026**. The threshold is now **10,000 unique users with access to the app across its installed servers**, rather than 100 servers. Below that threshold, enable needed intents in the Developer Portal. At the threshold, Discord notifies the owner and provides **90 days from notification** to apply. Timely submissions retain current access during review; apps can continue joining servers. Previously approved apps must reapply annually after notification. App verification and privileged intent review are now separate. [I1][I2]

App verification remains necessary to grow **past 100 servers**. The Developer Portal provides a verification checklist; the team owner completes identity verification through Stripe. A verified app does not thereby have unconditional Message Content access, and an unverified app in a few large servers can reach the intent-review threshold. [I1][I3]

`MESSAGE_CONTENT` controls message-content fields across Discord APIs, including `content`, `embeds`, `attachments`, `components`, and `poll`; it does not subscribe to events itself. Without access, affected fields are empty except for the app's own messages, DMs with the app, messages mentioning it, and messages targeted by a message context-menu command. Fetching messages through REST does not bypass the restriction. Enable the intent in both the portal and the Gateway client; unauthorized privileged-intent identification can close the connection with code `4014`. [I4]

Discord reviews whether an intent is necessary for the stated compliant functionality. Its current guide asks for the exact feature, why interactions cannot replace it, and responsible data handling, including in-memory processing/discarding or storage retention/security. Generic claims that a bot “needs message content” are insufficient. Unnecessary access, policy violations, or unclear/incomplete submissions can cause rejection. There is no published promise that this game's justification will be accepted. [I2]

**Applicability:** passive word/character measurement and content-based duplicate detection on arbitrary server messages require Message Content. Slash commands, DMs, mentions, and context menus provide explicitly selected input; they do not expose every ordinary message. Counting message events without reading text is possible, but cannot implement the specified length and duplicate rules. This is a technical conclusion from Discord's documented exceptions and alternative-intent guidance. [I4][I5]

### Gateway intents and installation

| Requirement | Necessary capability |
| --- | --- |
| Receive new server messages | `GUILD_MESSAGES` [I4] |
| Access their ordinary text | `MESSAGE_CONTENT` [I4] |
| Maintain guild/channel information for configuration | `GUILDS` [I4] |
| Receive reaction-add/remove events | `GUILD_MESSAGE_REACTIONS` only if subscribing to those events; REST reaction operations do not need this subscription [I4][I9] |
| Resolve the invoking user/message author | IDs/member data arrive in the relevant events/interactions; no full member-list or presence subscription is needed for these features [I4][I6] |

The Gateway intent map and interaction payload specify these data/event boundaries. `GUILD_MEMBERS`, `GUILD_PRESENCES`, and `DIRECT_MESSAGES` are unnecessary for the stated design. [I4][I6]

Install with the **`bot`** scope and **`applications.commands`**; the latter is automatically included by `bot`. No user `identify`, `email`, or `guilds` OAuth authorization flow is needed for this installation. Interaction webhooks do not require creating a channel webhook. [I7][I6]

### Channel and command permissions

Permissions below concern the **bot**, except where the row explicitly names the user. Effective permissions include channel overwrites. [I8]

| Behavior | Minimum relevant permission / distinction |
| --- | --- |
| Observe new messages in a configured channel | `VIEW_CHANNEL`; historical fetching additionally requires `READ_MESSAGE_HISTORY` [I8][I9] |
| Add the first ❗ reaction | `VIEW_CHANNEL` + `READ_MESSAGE_HISTORY` + `ADD_REACTIONS`; the last is unnecessary only if that emoji already has a reaction [I9] |
| Remove the bot's own ❗ from a user's message | Use **Delete Own Reaction** (`…/reactions/{emoji}/@me`); **`MANAGE_MESSAGES` is not required** merely because someone else authored the message [I9] |
| Remove someone else's reaction, or clear every reaction for an emoji/message | `MANAGE_MESSAGES`; these are different endpoints and unnecessary for this design [I9] |
| Invoke `/walker` | The **user** needs access to the command, including `USE_APPLICATION_COMMANDS` and applicable command/channel restrictions [I8][I10] |
| Ephemeral response, Catch/Run update, follow-up | Use the interaction callback/token routes; these are distinct from the normal bot channel-message route. No `MANAGE_MESSAGES` or `MANAGE_WEBHOOKS` grant is needed for the bot's own interaction response [I6] |
| Ordinary channel message, if added later | `SEND_MESSAGES`; within threads, `SEND_MESSAGES_IN_THREADS`; embeds/files can need their corresponding permissions [I8] |
| Save admin configuration in the bot database | No Discord management permission for the bot; authorize the **invoking administrator** [I10] |

Reaction endpoints explicitly distinguish own reactions from other users' reactions. The table does **not** recommend giving `MANAGE_MESSAGES` to clean up encounter indicators. [I9] Permission meanings and thread rules are documented in [I8]; interaction routes and command authorization in [I6][I10].

### Privacy and developer obligations

The Developer Terms apply to **processing**, including access and transient use, not just persistent storage. They require an accurate privacy policy explaining collection/use/sharing and deletion requests; publish its current URL in the Developer Portal and make it easily accessible from the app. Users must have an accessible way to request modification/deletion. Subject to legally required retention, delete API data promptly when no longer necessary, when operation stops, or when Discord/the relevant user requests it. Security measures expressly include **encryption at rest**, safeguards, and incident reporting. “We never save message text” does not remove these duties. [I11] (§5)

Developer Policy limits API data to necessary stated/approved functionality, requires respecting opt-outs/blocking/removal, and requires a reporting/support mechanism. It prohibits profiling users or their relationships and scraping; message-content use for AI training requires Discord permission. It also requires permission before initiating processes on a user/server's behalf. The policy does not prescribe a command specifically named `/opt-out`; respecting applicable opt-out decisions and providing data-deletion access are requirements. [I12]

`discord.py` caches up to 1,000 messages by default; `max_messages=None` disables that cache. This matters even when the database never contains text. [I13]

## Recommendations

- **Enable only** `GUILDS`, `GUILD_MESSAGES`, and `MESSAGE_CONTENT`. Filter configured guilds/channels, bots/webhooks, and opted-out users before normalization/counting. Enable tracking only after an administrator deliberately configures it.
- **Use guild installation and guild-only commands.** Restrict configuration commands with `default_member_permissions=MANAGE_GUILD` and check the invoking member's permission again in the handler. Defaults can be overridden by server command settings; runtime authorization protects the configuration policy. [I10]
- **Persist explicit per-server configuration.** Store a counted-channel allowlist and a reaction-enabled switch, with optional channel overrides. Validate channel ownership and effective bot access, define thread inheritance, and update the database and in-memory configuration cache consistently.
- **Start with `VIEW_CHANNEL`, `READ_MESSAGE_HISTORY`, and `ADD_REACTIONS`** for tracked channels using Unicode ❗. Disable indicators gracefully when permissions are missing; keep `/walker` usable. Do not request Administrator. Threads/private threads need a separately tested access policy.
- **Prepare a truthful review submission:** explain content-derived steps and short-lived duplicate detection, why explicit interaction input changes the core passive behavior, exactly which fields are examined, and what is discarded. Include screenshots and retention/security details. Do not describe gameplay as moderation to obtain approval. Keep an event-counting fallback as an explicit product decision.
- **Prefer explicit player enrollment**, plus `/walker opt-out`, `/walker delete-data`, and `/walker privacy`. Explain transient content processing, retained user/guild IDs, counts, game records, retention, and contact details. Server installation alone should not be treated as a researched legal basis for every member's personal-data processing.
- **Minimize retained information.** Persist game state and essential IDs only; disable message caching and payload logging, including error-reporting snapshots. For duplicates, keep bounded, short-lived keyed fingerprints in memory and document this processing. Do not claim hashes or per-user counts are anonymous. Protect the database and backups with encryption; define deletion/backup-expiry procedures and avoid automatically recreating a deleted profile on the next message.

## UNVERIFIED / implementation checks

- **Approval for this specific word/character-based game is UNVERIFIED.** No current official source found categorically accepting or rejecting all XP/leveling bots.
- **Documentation inconsistency:** parts of the general Gateway reference still describe post-verification intent approval. Prefer the dated June 2026 announcement and dedicated review guide; check the portal when approaching the threshold. Older “apply at 75 servers / approval at 100” privileged-intent instructions are obsolete. [I1][I2][I4]
- **The old 75-server eligibility threshold for app verification is UNVERIFIED currently.** The current verification page directs developers to the portal checklist without specifying 75. [I3]
- **Restricted-channel interaction edge cases are UNVERIFIED by a live test here.** Test `/walker`, ephemeral follow-ups/updates, and bot-own reaction removal with only the proposed grants and denied `SEND_MESSAGES`, including thread overwrites. Do not silently broaden permissions if an operation fails.

## Sources

All checked **2026-11-04**.

- **I1:** [Discord: Changes to Privileged Intent Access](https://support-dev.discord.com/hc/en-us/articles/40281523410967-Changes-to-Privileged-Intent-Access-for-Discord-Apps) — announcement updated June 11, 2026.
- **I2:** [Discord: Getting Started with Privileged Intent Review](https://docs.discord.com/developers/gateway/getting-started-with-privileged-intent-review).
- **I3:** [Discord: How Do I Get My App Verified?](https://support-dev.discord.com/hc/en-us/articles/23926564536471-How-Do-I-Get-My-App-Verified).
- **I4:** [Discord: Gateway intents and Message Content](https://docs.discord.com/developers/events/gateway).
- **I5:** [Discord: You Might Not Need a Privileged Intent](https://docs.discord.com/developers/gateway/you-might-not-need-a-privileged-intent).
- **I6:** [Discord: Receiving and Responding to Interactions](https://docs.discord.com/developers/interactions/receiving-and-responding).
- **I7:** [Discord: OAuth2 scopes and bot authorization](https://docs.discord.com/developers/topics/oauth2).
- **I8:** [Discord: Permissions](https://docs.discord.com/developers/topics/permissions).
- **I9:** [Discord: Message and reaction endpoints](https://docs.discord.com/developers/resources/message#create-reaction).
- **I10:** [Discord: Application Commands](https://docs.discord.com/developers/interactions/application-commands#permissions).
- **I11:** [Discord Developer Terms of Service](https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service).
- **I12:** [Discord Developer Policy](https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy).
- **I13:** [discord.py: Client `max_messages`](https://discordpy.readthedocs.io/en/stable/api.html#discord.Client).

[I1]: https://support-dev.discord.com/hc/en-us/articles/40281523410967-Changes-to-Privileged-Intent-Access-for-Discord-Apps
[I2]: https://docs.discord.com/developers/gateway/getting-started-with-privileged-intent-review
[I3]: https://support-dev.discord.com/hc/en-us/articles/23926564536471-How-Do-I-Get-My-App-Verified
[I4]: https://docs.discord.com/developers/events/gateway
[I5]: https://docs.discord.com/developers/gateway/you-might-not-need-a-privileged-intent
[I6]: https://docs.discord.com/developers/interactions/receiving-and-responding
[I7]: https://docs.discord.com/developers/topics/oauth2
[I8]: https://docs.discord.com/developers/topics/permissions
[I9]: https://docs.discord.com/developers/resources/message#create-reaction
[I10]: https://docs.discord.com/developers/interactions/application-commands#permissions
[I11]: https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service
[I12]: https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy
[I13]: https://discordpy.readthedocs.io/en/stable/api.html#discord.Client
