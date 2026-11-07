# Deployments and security on a shared home Ubuntu server

Checked **2026-11-04**. Proposed operations only; primary sources appear below.

## Facts

### Deployment and shutdown boundaries

- GitHub warns that self-hosted runners can remain compromised by untrusted workflow code; public-repository pull requests are a particular risk. Private repositories and environment approvals do not provide machine isolation. [D1]
- `npm ci` requires a lockfile, fails on a package/lock mismatch, and does not update the lock. Python deployments can pin transitive dependencies and verify package hashes. Python virtual environments contain absolute interpreter paths and generally cannot be moved safely. [D2], [D3], [D4]
- `systemd` normally stops services with `SIGTERM`, then escalates to `SIGKILL` after `TimeoutStopSec`. `Restart=on-failure` restarts failures, **not ordinary successful exit**; an explicit systemd stop also suppresses automatic restart. With `KillMode=mixed`, initial termination targets the main process; remaining children are killed when it exits or the stop timeout expires. [D5], [D6]
- Python's `asyncio.run()`/Runner documents special **SIGINT** handling, not automatic application-specific SIGTERM cleanup. Unix event loops provide `add_signal_handler`. In Node.js, adding a SIGTERM/SIGINT listener removes its default exit behavior. Library connection closure—`await client.close()` in discord.py or `await client.destroy()` in discord.js—does not implement the application's database/worker drain. [D7], [D22], [D8], [D9], [D10]
- Discord documents **200 application-command creates per day per guild**. Guild commands update immediately; global commands have version checking/read-repair. Bulk overwrite replaces the application's complete command list in the selected scope, including slash, user, and message commands. [D11]
- SQLite's backup API produces a database snapshot and supports live databases. [D12]

### Network and host security boundaries

- Gateway clients open secure WebSocket connections to Discord; interactions can arrive through that Gateway. Discord supports attachment uploads, including referencing uploaded images in embeds. Neither mechanism requires this bot to publish an inbound HTTP/image server. [D13], [D23], [D14]
- **Architectural inference:** normal Gateway use does not publish a home server's IP as part of the bot's ordinary message content. This is not anonymity: Discord documents IP-address collection, and contacted servers can observe the connection's source address. Fetching an attacker-controlled URL reveals the egress address to that destination. [D13], [D15]
- OWASP documents SSRF risks from server-side URL fetching, including access to internal addresses and redirect/DNS bypasses. It recommends allowed destinations and validation, with redirects disabled where appropriate. [D16]
- Ubuntu supports automatic security updates; automatic reboot is a separate setting, defaulting to false. Enabling it permits reboot without confirmation when required. Since Ubuntu 24.04, `needrestart` also restarts affected services automatically by default, independently of that reboot setting. Ubuntu LTS maintenance depends on release age and package coverage. [D17], [D18]
- OpenSSH supports public-key authentication and controls for root/password login. Ubuntu recommends validating SSH configuration before restarting it. Docker-published ports can bypass UFW's normal filtering path. [D19], [D20], [D21]

## Recommendations

### 1. Use an operator-run deployment script

Apply this flow when hosting implementation resumes; see the [repository status](README.md). Keep future deployment assets in `deploy/`, review the actual host first, and coordinate interruptions around its existing services.

| Approach | Assessment for this machine |
| --- | --- |
| `git pull`, install, restart in the running directory | Acceptable for disposable development; live files/dependencies can change before the deployment succeeds, and rollback is awkward. |
| Small operator-run script deploying a reviewed commit | **Recommended.** Makes preparation, stop, migration, activation, verification, and rollback repeatable without adding a permanent remote execution agent. |
| GitHub Actions self-hosted runner on this shared home host | Avoid. A workflow compromise would share a machine and network with unrelated services. Use GitHub-hosted CI for checks/builds; deploy reviewed output separately. |

Keep untrusted PR builds in isolated CI. Run only reviewed releases and reviewed dependency changes on this home host. Locks improve reproducibility, not trust. Build as an unprivileged deployment identity without the bot token, never through root-level `pip`/`npm` installation.

