"""C5 private trade screens and handlers on the shared Walker router (pokemon-trading T6)."""

import copy
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import discord

from pokewalker.db import Writer, open_db
from pokewalker.services import profiles, storage, trading
from pokewalker.services.reactions import ReactionService
from test_reactions import FakeDiscord

CONTENT = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))
TRADE_TIMED_OUT = "This window timed out. Please reopen /trade for a fresh one."
TRADE_OUTDATED = "This screen is out of date. Please reopen /trade to refresh."
TRADE_REOPEN = "That option changed since this screen opened. Please reopen /trade to refresh."
NOT_YOURS = "This screen is not yours. Open /walker for your own screen."
ACTIONS = {"trade_pick", "trade_offer", "trade_confirm", "trade_refresh", "trade_cancel", "trade_prev", "trade_next"}


class TradeScreenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.module = importlib.import_module("pokewalker.bot.trade")
        except ModuleNotFoundError:
            self.fail("pokewalker.bot.trade is absent")
        self.walker_module = importlib.import_module("pokewalker.bot.walker")
        self.conn = await open_db(":memory:", allow_unpatched=True)
        self.addAsyncCleanup(self.conn.close)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        self.bot = FakeDiscord(self.conn)
        self.bot.writer = self.writer
        self.bot.content = CONTENT
        self.bot.help_text = "Approved help"
        self.bot.reactions = ReactionService(self.bot)
        self.now = 2_000_000_000.0
        self.walker = self.walker_module.Walker(self.bot, clock=lambda: self.now, rng=random.Random(8))
        self.bot.walker = self.walker
        self.profiles = {}
        for user in (456, 789, 999):
            self.profiles[user] = await self.writer.run(lambda conn, user=user: profiles.enroll(
                conn, 123, user, 1, CONTENT, random.Random(8), datetime.now(timezone.utc)))
        self.sids = {}

    # --- helpers -------------------------------------------------------------------------------------------------

    def interaction(self, user, values=None):
        async def edit(**kwargs):
            self.assertFalse(self.conn.in_transaction)
        return SimpleNamespace(user=SimpleNamespace(id=user), guild_id=123, client=self.bot,
                               data={"values": values or []},
                               response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()),
                               edit_original_response=AsyncMock(side_effect=edit))

    async def rows(self, sql, args=()):
        return [dict(row) for row in await self.conn.execute_fetchall(sql, args)]

    async def session(self, user):
        return (await self.rows("SELECT * FROM sessions WHERE session_id=?", (self.sids[user],)))[0]

    async def start(self, user, selection="{}"):
        sid = str(uuid4())
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO sessions(session_id,guild_id,user_id,profile_id,revision,expires_at,selection) "
            "VALUES (?,'123',?,?,0,?,?)", (sid, str(user), self.profiles[user]["profile_id"], self.now + 900,
                                           selection)))
        self.sids[user] = sid
        return sid

    async def join(self, user, partner):
        """Open or join a trade through the service, then point this user's new session at it (as /trade will)."""
        await self.start(user)
        session = await self.session(user)
        result = await self.writer.run(lambda conn: trading.open_or_join(conn, session, str(partner), self.now, False))
        self.assertIn(result["status"], ("opened", "joined"))
        await self.writer.run(lambda conn: conn.execute(
            "UPDATE sessions SET selection=? WHERE session_id=?",
            (json.dumps({"trade_id": result["trade_id"], "trade_revision": 0, "phase": "trade"}), self.sids[user])))
        return result["trade_id"]

    async def pair(self):
        trade_id = await self.join(456, 789)
        await self.join(789, 456)
        return trade_id

    async def mon(self, user, uid, pokemon_id=16, shiny=0, favorite=0, caught_at=100):
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,gender,"
            "shiny,origin,favorite,content_version,caught_at) VALUES (?,?,?,20,15,15,15,'male',?,'catch',?,'test',?)",
            (uid, self.profiles[user]["profile_id"], pokemon_id, shiny, favorite, caught_at)))

    async def press(self, user, action, values=None, *, presser=None, revision=None, session_id=None):
        session = await self.session(user)
        interaction = self.interaction(presser or user, values)
        rev = session["revision"] if revision is None else revision
        await self.walker.route(interaction, f"pw:v1:{session_id or session['session_id']}:{rev}:{action}")
        return interaction

    async def offer(self, user, uid):
        await self.press(user, "trade_pick")
        return await self.press(user, "trade_offer", [uid])

    def shown(self, interaction):
        interaction.followup.send.assert_not_awaited()
        kwargs = interaction.edit_original_response.await_args.kwargs
        return kwargs["embed"].description, kwargs.get("view")

    def refused(self, interaction):
        interaction.edit_original_response.assert_not_awaited()
        return interaction.followup.send.await_args.args[0]

    @staticmethod
    def controls(view):
        return {item.custom_id.rsplit(":", 1)[1]: item for item in (view.children if view is not None else [])}

    async def trade_state(self, trade_id):
        return (await self.rows("SELECT * FROM trades WHERE trade_id=?", (trade_id,)),
                await self.rows("SELECT * FROM trade_sides WHERE trade_id=? ORDER BY side", (trade_id,)))

    async def snapshot(self, view_user=456, trade_id=None):
        session = await self.session(view_user)
        return session, await self.writer.run(lambda conn: trading.view(
            conn, session, trade_id, self.now, CONTENT, self.walker.multipliers))

    # --- renderers -----------------------------------------------------------------------------------------------

    async def test_trade_renderers_do_no_io(self):
        trade_id = await self.pair()
        await self.mon(456, "mine", shiny=1)
        await self.mon(789, "theirs", pokemon_id=144)
        await self.offer(456, "mine")
        await self.offer(789, "theirs")
        session, view = await self.snapshot(456, trade_id)
        rows, eligible, owned = await self.writer.run(lambda conn: trading.eligible_page(
            conn, session["profile_id"], 0, self.now))
        picker = {"session": session, "rows": [storage.stats(CONTENT, row, self.walker.multipliers)
                                               for row in rows], "eligible": eligible, "owned": owned, "offset": 0}
        completed = {**view, "session": session, "state": "completed", "received": {"name": "Articuno", "cp": 99}}
        ended = {**view, "session": session, "state": "cancelled"}
        trade = {**view, "session": session}
        states = [trade, picker, completed, ended]
        original = copy.deepcopy(states)
        with patch("builtins.open", side_effect=AssertionError("render file I/O")), \
                patch("aiosqlite.connect", side_effect=AssertionError("render DB I/O")):
            for render, state in ((self.module.render_trade, trade), (self.module.render_picker, picker),
                                  (self.module.render_result, completed), (self.module.render_result, ended)):
                rendered = render(state)
                self.assertIsInstance(rendered["embed"], discord.Embed)
                ids = [item.custom_id for item in (rendered["view"].children if rendered["view"] else [])]
                self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(states, original)

    async def test_confirm_disabled_until_both_joined_and_offered(self):
        trade_id = await self.join(456, 789)
        text, view = self.shown(await self.press(456, "trade_refresh"))
        self.assertIn("Trade with <@789>", text)
        self.assertIn("Waiting for them to join: they run /trade member:@you", text)
        self.assertIn("You offer: nothing yet", text)
        self.assertIn("They offer: nothing yet", text)
        self.assertIn("Expires 15 min after the last join, offer or confirm (now ", text)
        buttons = self.controls(view)
        self.assertEqual(set(buttons), {"trade_pick", "trade_confirm", "trade_refresh", "trade_cancel"})
        self.assertEqual([buttons[key].label for key in ("trade_pick", "trade_confirm", "trade_refresh", "trade_cancel")],
                         ["Choose Pokémon", "Confirm", "Refresh", "Cancel trade"])
        self.assertTrue(buttons["trade_confirm"].disabled)
        await self.mon(456, "mine")
        text, view = self.shown(await self.offer(456, "mine"))
        self.assertIn("You offer: Pidgey · ", text)
        self.assertTrue(self.controls(view)["trade_confirm"].disabled)
        await self.join(789, 456)
        text, view = self.shown(await self.press(456, "trade_refresh"))
        self.assertNotIn("Waiting for them to join", text)
        self.assertTrue(self.controls(view)["trade_confirm"].disabled)
        await self.mon(789, "theirs", pokemon_id=19)
        await self.offer(789, "theirs")
        text, view = self.shown(await self.press(456, "trade_refresh"))
        self.assertIn("They offer: Rattata · ", text)
        self.assertIn("CP ", text)
        self.assertIn("stars", text)
        self.assertFalse(self.controls(view)["trade_confirm"].disabled)
        text, view = self.shown(await self.press(456, "trade_confirm"))
        self.assertIn("Confirmed. Waiting for them.", text)
        self.assertTrue(self.controls(view)["trade_confirm"].disabled)
        _, sides = await self.trade_state(trade_id)
        self.assertEqual([side["confirmed_revision"] is not None for side in sides], [True, False])
        # The renderer itself also requires the partner's join, not only both offers.
        session, state = await self.snapshot(456, trade_id)
        state = {**state, "session": session, "partner_joined": False, "my_confirmed": False}
        self.assertTrue(self.controls(self.module.render_trade(state)["view"])["trade_confirm"].disabled)
        self.assertFalse(self.controls(self.module.render_trade({**state, "partner_joined": True})["view"])
                         ["trade_confirm"].disabled)

    async def test_special_trade_warning_both_sides(self):
        await self.pair()
        await self.mon(456, "plain")
        await self.mon(789, "plain2", pokemon_id=19)
        await self.offer(456, "plain")
        await self.offer(789, "plain2")
        text, _ = self.shown(await self.press(456, "trade_refresh"))
        self.assertNotIn("Special trade", text)
        await self.mon(456, "shiny", shiny=1)
        await self.mon(789, "legend", pokemon_id=144)
        await self.offer(456, "shiny")
        await self.offer(789, "legend")
        for user, mine, theirs in ((456, "Pidgey", "Articuno"), (789, "Articuno", "Pidgey")):
            text, _ = self.shown(await self.press(user, "trade_refresh"))
            line = next(line for line in text.splitlines() if line.startswith("Special trade: "))
            self.assertIn(f"your {mine}", line)
            self.assertIn(f"their {theirs}", line)
            self.assertIn("Shiny", line)
            self.assertIn("Legendary", line)

    async def arena_run(self, user, uid):
        await self.writer.run(lambda conn: conn.execute(
            'INSERT INTO arena_runs(run_id,profile_id,started_at,floor,slot,team,enemy) '
            'VALUES (?,?,?,1,0,?,?)',
            ('arena-' + str(user), self.profiles[user]['profile_id'], self.now,
             json.dumps([{'uid': uid, 'family_id': 1, 'special': False, 'full_hp': 40,
                          'hp': 40, 'snapshot': {}}]),
             json.dumps({'snapshot': {}, 'battle_hp': 40, 'special': False}))))

    async def test_picker_omits_team_member_and_offer_text_names_arena(self):
        trade_id = await self.pair()
        await self.mon(456, 'busy')
        await self.mon(456, 'spare')
        await self.arena_run(456, 'busy')
        text, view = self.shown(await self.press(456, 'trade_pick'))
        self.assertIn('1 tradable of 3 owned', text)
        self.assertEqual([o.value for o in self.controls(view)['trade_offer'].options], ['spare'])
        before = await self.trade_state(trade_id)
        self.assertEqual(self.refused(await self.press(456, 'trade_offer', ['busy'])), TRADE_REOPEN)
        self.assertEqual(await self.trade_state(trade_id), before)
        # The picker rejects busy UIDs first; exercise the service-refusal notice separately.
        with patch.object(trading, 'offer', new=AsyncMock(return_value={'status': 'ineligible', 'reason': 'in_arena'})):
            text, _ = self.shown(await self.press(456, 'trade_offer', ['spare']))
        self.assertIn("That Pokémon can't be traded: it is on an Arena team.", text)

    async def test_acceptance_refusal_text_names_arena_for_either_side(self):
        await self.pair()
        await self.mon(456, 'mine')
        await self.mon(789, 'theirs')
        await self.mon(789, 'spare')
        await self.offer(456, 'mine')
        await self.offer(789, 'theirs')
        await self.press(456, 'trade_refresh')
        await self.press(456, 'trade_confirm')
        await self.arena_run(789, 'theirs')
        await self.press(789, 'trade_refresh')
        text, _ = self.shown(await self.press(789, 'trade_confirm'))
        self.assertIn("Your Pokémon can't be traded: it is on an Arena team.", text)
        await self.offer(789, 'spare')
        await self.press(456, 'trade_refresh')
        await self.press(456, 'trade_confirm')
        await self.arena_run(456, 'mine')
        await self.press(789, 'trade_refresh')
        text, _ = self.shown(await self.press(789, 'trade_confirm'))
        self.assertIn("Their Pokémon can't be traded: it is on an Arena team.", text)

    async def test_picker_lists_only_eligible_ten_per_page(self):
        await self.pair()
        for number in range(11):
            await self.mon(456, f"m{number:02}", caught_at=1000 - number)
        await self.mon(456, "fav", favorite=1, caught_at=5000)
        text, view = self.shown(await self.press(456, "trade_pick"))
        self.assertIn("11 tradable of 13 owned · favorites, your companion and gym defenders can't be traded", text)
        controls = self.controls(view)
        self.assertEqual(set(controls), {"trade_offer", "trade_prev", "trade_next", "trade_refresh"})
        self.assertEqual([controls[key].label for key in ("trade_prev", "trade_next", "trade_refresh")],
                         ["Prev", "Next", "Back"])
        options = controls["trade_offer"].options
        self.assertEqual([option.value for option in options], [f"m{number:02}" for number in range(10)])
        self.assertTrue(options[0].label.startswith("#1 Pidgey · CP "))
        self.assertTrue(controls["trade_prev"].disabled)
        self.assertFalse(controls["trade_next"].disabled)
        _, view = self.shown(await self.press(456, "trade_next"))
        controls = self.controls(view)
        self.assertEqual([(option.label.split(" ")[0], option.value) for option in controls["trade_offer"].options],
                         [("#11", "m10")])
        self.assertTrue(controls["trade_next"].disabled)
        self.assertFalse(controls["trade_prev"].disabled)
        _, view = self.shown(await self.press(456, "trade_prev"))
        self.assertEqual(len(self.controls(view)["trade_offer"].options), 10)
        text, view = self.shown(await self.press(456, "trade_refresh"))
        self.assertIn("Trade with <@789>", text)

    async def test_picker_refuses_value_not_on_shown_page(self):
        trade_id = await self.pair()
        for number in range(11):
            await self.mon(456, f"m{number:02}", caught_at=1000 - number)
        await self.mon(456, "fav", favorite=1)
        await self.press(456, "trade_pick")
        before = await self.trade_state(trade_id)
        for values in (["m10"], ["fav"], [self.profiles[456]["companion_uid"]], ["m00", "m01"], []):
            session = await self.session(456)
            interaction = await self.press(456, "trade_offer", values)
            self.assertEqual(self.refused(interaction), TRADE_REOPEN)
            self.assertEqual(await self.session(456), session)
        self.assertEqual(await self.trade_state(trade_id), before)
        await self.press(456, "trade_refresh")
        self.assertEqual(self.refused(await self.press(456, "trade_offer", ["m00"])), TRADE_REOPEN)
        self.assertEqual(await self.trade_state(trade_id), before)
        text, _ = self.shown(await self.offer(456, "m00"))
        self.assertIn("You offer: Pidgey", text)

    async def test_refresh_shows_partner_change_needs_reconfirm(self):
        trade_id = await self.pair()
        await self.mon(456, "mine")
        await self.mon(789, "first", pokemon_id=19)
        await self.mon(789, "second", pokemon_id=25)
        await self.offer(456, "mine")
        await self.offer(789, "first")
        await self.press(456, "trade_refresh")
        text, view = self.shown(await self.press(456, "trade_confirm"))
        self.assertIn("You: confirmed", text)
        self.assertIn("Them: not confirmed", text)
        await self.offer(789, "second")
        text, view = self.shown(await self.press(456, "trade_refresh"))
        self.assertIn("They offer: Pikachu", text)
        self.assertIn("You: not confirmed", text)
        self.assertFalse(self.controls(view)["trade_confirm"].disabled)
        trade, _ = await self.trade_state(trade_id)
        self.assertEqual(json.loads((await self.session(456))["selection"])["trade_revision"], trade[0]["revision"])

    async def test_stale_confirm_shows_changed_notice(self):
        trade_id = await self.pair()
        await self.mon(456, "mine")
        await self.mon(789, "first", pokemon_id=19)
        await self.mon(789, "second", pokemon_id=25)
        await self.offer(456, "mine")
        await self.offer(789, "first")
        await self.press(456, "trade_refresh")
        await self.offer(789, "second")
        text, view = self.shown(await self.press(456, "trade_confirm"))
        self.assertIn("The offer changed — review it and confirm again.", text)
        self.assertIn("They offer: Pikachu", text)
        self.assertFalse(self.controls(view)["trade_confirm"].disabled)
        _, sides = await self.trade_state(trade_id)
        self.assertEqual([side["confirmed_revision"] for side in sides], [None, None])
        text, _ = self.shown(await self.press(456, "trade_confirm"))
        self.assertIn("Confirmed. Waiting for them.", text)

    async def test_confirm_refused_from_picker_phase(self):
        trade_id = await self.pair()
        await self.mon(456, "mine")
        await self.mon(789, "theirs", pokemon_id=19)
        await self.offer(456, "mine")
        await self.offer(789, "theirs")
        await self.press(456, "trade_refresh")
        await self.press(456, "trade_pick")
        session = await self.session(456)
        self.assertEqual(json.loads(session["selection"])["phase"], "pick")
        self.assertEqual(self.refused(await self.press(456, "trade_confirm")), TRADE_REOPEN)
        self.assertEqual(await self.session(456), session)
        _, sides = await self.trade_state(trade_id)
        self.assertEqual([side["confirmed_revision"] for side in sides], [None, None])
        await self.press(456, "trade_refresh")
        text, _ = self.shown(await self.press(456, "trade_confirm"))
        self.assertIn("Confirmed. Waiting for them.", text)

    async def test_offer_invalid_notice_names_whose_pokemon(self):
        await self.pair()
        await self.mon(456, "mine")
        await self.mon(789, "theirs", pokemon_id=19)
        await self.mon(789, "spare", pokemon_id=25)
        await self.offer(456, "mine")
        await self.offer(789, "theirs")
        await self.press(456, "trade_refresh")
        await self.press(456, "trade_confirm")
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET favorite=1 WHERE pokemon_uid='theirs'"))
        await self.press(789, "trade_refresh")
        text, _ = self.shown(await self.press(789, "trade_confirm"))
        self.assertIn("Your Pokémon can't be traded: it is a favorite.", text)
        await self.offer(789, "spare")
        await self.press(456, "trade_refresh")
        await self.press(456, "trade_confirm")
        await self.writer.run(lambda conn: conn.execute("UPDATE pokemon SET favorite=1 WHERE pokemon_uid='mine'"))
        await self.press(789, "trade_refresh")
        text, _ = self.shown(await self.press(789, "trade_confirm"))
        self.assertIn("Their Pokémon can't be traded: it is a favorite.", text)

    async def test_capped_notice_shows_wait_only_for_self(self):
        trade_id = await self.pair()
        await self.mon(456, "mine")
        await self.mon(789, "theirs", pokemon_id=19)
        await self.offer(456, "mine")
        await self.offer(789, "theirs")
        await self.press(456, "trade_refresh")
        await self.press(789, "trade_refresh")
        last = self.now - trading.CAP_SECONDS + 2 * 3600 + 5 * 60 + 1
        await self.writer.run(lambda conn: conn.execute("UPDATE profiles SET last_trade_at=? WHERE profile_id=?",
                                                        (last, self.profiles[456]["profile_id"])))
        text, _ = self.shown(await self.press(456, "trade_confirm"))
        self.assertIn("You can trade again in 2h 6m.", text)
        text, _ = self.shown(await self.press(789, "trade_confirm"))
        self.assertIn("They can't trade again yet.", text)
        self.assertNotIn("trade again in", text)
        trade, sides = await self.trade_state(trade_id)
        self.assertEqual(trade[0]["state"], "open")
        self.assertEqual([side["confirmed_revision"] for side in sides], [None, None])

    async def test_other_member_cannot_press_trade_buttons(self):
        trade_id = await self.pair()
        await self.mon(456, "mine")
        await self.start(999, json.dumps({"trade_id": trade_id, "trade_revision": 0}))
        before = (await self.trade_state(trade_id), await self.rows("SELECT * FROM sessions ORDER BY session_id"))
        for presser in (789, 999):
            for action, values in (("trade_cancel", None), ("trade_confirm", None), ("trade_pick", None),
                                   ("trade_offer", ["mine"]), ("trade_refresh", None)):
                interaction = await self.press(456, action, values, presser=presser)
                self.assertEqual(self.refused(interaction), NOT_YOURS)
        self.assertEqual((await self.trade_state(trade_id),
                          await self.rows("SELECT * FROM sessions ORDER BY session_id")), before)
        # A non-participant's own session holding the trade ID is refused by the service check.
        for action in ("trade_refresh", "trade_cancel", "trade_pick"):
            self.assertEqual(self.refused(await self.press(999, action)), TRADE_REOPEN)
        self.assertEqual((await self.trade_state(trade_id),
                          await self.rows("SELECT * FROM sessions ORDER BY session_id")), before)

    async def test_trade_timed_out_says_reopen_trade(self):
        await self.pair()
        session = await self.session(456)
        self.now += 901
        self.assertEqual(self.refused(await self.press(456, "trade_refresh")), TRADE_TIMED_OUT)
        self.assertEqual(self.refused(await self.press(456, "trade_refresh", session_id=str(uuid4()))),
                         TRADE_TIMED_OUT)
        self.assertEqual(await self.session(456), session)
        self.assertEqual(self.refused(await self.press(456, "home")),
                         "This window timed out. Please reopen /walker for a fresh one.")

    async def test_trade_outdated_says_reopen_trade(self):
        await self.pair()
        self.shown(await self.press(456, "trade_refresh"))
        self.now += 11
        session = await self.session(456)
        self.assertEqual(self.refused(await self.press(456, "trade_refresh", revision=0)), TRADE_OUTDATED)
        self.assertEqual(self.refused(await self.press(456, "home", revision=0)),
                         "This screen is out of date. Please reopen /walker to refresh.")
        self.assertEqual(await self.session(456), session)

    async def test_trade_handler_refusal_says_reopen_trade(self):
        trade_id = await self.pair()
        await self.start(456, "{}")
        for action in sorted(ACTIONS):
            session = await self.session(456)
            self.assertEqual(self.refused(await self.press(456, action, ["x"])), TRADE_REOPEN)
            self.assertEqual(await self.session(456), session)
        await self.start(456, json.dumps({"trade_id": trade_id, "trade_revision": 0}))
        # The offer select and paging only work from the picker this screen showed.
        for action in ("trade_offer", "trade_prev", "trade_next"):
            self.assertEqual(self.refused(await self.press(456, action, ["x"])), TRADE_REOPEN)
        self.assertEqual(self.refused(await self.press(456, "trade_unknown")), TRADE_REOPEN)

    async def test_trade_double_press_within_10s_is_silent(self):
        await self.pair()
        self.shown(await self.press(456, "trade_refresh"))
        self.now += 9
        session = await self.session(456)
        interaction = await self.press(456, "trade_refresh", revision=0)
        interaction.edit_original_response.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()
        self.assertEqual(await self.session(456), session)

    async def test_completed_screen_names_received_pokemon_no_home(self):
        trade_id = await self.pair()
        await self.mon(456, "mine")
        await self.mon(789, "theirs", pokemon_id=25)
        await self.offer(456, "mine")
        await self.offer(789, "theirs")
        await self.press(456, "trade_refresh")
        await self.press(789, "trade_refresh")
        self.shown(await self.press(456, "trade_confirm"))
        text, view = self.shown(await self.press(789, "trade_confirm"))
        trade, _ = await self.trade_state(trade_id)
        self.assertEqual(trade[0]["state"], "completed")
        self.assertRegex(text, r"^You received Pidgey \(CP \d+\)\. It counts for your Pokédex\. "
                               r"Open /walker → Storage to see it\.$")
        self.assertFalse(self.controls(view))
        text, view = self.shown(await self.press(456, "trade_refresh"))
        self.assertRegex(text, r"^You received Pikachu \(CP \d+\)\.")
        self.assertFalse(self.controls(view))

    async def test_result_follows_state_and_tolerates_missing_received(self):
        # T5 review F1/F2: a completed trade clears both confirmed flags and may lack `received`.
        session = {"session_id": "s", "revision": 3}
        base = {"session": session, "trade_id": "t", "revision": 4, "expires_at": self.now, "my_side": 0,
                "partner_user_id": "789", "partner_joined": True, "mine": None, "theirs": None,
                "my_confirmed": False, "partner_confirmed": False}
        rendered = self.module.render_result({**base, "state": "completed", "received": {"name": "Mew", "cp": 12}})
        self.assertEqual(rendered["embed"].description, "You received Mew (CP 12). It counts for your Pokédex. "
                                                        "Open /walker → Storage to see it.")
        rendered = self.module.render_result({**base, "state": "completed", "received": None})
        self.assertEqual(rendered["embed"].description, "Trade complete. It counts for your Pokédex. "
                                                        "Open /walker → Storage to see it.")
        self.assertFalse(self.controls(rendered["view"]))
        for state in ("cancelled", "expired"):
            rendered = self.module.render_result({**base, "state": state, "received": None})
            self.assertEqual(rendered["embed"].description, "This trade ended. Use /trade member to start again.")

    async def test_trade_screens_offer_no_home_or_walker_button(self):
        await self.pair()
        await self.mon(456, "again")
        for action in ("trade_refresh", "trade_pick"):
            _, view = self.shown(await self.press(456, action))
            for item in view.children:
                self.assertNotIn("home", item.custom_id)
                self.assertTrue(item.custom_id.rsplit(":", 1)[1] in ACTIONS)
                self.assertNotIn("walker", str(getattr(item, "label", "")).lower())

    async def test_buttons_work_after_channel_removed(self):
        await self.writer.run(lambda conn: conn.execute(
            "INSERT INTO trade_channels(guild_id,channel_id) VALUES ('123','555')"))
        trade_id = await self.pair()
        await self.writer.run(lambda conn: conn.execute("DELETE FROM trade_channels"))
        await self.mon(456, "mine")
        text, _ = self.shown(await self.offer(456, "mine"))
        self.assertIn("You offer: Pidgey", text)
        text, view = self.shown(await self.press(456, "trade_cancel"))
        self.assertEqual(text, "This trade ended. Use /trade member to start again.")
        self.assertFalse(self.controls(view))
        self.assertEqual((await self.trade_state(trade_id))[0][0]["state"], "cancelled")
        text, _ = self.shown(await self.press(789, "trade_refresh"))
        self.assertEqual(text, "This trade ended. Use /trade member to start again.")

    async def test_home_screen_has_no_trade_entry(self):
        self.assertTrue(ACTIONS <= set(self.walker.handlers))
        interaction = self.interaction(456)
        await self.walker.open(interaction)
        kwargs = interaction.edit_original_response.await_args.kwargs
        for item in kwargs["view"].children:
            self.assertNotIn("trade", item.custom_id)
            self.assertNotIn("trade", str(getattr(item, "label", "")).lower())
        self.assertNotIn("trade", kwargs["embed"].description.lower())


if __name__ == "__main__":
    unittest.main()
