"""D64 Shiny Charm: earned once by the 100% Pokédex milestone, toggled in the Bag, 4x shiny odds."""

import random
import sqlite3
import unittest
from unittest.mock import patch

from content.balance import load_table
from pokewalker.domain import encounters
from pokewalker.services import items, stepping
import test_lure as lure_tests
from test_encounters import FixedRandom


class ShinyCharmRollTests(unittest.TestCase):
    def setUp(self):
        self.rules = load_table('catch')['rules']

    def test_charm_multiplies_by_four_and_stacks_with_lure(self):
        base = self.rules['shiny_probability']
        self.assertEqual(self.rules['charm_probability_multiplier'], 4)
        just_under = lambda p: FixedRandom(p - 1e-9)
        self.assertFalse(encounters.roll_shiny(just_under(base * 4), False, rules=self.rules))
        self.assertTrue(encounters.roll_shiny(just_under(base * 4), False, rules=self.rules, charm=True))
        self.assertFalse(encounters.roll_shiny(FixedRandom(base * 4), False, rules=self.rules, charm=True))
        self.assertTrue(encounters.roll_shiny(just_under(base * 16), True, rules=self.rules, charm=True))
        self.assertFalse(encounters.roll_shiny(FixedRandom(base * 16), True, rules=self.rules, charm=True))

    def test_mirror_generation_passes_charm_through(self):
        with patch.object(encounters, 'roll_shiny', wraps=encounters.roll_shiny) as roll:
            encounters.generate_mirror(self.pools(), random.Random(1), chances=load_table('tier_chances')['chances'],
                                       rules=self.rules, charm=True)
        self.assertTrue(roll.call_args.kwargs['charm'])

    @staticmethod
    def pools():
        import json
        from pathlib import Path
        content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        identity = next(i for i in content['identities'] if i['tier'] == 'Common')
        return {identity['tier']: [identity]}


class ShinyCharmTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = lure_tests.LureTests.asyncSetUp
    close = lure_tests.LureTests.close
    current = lure_tests.LureTests.current
    screen = lure_tests.LureTests.screen
    buttons = lure_tests.LureTests.buttons
    credit = lure_tests.LureTests.credit
    interaction = lure_tests.LureTests.interaction
    rows = lure_tests.LureTests.rows
    click = lure_tests.LureTests.click

    async def earn(self):
        await self.conn.execute("INSERT INTO milestone_awards VALUES ('p','pokedex:100',500)")

    async def charm(self):
        return await items.shiny_charm(self.conn, 'p')

    async def test_not_owned_until_pokedex_complete(self):
        self.assertIsNone(await self.charm())
        await self.conn.execute("INSERT INTO milestone_awards VALUES ('p','pokedex:90',500)")
        self.assertIsNone(await self.charm())
        await self.earn()
        self.assertEqual(await self.charm(), 'on')

    async def test_column_defaults_on_and_rejects_other_values(self):
        self.assertEqual((await self.rows('SELECT shiny_charm_off FROM profiles'))[0]['shiny_charm_off'], 0)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.conn.execute("UPDATE profiles SET shiny_charm_off=2")

    async def test_encounters_roll_with_charm_only_while_on(self):
        await self.conn.execute("DELETE FROM inventory")
        with patch.object(encounters, 'roll_shiny', wraps=encounters.roll_shiny) as roll:
            await self.credit(1000, 'before')
        self.assertFalse(roll.call_args.kwargs['charm'])
        await self.earn()
        await self.conn.execute("UPDATE encounters SET state='ran'")
        with patch.object(encounters, 'roll_shiny', wraps=encounters.roll_shiny) as roll:
            await self.credit(1100, 'on')
        self.assertTrue(roll.call_args.kwargs['charm'])
        self.assertFalse(roll.call_args.args[1])
        await self.conn.execute("UPDATE profiles SET shiny_charm_off=1")
        await self.conn.execute("UPDATE encounters SET state='ran'")
        with patch.object(encounters, 'roll_shiny', wraps=encounters.roll_shiny) as roll:
            await self.credit(1200, 'off')
        self.assertFalse(roll.call_args.kwargs['charm'])

    async def test_mirror_encounters_also_use_charm(self):
        await self.earn()
        await self.conn.execute("INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,expires_at,"
                                "receipt_key,remaining_encounters) VALUES ('m','p','companion_mirror',0,NULL,'k',10)")
        spec = encounters.generate_mirror(ShinyCharmRollTests.pools(), random.Random(1),
                                          chances=load_table('tier_chances')['chances'],
                                          rules=load_table('catch')['rules'])
        with patch.object(encounters, 'mirror_hit', return_value=True), \
                patch.object(stepping, 'companion_mirror_pools', return_value=ShinyCharmRollTests.pools()), \
                patch.object(encounters, 'generate_mirror', return_value=spec) as mirrored:
            await self.credit(1000)
        self.assertTrue(mirrored.call_args.kwargs['charm'])

    async def test_bag_hides_charm_until_earned(self):
        rendered = await self.screen('bag')
        self.assertNotIn('Shiny Charm', rendered['embed'].description)
        self.assertFalse(any(label.startswith('Shiny Charm') for label in self.buttons(rendered)))
        refused = await self.click(await self.current(), 'shiny_charm_toggle')
        refused.followup.send.assert_awaited()
        self.assertEqual((await self.rows('SELECT shiny_charm_off FROM profiles'))[0]['shiny_charm_off'], 0)

    async def test_bag_toggles_charm_off_and_on(self):
        await self.earn()
        rendered = await self.screen('bag')
        self.assertIn('Shiny Charm: On · 4× shiny odds on every encounter', rendered['embed'].description)
        button = self.buttons(rendered)['Turn Shiny Charm off']
        self.assertTrue(button.custom_id.endswith(':shiny_charm_toggle'))
        rendered = await self.screen('shiny_charm_toggle')
        self.assertIn('Shiny Charm: Off', rendered['embed'].description)
        self.assertIn('Turn Shiny Charm on', self.buttons(rendered))
        self.assertEqual(await self.charm(), 'off')
        await self.screen('shiny_charm_toggle')
        self.assertEqual(await self.charm(), 'on')


if __name__ == '__main__':
    unittest.main()
