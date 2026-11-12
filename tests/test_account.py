"""M4.1 account privacy and deletion using real serialized storage, no network."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pokewalker.bot import client, messages
from pokewalker.config import Secret, Settings
from pokewalker.db import Writer, open_db
from pokewalker.services import deletion, marker_log, profiles


class AccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache = Path("build/test-account")
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "markers.jsonl"
        marker_log.create_empty(self.path)
        self.privacy_path = self.root / "privacy.txt"
        self.owner_text = "Owner privacy text. " + "Details. " * 300
        self.privacy_path.write_text(self.owner_text, encoding="utf-8")
        self.conn = await open_db(":memory:", allow_unpatched=True)
        self.addAsyncCleanup(self.conn.close)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.content = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))
        self.bot = SimpleNamespace(writer=self.writer, content=self.content,
                                   settings=SimpleNamespace(marker_log_path=self.path),
                                   privacy_text=self.owner_text,
                                   help_page=lambda index: {'embed': None, 'view': None}, reactions=SimpleNamespace(
                                       reconcile_reaction=AsyncMock(), reconcile_message=AsyncMock(),
                                       remove_own=AsyncMock()))
        await self.conn.execute("INSERT INTO guilds(guild_id,enabled) VALUES ('123',1),('999',1)")

    def group(self):
        self.assertIsNotNone(importlib.util.find_spec("pokewalker.bot.account"),
                             "M4.1 private account controls must exist")
        return importlib.import_module("pokewalker.bot.account").WalkerAccount(self.bot)

    def interaction(self, guild=123):
        interaction = SimpleNamespace(guild_id=guild, user=SimpleNamespace(id=456),
                                      response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()),
                                      edit_original_response=AsyncMock())

        async def edit(**kwargs):
            self.assertFalse(self.conn.in_transaction, "Reply must follow commit")
        interaction.edit_original_response.side_effect = edit
        return interaction

    async def invoke(self, name, *, confirm=None, interaction=None):
        interaction = interaction or self.interaction()
        group = self.group()
        command = group.get_command(name)
        await command.callback(group, interaction, **({"confirm": confirm} if confirm is not None else {}))
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.response.send_message.assert_not_awaited()
        return interaction

    async def scalar(self, sql, args=()):
        async with self.conn.execute(sql, args) as cursor:
            row = await cursor.fetchone()
            return row[0] if row is not None else None

    async def enroll(self):
        return await self.writer.run(lambda conn: profiles.enroll(
            conn, "123", "456", 1, self.content, random.Random(8), datetime.now(timezone.utc)))

    async def exclude(self):
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET excluded=1"))

    def text(self, interaction):
        return interaction.edit_original_response.await_args.kwargs["content"]

    def records(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    async def test_privacy_replies_owner_text_for_excluded_too(self):
        for excluded in (False, True):
            if excluded:
                await self.exclude()
            interaction = await self.invoke("privacy")
            replies = [interaction.edit_original_response.await_args.kwargs]
            replies += [call.kwargs for call in interaction.followup.send.await_args_list]
            self.assertEqual("".join(reply["content"] for reply in replies), self.owner_text)
            for reply in replies:
                self.assertLessEqual(len(reply["content"]), 2000)
                self.assertFalse(reply["allowed_mentions"].everyone)
            for call in interaction.followup.send.await_args_list:
                self.assertTrue(call.kwargs["ephemeral"])
        self.assertEqual(self.path.read_bytes(), b"")

    async def test_privacy_splits_long_text_at_line_breaks(self):
        text = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(12))
        interaction = SimpleNamespace(edit_original_response=AsyncMock(),
                                      followup=SimpleNamespace(send=AsyncMock()))
        await importlib.import_module("pokewalker.bot.account").WalkerAccount(SimpleNamespace()).reply(interaction, text)
        parts = [interaction.edit_original_response.await_args.kwargs["content"]]
        parts += [call.kwargs["content"] for call in interaction.followup.send.await_args_list]
        self.assertEqual("".join(parts), text)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part), 2000)
        for part in parts[:-1]:
            self.assertTrue(part.endswith("\n"), part[-20:])

    async def test_delete_without_confirm_names_loss_changes_nothing(self):
        profile = await self.enroll()
        for name in ("delete-data", "opt-out"):
            interaction = await self.invoke(name)
            for word in ("Pokémon", "items", "progress", "moderation", "restrictions", "opt-out", "confirm"):
                self.assertIn(word, self.text(interaction))
            self.assertEqual(await self.scalar("SELECT profile_id FROM profiles"), profile["profile_id"])
            self.assertFalse(await deletion.opted_out(self.conn, "123", "456"))
        self.assertEqual(self.path.read_bytes(), b"")

    async def test_delete_confirm_writes_marker_then_deletes_reply_after_commit(self):
        profile = await self.enroll()
        synced, fsync = [], os.fsync

        def observe(fd):
            synced.append(self.path.read_bytes())
            fsync(fd)

        apply = deletion.apply

        async def observe_delete(conn, states):
            self.assertTrue(synced)
            self.assertEqual(json.loads(synced[-1])["profile_id"], profile["profile_id"])
            self.assertIsNotNone(await profiles.get_profile(conn, "123", "456"))
            await apply(conn, states)

        with patch("os.fsync", side_effect=observe), patch.object(deletion, "apply", side_effect=observe_delete):
            interaction = await self.invoke("delete-data", confirm=True)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(self.records()[0]["kind"], "delete")
        self.assertIn("deleted", self.text(interaction).lower())

    async def test_delete_then_reenroll_new_uuid_restrictions_apply(self):
        first = await self.enroll()
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,share_banned) "
                                "VALUES ('123','456',1,1)")
        await self.conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                                "VALUES ('123','7','user','456','pause','reason',0)")
        await self.invoke("delete-data", confirm=True)
        second = await self.enroll()
        self.assertNotEqual(first["profile_id"], second["profile_id"])
        flags = await profiles.restrictions(self.conn, "123", "456")
        self.assertTrue(flags.paused and flags.share_banned)
        self.assertEqual(await self.scalar("SELECT count(*) FROM mod_audit"), 1)
        await deletion.replay_markers(self.writer, self.path)
        self.assertEqual(await self.scalar("SELECT profile_id FROM profiles"), second["profile_id"])

    async def test_excluded_can_delete_data_and_opt_out(self):
        for name in ("delete-data", "opt-out"):
            await self.conn.execute("DELETE FROM restrictions")
            await self.enroll()
            await self.exclude()
            await self.invoke(name, confirm=True)
            self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
            self.assertTrue((await profiles.restrictions(self.conn, "123", "456")).excluded)
        self.assertEqual([r["kind"] for r in self.records()], ["delete", "opt_out"])

    async def test_excluded_opt_in_refused_no_marker_no_change(self):
        await self.invoke("opt-out", confirm=True)
        await self.exclude()
        before = self.path.read_bytes()
        interaction = await self.invoke("opt-in")
        self.assertIn("excluded", self.text(interaction).lower())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(await deletion.opted_out(self.conn, "123", "456"))

    async def test_queued_exclusion_then_opt_in_refused_no_marker_replay_keeps_opted_out(self):
        await self.invoke("opt-out", confirm=True)
        entered, release = asyncio.Event(), asyncio.Event()

        async def exclusion(conn):
            entered.set()
            await release.wait()
            await conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")

        pending = asyncio.create_task(self.writer.run(exclusion))
        await asyncio.wait_for(entered.wait(), 2)
        opting_in = asyncio.create_task(self.invoke("opt-in"))
        await asyncio.sleep(0)
        release.set()
        await pending
        interaction = await opting_in
        self.assertIn("excluded", self.text(interaction).lower())
        self.assertNotIn("opt_in", [r.get("kind") for r in self.records()])
        await self.conn.execute("DELETE FROM opt_outs")
        await deletion.replay_markers(self.writer, self.path)
        self.assertTrue(await deletion.opted_out(self.conn, "123", "456"))

    async def test_opt_out_deletes_data_writes_marker_stops_counting(self):
        await self.enroll()
        await self.conn.execute("INSERT INTO guild_channels VALUES ('123','789',1,1)")
        await self.invoke("opt-out", confirm=True)
        message = SimpleNamespace(author=SimpleNamespace(id=456, bot=False), webhook_id=None,
                                  guild=SimpleNamespace(id=123), channel=SimpleNamespace(id=789),
                                  id=1, content="three eligible words", created_at=datetime.now(timezone.utc))
        await messages.on_message(self.bot, message)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM encounters"), 0)
        self.assertTrue(await deletion.opted_out(self.conn, "123", "456"))
        self.assertEqual(self.records()[0]["kind"], "opt_out")
        self.bot.reactions.reconcile_reaction.assert_not_awaited()

    async def test_delete_and_opt_out_remove_own_reactions_of_deleted_profile(self):
        for name in ("delete-data", "opt-out"):
            with self.subTest(name=name):
                profile = await self.enroll()
                await self.conn.execute("INSERT INTO reactions(message_id,profile_id,channel_id,desired,actual,"
                                        "created_at) VALUES ('11',?,'21','add','added',0)", (profile["profile_id"],))
                self.bot.reactions.remove_own.reset_mock()
                await self.invoke(name, confirm=True)
                rows = self.bot.reactions.remove_own.await_args.args[0]
                self.assertEqual([(r["message_id"], r["channel_id"]) for r in rows], [("11", "21")])
                await self.writer.run(lambda conn: conn.execute("DELETE FROM opt_outs"))

    async def test_opt_out_without_profile_writes_marker_only(self):
        await self.invoke("opt-out", confirm=True)
        self.assertIsNone(self.records()[0]["profile_id"])
        self.assertTrue(await deletion.opted_out(self.conn, "123", "456"))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts"), 0)

    async def test_opted_out_walker_and_enroll_refused_until_opt_in(self):
        from pokewalker.bot.walker import Walker
        await self.invoke("opt-out", confirm=True)
        interaction = self.interaction()
        await Walker(self.bot).open(interaction)
        self.assertIn("/walker-account opt-in", self.text(interaction))
        self.assertEqual(await self.scalar("SELECT count(*) FROM sessions"), 0)
        with self.assertRaisesRegex(ValueError, "/walker-account opt-in"):
            await self.enroll()
        await self.invoke("opt-in")
        interaction = self.interaction()
        await Walker(self.bot).open(interaction)
        self.assertEqual(await self.scalar("SELECT count(*) FROM sessions"), 1)
        await self.enroll()

    async def test_existing_onboarding_session_after_opt_out_privately_refused_without_writes(self):
        from pokewalker.bot.walker import Walker
        walker = Walker(self.bot)
        await walker.open(self.interaction())

        async def session():
            async with self.conn.execute("SELECT * FROM sessions") as cursor:
                return dict(await cursor.fetchone())

        async def click(action):
            current = await session()
            interaction = self.interaction()
            interaction.data = {"values": ["1"]}
            await walker.route(interaction, f"pw:v1:{current['session_id']}:{current['revision']}:{action}")
            return interaction

        await click("onboard_gen")
        await click("onboard_pick")
        before = await session()
        await self.invoke("opt-out", confirm=True)
        self.assertEqual(await session(), before)
        changes = self.conn.total_changes
        for action in ("home", "onboard_gen", "onboard_pick", "onboard_confirm"):
            interaction = await click(action)
            reply = interaction.followup.send.await_args
            self.assertIsNotNone(reply, "Opted-out component must receive private guidance")
            self.assertIn("/walker-account opt-in", reply.args[0])
            self.assertTrue(reply.kwargs["ephemeral"])
            interaction.edit_original_response.assert_not_awaited()
            self.assertEqual(await session(), before)
            self.assertEqual(self.conn.total_changes, changes)
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts"), 0)
        await self.invoke("opt-in")
        await click("onboard_confirm")
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)

    async def test_existing_onboarding_session_exclusion_precedes_opt_out_refusal(self):
        from pokewalker.bot.walker import Walker
        walker = Walker(self.bot)
        await walker.open(self.interaction())
        await self.invoke("opt-out", confirm=True)
        await self.exclude()
        async with self.conn.execute("SELECT session_id FROM sessions") as cursor:
            session_id = (await cursor.fetchone())[0]
        interaction = self.interaction()
        await walker.route(interaction, f"pw:v1:{session_id}:0:home")
        self.assertIn("excluded", interaction.followup.send.await_args.args[0])
        self.assertTrue(interaction.followup.send.await_args.kwargs["ephemeral"])

    async def test_opt_in_writes_marker_clears_row_then_onboarding_fresh_uuid(self):
        first = await self.enroll()
        await self.invoke("opt-out", confirm=True)
        interaction = await self.invoke("opt-in")
        self.assertIn("/walker", self.text(interaction))
        self.assertFalse(await deletion.opted_out(self.conn, "123", "456"))
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)
        second = await self.enroll()
        await self.invoke("opt-in")
        self.assertNotEqual(first["profile_id"], second["profile_id"])
        self.assertEqual([r["kind"] for r in self.records()], ["opt_out", "opt_in", "opt_in"])

    async def test_commands_guild_only_ephemeral_local(self):
        settings = Settings(Secret("synthetic"), owner_ids=frozenset({123}))
        bot = client.WalkerBot(settings)
        self.addAsyncCleanup(bot.close)
        group = bot.tree.get_command("walker-account")
        self.assertIsNotNone(group)
        self.assertTrue(group.guild_only)
        self.assertIsNone(group.default_permissions)
        self.assertEqual({c.name for c in group.commands}, {"privacy", "delete-data", "opt-out", "opt-in"})
        for name in ("privacy", "delete-data", "opt-out", "opt-in"):
            interaction = await self.invoke(name, interaction=self.interaction(guild=None))
            self.assertIn("server", self.text(interaction))
        self.assertEqual(self.path.read_bytes(), b"")

    async def test_startup_refuses_without_privacy_text(self):
        settings = Settings(Secret("synthetic"), owner_ids=frozenset({123}))
        for path in (None, self.root / "absent.txt", self.root / "empty.txt"):
            (self.root / "empty.txt").write_text(" \n", encoding="utf-8")
            bot = client.WalkerBot(replace(settings, privacy_path=path))
            self.addAsyncCleanup(bot.close)
            with patch.object(client, "open_db", AsyncMock()) as opening:
                with self.assertRaisesRegex((ValueError, FileNotFoundError), "privacy|PRIVACY"):
                    await bot.setup_hook()
                opening.assert_not_awaited()
                self.assertFalse(bot.admitting)

    async def test_privacy_path_loaded_once_at_startup_and_from_env(self):
        with patch.dict(os.environ, {"DISCORD_TOKEN": "synthetic", "POKEWALKER_OWNER_IDS": "123",
                                    "POKEWALKER_PRIVACY_PATH": str(self.privacy_path)}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.privacy_path, self.privacy_path)
        bot = client.WalkerBot(settings)
        self.addAsyncCleanup(bot.close)
        with patch.object(client, "load_content", return_value=self.content), \
                patch.object(client, "open_db", AsyncMock(return_value=self.conn)), \
                patch.object(client, "Writer", return_value=self.writer), \
                patch.object(client, "replay_markers", AsyncMock()):
            await bot.setup_hook()
        self.privacy_path.unlink()
        interaction = self.interaction()
        group = bot.tree.get_command("walker-account")
        await group.get_command("privacy").callback(group, interaction)
        replies = [interaction.edit_original_response.await_args.kwargs["content"]]
        replies += [call.kwargs["content"] for call in interaction.followup.send.await_args_list]
        self.assertEqual("".join(replies), self.owner_text)

    async def test_queued_enrollment_then_delete_resolves_current_profile_inside_job(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def enrollment(conn):
            entered.set()
            await release.wait()
            return await profiles.enroll(conn, "123", "456", 1, self.content,
                                         random.Random(8), datetime.now(timezone.utc))

        pending = asyncio.create_task(self.writer.run(enrollment))
        await asyncio.wait_for(entered.wait(), 2)
        deleting = asyncio.create_task(self.invoke("delete-data", confirm=True))
        await asyncio.sleep(0)
        release.set()
        profile = await pending
        await deleting
        self.assertEqual(self.records()[0]["profile_id"], profile["profile_id"])
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 0)

    async def test_deletion_failure_voids_rolls_back_and_sends_no_success(self):
        await self.enroll()
        interaction = self.interaction()
        with patch.object(deletion, "apply", side_effect=RuntimeError("delete failed")):
            with self.assertRaisesRegex(RuntimeError, "delete failed"):
                await self.invoke("opt-out", confirm=True, interaction=interaction)
        interaction.edit_original_response.assert_not_awaited()
        self.assertEqual(await self.scalar("SELECT count(*) FROM profiles"), 1)
        self.assertFalse(await deletion.opted_out(self.conn, "123", "456"))
        self.assertEqual(marker_log.fold(self.path), {})

    async def test_opt_in_filesystem_permission_error_is_not_exclusion_or_success(self):
        interaction = self.interaction()
        with patch.object(deletion, "append_marker", side_effect=PermissionError("log denied")):
            with self.assertRaisesRegex(PermissionError, "log denied"):
                await self.invoke("opt-in", interaction=interaction)
        interaction.edit_original_response.assert_not_awaited()

    async def test_delete_only_current_server_and_retains_opt_out(self):
        await self.enroll()
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                                "VALUES ('elsewhere','999','456',0)")
        await self.invoke("opt-out", confirm=True)
        await self.invoke("delete-data", confirm=True)
        self.assertEqual(await self.scalar("SELECT profile_id FROM profiles"), "elsewhere")
        self.assertTrue(await deletion.opted_out(self.conn, "123", "456"))
