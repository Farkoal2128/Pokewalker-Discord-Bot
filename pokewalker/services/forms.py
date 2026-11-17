"""D71/D72/D73 (owner requests 2026-11-17): change form, fuse and change look from details.

Gaining CP costs STARDUST_PER_CP per CP gained; the same or lower CP is free. A fusion
partner leaves storage and is kept as JSON in `fusions` until unfused.
"""

import json

from pokewalker.db import with_receipt
from pokewalker.domain.cp import cp
from pokewalker.services import storage
from pokewalker.services.profiles import arena_team, session_owner


STYLE_SPECIES = frozenset({741})  # Oricorio: its catchable styles switch between each other
FUSIONS = {800: {791: 'dusk', 792: 'dawn'},     # Necrozma + Solgaleo / Lunala
           646: {643: 'white', 644: 'black'},   # Kyurem + Reshiram / Zekrom
           898: {896: 'ice', 897: 'shadow'}}    # Calyrex + Glastrier / Spectrier
ULTRA_SPECIES, ULTRA = 800, 'ultra'
STARDUST_PER_CP = 10


def _default(content, species_id):
    return next(i for i in content['identities'] if i['species_id'] == species_id and i['kind'] == 'default')


def _form(content, species_id, key):
    return next(i for i in content['form_changes'] if i['species_id'] == species_id and i['form_key'] == key)


def species_of(content, pokemon):
    return storage.identify(content, pokemon)[0]['species_id']


def fused_key(content, pokemon, fusion):
    return FUSIONS[species_of(content, pokemon)][species_of(content, fusion['partner'])]


def options(content, pokemon, fusion):
    """Other forms this Pokemon may change into."""
    identity = storage.identify(content, pokemon)[0]
    sid = identity['species_id']
    if sid not in FUSIONS and any(item['species_id'] == sid for item in content.get('form_changes', [])):
        forms = [_default(content, sid), *(i for i in content['form_changes'] if i['species_id'] == sid)]
    elif sid in STYLE_SPECIES:
        forms = [i for i in content['identities'] if i['species_id'] == sid]
    elif sid == ULTRA_SPECIES and fusion is not None:
        forms = [_form(content, sid, fused_key(content, pokemon, fusion)), _form(content, sid, ULTRA)]
    else:
        forms = []
    return [item for item in forms if item['identity_id'] != identity['identity_id']]


def can_fuse(content, pokemon, fusion):
    return fusion is None and species_of(content, pokemon) in FUSIONS


def quote(content, pokemon, target, multipliers):
    ivs = [pokemon[key] for key in ('iv_attack', 'iv_defense', 'iv_stamina')]

    def value(identity):
        return cp([identity[k] for k in ('base_attack', 'base_defense', 'base_stamina')], ivs,
                  pokemon['level_x2'], multipliers=multipliers)

    before, after = value(storage.identify(content, pokemon)[0]), value(target)
    return {'cp_before': before, 'cp_after': after, 'cost': max(0, after - before) * STARDUST_PER_CP}


async def fusion_of(conn, uid):
    async with conn.execute('SELECT partner FROM fusions WHERE pokemon_uid=?', (uid,)) as cursor:
        row = await cursor.fetchone()
    return None if row is None else {'partner': json.loads(row['partner'])}


async def partners(conn, profile_id, content, pokemon, now):
    """Owned partners for an unfused fuser: not deployed, companion or in a live Arena team."""
    sid = species_of(content, pokemon)
    if sid not in FUSIONS:
        return []
    team = await arena_team(conn, profile_id, now)
    species = tuple(FUSIONS[sid])
    async with conn.execute(
            "SELECT * FROM pokemon WHERE profile_id=? AND state='owned' AND gym_deployment_id IS NULL "
            f"AND pokemon_id IN ({','.join('?' * len(species))}) "
            'AND pokemon_uid IS NOT (SELECT companion_uid FROM profiles WHERE profile_id=?)',
            (profile_id, *species, profile_id)) as cursor:
        rows = [dict(row) for row in await cursor.fetchall()]
    return [row for row in rows if row['pokemon_uid'] not in team]


