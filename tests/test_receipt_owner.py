"""C3 receipt ownership, legacy upgrades and deletion with real SQLite."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from pokewalker import db
from pokewalker.bot.walker import Walker
from pokewalker.services import catching, profiles
import test_db


class ReceiptOwnerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_db.DatabaseTests.asyncSetUp
    scalar = test_db.DatabaseTests.scalar
    profile = test_db.DatabaseTests.profile

    async def test_every_arena_receipt_action_carries_profile_id(self):
        from test_deletion import populate_arena
        writer = db.Writer(self.conn)
        self.addAsyncCleanup(writer.close)
        profile_id = await self.profile('player', 'guild')
        await populate_arena(self.conn, writer, profile_id, 'guild', 'player')
        rows = await self.conn.execute_fetchall("SELECT action,profile_id FROM action_receipts WHERE action LIKE 'arena_%'")
        self.assertEqual({row['action']: row['profile_id'] for row in rows},
                         {action: profile_id for action in ('arena_start', 'arena_heal', 'arena_fight', 'arena_redeem')})
        self.assertEqual(len(rows), 4)

    async def receipts_from_producers(self):
        content = json.loads(Path("content/artifact/content.json").read_text(encoding="utf-8"))
        writer = db.Writer(self.conn)
        self.addAsyncCleanup(writer.close)
        profile = await writer.run(lambda conn: profiles.enroll(
            conn, "123", "456", 1, content, random.Random(8), datetime.now(timezone.utc)))
        encounter_id = await self.scalar("SELECT encounter_id FROM encounters")
        await self.conn.execute("UPDATE encounters SET state='revealed',shiny=0,pokemon_id=25,"
                                "level_x2=40,tier='Common',source_message_id='private-run-source-6b03dc23'")
        session = {"session_id": "fixture", "revision": 0, "guild_id": "123", "user_id": "456",
                   "profile_id": profile["profile_id"], "selection": json.dumps({
                       "encounter_id": encounter_id, "encounter_revision": 0, "ball": "poke_ball"})}
        rng = random.Random(1)
        rng.random = lambda: 0.999999
        result = await writer.run(lambda conn: catching.throw(
            conn, encounter_id, session, 0, rng, 1000, content=content))
        self.assertEqual(result.status, "revealed")
        walker = Walker(SimpleNamespace(content=content), clock=lambda: 1001)
        await writer.run(lambda conn: walker.run(conn, session, None))
        await writer.close()
        return profile["profile_id"]

    async def legacy_schema(self):
        # Keep real producer results while restoring every pre-0003 table and column.
        for table in ('arena_runs', 'arena_tickets'):
            await self.conn.execute(f'DROP TABLE {table}')
        await self.conn.execute('ALTER TABLE guilds DROP COLUMN arena_enabled')
        await self.conn.execute('ALTER TABLE profiles DROP COLUMN arena_best_floor')
        await self.conn.execute('DROP INDEX pokemon_profile_state')
        for index in ('catch_attempts_receipt', 'resource_ledger_profile'):
            await self.conn.execute(f'DROP INDEX {index}')
        await self.conn.execute('DROP TRIGGER pokemon_trade_guard')
        for table in ("trade_sides", "trades", "trade_channels"):
            await self.conn.execute(f'DROP TABLE {table}')
        for column in ("last_trade_at", "last_trade_ping_at"):
            await self.conn.execute(f'ALTER TABLE profiles DROP COLUMN {column}')
        await self.conn.execute("ALTER TABLE profiles DROP COLUMN overflow_uid")
        await self.conn.execute("ALTER TABLE pokemon DROP COLUMN form_id")
        for trigger in ("encounter_queue_insert", "encounter_queue_update"):
            await self.conn.execute(f'DROP TRIGGER {trigger}')
        await self.conn.execute("ALTER TABLE encounters DROP COLUMN raid_spawn_id")
        await self.conn.execute("DROP TABLE raid_participation")
        await self.conn.execute("DROP TABLE world_spawns")
        await self.conn.execute("ALTER TABLE guilds DROP COLUMN gym_legendary_defenders")
        await self.conn.execute("ALTER TABLE profiles DROP COLUMN shiny_charm_off")
        await self.conn.execute("ALTER TABLE guilds DROP COLUMN raids_enabled")
        await self.conn.execute("ALTER TABLE guilds DROP COLUMN raid_channel_id")
        core = (db.MIGRATIONS / '0001_core.sql').read_text(encoding='utf-8')
        for name in ("encounter_queue_insert", "encounter_queue_update"):
            trigger = core[core.index(f'CREATE TRIGGER {name} '):].split('END;', 1)[0] + 'END;'
            await self.conn.execute(trigger)
        for trigger in ("pokemon_deployed_guard", "companion_deployed_guard"):
            await self.conn.execute(f'DROP TRIGGER {trigger}')
        await self.conn.execute("ALTER TABLE pokemon DROP COLUMN gym_deployment_id")
        for table in ("gym_battles", "gym_deployments", "gyms"):
            await self.conn.execute(f'DROP TABLE {table}')
        await self.conn.execute("DROP INDEX profiles_guild_key")
        await self.conn.execute("ALTER TABLE profiles DROP COLUMN last_battle_at")
        for table in ("inbox_items", "milestone_awards", "finds", "active_effects",
                      "opt_outs", "marker_log_init"):
            await self.conn.execute(f'DROP TABLE {table}')
        if await self.scalar("SELECT count(*) FROM pragma_table_info('action_receipts') "
                             "WHERE name='profile_id'"):
            await self.conn.execute("DROP INDEX action_receipts_profile_id")
            await self.conn.execute("ALTER TABLE action_receipts DROP COLUMN profile_id")
        await self.conn.execute("ALTER TABLE profiles DROP COLUMN last_share_at")
        await self.conn.execute("ALTER TABLE profiles DROP COLUMN storage_limit")
        await self.conn.execute("ALTER TABLE profiles DROP COLUMN bag_limit")
        await self.conn.execute("ALTER TABLE guilds DROP COLUMN sharing")
        await self.conn.execute("ALTER TABLE mod_audit RENAME TO mod_audit_current")
        await self.conn.execute("""CREATE TABLE mod_audit (
            audit_id INTEGER PRIMARY KEY,
            guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
            actor_id TEXT NOT NULL,
            target_kind TEXT NOT NULL CHECK(target_kind IN ('user','channel')),
            target_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL CHECK(length(trim(reason))>0),
            created_at REAL NOT NULL
        )""")
        await self.conn.execute("INSERT INTO mod_audit SELECT * FROM mod_audit_current")
        await self.conn.execute("DROP TABLE mod_audit_current")
        await self.conn.execute("PRAGMA user_version=2")
        self.assertEqual(await self.scalar("SELECT count(*) FROM pragma_table_info('action_receipts')"), 4)
        await self.conn.close()

    async def upgrade(self):
        self.conn = await db.open_db(self.path)
        self.addAsyncCleanup(self.conn.close)

    async def test_migration_adds_nullable_owner_cascade_applies_once(self):
        columns = await self.conn.execute_fetchall("PRAGMA table_info(action_receipts)")
        self.assertIn(("profile_id", "TEXT", 0), [(r["name"], r["type"], r["notnull"]) for r in columns])
        foreign_keys = await self.conn.execute_fetchall("PRAGMA foreign_key_list(action_receipts)")
        self.assertIn(("profile_id", "profiles", "CASCADE"),
                      [(r["from"], r["table"], r["on_delete"]) for r in foreign_keys])
        self.assertEqual(await self.scalar("SELECT name FROM pragma_index_info('action_receipts_profile_id')"),
                         "profile_id")
        await self.conn.close()
        await self.upgrade()
        self.assertEqual(await self.scalar("PRAGMA user_version"), len(list(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))))

    async def test_legacy_db_backfilled_then_delete_removes_every_receipt(self):
        profile_id = await self.receipts_from_producers()
        await self.conn.execute("DELETE FROM resource_ledger WHERE receipt_key LIKE 'enroll:%'")
        before = await self.conn.execute_fetchall("SELECT key,result FROM action_receipts ORDER BY key")
        await self.legacy_schema()
        await self.upgrade()
        after = await self.conn.execute_fetchall("SELECT key,result FROM action_receipts ORDER BY key")
        self.assertEqual([tuple(r) for r in after], [tuple(r) for r in before])
        owners = await self.conn.execute_fetchall("SELECT action,profile_id FROM action_receipts")
        self.assertEqual({r["action"]: r["profile_id"] for r in owners},
                         {action: profile_id for action in ("enroll", "throw", "run")})
        self.assertEqual(await self.scalar("SELECT count(*) FROM resource_ledger "
                                          "WHERE receipt_key LIKE 'run:%'"), 0)
        await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        marker = b"private-run-source-6b03dc23"
        self.assertIn(marker, self.path.read_bytes())
        for _ in range(2):
            await self.conn.execute("DELETE FROM profiles WHERE profile_id=?", (profile_id,))
            self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts"), 0)
        await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.assertNotIn(marker, self.path.read_bytes())
        backup_path = Path(self.temp.name) / "backup.sqlite3"
        with closing(sqlite3.connect(backup_path)) as backup:
            await self.conn.backup(backup)
        self.assertNotIn(marker, backup_path.read_bytes())

    async def test_legacy_throw_without_ledger_uses_encounter_owner(self):
        profile_id = await self.receipts_from_producers()
        await self.conn.execute("DELETE FROM resource_ledger WHERE receipt_key LIKE 'throw:%'")
        await self.legacy_schema()
        await self.upgrade()
        self.assertEqual(await self.scalar("SELECT profile_id FROM action_receipts WHERE action='throw'"),
                         profile_id)

    async def test_migration_deletes_orphan_receipts_and_aborts_on_unknown_action(self):
        await self.legacy_schema()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executemany("INSERT INTO action_receipts VALUES (?,?,'{}',0)",
                             [(f"{action}:missing", action) for action in ("enroll", "throw", "run", "unknown")])
            conn.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "unattributable"):
            unexpected = await db.open_db(self.path)
            await unexpected.close()
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM action_receipts").fetchone()[0], 4)
            self.assertEqual(len(conn.execute("PRAGMA table_info(action_receipts)").fetchall()), 4)
            conn.execute("DELETE FROM action_receipts WHERE action='unknown'")
            conn.commit()
        await self.upgrade()
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts"), 0)

    async def test_with_receipt_stores_owner_and_replay_returns_saved_result(self):
        profile_id = await self.profile()
        writer = db.Writer(self.conn)
        self.addAsyncCleanup(writer.close)
        compute = AsyncMock(return_value=({"value": 1}, []))
        first = await writer.run(lambda conn: db.with_receipt(
            conn, "profile:test", "test", compute, profile_id=profile_id))
        replay = await writer.run(lambda conn: db.with_receipt(
            conn, "profile:test", "test", compute, profile_id="missing"))
        self.assertEqual(first, replay)
        compute.assert_awaited_once()
        self.assertEqual(await self.scalar("SELECT profile_id FROM action_receipts"), profile_id)
        with self.assertRaisesRegex(ValueError, "action"):
            await writer.run(lambda conn: db.with_receipt(conn, "profile:test", "other", compute))
        with self.assertRaises(sqlite3.IntegrityError):
            await writer.run(lambda conn: db.with_receipt(
                conn, "bad:test", "test", compute, profile_id="missing"))
        await self.conn.execute("DELETE FROM profiles WHERE profile_id=?", (profile_id,))
        self.assertEqual(await self.scalar("SELECT count(*) FROM action_receipts"), 0)

    async def test_with_receipt_default_owner_null_keeps_existing_callers_green(self):
        writer = db.Writer(self.conn)
        self.addAsyncCleanup(writer.close)
        compute = AsyncMock(return_value=({"marker_id": "fixture"}, []))
        await writer.run(lambda conn: db.with_receipt(conn, "reset:fixture", "reset", compute))
        self.assertIsNone(await self.scalar("SELECT profile_id FROM action_receipts"))

    async def test_enroll_throw_run_receipts_carry_profile_id(self):
        profile_id = await self.receipts_from_producers()
        rows = await self.conn.execute_fetchall("SELECT action,profile_id FROM action_receipts")
        self.assertEqual({row["action"]: row["profile_id"] for row in rows},
                         {action: profile_id for action in ("enroll", "throw", "run")})


if __name__ == "__main__":
    unittest.main()
