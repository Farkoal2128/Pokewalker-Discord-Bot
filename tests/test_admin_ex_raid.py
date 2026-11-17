"""EXR-9 picker and private submit boundary over the committed catalog and SQLite."""

import asyncio
import importlib
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

import test_admin


def catalog():
    return json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))


class SuggestTests(unittest.TestCase):
    def suggest(self, text, content=None):
        try:
            module = importlib.import_module('pokewalker.bot.admin_ex_raid')
        except ModuleNotFoundError:
            self.fail('EXR-9 picker boundary is absent')
        return module.suggest(content or catalog(), text)

    def test_suggest_dex_number_lists_the_species_identities(self):
        rows = self.suggest('26')
        self.assertEqual(rows[:2], [('#026 Raichu', '26:26'),
                                  ('#026 Alolan Raichu', '10100:10202')])

    def test_suggest_ranks_prefix_then_substring_then_close_spelling(self):
        content = {'identities': [
            {'species_id': 3, 'name_en': 'Charzard', 'identity_id': 'close'},
            {'species_id': 2, 'name_en': 'Mega Charizard', 'identity_id': 'substring'},
            {'species_id': 1, 'name_en': 'Charizard', 'identity_id': 'prefix'}]}
        self.assertEqual([value for _, value in self.suggest('charizard', content)],
                         ['prefix', 'substring', 'close'])
        self.assertEqual(self.suggest('charzrd')[0], ('#006 Charizard', '6:6'))

    def test_suggest_ignores_case_and_accents_and_finds_forms(self):
        content = catalog()
        self.assertEqual(len(content['identities']), 1094)
        for text in ('FLABEBE', 'flabébé'):
            names = [label for label, _ in self.suggest(text, content)]
            self.assertTrue(any('Flabébé' in name for name in names))
        self.assertEqual(self.suggest('ALOLAN RAICHU')[0][1], '10100:10202')

    def test_suggest_returns_at_most_25_labelled_dex_and_name(self):
        content = catalog()
        expected = [(f"#{i['species_id']:03d} {i['name_en']}", i['identity_id'])
                    for i in content['identities'][:25]]
        self.assertEqual(self.suggest('', content), expected)
        for query in ('a', 'raichu', 'zzzzzzzzzz'):
            rows = self.suggest(query, content)
            self.assertLessEqual(len(rows), 25)
            self.assertEqual(len(rows), len({value for _, value in rows}))
            for label, value in rows:
                self.assertRegex(label, r'^#[0-9]{3,4} .+')
                self.assertIsInstance(value, str)


