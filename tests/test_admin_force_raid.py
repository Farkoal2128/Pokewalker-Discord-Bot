"""Owner amendment (2026-11-12): /walker-admin force-raid with a 24-hour per-server cooldown (C3/C5)."""

from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, AsyncMock, Mock, patch

from discord import app_commands

import test_admin_channels

START = 1_700_000_000.0
COOLDOWN = "Force raid is on cooldown in this server. Try again in {}."


class ForceRaidTests(unittest.IsolatedAsyncioTestCase):
    rows = test_admin_channels.AdminChannelTests.rows
    reply = test_admin_channels.AdminChannelTests.reply

    async def asyncSetUp(self):
        await test_admin_channels.AdminChannelTests.asyncSetUp(self)
        self.now = START
        self.content = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))
        self.bot.content = self.content
        self.bot.walker = SimpleNamespace(clock=lambda: self.now, rng=random.Random(6))
        self.posted = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=555)))
        self.bot.get_channel = Mock(return_value=self.posted)
        self.permissions()
        self.interaction.guild.get_channel = lambda channel_id: self.channel if channel_id == self.channel.id else None
        await self.conn.execute("INSERT INTO guilds(guild_id,created_at,raids_enabled,raid_channel_id) "
                                "VALUES ('123',0,1,'789')")
        await self.conn.commit()

    def permissions(self, *, embed=True, send=True):
        self.channel.permissions_for = lambda member: SimpleNamespace(embed_links=embed, send_messages=send)

    def command(self):
        command = self.group.get_command("force-raid")
        self.assertIsNotNone(command, "/walker-admin force-raid must exist")
        return command

    async def invoke(self, reason=" weekend event "):
        command = self.command()
        await command.callback(command.binding, self.interaction, reason=reason)
        return self.reply()

    def pool(self):
        return [i for i in self.content["identities"] if i["is_legendary"] and not i["is_mythical"]]

    async def counts(self):
        return (len(await self.rows("world_spawns")), len(await self.rows("mod_audit")))

    async def test_registered_under_walker_admin_with_required_reason_and_manage_server_default(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(SimpleNamespace())
        self.addAsyncCleanup(bot.close)
        root = bot.tree.get_command("walker-admin")
        command = root.get_command("force-raid")
        self.assertIsNotNone(command)
        self.assertNotIsInstance(command, app_commands.Group)
        self.assertEqual([(p.name, p.required) for p in command.parameters], [("reason", True)])
        self.assertTrue(root.guild_only)
        self.assertTrue(root.default_permissions.manage_guild)

    async def test_non_manager_dm_blank_reason_and_excluded_refused_without_writes(self):
        self.interaction.user.guild_permissions.manage_guild = False
        self.assertIn("Manage Server", await self.invoke())
        self.interaction.user.guild_permissions.manage_guild = True
        self.interaction.guild_id = None
        self.assertIn("Manage Server", await self.invoke())
        self.interaction.guild_id = 123
        self.assertEqual(await self.invoke(reason="   "), "A reason is required.")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        await self.conn.commit()
        self.assertIn("excluded", (await self.invoke()).lower())
        self.assertEqual(await self.counts(), (0, 0))
        self.posted.send.assert_not_awaited()

    async def test_permission_and_exclusion_rechecked_inside_writer_job(self):
        original = self.group.authorize

        async def revoke_after_entry(interaction):
            allowed = await original(interaction)
            interaction.user.guild_permissions.manage_guild = False
            return allowed

        run = self.writer.run

        async def deferred_first(fn, **kwargs):
            self.interaction.response.defer.assert_awaited_once_with(ephemeral=True)
            return await run(fn, **kwargs)

        with patch.object(self.group, "authorize", side_effect=revoke_after_entry), \
             patch.object(self.writer, "run", side_effect=deferred_first):
            self.assertEqual(await self.invoke(), "Manage Server permission is required.")
        self.interaction.user.guild_permissions.manage_guild = True

        async def exclude_after_entry(interaction):
            allowed = await original(interaction)
            await self.writer.run(lambda conn: conn.execute(
                "INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)"))
            return allowed

        with patch.object(self.group, "authorize", side_effect=exclude_after_entry):
            self.assertEqual(await self.invoke(), "Excluded members cannot manage this server's walker.")
        self.assertEqual(await self.counts(), (0, 0))

    async def test_each_raid_refusal_has_ticket_text_writes_nothing_and_starts_no_cooldown(self):
        other_guild = SimpleNamespace(id=789, guild=SimpleNamespace(id=999),
                                      permissions_for=lambda member: SimpleNamespace(embed_links=True, send_messages=True))
        moved = SimpleNamespace(id=999, guild=SimpleNamespace(id=123),
                                permissions_for=lambda member: SimpleNamespace(embed_links=True, send_messages=True))
        off, missing = "Raids are turned off in this server.", "No raid channel is configured."
        no_permission = "Missing raid channel permission: EMBED_LINKS and SEND_MESSAGES are required."
        cases = (
            ("UPDATE guilds SET raids_enabled=0", None, off),
            ("DELETE FROM guilds", None, off),
            ("INSERT INTO guilds(guild_id,created_at,raids_enabled) VALUES ('123',0,1)", None, missing),
            ("UPDATE guilds SET raid_channel_id='789'", {"embed": False}, no_permission),
            (None, {"send": False}, no_permission),
            (None, {"lookup": None}, no_permission),
            (None, {"lookup": other_guild}, no_permission),
            (None, {"lookup": moved}, "The raid channel changed; try again."),
        )
        for sql, setup, expected in cases:
            with self.subTest(expected=expected, setup=setup):
                if sql:
                    await self.conn.execute(sql)
                    await self.conn.commit()
                self.permissions(embed=(setup or {}).get("embed", True), send=(setup or {}).get("send", True))
                if setup and "lookup" in setup:
                    self.interaction.guild.get_channel = lambda channel_id, found=setup["lookup"]: found
                self.assertEqual(await self.invoke(), expected)
                self.assertEqual(await self.counts(), (0, 0))
        self.interaction.guild.get_channel = lambda channel_id: self.channel
        self.permissions()
        await self.conn.execute("INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,"
                                "spawned_at,expires_at,post_state,content_version) "
                                "VALUES ('ticket','123','789',144,'articuno',?,?,'sent','fixture')",
                                (START - 60, START + 60))
        await self.conn.commit()
        self.assertEqual(await self.invoke(), "A World Legendary is already active in this server.")
        self.assertEqual(await self.counts(), (1, 0))
        self.posted.send.assert_not_awaited()
        self.now = START + 60
        self.assertTrue((await self.invoke()).startswith("Spawned "))
        self.assertEqual(await self.counts(), (2, 1))

    async def test_success_inserts_null_owner_spawn_and_audit_then_announces_after_commit(self):
        await self.conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                                "VALUES ('123','456','guild','123','raids_on','setup',?)", (START - 10,))
        await self.conn.commit()
        expected = random.Random(6).choice(self.pool())
        seen = []

        async def announce(bot, spawn):
            self.assertIs(bot, self.bot)
            self.assertFalse(self.conn.in_transaction)
            seen.append((spawn, await self.rows("world_spawns"), await self.rows("mod_audit")))

        with patch("pokewalker.services.raids.announce", side_effect=announce):
            text = await self.invoke()
        until = datetime.fromtimestamp(START + 3600, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.assertEqual(text, f"Spawned {expected['name_en']} in <#789> until {until}.")
        self.interaction.edit_original_response.assert_awaited_with(
            content=text, allowed_mentions=ANY)
        mentions = self.interaction.edit_original_response.await_args.kwargs["allowed_mentions"]
        self.assertEqual(mentions.to_dict()["parse"], [])
        (spawn, spawns, audits), = seen
        row = spawns[0]
        self.assertEqual(spawn["spawn_id"], row["spawn_id"])
        self.assertEqual((row["guild_id"], row["channel_id"], row["identity_id"], row["pokemon_id"],
                          row["spawned_at"], row["expires_at"], row["spawned_by_profile_id"], row["post_state"],
                          row["ended"]),
                         ("123", "789", expected["identity_id"], expected["pokemon_id"],
                          START, START + 3600, None, "pending", 0))
        self.assertTrue(expected["is_legendary"] and not expected["is_mythical"])
        audit = audits[-1]
        self.assertEqual((audit["guild_id"], audit["actor_id"], audit["target_kind"], audit["target_id"],
                          audit["action"], audit["reason"], audit["created_at"]),
                         ("123", "456", "guild", "123", "force_raid", "weekend event", START))
        self.assertEqual(len(audits), 2)
        for table in ("inventory", "resource_ledger", "action_receipts"):
            self.assertEqual(await self.rows(table), [], table)

    async def test_audit_failure_rolls_back_spawn_and_never_announces(self):
        await self.conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON mod_audit "
                                "BEGIN SELECT RAISE(ABORT,'audit failed'); END")
        await self.conn.commit()
        with patch("pokewalker.services.raids.announce", new=AsyncMock()) as announce:
            with self.assertRaisesRegex(Exception, "audit failed"):
                await self.command().callback(self.command().binding, self.interaction, reason="Event")
        announce.assert_not_awaited()
        self.assertEqual(await self.counts(), (0, 0))

    async def test_real_announcement_posts_once_to_the_checked_channel(self):
        await self.invoke()
        self.bot.get_channel.assert_called_once_with(789)
        self.posted.send.assert_awaited_once()
        self.assertIn("World Legendary", self.posted.send.await_args.kwargs["embed"].title)
        self.assertEqual([(r["post_state"], r["message_id"]) for r in await self.rows("world_spawns")],
                         [("sent", "555")])

    async def test_second_force_within_24_hours_refused_with_time_left_and_no_writes(self):
        await self.invoke()
        await self.conn.execute("UPDATE world_spawns SET ended=1")
        await self.conn.commit()
        self.interaction.user.id = 457
        for elapsed, left in ((1, "24h 0m"), (3600, "23h 0m"), (86400 - 60.5, "0h 2m"),
                              (86400 - 60, "0h 1m"), (86399.9, "0h 1m")):
            with self.subTest(elapsed=elapsed):
                self.now = START + elapsed
                self.assertEqual(await self.invoke(), COOLDOWN.format(left))
                self.assertEqual(await self.counts(), (1, 1))
        await self.conn.execute("UPDATE guilds SET raids_enabled=0")
        await self.conn.commit()
        self.assertEqual(await self.invoke(), COOLDOWN.format("0h 1m"))

    async def test_force_allowed_exactly_86400_seconds_after_last_success(self):
        await self.invoke()
        self.now = START + 86400
        self.assertTrue((await self.invoke()).startswith("Spawned "))
        spawns = await self.rows("world_spawns")
        self.assertEqual([s["ended"] for s in sorted(spawns, key=lambda s: s["spawned_at"])], [1, 0])
        self.assertEqual([a["created_at"] for a in await self.rows("mod_audit")], [START, START + 86400])
        self.now = START + 86400 + 1
        await self.conn.execute("UPDATE world_spawns SET ended=1")
        await self.conn.commit()
        self.assertEqual(await self.invoke(), COOLDOWN.format("24h 0m"))

    async def test_cooldown_is_per_guild(self):
        await self.invoke()
        await self.conn.execute("INSERT INTO guilds(guild_id,created_at,raids_enabled,raid_channel_id) "
                                "VALUES ('124',0,1,'790')")
        await self.conn.commit()
        other = SimpleNamespace(id=790, guild=SimpleNamespace(id=124),
                                permissions_for=lambda member: SimpleNamespace(embed_links=True, send_messages=True))
        self.interaction.guild_id = 124
        self.interaction.guild.get_channel = lambda channel_id: other if channel_id == 790 else None
        self.now = START + 5
        self.assertTrue((await self.invoke()).startswith("Spawned "))
        self.assertEqual(sorted(a["guild_id"] for a in await self.rows("mod_audit")), ["123", "124"])
        self.assertEqual(sorted(s["guild_id"] for s in await self.rows("world_spawns")), ["123", "124"])

    async def test_service_requires_writer_transaction_and_reports_remaining_seconds(self):
        raids = importlib.import_module("pokewalker.services.raids")
        with self.assertRaises(RuntimeError):
            await raids.force_spawn(self.conn, "123", 456, "x", START, random.Random(6), self.content, 789)
        first = await self.writer.run(lambda conn: raids.force_spawn(
            conn, "123", 456, "Event", START, random.Random(6), self.content, 789))
        self.assertEqual(first["status"], "spawned")
        self.assertIsNone(first["spawn"]["spawned_by_profile_id"])
        again = await self.writer.run(lambda conn: raids.force_spawn(
            conn, "123", 456, "Event", START + 100, random.Random(6), self.content, 789))
        self.assertEqual(again, {"status": "cooldown", "remaining": 86300})
