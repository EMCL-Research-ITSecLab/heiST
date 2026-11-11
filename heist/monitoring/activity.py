"""Read-only, bounded event projection for administrators, never raw log export."""
from datetime import datetime, timedelta, timezone
import json
import re

import requests

from .pipeline import HTTPS


def read(settings, machine_ids=None, *, client_factory=HTTPS, now=None):
    now = now or datetime.now(timezone.utc)
    start = now-timedelta(minutes=15)
    result = {'status': 'not configured', 'checked_at': now.isoformat(), 'since': start.isoformat(),
              'events': [], 'counts': {}, 'has_more': False, 'coverage': 'unverified'}
    if machine_ids is not None and (len(machine_ids) > 20 or any(type(i) is not int or not 0 < i < 2**31 for i in machine_ids)):
        raise ValueError('Invalid machine scope')
    if not settings.get('ACTIVITY_INDEXER_USER') or not settings.get('ACTIVITY_INDEXER_PASSWORD'):
        return result
    if machine_ids == []:
        return {**result, 'status': 'ready', 'counts': {'commands': 0, 'processes': 0}}
    filters = [{'range': {'timestamp': {'gte': start.isoformat(), 'lte': now.isoformat()}}},
               {'terms': {'rule.groups': ['command_executed', 'process_creation']}}]
    filters.append({'terms': {'agent.name': ['Agent_'+str(i) for i in machine_ids]}} if machine_ids is not None
                   else {'regexp': {'agent.name': 'Agent_[0-9]+'}})
    fields = ['timestamp', 'agent.name', 'rule.id', 'rule.groups', 'rule.description',
              'data.cmd_line', 'data.command', 'data.win.eventdata.commandLine',
              'data.win.eventdata.scriptBlockText', 'data.win.eventdata.newProcessName']
    query = {'size': 26, 'timeout': '3s', 'track_total_hits': False, '_source': fields,
             'sort': [{'timestamp': 'desc'}], 'query': {'bool': {'filter': filters}},
             'aggs': {'types': {'filters': {'filters': {
                 'commands': {'term': {'rule.groups': 'command_executed'}},
                 'processes': {'term': {'rule.groups': 'process_creation'}}}}}}}
    client = None
    try:
        client = client_factory(settings, 'ACTIVITY_INDEXER', 9200)
        body = client.get('/wazuh-alerts-*/_search', params={'source': json.dumps(query), 'source_content_type': 'application/json'})
        if body.get('timed_out') is not False or body.get('_shards', {}).get('failed') != 0:
            raise ValueError('Incomplete event search')
        hits = body['hits']['hits']
        if not isinstance(hits, list) or len(hits) > 26:
            raise ValueError('Invalid event page')
        counts = {key: body['aggregations']['types']['buckets'][key]['doc_count'] for key in ('commands', 'processes')}
        if any(type(v) is not int or not 0 <= v < 2**53 for v in counts.values()):
            raise ValueError('Invalid event counts')
        events = []
        for hit in hits[:25]:
            item = hit['_source']
            agent = item['agent']['name']
            if not isinstance(agent, str) or not re.fullmatch(r'Agent_[1-9][0-9]{0,9}', agent):
                raise ValueError('Unexpected agent')
            machine = int(agent.removeprefix('Agent_'))
            if machine_ids is not None and machine not in machine_ids:
                raise ValueError('Event outside instance scope')
            at = datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00'))
            if at.tzinfo is None or not start <= at <= now:
                raise ValueError('Event outside time window')
            groups = item['rule']['groups']
            if not isinstance(groups, list) or not set(groups).intersection(('command_executed', 'process_creation')):
                raise ValueError('Unexpected event type')
            data = item.get('data', {})
            windows = data.get('win', {}).get('eventdata', {})
            command = next((v for v in (data.get('cmd_line'), data.get('command'), windows.get('commandLine'),
                           windows.get('scriptBlockText'), windows.get('newProcessName')) if isinstance(v, str) and v), '')
            description = item['rule'].get('description', '')
            if not isinstance(description, str):
                raise ValueError('Invalid description')
            events.append({'machine_id': machine, 'timestamp': at.isoformat(),
                           'kind': 'command' if 'command_executed' in groups else 'process',
                           'description': description[:300], 'command': command[:2048], 'truncated': len(command) > 2048})
        return {**result, 'status': 'ready', 'counts': counts, 'events': events, 'has_more': len(hits) > 25}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, requests.RequestException):
        return {**result, 'status': 'unavailable'}
    finally:
        if client is not None:
            client.close()
