"""C5 configuration: synthetic credentials only, no network."""

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ConfigTests(unittest.TestCase):
    def setUp(self):
        try:
            self.config = importlib.import_module("pokewalker.config")
        except ModuleNotFoundError:
            self.fail("M1.2 config absent: safe credentials unavailable")
        self.env = patch.dict(os.environ, {"DISCORD_TOKEN": "synthetic-token",
                                          "POKEWALKER_OWNER_IDS": "123,456"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_token_from_credentials_dir(self):
        cache = Path("build/test-config")
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as directory:
            Path(directory, "discord_token").write_text(" synthetic-credential \n", encoding="utf-8")
            os.environ["CREDENTIALS_DIRECTORY"] = directory
            with self.assertNoLogs("pokewalker.config", "WARNING"):
                settings = self.config.Settings.from_env()
            self.assertEqual(settings.token.value, "synthetic-credential")

    def test_token_env_fallback_warns(self):
        with self.assertLogs("pokewalker.config", "WARNING") as logs:
            settings = self.config.Settings.from_env()
        self.assertEqual(settings.token.value, "synthetic-token")
        self.assertIn("DISCORD_TOKEN", " ".join(logs.output))
        self.assertNotIn("synthetic-token", " ".join(logs.output))

    def test_token_repr_is_masked(self):
        settings = self.config.Settings.from_env()
        self.assertEqual(str(settings.token), "***")
        self.assertEqual(repr(settings.token), "***")
        self.assertNotIn("synthetic-token", repr(settings))

    def test_settings_paths_owners_and_override(self):
        os.environ.update(POKEWALKER_DB_PATH="build/test.db",
                          POKEWALKER_CONTENT_PATH="custom/artifact/content.json",
                          POKEWALKER_ALLOW_UNPATCHED_SQLITE="1", POKEWALKER_DEV_GUILD_ID="789")
        settings = self.config.Settings.from_env()
        self.assertEqual(settings.db_path, Path("build/test.db"))
        self.assertEqual(settings.content_path, Path("custom/artifact/content.json"))
        self.assertEqual(settings.owner_ids, frozenset({123, 456}))
        self.assertEqual(settings.dev_guild_id, 789)
        self.assertTrue(settings.allow_unpatched_sqlite)

    def test_production_requires_owners_dev_may_have_none(self):
        os.environ.pop("POKEWALKER_OWNER_IDS")
        with self.assertRaisesRegex(ValueError, "owner"):
            self.config.Settings.from_env()
        os.environ["POKEWALKER_DEV_GUILD_ID"] = "789"
        self.assertEqual(self.config.Settings.from_env().owner_ids, frozenset())

    def test_invalid_ids_and_override_fail_closed(self):
        for key, value in [("POKEWALKER_OWNER_IDS", "0"), ("POKEWALKER_OWNER_IDS", "x"),
                           ("POKEWALKER_OWNER_IDS", "123,,456"),
                           ("POKEWALKER_DEV_GUILD_ID", "-1"),
                           ("POKEWALKER_ALLOW_UNPATCHED_SQLITE", "yes")]:
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                with self.assertRaises(ValueError):
                    self.config.Settings.from_env()

    def test_empty_credential_does_not_use_env_token(self):
        cache = Path("build/test-config")
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as directory:
            Path(directory, "discord_token").write_text(" \n", encoding="utf-8")
            os.environ["CREDENTIALS_DIRECTORY"] = directory
            with self.assertRaisesRegex(ValueError, "token"):
                self.config.Settings.from_env()

    def test_missing_token_refused(self):
        os.environ.pop("DISCORD_TOKEN")
        with self.assertRaisesRegex(ValueError, "token"):
            self.config.Settings.from_env()

    def test_url_repr_masked(self):
        os.environ['POKEWALKER_HEARTBEAT_URL'] = 'https://synthetic.invalid/private'
        settings = self.config.Settings.from_env()
        self.assertEqual(str(settings.heartbeat_url), '***')
        self.assertNotIn('private', repr(settings))

    def test_url_from_credentials_dir_env_fallback_warns(self):
        cache = Path('build/test-config')
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as directory:
            Path(directory, 'discord_token').write_text('synthetic', encoding='utf-8')
            path = Path(directory, 'heartbeat_url')
            path.write_text(' https://synthetic.invalid/credential \n', encoding='utf-8')
            os.environ.update(CREDENTIALS_DIRECTORY=directory,
                              POKEWALKER_HEARTBEAT_URL='https://synthetic.invalid/fallback')
            with self.assertNoLogs('pokewalker.config', 'WARNING'):
                self.assertEqual(self.config.Settings.from_env().heartbeat_url.value,
                                 'https://synthetic.invalid/credential')
            path.write_text(' \n', encoding='utf-8')
            self.assertIsNone(self.config.Settings.from_env().heartbeat_url)
            path.unlink()
            with self.assertLogs('pokewalker.config', 'WARNING') as logs:
                self.assertEqual(self.config.Settings.from_env().heartbeat_url.value,
                                 'https://synthetic.invalid/fallback')
            self.assertIn('POKEWALKER_HEARTBEAT_URL', ''.join(logs.output))
            self.assertNotIn('https://', ''.join(logs.output))
            del os.environ['POKEWALKER_HEARTBEAT_URL']
            self.assertIsNone(self.config.Settings.from_env().heartbeat_url)