Use separate ownership and writable locations:

| Path | Purpose / ownership |
| --- | --- |
| `/opt/pokewalker/releases/<sha>/` | Complete release, dependencies/build output; root or deployment account owns it; bot can only read/execute. |
| `/opt/pokewalker/current` | Operator-controlled symlink to the active release. |
| `/var/lib/pokewalker/` | Durable database/state; writable by the dedicated bot identity. |
| `/var/cache/pokewalker/` | Bounded, disposable image cache; writable by the bot. |
| `/etc/pokewalker/` | Root-managed configuration/credentials; only necessary runtime access. |

The bot must not own its executable code, dependency environment, deployment script, or service unit, and must not have sudo rights. Keep credentials outside Git, build output, command-line arguments, and logs.

**Deployment sequence:**

1. Take an exclusive deployment lock. Fetch and resolve a reviewed full commit SHA; record the previous release, desired command-manifest hash, runtime version, dependency lock, and required schema version.
2. Prepare the inactive release at its **final release path**, with a fresh Python virtual environment and locked/hash-checked dependencies, or `npm ci` and the project's build. Do not relocate an already-created venv. Validate configuration and run checks without logging another production Gateway client in.
3. Stop the service and wait for its bounded shutdown and all workers. Keep **one production Gateway instance**; do not start the candidate alongside the old process.
4. Before migrations, create and verify a SQLite backup-API snapshot on encrypted storage; retain an encrypted recovery copy and schema/release metadata. Run the reviewed one-shot migration while the bot remains stopped.
5. Treat published releases as immutable. Atomically replace `current`, start the service, and verify Gateway readiness and database health. Preserve the previous release and deployment result. Sync commands only if the intended manifest changed.

**Rollback:** stop first, check schema compatibility, then select the previous release and start it. If commands changed, deliberately sync the manifest compatible with that release. Prefer backward-compatible migrations. A symlink switch cannot undo a schema change. Restore a backup only through an explicit recovery decision: it discards all later writes. Do not automatically restore a database after every failed startup, and do not run old code against an incompatible migrated schema.

### 2. Implement and test bounded shutdown

Handle SIGTERM and SIGINT explicitly in the application entry point; do not assume a library's `run()` helper flushes state. Make repeated signals enter one idempotent shutdown path:

1. Stop admitting new counting/encounter/image work. Acknowledge arriving interactions promptly with maintenance information when possible.
2. Drain accepted operations and pending step deltas into transactions. Finish acknowledged interactions within their token deadlines or persist resumable state for a fresh `/walker` invocation.
3. Close the Discord connection and database, and join/terminate remaining image workers. Exit only after cleanup; keep the entire drain **within 20 seconds**, below the coordinated unit's **30-second `TimeoutStopSec`**.

Verify actual SIGTERM behavior with queued writes and a running image job. Do not leave fire-and-forget tasks or children behind. `KillMode=mixed` requires the main process to manage and await children; its exit can trigger their termination. Ordinary intentional shutdown exits `0`. The optional owner-authorized restart policy deliberately exits `75` **after the same drain**, allowing `Restart=on-failure` to restart it; this is a distinct operational action, not ordinary shutdown. The bot does not invoke sudo or shell deployment commands.

### 3. Treat command registration as a deployment operation

Keep a versioned command manifest and hash per application/scope. Test changed commands in a development guild, then register the production manifest deliberately. Do not synchronize on every reconnect. Validate application ID, guild/global target, and the entire command set before bulk overwrite, including existing context-menu commands. Do not describe global propagation as a guaranteed one-hour wait. Track creates separately from edits; the documented daily allowance concerns creates. [D11]

### 4. Preserve the shared host and home-network boundary

