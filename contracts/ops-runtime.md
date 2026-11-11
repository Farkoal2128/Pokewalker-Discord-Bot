# C6: operations runtime

Owner: deployment operator. Producers: `deploy/` and the bot process. Consumers:
systemd, deployment/recovery operators, restic/rclone and the backup monitor.
This additive contract implements D28 and ADR 0001; changing paths, credentials,
exit meanings or retention is a compatibility change requiring requirement review.

## Paths and identity handoff

Releases live at `/opt/pokewalker/releases/<sha>`; `current` selects a completed
release. Root serializes deploys with `/run/pokewalker-deploy/lock` in a root-owned
0700 directory under trusted `/run`; an existing lock is root-owned 0600, regular
and not a symlink. Build runs as `pokewalker-deploy`, without bot/backup credentials.
Configuration checks run as `pokewalker` with the bot unit properties:
`EnvironmentFile=/etc/pokewalker/runtime.env`,
`LoadCredential=discord_token:/etc/pokewalker/credentials/discord_token`,
`LoadCredential=heartbeat_url:/etc/pokewalker/credentials/heartbeat_url`,
`RuntimeDirectory=pokewalker`. Readiness is `/run/pokewalker/ready`.
`POKEWALKER_CONTENT_PATH` and `POKEWALKER_PRIVACY_PATH` are relative to the
unit's `WorkingDirectory` (the candidate release during preflight, `current` at
runtime), so check-config validates the candidate's own files on first install
and upgrade (ponytail-review-1 #1). Hosts with absolute `current/...` values must update them.

The database is `/var/lib/pokewalker/walker.sqlite3`; `POKEWALKER_MARKER_LOG`
selects its external deletion-marker log. `DEPLOY_ROOT` is an isolated-root prefix
for offline harnesses, including the database path. The backup unit and deploy
handoff use `/etc/pokewalker/backup.env`, `StateDirectory=pokewalker-backup`
(`/var/lib/pokewalker-backup`) and umask 0077. This root-managed file uses plain
shell/systemd-compatible `KEY=value`: `RESTIC_REPOSITORY=rclone:<remote>:<path>`,
`RESTIC_PASSWORD_FILE`, `RCLONE_DRIVE_USE_TRASH=false`,
`POKEWALKER_MARKER_LOG`, `BACKUP_MONITOR_URL`. Templates contain placeholders only.
Protect this file, the rclone configuration, restic password file and monitor URL.
The backup unit's PATH includes `/opt/pokewalker/current/deploy` for `prune.sh`;
the operator's deploy PATH must also resolve the selected release's scripts.
Credentials and secret URLs never appear in command arguments or logs. curl gets
the URL through stdin configuration; child diagnostics are suppressed.

## Backups, retention and monitoring

`backup.sh` holds flock on `$STATE_DIRECTORY/lock` for its whole three-stage run,
including monitor completion. Timer and deploy use that same persistent lock.
Only `$STATE_DIRECTORY/artifacts` is passed to `prune.sh`: this directory contains
backup artifacts and partials exclusively. Never pass the state directory, live
marker directory, persistent lock, `failed-stage` or `last-success` to retention.
The `notified-invocation` record is also control metadata, outside artifacts.

Snapshot: readonly SQLite `.backup` to a unique partial, successful
`integrity_check` (`ok`) and empty `foreign_key_check`, then copy the marker log
beside it and rename both. Missing or uncopyable markers fail the snapshot; an
empty fresh-install log is valid. A failed stage removes this run's partials and
incomplete pair. Upload: restic backs up both files with tag `pokewalker`, using
rclone with Drive Trash disabled. Prune always runs, including after snapshot or
upload failure; local and tagged remote artifacts older than 28 days are removed
by age alone, without a last-good exception, and retry on every run (M5.2b).
A successful upload writes `<snapshot stem>.uploaded` beside the pair. Locally,
prune also removes uploaded pairs beyond the 24 newest snapshots; unuploaded
pairs stay until the 28-day cutoff. Rationale (ponytail-audit-1 #1): hourly full
copies kept 28 days (672) would fill the host disk; restic holds history.

On exits 0, 2 and 3, stdout is exactly this run's verified local SQLite snapshot
path plus newline, for `deploy.sh` recovery. Exit 1 has no snapshot stdout.
All failed stages log `backup: <stage> failed`; `failed-stage` holds the first
failed stage word. Later failures cannot mask a snapshot failure.
On all-stage success, write `last-success` (UTC epoch seconds), remove stale
`failed-stage`, and ping the dedicated monitor with a 10-second timeout and no
body. Monitor failure emits no secret diagnostics and cannot manufacture success
delivery. `last-success` records completed backup stages, not confirmed HTTP
delivery. No success ping is attempted after any failed stage.

`backup_alert.sh` posts only `snapshot`, `upload`, `prune`, or `unknown` to the
monitor's `/fail` URL; absent or invalid failure metadata becomes `unknown`.
Per the owner's alert-path ruling, `backup.sh` invokes it with the dominant stage
before returning any handled failure, including direct deployment runs. Notifier
failure never changes the backup exit or snapshot-only stdout. Early preflight
failures attempt `unknown`; an absent monitor URL cannot deliver a ping.
The service retains `OnFailure` for unexpected exits and signals. Its notifier
uses `--fallback`: query `systemctl show --property=InvocationID --value
pokewalker-backup.service` and skip only when that exact valid invocation ID has
already delivered a failure ping. Record `notified-invocation` only after a
successful direct ping with a valid systemd `INVOCATION_ID`. An unavailable or
invalid property never suppresses a fallback. A stale previous invocation cannot
suppress a crash notification; direct deploy runs have no backup-unit invocation.
Normal timer failures therefore send once, while fallback covers a script that
dies before reporting. A crash after delivery can race the record and duplicate
the ping; the owner accepts that limit. An unwritable dedup record also favors a
fallback alert over suppressing one. A later success ping does not erase the
monitor's evidence that the failure ping was sent. Keep that evidence externally;
the local record is only deduplication state, not an alert-delivery audit log.
The external check has a 1-hour period and 2-hour grace. Missing success pings
cover a dead host, missing monitor configuration and notifier/network failures.
No monitor URL means refuse execution. A restore uses the newest available marker
log, replaying exact deleted profile IDs (D28), never a re-enrolled profile's ID.

## Exit codes and recovery

| Process | Exit meanings |
| --- | --- |
| Bot | 0 clean stop; 1 writer died after a failed rollback (heartbeat drains, systemd restarts); 75 deliberate owner restart (`Restart=on-failure`, never success status 75) |
| Deploy | 0 ready; 10 preflight refused; 20 previous release restored or first-deploy readiness failed; 30 recovery failed; 40 unusable snapshot, previous release restarted if possible; 50 newer DB schema, stay stopped and print this run's recovery snapshot |
| Backup | 0 all stages succeeded; 1 snapshot failed; else 2 upload failed; else 3 prune failed |
| Prune | 0 complete; 1 any local/remote selection or deletion failed |

Deploy continues only on backup 0/2/3, warning on 2/3; all other statuses abort
before release switch. Backups are optional: when `/etc/pokewalker/backup.env` is
absent, an upgrade skips `backup.sh` and instead copies the stopped database with
SQLite `.backup` to `/var/lib/pokewalker-backup/pre-deploy-<sha>.sqlite3` (the
recovery snapshot), printing that path; a failed copy restarts the previous release (40). Readiness rollback checks schema compatibility before
starting old code. SQLite restore occurs only with explicit `--restore-db`.

## Verification

`tests/test_backup.py`, `tests/test_deploy_script.py`, `tests/test_prune.py` cover
fake-host orchestration. Linux permissions/flock, systemd, WAL-fixed SQLite,
restic/rclone, Google Drive deletion, monitor delivery and restore rehearsal
remain G-5 host acceptance; offline tests do not establish them.
