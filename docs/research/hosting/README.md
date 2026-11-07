# Home Ubuntu hosting research

Checked **2026-11-04**. Scope: one hobby Discord bot sharing an always-on home machine with other services. These are deployment recommendations, not evidence that the host is configured or tested.

## Facts

- Discord Gateway connections are initiated by the app over secure WebSocket. Receiving interactions through that connection needs no public HTTP interaction endpoint; **no inbound bot port is needed for this design**. This is an architectural conclusion from the documented transports. [F1], [F2]
- systemd can supervise a service and limit its cgroup resources. `CPUQuota=50%` means half of one CPU's time, not half of the machine's total capacity. [F3], [F4]
- SQLite supports online snapshots while the application runs. In WAL mode, `synchronous=FULL` gives stronger power-loss durability than `NORMAL`; neither preserves increments still buffered only in application memory. [F5], [F6]
- External missing-heartbeat monitoring can detect loss of the home machine or its Internet connection. A notifier running only on that machine cannot send during that outage. [F7]
- Repository status: the earlier Twitch-hosting proposal was reverted and hosting implementation deferred until the end of the project. This research does not reinstate that proposal. [R1]

## Recommendations

Use **one direct systemd service**, a dedicated non-login user, and a separate runtime/dependency set for this bot. Both Python/discord.py and Node/discord.js fit. Prefer SQLite on local persistent disk with one transaction-owning writer; choose PostgreSQL when measured concurrency or existing operational expertise justifies it.

Keep releases under `/opt/pokewalker/releases/<sha>` and switch `/opt/pokewalker/current` deliberately. The bot may write only its state, cache, and temporary directories. Use systemd credentials for secrets where supported; keep configuration outside Git.

Provisional limits: **384 MiB memory pressure threshold, 512 MiB maximum, half a CPU, 64 tasks**, one image worker and eight queued renders. Measure these against the host's spare capacity. Use bounded caches, hourly online database snapshots with encrypted off-machine copies, journald, and an external heartbeat. Deploy with an operator-run script and retain the previous release.

### Bring-up checklist — future implementation

Use this checklist when hosting implementation resumes. Inspect the actual machine and coordinate changes around its existing services before applying these recommendations.

1. Inventory Ubuntu/systemd versions, spare RAM/CPU/disk, existing services/firewall/logging, time synchronization, and automatic reboot/unlock behavior.
2. Create the service account and protected directories. Install the chosen pinned runtime and locked dependencies; keep code and secrets unwritable by the bot.
3. Implement bounded rendering, transaction ownership, a <=20-second graceful shutdown, and UTC-based persisted effect deadlines.
4. Adapt and verify the [systemd unit](process-and-runtime.md); audit existing firewall rules without replacing them. Enable the service at boot after a test start.
5. Configure the [backup/restore plan](reliability-and-data.md), cache limits, and [monitoring/admin controls](monitoring-and-admin.md). Complete an isolated restore before relying on backups.
6. Test disconnect/reconnect, reboot, SIGTERM, a failed render, a crash, failed backup delivery, and unauthorized admin access. Rehearse [deployment and rollback](deploy-and-security.md).

### Open decisions / UNVERIFIED

Actual host versions, capacity, sandbox compatibility, network rules, encryption/unattended boot, and successful recovery are **UNVERIFIED**. Decide Python versus Node, SQLite versus PostgreSQL, acceptable buffered-step loss, backup destination/retention, resource/cache budgets, and whether a UPS is worthwhile. The stack and hosting decisions still need the repository's research review and planning/ADR process.

| File | Detail |
| --- | --- |
| [process-and-runtime.md](process-and-runtime.md) | Supervisor comparison, unit template, isolation, secrets |
| [reliability-and-data.md](reliability-and-data.md) | Networking, outages, clocks, database, backups, caches |
| [monitoring-and-admin.md](monitoring-and-admin.md) | Logs, heartbeat/crash alerts, metrics, owner commands |
| [deploy-and-security.md](deploy-and-security.md) | Releases, shutdown, rollback, command sync, home security |

## Sources

All checked **2026-11-04**.

[F1]: https://docs.discord.com/developers/events/gateway
[F2]: https://docs.discord.com/developers/interactions/receiving-and-responding
[F3]: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
[F4]: https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html
[F5]: https://sqlite.org/backup.html
[F6]: https://sqlite.org/pragma.html#pragma_synchronous
[F7]: https://healthchecks.io/docs/monitoring_cron_jobs/
[R1]: https://github.com/Farkoal2128/Pokewalker-Discord-Bot/commit/39d55cc7515cbb3c8aee0367989617b1f692ad44
