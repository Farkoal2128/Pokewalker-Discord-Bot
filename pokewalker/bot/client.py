"""C5 Gateway process, bounded lifecycle and explicit command registration."""

import argparse
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import signal
import time

import discord
from discord import app_commands

from pokewalker.config import Settings, snowflake
from pokewalker.db import Writer, open_db
from pokewalker.bot.admin_channels import WalkerAdmin
from pokewalker.bot.admin_trade_channels import TradeChannels
from pokewalker.bot.mod import WalkerMod
from pokewalker.bot.account import WalkerAccount, load_privacy
from pokewalker.bot.checkin import command as checkin_command
from pokewalker.bot.raid import command as raid_command
from pokewalker.bot.trade import command as trade_command
from pokewalker.bot.heartbeat import Heartbeat
from pokewalker.services import gyms, raids, research, trading
from pokewalker.services.reactions import ReactionService
from pokewalker.services.deletion import replay_markers
from pokewalker.bot import admin, messages
from pokewalker.bot.walker import CUSTOM_ID, Walker, command


class _StartupStopped(RuntimeError):
    """Shutdown refused startup before any resources were acquired."""


LOG = logging.getLogger(__name__)
HELP_PATH = Path(__file__).resolve().parents[2] / 'content' / 'help.md'


def load_help():
    try:
        text = HELP_PATH.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as error:
        raise ValueError(f'Cannot read help text at {HELP_PATH}') from error
    if not text.strip() or len(text.encode('utf-16-le')) // 2 > 4096:
        raise ValueError('Help text must be nonempty and at most 4096 characters')
    return text


