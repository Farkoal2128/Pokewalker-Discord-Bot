"""D73 owner request 2026-11-17: cosmetic looks, unlocks, Change look and the Eternal tier."""

import json
import random
import unittest
from collections import Counter

from pokewalker.domain import encounters
from pokewalker.services import profiles, storage
import test_forms as forms_tests


CONTENT, MULTIPLIERS = forms_tests.CONTENT, forms_tests.MULTIPLIERS


def look(name):
    return next(item for item in CONTENT['looks'] if item['name_en'] == name)


class LookContentTests(unittest.TestCase):
    def test_looks_have_sprites_and_match_their_base(self):
        looks = CONTENT['looks']
        self.assertEqual(len(looks), 119)
        identities = {i['identity_id']: i for i in CONTENT['identities']}
        for item in looks:
            with self.subTest(look=item['name_en']):
                self.assertTrue(item['sprites']['normal'] and item['sprites']['shiny'])
                self.assertEqual(identities[item['base_identity_id']]['species_id'], item['species_id'])
        counts = Counter(item['species_id'] for item in looks)
        self.assertEqual((counts[201], counts[666], counts[25]), (27, 19, 14))  # Unown, Vivillon, Pikachu
        for missing in (664, 665, 1007, 1008, 414):  # Scatterbug, Spewpa, Koraidon, Miraidon, Mothim
            self.assertNotIn(missing, counts)
        names = {item['name_en'] for item in looks}
        self.assertFalse({n for n in names if 'Starter' in n or 'Power Construct' in n})

    def test_eternal_floette_is_its_own_tier_in_the_legendary_pool(self):
        eternal = next(i for i in CONTENT['identities'] if i.get('eternal'))
        self.assertEqual((eternal['name_en'], eternal['tier'], eternal['catch_candy']), ('Eternal Floette', 'Eternal', 10))
        _, pools = profiles.content_facts(CONTENT)
        self.assertIn(eternal, pools['Legendary/Mythical'])
        self.assertNotIn('Eternal', pools)
        spec = encounters.generate({'Legendary/Mythical': [eternal]}, {'weights': {}}, False, random.Random(1),
                                   chances={'common': 0, 'uncommon': 0, 'rare': 0, 'evolved': 0, 'legendary': 1},
                                   rules={**encounters_rules(), 'wild_level_range': [1, 1]})
        self.assertEqual(spec.tier, 'Eternal')

    def test_roll_look(self):
        self.assertIsNone(encounters.roll_look([], random.Random(1)))
        rng = random.Random(7)
        rolls = Counter(encounters.roll_look([10, 11], rng) for _ in range(10000))
        self.assertAlmostEqual(rolls[None] / 10000, 0.9, delta=0.02)
        self.assertAlmostEqual(rolls[10] / 10000, 0.05, delta=0.01)

    def test_identify_uses_look_name_and_sprite(self):
        b = look('Unown B')
        identity, sprite = storage.identify(CONTENT, {'pokemon_id': 201, 'form_id': None, 'look_id': b['look_id'],
                                                      'gender': 'genderless', 'shiny': 1})
        self.assertEqual((identity['name_en'], identity['identity_id']), ('Unown B', b['base_identity_id']))
        self.assertEqual(sprite, b['sprites']['shiny'])

    def test_evolution_targets_ignore_the_source_look(self):
        from pokewalker.services import evolution
        cap = next(i for i in CONTENT['looks'] if i['species_id'] == 25)
        pikachu = {'pokemon_id': 25, 'form_id': None, 'look_id': cap['look_id'], 'gender': 'male', 'shiny': 0}
        names = {evolution.target(CONTENT, pikachu, edge)['name_en'] for edge in CONTENT['evolutions']['25:25']}
        self.assertEqual(names, {'Raichu', 'Alolan Raichu'})

    def test_gym_snapshot_keeps_the_look(self):
        from pokewalker.services import gyms
        b = look('Unown B')
        row = {'pokemon_uid': 'u', 'pokemon_id': 201, 'form_id': None, 'revision': 0, 'content_version': 't',
               'level_x2': 20, 'iv_attack': 1, 'iv_defense': 1, 'iv_stamina': 1, 'gender': 'genderless',
               'shiny': 0, 'look_id': b['look_id']}
        _, snapshot = gyms._battle_snapshot(row, CONTENT, MULTIPLIERS)
        identity, sprite = storage.identify(CONTENT, snapshot)
        self.assertEqual((identity['name_en'], sprite), ('Unown B', b['sprites']['normal']))


