"""EX-Raid catalog picker and private, read-only submit preview (C5)."""

from difflib import get_close_matches
import unicodedata

import discord

from pokewalker.config import snowflake


def _fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(c))


def suggest(content, text):
    identities = content['identities']
    query = _fold(text)
    names = [_fold(i['name_en']) for i in identities]
    ranked = [i for i in identities if str(i['species_id']) == query.lstrip('0')]
    ranked.extend(i for i, name in zip(identities, names) if name.startswith(query))
    ranked.extend(i for i, name in zip(identities, names) if query in name)
    close = get_close_matches(query, names, n=25)
    by_name = dict(zip(names, identities))
    ranked.extend(by_name[name] for name in close)
    choices, seen = [], set()
    for identity in ranked:
        value = identity['identity_id']
        if value not in seen:
            choices.append((f"#{identity['species_id']:03d} {identity['name_en']}", value))
            seen.add(value)
        if len(choices) == 25:
            break
    return choices


async def open(admin, interaction, pokemon, server_id=None, shiny=None, level=None,
               iv_attack=None, iv_defense=None, iv_stamina=None, duration=None):
    identity = next((i for i in admin.bot.content['identities']
                     if i['identity_id'] == pokemon), None)
    if identity is None:
        await admin.reply(interaction, 'Pick a Pokémon from the list.')
        return
    bounds = ((level, 1, 40), (iv_attack, 0, 15), (iv_defense, 0, 15),
              (iv_stamina, 0, 15), (duration, 1, 24))
    if any(value is not None and (type(value) is not int or not low <= value <= high)
           for value, low, high in bounds):
        await admin.reply(interaction,
            'Level must be 1-40, each IV 0-15 and the duration 1-24 hours.')
        return
    try:
        target = 'none chosen' if server_id is None else snowflake(server_id)
    except ValueError:
        await admin.reply(interaction, 'Server ID must be a Discord ID.')
        return
    lines = [f"EX-Raid: #{identity['species_id']:03d} {identity['name_en']}"]
    for name, value in (('Shiny', shiny), ('Level', level), ('Attack IV', iv_attack),
                        ('Defense IV', iv_defense), ('Stamina IV', iv_stamina)):
        lines.append(f"{name}: {value if value is not None else 'rolled per player'}")
    hours = 1 if duration is None else duration
    lines.extend((f'Duration: {hours} hour' + ('s' if hours != 1 else ''), f'Target: {target}'))
    embed = discord.Embed(title=f"EX-Raid: #{identity['species_id']:03d} {identity['name_en']}")
    sprite = identity['sprites']['shiny' if shiny else 'normal']
    if sprite is not None:
        embed.set_image(url=sprite)
    await interaction.edit_original_response(content='\n'.join(lines), embed=embed,
        allowed_mentions=discord.AllowedMentions.none())
