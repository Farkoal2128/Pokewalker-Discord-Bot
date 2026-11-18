"""C5 EXR-7: kind-specific catch wording and selected-raid Back on real SQLite."""

import json
import unittest
from unittest.mock import patch

from pokewalker.services import raids
import test_raids


class ExRaidScreenTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_raids.RaidWalkerTests.asyncSetUp
    interaction = test_raids.RaidWalkerTests.interaction
    rows = test_raids.RaidWalkerTests.rows
    open = test_raids.RaidWalkerTests.open
    click = test_raids.RaidWalkerTests.click
    enroll = test_raids.RaidWalkerTests.enroll
    ready = test_raids.RaidWalkerTests.ready
    current = test_raids.RaidWalkerTests.current
    encounter_row = test_raids.RaidWalkerTests.encounter_row

    async def both_raids(self, selected='ex', *, ordinary=True):
        self.walker.clock = lambda: 1000
        if not hasattr(self, 'session'):
            self.session = await self.ready()
        identity = next(i for i in self.bot.content['identities'] if i['species_id'] == 144)

        async def seed(conn):
            await conn.execute('DELETE FROM encounters')
            await conn.execute('DELETE FROM world_spawns')
            # Reseeded spawns must not replay receipts pointing to deleted encounters.
            await conn.execute("DELETE FROM action_receipts WHERE action='raid_join'")
            await conn.execute("DELETE FROM pokemon WHERE pokemon_uid LIKE 'fixture-owned-%'")
            await conn.execute('UPDATE profiles SET storage_limit=250')
            if ordinary:
                columns = ','.join(self.encounter)
                await conn.execute(f'INSERT INTO encounters({columns}) VALUES '
                                   f"({','.join('?' for _ in self.encounter)})", tuple(self.encounter.values()))
            for kind in ('world', 'ex'):
                await conn.execute(
                    'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,'
                    'spawned_at,expires_at,post_state,content_version,kind) '
                    "VALUES (?,'123','channel',?,?,900,1200,'sent','fixture',?)",
                    (kind, identity['pokemon_id'], identity['identity_id'], kind))
            self.ids = {}
            for kind in ('world', 'ex'):
                result = await raids.join(conn, 123, 456, kind, 1000, self.walker.rng, self.bot.content)
                self.assertEqual(result['status'], 'new')
                self.ids[kind] = result['encounter_id']
            await conn.execute('UPDATE encounters SET shiny=1 WHERE raid_spawn_id IS NOT NULL')
            for item in ('poke_ball', 'great_ball', 'master_ball', 'razz_berry'):
                await conn.execute('INSERT INTO inventory VALUES (?,?,5) '
                                   'ON CONFLICT(profile_id,item_id) DO UPDATE SET quantity=5',
                                   (self.session['profile_id'], item))
            selection = {'encounter_id': self.ids[selected], 'encounter_revision': 0,
                         'ball': 'great_ball', 'berry': 'razz_berry'}
            await conn.execute('UPDATE sessions SET selection=? WHERE session_id=?',
                               (json.dumps(selection), self.session['session_id']))
        await self.writer.run(seed)
        return await self.current(self.session)

    async def screen(self, session, action, values=None):
        interaction = await self.click(session, action, values)
        return interaction.edit_original_response.await_args.kwargs, await self.current(session)

    async def confirmation(self, session, kind):
        if kind == 'master':
            _, session = await self.screen(session, 'pick_ball', ['master_ball'])
        if kind == 'storage':
            async def fill(conn):
                await conn.executemany(
                    'INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,'
                    'iv_defense,iv_stamina,gender,shiny,origin,content_version,caught_at) '
                    'SELECT ?,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,'
                    'gender,shiny,origin,content_version,caught_at FROM pokemon LIMIT 1',
                    [(f'fixture-owned-{i}',) for i in range(249)])
            await self.writer.run(fill)
        rendered, session = await self.screen(session, 'run' if kind == 'shiny' else 'throw')
        expected = {'master': 'Confirm Master Ball', 'shiny': 'Confirm Run', 'storage': 'Wild encounter'}[kind]
        self.assertEqual(rendered['embed'].title, expected)
        if kind == 'storage':
            self.assertIn('Storage is full', rendered['embed'].description)
        return rendered, session

    async def assert_kind(self, session, kind):
        state = await self.writer.run(lambda c: self.walker.encounter_state(
            c, session, json.loads(session['selection'])['encounter_id']))
        self.assertEqual(state.get('raid_kind'), kind)
        return state

    def assert_ex_tier(self, rendered):
        description = rendered['embed'].description
        self.assertIn(' · EX-Raid', description)
        self.assertNotIn('Legendary', description)

    async def test_ex_catch_screen_shows_ex_raid_line_and_tier_for_a_legendary_boss(self):
        session = await self.both_raids()
        state = await self.assert_kind(session, 'ex')
        self.assertEqual(state['encounter']['tier'], 'Legendary/Mythical')
        rendered = self.module.screens.render_catch(state)
        self.assertIn('Articuno', rendered['embed'].description)
        self.assertIn('EX-Raid · ends 1970-01-01 00:20:00 UTC', rendered['embed'].description)
        self.assert_ex_tier(rendered)

    async def test_ball_and_berry_rerenders_keep_the_ex_raid_line(self):
        session = await self.both_raids()
        for action, values in (('select_ball', None), ('pick_ball', ['poke_ball']),
                               ('select_berry', None), ('pick_berry', ['none'])):
            with self.subTest(action=action):
                rendered, session = await self.screen(session, action, values)
                self.assertIn('EX-Raid · ends 1970-01-01 00:20:00 UTC', rendered['embed'].description)
                self.assert_ex_tier(rendered)

    async def test_confirm_and_result_screens_show_ex_raid_tier(self):
        for kind in ('master', 'shiny', 'storage'):
            with self.subTest(kind=kind):
                session = await self.both_raids()
                rendered, session = await self.confirmation(session, kind)
                self.assert_ex_tier(rendered)
                if kind != 'storage':
                    rendered, session = await self.screen(session, 'master_confirm' if kind == 'master' else 'run_confirm')
                    self.assertEqual(rendered['embed'].title, 'Encounter result')
                    self.assert_ex_tier(rendered)
                    if kind == 'master':
                        reopened, _ = await self.open()
                        self.assert_ex_tier(reopened.edit_original_response.await_args.kwargs)
                        await self.writer.run(lambda c: c.execute('DELETE FROM pokemon WHERE source_encounter_id IS NOT NULL'))

    async def test_run_after_ex_expiry_says_the_ex_raid_left(self):
        for confirmed in (False, True):
            with self.subTest(confirmed=confirmed):
                session = await self.both_raids()
                if confirmed:
                    _, session = await self.confirmation(session, 'shiny')
                self.walker.clock = lambda: 1200
                before = await self.rows('SELECT * FROM encounters')
                refused = await self.click(session, 'run_confirm' if confirmed else 'run')
                self.assertEqual(refused.followup.send.await_args.args[0], 'The EX-Raid left.')
                self.assertEqual(await self.rows('SELECT * FROM encounters'), before)

    async def test_throw_after_ex_expiry_says_this_ex_raid_ended(self):
        session = await self.both_raids()
        self.walker.clock = lambda: 1200
        before = await self.rows('SELECT * FROM inventory')
        with patch.object(self.walker.rng, 'random', side_effect=AssertionError('expired roll')):
            rendered, _ = await self.screen(session, 'throw')
        self.assertIn('This EX-Raid ended; this encounter expired.', rendered['embed'].description)
        self.assert_ex_tier(rendered)
        self.assertEqual(await self.rows('SELECT * FROM inventory'), before)

    async def test_world_legendary_screens_and_refusals_unchanged(self):
        session = await self.both_raids('world')
        state = await self.writer.run(lambda c: self.walker.encounter_state(c, session, self.ids['world']))
        self.assertEqual(state['raid_line'], 'World Legendary · ends 1970-01-01 00:20:00 UTC')
        for render in (self.module.screens.render_catch, self.module.screens.render_master_confirm,
                       self.module.screens.render_run_confirm, self.module.screens.render_terminal):
            description = render(state)['embed'].description
            self.assertIn(' · Legendary/Mythical', description)
            self.assertNotIn('EX-Raid', description)
        self.walker.clock = lambda: 1200
        refused = await self.click(session, 'run')
        self.assertEqual(refused.followup.send.await_args.args[0], 'The World Legendary left.')
        rendered, _ = await self.screen(session, 'throw')
        self.assertIn('The World Legendary left; this encounter expired.', rendered['embed'].description)

    async def test_back_from_master_ball_shiny_run_and_storage_confirm_returns_to_selected_raid(self):
        for selected in ('world', 'ex'):
            for kind in ('master', 'shiny', 'storage'):
                with self.subTest(selected=selected, kind=kind):
                    session = await self.both_raids(selected)
                    _, session = await self.confirmation(session, kind)
                    before = await self.rows('SELECT * FROM encounters ORDER BY encounter_id')
                    inventory = await self.rows('SELECT * FROM inventory')
                    selection = json.loads(session['selection'])
                    with patch.object(self.walker.rng, 'random', side_effect=AssertionError('Back rerolled')):
                        _, session = await self.screen(session, 'open_encounter')
                    after = json.loads(session['selection'])
                    self.assertEqual(after['encounter_id'], self.ids[selected])
                    self.assertEqual((after['ball'], after['berry']), (selection['ball'], selection['berry']))
                    for flag in ('master_confirm', 'run_confirm', 'storage_confirm'):
                        self.assertNotIn(flag, after)
                    self.assertEqual(await self.rows('SELECT * FROM encounters ORDER BY encounter_id'), before)
                    self.assertEqual(await self.rows('SELECT * FROM inventory'), inventory)
                    self.assertEqual(len(await self.rows('SELECT * FROM raid_participation')), 2)

    async def test_back_after_selected_spawn_expired_follows_the_m81c_fallback(self):
        for selected in ('world', 'ex'):
            for cleanup in (False, True):
                for ordinary in (False, True):
                    for kind in ('master', 'shiny', 'storage'):
                        with self.subTest(selected=selected, cleanup=cleanup, ordinary=ordinary, kind=kind):
                            session = await self.both_raids(selected, ordinary=ordinary)
                            _, session = await self.confirmation(session, kind)
                            await self.writer.run(lambda c: c.execute(
                                'UPDATE world_spawns SET expires_at=1100 WHERE spawn_id=?', (selected,)))
                            self.walker.clock = lambda: 1100
                            other = 'ex' if selected == 'world' else 'world'
                            before = await self.rows('SELECT * FROM encounters WHERE encounter_id=?', (self.ids[other],))
                            if cleanup:
                                await self.writer.run(lambda c: raids.expire(c, 1100))
                            rendered, session = await self.screen(session, 'open_encounter')
                            selection = json.loads(session['selection'])
                            if ordinary:
                                self.assertEqual(selection['encounter_id'], self.encounter['encounter_id'])
                                self.assertEqual(rendered['embed'].title, 'Wild encounter')
                            else:
                                self.assertEqual(rendered['embed'].title, 'Walker')
                            for flag in ('master_confirm', 'run_confirm', 'storage_confirm'):
                                self.assertNotIn(flag, selection)
                            self.assertEqual(await self.rows('SELECT * FROM encounters WHERE encounter_id=?',
                                                             (self.ids[other],)), before)

class ExRaidEntryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_raids.RaidCommandTests.asyncSetUp
    interaction = test_raids.RaidCommandTests.interaction
    rows = test_raids.RaidCommandTests.rows
    enroll = test_raids.RaidCommandTests.enroll
    click = test_raids.RaidCommandTests.click
    current = test_raids.RaidCommandTests.current
    command = test_raids.RaidCommandTests.command
    invoke = test_raids.RaidCommandTests.invoke
    session = test_raids.RaidCommandTests.session
    rendered = test_raids.RaidCommandTests.rendered
    pending_ordinary_catch = test_raids.RaidCommandTests.pending_ordinary_catch

    async def seed_spawns(self, kinds=('world', 'ex')):
        identity = next(i for i in self.bot.content['identities'] if i['species_id'] == 144)
        async def seed(conn):
            await conn.execute('DELETE FROM encounters WHERE raid_spawn_id IS NOT NULL')
            await conn.execute('DELETE FROM raid_participation')
            await conn.execute("DELETE FROM action_receipts WHERE action='raid_join'")
            await conn.execute('DELETE FROM world_spawns')
            for kind in kinds:
                await conn.execute(
                    'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,'
                    'spawned_at,expires_at,post_state,content_version,kind) '
                    "VALUES (?,'123','789',?,?,1000,4600,'sent','fixture',?)",
                    (kind, identity['pokemon_id'], identity['identity_id'], kind))
        await self.writer.run(seed)

    async def chooser(self):
        shown = self.rendered(await self.invoke())
        self.assertEqual(shown.get('content'), 'Two raids are active here. Choose one.')
        session = await self.session()
        self.assertEqual(json.loads(session['selection']),
                         {'raid_choices': {'world': 'world', 'ex': 'ex'}})
        return shown, session

    async def test_no_live_raid_says_no_raid_is_active(self):
        for guild in (123, 999):
            with self.subTest(guild=guild):
                self.assertEqual(self.rendered(await self.invoke(guild=guild))['content'],
                                 'No raid is active here.')
        self.assertEqual(await self.rows(), [])

    async def test_one_live_raid_of_either_kind_opens_directly(self):
        for kind in ('world', 'ex'):
            with self.subTest(kind=kind):
                await self.seed_spawns((kind,))
                rendered = self.rendered(await self.invoke())
                self.assertEqual(rendered['embed'].title, 'Wild encounter')
                encounter = (await self.rows('SELECT * FROM encounters WHERE raid_spawn_id=?', (kind,)))[0]
                session = await self.session()
                self.assertEqual(json.loads(session['selection']),
                                 {'encounter_id': encounter['encounter_id'], 'ball': 'poke_ball',
                                  'berry': None, 'encounter_revision': encounter['revision']})
                self.assertEqual((session['revision'], session['expires_at']), (0, 1900))

    async def test_two_live_raids_show_chooser_labels_within_80(self):
        await self.seed_spawns()
        shown, session = await self.chooser()
        self.assertEqual((session['revision'], session['expires_at']), (0, 1900))
        buttons = shown['view'].children
        self.assertEqual([b.label for b in buttons],
                         ['World Legendary: Articuno · ends 1970-01-01 01:16:40 UTC',
                          'EX-Raid: Articuno · ends 1970-01-01 01:16:40 UTC'])
        for button, action in zip(buttons, ('raid_pick_world', 'raid_pick_ex')):
            self.assertEqual(button.custom_id, f"pw:v1:{session['session_id']}:0:{action}")
            self.assertRegex(button.custom_id, self.module.CUSTOM_ID)
            self.assertLessEqual(len(button.label), 80)
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])
        identity = next(i for i in self.bot.content['identities'] if i['species_id'] == 144)
        with patch.dict(identity, name_en='A' * 100):
            long_shown, _ = await self.chooser()
        self.assertEqual([len(b.label) for b in long_shown['view'].children], [80, 80])

    async def test_pick_joins_that_spawn_and_player_can_join_both(self):
        await self.seed_spawns()
        for kind in ('world', 'ex'):
            with self.subTest(kind=kind):
                _, session = await self.chooser()
                with patch.object(raids, 'join', wraps=raids.join) as joining:
                    picked = await self.click(session, f'raid_pick_{kind}', ['foreign-spawn'])
                self.assertEqual(joining.await_args.args[3], kind)
                self.assertIn('content', self.rendered(picked))
                self.assertIsNone(self.rendered(picked)['content'])
                self.assertEqual(self.rendered(picked)['embed'].title, 'Wild encounter')
                selection = json.loads((await self.current(session))['selection'])
                encounter = (await self.rows('SELECT * FROM encounters WHERE encounter_id=?',
                                             (selection['encounter_id'],)))[0]
                self.assertEqual(encounter['raid_spawn_id'], kind)
                self.assertEqual(selection, {'encounter_id': encounter['encounter_id'],
                                            'ball': 'poke_ball', 'berry': None,
                                            'encounter_revision': encounter['revision']})
        self.assertEqual(len(await self.rows('SELECT * FROM raid_participation')), 2)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='raid_join'")), 2)

    async def test_pick_after_its_spawn_ended_says_that_raid_has_ended(self):
        for kind in ('world', 'ex'):
            for cleanup in (False, True):
                with self.subTest(kind=kind, cleanup=cleanup):
                    await self.seed_spawns()
                    _, session = await self.chooser()
                    await self.writer.run(lambda c: c.execute(
                        'UPDATE world_spawns SET expires_at=1000 WHERE spawn_id=?', (kind,)))
                    if cleanup:
                        await self.writer.run(lambda c: raids.expire(c, self.now))
                    rendered = self.rendered(await self.click(session, f'raid_pick_{kind}'))
                    self.assertEqual(rendered['content'], 'That raid has ended.')
                    self.assertIsNone(rendered['view'])
                    self.assertIsNone(rendered['embed'])
                    self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])

    async def test_pick_after_a_replacement_spawn_never_joins_it(self):
        for kind in ('world', 'ex'):
            with self.subTest(kind=kind):
                await self.seed_spawns()
                _, session = await self.chooser()
                async def replace(conn):
                    await conn.execute('UPDATE world_spawns SET ended=1 WHERE spawn_id=?', (kind,))
                    await conn.execute(
                        'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,'
                        'spawned_at,expires_at,post_state,content_version,kind) '
                        "SELECT 'replacement',guild_id,channel_id,pokemon_id,identity_id,1000,4600,"
                        "'sent',content_version,kind FROM world_spawns WHERE spawn_id=?", (kind,))
                await self.writer.run(replace)
                with patch.object(raids, 'join', wraps=raids.join) as joining:
                    rendered = self.rendered(await self.click(session, f'raid_pick_{kind}'))
                self.assertEqual(joining.await_args.args[3], kind)
                self.assertEqual(rendered['content'], 'That raid has ended.')
                self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])

    async def test_pick_without_saved_choices_is_refused(self):
        await self.seed_spawns()
        for action in ('raid_pick_world', 'raid_pick_ex'):
            for selection in ({}, {'raid_choices': {}}, {'spawn_id': 'ex'}):
                with self.subTest(action=action, selection=selection):
                    _, session = await self.chooser()
                    await self.writer.run(lambda c: c.execute(
                        'UPDATE sessions SET selection=? WHERE session_id=?',
                        (json.dumps(selection), session['session_id'])))
                    with patch.object(raids, 'join', side_effect=AssertionError('unsaved join')):
                        refused = await self.click(session, action, ['ex'])
                    self.assertEqual(refused.followup.send.await_args.args[0], self.module.REOPEN)

    async def test_double_click_joins_once(self):
        import asyncio
        await self.seed_spawns()
        for kind in ('world', 'ex'):
            _, session = await self.chooser()
            await asyncio.gather(self.click(session, f'raid_pick_{kind}'),
                                 self.click(session, f'raid_pick_{kind}'))
            before = await self.rows('SELECT * FROM encounters WHERE raid_spawn_id=?', (kind,))
            _, reopened = await self.chooser()
            with patch.object(self.walker.rng, 'random', side_effect=AssertionError('reroll')):
                await self.click(reopened, f'raid_pick_{kind}')
            self.assertEqual(await self.rows('SELECT * FROM encounters WHERE raid_spawn_id=?', (kind,)), before)
            self.assertEqual(len(before), 1)
        self.assertEqual(len(await self.rows('SELECT * FROM raid_participation')), 2)
        self.assertEqual(len(await self.rows("SELECT * FROM action_receipts WHERE action='raid_join'")), 2)

    async def test_pending_catch_made_elsewhere_shows_its_menu_first(self):
        await self.seed_spawns()
        for kind in ('world', 'ex'):
            with self.subTest(kind=kind):
                _, session = await self.chooser()
                encounter_id = await self.pending_ordinary_catch()
                with patch.object(raids, 'join', side_effect=AssertionError('pending join')):
                    shown = self.rendered(await self.click(session, f'raid_pick_{kind}'))
                self.assertIn('content', shown)
                self.assertIsNone(shown['content'])
                self.assertEqual([b.label for b in shown['view'].children], ['Done', 'Send for research', 'Share'])
                self.assertEqual(json.loads((await self.current(session))['selection'])['encounter_id'], encounter_id)
                self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])
                await self.click(await self.current(session), 'ack')
                # Restore one ordinary encounter for the next separate-session catch.
                if kind == 'world':
                    await self.writer.run(lambda c: c.execute(
                        'INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,'
                        'iv_defense,iv_stamina,gender,shiny,tier,route_id,content_version,created_at) '
                        "SELECT 'second-ordinary',profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                        'iv_stamina,gender,0,tier,route_id,content_version,1001 FROM encounters '
                        'WHERE encounter_id=?', (encounter_id,)))

    async def test_already_joined_text_names_the_kind(self):
        for kind, name in (('world', 'World Legendary'), ('ex', 'EX-Raid')):
            for unreadable in ('null', 'missing', 'foreign'):
                with self.subTest(kind=kind, unreadable=unreadable):
                    await self.seed_spawns((kind,))
                    await self.invoke()
                    async def hide(conn):
                        if unreadable == 'null':
                            await conn.execute('UPDATE raid_participation SET encounter_id=NULL')
                        elif unreadable == 'missing':
                            await conn.execute('DELETE FROM encounters WHERE raid_spawn_id IS NOT NULL')
                        else:
                            await conn.execute(
                                'INSERT OR IGNORE INTO profiles(profile_id,guild_id,user_id,created_at) '
                                "VALUES ('foreign','123','other',0)")
                            await conn.execute("UPDATE encounters SET profile_id='foreign' "
                                               'WHERE raid_spawn_id IS NOT NULL')
                    await self.writer.run(hide)
                    with patch.object(self.walker.rng, 'random', side_effect=AssertionError('reroll')):
                        self.assertEqual(self.rendered(await self.invoke())['content'],
                                         f'You already joined this {name}; it can be joined once.')

    async def test_unenrolled_excluded_and_opted_out_see_no_chooser(self):
        from pokewalker.services import deletion
        from pokewalker.services.marker_log import State
        await self.seed_spawns()
        self.assertEqual(self.rendered(await self.invoke(user=999))['content'],
                         'Open /walker to enroll before joining.')
        await self.writer.run(lambda c: c.execute(
            "INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)"))
        self.assertEqual(self.rendered(await self.invoke())['content'], self.module.EXCLUDED)
        await self.writer.run(lambda c: c.execute('DELETE FROM restrictions'))
        await self.writer.run(lambda c: deletion.apply(c,
            {('123', '456'): State(delete_ids={self.profile['profile_id']}, opted_out=True)}))
        self.assertEqual(self.rendered(await self.invoke())['content'], 'Run /walker-account opt-in first')
        self.assertEqual(await self.rows(), [])
        self.assertEqual(await self.rows('SELECT * FROM raid_participation'), [])

    async def test_description_changes_the_global_manifest_only(self):
        from pokewalker.bot.client import WalkerBot
        from pokewalker.config import Settings, Secret
        bot = WalkerBot(Settings(Secret('synthetic'), owner_ids=frozenset({123}), admin_guild_id=123))
        self.addAsyncCleanup(bot.drain)
        command = bot.tree.get_command('raid')
        self.assertEqual(command.description, 'Join or reopen an active raid')
        global_hash, admin_hash = bot.command_manifest_hash(), bot.command_manifest_hash(123)
        command.description = 'Join or reopen the active World Legendary'
        self.assertNotEqual(bot.command_manifest_hash(), global_hash)
        self.assertEqual(bot.command_manifest_hash(123), admin_hash)