def encounters_rules():
    from content.balance import load_table
    return load_table('catch')['rules']


class LookTests(forms_tests.FormTests):
    async def set_look(self, uid, look_id, revision=0):
        from pokewalker.services import forms
        session = await self.current()
        return await self.writer.run(lambda conn: forms.set_look(conn, session, uid, revision, look_id, CONTENT))

    async def unlock(self, look_id, pid='p'):
        await self.conn.execute('INSERT INTO look_unlocks VALUES (?,?,1)', (pid, look_id))

    async def test_set_look_needs_unlock_and_returns_to_default(self):
        await self.pokemon('un', pokemon_id=201)
        b = look('Unown B')
        self.assertEqual((await self.set_look('un', b['look_id']))['status'], 'refused')
        await self.unlock(b['look_id'])
        self.assertEqual((await self.set_look('un', b['look_id']))['status'], 'used')
        self.assertEqual((await self.mon('un'))['look_id'], b['look_id'])
        self.assertEqual(await self.stardust(), 1000000)
        vivillon = next(i for i in CONTENT['looks'] if i['species_id'] == 666)
        await self.unlock(vivillon['look_id'])
        self.assertEqual((await self.set_look('un', vivillon['look_id'], 1))['status'], 'refused')  # other species
        self.assertEqual((await self.set_look('un', b['look_id'], 1))['status'], 'refused')         # already
        self.assertEqual((await self.set_look('un', None, 1))['status'], 'used')
        self.assertIsNone((await self.mon('un'))['look_id'])

    async def test_catch_store_unlocks_and_copies_look(self):
        b = look('Unown B')
        await self.conn.execute(
            "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
            "gender,shiny,tier,route_id,content_version,created_at,state,resolved_at,look_id) "
            "VALUES ('e1','p',201,20,1,2,3,'genderless',0,'Rare','meadow','test',1,'caught',2,?)", (b['look_id'],))
        await self.writer.run(lambda conn: self.walker.store(conn, {'profile_id': 'p'}, 'e1'))
        row = (await self.rows("SELECT * FROM pokemon WHERE source_encounter_id='e1'"))[0]
        self.assertEqual(row['look_id'], b['look_id'])
        self.assertEqual([r['look_id'] for r in await self.rows('SELECT * FROM look_unlocks')], [b['look_id']])

    async def test_evolution_carries_matching_look(self):
        from pokewalker.services import forms
        flabebe = next(i for i in CONTENT['looks'] if i['species_id'] == 669 and i['form_key'] == 'blue')
        floette = next(i for i in CONTENT['identities'] if i['species_id'] == 670 and i['kind'] == 'default')
        pokemon = {'pokemon_id': 669, 'form_id': None, 'look_id': flabebe['look_id'], 'gender': 'female', 'shiny': 0}
        carried = forms.carried_look(CONTENT, pokemon, floette)
        self.assertEqual(next(i for i in CONTENT['looks'] if i['look_id'] == carried)['form_key'], 'blue')
        artisan = next(i for i in CONTENT['looks'] if i['form_key'] == 'artisan')
        sinistcha = next(i for i in CONTENT['identities'] if i['identity_id'] == '1013:1013')
        masterpiece = next(i for i in CONTENT['looks'] if i['look_id'] == forms.carried_look(
            CONTENT, {**pokemon, 'pokemon_id': 1012, 'look_id': artisan['look_id']}, sinistcha))
        self.assertEqual(masterpiece['form_key'], 'masterpiece')
        bulbasaur = next(i for i in CONTENT['identities'] if i['identity_id'] == '2:2')
        self.assertIsNone(forms.carried_look(CONTENT, pokemon, bulbasaur))

    async def test_look_menu_lists_default_and_unlocked_only(self):
        await self.pokemon('un', pokemon_id=201)
        await self.unlock(look('Unown B')['look_id'])
        await self.conn.commit()
        rendered = await self.details('un')
        self.assertTrue(self.buttons(rendered)['Change look'].custom_id.endswith(':look_menu'))
        self.assertNotIn('Change look', self.buttons(await self.details('mon')))
        await self.details('un')
        rendered = await self.screen('look_menu')
        self.assertEqual(rendered['embed'].title, 'Change look')
        self.assertTrue(rendered['embed'].description.endswith('Unlocked 1 of 27.'))
        select = self.select(rendered)
        self.assertEqual([o.label for o in select.options], ['Unown B'])
        rendered = await self.screen('look_pick', [str(look('Unown B')['look_id'])])
        self.assertEqual(rendered['embed'].title, 'Pokémon details')
        self.assertIn('Unown B', rendered['embed'].description)
        rendered = await self.screen('look_menu')
        self.assertEqual([o.label for o in self.select(rendered).options], ['Unown A'])
        self.assertIn('reopen /walker', await self.refusal('look_pick', ['999999']))

    async def test_look_menu_splits_past_25(self):
        await self.pokemon('un', pokemon_id=201)
        for item in CONTENT['looks']:
            if item['species_id'] == 201:
                await self.unlock(item['look_id'])
        await self.conn.commit()
        await self.details('un')
        rendered = await self.screen('look_menu')
        selects = [x for x in rendered['view'].children if hasattr(x, 'options')]
        self.assertEqual([len(s.options) for s in selects], [25, 2])
        self.assertTrue(selects[1].custom_id.endswith(':look_pick_more'))


