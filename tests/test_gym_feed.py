"""D62 gym defender feeding (owner decision 2026-11-12) on real SQLite writer transactions."""

import json
import math
import unittest

from content.balance import load_table
from pokewalker.domain.battle import defender_hp
import test_gym_screens

HOUR = 3600


class GymFeedTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_gym_screens.GymScreenTests.scalar
    profile = test_gym_screens.GymScreenTests.profile
    pokemon = test_gym_screens.GymScreenTests.pokemon
    rows = test_gym_screens.GymScreenTests.rows
    snapshot = test_gym_screens.GymScreenTests.snapshot
    create = test_gym_screens.GymScreenTests.create
    deploy = test_gym_screens.GymScreenTests.deploy
    gyms = test_gym_screens.GymScreenTests.gyms
    click = test_gym_screens.GymScreenTests.click
    labels = staticmethod(test_gym_screens.GymScreenTests.labels)

    async def asyncSetUp(self):
        await test_gym_screens.GymScreenTests.asyncSetUp(self)
        self.rules = load_table('battle')['rules']
        self.dep = (await self.deploy(self.gym))['deployment']
        await self.berries(3)
        self.revision = 0

    async def berries(self, count):
        await self.conn.execute("INSERT INTO inventory VALUES (?,'razz_berry',?) ON CONFLICT(profile_id,item_id) "
                                'DO UPDATE SET quantity=excluded.quantity', (self.pid, count))

    async def feed(self, hours, session=None, deployment_id=None, revision=None):
        if revision is None:
            self.revision += 1
        session = {**(session or self.session), 'revision': self.revision if revision is None else revision}
        return await self.writer.run(lambda conn: self.gyms().feed(
            conn, session, self.gym['gym_id'], deployment_id or self.dep['deployment_id'],
            self.dep['deployed_at'] + hours, self.rules))

    async def stored(self):
        return (await self.rows('SELECT heal_x10,last_fed_at FROM gym_deployments WHERE deployment_id=?',
                                (self.dep['deployment_id'],)))[0]

    async def held(self):
        return await self.scalar("SELECT quantity FROM inventory WHERE profile_id=? AND item_id='razz_berry'",
                                 (self.pid,))

    async def test_feed_adds_half_but_never_above_double(self):
        # 7 h held: 1.3x; one feed reaches 1.8x, a second (after 10 min) is capped at 2.0x.
        self.assertEqual(await self.feed(7 * HOUR), {'status': 'fed', 'factor_x10': 18})
        self.assertEqual(await self.feed(7 * HOUR + 600), {'status': 'fed', 'factor_x10': 20})
        self.assertEqual((await self.stored())['heal_x10'], 7)
        self.assertEqual(await self.held(), 1)
        ledger = await self.rows("SELECT resource_id,delta,reason FROM resource_ledger WHERE reason='gym_feed'")
        self.assertEqual(ledger, [{'resource_id': 'razz_berry', 'delta': -1, 'reason': 'gym_feed'}] * 2)

    async def test_extra_heal_is_lost_and_weakening_continues(self):
        # 2 h held: 1.8x; feeding stores only the 0.2x that fits, then hour 5 shows 1.7x.
        self.assertEqual(await self.feed(2 * HOUR), {'status': 'fed', 'factor_x10': 20})
        self.assertEqual((await self.stored())['heal_x10'], 2)
        canonical = await self.canonical_hp()
        self.assertEqual(defender_hp(canonical, 5, 2), math.ceil(canonical * 17 / 10))
        self.assertEqual(defender_hp(canonical, 0, 7), canonical * 2)

    async def canonical_hp(self):
        from pokewalker.services import storage
        pokemon = (await self.rows("SELECT * FROM pokemon WHERE pokemon_uid='mon'"))[0]
        return storage.stats(self.content, pokemon, self.walker.multipliers)['hp']

    async def test_refusals_spend_nothing(self):
        cases = []
        before = await self.snapshot()
        cases.append(await self.feed(0))  # already 2.0x
        await self.berries(0)
        cases.append(await self.feed(3 * HOUR))
        self.assertEqual(cases, [{'status': 'full'}, {'status': 'missing'}])
        await self.berries(3)
        self.assertEqual(await self.snapshot(), before)

    async def test_ten_minute_wait_between_feeds(self):
        await self.feed(7 * HOUR)
        before = await self.snapshot()
        self.assertEqual(await self.feed(7 * HOUR + 599), {'status': 'cooldown', 'remaining': 1})
        self.assertEqual(await self.snapshot(), before)
        self.assertEqual((await self.feed(7 * HOUR + 600))['status'], 'fed')

    async def test_only_the_holder_of_this_deployment_can_feed(self):
        other = await self.profile('w', 'g')
        stranger = {'session_id': 'x', 'profile_id': other, 'guild_id': 'g', 'user_id': 'w'}
        before = await self.snapshot()
        self.assertEqual(await self.feed(3 * HOUR, session=stranger), {'status': 'stale'})
        self.assertEqual(await self.feed(3 * HOUR, deployment_id='old'), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)

    async def test_no_feeding_once_tenure_is_over(self):
        before = await self.snapshot()
        self.assertEqual(await self.feed(8 * HOUR), {'status': 'stale'})
        self.assertEqual(await self.snapshot(), before)

    async def test_double_press_spends_one_berry(self):
        first = await self.feed(4 * HOUR, revision=5)
        self.assertEqual(await self.feed(4 * HOUR + 5, revision=5), first)
        self.assertEqual(await self.held(), 2)

    async def test_holder_view_offers_feed_and_shows_healed_factor(self):
        self.now = self.dep['deployed_at'] + 4 * HOUR
        self.session['selection'] = json.dumps({'gym_id': self.gym['gym_id']})
        shown = await self.click('gym_view')
        self.assertIn('Feed Razz Berry', self.labels(shown))
        self.assertIn('×1.6', shown['embed'].description)
        fed = await self.click('gym_feed')
        self.assertIn('×2.0', fed['embed'].description)
        self.assertIn('Fed a Razz Berry', fed['embed'].description)
        self.session['revision'] += 1
        again = await self.click('gym_feed')
        self.assertIn('10 minutes', again['embed'].description)
        self.assertEqual(await self.held(), 2)
