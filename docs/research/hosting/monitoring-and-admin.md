# Monitoring and owner administration

Checked **2026-11-04**. Research for one home-hosted bot; no monitors, webhooks, or live admin commands were installed. Source dates apply to every fact below.

## Facts

- **journald** accepts service stdout/stderr and attaches service/process metadata. It supports persistent or volatile storage, automatic size-based rotation, retention controls, and per-service log rate limiting. `SystemMaxUse` in the default journal configuration affects the shared journal, not just this bot. [J1], [J2], [J3]
- stdout/stderr are streams converted into journal records. A JSON log line is therefore useful structured application text, but is not automatically a set of native indexed journal fields. `journalctl -o json` exports the enclosing journal record. [J1], [J4]
- Membership in `systemd-journal` permits reading all journal files; it is broader than access to one bot's errors. [J4]
- Healthchecks.io monitors expected outbound pings and alerts when a period plus grace interval elapses. Its ping API supports success/start/failure signals; ping URLs are secrets, and POST bodies can be retained. It offers Discord integration. This monitoring can detect a missing home host without inbound access to that host. [H1], [H2], [H3]
- Discord incoming webhooks use their own token to post into a channel; execution does not depend on the bot's Gateway session. Webhook requests support `allowed_mentions` and `wait=true` for delivery confirmation. [D1]
- `OnFailure=` activates another unit when a service enters the failed state. `Restart=on-failure` restarts unsuccessful exits, subject to start limits; clean exit 0 does not request a restart. `RestartMode=direct` skips failure/success hooks during automatic restart. [S1], [S2]
- Discord's command defaults can be overridden and administrators can access commands. An application-level owner check is therefore distinct from command visibility. discord.py supplies `app_commands.check`; the received interaction identifies its user. [D2], [P1]
- discord.py `Client.latency` measures heartbeat/acknowledgement round-trip time in seconds. discord.js v14 exposes readiness and WebSocket status/ping; use the pinned version's API when wiring metrics. Neither is an end-to-end database or rendering health check. [P2], [N1], [N2]

## Recommendations

### Logs: use journald and small, structured events

Send one-line JSON to stdout/stderr with UTC time, severity, event name, release SHA, run ID, duration, and a sanitized error code. Keep normal operation at INFO. Aggregate message/step counters periodically instead of logging each message. Redact secrets before logging, including URLs containing webhook/heartbeat tokens, authorization headers, exception payloads, and tracing locals. Do not record message text.

Use the service's `StandardOutput=journal` / `StandardError=journal`. Start with per-service `LogRateLimitIntervalSec=30s` and `LogRateLimitBurst=500`, plus application sampling of repeated errors. Rate limiting can discard diagnostics; count suppressed events. These are tuning proposals, not workload measurements.

Inspect the host's existing journal retention before changing it. Do not impose a bot-sized global cap on other services. If independent retention is needed, use an explicitly configured `LogNamespace=pokewalker` with its own journal configuration; a provisional budget is **128 MiB / 7 days**. Verify support and query it with `journalctl --namespace=pokewalker`. Prefer ordinary shared journald initially. Use rotating application files only if an existing collector requires them; configure bounded size/retention and correct reopen behavior instead of writing an unlimited file.

Local operator inspection, for the default namespace:

```sh
journalctl -u pokewalker-bot.service --since '1 hour ago' -n 100 --no-pager
systemctl show pokewalker-bot.service -p ActiveState -p NRestarts -p MemoryCurrent -p TasksCurrent
```

Do not expose these command runners through Discord. A JSON `level` field does not by itself set journald's native priority; use an appropriate logging adapter if filtering with `journalctl -p`.

### Heartbeats, crash alerts, and useful metrics

Use an **external** dead-man monitor with a ping every **60 seconds** and **120 seconds grace** (approximately three minutes without success before alert). Send success only when the event loop is responsive, Gateway readiness is current, and the database writer is healthy. An unrelated timer that blindly pings could report success while the bot is stuck. Check connectivity independently of message traffic; a quiet server is healthy. Do not restart merely because Discord or the home Internet is temporarily unavailable.

Give backups their own check, sending success only after a verified snapshot and required off-machine upload. Use finite HTTP timeouts, bounded retries, no diagnostic POST body, and protected ping URLs. A monitoring failure must not block gameplay.

For immediate crashes, use a narrowly scoped `OnFailure` notifier or a local service-health checker **outside the bot process**. It posts a fixed, sanitized summary to an owner-private Discord channel through a dedicated webhook. Store that webhook separately from the bot token, disable incidental mentions, honor HTTP retry delays, and coalesce repeated failures. Keep default restart mode; distinguish intentional owner restart code 75 from a crash. A brief crash/recovery can also be reported on next startup.

A local notifier cannot deliver during a power/network outage; the external missing-heartbeat alert covers that case. Discord can itself be unavailable, so add email or another independent notification channel. Self-hosting the monitor on the same home machine does not detect loss of that machine reliably.