for name in [n for n in dir(forms_tests.FormTests) if n.startswith('test_')]:
    setattr(LookTests, name, None)  # inherit fixtures only


if __name__ == '__main__':
    unittest.main()


class LookTradeTests(unittest.IsolatedAsyncioTestCase):
    """D73: receiving a Pokemon in a look by trade unlocks that look for the receiver."""

    import test_trading as _trading
    for _name in ('asyncSetUp', 'scalar', 'profile', 'svc', 'session', 'pokemon', 'rows', 'open', 'offer',
                  'confirm', 'ready'):
        locals()[_name] = getattr(_trading.TradingTests, _name)
    del _name

    async def test_trade_unlocks_received_look(self):
        b = look('Unown B')
        trade_id = await self.ready(theirs='unown')
        await self.conn.execute('UPDATE pokemon SET pokemon_id=201,look_id=? WHERE pokemon_uid=?', (b['look_id'], 'unown'))
        await self.conn.execute('UPDATE trade_sides SET pokemon_revision=0 WHERE pokemon_uid=?', ('unown',))
        self.assertEqual((await self.confirm('u', trade_id, 2))['status'], 'waiting')
        self.assertEqual((await self.confirm('v', trade_id, 2))['status'], 'completed')
        unlocks = await self.rows('SELECT profile_id,look_id FROM look_unlocks')
        self.assertEqual([(r['profile_id'], r['look_id']) for r in unlocks], [(self.ids['u'], b['look_id'])])


class ResearchProtectionTests(forms_tests.FormTests):
    async def test_fused_pokemon_cannot_be_sent_even_unlocked(self):
        from pokewalker.services import research
        await self.pokemon('kyu', pokemon_id=646)
        await self.pokemon('res', pokemon_id=643)
        self.assertEqual((await self.fuse('kyu', 'res'))['status'], 'used')

        async def send(uid, revision, preview_id):
            preview = {'id': preview_id, 'expires_at': 10 ** 12, 'unlocked': True}
            picks = [[uid, revision]]
            session = {**await self.current(),
                       'selection': json.dumps({'preview': preview, 'picks': picks, 'single': True})}
            return await self.writer.run(lambda conn: research.send(conn, session, picks, preview, 100, CONTENT))

        self.assertEqual((await send('mon', 0, 'control'))['status'], 'sent')  # the crafted path works
        self.assertEqual(await send('kyu', 1, 'fused'), {'status': 'changed'})
        self.assertEqual((await self.mon('kyu'))['state'], 'owned')
        await self.conn.commit()
        rendered = await self.details('kyu')
        self.assertTrue(self.buttons(rendered)['Send for research'].disabled)

    async def test_auto_research_skips_eternal_floette(self):
        from pokewalker.services import research
        eternal = next(i for i in CONTENT['identities'] if i.get('eternal'))
        for eid, pokemon_id in (('eternal', eternal['pokemon_id']), ('plain', 1)):
            await self.conn.execute(
                "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
                "gender,shiny,tier,route_id,content_version,created_at,state,resolved_at) "
                "VALUES (?,'p',?,20,1,2,3,'female',0,'Common','meadow','test',1,'caught',2)", (eid, pokemon_id))
        self.assertEqual(await self.writer.run(lambda conn: research.auto_send(conn, 10 ** 6, CONTENT)), 1)
        sent = await self.rows("SELECT source_encounter_id FROM pokemon WHERE state='sent'")
        self.assertEqual([r['source_encounter_id'] for r in sent], ['plain'])


