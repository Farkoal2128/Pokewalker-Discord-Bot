"""D28 serialized write-ahead deletion and receipt-independent replay."""

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from pokewalker.db import with_receipt
from pokewalker.services.marker_log import State, append_marker, append_void
from pokewalker.services import marker_log


LOG = logging.getLogger(__name__)


def _objects(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            yield item
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


async def _redact_gym_battles(conn, guild_id, profile_id):
    async with conn.execute('SELECT deployment_id FROM gym_deployments WHERE guild_id=? AND profile_id=?',
                            (guild_id, profile_id)) as cursor:
        deployments = {row[0] for row in await cursor.fetchall()}
    records = []
    async with conn.execute("SELECT key,result FROM action_receipts WHERE action='battle' AND profile_id IN "
                            '(SELECT profile_id FROM profiles WHERE guild_id=?)', (guild_id,)) as cursor:
        records.extend(('action_receipts', row[0], json.loads(row[1])) for row in await cursor.fetchall())
    async with conn.execute('SELECT session_id,selection FROM sessions WHERE guild_id=?', (guild_id,)) as cursor:
        records.extend(('sessions', row[0], json.loads(row[1])) for row in await cursor.fetchall())
    changed = set()
    battles = set()
    for index, (_, _, payload) in enumerate(records):
        for result in _objects(payload):
            snapshot = result.get('snapshot')
            deployment = snapshot.get('deployment') if isinstance(snapshot, dict) else None
            if not isinstance(deployment, dict) or (deployment.get('guild_id'), deployment.get('profile_id')) != (guild_id, profile_id):
                continue
            deployments.add(deployment['deployment_id'])
            battles.add(result['battle_id'])
            snapshot.update(defender=None, deployment=None, hours_held=None, defender_battle_hp=None)
            result.update(deployment_id=None, events=[])
            changed.add(index)
    for deployment_id in deployments:
        await conn.execute("UPDATE gym_battles SET events='[]' WHERE guild_id=? AND deployment_id=?",
                           (guild_id, deployment_id))
    for battle_id in battles:
        await conn.execute("UPDATE gym_battles SET events='[]' WHERE guild_id=? AND battle_id=?",
                           (guild_id, battle_id))
    for index, (table, key, payload) in enumerate(records):
        invalidated = False
        if table == 'sessions':
            for selection in _objects(payload):
                if selection.get('deployment_id') in deployments:
                    selection.clear()
                    invalidated = True
        if index not in changed and not invalidated:
            continue
        if table == 'sessions':
            await conn.execute('UPDATE sessions SET selection=?,revision=revision+? WHERE session_id=? AND guild_id=?',
                               (json.dumps(payload), int(invalidated), key, guild_id))
        else:
            await conn.execute('UPDATE action_receipts SET result=? WHERE key=?', (json.dumps(payload), key))


async def run_marker(writer, path, authorize=None, *, reactions=None, **fields):
    """Write the marker, apply it, then remove own ❗ reactions whose rows the cascade dropped."""
    tracked = []

    async def job(conn):
        marker_id = None
        try:
            if authorize is not None:
                await authorize(conn)
            if fields.get("kind") in {"delete", "reset", "opt_out"} and "profile_id" not in fields:
                async with conn.execute("SELECT profile_id FROM profiles WHERE guild_id=? AND user_id=?",
                                        (fields["guild_id"], fields["user_id"])) as cursor:
                    profile = await cursor.fetchone()
                fields["profile_id"] = profile[0] if profile else None
            marker_id = str(uuid4())
            marker = append_marker(path, marker_id=marker_id, **fields)
            state = State()
            if marker["kind"] in {"delete", "reset", "opt_out"} and marker["profile_id"] is not None:
                state.delete_ids.add(marker["profile_id"])
                async with conn.execute("SELECT encounter_id,message_id,channel_id FROM reactions WHERE profile_id=?",
                                        (marker["profile_id"],)) as cursor:
                    tracked[:] = [dict(row) for row in await cursor.fetchall()]
            if marker["kind"] in {"opt_out", "opt_in"}:
                state.opted_out = marker["kind"] == "opt_out"
            if marker["kind"] == "reset":
                state.resets.append(marker)
            await apply(conn, {(marker["guild_id"], marker["user_id"]): state})
            return marker
        except BaseException as failure:
            if marker_id is not None:
                try:
                    append_void(path, marker_id, time.time())
                except BaseException as void_failure:
                    message = f"Marker log recovery required: void durability unknown for {marker_id}"
                    LOG.critical(message)
                    # An active abort already waits for this job; do not await it back.
                    if isinstance(failure, asyncio.CancelledError) and asyncio.current_task().cancelling():
                        raise asyncio.CancelledError(message) from void_failure
                    try:
                        await writer.abort()
                    except asyncio.CancelledError:
                        raise asyncio.CancelledError(message) from void_failure
            raise

    marker = await writer.run(job)
    if reactions is not None and tracked:
        await reactions.remove_own(tracked)
    return marker


async def apply(conn, states, *, replay=False):
    if not conn.in_transaction:
        raise RuntimeError("Deletion requires an active writer transaction")
    for (guild_id, user_id), state in states.items():
        for profile_id in state.delete_ids:
            await _redact_gym_battles(conn, guild_id, profile_id)
            await conn.execute("DELETE FROM profiles WHERE profile_id=? AND guild_id=?", (profile_id, guild_id))
        if state.opted_out is True:
            await conn.execute("INSERT OR IGNORE INTO opt_outs(guild_id,user_id,created_at) VALUES (?,?,?)",
                               (guild_id, user_id, time.time()))
        elif state.opted_out is False:
            await conn.execute("DELETE FROM opt_outs WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        for reset in state.resets:
            async def audit(conn):
                try:
                    await conn.execute(
                        "INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                        "VALUES (?,?,'user',?,'reset',?,?)",
                        (guild_id, reset["actor_id"], user_id, reset["reason"], reset["at"]))
                except sqlite3.IntegrityError:
                    if not replay:
                        raise
                    LOG.warning("Skipping reset audit refused by constraint for marker %s", reset["marker_id"])
                return None, []

            await with_receipt(conn, f"reset:{reset['marker_id']}", "reset", audit, profile_id=None)


async def opted_out(conn, guild_id, user_id):
    async with conn.execute("SELECT 1 FROM opt_outs WHERE guild_id=? AND user_id=?", (guild_id, user_id)) as cursor:
        return await cursor.fetchone() is not None


async def replay_markers(writer, path):
    path = Path(path)

    async def initialize(conn):
        async with conn.execute("SELECT 1 FROM marker_log_init WHERE id=1") as cursor:
            initialized = await cursor.fetchone() is not None
        if not path.exists():
            if initialized:
                raise RuntimeError("marker log missing: restore the newest copy, D28")
            marker_log.create_empty(path)
        if not initialized:
            await conn.execute("INSERT INTO marker_log_init(id,at) VALUES (1,?)", (time.time(),))

    await writer.run(initialize)
    for member, state in marker_log.fold(path).items():
        mutation = State(delete_ids=state.delete_ids, opted_out=state.opted_out)
        await writer.run(lambda conn: apply(conn, {member: mutation}, replay=True))
        for reset in state.resets:
            audit = State(resets=[reset])
            await writer.run(lambda conn: apply(conn, {member: audit}, replay=True))
