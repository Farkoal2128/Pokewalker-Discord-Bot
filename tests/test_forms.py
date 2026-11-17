"""D71/D72 owner request 2026-11-17: change form and fusion from Pokemon details."""

import importlib
import json
import unittest

from pokewalker.domain.cp import cp
from pokewalker.services import storage
import test_iv_items as base


CONTENT, MULTIPLIERS = base.CONTENT, base.MULTIPLIERS


def forms():
    return importlib.import_module('pokewalker.services.forms')


def form(species_id, key):
    return next(i for i in CONTENT['form_changes'] if i['species_id'] == species_id and i['form_key'] == key)


def cp_of(identity, ivs=(10, 10, 10), level_x2=40):
    return cp([identity[k] for k in ('base_attack', 'base_defense', 'base_stamina')], ivs, level_x2,
              multipliers=MULTIPLIERS)


class ContentTests(unittest.TestCase):
    def test_form_changes_are_resolvable_and_never_encounters(self):
        changes = CONTENT['form_changes']
        self.assertEqual(len(changes), 66)
        counts = {}
        for item in changes:
            counts[item['species_id']] = counts.get(item['species_id'], 0) + 1
        self.assertEqual(counts, {386: 3, 479: 5, 493: 17, 718: 2, 773: 17, 1017: 3, 800: 3, 646: 2, 898: 2,
                                  483: 1, 484: 1, 487: 1, 492: 1, 641: 1, 642: 1, 645: 1, 648: 1, 720: 1, 905: 1,
                                  888: 1, 889: 1})
        encounter_ids = {i['identity_id'] for i in CONTENT['identities']}
        self.assertFalse(encounter_ids & {i['identity_id'] for i in changes})
        fire = form(493, 'fire')
        identity, sprite = storage.identify(CONTENT, {'pokemon_id': 493, 'form_id': fire['form_id'],
                                                      'gender': 'genderless', 'shiny': 0})
        self.assertEqual((identity['name_en'], identity['types']), ('Fire Arceus', ['fire']))
        self.assertTrue(sprite.endswith('/493-fire.png'))
        self.assertNotIn('unknown', {i['form_key'] for i in changes})


