"""EXR-9 picker and private submit boundary over the committed catalog and SQLite."""

import importlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import discord

import test_admin


def catalog():
    return json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))


class SuggestTests(unittest.TestCase):
    def suggest(self, text, content=None):
        try:
            module = importlib.import_module('pokewalker.bot.admin_ex_raid')
        except ModuleNotFoundError:
            self.fail('EXR-9 picker boundary is absent')
        return module.suggest(content or catalog(), text)

    def test_suggest_dex_number_lists_the_species_identities(self):
        rows = self.suggest('26')
        self.assertEqual(rows[:2], [('#026 Raichu', '26:26'),
                                  ('#026 Alolan Raichu', '10100:10202')])

    def test_suggest_ranks_prefix_then_substring_then_close_spelling(self):
        content = {'identities': [
            {'species_id': 3, 'name_en': 'Charzard', 'identity_id': 'close'},
            {'species_id': 2, 'name_en': 'Mega Charizard', 'identity_id': 'substring'},
            {'species_id': 1, 'name_en': 'Charizard', 'identity_id': 'prefix'}]}
        self.assertEqual([value for _, value in self.suggest('charizard', content)],
                         ['prefix', 'substring', 'close'])
        self.assertEqual(self.suggest('charzrd')[0], ('#006 Charizard', '6:6'))

    def test_suggest_ignores_case_and_accents_and_finds_forms(self):
        content = catalog()
        self.assertEqual(len(content['identities']), 1094)
        for text in ('FLABEBE', 'flabébé'):
            names = [label for label, _ in self.suggest(text, content)]
            self.assertTrue(any('Flabébé' in name for name in names))
        self.assertEqual(self.suggest('ALOLAN RAICHU')[0][1], '10100:10202')

    def test_suggest_returns_at_most_25_labelled_dex_and_name(self):
        content = catalog()
        expected = [(f"#{i['species_id']:03d} {i['name_en']}", i['identity_id'])
                    for i in content['identities'][:25]]
        self.assertEqual(self.suggest('', content), expected)
        for query in ('a', 'raichu', 'zzzzzzzzzz'):
            rows = self.suggest(query, content)
            self.assertLessEqual(len(rows), 25)
            self.assertEqual(len(rows), len({value for _, value in rows}))
            for label, value in rows:
                self.assertRegex(label, r'^#[0-9]{3,4} .+')
                self.assertIsInstance(value, str)


