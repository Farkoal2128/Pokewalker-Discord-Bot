"""EX-Raid catalog picker and owner-bound send manager (C5)."""

import asyncio
from datetime import datetime, timezone
from difflib import get_close_matches
import unicodedata
from types import SimpleNamespace
from uuid import uuid4

import discord

from pokewalker.config import snowflake
from pokewalker.bot import admin_gift
from pokewalker.services import raids

EXPIRED = 'This EX-Raid draft expired. Run /admin ex-raid again.'
SKIP_LABELS = (('raids_off', 'Raids off'), ('no_channel', 'No raid channel'),
               ('no_permission', 'No permission or bot not in server'),
               ('channel_changed', 'Raid channel changed'), ('active', 'EX-Raid already live'))


def attach(admin):
    admin.ex_raid_drafts = {}


def discard(draft):
    if draft.state == 'sending':
        draft.discard_pending = True
        return
    draft.state = 'discarded'
    draft.__dict__.pop('result', None)
    if draft.admin.ex_raid_drafts.get(draft.draft_id) is draft:
        draft.admin.ex_raid_drafts.pop(draft.draft_id)
    draft.view.stop()
    draft.guild_id = None


async def target_counts(admin, guild_id):
    bot = admin.bot
    return await bot.writer.run(lambda conn: raids.ex_target(
        conn, guild_id, bot.walker.clock(), lambda g, c: checked_channel(bot, g, c)))


def checked_channel(bot, guild_id, channel_id):
    guild = bot.get_guild(int(guild_id))
    return None if guild is None else raids.checked_channel(guild, guild_id, channel_id)


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
        guild_id = None if server_id is None else snowflake(server_id)
    except ValueError:
        await admin.reply(interaction, 'Server ID must be a Discord ID.')
        return
    counts = None if guild_id is None else await target_counts(admin, guild_id)
    if counts is not None and counts['status'] == 'unknown_server':
        await admin.reply(interaction, f'The bot has no data for server {guild_id}.')
        return
    draft = SimpleNamespace(admin=admin, draft_id=uuid4().hex, owner_id=interaction.user.id,
        identity=identity, locks=dict(shiny=shiny, level=level, iv_attack=iv_attack,
            iv_defense=iv_defense, iv_stamina=iv_stamina), hours=1 if duration is None else duration,
        guild_id=guild_id, all_servers=False, deadline=admin.bot.clock() + 900, revision=0,
        send_id=uuid4().hex, state='editing', discard_pending=False)
    draft.view = RaidView(draft)
    admin.ex_raid_drafts[draft.draft_id] = draft
    await draft.view.preview(interaction, counts)


