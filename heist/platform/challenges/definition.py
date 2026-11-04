"""Pure, bounded exercise-definition validation shared by authoring entry points."""
from collections import deque
import json
import re


class DefinitionError(ValueError):
    pass


def string(value, label, maximum, minimum=0, pattern=None):
    if not isinstance(value, str) or '\0' in value:
        raise DefinitionError(label+' must be text')
    value = value.strip()
    if not minimum <= len(value) <= maximum or (pattern and re.fullmatch(pattern, value) is None):
        raise DefinitionError(label+' has an invalid length or format')
    return value


def integer(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise DefinitionError(f'{label} must be an integer between {minimum} and {maximum}')
    return value


def boolean(value, label):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value in ('true', 'false'):
        return value == 'true'
    raise DefinitionError(label+' must be true or false')


def records(value, label, minimum, maximum):
    if isinstance(value, str):
        if len(value) > 65536:
            raise DefinitionError(label+' is too large')
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            raise DefinitionError(label+' must be a JSON list') from None
    if not isinstance(value, list) or not minimum <= len(value) <= maximum or any(not isinstance(item, dict) for item in value):
        raise DefinitionError(f'{label} must contain {minimum} to {maximum} objects')
    return value


def unique(values, label):
    if len(set(values)) != len(values):
        raise DefinitionError(label+' must be unique')


def metadata(value):
    if not isinstance(value, dict):
        raise DefinitionError('An exercise object is required')
    category = value.get('category')
    difficulty = value.get('difficulty')
    if category not in ('web', 'crypto', 'forensics', 'reverse', 'pwn', 'misc'):
        raise DefinitionError('Invalid category')
    if difficulty not in ('easy', 'medium', 'hard'):
        raise DefinitionError('Invalid difficulty')
    return {'name': string(value.get('name'), 'Exercise name', 100, 1, r'[A-Za-z0-9_ -]+'),
            'description': string(value.get('description'), 'Description', 2000, 1), 'category': category, 'difficulty': difficulty,
            'hint': string(value.get('hint', ''), 'General hint', 500),
            'solution': string(value.get('solution', ''), 'Solution', 2000),
            'is_active': boolean(value.get('isActive', False), 'Availability')}


def definition(value, artifacts):
    result = metadata(value)
    available = {item['display_name']: item for item in artifacts}
    machines = []
    for item in records(value.get('vms'), 'Machines', 1, 20):
        name = string(item.get('name'), 'Machine name', 50, 1, '[A-Za-z0-9_-]+')
        artifact = available.get(string(item.get('ova_name'), 'VM image', 255, 1))
        if artifact is None:
            raise DefinitionError('Select an owned VM image for '+name)
        role = item.get('ad_role', 'none')
        if role not in ('none', 'dc', 'member'):
            raise DefinitionError('Invalid Active Directory role')
        if role != 'none' and artifact['guest_os'] != 'windows':
            raise DefinitionError('Active Directory roles require a Windows image')
        domain = string(item.get('domain_name'), 'Domain', 253, 1).lower()
        if any(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) is None for label in domain.split('.')):
            raise DefinitionError('Invalid domain name')
        machines.append({'name': name, 'disk_file_id': artifact['id'], 'guest_os': artifact['guest_os'],
                         'cores': integer(item.get('cores'), 'CPU cores', 1, 16),
                         'ram_gb': integer(item.get('ram_gb'), 'RAM in GiB', 1, 32), 'domain_name': domain, 'ad_role': role})
    unique([item['name'].casefold() for item in machines], 'Machine names')
    names = {item['name'] for item in machines}
    networks = []
    for item in records(value.get('subnets'), 'Networks', 1, 10):
        name = string(item.get('name'), 'Network name', 50, 1, '[A-Za-z0-9_-]+')
        members = item.get('attached_vms')
        if not isinstance(members, list) or not 1 <= len(members) <= 20 or any(not isinstance(member, str) or member not in names for member in members):
            raise DefinitionError('Every network must attach existing machines')
        unique(members, 'Attached machine names')
        networks.append({'name': name, 'attached_vms': list(members), 'accessible': boolean(item.get('accessible', False), 'Network accessibility'),
                         'dmz': boolean(item.get('dmz', False), 'DMZ selection')})
    unique([item['name'].casefold() for item in networks], 'Network names')
    topology(machines, networks)
    flags = []
    for item in records(value.get('flags'), 'Flags', 1, 20):
        personal = boolean(item.get('user_specific', False), 'User-specific flag')
        machine = item.get('vm_name') if personal else None
        if personal and (not isinstance(machine, str) or machine not in names):
            raise DefinitionError('User-specific flags require an existing machine')
        flags.append({'flag': string(item.get('flag'), 'Flag', 255, 1),
                      'description': string(item.get('description', ''), 'Flag description', 500),
                      'points': integer(item.get('points'), 'Flag points', 1, 1000),
                      'order_index': integer(item.get('order_index'), 'Flag order', 0, 1000),
                      'user_specific': personal, 'vm_name': machine})
    unique([item['flag'] for item in flags], 'Flag values')
    unique([item['order_index'] for item in flags], 'Flag order indexes')
    hints = []
    for index, item in enumerate(records(value.get('hints', []), 'Hints', 0, 10)):
        hints.append({'hint_text': string(item.get('hint_text'), 'Hint', 500, 1),
                      'unlock_points': integer(item.get('unlock_points'), 'Hint unlock points', 0, 500),
                      'order_index': integer(item.get('order_index', index), 'Hint order', 0, 1000)})
    unique([item['order_index'] for item in hints], 'Hint order indexes')
    return {**result, 'machines': machines, 'networks': networks, 'flags': flags, 'hints': hints}


def topology(machines, networks):
    by_name = {item['name']: item for item in machines}
    reached = {name for network in networks if network['accessible'] for name in network['attached_vms']}
    queue = deque(reached)
    while queue:
        name = queue.popleft()
        for network in networks:
            if name in network['attached_vms']:
                for neighbor in network['attached_vms']:
                    if neighbor not in reached:
                        reached.add(neighbor)
                        queue.append(neighbor)
    if reached != set(by_name):
        raise DefinitionError('Every machine needs a path to a student-accessible network')
    memberships = {name: [network for network in networks if name in network['attached_vms']] for name in by_name}
    for network in networks:
        if sum(by_name[name]['ad_role'] == 'dc' for name in network['attached_vms']) > 1:
            raise DefinitionError('Only one Domain Controller is supported per network')
    for machine in machines:
        if machine['ad_role'] == 'member':
            controllers = [by_name[name] for network in memberships[machine['name']] for name in network['attached_vms'] if by_name[name]['ad_role'] == 'dc']
            if not any(controller['domain_name'] == machine['domain_name'] for controller in controllers):
                raise DefinitionError('A domain member must share a network and domain with its Domain Controller')