class ExRaidAdminTests(unittest.IsolatedAsyncioTestCase):
    interaction = test_admin.AdminTests.interaction

    async def asyncSetUp(self):
        await test_admin.AdminTests.asyncSetUp(self)
        self.bot.content = catalog()
        await self.bot.db.execute("INSERT INTO guilds(guild_id) VALUES ('999')")
        await self.bot.db.commit()

    def command(self):
        command = self.group.get_command('ex-raid')
        self.assertIsNotNone(command, '/admin ex-raid is absent')
        return command

    async def autocomplete(self, text='26', interaction=None):
        callback = self.command()._params['pokemon'].autocomplete
        self.assertIsNotNone(callback)
        return await callback(self.group, interaction or self.interaction(), text)

    async def submit(self, pokemon='6:6', interaction=None, **kwargs):
        interaction = interaction or self.interaction()
        command = self.command()
        before = '\n'.join([line async for line in self.bot.db.iterdump()])
        await command.callback(self.group, interaction, pokemon, **kwargs)
        self.assertEqual('\n'.join([line async for line in self.bot.db.iterdump()]), before)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        response = interaction.edit_original_response.await_args.kwargs
        self.assertEqual(response['allowed_mentions'].to_dict()['parse'], [])
        return response

    async def test_autocomplete_empty_outside_admin_guild_and_for_non_owner(self):
        for owner, guild in ((999, 123), (456, 999), (456, None)):
            interaction = self.interaction(owner=owner, guild=guild)
            self.assertEqual(await self.autocomplete(interaction=interaction), [])
            interaction.response.defer.assert_not_awaited()
            interaction.edit_original_response.assert_not_awaited()

    async def test_autocomplete_no_defer_writer_or_bucket_serves_excluded_owner(self):
        await self.bot.db.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        await self.bot.db.commit()
        self.group.requests[456] = [100] * 5
        before = dict(self.group.requests)
        interaction = self.interaction()
        with patch.object(self.bot.writer, 'run', side_effect=AssertionError('autocomplete writer job')):
            rows = await self.autocomplete(interaction=interaction)
        self.assertEqual([c.value for c in rows[:2]], ['26:26', '10100:10202'])
        self.assertTrue(all(isinstance(c, discord.app_commands.Choice) for c in rows))
        self.assertEqual(self.group.requests, before)
        self.assertEqual(self.group.gift_callbacks, {})
        interaction.response.defer.assert_not_awaited()
        interaction.response.send_message.assert_not_awaited()
        interaction.edit_original_response.assert_not_awaited()

    async def test_excluded_owner_refused_at_the_command(self):
        await self.bot.db.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        await self.bot.db.commit()
        self.assertEqual((await self.submit())['content'], 'Excluded owners cannot use admin commands.')

    async def test_known_identity_previews_locks_or_rolled_per_player(self):
        for locks in ({}, {'shiny': False, 'level': 1, 'iv_attack': 0,
                          'iv_defense': 15, 'iv_stamina': 7, 'duration': 24, 'server_id': '999'}):
            response = await self.submit(**locks)
            text = response['content']
            self.assertIn('#006 Charizard', text)
            self.assertIn('EX-Raid', text)
            for name, key in [('Shiny', 'shiny'), ('Level', 'level'), ('Attack IV', 'iv_attack'),
                              ('Defense IV', 'iv_defense'), ('Stamina IV', 'iv_stamina')]:
                expected = str(locks[key]) if key in locks else 'rolled per player'
                self.assertIn(f'{name}: {expected}', text)
            self.assertIn('Target: ' + ('server ' + locks['server_id'] if 'server_id' in locks
                                       else 'none chosen: press All servers'), text)
            self.assertEqual(response['embed'].image.url,
                             next(i for i in self.bot.content['identities'] if i['identity_id'] == '6:6')['sprites']['normal'])
            self.assertIsInstance(response['view'], discord.ui.View)

    async def test_free_text_and_unknown_identity_refused_nothing_written(self):
        for pokemon in ('Charizard', '99999:99999', ''):
            self.assertEqual((await self.submit(pokemon))['content'], 'Pick a Pokémon from the list.')

    async def test_out_of_range_level_iv_and_duration_refused(self):
        for key, values in [('level', (0, 41)), ('iv_attack', (-1, 16)),
                            ('iv_defense', (-1, 16)), ('iv_stamina', (-1, 16)),
                            ('duration', (0, 25))]:
            for value in values:
                with self.subTest(key=key, value=value):
                    self.group.requests.clear()
                    response = await self.submit(**{key: value})
                    self.assertEqual(response['content'],
                        'Level must be 1-40, each IV 0-15 and the duration 1-24 hours.')

    async def test_duration_omitted_is_one_hour(self):
        self.assertIn('Duration: 1 hour', (await self.submit())['content'])

    async def test_invalid_server_id_refused(self):
        for value in ('abc', '0', '-1', str(2**64), '１２３'):
            self.assertEqual((await self.submit(server_id=value))['content'],
                             'Server ID must be a Discord ID.')

    async def test_serialized_command_only_pokemon_required_with_ranges(self):
        command = self.command().to_dict(self.bot.tree)
        params = command['options']
        self.assertEqual([p['name'] for p in params], ['pokemon', 'server_id', 'shiny',
            'level', 'iv_attack', 'iv_defense', 'iv_stamina', 'duration'])
        self.assertEqual([p['name'] for p in params if p.get('required')], ['pokemon'])
        self.assertTrue(params[0]['autocomplete'])
        self.assertEqual([p['type'] for p in params], [3, 3, 5, 4, 4, 4, 4, 4])
        for param in params[3:]:
            self.assertEqual((param['min_value'], param['max_value']),
                (1, 40) if param['name'] == 'level' else
                (1, 24) if param['name'] == 'duration' else (0, 15))

    async def test_ex_raid_registered_only_in_the_admin_guild(self):
        self.assertIsNotNone(self.command())
        self.assertIsNone(self.bot.tree.get_command('admin'))
        self.assertIsNone(self.bot.tree.get_command('admin', guild=discord.Object(id=999)))
        for owner, guild in ((999, 123), (456, 999), (456, None)):
            result = await self.submit(interaction=self.interaction(owner=owner, guild=guild))
            self.assertEqual(result['content'], 'Only configured owners in the admin guild may use this command.')


