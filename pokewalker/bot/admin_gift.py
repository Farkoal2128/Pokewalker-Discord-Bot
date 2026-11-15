"""Owner-bound, temporary EX-Gift package editor (C5)."""

import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import discord

from pokewalker.config import snowflake
from pokewalker.services import deletion, ex_gift

EXPIRED = 'This gift draft expired. Run /admin gift again.'
CATEGORIES = ('Balls', 'Berries', 'Rare', 'IV items', 'Arena', 'Evolution')


class _Expired(Exception):
    pass


class Drafts(dict):
    def profile_deleted(self, guild_id, user_id):
        for draft in list(self.values()):
            if (str(draft.guild_id), str(draft.user_id)) == (str(guild_id), str(user_id)):
                discard(draft)


def attach(admin):
    admin.gift_drafts, admin.gift_callbacks = Drafts(), {}
    deletion.listen(admin.gift_drafts)


def discard(draft):
    if draft.state == 'sending':
        draft.discard_pending = True
        return
    draft.state = 'discarded'
    draft.__dict__.pop('result', None)
    if draft.admin.gift_drafts.get(draft.draft_id) is draft:
        draft.admin.gift_drafts.pop(draft.draft_id)
    draft.view.stop()
    draft.guild_id = draft.user_id = None


async def show(interaction, text, view=None):
    await interaction.edit_original_response(content=text[:2000], view=view,
        allowed_mentions=discord.AllowedMentions.none())


async def open(admin, interaction, scope, server_id, user_id):
    if ((scope == 'all' and (server_id is not None or user_id is not None))
            or (scope == 'server' and server_id is None) or scope not in ('all', 'server')):
        await show(interaction, 'Invalid scope and ID combination.')
        return
    try:
        guild = None if server_id is None else snowflake(server_id)
        user = None if user_id is None else snowflake(user_id)
    except ValueError:
        await show(interaction, 'Server and user IDs must be Discord IDs.')
        return
    scope = 'user' if user is not None else scope
    counts = await admin.bot.writer.run(lambda conn: ex_gift.target(conn, scope, guild, user))
    if counts['status'] == 'unknown_server':
        await show(interaction, f'The bot has no data for server {guild}.')
        return
    if counts['status'] == 'no_profile':
        await show(interaction, f'User {user} has no profile in server {guild}.')
        return
    draft = SimpleNamespace(admin=admin, draft_id=uuid4().hex, owner_id=interaction.user.id,
        scope=scope, guild_id=guild, user_id=user, deadline=admin.bot.clock() + 900,
        slots=[], revision=0, send_id=uuid4().hex, category='Balls', ex=False,
        page=0, picked=None, state='editing', discard_pending=False)
    draft.view = GiftView(draft)
    admin.gift_drafts[draft.draft_id] = draft
    await draft.view.editor(interaction)