class RaidView(admin_gift.OwnerView):
    def __init__(self, draft):
        self.draft = draft
        super().__init__(draft.admin, draft.owner_id, draft.deadline, EXPIRED)

    async def on_timeout(self):
        discard(self.draft)

    async def editable(self, interaction):
        draft = self.draft
        if (draft.admin.ex_raid_drafts.get(draft.draft_id) is not draft
                or draft.state == 'discarded' or draft.admin.bot.clock() >= draft.deadline):
            discard(draft)
            await self.refuse(interaction, EXPIRED)
            return False
        if draft.state == 'sent':
            await self.receipt(interaction)
            return False
        if draft.state != 'editing':
            await self.refuse(interaction, 'This EX-Raid is being sent.')
            return False
        return True

    async def interaction_check(self, interaction):
        if not await super().interaction_check(interaction):
            return False
        return await self.editable(interaction)

    async def action(self, interaction, action):
        if not await self.editable(interaction):
            return
        draft = self.draft
        if action == 'Cancel':
            discard(draft)
            await interaction.edit_original_response(content='EX-Raid draft cancelled.',
                view=None, embed=None, allowed_mentions=discord.AllowedMentions.none())
        elif action == 'All servers' and draft.guild_id is None and not draft.all_servers:
            draft.all_servers = True
            draft.revision += 1
            await self.preview(interaction)

    async def preview(self, interaction, counts=None):
        if not await self.editable(interaction):
            return
        draft = self.draft
        if counts is None and (draft.guild_id is not None or draft.all_servers):
            counts = await target_counts(draft.admin, draft.guild_id)
            if not await self.editable(interaction):
                return
        if counts is not None and counts['status'] != 'ok':
            await self.refuse(interaction, 'The EX-Raid target is no longer available.')
            return
        self.clear_items()
        for label in (['All servers'] if draft.guild_id is None and not draft.all_servers else []) + ['Cancel']:
            item = discord.ui.Button(label=label, row=0)
            async def callback(interaction, action=label):
                await self.action(interaction, action)
            item.callback = callback
            self.add_item(item)
        revision = draft.revision
        confirm = discord.ui.Button(label='Confirm', row=0,
            custom_id=f'ex_raid_confirm:{draft.draft_id}:{revision}',
            disabled=draft.guild_id is None and not draft.all_servers)
        async def confirm_callback(interaction):
            await self.confirm(interaction, revision)
        confirm.callback = confirm_callback
        self.add_item(confirm)
        identity = draft.identity
        title = f"EX-Raid: #{identity['species_id']:03d} {identity['name_en']}"
        lines = [f'Send ID: {draft.send_id}', title]
        for name, key in (('Shiny', 'shiny'), ('Level', 'level'), ('Attack IV', 'iv_attack'),
                          ('Defense IV', 'iv_defense'), ('Stamina IV', 'iv_stamina')):
            value = draft.locks[key]
            lines.append(f"{name}: {value if value is not None else 'rolled per player'}")
        target = (f'server {draft.guild_id}' if draft.guild_id is not None else
                  'all servers' if draft.all_servers else 'none chosen: press All servers')
        lines.extend((f'Duration: {draft.hours} hour' + ('s' if draft.hours != 1 else ''), f'Target: {target}'))
        if counts is not None:
            lines.extend(('Counts (provisional)', f"Targeted servers: {counts['servers']}",
                          f"Servers that will get it: {counts['spawning']}"))
            lines.extend(f"{label}: {counts['skipped'].get(reason, 0)}" for reason, label in SKIP_LABELS)
            if not counts['spawning']:
                lines.append('Nothing would spawn.')
        embed = discord.Embed(title=title)
        sprite = identity['sprites']['shiny' if draft.locks['shiny'] else 'normal']
        if sprite is not None:
            embed.set_image(url=sprite)
        await interaction.edit_original_response(content='\n'.join(lines), embed=embed,
            view=self, allowed_mentions=discord.AllowedMentions.none())

    async def receipt(self, interaction, snapshot=None):
        result = snapshot if snapshot is not None else self.draft.result
        identity = self.draft.identity
        lines = [f"Send ID: {result['ex_raid_id']}",
                 f"EX-Raid: #{identity['species_id']:03d} {identity['name_en']}"]
        for name, key in (('Shiny', 'shiny'), ('Level', 'level'), ('Attack IV', 'iv_attack'),
                          ('Defense IV', 'iv_defense'), ('Stamina IV', 'iv_stamina')):
            value = result[key]
            lines.append(f"{name}: {value if value is not None else 'rolled per player'}")
        hours, guild_id = result['hours'], result['guild_id']
        end = datetime.fromtimestamp(result['created_at'] + hours * 3600, timezone.utc).isoformat()
        lines.extend((f'Duration: {hours} hour' + ('s' if hours != 1 else ''),
            f'Target: {"all servers" if guild_id is None else f"server {guild_id}"}',
            f'End UTC: {end}', 'Counts (committed)', f"Targeted servers: {result['servers']}",
            f"Servers that got it: {result['spawned']}"))
        lines.extend(f"{label}: {result['skipped'].get(reason, 0)}" for reason, label in SKIP_LABELS)
        await interaction.edit_original_response(content='\n'.join(lines), view=None, embed=None,
            allowed_mentions=discord.AllowedMentions.none())

    async def confirm(self, interaction, revision):
        if not await self.editable(interaction):
            return
        draft, bot = self.draft, self.draft.admin.bot
        if revision != draft.revision or (draft.guild_id is None and not draft.all_servers):
            await self.refuse(interaction, 'This preview is out of date. Nothing was sent.')
            return
        snapshot = [None]
        def live():
            return (draft.admin.ex_raid_drafts.get(draft.draft_id) is draft
                    and draft.state == 'sending' and not draft.discard_pending
                    and bot.clock() < draft.deadline)
        async def job(conn):
            if not live():
                return {'status': 'expired'}
            result = await raids.ex_commit(conn, send_id=draft.send_id, owner_id=draft.owner_id,
                admin_guild_id=bot.settings.admin_guild_id, identity_id=draft.identity['identity_id'],
                locks=draft.locks, hours=draft.hours, guild_id=draft.guild_id,
                now=bot.walker.clock(), content=bot.content,
                checked=lambda g, c: checked_channel(bot, g, c))
            if not live():
                raise admin_gift._Expired
            return result
        def record(result):
            snapshot[0] = result
            if result['status'] == 'sent':
                draft.state, draft.result = 'sent', result
                if not result['replayed']:
                    bot.announce_ex_raid(result['ex_raid_id'])
        async def settle():
            try:
                result = await bot.writer.run(job, after_commit=record)
                if result['status'] == 'expired':
                    draft.discard_pending = True
            except admin_gift._Expired:
                draft.discard_pending = True
            except (Exception, asyncio.CancelledError):
                pass
            finally:
                if draft.state == 'sending':
                    draft.state = 'editing'
                if draft.discard_pending or bot.clock() >= draft.deadline:
                    discard(draft)
        draft.state = 'sending'
        draft.task = asyncio.create_task(settle())
        await asyncio.shield(draft.task)
        result = snapshot[0]
        if result is not None and result['status'] == 'sent':
            await self.receipt(interaction, result)
        elif result is not None and result['status'] == 'nothing':
            text = 'Nothing was sent: no server could get this EX-Raid.'
            text += '\n' + '\n'.join(f"{label}: {result['skipped'].get(reason, 0)}"
                                     for reason, label in SKIP_LABELS)
            await self.refuse(interaction, text)
        else:
            await self.refuse(interaction, 'Nothing was sent.')
