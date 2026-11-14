"""Item grants, conversion and durable count-model effects."""

from uuid import uuid4

from content.balance import limits, load_table
from pokewalker.db import with_receipt
from pokewalker.services.profiles import get_profile, queue_size, restrictions, session_owner


RARE = tuple(limits()['rare_pockets'])


async def bag_units(conn, profile_id):
    placeholders = ','.join('?' for _ in RARE)
    async with conn.execute("SELECT COALESCE(sum(quantity),0) FROM inventory WHERE profile_id=? "
                            f"AND item_id NOT IN ({placeholders})", (profile_id, *RARE)) as cursor:
        return (await cursor.fetchone())[0]


async def grant(conn, profile_id, item_id, quantity):
    if not conn.in_transaction:
        raise RuntimeError('Item grants require an active writer transaction')
    if type(quantity) is not int or quantity <= 0 or (item_id in RARE and quantity != 1):
        raise ValueError('Item packs require a positive integer quantity; rare packs contain one')
    async with conn.execute('SELECT bag_limit FROM profiles WHERE profile_id=?', (profile_id,)) as cursor:
        bag_limit = (await cursor.fetchone())['bag_limit']
    outcome, dust = 'granted', 0
    if item_id == 'stardust':
        outcome, dust = 'stardust', quantity
    elif item_id in RARE:
        async with conn.execute('SELECT quantity FROM inventory WHERE profile_id=? AND item_id=?',
                                (profile_id, item_id)) as cursor:
            held = await cursor.fetchone()
        if held is not None and held[0] > 0:
            outcome, dust = 'duplicate_rare', 500
    elif await bag_units(conn, profile_id) + quantity > bag_limit:
        outcome, dust = 'overflow', 10
    if dust:
        await conn.execute('UPDATE profiles SET stardust=stardust+? WHERE profile_id=?', (dust, profile_id))
    else:
        await conn.execute('INSERT INTO inventory VALUES (?,?,?) ON CONFLICT(profile_id,item_id) '
                           'DO UPDATE SET quantity=quantity+excluded.quantity', (profile_id, item_id, quantity))
    return outcome, dust


def resolve_item(rng, item_id, quantity, content):
    if item_id == 'evolution_item':
        kinds = content['evolution_items']
        return (rng.choice(kinds)['id'], quantity) if kinds else ('stardust', 100)
    return item_id, quantity


def roll_find(rng):
    rows = load_table('find_table')['rows']
    return rng.choices(rows, weights=[row['weight'] for row in rows], k=1)[0]


async def apply_finds(conn, profile, awarded_c, at, message_id, rng, content):
    from pokewalker.services.stepping import advance_meter

    if not conn.in_transaction:
        raise RuntimeError('Finds require an active writer transaction')
    pid, mid = profile['profile_id'], str(message_id)
    key = f'find:{mid}'
    rules = load_table('step_rules')['rules']
    async with conn.execute('SELECT count(*) FROM finds WHERE profile_id=? AND created_at>? AND created_at<=?',
                            (pid, at - 3600, at)) as cursor:
        count = (await cursor.fetchone())[0]
    meter, triggers = advance_meter(profile['find_meter_c'], awarded_c, rules['find_step_hundredths'],
                                    frozen=count >= rules['finds_per_rolling_hour'])
    async with conn.execute('SELECT 1 FROM action_receipts WHERE key=?', (key,)) as cursor:
        replay = await cursor.fetchone()
    if not triggers and replay is None:
        return meter
    if count + 1 >= rules['finds_per_rolling_hour']:
        meter = 0

    async def compute(conn):
        selected = roll_find(rng)
        item, quantity = resolve_item(rng, selected['item'], selected['quantity'], content)
        if item == 'stardust':
            quantity = await boost(conn, pid, quantity)
        outcome, dust = await grant(conn, pid, item, quantity)
        await conn.execute('INSERT INTO finds(profile_id,message_id,item_id,quantity,outcome,created_at) '
                           'VALUES (?,?,?,?,?,?)', (pid, mid, item, quantity, outcome, at))
        reason = {'overflow': 'find_overflow', 'duplicate_rare': 'find_duplicate_rare'}.get(outcome, 'find')
        return {'meter_c': meter, 'item': item, 'quantity': quantity, 'outcome': outcome}, [
            {'profile_id': pid, 'resource': 'stardust' if dust else 'item',
             'resource_id': None if dust else item, 'delta': dust or quantity, 'reason': reason}]

    result = await with_receipt(conn, key, 'find', compute, profile_id=pid)
    return result['meter_c']


