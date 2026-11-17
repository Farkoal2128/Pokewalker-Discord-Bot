"""D75 owner request 2026-11-17: alternate forms and looks as EX-Raid bosses."""

import importlib
import unittest

import test_admin_ex_raid as admin_tests
import test_ex_raid as ex_tests


CONTENT = admin_tests.catalog()


def look(name):
    return next(item for item in CONTENT['looks'] if item['name_en'] == name)


def form(species_id, key):
    return next(item for item in CONTENT['form_changes'] if item['species_id'] == species_id and item['form_key'] == key)


def raids():
    return importlib.import_module('pokewalker.services.raids')


class BossCatalogTests(unittest.TestCase):
    def test_bosses_add_form_changes_and_looks_but_not_fusion_forms(self):
        ids = {item['identity_id'] for item in raids().bosses(CONTENT)}
        self.assertLessEqual({i['identity_id'] for i in CONTENT['identities']}, ids)
        self.assertIn(form(493, 'fire')['identity_id'], ids)
        self.assertIn(form(386, 'attack')['identity_id'], ids)
        self.assertIn(f"look:{look('Unown B')['look_id']}", ids)
        for species_id, key in ((800, 'dusk'), (800, 'ultra'), (646, 'black'), (898, 'shadow')):
            self.assertNotIn(form(species_id, key)['identity_id'], ids)

    def test_boss_resolves_each_kind(self):
        fire = raids().boss(CONTENT, form(493, 'fire')['identity_id'])
        self.assertEqual((fire['name_en'], fire['types'], fire['form_id']), ('Fire Arceus', ['fire'], 10046))
        b = look('Unown B')
        unown = raids().boss(CONTENT, f"look:{b['look_id']}")
        self.assertEqual((unown['name_en'], unown['look_id'], unown['pokemon_id']), ('Unown B', b['look_id'], 201))
        self.assertEqual(unown['sprites']['normal'], b['sprites']['normal'])
        self.assertEqual(raids().boss(CONTENT, '25:25')['name_en'], 'Pikachu')
        for unknown in (form(646, 'black')['identity_id'], 'look:999999', 'look:x', 'nope'):
            self.assertIsNone(raids().boss(CONTENT, unknown))

    def test_picker_suggests_forms_and_looks(self):
        suggest = importlib.import_module('pokewalker.bot.admin_ex_raid').suggest
        self.assertIn(('#493 Fire Arceus', form(493, 'fire')['identity_id']), suggest(CONTENT, 'fire arceus'))
        b = look('Unown B')
        self.assertIn(('#201 Unown B', f"look:{b['look_id']}"), suggest(CONTENT, 'unown b'))
        self.assertFalse([row for row in suggest(CONTENT, 'black kyurem') if row[0].endswith('Black Kyurem')])


class RaidFormCatchTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = ex_tests.ExRaidCatchTests.asyncSetUp
    profile = ex_tests.ExRaidCatchTests.profile
    scalar = ex_tests.ExRaidCatchTests.scalar
    rows = ex_tests.ExRaidCatchTests.rows
    raids = ex_tests.ExRaidCatchTests.raids
    join = ex_tests.ExRaidCatchTests.join
    use = ex_tests.ExRaidCatchTests.use
    ticket = ex_tests.ExRaidCatchTests.ticket
    arguments = ex_tests.ExRaidCatchTests.arguments
    send = ex_tests.ExRaidCatchTests.send
    snapshot = ex_tests.ExRaidCatchTests.snapshot
    throw = ex_tests.ExRaidCatchTests.throw
    prepare = ex_tests.ExRaidCatchTests.prepare

    async def catch_and_store(self, identity_id):
        from pokewalker.bot.walker import Walker
        encounter, session = await self.prepare(identity_id, locks={'shiny': False, 'level': 1})
        for _ in range(40):
            result, _ = await self.throw(session)
            if result.status == 'caught':
                break
        self.assertEqual(result.status, 'caught')
        await self.writer.run(lambda conn: Walker.store(None, conn, {'profile_id': self.pid},
                                                         encounter['encounter_id']))
        stored, = await self.rows('SELECT * FROM pokemon WHERE source_encounter_id=?', (encounter['encounter_id'],))
        return encounter, stored

    async def test_form_change_boss_is_caught_in_its_form(self):
        from pokewalker.services import storage
        fire = form(493, 'fire')
        encounter, stored = await self.catch_and_store(fire['identity_id'])
        self.assertEqual((encounter['pokemon_id'], encounter['form_id']), (493, fire['form_id']))
        self.assertEqual((stored['pokemon_id'], stored['form_id']), (493, fire['form_id']))
        self.assertEqual(storage.identify(self.content, stored)[0]['name_en'], 'Fire Arceus')

    async def test_distinct_number_form_boss_can_be_thrown_at(self):
        attack = form(386, 'attack')
        encounter, stored = await self.catch_and_store(attack['identity_id'])
        self.assertEqual((stored['pokemon_id'], stored['form_id']), (attack['pokemon_id'], attack['form_id']))

    async def test_look_boss_is_caught_wearing_the_look_and_unlocks_it(self):
        b = look('Unown B')
        encounter, stored = await self.catch_and_store(f"look:{b['look_id']}")
        self.assertEqual((encounter['pokemon_id'], encounter['look_id']), (201, b['look_id']))
        self.assertEqual(stored['look_id'], b['look_id'])
        self.assertEqual(await self.rows('SELECT look_id FROM look_unlocks WHERE profile_id=?', (self.pid,)),
                         [{'look_id': b['look_id']}])

    async def test_fusion_form_boss_is_refused(self):
        result = await self.send(send_id='fused', identity_id=form(646, 'black')['identity_id'],
                                 locks={'shiny': False}, hours=1)
        self.assertEqual(result['status'], 'invalid')


if __name__ == '__main__':
    unittest.main()
