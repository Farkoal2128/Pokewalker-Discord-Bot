"""C5 trade channel configuration (OD8/P11); all mutations use the single writer."""

import time

import discord
from discord import app_commands

from pokewalker.services.profiles import restrictions

EXCLUDED = "Excluded members cannot configure walker channels."


class TradeChannels(app_commands.Group):
    """`/walker-admin trade-channels`; the root supplies guild-only and Manage Server defaults."""

    def __init__(self, admin):
        super().__init__(name="trade-channels", description="Configure channels where members can trade")
        self.admin = admin

    async def excluded(self, conn, interaction):
        return (await restrictions(conn, interaction.guild_id, interaction.user.id)).excluded

    async def write(self, conn, interaction, channel_id, reason, now, *, remove=False):
        guild_id, channel_id = str(interaction.guild_id), str(channel_id)
        sql = ("DELETE FROM trade_channels WHERE guild_id=? AND channel_id=?" if remove
               else "INSERT OR IGNORE INTO trade_channels(guild_id,channel_id) VALUES (?,?)")
        await conn.execute(sql, (guild_id, channel_id))
        await conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                           "VALUES (?,?,'channel',?,?,?,?)", (guild_id, str(interaction.user.id), channel_id,
                           "trade_channels_remove" if remove else "trade_channels_add", reason, now))

    async def change(self, interaction, channel, reason, *, remove=False):
        await interaction.response.defer(ephemeral=True)
        if not await self.admin.authorize(interaction):
            return
        if channel.guild.id != interaction.guild_id:
            await self.admin.reply(interaction, "Choose a channel in this server.")
            return
        reason = reason.strip()
        if not reason:
            await self.admin.reply(interaction, "A reason is required.")
            return

        async def mutation(conn):
            if await self.excluded(conn, interaction):
                return False
            now = time.time()
            await conn.execute("INSERT OR IGNORE INTO guilds(guild_id,created_at) VALUES (?,?)",
                               (str(interaction.guild_id), now))
            await self.write(conn, interaction, channel.id, reason, now, remove=remove)
            return True

        if not await self.admin.bot.writer.run(mutation):
            await self.admin.reply(interaction, EXCLUDED)
            return
        message = "Trade channel removed." if remove else "Trade channel added."
        if not remove and not channel.permissions_for(interaction.guild.me).send_messages:
            message += " Missing Send Messages; trade pings will fail until permissions recover."
        await self.admin.reply(interaction, message)

    @app_commands.command(name="add", description="Allow trading in a channel")
    async def add(self, interaction: discord.Interaction, channel: discord.TextChannel, reason: str):
        await self.change(interaction, channel, reason)

    @app_commands.command(name="remove", description="Stop new trades in a channel")
    async def remove(self, interaction: discord.Interaction, channel: discord.TextChannel, reason: str):
        await self.change(interaction, channel, reason, remove=True)

    @app_commands.command(name="add-all", description="Allow trading in all channels the bot can post in")
    async def add_all(self, interaction: discord.Interaction, reason: str):
        await interaction.response.defer(ephemeral=True)
        if not await self.admin.authorize(interaction):
            return
        reason = reason.strip()
        if not reason:
            await self.admin.reply(interaction, "A reason is required.")
            return
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except discord.HTTPException:
            await self.admin.reply(interaction, "Could not confirm your Manage Server permission. Nothing was changed.")
            return
        if not member.guild_permissions.manage_guild:
            await self.admin.reply(interaction, "Manage Server permission is required.")
            return

        async def mutation(conn):
            if await self.excluded(conn, interaction):
                return None
            guild_id, now = str(interaction.guild_id), time.time()
            await conn.execute("INSERT OR IGNORE INTO guilds(guild_id,created_at) VALUES (?,?)", (guild_id, now))
            async with conn.execute("SELECT channel_id FROM trade_channels WHERE guild_id=?", (guild_id,)) as cursor:
                existing = {row["channel_id"] for row in await cursor.fetchall()}
            enabled = skipped = already = 0
            for channel in interaction.guild.text_channels:
                permissions = channel.permissions_for(interaction.guild.me)
                if not permissions.view_channel or not permissions.send_messages:
                    skipped += 1
                elif str(channel.id) in existing:
                    already += 1
                else:
                    await self.write(conn, interaction, channel.id, reason, now)
                    enabled += 1
            return enabled, skipped, already

        result = await self.admin.bot.writer.run(mutation)
        if result is None:
            await self.admin.reply(interaction, EXCLUDED)
            return
        enabled, skipped, already = result
        await self.admin.reply(interaction, f"Enabled {enabled} channel{'' if enabled == 1 else 's'}; skipped {skipped} "
                               f"(no access); {already} already enabled. Channels created later are not added automatically.")

    @app_commands.command(name="list", description="List this server's trade channels")
    async def list_channels(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self.admin.authorize(interaction):
            return

        async def read(conn):
            if await self.excluded(conn, interaction):
                return None
            async with conn.execute("SELECT channel_id FROM trade_channels WHERE guild_id=? ORDER BY channel_id",
                                    (str(interaction.guild_id),)) as cursor:
                return [f"<#{row['channel_id']}>" for row in await cursor.fetchall()]

        lines = await self.admin.bot.writer.run(read)
        if lines is None:
            await self.admin.reply(interaction, EXCLUDED)
            return
        if not lines:
            await self.admin.reply(interaction, "No trade channels configured.")
            return
        # Sixty snowflake mentions (at most 24 characters each) stay below Discord's 2000-character limit.
        for start in range(0, len(lines), 60):
            text = "\n".join(lines[start:start + 60])
            if start == 0:
                await self.admin.reply(interaction, text)
            else:
                await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