async def _begin(conn, session, uid, expected_revision, key, action):
    """Shared checks: (profile_id, pokemon, early result or None)."""
    if not conn.in_transaction:
        raise RuntimeError('Form changes require an active writer transaction')
    profile, refusal = await session_owner(conn, session)
    if refusal is not None:
        return None, None, {**refusal, 'pokemon': None}
    pid = profile['profile_id']
    pokemon = await storage.detail(conn, pid, uid)
    async with conn.execute('SELECT profile_id,result FROM action_receipts WHERE key=? AND action=?',
                            (key, action)) as cursor:
        receipt = await cursor.fetchone()
    if receipt is not None:
        return pid, pokemon, (json.loads(receipt['result']) if receipt['profile_id'] == pid
                              else {'status': 'stale', 'pokemon': pokemon})
    if pokemon is None:
        return pid, None, {'status': 'stale', 'pokemon': None}
    if pokemon['gym_deployment_id'] is not None:
        return pid, pokemon, {'status': 'deployed', 'pokemon': pokemon}
    if pokemon['revision'] != expected_revision:
        return pid, pokemon, {'status': 'stale', 'pokemon': pokemon}
    return pid, pokemon, None


async def _stardust(conn, pid):
    async with conn.execute('SELECT stardust FROM profiles WHERE profile_id=?', (pid,)) as cursor:
        return (await cursor.fetchone())['stardust']


async def _set_form(conn, pid, pokemon, target, cost, reason):
    async with conn.execute("UPDATE pokemon SET pokemon_id=?,form_id=?,revision=revision+1 WHERE pokemon_uid=? "
                            "AND profile_id=? AND revision=? AND state='owned'",
                            (target['pokemon_id'], target['form_id'], pokemon['pokemon_uid'], pid,
                             pokemon['revision'])) as cursor:
        if cursor.rowcount != 1:
            raise RuntimeError('Form change guard refused the update')
    if cost:
        await conn.execute('UPDATE profiles SET stardust=stardust-? WHERE profile_id=?', (cost, pid))
    return [{'profile_id': pid, 'resource': 'stardust', 'delta': -cost, 'reason': reason}] if cost else []


def _look(content, look_id):
    return next((item for item in content.get('looks', []) if item['look_id'] == look_id), None) if look_id else None


def looks_of(content, pokemon):
    """D73: every cosmetic look of this Pokemon's identity."""
    identity_id = storage.identify(content, pokemon)[0]['identity_id']
    return [item for item in content.get('looks', []) if item['base_identity_id'] == identity_id]


EVOLVED_LOOK_KEYS = {'artisan': 'masterpiece'}  # Artisan Poltchageist evolves into Masterpiece Sinistcha


def carried_look(content, pokemon, target):
    """The target identity's look with the same (or aliased) form key, kept through evolution; else None."""
    look = _look(content, dict(pokemon).get('look_id'))
    if look is None:
        return None
    key = EVOLVED_LOOK_KEYS.get(look['form_key'], look['form_key'])
    return next((item['look_id'] for item in content['looks'] if item['base_identity_id'] == target['identity_id']
                 and item['form_key'] == key), None)


async def unlock(conn, profile_id, look_id, at):
    if look_id:
        await conn.execute('INSERT OR IGNORE INTO look_unlocks(profile_id,look_id,unlocked_at) VALUES (?,?,?)',
                           (profile_id, look_id, at))


async def unlocked(conn, profile_id):
    async with conn.execute('SELECT look_id FROM look_unlocks WHERE profile_id=?', (profile_id,)) as cursor:
        return {row['look_id'] for row in await cursor.fetchall()}


async def set_look(conn, session, uid, expected_revision, look_id, content):
    """D73: free switch to the default look (None) or an unlocked look of the same identity."""
    key = f'look:{uid}:{expected_revision}'
    pid, pokemon, early = await _begin(conn, session, uid, expected_revision, key, 'look')
    if early is not None:
        return early
    have = await unlocked(conn, pid)
    allowed = {None} | {item['look_id'] for item in looks_of(content, pokemon) if item['look_id'] in have}
    if look_id not in allowed or look_id == pokemon.get('look_id'):
        return {'status': 'refused', 'pokemon': pokemon}

    async def compute(conn):
        await conn.execute("UPDATE pokemon SET look_id=?,revision=revision+1 WHERE pokemon_uid=? AND profile_id=? "
                           "AND revision=? AND state='owned'", (look_id, uid, pid, expected_revision))
        return {'status': 'used', 'pokemon': await storage.detail(conn, pid, uid)}, []

    return await with_receipt(conn, key, 'look', compute, profile_id=pid)


