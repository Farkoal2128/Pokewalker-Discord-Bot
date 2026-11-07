"""D59 completion and lossless inbox delivery inside the existing writer."""

from content.balance import limits
from pokewalker.db import with_receipt
from pokewalker.services import capacity, items, profiles


def _evaluated(caught_species_ids, content):
    caught = set(caught_species_ids) & set(map(int, content['species']))
    milestones = content['milestones']
    result = []

    def add(category, key, entry, progress, complete, unit):
        milestone_id = f'{category}:{key}'
        result.append({'milestone_id': milestone_id, 'category': category, 'entry': entry,
                       'progress': f'{progress[0]}/{progress[1]} {unit}', 'complete': complete})

    for entry in milestones.get('pokedex', []):
        species_count = len(content['species'])
        required = (entry['percent'] * species_count + 99) // 100
        count = len(caught)
        add('pokedex', entry['percent'], entry, (count, required), bool(species_count) and
            count * 100 >= entry['percent'] * species_count, 'species')
    for category, key in (('starter_trios', 'generation'), ('regions', 'generation'),
                          ('legendary_groups', 'id'), ('mythical_sets', 'generation'),
                          ('extra_bundle_lines', 'id')):
        for entry in milestones.get(category, []):
            species = set(entry['species_ids'])
            count = len(species & caught)
            add(category, entry[key], entry, (count, len(species)), bool(species) and species <= caught, 'species')
    for category in ('all_starters', 'all_legendaries', 'all_mythicals'):
        if category in milestones:
            entry = milestones[category]
            species = set(entry['species_ids'])
            count = len(species & caught)
            add(category, 'all', entry, (count, len(species)), bool(species) and species <= caught, 'species')
    for category, flag in (('first_legendary', 'is_legendary'), ('first_mythical', 'is_mythical')):
        if category in milestones:
            complete = any(content['species'][str(s)].get(flag, False) for s in caught)
            add(category, 'first', milestones[category], (int(complete), 1), complete, 'catch')
    for entry in milestones.get('ultra_beast_first_catches', []):
        complete = entry['species_id'] in caught
        add('ultra_beast_first_catches', entry['species_id'], entry, (int(complete), 1), complete, 'catch')
    for entry in milestones.get('evolution_lines', {}).get('families', []):
        species = set(entry['species_ids'])
        count = len(species & caught)
        add('evolution_lines', entry['family_id'], entry, (count, len(species)),
            bool(species) and species <= caught, 'species')
    return result


def catalog(caught_species_ids, earned, content):
    if isinstance(earned, dict):
        earned_at = earned
    else:
        earned_at = {milestone_id: None for milestone_id in earned}
    rows = []
    for row in _evaluated(caught_species_ids, content):
        earned_time = earned_at.get(row['milestone_id'])
        rows.append({**row, 'bundle': row['entry'].get('bundle'), 'earned_at': earned_time,
                     'earned': row['milestone_id'] in earned_at})
    return rows


def due(caught_species_ids, earned_ids, content):
    milestones = content['milestones']
    earned = set(earned_ids)
    result = []
    for row in _evaluated(caught_species_ids, content):
        if not row['complete'] or row['milestone_id'] in earned:
            continue
        entry = row['entry']
        if row['category'] == 'evolution_lines':
            lines = [{'resource': 'candy', 'resource_id': str(entry['family_id']), 'quantity': entry['family_candy']},
                     {'resource': 'item', 'resource_id': 'ultra_ball', 'quantity': entry['ultra_ball']},
                     {'resource': 'stardust', 'resource_id': None, 'quantity': entry['stardust']}]
        else:
            lines = [{'resource': 'stardust' if item == 'stardust' else 'item',
                      'resource_id': None if item == 'stardust' else item, 'quantity': quantity}
                     for item, quantity in milestones['bundles'][entry['bundle']].items()]
        result.append((row['milestone_id'], lines))
    return result


async def list_for_profile(conn, profile_id, content):
    async with conn.execute('SELECT pokemon_id FROM pokedex WHERE profile_id=? AND caught_at IS NOT NULL',
                            (profile_id,)) as cursor:
        caught = {row[0] for row in await cursor.fetchall()}
    async with conn.execute('SELECT milestone_id,earned_at FROM milestone_awards WHERE profile_id=?',
                            (profile_id,)) as cursor:
        earned = {row['milestone_id']: row['earned_at'] for row in await cursor.fetchall()}
    return catalog(caught, earned, content)