async def recent_finds(conn, profile_id):
    async with conn.execute('SELECT * FROM finds WHERE profile_id=? ORDER BY created_at DESC,find_id DESC LIMIT 3',
                            (profile_id,)) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


def roll_checkin(rng):
    rows = load_table('checkin_table')['rows']
    return rng.choices(rows, weights=[row['weight'] for row in rows], k=1)[0]


async def checkin(conn, guild_id, user_id, now, rng, content=None):
    if not conn.in_transaction:
        raise RuntimeError('Check-in requires an active writer transaction')
    profile = await get_profile(conn, guild_id, user_id)
    if profile is None:
        return {'status': 'unenrolled'}
    flags = await restrictions(conn, guild_id, user_id)
    if flags.excluded:
        return {'status': 'excluded'}
    if flags.paused:
        return {'status': 'paused', 'until': flags.paused_until.isoformat() if flags.paused_until else None}
    last = profile['last_checkin_at']
    if last is not None and last > now - 3600:
        return {'status': 'too_early', 'seconds_left': last + 3600 - now}
    pid = profile['profile_id']

    async def compute(conn):
        outcomes, lines = [], []
        outcome, dust = await grant(conn, pid, 'poke_ball', 1)
        outcomes.append({'item': 'poke_ball', 'quantity': 1, 'outcome': outcome, 'dust': dust})
        selected = roll_checkin(rng)
        item, quantity = selected['item'], selected['quantity']
        outcome, dust = await grant(conn, pid, item, quantity)
        outcomes.append({'item': item, 'quantity': quantity, 'outcome': outcome, 'dust': dust})
        for entry in outcomes:
            lines.append({'profile_id': pid, 'resource': 'stardust' if entry['dust'] else 'item',
                          'resource_id': None if entry['dust'] else entry['item'],
                          'delta': entry['dust'] or entry['quantity'], 'reason': 'checkin'})
        await conn.execute('UPDATE profiles SET last_checkin_at=? WHERE profile_id=?', (now, pid))
        result = {'status': 'granted', 'outcomes': outcomes}
        if content is not None:
            # Deferred: stepping imports this module.
            from pokewalker.services.stepping import spawn_encounter
            if await queue_size(conn, pid) < limits()['encounter_queue']:
                result.update(encounter='queued',
                              encounter_id=await spawn_encounter(conn, profile, content, rng, now))
            else:
                result['encounter'] = 'queue_full'
        return result, lines

    return await with_receipt(conn, f'checkin:{pid}:{now}', 'checkin', compute, profile_id=pid)


def rate_for(item_id, content):
    rates = load_table('conversion_rates')['stardust_per_unit']
    if item_id in rates:
        return rates[item_id]
    if content is not None and any(kind['id'] == item_id for kind in content['evolution_items']):
        return rates['evolution_item']
    return None


async def convert(conn, session, item_id, quantity, content=None):
    if not conn.in_transaction:
        raise RuntimeError('Conversion requires an active writer transaction')
    _, refusal = await session_owner(conn, session)
    if refusal is not None:
        return refusal
    rate = rate_for(item_id, content)
    if rate is None or type(quantity) is not int or quantity < 1 or (item_id in RARE and quantity != 1):
        return {'status': 'refused'}
    pid, key = session['profile_id'], f"convert:{session['session_id']}:{session['revision']}"
    async with conn.execute('SELECT 1 FROM action_receipts WHERE key=?', (key,)) as cursor:
        replay = await cursor.fetchone()
    if replay is None:
        async with conn.execute('SELECT quantity FROM inventory WHERE profile_id=? AND item_id=?',
                                (pid, item_id)) as cursor:
            held = await cursor.fetchone()
        if held is None or quantity > held['quantity']:
            return {'status': 'changed'}

    async def compute(conn):
        dust = rate * quantity
        await conn.execute('UPDATE inventory SET quantity=quantity-? WHERE profile_id=? AND item_id=?',
                           (quantity, pid, item_id))
        await conn.execute('UPDATE profiles SET stardust=stardust+? WHERE profile_id=?', (dust, pid))
        lines = [{'profile_id': pid, 'resource': resource, 'resource_id': resource_id,
                  'delta': delta, 'reason': 'convert'} for resource, resource_id, delta in
                 (('item', item_id, -quantity), ('stardust', None, dust))]
        return {'item': item_id, 'quantity': quantity, 'stardust': dust}, lines

    return await with_receipt(conn, key, 'convert', compute, profile_id=pid)


