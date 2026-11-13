"""Owner amendment 2026-11-12: Companion Mirror selection, effect, activation and Bag."""

import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import shutil
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from content.balance import load_table
from pokewalker import db
from pokewalker.db import Writer, open_db
from pokewalker.domain import encounters
from pokewalker.services import items, stepping
import test_walker_router as router


CONTENT = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
WARNING = ("For your next 10 generated encounters, each has a 20% chance to be a Pokémon from your "
           "companion's family line, on any route. ⚠ The mirror never attracts Legendary, Mythical or "
           "Rare Pokémon — those family members are skipped, and if none qualify the encounter is a "
           "normal one. Existing queued encounters are unchanged.")
NO_CANDIDATES = "⚠ Your current companion's family has no Pokémon the mirror can attract."
BULBASAUR_LINE = {1, 2, 3}


class FixedRandom(random.Random):
    def __init__(self, value):
        super().__init__(1)
        self.value = value

    def random(self):
        return self.value


def family_of(pokemon_id):
    return next(i['family_id'] for i in CONTENT['identities'] if i['pokemon_id'] == pokemon_id)


class MirrorSelectionTests(unittest.TestCase):
    def setUp(self):
        self.chances = load_table('tier_chances')['chances']
        self.rules = load_table('catch')['rules']

    def pools(self, pokemon_id, identities=None):
        self.assertTrue(hasattr(encounters, 'mirror_pools'), 'Companion Mirror selection is absent')
        return encounters.mirror_pools(identities or CONTENT['identities'], family_of(pokemon_id))

    def ids(self, pools):
        return {tier: sorted(i['pokemon_id'] for i in pool) for tier, pool in pools.items()}

    def test_candidates_are_family_common_uncommon_evolved_only(self):
        self.assertEqual(self.ids(self.pools(1)), {'Common': [1], 'Uncommon': [2], 'Evolved': [3]})
        # Scyther is Rare tier; only its Evolved relatives qualify.
        self.assertEqual(self.ids(self.pools(123)), {'Evolved': [212, 900]})
        for legendary_or_rare in (150, 151, 793):
            with self.subTest(pokemon_id=legendary_or_rare):
                self.assertEqual(self.pools(legendary_or_rare), {})

    def test_legendary_and_mythical_flags_excluded_in_any_tier(self):
        family = [dict(i) for i in CONTENT['identities'] if i['family_id'] == family_of(1)]
        family[0]['is_legendary'] = True
        family[1]['is_mythical'] = True
        self.assertEqual(self.ids(self.pools(1, family)), {'Evolved': [3]})

    def test_generate_mirror_stays_in_family_with_tier_weights_and_no_legendary(self):
        pools = self.pools(1)
        rng = random.Random(3)
        counts = Counter(encounters.generate_mirror(pools, rng, chances=self.chances, rules=self.rules).pokemon_id
                         for _ in range(20000))
        self.assertEqual(set(counts), BULBASAUR_LINE)
        self.assertAlmostEqual(counts[1] / 20000, 60 / 96, delta=.015)
        self.assertAlmostEqual(counts[2] / 20000, 30 / 96, delta=.015)
        self.assertAlmostEqual(counts[3] / 20000, 6 / 96, delta=.008)
        # A draw that would be the 1% Legendary reservation stays inside the family.
        spec = encounters.generate_mirror(pools, FixedRandom(.001), chances=self.chances, rules=self.rules)
        self.assertIn(spec.pokemon_id, BULBASAUR_LINE)
        self.assertNotEqual(spec.tier, encounters.LEGENDARY)

    def test_identity_uniform_within_tier_ignoring_route_weights(self):
        pools = self.pools(133)
        evolved = {i['pokemon_id'] for i in pools['Evolved']}
        self.assertEqual(len(evolved), 8)
        rng = random.Random(5)
        counts = Counter()
        while sum(counts.values()) < 16000:
            spec = encounters.generate_mirror(pools, rng, chances=self.chances, rules=self.rules)
            if spec.tier == 'Evolved':
                counts[spec.pokemon_id] += 1
        self.assertEqual(set(counts), evolved)
        for pokemon_id in evolved:
            self.assertAlmostEqual(counts[pokemon_id] / 16000, 1 / 8, delta=.015)

    def test_shiny_uses_ordinary_odds_and_empty_pools_raise(self):
        with patch.object(encounters, 'roll_shiny', wraps=encounters.roll_shiny) as roll:
            encounters.generate_mirror(self.pools(1), random.Random(1), chances=self.chances, rules=self.rules)
        self.assertFalse(roll.call_args.args[1])
        with self.assertRaises(ValueError):
            encounters.generate_mirror({}, random.Random(1), chances=self.chances, rules=self.rules)

    def test_mirror_hit_is_twenty_percent(self):
        self.assertTrue(encounters.mirror_hit(FixedRandom(.19999), rules=self.rules))
        self.assertFalse(encounters.mirror_hit(FixedRandom(.2), rules=self.rules))
        rng = random.Random(11)
        rate = sum(encounters.mirror_hit(rng, rules=self.rules) for _ in range(50000)) / 50000
        self.assertAlmostEqual(rate, .2, delta=.01)