async def check_and_award(conn, profile_id, content, now):
    if not conn.in_transaction:
        raise RuntimeError('Milestones require an active writer transaction')
    async with conn.execute('SELECT pokemon_id FROM pokedex WHERE profile_id=? AND caught_at IS NOT NULL',
                            (profile_id,)) as cursor:
        caught = {row[0] for row in await cursor.fetchall()}
    async with conn.execute('SELECT milestone_id FROM milestone_awards WHERE profile_id=?', (profile_id,)) as cursor:
        earned = {row[0] for row in await cursor.fetchall()}
    for milestone_id, lines in due(caught, earned, content):
        await conn.execute('INSERT INTO milestone_awards VALUES (?,?,?)', (profile_id, milestone_id, now))
        for line in lines:
            await conn.execute('INSERT INTO inbox_items(profile_id,milestone_id,resource,resource_id,remaining,created_at) '
                               'VALUES (?,?,?,?,?,?)', (profile_id, milestone_id, line['resource'],
                                                       line['resource_id'], line['quantity'], now))


async def waiting(conn, profile_id):
    async with conn.execute('SELECT resource,sum(remaining) AS quantity FROM inbox_items WHERE profile_id=? '
                            'GROUP BY resource', (profile_id,)) as cursor:
        return {row['resource']: row['quantity'] for row in await cursor.fetchall()}


async def waiting_details(conn, profile_id):
    async with conn.execute(
            'SELECT milestone_id,resource,resource_id,sum(remaining) AS remaining,min(inbox_id) AS first_inbox '
            'FROM inbox_items WHERE profile_id=? AND remaining>0 '
            'GROUP BY milestone_id,resource,resource_id ORDER BY first_inbox', (profile_id,)) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def pending_count(conn, profile_id):
    async with conn.execute('SELECT count(DISTINCT milestone_id) FROM inbox_items WHERE profile_id=? AND remaining>0',
                            (profile_id,)) as cursor:
        return (await cursor.fetchone())[0]


async def claim(conn, session, now):
    if not conn.in_transaction:
        raise RuntimeError('Claim requires an active writer transaction')
    _, refusal = await profiles.session_owner(conn, session)
    if refusal is not None:
        return refusal

    async def compute(conn):
        moved, lines = {'item': 0, 'stardust': 0, 'candy': 0}, []
        async with conn.execute('SELECT * FROM inbox_items WHERE profile_id=? ORDER BY inbox_id',
                                (session['profile_id'],)) as cursor:
            rewards = await cursor.fetchall()
        for reward in rewards:
            resource, resource_id, amount = reward['resource'], reward['resource_id'], reward['remaining']
            if resource == 'item':
                rare = resource_id in items.RARE
                if rare:
                    async with conn.execute('SELECT COALESCE(sum(quantity),0) FROM inventory '
                                            'WHERE profile_id=? AND item_id=?',
                                            (session['profile_id'], resource_id)) as cursor:
                        units = (await cursor.fetchone())[0]
                    cap = limits()['rare_pockets'][resource_id]
                else:
                    units = await items.bag_units(conn, session['profile_id'])
                    cap = (await capacity.limits_for(conn, session['profile_id']))['bag_units']
                amount = min(amount, max(0, cap - units))
                if amount:
                    await conn.execute('INSERT INTO inventory VALUES (?,?,?) ON CONFLICT(profile_id,item_id) '
                                       'DO UPDATE SET quantity=quantity+excluded.quantity',
                                       (session['profile_id'], resource_id, amount))
            elif resource == 'stardust':
                await conn.execute('UPDATE profiles SET stardust=stardust+? WHERE profile_id=?',
                                   (amount, session['profile_id']))
            else:
                await conn.execute('INSERT INTO candy VALUES (?,?,?) ON CONFLICT(profile_id,family_id) '
                                   'DO UPDATE SET quantity=quantity+excluded.quantity',
                                   (session['profile_id'], int(resource_id), amount))
            if amount:
                await conn.execute('UPDATE inbox_items SET remaining=remaining-? WHERE inbox_id=?',
                                   (amount, reward['inbox_id']))
                moved[resource] += amount
                lines.append({'profile_id': session['profile_id'], 'resource': resource,
                              'resource_id': resource_id, 'delta': amount, 'reason': 'milestone_claim'})
        await conn.execute('DELETE FROM inbox_items WHERE profile_id=? AND remaining=0', (session['profile_id'],))
        return {'status': 'claimed', 'moved': moved}, lines

    return await with_receipt(conn, f"claim:{session['session_id']}:{session['revision']}", 'claim',
                              compute, profile_id=session['profile_id'])
