"""M1.4 profile and enrollment contracts, using the committed content artifact."""

from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch
from uuid import UUID

from pokewalker.db import Writer, open_db
from test_balance_tables import override_limits


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await open_db(":memory:", allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.conn.close)
        self.addAsyncCleanup(self.writer.close)
        self.content = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))
        self.assertEqual(len(self.content["starters"]), 27)
        try:
            self.service = importlib.import_module("pokewalker.services.profiles")
        except ModuleNotFoundError:
            self.fail("M1.4 profile service absent")
        self.now = datetime(2026, 11, 4, tzinfo=timezone.utc)

    async def rows(self, sql, args=()):
        async with self.conn.execute(sql, args) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def enroll(self, species=1):
        return await self.writer.run(lambda conn: self.service.enroll(
            conn, "123", "456", species, self.content, random.Random(8), self.now))

    async def test_enroll_creates_profile_starter_kit_pokedex_first_encounter(self):
        profile = await self.enroll()
        self.assertEqual(UUID(profile["profile_id"]).version, 4)
        self.assertEqual(profile["route_id"], "refreshing_field")
        self.assertEqual(await self.service.get_profile(self.conn, "123", "456"), profile)
        self.assertEqual({r["item_id"]: r["quantity"] for r in await self.rows("SELECT * FROM inventory")},
                         {"poke_ball": 30, "razz_berry": 5})
        dex = (await self.rows("SELECT * FROM pokedex"))[0]
        self.assertEqual(dex["pokemon_id"], 1)
        self.assertEqual(dex["seen_at"], self.now.timestamp())
        self.assertEqual(dex["caught_at"], self.now.timestamp())
        encounter = (await self.rows("SELECT * FROM encounters"))[0]
        self.assertEqual((encounter["state"], encounter["route_id"]), ("queued", "refreshing_field"))
        self.assertTrue(encounter["content_version"])
        self.assertEqual(await self.service.queue_size(self.conn, profile["profile_id"]), 1)
        self.assertEqual(len(await self.rows("SELECT * FROM resource_ledger")), 2)

    async def test_enroll_starter_kit_comes_from_capacities_table(self):
        override_limits(self, starter_kit={"poke_ball": 7})
        await self.enroll()
        self.assertEqual({r["item_id"]: r["quantity"] for r in await self.rows("SELECT * FROM inventory")},
                         {"poke_ball": 7})

    def test_content_version_and_pools_computed_once_per_loaded_content(self):
        self.service.content_facts.cache_clear()
        self.addCleanup(self.service.content_facts.cache_clear)
        version, pools = self.service.content_facts(self.content)
        self.assertEqual(len(version), 64)
        self.assertEqual(sum(map(len, pools.values())), len(self.content["identities"]))
        with patch.object(self.service.hashlib, "sha256", side_effect=AssertionError("rehashed")):
            self.assertIs(self.service.content_facts(self.content)[1], pools)
        other = json.loads(json.dumps(self.content))
        other["routes"] = {}
        self.assertNotEqual(self.service.content_facts(other)[0], version)

    async def test_enroll_twice_returns_same_receipt_no_second_kit(self):
        first = await self.enroll()
        with patch.object(self.service.encounters, "generate", side_effect=AssertionError("reroll")):
            self.assertEqual(await self.enroll(), first)
        for table in ("profiles", "pokemon", "encounters", "action_receipts"):
            self.assertEqual(len(await self.rows(f"SELECT * FROM {table}")), 1)
        self.assertEqual((await self.rows("SELECT quantity FROM inventory WHERE item_id='poke_ball'"))[0]["quantity"], 30)

    async def test_enroll_rejects_non_starter(self):
        with self.assertRaisesRegex(ValueError, "starter"):
            await self.enroll(25)
        self.assertEqual(await self.rows("SELECT * FROM profiles"), [])

    async def test_enroll_refused_when_excluded_without_profile(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        with self.assertRaisesRegex(ValueError, "excluded"):
            await self.enroll()
        self.assertEqual(await self.rows("SELECT * FROM profiles"), [])

    async def test_starter_rolls_and_favorite_companion(self):
        identity = next(i for i in self.content["identities"] if i["species_id"] == 1 and i["kind"] == "default")
        identity["gender_rate"] = 8
        profile = await self.enroll()
        starter = (await self.rows("SELECT * FROM pokemon"))[0]
        self.assertEqual((starter["origin"], starter["level_x2"], starter["shiny"], starter["favorite"]),
                         ("starter", 20, 0, 1))
        self.assertEqual(profile["companion_uid"], starter["pokemon_uid"])
        self.assertTrue(all(10 <= starter[k] <= 15 for k in ("iv_attack", "iv_defense", "iv_stamina")))
        self.assertEqual(starter["gender"], "female")

    async def test_profile_ids_differ_after_delete_and_reenroll(self):
        first = await self.enroll()
        # C3 account deletion also removes the receipt containing the deleted profile.
        await self.conn.execute("DELETE FROM profiles")
        await self.conn.execute("DELETE FROM action_receipts")
        self.assertNotEqual((await self.enroll())["profile_id"], first["profile_id"])

    async def test_restrictions_independent_pause_plus_share_ban_then_resume(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,share_banned) VALUES ('123','456',1,1)")
        flags = await self.service.restrictions(self.conn, "123", "456")
        self.assertTrue(flags.paused and flags.share_banned)
        self.assertFalse(flags.excluded)
        await self.conn.execute("UPDATE restrictions SET paused=0")
        flags = await self.service.restrictions(self.conn, "123", "456")
        self.assertFalse(flags.paused)
        self.assertTrue(flags.share_banned)

    async def test_indefinite_pause_is_paused_with_until_none(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused) VALUES ('123','456',1)")
        flags = await self.service.restrictions(self.conn, "123", "456")
        self.assertTrue(flags.paused)
        self.assertIsNone(flags.paused_until)

    async def test_timed_pause_expires_to_unpaused(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,paused,paused_until) VALUES ('123','456',1,100)")
        with patch.object(self.service.time, "time", return_value=99):
            flags = await self.service.restrictions(self.conn, "123", "456")
        self.assertTrue(flags.paused)
        self.assertEqual(flags.paused_until, datetime.fromtimestamp(100, timezone.utc))
        with patch.object(self.service.time, "time", return_value=100):
            self.assertFalse((await self.service.restrictions(self.conn, "123", "456")).paused)

    async def test_queue_size_counts_queued_and_revealed(self):
        profile = await self.enroll()
        for state, expected in (("queued", 1), ("revealed", 1), ("caught", 0), ("fled", 0), ("ran", 0)):
            await self.conn.execute("UPDATE encounters SET state=?", (state,))
            self.assertEqual(await self.service.queue_size(self.conn, profile["profile_id"]), expected)

    async def test_thread_inherits_parent_policy(self):
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.executemany("INSERT INTO guild_channels VALUES ('123',?,?,?)", [("10", 1, 0), ("11", 0, 1)])
        policy = await self.service.channel_policy(self.conn, "123", "11", "10")
        self.assertEqual((policy["channel_id"], policy["count_steps"], policy["react"]), ("10", 1, 0))
        self.assertIsNone(await self.service.channel_policy(self.conn, "123", "11", "99"))
        self.assertIsNone(await self.service.channel_policy(self.conn, "999", "10", None))

    async def test_encounter_failure_rolls_back_entire_enrollment(self):
        with patch.object(self.service.encounters, "generate", side_effect=ValueError("bad pool")):
            with self.assertRaisesRegex(ValueError, "bad pool"):
                await self.enroll()
        for table in ("profiles", "pokemon", "inventory", "pokedex", "action_receipts", "resource_ledger"):
            self.assertEqual(await self.rows(f"SELECT * FROM {table}"), [])

    async def test_existing_profile_without_receipt_is_refused(self):
        await self.enroll()
        await self.conn.execute("DELETE FROM action_receipts")
        with self.assertRaisesRegex(ValueError, "exists"):
            await self.enroll()

    async def test_exclusion_is_rechecked_before_enrollment_receipt_replay(self):
        await self.enroll()
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        with self.assertRaisesRegex(ValueError, "excluded"):
            await self.enroll()

    async def test_enrollment_requires_writer_transaction_and_aware_time(self):
        with self.assertRaisesRegex(RuntimeError, "transaction"):
            await self.service.enroll(self.conn, "123", "456", 1, self.content, random.Random(8), self.now)
        with self.assertRaisesRegex(ValueError, "timezone"):
            await self.writer.run(lambda conn: self.service.enroll(
                conn, "123", "456", 1, self.content, random.Random(8), self.now.replace(tzinfo=None)))
