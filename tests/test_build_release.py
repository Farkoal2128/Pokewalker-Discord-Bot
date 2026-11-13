"""M5.2e: release builds run without deployment secrets or root privileges."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
SHA = "a" * 40


def shell_path(path):
    path = Path(path).resolve().as_posix()
    return f"/{path[0].lower()}{path[2:]}" if len(path) > 1 and path[1] == ":" else path


@unittest.skipUnless(BASH, "bash unavailable; deployment behavior UNVERIFIED")
class BuildReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=REPO / "build")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.releases = self.root / "opt/pokewalker/releases"
        self.releases.mkdir(parents=True)
        (self.root / "srv/pokewalker/src").mkdir(parents=True)
        self.source = self.root / "source"
        (self.source / "deploy").mkdir(parents=True)
        (self.source / "deploy/pokewalker-bot.service").write_text("unit\n", encoding="utf-8")
        (self.source / "requirements.lock").write_text("example==1.0 --hash=sha256:" + "0" * 64 + "\n",
                                                       encoding="utf-8")
        self.log = self.root / "calls.log"
        self.log.touch()
        self.install("id", 'printf "%s\\n" "${FAKE_UID:-1000}"')
        self.install("git", r'''
printf 'git|%s\n' "$*" >> "$CALL_LOG"
case "$1" in
  cat-file) [[ ${FAKE_UNKNOWN:-0} != 1 && $3 == "$EXPECTED_SHA^{commit}" ]] ;;
  archive) [[ $2 == --format=tar && $3 == "$EXPECTED_SHA" ]] || exit 1
            tar -cf - -C "$ARCHIVE_SOURCE" . ;;
  *) exit 1 ;;
esac
''')
        self.install("python3", r'''
printf 'python3|%s\n' "$*" >> "$CALL_LOG"
[[ $1 == -m && $2 == venv ]] || exit 1
mkdir -p "$3/bin"
cat > "$3/bin/pip" <<'PIP'
#!/bin/bash
printf 'pip|%s\n' "$*" >> "$CALL_LOG"
exit "${FAKE_PIP_STATUS:-0}"
PIP
chmod +x "$3/bin/pip"
''')
        self.install("chmod", 'printf "chmod|%s\\n" "$*" >> "$CALL_LOG"; exec /usr/bin/chmod "$@"')
        self.install("sync", 'printf "sync|%s\\n" "$*" >> "$CALL_LOG"; exit 0')
        self.env = os.environ.copy()
        self.env.update({
            "PATH": shell_path(self.bin) + ":" + os.environ["PATH"],
            "DEPLOY_ROOT": shell_path(self.root),
            "CALL_LOG": str(self.log),
            "ARCHIVE_SOURCE": shell_path(self.source),
            "EXPECTED_SHA": SHA,
            "FAKE_UID": "1000",
        })
        self.script = REPO / "deploy/build_release.sh"

    def install(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -e\n" + body + "\n", encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def run_build(self, sha=SHA, env=None, cwd=REPO):
        return subprocess.run([BASH, shell_path(self.script), sha], cwd=cwd,
                              env=self.env if env is None else env,
                              text=True, capture_output=True)

    def release(self):
        return self.releases / SHA

    def test_refuses_root_exit_1(self):
        env = self.env.copy()
        env["FAKE_UID"] = "0"
        result = self.run_build(env=env)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.release().exists())
        self.assertEqual(self.log.read_text(encoding="utf-8"), "")

    def test_refuses_when_credential_or_backup_variables_present(self):
        for key in ("CREDENTIALS_DIRECTORY", "DISCORD_TOKEN", "RESTIC_REPOSITORY",
                    "RESTIC_PASSWORD_FILE", "BACKUP_MONITOR_URL"):
            with self.subTest(key=key):
                env = self.env.copy()
                env[key] = "synthetic-value"
                self.log.write_text("", encoding="utf-8")
                result = self.run_build(env=env)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.release().exists())
                self.assertEqual(self.log.read_text(encoding="utf-8"), "")

    def test_builds_from_the_deploy_checkout_whatever_the_working_directory(self):
        # Review fix: root may start deploy.sh from / or its own clone; git must still see the checkout.
        git = self.bin / "git"
        git.write_text(git.read_text(encoding="utf-8").replace(
            "printf 'git|%s\\n'", '[[ $PWD == */srv/pokewalker/src ]] || exit 1\nprintf \'git|%s\\n\''),
            encoding="utf-8", newline="\n")
        self.assertEqual(self.run_build(cwd="/").returncode, 0)
        self.assertTrue((self.release() / ".complete").exists())

    def test_refuses_without_the_deploy_checkout(self):
        shutil.rmtree(self.root / "srv")
        self.assertEqual(self.run_build().returncode, 1)
        self.assertFalse(self.release().exists())

    def test_refuses_short_or_unknown_sha(self):
        self.assertEqual(self.run_build("a" * 39).returncode, 1)
        env = self.env.copy()
        env["FAKE_UNKNOWN"] = "1"
        self.assertEqual(self.run_build(env=env).returncode, 1)
        self.assertFalse(self.release().exists())

    def test_venv_created_at_final_path_marker_written_last(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.release() / ".complete").is_file())
        calls = self.log.read_text(encoding="utf-8").splitlines()
        self.assertIn(f"python3|-m venv {shell_path(self.release())}/.venv", calls)
        pip_call = "pip|install --require-hashes --no-input -r "
        pip_call += f"{shell_path(self.release())}/requirements.lock"
        self.assertIn(pip_call, calls)
        self.assertGreater(calls.index("sync|-f " + shell_path(self.release()) + "/.complete"),
                           calls.index(pip_call))
        self.assertEqual(calls[-1], "sync|-f " + shell_path(self.release()))

    def test_complete_release_reused_incomplete_one_deleted_and_rebuilt(self):
        release = self.release()
        release.mkdir()
        (release / ".complete").write_text("complete", encoding="utf-8")
        (release / "preserved").write_text("keep", encoding="utf-8")
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((release / "preserved").read_text(encoding="utf-8"), "keep")
        calls = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(calls, [f"git|cat-file -e {SHA}^{{commit}}"])
        (release / ".complete").unlink()
        self.log.write_text("", encoding="utf-8")
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((release / "preserved").exists())
        self.assertTrue((release / ".complete").is_file())

    def test_pip_installs_with_require_hashes_from_lockfile(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--require-hashes --no-input -r", self.log.read_text(encoding="utf-8"))

    def test_release_not_writable_by_bot_identity(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text(encoding="utf-8").splitlines()
        self.assertIn("chmod|-R u+rwX,go+rX,go-w -- " + shell_path(self.release()), calls)

    def test_never_touches_etc_var_lib_or_current_link(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in (self.root / "etc/pokewalker", self.root / "var/lib/pokewalker",
                     self.root / "opt/pokewalker/current"):
            self.assertFalse(path.exists(), path)
        self.assertTrue(self.release().exists())

    def test_no_secret_literals(self):
        source = self.script.read_text(encoding="utf-8")
        self.assertNotIn("synthetic-secret", source)
        self.assertNotIn("discord_token:", source)
        self.assertNotIn("heartbeat_url:", source)


if __name__ == "__main__":
    unittest.main()
