"""M7.8 moderation on real writer transactions, with private Discord I/O."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pokewalker.services import gyms
import test_mod


class GymModTests(unittest.IsolatedAsyncioTestCase):
    make_interaction = test_mod.ModTests.make_interaction
    invoke = test_mod.ModTests.invoke
    change = test_mod.ModTests.change
    rows = test_mod.ModTests.rows
    text = test_mod.ModTests.text
    enroll = test_mod.ModTests.enroll

    async def asyncSetUp(self):
        await test_mod.ModTests.asyncSetUp(self)
        self.bot.content = self.content
        self.now = 1000 + 2 * 3600 + 3599
        self.bot.walker.clock = lambda: self.now
        self.profile = await self.enroll()
        self.pid = self.profile['profile_id']
        await self.conn.execute(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,content_version,caught_at) "
            "VALUES ('defender',?,1,20,10,10,10,'male',0,'catch','fixture',0)", (self.pid,))
        self.gym = await self.writer.run(lambda conn: gyms.create(conn, '123', 'Park', 0))
        session = {'session_id': 's', 'profile_id': self.pid, 'guild_id': '123', 'user_id': '789'}
        result = await self.writer.run(lambda conn: gyms.deploy(
            conn, session, self.gym['gym_id'], 'defender', 0, 1000, self.content))
        self.assertEqual(result['status'], 'deployed')
        self.dep = result['deployment']

    async def recall(self, gym='Park', reason=' Test reason '):
        command = self.group.get_command('gym-recall')
        self.assertIsNotNone(command, 'M7.8 gym-recall command must exist')
        await self.invoke('gym-recall', gym=gym, reason=reason)

    async def test_gym_recall_pays_completed_hours_no_survivor_audits_holder(self):
        with patch.object(self.module.time, 'time', return_value=42):
            await self.recall()
        dep = (await self.rows('gym_deployments'))[0]
        self.assertEqual((dep['end_reason'], dep['paid_hours'], dep['survivor_rolled'], dep['ended_at']),
                         ('mod_recall', 2, 0, self.now))
        inbox = await self.rows('inbox_items')
        self.assertEqual({row['milestone_id'] for row in inbox},
                         {f"gym_income:{self.dep['deployment_id']}:{h}" for h in (1, 2)})
        self.assertTrue(all(row['profile_id'] == self.pid for row in inbox))
        mon = next(row for row in await self.rows('pokemon') if row['pokemon_uid'] == 'defender')
        self.assertIsNone(mon['gym_deployment_id'])
        audit = (await self.rows('mod_audit'))[0]
        self.assertEqual(tuple(audit[k] for k in ('guild_id', 'actor_id', 'target_kind', 'target_id',
                                                  'action', 'reason', 'created_at')),
                         ('123', '456', 'user', '789', 'gym_recall', 'Test reason', 42))
        self.assertIn('Park', self.text())
        self.assertIn('789', self.text())
        self.interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        self.assertEqual(self.interaction.edit_original_response.await_args.kwargs['allowed_mentions'].to_dict()['parse'], [])
        await self.recall()
        self.assertEqual(self.text(), 'Gym is empty')
        self.assertEqual(await self.rows('inbox_items'), inbox)
        self.assertEqual(len(await self.rows('mod_audit')), 1)

    async def test_gym_recall_unknown_or_empty_gym_refused_no_audit(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('999')")
        await self.writer.run(lambda conn: gyms.create(conn, '999', 'Secret', 0))
        await self.writer.run(lambda conn: gyms.create(conn, '123', 'Empty', 0))
        for name, expected in [('Missing', 'No such gym'), ('Secret', 'No such gym'), ('Empty', 'Gym is empty')]:
            with self.subTest(name=name):
                await self.recall(name)
                self.assertEqual(self.text(), expected)
                self.assertEqual(await self.rows('mod_audit'), [])
        self.assertIsNone((await self.rows('gym_deployments'))[0]['ended_at'])

    async def test_exclude_ends_deployment_forfeits_unpaid_hours_in_same_job(self):
        end = gyms.end_deployment
        async def observe(conn, *args):
            self.assertTrue(conn.in_transaction)
            self.assertEqual((await self.rows('restrictions'))[0]['excluded'], 1)
            return await end(conn, *args)
        with patch.object(gyms, 'end_deployment', side_effect=observe):
            await self.change('exclude')
        dep = (await self.rows('gym_deployments'))[0]
        self.assertEqual((dep['end_reason'], dep['paid_hours'], dep['survivor_rolled']), ('excluded', 0, 0))
        self.assertEqual(await self.rows('inbox_items'), [])
        self.assertIsNone(next(row for row in await self.rows('pokemon') if row['pokemon_uid'] == 'defender')['gym_deployment_id'])

    async def test_include_does_not_redeploy(self):
        await self.change('exclude')
        await self.change('include')
        dep = (await self.rows('gym_deployments'))[0]
        self.assertEqual(dep['end_reason'], 'excluded')
        self.assertIsNotNone(dep['ended_at'])
        self.assertEqual((await self.rows('restrictions'))[0]['excluded'], 0)
        self.assertIsNone(next(row for row in await self.rows('pokemon') if row['pokemon_uid'] == 'defender')['gym_deployment_id'])

    async def test_status_shows_held_gym_or_none(self):
        await self.invoke('status', member=self.member)
        utc = datetime.fromtimestamp(1000, timezone.utc).isoformat()
        self.assertIn(f'Holds gym: Park since {utc} (2 hours)', self.text())
        await self.writer.run(lambda conn: gyms.end_deployment(
            conn, '123', self.dep['deployment_id'], 'excluded', self.now, self.bot.walker.rng, self.content))
        await self.invoke('status', member=self.member)
        self.assertIn('Holds gym: none', self.text())
        self.member = SimpleNamespace(id=888, guild=SimpleNamespace(id=123))
        await self.invoke('status', member=self.member)
        self.assertIn('Holds gym: none', self.text())
        self.assertEqual(await self.rows('mod_audit'), [])

    async def test_excluded_moderator_refused_inside_transaction(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def block(conn):
            entered.set()
            await release.wait()
            await conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        blocker = asyncio.create_task(self.writer.run(block))
        await entered.wait()
        command = asyncio.create_task(self.recall())
        try:
            for _ in range(50):
                if self.interaction.response.defer.await_count:
                    break
                await asyncio.sleep(0)
            self.interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        finally:
            release.set()
            await asyncio.gather(blocker, command)
        self.assertIn('excluded', self.text())
        self.assertEqual(await self.rows('mod_audit'), [])
        self.assertIsNone((await self.rows('gym_deployments'))[0]['ended_at'])
        self.assertEqual(await self.rows('inbox_items'), [])

    async def test_gym_calls_use_walker_clock(self):
        self.bot.clock = lambda: 9999999
        settle, end = gyms.settle, gyms.end_deployment
        with patch.object(self.module.time, 'time', return_value=5), \
                patch.object(gyms, 'settle', wraps=settle) as observed_settle, \
                patch.object(gyms, 'end_deployment', wraps=end) as observed_end:
            await self.recall()
        self.assertEqual(observed_settle.await_args.args[1], self.now)
        self.assertEqual(observed_end.await_args.args[4], self.now)

    async def test_audit_renders_guild_target_as_server(self):
        await self.conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                                "VALUES ('123','456','guild','123','sharing','Test',0)")
        await self.invoke('log')
        self.assertIn('target=server:123', self.text())
        self.assertNotIn('user:123', self.text())

    async def test_whitespace_reason_refused(self):
        await self.recall(reason=' \t\n')
        self.assertIn('reason', self.text())
        self.assertEqual(await self.rows('mod_audit'), [])
        self.assertIsNone((await self.rows('gym_deployments'))[0]['ended_at'])

    async def test_recall_and_exclude_rollback_with_audit_failure(self):
        await self.conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON mod_audit "
                                "BEGIN SELECT RAISE(ABORT,'audit failed'); END")
        for action in ('recall', 'exclude'):
            with self.subTest(action=action):
                with self.assertRaisesRegex(Exception, 'audit failed'):
                    await (self.recall() if action == 'recall' else self.change('exclude'))
                self.assertIsNone((await self.rows('gym_deployments'))[0]['ended_at'])
                self.assertEqual(await self.rows('inbox_items'), [])
                self.assertEqual(await self.rows('restrictions'), [])
                self.assertIsNotNone(next(row for row in await self.rows('pokemon') if row['pokemon_uid'] == 'defender')['gym_deployment_id'])
                self.interaction.edit_original_response.assert_not_awaited()

    async def test_expired_holder_settles_before_status_or_recall(self):
        self.now = self.dep['ends_at']
        await self.invoke('status', member=self.member)
        self.assertIn('Holds gym: none', self.text())
        dep = (await self.rows('gym_deployments'))[0]
        self.assertEqual((dep['end_reason'], dep['paid_hours'], dep['survivor_rolled']), ('expired', 8, 1))
        inbox = await self.rows('inbox_items')
        await self.recall()
        self.assertEqual(self.text(), 'Gym is empty')
        self.assertEqual(await self.rows('inbox_items'), inbox)
        self.assertEqual(await self.rows('mod_audit'), [])

    async def test_expired_recall_commits_settlement_without_mod_audit(self):
        self.now = self.dep['ends_at']
        await self.recall()
        self.assertEqual(self.text(), 'Gym is empty')
        dep = (await self.rows('gym_deployments'))[0]
        self.assertEqual((dep['end_reason'], dep['paid_hours'], dep['survivor_rolled']), ('expired', 8, 1))
        self.assertEqual(await self.rows('mod_audit'), [])

    async def test_gym_moderation_scoped_to_guild_even_for_same_member(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('999')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('foreign','999','789',0)")
        await self.conn.execute(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,content_version,caught_at) "
            "VALUES ('foreignmon','foreign',1,20,10,10,10,'male',0,'catch','fixture',0)")
        foreign = await self.writer.run(lambda conn: gyms.create(conn, '999', 'Park', 0))
        session = {'session_id': 'foreign', 'profile_id': 'foreign', 'guild_id': '999', 'user_id': '789'}
        deployed = await self.writer.run(lambda conn: gyms.deploy(
            conn, session, foreign['gym_id'], 'foreignmon', 0, 1000, self.content))
        before = deployed['deployment']
        await self.recall()
        self.assertEqual(next(row for row in await self.rows('gym_deployments')
                              if row['guild_id'] == '999'), before)
        await self.change('exclude')
        self.assertEqual(next(row for row in await self.rows('gym_deployments')
                              if row['guild_id'] == '999'), before)
        await self.invoke('status', member=self.member)
        self.assertIn('Holds gym: none', self.text())
        self.assertTrue(all(row['profile_id'] == self.pid for row in await self.rows('inbox_items')))

    async def test_recall_entry_permissions_and_guild_required(self):
        for mode in ('permission', 'dm'):
            self.interaction = self.make_interaction(guild=None if mode == 'dm' else 123)
            self.interaction.user.guild_permissions.moderate_members = mode != 'permission'
            await self.recall()
            self.assertIn('Moderate Members', self.text())
            self.assertIsNone((await self.rows('gym_deployments'))[0]['ended_at'])
        self.assertEqual(await self.rows('mod_audit'), [])