class FormTests(unittest.IsolatedAsyncioTestCase):
    interaction = base.IVItemTests.interaction
    rows = base.IVItemTests.rows
    click = base.IVItemTests.click
    connect = base.IVItemTests.connect
    close = base.IVItemTests.close
    current = base.IVItemTests.current
    mon = base.IVItemTests.mon
    snapshot = base.IVItemTests.snapshot
    screen = base.IVItemTests.screen
    refusal = base.IVItemTests.refusal
    buttons = base.IVItemTests.buttons
    details = base.IVItemTests.details
    deploy = base.IVItemTests.deploy

    async def asyncSetUp(self):
        await base.IVItemTests.asyncSetUp(self)
        await self.conn.execute("UPDATE profiles SET stardust=1000000 WHERE profile_id='p'")
        await self.conn.commit()

    async def pokemon(self, uid, pid='p', ivs=(10, 10, 10), pokemon_id=1, form_id=None):
        await self.conn.execute(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,form_id,level_x2,iv_attack,iv_defense,"
            "iv_stamina,gender,shiny,origin,content_version,caught_at) "
            "VALUES (?,?,?,?,40,?,?,?,'genderless',0,'catch','test',5)", (uid, pid, pokemon_id, form_id, *ivs))

    async def stardust(self):
        return (await self.rows("SELECT stardust FROM profiles WHERE profile_id='p'"))[0]['stardust']

    def select(self, rendered):
        return next(x for x in rendered['view'].children if hasattr(x, 'options'))

    async def change(self, uid, identity_id, revision=0):
        session = await self.current()
        return await self.writer.run(lambda conn: forms().change(
            conn, session, uid, revision, identity_id, CONTENT, MULTIPLIERS))

    async def fuse(self, uid, partner, revision=0, partner_revision=0):
        session = await self.current()
        return await self.writer.run(lambda conn: forms().fuse(
            conn, session, uid, revision, partner, partner_revision, CONTENT, MULTIPLIERS, 50))

    async def unfuse(self, uid, revision):
        session = await self.current()
        return await self.writer.run(lambda conn: forms().unfuse(conn, session, uid, revision, CONTENT, 60))

    # Service

    async def test_change_costs_10_per_cp_gained_and_lower_is_free(self):
        attack, defense = form(386, 'attack'), form(386, 'defense')
        await self.pokemon('deo', pokemon_id=10001, form_id=attack['form_id'])
        normal = next(i for i in CONTENT['identities'] if i['identity_id'] == '386:386')
        gain = cp_of(normal) - cp_of(attack)
        self.assertGreater(gain, 0)
        result = await self.change('deo', normal['identity_id'])
        self.assertEqual(result['status'], 'used')
        row = await self.mon('deo')
        self.assertEqual((row['pokemon_id'], row['form_id'], row['revision']), (386, 386, 1))
        self.assertEqual((row['iv_attack'], row['level_x2']), (10, 40))
        self.assertEqual(await self.stardust(), 1000000 - 10 * gain)
        self.assertEqual(await self.change('deo', normal['identity_id']), result)  # replay
        ledger = await self.rows('SELECT * FROM resource_ledger')
        self.assertEqual([(r['resource'], r['delta'], r['reason']) for r in ledger],
                         [('stardust', -10 * gain, 'form_change')])
        self.assertLess(cp_of(defense), cp_of(normal))
        self.assertEqual((await self.change('deo', defense['identity_id'], 1))['status'], 'used')
        self.assertEqual(await self.stardust(), 1000000 - 10 * gain)

    async def test_same_stat_forms_are_free_and_refusals_write_nothing(self):
        await self.pokemon('arc', pokemon_id=493)
        await self.pokemon('bulba', pokemon_id=1)
        self.assertEqual((await self.change('arc', form(493, 'fire')['identity_id']))['status'], 'used')
        self.assertEqual(await self.stardust(), 1000000)
        self.assertEqual((await self.mon('arc'))['form_id'], form(493, 'fire')['form_id'])
        before = await self.snapshot()
        for uid, target, revision, status in (
                ('arc', form(493, 'fire')['identity_id'], 1, 'refused'),       # current form
                ('arc', form(773, 'fire')['identity_id'], 1, 'refused'),       # another species
                ('arc', form(493, 'water')['identity_id'], 7, 'stale'),        # wrong revision
                ('bulba', form(493, 'water')['identity_id'], 0, 'refused'),    # no forms
                ('arc', form(800, 'ultra')['identity_id'], 1, 'refused')):
            with self.subTest(uid=uid, target=target):
                self.assertEqual((await self.change(uid, target, revision))['status'], status)
        await self.pokemon('deo', pokemon_id=10001, form_id=form(386, 'attack')['form_id'])
        await self.conn.execute("UPDATE profiles SET stardust=0 WHERE profile_id='p'")
        before = await self.snapshot()
        self.assertEqual((await self.change('deo', '386:386'))['status'], 'insufficient')
        self.assertEqual(await self.snapshot(), before)

    async def test_oricorio_switches_styles_free_and_zacian_crowns(self):
        await self.pokemon('ori', pokemon_id=741)
        pom = next(i for i in CONTENT['identities'] if i['name_en'] == 'Pom-pom Oricorio')
        self.assertEqual((await self.change('ori', pom['identity_id']))['status'], 'used')
        self.assertEqual(((await self.mon('ori'))['pokemon_id'], await self.stardust()), (pom['pokemon_id'], 1000000))
        await self.pokemon('zac', pokemon_id=888)
        crowned = form(888, 'crowned')
        self.assertEqual(crowned['types'], ['fairy', 'steel'])
        self.assertEqual((await self.change('zac', crowned['identity_id']))['status'], 'used')

    async def test_fuse_holds_partner_and_unfuse_returns_it(self):
        await self.pokemon('nec', pokemon_id=800)
        await self.pokemon('sol', pokemon_id=791, ivs=(1, 2, 3))
        partner = await self.mon('sol')
        before_cp = cp_of(storage.identify(CONTENT, await self.mon('nec'))[0])
        dusk = form(800, 'dusk')
        result = await self.fuse('nec', 'sol')
        self.assertEqual(result['status'], 'used')
        self.assertEqual((result['pokemon']['pokemon_id'], result['pokemon']['form_id']), (10155, dusk['form_id']))
        self.assertEqual(await self.rows("SELECT * FROM pokemon WHERE pokemon_uid='sol'"), [])
        self.assertEqual(await self.stardust(), 1000000 - 10 * max(0, cp_of(dusk) - before_cp))
        self.assertEqual(await storage.owned_count(self.conn, 'p'), 2)  # mon and nec
        # A fused Necrozma may become Ultra and back; unfused Necrozma may not.
        ultra = form(800, 'ultra')
        self.assertEqual((await self.change('nec', ultra['identity_id'], 1))['status'], 'used')
        self.assertEqual((await self.change('nec', form(800, 'dawn')['identity_id'], 2))['status'], 'refused')
        self.assertEqual((await self.change('nec', dusk['identity_id'], 2))['status'], 'used')
        result = await self.unfuse('nec', 3)
        self.assertEqual(result['status'], 'used')
        self.assertEqual((result['pokemon']['pokemon_id'], result['pokemon']['form_id']), (800, 800))
        back = await self.mon('sol')
        self.assertEqual({k: back[k] for k in back if k != 'revision'},
                         {k: partner[k] for k in partner if k != 'revision'})
        self.assertEqual(back['revision'], partner['revision'] + 1)
        self.assertEqual(await self.rows('SELECT * FROM fusions'), [])
        self.assertEqual((await self.change('nec', ultra['identity_id'], 4))['status'], 'refused')

    async def test_fuse_refuses_ineligible_partners_and_full_storage_blocks_unfuse(self):
        await self.pokemon('kyu', pokemon_id=646)
        await self.pokemon('res', pokemon_id=643)
        await self.pokemon('sol', pokemon_id=791)
        await self.pokemon('kyu2', pokemon_id=646)
        before = await self.snapshot()
        self.assertEqual((await self.fuse('kyu', 'sol'))['status'], 'refused')   # wrong partner species
        self.assertEqual((await self.fuse('kyu', 'kyu2'))['status'], 'refused')
        self.assertEqual((await self.fuse('kyu', 'res', partner_revision=4))['status'], 'stale')
        await self.conn.execute("UPDATE profiles SET companion_uid='res' WHERE profile_id='p'")
        self.assertEqual((await self.fuse('kyu', 'res'))['status'], 'refused')
        await self.conn.execute("UPDATE profiles SET companion_uid=NULL WHERE profile_id='p'")
        self.assertEqual((await self.snapshot())['pokemon'], before['pokemon'])
        self.assertEqual((await self.fuse('kyu', 'res'))['status'], 'used')
        self.assertEqual((await self.fuse('kyu', 'res', 1))['status'], 'refused')  # already fused
        self.assertEqual((await self.fuse('kyu2', 'res'))['status'], 'stale')
        self.assertEqual((await self.mon('kyu'))['form_id'], form(646, 'white')['form_id'])
        await self.conn.execute("UPDATE profiles SET storage_limit=250 WHERE profile_id='p'")
        for index in range(250 - await storage.owned_count(self.conn, 'p')):
            await self.pokemon(f'filler{index}')
        self.assertEqual((await self.unfuse('kyu', 1))['status'], 'full')
        await self.conn.execute("DELETE FROM pokemon WHERE pokemon_uid='filler0'")
        self.assertEqual((await self.unfuse('kyu', 1))['status'], 'used')

    async def test_fused_pokemon_is_untradable_and_profile_delete_cascades(self):
        trading = importlib.import_module('pokewalker.services.trading')
        await self.pokemon('cal', pokemon_id=898)
        await self.pokemon('gla', pokemon_id=896)
        self.assertEqual((await self.fuse('cal', 'gla'))['status'], 'used')
        async with self.conn.execute(f"SELECT pokemon_uid FROM pokemon WHERE profile_id=:pid AND {trading._TRADABLE}",
                                     {'pid': 'p'}) as cursor:
            tradable = {row[0] for row in await cursor.fetchall()}
        self.assertNotIn('cal', tradable)
        self.assertIn('mon', tradable)
        await self.conn.execute("DELETE FROM profiles WHERE profile_id='p'")
        self.assertEqual(await self.rows('SELECT * FROM fusions'), [])

    # Screens

    async def test_details_buttons(self):
        await self.pokemon('arc', pokemon_id=493)
        await self.pokemon('nec', pokemon_id=800)
        await self.pokemon('sol', pokemon_id=791)
        await self.conn.commit()
        self.assertNotIn('Change form', self.buttons(await self.details('mon')))
        buttons = self.buttons(await self.details('arc'))
        self.assertTrue(buttons['Change form'].custom_id.endswith(':form_menu'))
        self.assertEqual(buttons['Change form']._rendered_row, 0)
        self.assertNotIn('Fuse', buttons)
        buttons = self.buttons(await self.details('nec'))
        self.assertTrue(buttons['Fuse'].custom_id.endswith(':fuse_menu'))
        self.assertNotIn('Change form', buttons)
        await self.fuse('nec', 'sol')
        rendered = await self.details('nec')
        buttons = self.buttons(rendered)
        self.assertIn('Fused with Solgaleo', rendered['embed'].description)
        self.assertTrue(buttons['Unfuse'].custom_id.endswith(':unfuse_preview'))
        self.assertIn('Change form', buttons)
        self.assertNotIn('Fuse', buttons)

    async def test_form_menu_pick_and_confirm(self):
        await self.pokemon('deo', pokemon_id=10003, form_id=form(386, 'speed')['form_id'])
        await self.conn.commit()
        await self.details('deo')
        rendered = await self.screen('form_menu')
        self.assertEqual(rendered['embed'].title, 'Change form')
        self.assertEqual(rendered['embed'].description,
                         'Pick a form. Gaining CP costs 10 Stardust per CP; the same or lower CP is free. '
                         'Have 1,000,000 Stardust.')
        select = self.select(rendered)
        self.assertTrue(select.custom_id.endswith(':form_pick'))
        normal = next(i for i in CONTENT['identities'] if i['identity_id'] == '386:386')
        speed_cp = cp_of(form(386, 'speed'))
        cost = 10 * (cp_of(normal) - speed_cp)
        option = next(o for o in select.options if o.value == '386:386')
        self.assertEqual(option.label, f'Normal Deoxys · CP {cp_of(normal)}')
        self.assertEqual(option.description, f'Psychic · {cost:,} Stardust')
        self.assertEqual(len(select.options), 3)
        self.assertEqual(await self.refusal('form_confirm'), 'Pick a form first.')
        rendered = await self.screen('form_pick', ['386:386'])
        self.assertTrue(rendered['embed'].description.endswith(
            f'Normal Deoxys: CP {speed_cp} → {cp_of(normal)} · costs {cost:,} Stardust'))
        self.assertFalse(self.buttons(rendered)['Confirm'].disabled)
        rendered = await self.screen('form_confirm')
        self.assertEqual(rendered['embed'].title, 'Pokémon details')
        self.assertIn('Normal Deoxys', rendered['embed'].description)
        self.assertEqual(await self.stardust(), 1000000 - cost)

    async def test_form_menu_free_option_and_short_stardust(self):
        await self.pokemon('deo', pokemon_id=10001, form_id=form(386, 'attack')['form_id'])
        await self.conn.execute("UPDATE profiles SET stardust=0 WHERE profile_id='p'")
        await self.conn.commit()
        await self.details('deo')
        await self.screen('form_menu')
        rendered = await self.screen('form_pick', ['386:386'])
        self.assertTrue(self.buttons(rendered)['Confirm'].disabled)
        self.assertEqual(await self.refusal('form_confirm'), 'Not enough Stardust. Nothing was spent.')
        await self.pokemon('rot', pokemon_id=10008, form_id=10058)  # Heat Rotom
        await self.conn.commit()
        await self.details('rot')
        select = self.select(await self.screen('form_menu'))
        option = next(o for o in select.options if o.value == '479:479')
        self.assertEqual(option.description, 'Electric / Ghost · Free')

    async def test_fuse_menu_and_unfuse_screens(self):
        await self.pokemon('nec', pokemon_id=800)
        await self.pokemon('lun', pokemon_id=792, ivs=(15, 15, 15))
        await self.pokemon('sol', pokemon_id=791)
        await self.conn.commit()
        await self.details('nec')
        rendered = await self.screen('fuse_menu')
        self.assertEqual(rendered['embed'].title, 'Fuse')
        select = self.select(rendered)
        self.assertTrue(select.custom_id.endswith(':fuse_pick'))
        self.assertEqual([o.value for o in select.options], ['lun', 'sol'])  # highest CP first
        self.assertTrue(select.options[0].label.startswith('Lunala · CP '))
        self.assertTrue(select.options[0].description.startswith('→ Dawn Necrozma · CP '))
        self.assertEqual(await self.refusal('fuse_confirm'), 'Pick a partner first.')
        rendered = await self.screen('fuse_pick', ['sol'])
        self.assertIn('Fuse with Solgaleo: Dusk Necrozma · CP ', rendered['embed'].description)
        rendered = await self.screen('fuse_confirm')
        self.assertIn('Fused with Solgaleo', rendered['embed'].description)
        rendered = await self.screen('unfuse_preview')
        self.assertEqual(rendered['embed'].title, 'Unfuse')
        self.assertTrue(rendered['embed'].description.startswith('Solgaleo returns to storage. CP '))
        rendered = await self.screen('unfuse_confirm')
        self.assertEqual(rendered['embed'].title, 'Pokémon details')
        self.assertNotIn('Fused', rendered['embed'].description)
        self.assertEqual(len(await self.rows("SELECT * FROM pokemon WHERE pokemon_uid='sol'")), 1)

    async def test_fuse_menu_without_partners(self):
        await self.pokemon('kyu', pokemon_id=646)
        await self.conn.commit()
        await self.details('kyu')
        rendered = await self.screen('fuse_menu')
        self.assertIn('No Pokémon in storage can fuse with it.', rendered['embed'].description)
        self.assertFalse(any(hasattr(x, 'options') for x in rendered['view'].children))

    async def test_deployed_refuses(self):
        await self.pokemon('rot', pokemon_id=479)  # Rotom is not Legendary, so it can be deployed
        await self.conn.commit()
        await self.details('rot')
        await self.deploy('rot')
        rendered = await self.details('rot')
        self.assertTrue(self.buttons(rendered)['Change form'].disabled)
        self.assertEqual(await self.refusal('form_menu'), 'Recall it from the gym first')
        revision = (await self.mon('rot'))['revision']
        self.assertEqual((await self.change('rot', form(479, 'heat')['identity_id'], revision))['status'], 'deployed')


if __name__ == '__main__':
    unittest.main()
