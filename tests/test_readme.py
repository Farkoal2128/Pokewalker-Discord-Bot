import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
import tempfile

from pokewalker.bot.client import WalkerBot
from pokewalker.config import Secret, Settings


class ReadmeTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = WalkerBot(Settings(Secret('synthetic'), owner_ids=frozenset({456})))
        self.addAsyncCleanup(self.bot.drain)

    def test_approved_text_verbatim(self):
        content = Path('content/help.md').read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(),
                         '7ceb3f822172536053eb15924f33cf3f681e7d1d04e22bcc07aa772ab3cbe15c')

    async def test_invalid_help_refuses_startup_before_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'help.md'
            for contents in (None, '', '   ', 'x' * 4097):
                if contents is not None:
                    path.write_text(contents, encoding='utf-8')
                with self.subTest(contents=contents and len(contents)), \
                     patch('pokewalker.bot.client.HELP_PATH', path), \
                     patch('pokewalker.bot.client.load_privacy', return_value='privacy'), \
                     patch('pokewalker.bot.client.open_db', AsyncMock()) as opening:
                    with self.assertRaisesRegex(ValueError, '(?i)help'):
                        await self.bot._setup()
                    opening.assert_not_awaited()
                if path.exists():
                    path.unlink()

    async def test_guild_command_is_private_public_to_all_and_in_manifest(self):
        command = self.bot.tree.get_command('readme')
        self.assertIsNotNone(command)
        self.assertTrue(command.guild_only)
        self.assertIn('readme', {c.name for c in self.bot.scope_commands(None)})
        manifest = self.bot.command_manifest_hash()
        self.bot.tree.remove_command('readme')
        self.assertNotEqual(manifest, self.bot.command_manifest_hash())
        self.bot.help_text = 'Approved help'
        self.bot.writer = SimpleNamespace(run=AsyncMock(side_effect=AssertionError('must not read profile')))
        for user in (456, 999):
            interaction = SimpleNamespace(guild_id=123, user=SimpleNamespace(id=user),
                response=SimpleNamespace(send_message=AsyncMock()))
            await command.callback(interaction)
            args = interaction.response.send_message.await_args.kwargs
            self.assertTrue(args['ephemeral'])
            self.assertEqual(args['embed'].description, 'Approved help')
        self.bot.writer = None

    def test_limit_accepts_4096_characters(self):
        from pokewalker.bot.client import load_help
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'help.md'
            path.write_text('x' * 4096, encoding='utf-8')
            with patch('pokewalker.bot.client.HELP_PATH', path):
                self.assertEqual(load_help(), 'x' * 4096)

    def test_limit_counts_utf16_units_for_astral_characters(self):
        from pokewalker.bot.client import load_help
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'help.md'
            with patch('pokewalker.bot.client.HELP_PATH', path):
                valid = 'x' * 4094 + '\U0001f600'
                path.write_text(valid, encoding='utf-8')
                self.assertEqual(load_help(), valid)
                path.write_text('x' * 4095 + '\U0001f600', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, '4096'):
                    load_help()
