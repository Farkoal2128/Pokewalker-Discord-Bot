"""D25 companion selection and Candy with real writer transactions."""

from datetime import datetime, timezone
import random
import unittest
from unittest.mock import patch

import test_storage as storage_tests
from pokewalker.services import stepping


class CompanionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = storage_tests.StorageTests.asyncSetUp
    interaction = storage_tests.StorageTests.interaction
    rows = storage_tests.StorageTests.rows
    open = storage_tests.StorageTests.open
    click = storage_tests.StorageTests.click
    enroll = storage_tests.StorageTests.enroll
    exclude = storage_tests.StorageTests.exclude
    ready = storage_tests.StorageTests.ready
    current = storage_tests.StorageTests.current
    prepared = storage_tests.StorageTests.prepared
    storage = storage_tests.StorageTests.storage
    details = storage_tests.StorageTests.details
    buttons = storage_tests.StorageTests.buttons
    service = storage_tests.StorageTests.service
    deploy = storage_tests.StorageTests.deploy

    async def setup_pair(self, meter=0, identity=None, **changes):
        session = await self.prepared(2)
        identity = identity or next(item for item in self.bot.content["identities"] if item["pokemon_id"] == 25)
        self.new_uid, self.new_family = "p-001", identity["family_id"]
        async def seed(conn):
            await conn.execute("UPDATE profiles SET companion_meter_c=?", (meter,))
            fields = {"pokemon_id": identity["pokemon_id"], **changes}
            await conn.execute("UPDATE pokemon SET " + ",".join(f"{key}=?" for key in fields)
                               + " WHERE pokemon_uid=?", (*fields.values(), self.new_uid))
        await self.writer.run(seed)
        self.cache = stepping.DigestCache()
        return session

    async def profile_row(self):
        return (await self.rows("SELECT * FROM profiles WHERE profile_id=?", (self.profile["profile_id"],)))[0]

    async def candy(self):
        return {row["family_id"]: row["quantity"] for row in await self.rows("SELECT * FROM candy")}

    async def set_companion(self, session, uid=None):
        _, session = await self.details(session, uid or self.new_uid)
        interaction = await self.click(session, "companion")
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs, await self.current(session)

    async def credit(self, mid="100", words=10, at=10000):
        return await self.writer.run(lambda conn: stepping.credit_message(
            conn, self.profile, [f"{mid}word{i}" for i in range(words)],
            datetime.fromtimestamp(at, timezone.utc), mid, "789", content=self.bot.content,
            rng=random.Random(8), cache=self.cache))

    async def snapshot(self):
        return {table: await self.rows(f"SELECT * FROM {table}") for table in
                ("profiles", "pokemon", "sessions", "candy", "action_receipts", "resource_ledger")}

    async def test_set_companion_requires_owned_and_revision(self):
        session = await self.setup_pair()
        _, session = await self.details(session, self.new_uid)
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE pokemon SET revision=revision+1 WHERE pokemon_uid=?", (self.new_uid,)))
        before = await self.snapshot()
        refused = await self.click(session, "companion")
        refused.followup.send.assert_awaited_once()
        self.assertEqual(await self.snapshot(), before)
        rendered, _ = await self.set_companion(session)
        self.assertEqual((await self.profile_row())["companion_uid"], self.new_uid)
        self.assertIn("Companion", rendered["embed"].description)
        self.assertFalse(self.buttons(rendered)["Set companion"].disabled)

    async def test_set_companion_deployed_refused_trigger_not_reached(self):
        session = await self.setup_pair(14000)
        await self.deploy(session, self.new_uid)
        _, session = await self.details(session, self.new_uid)
        before, writes, execute = await self.snapshot(), self.conn.total_changes, self.conn.execute
        def refuse_update(sql, parameters=()):
            if "UPDATE profiles SET companion_uid" in sql:
                raise AssertionError("companion UPDATE reached deployed trigger")
            return execute(sql, parameters)
        with patch.object(self.conn, "execute", side_effect=refuse_update):
            refused = await self.click(session, "companion")
        refused.edit_original_response.assert_not_awaited()
        self.assertEqual(refused.followup.send.await_args.args[0], "Recall it from the gym first")
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(self.conn.total_changes, writes)
        self.assertEqual((await self.profile_row())["companion_uid"], self.uid)
        self.assertEqual((await self.profile_row())["companion_meter_c"], 14000)

    async def test_set_companion_idempotent_keeps_meter(self):
        session = await self.setup_pair(12345)
        _, session = await self.set_companion(session)
        before = await self.profile_row()
        pokemon = await self.rows("SELECT * FROM pokemon")
        await self.click(session, "companion")
        self.assertEqual(await self.profile_row(), before)
        self.assertEqual(before["companion_meter_c"], 12345)
        self.assertEqual(await self.rows("SELECT * FROM pokemon"), pokemon)

    async def test_swap_keeps_meter_progress(self):
        session = await self.setup_pair(14000)
        _, session = await self.set_companion(session)
        self.assertEqual((await self.profile_row())["companion_meter_c"], 14000)
        rendered, _ = await self.set_companion(session, self.uid)
        self.assertEqual((await self.profile_row())["companion_uid"], self.uid)
        self.assertEqual((await self.profile_row())["companion_meter_c"], 14000)
        self.assertIn("Companion", rendered["embed"].description)

    async def test_candy_at_150_goes_to_current_companion_family(self):
        session = await self.setup_pair(14000)
        await self.set_companion(session)
        await self.credit()
        self.assertEqual(await self.candy(), {self.new_family: 1})
        self.assertEqual((await self.profile_row())["companion_meter_c"], 0)

    async def test_swap_at_140_then_steps_pays_new_family_not_old(self):
        session = await self.setup_pair(13000)
        await self.credit()
        self.assertEqual((await self.profile_row())["companion_meter_c"], 14000)
        self.assertEqual(await self.candy(), {})
        await self.set_companion(session)
        await self.credit("101", at=10060)
        self.assertEqual(await self.candy(), {self.new_family: 1})
        self.assertNotEqual(self.new_family, 1)

    async def test_meter_keeps_remainder_after_candy(self):
        await self.setup_pair(14900)
        await self.credit(words=4)
        self.assertEqual((await self.profile_row())["companion_meter_c"], 300)
        self.assertEqual(await self.candy(), {1: 1})

    async def test_no_companion_meter_frozen_no_candy_steps_still_credit(self):
        await self.setup_pair(14900)
        await self.writer.run(lambda conn: conn.execute("UPDATE profiles SET companion_uid=NULL"))
        await self.credit()
        self.assertEqual((await self.profile_row())["companion_meter_c"], 14900)
        self.assertEqual(await self.candy(), {})
        self.assertEqual((await self.rows("SELECT awarded_c FROM step_events"))[0]["awarded_c"], 1000)
        self.assertEqual(await self.rows("SELECT * FROM action_receipts WHERE action='companion_candy'"), [])

    async def test_companion_candy_once_per_message_receipt_and_ledger(self):
        await self.setup_pair(14000)
        await self.credit()
        await self.credit()
        receipts = await self.rows("SELECT * FROM action_receipts WHERE key='companion:100'")
        self.assertEqual(len(receipts), 1)
        receipt = receipts[0]
        self.assertEqual((receipt["action"], receipt["profile_id"]), ("companion_candy", self.profile["profile_id"]))
        lines = await self.rows("SELECT * FROM resource_ledger WHERE receipt_key='companion:100'")
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["resource"], lines[0]["resource_id"], lines[0]["delta"], lines[0]["reason"]),
                         ("candy", "1", 1, "companion_candy"))
        self.assertEqual(await self.candy(), {1: 1})
        self.assertEqual(len(await self.rows("SELECT * FROM step_events")), 1)

    async def test_gender_variety_companion_pays_its_family(self):
        parent = next(item for item in self.bot.content["identities"] if item.get("gender_varieties"))
        female = parent["gender_varieties"]["female"]
        session = await self.setup_pair(14000, female, gender="female")
        await self.set_companion(session)
        await self.credit()
        self.assertEqual(await self.candy(), {female["family_id"]: 1})

    async def test_legendary_can_be_companion(self):
        legendary = next(item for item in self.bot.content["identities"] if item["is_legendary"])
        session = await self.setup_pair(14000, legendary)
        await self.set_companion(session)
        await self.credit()
        self.assertEqual((await self.profile_row())["companion_uid"], self.new_uid)
        self.assertEqual(await self.candy(), {legendary["family_id"]: 1})

    async def test_sent_pokemon_cannot_be_companion(self):
        session = await self.setup_pair()
        _, session = await self.details(session, self.new_uid)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET state='sent' WHERE pokemon_uid=?", (self.new_uid,)))
        before = await self.snapshot()
        refused = await self.click(session, "companion")
        refused.followup.send.assert_awaited_once()
        self.assertEqual(await self.snapshot(), before)

    async def test_home_thumbnail_switches_after_swap(self):
        session = await self.setup_pair()
        opened, _ = await self.open()
        old = opened.edit_original_response.await_args.kwargs["embed"]
        await self.set_companion(session)
        opened, _ = await self.open()
        embed = opened.edit_original_response.await_args.kwargs["embed"]
        pokemon = (await self.rows("SELECT * FROM pokemon WHERE pokemon_uid=?", (self.new_uid,)))[0]
        identity, sprite = self.service().identify(self.bot.content, pokemon)
        self.assertEqual(embed.thumbnail.url, sprite)
        self.assertNotEqual(embed.thumbnail.url, old.thumbnail.url)
        self.assertIn(identity["name_en"], embed.description)
        self.assertIn("CP ", embed.description)

    async def test_other_user_cannot_set_companion(self):
        session = await self.setup_pair()
        _, session = await self.details(session, self.new_uid)
        before = await self.snapshot()
        for who in ({"user": 999}, {"guild": 999}):
            refused = await self.click(session, "companion", **who)
            refused.followup.send.assert_awaited_once()
            self.assertEqual(await self.snapshot(), before)
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('foreign','123','999',0)"))
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE pokemon SET profile_id='foreign' WHERE pokemon_uid=?", (self.new_uid,)))
        before = await self.snapshot()
        refused = await self.click(session, "companion")
        refused.followup.send.assert_awaited_once()
        self.assertEqual(await self.snapshot(), before)

    async def test_excluded_refused(self):
        session = await self.setup_pair(14000)
        _, session = await self.details(session, self.new_uid)
        await self.exclude()
        before = await self.snapshot()
        refused = await self.click(session, "companion")
        refused.followup.send.assert_awaited_once()
        await self.credit()
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.rows("SELECT * FROM step_events"), [])

    async def test_ledger_failure_rolls_back_candy_meter_and_steps(self):
        await self.setup_pair(14900)
        await self.writer.run(lambda conn: conn.execute(
            "CREATE TRIGGER refuse_companion BEFORE INSERT ON resource_ledger "
            "WHEN NEW.reason='companion_candy' BEGIN SELECT RAISE(ABORT,'refuse companion'); END"))
        before = await self.snapshot()
        with self.assertRaisesRegex(Exception, "refuse companion"):
            await self.credit(words=4)
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual(await self.rows("SELECT * FROM step_events"), [])
        await self.writer.run(lambda conn: conn.execute("DROP TRIGGER refuse_companion"))
        await self.credit(words=4)
        self.assertEqual(await self.candy(), {1: 1})
