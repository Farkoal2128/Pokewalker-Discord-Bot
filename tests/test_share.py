"""M4.4 public sharing through the real writer/router and synthetic Discord I/O."""

import asyncio
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import discord

import test_catching as catching
from pokewalker.bot import screens


class ShareTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = catching.CatchingTests.asyncSetUp
    rows = catching.CatchingTests.rows
    open = catching.CatchingTests.open
    click = catching.CatchingTests.click
    enroll = catching.CatchingTests.enroll
    exclude = catching.CatchingTests.exclude
    ready = catching.CatchingTests.ready
    current = catching.CatchingTests.current
    reveal = catching.CatchingTests.reveal
    prepared = catching.CatchingTests.prepared

    def interaction(self, **kwargs):
        interaction = catching.CatchingTests.interaction(self, **kwargs)
        interaction.user.display_name = 'Player @everyone'
        permissions = SimpleNamespace(embed_links=True, send_messages=True, send_messages_in_threads=True)
        if not hasattr(self, 'channel'):
            self.channel = SimpleNamespace(id=789, parent_id=None, permissions_for=Mock(return_value=permissions),
                                           send=AsyncMock())
        interaction.channel = self.channel
        interaction.guild = SimpleNamespace(me=SimpleNamespace(id=42))
        return interaction

    async def caught(self):
        session = await self.prepared(shiny=1, gender='female')
        self.walker.rng = Mock(random=Mock(return_value=0))
        interaction = await self.click(session, 'throw')
        await catching.store_legacy(self.writer, self.encounter['encounter_id'], 1000)
        self.uid = (await self.rows("SELECT pokemon_uid FROM pokemon WHERE origin='catch'"))[0]['pokemon_uid']
        return interaction, await self.current(session)

    async def detail(self, session):
        await self.click(session, 'storage')
        interaction = await self.click(await self.current(session), 'storage_open', [self.uid])
        return interaction, await self.current(session)

    def rendered(self, interaction):
        return interaction.edit_original_response.await_args.kwargs

    def shares(self, rendered):
        return [item for item in rendered['view'].children if getattr(item, 'label', None) == 'Share']

    async def snapshot(self):
        return {table: await self.rows('SELECT * FROM ' + table) for table in
                ('profiles', 'sessions', 'action_receipts', 'pokemon')}

    async def refuse(self, session, expected, **kwargs):
        before = await self.snapshot()
        writes = self.conn.total_changes
        interaction = await self.click(session, 'share', **kwargs)
        self.assertIn(expected.lower(), interaction.followup.send.await_args.args[0].lower())
        self.assertTrue(interaction.followup.send.await_args.kwargs['ephemeral'])
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(self.conn.total_changes, writes)
        return interaction

    async def test_share_rendered_only_when_caught_owned_unbanned_sharing_on(self):
        interaction, session = await self.caught()
        self.assertEqual(self.shares(self.rendered(interaction)), [])
        encounter_id = json.loads(session['selection'])['encounter_id']
        interaction, session = await self.detail(session)
        self.assertFalse(self.shares(self.rendered(interaction))[0].disabled)
        await self.writer.run(lambda conn: conn.execute("UPDATE guilds SET sharing=0"))
        interaction = await self.click(session, 'storage_detail')
        self.assertEqual(self.shares(self.rendered(interaction)), [])
        state = await self.writer.run(lambda conn: self.walker.encounter_state(
            conn, session, encounter_id))
        self.assertEqual(self.shares(screens.render_terminal(state)), [])

    async def test_share_ban_removes_buttons_unban_restores(self):
        _, session = await self.caught()
        encounter_id = json.loads(session['selection'])['encounter_id']
        for banned in (1, 0):
            await self.writer.run(lambda conn: conn.execute(
                "INSERT INTO restrictions(guild_id,user_id,share_banned) VALUES ('123','456',?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET share_banned=excluded.share_banned", (banned,)))
            state = await self.writer.run(lambda conn: self.walker.encounter_state(conn, session, encounter_id))
            self.assertEqual(self.shares(screens.render_terminal(state)), [])
            interaction, session = await self.detail(session)
            self.assertEqual(len(self.shares(self.rendered(interaction))), 1 - banned)

    async def test_fled_and_ran_show_no_share(self):
        session = await self.prepared()
        for state in ('fled', 'ran'):
            await self.writer.run(lambda conn: conn.execute('UPDATE encounters SET state=?', (state,)))
            data = await self.writer.run(lambda conn: self.walker.encounter_state(
                conn, session, json.loads(session['selection'])['encounter_id']))
            self.assertEqual(self.shares(screens.render_terminal(data)), [])

    async def test_stored_catch_replayed_from_older_screen_has_no_share(self):
        first = await self.prepared()
        _, second = await self.open()
        _, second = await self.reveal(second)
        self.assertEqual(json.loads(first['selection'])['encounter_id'],
                         json.loads(second['selection'])['encounter_id'])
        self.walker.rng = Mock(random=Mock(return_value=0))
        await self.click(first, 'throw')
        await self.click(await self.current(first), 'ack')
        self.uid = (await self.rows("SELECT pokemon_uid FROM pokemon WHERE origin='catch'"))[0]['pokemon_uid']

        interaction = await self.click(second, 'throw')
        rendered = self.rendered(interaction)
        self.assertIn('caught', rendered['embed'].description)
        buttons = {button.label: button for button in rendered['view'].children}
        self.assertTrue(buttons['Done'].custom_id.endswith(':ack'))
        self.assertEqual(self.shares(rendered), [])
        interaction, _ = await self.detail(await self.current(first))
        self.assertEqual(len(self.shares(self.rendered(interaction))), 1)
        self.assertFalse(self.shares(self.rendered(interaction))[0].disabled)

    async def test_share_posts_one_public_embed_in_channel_no_mentions(self):
        _, session = await self.caught()
        interaction = await self.click(session, 'share')
        self.channel.send.assert_awaited_once()
        sent = self.channel.send.await_args.kwargs
        self.assertEqual(set(sent), {'embed', 'allowed_mentions'})
        self.assertEqual(sent['allowed_mentions'].to_dict()['parse'], [])
        self.assertIn('caught Pikachu', sent['embed'].title)
        self.assertIn('Shared', self.rendered(interaction)['content'])
        receipt = (await self.rows("SELECT * FROM action_receipts WHERE action='share'"))[0]
        self.assertEqual(receipt['profile_id'], session['profile_id'])
        self.assertEqual(receipt['key'], f"share:{session['session_id']}:{session['revision'] + 1}")
        self.assertEqual((await self.rows('SELECT last_share_at FROM profiles'))[0]['last_share_at'], 1000)

    async def test_after_commit_outside_writer_slow_send_not_blocking(self):
        _, session = await self.caught()
        started, release = asyncio.Event(), asyncio.Event()

        async def slow_send(**kwargs):
            self.assertIsNot(asyncio.current_task(), self.writer._task)
            self.assertFalse(self.conn.in_transaction)
            await self.writer.run(lambda conn: conn.execute('SELECT 1'))
            started.set()
            await release.wait()
        self.channel.send.side_effect = slow_send
        task = asyncio.create_task(self.click(session, 'share'))
        try:
            await asyncio.wait_for(started.wait(), 2)
            await asyncio.wait_for(self.writer.run(lambda conn: conn.execute('SELECT 1')), 2)
        finally:
            release.set()
            await task

    async def test_job_rollback_sends_nothing(self):
        _, session = await self.caught()
        await self.conn.execute("CREATE TRIGGER fail_session BEFORE UPDATE ON sessions "
                                "BEGIN SELECT RAISE(ABORT,'session failed'); END")
        before = await self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'session failed'):
            await self.click(session, 'share')
        self.assertEqual(await self.snapshot(), before)
        self.channel.send.assert_not_awaited()

    async def test_commit_failure_sends_nothing(self):
        _, session = await self.caught()
        before = await self.snapshot()
        with patch.object(self.conn, 'commit', side_effect=sqlite3.IntegrityError('commit failed')):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'commit failed'):
                await self.click(session, 'share')
        self.assertEqual(await self.snapshot(), before)
        self.channel.send.assert_not_awaited()

    async def test_embed_text_complete_without_image_when_sprite_null(self):
        _, session = await self.caught()
        identity = next(item for item in self.bot.content['identities'] if item['species_id'] == 25)
        identity['sprites']['shiny_female'] = None
        await self.click(session, 'share')
        embed = self.channel.send.await_args.kwargs['embed']
        self.assertIsNone(embed.image.url)
        for text in ('Pikachu', identity['kind'], 'female', 'Shiny', 'CP ', '456', '1970-01-01'):
            self.assertIn(text, embed.description)

    async def test_embed_image_exact_form_gender_shiny_sprite(self):
        _, session = await self.caught()
        candidates = [next(item for item in self.bot.content['identities'] if item['kind'] == 'regional')]
        candidates += [next(item for item in self.bot.content['identities'] if item['species_id'] == 25)]
        for identity in candidates:
            for shiny, gender in ((0, 'male'), (1, 'female')):
                await self.writer.run(lambda conn: conn.execute(
                    'UPDATE pokemon SET pokemon_id=?,shiny=?,gender=? WHERE pokemon_uid=?',
                    (identity['pokemon_id'], shiny, gender, self.uid)))
                self.walker.clock = lambda: self.now
                self.now = 1000 + 60 * self.channel.send.await_count
                await self.click(session, 'share')
                session = await self.current(session)
                key = ('shiny_female' if identity['has_gender_differences'] else 'shiny') if shiny else 'normal'
                self.assertEqual(self.channel.send.await_args.kwargs['embed'].image.url, identity['sprites'][key])

    async def test_sharing_off_ban_after_open_and_minute_cap_refused_in_transaction(self):
        _, session = await self.caught()
        await self.writer.run(lambda conn: conn.execute('UPDATE guilds SET sharing=0'))
        await self.refuse(session, 'sharing')
        await self.writer.run(lambda conn: conn.execute('UPDATE guilds SET sharing=1'))
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO restrictions(guild_id,user_id,share_banned) VALUES ('123','456',1)"))
        await self.refuse(session, 'banned')
        await self.writer.run(lambda conn: conn.execute('UPDATE restrictions SET share_banned=0'))
        await self.click(session, 'share')
        session = await self.current(session)
        self.walker.clock = lambda: 1059.999
        await self.refuse(session, 'minute')
        self.walker.clock = lambda: 1060
        await self.click(session, 'share')
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_missing_permission_explains_no_write(self):
        _, session = await self.caught()
        permissions = self.channel.permissions_for.return_value
        for permission in ('embed_links', 'send_messages'):
            setattr(permissions, permission, False)
            await self.refuse(session, 'permission')
            setattr(permissions, permission, True)
        self.channel.send.assert_not_awaited()

    async def test_thread_requires_send_messages_in_threads(self):
        _, session = await self.caught()
        self.channel.parent_id = 99
        permissions = self.channel.permissions_for.return_value
        permissions.send_messages_in_threads = False
        await self.refuse(session, 'send_messages_in_threads')
        permissions.send_messages_in_threads = True
        permissions.send_messages = False
        await self.click(session, 'share')
        self.channel.send.assert_awaited_once()

    async def test_double_click_second_stale_one_post(self):
        _, session = await self.caught()
        interactions = await asyncio.gather(self.click(session, 'share'), self.click(session, 'share'))
        self.channel.send.assert_awaited_once()
        self.assertEqual(sum(item.followup.send.await_count for item in interactions), 1)
        self.assertIn('stale', next(item.followup.send.await_args.args[0] for item in interactions
                                    if item.followup.send.await_count))

    async def test_send_failure_after_commit_explains_no_second_post(self):
        _, session = await self.caught()
        self.channel.send.side_effect = TimeoutError('possibly sent')
        interaction = await self.click(session, 'share')
        text = self.rendered(interaction)['content']
        self.assertIn('may already', text)
        self.assertIn('minute', text)
        await self.refuse(await self.current(session), 'minute')
        self.channel.send.assert_awaited_once()

    async def test_transport_and_rate_limit_failures_explain_spent_minute(self):
        _, session = await self.caught()
        for error in (aiohttp.ClientConnectionError('disconnected'), discord.RateLimited(60)):
            self.channel.send.side_effect = error
            self.walker.clock = lambda: self.now
            self.now = 1000 + 60 * self.channel.send.await_count
            interaction = await self.click(session, 'share')
            self.assertIn('may already', self.rendered(interaction)['content'])
            session = await self.current(session)
            await self.refuse(session, 'minute')
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_sent_pokemon_and_other_user_refused(self):
        _, session = await self.caught()
        await self.refuse(session, 'not yours', user=999)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET state='sent' WHERE pokemon_uid=?", (self.uid,)))
        await self.refuse(session, 'owned')
        state = await self.writer.run(lambda conn: self.walker.encounter_state(
            conn, session, json.loads(session['selection'])['encounter_id']))
        self.assertEqual(self.shares(screens.render_terminal(state)), [])
        self.channel.send.assert_not_awaited()

    async def test_storage_share_uses_selected_owned_pokemon(self):
        _, session = await self.caught()
        _, session = await self.detail(session)
        await self.click(session, 'share')
        self.assertIn('shares Pikachu', self.channel.send.await_args.kwargs['embed'].title)
        self.channel.send.assert_awaited_once()

    async def test_migration_preserves_existing_profile_and_starts_without_share_time(self):
        with sqlite3.connect(':memory:') as conn:
            migrations = Path('pokewalker/db/migrations')
            for migration in sorted(migrations.glob('*.sql')):
                if int(migration.name[:4]) < 10:
                    conn.executescript(migration.read_text(encoding='utf-8'))
            conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
            conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,stardust) "
                         "VALUES ('original','123','456',7,321)")
            conn.executescript((migrations / '0010_profiles_last_share.sql').read_text(encoding='utf-8'))
            self.assertEqual(conn.execute('SELECT profile_id,created_at,stardust,last_share_at FROM profiles').fetchone(),
                             ('original', 7, 321, None))

    async def test_receipt_replay_and_cancelled_send_do_not_retry_or_refund(self):
        _, session = await self.caught()
        started = asyncio.Event()

        async def pending(**kwargs):
            started.set()
            await asyncio.Future()
        self.channel.send.side_effect = pending
        task = asyncio.create_task(self.click(session, 'share'))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        session = await self.current(session)
        await self.refuse(session, 'minute')
        self.walker.clock = lambda: 1060
        # The direct handler replay exercises the durable reservation receipt.
        rendered = await self.writer.run(lambda conn: self.walker.handlers['share'](conn, session, self.interaction()))
        result = await rendered.pop('after_commit')()
        self.assertIn('already reserved', result['content'])
        self.assertEqual((await self.rows('SELECT last_share_at FROM profiles'))[0]['last_share_at'], 1000)
        self.channel.send.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