def readme_command(bot):
    @app_commands.command(name='readme', description='Learn how Pokéwalker works')
    @app_commands.guild_only()
    async def readme(interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message('Use /readme in a server.', ephemeral=True)
            return
        await interaction.response.send_message(embed=discord.Embed(description=bot.help_text), ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())
    return readme


class WalkerItem(discord.ui.DynamicItem[discord.ui.Item], template=CUSTOM_ID):
    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(item)

    async def callback(self, interaction):
        await interaction.client.walker.route(interaction, self.custom_id)


def load_content(path):
    raw = path.read_bytes()
    manifest = json.loads((path.parent.parent / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("artifact_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("Content artifact hash differs from manifest")
    return json.loads(raw)


class WalkerBot(discord.Client):
    def __init__(self, settings, *, clock=time.monotonic, wait_for=asyncio.wait_for):
        intents = discord.Intents.none()
        intents.guilds = intents.guild_messages = intents.message_content = True
        super().__init__(intents=intents, max_messages=None)
        self.settings, self.clock, self.wait_for = settings, clock, wait_for
        self.tree = app_commands.CommandTree(
            self, allowed_contexts=app_commands.AppCommandContext(
                guild=True, dm_channel=False, private_channel=False),
            allowed_installs=app_commands.AppInstallationType(guild=True, user=False))
        admin_group = WalkerAdmin(self)
        admin_group.add_command(TradeChannels(admin_group))
        self.tree.add_command(admin_group)
        self.tree.add_command(WalkerMod(self))
        self.tree.add_command(WalkerAccount(self))
        self.walker = Walker(self)
        self.tree.add_command(command(self))
        self.tree.add_command(checkin_command(self))
        self.tree.add_command(raid_command(self))
        self.tree.add_command(trade_command(self))
        self.tree.add_command(readme_command(self))
        self.admin = admin.register(self)
        self.started_at = self.clock()
        self.message_counts = {"received": 0, "credited": 0}
        self.db = self.writer = self.content = None
        self.admitting = False
        self._stopping = False
        self._startup_task = None
        self._drain_task = None
        self.reactions = None
        self._reaction_sweep = None
        self._gym_sweep = None
        self.heartbeat = Heartbeat(self)

    async def setup_hook(self):
        if self._stopping:
            raise _StartupStopped("Bot is stopping; startup refused")
        if self._startup_task is None:
            self._startup_task = asyncio.create_task(self._setup())
        try:
            await asyncio.shield(self._startup_task)
        except BaseException:
            await self.drain()
            raise

    async def _setup(self):
        if self.admin is not None:
            self.admin.attach_errors()
        self.privacy_text = load_privacy(self.settings)
        self.help_text = load_help()
        self.content = load_content(self.settings.content_path)
        conn = await open_db(self.settings.db_path,
                             allow_unpatched=self.settings.allow_unpatched_sqlite)
        if self._stopping:
            await conn.close()
            raise asyncio.CancelledError
        self.db = conn
        self.writer = Writer(conn)
        await replay_markers(self.writer, self.settings.marker_log_path)
        self.reactions = ReactionService(self)
        self.add_dynamic_items(WalkerItem)
        self.admitting = True

    async def on_ready(self):
        if not self._stopping and self.writer is not None:
            self.heartbeat.start()
            if self._gym_sweep is None:
                self._gym_sweep = asyncio.create_task(self._gym_sweep_loop())
        if not self._stopping and self.reactions is not None and self._reaction_sweep is None:
            self._reaction_sweep = asyncio.create_task(self.reactions.startup_sweep())
            await self._reaction_sweep
            if not self._stopping:
                await raids.resume_pending(self)

    async def _sweep_once(self):
        async def settle(conn):
            now = self.walker.clock()
            await gyms.settle(conn, now, self.walker.rng, self.content)
            await raids.expire(conn, now)
            await research.auto_send(conn, now, self.content)
            await trading.prune(conn, now)
            # A day of grace past expiry; the router already refuses expired sessions.
            await conn.execute('DELETE FROM sessions WHERE expires_at<=?', (now - 86400,))
        await self.writer.run(settle)

    async def _gym_sweep_loop(self):
        while True:
            try:
                await self._sweep_once()
            except Exception:
                LOG.exception("Gym settlement sweep failed")
            await asyncio.sleep(60)

    async def on_message(self, message):
        if self.admitting:
            await messages.on_message(self, message)

    def _begin_drain(self):
        self._stopping = True
        self.admitting = False
        if self._drain_task is None:
            self._drain_task = asyncio.create_task(self._drain())

    async def drain(self):
        self._begin_drain()
        return await asyncio.shield(self._drain_task)

    async def _drain(self):
        if self.admin is not None:
            self.admin.detach_errors()
        deadline = self.clock() + 20
        failures = []

        async def bounded(awaitable, limit=20):
            return await self.wait_for(awaitable, timeout=max(0, min(limit, deadline - self.clock())))

        if self._startup_task is not None and not self._startup_task.done():
            self._startup_task.cancel()
            try:
                results = await bounded(asyncio.gather(self._startup_task, return_exceptions=True), limit=19)
                failures.extend(result for result in results if isinstance(result, Exception))
            except Exception as error:
                failures.append(error)
        if self._reaction_sweep is not None and not self._reaction_sweep.done():
            self._reaction_sweep.cancel()
            try:
                await bounded(asyncio.gather(self._reaction_sweep, return_exceptions=True), limit=19)
            except Exception as error:
                failures.append(error)
        if self._gym_sweep is not None and not self._gym_sweep.done():
            self._gym_sweep.cancel()
            try:
                await bounded(asyncio.gather(self._gym_sweep, return_exceptions=True), limit=19)
            except Exception as error:
                failures.append(error)
        if self.heartbeat._task is not None:
            try:
                await bounded(self.heartbeat.stop(), limit=19)
            except Exception as error:
                failures.append(error)
        if self.writer is not None:
            try:
                # Reserve one second for rollback and connection cleanup after timeout.
                await bounded(self.writer.close(), limit=19)
            except Exception as error:
                failures.append(error)
                try:
                    await bounded(self.writer.abort())
                except Exception as abort_error:
                    failures.append(abort_error)
        for close in (super().close, self.db.close if self.db is not None else None):
            if close is not None:
                try:
                    await bounded(close())
                except Exception as error:
                    failures.append(error)
        if failures:
            raise RuntimeError("Shutdown drain failed; accepted work may have been aborted") from failures[0]
        return 0

    async def restart(self):
        await self.drain()
        raise SystemExit(75)

    async def serve(self):
        loop = asyncio.get_running_loop()
        previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
        signal_shutdown = False

        def shutdown(number, frame):
            nonlocal signal_shutdown
            signal_shutdown = True
            loop.call_soon_threadsafe(self._begin_drain)

        try:
            for number in previous:
                signal.signal(number, shutdown)
            await self.start(self.settings.token.value)
        except asyncio.CancelledError:
            if (not signal_shutdown or asyncio.current_task().cancelling()
                    or self._startup_task is None or not self._startup_task.cancelled()):
                raise
        except _StartupStopped:
            if not signal_shutdown:
                raise
        finally:
            try:
                await self.drain()
            finally:
                for number, handler in previous.items():
                    signal.signal(number, handler)
        # Non-zero lets Restart=on-failure replace a process whose writer died.
        return 1 if getattr(self.writer, "_failure", None) is not None else 0

    def scope_commands(self, guild):
        return sorted(self.tree.get_commands(guild=guild), key=lambda command: command.name)

    def command_manifest_hash(self, guild_id=None):
        guild = discord.Object(id=guild_id) if guild_id else None
        commands = self.scope_commands(guild)
        manifest = {"scope": guild_id or "global", "commands": [command.to_dict(self.tree) for command in commands]}
        return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    async def sync_commands(self, guild_id=None):
        try:
            await self.login(self.settings.token.value)
            guild = discord.Object(id=guild_id) if guild_id else None
            await self.tree.sync(guild=guild)
        finally:
            await self.drain()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    commands.add_parser("check-config")
    sync = commands.add_parser("sync-commands")
    scope = sync.add_mutually_exclusive_group(required=True)
    scope.add_argument("--guild", type=snowflake)
    scope.add_argument("--global", dest="global_scope", action="store_true")
    sync.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.command == "check-config":
        load_privacy(settings)
        load_help()
        load_content(settings.content_path)
        print("Configuration and content hash valid")
        return 0
    bot = WalkerBot(settings)
    if args.command == "sync-commands":
        print(f"Command manifest SHA256: {bot.command_manifest_hash(args.guild)}")
        if not args.yes:
            print("Pass --yes to synchronize this scope")
            return 1
        asyncio.run(bot.sync_commands(args.guild))
        return 0
    return asyncio.run(bot.serve())
