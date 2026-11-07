"""Background dead-man pings gated on Gateway readiness and queued writer progress."""

import asyncio
import logging
import os
import time
from asyncio import wait_for
from pathlib import Path

import aiohttp


LOG = logging.getLogger(__name__)


async def noop(conn):
    pass


class Heartbeat:
    def __init__(self, bot, *, clock=None, http=None):
        self.bot, self.http = bot, http
        self.now = clock.time if clock is not None else time.monotonic
        self.sleep = clock.sleep if clock is not None else asyncio.sleep
        self._task = None
        self._stopped = False
        self._ready = None
        self._last_failure = float('-inf')

    def start(self):
        if self._task is None and not self._stopped:
            directory = os.environ.get('RUNTIME_DIRECTORY')
            self._ready = Path(directory) / 'ready' if directory else None
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._mark(False)

    def _mark(self, healthy):
        try:
            if self._ready is not None:
                if healthy:
                    self._ready.touch()
                else:
                    self._ready.unlink(missing_ok=True)
        except OSError:
            self._warn()

    def _warn(self):
        if self.now() - self._last_failure >= 3600:
            LOG.warning('Heartbeat monitoring failed')
            self._last_failure = self.now()

    async def _run(self):
        session = self.http
        url = getattr(self.bot.settings, 'heartbeat_url', None)
        try:
            self._mark(False)
            if session is None and url is not None:
                session = aiohttp.ClientSession()
            while True:
                deadline = self.now() + 60
                try:
                    try:
                        await wait_for(self.bot.writer.run(noop), timeout=5)
                        healthy = self.bot.is_ready()
                    except Exception:
                        healthy = False
                        if self.bot.writer._failure is not None:
                            # A failed rollback kills the writer for good; exit so systemd restarts us.
                            LOG.error('Writer failed after rollback error; shutting down')
                            self.bot._begin_drain()
                    self._mark(healthy)
                    if healthy and url is not None:
                        async with session.get(url.value, timeout=aiohttp.ClientTimeout(total=10),
                                               allow_redirects=False) as response:
                            response.raise_for_status()
                except Exception:
                    self._warn()
                await self.sleep(max(0, deadline - self.now()))
        finally:
            try:
                self._mark(False)
            finally:
                if self.http is None and session is not None:
                    await session.close()
