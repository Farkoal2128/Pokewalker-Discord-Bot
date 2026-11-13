#!/bin/bash
# Preserve only the operator-selected tool path and isolated-root override.
exec env -i PATH="$PATH" DEPLOY_ROOT="${DEPLOY_ROOT:-}" \
    bash --noprofile --norc -s -- "$@" <<'DEPLOY'
set -euo pipefail
umask 077
root=${DEPLOY_ROOT%/}
base=$root/opt/pokewalker
current=$base/current
database=$root/var/lib/pokewalker/walker.sqlite3
ready=$root/run/pokewalker/ready
config=$root/etc/pokewalker
snapshot=
restore=

refuse() { printf 'deploy: preflight refused\n' >&2; exit 10; }
[[ $# == 1 || ( $# == 3 && $2 == --restore-db ) ]] || refuse
sha=$1
[[ $sha =~ ^[0-9a-fA-F]{40}$ && $(id -u) == 0 ]] || refuse
if [[ $# == 3 ]]; then
    restore=$3
    [[ -f $restore && $restore != *\"* && $restore != *$'\n'* && $restore != *$'\r'* ]] || refuse
fi
lock_directory=$root/run/pokewalker-deploy
# A trusted parent and private directory prevent an unprivileged check/open swap.
[[ -d $root/run && ! -L $root/run ]] || refuse
read -r run_owner run_mode < <(stat -c '%u %a' -- "$root/run") || refuse
[[ $run_owner == 0 && $run_mode =~ ^[0-7]{3,4}$ ]] || refuse
(( (8#$run_mode & 0022) == 0 )) || refuse
mkdir -m 0700 -- "$lock_directory" 2>/dev/null || true
[[ -d $lock_directory && ! -L $lock_directory ]] || refuse
[[ $(stat -c '%u:%a' -- "$lock_directory") == 0:700 ]] || refuse
lock=$lock_directory/lock
if [[ -e $lock || -L $lock ]]; then
    [[ -f $lock && ! -L $lock ]] || refuse
    [[ $(stat -c '%u:%a' -- "$lock") == 0:600 ]] || refuse
fi
exec 9>>"$lock" || refuse
flock -n 9 || refuse

previous=
if [[ -L $current && -f $database ]]; then
    previous=$(readlink -f "$current") || refuse
    [[ $previous == "$base/releases/"* && -f $previous/.complete ]] || refuse
elif [[ -e $current || -L $current || -e $database || -n $restore ]]; then
    refuse
fi
release=$base/releases/$sha
# releases/ is root-owned; pokewalker-deploy only gets the one directory it builds into.
# A release root does not own (an interrupted deploy, a pre-hardening build) is rebuilt.
if [[ ! -f $release/.complete || $(stat -c %u -- "$release" 2>/dev/null) != 0 ]]; then
    rm -rf -- "$release" "$release.root"
    install -d -m 0755 -o pokewalker-deploy -g pokewalker-deploy -- "$release" || refuse
fi
runuser -u pokewalker-deploy -- env -i PATH="$PATH" HOME=/var/lib/pokewalker-deploy \
    DEPLOY_ROOT="$root" build_release.sh "$sha" >/dev/null 2>&1 || refuse
[[ -f $release/.complete && -f $release/deploy/pokewalker-bot.service ]] || refuse
# Root installs this release's units and the backup timer runs its scripts as root, so
# pokewalker-deploy must not be able to change it after the build: root replaces a build it
# does not own with its own copy (open write handles then point at deleted files), and no
# link may lead to a file outside root-owned places.
if [[ $(stat -c %u -- "$release") != 0 ]]; then
    rm -rf -- "$release.root"
    cp -R --preserve=mode,timestamps -- "$release" "$release.root" || refuse
    rm -rf -- "$release" || refuse
    mv -T -- "$release.root" "$release" || refuse
fi
while IFS= read -r -d '' link; do
    target=$(readlink -f -- "$link") || refuse
    [[ $target == "$release/"* || $target == "$base/bin/"* || $target == "$base/python/"* ]] || refuse
done < <(find "$release" -type l -print0)
# A rollback reinstalls the previous release's units, which may predate root ownership.
[[ -z $previous ]] || chown -R root:root -- "$previous" || refuse

as_bot() {
    local directory=$1
    shift
    systemd-run --wait --pipe --collect \
        -p User=pokewalker -p "WorkingDirectory=$directory" \
        -p "EnvironmentFile=$config/runtime.env" \
        -p "LoadCredential=discord_token:$config/credentials/discord_token" \
        -p "LoadCredential=heartbeat_url:$config/credentials/heartbeat_url" \
        -p RuntimeDirectory=pokewalker -p RuntimeDirectoryPreserve=yes \
        "$directory/.venv/bin/python" "$@"
}
as_bot "$release" -m pokewalker check-config >/dev/null 2>&1 || refuse

# This reuses application serialization without logging into Discord or opening SQLite.
manifest() {
    as_bot "$1" -c 'from pokewalker.config import Settings
from pokewalker.bot.client import WalkerBot
s = Settings.from_env()
b = WalkerBot(s)
print("global", b.command_manifest_hash())
if s.admin_guild_id:
    print(s.admin_guild_id, b.command_manifest_hash(s.admin_guild_id))' 2>/dev/null
}
desired=$(manifest "$release") || refuse
old_manifest=
if [[ -n $previous ]]; then
    old_manifest=$(manifest "$previous") || refuse
fi
while read -r scope hash extra; do
    [[ $scope == global || $scope =~ ^[0-9]+$ ]] || refuse
    [[ $hash =~ ^[0-9a-f]{64}$ && -z $extra ]] || refuse
done <<< "$desired"

wait_ready() {
    local second
    for ((second=0; second<60; second++)); do
        [[ ! -f $ready ]] || return 0
        sleep 1
    done
    [[ -f $ready ]]
}

start() {
    rm -f "$ready" || return 1
    systemctl start pokewalker-bot.service || return 1
    wait_ready
}

activate() {
    local directory=$1 unit
    for unit in "$directory"/deploy/*.service "$directory"/deploy/*.timer; do
        [[ -f $unit ]] || continue
        install -m 0644 "$unit" "$root/etc/systemd/system/" || return 1
    done
    systemctl daemon-reload || return 1
    rm -f "$current.next" || return 1
    ln -s "$directory" "$current.next" || return 1
    mv -Tf "$current.next" "$current" || return 1
}

rollback() {
    systemctl stop pokewalker-bot.service || exit 30
    [[ -n $previous ]] || exit 20
    local version migrations
    version=$(sqlite3 -readonly "$database" 'PRAGMA user_version;') || version=invalid
    shopt -s nullglob
    migrations=("$previous"/pokewalker/db/migrations/[0-9][0-9][0-9][0-9]_*.sql)
    if [[ ! $version =~ ^[0-9]+$ ]] || ((10#$version > ${#migrations[@]})); then
        printf 'deploy: schema recovery required; snapshot: %s\n' "$snapshot" >&2
        exit 50
    fi
    activate "$previous" && start || exit 30
    exit 20
}

if [[ -n $previous && ! -f $config/backup.env ]]; then
    # Backups are optional; keep one plain local copy for --restore-db recovery.
    systemctl stop pokewalker-bot.service || exit 30
    # A new name each time, so a --restore-db of an earlier copy is never overwritten.
    snapshot=$root/var/lib/pokewalker-backup/pre-deploy/$sha-$(date -u +%Y%m%dT%H%M%SZ).sqlite3
    { mkdir -p -- "${snapshot%/*}" && rm -f -- "$snapshot" &&
        sqlite3 -readonly "$database" ".backup \"$snapshot\""; } >/dev/null 2>&1 ||
        { start || true; exit 40; }
    # D28: the installer's tmpfiles rule deletes these copies after 28 days.
    printf 'deploy: backups not configured; local copy: %s\n' "$snapshot" >&2
elif [[ -n $previous ]]; then
    systemctl stop pokewalker-bot.service || exit 30
    status=0
    # backup.env is root-managed plain KEY=value, also consumed by the backup unit.
    snapshot=$(
        env -i PATH="$PATH" DEPLOY_ROOT="$root" \
            STATE_DIRECTORY="$root/var/lib/pokewalker-backup" \
            bash --noprofile --norc -c '
                umask 077
                set -a
                . "$1/backup.env" || exit 1
                set +a
                exec backup.sh
            ' backup "$config"
    ) || status=$?
    case $status in
        0) ;;
        2|3) printf 'deploy: backup warning (status %s)\n' "$status" >&2 ;;
        *) start || true; exit 40 ;;
    esac
fi

if [[ -n $restore ]]; then
    # SQLite restores only at the operator's explicit request, with the bot stopped.
    [[ $(sqlite3 -readonly "$restore" 'PRAGMA integrity_check;') == ok ]] || rollback
    sqlite3 "$database" ".restore \"$restore\"" >/dev/null 2>&1 || rollback
fi
activate "$release" && start || rollback

while read -r scope hash; do
    printf 'deploy: manifest %s SHA256: %s\n' "$scope" "$hash"
    if [[ $'\n'$old_manifest$'\n' != *$'\n'"$scope $hash"$'\n'* ]]; then
        if [[ $scope == global ]]; then
            printf 'sync-commands --global --yes (bot identity and unit credentials)\n'
        else
            printf 'sync-commands --guild %s --yes (bot identity and unit credentials)\n' "$scope"
        fi
    fi
done <<< "$desired"
DEPLOY
