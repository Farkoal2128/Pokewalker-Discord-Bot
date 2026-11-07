"""M5.2d static deployment contracts; only template sourcing invokes Bash."""

import ast
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / "deploy"
BASH = shutil.which("bash")


class UnitTests(unittest.TestCase):
    def text(self, name):
        path = DEPLOY / name
        self.assertTrue(path.is_file(), f"Missing deployment artifact: {name}")
        return path.read_text(encoding="utf-8")

    def unit(self, name="pokewalker-bot.service"):
        properties = {}
        for line in self.text(name).splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                properties.setdefault(key, []).append(value)
        return properties

    def env(self, name):
        values = {}
        for line in self.text(name).splitlines():
            self.assertRegex(line, r"^[A-Z][A-Z0-9_]*=[A-Za-z0-9_./:,<>-]*$|^[A-Z][A-Z0-9_]*='[^'\n]*'$")
            key, raw = line.split("=", 1)
            self.assertNotIn(key, values)
            words = shlex.split(raw)
            self.assertLessEqual(len(words), 1)
            values[key] = words[0] if words else ""
        return values

    def assert_shell_values(self, name, values):
        self.assertIsNotNone(BASH, "bash unavailable; env compatibility UNVERIFIED")
        path = (DEPLOY / name).resolve().as_posix()
        if len(path) > 1 and path[1] == ":":
            path = f"/{path[0].lower()}{path[2:]}"
        result = subprocess.run(
            [BASH, "--noprofile", "--norc", "-c", 'set -a; . "$1"; /usr/bin/env -0', "env-check", path],
            cwd=REPO, env={"PATH": os.environ.get("PATH", "")}, capture_output=True, check=True)
        sourced = dict(member.decode().split("=", 1) for member in result.stdout.split(b"\0") if member)
        self.assertEqual({key: sourced[key] for key in values}, values)

    def test_unit_restart_on_failure_no_75_success_timeout_30s_runtime_dir(self):
        unit = self.unit()
        for key, value in {"Restart": "on-failure", "TimeoutStopSec": "30s",
                           "RuntimeDirectory": "pokewalker", "RuntimeDirectoryMode": "0700",
                           "LogRateLimitIntervalSec": "30s", "LogRateLimitBurst": "500"}.items():
            self.assertEqual(unit[key], [value])
        self.assertNotIn("SuccessExitStatus", unit)
        self.assertNotIn("POKEWALKER_ALLOW_UNPATCHED_SQLITE", self.text("pokewalker-bot.service"))

    def test_unit_loads_token_and_heartbeat_credentials_execstart_runs_module(self):
        unit = self.unit()
        self.assertEqual(unit["LoadCredential"], [
            "discord_token:/etc/pokewalker/credentials/discord_token",
            "heartbeat_url:/etc/pokewalker/credentials/heartbeat_url"])
        self.assertEqual(unit["WorkingDirectory"], ["/opt/pokewalker/current"])
        self.assertEqual(unit["ExecStart"], ["/opt/pokewalker/current/.venv/bin/python -m pokewalker run"])
        for key, value in {"User": "pokewalker", "Group": "pokewalker", "ProtectSystem": "strict",
                           "ProtectHome": "yes", "NoNewPrivileges": "yes", "UMask": "0077"}.items():
            self.assertEqual(unit[key], [value])

    def test_runtime_env_keys_match_settings_and_are_plain_key_value(self):
        values = self.env("runtime.env.example")
        config = ast.parse((REPO / "pokewalker/config.py").read_text(encoding="utf-8"))
        keys = set()
        for node in ast.walk(config):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and ast.unparse(node.func.value) == "os.environ" and node.args):
                keys.add(ast.literal_eval(node.args[0]))
            if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                keys.add(ast.literal_eval(node.slice))
        self.assertEqual(set(values), keys - {"CREDENTIALS_DIRECTORY"})
        self.assertTrue({"CREDENTIALS_DIRECTORY", "RUNTIME_DIRECTORY", "STATE_DIRECTORY"}.isdisjoint(values))
        self.assertEqual(values["POKEWALKER_DB_PATH"], "/var/lib/pokewalker/walker.sqlite3")
        self.assertEqual(values["POKEWALKER_MARKER_LOG"], "/var/lib/pokewalker/walker.sqlite3.markers.jsonl")
        self.assertEqual(values["POKEWALKER_ALLOW_UNPATCHED_SQLITE"], "0")
        self.assertEqual(values["POKEWALKER_RELEASE"], "REPLACE_RELEASE_SHA")
        # Relative to the unit's WorkingDirectory, so preflight checks the candidate release.
        self.assertEqual(values["POKEWALKER_PRIVACY_PATH"], "docs/features/pokewalker-bot/privacy.md")
        self.assertEqual(values["POKEWALKER_CONTENT_PATH"], "content/artifact/content.json")
        self.assert_shell_values("runtime.env.example", values)

    def test_backup_env_sets_drive_use_trash_false_and_is_plain_key_value(self):
        values = self.env("backup.env.example")
        self.assertEqual(set(values), {"RESTIC_REPOSITORY", "RESTIC_PASSWORD_FILE",
                                      "RCLONE_DRIVE_USE_TRASH", "POKEWALKER_MARKER_LOG", "BACKUP_MONITOR_URL"})
        self.assertEqual(values["RCLONE_DRIVE_USE_TRASH"], "false")
        self.assertEqual(values["RESTIC_REPOSITORY"], "rclone:<remote>:<path>")
        self.assertEqual(values["POKEWALKER_MARKER_LOG"],
                         self.env("runtime.env.example")["POKEWALKER_MARKER_LOG"])
        self.assert_shell_values("backup.env.example", values)

    def test_bot_unit_paths_match_deploy_handoff(self):
        script = self.text("deploy.sh")
        config = re.search(r"^config=\$root([^\n]+)$", script, re.M).group(1)
        handoff = script.split("as_bot() {", 1)[1].split("\n}", 1)[0]
        unit = self.unit()
        for key in ("User", "EnvironmentFile", "RuntimeDirectory"):
            values = re.findall(r'-p "?' + key + r'=([^\s"\\]+)', handoff)
            self.assertEqual(unit[key], [value.replace("$config", config) for value in values])
        credentials = re.findall(r'-p "LoadCredential=([^"\n]+)"', handoff)
        self.assertEqual(unit["LoadCredential"], [value.replace("$config", config) for value in credentials])
        self.assertEqual(unit["StateDirectory"], ["pokewalker"])
        self.assertTrue({"CREDENTIALS_DIRECTORY", "RUNTIME_DIRECTORY", "STATE_DIRECTORY"}.isdisjoint(
            self.env("runtime.env.example")))
        base = re.search(r"^base=\$root([^\n]+)$", script, re.M).group(1)
        self.assertEqual(unit["WorkingDirectory"], [base + "/current"])

    def test_backup_unit_paths_match_deploy_handoff(self):
        script = self.text("deploy.sh")
        config = re.search(r"^config=\$root([^\n]+)$", script, re.M).group(1)
        state = re.search(r'STATE_DIRECTORY="\$root([^"\n]+)"', script).group(1)
        self.assertIn('. "$1/backup.env"', script)
        self.assertIn('backup "$config"', script)
        self.assertTrue({"CREDENTIALS_DIRECTORY", "RUNTIME_DIRECTORY", "STATE_DIRECTORY"}.isdisjoint(
            self.env("backup.env.example")))
        for name in ("pokewalker-backup.service", "pokewalker-backup-failed.service"):
            with self.subTest(unit=name):
                unit = self.unit(name)
                self.assertEqual(unit["EnvironmentFile"], [config + "/backup.env"])
                self.assertEqual(["/var/lib/" + value for value in unit["StateDirectory"]], [state])
                self.assertEqual(unit["UMask"], ["0077"])

    def test_rehearsal_doc_lists_required_cases(self):
        text = self.text("restore-rehearsal.md")
        for case in ("UNVERIFIED", "systemd 247", "pokewalker-deploy", "no login", "no access to /etc/pokewalker",
                     "first deploy", "empty marker log", "before P1", "re-enrolled as P2", "interrupted deletion",
                     "unique fixture string", "bytes", "occupied gym", "unpaid hours", "old battle controls",
                     "failing upload", "fail ping", "missed hour", "2-hour grace", "Drive Trash", "28 days",
                     "--restore-db", "20 seconds", "30 seconds", "Python >= 3.12", "SQLite >= 3.51.3",
                     "CREDENTIALS_DIRECTORY", "RUNTIME_DIRECTORY", "STATE_DIRECTORY", "systemd supplies"):
            with self.subTest(case=case):
                self.assertIn(case, text)
        self.assertIn('python3 -c "import sqlite3,sys;print(sys.version, sqlite3.sqlite_version)"', text)
        self.assertIn("docs/decisions/0001-application-stack.md", text)

    def test_no_secret_literals(self):
        runtime = self.env("runtime.env.example")
        self.assertEqual(runtime["DISCORD_TOKEN"], "")
        self.assertEqual(runtime["POKEWALKER_HEARTBEAT_URL"], "")
        self.assertEqual(self.env("backup.env.example")["BACKUP_MONITOR_URL"], "REPLACE_BACKUP_MONITOR_URL")
        for name in ("pokewalker-bot.service", "runtime.env.example", "backup.env.example", "restore-rehearsal.md"):
            text = self.text(name)
            self.assertNotRegex(text, r"https://(?:hc-ping\.com|discord(?:app)?\.com/api/webhooks)/")
            self.assertNotRegex(text, r"[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{25,}")


if __name__ == "__main__":
    unittest.main()
