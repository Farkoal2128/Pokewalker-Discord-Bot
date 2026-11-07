# Discord interactions: private walker screens

Checked: **2026-11-04**. Scope: `/walker`, ephemeral screens, component handling, and encounter resolution. Source dates appear below; recommendations are implementation choices, not Discord guarantees.

## Facts

### Ephemeral responses and interaction lifecycle

- Initial interaction responses and follow-ups support `EPHEMERAL`; both can be edited through their interaction-webhook endpoints while the token is valid. Component interactions and modal submissions can also produce responses. An existing message's ephemeral status cannot change. [D1]
- A normal channel message cannot be made ephemeral: its creation flags exclude `EPHEMERAL`. Passive message receipt therefore cannot itself initiate a private ephemeral notification. A reaction on the triggering channel message is visible to people who can see that message. [D2]
- An interaction must receive its initial acknowledgement within **3 seconds**, or its token becomes invalid. Interaction tokens remain usable for **15 minutes**. A delivered button press is a new component interaction with its own ID/token and acknowledgement deadline; it does not renew the old slash-command token. [D1]
- `UPDATE_MESSAGE` (type 7) edits the component's source message. `DEFERRED_UPDATE_MESSAGE` (type 6) acknowledges a component and allows editing later without a loading response. `DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE` (type 5) creates a loading response; choose ephemerality when deferring. [D1]
- Each interaction permits one initial acknowledgement. After responding or deferring, use response edits or follow-ups, not a second initial response. [P1]
- Ephemeral messages are visible only to the interacting user. Discord's FAQ says they disappear after dismissal, sufficient time, or a **Discord client** restart; it specifies no numeric display lifetime. **UNVERIFIED:** an exact client retention time. The 15-minute token window is not a documented auto-deletion deadline. [D3]

### Components and library persistence

| Subject | Verified behavior |
| --- | --- |
| Component identifiers | Interactive buttons return the developer's `custom_id`. It is 1–100 characters and must be unique among components in the same message. An action row holds up to five buttons. [D4] |
| Classic versus V2 | Legacy components remain supported per message, and Discord states they will not be deprecated. Discord nevertheless recommends newer components for new projects. [D5] |
| V2 tradeoff | `IS_COMPONENTS_V2` replaces normal `content`/`embeds` with content components and disables polls/stickers. Once set on a message, the flag cannot be removed. It is not necessary for a classic action row with Catch/Run buttons. [D4][D5] |
| discord.py views | A persistent `View` requires `timeout=None` and explicit component `custom_id` values. `Client.add_view()` registers it for listening beyond the process lifecycle; `add_dynamic_items()` registers `DynamicItem` classes. Registration must be restored by application startup code. [P1][P2] |
| Ephemeral view caveat | `View()` defaults to a 180-second inactivity timeout. Sending an ephemeral view with `timeout=None` substitutes 15 minutes; it does not establish an indefinitely persistent ephemeral view. View timeout and Discord token lifetime are separate. [P1] |
| discord.js handlers | The official guide recommends a global `interactionCreate` listener for permanent component features. Collectors and `awaitMessageComponent()` are scoped listeners with configured timeouts; they are not durable application state. [J1] |
| Editing in discord.py | `interaction.edit_original_response()` supports editing the original ephemeral response; `interaction.response.edit_message()` updates the source of a component interaction. Use these interaction methods rather than ordinary channel-message edits. [P1] |

**Restart limitation — UNVERIFIED:** Discord does not document a guarantee that an ephemeral screen remains visible and usable across bot restarts. Restoring handlers is necessary for delivered clicks, but does not preserve the user's client UI or revive expired tokens. Do not promise “persistent ephemeral messages.” [D1][D3][P2][J1]

## Recommendations

### Screen and recovery design

Use **classic buttons initially**: the required screen is text or an embed plus Catch/Run. V2 is reasonable if later screens require richer layouts; it adds no durability or transaction safety. Keep screen rendering separate so either format can be selected without changing encounter logic.

Have `/walker` immediately defer ephemerally, load the oldest pending encounter, and edit its original response. Merely revealing an encounter must not consume it. Edits should replace that same screen. Use the explicit original-response edit after deferring; Discord marks the first-follow-up compatibility workaround as deprecated. [D1]

Use a global component router or startup-registered dispatch handlers. Store encounters and screen/session identity in the database, not inside a collector or view object. If an old screen remains visible and Discord delivers its click after a bot restart, a restored handler can process that new interaction using saved state. Always support reopening `/walker`; this reconstructs the current screen after dismissal, expiry, disconnection, or restart.

