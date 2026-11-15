"""EXG-5/EXG-6 manager payloads and synthetic callbacks over real SQLite."""

import asyncio
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
        from pokewalker.services import marker_log
        marker_log.create_empty(self.settings.marker_log_path)
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
        interaction.data = {'custom_id': item.custom_id}
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
            self.assertEqual([c['label'] for r in self.payload() for c in r['components']], ['Confirm', 'Edit', 'Cancel'])
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
                    # This synthetic sending state has no settlement task.
                    draft.state = 'editing'
                    admin_gift.discard(draft)
            before = (draft.revision, draft.send_id, list(draft.slots))
            await self.click('Choose item', 'poke_ball', draft=draft, control=item)
            self.assertEqual((draft.revision, draft.send_id, draft.slots), before)
            self.assertIsNone(draft.guild_id)
            self.assertIsNone(draft.user_id)
            self.assertNotIn(draft.draft_id, self.group.gift_drafts)
            self.assertTrue(draft.view.is_finished())


    async def preview(self, **kwargs):
        await self.open(**kwargs)
        await self.pick()
        await self.click('Preview')
        self.assertIn('Confirm', [getattr(item, 'label', None) for item in self.draft().view.children])
        return self.draft(), self.control('Confirm')

    async def gifts(self):
        async with self.bot.db.execute('SELECT gift_id,recipients FROM ex_gifts') as cursor:
            return [tuple(row) for row in await cursor.fetchall()]

    async def queued_confirm(self, draft, control, *, before_queue=False):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.bot.writer.run
        async def blocker(conn):
            entered.set()
            await release.wait()
        async def run(fn, **kwargs):
            if kwargs.get('after_commit') is not None and before_queue:
                entered.set()
                await release.wait()
            elif kwargs.get('after_commit') is not None:
                holding = asyncio.create_task(original(blocker))
                async def finish_blocker():
                    await holding
                self.addAsyncCleanup(finish_blocker)
                await entered.wait()
            return await original(fn, **kwargs)
        patched = patch.object(self.bot.writer, 'run', side_effect=run)
        patched.start()
        self.addCleanup(patched.stop)
        self.addCleanup(release.set)
        task = asyncio.create_task(self.click('Confirm', draft=draft, control=control))
        await entered.wait()
        await asyncio.sleep(0)
        return task, release

    async def delete_target(self, guild='123', user='456', kind='delete', **kwargs):
        from pokewalker.services import deletion
        return await deletion.run_marker(self.bot.writer, self.settings.marker_log_path,
            kind=kind, guild_id=guild, user_id=user, now=100, **kwargs)

    async def reenrol(self, conn):
        await conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                           "VALUES ('replacement','123','456',100)")

    def assert_discarded(self, draft):
        self.assertEqual(draft.state, 'discarded')
        self.assertNotIn(draft.draft_id, self.group.gift_drafts)
        self.assertTrue(draft.view.is_finished())
        self.assertIsNone(draft.guild_id)
        self.assertIsNone(draft.user_id)
        self.assertFalse(hasattr(draft, 'result'))

    async def test_new_bot_registers_drafts_without_error(self):
        from pokewalker.services import deletion
        self.assertIsInstance(self.group.gift_drafts, dict)
        self.assertIs(deletion._listeners[id(self.group.gift_drafts)], self.group.gift_drafts)
        await self.open()
        self.assertEqual(len(self.group.gift_drafts), 1)

    async def test_delete_discards_matching_one_user_drafts_only(self):
        await self.bot.db.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                  "VALUES ('c','999','456',0),('d','123','789',0)")
        drafts = []
        for scope, guild, user in (('server', '123', '456'), ('server', '123', '456'),
                ('server', '999', '456'), ('server', '123', '789'),
                ('server', '123', None), ('all', None, None)):
            self.group.requests.clear()
            await self.open(scope, guild, user)
            drafts.append(self.draft())
        await self.delete_target()
        for draft in drafts[:2]:
            self.assert_discarded(draft)
        for draft in drafts[2:]:
            self.assertIs(self.group.gift_drafts[draft.draft_id], draft)
            self.assertEqual(draft.state, 'editing')
            self.assertFalse(draft.view.is_finished())

    async def test_delete_opt_out_reset_discard_targeting_drafts(self):
        for kind in ('delete', 'reset', 'opt_out'):
            with self.subTest(kind=kind):
                self.group.requests.clear()
                await self.open('server', '123', '456')
                draft = self.draft()
                fields = {'actor_id': '456', 'reason': 'test reset'} if kind == 'reset' else {}
                await self.delete_target(kind=kind, **fields)
                self.assert_discarded(draft)
                if kind != 'opt_out':
                    await self.bot.writer.run(self.reenrol)

    async def test_delete_and_reenrol_while_confirm_waits_sends_nothing(self):
        draft, confirm = await self.preview(scope='server', server_id='123', user_id='456')
        original = self.bot.writer.run
        entered, release = asyncio.Event(), asyncio.Event()
        self.addCleanup(release.set)
        waiting = True
        async def run(fn, **kwargs):
            nonlocal waiting
            result = await original(fn, **kwargs)
            if waiting:
                waiting = False
                entered.set()
                await release.wait()
            return result
        with patch.object(self.bot.writer, 'run', side_effect=run):
            task = asyncio.create_task(self.click('Confirm', draft=draft, control=confirm))
            await entered.wait()
            self.assertEqual(draft.state, 'editing')
            await self.delete_target()
            await original(self.reenrol)
            release.set()
            reply = await task
        self.assert_discarded(draft)
        self.assertIn('expired', self.reply_text(reply))
        self.assertEqual(await self.gifts(), [])
        async with self.bot.db.execute('SELECT count(*) FROM ex_gift_recipients') as cursor:
            self.assertEqual((await cursor.fetchone())[0], 0)

    async def test_delete_and_reenrol_while_send_job_queued_sends_nothing(self):
        draft, confirm = await self.preview(scope='server', server_id='123', user_id='456')
        original = self.bot.writer.run
        entered, release = asyncio.Event(), asyncio.Event()
        self.addCleanup(release.set)
        async def authorize(conn):
            entered.set()
            await release.wait()
        async def run(fn, **kwargs):
            if kwargs.get('after_commit') is None:
                return await original(fn, **kwargs)
            deleting = asyncio.create_task(self.delete_target(authorize=authorize))
            await entered.wait()
            enrolling = asyncio.create_task(original(self.reenrol))
            await asyncio.sleep(0)
            sending = asyncio.create_task(original(fn, **kwargs))
            await asyncio.sleep(0)
            self.assertEqual(self.bot.writer._queue.qsize(), 2)
            self.assertEqual(draft.state, 'sending')
            release.set()
            await deleting
            await enrolling
            return await sending
        with patch.object(self.bot.writer, 'run', side_effect=run):
            reply = await self.click('Confirm', draft=draft, control=confirm)
        self.assert_discarded(draft)
        self.assertEqual(self.reply_text(reply), 'Nothing was sent.')
        self.assertEqual(await self.gifts(), [])
        async with self.bot.db.execute('SELECT count(*) FROM ex_gift_recipients') as cursor:
            self.assertEqual((await cursor.fetchone())[0], 0)
        async with self.bot.db.execute("SELECT profile_id FROM profiles WHERE user_id='456'") as cursor:
            self.assertEqual((await cursor.fetchone())[0], 'replacement')

    async def test_retained_controls_after_delete_change_nothing(self):
        draft, confirm = await self.preview(scope='server', server_id='123', user_id='456')
        await self.click('Edit')
        pick = self.control('Choose item')
        await self.click('Preview')
        controls = [confirm, pick, self.control('Edit'), self.control('Cancel')]
        await self.delete_target()
        before = (draft.revision, draft.send_id, list(draft.slots), await self.snapshot())
        for control in controls:
            reply = await self.click('retained', draft=draft, control=control, value='poke_ball')
            self.assertIn('expired', self.reply_text(reply))
        self.assertEqual((draft.revision, draft.send_id, draft.slots, await self.snapshot()), before)
        self.assert_discarded(draft)

    async def test_deleted_recipient_id_absent_owner_id_kept(self):
        import logging
        from unittest.mock import Mock
        handler = logging.StreamHandler()
        handler.emit = Mock()
        root = logging.getLogger()
        self.addCleanup(root.setLevel, root.level)
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        self.addCleanup(root.removeHandler, handler)
        recipient = '876543210987654321'
        await self.bot.db.execute("UPDATE profiles SET user_id=? WHERE profile_id='b'", (recipient,))
        draft, confirm = await self.preview(scope='server', server_id='999', user_id=recipient)
        await self.click('Confirm', draft=draft, control=confirm)
        self.assertEqual(await self.gifts(), [(draft.send_id, 1)])
        await self.delete_target('999', recipient)
        self.assert_discarded(draft)
        for table in ('ex_gifts', 'ex_gift_recipients', 'ex_items', 'action_receipts', 'resource_ledger'):
            async with self.bot.db.execute(f'SELECT * FROM {table}') as cursor:
                rows = [tuple(row) for row in await cursor.fetchall()]
            self.assertNotIn(recipient, json.dumps(rows), table)
            if table in ('ex_gift_recipients', 'ex_items'):
                self.assertEqual(rows, [])
        async with self.bot.db.execute('SELECT owner_id FROM ex_gifts WHERE gift_id=?',
                                       (draft.send_id,)) as cursor:
            self.assertEqual((await cursor.fetchone())[0], '456')
        for call in handler.emit.call_args_list:
            self.assertNotIn(recipient, call.args[0].getMessage())

    async def test_confirm_sends_once_receipt_has_counts_no_components(self):
        draft, confirm = await self.preview(scope='server', server_id='123', user_id='456')
        reply = await self.click('Confirm')
        text = self.reply_text(reply)
        for value in (draft.send_id, 'Scope: user', 'Server ID: 123', 'User ID: 456',
                      '1. Pok\u00e9 Ball', 'Counts (committed)', 'Targeted servers: 1',
                      'Servers with recipients: 1', 'Recipients: 1'):
            self.assertIn(value, text)
        self.assertIsNone(reply.edit_original_response.await_args.kwargs['view'])
        self.assertEqual(draft.state, 'sent')
        self.assertIs(self.group.gift_drafts[draft.draft_id], draft)
        await self.click('Confirm', control=confirm)
        self.assertEqual(await self.gifts(), [(draft.send_id, 1)])

    async def test_confirm_takes_authorize_bucket_token(self):
        draft, confirm = await self.preview()
        for _ in range(4):
            self.group.throttled(self.group.requests, 456, 5)
        reply = await self.click('Confirm')
        self.assertIn('Slow down', self.reply_text(reply))
        self.assertEqual(await self.gifts(), [])
        self.assertEqual(draft.state, 'editing')
        self.clock += 60
        for _ in range(30):
            self.group.throttled(self.group.gift_callbacks, 456, 30)
        await self.click('Confirm', control=confirm)
        self.assertEqual(len(self.group.requests[456]), 1)
        self.assertEqual(draft.state, 'sent')

    async def test_lost_response_retry_and_stale_click_return_same_send(self):
        draft, confirm = await self.preview()
        await self.click('Edit')
        pick = self.control('Choose item')
        await self.click('Preview')
        lost = self.interaction()
        lost.edit_original_response.side_effect = RuntimeError('lost response')
        with self.assertRaisesRegex(RuntimeError, 'lost response'):
            await self.click('Confirm', interaction=lost)
        receipt = draft.result
        for item in (confirm, pick):
            reply = await self.click('retained', draft=draft, control=item)
            self.assertIn(draft.send_id, self.reply_text(reply))
            self.assertIsNone(reply.edit_original_response.await_args.kwargs['view'])
            self.assertIs(draft.result, receipt)
        self.assertEqual(await self.gifts(), [(draft.send_id, 2)])

    async def test_stale_preview_revision_refused(self):
        draft, old = await self.preview()
        await self.click('Edit')
        await self.pick()
        reply = await self.click('Confirm', control=old)
        self.assertEqual(self.reply_text(reply), 'The package changed. Preview it again.')
        self.assertEqual(draft.state, 'editing')
        self.assertEqual(await self.gifts(), [])
        await self.click('Preview')
        await self.click('Confirm')
        reply = await self.click('Confirm', control=old)
        self.assertIn(draft.send_id, self.reply_text(reply))
        self.assertEqual(await self.gifts(), [(draft.send_id, 2)])

    async def test_edit_cancel_and_picks_refused_while_sending(self):
        draft, confirm = await self.preview()
        await self.click('Edit')
        controls = [self.control(label) for label in ('Choose item', 'Choose slot', 'Clear')]
        await self.click('Preview')
        controls += [self.control(label) for label in ('Edit', 'Cancel')]
        task, release = await self.queued_confirm(draft, confirm, before_queue=True)
        before = (draft.revision, draft.send_id, list(draft.slots))
        for control in controls + [confirm]:
            reply = await self.click('retained', control=control)
            self.assertEqual(self.reply_text(reply), 'This gift is being sent.')
        self.assertEqual((draft.revision, draft.send_id, draft.slots), before)
        release.set()
        await task
        for control in controls:
            reply = await self.click('retained', control=control)
            self.assertIn(draft.send_id, self.reply_text(reply))
            self.assertEqual(draft.state, 'sent')

    async def test_delayed_pick_racing_confirm_keeps_package_and_receipt(self):
        draft, confirm = await self.preview()
        await self.click('Edit')
        pick = self.control('Choose item')
        await self.click('Preview')
        original = draft.view.editable
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(interaction):
            if interaction is slow:
                entered.set()
                await release.wait()
            return await original(interaction)
        slow = self.interaction()
        pick._values = ['poke_ball']
        with patch.object(draft.view, 'editable', side_effect=delayed):
            task = asyncio.create_task(self.click('retained', interaction=slow, control=pick))
            await entered.wait()
            sent = await self.click('Confirm', control=confirm)
            release.set()
            await task
        self.assertEqual(draft.slots, ['poke_ball'])
        self.assertEqual(self.reply_text(slow), self.reply_text(sent))
        self.assertEqual(await self.gifts(), [(draft.send_id, 2)])

    async def test_confirm_queued_past_deadline_sends_nothing(self):
        draft, confirm = await self.preview()
        task, release = await self.queued_confirm(draft, confirm)
        self.clock = draft.deadline
        release.set()
        reply = await task
        self.assertIn('Nothing was sent.', self.reply_text(reply))
        self.assertEqual(draft.state, 'discarded')
        self.assertEqual(await self.gifts(), [])

    async def test_expiry_during_send_rolls_back(self):
        from pokewalker.services import ex_gift
        draft, confirm = await self.preview()
        original = ex_gift.send
        async def send(conn, **kwargs):
            result = await original(conn, **kwargs)
            self.clock = draft.deadline
            return result
        with patch.object(ex_gift, 'send', side_effect=send):
            reply = await self.click('Confirm')
        self.assertIn('Nothing was sent.', self.reply_text(reply))
        self.assertEqual(draft.state, 'discarded')
        self.assertEqual(await self.gifts(), [])
        async with self.bot.db.execute('SELECT count(*) FROM ex_gift_recipients') as cursor:
            self.assertEqual((await cursor.fetchone())[0], 0)

    async def test_cancel_while_job_queued_sends_nothing(self):
        from pokewalker.bot.admin_gift import discard
        draft, confirm = await self.preview()
        task, release = await self.queued_confirm(draft, confirm)
        discard(draft)
        release.set()
        await task
        self.assertEqual(draft.state, 'discarded')
        self.assertEqual(await self.gifts(), [])

    async def test_rollback_keeps_revision_and_send_id(self):
        from pokewalker.services import ex_gift
        draft, confirm = await self.preview()
        before = (draft.revision, draft.send_id)
        original = ex_gift.send
        async def broken(conn, **kwargs):
            await original(conn, **kwargs)
            raise RuntimeError('rollback')
        with patch.object(ex_gift, 'send', side_effect=broken):
            reply = await self.click('Confirm')
        self.assertIn('Nothing was sent.', self.reply_text(reply))
        self.assertEqual((draft.state, draft.revision, draft.send_id), ('editing', *before))
        self.assertEqual(await self.gifts(), [])
        await self.click('Confirm', control=confirm)
        self.assertEqual(await self.gifts(), [(before[1], 2)])

    async def test_cancelled_callback_then_commit_then_retry_returns_receipt(self):
        draft, confirm = await self.preview()
        task, release = await self.queued_confirm(draft, confirm)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(draft.state, 'sending')
        release.set()
        await draft.task
        reply = await self.click('Confirm', control=confirm)
        self.assertEqual(draft.state, 'sent')
        self.assertIn(draft.send_id, self.reply_text(reply))
        self.assertEqual(await self.gifts(), [(draft.send_id, 2)])

    async def test_cancelled_callback_then_rollback_restores_editing(self):
        from pokewalker.bot.admin_gift import discard
        from pokewalker.services import ex_gift
        original = ex_gift.send
        for discarded in (False, True):
            self.group.requests.clear()
            draft, confirm = await self.preview()
            entered, release = asyncio.Event(), asyncio.Event()
            async def broken(conn, **kwargs):
                await original(conn, **kwargs)
                entered.set()
                await release.wait()
                raise RuntimeError('rollback')
            with patch.object(ex_gift, 'send', side_effect=broken):
                task = asyncio.create_task(self.click('Confirm'))
                await entered.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                if discarded:
                    discard(draft)
                release.set()
                await draft.task
            self.assertEqual(draft.state, 'discarded' if discarded else 'editing')
            self.assertEqual(await self.gifts(), [])

    async def test_exclusion_after_preview_refused(self):
        draft, confirm = await self.preview()
        await self.bot.db.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        reply = await self.click('Confirm')
        self.assertIn('Excluded', self.reply_text(reply))
        self.assertEqual(draft.state, 'editing')
        self.assertEqual(await self.gifts(), [])
        await self.bot.db.execute('DELETE FROM restrictions')
        original = self.group.excluded
        async def exclude_after_check(conn, interaction):
            result = await original(conn, interaction)
            await conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
            return result
        with patch.object(self.group, 'excluded', side_effect=exclude_after_check):
            reply = await self.click('Confirm')
        self.assertIn('Nothing was sent.', self.reply_text(reply))
        self.assertEqual(draft.state, 'editing')
        self.assertEqual(await self.gifts(), [])

    async def test_zero_recipients_refused_at_commit(self):
        draft, confirm = await self.preview(scope='server', server_id='123')
        await self.bot.db.execute("DELETE FROM profiles WHERE guild_id='123'")
        reply = await self.click('Confirm')
        self.assertIn('Nothing was sent.', self.reply_text(reply))
        self.assertEqual(draft.state, 'editing')
        self.assertEqual(await self.gifts(), [])

    async def test_two_identical_one_user_drafts_one_commits(self):
        first, confirm = await self.preview(scope='server', server_id='123', user_id='456')
        second, _ = await self.preview(scope='server', server_id='123', user_id='456')
        await self.click('Confirm', draft=first, control=confirm)
        self.assertEqual(await self.gifts(), [(first.send_id, 1)])
        self.assertEqual(second.state, 'editing')
        self.assertEqual(second.slots, first.slots)

    async def test_old_control_after_restart_cannot_send(self):
        from pokewalker.bot.client import WalkerBot
        from pokewalker.db import Writer, open_db
        draft, confirm = await self.preview()
        message_id = 111
        self.bot._connection.store_view(draft.view, message_id)
        self.assertTrue(self.bot._connection._view_store._views)
        await self.bot.drain()
        restarted = WalkerBot(self.settings, clock=lambda: self.clock)
        self.addAsyncCleanup(restarted.drain)
        restarted.db = await open_db(self.settings.db_path, allow_unpatched=True)
        restarted.writer = Writer(restarted.db)
        fresh = restarted.tree.get_command('admin', guild=discord.Object(id=123))
        interaction = self.interaction()
        interaction.message = SimpleNamespace(id=message_id, interaction_metadata=None)
        restarted._connection._view_store.dispatch_view(2, confirm.custom_id, interaction)
        await asyncio.sleep(0)
        interaction.response.defer.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()
        self.assertEqual(fresh.gift_drafts, {})
        async with restarted.db.execute('SELECT count(*) FROM ex_gifts') as cursor:
            self.assertEqual((await cursor.fetchone())[0], 0)


    async def test_writer_cancellation_rollback_restores_editing(self):
        from pokewalker.services import ex_gift
        draft, confirm = await self.preview()
        original = ex_gift.send
        async def cancelled(conn, **kwargs):
            await original(conn, **kwargs)
            raise asyncio.CancelledError
        with patch.object(ex_gift, 'send', side_effect=cancelled):
            reply = await self.click('Confirm')
        self.assertEqual(draft.state, 'editing')
        self.assertIn('Nothing was sent.', self.reply_text(reply))
        self.assertEqual(await self.gifts(), [])


    async def test_timeout_during_commit_keeps_send_and_receipt_target(self):
        draft, confirm = await self.preview(scope='server', server_id='123', user_id='456')
        original = self.bot.db.commit
        async def expire_before_commit():
            if draft.state == 'sending':
                self.clock = draft.deadline
                await draft.view.on_timeout()
            await original()
        with patch.object(self.bot.db, 'commit', side_effect=expire_before_commit):
            reply = await self.click('Confirm', control=confirm)
        self.assertEqual(await self.gifts(), [(draft.send_id, 1)])
        text = self.reply_text(reply)
        for value in (draft.send_id, 'Scope: user', 'Server ID: 123', 'User ID: 456',
                      '1. Pok\u00e9 Ball', 'Counts (committed)', 'Recipients: 1'):
            self.assertIn(value, text)
        self.assertIsNone(reply.edit_original_response.await_args.kwargs['view'])
        self.assertEqual(draft.state, 'discarded')
        self.assertNotIn(draft.draft_id, self.group.gift_drafts)
        self.assertTrue(draft.view.is_finished())
        self.assertIsNone(draft.guild_id)
        self.assertIsNone(draft.user_id)
        self.assertFalse(hasattr(draft, 'result'))

    async def test_pending_discard_or_expiry_cleans_up_any_outcome(self):
        from pokewalker.bot.admin_gift import discard
        from pokewalker.services import ex_gift
        send, commit = ex_gift.send, self.bot.db.commit
        for ending in ('discard', 'expiry'):
            for outcome in ('refusal', 'rollback', 'expired', 'sent'):
                with self.subTest(ending=ending, outcome=outcome):
                    self.group.requests.clear()
                    self.group.gift_callbacks.clear()
                    draft, confirm = await self.preview(scope='server', server_id='123', user_id='456')
                    before = (draft.revision, draft.send_id)
                    pending = []
                    async def end():
                        if ending == 'discard':
                            discard(draft)
                            pending.append((getattr(draft, 'discard_pending', False), draft.state,
                                self.group.gift_drafts.get(draft.draft_id) is draft,
                                draft.guild_id, draft.user_id))
                        else:
                            self.clock = draft.deadline
                    async def result(conn, **kwargs):
                        if outcome == 'refusal':
                            return {'status': 'no_recipients'}
                        result = await send(conn, **kwargs)
                        if outcome != 'sent':
                            await end()
                            if outcome == 'rollback':
                                raise RuntimeError('rollback')
                        return result
                    async def finish_commit():
                        if draft.state == 'sending' and outcome in ('sent', 'refusal'):
                            await end()
                        await commit()
                    with patch.object(ex_gift, 'send', side_effect=result), patch.object(
                            self.bot.db, 'commit', side_effect=finish_commit):
                        reply = await self.click('Confirm', control=confirm)
                    if ending == 'discard':
                        self.assertEqual(pending, [(True, 'sending', True, 123, 456)])
                    self.assertEqual((draft.revision, draft.send_id), before)
                    self.assertEqual(draft.state, 'discarded')
                    self.assertNotIn(draft.draft_id, self.group.gift_drafts)
                    self.assertTrue(draft.view.is_finished())
                    self.assertIsNone(draft.guild_id)
                    self.assertIsNone(draft.user_id)
                    self.assertFalse(hasattr(draft, 'result'))
                    gifts = await self.gifts()
                    self.assertEqual((draft.send_id, 1) in gifts, outcome == 'sent')
                    if outcome == 'sent':
                        self.assertIn('User ID: 456', self.reply_text(reply))
                        self.assertIsNone(reply.edit_original_response.await_args.kwargs['view'])
                    else:
                        self.assertEqual(self.reply_text(reply), 'Nothing was sent.')
