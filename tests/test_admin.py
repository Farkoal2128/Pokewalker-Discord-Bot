"""M4.5a owner administration, real SQLite and synthetic Discord I/O."""

from datetime import datetime, timezone
import importlib
import logging
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

from pokewalker.bot.client import WalkerBot
from pokewalker.config import Secret, Settings
from pokewalker.db import Writer, open_db


class AdminTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.module = importlib.import_module('pokewalker.bot.admin')
        except ModuleNotFoundError:
            self.fail('M4.5a owner admin boundary absent')
        cache = Path('build/test-admin')
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings(Secret('synthetic-token'), Path(self.temp.name) / 'game.db',
                                 owner_ids=frozenset({456, 457}), admin_guild_id=123,
                                 release='test-release')
        self.bot = WalkerBot(self.settings, clock=lambda: 100)
        self.addAsyncCleanup(self.bot.drain)
        self.bot.db = await open_db(self.settings.db_path, allow_unpatched=True)
        self.bot.writer = Writer(self.bot.db)
        self.group = self.bot.tree.get_command('admin', guild=discord.Object(id=123))
        self.now = 1000.0
        self.time_patch = patch('pokewalker.bot.admin.time.time', side_effect=lambda: self.now)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)
        await self.bot.db.execute("INSERT INTO guilds(guild_id) VALUES ('123')")

    def interaction(self, *, owner=456, guild=123):
        return SimpleNamespace(guild_id=guild, user=SimpleNamespace(id=owner,
            guild_permissions=discord.Permissions.all()), response=SimpleNamespace(
            is_done=lambda: False, defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock())

    async def invoke(self, name, interaction=None):
        interaction = interaction or self.interaction()
        cmd = self.group.get_command(name)
        await cmd.callback(cmd.binding, interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        reply = interaction.edit_original_response.await_args
        self.assertIsNotNone(reply)
        self.assertLessEqual(len(reply.kwargs['content']), 2000)
        self.assertEqual(reply.kwargs['allowed_mentions'].to_dict().get('parse'), [])
        return reply.kwargs['content']

    async def test_non_owner_refused_on_every_subcommand_even_administrator(self):
        self.bot.restart = AsyncMock()
        for cmd in ('status', 'errors', 'restart'):
            for owner, guild in ((999, 123), (456, 999), (456, None)):
                text = await self.invoke(cmd, self.interaction(owner=owner, guild=guild))
                self.assertIn('owner', text.lower())
        self.bot.restart.assert_not_awaited()

    async def test_excluded_owner_refused_in_that_guild_incl_restart_confirm(self):
        await self.invoke('restart')
        await self.bot.db.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        self.bot.restart = AsyncMock()
        for cmd in ('status', 'errors', 'restart'):
            self.assertIn('excluded', (await self.invoke(cmd)).lower())
        self.bot.restart.assert_not_awaited()
        async with self.bot.db.execute('SELECT * FROM action_receipts') as cursor:
            self.assertEqual(await cursor.fetchall(), [])

    async def test_status_fields_and_no_secrets(self):
        self.bot.message_counts.update(received=9, credited=4)
        text = await self.invoke('status')
        for field in ('test-release', 'uptime', 'latency', 'ready', 'queue', 'closed',
                      'failure', 'guilds', 'received=9', 'credited=4', 'rejected=5',
                      self.bot.command_manifest_hash(123)[:12]):
            self.assertIn(field, text)
        for private in ('synthetic-token', str(self.settings.db_path), 'DISCORD_TOKEN'):
            self.assertNotIn(private, text)
        await self.bot.writer.close()
        self.bot.writer._failure = ValueError('synthetic-token')
        text = await self.invoke('status')
        self.assertIn('closed=True', text)
        self.assertIn('failure=True', text)
        self.assertNotIn('synthetic-token', text)

    async def test_owner_rate_limit_shared_window_boundary_and_no_action(self):
        clock = [100.0]
        self.bot.clock = lambda: clock[0]
        for name in ('status', 'errors', 'status', 'errors', 'status'):
            self.assertNotIn('slow down', (await self.invoke(name)).lower())
        self.assertIn('slow down, try again in 60 s', (await self.invoke('restart')).lower())
        self.assertIsNone(self.group.pending)
        for table in ('action_receipts', 'mod_audit'):
            async with self.bot.db.execute(f'SELECT count(*) FROM {table}') as cursor:
                self.assertEqual((await cursor.fetchone())[0], 0)
        clock[0] = 159.999
        self.assertIn('try again in 1 s', (await self.invoke('status')).lower())
        clock[0] = 160.0
        self.assertNotIn('slow down', (await self.invoke('status')).lower())

    async def test_owner_rate_limit_expires_only_requests_outside_rolling_window(self):
        clock = [100.0]
        self.bot.clock = lambda: clock[0]
        for at in (100, 110, 120, 130, 140):
            clock[0] = at
            await self.invoke('errors')
        clock[0] = 159.999
        self.assertIn('try again in 1 s', (await self.invoke('restart')).lower())
        clock[0] = 160
        self.assertNotIn('slow down', (await self.invoke('errors')).lower())
        self.assertIn('try again in 10 s', (await self.invoke('restart')).lower())
        self.assertIsNone(self.group.pending)

    async def test_owner_rate_limit_independent_owners_includes_restart_confirmation(self):
        for _ in range(5):
            await self.invoke('errors')
        other = lambda: self.interaction(owner=457)
        self.assertIn('confirm', (await self.invoke('restart', other())).lower())
        for _ in range(4):
            await self.invoke('errors', other())
        self.bot.restart = AsyncMock()
        self.assertIn('slow down', (await self.invoke('restart', other())).lower())
        self.bot.restart.assert_not_awaited()
        self.assertEqual(self.group.pending[0], 457)
        self.assertIn('slow down', (await self.invoke('status')).lower())

    async def test_status_uses_read_only_exclusion_with_real_closed_failed_writer(self):
        await self.bot.writer.close()
        self.bot.writer._failure = RuntimeError('synthetic-token /private/path')
        text = await self.invoke('status')
        self.assertIn('closed=True', text)
        self.assertIn('failure=True', text)
        self.assertIn('exclusion-read=ok', text)
        self.assertNotIn('synthetic-token', text)
        await self.bot.db.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        self.assertIn('excluded', (await self.invoke('status')).lower())
        for name in ('errors', 'restart'):
            with self.assertRaisesRegex(RuntimeError, 'closed'):
                await self.invoke(name)

    async def test_status_read_failure_still_owner_only_bounded_and_private(self):
        await self.bot.writer.close()
        with patch.object(self.module, 'open_reader', AsyncMock(
                side_effect=RuntimeError('synthetic-token /private/path')), create=True) as reader:
            for owner, guild in ((999, 123), (456, 999), (456, None)):
                self.assertIn('owner', (await self.invoke('status', self.interaction(owner=owner, guild=guild))).lower())
            reader.assert_not_awaited()
            text = await self.invoke('status')
        self.assertIn('exclusion-read=failed', text)
        for private in ('synthetic-token', '/private/path', 'RuntimeError'):
            self.assertNotIn(private, text)
        self.assertIsNone(self.group.pending)

    async def test_status_without_writer_reports_unavailable_health(self):
        await self.bot.writer.close()
        self.bot.writer = None
        text = await self.invoke('status')
        self.assertIn('closed=True', text)
        self.assertIn('queue=0', text)

    async def test_errors_bounded_ten_sanitized_no_text_no_token(self):
        self.group.attach_errors()
        self.group.attach_errors()
        for index in range(14):
            error = ValueError(f'synthetic-token /private/path message-{index}')
            record = logging.LogRecord('pokewalker.private.synthetic-token', logging.ERROR,
                '/private/path', 2, 'message text synthetic-token', (),
                (ValueError, error, None))
            self.group.error_handler.handle(record)
        self.assertEqual(len(self.group.error_handler.records), 10)
        for record in self.group.error_handler.records:
            self.assertEqual(set(record), {'time', 'logger', 'level', 'exception'})
        text = await self.invoke('errors')
        self.assertEqual(text.count('ValueError'), 10)
        for private in ('synthetic-token', '/private/path', 'message text'):
            self.assertNotIn(private, text)
        self.assertEqual(sum(h is self.group.error_handler for h in logging.getLogger().handlers), 1)
        await self.bot.drain()
        self.assertNotIn(self.group.error_handler, logging.getLogger().handlers)

    async def test_error_buffer_attached_at_setup_and_detached_at_drain(self):
        bot = WalkerBot(self.settings)
        self.addAsyncCleanup(bot.drain)
        with patch('pokewalker.bot.client.load_privacy', return_value='Synthetic privacy'), \
                patch('pokewalker.bot.client.replay_markers', AsyncMock()):
            await bot.setup_hook()
        self.assertIn(bot.admin.error_handler, logging.getLogger().handlers)
        logging.getLogger('pokewalker.bot.admin').error('Synthetic private text')
        self.assertEqual(bot.admin.error_handler.records[-1]['logger'], 'pokewalker')
        await bot.drain()
        self.assertNotIn(bot.admin.error_handler, logging.getLogger().handlers)

    async def test_restart_requires_second_call_within_60s_then_drains_and_exits_75(self):
        self.bot.admitting = True
        self.assertIn('confirm', (await self.invoke('restart')).lower())
        self.assertTrue(self.bot.admitting)
        interaction = self.interaction()
        with self.assertRaises(SystemExit) as stopped:
            await self.invoke('restart', interaction)
        self.assertEqual(stopped.exception.code, 75)
        self.assertIn('restarting', interaction.edit_original_response.await_args.kwargs['content'].lower())
        self.assertFalse(self.bot.admitting)
        self.assertTrue(self.bot.writer._task.done())
        self.assertTrue(self.bot.is_closed())

    async def test_restart_confirm_expired_or_other_owner_refused(self):
        self.bot.restart = AsyncMock()
        await self.invoke('restart')
        self.assertIn('owner', (await self.invoke('restart', self.interaction(owner=457))).lower())
        self.now += 60
        self.assertIn('expired', (await self.invoke('restart')).lower())
        self.bot.restart.assert_not_awaited()

    async def test_restart_cooldown_survives_fresh_bot_instance(self):
        self.bot.restart = AsyncMock()
        await self.invoke('restart')
        await self.invoke('restart')
        async with self.bot.db.execute('SELECT action,profile_id,created_at FROM action_receipts') as cursor:
            row = await cursor.fetchone()
        self.assertEqual((row['action'], row['profile_id'], row['created_at']), ('restart', None, 1000))
        await self.bot.drain()
        self.bot = WalkerBot(self.settings)
        self.addAsyncCleanup(self.bot.drain)
        self.bot.db = await open_db(self.settings.db_path, allow_unpatched=True)
        self.bot.writer = Writer(self.bot.db)
        self.group = self.bot.tree.get_command('admin', guild=discord.Object(id=123))
        self.bot.restart = AsyncMock()
        self.now = 1299
        await self.invoke('restart')
        self.assertIn('cooldown', (await self.invoke('restart')).lower())
        self.bot.restart.assert_not_awaited()
        self.now = 1300
        await self.invoke('restart')
        await self.invoke('restart')
        self.bot.restart.assert_awaited_once()

    async def test_restart_rechecks_exclusion_after_entry_authorization(self):
        await self.invoke('restart')
        original = self.group.authorize
        async def authorize_then_exclude(interaction):
            allowed = await original(interaction)
            await self.bot.db.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
            return allowed
        self.bot.restart = AsyncMock()
        with patch.object(self.group, 'authorize', side_effect=authorize_then_exclude):
            self.assertIn('excluded', (await self.invoke('restart')).lower())
        self.bot.restart.assert_not_awaited()

    async def test_failed_receipt_commit_never_acknowledges_or_restarts(self):
        await self.invoke('restart')
        self.bot.restart = AsyncMock()
        interaction = self.interaction()
        with patch.object(self.bot.db, 'commit', AsyncMock(side_effect=RuntimeError('commit failed'))):
            with self.assertRaisesRegex(RuntimeError, 'commit failed'):
                await self.invoke('restart', interaction)
        self.bot.restart.assert_not_awaited()
        interaction.edit_original_response.assert_not_awaited()

    async def test_message_counts_credit_without_mint_reject_duplicate_and_ignore(self):
        from pokewalker.bot import messages
        from uuid import uuid4
        await self.bot.db.execute("INSERT INTO guild_channels VALUES ('123','789',1,1)")
        await self.bot.db.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES (?,'123','456',0)", (str(uuid4()),))
        self.bot.content = {}
        self.bot.reactions = SimpleNamespace(reconcile_reaction=AsyncMock())
        message = SimpleNamespace(id=100, guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=456, bot=False), webhook_id=None,
            channel=SimpleNamespace(id=789), content='alpha bravo charlie delta',
            created_at=datetime.fromtimestamp(10000, timezone.utc))
        await messages.on_message(self.bot, message)
        self.assertEqual(self.bot.message_counts, {'received': 1, 'credited': 1})
        await messages.on_message(self.bot, message)
        message.guild = None
        await messages.on_message(self.bot, message)
        self.assertEqual(self.bot.message_counts, {'received': 3, 'credited': 1})
        self.bot.reactions.reconcile_reaction.assert_not_awaited()

    async def test_admin_settings_env_defaults_and_validation(self):
        with patch.dict(os.environ, {'DISCORD_TOKEN': 'synthetic-token', 'POKEWALKER_OWNER_IDS': '456'}, clear=True):
            settings = Settings.from_env()
            self.assertIsNone(settings.admin_guild_id)
            self.assertEqual(settings.release, 'dev')
            with patch.dict(os.environ, {'POKEWALKER_ADMIN_GUILD_ID': '123', 'POKEWALKER_RELEASE': 'v1'}):
                settings = Settings.from_env()
                self.assertEqual((settings.admin_guild_id, settings.release), (123, 'v1'))
            with patch.dict(os.environ, {'POKEWALKER_ADMIN_GUILD_ID': 'invalid'}):
                with self.assertRaises(ValueError):
                    Settings.from_env()