- Run a currently supported Ubuntu LTS and monitor security-update failures and reboot requirements. Keep security updates enabled, coordinating both service restarts and machine reboots with the other services; arrange timely maintenance for any critical-service exclusions. OS maintenance does not update a release's pinned application dependencies—schedule reviewed dependency refreshes too.
- Prefer SSH over the LAN or a private administration VPN. Test key login and console/recovery access before restricting authentication; then disable direct root login and password-based access as appropriate, reviewing keyboard-interactive/PAM/MFA settings too. Validate syntax, retain the existing session, and test a second login before disconnecting.
- Do not forward an Internet port for this Gateway bot. Inventory existing firewall rules/services before changes; preserve their access. A VPN is **not required for Gateway operation** and does not remove application or LAN-security risks. If Docker is introduced, do not assume UFW protects published container ports. [D21]
- Prefer packaged assets or fixed trusted image hosts. Reject arbitrary user URLs; if remote fetching is necessary, allowlist HTTPS hosts/ports, validate resolved IPv4/IPv6 addresses, reject private/loopback/link-local destinations, and disable redirects or validate every hop and actual connection destination. Bound bytes, redirects, time, decoded dimensions, concurrency, and cache disk use. Upload finished files to Discord instead of serving an image directory publicly. [D16], [D14]
- A shared home host combines bot workload, unrelated services, household connectivity/power, and LAN exposure. Restrict the bot's filesystem and resource access. Move to a separately administered VPS when isolation or availability requirements justify it; neither location guarantees anonymity or security.

## UNVERIFIED / acceptance checks

These operations and protections are untested on the user's machine. The chosen dependency locks, worker model, migration compatibility, and actual home-network topology remain **UNVERIFIED**. Test the deploy/rollback sequence on disposable data, then verify backup restoration and bounded SIGTERM before production deployment.

## Sources

All checked **2026-11-04**.

- [D1] — GitHub self-hosted runner security.
- [D2] — npm ci.
- [D3] — pip repeatable installs.
- [D4] — Python virtual environments.
- [D5] — systemd.service.
- [D6] — systemd.kill.
- [D7] — Python asyncio runners.
- [D8] — Node process signals.
- [D9] — discord.py Client.
- [D10] — discord.js Client.
- [D11] — Discord application commands.
- [D12] — SQLite backup API.
- [D13] — Discord Gateway.
- [D14] — Discord file uploads.
- [D15] — Discord privacy policy.
- [D16] — OWASP SSRF prevention.
- [D17] — Ubuntu automatic updates/restarts.
- [D18] — Ubuntu release/support coverage.
- [D19] — OpenSSH configuration.
- [D20] — Ubuntu OpenSSH guidance.
- [D21] — Docker/UFW interaction.
- [D22] — Python Unix signal handling.
- [D23] — Discord interaction delivery.

[D1]: https://docs.github.com/en/actions/reference/security/secure-use#hardening-for-self-hosted-runners
[D2]: https://docs.npmjs.com/cli/v11/commands/npm-ci/
[D3]: https://pip.pypa.io/en/stable/topics/repeatable-installs/
[D4]: https://docs.python.org/3/library/venv.html
[D5]: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
[D6]: https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html
[D7]: https://docs.python.org/3/library/asyncio-runner.html
[D8]: https://nodejs.org/api/process.html#signal-events
[D9]: https://discordpy.readthedocs.io/en/stable/api.html#discord.Client
[D10]: https://discord.js.org/docs/packages/discord.js/main/Client:Class
[D11]: https://docs.discord.com/developers/interactions/application-commands
[D12]: https://sqlite.org/backup.html
[D13]: https://docs.discord.com/developers/events/gateway
[D14]: https://docs.discord.com/developers/reference#uploading-files
[D15]: https://discord.com/privacy
[D16]: https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
[D17]: https://ubuntu.com/server/docs/how-to/software/automatic-updates/
[D18]: https://ubuntu.com/project/docs/release-team/ubuntu-releases/
[D19]: https://man.openbsd.org/sshd_config
[D20]: https://ubuntu.com/server/docs/how-to/security/openssh-server/
[D21]: https://docs.docker.com/engine/network/packet-filtering-firewalls/#docker-and-ufw
[D22]: https://docs.python.org/3/library/asyncio-eventloop.html#unix-signals
[D23]: https://docs.discord.com/developers/interactions/receiving-and-responding
