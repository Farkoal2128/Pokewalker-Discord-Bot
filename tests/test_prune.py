"""D28 retention on disposable repository paths and a fake restic only."""

import datetime as dt
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from test_deploy_script import BASH, REPO, shell_path


NOW = 1_800_000_000
CUTOFF = NOW - 28 * 86_400
OLD_ID = "a" * 64
OTHER_ID = "b" * 64
SECRET = "synthetic-prune-secret-never-print"


def snapshot(identifier, epoch, path="/different/backup"):
    return {"id": identifier,
            "time": dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat(),
            "paths": [path]}


class SelectorTests(unittest.TestCase):
    def select(self, snapshots):
        script = REPO / "deploy/prune_select.py"
        self.assertTrue(script.is_file(), "required explicit-cutoff selector is absent")
        return subprocess.run([sys.executable, str(script), "--now", str(NOW), "--days", "28"],
                              input=json.dumps(snapshots), text=True, capture_output=True,
                              cwd=REPO, timeout=10)

    def test_select_uses_explicit_cutoff_not_latest_snapshot(self):
        result = self.select([snapshot(OLD_ID, CUTOFF - 86_400),
                              snapshot(OTHER_ID, CUTOFF - 1)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [OLD_ID, OTHER_ID])

    def test_select_boundary_exact_and_ignores_path_grouping(self):
        result = self.select([snapshot(OLD_ID, CUTOFF - 0.5, "/unique/old"),
                              snapshot(OTHER_ID, CUTOFF, "/unique/edge"),
                              snapshot("c" * 64, NOW, "/unique/current")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [OLD_ID])

    def test_invalid_snapshot_input_refuses_all_ids_without_echo(self):
        for bad in ({"id": "--" + SECRET, "time": "invalid"},
                    {"id": OTHER_ID, "time": "invalid-" + SECRET}):
            with self.subTest(bad=bad):
                result = self.select([snapshot(OLD_ID, CUTOFF - 1), bad])
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertNotIn(SECRET, result.stderr)

    def test_local_keeps_24_newest_and_every_unuploaded_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            pairs = []
            for index in range(27):
                epoch = NOW - (index + 1) * 3_600
                stem = f"snapshot-{index:08d}"
                names = [f"{stem}.sqlite3", f"{stem}.markers.jsonl"]
                if index != 25:
                    names.append(f"{stem}.uploaded")
                for name in names:
                    (root / name).write_bytes(b"synthetic")
                    os.utime(root / name, (epoch, epoch))
                pairs.append([root / name for name in names])
            result = subprocess.run([sys.executable, str(REPO / "deploy/prune_select.py"),
                                     "--now", str(NOW), "--days", "28", "--keep", "24",
                                     "--local", str(root)], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            selected = {Path(os.fsdecode(path)) for path in result.stdout.split(b"\0") if path}
            # Index 25 never uploaded, so only the uploaded pairs past the newest 24 expire.
            self.assertEqual(selected, set(pairs[24]) | set(pairs[26]))


@unittest.skipUnless(BASH, "bash unavailable; prune orchestration UNVERIFIED")
class PruneTests(unittest.TestCase):
    def setUp(self):
        cache = REPO / "build/test-prune"
        cache.mkdir(parents=True, exist_ok=True)
        self.assertTrue(cache.resolve().is_relative_to(REPO))
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.root = Path(self.temp.name).resolve()
        # Every recursive cleanup target must stay inside this disposable repo root.
        self.assertTrue(self.root.is_relative_to(cache.resolve()))
        self.addCleanup(self.temp.cleanup)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.backups = self.root / "backups with spaces"
        self.backups.mkdir()
        self.log = self.root / "calls"
        self.log.touch()
        self.snapshots = self.root / "snapshots.json"
        self.snapshots.write_text("[]", encoding="utf-8")
        root = shlex.quote(shell_path(self.root))
        self.shim("python3", f'exec {shlex.quote(shell_path(sys.executable))} "$@"\n')
        self.shim("date", f'printf "called\\n" >> {root}/clock-calls\nprintf "{NOW}\\n"\n')
        self.shim("rm", f'''root={root}
printf 'rm|%s\\n' "${{!#}}" >> "$root/calls"
[[ ! -e "$root/fail-local" ]] || {{ printf '%s\\n' "$RESTIC_PASSWORD" >&2; exit 1; }}
exec /usr/bin/rm "$@"
''')
        self.shim("restic", f'''root={root}
printf 'restic' >> "$root/calls"
printf '|%s' "$@" >> "$root/calls"
printf '\\n' >> "$root/calls"
[[ ! -e "$root/fail-$1" ]] || {{ printf '%s\\n' "$RESTIC_PASSWORD" >&2; exit 1; }}
[[ $1 != snapshots ]] || cat "$root/snapshots.json"
''')

    def shim(self, name, behavior):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + behavior, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def file(self, name, epoch):
        path = self.backups / name
        path.write_text("synthetic backup", encoding="utf-8")
        os.utime(path, (epoch, epoch))
        return path

    def stale(self):
        self.snapshots.write_text(json.dumps([snapshot(OLD_ID, CUTOFF - 1),
                                              snapshot(OTHER_ID, CUTOFF - 2)]),
                                  encoding="utf-8")

    def run_prune(self, backup_dir=None, cwd=None):
        script = REPO / "deploy/prune.sh"
        self.assertTrue(script.is_file(), "required local-first prune orchestrator is absent")
        environment = os.environ.copy()
        environment.update(PATH=f"{shell_path(self.bin)}:/usr/bin:/bin",
                           RESTIC_PASSWORD=SECRET, RESTIC_REPOSITORY=SECRET,
                           BACKUP_MONITOR_URL=SECRET)
        result = subprocess.run([BASH, "--noprofile", "--norc", shell_path(script),
                                 shell_path(self.backups) if backup_dir is None else backup_dir],
                                env=environment, cwd=REPO if cwd is None else cwd,
                                text=True, capture_output=True, timeout=10)
        self.calls = self.log.read_text(encoding="utf-8").splitlines()
        self.output = result.stdout + result.stderr
        return result.returncode

    def test_local_selection_by_explicit_cutoff_not_mtime_plus_28(self):
        stale = [self.file("snapshot.sqlite3", CUTOFF - 1),
                 self.file("marker copy.jsonl", CUTOFF - 0.5),
                 self.file("stale.partial", CUTOFF - 1)]
        edge = self.file("boundary.sqlite3", CUTOFF)
        recent = self.file("recent.partial", NOW)
        nested = self.backups / "directory"
        nested.mkdir()
        untouched = nested / "old.sqlite3"
        untouched.write_text("keep", encoding="utf-8")
        os.utime(untouched, (CUTOFF - 1, CUTOFF - 1))
        result = subprocess.run([sys.executable, str(REPO / "deploy/prune_select.py"),
                                 "--now", str(NOW), "--days", "28", "--local",
                                 str(self.backups)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = [Path(os.fsdecode(path)) for path in result.stdout.split(b"\0") if path]
        self.assertEqual(set(selected), set(stale))
        self.assertEqual(self.run_prune(), 0, self.output)
        self.assertTrue(all(not path.exists() for path in stale))
        self.assertTrue(all(path.exists() for path in (edge, recent, untouched)))

    def test_prune_keeps_only_24_newest_uploaded_snapshots(self):
        for index in range(25):
            for suffix in ("sqlite3", "uploaded"):
                self.file(f"snapshot-{index:08d}.{suffix}", NOW - index * 3_600)
        self.assertEqual(self.run_prune(), 0, self.output)
        self.assertEqual(len(list(self.backups.glob("*.sqlite3"))), 24)
        self.assertFalse((self.backups / "snapshot-00000024.sqlite3").exists())

    def test_forget_gets_exactly_the_listed_ids(self):
        self.stale()
        self.assertEqual(self.run_prune(), 0, self.output)
        self.assertEqual(self.calls, ["restic|snapshots|--json|--tag|pokewalker",
                                     f"restic|forget|{OLD_ID}|{OTHER_ID}", "restic|prune"])

    def test_no_stale_ids_skips_forget_still_runs_prune_exit_0(self):
        self.snapshots.write_text(json.dumps([snapshot(OLD_ID, CUTOFF)]), encoding="utf-8")
        self.assertEqual(self.run_prune(), 0, self.output)
        self.assertEqual(self.calls, ["restic|snapshots|--json|--tag|pokewalker", "restic|prune"])
        self.assertEqual((self.root / "clock-calls").read_text().splitlines(), ["called"])

    def empty_local_cwd(self):
        directory = self.root / "empty-local-cwd"
        directory.mkdir()
        self.assertTrue(directory.resolve().is_relative_to(self.root))
        sentinel = directory / "stale-sentinel"
        sentinel.write_bytes(b"must survive empty backup directory")
        os.utime(sentinel, (CUTOFF - 1, CUTOFF - 1))
        return directory, sentinel

    def test_empty_local_selector_rejects_before_resolving_cwd(self):
        cwd, sentinel = self.empty_local_cwd()
        result = subprocess.run([sys.executable, str(REPO / "deploy/prune_select.py"),
                                 "--now", str(NOW), "--days", "28", "--local", ""],
                                cwd=cwd, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(sentinel.read_bytes(), b"must survive empty backup directory")

    def test_empty_local_retains_cwd_bytes_and_still_prunes_remote(self):
        cwd, sentinel = self.empty_local_cwd()
        status = self.run_prune(backup_dir="", cwd=cwd)
        self.assertTrue(sentinel.exists(), "empty --local deleted the cwd sentinel")
        self.assertEqual(sentinel.read_bytes(), b"must survive empty backup directory")
        self.assertEqual(status, 1, self.output)
        self.assertEqual(self.output, "prune: local failed\n")
        self.assertEqual(self.calls, ["restic|snapshots|--json|--tag|pokewalker", "restic|prune"])

    def test_local_selection_never_follows_symlinks(self):
        sentinel = self.root / "sentinel.sqlite3"
        sentinel.write_text("keep outside backup directory", encoding="utf-8")
        os.utime(sentinel, (CUTOFF - 1, CUTOFF - 1))
        link = self.backups / "linked.sqlite3"
        link.symlink_to(sentinel)
        self.assertEqual(self.run_prune(), 0, self.output)
        self.assertTrue(link.is_symlink())
        self.assertEqual(sentinel.read_text(), "keep outside backup directory")

    def test_unreadable_local_directory_still_attempts_remote(self):
        self.backups.rmdir()
        self.stale()
        self.assertEqual(self.run_prune(), 1, self.output)
        self.assertEqual(self.output, "prune: local failed\n")
        self.assertIn(f"restic|forget|{OLD_ID}|{OTHER_ID}", self.calls)
        self.assertEqual(self.calls[-1], "restic|prune")

    def test_invalid_remote_listing_skips_forget_still_prunes(self):
        self.snapshots.write_text(json.dumps([snapshot(OLD_ID, CUTOFF - 1),
                                              {"id": "--" + SECRET}]), encoding="utf-8")
        self.assertEqual(self.run_prune(), 1, self.output)
        self.assertEqual(self.output, "prune: forget failed\n")
        self.assertEqual(self.calls, ["restic|snapshots|--json|--tag|pokewalker", "restic|prune"])

    def test_forget_ok_prune_fails_exit_1_then_rerun_without_stale_ids_prunes_exit_0(self):
        self.stale()
        (self.root / "fail-prune").touch()
        self.assertEqual(self.run_prune(), 1, self.output)
        self.assertEqual(self.output, "prune: prune failed\n")
        self.assertIn(f"restic|forget|{OLD_ID}|{OTHER_ID}", self.calls)
        (self.root / "fail-prune").unlink()
        self.snapshots.write_text("[]", encoding="utf-8")
        self.log.write_text("", encoding="utf-8")
        self.assertEqual(self.run_prune(), 0, self.output)
        self.assertEqual(self.calls[-1], "restic|prune")
        self.assertFalse(any(call.startswith("restic|forget") for call in self.calls))

    def test_remote_failure_still_deletes_local_exit_1(self):
        for failure in ("snapshots", "forget"):
            with self.subTest(failure=failure):
                self.stale()
                stale = self.file("stale.partial", CUTOFF - 1)
                (self.root / f"fail-{failure}").touch()
                self.log.write_text("", encoding="utf-8")
                self.assertEqual(self.run_prune(), 1, self.output)
                self.assertFalse(stale.exists())
                self.assertTrue(self.calls[0].startswith("rm|"))
                self.assertEqual(self.calls[-1], "restic|prune")
                self.assertEqual(self.output, "prune: forget failed\n")
                (self.root / f"fail-{failure}").unlink()

    def test_local_failure_still_prunes_remote_exit_1(self):
        stale = self.file("stale.partial", CUTOFF - 1)
        self.stale()
        (self.root / "fail-local").touch()
        self.assertEqual(self.run_prune(), 1, self.output)
        self.assertTrue(stale.exists())
        self.assertEqual(self.calls[-1], "restic|prune")
        self.assertIn(f"restic|forget|{OLD_ID}|{OTHER_ID}", self.calls)
        self.assertEqual(self.output, "prune: local failed\n")

    def test_no_secret_literals_in_output(self):
        self.file("stale.partial", CUTOFF - 1)
        self.stale()
        for stage in ("local", "forget", "prune"):
            (self.root / f"fail-{stage}").touch()
        self.assertEqual(self.run_prune(), 1, self.output)
        self.assertEqual(self.output, "prune: local failed\nprune: forget failed\nprune: prune failed\n")
        self.assertNotIn(SECRET, self.output + "\n".join(self.calls))

    @unittest.skipIf(os.name == "nt", "Windows filenames cannot contain newlines")
    def test_local_filename_with_newline_is_one_literal_path(self):
        stale = self.file("snapshot\nodd.partial", CUTOFF - 1)
        self.assertEqual(self.run_prune(), 0, self.output)
        self.assertFalse(stale.exists())