class GiftView(discord.ui.View):
    def __init__(self, draft):
        self.draft = draft
        super().__init__(timeout=max(0, draft.deadline - draft.admin.bot.clock()))

    async def on_timeout(self):
        discard(self.draft)

    async def refuse(self, interaction, text):
        await interaction.followup.send(content=text, ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())

    async def interaction_check(self, interaction):
        await interaction.response.defer(ephemeral=True)
        draft, admin = self.draft, self.draft.admin
        if (interaction.user.id != draft.owner_id
                or interaction.user.id not in admin.bot.settings.owner_ids
                or interaction.guild_id != admin.bot.settings.admin_guild_id):
            await self.refuse(interaction, 'Only the configured owner in the admin guild may use this draft.')
            return False
        if admin.bot.clock() >= draft.deadline:
            discard(draft)
            await self.refuse(interaction, EXPIRED)
            return False
        confirm = interaction.data.get('custom_id', '').startswith('gift_confirm:')
        wait = admin.throttled(admin.requests if confirm else admin.gift_callbacks,
                               draft.owner_id, 5 if confirm else 30)
        if wait is not None:
            await self.refuse(interaction, f'Slow down, try again in {wait} s.')
            return False
        if await admin.bot.writer.run(lambda conn: admin.excluded(conn, interaction)):
            await self.refuse(interaction, 'Excluded owners cannot use admin commands.')
            return False
        self.timeout = max(0, draft.deadline - admin.bot.clock())
        return True

    async def editable(self, interaction):
        draft = self.draft
        if (draft.admin.gift_drafts.get(draft.draft_id) is not draft
                or draft.state == 'discarded' or draft.admin.bot.clock() >= draft.deadline):
            discard(draft)
            await self.refuse(interaction, EXPIRED)
            return False
        if draft.state == 'sent':
            await self.receipt(interaction)
            return False
        if draft.state != 'editing':
            await self.refuse(interaction, 'This gift is being sent.')
            return False
        return True

    def button(self, label, action, row, disabled=False):
        revision = self.draft.revision
        options = {'custom_id': f'gift_confirm:{self.draft.draft_id}:{revision}'} if action == 'Confirm' else {}
        item = discord.ui.Button(label=label, row=row, disabled=disabled, **options)
        async def callback(interaction):
            if action == 'Confirm':
                await self.confirm(interaction, revision)
            else:
                await self.action(interaction, action)
        item.callback = callback
        self.add_item(item)

    def select(self, placeholder, options, row, action, disabled=False):
        item = discord.ui.Select(placeholder=placeholder, options=options, row=row, disabled=disabled)
        async def callback(interaction):
            await self.action(interaction, action, item.values[0] if len(item.values) == 1 else None)
        item.callback = callback
        self.add_item(item)

    async def editor(self, interaction):
        if not await self.editable(interaction):
            return
        draft, content = self.draft, self.draft.admin.bot.content
        self.timeout = max(0, draft.deadline - draft.admin.bot.clock())
        self.clear_items()
        for n, category in enumerate(CATEGORIES):
            self.button(category, category, 0 if n < 5 else 1)
        keys, pages = ex_gift.page(content, draft.category, draft.ex, draft.page)
        self.button('EX', 'EX', 1)
        self.button('Prev', 'Prev', 1, draft.page == 0)
        self.button('Next', 'Next', 1, draft.page + 1 >= pages)
        self.select('Choose item', [discord.SelectOption(label=ex_gift.label(key, content), value=key)
                    for key in keys], 2, 'pick', len(draft.slots) == 10)
        if draft.slots:
            self.select('Choose slot', [discord.SelectOption(
                label=f'{n + 1}. {ex_gift.label(key, content)}', value=str(n))
                for n, key in enumerate(draft.slots)], 3, 'slot')
        for label, disabled in (('Remove', draft.picked is None), ('Clear', False),
                                ('Preview', not draft.slots), ('Cancel', False)):
            self.button(label, label, 4, disabled)
        await show(interaction, f'EX-Gift manager · {len(draft.slots)}/10 slots · '
                   f'{"EX" if draft.ex else draft.category} · page {draft.page + 1}/{pages}', self)

    async def action(self, interaction, action, value=None):
        if not await self.editable(interaction):
            return
        draft, content = self.draft, self.draft.admin.bot.content
        changed = False
        if action == 'Cancel':
            discard(draft)
            await show(interaction, 'Gift draft cancelled.')
            return
        if action == 'Preview':
            if not draft.slots:
                await self.refuse(interaction, 'Choose at least one item first.')
                return
            counts = await draft.admin.bot.writer.run(lambda conn: ex_gift.target(
                conn, draft.scope, draft.guild_id, draft.user_id))
            if not await self.editable(interaction):
                return
            if counts['status'] != 'ok':
                await self.refuse(interaction, 'The gift target is no longer available.')
                return
            self.clear_items()
            self.button('Confirm', 'Confirm', 0)
            self.button('Edit', 'Edit', 0)
            self.button('Cancel', 'Cancel', 0)
            self.timeout = max(0, draft.deadline - draft.admin.bot.clock())
            text = f'Send ID: {draft.send_id}\nScope: {draft.scope}'
            if draft.guild_id is not None:
                text += f'\nServer ID: {draft.guild_id}'
            if draft.user_id is not None:
                text += f'\nUser ID: {draft.user_id}'
            text += '\n' + '\n'.join(f'{n + 1}. {ex_gift.label(key, content)}'
                                    for n, key in enumerate(draft.slots))
            text += (f'\nCounts (provisional)\nTargeted servers: {counts["servers"]}'
                     f'\nServers with recipients: {counts["servers_with_recipients"]}'
                     f'\nRecipients: {counts["recipients"]}')
            if counts['recipients'] == 0:
                text += '\nNo enrolled recipients: nothing can be sent.'
            await show(interaction, text, self)
            return
        if action in CATEGORIES:
            draft.category, draft.page = action, 0
        elif action == 'EX':
            draft.ex, draft.page = not draft.ex, 0
        elif action in ('Prev', 'Next'):
            _, pages = ex_gift.page(content, draft.category, draft.ex, draft.page)
            draft.page = max(0, min(pages - 1, draft.page + (1 if action == 'Next' else -1)))
        elif action == 'pick':
            keys, _ = ex_gift.page(content, draft.category, draft.ex, draft.page)
            if len(draft.slots) >= 10 or value not in keys:
                await self.refuse(interaction, 'This item cannot be picked.')
                return
            draft.slots.append(value)
            changed = True
        elif action == 'slot':
            if value not in [str(n) for n in range(len(draft.slots))]:
                await self.refuse(interaction, 'Choose a current slot.')
                return
            draft.picked = int(value)
        elif action == 'Remove' and draft.picked is not None:
            draft.slots.pop(draft.picked)
            changed = True
        elif action == 'Clear' and draft.slots:
            draft.slots.clear()
            changed = True
        if changed:
            draft.revision += 1
            draft.send_id, draft.picked = uuid4().hex, None
        await self.editor(interaction)

    async def receipt(self, interaction, snapshot=None):
        draft = self.draft
        result, user_id = snapshot or (draft.result, draft.user_id)
        text = f'Send ID: {result["gift_id"]}\nScope: {result["scope"]}'
        if result['guild_id'] is not None:
            text += f'\nServer ID: {result["guild_id"]}'
        if user_id is not None:
            text += f'\nUser ID: {user_id}'
        text += '\n' + '\n'.join(f'{n + 1}. {ex_gift.label(key, draft.admin.bot.content)}'
                                 for n, key in enumerate(result['items']))
        text += (f'\nCounts (committed)\nTargeted servers: {result["servers"]}'
                 f'\nServers with recipients: {result["servers_with_recipients"]}'
                 f'\nRecipients: {result["recipients"]}')
        await show(interaction, text)

    async def confirm(self, interaction, revision):
        if not await self.editable(interaction):
            return
        draft, bot = self.draft, self.draft.admin.bot
        if revision != draft.revision:
            await self.refuse(interaction, 'The package changed. Preview it again.')
            return
        snapshot = [None, draft.user_id]
        def live():
            return (draft.admin.gift_drafts.get(draft.draft_id) is draft
                    and draft.state == 'sending' and not draft.discard_pending
                    and bot.clock() < draft.deadline)
        async def job(conn):
            if not live():
                return {'status': 'expired'}
            result = await ex_gift.send(conn, send_id=draft.send_id, owner_id=draft.owner_id,
                admin_guild_id=bot.settings.admin_guild_id, scope=draft.scope,
                guild_id=draft.guild_id, user_id=draft.user_id, items=list(draft.slots),
                content=bot.content, now=time.time())
            if not live():
                raise _Expired
            return result
        def record(result):
            if result['status'] == 'sent':
                draft.state, draft.result, snapshot[0] = 'sent', result, result
        async def settle():
            try:
                result = await bot.writer.run(job, after_commit=record)
                if result['status'] == 'expired':
                    draft.discard_pending = True
            except _Expired:
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
        if snapshot[0] is not None:
            await self.receipt(interaction, snapshot)
        else:
            await self.refuse(interaction, 'Nothing was sent.')
