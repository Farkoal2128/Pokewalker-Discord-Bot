#!/bin/bash
set -uo pipefail
umask 077
[[ -n ${BACKUP_MONITOR_URL:-} ]] || exit 1
state=${STATE_DIRECTORY:-/var/lib/pokewalker-backup}
fallback=false
if [[ ${1:-} == --fallback ]]; then
    fallback=true
    invocation=$(systemctl show --property=InvocationID --value pokewalker-backup.service 2>/dev/null) || invocation=
    if [[ $invocation =~ ^[0-9a-f]{32}$ && -f $state/notified-invocation ]]; then
        IFS= read -r notified < "$state/notified-invocation" || notified=
        [[ $notified != "$invocation" ]] || exit 0
    fi
fi
stage=${1:-unknown}
if [[ $# == 0 || $fallback == true ]]; then
    IFS= read -r stage 2>/dev/null < "$state/failed-stage" || stage=unknown
fi
case $stage in snapshot|upload|prune) ;; *) stage=unknown ;; esac
url=${BACKUP_MONITOR_URL%/}/fail
[[ $url != *$'\n'* && $url != *$'\r'* ]] || exit 1
url=${url//\\/\\\\}
url=${url//\"/\\\"}
printf 'url = "%s"\n' "$url" |
    curl --config - --silent --fail --max-time 10 --output /dev/null --data "$stage" >/dev/null 2>&1 || exit 1
if [[ $fallback == false && ${INVOCATION_ID:-} =~ ^[0-9a-f]{32}$ ]]; then
    printf '%s\n' "$INVOCATION_ID" > "$state/notified-invocation"
fi
exit 0
