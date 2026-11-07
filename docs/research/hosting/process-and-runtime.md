# Process, runtime, and secrets

Checked **2026-11-04**. Scope: one always-on Discord Gateway bot on a home Ubuntu machine shared with other services. **UNVERIFIED:** Ubuntu/systemd versions, CPU architecture, available RAM, cgroup configuration, and eventual Python/Node application entry point. Nothing here has been run on the home machine.

## Facts

### Process managers

| Option | Documented behavior |
| --- | --- |
| systemd | Supervises a foreground process, controls restart behavior, and applies resource controls to its service cgroup. `Type=exec` detects failure to execute the program; it does not establish Discord readiness. [S2], [S4] |
| Docker / Compose | Docker supplies restart policies; `unless-stopped` survives daemon restarts unless the container was stopped. Docker advises against competing process managers for the same container. Compose binds secret files into containers; this is not disk encryption (inference from its delivery mechanism). [D1], [D2] |
| PM2 | Provides persistent process lists using `pm2 save` and a generated startup service. Its documentation requires updating startup configuration after changing the Node binary. [M1] |

### Supervision, isolation, and secrets

- `RestartSec` provides a fixed delay. Exponential `RestartSteps` plus `RestartMaxDelaySec` require **systemd 254+**. `Restart=on-failure` restarts nonzero exits; an intentional `systemctl stop` does not trigger it. [S2]
- `StartLimitIntervalSec`/`StartLimitBurst` also count manual starts. Reaching the limit stops automatic retries; elapsed time alone does not schedule another attempt. `systemctl reset-failed` clears the counter. [S3]
- `ProtectSystem=strict` makes most paths read-only; managed state/cache/runtime directories remain writable. `ProtectHome` hides home directories; `NoNewPrivileges` covers descendants; `PrivateTmp` isolates temporary directories. `ReadWritePaths` does not grant Unix filesystem permissions. [S1]
- `MemoryHigh` throttles/reclaims memory; `MemoryMax` can cause an in-cgroup OOM kill. `CPUQuota=50%` caps aggregate CPU time at half of one CPU's equivalent, not a reserved core. `TasksMax` counts processes **and threads**, including descendants. [S4]
- `LoadCredential` requires **systemd 247+**. Credentials appear as read-only files under `CREDENTIALS_DIRECTORY`. The proposed unit loads them at startup; replacing the source file requires restarting it. Environment variables propagate to descendants and are unsuitable for stronger secret isolation. [S1], [S5]
- Ubuntu's `adduser --system` supports a separate service account and defaults to a non-login shell; `--group` creates its corresponding group. [U1]
- `network-online.target` concerns boot ordering, not ongoing Internet availability. [S6]

### Runtime and native work

- Python virtual environments isolate packages, need no activation when invoking their interpreter directly, and should be recreated at their final path rather than relocated. [P1]
- Node recommends Active/Maintenance LTS for production. nvm relies on shell setup; fnm requires its generated environment; Volta routes commands through its configured PATH and project settings. A working interactive terminal does not establish a working service environment. [N1], [N2], [N3], [N4]
- Pillow uses native codecs; node-canvas uses Cairo; sharp's libvips work can use multiple threads per image, with additional codec threads. Cancelling a running Python executor future does not stop its work. [I1], [I2], [I3], [P2]
- `MemoryDenyWriteExecute` conflicts with JIT engines and some native-code techniques. [S1]

## Recommendations

### Prefer one direct systemd service

Use systemd for either discord.py or discord.js: one supervisor, existing journal integration, explicit limits, and no extra process-manager installation. Choose Docker/Compose if this machine already has a maintained container workflow or image packaging materially simplifies native dependencies. In that case use one container restart policy, a non-root container user, explicit resource limits, and persistent state outside the image; never expose the Docker socket to the bot. Docker's daemon privileges remain a host-security consideration. [D3]

PM2 is reasonable for an owner already operating Node applications with it, but adds little for this single bot. Use one fork-mode instance; do not enable clustering or overlapping deployments of an unsharded Gateway consumer. Use one supervising arrangement, not independent systemd and PM2 launches of the bot.

### Accounts, paths, and ownership

Create a dedicated `pokewalker` account/group with no interactive login, sudo access, Docker membership, or access to other services' credentials. Keep deployments controlled by root or a separate authorized deployer; the running bot must not update its own code or dependencies.

