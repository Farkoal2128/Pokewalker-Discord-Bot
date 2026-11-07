"""C3 SQLite boundary: migrations and one transaction-owning asyncio writer."""

import asyncio
import json
import inspect
import logging
import sqlite3
import time
from pathlib import Path

import aiosqlite


MIGRATIONS = Path(__file__).with_name("migrations")
LOG = logging.getLogger(__name__)


def check_sqlite_version(version):
    return (version >= (3, 51, 3) or (3, 50, 7) <= version < (3, 51, 0)
            or (3, 44, 6) <= version < (3, 45, 0))


async def open_db(path, *, allow_unpatched=False):
    if not check_sqlite_version(sqlite3.sqlite_version_info):
        if not allow_unpatched:
            raise RuntimeError("SQLite lacks the WAL-reset fix; patched SQLite required")
        LOG.warning("Using unpatched SQLite %s; development override only", sqlite3.sqlite_version)
    conn = await aiosqlite.connect(path, isolation_level=None)
    conn.row_factory = aiosqlite.Row
    try:
        for pragma in ("busy_timeout=5000", "journal_mode=WAL", "synchronous=FULL",
                       "secure_delete=ON", "foreign_keys=ON"):
            await conn.execute(f"PRAGMA {pragma}")
        migrations = sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        versions = [int(path.name[:4]) for path in migrations]
        if versions != list(range(1, len(versions) + 1)):
            raise RuntimeError("Migration numbering must be contiguous from 0001")
        async with conn.execute("PRAGMA user_version") as cursor:
            current = (await cursor.fetchone())[0]
        if current > len(migrations):
            raise RuntimeError("Database schema is newer than this application")
        for version, migration in enumerate(migrations, 1):
            if version > current:
                await conn.executescript(
                    "BEGIN IMMEDIATE;\n" + migration.read_text(encoding="utf-8")
                    + f"\nPRAGMA user_version={version};\nCOMMIT;")
        return conn
    except BaseException:
        await conn.rollback()
        await conn.close()
        raise


async def open_reader(path):
    conn = await aiosqlite.connect(Path(path).resolve().as_uri() + "?mode=ro",
                                   uri=True, isolation_level=None)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


class Writer:
    def __init__(self, conn):
        self._conn = conn
        self._queue = asyncio.Queue()
        self._closed = False
        self._failure = None
        self._abort_task = None
        self._task = asyncio.create_task(self._work())

    async def run(self, fn, *, after_commit=None):
        if after_commit is not None and (not callable(after_commit)
                or inspect.iscoroutinefunction(after_commit)
                or inspect.iscoroutinefunction(getattr(after_commit, '__call__', None))):
            raise TypeError('Post-commit observers must be synchronous callables')
        if self._closed:
            raise RuntimeError("Writer is closed") from self._failure
        if asyncio.current_task() is self._task:
            raise RuntimeError("Writer jobs cannot recursively queue jobs")
        future = asyncio.get_running_loop().create_future()
        self._queue.put_nowait((fn, future, after_commit))
        return await future

    async def close(self):
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(None)
        try:
            await asyncio.shield(self._task)
        except asyncio.CancelledError:
            if not self._task.cancelled():
                raise

    async def abort(self):
        self._closed = True
        if self._abort_task is None:
            self._abort_task = asyncio.create_task(self._abort())
        await asyncio.shield(self._abort_task)

    async def _abort(self):
        if not self._task.done():
            self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        while not self._queue.empty():
            queued = self._queue.get_nowait()
            if queued is not None and not queued[1].done():
                queued[1].set_exception(RuntimeError("Writer aborted before job started"))

    async def _work(self):
        while (job := await self._queue.get()) is not None:
            fn, future, after_commit = job
            try:
                await self._conn.execute("BEGIN IMMEDIATE")
                result = await fn(self._conn)
                await self._conn.commit()
            except (Exception, asyncio.CancelledError) as error:
                try:
                    await self._conn.rollback()
                except (Exception, asyncio.CancelledError) as rollback_error:
                    self._closed = True
                    rollback_error.__cause__ = error.with_traceback(None)
                    rollback_error.__context__ = None
                    self._failure = rollback_error.with_traceback(None)
                    try:
                        await self._conn.close()
                    except (Exception, asyncio.CancelledError) as close_error:
                        rollback_error.add_note(f"Connection close also failed: {close_error}")
                    pending = [future]
                    while not self._queue.empty():
                        queued = self._queue.get_nowait()
                        if queued is not None:
                            pending.append(queued[1])
                    for waiting in pending:
                        if not waiting.done():
                            waiting.set_exception(self._failure)
                    return
                if not future.done():
                    # Do not expose the still-running worker frame to caller traceback cleanup.
                    future.set_exception(error.with_traceback(None))
                if isinstance(error, asyncio.CancelledError):
                    return
            else:
                if after_commit is not None:
                    try:
                        observed = after_commit(result)
                        if inspect.isawaitable(observed):
                            if inspect.iscoroutine(observed):
                                observed.close()
                            raise TypeError('Post-commit observers cannot await')
                    except BaseException:
                        # Committed data and later jobs survive a broken observer.
                        LOG.error('Post-commit observer failed')
                if not future.done():
                    future.set_result(result)


async def with_receipt(conn, key, action, compute, *, profile_id=None):
    if not conn.in_transaction:
        raise RuntimeError("Receipts require an active writer transaction")
    async with conn.execute("SELECT action,result FROM action_receipts WHERE key=?", (key,)) as cursor:
        saved = await cursor.fetchone()
    if saved is not None:
        if saved["action"] != action:
            raise ValueError("Receipt key already belongs to another action")
        return json.loads(saved["result"])
    result, lines = await compute(conn)
    encoded = json.dumps(result, allow_nan=False, separators=(",", ":"))
    await conn.execute("INSERT INTO action_receipts(key,action,result,created_at,profile_id) VALUES (?,?,?,?,?)",
                       (key, action, encoded, time.time(), profile_id))
    for ordinal, line in enumerate(lines):
        await conn.execute(
            "INSERT INTO resource_ledger(receipt_key,line_key,profile_id,resource,resource_id,delta,reason) "
            "VALUES (?,?,?,?,?,?,?)", (key, ordinal, line["profile_id"], line["resource"],
                                      line.get("resource_id"), line["delta"], line["reason"]))
    return json.loads(encoded)
