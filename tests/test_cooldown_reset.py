"""D67 owner cooldown resets (owner request 2026-11-14): service on real SQLite and /admin commands."""

import importlib
import random
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import discord

from pokewalker.db import Writer, open_db
import test_admin
import test_admin_force_raid
import test_arena
import test_gym_feed

COLUMNS = {'checkin': 'last_checkin_at', 'gym_battle': 'last_battle_at',
           'trade': 'last_trade_at', 'trade_ping': 'last_trade_ping_at'}
PLAYER = ['checkin', 'gym_battle', 'gym_feed', 'arena_run', 'trade', 'trade_ping']


def service():
    return importlib.import_module('pokewalker.services.cooldowns')


async def reset(writer, guild_id, user_id, cooldown, now=5000.0, actor=456):
    return await writer.run(lambda conn: service().reset(conn, guild_id, user_id, cooldown, actor, now))


class CooldownResetServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await open_db(':memory:', allow_unpatched=True)
        self.addAsyncCleanup(self.conn.close)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123'),('999')")
        for pid, guild, user in (('a', '123', '1'), ('b', '123', '2'), ('c', '999', '1')):
            await self.conn.execute('INSERT INTO profiles(profile_id,guild_id,user_id,created_at,last_checkin_at,'
                                    'last_battle_at,last_trade_at,last_trade_ping_at) VALUES (?,?,?,0,10,20,30,40)',
                                    (pid, guild, user))
        await self.conn.commit()

    async def profile(self, pid):
        async with self.conn.execute('SELECT * FROM profiles WHERE profile_id=?', (pid,)) as cursor:
            return dict(await cursor.fetchone())

    async def test_user_reset_clears_only_the_chosen_cooldown_for_that_player(self):
        for kind, column in COLUMNS.items():
            with self.subTest(kind=kind):
                await self.conn.execute(f'UPDATE profiles SET {column}=99')
                result = await reset(self.writer, 123, 1, kind)
                self.assertEqual(result, {'status': 'reset', 'players': 1, 'cooldowns': [kind]})
                player = await self.profile('a')
                self.assertIsNone(player[column])
                self.assertEqual((await self.profile('b'))[column], 99)
                self.assertEqual((await self.profile('c'))[column], 99)
                self.assertTrue(all(player[other] is not None for other in set(COLUMNS.values()) - {column}))
                await self.conn.execute(f'UPDATE profiles SET {column}=1')

    async def test_all_for_user_resets_every_player_cooldown_but_not_force_raid(self):
        result = await reset(self.writer, '123', '1', 'all')
        self.assertEqual(result, {'status': 'reset', 'players': 1, 'cooldowns': PLAYER})
        profile = await self.profile('a')
        self.assertTrue(all(profile[column] is None for column in COLUMNS.values()))
        self.assertEqual(profile['arena_cooldown_reset_at'], 5000.0)
        async with self.conn.execute("SELECT force_raid_reset_at FROM guilds WHERE guild_id='123'") as cursor:
            self.assertIsNone((await cursor.fetchone())[0])

    async def test_server_reset_covers_every_player_in_that_server_only(self):
        result = await reset(self.writer, '123', None, 'all')
        self.assertEqual(result, {'status': 'reset', 'players': 2, 'cooldowns': [*PLAYER, 'force_raid']})
        for pid in ('a', 'b'):
            self.assertIsNone((await self.profile(pid))['last_battle_at'])
        self.assertEqual((await self.profile('c'))['last_battle_at'], 20)
        async with self.conn.execute('SELECT guild_id,force_raid_reset_at FROM guilds ORDER BY 1') as cursor:
            self.assertEqual([tuple(row) for row in await cursor.fetchall()], [('123', 5000.0), ('999', None)])

    async def test_each_reset_is_audited_in_the_target_server(self):
        await reset(self.writer, '123', '1', 'trade')
        await reset(self.writer, '999', None, 'force_raid', now=6000.0)
        async with self.conn.execute('SELECT guild_id,actor_id,target_kind,target_id,action,reason,created_at '
                                     'FROM mod_audit ORDER BY audit_id') as cursor:
            self.assertEqual([tuple(row) for row in await cursor.fetchall()], [
                ('123', '456', 'user', '1', 'cooldown_reset', 'trade', 5000.0),
                ('999', '456', 'guild', '999', 'cooldown_reset', 'force_raid', 6000.0)])

    async def test_unknown_server_and_missing_player_write_nothing(self):
        before = [await self.profile(pid) for pid in 'abc']
        self.assertEqual(await reset(self.writer, '555', None, 'all'), {'status': 'unknown_server'})
        self.assertEqual(await reset(self.writer, '123', '3', 'all'), {'status': 'no_profile'})
        self.assertEqual([await self.profile(pid) for pid in 'abc'], before)
        async with self.conn.execute('SELECT count(*) FROM mod_audit') as cursor:
            self.assertEqual((await cursor.fetchone())[0], 0)

    async def test_rejects_unknown_choices_and_force_raid_for_one_player(self):
        for user, kind in (('1', 'force_raid'), ('1', 'bogus'), (None, 'bogus')):
            with self.subTest(kind=kind, user=user), self.assertRaises(ValueError):
                await reset(self.writer, '123', user, kind)

    async def test_requires_writer_transaction(self):
        with self.assertRaises(RuntimeError):
            await service().reset(self.conn, '123', '1', 'all', 456, 5000.0)


