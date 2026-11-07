"""Crash-safe own-reaction reconciliation; Discord I/O is always after commit."""

import asyncio
import logging
from weakref import WeakValueDictionary

import discord

from pokewalker.services.profiles import channel_policy


LOG = logging.getLogger(__name__)
EMOJI = "❗"


class ReactionService:
    def __init__(self, bot):
        self.bot = bot
        self.writer = bot.writer
        self._locks = WeakValueDictionary()
        self._warned_channels = set()

    def _outside_writer(self):
        # Queuing another writer job from its own task would deadlock.
        if asyncio.current_task() is self.writer._task:
            raise RuntimeError("Reaction reconciliation cannot run inside a writer transaction")

    async def _read(self, column, key):
        async def read(conn):
            async with conn.execute(
                f"SELECT r.*,p.guild_id FROM reactions r JOIN profiles p USING(profile_id) "
                f"WHERE r.{column}=?", (key,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row is not None else None
        return await self.writer.run(read)

    async def reconcile_reaction(self, encounter_id):
        self._outside_writer()
        await self._reconcile("encounter_id", encounter_id)

    async def reconcile_message(self, message_id):
        """Reconcile pending pre-0002 rows that have no encounter coordinate."""
        self._outside_writer()
        await self._reconcile("message_id", message_id)

    async def startup_sweep(self):
        self._outside_writer()

        async def pending(conn):
            async with conn.execute(
                "SELECT encounter_id,message_id FROM reactions "
                "WHERE desired='remove' OR (desired='add' AND actual='none')") as cursor:
                return await cursor.fetchall()

        for row in await self.writer.run(pending):
            if row["encounter_id"] is None:
                await self._reconcile("message_id", row["message_id"])
            else:
                await self.reconcile_reaction(row["encounter_id"])

    async def _reconcile(self, column, key):
        lock_key = (column, key)
        lock = self._locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            row = await self._read(column, key)
            if row is None:
                return
            try:
                if row["desired"] == "add" and row["actual"] == "none":
                    channel = self.bot.get_channel(int(row["channel_id"]))
                    if channel is None:
                        channel = await self.bot.fetch_channel(int(row["channel_id"]))

                    async def policy(conn):
                        return await channel_policy(conn, row["guild_id"], row["channel_id"],
                                                    getattr(channel, "parent_id", None))

                    configured = await self.writer.run(policy)
                    if configured is not None and configured["react"]:
                        await self._message(row).add_reaction(EMOJI)
                        await self._mark_added(row)
                row = await self._read(column, key)
                if row is not None and row["desired"] == "remove":
                    try:
                        await self._message(row).remove_reaction(EMOJI, self.bot.user)
                    except discord.NotFound:
                        pass
                    await self._retire(row)
            except discord.Forbidden:
                if row["channel_id"] not in self._warned_channels:
                    self._warned_channels.add(row["channel_id"])
                    LOG.warning("Reaction permission denied in channel %s; pending retry", row["channel_id"])
            except discord.HTTPException:
                pass

    async def remove_own(self, rows):
        """Remove own reactions for rows already deleted with their profile (D28)."""
        self._outside_writer()
        for row in rows:
            # Same lock as _reconcile: an in-flight add finishes (and sees no row) before we remove.
            key = (("message_id", row["message_id"]) if row["encounter_id"] is None
                   else ("encounter_id", row["encounter_id"]))
            async with self._locks.setdefault(key, asyncio.Lock()):
                try:
                    await self._message(row).remove_reaction(EMOJI, self.bot.user)
                except discord.HTTPException:  # NotFound, Forbidden: nothing left to retry from
                    pass

    def _message(self, row):
        return self.bot.get_partial_messageable(int(row["channel_id"])).get_partial_message(
            int(row["message_id"]))

    async def _mark_added(self, row):
        async def update(conn):
            await conn.execute(
                "UPDATE reactions SET actual='added' WHERE message_id=? AND desired='add' AND revision=?",
                (row["message_id"], row["revision"]))
        await self.writer.run(update)

    async def _retire(self, row):
        async def delete(conn):
            await conn.execute(
                "DELETE FROM reactions WHERE message_id=? AND desired='remove' AND revision=?",
                (row["message_id"], row["revision"]))
        await self.writer.run(delete)
