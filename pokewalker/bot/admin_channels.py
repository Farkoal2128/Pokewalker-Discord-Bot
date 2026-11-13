"""C5 guild channel policy commands; all mutations use the single writer."""

import math
import time
from datetime import datetime, timezone

import discord
from discord import app_commands

from pokewalker.bot.bag import RAID_REFUSALS
from pokewalker.services import deletion, gyms as gym_service, profiles, raids as raid_service
from pokewalker.services.profiles import restrictions


class _Refused(ValueError):
    pass


class WalkerAdmin(app_commands.Group):
    channels = app_commands.Group(name="channels", description="Configure walker channels")
    gyms = app_commands.Group(name="gyms", description="Manage this server's gyms")

    def __init__(self, bot):
        super().__init__(name="walker-admin", description="Manage this server's walker",
                         guild_only=True, default_permissions=discord.Permissions(manage_guild=True))
        self.bot = bot

    async def authorize(self, interaction):
        if interaction.guild_id is None or not interaction.user.guild_permissions.manage_guild:
            await self.reply(interaction, "Manage Server permission in a server is required.")
            return False
        flags = await self.bot.writer.run(lambda conn: restrictions(conn, interaction.guild_id, interaction.user.id))
        if flags.excluded:
            await self.reply(interaction, "Excluded members cannot configure walker channels.")
            return False
        return True

    async def reply(self, interaction, text):
        if getattr(interaction.response, "is_done", lambda: False)():
            await interaction.edit_original_response(content=text[:2000], allowed_mentions=discord.AllowedMentions.none())
        else:
            await interaction.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def add_all_reason(self, interaction, reason):
        """Shared add-all preamble: the stripped reason, or None after replying with the refusal."""
        await interaction.response.defer(ephemeral=True)
        if not await self.authorize(interaction):
            return None
        reason = reason.strip()
        if not reason:
            await self.reply(interaction, "A reason is required.")
            return None
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except discord.HTTPException:
            await self.reply(interaction, "Could not confirm your Manage Server permission. Nothing was changed.")
            return None
        if not member.guild_permissions.manage_guild:
            await self.reply(interaction, "Manage Server permission is required.")
            return None
        return reason

    async def send_lines(self, interaction, lines, per_message):
        """Reply with lines in chunks that stay under Discord's 2000-character limit."""
        for start in range(0, len(lines), per_message):
            text = "\n".join(lines[start:start + per_message])
            if start == 0:
                await self.reply(interaction, text)
            else:
                await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def write_channel(self, conn, interaction, channel_id, reason, now, *, remove=False, count=True, react=True):
        guild_id, channel_id = str(interaction.guild_id), str(channel_id)
        if remove:
            await conn.execute("DELETE FROM guild_channels WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
        else:
            await conn.execute("INSERT INTO guild_channels VALUES (?,?,?,?) ON CONFLICT(guild_id,channel_id) "
                               "DO UPDATE SET count_steps=excluded.count_steps,react=excluded.react",
                               (guild_id, channel_id, count, react))
        await conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                           "VALUES (?,?,'channel',?,?,?,?)", (guild_id, str(interaction.user.id), channel_id,
                           "channels_remove" if remove else "channels_add", reason, now))

    async def change(self, interaction, channel, reason, *, remove=False, count=True, react=True):
        await interaction.response.defer(ephemeral=True)
        if not await self.authorize(interaction):
            return
        if channel.guild.id != interaction.guild_id:
            await self.reply(interaction, "Choose a channel in this server.")
            return
        reason = reason.strip()
        if not reason:
            await self.reply(interaction, "A reason is required.")
            return

        async def mutation(conn):
            if (await restrictions(conn, interaction.guild_id, interaction.user.id)).excluded:
                return False
            now = time.time()
            await conn.execute("INSERT OR IGNORE INTO guilds(guild_id,created_at) VALUES (?,?)",
                               (str(interaction.guild_id), now))
            await self.write_channel(conn, interaction, channel.id, reason, now, remove=remove, count=count, react=react)
            return True

        if not await self.bot.writer.run(mutation):
            await self.reply(interaction, "Excluded members cannot configure walker channels.")
            return
        message = "Channel removed." if remove else "Channel configured."
        if not remove:
            permissions = channel.permissions_for(interaction.guild.me)
            if not permissions.add_reactions or not permissions.read_message_history:
                message += " Missing Add Reactions or Read Message History; reactions will skip until permissions recover."
        await self.reply(interaction, message)

    @channels.command(name="add", description="Enable a channel with counting and reaction preferences")
    async def add(self, interaction: discord.Interaction, channel: discord.TextChannel,
                  reason: str, count: bool = True, react: bool = True):
        await self.change(interaction, channel, reason, count=count, react=react)

    @channels.command(name="add-all", description="Enable all accessible text and announcement channels")
    async def add_all(self, interaction: discord.Interaction, reason: str, count: bool = True):
        reason = await self.add_all_reason(interaction, reason)
        if reason is None:
            return

        async def mutation(conn):
            if (await restrictions(conn, interaction.guild_id, interaction.user.id)).excluded:
                return None
            now = time.time()
            await conn.execute("INSERT OR IGNORE INTO guilds(guild_id,created_at) VALUES (?,?)",
                               (str(interaction.guild_id), now))
            async with conn.execute("SELECT channel_id FROM guild_channels WHERE guild_id=?",
                                    (str(interaction.guild_id),)) as cursor:
                existing = {row["channel_id"] for row in await cursor.fetchall()}
            enabled = skipped = already = 0
            for channel in interaction.guild.text_channels:
                if not channel.permissions_for(interaction.guild.me).view_channel:
                    skipped += 1
                elif str(channel.id) in existing:
                    already += 1
                else:
                    await self.write_channel(conn, interaction, channel.id, reason, now, count=count)
                    enabled += 1
            return enabled, skipped, already

        result = await self.bot.writer.run(mutation)
        if result is None:
            await self.reply(interaction, "Excluded members cannot configure walker channels.")
            return
        enabled, skipped, already = result
        await self.reply(interaction, f"Enabled {enabled} channel{'' if enabled == 1 else 's'}; skipped {skipped} (no access); {already} already enabled. "
                         "Channels created later are not added automatically.")

    @channels.command(name="remove", description="Remove a channel's walker policy")
    async def remove(self, interaction: discord.Interaction, channel: discord.TextChannel, reason: str):
        await self.change(interaction, channel, reason, remove=True)

    @channels.command(name="list", description="List this server's walker channel policies")
    async def list_channels(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self.authorize(interaction):
            return
        async def read(conn):
            if (await restrictions(conn, interaction.guild_id, interaction.user.id)).excluded:
                return None
            async with conn.execute("SELECT channel_id,count_steps,react FROM guild_channels WHERE guild_id=? "
                                    "ORDER BY channel_id", (str(interaction.guild_id),)) as cursor:
                return await cursor.fetchall()

        rows = await self.bot.writer.run(read)
        if rows is None:
            await self.reply(interaction, "Excluded members cannot configure walker channels.")
            return
        lines = [f"<#{row['channel_id']}> count={bool(row['count_steps'])} react={bool(row['react'])}" for row in rows]
        if not lines:
            await self.reply(interaction, "No walker channels configured.")
            return
        await self.send_lines(interaction, lines, 30)  # thirty snowflake-sized rows per message

    async def check_actor(self, conn, interaction):
        if not interaction.user.guild_permissions.manage_guild:
            raise _Refused("Manage Server permission is required.")
        if (await restrictions(conn, interaction.guild_id, interaction.user.id)).excluded:
            raise _Refused("Excluded members cannot manage this server's walker.")

    @app_commands.command(name="reset", description="Permanently reset a user's game data in this server")
    async def reset(self, interaction: discord.Interaction, member: discord.User,
                    reason: str, confirm: bool = False):
        await interaction.response.defer(ephemeral=True)
        if not await self.authorize(interaction):
            return
        reason = reason.strip()
        if not reason:
            await self.reply(interaction, "A reason is required.")
            return

        async def authorize(conn):
            await self.check_actor(conn, interaction)
            profile = await profiles.get_profile(conn, interaction.guild_id, member.id)
            if profile is None:
                raise _Refused("That user is not enrolled in this server.")
            async with conn.execute("SELECT count(*) FROM pokemon WHERE profile_id=? AND state='owned'",
                                    (profile["profile_id"],)) as cursor:
                count = (await cursor.fetchone())[0]
            return profile, count

        try:
            if not confirm:
                profile, count = await self.bot.writer.run(authorize)
                await self.reply(interaction,
                    f"Reset {member.display_name} ({member.id}) in this server? This permanently deletes their "
                    f"profile, {count} Pokémon, {profile['stardust']} Stardust, items and progress. "
                    "This cannot be undone. Moderation history, restrictions and opt-out choice remain. "
                    "Use confirm=True to continue.")
                return
            await deletion.run_marker(self.bot.writer, self.bot.settings.marker_log_path, authorize,
                                      reactions=self.bot.reactions, kind="reset", guild_id=str(interaction.guild_id), user_id=str(member.id),
                                      actor_id=str(interaction.user.id), reason=reason, now=time.time())
        except _Refused as error:
            await self.reply(interaction, str(error))
            return
        await self.reply(interaction, f"Game data for user {member.id} in this server was reset.")

    @app_commands.command(name="sharing", description="Enable or disable sharing for this server")
    @app_commands.choices(on=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def sharing(self, interaction: discord.Interaction, on: str, reason: str):
        await interaction.response.defer(ephemeral=True)
        if not await self.authorize(interaction):
            return
        reason = reason.strip()
        if not reason:
            await self.reply(interaction, "A reason is required.")
            return
        if on not in {"on", "off"}:
            await self.reply(interaction, "Choose on or off.")
            return

        async def mutation(conn):
            await self.check_actor(conn, interaction)
            guild_id, now = str(interaction.guild_id), time.time()
            await conn.execute("INSERT OR IGNORE INTO guilds(guild_id,created_at) VALUES (?,?)", (guild_id, now))
            await conn.execute("UPDATE guilds SET sharing=? WHERE guild_id=?", (on == "on", guild_id))
            await conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                               "VALUES (?,?,'guild',?,?,?,?)", (guild_id, str(interaction.user.id), guild_id,
                               "sharing_" + on, reason, now))

        try:
            await self.bot.writer.run(mutation)
        except _Refused as error:
            await self.reply(interaction, str(error))
            return
        await self.reply(interaction, f"Sharing is {on} for this server.")


    @app_commands.command(name="raids", description="Enable or disable World Legendary spawns in this server")
    @app_commands.choices(on=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def raids(self, interaction: discord.Interaction, on: str, reason: str,
                    channel: discord.TextChannel | None = None):
        await interaction.response.defer(ephemeral=True)
        if not await self.authorize(interaction):
            return
        reason = reason.strip()
        if not reason:
            await self.reply(interaction, "A reason is required.")
            return
        if on not in {"on", "off"}:
            await self.reply(interaction, "Choose on or off.")
            return
        if on == "on" and (channel is None or channel.guild.id != interaction.guild_id):
            await self.reply(interaction, "Choose a text channel in this server.")
            return

        async def mutation(conn):
            await self.check_actor(conn, interaction)
            guild_id, now = str(interaction.guild_id), time.time()
            await conn.execute("INSERT OR IGNORE INTO guilds(guild_id,created_at) VALUES (?,?)", (guild_id, now))
            if on == "on":
                await conn.execute("UPDATE guilds SET raids_enabled=1,raid_channel_id=? WHERE guild_id=?",
                                   (str(channel.id), guild_id))
            else:
                await conn.execute("UPDATE guilds SET raids_enabled=0 WHERE guild_id=?", (guild_id,))
            await conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                               "VALUES (?,?,'guild',?,?,?,?)", (guild_id, str(interaction.user.id), guild_id,
                               "raids_" + on, reason, now))

        try:
            await self.bot.writer.run(mutation)
        except _Refused as error:
            await self.reply(interaction, str(error))
            return
        message = f"Raids are {on} for this server."
        if on == "on":
            permissions = channel.permissions_for(interaction.guild.me)
            if not permissions.embed_links or not permissions.send_messages:
                message += " Missing channel permission: EMBED_LINKS and SEND_MESSAGES are required for announcements."
        await self.reply(interaction, message)

    @app_commands.command(name="force-raid", description="Spawn a World Legendary in the raid channel now (24-hour cooldown)")
    async def force_raid(self, interaction: discord.Interaction, reason: str):
        await interaction.response.defer(ephemeral=True)
        if not await self.authorize(interaction):
            return
        reason = reason.strip()
        if not reason:
            await self.reply(interaction, "A reason is required.")
            return

        async def job(conn):
            await self.check_actor(conn, interaction)
            guild_id = str(interaction.guild_id)
            async with conn.execute("SELECT raid_channel_id FROM guilds WHERE guild_id=?", (guild_id,)) as cursor:
                guild = await cursor.fetchone()
            checked = raid_service.checked_channel(interaction.guild, guild_id, guild and guild["raid_channel_id"])
            return await raid_service.force_spawn(conn, guild_id, interaction.user.id, reason, self.bot.walker.clock(),
                                                  self.bot.walker.rng, self.bot.content, checked)

        try:
            result = await self.bot.writer.run(job)
        except _Refused as error:
            await self.reply(interaction, str(error))
            return
        if result["status"] == "cooldown":
            hours, minutes = divmod(math.ceil(result["remaining"] / 60), 60)
            await self.reply(interaction, f"Force raid is on cooldown in this server. Try again in {hours}h {minutes}m.")
            return
        if result["status"] != "spawned":
            await self.reply(interaction, RAID_REFUSALS[result["status"]])
            return
        spawn = result["spawn"]
        await raid_service.announce(self.bot, spawn)
        identity = next(i for i in self.bot.content["identities"] if i["identity_id"] == spawn["identity_id"])
        until = datetime.fromtimestamp(spawn["expires_at"], timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        await self.reply(interaction, f"Spawned {identity['name_en']} in <#{spawn['channel_id']}> until {until}.")

    async def gym_command(self, interaction, action, name=None, reason=None):
        await interaction.response.defer(ephemeral=True)
        if not await self.authorize(interaction):
            return
        if action != "list":
            name, reason = name.strip(), reason.strip()
            if not reason:
                await self.reply(interaction, "A reason is required.")
                return

        async def job(conn):
            await self.check_actor(conn, interaction)
            guild_id, now = str(interaction.guild_id), self.bot.walker.clock()
            await gym_service.settle(conn, now, self.bot.walker.rng, self.bot.content)
            if action == "create":
                await conn.execute("INSERT OR IGNORE INTO guilds(guild_id,created_at) VALUES (?,?)", (guild_id, now))
                result = await gym_service.create(conn, guild_id, name, now)
                if "status" in result:
                    return {"invalid": "Gym names must have 1 to 32 characters.",
                            "duplicate": "That gym name is already reserved in this server.",
                            "full": "This server already has 10 active gyms."}[result["status"]]
            else:
                rows = await gym_service.list_gyms(conn, guild_id)
                if action == "list":
                    return "\n".join(row["name"] for row in rows) or "No gyms configured in this server."
                gym = next((row for row in rows if row["name"] == name), None)
                if gym is None:
                    return "No active gym with that name in this server."
                await gym_service.retire(conn, guild_id, gym["gym_id"], now,
                                         self.bot.walker.rng, self.bot.content)
            await conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                               "VALUES (?,?,'guild',?,?,?,?)", (guild_id, str(interaction.user.id), guild_id,
                               f"gym_{action}:{name}", reason, now))
            return "Gym created." if action == "create" else "Gym removed."

        try:
            text = await self.bot.writer.run(job)
        except _Refused as error:
            text = str(error)
        await self.reply(interaction, text)

    @gyms.command(name="create", description="Create an empty gym in this server")
    async def create_gym(self, interaction: discord.Interaction, name: str, reason: str):
        await self.gym_command(interaction, "create", name, reason)

    @gyms.command(name="remove", description="Retire a gym and return its defender")
    async def remove_gym(self, interaction: discord.Interaction, name: str, reason: str):
        await self.gym_command(interaction, "remove", name, reason)

    @gyms.command(name="list", description="List this server's active gyms")
    async def list_gyms(self, interaction: discord.Interaction):
        await self.gym_command(interaction, "list")
