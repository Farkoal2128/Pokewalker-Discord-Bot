"""D12/D22/D29 private check-in command; acknowledge before writer waits."""

import math
import random
import time

import discord
from discord import app_commands

from pokewalker.services import items


def command(bot):
    @app_commands.command(name='checkin', description='Collect your hourly Poké Ball, common item and wild encounter')
    @app_commands.guild_only()
    async def checkin(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.guild_id is None:
            text = 'Use /checkin in a server.'
        else:
            result = await bot.writer.run(lambda conn: items.checkin(
                conn, interaction.guild_id, interaction.user.id, time.time(), random.SystemRandom(),
                content=bot.content))
            status = result['status']
            if status == 'granted':
                names = {'poke_ball': 'Poké Ball', 'great_ball': 'Great Ball',
                         'razz_berry': 'Razz Berry', 'pinap_berry': 'Pinap Berry', 'vitamin': 'Vitamin'}
                lines = []
                for entry in result['outcomes']:
                    line = f"{names[entry['item']]} ×{entry['quantity']}"
                    if entry['outcome'] == 'overflow':
                        line += ' — bag full, +10 Stardust'
                    lines.append(line)
                if result.get('encounter') == 'queued':
                    lines.append('+1 wild encounter queued — open /walker.')
                elif result.get('encounter') == 'queue_full':
                    lines.append('Queue is full — no encounter added.')
                text = '\n'.join(lines)
            elif status == 'too_early':
                text = f"Check-in available in {math.ceil(result['seconds_left'])} seconds."
            elif status == 'paused':
                text = 'Check-ins are paused ' + (f"until {result['until']}." if result['until'] else 'indefinitely.')
            elif status == 'excluded':
                text = 'Excluded members cannot check in.'
            else:
                text = 'Open /walker to enroll before checking in.'
        await interaction.edit_original_response(content=text, allowed_mentions=discord.AllowedMentions.none())
    return checkin
