"""M5.2c contracts on disposable paths; no live commands or HTTP requests."""

import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unittest

import test_deploy_script as deploy_tests
from test_deploy_script import BASH, REPO, OLD, NEW, shell_path


SECRET = "synthetic-backup-secret-never-log"
INVOCATION = "1" * 32
PREVIOUS_INVOCATION = "2" * 32


@unittest.skipUnless(BASH, "bash unavailable; backups UNVERIFIED")
class BackupTests(unittest.TestCase):
    def setUp(self):
        cache = REPO / "build/test-backup"
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(cache.resolve()))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.state = self.root / "var/lib/pokewalker-backup"
        self.state.mkdir(parents=True)
        self.log = self.root / "calls"
        self.log.touch()
        self.marker = self.root / "markers.jsonl"
        self.marker.write_text("synthetic marker\n", encoding="utf-8")
        self.database = self.root / "var/lib/pokewalker/walker.sqlite3"
        self.database.parent.mkdir(parents=True)
        self.database.write_bytes(b"original synthetic database")
        self.monitor_config = self.root / "monitor-config"
        self.body = self.root / "monitor-body"
        root = shlex.quote(shell_path(self.root))
        self.shim("sqlite3", f'''root={root}
printf 'sqlite3|%s\\n' "${{!#}}" >> "$root/calls"
if [[ ${{!#}} == .backup* ]]; then
    target=${{!#}}; target=${{target#*\\\"}}; target=${{target%\\\"}}
    printf 'verified snapshot' > "$target"
    [[ ! -e "$root/fail-snapshot" ]] || exit 1
elif [[ ${{!#}} == *integrity_check* ]]; then
    [[ ! -e "$root/fail-integrity" ]] && printf 'ok\\n' || printf 'corrupt\\n'
    [[ ! -e "$root/fail-integrity-exit" ]] || exit 1
elif [[ ${{!#}} == *foreign_key_check* ]]; then
    [[ ! -e "$root/fail-foreign" ]] || printf 'violation\\n'
fi
''')
        self.shim("restic", f'''root={root}
printf 'restic' >> "$root/calls"; printf '|%s' "$@" >> "$root/calls"; printf '\\n' >> "$root/calls"
printf 'trash|%s\\n' "$RCLONE_DRIVE_USE_TRASH" >> "$root/calls"
if [[ -e "$root/block-upload" && $1 == backup ]]; then
    touch "$root/upload-entered"
    while [[ ! -e "$root/release-upload" ]]; do /usr/bin/sleep 0.02; done
fi
[[ ! -e "$root/fail-$1" ]] || {{ printf '%s' "$RESTIC_PASSWORD"; printf '%s' "$RESTIC_PASSWORD" >&2; exit 1; }}
[[ $1 != snapshots ]] || printf '[]'
''')
        self.shim("prune.sh", f'''root={root}
printf 'prune|%s\\n' "$1" >> "$root/calls"
[[ ! -e "$root/fail-prune" ]]
''')
        self.shim("curl", f'''root={root}
printf 'curl' >> "$root/calls"; printf '|%s' "$@" >> "$root/calls"; printf '\\n' >> "$root/calls"
cat > "$root/monitor-config"
while [[ $# -gt 0 ]]; do
    if [[ $1 == --data ]]; then printf '%s' "$2" > "$root/monitor-body"; fi
    shift
done
[[ ! -e "$root/fail-monitor" ]] || {{ printf '%s' "$BACKUP_MONITOR_URL" >&2; exit 1; }}
''')
        self.shim("cp", f'''[[ ! -e {root}/fail-marker ]] || exit 1
exec /usr/bin/cp "$@"
''')
        self.shim("systemctl", f'''root={root}
[[ $* == 'show --property=InvocationID --value pokewalker-backup.service' ]] || exit 99
[[ ! -e "$root/fail-invocation-query" && -e "$root/current-invocation" ]] || exit 1
cat "$root/current-invocation"
''')
        # Git Bash has no flock; this fake implements command-mode ownership only.
        lock_script = self.root / "fake_flock.py"
        lock_script.write_text('''import os, subprocess, sys
f = open(sys.argv[1], "a+b")
if os.name == "nt":
    import msvcrt
    f.seek(0)
    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
else:
    import fcntl
    fcntl.flock(f, fcntl.LOCK_EX)
for key in ("STATE_DIRECTORY", "DEPLOY_ROOT", "POKEWALKER_MARKER_LOG"):
    value = os.environ.get(key, "").replace(chr(92), "/")
    if len(value) > 1 and value[1] == ":":
        value = "/" + value[0].lower() + value[2:]
    os.environ[key] = value
try:
    result = subprocess.run([sys.argv[2], *sys.argv[4:]])
finally:
    f.close()
raise SystemExit(result.returncode)
''', encoding="utf-8")
        self.shim("flock", f'exec {shlex.quote(shell_path(sys.executable))} '
                  f'{shlex.quote(shell_path(lock_script))} "$1" '
                  f'{shlex.quote(shell_path(BASH))} "${{@:2}}"\n')
        self.shim("python3", f'exec {shlex.quote(shell_path(sys.executable))} "$@"\n')

    def shim(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def environment(self):
        environment = os.environ.copy()
        # A test run under systemd inherits a real INVOCATION_ID; the cases set their own.
        environment.pop("INVOCATION_ID", None)
        environment.update(PATH=f"{shell_path(self.bin)}:/usr/bin:/bin",
                           STATE_DIRECTORY=shell_path(self.state), DEPLOY_ROOT=shell_path(self.root),
                           POKEWALKER_MARKER_LOG=shell_path(self.marker),
                           BACKUP_MONITOR_URL=f"https://synthetic.invalid/{SECRET}",
                           RESTIC_REPOSITORY=f"rclone:synthetic:{SECRET}", RESTIC_PASSWORD=SECRET,
                           RCLONE_DRIVE_USE_TRASH="false")
        return environment

    def command(self, name="backup.sh"):
        script = REPO / "deploy" / name
        self.assertTrue(script.is_file(), f"required {name} is absent")
        return [BASH, "--noprofile", "--norc", shell_path(script)]

    def run_backup(self, name="backup.sh", environment=None, args=()):
        result = subprocess.run([*self.command(name), *args], env=environment or self.environment(),
                                cwd=REPO, text=True, capture_output=True, timeout=15)
        self.calls = self.log.read_text().splitlines()
        return result

    def mark_failure(self, *stages):
        for stage in stages:
            (self.root / f"fail-{stage}").touch()

    def snapshot(self, result, status):
        self.assertEqual(result.returncode, status, result.stderr)
        paths = list((self.state / "artifacts").glob("*.sqlite3"))
        self.assertEqual(len(paths), 1)
        self.assertEqual(result.stdout, shell_path(paths[0]) + "\n")
        self.assertEqual(paths[0].read_bytes(), b"verified snapshot")
        self.assertFalse(list((self.state / "artifacts").glob("*.partial")))
        self.assertEqual(self.database.read_bytes(), b"original synthetic database")
        return paths[0]

    def no_snapshot(self, result):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse(list((self.state / "artifacts").iterdir()))
        self.assertFalse(any(call.startswith("restic|backup") for call in self.calls))

    def test_integrity_failure_deletes_partial_no_upload_exit_1(self):
        for stage in ("integrity", "integrity-exit", "foreign", "snapshot"):
            with self.subTest(stage=stage):
                self.mark_failure(stage)
                self.no_snapshot(self.run_backup())
                (self.root / f"fail-{stage}").unlink()

    def test_missing_or_uncopyable_marker_log_deletes_both_partials_exit_1(self):
        self.marker.unlink()
        self.no_snapshot(self.run_backup())
        self.marker.touch()
        self.mark_failure("marker")
        self.no_snapshot(self.run_backup())

    def test_fresh_install_empty_marker_log_copied_exit_0(self):
        self.marker.write_bytes(b"")
        self.snapshot(self.run_backup(), 0)
        markers = list((self.state / "artifacts").glob("*.markers.jsonl"))
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].read_bytes(), b"")
        uploads = [line for line in self.calls if line.startswith("restic|backup")]
        self.assertEqual(len(uploads), 1)
        self.assertIn("|--tag|pokewalker|", uploads[0])
        self.assertIn(shell_path(markers[0]), uploads[0])

    def test_runs_serialized_by_flock(self):
        (self.root / "block-upload").touch()
        first = subprocess.Popen(self.command(), env=self.environment(), cwd=REPO,
                                 text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        second = None
        try:
            deadline = time.monotonic() + 8
            while not (self.root / "upload-entered").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((self.root / "upload-entered").exists())
            second = subprocess.Popen(self.command(), env=self.environment(), cwd=REPO,
                                      text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(0.3)
            self.assertEqual(self.log.read_text().count("restic|backup"), 1)
            self.assertIsNone(second.poll())
            (self.root / "release-upload").touch()
            for child in (first, second):
                output, errors = child.communicate(timeout=12)
                self.assertEqual(child.returncode, 0, errors)
                self.assertEqual(len(output.splitlines()), 1)
            self.assertEqual(len(list((self.state / "artifacts").glob("*.sqlite3"))), 2)
        finally:
            (self.root / "release-upload").touch()
            for child in (first, second):
                if child is not None:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=12)

    def test_snapshot_and_prune_failure_exit_1_prune_attempted_both_logged(self):
        self.mark_failure("integrity", "prune")
        result = self.run_backup()
        self.no_snapshot(result)
        self.assertEqual(result.stderr, "backup: snapshot failed\nbackup: prune failed\n")
        self.assertEqual((self.state / "failed-stage").read_text(), "snapshot\n")
        self.assertIn("prune|" + shell_path(self.state / "artifacts"), self.calls)

    def test_only_successful_upload_marks_snapshot_uploaded(self):
        snapshot = self.snapshot(self.run_backup(), 0)
        self.assertTrue(snapshot.with_suffix(".uploaded").is_file())
        self.mark_failure("backup")
        result = self.run_backup()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(len(list((self.state / "artifacts").glob("*.sqlite3"))), 2)
        uploaded = {path.stem for path in (self.state / "artifacts").glob("*.uploaded")}
        self.assertEqual(uploaded, {snapshot.stem})

    def test_upload_and_prune_failure_exit_2(self):
        self.mark_failure("backup", "prune")
        result = self.run_backup()
        self.snapshot(result, 2)
        self.assertEqual(result.stderr, "backup: upload failed\nbackup: prune failed\n")
        self.assertEqual((self.state / "failed-stage").read_text(), "upload\n")

    def test_prune_failure_exit_3_no_success_ping(self):
        self.mark_failure("prune")
        result = self.run_backup()
        self.snapshot(result, 3)
        self.assertEqual(result.stderr, "backup: prune failed\n")
        self.assertEqual(self.body.read_text(), "prune")
        self.assertEqual(self.fail_pings(), ["prune"])
        self.assertFalse((self.state / "last-success").exists())

    def test_success_ping_only_after_all_stages_succeed(self):
        self.snapshot(self.run_backup(), 0)
        self.assertTrue((self.state / "last-success").read_text().strip().isdigit())
        self.assertFalse((self.state / "failed-stage").exists())
        self.assertTrue(self.calls[-1].startswith("curl|"))
        self.assertIn("|--max-time|10|", self.calls[-1])
        self.assertNotIn("--data", self.calls[-1])
        self.assertIn(SECRET, self.monitor_config.read_text())
        self.assertFalse(self.body.exists())
        self.assertIn("trash|false", self.calls)

    def test_alert_sends_stage_word_only(self):
        for stage in ("snapshot", "upload", "prune", "malicious " + SECRET, None):
            with self.subTest(stage=stage):
                metadata = self.state / "failed-stage"
                if stage is None:
                    metadata.unlink(missing_ok=True)
                else:
                    metadata.write_text(stage + "\n", encoding="utf-8", newline="\n")
                result = self.run_backup("backup_alert.sh")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout + result.stderr, "")
                self.assertEqual(self.body.read_text(), stage if stage in ("snapshot", "upload", "prune") else "unknown")
                self.assertIn(SECRET + '/fail"', self.monitor_config.read_text())
                self.assertNotIn(SECRET, result.stdout + result.stderr + "\n".join(self.calls))

    def test_missing_monitor_url_refuses_to_run(self):
        environment = self.environment()
        environment.pop("BACKUP_MONITOR_URL")
        for name in ("backup.sh", "backup_alert.sh"):
            result = self.run_backup(name, environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls, [])
        self.assertFalse((self.state / "artifacts").exists())

    def test_no_secret_literals(self):
        self.mark_failure("backup", "prune", "monitor")
        result = self.run_backup()
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(SECRET, result.stdout + result.stderr + "\n".join(self.calls))
        self.assertEqual(self.fail_pings(), ["upload"])

    def fail_pings(self):
        return [line.rsplit("|--data|", 1)[1] for line in self.log.read_text().splitlines()
                if line.startswith("curl|") and "|--data|" in line]

    def fallback(self):
        unit = (REPO / "deploy/pokewalker-backup-failed.service").read_text()
        start = next(line.split("=", 1)[1] for line in unit.splitlines() if line.startswith("ExecStart="))
        command = shlex.split(start)
        self.assertEqual(command, ["/opt/pokewalker/current/deploy/backup_alert.sh", "--fallback"])
        # Fake systemd provides the notifier unit's own, different invocation ID.
        environment = self.environment()
        environment["INVOCATION_ID"] = "3" * 32
        return self.run_backup("backup_alert.sh", environment, args=command[1:])

    def fake_systemd_finish(self, result):
        # Model only unit exit classification and OnFailure dispatch, not systemd.
        service = (REPO / "deploy/pokewalker-backup.service").read_text()
        accepted = {0}
        for line in service.splitlines():
            if line.startswith("SuccessExitStatus="):
                accepted.update(int(word) for word in line.split("=", 1)[1].split())
        if result.returncode not in accepted:
            self.assertIn("OnFailure=pokewalker-backup-failed.service", service)
            return self.fallback()
        return None

    def test_timer_failure_direct_alert_then_onfailure_sends_exactly_once(self):
        environment = self.environment()
        environment["INVOCATION_ID"] = INVOCATION
        (self.root / "current-invocation").write_text(INVOCATION, encoding="utf-8")
        self.mark_failure("prune")
        result = self.run_backup(environment=environment)
        self.snapshot(result, 3)
        self.assertEqual(self.fail_pings(), ["prune"])
        self.assertEqual((self.state / "notified-invocation").read_text().strip(), INVOCATION)
        self.assertEqual(self.fake_systemd_finish(result).returncode, 0)
        self.assertEqual(self.fail_pings(), ["prune"])
        (self.root / "fail-prune").unlink()
        environment["INVOCATION_ID"] = "4" * 32
        self.assertEqual(self.run_backup(environment=environment).returncode, 0)
        self.assertEqual(self.fail_pings(), ["prune"])
        self.assertNotIn("|--data|", self.calls[-1])

    def test_unexpected_exit_or_signal_onfailure_not_masked_by_previous_invocation(self):
        service = (REPO / "deploy/pokewalker-backup.service").read_text()
        self.assertNotIn("SuccessExitStatus=", service)
        for fake_systemd_exit in (1, -9):
            with self.subTest(fake_systemd_exit=fake_systemd_exit):
                self.log.write_text("")
                (self.state / "notified-invocation").write_text(PREVIOUS_INVOCATION, encoding="utf-8")
                (self.root / "current-invocation").write_text(INVOCATION, encoding="utf-8")
                if fake_systemd_exit == 1:
                    self.shim("flock", "exit 1\n")
                    result = self.run_backup()
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(self.fail_pings(), [])
                else:
                    # A synthetic signal result avoids killing any real process.
                    result = subprocess.CompletedProcess(["fake-systemd-signal"], -9)
                self.assertEqual(self.fake_systemd_finish(result).returncode, 0)
                self.assertEqual(self.fail_pings(), ["unknown"])

    def test_failed_direct_alert_preserves_exit_and_allows_onfailure_retry(self):
        environment = self.environment()
        environment["INVOCATION_ID"] = INVOCATION
        (self.root / "current-invocation").write_text(INVOCATION, encoding="utf-8")
        self.mark_failure("backup", "prune", "monitor")
        result = self.run_backup(environment=environment)
        self.snapshot(result, 2)
        self.assertEqual(self.fail_pings(), ["upload"])
        self.assertFalse((self.state / "notified-invocation").exists())
        (self.root / "fail-monitor").unlink()
        self.assertEqual(self.fallback().returncode, 0)
        self.assertEqual(self.fail_pings(), ["upload", "upload"])
        self.assertFalse((self.state / "notified-invocation").exists())

    def test_unavailable_invocation_property_does_not_suppress_fallback(self):
        (self.state / "notified-invocation").write_text(INVOCATION, encoding="utf-8")
        self.mark_failure("invocation-query")
        self.assertEqual(self.fallback().returncode, 0)
        self.assertEqual(self.fail_pings(), ["unknown"])

    def test_real_prune_never_deletes_lock_or_monitor_metadata(self):
        self.shim("prune.sh", f'exec bash {shlex.quote(shell_path(REPO / "deploy/prune.sh"))} "$@"\n')
        for name in ("lock", "last-success", "failed-stage", "notified-invocation"):
            path = self.state / name
            path.write_text("old metadata")
            os.utime(path, (1, 1))
        self.mark_failure("backup")
        result = self.run_backup()
        self.snapshot(result, 2)
        self.assertEqual((self.state / "lock").read_text(), "old metadata")
        self.assertEqual((self.state / "last-success").read_text(), "old metadata")
        self.assertEqual((self.state / "notified-invocation").read_text(), "old metadata")
        self.assertEqual((self.state / "failed-stage").read_text(), "upload\n")
        self.assertIn("restic|prune", self.calls)

    def test_monitor_failure_is_redacted_and_does_not_claim_http_delivery(self):
        self.mark_failure("monitor")
        result = self.run_backup()
        self.snapshot(result, 0)
        self.assertNotIn(SECRET, result.stdout + result.stderr + "\n".join(self.calls))


