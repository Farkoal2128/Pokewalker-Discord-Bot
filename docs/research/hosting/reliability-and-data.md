# Home Ubuntu hosting: reliability and data

**All sources checked 2026-11-04.** Research for a home machine shared with other services; no host changes.

## 3. Networking, outages, and time

### Facts

- Discord delivers events through an outbound secure WebSocket; REST uses HTTPS, and its documented image CDN is `cdn.discordapp.com`. Interactions can arrive through that Gateway connection instead of an HTTP interaction endpoint. [N1], [N2], [N3]
- Successful Gateway Resume replays missed events. A session can become unresumable, requiring a new Identify; complete recovery of messages sent during an outage is therefore **not guaranteed**. Python's `discord.py` defaults to `reconnect=True` for recoverable failures, excluding cases such as invalid credentials. `discord.js` documents reconnect/re-identify and successful-resume events. [N1], [N4], [N5]
- `network-online.target` delays startup until the network manager's definition of “online”; it does not continuously monitor Internet availability. [N6]
- Conventional DNS uses UDP/TCP 53. Ubuntu supports `systemd-timesyncd` or `chrony`; NTP uses UDP 123, while an NTS configuration also needs TCP 4460 for key exchange. Chrony replaced timesyncd as Ubuntu's default starting with 25.10, so inspect the installed configuration. [N7], [N8], [N9]
- Python's monotonic clock is unaffected by wall-clock adjustments, but its reference point is undefined; only differences are meaningful. Enabling a systemd unit with `WantedBy=multi-user.target` makes it a boot dependency. [N10], [N11]

### Recommendations

**Use Gateway interactions and outbound connections only.** The bot needs no public listener, inbound router forwarding, public domain, or inbound UFW exception. Voice is outside this design. Preserve inbound access already needed by SSH and the machine's other services.

| Outbound need | Allow according to the existing network policy |
| --- | --- |
| Discord | TCP 443 for Gateway WSS, REST HTTPS, and CDN downloads when used. Honor library-discovered Gateway/resume URLs. |
| Name resolution/time | The host's actual DNS resolver and NTP/NTS servers, using their configured protocols. |
| Optional services | Chosen sprite source, backup destination, outbound health-check URL, and normal OS/package update sources. Protocols depend on the selected provider. |

Do not build a permanent allowlist from observed Discord IP addresses. Keep normal DNS resolution; if restrictive egress is necessary, maintain hostname-aware policy and test reconnects. **UNVERIFIED:** existing firewall rules, SSH port, DNS/NTS settings, and optional provider endpoints.

First inspect UFW:

```sh
sudo ufw status verbose
sudo ufw status numbered
```

For an otherwise unconfigured host, target deny unsolicited inbound/allow outbound, with explicit SSH/other-service exceptions before enabling.

If UFW already manages this host and outbound HTTPS is blocked, `sudo ufw allow out 443/tcp` is an example rule to **merge with the existing policy**, not a complete firewall setup. Preserve SSH and every existing service, cover DNS/time/backup traffic, and check IPv6. Do not reset UFW, change global defaults, or introduce a competing firewall manager blindly. [N12]

Enable the reviewed bot service and backup timer at boot; review idle-suspend and firmware power-return settings alongside existing workloads. Optionally add a UPS for computer/router with tested low-battery shutdown. Preserve filesystem durability settings; a UPS supplements durable commits/backups.

Let the libraries reconnect/resume with backoff; do not launch extra bot instances on each disconnect. Monitor disconnect duration and retry failures. Router/ISP outages may leave the bot process healthy but disconnected; `Restart=on-failure` alone cannot detect that condition. Keep a bounded backlog, acknowledge interactions promptly when connected, and do not award guessed steps for offline messages. Startup ordering is not a substitute for handling later network failure.

Keep the existing supported time daemon synchronized; `timedatectl status` and, for chrony, `chronyc tracking` provide useful checks. Synchronized system time suffices for game deadlines. Persist UTC deadlines and the last applied decay/progress timestamp; use monotonic durations only while running. After restart, recompute remaining time from persisted UTC state. Apply any chosen offline decay once in a transaction that advances its checkpoint; repeated startup or reconnect must not apply it again. Decide the offline-decay policy explicitly and flag large clock errors before catch-up.

## 4. Durable state, backups, and media cache

### Facts

- SQLite WAL allows concurrent readers but only one writer, and is unsuitable for a database shared over a network filesystem. WAL with `synchronous=FULL` provides commit durability; `NORMAL` can lose recently committed data after power/OS failure. Durability still depends on the filesystem/storage honoring sync operations. [D1], [D2], [D3]
- The WAL-reset corruption fix is in **3.51.3** and later, with backports **3.50.7** and **3.44.6**. **UNVERIFIED:** both the bot's linked SQLite engine and the backup CLI on the eventual host, including distribution backports. [D1]
- SQLite's online backup API supports consistent live backups; the CLI exposes `.backup`. `VACUUM INTO` creates a compact consistent snapshot into a new/empty destination. Since **3.40.0** it honors `synchronous`; current documentation specifies output synchronization for `NORMAL`/`FULL`. Interrupted output may be incomplete. [D4], [D5], [D6], [D7]
- A calendar timer with `Persistent=true` triggers a catch-up run after inactivity if a run was missed. `integrity_check` does not check foreign keys; use `foreign_key_check` separately. [D8], [D2]
- Litestream continuously replicates SQLite changes; latest verified release is **0.5.18**. Version 0.5 uses LTX storage, permits one replica per database, and lacks its former Age encryption. Old configuration/restore assumptions need review. **UNVERIFIED:** compatibility of the eventual binary, SQLite build, storage provider, and restore toolchain. [D9], [D10], [D11]
- systemd distinguishes `/var/lib` state from `/var/cache` cache directories. Pillow detects excessive decoded image sizes through its decompression-bomb protections. [D12], [D13]