| Path | Proposed purpose and ownership |
| --- | --- |
| `/opt/pokewalker/releases/<sha>` | Immutable release plus dependencies; root/deployer owned, service-readable, never service-writable |
| `/opt/pokewalker/current` | Deployment-controlled link to the selected release |
| `/var/lib/pokewalker` | Persistent database/state; service owned, mode `0700` |
| `/var/cache/pokewalker` | Rebuildable render/font cache; service owned, `0700` |
| `/run/pokewalker` | Temporary runtime files; service owned, `0700`, removed on stop |
| `/etc/pokewalker` | Root-owned configuration directory, `0700`; config/token files `0600` |

Use a per-release Python `.venv` built at its final release path, with locked dependencies; do not replace Ubuntu's system Python. For Node, pin a compatible supported LTS patch and lock dependencies. A supported distro package is simplest if it meets the selected library requirements; otherwise provision a protected versioned runtime, exposed at `current/runtime/bin/node`. Build TypeScript and native dependencies during deployment, not service startup.

Use absolute executable paths and an explicit `WorkingDirectory`. Avoid `bash -lc`, sourcing `.bashrc`, or relying on nvm/fnm/Volta settings in an administrator's home. `ProtectHome=yes` intentionally prevents access there. If retaining a version manager, provision its runtime outside home directories and explicitly configure its paths; verify that service startup never downloads anything.

### Credentials and rotation

Prefer `LoadCredential` for the bot token. The future application must read `CREDENTIALS_DIRECTORY/discord_token`; it must not assume the token is automatically an environment variable. Keep `/etc/pokewalker/runtime.env` for nonsecret `KEY=value` configuration; it is not a shell script.

For older systemd or an application that only supports `DISCORD_TOKEN`, an `EnvironmentFile` containing the token is a compatibility fallback: keep it root-owned `0600`, outside Git, and never print its contents. It still places the token in the application's environment. `LoadCredential` also leaves its source file plaintext unless encrypted separately; use protected storage/backups, or evaluate `LoadCredentialEncrypted` against the installed systemd. [S5]

Discord treats the token as a highly sensitive API credential and provides **Reset Token** in the Developer Portal. [A1] On exposure, reset it promptly, securely replace the source credential, restart the service, and inspect unauthorized activity and leaked copies. Changing a local file alone does not rotate the Discord credential. Exclude tokens, environments, raw messages, and credential files from logs, crash reports, release artifacts, and ordinary backups.

### Hardened unit template

The service name and conservative ceilings below are recommendations. Prefer credential-file delivery over the environment-file alternative. Confirm the host's spare capacity and measure native-image peaks before selecting the final resource budget.

Proposed `/etc/systemd/system/pokewalker-bot.service`. **Not deployable unchanged:** the app does not exist; replace the module/build placeholder and implement credential-file loading. This example assumes systemd **247+** and working cgroup-v2 CPU/memory/pids controllers. Values are starting recommendations, not measured requirements. Directory directives create/own the writable paths; explicit `ReadWritePaths` documents the allowed exceptions. [S1], [S4]

