# G-5 host bring-up and restore rehearsal

UNVERIFIED: this is an owner-run checklist, with no host acceptance recorded.
Use disposable synthetic player data and an isolated rehearsal database/repository;
do not restore over the live database to demonstrate these cases. Record actual
commands, versions, results and alert evidence before marking G-5 complete.
See [ADR 0001](../docs/decisions/0001-application-stack.md) and
[C6](../contracts/ops-runtime.md) for the required invariants.

## Inventory and protected configuration

- [ ] Confirm systemd 247 or later (required for LoadCredential), Ubuntu version,
  architecture, cgroup-v2 controllers, free disk and capacity alongside other services.
  The unit's CPU/memory/task limits are provisional until measured on this host.
- [ ] Confirm Python >= 3.12 and SQLite >= 3.51.3 (or WAL-fixed backports 3.50.7 /
  3.44.6). Record the exact PLAN G-5 version command output from the host:
  `python3 -c "import sqlite3,sys;print(sys.version, sqlite3.sqlite_version)"`.
  Also check the release venv's linked SQLite; do not enable the unpatched override.
- [ ] Provision `pokewalker` (bot account/group, no login, sudo, Docker or journal
  access) and `pokewalker-deploy` (build account, no access to /etc/pokewalker).
  Releases under `/opt/pokewalker/releases/<sha>` and the `current` link are controlled
  by deployment, readable but never writable by the bot. Build each venv at its final path.
- [ ] Protect `/etc/pokewalker` as root-owned 0700 and its files as root-owned 0600.
  Copy the env examples to `runtime.env` and `backup.env` there and replace every
  placeholder privately. Keep plain shell/systemd-compatible `KEY=value` assignments.
  Set the release SHA, owner IDs, admin guild ID and the protected restic/rclone setup.
  The privacy path selects the G-4-approved text in the readable release tree.
- [ ] Put the token and bot heartbeat URL in `credentials/discord_token` and
  `credentials/heartbeat_url`, delivered only through LoadCredential. Keep the
  `DISCORD_TOKEN` and `POKEWALKER_HEARTBEAT_URL` fallbacks empty in `runtime.env`.
  It contains every operator-configurable Settings.from_env key, with no secrets.
  Per the owner ruling, systemd supplies `CREDENTIALS_DIRECTORY`, `RUNTIME_DIRECTORY`
  and `STATE_DIRECTORY`; neither env template sets them. The transient check receives
  its own credential directory. The backup unit supplies its state directory, while
  deploy sets that same `/var/lib/pokewalker-backup` explicitly for a direct backup.
- [ ] Protect the rclone config, `RESTIC_PASSWORD_FILE` and dedicated
  `BACKUP_MONITOR_URL`. Initialize the encrypted off-machine repository under owner
  control. Configure the backup check for a 1-hour period and 2-hour grace and the bot
  heartbeat for a 60-second period and 120-second grace. Verify an independent alert
  channel; never copy secret URLs or tokens into the recorded evidence.

## First deployment and lifecycle

- [ ] Validate the units on the host before enabling them. Provision the authorized
  `build_release.sh` helper, root-controlled deploy PATH resolving the selected release's
  scripts, lock parent and unit-install directories required by `deploy.sh` (M5.2a).
  Confirm build receives neither bot credentials nor backup secrets; config checks
  run as the bot with the same EnvironmentFile, LoadCredential and RuntimeDirectory.
- [ ] On the first deploy, with no current link and no database, run the owner-selected
  40-character release SHA through `deploy.sh`. Confirm it skips stop/backup/rollback,
  installs the units, selects `current`, starts one bot and waits for `/run/pokewalker/ready`.
  The first startup creates the empty marker log beside the database; do not create
  an empty replacement if an initialized installation loses its existing markers.
- [ ] Enable the bot and hourly backup timer only after validation. Verify reboot,
  credential rotation and start-limit recovery. Confirm SIGTERM drains within
  20 seconds, below the unit stop timeout of 30 seconds, and leaves no children.
  Confirm an owner restart exits 75 and restarts under Restart=on-failure.
  Check sanitized journald output, per-unit rate limits and permissions with no secrets.
- [ ] Measure synchronous=FULL write latency at the measured chat rate. Exercise
  readiness failure and rollback, including exit 50 staying stopped for a newer schema.
  Restore SQLite only through the explicit owner-selected `--restore-db` path.

## ADR deletion and restore cases

Keep the newest external marker log when restoring an older database. Replay exact
profile IDs rather than deleting a later enrollment with the same guild/user.

- [ ] Snapshot before P1 is deleted, delete P1, then restore that snapshot with the
  newest markers. Startup replay removes P1 and its game data.
- [ ] Snapshot after P1 is deleted and the player is re-enrolled as P2. Restore with
  P1's marker: P2 and its data remain untouched.
- [ ] Simulate an interrupted deletion after the marker is durably saved but before
  database deletion commits. The next startup finishes deletion, including after restore.
- [ ] Delete a profile holding a unique fixture string and take a fresh backup.
  Confirm the string's bytes are absent from the raw backup file as well as its rows.
- [ ] Include an occupied gym with unpaid hours in the v2 restore fixture. After marker
  replay the gym is empty, old battle controls are refused and no income reaches P2.

## Backup, retention and monitor evidence

- [ ] Verify a readonly SQLite snapshot, integrity_check=ok, empty foreign_key_check
  and the paired external marker copy. Restore it and replay markers successfully.
  Check encryption/off-machine upload and exclusive timer/deploy locking.
- [ ] Seed synthetic local and tagged remote backups older than 28 days. Run prune
  with a failing upload: expired artifacts are removed anyway, this run's verified
  snapshot is reported, upload remains the dominant failure and the fail ping is seen.
  Keep evidence of the fail ping externally even if a later successful run pings success.
  Verify notification fallback for a crash and no duplicate normal failure notification.
- [ ] Verify Drive Trash is empty after prune and rclone has
  `RCLONE_DRIVE_USE_TRASH=false`; retained Trash must not extend the deletion window.
- [ ] Rehearse a missed hour and continued missing pings through the 2-hour grace;
  confirm the external alert, then restore the schedule. Also test failed prune,
  missing marker log, missing monitor configuration and monitor/network failure.
- [ ] Record results and unresolved gaps in the owner G-5 evidence. Offline tests
  establish template/path agreement only; Linux identity, systemd, backup storage,
  monitor delivery, runtime capacity and real restoration remain host acceptance.
