"""C5 lifecycle and CLI acceptance, with no connected Discord objects."""

import asyncio
import hashlib
import importlib
import io
import json
import os
import signal
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord


class LifecycleRuntimeIsolationTests(unittest.TestCase):
    def test_lifecycle_fixture_preserves_external_runtime_through_async_cleanup(self):
        from pokewalker.bot.client import WalkerBot

        cache = Path('build/test-client')
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as external:
            sentinel = Path(external, 'ready')
            sentinel.write_text('synthetic external owner', encoding='utf-8')
            cleanup_runtimes = []
            original_close = WalkerBot.close

            async def observed_close(bot):
                cleanup_runtimes.append(Path(os.environ['RUNTIME_DIRECTORY']).resolve())
                await original_close(bot)

            case = ClientLifecycleTests(
                'test_first_ready_sweeps_once_after_setup_without_blocking_setup')
            result = unittest.TestResult()
            with patch.dict(os.environ, {'RUNTIME_DIRECTORY': external}), \
                    patch.object(WalkerBot, 'close', observed_close):
                case.run(result)
                self.assertEqual(os.environ['RUNTIME_DIRECTORY'], external)
            self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
            self.assertTrue(sentinel.exists(), 'Lifecycle fixture removed another runtime owner marker')
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'synthetic external owner')
            self.assertTrue(cleanup_runtimes)
            self.assertNotIn(Path(external).resolve(), cleanup_runtimes)


class ClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.client = importlib.import_module("pokewalker.bot.client")
            self.config = importlib.import_module("pokewalker.config")
        except ModuleNotFoundError:
            self.fail("M1.2 client absent: lifecycle contract unavailable")
        cache = Path("build/test-client")
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        runtime = root / 'runtime'
        runtime.mkdir()
        self.enterContext(patch.dict(os.environ, {'RUNTIME_DIRECTORY': str(runtime)}))
        (root / "artifact").mkdir()
        self.content_path = root / "artifact/content.json"
        self.content_path.write_bytes(b'{"schema_version":1}\n')
        (root / "manifest.json").write_text(json.dumps({
            "artifact_sha256": hashlib.sha256(self.content_path.read_bytes()).hexdigest()}))
        self.settings = self.config.Settings(self.config.Secret("synthetic-token"),
                                             root / "game.db", self.content_path, frozenset({123}),
                                             privacy_path=root / "privacy.txt")
        self.settings.privacy_path.write_text("Synthetic owner privacy text", encoding="utf-8")
        self.bot = self.client.WalkerBot(self.settings)
        self.addAsyncCleanup(self.bot.close)

    async def test_intents_exact_set(self):
        self.assertEqual({name for name, enabled in self.bot.intents if enabled},
                         {"guilds", "guild_messages", "message_content"})
        self.assertIsInstance(self.bot.tree, discord.app_commands.CommandTree)
        self.assertTrue(self.bot.tree.allowed_contexts.guild)
        self.assertFalse(self.bot.tree.allowed_contexts.dm_channel)
        self.assertFalse(self.bot.tree.allowed_contexts.private_channel)

    async def test_presence_is_permanent_walker_custom_status(self):
        activity = self.bot._connection._activity
        self.assertEqual(activity, discord.CustomActivity(name="/walker").to_dict())
        self.assertEqual(self.bot._connection._status, "online")

    async def test_message_cache_disabled(self):
        self.assertIsNone(self.bot._connection.max_messages)

    async def test_walker_registered_locally_and_generic_dynamic_item_routes_select_and_button(self):
        command = self.bot.tree.get_command("walker")
        self.assertIsNotNone(command, "/walker must be registered before explicit synchronization")
        self.assertTrue(command.guild_only)
        self.bot.walker.route = AsyncMock()
        for component in (discord.ui.Button(custom_id="pw:v1:abcd:0:home"),
                          discord.ui.Select(custom_id="pw:v1:abcd:0:onboard_gen",
                                            options=[discord.SelectOption(label="Generation 1", value="1")])):
            view = discord.ui.View(timeout=None)
            view.add_item(component)
            # Exercise discord.py's reconstruction/refresh path, including Select state.
            message = SimpleNamespace(flags=discord.MessageFlags(), components=[
                discord.components._component_factory(raw) for raw in view.to_components()])
            interaction = SimpleNamespace(client=self.bot, message=message, data={"values": ["1"]})
            await self.bot._connection._view_store.schedule_dynamic_item_call(
                component.type.value, self.client.WalkerItem, interaction, component.custom_id,
                self.client.WalkerItem.__discord_ui_compiled_template__.fullmatch(component.custom_id))
            self.bot.walker.route.assert_awaited_with(interaction, component.custom_id)

    async def test_gateway_message_delegation_obeys_admission(self):
        message = object()
        with patch("pokewalker.bot.messages.on_message", AsyncMock()) as handle:
            await self.bot.on_message(message)
            handle.assert_not_awaited()
            self.bot.admitting = True
            await self.bot.on_message(message)
            handle.assert_awaited_once_with(self.bot, message)
            self.bot.admitting = False

    async def test_manifest_mismatch_refuses_start(self):
        self.content_path.write_bytes(b'{"tampered":true}\n')
        with patch.object(self.client, "open_db", AsyncMock()) as opening:
            with self.assertRaisesRegex(ValueError, "hash"):
                await self.bot.setup_hook()
        opening.assert_not_awaited()
        self.assertFalse(self.bot.admitting)

    async def test_missing_manifest_hash_refuses_start(self):
        (self.content_path.parent.parent / "manifest.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "hash"):
            await self.bot.setup_hook()

    async def test_setup_starts_writer_and_dynamic_item_never_syncs(self):
        conn = SimpleNamespace(close=AsyncMock())
        writer = SimpleNamespace(close=AsyncMock(), abort=AsyncMock())
        with patch.object(self.client, "open_db", AsyncMock(return_value=conn)) as opening, \
                patch.object(self.client, "Writer", return_value=writer) as factory, \
                patch.object(self.client, "replay_markers", AsyncMock(), create=True), \
                patch.object(self.bot, "add_dynamic_items") as register, \
                patch.object(self.bot.tree, "sync", AsyncMock()) as sync:
            await self.bot.setup_hook()
        opening.assert_awaited_once_with(self.settings.db_path, allow_unpatched=False)
        factory.assert_called_once_with(conn)
        register.assert_called_once_with(self.client.WalkerItem, self.client.ReadmeItem)
        sync.assert_not_awaited()
        self.assertEqual(self.bot.content, {"schema_version": 1})
        self.assertTrue(self.bot.admitting)

    async def test_first_ready_sweeps_once_after_setup_without_blocking_setup(self):
        conn = SimpleNamespace(close=AsyncMock())
        writer = SimpleNamespace(run=AsyncMock(), close=AsyncMock(), abort=AsyncMock())
        service = SimpleNamespace(startup_sweep=AsyncMock())
        with patch.object(self.client, "open_db", AsyncMock(return_value=conn)), \
                patch.object(self.client, "Writer", return_value=writer), \
                patch.object(self.client, "replay_markers", AsyncMock(), create=True), \
                patch.object(self.client, "ReactionService", return_value=service, create=True), \
                patch.object(self.client.raids, "resume_pending", AsyncMock()):
            await self.bot.setup_hook()
            service.startup_sweep.assert_not_awaited()
            await self.bot.on_ready()
            await self.bot.on_ready()
        service.startup_sweep.assert_awaited_once()
        await self.bot.drain()

    async def test_failed_reaction_sweep_still_announces_pending_raids(self):
        # Audit fix: a network error in the sweep must not skip resume_pending.
        conn = SimpleNamespace(close=AsyncMock())
        writer = SimpleNamespace(run=AsyncMock(), close=AsyncMock(), abort=AsyncMock())
        service = SimpleNamespace(startup_sweep=AsyncMock(side_effect=OSError("connection reset")))
        resume = AsyncMock()
        with patch.object(self.client, "open_db", AsyncMock(return_value=conn)), \
                patch.object(self.client, "Writer", return_value=writer), \
                patch.object(self.client, "replay_markers", AsyncMock(), create=True), \
                patch.object(self.client, "ReactionService", return_value=service, create=True), \
                patch.object(self.client.raids, "resume_pending", resume), \
                self.assertLogs("pokewalker.bot.client", "ERROR"):
            await self.bot.setup_hook()
            await self.bot.on_ready()
        resume.assert_awaited_once()
        await self.bot.drain()

    async def test_replay_runs_before_admitting(self):
        self.addAsyncCleanup(self.bot.drain)
        from pokewalker.services.deletion import replay_markers
        from pokewalker.services.marker_log import append_marker, create_empty
        from pokewalker.db import open_db
        from uuid import uuid4

        profile_id = str(uuid4())
        conn = await open_db(self.settings.db_path)
        try:
            await conn.execute("INSERT INTO guilds(guild_id) VALUES ('1')")
            await conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                               "VALUES (?,'1','2',0)", (profile_id,))
        finally:
            await conn.close()
        create_empty(self.settings.marker_log_path)
        append_marker(self.settings.marker_log_path, "delete", "1", "2", 100, profile_id=profile_id)
        entered = asyncio.Event()

        async def observe(writer, path):
            self.assertFalse(self.bot.admitting)
            self.assertIsNone(self.bot.reactions)
            entered.set()
            await replay_markers(writer, path)
            self.assertFalse(self.bot.admitting)

        with patch.object(self.client, "replay_markers", side_effect=observe, create=True):
            await self.bot.setup_hook()
        self.assertTrue(entered.is_set())
        self.assertTrue(self.bot.admitting)
        async with self.bot.db.execute("SELECT count(*) FROM profiles") as cursor:
            self.assertEqual((await cursor.fetchone())[0], 0)
        await self.bot.drain()

    async def test_replay_failure_refuses_admission_and_closes_resources(self):
        self.addAsyncCleanup(self.bot.drain)
        self.settings.marker_log_path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "corrupt marker log"):
            await self.bot.setup_hook()
        self.assertFalse(self.bot.admitting)
        self.assertIsNone(self.bot.reactions)
        self.assertTrue(self.bot.writer._task.done())
        self.assertTrue(self.bot.is_closed())
        with self.assertRaisesRegex(ValueError, "no active connection"):
            await self.bot.db.execute("SELECT 1")

    async def test_cancel_during_replay_drains_writer_and_closes_connection(self):
        self.addAsyncCleanup(self.bot.drain)
        from pokewalker.services import deletion, marker_log

        marker_log.create_empty(self.settings.marker_log_path)
        marker_log.append_marker(self.settings.marker_log_path, "opt_in", "1", "2", 100)
        entered, release = asyncio.Event(), asyncio.Event()
        applied = []
        apply = deletion.apply

        async def paused(conn, states, **kwargs):
            self.assertTrue(conn.in_transaction)
            entered.set()
            await release.wait()
            await apply(conn, states, **kwargs)
            applied.append(True)

        with patch.object(deletion, "apply", side_effect=paused):
            startup = asyncio.create_task(self.bot.setup_hook())
            try:
                await asyncio.wait_for(entered.wait(), 1)
                startup.cancel()
                await asyncio.sleep(0)
                self.assertFalse(self.bot.admitting)
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(startup, 1)
            finally:
                release.set()
                if not startup.done():
                    startup.cancel()
                await asyncio.gather(startup, return_exceptions=True)
        self.assertFalse(self.bot.admitting)
        self.assertIsNone(self.bot.reactions)
        self.assertTrue(self.bot.writer._task.done())
        self.assertEqual(applied, [True])
        self.assertTrue(self.bot.is_closed())
        with self.assertRaisesRegex(ValueError, "no active connection"):
            await self.bot.db.execute("SELECT 1")

    async def test_shutdown_cancels_startup_reaction_sweep_before_writer_close(self):
        entered = asyncio.Event()
        order = []

        async def sweep():
            entered.set()
            try:
                await asyncio.Future()
            finally:
                order.append("sweep stopped")

        async def close_writer():
            order.append("writer closed")

        self.bot.reactions = SimpleNamespace(startup_sweep=sweep)
        self.bot.writer = SimpleNamespace(run=AsyncMock(), close=close_writer, abort=AsyncMock())
        ready = asyncio.create_task(self.bot.on_ready())
        await entered.wait()
        await self.bot.drain()
        await asyncio.gather(ready, return_exceptions=True)
        self.assertEqual(order, ["sweep stopped", "writer closed"])

    async def test_shutdown_during_open_cleans_late_resources_without_admission(self):
        entered, release = asyncio.Event(), asyncio.Event()
        conn = SimpleNamespace(close=AsyncMock())

        async def open_late(*args, **kwargs):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                # Simulate an acquisition finishing as cancellation arrives.
                await release.wait()
            return conn

        with patch.object(self.client, "open_db", side_effect=open_late), \
                patch.object(self.client, "Writer") as writer, \
                patch.object(self.bot, "add_dynamic_items") as register:
            startup = asyncio.create_task(self.bot.setup_hook())
            await entered.wait()
            shutdown = asyncio.create_task(self.bot.drain())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            release.set()
            result = await asyncio.gather(startup, return_exceptions=True)
            self.assertEqual(await shutdown, 0)
        self.assertIsInstance(result[0], BaseException)
        self.assertFalse(self.bot.admitting)
        conn.close.assert_awaited_once()
        writer.assert_not_called()
        register.assert_not_called()

    async def test_setup_after_shutdown_is_refused(self):
        await self.bot.drain()
        with patch.object(self.client, "open_db", AsyncMock()) as opening:
            with self.assertRaisesRegex(RuntimeError, "stopping"):
                await self.bot.setup_hook()
        opening.assert_not_awaited()

    async def assert_final_cleanup(self, operation, *, blocked):
        bot = self.client.WalkerBot(self.settings)
        self.addAsyncCleanup(bot.close)
        order, deadlines = [], []

        async def finish(name):
            order.append(name)

        async def close_discord(client):
            await finish("discord")
            if blocked:
                await asyncio.Future()

        async def deadline(awaitable, timeout):
            deadlines.append(timeout)
            return await asyncio.wait_for(awaitable, min(timeout, 0.01))

        bot.wait_for = deadline
        bot.admitting = True
        bot.writer = SimpleNamespace(close=lambda: finish("writer"), abort=AsyncMock())
        bot.db = SimpleNamespace(close=lambda: finish("db"))
        with patch.object(bot, "start", AsyncMock()), patch.object(bot, "login", AsyncMock()), \
                patch.object(bot.tree, "sync", AsyncMock()), patch.object(signal, "signal"), \
                patch.object(discord.Client, "close", close_discord):
            running = asyncio.create_task(getattr(bot, operation)())
            done, _ = await asyncio.wait({running}, timeout=0.1)
            if not done:
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
                self.fail(f"{operation} bypassed the injected shutdown deadline")
            if blocked:
                with self.assertRaisesRegex(RuntimeError, "drain"):
                    await running
            else:
                await running
        self.assertEqual(order, ["writer", "discord", "db"])
        self.assertFalse(bot.admitting)
        self.assertEqual(len(deadlines), 3)
        self.assertTrue(all(0 < timeout <= 20 for timeout in deadlines))

    async def test_serve_cleanup_order(self):
        await self.assert_final_cleanup("serve", blocked=False)

    async def test_sync_cleanup_order(self):
        await self.assert_final_cleanup("sync_commands", blocked=False)

    async def test_serve_blocked_close_uses_drain_deadline(self):
        await self.assert_final_cleanup("serve", blocked=True)

    async def test_sync_blocked_close_uses_drain_deadline(self):
        await self.assert_final_cleanup("sync_commands", blocked=True)

    async def test_drain_idempotent_and_bounded(self):
        order, deadlines = [], []
        now = [100.0]

        async def finish(name):
            self.assertFalse(self.bot.admitting)
            order.append(name)
            now[0] += 1

        async def wait_for(awaitable, timeout):
            deadlines.append(timeout)
            return await awaitable

        self.bot.clock = lambda: now[0]
        self.bot.wait_for = wait_for
        self.bot.admitting = True
        self.bot.writer = SimpleNamespace(close=lambda: finish("writer"), abort=AsyncMock())
        self.bot.db = SimpleNamespace(close=lambda: finish("db"))
        with patch.object(discord.Client, "close", lambda client: finish("discord")):
            self.assertEqual(await asyncio.gather(self.bot.drain(), self.bot.drain()), [0, 0])
            self.assertEqual(await self.bot.drain(), 0)
        self.assertEqual(order, ["writer", "discord", "db"])
        self.assertEqual(deadlines, [19, 19, 18])

    async def test_timeout_aborts_writer_and_reports_failure(self):
        started = asyncio.Event()

        async def stuck():
            started.set()
            await asyncio.Future()

        async def deadline(awaitable, timeout):
            return await asyncio.wait_for(awaitable, min(timeout, 0.01))

        self.bot.wait_for = deadline
        self.bot.writer = SimpleNamespace(close=stuck, abort=AsyncMock())
        self.bot.db = SimpleNamespace(close=AsyncMock())
        with self.assertRaisesRegex(RuntimeError, "drain"):
            await self.bot.drain()
        self.assertTrue(started.is_set())
        self.bot.writer.abort.assert_awaited_once()
        self.bot.db.close.assert_awaited_once()
        self.assertTrue(self.bot.is_closed())

    async def test_serve_exits_1_after_writer_died_on_failed_rollback(self):
        self.bot.writer = SimpleNamespace(close=AsyncMock(), abort=AsyncMock(), _failure=OSError("disk"))
        self.bot.db = SimpleNamespace(close=AsyncMock())
        with patch.object(self.bot, "start", AsyncMock()), patch.object(signal, "signal"):
            self.assertEqual(await self.bot.serve(), 1)

    async def test_restart_exits_75_after_drain(self):
        with patch.object(self.bot, "drain", AsyncMock(return_value=0)) as drain:
            with self.assertRaises(SystemExit) as exit_status:
                await self.bot.restart()
        drain.assert_awaited_once()
        self.assertEqual(exit_status.exception.code, 75)

    async def test_failed_drain_never_reports_successful_restart(self):
        with patch.object(self.bot, "drain", AsyncMock(side_effect=RuntimeError("drain failed"))):
            with self.assertRaisesRegex(RuntimeError, "drain failed"):
                await self.bot.restart()

    async def test_cancelled_drain_waiter_does_not_cancel_cleanup(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def finish():
            started.set()
            await release.wait()

        self.bot.writer = SimpleNamespace(close=finish, abort=AsyncMock())
        self.bot.db = SimpleNamespace(close=AsyncMock())
        waiter = asyncio.create_task(self.bot.drain())
        await started.wait()
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        release.set()
        self.assertEqual(await self.bot.drain(), 0)
        self.bot.db.close.assert_awaited_once()

    async def test_signals_drain_and_restore_handlers(self):
        previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
        callbacks = {}

        def install(number, handler):
            callbacks[number] = handler

        async def start(token):
            self.assertEqual(token, "synthetic-token")
            callbacks[signal.SIGTERM](signal.SIGTERM, None)
            await asyncio.sleep(0)

        with patch.object(signal, "signal", side_effect=install) as installed, \
                patch.object(self.bot, "start", side_effect=start), \
                patch.object(self.bot, "drain", AsyncMock(return_value=0)) as drain:
            self.assertEqual(await self.bot.serve(), 0)
        self.assertGreaterEqual(drain.await_count, 1)
        for number, handler in previous.items():
            self.assertIn(unittest.mock.call(number, handler), installed.call_args_list)

    async def assert_signal_during_startup(self, *, paused_open):
        handlers, entered = {}, asyncio.Event()
        previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
        conn = SimpleNamespace(close=AsyncMock())

        async def open_paused(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                return conn

        async def start(token):
            if not paused_open:
                handlers[signal.SIGTERM](signal.SIGTERM, None)
                await asyncio.sleep(0)
            await self.bot.setup_hook()

        with patch.object(signal, "signal", side_effect=lambda number, handler: handlers.update({number: handler})) as installed, \
                patch.object(self.bot, "start", side_effect=start), \
                patch.object(self.client, "open_db", side_effect=open_paused) as opening, \
                patch.object(self.client, "Writer") as writer:
            running = asyncio.create_task(self.bot.serve())
            if paused_open:
                await entered.wait()
                handlers[signal.SIGTERM](signal.SIGTERM, None)
            self.assertEqual(await asyncio.wait_for(running, timeout=1), 0)
        self.assertFalse(self.bot.admitting)
        self.assertTrue(self.bot.is_closed())
        writer.assert_not_called()
        if paused_open:
            conn.close.assert_awaited_once()
        else:
            opening.assert_not_awaited()
        for number, handler in previous.items():
            self.assertIn(unittest.mock.call(number, handler), installed.call_args_list)

    async def test_signal_during_paused_startup_exits_zero(self):
        await self.assert_signal_during_startup(paused_open=True)

    async def test_signal_before_setup_exits_zero(self):
        await self.assert_signal_during_startup(paused_open=False)

    async def assert_external_cancellation(self, *, with_signal):
        handlers, entered = {}, asyncio.Event()

        async def open_paused(*args, **kwargs):
            entered.set()
            await asyncio.Future()

        async def start(token):
            await self.bot.setup_hook()

        with patch.object(signal, "signal", side_effect=lambda number, handler: handlers.update({number: handler})), \
                patch.object(self.bot, "start", side_effect=start), \
                patch.object(self.client, "open_db", side_effect=open_paused):
            running = asyncio.create_task(self.bot.serve())
            await entered.wait()
            if with_signal:
                handlers[signal.SIGTERM](signal.SIGTERM, None)
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running
        self.assertFalse(self.bot.admitting)
        self.assertTrue(self.bot.is_closed())
        self.assertTrue(self.bot._startup_task.cancelled())

    async def test_external_serve_cancellation_remains_cancelled(self):
        await self.assert_external_cancellation(with_signal=False)

    async def test_external_cancellation_with_signal_remains_cancelled(self):
        await self.assert_external_cancellation(with_signal=True)

    async def test_signal_does_not_hide_real_startup_failure(self):
        handlers = {}

        async def start(token):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            raise ValueError("synthetic startup failure")

        with patch.object(signal, "signal", side_effect=lambda number, handler: handlers.update({number: handler})), \
                patch.object(self.bot, "start", side_effect=start):
            with self.assertRaisesRegex(ValueError, "synthetic startup failure"):
                await self.bot.serve()

    async def test_signal_does_not_hide_drain_failure(self):
        handlers = {}

        async def start(token):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            await asyncio.sleep(0)
            await self.bot.setup_hook()

        with patch.object(signal, "signal", side_effect=lambda number, handler: handlers.update({number: handler})), \
                patch.object(self.bot, "start", side_effect=start), \
                patch.object(self.bot, "drain", AsyncMock(side_effect=RuntimeError("synthetic drain failure"))):
            with self.assertRaisesRegex(RuntimeError, "synthetic drain failure"):
                await self.bot.serve()

    async def test_custom_id_pattern(self):
        item = self.client.WalkerItem(discord.ui.Button(custom_id="pw:v1:abcd-1234:42:catch"))
        self.assertEqual(item.template.fullmatch(item.custom_id).groupdict(),
                         {"session": "abcd-1234", "rev": "42", "action": "catch"})
        for invalid in ("pw:v2:a:1:catch", "pw:v1:A:1:catch", "pw:v1:a:-1:catch",
                        "pw:v1:a:1:catch!", "pw:v1:a:1:catch\n"):
            self.assertIsNone(item.template.fullmatch(invalid))
        # M1.6 replaces the placeholder reply with the durable router.
        interaction = SimpleNamespace(client=self.bot)
        self.bot.walker.route = AsyncMock()
        await item.callback(interaction)
        self.bot.walker.route.assert_awaited_once_with(interaction, item.custom_id)

    async def test_sync_requires_explicit_scope_and_yes(self):
        for args in (["sync-commands"], ["sync-commands", "--yes"],
                     ["sync-commands", "--guild", "123", "--global", "--yes"],
                     ["sync-commands", "--guild", "0", "--yes"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), \
                    patch.object(self.client, "WalkerBot") as factory:
                with self.assertRaises(SystemExit) as stopped:
                    self.client.main(args)
                self.assertNotEqual(stopped.exception.code, 0)
                factory.assert_not_called()
        with patch.object(self.client.Settings, "from_env", return_value=self.settings), \
                patch.object(self.client, "WalkerBot", return_value=self.bot), \
                patch.object(self.client.asyncio, "run") as run, redirect_stdout(io.StringIO()) as output:
            self.assertNotEqual(self.client.main(["sync-commands", "--global"]), 0)
            run.assert_not_called()
        self.assertIn("--yes", output.getvalue())
        self.assertRegex(output.getvalue(), r"[0-9a-f]{64}")

    async def test_sync_authenticates_without_gateway_for_selected_scope(self):
        with patch.object(self.bot, "login", AsyncMock()) as login, \
                patch.object(self.bot, "connect", AsyncMock()) as connect, \
                patch.object(self.bot.tree, "sync", AsyncMock()) as sync:
            await self.bot.sync_commands(guild_id=123)
            sync.assert_awaited_once()
            self.assertEqual(sync.await_args.kwargs["guild"].id, 123)
            sync.reset_mock()
            await self.bot.sync_commands(guild_id=None)
            sync.assert_awaited_once_with(guild=None)
        login.assert_awaited_with("synthetic-token")
        connect.assert_not_awaited()

    async def test_command_manifest_hash_covers_scope_and_commands(self):
        before = self.bot.command_manifest_hash()
        self.assertNotEqual(before, self.bot.command_manifest_hash(123))

        @discord.app_commands.command(name="fixture", description="Synthetic command")
        async def fixture(interaction: discord.Interaction):
            pass

        self.bot.tree.add_command(fixture)
        self.assertNotEqual(before, self.bot.command_manifest_hash())
        self.assertEqual(self.bot.command_manifest_hash(), self.bot.command_manifest_hash())

    async def test_check_config_never_constructs_client_or_network(self):
        with patch.object(self.client.Settings, "from_env", return_value=self.settings), \
                patch.object(self.client, "WalkerBot") as factory, redirect_stdout(io.StringIO()):
            self.assertEqual(self.client.main(["check-config"]), 0)
        factory.assert_not_called()


class CliDispatchTests(unittest.TestCase):
    def test_run_and_confirmed_sync_dispatch_only_requested_operation(self):
        client = importlib.import_module("pokewalker.bot.client")
        for args, operation, guild in [(["run"], "serve", None),
                                       (["sync-commands", "--global", "--yes"], "sync_commands", None),
                                       (["sync-commands", "--guild", "123", "--yes"], "sync_commands", 123)]:
            with self.subTest(args=args):
                bot = SimpleNamespace(serve=AsyncMock(return_value=0), sync_commands=AsyncMock(),
                                      command_manifest_hash=Mock(return_value="a" * 64))
                with patch.object(client.Settings, "from_env"), \
                        patch.object(client, "WalkerBot", return_value=bot), redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(client.main(args), 0)
                if operation == "serve":
                    bot.serve.assert_awaited_once_with()
                    bot.sync_commands.assert_not_awaited()
                else:
                    bot.command_manifest_hash.assert_called_once_with(guild)
                    bot.sync_commands.assert_awaited_once_with(guild)
                    bot.serve.assert_not_awaited()
                    self.assertIn("a" * 64, output.getvalue())

class AdminManifestTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, guild=123):
        from pokewalker.config import Secret
        return SimpleNamespace(token=Secret('synthetic-token'), owner_ids=frozenset({456}), admin_guild_id=guild)

    async def test_admin_registered_only_to_admin_guild_else_absent_and_logged(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(self.settings())
        self.addAsyncCleanup(bot.drain)
        self.assertIsNone(bot.tree.get_command('admin'))
        self.assertIsNone(bot.tree.get_command('admin', guild=discord.Object(id=999)))
        admin = bot.tree.get_command('admin', guild=discord.Object(id=123))
        self.assertIsNotNone(admin)
        self.assertTrue(admin.guild_only)
        self.assertEqual({c.name for c in admin.commands}, {'status', 'errors', 'restart'})
        with self.assertLogs('pokewalker.bot.admin', 'WARNING') as captured:
            disabled = WalkerBot(self.settings(None))
        self.addAsyncCleanup(disabled.drain)
        self.assertIsNone(disabled.tree.get_command('admin'))
        self.assertIsNone(disabled.tree.get_command('admin', guild=discord.Object(id=123)))
        self.assertIn('disabled', ' '.join(captured.output).lower())

    async def test_sync_payload_and_hash_contain_only_selected_scope(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(self.settings())
        self.addAsyncCleanup(bot.drain)
        bot._connection.application_id = 987
        guild = discord.Object(id=123)

        @discord.app_commands.command(name='collision', description='Global command')
        async def global_command(interaction: discord.Interaction):
            pass

        @discord.app_commands.command(name='collision', description='Guild command')
        async def guild_command(interaction: discord.Interaction):
            pass

        bot.tree.add_command(global_command)
        bot.tree.add_command(guild_command, guild=guild)
        bot.tree.add_command(guild_command, guild=discord.Object(id=999))
        global_payload = [c.to_dict(bot.tree) for c in bot.tree.get_commands()]
        other_payload = [c.to_dict(bot.tree) for c in bot.tree.get_commands(guild=discord.Object(id=999))]
        before = bot.command_manifest_hash(123)
        global_before = bot.command_manifest_hash()
        with patch.object(bot, 'login', AsyncMock()), \
                patch.object(bot.http, 'bulk_upsert_guild_commands', AsyncMock(return_value=[])) as guild_sync, \
                patch.object(bot.http, 'bulk_upsert_global_commands', AsyncMock(return_value=[])) as global_sync:
            await bot.sync_commands(123)
            guild_sync.assert_awaited_once()
            self.assertEqual(guild_sync.await_args.args, (987, 123))
            payload = guild_sync.await_args.kwargs['payload']
            self.assertEqual({c['name'] for c in payload}, {'admin', 'collision'})
            self.assertEqual(next(c['description'] for c in payload if c['name'] == 'collision'), 'Guild command')
            expected = {'scope': 123, 'commands': sorted(payload, key=lambda c: c['name'])}
            digest = hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            self.assertEqual(before, digest)
            self.assertEqual(bot.command_manifest_hash(123), digest)
            global_sync.assert_not_awaited()
            self.assertIsNone(bot.tree.get_command('admin'))
            self.assertEqual([c.to_dict(bot.tree) for c in bot.tree.get_commands()], global_payload)
            self.assertEqual([c.to_dict(bot.tree) for c in bot.tree.get_commands(guild=discord.Object(id=999))],
                             other_payload)
            self.assertEqual(bot.command_manifest_hash(), global_before)
            await bot.sync_commands()
            global_sync.assert_awaited_once_with(987, payload=global_payload)
            self.assertEqual(guild_sync.await_count, 1)
            empty_before = bot.command_manifest_hash(321)
            await bot.sync_commands(321)
            guild_sync.assert_awaited_with(987, 321, payload=[])
            self.assertEqual(bot.command_manifest_hash(321), empty_before)
            expected = {'scope': 321, 'commands': []}
            self.assertEqual(empty_before, hashlib.sha256(
                json.dumps(expected, sort_keys=True, separators=(',', ':')).encode()).hexdigest())

    async def test_guild_hash_ignores_global_changes_and_tracks_guild_changes(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(self.settings())
        self.addAsyncCleanup(bot.drain)
        before = bot.command_manifest_hash(123)
        global_before = bot.command_manifest_hash()
        other_before = bot.command_manifest_hash(999)
        bot.tree.remove_command('walker')
        self.assertEqual(bot.command_manifest_hash(123), before)
        self.assertNotEqual(bot.command_manifest_hash(), global_before)
        bot.tree.remove_command('admin', guild=discord.Object(id=123))
        self.assertNotEqual(bot.command_manifest_hash(123), before)
        self.assertEqual(bot.command_manifest_hash(999), other_before)
        expected = {'scope': 999, 'commands': []}
        self.assertEqual(other_before, hashlib.sha256(
            json.dumps(expected, sort_keys=True, separators=(',', ':')).encode()).hexdigest())

    async def test_manifests_global_without_admin_guild_with_admin(self):
        from pokewalker.bot.client import WalkerBot
        bot = WalkerBot(self.settings())
        disabled = WalkerBot(self.settings(None))
        self.addAsyncCleanup(bot.drain)
        self.addAsyncCleanup(disabled.drain)
        self.assertEqual(bot.command_manifest_hash(), disabled.command_manifest_hash())
        self.assertEqual(bot.command_manifest_hash(999), disabled.command_manifest_hash(999))
        self.assertNotEqual(bot.command_manifest_hash(123), disabled.command_manifest_hash(123))
        names = {c.name for c in bot.scope_commands(discord.Object(id=123))}
        self.assertEqual(names, {'admin'})
