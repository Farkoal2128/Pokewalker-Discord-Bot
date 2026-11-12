"""C3 trading service: eligibility, open/join/reopen, cap, ping window, offer, cancel."""

import importlib
import json
from pathlib import Path
import unittest

from pokewalker import db
import test_db


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
        rows, eligible, owned = await self.svc().eligible_page(self.conn, self.ids['u'], 0)
        self.assertEqual(([row['pokemon_uid'] for row in rows], eligible, owned), (expected, 9, 12))
        await self.pokemon('p12', caught_at=50)
        await self.pokemon('p13', caught_at=50)
        rows, eligible, owned = await self.svc().eligible_page(self.conn, self.ids['u'], 10)
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


if __name__ == '__main__':
    unittest.main()