### Recommendations

**Start with SQLite on local persistent disk and one bot process.** One writer actor should own complete transactions, including step flushes, encounter transitions, and catches. Serializing individual async calls is insufficient. Configure WAL, `synchronous=FULL`, and bounded busy retries; confirm both application and backup SQLite builds contain the WAL fix. Never place the live database on SMB/NFS or a cloud-sync folder. Move to Postgres when genuinely concurrent writers, remote database access, or operational needs justify its extra service and backup work. [D14]

| Path | Purpose |
| --- | --- |
| `/var/lib/pokewalker/` | Database, durable game state, and any non-regenerable asset metadata. |
| `/var/cache/pokewalker/` | Downloaded sprites/rendered images that can be safely recreated. |
| `/var/backups/pokewalker/` | Root/backup-job-managed snapshot staging, outside the cache and bot-writable tree. |

Keep local state and snapshot staging on encrypted storage. **UNVERIFIED:** existing encryption and boot-unlock setup. Document unattended unlock and key recovery; a manual LUKS passphrase can block automatic return after power loss.

Power loss destroys uncommitted RAM deltas even with WAL/FULL. Keep the existing flush-loss budget explicit and commit encounters/catches before reporting success. Monitor filesystem space, WAL growth, failed writes, and age of the last successful off-machine backup. Never delete WAL/journal files manually to “repair” a database.

#### Automated backup baseline

Proposed schedule: **hourly online snapshot, encrypted off-machine copy after each success, retain 24 hourly / 7 daily / 4 weekly restore points**. Off-machine recovery exposure includes backup delay, Internet outages, and uncommitted app data. Another disk in the computer is not off-machine protection; off-site copies also cover loss of home equipment.

Use a separately hardened root backup job with constant configured paths. Bot-owned 0700/0600 state requires deliberate ACLs for current/future DB, WAL, and shm files before an unprivileged backup user can read it. Give backups independent memory/CPU/I/O limits and lower priority; the bot cgroup does not constrain them. Prevent overlapping jobs; keep backup credentials/destination inaccessible to the bot. [D15]

Make `/var/backups/pokewalker` root/backup-job-owned **0700**, set the backup unit's own **`UMask=0077`**, and keep snapshots/recovery metadata **0600**. The bot's file mask does not propagate into that separate job; encrypted disks still need access controls while mounted.

Use the online API or `.backup` against a **unique staging destination**, with a busy timeout. Example for an already-permissioned backup job; replace `UNIQUE` and check every exit status:

```sh
sqlite3 -readonly /var/lib/pokewalker/walker.sqlite3 <<'SQL'
.timeout 5000
.backup /var/backups/pokewalker/walker-UNIQUE.partial
SQL
```

Check the snapshot, finalize its filename after success, then encrypt/upload. Never copy just the live `.db` file or rely on independently copied `.db`/WAL files. `VACUUM INTO` is a valid alternative on verified versions, but costs more CPU and is not incremental; reserve sufficient temporary space. For this small database, scheduled `.backup` is the simpler default. Do not make routine backups depend on stopping the bot.

Use a calendar systemd timer with `OnCalendar=hourly`, `Persistent=true`, and modest randomized delay. Retry failed uploads independently and retain unuploaded snapshots within a bounded disk budget; alert before that budget is exhausted. Apply retention only after a new copy succeeds. A missed-run catch-up creates one current snapshot, not one per missed hour.

Use an encrypted repository such as restic. Keep recovery keys separately recoverable, including offline/off-site. Include schema/version information, required durable assets, and deployment/configuration recovery notes. Exclude regenerable cache; recover secrets separately under restricted access. Restic's default `check` does not read all stored data; `check --read-data` does. [D16], [D17]

Verify snapshots with `PRAGMA integrity_check` and `PRAGMA foreign_key_check`; periodically read/verify remote data. **Monthly restore drill / real-recovery procedure:**

1. Retrieve/decrypt a selected remote snapshot into a fresh, restricted directory. Run offline integrity, foreign-key, schema, and game-state checks without a Discord token or network login. Record recovery time.
2. For real recovery only, stop the bot and pause backup/replication jobs and their timers; confirm all database users/workers have closed it. Quarantine the old database **together with any WAL/shm/rollback-journal sidecars**. Never pair a restored snapshot with old sidecars. [D3]
3. Install the validated snapshot in a clean state location. Verify restored directory/file ownership for `pokewalker` and modes **0700/0600**; a root-owned backup must not remain unreadable to the service.
4. Start exactly one production instance, check health, and resume the backup schedule. An offline drill ends before this activation step.

