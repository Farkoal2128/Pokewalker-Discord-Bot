#!/bin/bash
set -uo pipefail
umask 077
export STATE_DIRECTORY=${STATE_DIRECTORY:-/var/lib/pokewalker-backup}
alert=$(dirname -- "${BASH_SOURCE[0]}")/backup_alert.sh
refuse() { "$alert" unknown >/dev/null 2>&1 || true; exit 1; }
[[ -n ${BACKUP_MONITOR_URL:-} ]] || refuse
mkdir -p -- "$STATE_DIRECTORY" 2>/dev/null || refuse
# Command-mode flock keeps the same lock through snapshot, upload, prune and ping.
exec flock "$STATE_DIRECTORY/lock" bash --noprofile --norc -s -- "$alert" <<'BACKUP'
set -uo pipefail
alert=$1
artifacts=$STATE_DIRECTORY/artifacts
snapshot=
markers=
status=0
stage=
export RCLONE_DRIVE_USE_TRASH=false
failed() {
    printf 'backup: %s failed\n' "$1" >&2
    if (( status == 0 )); then status=$2; stage=$1; fi
}
snapshot_stage() {
    mkdir -p -- "$artifacts" || return 1
    partial=$(mktemp "$artifacts/snapshot-XXXXXXXX.sqlite3.partial") || return 1
    marker_partial=${partial%.sqlite3.partial}.markers.jsonl.partial
    snapshot=${partial%.partial}
    markers=${marker_partial%.partial}
    database=${DEPLOY_ROOT:-}/var/lib/pokewalker/walker.sqlite3
    [[ $partial != *\"* && $partial != *$'\n'* && $partial != *$'\r'* ]] || return 1
    sqlite3 -readonly "$database" ".backup \"$partial\"" || return 1
    integrity=$(sqlite3 -readonly "$partial" 'PRAGMA integrity_check;') || return 1
    [[ $integrity == ok ]] || return 1
    violations=$(sqlite3 -readonly "$partial" 'PRAGMA foreign_key_check;') || return 1
    [[ -z $violations ]] || return 1
    cp -- "${POKEWALKER_MARKER_LOG:-}" "$marker_partial" || return 1
    mv -- "$partial" "$snapshot" || return 1
    mv -- "$marker_partial" "$markers" || return 1
}
partial=
marker_partial=
if ! snapshot_stage >/dev/null 2>&1; then
    rm -f -- "$partial" "$marker_partial" "$snapshot" "$markers" >/dev/null 2>&1
    failed snapshot 1
else
    if restic backup --tag pokewalker "$snapshot" "$markers" >/dev/null 2>&1; then
        # Lets local prune drop this pair once it is off-machine and past the newest 24.
        : > "${snapshot%.sqlite3}.uploaded" 2>/dev/null || true
    else
        failed upload 2
    fi
fi
prune.sh "$artifacts" >/dev/null 2>&1 || failed prune 3
if (( status )); then
    printf '%s\n' "$stage" > "$STATE_DIRECTORY/failed-stage"
    "$alert" "$stage" >/dev/null 2>&1 || true
else
    date +%s > "$STATE_DIRECTORY/last-success"
    rm -f -- "$STATE_DIRECTORY/failed-stage"
    url=${BACKUP_MONITOR_URL//\\/\\\\}
    url=${url//\"/\\\"}
    if [[ $url != *$'\n'* && $url != *$'\r'* ]]; then
        printf 'url = "%s"\n' "$url" |
            curl --config - --silent --fail --max-time 10 --output /dev/null >/dev/null 2>&1 || true
    fi
fi
(( status == 1 )) || printf '%s\n' "$snapshot"
exit "$status"
BACKUP
