"""EXG-5 manager payloads and synthetic callbacks over real SQLite."""

import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

import test_admin


class GiftTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, **kwargs):
        interaction = test_admin.AdminTests.interaction(self, **kwargs)
        interaction.followup = SimpleNamespace(send=AsyncMock())
        return interaction

    def reply_text(self, interaction):
        reply = interaction.followup.send.await_args or interaction.edit_original_response.await_args
        return reply.kwargs['content']

    async def asyncSetUp(self):
        await test_admin.AdminTests.asyncSetUp(self)
        self.clock = 100.0
        self.bot.clock = lambda: self.clock
        self.bot.content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        await self.bot.db.execute("INSERT INTO guilds(guild_id) VALUES ('999')")
        await self.bot.db.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('a','123','456',0),('b','999','789',0)")
        await self.bot.db.commit()

    async def open(self, scope='all', server_id=None, user_id=None, interaction=None):
        interaction = interaction or self.interaction()
        command = self.group.get_command('gift')
        self.assertIsNotNone(command, '/admin gift is absent')
        await command.callback(self.group, interaction, discord.app_commands.Choice(name=scope, value=scope),
                               server_id, user_id)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        self.assertEqual(interaction.edit_original_response.await_args.kwargs['allowed_mentions'].to_dict()['parse'], [])
        return interaction

    def draft(self):
        return next(reversed(self.group.gift_drafts.values()))

    def control(self, label, draft=None):
        return next(item for item in (draft or self.draft()).view.children
                    if getattr(item, 'label', None) == label or getattr(item, 'placeholder', None) == label)

    async def click(self, label, value=None, *, interaction=None, draft=None, control=None):
        draft = draft or self.draft()
        item = control or self.control(label, draft)
        interaction = interaction or self.interaction()
        if value is not None:
            item._values = [value]
        if await draft.view.interaction_check(interaction):
            await item.callback(interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        if interaction.edit_original_response.await_args:
            self.assertEqual(interaction.edit_original_response.await_args.kwargs['allowed_mentions'].to_dict()['parse'], [])
        if interaction.followup.send.await_args:
            self.assertTrue(interaction.followup.send.await_args.kwargs['ephemeral'])
            self.assertEqual(interaction.followup.send.await_args.kwargs['allowed_mentions'].to_dict()['parse'], [])
        return interaction

    def payload(self):
        payload = self.draft().view.to_components()
        self.assertLessEqual(len(payload), 5)
        for row in payload:
            for item in row['components']:
                if item['type'] == 3:
                    self.assertTrue(1 <= len(item['options']) <= 25)
                    self.assertTrue(all(1 <= len(option['label']) <= 100 for option in item['options']))
        return payload

    async def pick(self, key='poke_ball'):
        return await self.click('Choose item', key)

    async def snapshot(self):
        return '\n'.join([line async for line in self.bot.db.iterdump()])

    async def test_parameters_admin_guild_only(self):
        command = self.group.get_command('gift')
        self.assertIsNotNone(command, '/admin gift is absent')
        params = {p.name: p for p in command.parameters}
        self.assertEqual(set(params), {'scope', 'server_id', 'user_id'})
        self.assertEqual([c.value for c in params['scope'].choices], ['all', 'server'])
        self.assertTrue(params['scope'].required)
        self.assertTrue(all(params[key].type == discord.AppCommandOptionType.string for key in params))
        self.assertFalse(params['server_id'].required or params['user_id'].required)
        self.assertIsNone(self.bot.tree.get_command('admin'))
        for owner, guild in ((999, 123), (456, 999), (456, None)):
            await self.open(interaction=self.interaction(owner=owner, guild=guild))
        self.assertEqual(self.group.gift_drafts, {})
        await self.open()
        self.assertEqual(self.draft().owner_id, 456)

    async def test_bad_scope_id_combos_write_nothing(self):
        before = await self.snapshot()
        for scope, server, user, text in (
                ('all', '123', None, 'scope'), ('all', None, '456', 'scope'),
                ('server', None, None, 'scope'), ('server', 'bad', None, 'Discord IDs'),
                ('server', '123', 'bad', 'Discord IDs'), ('server', '555', None, 'no data'),
                ('server', '123', '888', 'no profile'), ('server', '123', '789', 'no profile')):
            self.group.requests.clear()
            reply = await self.open(scope, server, user)
            self.assertIn(text, reply.edit_original_response.await_args.kwargs['content'])
            self.assertEqual(self.group.gift_drafts, {})
            self.assertEqual(await self.snapshot(), before)

    async def test_rows_4_14_at_0_and_5_15_at_10_slots(self):
        await self.open()
        payload = self.payload()
        self.assertEqual((len(payload), sum(len(r['components']) for r in payload)), (4, 14))
        self.assertTrue(self.control('Preview').disabled)
        self.assertTrue(self.control('Remove').disabled)
        for _ in range(10):
            await self.pick()
        payload = self.payload()
        self.assertEqual((len(payload), sum(len(r['components']) for r in payload)), (5, 15))
        self.assertTrue(self.control('Choose item').disabled)
        self.assertEqual([o['label'] for o in payload[3]['components'][0]['options']],
                         [f'{n}. Poké Ball' for n in range(1, 11)])
        await self.pick()
        self.assertEqual(len(self.draft().slots), 10)

    async def test_clear_and_last_remove_omit_slot_select(self):
        await self.open()
        await self.pick()
        await self.click('Choose slot', '0')
        self.assertFalse(self.control('Remove').disabled)
        await self.click('Remove')
        self.assertEqual(len(self.payload()), 4)
        await self.pick()
        await self.click('Clear')
        self.assertEqual(len(self.payload()), 4)
        self.assertEqual(self.draft().slots, [])

    async def test_duplicate_picks(self):
        await self.open()
        await self.pick()
        await self.pick()
        self.assertEqual(self.draft().slots, ['poke_ball', 'poke_ball'])
        self.payload()

    async def test_category_and_ex_reset_page(self):
        await self.open()
        await self.click('Evolution')
        await self.click('Next')
        self.assertEqual(self.draft().page, 1)
        await self.click('Berries')
        self.assertEqual(self.draft().page, 0)
        await self.click('Evolution')
        await self.click('Next')
        await self.click('EX')
        self.assertEqual(self.draft().page, 0)
        self.assertTrue(self.draft().ex)
        self.assertEqual(len(self.payload()[2]['components'][0]['options']), 6)

    async def test_largest_page_25_labels(self):
        await self.open()
        await self.click('Evolution')
        options = self.payload()[2]['components'][0]['options']
        self.assertEqual(len(options), 25)
        self.assertEqual([o['label'] for o in options],
                         [next(e['name_en'] for e in self.bot.content['evolution_items'] if e['id'] == o['value'])
                          for o in options])
        await self.click('Next')
        self.assertEqual(len(self.payload()[2]['components'][0]['options']), 25)

    async def test_change_new_revision_and_send_id(self):
        await self.open()
        draft = self.draft()
        previous = (draft.revision, draft.send_id)
        for label, value in (('Choose item', 'poke_ball'), ('Choose item', 'poke_ball'),
                             ('Choose slot', '0'), ('Remove', None), ('Clear', None)):
            await self.click(label, value)
            current = (draft.revision, draft.send_id)
            if label == 'Choose slot':
                self.assertEqual(current, previous)
            else:
                self.assertEqual(current[0], previous[0] + 1)
                self.assertNotEqual(current[1], previous[1])
                self.assertIsNone(draft.picked)
            previous = current

    async def test_forged_callback_changes_nothing(self):
        await self.open()
        draft = self.draft()
        before = (draft.revision, draft.send_id, list(draft.slots), self.payload())
        for owner, guild in ((457, 123), (999, 123), (456, 999), (456, None)):
            refused = await self.click('Choose item', 'poke_ball', interaction=self.interaction(owner=owner, guild=guild))
            refused.edit_original_response.assert_not_awaited()
            refused.followup.send.assert_awaited_once()
        await self.pick('not_an_item')
        await self.pick('shiny_patch')  # A known item outside the displayed ordinary page.
        self.assertEqual((draft.revision, draft.send_id, draft.slots, self.payload()), before)

    async def test_exclusion_after_open_refuses(self):
        await self.open()
        before = self.payload()
        await self.bot.db.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        reply = await self.pick()
        self.assertIn('Excluded', self.reply_text(reply))
        self.assertEqual(self.draft().slots, [])
        self.assertEqual(self.payload(), before)

    async def test_bucket_30_shared_by_drafts(self):
        await self.open()
        first = self.draft()
        await self.open()
        second = self.draft()
        for n in range(30):
            await self.click('Berries', draft=first if n % 2 else second)
        reply = await self.pick()
        self.assertIn('60 s', self.reply_text(reply))
        self.assertEqual(second.slots, [])
        self.clock += 60
        await self.pick('razz_berry')
        self.assertEqual(second.slots, ['razz_berry'])

    async def test_deadline_absolute(self):
        await self.open()
        draft = self.draft()
        deadline = draft.deadline
        self.clock += 899
        await self.pick('not_an_item')
        self.assertLessEqual(draft.view.timeout, 1)
        await self.pick()
        self.assertEqual(draft.deadline, deadline)
        self.assertLessEqual(draft.view.timeout, 1)
        self.clock += 1
        reply = await self.click('Preview')
        self.assertEqual(self.reply_text(reply),
                         'This gift draft expired. Run /admin gift again.')
        self.assertEqual(draft.state, 'discarded')
        self.assertEqual(self.group.gift_drafts, {})
        self.assertTrue(draft.view.is_finished())

    async def test_preview_contents_and_zero_line(self):
        for scope, guild, user, counts in (('all', None, None, (2, 2, 2)),
                ('server', '123', '456', (1, 1, 1)), ('server', '123', None, (1, 0, 0))):
            if counts[-1] == 0:
                await self.bot.db.execute("DELETE FROM profiles WHERE guild_id='123'")
            await self.open(scope, guild, user)
            await self.pick()
            draft = self.draft()
            previous = (draft.revision, draft.send_id)
            reply = await self.click('Preview')
            text = reply.edit_original_response.await_args.kwargs['content']
            for value in (draft.send_id, 'Scope: ' + ('user' if user else scope), '1. Poké Ball',
                          f'Targeted servers: {counts[0]}', f'Servers with recipients: {counts[1]}',
                          f'Recipients: {counts[2]}', 'provisional'):
                self.assertIn(value, text)
            if guild:
                self.assertIn(f'Server ID: {guild}', text)
            if user:
                self.assertIn(f'User ID: {user}', text)
            self.assertEqual('No enrolled recipients: nothing can be sent.' in text, counts[-1] == 0)
            self.assertEqual([c['label'] for r in self.payload() for c in r['components']], ['Edit', 'Cancel'])
            await self.click('Edit')
            self.assertEqual((draft.revision, draft.send_id), previous)
            self.assertEqual(len(self.payload()), 5)

    async def test_retained_controls_after_discard_change_nothing(self):
        from pokewalker.bot import admin_gift
        for ending in ('Cancel', 'timeout', 'awaited_discard', 'awaited_sending'):
            await self.open('server', '123', '456')
            draft = self.draft()
            item = self.control('Choose item')
            if ending == 'Cancel':
                reply = await self.click('Cancel')
                self.assertIsNone(reply.edit_original_response.await_args.kwargs['view'])
            elif ending == 'timeout':
                await draft.view.on_timeout()
            else:
                original = self.group.excluded
                async def changed(conn, interaction):
                    result = await original(conn, interaction)
                    if ending == 'awaited_discard':
                        admin_gift.discard(draft)
                    else:
                        draft.state = 'sending'
                    return result
                with patch.object(self.group, 'excluded', side_effect=changed):
                    await self.click('Choose item', 'poke_ball', draft=draft, control=item)
                if ending == 'awaited_sending':
                    self.assertEqual(draft.slots, [])
                    admin_gift.discard(draft)
            before = (draft.revision, draft.send_id, list(draft.slots))
            await self.click('Choose item', 'poke_ball', draft=draft, control=item)
            self.assertEqual((draft.revision, draft.send_id, draft.slots), before)
            self.assertIsNone(draft.guild_id)
            self.assertIsNone(draft.user_id)
            self.assertNotIn(draft.draft_id, self.group.gift_drafts)
            self.assertTrue(draft.view.is_finished())