**Local validation, 2026-11-04:** Python/SQLite **3.53.1** backup API copied the committed snapshot while a write transaction was open; restore into a fresh directory after quarantining crash-fixture WAL files passed integrity, foreign-key, and fixture count checks. This tested disposable local data only. CLI `.backup`, encryption/off-machine retrieval, the real schema, and host recovery remain **UNVERIFIED**.

Consider Litestream only if a shorter recovery window merits another daemon and its monitoring. Pin a tested release; verify retention, replica lag, encryption, and restoration across the exact versions. Do not paste old 0.3 Age-encryption or multi-replica examples into 0.5. Replication does not replace retained backups and restore drills.

#### Bounded media cache

Proposed **combined sprite/render cache** limits: **256 MiB and 2,000 entries**, **7-day TTL**, and LRU eviction; whichever limit is reached first governs. Reserve disk headroom and disable cache writes before space becomes critical. Optional separate cache/state filesystem quotas can contain buggy writers; verify host support. Use bounded cleanup batches and atomic publication; exclude active/in-flight files. Keep required/non-regenerable assets separately from cache so cleanup never removes durable inputs.

Fetch only configured trusted sources, using derived cache keys rather than arbitrary user URLs/paths. Bound timeouts, redirects, downloaded bytes, decoded pixels, and animation frames; verify the actual format and keep image-library decompression protections enabled. Share the single render worker and bounded queue with the process design; a cache miss or sprite outage should yield a fallback screen, not block interaction acknowledgement. Actual provider availability and cache sizing remain **UNVERIFIED until measured**.

[N1]: https://docs.discord.com/developers/events/gateway "Discord Gateway — checked 2026-11-04"
[N2]: https://docs.discord.com/developers/reference "Discord API and CDN reference — checked 2026-11-04"
[N3]: https://docs.discord.com/developers/interactions/receiving-and-responding "Discord interaction transports — checked 2026-11-04"
[N4]: https://discordpy.readthedocs.io/en/stable/api.html#discord.Client.connect "discord.py reconnect — checked 2026-11-04"
[N5]: https://discord.js.org/docs/packages/discord.js/14.27.0/Client%3AClass "discord.js reconnect/resume events — checked 2026-11-04"
[N6]: https://systemd.io/NETWORK_ONLINE/ "systemd network startup ordering — checked 2026-11-04"
[N7]: https://www.iana.org/assignments/service-names-port-numbers/service-names-port-numbers.xhtml?search=domain "IANA DNS ports — checked 2026-11-04"
[N8]: https://ubuntu.com/server/docs/how-to/networking/timedatectl-and-timesyncd/ "Ubuntu time synchronization — checked 2026-11-04"
[N9]: https://documentation.ubuntu.com/release-notes/25.10/ "Ubuntu NTS ports/default — checked 2026-11-04"
[N10]: https://docs.python.org/3/library/time.html#time.monotonic "Python monotonic clock — checked 2026-11-04"
[N11]: https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html "systemd enable/boot semantics — checked 2026-11-04"
[N12]: https://ubuntu.com/server/docs/firewalls/ "Ubuntu UFW guidance — checked 2026-11-04"
[D1]: https://sqlite.org/wal.html "SQLite WAL and WAL-reset fix — checked 2026-11-04"
[D2]: https://sqlite.org/pragma.html "SQLite sync/integrity pragmas — checked 2026-11-04"
[D3]: https://sqlite.org/howtocorrupt.html "SQLite storage/sync assumptions — checked 2026-11-04"
[D4]: https://sqlite.org/backup.html "SQLite online backup — checked 2026-11-04"
[D5]: https://sqlite.org/cli.html "SQLite CLI backup — checked 2026-11-04"
[D6]: https://sqlite.org/lang_vacuum.html "SQLite VACUUM INTO — checked 2026-11-04"
[D7]: https://sqlite.org/releaselog/3_40_0.html "SQLite 3.40.0 sync change — checked 2026-11-04"
[D8]: https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html "systemd persistent timers — checked 2026-11-04"
[D9]: https://litestream.io/ "Litestream replication — checked 2026-11-04"
[D10]: https://github.com/benbjohnson/litestream/releases/tag/v0.5.18 "Litestream release — checked 2026-11-04"
[D11]: https://litestream.io/docs/migration/ "Litestream 0.5 migration constraints — checked 2026-11-04"
[D12]: https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html "systemd state/cache directories — checked 2026-11-04"
[D13]: https://pillow.readthedocs.io/en/stable/reference/Image.html "Pillow decompression limits — checked 2026-11-04"
[D14]: https://sqlite.org/whentouse.html "SQLite concurrency tradeoffs — checked 2026-11-04"
[D15]: https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html "systemd resource controls — checked 2026-11-04"
[D16]: https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html "restic encrypted repository access — checked 2026-11-04"
[D17]: https://restic.readthedocs.io/en/stable/045_working_with_repos.html "restic verification scope — checked 2026-11-04"
