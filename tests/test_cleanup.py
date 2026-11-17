"""D74 data cleanup: clocks, receipts, counters, reactions and space reclaim on real SQLite."""

import asyncio
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from pokewalker import db
import test_catching as catching
import test_reactions as reactions
import test_stepping as stepping
import test_walker_ack as ack

NOW = 10_000_000.0
HOUR, DAY = 3600, 86400
REPO = Path(__file__).resolve().parents[1]


def cleanup_module(test):
    try:
        return importlib.import_module("pokewalker.services.cleanup")
    except ModuleNotFoundError:
        test.fail("D74 cleanup service is absent")


async def add_encounter(conn, *, profile="p", state="caught", resolved=None, acknowledged=None,
                        raid=None, encounter_id=None, created=0):
    encounter_id = encounter_id or str(uuid4())
    await conn.execute(
        "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
        "gender,shiny,tier,route_id,content_version,created_at,state,resolved_at,acknowledged_at,raid_spawn_id) "
        "VALUES (?,?,25,20,1,2,3,'male',0,'common','refreshing_field','fixture',?,?,?,?,?)",
        (encounter_id, profile, created, state, resolved, acknowledged, raid))
    return encounter_id


async def add_receipt(conn, key, *, created=0, profile="p", action="fixture", lines=1):
    await conn.execute("INSERT INTO action_receipts(key,action,result,created_at,profile_id) VALUES (?,?,'{}',?,?)",
                       (key, action, created, profile))
    for line in range(lines):
        await conn.execute("INSERT INTO resource_ledger VALUES (?,?,?,'stardust',NULL,1,'fixture')",
                           (key, line, profile))
    return key


async def add_throw(conn, encounter_id, ordinal=0, success=0, *, profile="p"):
    key = await add_receipt(conn, f"throw:{encounter_id}:{ordinal}", action="throw", profile=profile)
    await conn.execute("INSERT INTO catch_attempts(encounter_id,ordinal,ball,p,success,fled,receipt_key,created_at) "
                       "VALUES (?,?,'poke_ball',0.5,?,0,?,0)", (encounter_id, ordinal, success, key))
    return key


async def add_pokemon(conn, encounter_id, *, profile="p"):
    uid = str(uuid4())
    await conn.execute("INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
                       "iv_stamina,gender,shiny,origin,source_encounter_id,content_version,caught_at) "
                       "VALUES (?,?,25,20,1,2,3,'male',0,'catch',?,'fixture',0)", (uid, profile, encounter_id))
    return uid


async def add_spawn(conn, spawn_id, *, ended=0, expires=NOW + HOUR, guild="g"):
    await conn.execute("INSERT INTO world_spawns(spawn_id,guild_id,channel_id,pokemon_id,identity_id,spawned_at,"
                       "expires_at,post_state,ended,content_version) VALUES (?,?,'1',144,'articuno',0,?,'sent',?,'f')",
                       (spawn_id, guild, expires, ended))


async def add_gym_battle(conn, battle_id, created, *, profile="p"):
    await conn.execute("INSERT INTO gym_battles(battle_id,guild_id,gym_id,challenger_profile_id,outcome,reason,"
                       "ticks,events,engine,created_at) VALUES (?,'g','gym',?,'win','defender_fainted',1,'[]','1',?)",
                       (battle_id, profile, created))


async def add_run(conn, run_id, started, *, profile="p", ended=True):
    await conn.execute("INSERT INTO arena_runs(run_id,profile_id,started_at,ended_at,end_reason,floor,slot,team,enemy) "
                       "VALUES (?,?,?,?,?,1,0,'[]','{}')",
                       (run_id, profile, started, started + 1 if ended else None, "loss" if ended else None))


async def add_step(conn, message_id, created, *, profile="p", awarded=100):
    await conn.execute("INSERT INTO step_events VALUES (?,?,'1',4,4,0,?,'credited',?)",
                       (message_id, profile, awarded, created))


async def seed_worst_case(conn, now, *, batch=1000, profiles=101):
    """Every cleanup stage just over its cap; used by the cap test and the timing record."""
    old = now - 2 * DAY - 1
    for index in range(profiles):
        pid = f"arena-{index}"
        await conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES (?,'g',?,0)",
                           (pid, f"u{index}"))
        await add_run(conn, f"{pid}-old", 1, profile=pid)
        await add_run(conn, f"{pid}-new", 2, profile=pid)
        for kind in ("arena_fight", "arena_use", "arena_heal"):
            for n in range(20):
                await add_receipt(conn, f"{kind}:{pid}-old:{n}", profile=pid)
    encounters = []
    for _ in range(batch + 1):
        eid = await add_encounter(conn, state="caught", resolved=old, acknowledged=old)
        await add_throw(conn, eid, 0, 1)
        await add_receipt(conn, f"run:{eid}:0")
        await add_receipt(conn, f"research:auto:{eid}")
        encounters.append(eid)
    for index in range(batch + 1):
        await add_step(conn, f"m{index}", old)
        await add_gym_battle(conn, f"b{index}", old)
        await add_receipt(conn, f"battle:s{index}:1", created=old)
    for kind in ("throw:{}:0", "run:{}:1", "research:auto:{}"):
        for _ in range(batch):
            await add_receipt(conn, kind.format(uuid4()))
    return encounters


class CleanupBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cleanup = cleanup_module(self)
        root = REPO / "build/test-cleanup"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "game.sqlite3"
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('g')")
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('p','g','u',0)")
        await self.conn.execute("INSERT INTO gyms(gym_id,guild_id,name,created_at) VALUES ('gym','g','Gym',0)")

    async def sweep(self, now=NOW, resume=None, **kwargs):
        return await self.writer.run(lambda conn: self.cleanup.sweep(conn, now, resume, **kwargs))

    async def column(self, sql, args=()):
        return [row[0] for row in await self.conn.execute_fetchall(sql, args)]

    async def scalar(self, sql, args=()):
        return (await self.conn.execute_fetchall(sql, args))[0][0]

    async def encounters(self):
        return set(await self.column("SELECT encounter_id FROM encounters"))

    async def keys(self, pattern="*"):
        return set(await self.column("SELECT key FROM action_receipts WHERE key GLOB ?", (pattern,)))

    async def ledger(self):
        return set(await self.column("SELECT DISTINCT receipt_key FROM resource_ledger"))


class EncounterClockTests(CleanupBase):
    async def test_encounter_clocks(self):
        c = self.conn
        gone = {
            "ack_caught": await add_encounter(c, state="caught", resolved=NOW - HOUR, acknowledged=NOW - HOUR),
            "ack_fled": await add_encounter(c, state="fled", resolved=NOW - HOUR - 1, acknowledged=NOW - 10),
            "ack_ran": await add_encounter(c, state="ran", resolved=NOW - 5 * DAY, acknowledged=NOW - 5 * DAY),
            "unack_fled_24h": await add_encounter(c, state="fled", resolved=NOW - DAY),
            "unack_ran_24h": await add_encounter(c, state="ran", resolved=NOW - DAY - 5),
            "unack_stored_24h": await add_encounter(c, state="caught", resolved=NOW - DAY),
        }
        kept = {
            "ack_recent": await add_encounter(c, state="caught", resolved=NOW - HOUR + 1, acknowledged=NOW - 1),
            "unack_fled_23h": await add_encounter(c, state="fled", resolved=NOW - 23 * HOUR),
            "unack_stored_23h": await add_encounter(c, state="caught", resolved=NOW - 23 * HOUR),
            "unack_waiting": await add_encounter(c, state="caught", resolved=NOW - 30 * DAY),
            "queued": await add_encounter(c, state="queued"),
            "revealed": await add_encounter(c, state="revealed"),
        }
        await add_spawn(c, "live")
        kept["live_raid"] = await add_encounter(c, state="caught", resolved=NOW - DAY, acknowledged=NOW - DAY,
                                                raid="live")
        stored = await add_pokemon(c, gone["unack_stored_24h"])
        await add_pokemon(c, kept["unack_stored_23h"])
        for name in ("ack_caught", "ack_fled"):
            await add_throw(c, gone[name], 0)
        await add_throw(c, kept["ack_recent"], 0)
        await self.sweep()
        self.assertEqual(await self.encounters(), set(kept.values()))
        self.assertEqual(set(await self.column("SELECT encounter_id FROM catch_attempts")), {kept["ack_recent"]})
        # Stored Pokemon keep everything but the encounter link.
        self.assertEqual(await self.column("SELECT source_encounter_id FROM pokemon WHERE pokemon_uid=?", (stored,)),
                         [None])

    async def test_raid_encounter_waits_for_its_spawn_to_end(self):
        await add_spawn(self.conn, "raid")
        eid = await add_encounter(self.conn, state="caught", resolved=NOW - 2 * HOUR, acknowledged=NOW - 2 * HOUR,
                                  raid="raid")
        await self.conn.execute("INSERT INTO raid_participation VALUES ('g','u','raid',?,0)", (eid,))
        await self.sweep()
        self.assertEqual(await self.encounters(), {eid})
        await self.conn.execute("UPDATE world_spawns SET ended=1")
        await self.sweep()
        self.assertEqual(await self.encounters(), set())
        self.assertEqual(await self.column("SELECT encounter_id FROM raid_participation"), [None])

    async def test_receipts_of_a_deleted_encounter_go_with_it_others_stay(self):
        old = NOW - 2 * HOUR
        eid = await add_encounter(self.conn, state="caught", resolved=old, acknowledged=old)
        live = await add_encounter(self.conn, state="revealed")
        doomed = {await add_throw(self.conn, eid, 0), await add_throw(self.conn, eid, 1, 1),
                  await add_receipt(self.conn, f"run:{eid}:4"), await add_receipt(self.conn, f"research:auto:{eid}")}
        others = {await add_throw(self.conn, live, 0), await add_receipt(self.conn, f"run:{live}:0"),
                  await add_receipt(self.conn, f"research:{eid}:x"), await add_receipt(self.conn, "trade:t:1"),
                  await add_receipt(self.conn, f"companion:{eid}"), await add_receipt(self.conn, "arena_start:p:1")}
        await self.sweep()
        self.assertEqual(await self.keys(), others)
        self.assertEqual(await self.ledger(), others)
        self.assertFalse(doomed & await self.ledger())

    async def test_battle_receipts_go_after_two_days_not_one(self):
        old = await add_receipt(self.conn, "battle:s1:1", created=NOW - 2 * DAY)
        recent = await add_receipt(self.conn, "battle:s2:1", created=NOW - DAY)
        other = await add_receipt(self.conn, "gym_feed:x", created=NOW - 9 * DAY)
        await self.sweep()
        self.assertEqual(await self.keys(), {recent, other})
        self.assertEqual(await self.ledger(), {recent, other})
        self.assertNotIn(old, await self.ledger())

    async def test_gym_battles_older_than_an_hour_go(self):
        await add_gym_battle(self.conn, "old", NOW - HOUR)
        await add_gym_battle(self.conn, "new", NOW - HOUR + 1)
        await self.sweep()
        self.assertEqual(await self.column("SELECT battle_id FROM gym_battles"), ["new"])

    async def test_only_each_profiles_latest_arena_run_remains_with_its_receipts(self):
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('q','g','v',0)")
        await add_run(self.conn, "p-1", 1)
        await add_run(self.conn, "p-2", 2)
        await add_run(self.conn, "p-3", 3, ended=False)
        await add_run(self.conn, "q-a", 5, profile="q")
        await add_run(self.conn, "q-b", 5, profile="q")  # same start: run_id breaks the tie
        kept = set()
        for run in ("p-1", "p-2", "p-3", "q-a", "q-b"):
            for kind in ("arena_fight", "arena_use", "arena_heal"):
                key = await add_receipt(self.conn, f"{kind}:{run}:1:0", profile="p" if run[0] == "p" else "q")
                if run in ("p-3", "q-b"):
                    kept.add(key)
        kept.add(await add_receipt(self.conn, "arena_start:p:1"))
        await self.sweep()
        self.assertEqual(set(await self.column("SELECT run_id FROM arena_runs")), {"p-3", "q-b"})
        self.assertEqual(await self.keys(), kept)
        self.assertEqual(await self.ledger(), kept)

    async def test_a_single_ended_run_stays(self):
        await add_run(self.conn, "only", 1)
        await self.sweep()
        self.assertEqual(await self.column("SELECT run_id FROM arena_runs"), ["only"])

    async def test_step_events_older_than_a_day_go_and_newer_stay(self):
        await add_step(self.conn, "old", NOW - DAY)
        await add_step(self.conn, "new", NOW - DAY + 1)
        await self.sweep()
        self.assertEqual(await self.column("SELECT message_id FROM step_events"), ["new"])

    async def test_each_stage_caps_per_run_and_batch_receipts_cover_exactly_the_batch(self):
        encounters = await self.writer.run(lambda conn: seed_worst_case(conn, NOW))
        await self.sweep()
        self.assertEqual(await self.scalar("SELECT count(*) FROM encounters"), 1)
        survivor = (await self.encounters()).pop()
        self.assertIn(survivor, encounters)
        self.assertEqual(await self.keys(f"*{survivor}*"),
                         {f"throw:{survivor}:0", f"run:{survivor}:0", f"research:auto:{survivor}"})
        self.assertEqual(await self.scalar("SELECT count(*) FROM step_events"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM gym_battles"), 1)
        self.assertEqual(len(await self.keys("battle:*")), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM arena_runs"), 102)
        self.assertEqual(len(await self.keys("arena_*")), 60)

    async def test_a_smaller_batch_caps_every_stage_at_that_size(self):
        await self.writer.run(lambda conn: seed_worst_case(conn, NOW, batch=4, profiles=0))
        await self.sweep(batch=3)
        for table in ("encounters", "step_events", "gym_battles"):
            with self.subTest(table=table):
                self.assertEqual(await self.scalar(f"SELECT count(*) FROM {table}"), 2)
        self.assertEqual(len(await self.keys("battle:*")), 2)


class ReceiptSweepTests(CleanupBase):
    async def test_leftover_throw_receipts_of_an_expired_raid_go_live_and_odd_keys_stay(self):
        from pokewalker.services import raids
        await add_spawn(self.conn, "raid", expires=NOW - 1)
        eid = await add_encounter(self.conn, state="revealed", raid="raid")
        failed = {await add_throw(self.conn, eid, 0), await add_throw(self.conn, eid, 1)}
        live = await add_encounter(self.conn, state="revealed")
        kept = {await add_throw(self.conn, live, 0), await add_receipt(self.conn, f"run:{live}:2"),
                await add_receipt(self.conn, f"research:auto:{live}")}
        odd = {await add_receipt(self.conn, key) for key in (
            "throw:legacy:0", f"throw:{str(uuid4()).upper()}:0", f"throw:{uuid4()}", "run:x:1",
            "research:auto:abc", f"research:auto:{uuid4()}:extra", f"throwx:{uuid4()}:0")}
        await self.writer.run(lambda conn: raids.expire(conn, NOW))
        self.assertEqual(await self.encounters(), {live})
        self.assertTrue(failed <= await self.keys())
        await self.sweep()
        self.assertEqual(await self.keys(), kept | odd)

    async def test_leftover_sweep_examines_at_most_a_batch_per_kind_and_resumes(self):
        async def seed(conn):
            for _ in range(1000):  # unclaimed catches stay; their keys sort before the leftovers
                eid = await add_encounter(conn, state="caught", resolved=NOW,
                                          encounter_id="00000000" + str(uuid4())[8:])
                await add_receipt(conn, f"throw:{eid}:0")
            return {await add_receipt(conn, f"throw:f{str(uuid4())[1:]}:0") for _ in range(5)}
        leftovers = await self.writer.run(seed)
        resume = await self.sweep()
        self.assertEqual(leftovers & await self.keys(), leftovers)  # 1,000 live keys examined first
        again = await self.sweep(resume=None)
        self.assertEqual(leftovers & await self.keys(), leftovers)  # a restart starts over
        resume = await self.sweep(resume=resume)
        self.assertEqual(leftovers & await self.keys(), set())
        self.assertEqual(len(await self.keys("throw:*")), 1000)
        self.assertIsNotNone(again)

    async def test_queries_use_indexes(self):
        from pokewalker.services import research
        # Seed every stage so each delete actually runs (an empty database returns early).
        encounters = await self.writer.run(lambda conn: seed_worst_case(conn, NOW, batch=2, profiles=1))
        await self.conn.execute(
            "INSERT INTO reactions(message_id,profile_id,channel_id,desired,created_at,encounter_id) "
            "VALUES ('msg','p','c','add',0,?)", (encounters[0],))
        await self.conn.commit()
        statements = []
        await self.conn.set_trace_callback(statements.append)
        await self.sweep()
        await self.writer.run(lambda conn: research.auto_send(conn, NOW, {}))
        await self.conn.set_trace_callback(None)
        tables = ("encounters", "action_receipts", "catch_attempts", "step_events", "gym_battles", "reactions",
                  "world_spawns", "pokemon", "resource_ledger")
        checked = 0
        for sql in statements:
            if not sql.lstrip().upper().startswith(("SELECT", "DELETE", "UPDATE")):
                continue
            plan = " | ".join(row[-1] for row in await self.conn.execute_fetchall("EXPLAIN QUERY PLAN " + sql))
            checked += 1
            with self.subTest(sql=sql):
                for table in tables:
                    self.assertNotRegex(plan, rf"\bSCAN {table}\b(?! VIRTUAL)")
                if "acknowledged_at IS NULL" in sql and "shiny=0" in sql:
                    self.assertIn("encounters_unclaimed", plan)
        self.assertGreater(checked, 5)
        self.assertTrue(any("shiny=0" in sql for sql in statements))
        for fragment in ("UPDATE reactions", "DELETE FROM encounters", "FROM catch_attempts",
                         "research:auto:", "NOT EXISTS (SELECT 1 FROM encounters", "arena_fight:",
                         "DELETE FROM arena_runs", "DELETE FROM step_events", "DELETE FROM gym_battles"):
            with self.subTest(ran=fragment):
                self.assertTrue(any(fragment in sql for sql in statements), fragment)


class ReactionCleanupTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = reactions.ReactionTests.asyncSetUp
    seed = reactions.ReactionTests.seed
    scalar = reactions.ReactionTests.scalar
    remove_desired = reactions.ReactionTests.remove_desired

    async def sweep(self, now=NOW):
        cleanup = cleanup_module(self)
        return await self.writer.run(lambda conn: cleanup.sweep(conn, now, None))

    async def test_reaction_row_is_detached_and_still_removed_on_next_walker(self):
        await self.conn.execute("UPDATE encounters SET state='fled',resolved_at=?", (NOW - DAY,))
        await self.service.reconcile_reaction("e")
        self.assertEqual(self.discord.present, {10})
        await self.sweep()
        self.assertEqual(await self.scalar("SELECT count(*) FROM encounters"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM reactions WHERE encounter_id IS NULL"), 1)
        await self.remove_desired()  # what /walker open does
        await self.service.reconcile_message("10")
        self.assertEqual(self.discord.present, set())
        self.assertEqual(await self.scalar("SELECT count(*) FROM reactions"), 0)

    async def blocked_add(self, start):
        self.discord.add_started, self.discord.add_release = asyncio.Event(), asyncio.Event()
        adding = asyncio.create_task(start())
        await self.discord.add_started.wait()
        return adding

    async def assert_waits_for_add(self, adding, second):
        task = asyncio.create_task(second())
        for _ in range(20):
            await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.discord.add_release.set()
        await asyncio.gather(adding, task)
        self.assertEqual([call[0] for call in self.discord.calls], ["add", "remove"])

    async def test_handler_and_walker_share_the_message_lock_across_detachment(self):
        adding = await self.blocked_add(lambda: self.service.reconcile_reaction("e"))
        await self.conn.execute("UPDATE reactions SET encounter_id=NULL,desired='remove',revision=revision+1")
        await self.assert_waits_for_add(adding, lambda: self.service.reconcile_message("10"))
        self.assertEqual(self.discord.present, set())

    async def test_reconcile_reaction_waits_on_the_message_lock(self):
        adding = await self.blocked_add(lambda: self.service.reconcile_message("10"))
        await self.remove_desired()
        await self.assert_waits_for_add(adding, lambda: self.service.reconcile_reaction("e"))

    async def test_remove_own_locks_by_the_stored_message_id(self):
        adding = await self.blocked_add(lambda: self.service.reconcile_message("10"))
        row = {"message_id": "10", "encounter_id": "e", "channel_id": "3"}
        await self.assert_waits_for_add(adding, lambda: self.service.remove_own([row]))

    async def test_startup_sweep_reconciles_by_message_id(self):
        await self.seed("e2", "11", "remove", "none")
        with patch.object(self.service, "reconcile_message", AsyncMock()) as by_message, \
             patch.object(self.service, "reconcile_reaction", AsyncMock()) as by_encounter:
            await self.service.startup_sweep()
        self.assertEqual(sorted(call.args[0] for call in by_message.await_args_list), ["10", "11"])
        by_encounter.assert_not_awaited()


class DoneAfterCleanupTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = ack.AcknowledgementTests.asyncSetUp
    interaction = ack.AcknowledgementTests.interaction
    rows = ack.AcknowledgementTests.rows
    open = ack.AcknowledgementTests.open
    click = ack.AcknowledgementTests.click
    enroll = ack.AcknowledgementTests.enroll
    exclude = ack.AcknowledgementTests.exclude
    ready = ack.AcknowledgementTests.ready
    current = ack.AcknowledgementTests.current
    reveal = ack.AcknowledgementTests.reveal
    encounter_row = ack.AcknowledgementTests.encounter_row
    prepared = ack.AcknowledgementTests.prepared
    caught = ack.AcknowledgementTests.caught
    caught_after_prepared = ack.AcknowledgementTests.caught_after_prepared
    restart = ack.AcknowledgementTests.restart
    rendered = ack.AcknowledgementTests.rendered

    async def test_done_on_a_recovery_screen_whose_encounter_was_cleaned_up_returns_home(self):
        cleanup = cleanup_module(self)
        await self.caught()
        await catching.store_legacy(self.writer, self.encounter["encounter_id"], 1000)
        self.restart()
        interaction, session = await self.open()
        self.assertEqual(self.rendered(interaction)["embed"].title, "Encounter result")
        await self.writer.run(lambda conn: cleanup.sweep(conn, 1000 + DAY, None))
        self.assertEqual(await self.rows("SELECT * FROM encounters WHERE encounter_id=?",
                                         (self.encounter["encounter_id"],)), [])
        interaction = await self.click(session, "ack")
        self.assertEqual(self.rendered(interaction)["embed"].title, "Walker")

    async def test_done_on_a_result_screen_after_its_encounter_is_gone_returns_home(self):
        result, session = await self.caught()
        await catching.store_legacy(self.writer, self.encounter["encounter_id"], 1000)
        await self.writer.run(lambda conn: conn.execute("DELETE FROM encounters"))
        interaction = await self.click(session, "ack")
        self.assertEqual(self.rendered(interaction)["embed"].title, "Walker")


class CatchCounterTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = catching.CatchingTests.asyncSetUp
    interaction = catching.CatchingTests.interaction
    rows = catching.CatchingTests.rows
    open = catching.CatchingTests.open
    click = catching.CatchingTests.click
    enroll = catching.CatchingTests.enroll
    exclude = catching.CatchingTests.exclude
    ready = catching.CatchingTests.ready
    current = catching.CatchingTests.current
    reveal = catching.CatchingTests.reveal
    encounter_row = catching.CatchingTests.encounter_row
    prepared = catching.CatchingTests.prepared
    throw = catching.CatchingTests.throw
    inventory = catching.CatchingTests.inventory

    async def total(self):
        return (await self.rows("SELECT catch_total FROM profiles"))[0]["catch_total"]

    async def test_success_increments_once_replay_failure_and_refusal_do_not(self):
        session = dict(await self.prepared())
        missed, _ = await self.throw(session, (0.999999, 0.999999))  # a miss that does not flee
        self.assertEqual((missed.status, await self.total()), ("revealed", 0))
        await self.inventory(poke_ball=0)
        refused, _ = await self.throw(dict(session), ())
        self.assertEqual((refused.status, await self.total()), ("no_ball", 0))
        await self.inventory(poke_ball=5)
        first, _ = await self.throw(dict(session), (0,))
        self.assertEqual((first.status, await self.total()), ("caught", 1))
        replay, _ = await self.throw(dict(session), ())
        self.assertEqual((replay.status, await self.total()), ("caught", 1))


class StepCounterTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = stepping.SteppingTests.asyncSetUp
    rows = stepping.SteppingTests.rows
    credit = stepping.SteppingTests.credit

    async def test_credit_adds_exactly_its_award_and_survives_pruning(self):
        from pokewalker.services import profiles
        cleanup = cleanup_module(self)
        await self.credit("old", at=10000)
        await self.credit("old", at=10000)  # a redelivered message credits nothing
        await self.credit("new", at=10000 + DAY, words=["echo", "foxtrot", "golf", "hotel", "india"])
        awarded = {row["message_id"]: row["awarded_c"] for row in await self.rows("step_events")}
        self.assertTrue(all(awarded.values()))
        self.assertEqual((await self.rows("profiles"))[0]["steps_total_c"], sum(awarded.values()))
        await self.writer.run(lambda conn: cleanup.sweep(conn, 10000 + DAY, None))
        self.assertEqual([row["message_id"] for row in await self.rows("step_events")], ["new"])
        total = await self.writer.run(lambda conn: profiles.lifetime_steps_c(conn, self.pid))
        self.assertEqual(total, sum(awarded.values()))


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        root = REPO / "build/test-cleanup"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    async def schema33(self, name="old.sqlite3", mode0=True):
        prior = self.dir / "schema33"
        if not prior.exists():
            prior.mkdir()
            for migration in db.MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"):
                if int(migration.name[:4]) <= 33:
                    shutil.copyfile(migration, prior / migration.name)
        path = self.dir / name
        with patch.object(db, "MIGRATIONS", prior):
            old = await db.open_db(path)
        try:
            await old.executescript(
                "INSERT INTO guilds(guild_id) VALUES ('g');"
                "INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES ('p','g','u',0),('q','g','v',0);"
                "INSERT INTO step_events VALUES ('m1','p','1',4,4,0,175,'credited',1),"
                "('m2','p','1',4,4,0,400,'credited',2),('m3','q','1',4,4,0,0,'paused',3);")
            for state, success in (("caught", 1), ("fled", 0), ("caught", 1)):
                eid = await add_encounter(old, state=state, resolved=1)
                await old.execute("INSERT INTO catch_attempts(encounter_id,ordinal,ball,p,success,fled,created_at) "
                                  "VALUES (?,0,'poke_ball',1,?,0,1)", (eid, success))
            await old.execute("CREATE TABLE filler(x)")
            await old.execute("INSERT INTO filler SELECT randomblob(4000) FROM json_each(?)",
                              (json.dumps(list(range(300))),))
            await old.execute("DELETE FROM filler")
        finally:
            await old.close()
        if mode0:
            with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as raw:
                raw.execute("PRAGMA auto_vacuum=NONE")
                raw.execute("VACUUM")
                self.assertEqual(raw.execute("PRAGMA auto_vacuum").fetchone()[0], 0)
        return path

    def pragma(self, path, name):
        with contextlib.closing(sqlite3.connect(path)) as raw:
            return raw.execute(f"PRAGMA {name}").fetchone()[0]

    async def migrate(self, path, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = await db.migrate(path, **kwargs)
        return code, out.getvalue()

    async def test_new_database_is_incremental_with_a_64_mib_journal_limit(self):
        conn = await db.open_db(self.dir / "new.sqlite3")
        try:
            self.assertEqual((await conn.execute_fetchall("PRAGMA auto_vacuum"))[0][0], 2)
            self.assertEqual((await conn.execute_fetchall("PRAGMA journal_size_limit"))[0][0], 64 * 1024 * 1024)
            self.assertEqual((await conn.execute_fetchall("PRAGMA journal_mode"))[0][0], "wal")
        finally:
            await conn.close()

    async def test_0034_backfills_both_counters(self):
        path = await self.schema33()
        conn = await db.open_db(path)
        try:
            rows = {row["profile_id"]: (row["catch_total"], row["steps_total_c"])
                    for row in await conn.execute_fetchall("SELECT * FROM profiles")}
            self.assertEqual(rows, {"p": (2, 575), "q": (0, 0)})
            self.assertEqual((await conn.execute_fetchall("PRAGMA user_version"))[0][0], 35)
            names = {row[0] for row in await conn.execute_fetchall("SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertTrue({"encounters_resolved", "encounters_unclaimed", "gym_battles_created",
                             "step_events_created"} <= names)
        finally:
            await conn.close()

    async def test_migrate_applies_migrations_and_converts_when_space_allows(self):
        path = await self.schema33()
        code, out = await self.migrate(path)
        self.assertEqual(code, 0)
        self.assertEqual(self.pragma(path, "user_version"), 35)
        self.assertEqual(self.pragma(path, "auto_vacuum"), 2)
        self.assertIn("incremental", out)
        code, out = await self.migrate(path)
        self.assertEqual((code, self.pragma(path, "auto_vacuum")), (0, 2))
        self.assertIn("already", out)

    async def test_migrate_warns_and_exits_zero_when_space_is_short(self):
        path = await self.schema33()
        usage = shutil.disk_usage(self.dir)
        with patch.object(db.shutil, "disk_usage", return_value=usage._replace(free=0)):
            code, out = await self.migrate(path)
        self.assertEqual(code, 0)
        self.assertIn("warning", out.lower())
        self.assertEqual(self.pragma(path, "user_version"), 35)
        self.assertEqual(self.pragma(path, "auto_vacuum"), 0)

    async def test_migrate_warns_and_exits_zero_when_vacuum_fails(self):
        # A failed one-time VACUUM (e.g. disk full) must never fail the deploy after 0034 applied.
        import aiosqlite
        path = await self.schema33()
        original = aiosqlite.Connection.execute

        def execute(conn, sql, *args, **kwargs):
            if sql == "VACUUM":
                raise sqlite3.OperationalError("database or disk is full")
            return original(conn, sql, *args, **kwargs)

        with patch.object(aiosqlite.Connection, "execute", execute):
            code, out = await self.migrate(path)
        self.assertEqual(code, 0)
        self.assertIn("warning", out.lower())
        self.assertEqual(self.pragma(path, "user_version"), 35)
        self.assertEqual(self.pragma(path, "auto_vacuum"), 0)

    def cli(self, path):
        env = {**os.environ, "DISCORD_TOKEN": "synthetic", "POKEWALKER_OWNER_IDS": "1",
               "POKEWALKER_DB_PATH": str(path)}
        env.pop("CREDENTIALS_DIRECTORY", None)
        return subprocess.run([sys.executable, "-m", "pokewalker", "migrate"], cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=120)

    async def test_migrate_cli_exits_zero_and_nonzero_when_a_migration_fails(self):
        path = await self.schema33()
        result = self.cli(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("migrate:", result.stdout)
        with contextlib.closing(sqlite3.connect(path)) as raw:
            raw.execute("PRAGMA user_version=999")
        result = self.cli(path)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("synthetic", result.stdout + result.stderr)


class ReclaimTests(CleanupBase):
    async def fill_and_free(self, conn):
        await conn.execute("CREATE TABLE filler(x)")
        await conn.execute("INSERT INTO filler SELECT randomblob(4000) FROM json_each(?)",
                           (json.dumps(list(range(400))),))
        await conn.execute("DELETE FROM filler")

    async def test_reclaim_through_the_writer_commits_and_frees_pages(self):
        await self.writer.run(self.fill_and_free)
        before = await self.scalar("PRAGMA freelist_count")
        self.assertGreater(before, 100)
        await self.writer.run(self.cleanup.reclaim)
        self.assertLess(await self.scalar("PRAGMA freelist_count"), before)
        self.assertFalse(self.conn.in_transaction)

    async def test_reclaim_on_a_mode_0_database_frees_nothing_without_error(self):
        path = Path(self.temp.name) / "mode0.sqlite3"
        with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as raw:
            raw.execute("CREATE TABLE filler(x)")
            raw.execute("INSERT INTO filler SELECT randomblob(4000) FROM json_each(?)", (json.dumps(list(range(50))),))
            raw.execute("DELETE FROM filler")
        conn = await db.open_db(path)
        self.addAsyncCleanup(conn.close)
        self.assertEqual((await conn.execute_fetchall("PRAGMA auto_vacuum"))[0][0], 0)
        before = (await conn.execute_fetchall("PRAGMA freelist_count"))[0][0]
        writer = db.Writer(conn)
        self.addAsyncCleanup(writer.close)
        await writer.run(self.cleanup.reclaim)
        self.assertEqual((await conn.execute_fetchall("PRAGMA freelist_count"))[0][0], before)


class SweepLoopTests(CleanupBase):
    def bot(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(SimpleNamespace(), clock=lambda: 5.0)
        bot.writer, bot.content = self.writer, {"identities": []}
        bot.walker.clock = lambda: NOW
        self.addAsyncCleanup(bot.drain)
        return bot

    async def one_pass(self, bot):
        async def stop(seconds):
            raise asyncio.CancelledError
        with patch("pokewalker.bot.client.asyncio.sleep", side_effect=stop), \
             self.assertLogs("pokewalker.bot.client", level="ERROR") as logs:
            with self.assertRaises(asyncio.CancelledError):
                await bot._gym_sweep_loop()
        return " ".join(logs.output).lower()

    async def test_cleanup_failure_keeps_the_sweep_committed(self):
        await self.conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,revision,selection,expires_at) "
                                "VALUES ('s','g','u',0,'{}',?)", (NOW - DAY - 1,))
        old = await add_encounter(self.conn, state="fled", resolved=NOW - DAY, acknowledged=NOW - DAY)
        bot = self.bot()
        with patch.object(self.cleanup, "reclaim", AsyncMock(side_effect=RuntimeError("synthetic cleanup"))):
            logs = await self.one_pass(bot)
        self.assertIn("cleanup", logs)
        self.assertEqual(await self.column("SELECT session_id FROM sessions"), [])
        self.assertEqual(await self.encounters(), {old})  # the failed cleanup job rolled back whole

    async def test_sweep_failure_does_not_skip_cleanup(self):
        await add_encounter(self.conn, state="fled", resolved=NOW - DAY, acknowledged=NOW - DAY)
        bot = self.bot()
        with patch.object(bot, "_sweep_once", AsyncMock(side_effect=RuntimeError("synthetic sweep"))):
            logs = await self.one_pass(bot)
        self.assertIn("sweep", logs)
        self.assertEqual(await self.encounters(), set())


class PrivacyTextTests(unittest.TestCase):
    def test_privacy_text_states_the_code_clocks(self):
        cleanup = cleanup_module(self)
        text = (REPO / "docs/features/pokewalker-bot/privacy.md").read_text(encoding="utf-8")
        long = next(paragraph for paragraph in text.split("\n\n") if paragraph.startswith("**How long.**"))
        gyms = next(paragraph for paragraph in text.split("\n\n") if paragraph.startswith("**Gyms.**"))
        self.assertEqual((cleanup.ACKNOWLEDGED_KEEP, cleanup.UNACKNOWLEDGED_KEEP, cleanup.STEP_EVENT_KEEP,
                          cleanup.GYM_BATTLE_KEEP, cleanup.BATTLE_RECEIPT_KEEP),
                         (HOUR, DAY, DAY, HOUR, 2 * DAY))
        for phrase in (f"Step-count records (message ID, channel ID, time, word counts) are kept "
                       f"{cleanup.STEP_EVENT_KEEP // HOUR} hours",
                       f"about an hour after its result once you close it",
                       f"or {cleanup.UNACKNOWLEDGED_KEEP // HOUR} hours after a fled or ran result",
                       f"Gym battle logs and results are kept {cleanup.BATTLE_RECEIPT_KEEP // DAY} days",
                       f"an internal copy goes after {cleanup.GYM_BATTLE_KEEP // HOUR} hour",
                       "Only your latest Arena run is kept, with its fight, item and heal records",
                       "backup copies keep everything for up to 28 days"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, long)
        self.assertIn(f"kept for {cleanup.BATTLE_RECEIPT_KEEP // DAY} days", gyms)


if __name__ == "__main__":
    unittest.main()