async def buy_evolution_item(conn, session, kind, now, content):
    return await _buy(conn, session, kind, load_table('evolution')['item_price_stardust'],
                      known=lambda: any(item['id'] == kind for item in content['evolution_items']))


async def buy_vitamin(conn, session, now):
    return await _buy(conn, session, 'vitamin', load_table('conversion_rates')['purchase_stardust']['vitamin'])


async def _buy(conn, session, kind, price, known=None):
    """One Stardust-priced Bag item per session revision, shared by evolution items and Vitamins."""
    if not conn.in_transaction:
        raise RuntimeError('Purchases require an active writer transaction')
    profile, refusal = await session_owner(conn, session)
    if refusal is not None:
        return refusal
    pid, key = session['profile_id'], f"buy:{session['session_id']}:{session['revision']}"
    async with conn.execute('SELECT 1 FROM action_receipts WHERE key=?', (key,)) as cursor:
        replay = await cursor.fetchone()
    if replay is None:
        if known is not None and not known():
            return {'status': 'refused'}
        if profile['stardust'] < price:
            return {'status': 'insufficient'}
        if await bag_units(conn, pid) + 1 > profile['bag_limit']:
            return {'status': 'bag_full'}

    async def compute(conn):
        await conn.execute('UPDATE profiles SET stardust=stardust-? WHERE profile_id=?', (price, pid))
        await conn.execute('INSERT INTO inventory VALUES (?,?,1) ON CONFLICT(profile_id,item_id) '
                           'DO UPDATE SET quantity=quantity+1', (pid, kind))
        lines = [{'profile_id': pid, 'resource': resource, 'resource_id': resource_id,
                  'delta': delta, 'reason': 'buy'} for resource, resource_id, delta in
                 (('stardust', None, -price), ('item', kind, 1))]
        return {'item': kind, 'quantity': 1, 'stardust': price}, lines

    return await with_receipt(conn, key, 'buy', compute, profile_id=pid)


def trade_up_rule(item_id):
    """The conversion_rates trade_up rule consuming item_id, or None."""
    return next((rule for rule in load_table('conversion_rates')['trade_up'] if rule['from'] == item_id), None)


async def trade_up(conn, session, item_id, outputs):
    if not conn.in_transaction:
        raise RuntimeError('Trade-ups require an active writer transaction')
    _, refusal = await session_owner(conn, session)
    if refusal is not None:
        return refusal
    rule = trade_up_rule(item_id)
    if rule is None or type(outputs) is not int or outputs < 1:
        return {'status': 'refused'}
    pid, key = session['profile_id'], f"tradeup:{session['session_id']}:{session['revision']}"
    consumed, target = rule['input_per_output'] * outputs, rule['to']
    async with conn.execute('SELECT 1 FROM action_receipts WHERE key=?', (key,)) as cursor:
        replay = await cursor.fetchone()
    if replay is None:
        async with conn.execute('SELECT quantity FROM inventory WHERE profile_id=? AND item_id=?',
                                (pid, item_id)) as cursor:
            held = await cursor.fetchone()
        if held is None or held['quantity'] < consumed:
            return {'status': 'insufficient'}

    async def compute(conn):
        await conn.execute('UPDATE inventory SET quantity=quantity-? WHERE profile_id=? AND item_id=?',
                           (consumed, pid, item_id))
        await conn.execute('INSERT INTO inventory VALUES (?,?,?) ON CONFLICT(profile_id,item_id) '
                           'DO UPDATE SET quantity=quantity+excluded.quantity', (pid, target, outputs))
        lines = [{'profile_id': pid, 'resource': 'item', 'resource_id': resource_id,
                  'delta': delta, 'reason': 'trade_up'} for resource_id, delta in
                 ((item_id, -consumed), (target, outputs))]
        return {'from': item_id, 'to': target, 'consumed': consumed, 'produced': outputs}, lines

    return await with_receipt(conn, key, 'trade_up', compute, profile_id=pid)


async def _active_encounter_effect(conn, profile_id, kind):
    async with conn.execute('SELECT effect_id FROM active_effects WHERE profile_id=? AND kind=? '
                            'AND remaining_encounters>0', (profile_id, kind)) as cursor:
        row = await cursor.fetchone()
    return row['effect_id'] if row is not None else None


async def active_lure(conn, profile_id):
    return await _active_encounter_effect(conn, profile_id, 'shiny_lure')