for name in [n for n in dir(forms_tests.FormTests) if n.startswith('test_')]:
    setattr(ResearchProtectionTests, name, None)  # inherit fixtures only


class LookEvolutionAndUnfuseTests(forms_tests.FormTests):
    async def test_evolving_keeps_and_unlocks_the_matching_look(self):
        from pokewalker.services import evolution
        blue = next(i for i in CONTENT['looks'] if i['species_id'] == 669 and i['form_key'] == 'blue')
        await self.pokemon('fla', pokemon_id=669)
        await self.conn.execute('UPDATE pokemon SET look_id=? WHERE pokemon_uid=?', (blue['look_id'], 'fla'))
        family = storage.identify(CONTENT, await self.mon('fla'))[0]['family_id']
        await self.conn.execute('INSERT INTO candy VALUES (?,?,500)', ('p', family))
        edge = CONTENT['evolutions']['669:669'][0]
        session = await self.current()
        result = await self.writer.run(lambda conn: evolution.evolve(
            conn, session, 'fla', edge['edge_id'], 0, CONTENT, MULTIPLIERS, 50))
        self.assertEqual(result['status'], 'evolved')
        row = await self.mon('fla')
        floette_blue = next(i for i in CONTENT['looks'] if i['species_id'] == 670 and i['form_key'] == 'blue')
        self.assertEqual(row['look_id'], floette_blue['look_id'])
        unlocks = {r['look_id'] for r in await self.rows('SELECT look_id FROM look_unlocks')}
        self.assertEqual(unlocks, {floette_blue['look_id']})

    async def test_unfuse_clears_a_vanished_source_encounter(self):
        await self.conn.execute(
            "INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
            "gender,shiny,tier,route_id,content_version,created_at,state,resolved_at) "
            "VALUES ('e9','p',791,20,1,2,3,'genderless',0,'Legendary/Mythical','meadow','test',1,'caught',2)")
        await self.pokemon('nec', pokemon_id=800)
        await self.pokemon('sol', pokemon_id=791)
        await self.conn.execute("UPDATE pokemon SET source_encounter_id='e9' WHERE pokemon_uid='sol'")
        self.assertEqual((await self.fuse('nec', 'sol'))['status'], 'used')
        await self.conn.execute("DELETE FROM encounters WHERE encounter_id='e9'")
        self.assertEqual((await self.unfuse('nec', 1))['status'], 'used')
        back = await self.mon('sol')
        self.assertIsNone(back['source_encounter_id'])
        self.assertEqual(back['pokemon_id'], 791)


for name in [n for n in dir(forms_tests.FormTests) if n.startswith('test_')]:
    setattr(LookEvolutionAndUnfuseTests, name, None)  # inherit fixtures only


class LookSpawnTests(forms_tests.FormTests):
    async def test_wild_spawn_saves_a_rolled_look(self):
        from unittest import mock
        from pokewalker.services import stepping
        unown = next(i for i in CONTENT['identities'] if i['identity_id'] == '201:201')
        spec = encounters._spec(unown, unown['tier'], False, random.Random(1), encounters_rules())

        class Always(random.Random):
            def random(self):
                return 0.0

        profile = dict((await self.rows("SELECT * FROM profiles WHERE profile_id='p'"))[0])
        with mock.patch.object(stepping.encounters, 'generate', return_value=spec):
            eid = await self.writer.run(lambda conn: stepping.spawn_encounter(conn, profile, CONTENT, Always(1), 5))
        row = (await self.rows('SELECT look_id FROM encounters WHERE encounter_id=?', (eid,)))[0]
        self.assertIn(row['look_id'], {i['look_id'] for i in CONTENT['looks'] if i['species_id'] == 201})


for name in [n for n in dir(forms_tests.FormTests) if n.startswith('test_')]:
    setattr(LookSpawnTests, name, None)  # inherit fixtures only
