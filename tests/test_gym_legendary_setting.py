"""D63 per-server Legendary/Mythical gym defender setting (owner decision 2026-11-12)."""

import unittest
from unittest.mock import patch

import test_gym_battle
import test_gyms
from pokewalker.domain import battle as engine


def legendary(content, key='is_legendary'):
    return next(item for item in content['identities'] if item[key])


class LegendaryDefenderServiceTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_gyms.GymTests.scalar
    profile = test_gyms.GymTests.profile
    pokemon = test_gyms.GymTests.pokemon
    rows = test_gyms.GymTests.rows
    snapshot = test_gyms.GymTests.snapshot
    create = test_gyms.GymTests.create
    deploy = test_gyms.GymTests.deploy
    gyms = test_gyms.GymTests.gyms
    admin = test_gyms.GymTests.admin
    admin_invoke = test_gyms.GymTests.admin_invoke

    async def asyncSetUp(self):
        await test_gyms.GymTests.asyncSetUp(self)

    async def allow(self, value):
        await self.conn.execute("UPDATE guilds SET gym_legendary_defenders=? WHERE guild_id='g'", (value,))

    async def test_legendary_and_mythical_defend_only_when_the_server_allows(self):
        gym = await self.create()
        for key in ('is_legendary', 'is_mythical'):
            with self.subTest(key=key):
                await self.conn.execute("UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid='mon'",
                                        (legendary(self.content, key)['pokemon_id'],))
                before = await self.snapshot()
                self.assertEqual((await self.deploy(gym))['status'], 'legendary_or_mythical')
                self.assertEqual(await self.snapshot(), before)
        await self.allow(1)
        self.assertEqual((await self.deploy(gym))['status'], 'deployed')

    async def test_admin_command_sets_audits_and_lists_the_setting(self):
        self.admin()
        self.assertIn('not allowed', await self.admin_invoke('list'))
        self.assertIn('now allowed', await self.admin_invoke('legendary', on='on', reason='  event week  '))
        self.assertEqual(await self.scalar("SELECT gym_legendary_defenders FROM guilds WHERE guild_id='g'"), 1)
        self.assertIn('Legendary/Mythical defenders: allowed', await self.admin_invoke('list'))
        self.assertIn('not allowed', await self.admin_invoke('legendary', on='off', reason='back to normal'))
        self.assertEqual(await self.scalar("SELECT gym_legendary_defenders FROM guilds WHERE guild_id='g'"), 0)
        audit = await self.rows('SELECT action,reason FROM mod_audit ORDER BY rowid')
        self.assertEqual(audit, [{'action': 'gym_legendary_on', 'reason': 'event week'},
                                 {'action': 'gym_legendary_off', 'reason': 'back to normal'}])
        before = await self.snapshot()
        self.assertIn('reason', (await self.admin_invoke('legendary', on='on', reason='  ')).lower())
        self.interaction.user.guild_permissions.manage_guild = False
        self.assertIn('Manage Server', await self.admin_invoke('legendary', on='on', reason='x'))
        self.assertEqual(await self.snapshot(), before)

    async def test_turning_it_off_keeps_a_legendary_defender_in_place(self):
        await self.allow(1)
        await self.conn.execute("UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid='mon'",
                                (legendary(self.content)['pokemon_id'],))
        dep = (await self.deploy(await self.create()))['deployment']
        await self.allow(0)
        self.assertIsNone((await self.rows('SELECT ended_at FROM gym_deployments WHERE deployment_id=?',
                                           (dep['deployment_id'],)))[0]['ended_at'])


class LegendaryNomineeTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_gym_battle.GymBattleTests.scalar
    profile = test_gym_battle.GymBattleTests.profile
    pokemon = test_gym_battle.GymBattleTests.pokemon
    rows = test_gym_battle.GymBattleTests.rows
    snapshot = test_gym_battle.GymBattleTests.snapshot
    create = test_gym_battle.GymBattleTests.create
    deploy = test_gym_battle.GymBattleTests.deploy
    gyms = test_gym_battle.GymBattleTests.gyms
    fight = test_gym_battle.GymBattleTests.fight
    refused = test_gym_battle.GymBattleTests.refused

    async def asyncSetUp(self):
        await test_gym_battle.GymBattleTests.asyncSetUp(self)
        await self.conn.execute("UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid='mon'",
                                (legendary(self.content)['pokemon_id'],))

    async def test_legendary_claims_a_won_gym_only_when_allowed(self):
        await self.refused('invalid', nominee_uid='mon')
        await self.conn.execute("UPDATE guilds SET gym_legendary_defenders=1 WHERE guild_id='g'")
        outcome = engine.Result('win', 'defender_fainted', 3, (0,), ('won',))
        with patch.object(engine, 'simulate', return_value=outcome):
            result = await self.fight(nominee_uid='mon')
        self.assertTrue(result['claimed'])


class LegendaryScreenTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_gym_battle.GymBattleScreenTests.scalar
    profile = test_gym_battle.GymBattleScreenTests.profile
    pokemon = test_gym_battle.GymBattleScreenTests.pokemon
    rows = test_gym_battle.GymBattleScreenTests.rows
    snapshot = test_gym_battle.GymBattleScreenTests.snapshot
    create = test_gym_battle.GymBattleScreenTests.create
    deploy = test_gym_battle.GymBattleScreenTests.deploy
    gyms = test_gym_battle.GymBattleScreenTests.gyms
    set_forms = test_gym_battle.GymBattleScreenTests.set_forms
    click = test_gym_battle.GymBattleScreenTests.click
    preview = test_gym_battle.GymBattleScreenTests.preview
    component = staticmethod(test_gym_battle.GymBattleScreenTests.component)

    async def asyncSetUp(self):
        await test_gym_battle.GymBattleScreenTests.asyncSetUp(self)
        await self.conn.execute("UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid='mon'",
                                (legendary(self.content)['pokemon_id'],))

    async def claim_labels(self):
        await self.preview()
        shown = await self.click('gym_party_pick', ['mon'])
        return [option.label for option in self.component(shown, 'gym_party_outcome').options]

    async def test_claim_option_for_a_legendary_attacker_follows_the_setting(self):
        self.assertEqual(await self.claim_labels(), ['Clear only'])
        await self.conn.execute("UPDATE guilds SET gym_legendary_defenders=1 WHERE guild_id='g'")
        self.assertEqual(await self.claim_labels(), ['Clear only', 'Claim with attacker'])

    async def test_deploy_picker_marks_legendary_only_while_not_allowed(self):
        other = await self.create('Empty')
        self.session['selection'] = '{"gym_id": "%s"}' % other['gym_id']
        shown = await self.click('gym_deploy')
        self.assertIn('disabled: Legendary / Mythical', shown['embed'].description)
        await self.conn.execute("UPDATE guilds SET gym_legendary_defenders=1 WHERE guild_id='g'")
        shown = await self.click('gym_deploy')
        self.assertNotIn('Legendary / Mythical', shown['embed'].description)
