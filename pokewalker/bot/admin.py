"""C5 owner-only diagnostics and durable, confirmed process restart."""

import builtins
from collections import deque
import logging
import math
import time

import discord
from discord import app_commands

from pokewalker.db import open_reader, with_receipt
from pokewalker.services.profiles import restrictions

LOG = logging.getLogger(__name__)


class ErrorBuffer(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = deque(maxlen=10)

    def emit(self, record):
        # Retain only trusted categories, never formatted log/exception text.
        kind = type(record.exc_info[1]).__name__ if record.exc_info else None
        kind = kind if isinstance(getattr(builtins, kind or '', None), type) else 'Exception'
        self.records.append({'time': record.created, 'logger': record.name.split('.')[0]
            if record.name.split('.')[0] in {'pokewalker', 'discord'} else 'application',
            'level': 'CRITICAL' if record.levelno >= logging.CRITICAL else 'ERROR',
            'exception': kind if record.exc_info else 'none'})


class Admin(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name='admin', description='Owner diagnostics and restart', guild_only=True)
        self.bot, self.pending = bot, None
        self.error_handler = ErrorBuffer()
        self.requests = {}

    def attach_errors(self):
        root = logging.getLogger()
        if self.error_handler not in root.handlers:
            root.addHandler(self.error_handler)

    def detach_errors(self):
        logging.getLogger().removeHandler(self.error_handler)
        self.error_handler.close()

    async def reply(self, interaction, text):
        await interaction.edit_original_response(content=text[:2000],
            allowed_mentions=discord.AllowedMentions.none())

    async def authorize(self, interaction, *, status=False):
        await interaction.response.defer(ephemeral=True)
        if (interaction.guild_id != self.bot.settings.admin_guild_id
                or interaction.user.id not in self.bot.settings.owner_ids):
            await self.reply(interaction, 'Only configured owners in the admin guild may use this command.')
            return False
        now = self.bot.clock()
        requests = self.requests.setdefault(interaction.user.id, deque())
        while requests and requests[0] <= now - 60:
            requests.popleft()
        if len(requests) >= 5:
            await self.reply(interaction, f'Slow down, try again in {math.ceil(requests[0] + 60 - now)} s.')
            return False
        requests.append(now)
        if status:
            return True
        excluded = await self.bot.writer.run(lambda conn: self.excluded(conn, interaction))
        if excluded:
            await self.reply(interaction, 'Excluded owners cannot use admin commands.')
            return False
        return True

    async def excluded(self, conn, interaction):
        return (await restrictions(conn, interaction.guild_id, interaction.user.id)).excluded

    @app_commands.command(name='status', description='Show bounded process health')
    async def status(self, interaction: discord.Interaction):
        if not await self.authorize(interaction, status=True):
            return
        excluded, read_failed = False, False
        try:
            reader = await open_reader(self.bot.settings.db_path)
            try:
                excluded = await self.excluded(reader, interaction)
            finally:
                await reader.close()
        except Exception:
            read_failed = True
        if excluded:
            await self.reply(interaction, 'Excluded owners cannot use admin commands.')
            return
        bot, writer = self.bot, self.bot.writer
        queue = writer._queue.qsize() if writer is not None else 0
        closed = writer is None or writer._closed
        failed = writer is not None and writer._failure is not None
        counts = bot.message_counts
        release = getattr(bot.settings, 'release', 'dev').replace(bot.settings.token.value, '***')[:80]
        await self.reply(interaction, f'release={release} uptime={max(0, bot.clock() - bot.started_at):.0f}s '
            f'latency={bot.latency:.3f}s ready={bot.is_ready()}\n'
            f'writer queue={queue} closed={closed} failure={failed} exclusion-read={"failed" if read_failed else "ok"}\n'
            f'guilds={len(bot.guilds)} received={counts["received"]} credited={counts["credited"]} '
            f'rejected={counts["received"] - counts["credited"]}\n'
            f'manifest={bot.command_manifest_hash(bot.settings.admin_guild_id)[:12]}')

    @app_commands.command(name='errors', description='Show ten sanitized error summaries')
    async def errors(self, interaction: discord.Interaction):
        if not await self.authorize(interaction):
            return
        await self.reply(interaction, '\n'.join(
            f'{row["time"]:.0f} {row["logger"]} {row["level"]} {row["exception"]}'
            for row in self.error_handler.records) or 'No recorded errors.')

    @app_commands.command(name='restart', description='Confirm and drain before an intentional restart')
    async def restart(self, interaction: discord.Interaction):
        if not await self.authorize(interaction):
            return
        now = time.time()
        if self.pending is None:
            self.pending = (interaction.user.id, now + 60)
            await self.reply(interaction, 'Confirm by calling /admin restart again within 60 seconds.')
            return
        owner, expires = self.pending
        if now >= expires:
            self.pending = None
            await self.reply(interaction, 'Restart confirmation expired; request it again.')
            return
        if owner != interaction.user.id:
            await self.reply(interaction, 'Only the requesting owner can confirm this restart.')
            return
        self.pending = None

        async def reserve(conn):
            if await self.excluded(conn, interaction):
                return 'Excluded owners cannot restart.'
            async with conn.execute("SELECT 1 FROM action_receipts WHERE action='restart' AND created_at>? LIMIT 1",
                                    (now - 300,)) as cursor:
                if await cursor.fetchone():
                    return 'Restart cooldown is active (300 seconds).'
            async def record(conn):
                return {'restart': True}, []
            await with_receipt(conn, f'restart:{now}', 'restart', record, profile_id=None)
            return None

        refused = await self.bot.writer.run(reserve)
        if refused:
            await self.reply(interaction, refused)
            return
        await self.reply(interaction, 'Restarting; draining accepted work.')
        await self.bot.restart()


def register(bot):
    guild_id = getattr(bot.settings, 'admin_guild_id', None)
    if guild_id is None:
        LOG.warning('Owner admin commands disabled: POKEWALKER_ADMIN_GUILD_ID is unset')
        return None
    admin = Admin(bot)
    bot.tree.add_command(admin, guild=discord.Object(id=guild_id))
    return admin