class CompanionMirrorTests(unittest.IsolatedAsyncioTestCase):
    interaction = router.WalkerTests.interaction
    rows = router.WalkerTests.rows
    click = router.WalkerTests.click

    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(dir='.')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'mirror.sqlite'
        self.conn = await open_db(self.path, allow_unpatched=True)
        self.writer = Writer(self.conn)
        self.addAsyncCleanup(self.close)
        self.content = CONTENT
        self.bot = SimpleNamespace(writer=self.writer, content=self.content)
        from pokewalker.bot.walker import Walker
        self.now = 1000
        self.walker = Walker(self.bot, clock=lambda: self.now)
        await self.conn.execute("INSERT INTO guilds(guild_id) VALUES ('123')")
        # Bulbasaur's family has zero weight on beautiful_beach.
        await self.conn.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at,route_id) "
                                "VALUES ('p','123','456',0,'beautiful_beach')")
        await self.conn.execute("INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) "
                                "VALUES ('abcd','123','456','p',9000)")
        await self.conn.executemany('INSERT INTO inventory VALUES (?,?,?)',
                                    [('p', 'companion_mirror', 2), ('p', 'shiny_lure', 1)])
        await self.companion('bulbasaur', 1)

    async def close(self):
        await self.writer.close()
        await self.conn.close()

    async def companion(self, uid, pokemon_id, pid='p'):
        await self.conn.execute(
            "INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,iv_stamina,"
            "gender,shiny,origin,content_version,caught_at) VALUES (?,?,?,20,1,2,3,'male',0,'catch','test',5)",
            (uid, pid, pokemon_id))
        await self.conn.execute('UPDATE profiles SET companion_uid=? WHERE profile_id=?', (uid, pid))

    async def current(self):
        return (await self.rows())[0]

    async def activate(self, session=None, now=1000):
        self.assertTrue(hasattr(items, 'activate_mirror'), 'Companion Mirror activation service is absent')
        session = session or await self.current()
        return await self.writer.run(lambda conn: items.activate_mirror(conn, session, now))

    async def snapshot(self):
        return {table: await self.rows(f'SELECT * FROM {table}') for table in
                ('profiles', 'inventory', 'sessions', 'active_effects', 'action_receipts', 'resource_ledger')}

    async def held(self, item='companion_mirror'):
        rows = await self.rows('SELECT quantity FROM inventory WHERE item_id=?', (item,))
        return rows[0]['quantity'] if rows else 0

    async def remaining(self):
        return (await self.rows("SELECT remaining_encounters FROM active_effects "
                                "WHERE kind='companion_mirror'"))[0]['remaining_encounters']

    async def credit(self, at, mid='m', seed=8):
        await self.conn.execute("UPDATE encounters SET state='ran'")
        await self.conn.execute("UPDATE profiles SET encounter_meter_c=9900 WHERE profile_id='p'")
        profile = (await self.rows("SELECT * FROM profiles WHERE profile_id='p'"))[0]
        await self.writer.run(lambda conn: stepping.credit_message(
            conn, profile, ['fresh', 'valid', 'words', mid], datetime.fromtimestamp(at, timezone.utc), mid, '789',
            content=self.content, rng=random.Random(seed), cache=stepping.DigestCache()))
        return (await self.rows('SELECT * FROM encounters WHERE source_message_id=?', (mid,)))[0]

    async def screen(self, action):
        interaction = await self.click(await self.current(), action)
        interaction.edit_original_response.assert_awaited_once()
        return interaction.edit_original_response.await_args.kwargs

    def buttons(self, rendered):
        return {x.label: x for x in rendered['view'].children if hasattr(x, 'label')}

    # Activation service

    async def test_activate_consumes_one_and_creates_ten_encounter_effect(self):
        effect = await self.activate()
        row = (await self.rows('SELECT * FROM active_effects'))[0]
        self.assertEqual(effect, row)
        self.assertEqual((row['profile_id'], row['kind'], row['starts_at'], row['expires_at'],
                          row['remaining_encounters'], row['remaining_rewards']),
                         ('p', 'companion_mirror', 1000, None, 10, 0))
        self.assertEqual(await self.held(), 1)
        receipt = (await self.rows('SELECT * FROM action_receipts'))[0]
        self.assertEqual((receipt['key'], receipt['action'], receipt['profile_id']), ('mirror:abcd:0', 'mirror', 'p'))
        self.assertEqual(json.loads(receipt['result']), effect)
        line = (await self.rows('SELECT * FROM resource_ledger'))[0]
        self.assertEqual((line['resource'], line['resource_id'], line['delta'], line['reason']),
                         ('item', 'companion_mirror', -1, 'mirror_activate'))
        self.assertEqual(await items.active_mirror(self.conn, 'p'), row['effect_id'])
        self.assertIsNone(await items.active_lure(self.conn, 'p'))

    async def test_missing_item_refused_without_effect(self):
        await self.conn.execute("UPDATE inventory SET quantity=0 WHERE item_id='companion_mirror'")
        self.assertEqual(await self.activate(), {'status': 'missing'})
        self.assertEqual(await self.rows('SELECT * FROM active_effects'), [])
        self.assertEqual(await self.rows('SELECT * FROM resource_ledger'), [])

    async def test_mirror_and_lure_exclude_each_other_both_directions(self):
        session = await self.current()
        await self.activate()
        lure = await self.writer.run(lambda conn: items.activate_lure(conn, {**session, 'revision': 1}, 1100))
        self.assertEqual(lure, {'status': 'already_active'})
        self.assertEqual(await self.held('shiny_lure'), 1)
        self.assertEqual(await self.activate({**session, 'revision': 2}), {'status': 'already_active'})
        self.assertEqual(await self.held(), 1)
        await self.conn.execute("UPDATE active_effects SET remaining_encounters=0")
        lure = await self.writer.run(lambda conn: items.activate_lure(conn, {**session, 'revision': 3}, 1200))
        self.assertEqual(lure['kind'], 'shiny_lure')
        self.assertEqual(await self.activate({**session, 'revision': 4}), {'status': 'already_active'})
        self.assertEqual(await self.held(), 1)
        self.assertEqual(len(await self.rows("SELECT * FROM resource_ledger WHERE reason='mirror_activate'")), 1)

    async def test_receipt_replay_and_double_click_spend_once(self):
        await self.screen('mirror_confirm')
        before = await self.current()
        clicks = await asyncio.gather(self.click(before, 'mirror_activate'), self.click(before, 'mirror_activate'))
        self.assertEqual(sum(c.edit_original_response.await_count for c in clicks), 1)
        effect = (await self.rows('SELECT * FROM active_effects'))[0]
        await self.credit(1100)
        saved = await self.snapshot()
        self.assertEqual(await self.activate({**before, 'revision': before['revision'] + 1}, 8000), effect)
        self.assertEqual(await self.snapshot(), saved)
        self.assertEqual(await self.held(), 1)
        self.assertEqual(await self.remaining(), 9)

    async def test_excluded_stale_and_outside_transaction_refused(self):
        session = await self.current()
        with self.assertRaisesRegex(RuntimeError, 'writer transaction'):
            await items.activate_mirror(self.conn, session, 1000)
        before = await self.snapshot()
        for change in ({'user_id': '999'}, {'guild_id': '999'}, {'profile_id': 'other'}, {'session_id': 'missing'}):
            self.assertEqual(await self.activate({**session, **change}), {'status': 'stale'})
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('123','456',1)")
        before = await self.snapshot()
        self.assertEqual(await self.activate(session), {'status': 'excluded'})
        self.assertEqual(await self.snapshot(), before)

    async def test_ledger_failure_rolls_back(self):
        self.assertTrue(hasattr(items, 'activate_mirror'), 'Companion Mirror activation service is absent')
        before = await self.snapshot()
        await self.conn.execute("CREATE TRIGGER fail_mirror BEFORE INSERT ON resource_ledger "
                                "BEGIN SELECT RAISE(ABORT,'ledger failed'); END")
        with self.assertRaisesRegex(Exception, 'ledger failed'):
            await self.activate()
        self.assertEqual(await self.snapshot(), before)

    # Encounter generation

    async def test_every_generated_encounter_decrements_and_effect_ends_after_ten(self):
        await self.activate()
        draws = [True, False] * 5
        with patch.object(encounters, 'mirror_hit', side_effect=draws) as hit:
            for i in range(10):
                row = await self.credit(1100 + 60 * i, f'gen-{i}', seed=i)
                self.assertEqual(await self.remaining(), 9 - i)
                self.assertIsNone(row['lure_id'])
                self.assertEqual(row['route_id'], 'beautiful_beach')
                if draws[i]:
                    self.assertIn(row['pokemon_id'], BULBASAUR_LINE)
        self.assertEqual(hit.call_count, 10)
        self.assertIsNone(await items.active_mirror(self.conn, 'p'))
        with patch.object(encounters, 'mirror_hit') as hit:
            await self.credit(2000, 'eleventh')
        hit.assert_not_called()
        self.assertEqual(await self.remaining(), 0)

    async def test_hit_draws_from_companion_family_ignoring_route(self):
        await self.activate()
        weights = self.content['routes']['beautiful_beach']['weights']
        self.assertEqual([weights.get(f'{n}:{n}', 0) for n in BULBASAUR_LINE], [0, 0, 0])
        seen = set()
        with patch.object(encounters, 'mirror_hit', return_value=True):
            for i in range(10):
                row = await self.credit(1100 + 60 * i, f'hit-{i}', seed=100 + i)
                self.assertIn(row['pokemon_id'], BULBASAUR_LINE)
                self.assertEqual((row['route_id'], row['lure_id']), ('beautiful_beach', None))
                seen.add(row['pokemon_id'])
        self.assertIn(1, seen)

    async def test_rare_family_members_never_attracted(self):
        await self.conn.execute("UPDATE profiles SET companion_uid=NULL")
        await self.companion('scyther', 123)
        await self.activate()
        with patch.object(encounters, 'mirror_hit', return_value=True):
            for i in range(10):
                row = await self.credit(1100 + 60 * i, f'rare-{i}', seed=200 + i)
                self.assertIn(row['pokemon_id'], {212, 900})

    async def test_miss_generates_normal_route_encounter(self):
        await self.activate()
        with patch.object(encounters, 'mirror_hit', return_value=False), \
                patch.object(encounters, 'generate_mirror') as mirrored, \
                patch.object(encounters, 'generate', wraps=encounters.generate) as normal:
            row = await self.credit(1100)
        mirrored.assert_not_called()
        self.assertIs(normal.call_args.args[1], self.content['routes']['beautiful_beach'])
        self.assertFalse(normal.call_args.args[2])
        self.assertEqual(row['route_id'], 'beautiful_beach')
        self.assertEqual(await self.remaining(), 9)

    async def test_no_companion_or_no_candidates_falls_back_to_route(self):
        await self.activate()
        for index, (case, setup) in enumerate((('none', None), ('mewtwo', 150), ('nihilego', 793))):
            with self.subTest(case=case):
                await self.conn.execute("UPDATE profiles SET companion_uid=NULL")
                if setup is not None:
                    await self.companion(case, setup)
                with patch.object(encounters, 'mirror_hit', return_value=True), \
                        patch.object(encounters, 'generate_mirror') as mirrored, \
                        patch.object(encounters, 'generate', wraps=encounters.generate) as normal:
                    await self.credit(1100 + 100 * index, f'fallback-{case}')
                mirrored.assert_not_called()
                normal.assert_called_once()
        self.assertEqual(await self.remaining(), 7)

    async def test_current_companion_is_used_at_generation_time(self):
        await self.activate()
        await self.companion('eevee', 133)
        eevee_line = {i['pokemon_id'] for i in self.content['identities'] if i['family_id'] == family_of(133)}
        with patch.object(encounters, 'mirror_hit', return_value=True):
            row = await self.credit(1100)
        self.assertIn(row['pokemon_id'], eevee_line)

    async def test_checkin_encounter_uses_and_spends_mirror(self):
        await self.activate()
        with patch.object(encounters, 'mirror_hit', return_value=True):
            result = await self.writer.run(lambda conn: items.checkin(
                conn, '123', '456', 5000, random.Random(3), self.content))
        self.assertEqual(result['encounter'], 'queued')
        row = (await self.rows('SELECT * FROM encounters WHERE encounter_id=?', (result['encounter_id'],)))[0]
        self.assertIn(row['pokemon_id'], BULBASAUR_LINE)
        self.assertIsNone(row['lure_id'])
        self.assertEqual(await self.remaining(), 9)

    async def test_existing_queued_encounters_unchanged(self):
        before = await self.credit(900, 'before')
        await self.activate()
        with patch.object(encounters, 'mirror_hit', return_value=True):
            await self.credit(1100, 'after')
        self.assertEqual((await self.rows('SELECT * FROM encounters WHERE encounter_id=?',
                                        (before['encounter_id'],)))[0], {**before, 'state': 'ran'})

    # Bag

    async def test_bag_button_confirm_warning_and_activation(self):
        rendered = await self.screen('bag')
        button = self.buttons(rendered)['Companion Mirror']
        self.assertFalse(button.disabled)
        self.assertTrue(button.custom_id.endswith(':mirror_confirm'))
        preview = await self.screen('mirror_confirm')
        self.assertEqual(preview['embed'].description, WARNING)
        self.assertTrue(self.buttons(preview)['Activate'].custom_id.endswith(':mirror_activate'))
        self.assertTrue(self.buttons(preview)['Back'].custom_id.endswith(':bag'))
        self.assertEqual(await self.held(), 2)
        rendered = await self.screen('mirror_activate')
        self.assertIn('Companion Mirror: 10 encounters remaining', rendered['embed'].description)
        self.assertTrue(self.buttons(rendered)['Companion Mirror'].disabled)
        self.assertTrue(self.buttons(rendered)['Shiny Lure'].disabled)
        self.assertEqual(await self.held(), 1)

    async def test_confirm_warns_when_companion_family_has_no_candidates(self):
        for case, pokemon_id in (('none', None), ('mewtwo', 150), ('nihilego', 793), ('bulbasaur2', 1)):
            with self.subTest(case=case):
                await self.conn.execute("UPDATE profiles SET companion_uid=NULL")
                if pokemon_id is not None:
                    await self.companion(case, pokemon_id)
                text = (await self.screen('mirror_confirm'))['embed'].description
                self.assertTrue(text.startswith(WARNING))
                self.assertEqual(NO_CANDIDATES in text, pokemon_id != 1)

    async def test_button_disabled_without_item_or_while_lure_active(self):
        session = await self.current()
        await self.writer.run(lambda conn: items.activate_lure(conn, session, 1000))
        rendered = await self.screen('bag')
        self.assertTrue(self.buttons(rendered)['Companion Mirror'].disabled)
        before = await self.snapshot()
        refused = await self.click(await self.current(), 'mirror_confirm')
        refused.followup.send.assert_awaited_once()
        self.assertEqual(await self.snapshot(), before)
        await self.conn.execute('UPDATE active_effects SET remaining_encounters=0')
        self.assertFalse(self.buttons(await self.screen('bag'))['Companion Mirror'].disabled)
        await self.conn.execute("UPDATE inventory SET quantity=0 WHERE item_id='companion_mirror'")
        self.assertTrue(self.buttons(await self.screen('bag'))['Companion Mirror'].disabled)

    async def test_skipped_confirmation_and_other_user_refused(self):
        before = await self.snapshot()
        skipped = await self.click(await self.current(), 'mirror_activate')
        skipped.followup.send.assert_awaited_once()
        self.assertEqual(await self.snapshot(), before)
        await self.screen('mirror_confirm')
        before = await self.snapshot()
        other = await self.click(await self.current(), 'mirror_activate', user=999)
        self.assertIn('not yours', other.followup.send.await_args.args[0])
        self.assertEqual(await self.snapshot(), before)

    async def test_bag_with_every_button_fits_discord_rows(self):
        await self.conn.executemany('INSERT INTO inventory VALUES (?,?,1)',
                                    [('p', 'star_piece'), ('p', 'world_legendary_ticket')])
        rendered = await self.screen('bag')
        self.assertIn('Companion Mirror', self.buttons(rendered))
        view = rendered['view']
        self.assertLessEqual(len(view.children), 25)
        widths = [0] * 5
        for component in view.children:
            self.assertIn(component._rendered_row, range(5))
            widths[component._rendered_row] += component.width
        self.assertTrue(all(width <= 5 for width in widths))

    # Migration 0019

    async def test_migration_0019_preserves_effects_and_indexes(self):
        prior = Path(self.temp.name) / 'prior'
        prior.mkdir()
        for migration in db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'):
            if int(migration.name[:4]) <= 18:
                shutil.copyfile(migration, prior / migration.name)
        path = Path(self.temp.name) / 'v18.sqlite'
        with patch.object(db, 'MIGRATIONS', prior):
            old = await db.open_db(path, allow_unpatched=True)
        try:
            await old.execute("INSERT INTO guilds(guild_id) VALUES ('g')")
            for pid in ('a', 'b'):
                await old.execute("INSERT INTO profiles(profile_id,guild_id,user_id,created_at) VALUES (?,'g',?,0)",
                                  (pid, pid))
            for values in (('lure', 'a', 'shiny_lure', 4, 0), ('spent', 'a', 'shiny_lure', 0, 0),
                           ('star', 'a', 'star_piece', 0, 6)):
                await old.execute('INSERT INTO active_effects VALUES (?,?,?,1,NULL,?,?,?)',
                                  (*values[:3], 'key-' + values[0], *values[3:]))
            before = [tuple(row) for row in await old.execute_fetchall('SELECT * FROM active_effects ORDER BY rowid')]
        finally:
            await old.close()
        for _ in range(2):
            upgraded = await db.open_db(path, allow_unpatched=True)
            try:
                rows = [tuple(row) for row in await upgraded.execute_fetchall(
                    'SELECT * FROM active_effects ORDER BY rowid')]
                self.assertEqual(rows, before)
                indexes = {row['name'] for row in await upgraded.execute_fetchall('PRAGMA index_list(active_effects)')}
                self.assertTrue({'active_effects_profile_remaining', 'active_effects_one_active',
                                 'active_effects_one_star_piece'} <= indexes)
                self.assertEqual((await upgraded.execute_fetchall('PRAGMA user_version'))[0][0],
                                 len(list(db.MIGRATIONS.glob('[0-9][0-9][0-9][0-9]_*.sql'))))
                insert = ('INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,receipt_key,'
                          'remaining_encounters,remaining_rewards) VALUES (?,?,?,2,?,?,?)')
                for values in (('m1', 'a', 'companion_mirror', 'k1', 5, 0),
                               ('m2', 'b', 'companion_mirror', 'k2', 5, 1),
                               ('m3', 'b', 'companion_mirror', 'k3', 11, 0),
                               ('m4', 'b', 'another', 'k4', 5, 0)):
                    with self.subTest(values=values), self.assertRaises(sqlite3.IntegrityError):
                        await upgraded.execute(insert, values)
                await upgraded.execute(insert, ('m5', 'b', 'companion_mirror', 'k5', 10, 0))
                await upgraded.execute("DELETE FROM active_effects WHERE effect_id='m5'")
                self.assertEqual(await upgraded.execute_fetchall('PRAGMA foreign_key_check'), [])
            finally:
                await upgraded.close()


if __name__ == '__main__':
    unittest.main()
