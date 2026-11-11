"""M5.2a operator boundary; every host operation is a Bash PATH fake.

These checks prove orchestration, not Linux identities, systemd or live readiness.
The harness is also reusable by M5.2c's real-backup boundary test.
"""

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
OLD = "a" * 40
NEW = "b" * 40
TOKEN = "synthetic-secret-do-not-print"


def shell_path(path, resolve=True):
    # A Linux venv's python is a symlink; resolving it would escape the venv's packages.
    path = (Path(path).resolve() if resolve else Path(os.path.abspath(path))).as_posix()
    return f"/{path[0].lower()}{path[2:]}" if len(path) > 1 and path[1] == ":" else path


@unittest.skipUnless(BASH, "bash unavailable; deployment behavior UNVERIFIED")
class DeployScriptTests(unittest.TestCase):
    def setUp(self):
        cache = REPO / "build/test-deploy"
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls"
        self.log.touch()
        self.fixture = self.root / "fixture"
        self.fixture.mkdir()
        for directory in ("opt/pokewalker/releases", "var/lib/pokewalker",
                          "var/lib/pokewalker-backup", "run/pokewalker", "var/lock",
                          "etc/pokewalker", "etc/systemd/system"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.db = self.root / "var/lib/pokewalker/walker.sqlite3"
        self.current = self.root / "opt/pokewalker/current"
        self.ready = self.root / "run/pokewalker/ready"
        self.release(OLD)
        self.release(NEW)
        self.current.symlink_to(self.release_path(OLD), target_is_directory=True)
        self.db.write_text("original database", encoding="utf-8")
        self.setting("schema", "1")
        self.setting("ready", "1 1")
        self.setting("backup", "0")
        self.setting("manifest-old", "1" * 64)
        self.setting("manifest-new", "2" * 64)
        (self.root / "etc/pokewalker/backup.env").write_text(
            "RESTIC_REPOSITORY=synthetic:repository\n"
            "RESTIC_PASSWORD_FILE=/synthetic/password-file\n"
            "RCLONE_DRIVE_USE_TRASH=false\n"
            "POKEWALKER_MARKER_LOG=/synthetic/markers\n"
            "BACKUP_MONITOR_URL=https://synthetic.invalid/monitor\n", encoding="utf-8", newline="\n")
        root = shlex.quote(shell_path(self.root))
        prelude = f'''#!/bin/bash
root={root}
name=${{0##*/}}
printf '%s' "$name" >> "$root/calls"
printf '|%s' "$@" >> "$root/calls"
printf '\\n' >> "$root/calls"
'''
        behavior = r'''
case "$name" in
env) exec /usr/bin/env "$@" ;;
id) printf '%s\n' "$(< "$root/fixture/uid")" ;;
stat)
    case "${!#}" in
    "$root/run")
        if [[ -e "$root/fixture/run-stat" ]]; then
            printf '%s\n' "$(< "$root/fixture/run-stat")"
        else printf '0 755\n'; fi ;;
    "$root/run/pokewalker-deploy")
        if [[ -e "$root/fixture/lock-directory-stat" ]]; then
            printf '%s\n' "$(< "$root/fixture/lock-directory-stat")"
        else printf '0:700\n'; fi ;;
    "$root/run/pokewalker-deploy/lock") printf '0:600\n' ;;
    *) exit 99 ;;
    esac ;;
flock) [[ ! -e "$root/fixture/locked" ]] ;;
runuser) [[ $1 == -u && $2 == pokewalker-deploy && $3 == -- ]] || exit 99
         shift 3; exec "$@" ;;
build_release.sh)
    printf 'build-env|%s|%s|%s|%s|%s|%s\n' "${HOME-unset}" "${DISCORD_TOKEN-unset}" \
        "${CREDENTIALS_DIRECTORY-unset}" "${RESTIC_PASSWORD-unset}" \
        "${BACKUP_MONITOR_URL-unset}" "${OPERATOR_ONLY-unset}" >> "$root/calls"
    [[ ! -e "$root/fixture/build-fail" ]] ;;
systemd-run)
    [[ ! -e "$root/fixture/check-fail" ]] || exit 1
    printf 'bot-env|%s|%s\n' "${DISCORD_TOKEN-unset}" "${OPERATOR_ONLY-unset}" >> "$root/calls"
    for arg in "$@"; do
        if [[ $arg == */.venv/bin/python ]]; then
            release=${arg%/.venv/bin/python}
        fi
        case "$arg" in
        WorkingDirectory=*) workdir=${arg#WorkingDirectory=} ;;
        EnvironmentFile=*) envfile=${arg#EnvironmentFile=} ;;
        esac
    done
    if [[ -e "$root/fixture/real-check" ]] &&
            [[ ${!#} == check-config || -e "$root/fixture/real-manifest" ]]; then
        # Real loader in the unit's WorkingDirectory; absolute env paths live under the fake root.
        native() { if command -v cygpath >/dev/null; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
        cd "$workdir" || exit 1
        while IFS='=' read -r key value; do
            [[ -n $key ]] || continue
            [[ $value != /* ]] || value=$(native "$root$value")
            export "$key=$value"
        done < "$envfile"
        export CREDENTIALS_DIRECTORY=$(native "$root/fixture/credentials")
        export PYTHONPATH=$(native "$(< "$root/fixture/repo")")
        if [[ ${!#} == check-config ]]; then
            exec "$(< "$root/fixture/python")" -m pokewalker check-config
        fi
        # Native Windows Python must emit the Linux unit's LF stdout protocol.
        exec "$(< "$root/fixture/python")" -c $'import sys; sys.stdout.reconfigure(newline="\\n")\n'"${!#}"
    elif [[ " $* " == *' check-config '* || ${!#} == check-config ]]; then
        printf 'Configuration and content hash valid\n'
    else
        if [[ $release == */aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ]]; then
            printf 'global %s\n' "$(< "$root/fixture/manifest-old")"
        else
            printf 'global %s\n' "$(< "$root/fixture/manifest-new")"
        fi
    fi ;;
systemctl)
    printf 'root-env|%s|%s\n' "${DISCORD_TOKEN-unset}" "${OPERATOR_ONLY-unset}" >> "$root/calls"
    case "$1" in
    stop) /usr/bin/rm -f "$root/run/pokewalker/ready" ;;
    start)
        count=0; [[ ! -e "$root/fixture/starts" ]] || count=$(< "$root/fixture/starts")
        (( count += 1 )); printf '%s' "$count" > "$root/fixture/starts"
        read -ra outcomes < "$root/fixture/ready"
        if [[ ${outcomes[count-1]:-0} == 1 ]]; then
            printf ready > "$root/run/pokewalker/ready"
        fi ;;
    esac ;;
backup.sh)
    printf 'backup-env|%s|%s|%s|%s|%s|%s\n' "${STATE_DIRECTORY-unset}" \
        "${RESTIC_REPOSITORY-unset}" "${RCLONE_DRIVE_USE_TRASH-unset}" \
        "${DISCORD_TOKEN-unset}" "${OPERATOR_ONLY-unset}" "$(umask)" >> "$root/calls"
    printf '%s\n' "$root/var/lib/pokewalker-backup/this-run.sqlite3"
    exit "$(< "$root/fixture/backup")" ;;
sqlite3)
    if [[ ${!#} == 'PRAGMA user_version;' ]]; then
        printf '%s\n' "$(< "$root/fixture/schema")"
    elif [[ ${!#} == .restore* ]]; then
        printf restored > "$root/var/lib/pokewalker/walker.sqlite3"
        printf 1 > "$root/fixture/schema"
    elif [[ ${!#} == 'PRAGMA integrity_check;' ]]; then
        printf 'ok\n'
    fi ;;
sleep) : ;;
ln) MSYS=winsymlinks:nativestrict exec /usr/bin/ln "$@" ;;
*) exec "/usr/bin/$name" "$@" ;;
esac
'''
        for name in ("env", "id", "stat", "flock", "runuser", "build_release.sh", "systemd-run",
                     "systemctl", "backup.sh", "sqlite3", "sleep", "readlink", "install",
                     "ln", "mv", "rm", "mkdir"):
            path = self.bin / name
            path.write_text(prelude + behavior, encoding="utf-8", newline="\n")
            path.chmod(0o755)
        self.setting("uid", "0")

    def setting(self, name, value):
        (self.fixture / name).write_text(value + "\n", encoding="utf-8", newline="\n")

    def release_path(self, sha):
        return self.root / "opt/pokewalker/releases" / sha

    def release(self, sha):
        release = self.release_path(sha)
        (release / "deploy").mkdir(parents=True, exist_ok=True)
        (release / "pokewalker/db/migrations").mkdir(parents=True, exist_ok=True)
        (release / "pokewalker/db/migrations/0001_initial.sql").touch()
        (release / ".complete").touch()
        for unit in ("pokewalker-bot.service", "pokewalker-backup.service",
                     "pokewalker-backup.timer", "pokewalker-backup-failed.service"):
            (release / "deploy" / unit).write_text(sha, encoding="utf-8")

    def real_check_config(self, valid=(OLD, NEW)):
        """Run the real check-config loader against candidate releases holding these files."""
        self.setting("real-check", "1")
        self.setting("python", shell_path(sys.executable, resolve=False))
        self.setting("repo", shell_path(REPO))
        (self.fixture / "credentials").mkdir()
        (self.fixture / "credentials/discord_token").write_text(TOKEN, encoding="utf-8")
        runtime = (REPO / "deploy/runtime.env.example").read_text(encoding="utf-8")
        runtime = runtime.replace("REPLACE_OWNER_IDS", "123456789012345678").replace(
            "REPLACE_ADMIN_GUILD_ID", "223456789012345678")
        (self.root / "etc/pokewalker/runtime.env").write_text(runtime, encoding="utf-8", newline="\n")
        artifact = (REPO / "content/artifact/content.json").read_bytes()
        for sha in (OLD, NEW):
            release = self.release_path(sha)
            (release / "content/artifact").mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / "content/manifest.json", release / "content/manifest.json")
            # A trailing byte breaks the manifest hash, as a corrupt candidate artifact would.
            (release / "content/artifact/content.json").write_bytes(
                artifact if sha in valid else artifact + b" ")
            privacy = release / "docs/features/pokewalker-bot/privacy.md"
            privacy.parent.mkdir(parents=True, exist_ok=True)
            privacy.write_text(f"Privacy text for {sha}.", encoding="utf-8")

    def test_real_check_config_first_install_reads_candidate_release(self):
        self.current.unlink()
        self.db.unlink()
        self.real_check_config(valid=(NEW,))
        self.assertEqual(self.run_deploy(), 0, self.output)
        self.assertEqual(Path(os.path.realpath(self.current)), self.release_path(NEW).resolve())

    def test_real_check_config_upgrade_refuses_broken_candidate_content(self):
        self.real_check_config(valid=(OLD,))
        self.assertEqual(self.run_deploy(), 10, self.output)
        self.assertIn("preflight refused", self.output)
        self.assertEqual(Path(os.path.realpath(self.current)), self.release_path(OLD).resolve())

    def run_deploy(self, *args):
        script = REPO / "deploy/deploy.sh"
        self.assertTrue(script.exists(), "required root deployment orchestrator is absent")
        environment = os.environ.copy()
        environment.update(PATH=f"{shell_path(self.bin)}:/usr/bin:/bin",
                           DEPLOY_ROOT=shell_path(self.root), DISCORD_TOKEN=TOKEN,
                           CREDENTIALS_DIRECTORY="/synthetic/operator-credentials",
                           RESTIC_PASSWORD=TOKEN, BACKUP_MONITOR_URL=TOKEN,
                           OPERATOR_ONLY="operator-shell-state")
        result = subprocess.run([BASH, "--noprofile", "--norc", shell_path(script),
                                 *(args or (NEW,))], env=environment, cwd=REPO,
                                text=True, capture_output=True, timeout=120)  # headroom: rollback cases take ~27 s alone, more on a loaded host
        self.calls = self.log.read_text(encoding="utf-8").splitlines()
        self.output = result.stdout + result.stderr
        return result.returncode

    def named(self, name):
        return [line for line in self.calls if line.split("|", 1)[0] == name]

    def test_build_as_deploy_user_clean_env_no_credentials(self):
        self.assertEqual(self.run_deploy(), 0, self.output)
        call = self.named("runuser")[0]
        self.assertIn("|-u|pokewalker-deploy|--|env|-i|PATH=", call)
        self.assertIn("|HOME=/var/lib/pokewalker-deploy|", call)
        self.assertEqual(self.named("build-env"),
                         ["build-env|/var/lib/pokewalker-deploy|unset|unset|unset|unset|unset"])

    def test_check_config_as_bot_user_with_unit_properties(self):
        self.assertEqual(self.run_deploy(), 0, self.output)
        call = next(line for line in self.named("systemd-run") if line.endswith("|check-config"))
        for prop in ("User=pokewalker", "EnvironmentFile=" + shell_path(self.root / "etc/pokewalker/runtime.env"),
                     "LoadCredential=discord_token:" + shell_path(self.root / "etc/pokewalker/credentials/discord_token"),
                     "LoadCredential=heartbeat_url:" + shell_path(self.root / "etc/pokewalker/credentials/heartbeat_url")):
            self.assertIn("|-p|" + prop, call)
        self.assertIn("|--wait|--pipe|--collect|", call)
        self.assertTrue(all(line == "bot-env|unset|unset" for line in self.named("bot-env")))

    def test_root_steps_only(self):
        self.assertEqual(self.run_deploy(), 0, self.output)
        self.assertTrue(all(line == "root-env|unset|unset" for line in self.named("root-env")))
        backup = self.named("backup-env")[0]
        self.assertIn("|synthetic:repository|false|unset|unset|0077", backup)
        self.assertIn(shell_path(self.root / "var/lib/pokewalker-backup"), backup)
        self.assertFalse(any(line.split("|", 1)[0] in {"pip", "python", "python3"}
                             for line in self.calls))

    def test_first_deploy_skips_stop_backup_and_rollback(self):
        self.current.unlink()
        self.db.unlink()
        self.assertEqual(self.run_deploy(), 0, self.output)
        self.assertFalse(self.named("backup.sh"))
        self.assertFalse(any("|stop|" in line for line in self.named("systemctl")))
        self.log.write_text("", encoding="utf-8")
        self.current.unlink()
        self.setting("ready", "0")
        self.assertEqual(self.run_deploy(), 20, self.output)
        self.assertEqual(len([x for x in self.named("systemctl") if "|start|" in x]), 1)
        self.assertIn("|stop|pokewalker-bot.service", self.named("systemctl")[-1])

    def test_half_installed_host_exit_10(self):
        self.db.unlink()
        self.assertEqual(self.run_deploy(), 10, self.output)
        self.assertFalse(self.named("systemctl"))
        self.db.touch()
        self.current.unlink()
        self.assertEqual(self.run_deploy(), 10, self.output)

    def test_check_config_failure_exit_10_before_stop(self):
        self.setting("check-fail", "1")
        self.assertEqual(self.run_deploy(), 10, self.output)
        self.assertFalse(self.named("systemctl"))

    def test_incomplete_release_never_used(self):
        (self.release_path(NEW) / ".complete").unlink()
        self.assertEqual(self.run_deploy(), 10, self.output)
        self.assertFalse(self.named("systemctl"))
        self.assertTrue(self.current.resolve().name == OLD)

    def test_call_order_stop_backup_switch_start_wait_ready(self):
        self.assertEqual(self.run_deploy(), 0, self.output)
        events = [line.split("|", 1)[0] for line in self.calls]
        self.assertLess(events.index("flock"), events.index("build_release.sh"))
        stop = next(i for i, x in enumerate(self.calls) if x == "systemctl|stop|pokewalker-bot.service")
        backup = events.index("backup.sh")
        switch = events.index("mv")
        start = next(i for i, x in enumerate(self.calls) if x == "systemctl|start|pokewalker-bot.service")
        self.assertLess(stop, backup)
        self.assertLess(backup, switch)
        self.assertLess(switch, start)
        self.assertEqual(self.current.resolve().name, NEW)
        self.assertEqual((self.root / "etc/systemd/system/pokewalker-bot.service").read_text(), NEW)

    def test_snapshot_failure_after_stop_restarts_previous_exit_40(self):
        self.setting("backup", "1")
        self.assertEqual(self.run_deploy(), 40, self.output)
        self.assertEqual(self.current.resolve().name, OLD)
        self.assertTrue(self.ready.exists())
        self.assertFalse(self.named("install"))

    def test_unknown_backup_status_treated_as_no_snapshot_exit_40(self):
        self.setting("backup", "17")
        self.assertEqual(self.run_deploy(), 40, self.output)
        self.assertEqual(self.current.resolve().name, OLD)

    def test_backup_2_or_3_warns_and_continues(self):
        for status in (2, 3):
            with self.subTest(status=status):
                self.setting("backup", str(status))
                self.assertEqual(self.run_deploy(), 0, self.output)
                self.assertIn("warning", self.output.lower())

    def test_backups_not_configured_takes_local_copy_and_continues(self):
        (self.root / "etc/pokewalker/backup.env").unlink()
        self.assertEqual(self.run_deploy(), 0, self.output)
        self.assertFalse(self.named("backup.sh"))
        copy = shell_path(self.root / f"var/lib/pokewalker-backup/pre-deploy-{NEW}.sqlite3")
        self.assertIn(f'sqlite3|-readonly|{shell_path(self.db)}|.backup "{copy}"', self.calls)
        self.assertIn(f"backups not configured; local copy: {copy}", self.output)
        self.assertEqual(self.current.resolve().name, NEW)

    def test_backups_not_configured_copy_failure_restarts_previous_exit_40(self):
        (self.root / "etc/pokewalker/backup.env").unlink()
        (self.root / "var/lib/pokewalker-backup").rmdir()
        (self.root / "var/lib/pokewalker-backup").write_text("not a directory")
        self.assertEqual(self.run_deploy(), 40, self.output)
        self.assertEqual(self.current.resolve().name, OLD)
        self.assertTrue(self.ready.exists())

    def test_compatible_rollback_exit_20(self):
        self.setting("ready", "0 1")
        self.ready.touch()  # a stale marker cannot make the new start healthy
        self.assertEqual(self.run_deploy(), 20, self.output)
        self.assertEqual(self.current.resolve().name, OLD)
        self.assertEqual((self.root / "etc/systemd/system/pokewalker-bot.service").read_text(), OLD)
        self.assertEqual(len(self.named("sleep")), 60)
        self.assertTrue(any("|-readonly|" in x and x.endswith("|PRAGMA user_version;")
                            for x in self.named("sqlite3")))

    def test_migration_then_readiness_failure_newer_schema_stays_stopped_exit_50(self):
        self.setting("ready", "0 1")
        self.setting("schema", "2")
        self.assertEqual(self.run_deploy(), 50, self.output)
        self.assertEqual(len([x for x in self.named("systemctl") if "|start|" in x]), 1)
        self.assertFalse(self.ready.exists())
        self.assertIn("this-run.sqlite3", self.output)
        self.assertFalse(any(".restore" in x for x in self.named("sqlite3")))

    def test_db_restored_only_with_restore_db(self):
        self.assertEqual(self.run_deploy(), 0, self.output)
        self.assertEqual(self.db.read_text(), "original database")
        snapshot = self.root / "explicit snapshot.sqlite3"
        snapshot.write_text("synthetic snapshot", encoding="utf-8")
        self.assertEqual(self.run_deploy(NEW, "--restore-db", shell_path(snapshot)), 0, self.output)
        self.assertEqual(self.db.read_text(), "restored")
        restores = [x for x in self.named("sqlite3") if ".restore" in x]
        self.assertEqual(len(restores), 1)
        self.assertIn(shell_path(snapshot), restores[0])
        stop = max(i for i, x in enumerate(self.calls) if x == "systemctl|stop|pokewalker-bot.service")
        self.assertLess(stop, self.calls.index(restores[0]))

    def test_rollback_failure_exit_30(self):
        self.setting("ready", "0 0")
        self.assertEqual(self.run_deploy(), 30, self.output)
        self.assertEqual(self.current.resolve().name, OLD)

    def test_sync_line_only_on_manifest_change(self):
        self.assertEqual(self.run_deploy(), 0, self.output)
        self.assertIn("2" * 64, self.output)
        self.assertIn("sync-commands --global", self.output)
        self.setting("manifest-old", "2" * 64)
        self.assertEqual(self.run_deploy(), 0, self.output)
        self.assertNotIn("sync-commands", self.output)

    def test_generated_manifests_match_actual_registration_scopes(self):
        from pokewalker.bot.client import WalkerBot
        from pokewalker.config import Secret, Settings
        import discord

        self.current.unlink()
        self.db.unlink()
        self.real_check_config()
        self.setting('real-manifest', '1')
        guild_id = 223456789012345678
        bot = WalkerBot(Settings(Secret(TOKEN), owner_ids=frozenset({123456789012345678}),
                                 admin_guild_id=guild_id))
        self.assertEqual(self.run_deploy(), 0, self.output)
        for scope, guild in [('global', None), (guild_id, discord.Object(id=guild_id))]:
            with self.subTest(scope=scope):
                payload = [c.to_dict(bot.tree) for c in sorted(
                    bot.tree.get_commands(guild=guild), key=lambda c: c.name)]
                if guild is not None:
                    self.assertEqual({c['name'] for c in payload}, {'admin'})
                manifest = {'scope': scope, 'commands': payload}
                digest = hashlib.sha256(json.dumps(
                    manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                self.assertIn(f'deploy: manifest {scope} SHA256: {digest}', self.output)
        self.assertIn(f'sync-commands --guild {guild_id} --yes', self.output)
        self.assertIn('sync-commands --global --yes', self.output)

    def test_no_token_in_args_or_output(self):
        self.assertEqual(self.run_deploy(), 0, self.output)
        self.assertNotIn(TOKEN, self.output + "\n".join(self.calls))

    def test_lock_symlink_cannot_truncate_target_or_touch_service(self):
        sentinel = self.root / "sentinel"
        sentinel.write_bytes(b"must survive deployment locking")
        private = self.root / "run/pokewalker-deploy"
        private.mkdir(mode=0o700)
        (private / "lock").symlink_to(sentinel)
        # Also cover the legacy world-writable lock location during upgrades.
        (self.root / "var/lock/pokewalker-deploy.lock").symlink_to(sentinel)
        status = self.run_deploy()
        self.assertEqual(sentinel.read_bytes(), b"must survive deployment locking")
        self.assertEqual(status, 10, self.output)
        self.assertFalse(self.named("systemctl"))
        self.assertFalse(self.named("build_release.sh"))

    def test_lock_rejects_untrusted_parent_private_directory_or_directory_symlink(self):
        for setting, value in (("run-stat", "1000 755"), ("run-stat", "0 777"),
                               ("lock-directory-stat", "1000:700"),
                               ("lock-directory-stat", "0:755")):
            with self.subTest(setting=setting, value=value):
                self.log.write_text("", encoding="utf-8")
                self.setting(setting, value)
                self.assertEqual(self.run_deploy(), 10, self.output)
                self.assertFalse(self.named("flock"))
                self.assertFalse(self.named("systemctl"))
                (self.fixture / setting).unlink()
        private = self.root / "run/pokewalker-deploy"
        private.rmdir()
        outside = self.root / "outside"
        outside.mkdir()
        private.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_deploy(), 10, self.output)
        self.assertFalse(list(outside.iterdir()))

    def test_existing_regular_lock_is_not_truncated(self):
        private = self.root / "run/pokewalker-deploy"
        private.mkdir(mode=0o700)
        lock = private / "lock"
        lock.write_bytes(b"existing lock bytes")
        self.assertEqual(self.run_deploy(), 0, self.output)
        self.assertEqual(lock.read_bytes(), b"existing lock bytes")

    def test_build_failure_invalid_sha_nonroot_or_locked_leave_service_untouched(self):
        for name, value, args in (("build-fail", "1", (NEW,)),
                                  ("uid", "123", (NEW,)),
                                  ("locked", "1", (NEW,)),
                                  ("unused", "1", ("main",))):
            with self.subTest(name=name):
                self.log.write_text("", encoding="utf-8")
                self.setting(name, value)
                self.assertEqual(self.run_deploy(*args), 10, self.output)
                self.assertFalse(self.named("systemctl"))
                (self.fixture / name).unlink()
                self.setting("uid", "0")
