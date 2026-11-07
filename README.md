# Pokewalker-Discord-Bot

A Discord bot inspired by the Pokéwalker step-counter accessory from Pokémon
HeartGold/SoulSilver: members "walk" by chatting, meet wild Pokémon, and catch,
collect and power them up through the private `/walker` screen. Run `/readme` in
Discord for the player guide.

Requirements are in [docs/features/pokewalker-bot](docs/features/pokewalker-bot/README.md),
the stack is [ADR 0001](docs/decisions/0001-application-stack.md), and the build plan is
[PLAN.md](docs/features/pokewalker-bot/PLAN.md). The repository was initialized from
[`Farkoal2128/template-repo`](https://github.com/Farkoal2128/template-repo); feature work runs
through `feature-pipeline` using the repository facts in [PIPELINE.md](PIPELINE.md).

## Setting up the bot

The bot runs as a systemd service on a Linux host, with hourly encrypted backups to
Google Drive. The host steps below have been tested only against stand-in commands, not
on a real server yet; the full checklist is [deploy/restore-rehearsal.md](deploy/restore-rehearsal.md).

**Ubuntu shortcut:** after step 1, install [uv](https://docs.astral.sh/uv/) as your user and run
`sudo deploy/install_ubuntu.sh` from your clone. It does steps 2–4 and 6 for that clone's `HEAD`
(prompting for your IDs and the bot token), registers the slash commands and enables the bot on
boot. Backups (step 5) stay manual. Re-run it after pulling to deploy an update; upgrades take a
pre-deploy backup, so set up step 5 first.

### 1. Create the Discord application

1. In the [Discord Developer Portal](https://discord.com/developers/applications), create an
   application and open **Bot**.
2. Under **Privileged Gateway Intents**, turn **Message Content** on. Leave **Presence** and
   **Server Members** off. Leave **Requires OAuth2 Code Grant** off; turn **Public Bot** on
   only if other people should be able to invite it.
3. Copy the bot token (**Reset Token**). Keep it secret; never commit it or paste it in chat.
4. Invite the bot with scopes `bot` and `applications.commands` and these permissions:
   View Channels, Read Message History, Add Reactions (integer `66624`), plus Embed Links if
   you will use Share (`83008`):

   ```
   https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot+applications.commands&permissions=83008
   ```

5. With Discord **Developer Mode** on, copy your **User ID** (bot owner) and the **Server ID**
   of the server that should get the owner-only `/admin` command.

### 2. Prepare the host

Requirements: Linux with systemd 247+, Python 3.12+, and SQLite **3.51.3 or later** (or the
WAL-fixed 3.50.7 / 3.44.6) linked into that Python. The bot refuses to start on older SQLite.
Check with:

```bash
python3 -c "import sqlite3,sys;print(sys.version, sqlite3.sqlite_version)"
```

If the system SQLite is too old, use a Python build that bundles a newer one (for example a
[uv](https://docs.astral.sh/uv/)-managed CPython) and make it the `python3` on the deploy `PATH`.
Ubuntu 24.04 ships SQLite 3.45.1, which the bot refuses. Install the interpreter outside
`/home` (the bot unit sets `ProtectHome=yes`, and release venvs link to it), readable by both
service users:

```bash
sudo env UV_PYTHON_INSTALL_DIR=/opt/pokewalker/python ~/.local/bin/uv python install 3.12
sudo install -d -m 0755 /opt/pokewalker/bin
sudo ln -sf "$(sudo env UV_PYTHON_INSTALL_DIR=/opt/pokewalker/python ~/.local/bin/uv python find 3.12 --managed-python)" /opt/pokewalker/bin/python3
/opt/pokewalker/bin/python3 -c "import sqlite3;print(sqlite3.sqlite_version)"
```

Then put `/opt/pokewalker/bin` first on the deploy `PATH` in step 6.

Install the tools the scripts call (on Debian/Ubuntu; get `rclone` and `restic` from their
own sites if the packaged versions are old):

```bash
sudo apt install git python3-venv sqlite3 curl util-linux restic rclone
```

Create the two service accounts and the directories:

```bash
sudo useradd --system --home-dir /var/lib/pokewalker --shell /usr/sbin/nologin pokewalker
sudo useradd --system --home-dir /var/lib/pokewalker-deploy --create-home --shell /usr/sbin/nologin pokewalker-deploy
sudo install -d -m 0755 -o root -g root /opt/pokewalker
sudo install -d -m 0755 -o pokewalker-deploy -g pokewalker-deploy /opt/pokewalker/releases /srv/pokewalker
sudo install -d -m 0700 -o root -g root /etc/pokewalker /etc/pokewalker/credentials
```

`pokewalker` runs the bot; `pokewalker-deploy` only builds releases and never sees
`/etc/pokewalker`.

### 3. Get the code

```bash
sudo -u pokewalker-deploy git clone https://github.com/Farkoal2128/Pokewalker-Discord-Bot.git /srv/pokewalker/src
```

(If the repository is private, give `pokewalker-deploy` a read-only deploy key.)

### 4. Write the bot configuration

```bash
cd /srv/pokewalker/src
sudo install -m 0600 deploy/runtime.env.example /etc/pokewalker/runtime.env
sudo nano /etc/pokewalker/runtime.env
```

Fill in `POKEWALKER_OWNER_IDS` (your user ID; comma-separate several), `POKEWALKER_ADMIN_GUILD_ID`
(the server for `/admin`) and `POKEWALKER_RELEASE` (the commit you will deploy). Leave
`DISCORD_TOKEN` and `POKEWALKER_HEARTBEAT_URL` **empty**, keep the relative content and privacy
paths as they are, and keep `POKEWALKER_ALLOW_UNPATCHED_SQLITE=0`.

Put the secrets in credential files, which systemd hands to the bot:

```bash
sudo sh -c 'umask 077; printf "%s" "PASTE_BOT_TOKEN" > /etc/pokewalker/credentials/discord_token'
sudo sh -c 'umask 077; : > /etc/pokewalker/credentials/heartbeat_url'
```

The second file must exist even if empty. To get an alert when the bot stops, put a
heartbeat-monitor URL in it (for example a [Healthchecks.io](https://healthchecks.io) check with
a 60-second period and 120-second grace).

### 5. Set up Google Drive backups

Backups run hourly as root. Each is an integrity-checked SQLite snapshot plus the deletion log,
encrypted by **restic** and stored in Google Drive through **rclone**. Snapshots older than
28 days are deleted from Drive permanently (not to Drive's Trash); locally only the 24 newest
uploaded snapshots are kept. A failed stage pings your backup monitor's `/fail` URL.

**a. Create the rclone Google Drive remote.** The server usually has no browser, so get the
Google sign-in token on a computer that does, with rclone installed:

```bash
rclone authorize "drive"
```

Sign in with the Google account that should hold the backups, then copy the token JSON it
prints. On the server, create the remote in a root-only config file:

```bash
sudo rclone config --config /etc/pokewalker/rclone.conf
```

Answer: `n` (new remote) → name `gdrive` → storage `drive` → leave client ID and secret empty
(or use your own Google OAuth client, which rclone recommends for reliability) → scope `drive.file`
(rclone can only see files it created) → leave root folder and service account empty →
**No** to advanced config → **No** to auto config, then paste the token JSON → **No** to shared
drive → `y` to keep. Then lock it down and test it:

```bash
sudo chmod 600 /etc/pokewalker/rclone.conf
sudo rclone --config /etc/pokewalker/rclone.conf mkdir gdrive:pokewalker-backups
sudo rclone --config /etc/pokewalker/rclone.conf lsd gdrive:
```

**b. Create the restic password and repository.** Store the password somewhere safe as well;
without it the backups cannot be decrypted.

```bash
sudo sh -c 'umask 077; head -c 32 /dev/urandom | base64 > /etc/pokewalker/credentials/restic_password'
sudo env RCLONE_CONFIG=/etc/pokewalker/rclone.conf RCLONE_DRIVE_USE_TRASH=false \
  RESTIC_PASSWORD_FILE=/etc/pokewalker/credentials/restic_password \
  restic -r rclone:gdrive:pokewalker-backups init
```

**c. Write the backup configuration.**

```bash
sudo install -m 0600 deploy/backup.env.example /etc/pokewalker/backup.env
sudo nano /etc/pokewalker/backup.env
```

Set:

```
RESTIC_REPOSITORY=rclone:gdrive:pokewalker-backups
RESTIC_PASSWORD_FILE=/etc/pokewalker/credentials/restic_password
RCLONE_DRIVE_USE_TRASH=false
RCLONE_CONFIG=/etc/pokewalker/rclone.conf
POKEWALKER_MARKER_LOG=/var/lib/pokewalker/walker.sqlite3.markers.jsonl
BACKUP_MONITOR_URL=https://hc-ping.com/<your-check-uuid>
```

`BACKUP_MONITOR_URL` is required: backups refuse to run without it. Use a separate check with a
1-hour period and 2-hour grace; success pings the URL and failures ping `<URL>/fail`.

### 6. Deploy

Deploys run from the source checkout as root. They build the release as `pokewalker-deploy`,
check the configuration as the bot user, take a backup when upgrading, switch the `current`
link, and wait for the bot to report ready, rolling back if it doesn't:

```bash
cd /srv/pokewalker/src
sudo -u pokewalker-deploy git fetch origin
SHA=$(sudo -u pokewalker-deploy git rev-parse origin/main)
sudo sed -i "s/^POKEWALKER_RELEASE=.*/POKEWALKER_RELEASE=$SHA/" /etc/pokewalker/runtime.env
sudo env PATH="$PWD/deploy:/opt/pokewalker/bin:$PATH" deploy/deploy.sh "$SHA"
sudo systemctl enable --now pokewalker-bot.service pokewalker-backup.timer
```

Exit codes: `0` deployed · `10` preflight refused (configuration, build or check-config failed;
nothing changed) · `20` rolled back to the previous release · `30` rollback failed, bot stopped ·
`40` pre-deploy backup failed, previous release restarted · `50` the database is newer than the
previous release; the bot stays stopped and the printed snapshot is needed with `--restore-db`.

When the slash commands changed, the deploy prints which `sync-commands` to run. Register
gameplay commands globally as the bot user with its credentials:

```bash
sudo systemd-run --wait --pipe --collect -p User=pokewalker \
  -p WorkingDirectory=/opt/pokewalker/current \
  -p EnvironmentFile=/etc/pokewalker/runtime.env \
  -p LoadCredential=discord_token:/etc/pokewalker/credentials/discord_token \
  -p LoadCredential=heartbeat_url:/etc/pokewalker/credentials/heartbeat_url \
  /opt/pokewalker/current/.venv/bin/python -m pokewalker sync-commands --global --yes
```

For `/admin`, also run the command above with `sync-commands --guild <ADMIN_GUILD_ID> --yes`
as its final arguments. Global command changes can take a while to appear everywhere.

### 7. Configure each Discord server

In each server, someone with **Manage Server** picks the walking channels:
`/walker-admin channels add channel:#general reason:setup` (add `react:False` to count steps
without the ❗ reaction). Players start with `/walker`.

### 8. Run it

- Logs: `journalctl -u pokewalker-bot.service -f`; backups: `journalctl -u pokewalker-backup.service`.
- Update: repeat step 6 with the new commit.
- Restore a backup (bot stopped automatically): `sudo env PATH="$PWD/deploy:$PATH" deploy/deploy.sh "$SHA" --restore-db /path/to/snapshot.sqlite3`.
  Retrieve snapshots with `restic -r rclone:gdrive:pokewalker-backups restore latest --target /tmp/restore`
  (same environment variables as step 5b).
- Before relying on it, rehearse a restore with throwaway data:
  [deploy/restore-rehearsal.md](deploy/restore-rehearsal.md).

### Local development

```bash
python3.12 -m venv .venv          # any Python 3.12+ with SQLite >= 3.51.3
.venv/Scripts/python -m pip install --require-hashes -r requirements.lock   # .venv/bin/python on Linux
.venv/Scripts/python -m unittest discover -s tests -p "test_*.py"
```

To run against a test server, set `DISCORD_TOKEN`, `POKEWALKER_DEV_GUILD_ID`,
`POKEWALKER_OWNER_IDS`, `POKEWALKER_ADMIN_GUILD_ID`, `POKEWALKER_PRIVACY_PATH=docs/features/pokewalker-bot/privacy.md`
and `POKEWALKER_MARKER_LOG` (outside the repo), then run
`python -m pokewalker sync-commands --global --yes` for gameplay and
`python -m pokewalker sync-commands --guild <ADMIN_GUILD_ID> --yes` for `/admin`, then
`python -m pokewalker run`. Global command changes can take a while to appear.

## Default five-agent team

The template is ready for a five-agent development workflow modeled on the bounded work-order system used in `myAutoclip`:

| Team member | Responsibility |
| --- | --- |
| Lead Developer | Root coordinator; requirements, architecture, contracts, decomposition, integration, final status |
| Developer A | TDD implementation in an explicitly owned file scope |
| Developer B | Parallel TDD implementation in a disjoint file scope |
| Testing Agent | Independent same-session verification; reports defects instead of silently fixing them |
| Documentation Agent | Requirements/plans/ADRs/progress/evidence reconciliation after facts are established |

The root Lead plus the four configured Codex subagents equals five agents total.
See [multi-agent workflow](docs/multi-agent-workflow.md) and the [team contract](.agents/team/README.md).

Not every task should use every role. Short or tightly sequential work stays with the Lead.
Parallel writers are allowed only with non-overlapping ownership.

## Working agreement

**Requirement → Contract → RED → Minimal implementation → GREEN → Refactor → Verify → Document → Integrate.**

The source-of-truth order is:

1. requirements;
2. contracts;
3. executable tests;
4. implementation.

Never rewrite a contract or weaken a valid test merely because implementation disagrees.

## Getting started

Clone this project and verify the scaffold with Python 3.11 or later:

```sh
git clone https://github.com/Farkoal2128/Pokewalker-Discord-Bot.git
cd Pokewalker-Discord-Bot
python -m unittest discover -s tests -p "test_*.py"
python scripts/guard.py
python scripts/verify.py
```

The project has its own Git history and origin. `.template.json` records its project identity
and canonical framework source. Next, define requirements in `docs/features/`, document
boundaries in `contracts/`, and configure application checks in `.project/commands.json`.

## Repository map

| Area | Purpose |
| --- | --- |
| `AGENTS.md` | Repository-wide human/agent working contract |
| `PIPELINE.md` | Repository facts for `feature-pipeline` skills |
| `.agents/skills/` | TDD, contract, implementation, review, verification, and orchestration playbooks |
| `.agents/team/` | Default five-agent responsibilities and ownership rules |
| `.codex/` | Codex subagent routing for Developer A/B, Tester, and Documentation |
| `contracts/` | Authoritative external/domain boundary templates |
| `rules/` | Coding, testing, contract, security, and collaboration rules |
| `docs/features/` | Canonical feature plans and progress |
| `docs/decisions/` | Architecture Decision Records |
| `docs/templates/` | Work orders and reusable engineering records |
| `docs/verification/` | Exact executed evidence and limitations |
| `.project/commands.json` | Project-specific verification command adapter |
| `scripts/` | Copy guard and framework verification |
| `.github/` | CI and pull-request discipline |

## Multi-agent configuration

`.codex/config.toml` configures four subagent roles with a maximum of four concurrent
subagent threads. The coordinating/root agent is the Lead Developer.

The reference configuration follows the same routing pattern used in `myAutoclip`:
Developer A/B use an implementation profile; Tester and Documentation use a lighter high-effort profile.
If those model identifiers are unavailable in a future Codex environment, use the closest available models
and record actual runtime metadata rather than claiming the configured model ran.

Every delegated assignment uses [agent-work-order.md](docs/templates/agent-work-order.md).
For a whole run, [team-run.md](docs/templates/team-run.md) records dependency order,
exclusive write ownership, integration order, evidence, and stop conditions.

## Verification

```sh
python -m unittest discover -s tests -p "test_*.py"
python scripts/verify.py
python scripts/guard.py
```

A pristine framework passing its own tests is **not** proof that an application is ready.
Application verification commands start unconfigured in `.project/commands.json`.
A real project must replace them with actual unit, contract, integration, e2e, type, lint,
format, build, and security checks.

## Review boundaries

Same-session subagents are internal engineering assistance, not external independent approval.
Human acceptance, legal/security approval, production authorization, publication, spending,
and destructive data operations remain separately scoped actions.

See [adoption](docs/adoption.md), [GitHub setup](docs/github-setup.md), and
[provenance](docs/provenance/README.md).
