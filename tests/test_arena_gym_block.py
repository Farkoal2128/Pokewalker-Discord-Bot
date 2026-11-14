"""AR-6a/b gym guards and private screens with real Arena rows."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from content.balance import load_table
from pokewalker.bot.walker import _Refused
from pokewalker.domain import battle as engine
from pokewalker.services import profiles
import test_gym_battle


class ArenaGymBlockTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_gym_battle.GymBattleTests.scalar
    profile = test_gym_battle.GymBattleTests.profile
    pokemon = test_gym_battle.GymBattleTests.pokemon
    rows = test_gym_battle.GymBattleTests.rows
    snapshot = test_gym_battle.GymBattleTests.snapshot
    create = test_gym_battle.GymBattleTests.create
    deploy = test_gym_battle.GymBattleTests.deploy
    gyms = test_gym_battle.GymBattleTests.gyms
    fight = test_gym_battle.GymBattleTests.fight
    click = test_gym_battle.GymBattleScreenTests.click
    preview = test_gym_battle.GymBattleScreenTests.preview
    ready = test_gym_battle.GymBattleScreenTests.ready
    component = staticmethod(test_gym_battle.GymBattleScreenTests.component)

    async def asyncSetUp(self):
        await test_gym_battle.GymBattleScreenTests.asyncSetUp(self)
        self.empty = await self.create('Empty')

    async def arena(self, *, uid='mon', pid=None):
        pid = pid or self.pid
        await self.conn.execute(
            'INSERT INTO arena_runs(run_id,profile_id,started_at,floor,slot,team,enemy) '
            'VALUES (?,?,?,1,0,?,?)',
            ('arena:' + pid, pid, self.now,
             json.dumps([{'uid': uid, 'family_id': 1, 'special': False, 'full_hp': 40,
                          'hp': 40, 'snapshot': {}}]),
             json.dumps({'snapshot': {}, 'battle_hp': 40, 'special': False})))

    async def companion(self):
        await self.conn.execute('UPDATE profiles SET companion_uid=? WHERE profile_id=?', ('mon', self.pid))

    async def deploy_picker(self):
        self.session['selection'] = json.dumps({'gym_id': self.empty['gym_id']})
        return await self.click('gym_deploy')

    def option(self, shown, action, uid='mon'):
        return next(option for option in self.component(shown, action).options if option.value == uid)

    async def refused_fight(self, **changes):
        before = await self.snapshot()
        with patch.object(engine, 'simulate', wraps=engine.simulate) as simulate:
            self.assertEqual(await self.fight(**changes), {'status': 'in_arena'})
            simulate.assert_not_called()
        self.assertEqual(await self.snapshot(), before)
        self.assertIsNone(await self.scalar('SELECT last_battle_at FROM profiles WHERE profile_id=?', (self.pid,)))
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_battles'), 0)

    async def test_companion_on_team_reports_in_arena_everywhere(self):
        await self.companion()
        await self.arena()
        self.assertEqual(await self.deploy(self.empty, now=self.now), {'status': 'in_arena'})
        await self.refused_fight(nominee_uid='mon')
        shown = await self.deploy_picker()
        self.assertIn('in the Arena', self.option(shown, 'gym_deploy_select').label)
        shown = await self.preview()
        self.assertIn('in the Arena', self.option(shown, 'gym_party_pick').label)

    async def test_companion_off_team_still_companion(self):
        await self.companion()
        await self.arena(uid='two')
        self.assertEqual(await self.deploy(self.empty, now=self.now), {'status': 'companion'})
        self.assertEqual(await self.fight(), {'status': 'invalid'})
        for shown, action in ((await self.deploy_picker(), 'gym_deploy_select'),
                              (await self.preview(), 'gym_party_pick')):
            label = self.option(shown, action).label
            self.assertIn('companion', label)
            self.assertNotIn('in the Arena', label)

    async def test_deploy_refuses_live_team_member_in_arena_nothing_written(self):
        await self.arena()
        before, changes = await self.snapshot(), self.conn.total_changes
        self.assertEqual(await self.deploy(self.empty, now=self.now), {'status': 'in_arena'})
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(self.conn.total_changes, changes)

    async def test_deploy_allowed_after_hour_18_without_opening_arena(self):
        await self.arena()
        arena_before = await self.rows('SELECT * FROM arena_runs')
        expiry = self.now + load_table('arena')['rules']['run_seconds']
        self.assertEqual((await self.deploy(self.empty, now=expiry))['status'], 'deployed')
        self.assertEqual(await self.rows('SELECT * FROM arena_runs'), arena_before)

    async def test_deploy_allowed_after_run_ended(self):
        await self.arena()
        await self.conn.execute('UPDATE arena_runs SET ended_at=?,end_reason=?', (self.now, 'loss'))
        self.assertEqual((await self.deploy(self.empty, now=self.now))['status'], 'deployed')

    async def test_other_profiles_run_does_not_block(self):
        await self.arena(pid=self.defender)
        self.assertEqual((await self.deploy(self.empty, now=self.now))['status'], 'deployed')
        self.assertEqual((await self.fight(party=[('two', 0)]))['status'], 'completed')

    async def test_battle_refuses_team_attacker_before_fight_no_cooldown_no_battle_row(self):
        await self.arena()
        await self.refused_fight()

    async def test_claim_with_team_member_refused_defender_stays_no_cooldown(self):
        await self.arena()
        await self.refused_fight(nominee_uid='mon')
        self.assertIsNone(await self.scalar('SELECT ended_at FROM gym_deployments WHERE deployment_id=?',
                                           (self.dep['deployment_id'],)))

    async def test_refused_battle_rolls_back_settle_payouts(self):
        owner = await self.profile('expired', 'g')
        await self.pokemon('expired', pid=owner)
        old_gym = await self.create('Expired')
        expired = (await self.deploy(old_gym, 'expired', now=0, session={
            **self.session, 'profile_id': owner, 'user_id': 'expired', 'session_id': 'expired'}))['deployment']
        await self.conn.execute('UPDATE gym_deployments SET ends_at=? WHERE deployment_id=?',
                                (self.now - 1, expired['deployment_id']))
        await self.arena()
        with patch.object(self.gyms(), 'settle', wraps=self.gyms().settle) as settle:
            await self.refused_fight()
            settle.assert_awaited_once()
        self.assertIsNone(await self.scalar('SELECT ended_at FROM gym_deployments WHERE deployment_id=?',
                                           (expired['deployment_id'],)))

    async def test_deploy_and_attacker_pickers_mark_team_members_in_the_arena(self):
        await self.arena()
        with patch.object(profiles, 'arena_team', wraps=profiles.arena_team) as team:
            shown = await self.deploy_picker()
            team.assert_awaited_once()
        self.assertIn('in the Arena', self.option(shown, 'gym_deploy_select').label)
        with self.assertRaises(_Refused):
            await self.click('gym_deploy_select', ['mon'])
        with patch.object(profiles, 'arena_team', wraps=profiles.arena_team) as team:
            shown = await self.preview()
            team.assert_awaited_once()
        self.assertIn('in the Arena', self.option(shown, 'gym_party_pick').label)
        with self.assertRaises(_Refused):
            await self.click('gym_party_pick', ['mon'])

    async def test_claim_select_omits_team_member(self):
        await self.ready()
        await self.arena()
        shown = await self.click('gym_party_sort')
        self.assertEqual([option.value for option in self.component(shown, 'gym_party_outcome').options], ['clear'])
        self.assertTrue(self.component(shown, 'gym_battle_start').disabled)

    async def test_start_with_team_member_keeps_party_screen_with_arena_notice(self):
        await self.ready()
        await self.arena()
        before = await self.snapshot()
        shown = await self.click('gym_battle_start')
        notice = 'That Pokémon is on your Arena team. Pick another attacker.'
        self.assertEqual(shown['embed'].title, 'Gym battle party')
        self.assertIn(notice, shown['embed'].description)
        self.assertEqual(json.loads(self.session['selection'])['phase'], 'gym_party')
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('UPDATE arena_runs SET ended_at=?,end_reason=?', (self.now, 'loss'))
        await self.ready()
        with patch.object(self.gyms(), 'battle', new=AsyncMock(return_value={'status': 'in_arena'})):
            shown = await self.click('gym_battle_start')
        self.assertEqual(shown['embed'].title, 'Gym battle party')
        self.assertIn(notice, shown['embed'].description)

    async def test_deploy_confirm_names_arena_reason(self):
        await self.deploy_picker()
        await self.click('gym_deploy_select', ['mon'])
        await self.arena()
        before = await self.snapshot()
        with self.assertRaisesRegex(_Refused, "This Pokémon is on your Arena team and can't defend a gym until the run ends\\."):
            await self.click('gym_deploy_confirm')
        self.assertEqual(await self.snapshot(), before)

    async def test_no_result_screen_says_already_hold_a_gym_for_arena_refusal(self):
        await self.ready()
        await self.click('gym_party_outcome', ['mon'])
        await self.arena()
        with patch.object(self.screens, 'render_result', wraps=self.screens.render_result) as render_result:
            shown = await self.click('gym_battle_start')
            render_result.assert_not_called()
        self.assertEqual(shown['embed'].title, 'Gym battle party')
        self.assertNotIn('already hold a gym', shown['embed'].description)
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_battles'), 0)


if __name__ == '__main__':
    unittest.main()
