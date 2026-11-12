"""Private gym screens exercise real guild-scoped writer transactions."""

import importlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pokewalker.bot.walker import Walker, _Refused, REOPEN
import test_gyms
import test_walker_router


class GymScreenTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_gyms.GymTests.scalar
    profile = test_gyms.GymTests.profile
    pokemon = test_gyms.GymTests.pokemon
    rows = test_gyms.GymTests.rows
    snapshot = test_gyms.GymTests.snapshot
    create = test_gyms.GymTests.create
    deploy = test_gyms.GymTests.deploy
    gyms = test_gyms.GymTests.gyms

    async def asyncSetUp(self):
        await test_gyms.GymTests.asyncSetUp(self)
        try:
            self.screens = importlib.import_module('pokewalker.bot.gyms')
        except ModuleNotFoundError:
            self.fail('Private gym screen handlers are absent')
        self.now = 1000
        self.walker = Walker(SimpleNamespace(content=self.content), clock=lambda: self.now, rng=self.rng)
        self.session.update(revision=0, selection='{}')
        self.gym = await self.create()

    async def click(self, action, values=None):
        interaction = SimpleNamespace(data={'values': values or []})
        return await self.writer.run(lambda conn: self.walker.handlers[action](conn, self.session, interaction))

    def selected(self, **values):
        self.session['selection'] = json.dumps({'gym_id': self.gym['gym_id'], **values})

    async def view(self):
        self.selected()
        return await self.click('gym_view')

    async def preview(self, uid='mon'):
        await self.view()
        await self.click('gym_deploy')
        return await self.click('gym_deploy_select', [uid])

    @staticmethod
    def labels(rendered):
        return {item.label for item in rendered['view'].children if hasattr(item, 'label')}

    @staticmethod
    def select(rendered):
        return next(item for item in rendered['view'].children if hasattr(item, 'options'))

    async def test_home_button_opens_gym_list_through_router(self):
        self.bot = self.walker.bot
        self.bot.writer = self.writer
        interaction = test_walker_router.WalkerTests.interaction(self, user='u', guild='g')
        await self.walker.open(interaction)
        home = interaction.edit_original_response.await_args.kwargs
        button = next(item for item in home['view'].children if item.label == 'Gyms')
        self.assertFalse(button.disabled)
        interaction = test_walker_router.WalkerTests.interaction(self, user='u', guild='g')
        await self.walker.route(interaction, button.custom_id)
        shown = interaction.edit_original_response.await_args.kwargs
        self.assertEqual(shown['embed'].title, 'Gyms')
        self.assertIn('Park', shown['embed'].description)
        self.assertEqual(self.select(shown).options[0].value, self.gym['gym_id'])

    async def test_list_shows_empty_and_held_gyms_text_only(self):
        await self.create('Empty')
        await self.deploy(self.gym)
        self.now += 3600
        result = await self.click('gyms')
        text = result['embed'].description
        self.assertIn('Empty · empty', text)
        for fragment in ('Park · Holder <@u> · Defender CP ', 'held 1 h', 'battle HP ×1.9'):
            self.assertIn(fragment, text)
        self.assertFalse(result['embed'].image)
        self.assertEqual(len(self.select(result).options), 2)
        self.assertEqual((await self.click('gym_view', [self.gym['gym_id']]))['embed'].title, 'Park')

    async def test_view_embed_image_is_defender_sprite_text_complete_without_it(self):
        await self.deploy(self.gym)
        self.now += 7200
        result = await self.view()
        text = result['embed'].description
        for fragment in ('Bulbasaur', 'CP ', 'Grass / Poison', 'HP ', 'held 2 h', '×1.8', '6 h', 'Holder <@u>'):
            self.assertIn(fragment, text)
        self.assertTrue(result['embed'].image.url)
        with patch('pokewalker.bot.gyms.storage.identify', return_value=(self.content['identities'][0], None)):
            fallback = await self.view()
        self.assertFalse(fallback['embed'].image)
        self.assertEqual(fallback['embed'].description, text)

    async def test_view_buttons_by_state_empty_mine_other(self):
        self.assertEqual(self.labels(await self.view()), {'Deploy', 'Back'})
        await self.deploy(self.gym)
        self.assertEqual(self.labels(await self.view()), {'Recall', 'Rewards', 'Back'})
        pid = await self.profile('neighbor', 'g')
        self.session.update(profile_id=pid, user_id='neighbor')
        self.assertEqual(self.labels(await self.view()), {'Battle', 'Back'})
        self.assertIn('gym_battle', self.walker.handlers)

    async def test_deploy_picker_pages_and_marks_ineligible_refused_in_transaction(self):
        for i in range(12):
            await self.pokemon(f'a{i:02}')
        legendary = next(item for item in self.content['identities'] if item['is_legendary'])
        await self.conn.execute("UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid='a01'", (legendary['pokemon_id'],))
        await self.conn.execute("UPDATE profiles SET companion_uid='a00' WHERE profile_id=?", (self.pid,))
        occupied = await self.create('Occupied')
        await self.deploy(occupied, 'a02', session={**self.session, 'session_id': 'occupied'})
        await self.view()
        first = await self.click('gym_deploy')
        options = self.select(first).options
        self.assertEqual(len(options), 10)
        for option, reason in zip(options[:3], ('companion', 'Legendary', 'deployed')):
            self.assertIn(reason, option.label)
            before = await self.snapshot()
            with self.assertRaises(_Refused):
                await self.click('gym_deploy_select', [option.value])
            self.assertEqual(await self.snapshot(), before)
        with self.assertRaises(_Refused):
            await self.click('gym_deploy_select', ['mon'])
        page = await self.click('gym_deploy_next')
        self.assertEqual(len(self.select(page).options), 3)
        with self.assertRaises(_Refused):
            await self.click('gym_deploy_select', ['a03'])
        await self.click('gym_deploy_prev')
        await self.click('gym_deploy_select', ['a03'])
        before = await self.snapshot()
        with self.assertRaises(_Refused):
            await self.click('gym_deploy_confirm')
        self.assertEqual(await self.snapshot(), before)

    async def test_deploy_picker_labels_include_cp(self):
        await self.view()
        shown = await self.click('gym_deploy')
        option = self.select(shown).options[0]
        self.assertRegex(option.label, r'^Bulbasaur · CP \d+')
        self.assertIn(option.label, shown['embed'].description)

    async def test_deploy_select_at_most_25_options(self):
        for i in range(28):
            await self.pokemon(f'poke-{i:02}')
        await self.view()
        for action in ('gym_deploy', 'gym_deploy_next', 'gym_deploy_next'):
            options = self.select(await self.click(action)).options
            self.assertLessEqual(len(options), 25)
            self.assertLessEqual(len(options), 10)

    async def test_deploy_confirmation_exact_form_shiny_sprite_and_complete_text(self):
        identity = next(item for item in self.content['identities']
                        if item['kind'] != 'default' and item['sprites']['shiny']
                        and not item['is_legendary'] and not item['is_mythical'])
        await self.conn.execute("UPDATE pokemon SET pokemon_id=?,shiny=1 WHERE pokemon_uid='mon'", (identity['pokemon_id'],))
        result = await self.preview()
        self.assertEqual(result['embed'].image.url, identity['sprites']['shiny'])
        self.assertNotEqual(result['embed'].image.url, identity['sprites']['normal'])
        for fragment in (identity['name_en'], identity['kind'], 'male', 'Shiny', 'CP ', 'HP ',
                         ' / '.join(t.title() for t in identity['types']), self.gym['name']):
            self.assertIn(fragment, result['embed'].description)
        self.assertEqual(self.labels(result), {'Confirm', 'Back'})

    async def test_deploy_confirmation_missing_sprite_keeps_full_text_no_substitute(self):
        await self.conn.execute("UPDATE pokemon SET shiny=1 WHERE pokemon_uid='mon'")
        identity = next(item for item in self.content['identities'] if item['pokemon_id'] == 1)
        before = await self.preview()
        identity['sprites']['shiny'] = None
        self.assertIsNotNone(identity['sprites']['normal'])
        result = await self.preview()
        self.assertFalse(result['embed'].image)
        self.assertEqual(result['embed'].description, before['embed'].description)
        for fragment in (identity['name_en'], 'Shiny', 'CP ', 'HP ', self.gym['name']):
            self.assertIn(fragment, result['embed'].description)

    async def test_deploy_confirm_twice_one_deployment(self):
        await self.preview()
        with patch('pokewalker.bot.gyms.service.deploy', wraps=self.gyms().deploy) as deploying:
            await self.click('gym_deploy_confirm')
        self.assertIs(deploying.call_args.args[-1], self.walker.bot.content)
        before = await self.snapshot()
        with self.assertRaises(_Refused):
            await self.click('gym_deploy_confirm')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_deployments'), 1)

    async def test_router_deploy_recall_other_pokemon_same_revision_and_duplicate(self):
        await self.pokemon('second')
        self.walker.bot.writer = self.writer
        await self.conn.execute('INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) '
                                "VALUES ('abc','g','u',?,999999)", (self.pid,))

        async def route(action, values=None, revision=None):
            if revision is None:
                revision = await self.scalar("SELECT revision FROM sessions WHERE session_id='abc'")
            interaction = SimpleNamespace(
                user=SimpleNamespace(id='u'), guild_id='g', data={'values': values or []},
                response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()),
                edit_original_response=AsyncMock())
            await self.walker.route(interaction, f'pw:v1:abc:{revision}:{action}')
            return interaction

        await route('gym_view', [self.gym['gym_id']])
        for uid in ('mon', 'second'):
            await route('gym_deploy')
            await route('gym_deploy_select', [uid])
            revision = await self.scalar("SELECT revision FROM sessions WHERE session_id='abc'")
            confirmed = await route('gym_deploy_confirm')
            confirmed.followup.send.assert_not_awaited()
            self.assertIn('Holder <@u>', confirmed.edit_original_response.call_args.kwargs['embed'].description)
            active = await self.rows('SELECT * FROM gym_deployments WHERE ended_at IS NULL')
            self.assertEqual([row['pokemon_uid'] for row in active], [uid])
            self.assertEqual(await self.scalar('SELECT gym_deployment_id FROM pokemon WHERE pokemon_uid=?',
                                               (uid,)), active[0]['deployment_id'])
            before = await self.snapshot()
            duplicate = await route('gym_deploy_confirm', revision=revision)
            duplicate.followup.send.assert_not_awaited()
            duplicate.edit_original_response.assert_not_awaited()
            self.assertEqual(await self.snapshot(), before)
            if uid == 'mon':
                await route('gym_recall')
                await route('gym_recall_confirm')
                self.assertEqual(await self.rows('SELECT * FROM gym_deployments WHERE ended_at IS NULL'), [])
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_deployments'), 2)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts WHERE action='deploy'"), 2)

    async def test_deploy_confirmation_rechecks_revision_and_eligibility(self):
        for change in ('revision', 'companion', 'legendary'):
            await self.conn.execute("UPDATE profiles SET companion_uid=NULL WHERE profile_id=?", (self.pid,))
            await self.conn.execute("UPDATE pokemon SET pokemon_id=1 WHERE pokemon_uid='mon'")
            await self.preview()
            if change == 'revision':
                await self.conn.execute("UPDATE pokemon SET revision=revision+1 WHERE pokemon_uid='mon'")
            elif change == 'companion':
                await self.conn.execute("UPDATE profiles SET companion_uid='mon' WHERE profile_id=?", (self.pid,))
            else:
                identity = next(item for item in self.content['identities'] if item['is_legendary'])
                await self.conn.execute("UPDATE pokemon SET pokemon_id=? WHERE pokemon_uid='mon'", (identity['pokemon_id'],))
            before = await self.snapshot()
            with self.subTest(change=change), self.assertRaises(_Refused):
                await self.click('gym_deploy_confirm')
            self.assertEqual(await self.snapshot(), before)

    async def test_deploy_confirm_after_gym_removed_refused_no_deployment(self):
        await self.preview()
        await self.writer.run(lambda conn: self.gyms().retire(conn, 'g', self.gym['gym_id'], self.now, self.rng, self.content))
        before = await self.snapshot()
        with self.assertRaisesRegex(_Refused, 'This gym changed. Reopen it.'):
            await self.click('gym_deploy_confirm')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.scalar('SELECT count(*) FROM gym_deployments'), 0)

    async def test_recall_confirm_pays_hours_forfeits_survivor(self):
        dep = (await self.deploy(self.gym))['deployment']
        self.now += 7200
        await self.view()
        text = (await self.click('gym_recall'))['embed'].description
        self.assertIn('Income for full hours is paid; the survivor roll is forfeited', text)
        result = await self.click('gym_recall_confirm')
        self.assertIn('empty', result['embed'].description)
        row = (await self.rows('SELECT * FROM gym_deployments'))[0]
        self.assertEqual((row['end_reason'], row['paid_hours'], row['survivor_rolled']), ('recalled', 2, 0))
        self.assertEqual(await self.scalar("SELECT count(*) FROM inbox_items WHERE milestone_id LIKE 'gym_income:%'"), 2)
        self.assertEqual(await self.scalar("SELECT count(*) FROM inbox_items WHERE milestone_id LIKE 'survivor:%'"), 0)
        self.assertIsNone(await self.scalar("SELECT gym_deployment_id FROM pokemon WHERE pokemon_uid='mon'"))

    async def test_recall_confirm_after_gym_changed_hands_refused_nothing_changes(self):
        dep = (await self.deploy(self.gym))['deployment']
        await self.view()
        await self.click('gym_recall')
        await self.writer.run(lambda conn: self.gyms().end_deployment(conn, 'g', dep['deployment_id'], 'recalled', self.now, self.rng, self.content))
        pid = await self.profile('neighbor', 'g')
        await self.pokemon('neighbor', pid=pid)
        await self.deploy(self.gym, 'neighbor', session={**self.session, 'session_id': 'neighbor', 'profile_id': pid, 'user_id': 'neighbor'})
        self.now += 3600
        before = await self.snapshot()
        with self.assertRaisesRegex(_Refused, 'This gym changed. Reopen it.'):
            await self.click('gym_recall_confirm')
        self.assertEqual(await self.snapshot(), before)

    async def test_rewards_by_non_holder_refused(self):
        dep = (await self.deploy(self.gym))['deployment']
        pid = await self.profile('neighbor', 'g')
        self.session.update(profile_id=pid, user_id='neighbor')
        self.selected(deployment_id=dep['deployment_id'])
        self.now += 3600
        before = await self.snapshot()
        with self.assertRaisesRegex(_Refused, 'This gym changed. Reopen it.'):
            await self.click('gym_rewards')
        self.assertEqual(await self.snapshot(), before)

    async def test_rewards_adds_only_unpaid_hours_to_inbox_notice_counts_them(self):
        await self.deploy(self.gym)
        await self.view()
        self.now += 7200
        for count in (2, 0):
            result = await self.click('gym_rewards')
            self.assertIn(f'{count} hours of gym income added to your Inbox', result['embed'].description)
        self.now += 3600
        result = await self.click('gym_rewards')
        self.assertIn('1 hours of gym income added to your Inbox', result['embed'].description)
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 3)
        self.assertEqual(await self.scalar('SELECT count(*) FROM resource_ledger'), 0)

    async def test_view_runs_settle_so_expired_tenure_shows_empty_and_pays(self):
        await self.deploy(self.gym)
        self.now += 28800
        result = await self.view()
        self.assertEqual(self.labels(result), {'Deploy', 'Back'})
        self.assertEqual(await self.scalar('SELECT count(*) FROM inbox_items'), 10)
        self.assertEqual(await self.scalar('SELECT paid_hours FROM gym_deployments'), 8)
        self.assertEqual(await self.scalar('SELECT survivor_rolled FROM gym_deployments'), 1)

    async def test_foreign_guild_gym_id_view_deploy_recall_rewards_refused_nothing_changes(self):
        foreign = await self.create('Foreign', guild='h')
        # An overdue valid deployment must not settle as a side effect of a bad target.
        dep = (await self.deploy(self.gym))['deployment']
        self.now += 28800
        for action in ('gym_view', 'gym_deploy', 'gym_deploy_select', 'gym_deploy_confirm', 'gym_recall', 'gym_recall_confirm', 'gym_rewards'):
            messages = []
            for gym_id in (foreign['gym_id'], 'missing'):
                self.selected(deployment_id=dep['deployment_id'], phase='gym_deploy_confirm', pokemon_uid='mon', pokemon_revision=0)
                selection = json.loads(self.session['selection'])
                selection['gym_id'] = gym_id
                self.session['selection'] = json.dumps(selection)
                before = await self.snapshot()
                with self.assertRaises(_Refused) as caught, patch('pokewalker.bot.gyms.service.get_gym', wraps=self.gyms().get_gym) as getting:
                    await self.click(action, ['mon'] if action == 'gym_deploy_select' else None)
                messages.append(str(caught.exception))
                self.assertTrue(all(call.args[1] == 'g' for call in getting.call_args_list))
                self.assertEqual(await self.snapshot(), before)
            self.assertEqual(messages[0], messages[1])

    async def test_excluded_refused_paused_allowed(self):
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,excluded) VALUES ('g','u',1,0)")
        await self.preview()
        await self.click('gym_deploy_confirm')
        await self.conn.execute("UPDATE restrictions SET excluded=1 WHERE guild_id='g' AND user_id='u'")
        before = await self.snapshot()
        for action in ('gyms', 'gym_view', 'gym_deploy', 'gym_recall_confirm', 'gym_rewards'):
            with self.assertRaisesRegex(_Refused, 'excluded'):
                await self.click(action)
        self.assertEqual(await self.snapshot(), before)

    async def test_render_functions_do_no_io(self):
        captured = []
        async def capture(name, invoke):
            renderer = getattr(self.screens, name)
            def record(state):
                captured.append((renderer, state))
                return renderer(state)
            with patch.object(self.screens, name, side_effect=record):
                await invoke()
        await capture('render_list', lambda: self.click('gyms'))
        await capture('render_view', self.view)
        await capture('render_deploy', lambda: self.click('gym_deploy'))
        await capture('render_deploy', lambda: self.click('gym_deploy_select', ['mon']))
        await self.click('gym_deploy_confirm')
        await capture('render_view', self.view)
        await capture('render_recall', lambda: self.click('gym_recall'))
        with patch('builtins.open', side_effect=AssertionError('renderer I/O')), patch.object(self.conn, 'execute', side_effect=AssertionError('renderer SQL')):
            for renderer, state in captured:
                self.assertIsNotNone(renderer(state)['embed'])