class RaidDraftTests(unittest.IsolatedAsyncioTestCase):
    command = ExRaidAdminTests.command
    submit = ExRaidAdminTests.submit

    def interaction(self, **kwargs):
        interaction = test_admin.AdminTests.interaction(self, **kwargs)
        interaction.followup = SimpleNamespace(send=AsyncMock())
        return interaction

    async def asyncSetUp(self):
        await ExRaidAdminTests.asyncSetUp(self)
        self.clock = 100.0
        self.bot.clock = lambda: self.clock
        self.bot.walker.clock = lambda: 1000.0
        self.guilds = {}
        self.bot.get_guild = Mock(side_effect=self.guilds.get)
        await self.bot.db.execute("UPDATE guilds SET raids_enabled=1,raid_channel_id='321' WHERE guild_id='123'")
        self.cache_guild(123)
        await self.bot.db.commit()

    def cache_guild(self, guild_id, *, channel_id=321, permitted=True):
        channel = SimpleNamespace(id=channel_id, guild=SimpleNamespace(id=guild_id),
            permissions_for=Mock(return_value=SimpleNamespace(
                embed_links=permitted, send_messages=permitted)))
        self.guilds[guild_id] = SimpleNamespace(me=object(),
            get_channel=Mock(return_value=channel))
        return channel

    def draft(self):
        self.assertTrue(hasattr(self.group, 'ex_raid_drafts'), 'EX-Raid draft registry is absent')
        self.assertTrue(self.group.ex_raid_drafts, 'No EX-Raid draft was opened')
        return next(reversed(self.group.ex_raid_drafts.values()))

    def control(self, label, draft):
        return next(item for item in draft.view.children if item.label == label)

    async def click(self, label, *, draft=None, interaction=None, control=None):
        draft = draft or self.draft()
        item = control or self.control(label, draft)
        interaction = interaction or self.interaction()
        interaction.data = {'custom_id': item.custom_id}
        if await draft.view.interaction_check(interaction):
            await item.callback(interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        for reply in (interaction.edit_original_response.await_args, interaction.followup.send.await_args):
            if reply:
                self.assertEqual(reply.kwargs['allowed_mentions'].to_dict()['parse'], [])
        return interaction

    async def snapshot(self):
        return '\n'.join([line async for line in self.bot.db.iterdump()])

    async def test_server_target_preview_shows_send_id_boss_locks_duration_counts(self):
        response = await self.submit(server_id='123', shiny=True, level=40, iv_attack=0,
                                     iv_defense=15, iv_stamina=7, duration=24)
        draft = self.draft()
        self.assertEqual((draft.owner_id, draft.guild_id, draft.all_servers), (456, 123, False))
        self.assertEqual((draft.deadline, draft.revision, draft.state, draft.discard_pending),
                         (1000, 0, 'editing', False))
        self.assertRegex(draft.send_id, r'^[0-9a-f]{32}$')
        self.assertEqual(draft.identity['identity_id'], '6:6')
        self.assertEqual(draft.hours, 24)
        self.assertEqual(draft.locks, dict(shiny=True, level=40, iv_attack=0, iv_defense=15, iv_stamina=7))
        for text in (draft.send_id, '#006 Charizard', 'Shiny: True', 'Level: 40', 'Attack IV: 0',
                     'Defense IV: 15', 'Stamina IV: 7', 'Duration: 24 hours', 'Target: server 123',
                     'Counts (provisional)', 'Targeted servers: 1', 'Servers that will get it: 1'):
            self.assertIn(text, response['content'])
        self.assertEqual(response['embed'].image.url, draft.identity['sprites']['shiny'])
        self.assertEqual([item.label for item in draft.view.children], ['Cancel', 'Confirm'])
        self.bot.get_guild.assert_called_once_with(123)
        self.guilds[123].get_channel.assert_called_once_with(321)

    async def test_unknown_server_refused_no_draft(self):
        response = await self.submit(server_id='888')
        self.assertEqual(response['content'], 'The bot has no data for server 888.')
        self.assertEqual(self.group.ex_raid_drafts, {})
        self.assertIsNone(response.get('view'))

    async def test_without_server_id_shows_all_servers_no_target_no_counts(self):
        from pokewalker.services import raids
        with patch.object(raids, 'ex_target', side_effect=AssertionError('No implicit global target')):
            response = await self.submit()
        draft = self.draft()
        self.assertEqual((draft.guild_id, draft.all_servers), (None, False))
        self.assertIn('Target: none chosen: press All servers', response['content'])
        self.assertNotIn('Counts', response['content'])
        self.assertEqual([item.label for item in draft.view.children], ['All servers', 'Cancel', 'Confirm'])
        self.assertIn('rolled per player', response['content'])
        self.bot.get_guild.assert_not_called()

    async def test_all_servers_press_bumps_revision_and_shows_global_counts(self):
        await self.submit()
        draft = self.draft()
        send_id, deadline = draft.send_id, draft.deadline
        old_all = self.control('All servers', draft)
        response = (await self.click('All servers')).edit_original_response.await_args.kwargs
        self.assertEqual((draft.guild_id, draft.all_servers, draft.revision), (None, True, 1))
        self.assertEqual((draft.send_id, draft.deadline), (send_id, deadline))
        for text in ('Target: all servers', 'Counts (provisional)', 'Targeted servers: 2',
                     'Servers that will get it: 1', 'Raids off: 1'):
            self.assertIn(text, response['content'])
        self.assertEqual([item.label for item in draft.view.children], ['Cancel', 'Confirm'])
        await self.click('All servers', draft=draft, control=old_all)
        self.assertEqual(draft.revision, 1)

    async def test_counts_list_each_skip_reason_marked_provisional(self):
        for guild_id in range(200, 205):
            await self.bot.db.execute("INSERT INTO guilds(guild_id,raids_enabled,raid_channel_id) VALUES (?,1,'321')",
                                      (str(guild_id),))
        await self.bot.db.execute("UPDATE guilds SET raid_channel_id=NULL WHERE guild_id='200'")
        self.cache_guild(201, permitted=False)
        self.cache_guild(202, channel_id=654)
        self.cache_guild(203)
        await self.bot.db.execute(
            'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,'
            'spawned_at,expires_at,post_state,content_version,kind) '
            "VALUES ('live','203','321',6,'6:6',0,1001,'sent','fixture','ex')")
        await self.bot.db.commit()
        await self.submit()
        text = (await self.click('All servers')).edit_original_response.await_args.kwargs['content']
        for expected in ('Counts (provisional)', 'Targeted servers: 7', 'Servers that will get it: 1',
                         'Raids off: 1', 'No raid channel: 1', 'No permission or bot not in server: 2',
                         'Raid channel changed: 1', 'EX-Raid already live: 1'):
            self.assertIn(expected, text)
        self.group.requests.clear()
        empty = await self.submit(server_id='999')
        self.assertIn('Nothing would spawn.', empty['content'])
        self.assertNotIn('Nothing would spawn.', text)
        # Spawn liveness must use the UTC walker clock, never the monotonic draft clock.
        self.bot.walker.clock = lambda: 1001.0
        self.assertIn('Servers that will get it: 1', (await self.submit(server_id='203'))['content'])

    async def test_cancel_discards_and_leaves_text_without_controls(self):
        await self.submit(server_id='123')
        draft = self.draft()
        response = (await self.click('Cancel')).edit_original_response.await_args.kwargs
        self.assertEqual(response['content'], 'EX-Raid draft cancelled.')
        self.assertIsNone(response['view'])
        self.assertIsNone(response['embed'])
        self.assertEqual(self.group.ex_raid_drafts, {})
        self.assertEqual((draft.state, draft.guild_id), ('discarded', None))
        self.assertTrue(draft.view.is_finished())

    async def test_draft_expires_after_900_s_and_presses_refuse(self):
        await self.submit()
        draft = self.draft()
        self.clock = 999.999
        await self.click('All servers')
        self.assertTrue(draft.all_servers)
        self.clock = 1000
        expired = await self.click('Cancel', draft=draft)
        self.assertEqual(expired.followup.send.await_args.kwargs['content'],
                         'This EX-Raid draft expired. Run /admin ex-raid again.')
        expired.edit_original_response.assert_not_awaited()
        self.assertEqual(self.group.ex_raid_drafts, {})
        await self.submit()
        timed = self.draft()
        await timed.view.on_timeout()
        self.assertEqual((self.group.ex_raid_drafts, timed.state), ({}, 'discarded'))

    async def test_other_owner_other_guild_and_excluded_owner_refused(self):
        await self.submit()
        draft = self.draft()
        for owner, guild in ((457, 123), (999, 123), (456, 999), (456, None)):
            denied = await self.click('All servers', interaction=self.interaction(owner=owner, guild=guild))
            self.assertIn('owner', denied.followup.send.await_args.kwargs['content'])
            denied.edit_original_response.assert_not_awaited()
        await self.bot.db.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        await self.bot.db.commit()
        denied = await self.click('All servers')
        self.assertIn('Excluded', denied.followup.send.await_args.kwargs['content'])
        denied.edit_original_response.assert_not_awaited()
        self.assertEqual((draft.all_servers, draft.revision, draft.state), (False, 0, 'editing'))

    async def test_presses_share_the_30_per_minute_bucket_with_ex_gift(self):
        from pokewalker.bot import admin_gift
        await self.submit()
        draft = self.draft()
        gift = admin_gift.OwnerView(self.group, 456, 1000, 'expired')
        self.addCleanup(gift.stop)
        for _ in range(29):
            press = self.interaction()
            press.data = {'custom_id': 'gift-control'}
            self.assertTrue(await gift.interaction_check(press))
        await self.click('All servers')
        self.assertEqual(len(self.group.gift_callbacks[456]), 30)
        denied = await self.click('Cancel')
        self.assertIn('Slow down', denied.followup.send.await_args.kwargs['content'])
        self.assertEqual(draft.state, 'editing')
        self.clock = 160
        await self.click('Cancel')
        self.assertEqual(draft.state, 'discarded')

    async def test_press_after_restart_finds_no_handler(self):
        from pokewalker.bot.client import WalkerBot
        await self.submit()
        draft = self.draft()
        control = self.control('All servers', draft)
        self.bot._connection.store_view(draft.view, 111)
        self.assertTrue(self.bot._connection._view_store._views)
        await self.bot.drain()
        restarted = WalkerBot(self.settings, clock=lambda: self.clock)
        self.addAsyncCleanup(restarted.drain)
        fresh = restarted.tree.get_command('admin', guild=discord.Object(id=123))
        interaction = self.interaction()
        interaction.message = SimpleNamespace(id=111, interaction_metadata=None)
        restarted._connection._view_store.dispatch_view(2, control.custom_id, interaction)
        await asyncio.sleep(0)
        interaction.response.defer.assert_not_awaited()
        interaction.edit_original_response.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()
        self.assertEqual(fresh.ex_raid_drafts, {})

    async def test_view_within_discord_component_limits(self):
        for target in (None, '123'):
            response = await self.submit(server_id=target)
            view = response.get('view')
            self.assertIsInstance(view, discord.ui.View)
            for row in view.to_components():
                self.assertLessEqual(len(row['components']), 5)
                for item in row['components']:
                    self.assertEqual(item['type'], 2)
                    self.assertTrue(1 <= len(item['label']) <= 80)
                    self.assertTrue(1 <= len(item['custom_id']) <= 100)
            self.assertLessEqual(len(view.to_components()), 5)
            self.assertLessEqual(len(response['content']), 2000)
            self.assertFalse(view.is_persistent())

    async def test_preview_writes_nothing(self):
        before, writes = await self.snapshot(), self.bot.db.total_changes
        await self.submit()
        await self.click('All servers')
        await self.submit(server_id='123')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(self.bot.db.total_changes, writes)
        from pokewalker.services import raids
        for state in ('sending', 'sent', 'unregistered'):
            draft = self.draft()
            draft.state = state
            if state == 'sent':
                draft.result = dict(ex_raid_id=draft.send_id, hours=draft.hours,
                    guild_id=draft.guild_id, created_at=1000, servers=1, spawned=1,
                    skipped={}, **draft.locks)
            if state == 'unregistered':
                draft.state = 'editing'
                self.group.ex_raid_drafts.pop(draft.draft_id)
            with patch.object(raids, 'ex_target', side_effect=AssertionError('Stale draft counted')):
                denied = await self.click('Cancel', draft=draft)
            if state == 'sent':
                self.assertIn(draft.send_id, denied.edit_original_response.await_args.kwargs['content'])
                denied.followup.send.assert_not_awaited()
                del draft.result
            else:
                denied.edit_original_response.assert_not_awaited()
                denied.followup.send.assert_awaited_once()
            if state != 'unregistered':
                draft.state = 'editing'
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(self.bot.db.total_changes, writes)


    async def test_registry_and_state_rechecked_after_awaits(self):
        from pokewalker.bot import admin_ex_raid
        for change in ('unregister', 'sending', 'expire'):
            await self.submit()
            draft = self.draft()
            async def exclusion(conn, interaction):
                if change == 'unregister':
                    self.group.ex_raid_drafts.pop(draft.draft_id)
                elif change == 'sending':
                    draft.state = 'sending'
                else:
                    self.clock = draft.deadline
                return False
            with patch.object(self.group, 'excluded', side_effect=exclusion):
                denied = await self.click('All servers', draft=draft)
            denied.edit_original_response.assert_not_awaited()
            denied.followup.send.assert_awaited_once()
            self.assertFalse(draft.all_servers)
            draft.state = 'editing'
            admin_ex_raid.discard(draft)
        await self.submit()
        draft = self.draft()
        original = admin_ex_raid.target_counts
        async def discard_while_counting(admin, guild_id):
            counts = await original(admin, guild_id)
            admin_ex_raid.discard(draft)
            return counts
        with patch.object(admin_ex_raid, 'target_counts', side_effect=discard_while_counting):
            denied = await self.click('All servers', draft=draft)
        denied.edit_original_response.assert_not_awaited()
        self.assertIn('expired', denied.followup.send.await_args.kwargs['content'])
        self.assertEqual(self.group.ex_raid_drafts, {})

    async def test_discard_while_sending_marks_pending_then_clears_receipt(self):
        from pokewalker.bot import admin_ex_raid
        await self.submit()
        draft = self.draft()
        draft.state = 'sending'
        draft.result = {'status': 'sent'}
        admin_ex_raid.discard(draft)
        self.assertTrue(draft.discard_pending)
        self.assertIs(self.group.ex_raid_drafts[draft.draft_id], draft)
        self.assertEqual(draft.state, 'sending')
        draft.state = 'sent'
        admin_ex_raid.discard(draft)
        self.assertFalse(hasattr(draft, 'result'))
        self.assertEqual(self.group.ex_raid_drafts, {})


class RaidConfirmTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = RaidDraftTests.asyncSetUp
    interaction = RaidDraftTests.interaction
    cache_guild = RaidDraftTests.cache_guild
    command = RaidDraftTests.command
    submit = RaidDraftTests.submit
    draft = RaidDraftTests.draft
    control = RaidDraftTests.control
    click = RaidDraftTests.click
    snapshot = RaidDraftTests.snapshot

    async def preview(self, **kwargs):
        self.bot.announce_ex_raid = Mock()
        await self.submit(**kwargs)
        draft = self.draft()
        self.assertIn('Confirm', [item.label for item in draft.view.children])
        return draft, self.control('Confirm', draft)

    def reply_text(self, reply):
        call = reply.edit_original_response.await_args or reply.followup.send.await_args
        return call.kwargs['content']

    async def rows(self, sql):
        async with self.bot.db.execute(sql) as cursor:
            return [tuple(row) for row in await cursor.fetchall()]

    async def queued(self, draft, control, *, before_queue=False):
        entered, release = asyncio.Event(), asyncio.Event()
        run = self.bot.writer.run
        async def block(conn):
            entered.set()
            await release.wait()
        async def queued_run(fn, **kwargs):
            if kwargs.get('after_commit') and before_queue:
                entered.set()
                await release.wait()
            elif kwargs.get('after_commit'):
                holding = asyncio.create_task(run(block))
                async def finish_blocker():
                    await holding
                self.addAsyncCleanup(finish_blocker)
                await entered.wait()
            return await run(fn, **kwargs)
        patched = patch.object(self.bot.writer, 'run', side_effect=queued_run)
        patched.start()
        self.addCleanup(patched.stop)
        self.addCleanup(release.set)
        task = asyncio.create_task(self.click('Confirm', draft=draft, control=control))
        await asyncio.wait_for(entered.wait(), 5)
        await asyncio.sleep(0)
        return task, release

    async def test_confirm_disabled_until_target_then_sends_once_with_counts(self):
        draft, old = await self.preview(shiny=True, level=40, iv_attack=0,
            iv_defense=15, iv_stamina=7, duration=24)
        self.assertTrue(old.disabled)
        self.assertEqual(old.custom_id, f'ex_raid_confirm:{draft.draft_id}:0')
        refused = await self.click('Confirm')
        self.assertEqual(self.reply_text(refused), 'This preview is out of date. Nothing was sent.')
        await self.click('All servers')
        confirm = self.control('Confirm', draft)
        self.assertFalse(confirm.disabled)
        self.assertEqual(confirm.custom_id, f'ex_raid_confirm:{draft.draft_id}:1')
        reply = await self.click('Confirm')
        text = self.reply_text(reply)
        for value in (draft.send_id, '#006 Charizard', 'Shiny: 1', 'Level: 40', 'Attack IV: 0',
                      'Defense IV: 15', 'Stamina IV: 7', 'Duration: 24 hours', 'Target: all servers',
                      'End UTC: 1970-01-02T00:16:40+00:00', 'Counts (committed)',
                      'Targeted servers: 2', 'Servers that got it: 1', 'Raids off: 1',
                      'No raid channel: 0', 'No permission or bot not in server: 0',
                      'Raid channel changed: 0', 'EX-Raid already live: 0'):
            self.assertIn(value, text)
        self.assertIsNone(reply.edit_original_response.await_args.kwargs['view'])
        self.assertIsNone(reply.edit_original_response.await_args.kwargs['embed'])
        before = await self.snapshot()
        repeated = await self.click('Confirm', control=confirm)
        self.assertEqual(self.reply_text(repeated), text)
        self.assertEqual(await self.snapshot(), before)
        self.bot.announce_ex_raid.assert_called_once_with(draft.send_id)

    async def test_confirm_takes_5_per_minute_token_shared_with_ex_gift(self):
        from pokewalker.bot import admin_gift
        draft, confirm = await self.preview(server_id='123')
        gift = admin_gift.OwnerView(self.group, 456, 1000, 'expired')
        self.addCleanup(gift.stop)
        for _ in range(3):
            press = self.interaction()
            press.data = {'custom_id': 'gift_confirm:fixture:0'}
            self.assertTrue(await gift.interaction_check(press))
        self.assertEqual(len(self.group.requests[456]), 4)
        await self.click('Confirm')
        self.assertEqual(len(self.group.requests[456]), 5)
        denied = await self.click('Confirm', control=confirm)
        self.assertIn('Slow down', self.reply_text(denied))
        self.assertNotIn(456, self.group.gift_callbacks)

    async def test_stale_confirm_from_before_all_servers_is_refused(self):
        draft, stale = await self.preview()
        await self.click('All servers')
        before = await self.snapshot()
        reply = await self.click('Confirm', control=stale)
        self.assertEqual(self.reply_text(reply), 'This preview is out of date. Nothing was sent.')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(draft.state, 'editing')

    async def test_retried_confirm_and_lost_ack_return_the_same_receipt(self):
        draft, confirm = await self.preview(server_id='123')
        failed = self.interaction()
        failed.edit_original_response.side_effect = RuntimeError('lost ack')
        with self.assertRaisesRegex(RuntimeError, 'lost ack'):
            await self.click('Confirm', interaction=failed)
        expected = failed.edit_original_response.await_args.kwargs['content']
        for label in ('Confirm', 'Cancel'):
            reply = await self.click(label, control=confirm if label == 'Confirm' else None)
            self.assertEqual(self.reply_text(reply), expected)
        self.assertEqual(await self.rows('SELECT ex_raid_id,spawned FROM ex_raids'), [(draft.send_id, 1)])
        self.bot.announce_ex_raid.assert_called_once_with(draft.send_id)

    async def test_replay_after_expiry_or_server_changes_spawns_nothing(self):
        from pokewalker.services import raids
        draft, confirm = await self.preview(server_id='123')
        await self.click('Confirm')
        saved = draft.result
        await self.bot.db.execute('UPDATE world_spawns SET expires_at=1')
        await self.bot.db.execute('UPDATE guilds SET raids_enabled=0')
        await self.bot.db.commit()
        before = await self.snapshot()
        # Exercise service replay through Confirm, as a lost in-memory acknowledgement.
        draft.state = 'editing'
        with patch.object(raids, 'checked_channel', side_effect=AssertionError('Replay targeted')):
            reply = await self.click('Confirm', control=confirm)
        self.assertEqual(await self.snapshot(), before)
        self.assertTrue(draft.result['replayed'])
        self.assertIn(saved['ex_raid_id'], self.reply_text(reply))
        self.bot.announce_ex_raid.assert_called_once_with(draft.send_id)

    async def test_send_spawning_nowhere_lists_skip_reasons_writes_nothing(self):
        draft, _ = await self.preview()
        await self.click('All servers')
        await self.bot.db.execute('UPDATE guilds SET raids_enabled=0')
        await self.bot.db.commit()
        before = await self.snapshot()
        reply = await self.click('Confirm')
        text = self.reply_text(reply)
        self.assertIn('Nothing was sent: no server could get this EX-Raid.', text)
        for reason, label in importlib.import_module('pokewalker.bot.admin_ex_raid').SKIP_LABELS:
            self.assertIn(f'{label}: {2 if reason == "raids_off" else 0}', text)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(draft.state, 'editing')
        self.bot.announce_ex_raid.assert_not_called()

    async def test_insert_failure_restores_editing_with_same_send_id(self):
        draft, confirm = await self.preview(server_id='123')
        before, identity = await self.snapshot(), (draft.revision, draft.send_id)
        await self.bot.db.execute("CREATE TEMP TRIGGER fail_ex BEFORE INSERT ON world_spawns "
            "BEGIN SELECT RAISE(ABORT,'fixture insert failure'); END")
        reply = await self.click('Confirm')
        self.assertEqual(self.reply_text(reply), 'Nothing was sent.')
        self.assertEqual((draft.state, draft.revision, draft.send_id), ('editing', *identity))
        await self.bot.db.execute('DROP TRIGGER fail_ex')
        await self.bot.db.commit()
        self.assertEqual(await self.snapshot(), before)
        await self.click('Confirm', control=confirm)
        self.assertEqual(await self.rows('SELECT ex_raid_id FROM ex_raids'), [(identity[1],)])

    async def test_owner_excluded_after_preview_or_while_confirm_waits(self):
        draft, confirm = await self.preview(server_id='123')
        sql = "INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)"
        await self.bot.db.execute(sql)
        await self.bot.db.commit()
        reply = await self.click('Confirm')
        self.assertIn('Excluded', self.reply_text(reply))
        await self.bot.db.execute('DELETE FROM restrictions')
        await self.bot.db.commit()
        excluded = self.group.excluded
        async def exclude_after_check(conn, interaction):
            result = await excluded(conn, interaction)
            await conn.execute(sql)
            return result
        with patch.object(self.group, 'excluded', side_effect=exclude_after_check):
            reply = await self.click('Confirm', control=confirm)
        self.assertEqual(self.reply_text(reply), 'Nothing was sent.')
        self.assertEqual(draft.state, 'editing')
        self.assertEqual(await self.rows('SELECT * FROM ex_raids'), [])

    async def test_confirm_queued_past_deadline_sends_nothing(self):
        draft, confirm = await self.preview(server_id='123')
        before = await self.snapshot()
        task, release = await self.queued(draft, confirm)
        self.clock = draft.deadline
        release.set()
        reply = await task
        self.assertEqual(self.reply_text(reply), 'Nothing was sent.')
        self.assertEqual((draft.state, self.group.ex_raid_drafts), ('discarded', {}))
        self.assertEqual(await self.snapshot(), before)

    async def test_cancel_during_commit_keeps_the_committed_send(self):
        from pokewalker.bot.admin_ex_raid import discard
        commit = self.bot.db.commit
        for ending in ('discard', 'deadline'):
            with self.subTest(ending=ending):
                self.group.requests.clear()
                await self.bot.db.execute('UPDATE world_spawns SET expires_at=1')
                await commit()
                draft, _ = await self.preview(server_id='123')
                async def cancel_at_commit():
                    if draft.state == 'sending':
                        if ending == 'discard':
                            discard(draft)
                            self.assertTrue(draft.discard_pending)
                        else:
                            self.clock = draft.deadline
                    await commit()
                with patch.object(self.bot.db, 'commit', side_effect=cancel_at_commit):
                    reply = await self.click('Confirm')
                self.assertEqual(draft.state, 'discarded')
                self.assertNotIn(draft.draft_id, self.group.ex_raid_drafts)
                self.assertFalse(hasattr(draft, 'result'))
                self.assertIn('Target: server 123', self.reply_text(reply))
                self.assertIn((draft.send_id,), await self.rows('SELECT ex_raid_id FROM ex_raids'))
                self.bot.announce_ex_raid.assert_called_once_with(draft.send_id)

    async def rollback_after_service(self, ending):
        from pokewalker.bot.admin_ex_raid import discard
        from pokewalker.services import raids
        draft, _ = await self.preview(server_id='123')
        await self.bot.db.execute(
            'INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,'
            'spawned_at,expires_at,post_state,content_version,kind) '
            "VALUES ('overdue','123','321',6,'6:6',0,999,'pending','fixture','ex')")
        await self.bot.db.commit()
        before = await self.snapshot()
        send = raids.ex_commit
        async def end_after_send(conn, **kwargs):
            result = await send(conn, **kwargs)
            self.assertEqual(result['status'], 'sent')
            if ending == 'deadline':
                self.clock = draft.deadline
            else:
                discard(draft)
            return result
        with patch.object(raids, 'ex_commit', side_effect=end_after_send):
            reply = await self.click('Confirm')
        self.assertEqual(self.reply_text(reply), 'Nothing was sent.')
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((draft.state, self.group.ex_raid_drafts), ('discarded', {}))
        self.assertTrue(draft.view.is_finished())
        self.bot.announce_ex_raid.assert_not_called()

    async def test_deadline_during_commit_rolls_back_settlement_send_spawns(self):
        await self.rollback_after_service('deadline')

    async def test_discard_before_final_live_check_rolls_back_and_cleans_up(self):
        await self.rollback_after_service('discard')

    async def test_cancel_then_rollback_restores_revision_and_send_id(self):
        from pokewalker.services import raids
        draft, confirm = await self.preview(server_id='123')
        before, identity = await self.snapshot(), (draft.revision, draft.send_id)
        send = raids.ex_commit
        async def broken(conn, **kwargs):
            await send(conn, **kwargs)
            raise RuntimeError('rollback')
        with patch.object(raids, 'ex_commit', side_effect=broken):
            task, release = await self.queued(draft, confirm)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            release.set()
            await draft.task
        self.assertEqual((draft.state, draft.revision, draft.send_id), ('editing', *identity))
        self.assertEqual(await self.snapshot(), before)
        self.bot.announce_ex_raid.assert_not_called()

    async def test_cancelled_callback_still_commits_and_schedules_fanout(self):
        draft, confirm = await self.preview(server_id='123')
        task, release = await self.queued(draft, confirm, before_queue=True)
        while_sending = await self.click('Cancel')
        self.assertEqual(self.reply_text(while_sending), 'This EX-Raid is being sent.')
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        release.set()
        await draft.task
        self.assertEqual(draft.state, 'sent')
        self.assertEqual(await self.rows('SELECT ex_raid_id FROM ex_raids'), [(draft.send_id,)])
        self.bot.announce_ex_raid.assert_called_once_with(draft.send_id)
        reply = await self.click('Confirm', control=confirm)
        self.assertIn(draft.send_id, self.reply_text(reply))

    async def test_fanout_scheduled_before_receipt_survives_failed_reply(self):
        draft, _ = await self.preview(server_id='123')
        reply = self.interaction()
        async def failed_reply(**kwargs):
            self.bot.announce_ex_raid.assert_called_once_with(draft.send_id)
            self.assertEqual(await self.rows('SELECT ex_raid_id FROM ex_raids'), [(draft.send_id,)])
            raise RuntimeError('reply failed')
        reply.edit_original_response.side_effect = failed_reply
        with self.assertRaisesRegex(RuntimeError, 'reply failed'):
            await self.click('Confirm', interaction=reply)
        self.assertEqual(draft.state, 'sent')

    async def test_confirm_through_drain_leaves_rows_pending(self):
        from pokewalker.bot.client import WalkerBot
        from pokewalker.services import raids
        from pokewalker.db import open_db
        draft, _ = await self.preview(server_id='123')
        self.bot.announce_ex_raid = WalkerBot.announce_ex_raid.__get__(self.bot)
        send = raids.ex_commit
        async def during_drain(conn, **kwargs):
            result = await send(conn, **kwargs)
            self.bot._begin_drain()
            return result
        with patch.object(raids, 'ex_commit', side_effect=during_drain):
            reply = await self.click('Confirm')
        await self.bot.drain()
        conn = await open_db(self.settings.db_path, allow_unpatched=True)
        try:
            async with conn.execute('SELECT post_state FROM world_spawns') as cursor:
                self.assertEqual([row[0] for row in await cursor.fetchall()], ['pending'])
        finally:
            await conn.close()
        self.assertIn(draft.send_id, self.reply_text(reply))
        self.assertEqual(self.bot._raid_fanouts, set())

    async def test_forged_and_other_owner_confirm_refused(self):
        draft, confirm = await self.preview(server_id='123')
        before = await self.snapshot()
        self.bot._connection.store_view(draft.view, 111)
        forged = self.interaction()
        forged.message = SimpleNamespace(id=111, interaction_metadata=None)
        self.bot._connection._view_store.dispatch_view(2, 'ex_raid_confirm:forged:0', forged)
        await asyncio.sleep(0)
        forged.response.defer.assert_not_awaited()
        forged.edit_original_response.assert_not_awaited()
        forged.followup.send.assert_not_awaited()
        for owner, guild in ((457, 123), (999, 123), (456, 999), (456, None)):
            reply = await self.click('Confirm', interaction=self.interaction(owner=owner, guild=guild))
            self.assertIn('owner', self.reply_text(reply))
        # A copied control cannot revive an unregistered draft.
        self.group.ex_raid_drafts.pop(draft.draft_id)
        reply = await self.click('Confirm', draft=draft, control=confirm)
        self.assertIn('expired', self.reply_text(reply))
        self.assertEqual(await self.snapshot(), before)

    async def test_old_control_after_restart_cannot_send(self):
        from pokewalker.bot.client import WalkerBot
        draft, confirm = await self.preview(server_id='123')
        self.bot._connection.store_view(draft.view, 111)
        before = await self.snapshot()
        await self.bot.drain()
        restarted = WalkerBot(self.settings, clock=lambda: self.clock)
        self.addAsyncCleanup(restarted.drain)
        interaction = self.interaction()
        interaction.message = SimpleNamespace(id=111, interaction_metadata=None)
        restarted._connection._view_store.dispatch_view(2, confirm.custom_id, interaction)
        await asyncio.sleep(0)
        interaction.response.defer.assert_not_awaited()
        interaction.edit_original_response.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()
        from pokewalker.db import open_db
        conn = await open_db(self.settings.db_path, allow_unpatched=True)
        try:
            self.assertEqual('\n'.join([line async for line in conn.iterdump()]), before)
        finally:
            await conn.close()
