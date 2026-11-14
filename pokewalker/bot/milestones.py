"""Private reward inbox with durable Claim and detached rendering."""

import json
import re

import discord

from content.balance import load_table
from pokewalker.bot.screens_catch import custom_id
from pokewalker.services import arena, items, milestones as service


def _entries(content):
    milestones = content['milestones']
    entries = {}
    for category, field, key_field in (
            ('pokedex', 'pokedex', 'percent'),
            ('starter_trios', 'starter_trios', 'generation'),
            ('regions', 'regions', 'generation'),
            ('mythical_sets', 'mythical_sets', 'generation'),
            ('legendary_groups', 'legendary_groups', 'id'),
            ('extra_bundle_lines', 'extra_bundle_lines', 'id'),
            ('ultra_beast_first_catches', 'ultra_beast_first_catches', 'species_id'),
            ('evolution_lines', 'evolution_lines.families', 'family_id')):
        rows = milestones
        for part in field.split('.'):
            rows = rows.get(part, []) if isinstance(rows, dict) else rows
        for row in rows if isinstance(rows, list) else []:
            entries[f"{category}:{row[key_field]}"] = row.get('bundle')
    for category in ('all_starters', 'all_legendaries', 'all_mythicals', 'first_legendary', 'first_mythical'):
        if category in milestones:
            key = 'all' if category.startswith('all_') else 'first'
            entries[f'{category}:{key}'] = milestones[category].get('bundle')
    return entries


def _species_name(content, species_id):
    return next((row['name_en'] for row in content.get('identities', [])
                 if row['species_id'] == int(species_id)), f'Species {species_id}')


def _display_words(value):
    words = value.replace('_', ' ').split()
    return ' '.join(word.title() if index == 0 or word.lower() not in {'and', 'of'}
                    else word.lower() for index, word in enumerate(words))


def _milestone_name(milestone_id, content):
    category, _, key = milestone_id.partition(':')
    generation = f'Generation {key}'
    if category == 'pokedex':
        return f'Pok\u00e9dex {key}%'
    if category == 'ultra_beast_first_catches':
        return f'First Ultra Beast catch: {_species_name(content, key)}'
    if category == 'evolution_lines':
        species = content.get('families', {}).get(str(key), [])
        return f"Evolution line: {_species_name(content, species[0])}" if species else f'Evolution line {key}'
    if category == 'extra_bundle_lines':
        entry = next((row for row in content['milestones'].get('extra_bundle_lines', [])
                      if row['id'] == key), None)
        if entry and entry.get('species_ids'):
            return f"{_species_name(content, entry['species_ids'][0])} evolution line"
    labels = {
        'starter_trios': f'{generation} starter trio',
        'regions': f'{generation} Pok\u00e9dex complete',
        'mythical_sets': f'{generation} Mythical set',
        'legendary_groups': f'Legendary group: {_display_words(key)}',
        'all_starters': 'All starters', 'all_legendaries': 'All Legendaries',
        'all_mythicals': 'All Mythicals', 'first_legendary': 'First Legendary',
        'first_mythical': 'First Mythical',
    }
    return labels.get(category, f'{category.replace("_", " ").title()}: {key}')


def _reward_name(row, content):
    resource, resource_id = row['resource'], row['resource_id']
    if resource == 'stardust':
        return 'Stardust'
    if resource == 'candy':
        return f"{_species_name(content, content.get('families', {}).get(str(resource_id), [resource_id])[0])} Candy"
    return str(resource_id or 'Item').replace('_', ' ').title()


async def _gym_labels(conn, session, details):
    labels = {}
    for row in details:
        key = row['milestone_id']
        if key.startswith('arena_month:'):
            parts = key.split(':')
            label = 'Arena leaderboard reward'
            if (len(parts) == 3 and re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', parts[1])
                    and parts[2] in ('1', '2', '3')):
                place = {'1': '1st', '2': '2nd', '3': '3rd'}[parts[2]]
                label = f'Arena leaderboard {parts[1]}: {place} place'
            labels[key] = label
        if key.startswith('arena:'):
            parts = key.split(':')
            label = 'Arena ticket reward'
            if len(parts) >= 3 and parts[1]:
                if len(parts) == 3 and parts[2] == 'stardust':
                    label = 'Arena ticket: Stardust'
                elif (len(parts) == 4 and parts[2] in ('income', 'survivor')
                      and parts[3].isascii() and parts[3].isdecimal()):
                    label = 'Arena ticket: ' + ('income roll' if parts[2] == 'income' else 'survivor reward')
            labels[key] = label
    rewards = {row['milestone_id']: row['milestone_id'].split(':') for row in details
               if row['milestone_id'].startswith(('gym_income:', 'survivor:'))}
    labels.update({milestone_id: 'Gym income reward' if parts[0] == 'gym_income' else 'Gym survivor reward'
                   for milestone_id, parts in rewards.items()})
    rewards = {milestone_id: parts for milestone_id, parts in rewards.items() if parts[1] and (
        (parts[0] == 'gym_income' and len(parts) == 3 and parts[2] in ('1', '2', '3', '4', '5', '6', '7', '8'))
        or (parts[0] == 'survivor' and len(parts) == 2))}
    if not rewards:
        return labels
    deployments = sorted({parts[1] for parts in rewards.values()})
    async with conn.execute(
            'SELECT deployment_id,gyms.name FROM gym_deployments JOIN gyms USING (gym_id,guild_id) '
            'WHERE gym_deployments.guild_id=? AND profile_id=? AND deployment_id IN ('
            + ','.join('?' for _ in deployments) + ')',
            (session['guild_id'], session['profile_id'], *deployments)) as cursor:
        names = {row['deployment_id']: row['name'] for row in await cursor.fetchall()}
    for milestone_id, parts in rewards.items():
        name = names.get(parts[1], 'a gym')
        labels[milestone_id] = (f'Gym income: {name} hour {parts[2]}' if parts[0] == 'gym_income'
                                else f'Gym survivor reward: {name}')
    return labels