class ExRaidAdminTests(unittest.IsolatedAsyncioTestCase):
    interaction = test_admin.AdminTests.interaction

    async def asyncSetUp(self):
        await test_admin.AdminTests.asyncSetUp(self)
        self.bot.content = catalog()
        await self.bot.db.commit()

    def command(self):
        command = self.group.get_command('ex-raid')
        self.assertIsNotNone(command, '/admin ex-raid is absent')
        return command

    async def autocomplete(self, text='26', interaction=None):
        callback = self.command()._params['pokemon'].autocomplete
        self.assertIsNotNone(callback)
        return await callback(self.group, interaction or self.interaction(), text)

    async def submit(self, pokemon='6:6', interaction=None, **kwargs):
        interaction = interaction or self.interaction()
        command = self.command()
        before = '\n'.join([line async for line in self.bot.db.iterdump()])
        await command.callback(self.group, interaction, pokemon, **kwargs)
        self.assertEqual('\n'.join([line async for line in self.bot.db.iterdump()]), before)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        response = interaction.edit_original_response.await_args.kwargs
        self.assertEqual(response['allowed_mentions'].to_dict()['parse'], [])
        return response

    async def test_autocomplete_empty_outside_admin_guild_and_for_non_owner(self):
        for owner, guild in ((999, 123), (456, 999), (456, None)):
            interaction = self.interaction(owner=owner, guild=guild)
            self.assertEqual(await self.autocomplete(interaction=interaction), [])
            interaction.response.defer.assert_not_awaited()
            interaction.edit_original_response.assert_not_awaited()

    async def test_autocomplete_no_defer_writer_or_bucket_serves_excluded_owner(self):
        await self.bot.db.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        await self.bot.db.commit()
        self.group.requests[456] = [100] * 5
        before = dict(self.group.requests)
        interaction = self.interaction()
        with patch.object(self.bot.writer, 'run', side_effect=AssertionError('autocomplete writer job')):
            rows = await self.autocomplete(interaction=interaction)
        self.assertEqual([c.value for c in rows[:2]], ['26:26', '10100:10202'])
        self.assertTrue(all(isinstance(c, discord.app_commands.Choice) for c in rows))
        self.assertEqual(self.group.requests, before)
        self.assertEqual(self.group.gift_callbacks, {})
        interaction.response.defer.assert_not_awaited()
        interaction.response.send_message.assert_not_awaited()
        interaction.edit_original_response.assert_not_awaited()

    async def test_excluded_owner_refused_at_the_command(self):
        await self.bot.db.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        await self.bot.db.commit()
        self.assertEqual((await self.submit())['content'], 'Excluded owners cannot use admin commands.')

    async def test_known_identity_previews_locks_or_rolled_per_player(self):
        for locks in ({}, {'shiny': False, 'level': 1, 'iv_attack': 0,
                          'iv_defense': 15, 'iv_stamina': 7, 'duration': 24, 'server_id': '999'}):
            response = await self.submit(**locks)
            text = response['content']
            self.assertIn('#006 Charizard', text)
            self.assertIn('EX-Raid', text)
            for name, key in [('Shiny', 'shiny'), ('Level', 'level'), ('Attack IV', 'iv_attack'),
                              ('Defense IV', 'iv_defense'), ('Stamina IV', 'iv_stamina')]:
                expected = str(locks[key]) if key in locks else 'rolled per player'
                self.assertIn(f'{name}: {expected}', text)
            self.assertIn('Target: ' + locks.get('server_id', 'none chosen'), text)
            self.assertEqual(response['embed'].image.url,
                             next(i for i in self.bot.content['identities'] if i['identity_id'] == '6:6')['sprites']['normal'])
            self.assertIsNone(response.get('view'))

    async def test_free_text_and_unknown_identity_refused_nothing_written(self):
        for pokemon in ('Charizard', '99999:99999', ''):
            self.assertEqual((await self.submit(pokemon))['content'], 'Pick a Pokémon from the list.')

    async def test_out_of_range_level_iv_and_duration_refused(self):
        for key, values in [('level', (0, 41)), ('iv_attack', (-1, 16)),
                            ('iv_defense', (-1, 16)), ('iv_stamina', (-1, 16)),
                            ('duration', (0, 25))]:
            for value in values:
                with self.subTest(key=key, value=value):
                    self.group.requests.clear()
                    response = await self.submit(**{key: value})
                    self.assertEqual(response['content'],
                        'Level must be 1-40, each IV 0-15 and the duration 1-24 hours.')

    async def test_duration_omitted_is_one_hour(self):
        self.assertIn('Duration: 1 hour', (await self.submit())['content'])

    async def test_invalid_server_id_refused(self):
        for value in ('abc', '0', '-1', str(2**64), '１２３'):
            self.assertEqual((await self.submit(server_id=value))['content'],
                             'Server ID must be a Discord ID.')

    async def test_serialized_command_only_pokemon_required_with_ranges(self):
        command = self.command().to_dict(self.bot.tree)
        params = command['options']
        self.assertEqual([p['name'] for p in params], ['pokemon', 'server_id', 'shiny',
            'level', 'iv_attack', 'iv_defense', 'iv_stamina', 'duration'])
        self.assertEqual([p['name'] for p in params if p.get('required')], ['pokemon'])
        self.assertTrue(params[0]['autocomplete'])
        self.assertEqual([p['type'] for p in params], [3, 3, 5, 4, 4, 4, 4, 4])
        for param in params[3:]:
            self.assertEqual((param['min_value'], param['max_value']),
                (1, 40) if param['name'] == 'level' else
                (1, 24) if param['name'] == 'duration' else (0, 15))

    async def test_ex_raid_registered_only_in_the_admin_guild(self):
        self.assertIsNotNone(self.command())
        self.assertIsNone(self.bot.tree.get_command('admin'))
        self.assertIsNone(self.bot.tree.get_command('admin', guild=discord.Object(id=999)))
        for owner, guild in ((999, 123), (456, 999), (456, None)):
            result = await self.submit(interaction=self.interaction(owner=owner, guild=guild))
            self.assertEqual(result['content'], 'Only configured owners in the admin guild may use this command.')
