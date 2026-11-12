import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
import tempfile

import discord
from discord import app_commands

from pokewalker.bot.client import WalkerBot
from pokewalker.config import Secret, Settings

BREAK = '<!-- page -->'
# sha256 of content/help.md:1-14 at 8face5b, joined by LF without a trailing newline (R2).
PAGE_ONE_SHA256 = 'a3c02f50422b436c961342e5937e3d0c3ca16bd6426000dc9e807bfc4f18e5e5'
CHECKIN_SENTENCE = (
    "**Finds and check-ins.** Walking also finds items now and then. Use `/checkin` once an hour, "
    "60 minutes after your last one. It always gives a Poké Ball plus one bonus item: a Great Ball, "
    "a Razz Berry, 2 Poké Balls, a Pinap Berry or, rarely, a Vitamin; an item that doesn't fit in your bag "
    "becomes 10 Stardust. "
    "It also queues one wild encounter if your queue has room; otherwise the reply says your queue is full. "
    "You can't check in while you're paused.")


def units(text):
    return len(text.encode('utf-16-le')) // 2


class ReadmeTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = WalkerBot(Settings(Secret('synthetic'), owner_ids=frozenset({456})))
        self.addAsyncCleanup(self.bot.drain)

    def pages(self):
        from pokewalker.bot.client import load_help
        return load_help()

    def test_approved_text_verbatim(self):
        content = Path('content/help.md').read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(),
                         'c3454d4058d7d84c3acb769a9c730cbbfbbc51f068b570aff5d838fc88229be5')

    def test_page_one_is_current_opening_verbatim(self):
        page = self.pages()[0]
        self.assertEqual(hashlib.sha256(page.encode('utf-8')).hexdigest(), PAGE_ONE_SHA256)

    def test_pages_within_limit_last_is_admin(self):
        pages = self.pages()
        self.assertGreaterEqual(len(pages), 2)
        for page in pages:
            self.assertTrue(page.strip())
            self.assertLessEqual(units(page), 4096)
        self.assertTrue(pages[-1].startswith('# Server setup (admins and moderators)\n'))
        for page in pages[:-1]:
            self.assertNotIn('/walker-admin', page)
            self.assertNotIn('/walker-mod', page)
        for sentence in ('Members with Manage Server can create, remove and list gyms with `/walker-admin gyms`.',
                         '**Gym moderation.** Members with Moderate Members can use `/walker-mod gym-recall',
                         '**Server raids.** Manage Server can enable World Legendary spawns'):
            self.assertIn(sentence, pages[-1])
        self.assertIn('Gym defenders return automatically after 8 hours.', pages[2])

    def test_load_help_refuses_bad_pages(self):
        from pokewalker.bot.client import load_help
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'help.md'
            with patch('pokewalker.bot.client.HELP_PATH', path):
                with self.assertRaisesRegex(ValueError, '(?i)help'):
                    load_help()
                good = 'x' * 4094 + '\U0001f600'
                path.write_text(f'{good}\n{BREAK}\nB\n', encoding='utf-8')
                self.assertEqual(load_help(), [good, 'B'])
                path.write_text(f'A\n\n{BREAK}\n\n{"y" * 4096}\n{BREAK}\nC', encoding='utf-8')
                self.assertEqual(load_help(), ['A', 'y' * 4096, 'C'])
                for bad in ('', '   ', 'single page', f'A\n{BREAK}\n   \n', f'{BREAK}\nB',
                            f'A\n{BREAK}\n' + 'x' * 4097, f'A\n{BREAK}\n' + 'x' * 4095 + '\U0001f600',
                            f'A\n {BREAK}\nB', f'A\n{BREAK} \nB', f'A <!-- page --> B'):
                    path.write_text(bad, encoding='utf-8')
                    with self.subTest(bad=bad[:40]), self.assertRaisesRegex(ValueError, '(?i)help'):
                        load_help()

    async def test_invalid_help_refuses_startup_before_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'help.md'
            for contents in (None, '', '   ', 'x' * 4097, 'one page only'):
                if contents is not None:
                    path.write_text(contents, encoding='utf-8')
                with self.subTest(contents=contents and len(contents)), \
                     patch('pokewalker.bot.client.HELP_PATH', path), \
                     patch('pokewalker.bot.client.load_privacy', return_value='privacy'), \
                     patch('pokewalker.bot.client.open_db', AsyncMock()) as opening:
                    with self.assertRaisesRegex(ValueError, '(?i)help'):
                        await self.bot._setup()
                    opening.assert_not_awaited()
                if path.exists():
                    path.unlink()

    def test_admin_page_names_every_admin_and_mod_subcommand(self):
        page = self.pages()[-1]
        spans = re.findall(r'`([^`]+)`', page)
        documented, children = set(), set()
        for root in ('walker-admin', 'walker-mod'):
            command = next(c for c in self.bot.tree.get_commands(guild=None) if c.name == root)
            self.assertIn(f'**`/{root}`**', page)
            for child in command.commands:
                children.add(child.name)
                if isinstance(child, app_commands.Group):
                    names = {leaf.name for leaf in child.commands}
                    listed = [set(span.split()[1].split('|')) for span in spans
                              if span.split()[0] == child.name and len(span.split()) > 1]
                    self.assertIn(names, listed, f'{root} {child.name}')
                    documented |= {f'{root} {child.name} {name}' for name in names}
                else:
                    self.assertTrue(any(span.split()[0] == child.name for span in spans), f'{root} {child.name}')
                    documented.add(f'{root} {child.name}')
        self.assertIn('trade-channels add|add-all|remove|list', page)
        self.assertIn('**`/walker-admin`** (needs Manage Server)', page)
        self.assertIn('**`/walker-mod`** (needs Moderate Members)', page)
        self.assertNotRegex(page, r'(?<![\w-])/admin\b')
        self.assertEqual(len(documented), 24)
        listed = {span.split()[0] for line in page.splitlines() if line.startswith('- ')
                  for span in re.findall(r'`([^`]+)`', line)}
        self.assertEqual(listed, children)

    def test_checkin_text_matches_service_behaviour(self):
        from pokewalker.services import items
        pages = self.pages()
        self.assertIn(CHECKIN_SENTENCE, pages[1])
        self.assertNotIn('for a Poké Ball, a bonus item and a wild encounter', ''.join(pages))
        table = json.loads(Path('content/balance/checkin_table.json').read_text(encoding='utf-8'))['rows']
        phrases = {('great_ball', 1): 'a Great Ball', ('razz_berry', 1): 'a Razz Berry',
                   ('poke_ball', 2): '2 Poké Balls', ('pinap_berry', 1): 'a Pinap Berry',
                   ('vitamin', 1): 'rarely, a Vitamin'}
        self.assertEqual({(row['item'], row['quantity']) for row in table}, set(phrases))
        for phrase in phrases.values():
            self.assertIn(phrase, CHECKIN_SENTENCE)
        self.assertEqual(items.limits()['encounter_queue'], 3)

    def test_iv_items_and_trade_up_on_player_page(self):
        # Owner amendments 2026-11-12: Bottlecap and Vitamin; ball trade-up.
        from content.balance import load_table
        pages = self.pages()
        rates = load_table('conversion_rates')
        for heading, facts in (
                ('**Vitamins and Bottlecaps.**',
                 ("Use one from a Pokémon's details on its lowest IV", 'a Vitamin raises it by 1',
                  'a Bottlecap raises it to the max', 'CP and Appraisal stars',
                  'Neither works once all its IVs are perfect',
                  f"Buy Vitamins in Bag for {rates['purchase_stardust']['vitamin']:,} Stardust each",
                  'Bottlecaps come from gym survivor rewards')),
                ('**Trade up.**',
                 ('In Bag, trade 2 Poké Balls for 1 Great Ball, or 2 Great Balls for 1 Ultra Ball.',))):
            player = [page for page in pages[:-1] if heading in page]
            self.assertEqual(len(player), 1, heading)
            self.assertNotIn(heading, pages[-1])
            for fact in facts:
                self.assertIn(fact, player[0])
        self.assertEqual([(rule['from'], rule['to'], rule['input_per_output']) for rule in rates['trade_up']],
                         [('poke_ball', 'great_ball', 2), ('great_ball', 'ultra_ball', 2)])

    def test_trading_section_on_player_page(self):
        pages = self.pages()
        player = [page for page in pages[:-1] if '**Trading.**' in page]
        self.assertEqual(len(player), 1)
        self.assertNotIn('**Trading.**', pages[-1])
        for fact in ('In a trade channel, use `/trade member`', "they're pinged", 'join by using `/trade`',
                     'one Pokémon', 'both confirm',
                     "Favorites, your companion and gym defenders can't be traded", 'once per day',
                     'Pokémon you receive count for your Pokédex'):
            self.assertIn(fact, player[0])

    def load(self):
        self.bot.help_pages = self.pages()
        self.bot.writer = SimpleNamespace(run=AsyncMock(side_effect=AssertionError('must not use the writer')))
        self.bot.walker.route = AsyncMock(side_effect=AssertionError('must not route'))
        self.addCleanup(setattr, self.bot, 'writer', None)

    def ids(self, view):
        return [(item.label, item.custom_id, item.disabled) for item in view.children]

    async def click(self, custom_id):
        from pokewalker.bot.client import ReadmeItem
        match = ReadmeItem.__discord_ui_compiled_template__.match(custom_id)
        self.assertIsNotNone(match)
        interaction = SimpleNamespace(guild_id=123, user=SimpleNamespace(id=999), client=self.bot,
                                      response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()))
        item = await ReadmeItem.from_custom_id(interaction, discord.ui.Button(custom_id=custom_id), match)
        await item.callback(interaction)
        return interaction

    async def test_guild_command_is_private_public_to_all_and_in_manifest(self):
        command = self.bot.tree.get_command('readme')
        self.assertIsNotNone(command)
        self.assertTrue(command.guild_only)
        self.assertIn('readme', {c.name for c in self.bot.scope_commands(None)})
        manifest = self.bot.command_manifest_hash()
        self.bot.tree.remove_command('readme')
        self.assertNotEqual(manifest, self.bot.command_manifest_hash())
        self.load()
        count = len(self.bot.help_pages)
        for user in (456, 999):
            interaction = SimpleNamespace(guild_id=123, user=SimpleNamespace(id=user),
                response=SimpleNamespace(send_message=AsyncMock()))
            await command.callback(interaction)
            args = interaction.response.send_message.await_args.kwargs
            self.assertTrue(args['ephemeral'])
            self.assertEqual(args['embed'].title, f'Pokéwalker help (1/{count})')
            self.assertEqual(args['embed'].description, self.bot.help_pages[0])
            self.assertEqual(self.ids(args['view']), [('Prev', 'pw:readme:v1:0', True),
                                                      ('Next', 'pw:readme:v1:1', False)])
            self.assertTrue(args['view'].is_finished(), 'clicks route by custom_id; the view must not stay stored')

    async def test_page_buttons_edit_message_without_database(self):
        self.load()
        count = len(self.bot.help_pages)
        for page in range(count):
            interaction = await self.click(f'pw:readme:v1:{page}')
            interaction.response.send_message.assert_not_awaited()
            args = interaction.response.edit_message.await_args.kwargs
            self.assertEqual(args['embed'].title, f'Pokéwalker help ({page + 1}/{count})')
            self.assertEqual(args['embed'].description, self.bot.help_pages[page])
            ids = self.ids(args['view'])
            self.assertTrue(args['view'].is_finished())
            self.assertEqual([label for label, _, _ in ids], ['Prev', 'Next'])
            self.assertEqual(len({custom_id for _, custom_id, _ in ids}), 2)
            self.assertEqual(ids[0][2], page == 0)
            self.assertEqual(ids[1][2], page == count - 1)
            if page > 0:
                self.assertEqual(ids[0][1], f'pw:readme:v1:{page - 1}')
            if page < count - 1:
                self.assertEqual(ids[1][1], f'pw:readme:v1:{page + 1}')
        self.bot.walker.route.assert_not_awaited()

    async def test_out_of_range_page_refused(self):
        self.load()
        for page in (len(self.bot.help_pages), 99):
            interaction = await self.click(f'pw:readme:v1:{page}')
            interaction.response.edit_message.assert_not_awaited()
            interaction.response.send_message.assert_awaited_once_with('Run /readme again.', ephemeral=True)

    async def test_readme_ids_skip_walker_router(self):
        from pokewalker.bot.client import ReadmeItem
        from pokewalker.bot.walker import CUSTOM_ID
        self.assertEqual(ReadmeItem.__discord_ui_compiled_template__.pattern, r'^pw:readme:v1:(?P<page>\d+)$')
        self.load()
        for page in range(len(self.bot.help_pages)):
            self.assertIsNone(re.match(CUSTOM_ID, f'pw:readme:v1:{page}'))
        for bad in ('pw:readme:v1:-1', 'pw:readme:v2:0', 'pw:readme:v1:x'):
            self.assertIsNone(ReadmeItem.__discord_ui_compiled_template__.match(bad))
        await self.click('pw:readme:v1:1')
        self.bot.walker.route.assert_not_awaited()