def _detail_lines(details, content, labels):
    groups = {}
    for row in details:
        groups.setdefault(row['milestone_id'], []).append(row)
    bundles = _entries(content)
    lines = []
    for milestone_id, rows in groups.items():
        bundle = bundles.get(milestone_id)
        label = labels.get(milestone_id) or _milestone_name(milestone_id, content)
        tier = f' [{bundle.title()}]' if bundle else ''
        rewards = ', '.join(f"{_reward_name(row, content)} \u00d7{row['remaining']}" for row in rows)
        lines.append(f'{label}{tier}: {rewards}')
    return lines


def render(state, content):
    moved, waiting = state.get('moved', {}), state['waiting']
    lines = [f"Moved: {sum(moved.values())}", f"Waiting: {sum(waiting.values())}"]
    for resource in ('item', 'stardust', 'candy'):
        lines.append(f"{resource.title()}: moved {moved.get(resource, 0)} / waiting {waiting.get(resource, 0)}")
    if waiting:
        lines.append('Items wait for bag space; rare rewards wait for an empty pocket.')
    moved_lines = _detail_lines(state.get('moved_details', []), content, state.get('labels', {}))
    waiting_lines = _detail_lines(state.get('waiting_details', []), content, state.get('labels', {}))
    shown = [min(15, len(moved_lines)), min(15, len(waiting_lines))]
    while True:
        detail_lines = []
        for heading, details, count, label in (
                ('Moved milestones:', moved_lines, shown[0], 'moved'),
                ('Still waiting:', waiting_lines, shown[1], 'waiting')):
            if details or (label == 'waiting' and moved_lines):
                detail_lines.append(heading)
                detail_lines.extend(details[:count])
                if len(details) > count:
                    detail_lines.append(f'And {len(details) - count} more {label} milestones.')
                elif label == 'waiting' and moved_lines and not details:
                    detail_lines.append('none')
        description = '\n'.join(lines + detail_lines)
        if len(description) <= 4096:
            break
        index = 0 if shown[0] >= shown[1] else 1
        if shown[index] == 0:
            index = 1 - index
        if shown[index] == 0:
            break
        shown[index] -= 1
    view = discord.ui.View(timeout=None)
    buttons = [('Claim', 'claim'), ('Back', 'home')]
    expansion = state.get('bag_expansion', {})
    if expansion and any(row['resource'] == 'item' and row['resource_id'] not in items.RARE
                         for row in state.get('waiting_details', [])):
        buttons.extend([(f"Expand bag (+{expansion['step']}, {expansion['stardust']:,} Stardust)",
                         'inbox_expand_bag'), ('Convert items', 'inbox_convert')])
    for label, action in buttons:
        view.add_item(discord.ui.Button(label=label, custom_id=custom_id(state, action)))
    return {'embed': discord.Embed(title='Reward inbox', description=description), 'view': view}


def handlers(walker):
    from pokewalker.bot.walker import _Refused, REOPEN, EXCLUDED

    async def inbox(conn, session, interaction):
        await arena.settle(conn, session['guild_id'], walker.clock())
        if json.loads(session['selection']).get('back') == 'inbox':
            session['selection'] = '{}'
        details = await service.waiting_details(conn, session['profile_id'])
        return render({'session': session, 'waiting': await service.waiting(conn, session['profile_id']),
                       'waiting_details': details, 'bag_expansion': load_table('capacities')['expansion']['bag'],
                       'labels': await _gym_labels(conn, session, details)}, walker.bot.content)

    async def claim(conn, session, interaction):
        before = await service.waiting_details(conn, session['profile_id'])
        result = await service.claim(conn, session, walker.clock())
        if result['status'] != 'claimed':
            raise _Refused(EXCLUDED if result['status'] == 'excluded' else REOPEN)
        after = await service.waiting_details(conn, session['profile_id'])
        old = {(r['milestone_id'], r['resource'], r['resource_id']): r['remaining'] for r in before}
        current = {(r['milestone_id'], r['resource'], r['resource_id']): r['remaining'] for r in after}
        moved_details = [{'milestone_id': milestone_id, 'resource': resource, 'resource_id': resource_id,
                          'remaining': amount - current.get((milestone_id, resource, resource_id), 0)}
                         for (milestone_id, resource, resource_id), amount in old.items()
                         if amount > current.get((milestone_id, resource, resource_id), 0)]
        moved = {}
        for row in moved_details:
            moved[row['resource']] = moved.get(row['resource'], 0) + row['remaining']
        return render({'session': session, 'moved': moved,
                       'moved_details': moved_details, 'waiting': await service.waiting(conn, session['profile_id']),
                       'waiting_details': after, 'bag_expansion': load_table('capacities')['expansion']['bag'],
                       'labels': await _gym_labels(conn, session, moved_details + after)}, walker.bot.content)

    return {'inbox': inbox, 'claim': claim}
