#!/bin/bash
set -uo pipefail
failed=0
fail() { printf 'prune: %s failed\n' "$1" >&2; failed=1; }
[[ $# == 1 ]] || { fail local; exit 1; }
selector=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/prune_select.py
now=$(date +%s 2>/dev/null) || now=invalid

# Local retention never waits for repository availability; filenames stay NUL-delimited.
if ! python3 "$selector" --now "$now" --days 28 --keep 24 --local "$1" 2>/dev/null | (
    status=0
    while IFS= read -r -d '' file; do
        rm -- "$file" >/dev/null 2>&1 || status=1
    done
    exit "$status"
); then
    fail local
fi

if ids=$(restic snapshots --json --tag pokewalker 2>/dev/null |
         python3 "$selector" --now "$now" --days 28 2>/dev/null); then
    if [[ -n $ids ]]; then
        mapfile -t selected <<< "$ids"
        restic forget "${selected[@]}" >/dev/null 2>&1 || fail forget
    fi
else
    fail forget
fi
# A previous forget may have succeeded while its data prune failed.
restic prune >/dev/null 2>&1 || fail prune
exit "$failed"
