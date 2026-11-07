"""Q15/C3 persisted forms and compatible identity lookup on real SQLite rows."""

import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from pokewalker import db
from pokewalker.services import storage
import test_db


class PokemonFormTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_db.DatabaseTests.asyncSetUp
    profile = test_db.DatabaseTests.profile

    async def insert_pokemon(self, conn, profile_id):
        await conn.execute(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,content_version,caught_at) "
            "VALUES ('pokemon',?,1,20,10,11,12,'female',1,'catch','fixture',123)", (profile_id,))

    async def test_migration_0016_adds_nullable_form_id_rows_unchanged(self):
        prior = Path(self.temp.name) / 'prior'
        prior.mkdir()
        for migration in sorted(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))[:14]:
            (prior / migration.name).write_bytes(migration.read_bytes())
        path = Path(self.temp.name) / 'prior.sqlite3'
        with patch.object(db, 'MIGRATIONS', prior):
            old = await db.open_db(path)
        try:
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('guild')")
            await old.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) "
                              "VALUES ('profile','guild','user',0)")
            await self.insert_pokemon(old, 'profile')
            before = dict((await old.execute_fetchall('SELECT * FROM pokemon'))[0])
        finally:
            await old.close()
        schema = None
        for _ in range(2):
            upgraded = await db.open_db(path)
            try:
                after = dict((await upgraded.execute_fetchall('SELECT * FROM pokemon'))[0])
                self.assertIn('form_id', after)
                self.assertIsNone(after.pop('form_id'))
                self.assertEqual(after, before)
                self.assertEqual(await upgraded.execute_fetchall('PRAGMA foreign_key_check'), [])
                self.assertEqual((await upgraded.execute_fetchall('PRAGMA user_version'))[0][0],
                                 len(list(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))))
                current_schema = [tuple(row) for row in await upgraded.execute_fetchall(
                    'SELECT type,name,sql FROM sqlite_master ORDER BY name')]
                if schema is not None:
                    self.assertEqual(current_schema, schema)
                    self.assertEqual(upgraded.total_changes, 0)
                schema = current_schema
            finally:
                await upgraded.close()

    async def test_form_id_check_rejects_text_and_zero(self):
        await self.insert_pokemon(self.conn, await self.profile())
        for value in ('not-a-form', 0, -1, 1.5):
            with self.subTest(value=value), self.assertRaises(sqlite3.IntegrityError):
                await self.conn.execute('UPDATE pokemon SET form_id=?', (value,))
        for value in (None, 1, 10346):
            await self.conn.execute('UPDATE pokemon SET form_id=?', (value,))
            row = (await self.conn.execute_fetchall('SELECT form_id FROM pokemon'))[0]
            self.assertEqual(row['form_id'], value)

    async def test_identify_accepts_sqlite_rows_with_and_without_form_id_and_dicts(self):
        profile_id = await self.profile()
        await self.insert_pokemon(self.conn, profile_id)
        await self.conn.execute(
            "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,tier,route_id,content_version,created_at) "
            "VALUES ('encounter',?,1,20,10,11,12,'female',1,'Common','refreshing_field','fixture',123)",
            (profile_id,))
        pokemon = (await self.conn.execute_fetchall('SELECT * FROM pokemon'))[0]
        encounter = (await self.conn.execute_fetchall('SELECT * FROM encounters'))[0]
        self.assertIsInstance(pokemon, sqlite3.Row)
        self.assertIsInstance(encounter, sqlite3.Row)
        self.assertIn('form_id', pokemon.keys())
        self.assertNotIn('form_id', encounter.keys())
        content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        expected = content['identities'][0]
        for row in (pokemon, encounter, dict(pokemon), dict(encounter)):
            self.assertEqual(storage.identify(content, row), (expected, expected['sprites']['shiny']))
        await self.conn.execute('UPDATE pokemon SET form_id=?', (expected['form_id'],))
        row = (await self.conn.execute_fetchall('SELECT * FROM pokemon'))[0]
        self.assertEqual(storage.identify(content, row), (expected, expected['sprites']['shiny']))

    def test_identify_form_id_selects_exact_record_and_its_sprite(self):
        default = dict(pokemon_id=869, form_id=869, has_gender_differences=False,
                       sprites=dict(normal='default.png', shiny='default-shiny.png'))
        form = {**default, 'form_id': 10346,
                'sprites': dict(normal='form.png', shiny='form-shiny.png')}
        content = dict(identities=[default], evolution_targets=[form])
        for shiny, key in ((0, 'normal'), (1, 'shiny')):
            pokemon = dict(pokemon_id=869, gender='female', shiny=shiny)
            for form_id, expected in ((None, default), (869, default), (10346, form)):
                with self.subTest(shiny=shiny, form_id=form_id):
                    self.assertEqual(storage.identify(content, {**pokemon, 'form_id': form_id}),
                                     (expected, expected['sprites'][key]))
            self.assertEqual(storage.identify(content, pokemon), (default, default['sprites'][key]))
        with self.assertRaises(StopIteration):
            storage.identify(content, dict(pokemon_id=869, form_id=999, gender='female', shiny=0))

    def test_evolution_target_uses_edge_form_then_gender_variety(self):
        from pokewalker.services.evolution import target
        content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        lechonk = dict(pokemon_id=915, form_id=915, gender='female', shiny=1)
        edge = dict(to_identity_id='916:916')
        resolved = target(content, lechonk, edge)
        self.assertEqual((resolved['pokemon_id'], resolved['form_id']), (10254, 10423))

    def test_identify_unchanged_for_every_committed_record(self):
        content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        records = [variant for item in [*content['identities'], *content['evolution_targets']]
                   for variant in [item, *item.get('gender_varieties', {}).values()]]
        for record in records:
            expected = next(item for item in records if item['pokemon_id'] == record['pokemon_id'])
            for gender in ('male', 'female'):
                for shiny in (0, 1):
                    female = gender == 'female' and expected['has_gender_differences']
                    key = ('shiny_female' if female else 'shiny') if shiny else ('female' if female else 'normal')
                    pokemon = dict(pokemon_id=record['pokemon_id'], gender=gender, shiny=shiny)
                    for shape in (pokemon, {**pokemon, 'form_id': None},
                                  {**pokemon, 'form_id': record['form_id']}):
                        with self.subTest(identity=record['identity_id'], gender=gender, shiny=shiny,
                                          form_id=shape.get('form_id')):
                            resolved = next(item for item in records
                                            if item['pokemon_id'] == record['pokemon_id']
                                            and item['form_id'] == record['form_id']) if shape.get('form_id') is not None else expected
                            self.assertEqual(storage.identify(content, shape),
                                             (resolved, resolved['sprites'][key]))