Give screens an application expiry and revision. A stale screen should explain that the user can reopen `/walker`, without consuming an encounter. Expiring the screen must not expire the queue. Avoid storing interaction tokens durably; they are short-lived credentials, not encounter identifiers.

Example handler shape in discord.py; service/render functions are placeholders. The button callback defers the **update**, rather than creating another screen. [P1]

```python
# /walker
await interaction.response.defer(ephemeral=True)
await interaction.edit_original_response(**await render_pending_from_db(...))

# Catch/Run callback
await interaction.response.defer()  # Component acknowledgement (type 6).
state = await resolve_once_in_transaction(...)
await interaction.edit_original_response(**render(state))
```

### Identifiers and authorization

Use an opaque, versioned identifier such as `walker:v1:<session_id>:<revision>:catch`. Keep it within Discord's length limit. Resolve the session in the database and verify `(guild_id, user_id)`, encounter identity, expiry, revision, and allowed action from the received interaction. Do not trust a user ID embedded in `custom_id`. Do not encode secret outcomes or use the original message ID as the sole authorization check.

### Double-click and race-safe resolution

1. **Acknowledge first.** Avoid waiting for a database lock or random-outcome calculation before the response deadline. Reject malformed/unauthorized interactions without changing state.
2. **Serialize the state transition in a database transaction.** Lock the encounter/player row, or use a conditional update against the expected state/revision. A process mutex alone cannot cover restarts or multiple workers.
3. **Check and apply once.** Require `status=pending` and the expected revision. Generate and persist the outcome once; insert the catch, update inventory, and resolve the encounter in the same transaction. A unique catch record per encounter and a unique processed interaction ID provide additional constraints.
4. **Handle losers deterministically.** Two clicks normally have different interaction IDs, so deduplicating IDs alone is insufficient. The second Catch/Run must observe the completed transition and return saved current state, without rerolling or awarding again.
5. **Commit before updating Discord.** If rendering/editing fails, keep the committed outcome; `/walker` recovers it. Never retry an award because an HTTP edit failed.
6. **Keep presentation ordered.** Serialize edits per screen, then read current state before rendering. Otherwise a delayed edit can overwrite a newer screen even when the database is correct. Disable terminal buttons for clarity; database conditions enforce correctness.

Implementation verification should cover simultaneous Catch/Catch, Catch/Run, two open `/walker` screens, a repeated interaction delivery, and a restart after commit but before message edit. See [performance/storage](discord-rate-limits-performance.md) for transaction and writer choices.

## Sources

- **D1.** [Discord: Receiving and Responding to Interactions](https://docs.discord.com/developers/interactions/receiving-and-responding) — checked **2026-11-04**.
- **D2.** [Discord: Message Resource, Create Message and reactions](https://docs.discord.com/developers/resources/message) — checked **2026-11-04**.
- **D3.** [Discord: Ephemeral Messages FAQ](https://support-apps.discord.com/hc/en-us/articles/26501839512855-Ephemeral-Messages-FAQ) — checked **2026-11-04**. Use the API reference for supported interaction types; this FAQ simplifies them to slash commands.
- **D4.** [Discord: Component Reference](https://docs.discord.com/developers/components/reference) — checked **2026-11-04**.
- **D5.** [Discord: Components Overview](https://docs.discord.com/developers/components/overview) — checked **2026-11-04**.
- **P1.** [discord.py: Interaction/UI API](https://discordpy.readthedocs.io/en/stable/interactions/api.html) — checked **2026-11-04**.
- **P2.** [discord.py: Client.add_view and add_dynamic_items](https://discordpy.readthedocs.io/en/stable/api.html#discord.Client.add_view) — checked **2026-11-04**.
- **J1.** [discord.js: Responding to component interactions](https://discordjs.guide/legacy/interactive-components/interactions) — checked **2026-11-04**.

[D1]: https://docs.discord.com/developers/interactions/receiving-and-responding
[D2]: https://docs.discord.com/developers/resources/message
[D3]: https://support-apps.discord.com/hc/en-us/articles/26501839512855-Ephemeral-Messages-FAQ
[D4]: https://docs.discord.com/developers/components/reference
[D5]: https://docs.discord.com/developers/components/overview
[P1]: https://discordpy.readthedocs.io/en/stable/interactions/api.html
[P2]: https://discordpy.readthedocs.io/en/stable/api.html#discord.Client.add_view
[J1]: https://discordjs.guide/legacy/interactive-components/interactions
