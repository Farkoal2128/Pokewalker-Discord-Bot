#!/bin/bash
# Ubuntu host setup plus deploy of this checkout's HEAD (README steps 2-4 and 6).
# Run from your own clone: sudo deploy/install_ubuntu.sh
# Safe to re-run: existing users, directories, config and credentials are kept.
set -euo pipefail
umask 022

[[ $(id -u) == 0 ]] || { echo "install_ubuntu: run with sudo" >&2; exit 1; }
checkout=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
git() { command git -c safe.directory='*' "$@"; }
sha=$(git -C "$checkout" rev-parse HEAD)
[[ -z $(git -C "$checkout" status --porcelain --untracked-files=no) ]] ||
    echo "install_ubuntu: warning: uncommitted changes are not deployed (deploying $sha)" >&2

home=$(getent passwd "${SUDO_USER:-root}" | cut -d: -f6)
uv=${UV:-$(command -v uv || echo "$home/.local/bin/uv")}
[[ -x $uv ]] || { echo "install_ubuntu: uv not found; install it: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; exit 1; }

echo "== packages"
apt-get install -y -q git python3-venv sqlite3 curl util-linux restic rclone >/dev/null

echo "== directories and service users"
install -d -m 0755 -o root -g root /opt/pokewalker /opt/pokewalker/bin
id -u pokewalker >/dev/null 2>&1 ||
    useradd --system --home-dir /var/lib/pokewalker --shell /usr/sbin/nologin pokewalker
id -u pokewalker-deploy >/dev/null 2>&1 ||
    useradd --system --home-dir /var/lib/pokewalker-deploy --create-home --shell /usr/sbin/nologin pokewalker-deploy
install -d -m 0755 -o pokewalker-deploy -g pokewalker-deploy /opt/pokewalker/releases /srv/pokewalker
install -d -m 0700 -o root -g root /etc/pokewalker /etc/pokewalker/credentials

echo "== Python with a WAL-fixed SQLite (Ubuntu's 3.45.1 is refused)"
# Outside /home: the bot unit sets ProtectHome=yes and release venvs link here.
export UV_PYTHON_INSTALL_DIR=/opt/pokewalker/python
"$uv" python install 3.12 >/dev/null
ln -sfn "$("$uv" python find 3.12 --managed-python)" /opt/pokewalker/bin/python3
/opt/pokewalker/bin/python3 -c 'import sqlite3, sys
ok =(sqlite3.sqlite_version_info >= (3, 51, 3) or (3, 50, 7) <= sqlite3.sqlite_version_info < (3, 51, 0)
      or (3, 44, 6) <= sqlite3.sqlite_version_info < (3, 45, 0))
print("   python", sys.version.split()[0], "sqlite", sqlite3.sqlite_version)
raise SystemExit(0 if ok else 1)'

echo "== source /srv/pokewalker/src at $sha"
src=/srv/pokewalker/src
[[ -d $src/.git ]] || git clone -q --no-checkout "$checkout" "$src"
git -C "$src" fetch -q "$checkout" HEAD
git -C "$src" checkout -q --detach "$sha"
chown -R pokewalker-deploy:pokewalker-deploy "$src"

echo "== configuration"
config=/etc/pokewalker/runtime.env
if [[ ! -f $config ]]; then
    read -rp "Your Discord user ID (bot owner; comma-separate several): " owners
    read -rp "Server ID for the owner-only /admin command (blank for none): " guild
    [[ $owners =~ ^[0-9]+(,[0-9]+)*$ && $guild =~ ^[0-9]*$ ]] || { echo "install_ubuntu: IDs must be numbers" >&2; exit 1; }
    (umask 077; sed -e "s/^POKEWALKER_OWNER_IDS=.*/POKEWALKER_OWNER_IDS=$owners/" \
        -e "s/^POKEWALKER_ADMIN_GUILD_ID=.*/POKEWALKER_ADMIN_GUILD_ID=$guild/" \
        "$src/deploy/runtime.env.example" > "$config")
fi
sed -i "s/^POKEWALKER_RELEASE=.*/POKEWALKER_RELEASE=$sha/" "$config"
token_file=/etc/pokewalker/credentials/discord_token
if [[ ! -s $token_file ]]; then
    read -rsp "Discord bot token (input hidden): " token; echo
    [[ -n $token ]] || { echo "install_ubuntu: token is required" >&2; exit 1; }
    (umask 077; printf '%s' "$token" > "$token_file")
    unset token
fi
[[ -e /etc/pokewalker/credentials/heartbeat_url ]] || (umask 077; : > /etc/pokewalker/credentials/heartbeat_url)

echo "== deploy"
cd "$src"
log=$(mktemp)
status=0
env PATH="$src/deploy:/opt/pokewalker/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    deploy/deploy.sh "$sha" 2>&1 | tee "$log" || status=${PIPESTATUS[0]}
if (( status )); then
    echo "install_ubuntu: deploy exited $status (see README step 6 exit codes;" \
         "40 on an upgrade means backups in README step 5 are not set up yet)" >&2
    exit "$status"
fi
systemctl enable pokewalker-bot.service >/dev/null 2>&1

echo "== slash commands"
grep -o '^sync-commands --[a-z]* *[0-9]* *--yes' "$log" | while read -r -a args; do
    systemd-run --wait --pipe --collect -p User=pokewalker \
        -p WorkingDirectory=/opt/pokewalker/current -p EnvironmentFile="$config" \
        -p LoadCredential=discord_token:"$token_file" \
        -p LoadCredential=heartbeat_url:/etc/pokewalker/credentials/heartbeat_url \
        /opt/pokewalker/current/.venv/bin/python -m pokewalker "${args[@]}"
done
rm -f "$log"

echo
echo "Done. The bot is running and starts on boot. Logs: journalctl -u pokewalker-bot.service -f"
echo "Backups are not enabled yet; set them up with README step 5, then:"
echo "  sudo systemctl enable --now pokewalker-backup.timer"