class BackupUnitsTests(unittest.TestCase):
    def test_units_hourly_persistent_umask_onfailure(self):
        service = (REPO / "deploy/pokewalker-backup.service").read_text()
        for expected in ("Type=oneshot", "UMask=0077", "EnvironmentFile=/etc/pokewalker/backup.env",
                         "StateDirectory=pokewalker-backup", "OnFailure=pokewalker-backup-failed.service",
                         "Environment=PATH=/opt/pokewalker/current/deploy:",
                         "ExecStart=/opt/pokewalker/current/deploy/backup.sh"):
            self.assertIn(expected, service)
        timer = (REPO / "deploy/pokewalker-backup.timer").read_text()
        for expected in ("OnCalendar=hourly", "Persistent=true", "RandomizedDelaySec=", "WantedBy=timers.target"):
            self.assertIn(expected, timer)
        alert = (REPO / "deploy/pokewalker-backup-failed.service").read_text()
        for expected in ("EnvironmentFile=/etc/pokewalker/backup.env", "StateDirectory=pokewalker-backup",
                         "ExecStart=/opt/pokewalker/current/deploy/backup_alert.sh", "UMask=0077"):
            self.assertIn(expected, alert)


@unittest.skipUnless(BASH, "bash unavailable; backup/deploy integration UNVERIFIED")
class BackupDeployIntegrationTests(unittest.TestCase):
    def host(self):
        host = deploy_tests.DeployScriptTests()
        host.setUp()
        self.addCleanup(host.doCleanups)
        backup = BackupTests()
        backup.setUp()
        self.addCleanup(backup.doCleanups)
        # Use the deployed interface, isolated host database and fake backup commands.
        for name in ("sqlite3", "restic", "prune.sh", "curl", "flock", "cp"):
            target = host.bin / name
            if name == "flock":
                body = f'[[ $1 != -n ]] || exit 0\nexec bash {shlex.quote(shell_path(backup.bin / name))} "$@"\n'
            else:
                body = f'exec bash {shlex.quote(shell_path(backup.bin / name))} "$@"\n'
            target.write_text("#!/bin/bash\n" + body, encoding="utf-8", newline="\n")
            target.chmod(0o755)  # Linux PATH lookup skips non-executable shims.
        (host.bin / "backup.sh").write_text(
            f'#!/bin/bash\nexec bash {shlex.quote(shell_path(REPO / "deploy/backup.sh"))}\n',
            encoding="utf-8", newline="\n")
        config = host.root / "etc/pokewalker/backup.env"
        config.write_text(config.read_text().replace("/synthetic/markers", shlex.quote(shell_path(backup.marker))),
                          encoding="utf-8", newline="\n")
        return host, backup

    def test_deploy_with_real_backup_snapshot_and_prune_failure_exit_40(self):
        host, backup = self.host()
        backup.mark_failure("integrity", "prune")
        self.assertEqual(host.run_deploy(NEW), 40, host.output)
        self.assertEqual(host.current.resolve().name, OLD)
        self.assertTrue(host.ready.exists())
        self.assertFalse(host.named("install"))
        self.assertIn("backup: snapshot failed", host.output)
        self.assertIn("backup: prune failed", host.output)

    def test_deploy_real_backup_upload_or_prune_warning_continues(self):
        for failure, status in (("backup", 2), ("prune", 3)):
            with self.subTest(failure=failure):
                host, backup = self.host()
                backup.mark_failure(failure)
                self.assertEqual(host.run_deploy(NEW), 0, host.output)
                self.assertEqual(host.current.resolve().name, NEW)
                self.assertIn(f"backup warning (status {status})", host.output)
                self.assertEqual(backup.fail_pings(), ["upload" if status == 2 else "prune"])
                self.assertEqual(len(list((host.root / "var/lib/pokewalker-backup/artifacts").glob("*.sqlite3"))), 1)

    def test_deploy_real_backup_recovery_prints_exact_verified_snapshot(self):
        host, backup = self.host()
        host.setting("ready", "0 1")
        # Preserve the M5.2a fake schema response; all SQLite work stays fake.
        prior = (host.bin / "sqlite3").read_text()
        (host.bin / "sqlite3").write_text(
            '#!/bin/bash\nif [[ ${!#} == "PRAGMA user_version;" ]]; then printf "2\\n"; exit; fi\n' + prior,
            encoding="utf-8", newline="\n")
        self.assertEqual(host.run_deploy(NEW), 50, host.output)
        snapshots = list((host.root / "var/lib/pokewalker-backup/artifacts").glob("*.sqlite3"))
        self.assertEqual(len(snapshots), 1)
        self.assertIn("snapshot: " + shell_path(snapshots[0]) + "\n", host.output)


if __name__ == "__main__":
    unittest.main()
