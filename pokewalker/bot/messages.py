"""Thin content-free Gateway adapter; see contracts/step-rules.md M1.5."""

from pokewalker.domain.steps import eligible_words
from pokewalker.services.profiles import channel_policy, get_profile
from pokewalker.services.stepping import credit_message


async def on_message(bot, message):
    counts = getattr(bot, "message_counts", {"received": 0, "credited": 0})
    counts["received"] += 1
    if message.author.bot or message.webhook_id is not None or message.guild is None:
        return
    guild_id, user_id = message.guild.id, message.author.id
    channel_id, parent_id = message.channel.id, getattr(message.channel, "parent_id", None)
    message_id, created_at = message.id, getattr(message, "created_at", None)
    words = eligible_words(message.content)
    del message

    async def credit(conn):
        async with conn.execute("SELECT enabled FROM guilds WHERE guild_id=?", (str(guild_id),)) as cursor:
            guild = await cursor.fetchone()
        if guild is None or not guild["enabled"]:
            return None
        policy = await channel_policy(conn, guild_id, channel_id, parent_id)
        if policy is None or not policy["count_steps"]:
            return None
        profile = await get_profile(conn, guild_id, user_id)
        if profile is None:
            return None
        async with conn.execute("SELECT 1 FROM step_events WHERE message_id=?", (str(message_id),)) as cursor:
            existed = await cursor.fetchone()
        encounter = await credit_message(conn, profile, words, created_at, message_id, channel_id, content=bot.content)
        async with conn.execute("SELECT accepted_words FROM step_events WHERE message_id=?", (str(message_id),)) as cursor:
            event = await cursor.fetchone()
        return encounter, bool(not existed and event and event["accepted_words"] > 0)

    result = await bot.writer.run(credit, after_commit=lambda result:
        counts.update(credited=counts["credited"] + bool(result and result[1])))
    encounter_id, _ = result or (None, False)
    if encounter_id is not None:
        await bot.reactions.reconcile_reaction(encounter_id)