async def active_mirror(conn, profile_id):
    return await _active_encounter_effect(conn, profile_id, 'companion_mirror')


# D64: the Shiny Charm is not an inventory item; earning this milestone grants it for good.
SHINY_CHARM_MILESTONE = 'pokedex:100'


async def shiny_charm(conn, profile_id):
    """'on', 'off', or None when the player has not completed the Pokédex."""
    async with conn.execute('SELECT p.shiny_charm_off FROM profiles p JOIN milestone_awards m '
                            'ON m.profile_id=p.profile_id AND m.milestone_id=? WHERE p.profile_id=?',
                            (SHINY_CHARM_MILESTONE, profile_id)) as cursor:
        row = await cursor.fetchone()
    return None if row is None else ('off' if row[0] else 'on')


async def _activate_effect(conn, session, now, *, kind, action, label, active, remaining):
    """Spend one `kind` to start an effect unless `active(conn, pid)` says one is already running."""
    if not conn.in_transaction:
        raise RuntimeError(f'{label} activation requires an active writer transaction')
    _, refusal = await session_owner(conn, session)
    if refusal is not None:
        return refusal
    pid, key = session['profile_id'], f"{action}:{session['session_id']}:{session['revision']}"

    async def compute(conn):
        if await active(conn, pid):
            return {'status': 'already_active'}, []
        async with conn.execute('SELECT quantity FROM inventory WHERE profile_id=? AND item_id=?',
                                (pid, kind)) as cursor:
            held = await cursor.fetchone()
        if held is None or held['quantity'] < 1:
            return {'status': 'missing'}, []
        effect = {'effect_id': str(uuid4()), 'profile_id': pid, 'kind': kind,
                  'starts_at': now, 'expires_at': None, 'receipt_key': key,
                  'remaining_encounters': 0, 'remaining_rewards': 0, **remaining}
        await conn.execute('UPDATE inventory SET quantity=quantity-1 WHERE profile_id=? AND item_id=?', (pid, kind))
        await conn.execute('INSERT INTO active_effects(effect_id,profile_id,kind,starts_at,expires_at,receipt_key,'
                           'remaining_encounters,remaining_rewards) VALUES (?,?,?,?,?,?,?,?)', tuple(effect.values()))
        return effect, [{'profile_id': pid, 'resource': 'item', 'resource_id': kind,
                         'delta': -1, 'reason': f'{action}_activate'}]

    return await with_receipt(conn, key, action, compute, profile_id=pid)


async def _encounter_effect_active(conn, pid):
    """One encounter booster (Shiny Lure or Companion Mirror) at a time, per profile."""
    async with conn.execute('SELECT 1 FROM active_effects WHERE profile_id=? AND remaining_encounters>0',
                            (pid,)) as cursor:
        return await cursor.fetchone() is not None


async def activate_lure(conn, session, now):
    return await _activate_effect(conn, session, now, kind='shiny_lure', action='lure', label='Lure',
                                  active=_encounter_effect_active,
                                  remaining={'remaining_encounters': load_table('catch')['rules']['lure_encounters']})


async def activate_mirror(conn, session, now):
    return await _activate_effect(conn, session, now, kind='companion_mirror', action='mirror',
                                  label='Companion Mirror', active=_encounter_effect_active,
                                  remaining={'remaining_encounters': load_table('catch')['rules']['mirror_encounters']})


async def active_star_piece(conn, profile_id):
    async with conn.execute("SELECT effect_id FROM active_effects WHERE profile_id=? AND kind='star_piece' "
                            'AND remaining_rewards>0', (profile_id,)) as cursor:
        row = await cursor.fetchone()
    return row['effect_id'] if row is not None else None


async def activate_star_piece(conn, session, now):
    async def active(conn, pid):
        return await active_star_piece(conn, pid) is not None

    return await _activate_effect(conn, session, now, kind='star_piece', action='star_piece', label='Star Piece',
                                  active=active,
                                  remaining={'remaining_rewards': load_table('evolution')['star_piece']['rewards']})


async def boost(conn, profile_id, amount):
    if not conn.in_transaction:
        raise RuntimeError('Stardust boosts require an active writer transaction')
    effect_id = await active_star_piece(conn, profile_id)
    if effect_id is None:
        return amount
    await conn.execute('UPDATE active_effects SET remaining_rewards=remaining_rewards-1 WHERE effect_id=?',
                       (effect_id,))
    star_piece = load_table('evolution')['star_piece']
    return amount * star_piece['multiplier_numerator'] // star_piece['multiplier_denominator']
