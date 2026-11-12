"""M2.3 atomic currency spending and private power-up confirmation contracts."""

import importlib
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_storage as storage_tests
from test_catching import store_legacy
from pokewalker.domain.cp import cp


class PowerupTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = storage_tests.StorageTests.asyncSetUp
    interaction = storage_tests.StorageTests.interaction
    rows = storage_tests.StorageTests.rows
    open = storage_tests.StorageTests.open
    click = storage_tests.StorageTests.click
    enroll = storage_tests.StorageTests.enroll
    exclude = storage_tests.StorageTests.exclude
    ready = storage_tests.StorageTests.ready
    current = storage_tests.StorageTests.current
    reveal = storage_tests.StorageTests.reveal
    prepared = storage_tests.StorageTests.prepared
    storage = storage_tests.StorageTests.storage
    details = storage_tests.StorageTests.details
    buttons = storage_tests.StorageTests.buttons

    def service(self):
        return importlib.import_module("pokewalker.services.powerup")

    async def funded(self, **changes):
        session = await self.prepared(**changes)
        pokemon = await self.pokemon()
        identity, _ = storage_tests.StorageTests.service(self).identify(self.bot.content, pokemon)
        self.family = identity["family_id"]
        await self.writer.run(lambda conn: conn.execute("UPDATE profiles SET stardust=10000"))
        await self.writer.run(lambda conn: conn.execute("INSERT INTO candy VALUES (?,?,100)",
                                                       (self.profile["profile_id"], self.family)))
        return session

    async def pokemon(self):
        return (await self.rows("SELECT * FROM pokemon WHERE pokemon_uid=?", (self.uid,)))[0]

    async def quote(self):
        return await self.service().quote(self.conn, self.profile["profile_id"], self.uid,
                                          self.bot.content, self.walker.multipliers)

    async def confirm(self, session, revision=0):
        return await self.writer.run(lambda conn: self.service().power_up(
            conn, session, self.uid, revision, self.bot.content, self.walker.multipliers))

    async def snapshot(self):
        return {table: await self.rows(f"SELECT * FROM {table}") for table in
                ("pokemon", "profiles", "candy", "resource_ledger", "action_receipts")}

    async def screen(self, session, action="power_up"):
        interaction = await self.click(session, action)
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs, await self.current(session)

    async def deploy(self, session):
        from pokewalker.services import gyms
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE profiles SET companion_uid=NULL WHERE profile_id=?", (self.profile["profile_id"],)))
        gym = await self.writer.run(lambda conn: gyms.create(conn, session["guild_id"], "Park", 100))
        pokemon = await self.pokemon()
        result = await self.writer.run(lambda conn: gyms.deploy(
            conn, session, gym["gym_id"], self.uid, pokemon["revision"], 1000, self.bot.content))
        self.assertEqual(result["status"], "deployed")
        return result["deployment"]

    async def test_power_up_deployed_stale_no_spend_trigger_not_reached(self):
        session = await self.funded()
        await self.deploy(session)
        before = await self.snapshot()
        with patch.object(self.service(), "quote", wraps=self.service().quote) as quote:
            result = await self.confirm(session, (await self.pokemon())["revision"])
        self.assertEqual(result, {"status": "stale", "pokemon": await self.pokemon()})
        quote.assert_not_awaited()
        self.assertEqual(await self.snapshot(), before)

    async def test_power_up_then_deploy_then_replay_returns_saved_result_no_extra_spend(self):
        session = await self.funded()
        saved = await self.confirm(session)
        self.assertEqual(saved["status"], "powered_up")
        await self.deploy(session)
        before = await self.snapshot()
        self.assertEqual(await self.confirm(session), saved)
        self.assertEqual(await self.snapshot(), before)

    async def test_quote_band_lower_inclusive_upper_exclusive(self):
        await self.funded()
        for level, candy, dust in ((19, 1, 100), (20, 2, 250), (39, 2, 250), (40, 3, 500),
                                   (59, 3, 500), (60, 4, 1000), (79, 4, 1000)):
            with self.subTest(level=level):
                await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET level_x2=?", (level,)))
                quote = await self.quote()
                self.assertEqual((quote["candy_cost"], quote["stardust_cost"]), (candy, dust))

    async def test_quote_cp_before_after_from_cpm_and_no_level_text(self):
        session = await self.funded()
        rendered, session = await self.details(session)
        self.assertFalse(self.buttons(rendered)["Power up"].disabled)
        before = await self.snapshot()
        quote = await self.quote()
        pokemon = await self.pokemon()
        identity, _ = storage_tests.StorageTests.service(self).identify(self.bot.content, pokemon)
        base = [identity[k] for k in ("base_attack", "base_defense", "base_stamina")]
        ivs = [pokemon[k] for k in ("iv_attack", "iv_defense", "iv_stamina")]
        for field, level in (("cp_before", pokemon["level_x2"]), ("cp_after", pokemon["level_x2"] + 1)):
            self.assertEqual(quote[field], cp(base, ivs, level, multipliers=self.walker.multipliers))
        rendered, session = await self.screen(session)
        text = rendered["embed"].title + rendered["embed"].description
        self.assertIn(f"CP {quote['cp_before']} → {quote['cp_after']}", text)
        self.assertIn(f"{quote['candy_cost']} Candy (have 100)", text)
        self.assertIn(f"{quote['stardust_cost']} Stardust (have 10000)", text)
        self.assertNotIn("level", text.lower())
        self.assertFalse(self.buttons(rendered)["Confirm"].disabled)
        back, _ = await self.screen(session, "storage_detail")
        self.assertEqual(back["embed"].title, "Pokémon details")
        self.assertEqual(await self.snapshot(), before)

    async def test_at_cap_80_no_quote_no_spend(self):
        session = await self.funded(level_x2=80)
        _, session = await self.details(session)
        before = await self.snapshot()
        quote = await self.quote()
        self.assertTrue(quote["at_cap"])
        self.assertFalse(quote["affordable"])
        self.assertEqual((quote["cp_after"], quote["candy_cost"], quote["stardust_cost"]), (None, None, None))
        rendered, _ = await self.screen(session)
        self.assertTrue(self.buttons(rendered)["Confirm"].disabled)
        self.assertNotIn("level", rendered["embed"].description.lower())
        self.assertEqual((await self.confirm(session))["status"], "at_cap")
        self.assertEqual(await self.snapshot(), before)

    async def test_confirm_debits_candy_stardust_bumps_level_revision_with_ledger_lines(self):
        session = await self.funded()
        before, quote = await self.pokemon(), await self.quote()
        _, session = await self.details(session)
        _, session = await self.screen(session)
        rendered, session = await self.screen(session, "power_up_confirm")
        self.assertEqual(await self.pokemon(), {**before, "level_x2": before["level_x2"] + 1, "revision": 1})
        self.assertIn(f"CP {quote['cp_after']}", rendered["embed"].description)
        self.assertEqual(json.loads(session["selection"])["pokemon_revision"], 1)
        balances = await self.service().balances(self.conn, self.profile["profile_id"])
        self.assertEqual(balances, {"stardust": 10000 - quote["stardust_cost"],
                                    "candy": {self.family: 100 - quote["candy_cost"]}})
        lines = await self.rows("SELECT * FROM resource_ledger WHERE reason='powerup' ORDER BY line_key")
        self.assertEqual([(r["resource"], r["resource_id"], r["delta"]) for r in lines],
                         [("candy", str(self.family), -quote["candy_cost"]), ("stardust", None, -quote["stardust_cost"])])
        receipt = (await self.rows("SELECT * FROM action_receipts WHERE action='powerup'"))[0]
        self.assertEqual((receipt["key"], receipt["profile_id"]),
                         (f"powerup:{self.uid}:0", self.profile["profile_id"]))

    async def test_insufficient_candy_or_stardust_refused_no_spend(self):
        session = await self.funded()
        _, session = await self.details(session)
        for table, column, restore in (("candy", "quantity", 100), ("profiles", "stardust", 10000)):
            await self.writer.run(lambda conn: conn.execute(f"UPDATE {table} SET {column}=0"))
            before = await self.snapshot()
            rendered, _ = await self.screen(await self.current(session))
            self.assertTrue(self.buttons(rendered)["Confirm"].disabled)
            self.assertEqual((await self.confirm(session))["status"], "insufficient")
            self.assertEqual(await self.snapshot(), before)
            await self.writer.run(lambda conn: conn.execute(f"UPDATE {table} SET {column}=?", (restore,)))

    async def test_confirm_twice_one_half_level(self):
        session = await self.funded()
        _, session = await self.details(session)
        _, session = await self.screen(session)
        original = self.buttons((await self.screen(session))[0])["Confirm"].custom_id
        session = await self.current(session)
        result = await self.confirm(session)
        before = await self.snapshot()
        self.assertEqual(await self.confirm(session), result)
        self.assertEqual(await self.snapshot(), before)
        await self.walker.route(self.interaction(), original)
        before = await self.snapshot()
        retry = self.interaction()
        await self.walker.route(retry, original)
        retry.edit_original_response.assert_not_awaited()
        retry.followup.send.assert_not_awaited()
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.pokemon())["revision"], 1)

    async def test_restart_after_commit_before_reply_one_half_level(self):
        session = await self.funded()
        _, session = await self.details(session)
        rendered, session = await self.screen(session)
        original = self.buttons(rendered)["Confirm"].custom_id
        interaction = self.interaction()
        interaction.edit_original_response.side_effect = RuntimeError("reply lost")
        with self.assertRaisesRegex(RuntimeError, "reply lost"):
            await self.walker.route(interaction, original)
        before = await self.snapshot()
        self.walker = self.module.Walker(self.bot, clock=lambda: 1001)
        self.bot.walker = self.walker
        with patch.dict(self.walker.handlers, power_up_confirm=AsyncMock(side_effect=AssertionError("stale handler"))):
            retry = await self.click(session, "power_up_confirm")
        retry.edit_original_response.assert_not_awaited()
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.confirm(session))["status"], "powered_up")
        _, reopened = await self.open()
        rendered, _ = await self.details(reopened)
        self.assertIn("CP ", rendered["embed"].description)
        self.assertEqual((await self.pokemon())["revision"], 1)

    async def test_stale_pokemon_revision_refused(self):
        session = await self.funded()
        _, session = await self.details(session)
        _, session = await self.screen(session)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET revision=1"))
        before = await self.snapshot()
        self.assertEqual((await self.confirm(session))["status"], "stale")
        retry = await self.click(session, "power_up_confirm")
        retry.edit_original_response.assert_not_awaited()
        retry = await self.click(session, "power_up")
        retry.edit_original_response.assert_not_awaited()
        self.assertEqual(await self.snapshot(), before)

    async def test_sent_or_other_owner_refused(self):
        session = await self.funded()
        for override in ({"user_id": "999"}, {"guild_id": "999"}, {"profile_id": "other"}):
            before = await self.snapshot()
            self.assertEqual((await self.confirm({**session, **override}))["status"], "stale")
            self.assertEqual(await self.snapshot(), before)
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET state='sent'"))
        before = await self.snapshot()
        self.assertEqual((await self.confirm(session))["status"], "stale")
        self.assertIsNone(await self.quote())
        self.assertEqual(await self.snapshot(), before)

    async def test_excluded_refused_inside_transaction(self):
        session = await self.funded()
        await self.confirm(session)
        await self.exclude()
        before = await self.snapshot()
        self.assertEqual((await self.confirm(session))["status"], "excluded")
        self.assertEqual(await self.snapshot(), before)

    async def test_ivs_shiny_unchanged(self):
        session = await self.funded(shiny=1, gender="female", iv_attack=0, iv_defense=15, iv_stamina=7)
        before = await self.pokemon()
        await self.confirm(session)
        self.assertEqual(await self.pokemon(), {**before, "level_x2": before["level_x2"] + 1, "revision": 1})

    async def test_ledger_sums_equal_balance_deltas_across_catch_send_powerup(self):
        from pokewalker.services import catching, research
        session = await self.prepared(level_x2=19)
        starter = await self.pokemon()
        await self.writer.run(lambda conn: conn.execute("UPDATE encounters SET pokemon_id=?", (starter["pokemon_id"],)))
        _, session = await self.reveal(session)
        selection = json.loads(session["selection"])
        await self.writer.run(lambda conn: catching.throw(conn, selection["encounter_id"], session,
                             selection["encounter_revision"], Mock(random=Mock(return_value=0)), 1000,
                             content=self.bot.content))
        await store_legacy(self.writer, selection["encounter_id"], 1000)
        caught = (await self.rows("SELECT * FROM pokemon WHERE origin='catch'"))[0]
        preview = {"id": "ledger-chain", "expires_at": 1120, "unlocked": False}
        picks = [[caught["pokemon_uid"], caught["revision"]]]
        research_session = {**session, "selection": json.dumps({"picks": picks, "preview": preview})}
        await self.writer.run(lambda conn: research.send(conn, research_session, picks, preview, 1000, self.bot.content))
        self.assertEqual((await self.confirm(session))["status"], "powered_up")
        balances = await self.service().balances(self.conn, self.profile["profile_id"])
        lines = await self.rows("SELECT * FROM resource_ledger WHERE resource IN ('candy','stardust')")
        self.assertEqual(balances["stardust"], sum(r["delta"] for r in lines if r["resource"] == "stardust"))
        for family, quantity in balances["candy"].items():
            self.assertEqual(quantity, sum(r["delta"] for r in lines if r["resource"] == "candy" and r["resource_id"] == str(family)))
        self.assertEqual({r["reason"] for r in lines}, {"catch_reward", "research_send", "powerup"})

    async def test_render_functions_do_no_io(self):
        session = await self.funded()
        quote = await self.quote()
        module = importlib.import_module("pokewalker.bot.powerup")
        with patch.object(self.writer, "run", side_effect=AssertionError("database I/O")), \
                patch("builtins.open", side_effect=AssertionError("file I/O")), \
                patch("socket.socket", side_effect=AssertionError("network I/O")):
            self.assertEqual(module.render_quote({"session": session, "quote": quote})["embed"].title, "Power up")

    async def test_ledger_failure_rolls_back_everything(self):
        session = await self.funded()
        before = await self.snapshot()
        execute = self.conn.execute
        def fail(sql, parameters=()):
            if "INSERT INTO resource_ledger" in sql:
                raise RuntimeError("ledger unavailable")
            return execute(sql, parameters)
        with patch.object(self.conn, "execute", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "ledger unavailable"):
                await self.confirm(session)
        self.assertEqual(await self.snapshot(), before)

    async def test_other_profile_cannot_replay_owned_receipt(self):
        from datetime import datetime, timezone
        import random
        from pokewalker.services import profiles
        session = await self.funded()
        await self.confirm(session)
        other = await self.writer.run(lambda conn: profiles.enroll(
            conn, 123, 999, 1, self.bot.content, random.Random(8), datetime.now(timezone.utc)))
        before = await self.snapshot()
        forged = {**session, "user_id": "999", "profile_id": other["profile_id"]}
        self.assertEqual((await self.confirm(forged))["status"], "stale")
        self.assertEqual(await self.snapshot(), before)

    async def test_final_half_step_reaches_cap_and_cannot_spend_again(self):
        session = await self.funded(level_x2=79)
        self.assertEqual((await self.confirm(session))["status"], "powered_up")
        self.assertEqual((await self.pokemon())["level_x2"], 80)
        before = await self.snapshot()
        self.assertEqual((await self.confirm(session, 1))["status"], "at_cap")
        self.assertEqual(await self.snapshot(), before)

    async def test_transaction_required_and_missing_candy_is_zero(self):
        session = await self.prepared()
        self.assertEqual((await self.quote())["candy_have"], 0)
        with self.assertRaisesRegex(RuntimeError, "active writer transaction"):
            await self.service().power_up(self.conn, session, self.uid, 0, self.bot.content, self.walker.multipliers)
        before = await self.snapshot()
        self.assertEqual((await self.confirm(session))["status"], "insufficient")
        self.assertEqual(await self.snapshot(), before)

    async def rare(self, quantity):
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO inventory VALUES (?,'rare_candy',?) ON CONFLICT(profile_id,item_id) DO UPDATE SET quantity=excluded.quantity",
            (self.profile["profile_id"], quantity)))

    async def rare_snapshot(self):
        return {**await self.snapshot(), "inventory": await self.rows("SELECT * FROM inventory ORDER BY item_id")}

    async def rare_confirm(self, session, revision=0):
        return await self.writer.run(lambda conn: self.service().power_up(
            conn, session, self.uid, revision, self.bot.content, self.walker.multipliers, use_rare_candy=True))

    async def test_rare_candy_powers_up_one_step_without_candy_or_stardust(self):
        session = await self.prepared()
        await self.rare(2)
        before = await self.pokemon()
        result = await self.rare_confirm(session)
        self.assertEqual(result["status"], "powered_up")
        self.assertEqual(await self.pokemon(), {**before, "level_x2": before["level_x2"] + 1, "revision": 1})
        self.assertEqual(await self.rows("SELECT quantity FROM inventory WHERE item_id='rare_candy'"), [{"quantity": 1}])
        self.assertEqual(await self.service().balances(self.conn, self.profile["profile_id"]),
                         {"stardust": 0, "candy": {}})
        lines = await self.rows("SELECT * FROM resource_ledger WHERE reason='powerup'")
        self.assertEqual([(r["resource"], r["resource_id"], r["delta"]) for r in lines], [("item", "rare_candy", -1)])

    async def test_rare_candy_quote_and_refusals(self):
        session = await self.prepared()
        quote = await self.quote()
        self.assertEqual((quote["rare_candy_have"], quote["rare_affordable"]), (0, False))
        before = await self.rare_snapshot()
        self.assertEqual((await self.rare_confirm(session))["status"], "insufficient")
        self.assertEqual(await self.rare_snapshot(), before)
        await self.rare(1)
        quote = await self.quote()
        self.assertEqual((quote["rare_candy_have"], quote["rare_affordable"]), (1, True))
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET level_x2=80"))
        quote = await self.quote()
        self.assertFalse(quote["rare_affordable"])
        before = await self.rare_snapshot()
        self.assertEqual((await self.rare_confirm(session))["status"], "at_cap")
        self.assertEqual(await self.rare_snapshot(), before)

    async def test_rare_candy_deployed_stale_and_replay_spend_once(self):
        session = await self.prepared()
        await self.rare(3)
        first = await self.rare_confirm(session)
        self.assertEqual(first["status"], "powered_up")
        before = await self.rare_snapshot()
        self.assertEqual(await self.rare_confirm(session), first)
        self.assertEqual(await self.rare_snapshot(), before)
        self.assertEqual((await self.rare_confirm(session, 5))["status"], "stale")
        await self.deploy(session)
        before = await self.rare_snapshot()
        self.assertEqual((await self.rare_confirm(session, (await self.pokemon())["revision"]))["status"], "stale")
        self.assertEqual(await self.rare_snapshot(), before)

    async def test_rare_candy_button_powers_up_from_quote_screen(self):
        session = await self.prepared()
        _, session = await self.details(session)
        rendered, session = await self.screen(session)
        self.assertIn("Rare Candy (have 0)", rendered["embed"].description)
        self.assertTrue(self.buttons(rendered)["Use Rare Candy"].disabled)
        await self.rare(1)
        rendered, session = await self.screen(session)
        self.assertIn("Rare Candy (have 1)", rendered["embed"].description)
        self.assertTrue(self.buttons(rendered)["Confirm"].disabled)
        self.assertFalse(self.buttons(rendered)["Use Rare Candy"].disabled)
        before = await self.pokemon()
        rendered, session = await self.screen(session, "power_up_rare")
        self.assertEqual(rendered["embed"].title, "Pokémon details")
        self.assertEqual((await self.pokemon())["level_x2"], before["level_x2"] + 1)
        self.assertEqual(json.loads(session["selection"])["pokemon_revision"], 1)
        self.assertEqual(await self.rows("SELECT quantity FROM inventory WHERE item_id='rare_candy'"), [{"quantity": 0}])
