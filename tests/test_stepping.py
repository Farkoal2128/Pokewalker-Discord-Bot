"""M1.5 credit jobs against actual SQLite writer transactions."""

from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from pokewalker.db import Writer, open_db


class SteppingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        root = Path("build/test-stepping")
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "game.db"
        self.conn = await open_db(self.path, allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.conn.close)
        self.addAsyncCleanup(self.writer.close)
        self.content = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))
        self.pid = str(uuid4())
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES (?,'123','456',0)", (self.pid,))
        async with self.conn.execute("SELECT * FROM profiles") as cursor:
            self.profile = dict(await cursor.fetchone())
        try:
            self.service = importlib.import_module("pokewalker.services.stepping")
        except ModuleNotFoundError:
            self.fail("M1.5 atomic credit service absent")
        self.cache = self.service.DigestCache()
        self.rng = random.Random(8)
        self.words = ["alpha", "bravo", "charlie", "delta"]

    async def rows(self, table):
        async with self.conn.execute(f"SELECT * FROM {table}") as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def credit(self, message_id="100", at=10000, words=None, channel_id="789", **kwargs):
        created = datetime.fromtimestamp(at, timezone.utc) if at is not None else None
        return await self.writer.run(lambda conn: self.service.credit_message(
            conn, self.profile, self.words if words is None else words, created,
            message_id, channel_id, content=self.content, rng=self.rng, cache=self.cache, **kwargs))

    async def set_meter(self, encounter=0, companion=0):
        await self.conn.execute("UPDATE profiles SET encounter_meter_c=?,companion_meter_c=?", (encounter, companion))

    async def test_message_processed_once(self):
        await self.credit()
        await self.credit()
        self.assertEqual(len(await self.rows("step_events")), 1)
        self.assertEqual((await self.rows("profiles"))[0]["encounter_meter_c"], 400)

    async def test_rolling_hour_by_message_time_not_receipt_time(self):
        for mid, at, count in (("old", 6400, 300), ("recent", 6500, 299), ("future", 10001, 900)):
            await self.conn.execute("INSERT INTO step_events VALUES (?,?,?, ?,?,0,?,'credited',?)",
                                    (mid, self.pid, "800", count, count, count * 100, at))
        await self.credit()
        row = next(r for r in await self.rows("step_events") if r["message_id"] == "100")
        self.assertEqual((row["accepted_words"], row["awarded_c"]), (4, 175))

    async def test_mint_at_100_keeps_remainder(self):
        await self.set_meter(9900)
        eid = await self.credit()
        row = (await self.rows("encounters"))[0]
        self.assertEqual(row["encounter_id"], eid)
        self.assertEqual((row["source_channel_id"], row["source_message_id"], row["route_id"]),
                         ("789", "100", "refreshing_field"))
        self.assertEqual(len(row["content_version"]), 64)
        self.assertEqual((await self.rows("profiles"))[0]["encounter_meter_c"], 300)

    async def test_two_mints_from_one_message_when_meter_high(self):
        await self.set_meter(19900)
        await self.credit()
        self.assertEqual(len(await self.rows("encounters")), 2)
        self.assertEqual((await self.rows("profiles"))[0]["encounter_meter_c"], 300)
        self.assertEqual(len(await self.rows("reactions")), 1)

    async def test_queue_full_counts_revealed_no_mint_meter_unchanged(self):
        await self.set_meter(29900)
        await self.credit()
        await self.conn.execute("UPDATE encounters SET state='revealed'")
        before = (await self.rows("profiles"))[0]["encounter_meter_c"]
        await self.credit("101", 10060, ["other", "fresh", "words", "here"])
        self.assertEqual(len(await self.rows("encounters")), 3)
        self.assertEqual((await self.rows("profiles"))[0]["encounter_meter_c"], before)
        self.assertEqual((await self.rows("step_events"))[-1]["awarded_c"], 400)

    async def test_frozen_meter_adds_nothing(self):
        self.assertEqual(self.service.advance_meter(9900, 2000, 10000, True), (9900, 0))
        self.assertEqual(self.service.advance_meter(9900, 2000, 10000, False), (1900, 1))

    async def test_companion_meter_only_with_companion_keeps_partial(self):
        await self.set_meter(companion=14900)
        await self.credit()
        self.assertEqual((await self.rows("profiles"))[0]["companion_meter_c"], 14900)
        await self.conn.execute("INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,gender,shiny,origin,content_version,caught_at) VALUES ('pet',?,1,20,10,10,10,'male',0,'starter','v1',0)", (self.pid,))
        await self.conn.execute("UPDATE profiles SET companion_uid='pet'")
        await self.credit("101", 10060, ["other", "fresh", "words", "here"])
        self.assertEqual((await self.rows("profiles"))[0]["companion_meter_c"], 300)
        self.assertEqual([(row["family_id"], row["quantity"]) for row in await self.rows("candy")], [(1, 1)])
        self.assertEqual([row["reason"] for row in await self.rows("resource_ledger")], ["companion_candy"])

    async def test_each_message_that_mints_gets_one_reaction(self):
        ids = []
        for number in range(3):
            await self.set_meter(9900)
            ids.append(await self.credit(str(100 + number), 10000 + number * 60,
                                         [f"word{number}", "fresh", "other", "here"]))
        self.assertTrue(all(ids))
        self.assertEqual(len(await self.rows("encounters")), 3)
        self.assertEqual([r["encounter_id"] for r in await self.rows("reactions")], ids)
        await self.set_meter(9900)
        self.assertIsNone(await self.credit("103", 10180, ["fourth", "fresh", "other", "here"]))
        self.assertEqual(len(await self.rows("reactions")), 3)

    async def test_reaction_row_written_in_same_commit(self):
        await self.set_meter(9900)
        await self.conn.execute("CREATE TRIGGER refuse_reaction BEFORE INSERT ON reactions BEGIN SELECT RAISE(ABORT,'refuse reaction'); END")
        with self.assertRaisesRegex(Exception, "refuse reaction"):
            await self.credit()
        self.assertEqual(await self.rows("step_events"), [])
        self.assertEqual(await self.rows("encounters"), [])
        self.assertEqual((await self.rows("profiles"))[0]["encounter_meter_c"], 9900)
        await self.conn.execute("DROP TRIGGER refuse_reaction")
        await self.credit()
        self.assertEqual((await self.rows("step_events"))[0]["awarded_c"], 400)

    async def test_content_never_persisted(self):
        sentinel = "PrivateUniqueBodySentinelThatMustNeverReachDisk"
        await self.credit(words=[sentinel, "four", "eligible", "words"])
        await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for path in Path(self.temp.name).glob("game.db*"):
            self.assertNotIn(sentinel.encode(), path.read_bytes())

    async def test_duplicate_digest_cross_channel_and_restart_reset(self):
        await self.credit()
        await self.credit("101", 10060, channel_id="800")
        self.assertEqual((await self.rows("step_events"))[-1]["reason"], "duplicate")
        self.cache = self.service.DigestCache()
        await self.credit("102", 10120)
        self.assertEqual((await self.rows("step_events"))[-1]["awarded_c"], 400)

    async def test_minute_cap_and_cooldown_use_committed_sql_history(self):
        await self.credit(words=[f"word{i}" for i in range(20)])
        await self.credit("101", 10001, ["new", "fresh", "words", "here"])
        self.assertEqual((await self.rows("step_events"))[-1]["reason"], "cooldown")
        await self.credit("102", 10015, [f"other{i}" for i in range(20)])
        self.assertEqual((await self.rows("step_events"))[-1]["accepted_words"], 10)
        await self.credit("103", 10030, ["new", "fresh", "words", "here"])
        self.assertEqual((await self.rows("step_events"))[-1]["reason"], "minute_cap")

    async def test_no_timestamp_is_recorded_without_award(self):
        await self.credit(at=None)
        row = (await self.rows("step_events"))[0]
        self.assertEqual((row["reason"], row["accepted_words"], row["awarded_c"]), ("no_timestamp", 0, 0))

    async def test_lure_and_generated_roll_are_frozen(self):
        await self.set_meter(9900)
        await self.conn.execute("INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,expires_at,"
                                "receipt_key,remaining_encounters) VALUES ('active-lure',?,'shiny_lure',0,NULL,'test',10)",
                                (self.pid,))
        generate = self.service.encounters.generate
        rolls = []

        def record(*args, **kwargs):
            self.assertTrue(args[2])
            spec = generate(*args, **kwargs)
            rolls.append(spec)
            return spec

        with patch.object(self.service.encounters, "generate", side_effect=record):
            await self.credit()
        spec = rolls[0]
        row = (await self.rows("encounters"))[0]
        self.assertEqual(row["lure_id"], "active-lure")
        self.assertEqual((row["pokemon_id"], row["level_x2"], row["iv_attack"], row["iv_defense"],
                          row["iv_stamina"], row["gender"], bool(row["shiny"]), row["tier"]),
                         (spec.pokemon_id, spec.level_x2, *spec.ivs, spec.gender or "genderless",
                          spec.shiny, spec.tier))
        self.assertTrue(row["content_version"])
