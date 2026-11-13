#!/bin/bash
set -euo pipefail
umask 022

refuse() { printf 'build_release: refused\n' >&2; exit 1; }

[[ $(id -u) != 0 ]] || refuse
for name in CREDENTIALS_DIRECTORY DISCORD_TOKEN BACKUP_MONITOR_URL; do
    [[ ! -v $name ]] || refuse
done
while IFS= read -r name; do
    [[ $name != RESTIC_* ]] || refuse
done < <(compgen -e)

[[ $# == 1 && $1 =~ ^[0-9a-fA-F]{40}$ ]] || refuse
sha=$1
# The deploy user's checkout, whatever directory root started deploy.sh from.
cd -- "${DEPLOY_ROOT:-}/srv/pokewalker/src" || refuse
git cat-file -e "${sha}^{commit}" || refuse

base=${DEPLOY_ROOT:-}/opt/pokewalker
release=$base/releases/$sha
[[ ! -f $release/.complete ]] || exit 0

# deploy.sh hands us this directory inside root-owned releases/; empty any partial build.
mkdir -p -- "$release"
find "$release" -mindepth 1 -delete
git archive --format=tar "$sha" | tar -xf - -C "$release"
python3 -m venv "$release/.venv"
"$release/.venv/bin/pip" install --require-hashes --no-input -r "$release/requirements.lock"
chmod -R u+rwX,go+rX,go-w -- "$release"
printf '%s\n' "$sha" > "$release/.complete"
sync -f "$release/.complete"
sync -f "$release"
