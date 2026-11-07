"""C5 private account controls over the D28 serialized deletion service."""

import time

import discord
from discord import app_commands

from pokewalker.services import deletion, profiles


class _Excluded(ValueError):
    pass


def load_privacy(settings):
    if settings.privacy_path is None:
        raise ValueError("POKEWALKER_PRIVACY_PATH is required")
    try:
        text = settings.privacy_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("Cannot read the privacy text at POKEWALKER_PRIVACY_PATH") from error
    if not text.strip():
        raise ValueError("The privacy text must not be blank")
    return text


class WalkerAccount(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name="walker-account", description="Privacy and account controls", guild_only=True)
        self.bot = bot

    async def reply(self, interaction, text):
        parts = []
        while len(text) > 2000:
            cut = text.rfind("\n", 0, 2000) + 1 or 2000  # split after a line break when one fits
            parts.append(text[:cut])
            text = text[cut:]
        parts.append(text)
        await interaction.edit_original_response(content=parts[0], allowed_mentions=discord.AllowedMentions.none())
        for part in parts[1:]:
            await interaction.followup.send(content=part, ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())

    async def begin(self, interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.guild_id is None:
            await self.reply(interaction, "Use /walker-account in a server.")
            return False
        return True

    @app_commands.command(name="privacy", description="Read the owner's privacy information")
    async def privacy(self, interaction: discord.Interaction):
        if await self.begin(interaction):
            await self.reply(interaction, self.bot.privacy_text)

    async def delete(self, interaction, kind, confirm):
        if not await self.begin(interaction):
            return
        if not confirm:
            await self.reply(interaction,
                             "This permanently deletes your profile, Pokémon, items and progress in this server. "
                             "Your moderation history, active restrictions and the opt-out marker are retained. "
                             + ("Opt-out also stops tracking until /walker-account opt-in. " if kind == "opt_out" else "")
                             + "Use confirm=True to continue.")
            return
        await deletion.run_marker(self.bot.writer, self.bot.settings.marker_log_path,
                                  reactions=self.bot.reactions, kind=kind, guild_id=str(interaction.guild_id),
                                  user_id=str(interaction.user.id), now=time.time())
        await self.reply(interaction, "Your game data in this server was deleted. " + (
            "Tracking is stopped until /walker-account opt-in." if kind == "opt_out"
            else "Moderation history, restrictions and your opt-out choice are retained."))

    @app_commands.command(name="delete-data", description="Delete your game data in this server")
    async def delete_data(self, interaction: discord.Interaction, confirm: bool = False):
        await self.delete(interaction, "delete", confirm)

    @app_commands.command(name="opt-out", description="Delete your game data and stop tracking in this server")
    async def opt_out(self, interaction: discord.Interaction, confirm: bool = False):
        await self.delete(interaction, "opt_out", confirm)

    @app_commands.command(name="opt-in", description="Allow fresh enrollment in this server")
    async def opt_in(self, interaction: discord.Interaction):
        if not await self.begin(interaction):
            return

        async def authorize(conn):
            if (await profiles.restrictions(conn, interaction.guild_id, interaction.user.id)).excluded:
                raise _Excluded("Excluded members cannot opt in here.")

        try:
            await deletion.run_marker(self.bot.writer, self.bot.settings.marker_log_path, authorize,
                                      kind="opt_in", guild_id=str(interaction.guild_id),
                                      user_id=str(interaction.user.id), now=time.time())
        except _Excluded as error:
            await self.reply(interaction, str(error))
            return
        await self.reply(interaction, "Opted in. Run /walker to enroll again if you have no profile.")