class FeedResetTests(unittest.IsolatedAsyncioTestCase):
    _base = test_gym_feed.GymFeedTests
    scalar, profile, pokemon, rows = _base.scalar, _base.profile, _base.pokemon, _base.rows
    snapshot, create, deploy, gyms = _base.snapshot, _base.create, _base.deploy, _base.gyms
    berries, feed, stored, asyncSetUp = _base.berries, _base.feed, _base.stored, _base.asyncSetUp

    async def test_feeding_reset_lets_the_holder_feed_again_now(self):
        self.assertEqual((await self.feed(7 * 3600))['status'], 'fed')
        self.assertEqual((await self.feed(7 * 3600 + 5))['status'], 'cooldown')
        await reset(self.writer, self.session['guild_id'], self.session['user_id'], 'gym_feed')
        self.assertIsNone((await self.stored())['last_fed_at'])
        self.assertEqual((await self.feed(7 * 3600 + 10))['status'], 'fed')


class ArenaResetTests(unittest.IsolatedAsyncioTestCase):
    _base = test_arena.ArenaTests
    profile, scalar, service, rows = _base.profile, _base.scalar, _base.service, _base.rows
    snapshot, state, start, asyncSetUp = _base.snapshot, _base.state, _base.start, _base.asyncSetUp

    async def test_reset_after_run_start_clears_arena_cooldown(self):
        await self.start()
        await self.conn.execute("UPDATE arena_runs SET ended_at=2000,end_reason='loss'")
        self.assertGreater((await self.state(now=2000))['cooldown_left'], 0)
        await reset(self.writer, 'g', 'u', 'arena_run', now=2100.0)
        self.assertEqual((await self.state(now=2200))['cooldown_left'], 0)
        result = await self.start(now=2200, session={**self.session, '_original_revision': 6})
        self.assertEqual(result['status'], 'started')
        self.assertGreater((await self.state(now=2300))['cooldown_left'], 0)

    async def test_reset_before_run_start_does_not_carry_over(self):
        await reset(self.writer, 'g', 'u', 'arena_run', now=900.0)
        await self.start()
        await self.conn.execute("UPDATE arena_runs SET ended_at=2000,end_reason='loss'")
        self.assertEqual((await self.state(now=2000))['cooldown_left'], 63800)


class ForceRaidResetTests(unittest.IsolatedAsyncioTestCase):
    rows = test_admin_force_raid.ForceRaidTests.rows
    reply = test_admin_force_raid.ForceRaidTests.reply
    permissions = test_admin_force_raid.ForceRaidTests.permissions
    command = test_admin_force_raid.ForceRaidTests.command
    invoke = test_admin_force_raid.ForceRaidTests.invoke
    asyncSetUp = test_admin_force_raid.ForceRaidTests.asyncSetUp

    async def test_server_reset_clears_force_raid_cooldown(self):
        start = test_admin_force_raid.START
        self.assertTrue((await self.invoke()).startswith('Spawned '))
        self.now = start + 4000
        self.assertIn('on cooldown', await self.invoke())
        await reset(self.writer, '123', None, 'force_raid', now=start + 4100)
        self.now = start + 4200
        self.assertTrue((await self.invoke()).startswith('Spawned '))
        self.now = start + 8000
        self.assertIn('on cooldown', await self.invoke())


class CooldownCommandTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_admin.AdminTests.asyncSetUp
    interaction = test_admin.AdminTests.interaction

    async def run_command(self, name, interaction=None, **options):
        interaction = interaction or self.interaction()
        command = self.group.get_command(name)
        self.assertIsNotNone(command, f'/admin {name} must exist')
        choice = options.pop('cooldown', 'all')
        await command.callback(command.binding, interaction, **options,
                               cooldown=discord.app_commands.Choice(name=choice, value=choice))
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        reply = interaction.edit_original_response.await_args.kwargs
        self.assertEqual(reply['allowed_mentions'].to_dict().get('parse'), [])
        self.assertLessEqual(len(reply['content']), 2000)
        return reply['content']

    async def seed(self):
        await self.bot.db.execute("INSERT INTO guilds(guild_id) VALUES ('777')")
        await self.bot.db.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,last_battle_at) "
                                  "VALUES ('p','777','42',0,10)")
        await self.bot.db.commit()

    async def battle_at(self):
        async with self.bot.db.execute("SELECT last_battle_at FROM profiles WHERE profile_id='p'") as cursor:
            return (await cursor.fetchone())[0]

    def choices(self, name):
        parameter = next(p for p in self.group.get_command(name).parameters if p.name == 'cooldown')
        return [choice.value for choice in parameter.choices]

    async def test_commands_exist_only_in_admin_guild_with_cooldown_choices(self):
        self.assertIsNone(self.bot.tree.get_command('admin'))
        self.assertEqual(self.choices('cooldown-user'), ['all', *PLAYER])
        self.assertEqual(self.choices('cooldown-server'), ['all', *PLAYER, 'force_raid'])
        user = {p.name: p.required for p in self.group.get_command('cooldown-user').parameters}
        self.assertEqual(user, {'server_id': True, 'user_id': True, 'cooldown': True})
        server = {p.name: p.required for p in self.group.get_command('cooldown-server').parameters}
        self.assertEqual(server, {'server_id': True, 'cooldown': True})

    async def test_user_reset_by_ids_replies_and_clears(self):
        await self.seed()
        text = await self.run_command('cooldown-user', server_id='777', user_id='42', cooldown='gym_battle')
        self.assertEqual(text, 'Reset Gym battle for user 42 in server 777.')
        self.assertIsNone(await self.battle_at())

    async def test_server_reset_names_the_server_when_known(self):
        await self.seed()
        self.bot.get_guild = Mock(return_value=SimpleNamespace(name='Walkers'))
        text = await self.run_command('cooldown-server', server_id='777')
        self.assertEqual(text, 'Reset all cooldowns for 1 player in Walkers (777).')
        self.assertIsNone(await self.battle_at())

    async def test_bad_ids_unknown_server_and_missing_player_change_nothing(self):
        await self.seed()
        for options, expected in (
                ({'server_id': 'abc', 'user_id': '42'}, 'Server and user IDs must be Discord IDs.'),
                ({'server_id': '777', 'user_id': '-4'}, 'Server and user IDs must be Discord IDs.'),
                ({'server_id': '555', 'user_id': '42'}, 'The bot has no data for server 555.'),
                ({'server_id': '777', 'user_id': '43'}, 'User 43 has no profile in server 777.')):
            with self.subTest(options=options):
                self.assertEqual(await self.run_command('cooldown-user', **options), expected)
        self.assertEqual(await self.battle_at(), 10)

    async def test_non_owner_or_other_guild_refused_and_nothing_written(self):
        await self.seed()
        for owner, guild in ((999, 123), (456, 777)):
            text = await self.run_command('cooldown-server', self.interaction(owner=owner, guild=guild),
                                          server_id='777')
            self.assertIn('owner', text.lower())
        self.assertEqual(await self.battle_at(), 10)


if __name__ == '__main__':
    unittest.main()
