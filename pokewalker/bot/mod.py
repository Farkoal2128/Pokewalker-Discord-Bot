"""C5 private member moderation over existing C3 restrictions and audit."""

from datetime import datetime, timezone
import time

import discord
from discord import app_commands

from pokewalker.services import gyms, profiles


class _Refused(ValueError):
    pass


class WalkerMod(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name="walker-mod", description="Moderate this server's walker",
                         guild_only=True, default_permissions=discord.Permissions(moderate_members=True))
        self.bot = bot

    async def reply(self, interaction, text):
        await interaction.edit_original_response(content=text[:2000], allowed_mentions=discord.AllowedMentions.none())
        for start in range(2000, len(text), 2000):
            await interaction.followup.send(content=text[start:start + 2000], ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())

    def check_permission(self, interaction):
        if interaction.guild_id is None or not interaction.user.guild_permissions.moderate_members:
            raise _Refused("Moderate Members permission in a server is required.")

    async def begin(self, interaction, member=None):
        await interaction.response.defer(ephemeral=True)
        try:
            self.check_permission(interaction)
            if member is not None and member.guild.id != interaction.guild_id:
                raise _Refused("Choose a member in this server.")
        except _Refused as error:
            await self.reply(interaction, str(error))
            return False
        return True

    async def authorize(self, conn, interaction):
        self.check_permission(interaction)
        if (await profiles.restrictions(conn, interaction.guild_id, interaction.user.id)).excluded:
            raise _Refused("You are excluded and cannot use moderation commands.")

    async def change(self, interaction, member, reason, action, duration=None):
        if not await self.begin(interaction, member):
            return
        reason = reason.strip()
        if not reason:
            await self.reply(interaction, "A reason is required.")
            return

        async def mutation(conn):
            await self.authorize(conn, interaction)
            guild, user, now = str(interaction.guild_id), str(member.id), time.time()
            await conn.execute("INSERT OR IGNORE INTO guilds(guild_id,created_at) VALUES (?,?)", (guild, now))
            await conn.execute("INSERT OR IGNORE INTO restrictions(guild_id,user_id) VALUES (?,?)", (guild, user))
            if action in ("pause", "resume"):
                seconds = {"indefinite": None, "1h": 3600, "24h": 86400, "7d": 604800}[
                    duration.value if duration is not None else "indefinite"]
                until = now + seconds if action == "pause" and seconds is not None else None
                await conn.execute("UPDATE restrictions SET paused=?,paused_until=? WHERE guild_id=? AND user_id=?",
                                   (action == "pause", until, guild, user))
            elif action in ("exclude", "include"):
                await conn.execute("UPDATE restrictions SET excluded=? WHERE guild_id=? AND user_id=?",
                                   (action == "exclude", guild, user))
            else:
                await conn.execute("UPDATE restrictions SET share_banned=? WHERE guild_id=? AND user_id=?",
                                   (action == "share-ban", guild, user))
            if action == "exclude":
                for deployment in await conn.execute_fetchall("SELECT deployment_id FROM gym_deployments WHERE guild_id=? AND profile_id=(SELECT profile_id FROM profiles WHERE guild_id=? AND user_id=?) AND ended_at IS NULL", (guild, guild, user)):
                    await gyms.end_deployment(conn, guild, deployment["deployment_id"], "excluded", self.bot.walker.clock(), self.bot.walker.rng, self.bot.content)
            await conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                               "VALUES (?,?,'user',?,?,?,?)",
                               (guild, str(interaction.user.id), user, action, reason, now))

        try:
            await self.bot.writer.run(mutation)
        except _Refused as error:
            await self.reply(interaction, str(error))
            return
        await self.reply(interaction, f"{action} applied to user {member.id}.")

    @app_commands.command(name="pause", description="Pause earning in this server")
    @app_commands.choices(duration=[app_commands.Choice(name=name, value=value) for name, value in
        (("Indefinitely", "indefinite"), ("1 hour", "1h"), ("24 hours", "24h"), ("7 days", "7d"))])
    async def pause(self, interaction: discord.Interaction, member: discord.Member, reason: str,
                    duration: app_commands.Choice[str] = None):
        await self.change(interaction, member, reason, "pause", duration)

    @app_commands.command(name="resume", description="Lift a member's earning pause")
    async def resume(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await self.change(interaction, member, reason, "resume")

    @app_commands.command(name="exclude", description="Block a member from this server's game")
    async def exclude(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await self.change(interaction, member, reason, "exclude")

    @app_commands.command(name="include", description="Reverse a member's exclusion")
    async def include(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await self.change(interaction, member, reason, "include")

    @app_commands.command(name="share-ban", description="Disable a member's Share buttons")
    async def share_ban(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await self.change(interaction, member, reason, "share-ban")

    @app_commands.command(name="share-unban", description="Restore a member's Share buttons")
    async def share_unban(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await self.change(interaction, member, reason, "share-unban")

    @app_commands.command(name="gym-recall", description="Return a gym defender and pay completed hours")
    async def gym_recall(self, interaction: discord.Interaction, gym: str, reason: str):
        if not await self.begin(interaction):
            return
        reason = reason.strip()
        if not reason:
            await self.reply(interaction, "A reason is required.")
            return

        async def mutation(conn):
            await self.authorize(conn, interaction)
            guild, gym_now = str(interaction.guild_id), self.bot.walker.clock()
            await gyms.settle(conn, gym_now, self.bot.walker.rng, self.bot.content)
            selected = next((row for row in await gyms.list_gyms(conn, guild) if row["name"] == gym), None)
            if selected is None:
                return "No such gym"
            async with conn.execute("SELECT d.deployment_id,p.user_id FROM gym_deployments d "
                                    "JOIN profiles p ON p.profile_id=d.profile_id AND p.guild_id=d.guild_id "
                                    "WHERE d.guild_id=? AND d.gym_id=? AND d.ended_at IS NULL",
                                    (guild, selected["gym_id"])) as cursor:
                deployment = await cursor.fetchone()
            if deployment is None:
                return "Gym is empty"
            await gyms.end_deployment(conn, guild, deployment["deployment_id"], "mod_recall", gym_now,
                                      self.bot.walker.rng, self.bot.content)
            await conn.execute("INSERT INTO mod_audit(guild_id,actor_id,target_kind,target_id,action,reason,created_at) "
                               "VALUES (?,?,'user',?,'gym_recall',?,?)",
                               (guild, str(interaction.user.id), deployment["user_id"], reason, time.time()))
            return f"Recalled {selected['name']} holder {deployment['user_id']}."

        try:
            text = await self.bot.writer.run(mutation)
        except _Refused as error:
            text = str(error)
        await self.reply(interaction, text)

    async def audit(self, conn, guild_id, member, limit):
        query = "SELECT * FROM mod_audit WHERE guild_id=?"
        args = [str(guild_id)]
        if member is not None:
            query += " AND target_kind='user' AND target_id=?"
            args.append(str(member.id))
        async with conn.execute(query + " ORDER BY created_at DESC,audit_id DESC LIMIT ?", (*args, limit)) as cursor:
            rows = await cursor.fetchall()
        lines = []
        for row in rows:
            target = f"<#{row['target_id']}>" if row["target_kind"] == "channel" else f"{'server' if row['target_kind'] == 'guild' else 'user'}:{row['target_id']}"
            lines.append(f"{row['created_at']:.3f} actor={row['actor_id']} target={target} "
                         f"{row['action']}: {row['reason']}")
        return lines or ["No moderation actions."]

    @app_commands.command(name="status", description="Show a member's game and moderation summary")
    async def status(self, interaction: discord.Interaction, member: discord.Member):
        if not await self.begin(interaction, member):
            return

        async def read(conn):
            await self.authorize(conn, interaction)
            profile = await profiles.get_profile(conn, interaction.guild_id, member.id)
            flags = await profiles.restrictions(conn, interaction.guild_id, member.id)
            pid, now = profile["profile_id"] if profile else None, time.time()
            async with conn.execute("SELECT coalesce(sum(CASE WHEN created_at>=? AND created_at<=? THEN awarded_c END),0),"
                                    "coalesce(sum(awarded_c),0),"
                                    "coalesce(sum(CASE WHEN created_at>=? AND created_at<=? AND "
                                    "reason IN ('minimum','cooldown','minute_cap','duplicate','credited') "
                                    "THEN discarded_words END),0) "
                                    "FROM step_events WHERE profile_id=?", (now - 3600, now, now - 3600, now, pid)) as cursor:
                hour, total, discarded = await cursor.fetchone()
            async with conn.execute("SELECT count(*) FROM catch_attempts a JOIN encounters e USING(encounter_id) "
                                    "WHERE e.profile_id=? AND a.success=1", (pid,)) as cursor:
                catches = (await cursor.fetchone())[0]
            gym_now = self.bot.walker.clock()
            await gyms.settle(conn, gym_now, self.bot.walker.rng, self.bot.content)
            async with conn.execute("SELECT g.name,d.deployed_at FROM gym_deployments d "
                                    "JOIN gyms g ON g.gym_id=d.gym_id AND g.guild_id=d.guild_id "
                                    "WHERE d.guild_id=? AND d.profile_id=? AND d.ended_at IS NULL",
                                    (str(interaction.guild_id), pid)) as cursor:
                deployment = await cursor.fetchone()
            held = "none"
            if deployment is not None:
                since = datetime.fromtimestamp(deployment["deployed_at"], timezone.utc).isoformat()
                hours = max(0, int((gym_now - deployment["deployed_at"]) // 3600))
                held = f"{deployment['name']} since {since} ({hours} hours)"
            until = flags.paused_until.isoformat() if flags.paused_until else "indefinite"
            lines = [f"User: {member.id}", f"Enrolled: {profile is not None}",
                     f"Paused: {flags.paused}" + (f" ({until})" if flags.paused else ""),
                     f"Excluded: {flags.excluded}", f"Share-banned: {flags.share_banned}",
                     f"Steps last hour: {hour / 100:.2f}", f"Steps total: {total / 100:.2f}",
                     f"Base steps discarded by anti-farming last hour: {discarded}",
                     f"Queue size: {await profiles.queue_size(conn, pid)}",
                     f"Catches: {catches}", f"Holds gym: {held}", "Recent moderation actions:"]
            return "\n".join(lines + await self.audit(conn, interaction.guild_id, member, 5))

        try:
            text = await self.bot.writer.run(read)
        except _Refused as error:
            text = str(error)
        await self.reply(interaction, text)

    @app_commands.command(name="log", description="Show the last 25 moderation actions")
    async def log(self, interaction: discord.Interaction, member: discord.Member = None):
        if not await self.begin(interaction, member):
            return

        async def read(conn):
            await self.authorize(conn, interaction)
            return "\n".join(await self.audit(conn, interaction.guild_id, member, 25))

        try:
            text = await self.bot.writer.run(read)
        except _Refused as error:
            text = str(error)
        await self.reply(interaction, text)