```ini
[Unit]
Description=Pokewalker Discord bot
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=600
StartLimitBurst=5

[Service]
Type=exec
User=pokewalker
Group=pokewalker
WorkingDirectory=/opt/pokewalker/current
EnvironmentFile=/etc/pokewalker/runtime.env
LoadCredential=discord_token:/etc/pokewalker/discord_token
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=XDG_CACHE_HOME=/var/cache/pokewalker
ExecStart=/opt/pokewalker/current/.venv/bin/python -m REPLACE_WITH_BOT_MODULE
# Node alternative: replace ExecStart above; do not add a second ExecStart.
# ExecStart=/opt/pokewalker/current/runtime/bin/node /opt/pokewalker/current/dist/REPLACE_WITH_BOT_ENTRY.js
Restart=on-failure
RestartSec=10s
TimeoutStopSec=30s
KillMode=mixed
UMask=0077
LimitCORE=0
StateDirectory=pokewalker
StateDirectoryMode=0700
CacheDirectory=pokewalker
CacheDirectoryMode=0700
RuntimeDirectory=pokewalker
RuntimeDirectoryMode=0700
ProtectSystem=strict
ProtectHome=yes
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
CapabilityBoundingSet=
ReadWritePaths=/var/lib/pokewalker /var/cache/pokewalker /run/pokewalker
MemoryHigh=384M
MemoryMax=512M
MemorySwapMax=128M
OOMPolicy=stop
CPUQuota=50%
TasksMax=64
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

`MemoryMax` does not bound swap; the provisional `MemorySwapMax=128M` does. `OOMPolicy=stop` ends the service after a worker OOM so `Restart=on-failure` can restart the whole unit. [S2], [S4]

On **254+ only**, optionally add `RestartSteps=4` and `RestartMaxDelaySec=120s`; retain the fixed `RestartSec` baseline elsewhere. Keep the default normal restart mode. After fixing a start-limit failure, an operator can reset the failed state and start the unit; avoid an uncontrolled retry timer. Network disconnects should use the library's reconnect/backoff path rather than repeatedly exiting the process.

Implement one bounded shutdown path: stop admission, cancel queued renders, drain accepted writes/pending step deltas within **20 seconds**, stop/join workers, close Discord/database connections, then exit. With `KillMode=mixed`, systemd initially signals the main process; remaining children receive SIGKILL when the main exits or the stop timeout expires. [S7] For the optional owner-only restart action, acknowledge first, use this shutdown path, then exit **75**; do not add 75 to `SuccessExitStatus`, which would defeat `on-failure`. Do not give the bot sudo/Polkit or shell-based restart access. Omit `WatchdogSec` until the application implements `sd_notify` watchdog reporting. [S2]

### Rendering and verification

Start with **one render worker, eight queued jobs**, nonblocking queue admission, bounded image dimensions/output size, and a provisional **10-second job deadline**. Use a killable worker process when hard cancellation is required; an await timeout alone is insufficient. Retain workers inside the service cgroup. For sharp, also bound per-image/native thread concurrency; a task limit is not a render-queue limit. Test actual fonts/codecs under the sandbox before tightening syscall restrictions or considering `MemoryDenyWriteExecute`.

Check the installed systemd version/controllers and validate the adapted unit before enabling it. Measure aggregate bot/worker memory, CPU throttling, queue depth, and Gateway responsiveness alongside other home services before adjusting caps. Test reboot startup, token rotation, graceful stop, child cleanup, and start-limit recovery. **UNVERIFIED:** whether these provisional limits fit the machine or chosen image stack; this document is not a deployment or host validation result.

## Sources

All sources below checked **2026-11-04**.

- [S1] systemd execution, filesystem isolation, credentials, and JIT caveats.
- [S2] systemd service lifecycle, restart options, and watchdog requirements.
- [S3] systemd unit start limits.
- [S4] systemd cgroup resource controls.
- [S5] systemd credential design and delivery.
- [S6] systemd network synchronization targets.
- [S7] systemd process termination behavior.
- [U1] Ubuntu `adduser` manual (24.04 reference; host release unknown).
- [P1] Python virtual environments.
- [P2] Python executor cancellation.
- [N1] Node release/support policy.
- [N2] nvm shell initialization.
- [N3] fnm environment setup.
- [N4] Volta toolchain/project selection.
- [D1] Docker restart policies.
- [D2] Docker Compose secrets.
- [D3] Docker daemon/container security.
- [M1] PM2 startup and Node upgrades.
- [A1] Discord token handling/reset.
- [I1] Pillow native dependencies.
- [I2] node-canvas native implementation.
- [I3] sharp concurrency and thread behavior.

[S1]: https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
[S2]: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
[S3]: https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html
[S4]: https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html
[S5]: https://systemd.io/CREDENTIALS/
[S6]: https://systemd.io/NETWORK_ONLINE/
[S7]: https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html
[U1]: https://manpages.ubuntu.com/manpages/noble/man8/adduser.8.html
[P1]: https://docs.python.org/3/library/venv.html
[P2]: https://docs.python.org/3/library/concurrent.futures.html
[N1]: https://nodejs.org/en/about/previous-releases
[N2]: https://github.com/nvm-sh/nvm
[N3]: https://github.com/Schniz/fnm
[N4]: https://docs.volta.sh/guide/understanding
[D1]: https://docs.docker.com/engine/containers/start-containers-automatically/
[D2]: https://docs.docker.com/compose/how-tos/use-secrets/
[D3]: https://docs.docker.com/engine/security/
[M1]: https://pm2.keymetrics.io/docs/usage/startup/
[A1]: https://docs.discord.com/developers/quick-start/getting-started
[I1]: https://pillow.readthedocs.io/en/stable/installation/building-from-source.html
[I2]: https://github.com/Automattic/node-canvas
[I3]: https://sharp.pixelplumbing.com/api-utility/