async def change(conn, session, uid, expected_revision, identity_id, content, multipliers):
    key = f'form:{uid}:{expected_revision}'
    pid, pokemon, early = await _begin(conn, session, uid, expected_revision, key, 'form_change')
    if early is not None:
        return early
    target = next((item for item in options(content, pokemon, await fusion_of(conn, uid))
                   if item['identity_id'] == identity_id), None)
    if target is None:
        return {'status': 'refused', 'pokemon': pokemon}
    cost = quote(content, pokemon, target, multipliers)['cost']
    if await _stardust(conn, pid) < cost:
        return {'status': 'insufficient', 'pokemon': pokemon}

    async def compute(conn):
        lines = await _set_form(conn, pid, pokemon, target, cost, 'form_change')
        return {'status': 'used', 'pokemon': await storage.detail(conn, pid, uid)}, lines

    return await with_receipt(conn, key, 'form_change', compute, profile_id=pid)


async def fuse(conn, session, uid, expected_revision, partner_uid, partner_revision, content, multipliers, now):
    key = f'fuse:{uid}:{expected_revision}'
    pid, pokemon, early = await _begin(conn, session, uid, expected_revision, key, 'fuse')
    if early is not None:
        return early
    if not can_fuse(content, pokemon, await fusion_of(conn, uid)):
        return {'status': 'refused', 'pokemon': pokemon}
    partner = await storage.detail(conn, pid, partner_uid)
    if partner is None or partner['revision'] != partner_revision:
        return {'status': 'stale', 'pokemon': pokemon}
    if partner_uid not in {row['pokemon_uid'] for row in await partners(conn, pid, content, pokemon, now)}:
        return {'status': 'refused', 'pokemon': pokemon}
    target = _form(content, species_of(content, pokemon), fused_key(content, pokemon, {'partner': partner}))
    cost = quote(content, pokemon, target, multipliers)['cost']
    if await _stardust(conn, pid) < cost:
        return {'status': 'insufficient', 'pokemon': pokemon}

    async def compute(conn):
        await conn.execute('INSERT INTO fusions(pokemon_uid,partner_uid,partner,fused_at) VALUES (?,?,?,?)',
                           (uid, partner_uid, json.dumps(partner, separators=(',', ':')), now))
        async with conn.execute('DELETE FROM pokemon WHERE pokemon_uid=? AND profile_id=? AND revision=?',
                                (partner_uid, pid, partner_revision)) as cursor:
            if cursor.rowcount != 1:
                raise RuntimeError('Fusion guard refused the partner')
        lines = await _set_form(conn, pid, pokemon, target, cost, 'fuse')
        return {'status': 'used', 'pokemon': await storage.detail(conn, pid, uid)}, lines

    return await with_receipt(conn, key, 'fuse', compute, profile_id=pid)


async def unfuse(conn, session, uid, expected_revision, content, now):
    key = f'unfuse:{uid}:{expected_revision}'
    pid, pokemon, early = await _begin(conn, session, uid, expected_revision, key, 'unfuse')
    if early is not None:
        return early
    fusion = await fusion_of(conn, uid)
    if fusion is None:
        return {'status': 'refused', 'pokemon': pokemon}
    async with conn.execute('SELECT storage_limit FROM profiles WHERE profile_id=?', (pid,)) as cursor:
        limit = (await cursor.fetchone())['storage_limit']
    if await storage.owned_count(conn, pid) >= limit:
        return {'status': 'full', 'pokemon': pokemon}

    async def compute(conn):
        await _set_form(conn, pid, pokemon, _default(content, species_of(content, pokemon)), 0, 'unfuse')
        async with conn.execute('PRAGMA table_info(pokemon)') as cursor:
            columns = [row['name'] for row in await cursor.fetchall()]
        partner = {key: value for key, value in fusion['partner'].items() if key in columns}
        partner.update(profile_id=pid, revision=partner['revision'] + 1, gym_deployment_id=None)
        if partner.get('source_encounter_id') is not None:
            async with conn.execute('SELECT 1 FROM encounters WHERE encounter_id=?',
                                    (partner['source_encounter_id'],)) as cursor:
                if await cursor.fetchone() is None:
                    partner['source_encounter_id'] = None
        await conn.execute(f"INSERT INTO pokemon({','.join(partner)}) VALUES ({','.join('?' * len(partner))})",
                           tuple(partner.values()))
        await conn.execute('DELETE FROM fusions WHERE pokemon_uid=?', (uid,))
        return {'status': 'used', 'pokemon': await storage.detail(conn, pid, uid)}, []

    return await with_receipt(conn, key, 'unfuse', compute, profile_id=pid)
