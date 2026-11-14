"""C3 trading service: eligibility, open/join/reopen, cap, ping window, offer, cancel, confirm and swap."""

import asyncio
import importlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from pokewalker import db
import test_db

CONTENT = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
_NEUTRAL = {'is_legendary': False, 'is_mythical': False}


class TradingTests(unittest.IsolatedAsyncioTestCase):
    scalar = test_db.DatabaseTests.scalar
    profile = test_db.DatabaseTests.profile

    async def asyncSetUp(self):
        await test_db.DatabaseTests.asyncSetUp(self)
        self.ids = {user: await self.profile(user, 'g') for user in ('u', 'v', 'w', 'y')}
        self.ids['x'] = await self.profile('x', 'h')
        for user, pid in self.ids.items():
            await self.conn.execute('INSERT INTO sessions(session_id,guild_id,user_id,profile_id,expires_at) '
                                    'VALUES (?,?,?,?,1e12)', ('s' + user, 'h' if user == 'x' else 'g', user, pid))
        self.writer = db.Writer(self.conn)
        self.addAsyncCleanup(self.writer.close)
        await self.pokemon('mon')

    def svc(self):
        try:
            return importlib.import_module('pokewalker.services.trading')
        except ModuleNotFoundError:
            self.fail('Trading service is absent')

    def session(self, user):
        return {'session_id': 's' + user, 'profile_id': self.ids[user],
                'guild_id': 'h' if user == 'x' else 'g', 'user_id': user}

    async def pokemon(self, uid, user='u', pokemon_id=1, shiny=0, caught_at=0, **extra):
        cols = ''.join(',' + key for key in extra)
        await self.conn.execute(
            'INSERT INTO pokemon(pokemon_uid,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,'
            f'iv_stamina,gender,shiny,origin,content_version,caught_at{cols}) '
            f"VALUES (?,?,?,20,10,10,10,'male',?,'catch','test',?{',?' * len(extra)})",
            (uid, self.ids[user], pokemon_id, shiny, caught_at, *extra.values()))

    async def rows(self, sql, args=()):
        return [dict(row) for row in await self.conn.execute_fetchall(sql, args)]

    async def open(self, user, partner, now=1000, can_ping=True):
        return await self.writer.run(lambda conn: self.svc().open_or_join(
            conn, self.session(user), partner, now, can_ping))

    async def offer(self, user, trade_id, uid='mon', now=1100):
        return await self.writer.run(lambda conn: self.svc().offer(conn, self.session(user), trade_id, uid, now))

    async def cancel(self, user, trade_id, now=1100):
        return await self.writer.run(lambda conn: self.svc().cancel(conn, self.session(user), trade_id, now))

    async def current(self, user, now):
        return await self.writer.run(lambda conn: self.svc().current(conn, self.session(user), now))

    async def trade(self, trade_id):
        return (await self.rows('SELECT * FROM trades WHERE trade_id=?', (trade_id,)))[0]

    async def sides(self, trade_id):
        return await self.rows('SELECT side,profile_id,joined_at,open,pokemon_uid,pokemon_revision,'
                               'confirmed_revision FROM trade_sides WHERE trade_id=? ORDER BY side', (trade_id,))

    async def state(self):
        return {table: await self.rows(f'SELECT * FROM {table} ORDER BY 1') for table in
                ('trades', 'trade_sides', 'profiles', 'pokemon')}

    async def joined_pair(self):
        trade_id = (await self.open('u', 'v'))['trade_id']
        self.assertEqual((await self.open('v', 'u', now=1050))['status'], 'joined')
        return trade_id

    async def arena_run(self, user='u', uids=('mon',), started_at=1150):
        await self.writer.run(lambda conn: conn.execute(
            'INSERT INTO arena_runs(run_id,profile_id,started_at,floor,slot,team,enemy) '
            'VALUES (?,?,?,1,0,?,?)',
            ('arena-' + user, self.ids[user], started_at,
             json.dumps([{'uid': uid, 'family_id': 1, 'special': False, 'full_hp': 40,
                          'hp': 40, 'snapshot': {}} for uid in uids]),
             json.dumps({'snapshot': {}, 'battle_hp': 40, 'special': False}))))

    async def test_eligible_page_omits_live_team_members_and_counts_agree(self):
        for index in range(14):
            await self.pokemon(f'p{index:02}', caught_at=index + 1)
        before = await self.svc().eligible_page(self.conn, self.ids['u'], 0, 1200)
        await self.arena_run(uids=('p11', 'p05', 'mon'))
        pages = [await self.svc().eligible_page(self.conn, self.ids['u'], offset, 1200)
                 for offset in (0, 10)]
        self.assertEqual([row['pokemon_uid'] for page, _, _ in pages for row in page],
                         [f'p{i:02}' for i in range(13, -1, -1) if i not in (5, 11)])
        self.assertEqual([(eligible, owned) for _, eligible, owned in pages], [(12, 15), (12, 15)])
        self.assertEqual(before[1:], (15, 15))
        self.assertEqual(pages[0][2], before[2])

    async def test_offer_refuses_team_member_in_arena_no_write(self):
        await self.arena_run(started_at=1000)
        before = await self.rows('SELECT * FROM arena_runs')
        await self.refused_offer('in_arena')
        self.assertEqual(await self.rows('SELECT * FROM arena_runs'), before)

    async def test_offer_made_before_run_start_refused_at_acceptance_side_cleared(self):
        trade_id = await self.ready()
        await self.arena_run()
        await self.invalid(trade_id, 0, 'in_arena')

    async def test_partner_side_team_member_refused_names_their_side(self):
        trade_id = await self.ready()
        await self.arena_run('v', ('theirs',))
        await self.invalid(trade_id, 1, 'in_arena')

    async def test_team_member_tradable_after_hour_18_and_after_run_end(self):
        for ended in (False, True):
            with self.subTest(ended=ended):
                await self.conn.execute('DELETE FROM trades')
                await self.conn.execute('DELETE FROM arena_runs')
                await self.arena_run(started_at=1000 if ended else 1200 - 18 * 3600)
                if ended:
                    await self.conn.execute("UPDATE arena_runs SET ended_at=1150,end_reason='loss'")
                arena = await self.rows('SELECT * FROM arena_runs')
                rows, eligible, owned = await self.svc().eligible_page(self.conn, self.ids['u'], 0, 1200)
                self.assertEqual(([row['pokemon_uid'] for row in rows], eligible, owned), (['mon'], 1, 1))
                trade_id = await self.joined_pair()
                self.assertEqual((await self.offer('u', trade_id, now=1200))['status'], 'offered')
                await self.pokemon('theirs-' + str(ended), user='v')
                await self.offer('v', trade_id, 'theirs-' + str(ended), now=1200)
                self.assertEqual((await self.confirm('u', trade_id, 2))['status'], 'waiting')
                self.assertEqual((await self.confirm('v', trade_id, 2))['status'], 'completed')
                self.assertEqual(await self.rows('SELECT * FROM arena_runs'), arena)
                await self.conn.execute("UPDATE profiles SET last_trade_at=NULL")
                await self.conn.execute("DELETE FROM pokemon WHERE pokemon_uid!='mon'")
                await self.conn.execute("UPDATE pokemon SET profile_id=? WHERE pokemon_uid='mon'", (self.ids['u'],))

    async def test_other_profiles_run_does_not_block_my_trade(self):
        trade_id = await self.ready()
        await self.arena_run('w', ('mon', 'theirs'))
        rows, eligible, owned = await self.svc().eligible_page(self.conn, self.ids['u'], 0, 1200)
        self.assertEqual(([row['pokemon_uid'] for row in rows], eligible, owned), (['mon'], 1, 1))
        self.assertEqual((await self.offer('u', trade_id, now=1200))['status'], 'offered')
        self.assertEqual((await self.confirm('u', trade_id, 3))['status'], 'waiting')
        self.assertEqual((await self.confirm('v', trade_id, 3))['status'], 'completed')

    async def test_open_trade_same_server_partner_side_unjoined(self):
        self.assertEqual((self.svc().TRADE_SECONDS, self.svc().CAP_SECONDS, self.svc().PING_SECONDS),
                         (900, 86400, 600))
        with self.assertRaises(RuntimeError):
            await self.svc().open_or_join(self.conn, self.session('u'), 'v', 1000, True)
        result = await self.open('u', 'v')
        self.assertEqual(result, {'status': 'opened', 'trade_id': result['trade_id'], 'ping': 'reserved'})
        trade = await self.trade(result['trade_id'])
        self.assertEqual({key: trade[key] for key in ('guild_id', 'initiator_profile_id', 'partner_profile_id',
                                                      'state', 'revision', 'created_at', 'expires_at',
                                                      'ended_at')},
                         {'guild_id': 'g', 'initiator_profile_id': self.ids['u'],
                          'partner_profile_id': self.ids['v'], 'state': 'open', 'revision': 0,
                          'created_at': 1000, 'expires_at': 1900, 'ended_at': None})
        self.assertEqual([(s['side'], s['profile_id'], s['joined_at'], s['open'])
                          for s in await self.rows('SELECT * FROM trade_sides')],
                         [(0, self.ids['u'], 1000, 1), (1, self.ids['v'], None, 0)])

    async def test_open_refuses_self_unenrolled_foreign_excluded(self):
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','w',1)")
        before = await self.state()
        for user, partner, status in (('u', 'u', 'self'), ('u', 'nobody', 'partner_not_enrolled'),
                                      ('u', 'x', 'partner_not_enrolled'), ('u', 'w', 'partner_unavailable'),
                                      ('w', 'u', 'excluded')):
            with self.subTest(user=user, partner=partner):
                self.assertEqual(await self.open(user, partner), {'status': status})
        stale = {**self.session('u'), 'profile_id': self.ids['v']}
        self.assertEqual(await self.writer.run(lambda conn: self.svc().open_or_join(conn, stale, 'v', 1000, True)),
                         {'status': 'stale'})
        self.assertEqual(await self.state(), before)

    async def test_partner_joins_and_reopen_is_not_new(self):
        trade_id = (await self.open('u', 'v'))['trade_id']
        self.assertEqual(await self.open('v', 'u', now=1100), {'status': 'joined', 'trade_id': trade_id})
        self.assertEqual((await self.sides(trade_id))[1]['joined_at'], 1100)
        self.assertEqual((await self.sides(trade_id))[1]['open'], 1)
        for user, partner in (('v', 'u'), ('u', 'v')):
            self.assertEqual(await self.open(user, partner, now=1200), {'status': 'reopened', 'trade_id': trade_id})
        self.assertEqual(await self.scalar('SELECT count(*) FROM trades'), 1)
        self.assertEqual(await self.scalar('SELECT count(*) FROM trade_sides'), 2)

    async def test_uninvited_partner_not_blocked_from_other_trades(self):
        first = (await self.open('u', 'v'))['trade_id']
        second = await self.open('w', 'v')
        self.assertEqual(second['status'], 'opened')
        self.assertEqual(await self.open('v', 'u'), {'status': 'joined', 'trade_id': first})
        self.assertEqual(await self.scalar('SELECT count(*) FROM trade_sides WHERE profile_id=? AND open=1',
                                           (self.ids['v'],)), 1)

    async def test_busy_and_partner_busy_reveal_no_identity(self):
        invite = (await self.open('w', 'v'))['trade_id']
        await self.open('u', 'v')
        self.assertEqual(await self.open('u', 'w'), {'status': 'busy', 'partner_user_id': 'v'})
        self.assertEqual(await self.open('y', 'u'), {'status': 'partner_busy'})
        self.assertEqual((await self.open('v', 'u'))['status'], 'joined')
        self.assertEqual(await self.open('v', 'w'), {'status': 'busy', 'partner_user_id': 'u'})
        self.assertEqual(await self.open('y', 'v'), {'status': 'partner_busy'})
        self.assertIsNone((await self.sides(invite))[1]['joined_at'])
        self.assertEqual(await self.scalar('SELECT count(*) FROM trades'), 2)

    async def test_capped_caller_gets_seconds_left_partner_no_time(self):
        svc = self.svc()
        self.assertEqual(svc.cap_left({'last_trade_at': None}, 5000), 0)
        self.assertEqual(svc.cap_left({'last_trade_at': 1000}, 1000 + 86400), 0)
        self.assertEqual(svc.cap_left({'last_trade_at': 1000}, 4600), 82800)
        invite = (await self.open('w', 'u', now=4000))['trade_id']
        await self.conn.execute('UPDATE profiles SET last_trade_at=1000 WHERE user_id=?', ('u',))
        for user, partner, result in (('u', 'v', {'status': 'capped', 'seconds_left': 82800}),
                                      ('u', 'w', {'status': 'capped', 'seconds_left': 82800}),
                                      ('v', 'u', {'status': 'partner_capped'})):
            with self.subTest(user=user, partner=partner):
                self.assertEqual(await self.open(user, partner, now=4600), result)
        await self.conn.execute("UPDATE profiles SET last_trade_at=NULL WHERE user_id='u'")
        await self.conn.execute("UPDATE profiles SET last_trade_at=1000 WHERE user_id='w'")
        self.assertEqual(await self.open('u', 'w', now=4600), {'status': 'partner_capped'})
        self.assertIsNone((await self.sides(invite))[1]['joined_at'])
        self.assertEqual((await self.open('u', 'w', now=1000 + 86400))['status'], 'opened')

    async def test_cancelled_and_expired_trades_do_not_cap(self):
        trade_id = await self.joined_pair()
        self.assertEqual(await self.cancel('u', trade_id), {'status': 'cancelled', 'trade_id': trade_id})
        again = await self.open('u', 'v', now=1200)
        self.assertEqual(again['status'], 'opened')
        self.assertNotEqual(again['trade_id'], trade_id)
        later = await self.open('v', 'u', now=1200 + 900)
        self.assertEqual(later['status'], 'opened')
        self.assertEqual((await self.trade(again['trade_id']))['state'], 'expired')
        self.assertEqual([row['last_trade_at'] for row in await self.rows('SELECT * FROM profiles')],
                         [None] * 5)

    async def test_expired_trade_ends_on_touch_and_frees_members(self):
        trade_id = await self.joined_pair()
        self.assertEqual((await self.current('u', 1899))['trade_id'], trade_id)
        self.assertEqual(len((await self.current('u', 1899))['sides']), 2)
        self.assertEqual((await self.trade(trade_id))['state'], 'open')
        self.assertIsNone(await self.current('v', 1950))
        trade = await self.trade(trade_id)
        self.assertEqual((trade['state'], trade['ended_at']), ('expired', 1950))
        self.assertEqual([side['open'] for side in await self.sides(trade_id)], [0, 0])
        self.assertEqual((await self.open('w', 'u', now=1950))['status'], 'opened')
        self.assertEqual((await self.open('y', 'v', now=1950))['status'], 'opened')

    async def test_activity_extends_trade_expiry(self):
        trade_id = (await self.open('u', 'v'))['trade_id']
        await self.open('v', 'u', now=1300)
        self.assertEqual((await self.trade(trade_id))['expires_at'], 2200)
        self.assertEqual((await self.offer('u', trade_id, now=1500))['status'], 'offered')
        self.assertEqual((await self.trade(trade_id))['expires_at'], 2400)
        await self.open('v', 'u', now=1600)
        self.assertEqual((await self.trade(trade_id))['expires_at'], 2400, 'reopen is not activity')

    async def test_idle_trade_expires_after_15_minutes(self):
        trade_id = (await self.open('u', 'v'))['trade_id']
        self.assertEqual((await self.offer('u', trade_id, now=1899))['status'], 'offered')
        self.assertEqual(await self.offer('u', trade_id, now=2799), {'status': 'expired'})
        trade = await self.trade(trade_id)
        self.assertEqual((trade['state'], trade['ended_at'], trade['revision']), ('expired', 2799, 1))
        self.assertEqual(await self.cancel('u', trade_id, now=2800), {'status': 'expired'})

    async def test_ping_reserved_once_per_10_minutes_per_opener(self):
        ping = 'SELECT last_trade_ping_at FROM profiles WHERE user_id=?'
        first = await self.open('u', 'v', now=1000)
        self.assertEqual(first['ping'], 'reserved')
        await self.cancel('u', first['trade_id'], now=1000)
        second = await self.open('u', 'w', now=1599)
        self.assertEqual((second['status'], second['ping']), ('opened', 'rate_limited'))
        self.assertEqual(await self.scalar(ping, ('u',)), 1000)
        await self.cancel('u', second['trade_id'], now=1599)
        self.assertEqual((await self.open('u', 'v', now=1600))['ping'], 'reserved')
        self.assertEqual(await self.scalar(ping, ('u',)), 1600)
        self.assertEqual((await self.open('w', 'v', now=1600))['ping'], 'reserved')

    async def test_no_ping_on_join_reopen_or_no_permission(self):
        ping = 'SELECT last_trade_ping_at FROM profiles WHERE user_id=?'
        opened = await self.open('u', 'v', can_ping=False)
        self.assertEqual(opened['ping'], 'no_permission')
        self.assertIsNone(await self.scalar(ping, ('u',)))
        for user, partner, status in (('v', 'u', 'joined'), ('v', 'u', 'reopened'), ('u', 'v', 'reopened')):
            result = await self.open(user, partner, now=1100)
            self.assertEqual(result, {'status': status, 'trade_id': opened['trade_id']})
        self.assertEqual([row['last_trade_ping_at'] for row in await self.rows('SELECT * FROM profiles')],
                         [None] * 5)

    async def refused_offer(self, reason, uid='mon', user='u'):
        trade_id = await self.joined_pair()
        before = await self.state()
        self.assertEqual(await self.offer(user, trade_id, uid), {'status': 'ineligible', 'reason': reason})
        self.assertEqual(await self.state(), before)

    async def test_offer_refuses_favorite_at_offer_time(self):
        await self.conn.execute("UPDATE pokemon SET favorite=1 WHERE pokemon_uid='mon'")
        await self.refused_offer('favorite')

    async def test_offer_refuses_gym_deployed_at_offer_time(self):
        await self.conn.execute("INSERT INTO gyms(gym_id,guild_id,name,created_at) VALUES ('gym','g','Park',0)")
        await self.conn.execute(
            'INSERT INTO gym_deployments(deployment_id,guild_id,gym_id,profile_id,pokemon_uid,'
            "deployed_at,ends_at) VALUES ('d','g','gym',?,'mon',0,100)", (self.ids['u'],))
        await self.conn.execute("UPDATE pokemon SET gym_deployment_id='d'")
        await self.refused_offer('deployed')

    async def test_offer_refuses_companion_at_offer_time(self):
        await self.conn.execute("UPDATE profiles SET companion_uid='mon' WHERE user_id='u'")
        await self.refused_offer('companion')

    async def test_offer_allows_shiny_legendary(self):
        content = json.loads(Path('content/artifact/content.json').read_text(encoding='utf-8'))
        legend = next(item for item in content['identities'] if item['pokemon_id'] == 144)
        await self.pokemon('legend', pokemon_id=144, shiny=1)
        profile = (await self.rows("SELECT * FROM profiles WHERE user_id='u'"))[0]
        pokemon = (await self.rows("SELECT * FROM pokemon WHERE pokemon_uid='legend'"))[0]
        self.assertIsNone(self.svc().tradable_reason(legend, pokemon, profile))
        trade_id = await self.joined_pair()
        self.assertEqual((await self.offer('u', trade_id, 'legend'))['status'], 'offered')

    async def test_offer_refuses_sent_and_foreign(self):
        await self.pokemon('gone', state='sent')
        await self.pokemon('theirs', user='v')
        for uid in ('gone', 'theirs', 'missing'):
            with self.subTest(uid=uid):
                await self.conn.execute('DELETE FROM trades')
                await self.refused_offer('not_owned', uid)
        profile = (await self.rows("SELECT * FROM profiles WHERE user_id='u'"))[0]
        self.assertEqual(self.svc().tradable_reason({}, None, profile), 'not_owned')

    async def test_offer_bumps_revision_clears_confirmations(self):
        await self.pokemon('theirs', user='v')
        await self.conn.execute("UPDATE pokemon SET revision=4 WHERE pokemon_uid='mon'")
        trade_id = await self.joined_pair()
        await self.conn.execute('UPDATE trade_sides SET confirmed_revision=0')
        self.assertEqual(await self.offer('u', trade_id), {'status': 'offered', 'trade_id': trade_id, 'revision': 1})
        self.assertEqual([(s['pokemon_uid'], s['pokemon_revision'], s['confirmed_revision'])
                          for s in await self.sides(trade_id)], [('mon', 4, None), (None, None, None)])
        await self.conn.execute('UPDATE trade_sides SET confirmed_revision=1')
        self.assertEqual((await self.offer('v', trade_id, 'theirs'))['revision'], 2)
        self.assertEqual([(s['pokemon_uid'], s['pokemon_revision'], s['confirmed_revision'])
                          for s in await self.sides(trade_id)], [('mon', 4, None), ('theirs', 0, None)])
        self.assertEqual((await self.trade(trade_id))['revision'], 2)

    async def test_eligible_page_only_tradable(self):
        await self.conn.execute("DELETE FROM pokemon")
        for index in range(12):
            await self.pokemon(f'p{index:02}', caught_at=index // 2)
        await self.conn.execute("INSERT INTO gyms(gym_id,guild_id,name,created_at) VALUES ('gym','g','Park',0)")
        await self.conn.execute(
            'INSERT INTO gym_deployments(deployment_id,guild_id,gym_id,profile_id,pokemon_uid,'
            "deployed_at,ends_at) VALUES ('d','g','gym',?,'p00',0,100)", (self.ids['u'],))
        await self.conn.execute("UPDATE pokemon SET gym_deployment_id='d' WHERE pokemon_uid='p00'")
        await self.conn.execute("UPDATE pokemon SET favorite=1 WHERE pokemon_uid='p05'")
        await self.conn.execute("UPDATE profiles SET companion_uid='p11' WHERE user_id='u'")
        await self.pokemon('sent', caught_at=99, state='sent')
        await self.pokemon('theirs', user='v', caught_at=99)
        expected = ['p10', 'p08', 'p09', 'p06', 'p07', 'p04', 'p02', 'p03', 'p01']
        rows, eligible, owned = await self.svc().eligible_page(self.conn, self.ids['u'], 0, 1200)
        self.assertEqual(([row['pokemon_uid'] for row in rows], eligible, owned), (expected, 9, 12))
        await self.pokemon('p12', caught_at=50)
        await self.pokemon('p13', caught_at=50)
        rows, eligible, owned = await self.svc().eligible_page(self.conn, self.ids['u'], 10, 1200)
        self.assertEqual(([row['pokemon_uid'] for row in rows], eligible, owned), (['p01'], 11, 14))

    async def test_non_participant_or_unjoined_stale(self):
        trade_id = (await self.open('u', 'v'))['trade_id']
        await self.pokemon('theirs', user='v')
        await self.pokemon('third', user='w')
        before = await self.state()
        for user, uid in (('v', 'theirs'), ('w', 'third'), ('x', 'mon')):
            with self.subTest(user=user):
                self.assertEqual(await self.offer(user, trade_id, uid), {'status': 'stale'})
                self.assertEqual(await self.cancel(user, trade_id), {'status': 'stale'})
        self.assertEqual(await self.offer('u', 'missing'), {'status': 'stale'})
        self.assertIsNone(await self.current('v', 1100))
        self.assertIsNone(await self.current('w', 1100))
        self.assertEqual(await self.state(), before)

    async def test_joined_participant_cancels(self):
        trade_id = await self.joined_pair()
        self.assertEqual(await self.cancel('v', trade_id, now=1200), {'status': 'cancelled', 'trade_id': trade_id})
        trade = await self.trade(trade_id)
        self.assertEqual((trade['state'], trade['ended_at']), ('cancelled', 1200))
        self.assertEqual([side['open'] for side in await self.sides(trade_id)], [0, 0])
        self.assertEqual(await self.cancel('u', trade_id, now=1300), {'status': 'ended'})
        self.assertEqual(await self.offer('u', trade_id, now=1300), {'status': 'ended'})
        self.assertIsNone(await self.current('u', 1300))

    # T4: confirm and the atomic swap.

    async def confirm(self, user, trade_id, seen, now=1200):
        return await self.writer.run(lambda conn: self.svc().confirm(
            conn, self.session(user), trade_id, seen, now, CONTENT))

    async def ready(self, a='u', b='v', mine='mon', theirs='theirs'):
        """A joined trade where a offers mine and b offers theirs, at trade revision 2."""
        if mine != 'mon':
            await self.pokemon(mine, user=a)
        await self.pokemon(theirs, user=b)
        trade_id = (await self.open(a, b))['trade_id']
        self.assertEqual((await self.open(b, a, now=1050))['status'], 'joined')
        self.assertEqual((await self.offer(a, trade_id, mine))['status'], 'offered')
        self.assertEqual((await self.offer(b, trade_id, theirs))['revision'], 2)
        return trade_id

    async def owners(self):
        return {row['pokemon_uid']: (row['profile_id'], row['revision'])
                for row in await self.rows('SELECT * FROM pokemon')}

    async def last_trade(self):
        return {row['user_id']: row['last_trade_at'] for row in await self.rows('SELECT * FROM profiles')}

    async def test_both_confirm_swaps_and_caps_both_for_24h(self):
        trade_id = await self.ready()
        self.assertEqual(await self.confirm('u', trade_id, 2), {'status': 'waiting', 'trade_id': trade_id})
        self.assertEqual(await self.confirm('v', trade_id, 2, now=1300), {'status': 'completed', 'trade_id': trade_id})
        self.assertEqual(await self.owners(), {'mon': (self.ids['v'], 1), 'theirs': (self.ids['u'], 1)})
        trade = await self.trade(trade_id)
        self.assertEqual((trade['state'], trade['ended_at'], trade['revision']), ('completed', 1300, 3))
        self.assertEqual([side['open'] for side in await self.sides(trade_id)], [0, 0])
        self.assertEqual(await self.last_trade(), {'u': 1300, 'v': 1300, 'w': None, 'y': None, 'x': None})
        self.assertEqual(await self.open('u', 'w', now=1300 + 86399), {'status': 'capped', 'seconds_left': 1})
        self.assertEqual(await self.open('w', 'v', now=1300 + 86399), {'status': 'partner_capped'})
        self.assertEqual((await self.open('u', 'w', now=1300 + 86400))['status'], 'opened')

    async def test_first_confirm_waits_without_swap(self):
        trade_id = await self.ready()
        pokemon = await self.owners()
        for _ in range(2):
            self.assertEqual(await self.confirm('u', trade_id, 2), {'status': 'waiting', 'trade_id': trade_id})
        self.assertEqual([side['confirmed_revision'] for side in await self.sides(trade_id)], [2, None])
        self.assertEqual(await self.owners(), pokemon)
        self.assertEqual(((await self.trade(trade_id))['state'], (await self.trade(trade_id))['revision']), ('open', 2))
        self.assertEqual(set((await self.last_trade()).values()), {None})

    async def test_confirm_extends_trade_expiry(self):
        trade_id = await self.ready()
        self.assertEqual((await self.trade(trade_id))['expires_at'], 2000)
        await self.confirm('u', trade_id, 2, now=1500)
        self.assertEqual((await self.trade(trade_id))['expires_at'], 2400)
        await self.confirm('u', trade_id, 2, now=1400)
        self.assertEqual((await self.trade(trade_id))['expires_at'], 2400, 'activity never shortens expiry')
        self.assertEqual(await self.confirm('v', trade_id, 1, now=1600), {'status': 'changed'})
        self.assertEqual((await self.trade(trade_id))['expires_at'], 2400, 'a refused confirm is not activity')
        self.assertEqual(await self.confirm('v', trade_id, 2, now=2400), {'status': 'expired'})
        self.assertEqual((await self.trade(trade_id))['state'], 'expired')

    async def test_concurrent_confirms_same_trade_swap_once(self):
        trade_id = await self.ready()
        results = await asyncio.gather(*(self.confirm(user, trade_id, 2) for user in ('u', 'v', 'u', 'v')))
        self.assertEqual(sorted(result['status'] for result in results), ['completed'] * 3 + ['waiting'])
        self.assertEqual({result['trade_id'] for result in results}, {trade_id})
        self.assertEqual(await self.owners(), {'mon': (self.ids['v'], 1), 'theirs': (self.ids['u'], 1)})
        self.assertEqual((await self.trade(trade_id))['revision'], 3)

    async def test_concurrent_confirms_on_two_trades_complete_each_once(self):
        first = await self.ready()
        second = await self.ready('w', 'y', 'wmon', 'ymon')
        calls = [(user, trade_id) for _ in range(2) for user, trade_id in
                 (('u', first), ('w', second), ('v', first), ('y', second))]
        results = await asyncio.gather(*(self.confirm(user, trade_id, 2) for user, trade_id in calls))
        for trade_id in (first, second):
            mine = [result['status'] for result in results if result['trade_id'] == trade_id]
            self.assertEqual(sorted(mine), ['completed'] * 3 + ['waiting'])
            self.assertEqual((await self.trade(trade_id))['state'], 'completed')
        self.assertEqual(await self.owners(), {'mon': (self.ids['v'], 1), 'theirs': (self.ids['u'], 1),
                                               'wmon': (self.ids['y'], 1), 'ymon': (self.ids['w'], 1)})
        self.assertEqual(await self.last_trade(), {'u': 1200, 'v': 1200, 'w': 1200, 'y': 1200, 'x': None})

    async def test_repeat_confirm_after_completion_returns_completed(self):
        trade_id = await self.ready()
        await self.confirm('u', trade_id, 2)
        await self.confirm('v', trade_id, 2)
        before = await self.state()
        for user, seen in (('u', 2), ('v', 2), ('u', 3), ('v', 0)):
            with self.subTest(user=user, seen=seen):
                self.assertEqual(await self.confirm(user, trade_id, seen, now=1300),
                                 {'status': 'completed', 'trade_id': trade_id})
        self.assertEqual(await self.confirm('w', trade_id, 2), {'status': 'stale'})
        self.assertEqual(await self.offer('u', trade_id, 'theirs'), {'status': 'ended'})
        self.assertEqual(await self.cancel('v', trade_id), {'status': 'ended'})
        self.assertEqual(await self.state(), before)

    async def test_offer_change_requires_both_confirms_again(self):
        trade_id = await self.ready()
        await self.pokemon('other', user='v')
        self.assertEqual((await self.confirm('u', trade_id, 2))['status'], 'waiting')
        self.assertEqual((await self.offer('v', trade_id, 'other'))['revision'], 3)
        self.assertEqual([side['confirmed_revision'] for side in await self.sides(trade_id)], [None, None])
        self.assertEqual((await self.confirm('v', trade_id, 3))['status'], 'waiting')
        self.assertEqual(await self.confirm('u', trade_id, 2), {'status': 'changed'})
        self.assertEqual((await self.owners())['mon'], (self.ids['u'], 0))
        self.assertEqual(await self.confirm('u', trade_id, 3), {'status': 'completed', 'trade_id': trade_id})
        owners = await self.owners()
        self.assertEqual((owners['mon'], owners['other'], owners['theirs']),
                         ((self.ids['v'], 1), (self.ids['u'], 1), (self.ids['v'], 0)))

    async def test_confirm_with_stale_seen_revision_refused(self):
        trade_id = await self.ready()
        await self.confirm('v', trade_id, 2)
        before = await self.state()
        for user, seen in (('u', 1), ('u', 3), ('v', 0)):
            with self.subTest(user=user, seen=seen):
                self.assertEqual(await self.confirm(user, trade_id, seen), {'status': 'changed'})
        self.assertEqual(await self.state(), before)

    async def test_confirm_refuses_stale_caller_and_incomplete_trade(self):
        trade_id = (await self.open('u', 'v'))['trade_id']
        before = await self.state()
        for user in ('v', 'w', 'x'):
            with self.subTest(user=user):
                self.assertEqual(await self.confirm(user, trade_id, 0), {'status': 'stale'})
        self.assertEqual(await self.confirm('u', 'missing', 0), {'status': 'stale'})
        self.assertEqual(await self.confirm('u', trade_id, 0), {'status': 'incomplete'})
        self.assertEqual(await self.state(), before)
        await self.open('v', 'u', now=1050)
        self.assertEqual((await self.offer('u', trade_id))['revision'], 1)
        joined = await self.state()
        self.assertEqual(await self.confirm('v', trade_id, 1), {'status': 'incomplete'})
        self.assertEqual(await self.state(), joined)

    async def invalid(self, trade_id, side, reason):
        """The second confirm finds one offer invalid: that offer and both confirmations clear, nothing moves."""
        self.assertEqual((await self.confirm('u', trade_id, 2))['status'], 'waiting')
        sides = await self.sides(trade_id)
        owners = {uid: owner for uid, (owner, _) in (await self.owners()).items()}
        self.assertEqual(await self.confirm('v', trade_id, 2, now=1300),
                         {'status': 'offer_invalid', 'side': side, 'reason': reason})
        after = await self.sides(trade_id)
        self.assertEqual([(s['pokemon_uid'], s['pokemon_revision']) for s in after],
                         [(None, None) if s['side'] == side else (s['pokemon_uid'], s['pokemon_revision'])
                          for s in sides])
        self.assertEqual([s['confirmed_revision'] for s in after], [None, None])
        trade = await self.trade(trade_id)
        self.assertEqual((trade['state'], trade['revision'], trade['expires_at']), ('open', 3, 2200))
        self.assertEqual({uid: owner for uid, (owner, _) in (await self.owners()).items()}, owners)
        self.assertEqual(set((await self.last_trade()).values()), {None})

    async def test_execute_refuses_pokemon_favorited_after_offer(self):
        trade_id = await self.ready()
        storage = importlib.import_module('pokewalker.services.storage')
        self.assertIsNotNone(await self.writer.run(
            lambda conn: storage.set_favorite(conn, self.ids['u'], 'mon', 1, 0)))
        await self.invalid(trade_id, 0, 'favorite')

    async def test_execute_refuses_pokemon_deployed_after_offer(self):
        trade_id = await self.ready()
        await self.conn.execute("INSERT INTO gyms(gym_id,guild_id,name,created_at) VALUES ('gym','g','Park',0)")
        await self.conn.execute(
            'INSERT INTO gym_deployments(deployment_id,guild_id,gym_id,profile_id,pokemon_uid,'
            "deployed_at,ends_at) VALUES ('d','g','gym',?,'theirs',0,100)", (self.ids['v'],))
        # gyms.py deploys with revision+1, like every Pokemon writer.
        await self.conn.execute("UPDATE pokemon SET gym_deployment_id='d',revision=revision+1 "
                                "WHERE pokemon_uid='theirs'")
        await self.invalid(trade_id, 1, 'deployed')

    async def test_execute_refuses_pokemon_made_companion_after_offer(self):
        trade_id = await self.ready()
        # Set companion (bot/storage.py) bumps no revision, so only the explicit check catches it.
        await self.conn.execute("UPDATE profiles SET companion_uid='mon' WHERE user_id='u'")
        await self.invalid(trade_id, 0, 'companion')

    async def test_execute_refuses_evolved_powered_or_sent_after_offer(self):
        # The same writes as evolution.py, powerup.py and research.py: each bumps the revision.
        for case, change, reason in (
                ('evolved', 'pokemon_id=2', 'changed'), ('powered', 'level_x2=level_x2+1', 'changed'),
                ('sent', "state='sent'", 'not_owned')):
            with self.subTest(case=case):
                await self.conn.execute('DELETE FROM trades')
                trade_id = await self.ready(mine='u_' + case, theirs='v_' + case)
                await self.conn.execute(f'UPDATE pokemon SET {change},revision=revision+1 WHERE pokemon_uid=?',
                                        ('v_' + case,))
                await self.invalid(trade_id, 1, reason)

    async def test_execute_refuses_excluded_partner(self):
        trade_id = await self.ready()
        self.assertEqual((await self.confirm('u', trade_id, 2))['status'], 'waiting')
        await self.conn.execute("INSERT INTO restrictions(guild_id,user_id,excluded) VALUES ('g','v',1)")
        pokemon = await self.owners()
        self.assertEqual(await self.confirm('u', trade_id, 2), {'status': 'partner_unavailable'})
        self.assertEqual([side['confirmed_revision'] for side in await self.sides(trade_id)], [None, None])
        self.assertEqual(await self.confirm('v', trade_id, 2), {'status': 'excluded'})
        self.assertEqual(await self.owners(), pokemon)
        self.assertEqual((await self.trade(trade_id))['state'], 'open')

    async def test_step4_refuses_side_that_became_capped(self):
        trade_id = await self.ready()
        self.assertEqual((await self.confirm('v', trade_id, 2))['status'], 'waiting')
        await self.conn.execute("UPDATE profiles SET last_trade_at=1100 WHERE user_id='u'")
        before = await self.state()
        self.assertEqual(await self.confirm('u', trade_id, 2), {'status': 'capped', 'seconds_left': 86300})
        self.assertEqual(await self.confirm('v', trade_id, 2), {'status': 'partner_capped'})
        self.assertEqual(await self.state(), before)

    async def test_cap_boundary_allows_trade_at_exactly_86400_seconds(self):
        trade_id = await self.ready()
        await self.conn.execute("UPDATE profiles SET last_trade_at=? WHERE user_id='u'", (1200 - 86400,))
        await self.conn.execute("UPDATE profiles SET last_trade_at=? WHERE user_id='v'", (1200 - 86399,))
        self.assertEqual(await self.confirm('u', trade_id, 2), {'status': 'partner_capped'})
        self.assertEqual(await self.confirm('v', trade_id, 2), {'status': 'capped', 'seconds_left': 1})
        await self.conn.execute("UPDATE profiles SET last_trade_at=? WHERE user_id='v'", (1200 - 86400,))
        self.assertEqual((await self.confirm('u', trade_id, 2))['status'], 'waiting')
        self.assertEqual(await self.confirm('v', trade_id, 2), {'status': 'completed', 'trade_id': trade_id})
        self.assertEqual((await self.last_trade())['u'], 1200)
        self.assertEqual((await self.last_trade())['v'], 1200)

    async def test_backstops_roll_back_whole_job(self):
        svc = self.svc()
        cases = (
            # Step 7.1: the guarded last_trade_at UPDATE hits one row, not two.
            ('cap_left', "UPDATE profiles SET last_trade_at=1150 WHERE user_id='v'", RuntimeError),
            # Step 7.2: the owner UPDATE restating eligibility hits no row.
            ('tradable_reason', "UPDATE pokemon SET favorite=1 WHERE pokemon_uid='theirs'", RuntimeError),
            # The pokemon_trade_guard trigger: a companion passes the UPDATE's own filter.
            ('tradable_reason', "UPDATE profiles SET companion_uid='theirs' WHERE user_id='v'",
             sqlite3.IntegrityError))
        for check, sql, error in cases:
            with self.subTest(check=check, sql=sql):
                await self.conn.execute('DELETE FROM trades')
                await self.conn.execute('UPDATE profiles SET last_trade_at=NULL,companion_uid=NULL')
                await self.conn.execute('DELETE FROM pokemon')
                await self.pokemon('mon')
                trade_id = await self.ready()
                self.assertEqual((await self.confirm('u', trade_id, 2))['status'], 'waiting')
                await self.conn.execute(sql)
                before = await self.state()
                with patch.object(svc, check, return_value=None if check == 'tradable_reason' else 0), \
                        self.assertRaises(error):
                    await self.confirm('v', trade_id, 2, now=1300)
                self.assertEqual(await self.state(), before)
                self.assertNotEqual((await self.confirm('v', trade_id, 2, now=1300))['status'], 'completed')

    async def test_swap_acknowledges_unacknowledged_source_encounters(self):
        for encounter, user, acknowledged in (('e_mon', 'u', None), ('e_theirs', 'v', 50), ('e_other', 'u', None)):
            await self.conn.execute(
                'INSERT INTO encounters(encounter_id,profile_id,pokemon_id,level_x2,iv_attack,iv_defense,'
                "iv_stamina,gender,shiny,tier,route_id,state,content_version,created_at,acknowledged_at) "
                "VALUES (?,?,1,20,10,10,10,'male',0,'common','refreshing_field','caught','test',0,?)",
                (encounter, self.ids[user], acknowledged))
        await self.conn.execute("UPDATE pokemon SET source_encounter_id='e_mon' WHERE pokemon_uid='mon'")
        await self.pokemon('theirs', user='v', source_encounter_id='e_theirs')
        trade_id = await self.ready(theirs='plain')
        await self.offer('v', trade_id, 'theirs')
        await self.confirm('u', trade_id, 3)
        self.assertEqual((await self.confirm('v', trade_id, 3, now=1300))['status'], 'completed')
        encounters = await self.rows('SELECT * FROM encounters')
        self.assertEqual({row['encounter_id']: row['acknowledged_at'] for row in encounters},
                         {'e_mon': 1300, 'e_theirs': 50, 'e_other': None})

    async def test_trade_moves_no_candy_stardust_or_items(self):
        for user in ('u', 'v'):
            await self.conn.execute('UPDATE profiles SET stardust=? WHERE profile_id=?',
                                    (500 if user == 'u' else 900, self.ids[user]))
            await self.conn.execute('INSERT INTO candy VALUES (?,1,?)', (self.ids[user], 3 if user == 'u' else 5))
            await self.conn.execute("INSERT INTO inventory VALUES (?,'poke_ball',?)", (self.ids[user], 7))
        trade_id = await self.ready()
        tables = ('candy', 'inventory', 'action_receipts', 'resource_ledger')
        before = {table: await self.rows(f'SELECT * FROM {table} ORDER BY 1,2') for table in tables}
        stardust = await self.rows('SELECT profile_id,stardust FROM profiles ORDER BY 1')
        await self.confirm('u', trade_id, 2)
        self.assertEqual((await self.confirm('v', trade_id, 2))['status'], 'completed')
        self.assertEqual({table: await self.rows(f'SELECT * FROM {table} ORDER BY 1,2') for table in tables}, before)
        self.assertEqual(await self.rows('SELECT profile_id,stardust FROM profiles ORDER BY 1'), stardust)

    async def test_full_storage_members_can_still_swap_one_for_one(self):
        for user in ('u', 'v'):
            for index in range(249):
                await self.pokemon(f'{user}{index:03}', user=user)
        trade_id = await self.ready()
        owned = "SELECT count(*) FROM pokemon WHERE profile_id=? AND state='owned'"
        for user in ('u', 'v'):
            self.assertEqual(await self.scalar('SELECT storage_limit FROM profiles WHERE profile_id=?',
                                               (self.ids[user],)), 250)
            self.assertEqual(await self.scalar(owned, (self.ids[user],)), 250)
        await self.confirm('u', trade_id, 2)
        self.assertEqual((await self.confirm('v', trade_id, 2))['status'], 'completed')
        for user in ('u', 'v'):
            self.assertEqual(await self.scalar(owned, (self.ids[user],)), 250)

    async def test_old_owner_actions_on_traded_pokemon_are_stale(self):
        storage = importlib.import_module('pokewalker.services.storage')
        trade_id = await self.ready()
        await self.confirm('u', trade_id, 2)
        await self.confirm('v', trade_id, 2)
        self.assertIsNone(await storage.detail(self.conn, self.ids['u'], 'mon'))
        self.assertIsNone(await self.writer.run(lambda conn: storage.set_favorite(conn, self.ids['u'], 'mon', 1, 1)))
        profile = (await self.rows("SELECT * FROM profiles WHERE user_id='u'"))[0]
        pokemon = (await self.rows("SELECT * FROM pokemon WHERE pokemon_uid='mon'"))[0]
        self.assertEqual(self.svc().tradable_reason(_NEUTRAL, pokemon, profile), 'not_owned')
        rows, _, _ = await self.svc().eligible_page(self.conn, self.ids['u'], 0, 1200)
        self.assertEqual([row['pokemon_uid'] for row in rows], ['theirs'])
        self.assertEqual((await storage.detail(self.conn, self.ids['v'], 'mon'))['revision'], 1)
        self.assertEqual((await self.writer.run(
            lambda conn: storage.set_favorite(conn, self.ids['v'], 'mon', 1, 1)))['favorite'], 1)


    # T3 review: an offer refusal keeps its reason when the Pokemon is also special (OD6).

    async def test_offer_refuses_shiny_favorite_and_legendary_companion(self):
        await self.pokemon('shinyfav', shiny=1, favorite=1)
        await self.pokemon('legend', pokemon_id=144)
        await self.conn.execute("UPDATE profiles SET companion_uid='legend' WHERE user_id='u'")
        for uid, reason in (('shinyfav', 'favorite'), ('legend', 'companion')):
            with self.subTest(uid=uid):
                await self.conn.execute('DELETE FROM trades')
                await self.refused_offer(reason, uid)

    # T5: Pokedex and milestone credit on receipt, view and prune.

    async def dex(self, user):
        return {row['pokemon_id']: (row['seen_at'], row['caught_at'])
                for row in await self.rows('SELECT * FROM pokedex WHERE profile_id=?', (self.ids[user],))}

    async def credit(self):
        return {table: await self.rows(f'SELECT * FROM {table} ORDER BY 1,2')
                for table in ('pokedex', 'milestone_awards', 'inbox_items')}

    async def swap(self, a, b, mine, theirs, now=1000):
        """A completed trade where a gives mine and b gives theirs; it completes at now+200."""
        trade_id = (await self.open(a, b, now=now))['trade_id']
        self.assertEqual((await self.open(b, a, now=now + 50))['status'], 'joined')
        self.assertEqual((await self.offer(a, trade_id, mine, now=now + 100))['status'], 'offered')
        revision = (await self.offer(b, trade_id, theirs, now=now + 100))['revision']
        self.assertEqual((await self.confirm(a, trade_id, revision, now=now + 200))['status'], 'waiting')
        self.assertEqual((await self.confirm(b, trade_id, revision, now=now + 200))['status'], 'completed')
        return trade_id

    def bundle_lines(self, user, milestone_id, category, now):
        bundle = CONTENT['milestones']['bundles'][CONTENT['milestones'][category]['bundle']]
        return sorted((self.ids[user], milestone_id, 'stardust' if item == 'stardust' else 'item',
                       None if item == 'stardust' else item, quantity, now) for item, quantity in bundle.items())

    async def inbox(self):
        return sorted((row['profile_id'], row['milestone_id'], row['resource'], row['resource_id'],
                       row['remaining'], row['created_at'])
                      for row in await self.rows('SELECT * FROM inbox_items'))

    async def test_receiver_registers_species_caught(self):
        await self.pokemon('theirs', user='v', pokemon_id=4)
        await self.swap('u', 'v', 'mon', 'theirs')
        self.assertEqual(await self.dex('u'), {4: (1200, 1200)})
        self.assertEqual(await self.dex('v'), {1: (1200, 1200)})

    async def test_existing_seen_gains_caught_and_keeps_seen_at(self):
        await self.conn.execute('INSERT INTO pokedex(profile_id,pokemon_id,seen_at) VALUES (?,4,50)', (self.ids['u'],))
        await self.pokemon('theirs', user='v', pokemon_id=4)
        await self.swap('u', 'v', 'mon', 'theirs')
        self.assertEqual(await self.dex('u'), {4: (50, 1200)})

    async def test_existing_caught_at_unchanged(self):
        await self.conn.execute('INSERT INTO pokedex VALUES (?,4,50,60)', (self.ids['u'],))
        await self.pokemon('theirs', user='v', pokemon_id=4)
        await self.swap('u', 'v', 'mon', 'theirs')
        self.assertEqual(await self.dex('u'), {4: (50, 60)})

    async def test_form_folds_to_species(self):
        await self.pokemon('alolan', user='v', pokemon_id=10091, form_id=10193)
        await self.swap('u', 'v', 'mon', 'alolan')
        self.assertEqual(await self.dex('u'), {19: (1200, 1200)})

    async def test_completing_milestone_awards_once_to_inbox_in_same_commit(self):
        milestones = importlib.import_module('pokewalker.services.milestones')
        await self.conn.execute("UPDATE pokemon SET pokemon_id=144 WHERE pokemon_uid='mon'")
        trade_id = await self.ready()
        await self.conn.execute("UPDATE pokemon SET pokemon_id=151 WHERE pokemon_uid='theirs'")
        self.assertEqual((await self.confirm('u', trade_id, 2))['status'], 'waiting')
        real = milestones.check_and_award

        async def award_then_fail(conn, profile_id, content, now):
            await real(conn, profile_id, content, now)
            raise RuntimeError('award failed after writing')

        before = {**await self.state(), **await self.credit()}
        with patch.object(milestones, 'check_and_award', award_then_fail), self.assertRaises(RuntimeError):
            await self.confirm('v', trade_id, 2, now=1300)
        self.assertEqual({**await self.state(), **await self.credit()}, before, 'credit and swap share one job')
        self.assertEqual(await self.confirm('v', trade_id, 2, now=1300), {'status': 'completed', 'trade_id': trade_id})
        self.assertEqual(sorted(tuple(row.values()) for row in await self.rows('SELECT * FROM milestone_awards')),
                         sorted([(self.ids['v'], 'first_legendary:first', 1300),
                                 (self.ids['u'], 'first_mythical:first', 1300)]))
        self.assertEqual(await self.inbox(), sorted(
            self.bundle_lines('v', 'first_legendary:first', 'first_legendary', 1300)
            + self.bundle_lines('u', 'first_mythical:first', 'first_mythical', 1300)))
        after = await self.credit()
        self.assertEqual(await self.confirm('v', trade_id, 2, now=1400), {'status': 'completed', 'trade_id': trade_id})
        self.assertEqual(await self.credit(), after)

    async def test_giver_pokedex_entry_never_removed(self):
        await self.conn.execute('INSERT INTO pokedex VALUES (?,1,10,20)', (self.ids['u'],))
        await self.conn.execute('INSERT INTO pokedex VALUES (?,4,30,40)', (self.ids['v'],))
        await self.pokemon('theirs', user='v', pokemon_id=4)
        await self.swap('u', 'v', 'mon', 'theirs')
        self.assertEqual(await self.dex('u'), {1: (10, 20), 4: (1200, 1200)})
        self.assertEqual(await self.dex('v'), {1: (1200, 1200), 4: (30, 40)})

    async def test_ping_pong_awards_each_profile_at_most_once(self):
        await self.pokemon('legend', pokemon_id=144)
        await self.pokemon('plain', user='v')
        await self.swap('u', 'v', 'legend', 'plain', now=1000)
        await self.swap('v', 'u', 'legend', 'plain', now=1200 + 86400)
        await self.swap('u', 'v', 'legend', 'plain', now=1400 + 2 * 86400)
        self.assertEqual((await self.rows("SELECT profile_id FROM pokemon WHERE pokemon_uid='legend'"))[0]['profile_id'],
                         self.ids['v'])
        self.assertEqual(sorted(tuple(row.values()) for row in await self.rows('SELECT * FROM milestone_awards')),
                         sorted([(self.ids['v'], 'first_legendary:first', 1200),
                                 (self.ids['u'], 'first_legendary:first', 87800)]))
        self.assertEqual(await self.inbox(), sorted(
            self.bundle_lines('v', 'first_legendary:first', 'first_legendary', 1200)
            + self.bundle_lines('u', 'first_legendary:first', 'first_legendary', 87800)))

    async def test_refused_execution_writes_no_pokedex_or_awards(self):
        svc = self.svc()
        await self.conn.execute("UPDATE pokemon SET pokemon_id=144 WHERE pokemon_uid='mon'")
        trade_id = await self.ready()
        empty = {'pokedex': [], 'milestone_awards': [], 'inbox_items': []}
        self.assertEqual((await self.confirm('u', trade_id, 2))['status'], 'waiting')
        self.assertEqual(await self.credit(), empty)
        await self.conn.execute("UPDATE pokemon SET favorite=1 WHERE pokemon_uid='theirs'")
        self.assertEqual(await self.confirm('v', trade_id, 2), {'status': 'offer_invalid', 'side': 1,
                                                                 'reason': 'favorite'})
        self.assertEqual(await self.credit(), empty)
        await self.conn.execute("UPDATE pokemon SET favorite=0 WHERE pokemon_uid='theirs'")
        revision = (await self.offer('v', trade_id, 'theirs'))['revision']
        self.assertEqual((await self.confirm('u', trade_id, revision))['status'], 'waiting')
        await self.conn.execute("UPDATE profiles SET last_trade_at=1150 WHERE user_id='v'")
        with patch.object(svc, 'cap_left', return_value=0), self.assertRaises(RuntimeError):
            await self.confirm('v', trade_id, revision)
        self.assertEqual(await self.credit(), empty)
        self.assertEqual((await self.confirm('v', trade_id, revision))['status'], 'capped')
        self.assertEqual(await self.credit(), empty)

    async def view(self, user, trade_id, now=1150, session=None):
        multipliers = importlib.import_module('content.balance').load_table('cpm')['multipliers']
        return await self.writer.run(lambda conn: self.svc().view(
            conn, session or self.session(user), trade_id, now, CONTENT, multipliers))

    async def offered(self, uid):
        storage = importlib.import_module('pokewalker.services.storage')
        multipliers = importlib.import_module('content.balance').load_table('cpm')['multipliers']
        row = (await self.rows('SELECT * FROM pokemon WHERE pokemon_uid=?', (uid,)))[0]
        return storage.stats(CONTENT, row, multipliers)

    async def test_view_snapshot_detached_participant_only_with_special_flags(self):
        await self.pokemon('legend', pokemon_id=144, shiny=1)
        await self.pokemon('starter', user='v', pokemon_id=4)
        await self.conn.execute("UPDATE pokemon SET origin='starter' WHERE pokemon_uid='starter'")
        trade_id = (await self.open('u', 'v'))['trade_id']
        self.assertEqual(await self.view('u', trade_id), {
            'trade_id': trade_id, 'state': 'open', 'revision': 0, 'expires_at': 1900, 'my_side': 0,
            'partner_user_id': 'v', 'partner_joined': False, 'mine': None, 'theirs': None,
            'my_confirmed': False, 'partner_confirmed': False, 'received': None})
        stale = {**self.session('u'), 'profile_id': self.ids['v']}
        for user, session in (('v', None), ('w', None), ('x', None), ('u', stale)):
            with self.subTest(user=user, stale=session is not None):
                self.assertIsNone(await self.view(user, trade_id, session=session))
        await self.open('v', 'u', now=1050)
        await self.offer('u', trade_id, 'legend')
        await self.offer('v', trade_id, 'starter')
        await self.confirm('u', trade_id, 2, now=1150)
        legend, starter = await self.offered('legend'), await self.offered('starter')
        mine = await self.view('u', trade_id)
        self.assertEqual(json.loads(json.dumps(mine)), mine, 'plain values only')
        self.assertEqual(mine, {
            'trade_id': trade_id, 'state': 'open', 'revision': 2, 'expires_at': 2050, 'my_side': 0,
            'partner_user_id': 'v', 'partner_joined': True,
            'mine': {**legend, 'special': {'shiny': True, 'legendary': True, 'mythical': False, 'starter': False}},
            'theirs': {**starter, 'special': {'shiny': False, 'legendary': False, 'mythical': False,
                                              'starter': True}},
            'my_confirmed': True, 'partner_confirmed': False, 'received': None})
        theirs = await self.view('v', trade_id)
        self.assertEqual((theirs['my_side'], theirs['partner_user_id'], theirs['mine']['pokemon']['pokemon_uid'],
                          theirs['my_confirmed'], theirs['partner_confirmed']), (1, 'u', 'starter', False, True))
        await self.conn.execute("UPDATE pokemon SET level_x2=40 WHERE pokemon_uid='legend'")
        self.assertEqual(mine['mine']['pokemon']['level_x2'], 20, 'a snapshot is detached from the database')
        self.assertEqual((await self.view('u', trade_id, now=2050))['state'], 'expired')
        self.assertEqual((await self.trade(trade_id))['state'], 'open', 'view writes nothing')
        await self.conn.execute("UPDATE pokemon SET level_x2=20 WHERE pokemon_uid='legend'")
        self.assertEqual((await self.confirm('v', trade_id, 2, now=1300))['status'], 'completed')
        done = {user: await self.view(user, trade_id, now=1400) for user in ('u', 'v')}
        self.assertEqual((done['u']['state'], done['u']['received']),
                         ('completed', {'name': 'Charmander', 'cp': starter['cp']}))
        self.assertEqual(done['v']['received'], {'name': 'Articuno', 'cp': legend['cp']})
        self.assertIsNone(await self.view('w', trade_id, now=1400))

    async def prune(self, now):
        return await self.writer.run(lambda conn: self.svc().prune(conn, now))

    async def test_prune_expires_stale_and_deletes_ended_after_a_day_keeps_cap(self):
        with self.assertRaises(RuntimeError):
            await self.svc().prune(self.conn, 1000)
        await self.pokemon('theirs', user='v')
        done = await self.swap('u', 'v', 'mon', 'theirs')
        idle = (await self.open('w', 'y', now=1000))['trade_id']
        states = lambda: self.rows('SELECT trade_id,state,ended_at FROM trades ORDER BY created_at,trade_id')
        await self.prune(1899)
        self.assertEqual({row['trade_id']: (row['state'], row['ended_at']) for row in await states()},
                         {done: ('completed', 1200), idle: ('open', None)})
        await self.prune(1900)
        self.assertEqual({row['trade_id']: (row['state'], row['ended_at']) for row in await states()},
                         {done: ('completed', 1200), idle: ('expired', 1900)})
        self.assertEqual([side['open'] for side in await self.sides(idle)], [0, 0])
        await self.prune(1200 + 86399)
        self.assertEqual(len(await states()), 2)
        await self.prune(1200 + 86400)
        self.assertEqual([row['trade_id'] for row in await states()], [idle])
        self.assertEqual(await self.scalar('SELECT count(*) FROM trade_sides WHERE trade_id=?', (done,)), 0)
        self.assertEqual(await self.last_trade(), {'u': 1200, 'v': 1200, 'w': None, 'y': None, 'x': None})
        self.assertEqual(await self.open('w', 'u', now=1200 + 86399), {'status': 'partner_capped'})
        await self.prune(1900 + 86400)
        self.assertEqual(await states(), [])
        self.assertEqual(await self.scalar('SELECT count(*) FROM trade_sides'), 0)
        self.assertEqual((await self.last_trade())['u'], 1200)


if __name__ == '__main__':
    unittest.main()
