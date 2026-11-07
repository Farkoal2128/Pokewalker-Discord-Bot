"""M4.5b health uses queued writer progress, synthetic URLs and local temp files."""

import asyncio
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from pokewalker.config import Secret, Settings
from pokewalker.db import Writer


class Clock:
    def __init__(self):
        self.now = 0
        self.waiting = asyncio.Queue()
        self.release = asyncio.Queue()

    def time(self):
        return self.now

    async def sleep(self, seconds):
        await self.waiting.put(seconds)
        await self.release.get()


class HeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module = importlib.import_module('pokewalker.bot.heartbeat')
        cache = Path('build/test-heartbeat')
        cache.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(temp.cleanup)
        self.ready = Path(temp.name, 'ready')
        env = patch.dict(os.environ, {'RUNTIME_DIRECTORY': temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.clock = Clock()
        self.conn = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.writer.abort)
        self.bot = SimpleNamespace(settings=SimpleNamespace(heartbeat_url=Secret('https://synthetic.invalid/private')),
                                   writer=self.writer, is_ready=Mock(return_value=True))
        self.response = SimpleNamespace(raise_for_status=Mock())
        self.http = SimpleNamespace(get=Mock(return_value=MagicMock()))
        self.http.get.return_value.__aenter__ = AsyncMock(return_value=self.response)
        self.monitor = self.module.Heartbeat(self.bot, clock=self.clock, http=self.http)
        self.addAsyncCleanup(self.monitor.stop)

    async def tick(self):
        return await asyncio.wait_for(self.clock.waiting.get(), 1)

    async def advance(self, seconds=60):
        self.clock.now += seconds
        self.clock.release.put_nowait(None)
        return await self.tick()

    async def test_pings_every_60s_when_ready_and_probe_completes(self):
        self.monitor.start()
        self.monitor.start()
        self.assertEqual(await self.tick(), 60)
        self.assertEqual(await self.advance(), 60)
        self.assertEqual(self.http.get.call_count, 2)
        self.assertEqual(self.conn.commit.await_count, 2)
        args, kwargs = self.http.get.call_args
        self.assertEqual(args, (self.bot.settings.heartbeat_url.value,))
        self.assertEqual(kwargs['timeout'].total, 10)
        self.assertFalse(kwargs['allow_redirects'])
        self.assertNotIn('data', kwargs)

    async def test_stalled_writer_job_suppresses_success_while_ready_true(self):
        entered = asyncio.Event()

        async def stalled(conn):
            entered.set()
            await asyncio.Future()

        pending = asyncio.create_task(self.writer.run(stalled))
        self.addAsyncCleanup(lambda: asyncio.gather(pending, return_exceptions=True))
        await entered.wait()
        self.ready.touch()
        real_wait = asyncio.wait_for

        async def fast_timeout(awaitable, timeout):
            self.assertEqual(timeout, 5)
            return await real_wait(awaitable, 0.01)

        with patch.object(self.module, 'wait_for', side_effect=fast_timeout):
            self.monitor.start()
            await self.tick()
        self.http.get.assert_not_called()
        self.assertFalse(self.ready.exists())
        await self.writer.abort()

    async def test_closed_writer_suppresses_success(self):
        await self.writer.close()
        self.monitor.start()
        await self.tick()
        self.http.get.assert_not_called()
        self.assertFalse(self.ready.exists())

    async def test_dead_writer_after_failed_rollback_begins_drain(self):
        self.conn.execute.side_effect = [None, RuntimeError('job failed')]
        self.conn.rollback.side_effect = OSError('disk I/O error')
        self.conn.close = AsyncMock()

        async def job(conn):
            await conn.execute('UPDATE')

        with self.assertRaises(OSError):
            await self.writer.run(job)
        self.bot._begin_drain = Mock()
        self.monitor.start()
        await self.tick()
        self.bot._begin_drain.assert_called_once_with()
        self.http.get.assert_not_called()

    async def test_not_ready_suppresses_success(self):
        self.bot.is_ready.return_value = False
        self.monitor.start()
        await self.tick()
        self.http.get.assert_not_called()
        self.assertFalse(self.ready.exists())

    async def test_http_failure_never_blocks_and_logs_once_per_hour(self):
        self.http.get.side_effect = RuntimeError(self.bot.settings.heartbeat_url.value)
        with self.assertLogs('pokewalker.bot.heartbeat', 'WARNING') as logs:
            self.monitor.start()
            await self.tick()
            await self.advance()
            await self.advance(3540)
        self.assertEqual(len(logs.output), 2)
        self.assertNotIn('private', ''.join(logs.output))
        self.assertTrue(self.ready.exists())
        await asyncio.wait_for(self.writer.run(lambda conn: self.conn.commit()), 1)

    async def test_no_url_still_runs_health_loop_and_maintains_ready_file_no_ping(self):
        self.bot.settings.heartbeat_url = None
        self.monitor.http = None
        with patch.object(self.module.aiohttp, 'ClientSession') as session:
            self.monitor.start()
            await self.tick()
            self.assertTrue(self.ready.exists())
            self.bot.is_ready.return_value = False
            await self.advance()
            session.assert_not_called()
        self.assertFalse(self.ready.exists())
        self.http.get.assert_not_called()

    async def test_ready_file_touched_on_health_removed_on_unhealthy_and_on_drain(self):
        self.monitor.start()
        await self.tick()
        self.assertTrue(self.ready.exists())
        self.bot.is_ready.return_value = False
        await self.advance()
        self.assertFalse(self.ready.exists())
        self.bot.is_ready.return_value = True
        await self.advance()
        self.assertTrue(self.ready.exists())
        await self.monitor.stop()
        self.assertFalse(self.ready.exists())
        await self.monitor.stop()
        self.monitor.start()
        self.assertTrue(self.monitor._task.done())

    async def test_stop_before_start_does_not_remove_unowned_marker(self):
        self.ready.touch()
        await self.monitor.stop()
        self.assertTrue(self.ready.exists())

    async def test_marker_error_is_sanitized_and_health_loop_keeps_running(self):
        with patch.object(Path, 'unlink', side_effect=OSError('synthetic private path')), \
                self.assertLogs('pokewalker.bot.heartbeat', 'WARNING') as logs:
            self.monitor.start()
            await self.tick()
            await self.advance()
        self.assertEqual(self.http.get.call_count, 2)
        self.assertEqual(len(logs.output), 1)
        self.assertNotIn('private', ''.join(logs.output))

    async def test_blocked_http_does_not_block_writer_and_is_cancelled_on_stop(self):
        entered = asyncio.Event()

        async def block():
            entered.set()
            await asyncio.Future()

        self.http.get.return_value.__aenter__.side_effect = block
        self.monitor.start()
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(self.writer.run(lambda conn: self.conn.commit()), 1)
        await asyncio.wait_for(self.monitor.stop(), 1)
        self.assertFalse(self.ready.exists())

    async def test_default_http_session_closed_in_drain_but_injected_session_not_closed(self):
        self.http.close = AsyncMock()
        self.monitor.start()
        await self.tick()
        await self.monitor.stop()
        self.http.close.assert_not_awaited()
        monitor = self.module.Heartbeat(self.bot, clock=self.clock)
        with patch.object(self.module.aiohttp, 'ClientSession', return_value=self.http):
            monitor.start()
            await self.tick()
            await monitor.stop()
        self.http.close.assert_awaited_once()

    async def test_stopped_on_drain_before_writer_close(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(Settings(Secret('synthetic'), owner_ids=frozenset({123})))
        self.addAsyncCleanup(bot.drain)
        bot.heartbeat = self.monitor
        bot._sweep_once = AsyncMock()
        bot.writer = self.writer
        bot.reactions = SimpleNamespace(startup_sweep=AsyncMock())
        bot.is_ready = Mock(return_value=True)
        with patch('pokewalker.bot.client.raids.resume_pending', AsyncMock()):
            await bot.on_ready()
            await bot.on_ready()
        await self.tick()
        self.assertTrue(self.ready.exists())
        original_close = self.writer.close

        async def close():
            self.assertTrue(self.monitor._task.done())
            self.assertFalse(self.ready.exists())
            await original_close()

        with patch.object(self.writer, 'close', side_effect=close):
            await bot.drain()
        bot.heartbeat.start = Mock()
        await bot.on_ready()
        bot.heartbeat.start.assert_not_called()