| Observe | Why |
| --- | --- |
| Gateway ready state, heartbeat latency, reconnect count | Separate network trouble from application trouble |
| Event-loop lag; received/accepted/rejected message rates | Detect blocking rendering, overload, or abuse |
| Writer queue depth, oldest uncommitted award, transaction latency/errors | Reveal persistence lag and the crash-loss window |
| Render queue depth, runtime/failure count, native memory peak | Tune image concurrency and prevent runaway work |
| Cgroup memory/tasks, CPU usage, OOM/restart count | Include render children/native allocations in resource use |
| Free disk/inodes, database/WAL/cache bytes, backup age and last restore drill | Detect storage exhaustion and failed protection |

Start with sampled in-process counters and an owner status screen. Add a localhost/Unix-socket metrics exporter only if the host already has monitoring; no public dashboard or inbound port is needed. Avoid per-user metric labels.

### Owner-only Discord commands

Use an immutable **owner-ID allowlist from protected configuration**. Check the invoking ID on every slash command and every component callback; usernames, server ownership, and administrator roles are not substitutes. Keep Discord snowflakes as strings in JavaScript. Restrict discovery to the test/admin guild, acknowledge privately, limit output size, and rate-limit requests.

| Command | Allowed behavior |
| --- | --- |
| `/admin status` | Return release, uptime, Gateway/writer/render health and bounded aggregate metrics |
| `/admin errors` | Return at most ten sanitized summaries from a bounded application-owned error buffer; buffer loss on restart is acceptable |
| `/admin restart` | Confirm once with an expiring owner-bound action, acknowledge ephemerally, quiesce/drain/flush, then deliberately exit **75** |

The restart uses `Restart=on-failure`; the bot needs no sudo, shell, or systemd-management permission. Reserve code 75 for this path, classify it as intentional in alerts, and enforce a restart cooldown. Do not add 75 to `SuccessExitStatus` under this design. Start limits still apply. See [shutdown and deployment](deploy-and-security.md).

These commands belong to Pokéwalker itself. Keep any future controller in another service outside this scope; it would need its own narrow authorization and integration design.

Never expose arbitrary shell/eval, SQL, file paths, environment dumps, token readback, package installation, deployment revisions, service names, or unrestricted URL fetching through Discord. Do not give the bot `adm`/`systemd-journal` membership for error-tail convenience. Retain SSH over the LAN/VPN for a bot that cannot connect; Discord administration cannot repair a stopped or disconnected bot.

## UNVERIFIED / implementation checks

The host's journal persistence, namespace support, current monitoring, available resources, and alert delivery are **UNVERIFIED**. During bring-up, test a synthetic redacted error, deliberate process failure, start-limit exhaustion, missed heartbeat, failed backup upload, unauthorized admin invocation, and duplicate restart confirmation. Verify that credentials/message content never appear in any output. No such live tests were performed for this research.

## Sources

All checked **2026-11-04**.

- [J1] systemd-journald: stream logging and namespaces.
- [J2] journald.conf: storage, retention, rotation, rate limits.
- [J3] systemd.exec: output routing, per-unit log limits, namespaces.
- [J4] journalctl: access control, filters, and JSON output.
- [H1] Healthchecks.io monitoring concepts.
- [H2] Healthchecks.io ping API and secret URLs.
- [H3] Healthchecks.io supported integrations.
- [D1] Discord webhook resource.
- [D2] Discord application-command permissions.
- [S1] systemd.unit: failure dependencies.
- [S2] systemd.service: restart and exit-status behavior.
- [P1] discord.py application-command checks.
- [P2] discord.py client latency/readiness.
- [N1] discord.js v14 client reference.
- [N2] discord.js v14 WebSocket manager reference.

[J1]: https://manpages.ubuntu.com/manpages/noble/man8/systemd-journald.service.8.html
[J2]: https://www.freedesktop.org/software/systemd/man/latest/journald.conf.html
[J3]: https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
[J4]: https://www.freedesktop.org/software/systemd/man/latest/journalctl.html
[H1]: https://healthchecks.io/docs/
[H2]: https://healthchecks.io/docs/http_api/
[H3]: https://healthchecks.io/
[D1]: https://docs.discord.com/developers/resources/webhook
[D2]: https://docs.discord.com/developers/interactions/application-commands
[S1]: https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html
[S2]: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
[P1]: https://discordpy.readthedocs.io/en/stable/interactions/api.html#discord.app_commands.check
[P2]: https://discordpy.readthedocs.io/en/stable/api.html#discord.Client.latency
[N1]: https://discord.js.org/docs/packages/discord.js/14.27.0/Client%3AClass
[N2]: https://discord.js.org/docs/packages/discord.js/14.27.0/WebSocketManager%3AClass
