"""Arena server switch through local commands and real writer transactions."""

import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pokewalker import db
from pokewalker.bot.admin_channels import WalkerAdmin
import test_arena


class ArenaAdminTests(unittest.IsolatedAsyncioTestCase):
    profile = test_arena.ArenaTests.profile
    scalar = test_arena.ArenaTests.scalar
    rows = test_arena.ArenaTests.rows
    snapshot = test_arena.ArenaTests.snapshot
    service = test_arena.ArenaTests.service
    start = test_arena.ArenaTests.start
    state = test_arena.ArenaTests.state
    heal = test_arena.ArenaTests.heal
    order = test_arena.ArenaTests.order
    fight = test_arena.ArenaTests.fight
    outcome = test_arena.ArenaTests.outcome
    ticket = test_arena.ArenaTests.ticket
    redeem = test_arena.ArenaTests.redeem
    inventory = test_arena.ArenaTests.inventory

    async def asyncSetUp(self):
        await test_arena.ArenaTests.asyncSetUp(self)
        self.now = 1200
        self.bot = SimpleNamespace(writer=self.writer, walker=SimpleNamespace(clock=lambda: self.now))
        self.group = WalkerAdmin(self.bot)
        self.interaction = SimpleNamespace(
            guild_id='g', user=SimpleNamespace(id='moderator', guild_permissions=SimpleNamespace(manage_guild=True)),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=lambda: True),
            edit_original_response=AsyncMock())

    async def invoke(self, on='off', reason='  event maintenance  '):
        command = self.group.get_command('arena')
        self.assertIsNotNone(command, 'The direct Arena admin subcommand is absent')
        await command.callback(command.binding, self.interaction, on=on, reason=reason)
        self.interaction.response.defer.assert_awaited_with(ephemeral=True)
        self.interaction.response.send_message.assert_not_awaited()
        self.assertFalse(self.conn.in_transaction, 'Reply must follow commit or rollback')
        response = self.interaction.edit_original_response.await_args.kwargs
        self.assertEqual(response['allowed_mentions'].to_dict()['parse'], [])
        return response['content']

    async def test_arena_off_then_on_sets_flag_and_writes_audit_rows_with_reason(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('neighbor')")
        for value in ('off', 'on'):
            await self.invoke(value)
            self.assertEqual(await self.scalar("SELECT arena_enabled FROM guilds WHERE guild_id='g'"), value == 'on')
            self.assertEqual(await self.scalar("SELECT arena_enabled FROM guilds WHERE guild_id='neighbor'"), 1)
        self.assertEqual(await self.rows('SELECT guild_id,actor_id,target_kind,target_id,action,reason,created_at '
                                        'FROM mod_audit ORDER BY audit_id'), [
            {'guild_id': 'g', 'actor_id': 'moderator', 'target_kind': 'guild', 'target_id': 'g',
             'action': 'arena_' + value, 'reason': 'event maintenance', 'created_at': self.now}
            for value in ('off', 'on')])
        self.interaction.guild_id = 'new-server'
        await self.invoke()
        self.assertEqual(await self.scalar("SELECT arena_enabled FROM guilds WHERE guild_id='new-server'"), 0)

    async def test_arena_defaults_on_for_new_and_migrated_guilds(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('new')")
        self.assertEqual(await self.scalar("SELECT arena_enabled FROM guilds WHERE guild_id='new'"), 1)
        prior = Path(self.temp.name) / 'prior'
        prior.mkdir()
        for migration in db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'):
            if int(migration.name[:4]) <= 24:
                shutil.copyfile(migration, prior / migration.name)
        path = Path(self.temp.name) / 'old.sqlite3'
        with patch.object(db, 'MIGRATIONS', prior):
            old = await db.open_db(path)
        try:
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('existing')")
        finally:
            await old.close()
        upgraded = await db.open_db(path)
        try:
            self.assertEqual(await self.scalar("SELECT arena_enabled FROM guilds WHERE guild_id='existing'", conn=upgraded), 1)
            self.assertEqual(await upgraded.execute_fetchall('PRAGMA foreign_key_check'), [])
        finally:
            await upgraded.close()

    async def test_reason_required_changes_nothing(self):
        before = await self.snapshot()
        for value, reason, notice in [('off', ' \t ', 'A reason is required.'),
                                      ('invalid', 'maintenance', 'Choose on or off.')]:
            self.assertEqual(await self.invoke(value, reason), notice)
            self.assertEqual(await self.snapshot(), before)
            self.assertEqual(await self.rows('SELECT * FROM mod_audit'), [])

    async def test_manage_server_required_and_excluded_actor_refused(self):
        before = await self.snapshot()
        self.interaction.user.guild_permissions.manage_guild = False
        self.assertIn('Manage Server', await self.invoke())
        self.interaction.user.guild_permissions.manage_guild = True
        self.interaction.guild_id = None
        self.assertIn('in a server', await self.invoke())
        self.interaction.guild_id = 'g'
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','moderator',1)")
        before = await self.snapshot()
        self.assertIn('Excluded', await self.invoke())
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.rows('SELECT * FROM mod_audit'), [])

    async def test_reply_names_new_state(self):
        self.assertEqual(await self.invoke('off'), 'The Arena is now off in this server. '
                         'Runs already started can be finished, and tickets can still be redeemed.')
        self.assertEqual(await self.invoke('on'), 'The Arena is now on in this server.')

    async def test_off_blocks_new_runs_only_live_run_and_redeem_continue(self):
        run = (await self.start())['run']
        run['team'][0]['hp'] = 1
        await self.conn.execute('UPDATE arena_runs SET team=?', (json.dumps(run['team']),))
        await self.inventory('razz_berry', 20)
        await self.ticket('bronze')
        await self.invoke('off')
        other = {'session_id': 'other', 'profile_id': self.other, 'guild_id': 'g', 'user_id': 'v', 'revision': 0}
        await self.conn.execute('INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) '
                                "VALUES ('other','g','v',?,999999)", (self.other,))
        self.assertEqual(await self.start(session=other), {'status': 'off'})
        healed = await self.heal(run, [0])
        self.assertEqual(healed['status'], 'healed')
        ordered = await self.order(healed['run'], [2, 1, 0])
        self.assertEqual(ordered['status'], 'ordered')
        with patch.object(test_arena.battle_engine, 'simulate', return_value=self.outcome()):
            self.assertEqual((await self.fight(ordered['run']))['status'], 'won')
        self.assertEqual((await self.redeem())['status'], 'redeemed')
        self.assertIsNone((await self.state())['run']['ended_at'])
        self.assertEqual(await self.scalar('SELECT COUNT(*) FROM arena_runs'), 1)

    async def test_on_again_keeps_cooldown_best_floor_and_tickets(self):
        await self.start()
        await self.conn.execute("UPDATE arena_runs SET ended_at=1100,end_reason='loss'")
        await self.conn.execute('UPDATE profiles SET arena_best_floor=60 WHERE profile_id=?', (self.pid,))
        await self.ticket('gold', 5)
        before = await self.state(now=self.now)
        rows = {table: await self.rows(f'SELECT * FROM {table}') for table in ('profiles', 'arena_runs', 'arena_tickets')}
        await self.invoke('off')
        await self.invoke('on')
        self.assertEqual(await self.state(now=self.now), before)
        self.assertGreater(before['cooldown_left'], 0)
        for table, expected in rows.items():
            self.assertEqual(await self.rows(f'SELECT * FROM {table}'), expected)

    async def test_arena_subcommand_registered_in_client_manifest(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(SimpleNamespace())
        self.addAsyncCleanup(bot.close)
        with patch.object(bot.tree, 'sync', new=AsyncMock(side_effect=AssertionError('No Discord sync'))) as syncing:
            group = bot.tree.get_command('walker-admin')
            command = group.get_command('arena')
            self.assertIsNotNone(command, 'Arena must be a direct walker-admin subcommand')
            self.assertTrue(group.guild_only)
            self.assertEqual(group.default_permissions.value, 32)
            self.assertEqual({p.name for p in command.parameters if p.required}, {'on', 'reason'})
            on = next(p for p in command.parameters if p.name == 'on')
            self.assertEqual([(choice.name, choice.value) for choice in on.choices], [('on', 'on'), ('off', 'off')])
            manifest = bot.command_manifest_hash()
            group.remove_command('arena')
            self.assertNotEqual(bot.command_manifest_hash(), manifest)
            syncing.assert_not_awaited()

    async def test_actor_rechecked_inside_mutation(self):
        run = self.writer.run
        calls = 0

        async def queued(mutation, **kwargs):
            nonlocal calls
            calls += 1
            self.interaction.response.defer.assert_awaited_with(ephemeral=True)
            if calls == 2:
                await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','moderator',1)")
            return await run(mutation, **kwargs)

        with patch.object(self.writer, 'run', side_effect=queued):
            self.assertIn('Excluded', await self.invoke())
        self.assertEqual(calls, 2)
        self.assertEqual(await self.scalar("SELECT arena_enabled FROM guilds WHERE guild_id='g'"), 1)
        self.assertEqual(await self.rows('SELECT * FROM mod_audit'), [])

    async def test_audit_failure_rolls_back_setting(self):
        await self.conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON mod_audit "
                                "BEGIN SELECT RAISE(ABORT,'audit failed'); END")
        before = await self.snapshot()
        with self.assertRaisesRegex(Exception, 'audit failed'):
            await self.invoke()
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.rows('SELECT * FROM mod_audit'), [])
