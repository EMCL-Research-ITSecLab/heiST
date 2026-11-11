"""Event search scope, privacy, partial results and bounded projections."""
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import Mock

from heist.monitoring.activity import read

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
SETTINGS = {'ACTIVITY_INDEXER_USER': 'reader', 'ACTIVITY_INDEXER_PASSWORD': 'fixture-private'}


def response():
    return {'timed_out': False, '_shards': {'failed': 0}, 'hits': {'hits': [{'_source': {
        'timestamp': '2026-11-11T11:59:00Z', 'agent': {'name': 'Agent_123'},
        'rule': {'groups': ['process_creation', 'command_executed'], 'description': 'Command received'},
        'data': {'cmd_line': '<script>fixture</script>', 'private': 'never project'},
        'full_log': 'private raw record'}}]},
        'aggregations': {'types': {'buckets': {'commands': {'doc_count': 1}, 'processes': {'doc_count': 1}}}}}


class ActivityTests(unittest.TestCase):
    def test_search_is_fixed_scoped_and_projects_only_selected_fields(self):
        client = Mock();client.get.return_value = response()
        result = read(SETTINGS, [123], client_factory=Mock(return_value=client), now=NOW)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['counts'], {'commands': 1, 'processes': 1})
        self.assertEqual(result['coverage'], 'unverified')
        self.assertNotIn('private', json.dumps(result))
        path = client.get.call_args.args[0]
        query = json.loads(client.get.call_args.kwargs['params']['source'])
        self.assertEqual(path, '/wazuh-alerts-*/_search')
        self.assertIn({'terms': {'agent.name': ['Agent_123']}}, query['query']['bool']['filter'])
        self.assertNotIn('full_log', query['_source'])
        client.close.assert_called_once()

    def test_other_instance_or_old_event_or_partial_result_is_never_returned(self):
        for change in ('scope', 'old', 'shards', 'timeout'):
            value = response()
            if change == 'scope':value['hits']['hits'][0]['_source']['agent']['name'] = 'Agent_999'
            if change == 'old':value['hits']['hits'][0]['_source']['timestamp'] = '2026-11-10T12:00:00Z'
            if change == 'shards':value['_shards']['failed'] = 1
            if change == 'timeout':value['timed_out'] = True
            client = Mock();client.get.return_value = value
            with self.subTest(change=change):
                result = read(SETTINGS, [123], client_factory=Mock(return_value=client), now=NOW)
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(result['events'], [])

    def test_zero_events_does_not_establish_collection_coverage(self):
        value = response();value['hits']['hits'] = []
        for item in value['aggregations']['types']['buckets'].values():item['doc_count'] = 0
        client = Mock();client.get.return_value = value
        result = read(SETTINGS, client_factory=Mock(return_value=client), now=NOW)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['events'], [])
        self.assertEqual(result['coverage'], 'unverified')

    def test_missing_credentials_and_invalid_scope_never_query(self):
        factory = Mock()
        self.assertEqual(read({}, client_factory=factory, now=NOW)['status'], 'not configured')
        for ids in ([True], [-1], list(range(1, 22))):
            with self.assertRaises(ValueError):read(SETTINGS, ids, client_factory=factory, now=NOW)
        factory.assert_not_called()

    def test_command_text_and_page_are_bounded(self):
        value = response();value['hits']['hits'][0]['_source']['data']['cmd_line'] = 'x'*3000
        value['hits']['hits'] *= 26
        client = Mock();client.get.return_value = value
        result = read(SETTINGS, [123], client_factory=Mock(return_value=client), now=NOW)
        self.assertEqual(len(result['events']), 25)
        self.assertTrue(result['has_more'])
        self.assertTrue(result['events'][0]['truncated'])
        self.assertEqual(len(result['events'][0]['command']), 2048)


class DashboardTests(unittest.TestCase):
    def test_dashboard_datasources_time_fields_and_agent_scope_match_wazuh(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]/'heist/monitoring/grafana/config'
        dashboard = json.loads((root/'wazuh_dashboard.json').read_text())['dashboard']
        source = json.loads((root/'wazuh_datasource.json').read_text())
        self.assertEqual(source['jsonData']['timeField'], 'timestamp')
        self.assertEqual(source['jsonData']['index'], 'wazuh-alerts-*')
        self.assertNotIn('@timestamp', json.dumps(dashboard))
        variables = dashboard['templating']['list']
        self.assertEqual([v['name'] for v in variables], ['agent'])
        self.assertEqual(variables[0]['allValue'], '*')
        def walk(value):
            if isinstance(value, dict):
                if value.get('type') == 'elasticsearch' and 'uid' in value:
                    self.assertEqual(value['uid'], '${DS_WAZUH-2}')
                for child in value.values():walk(child)
            elif isinstance(value, list):
                for child in value:walk(child)
        walk(dashboard)
        for panel in dashboard['panels']:
            for target in panel.get('targets', []):
                self.assertIn('agent.name:${agent:lucene}', target['query'])


class GrafanaSourceTests(unittest.TestCase):
    def test_existing_source_is_updated_in_place_with_ca_verification(self):
        import tempfile
        from pathlib import Path
        from heist.monitoring.grafana.datasources import update_wazuh
        with tempfile.TemporaryDirectory() as directory:
            ca=Path(directory)/'ca.pem';ca.write_text('-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----')
            settings={'MONITORING_HOST':'10.0.0.103','WAZUH_INDEXER_CA_FILE':str(ca),
                      'WAZUH_INDEXER_USER':'reader','WAZUH_INDEXER_PASSWORD':'fixture-private'}
            session=Mock();session.get.return_value.status_code=200
            session.get.return_value.json.return_value={'uid':'existing-uid','name':'Wazuh-2','type':'elasticsearch',
                                                       'jsonData':{'esVersion':'7.10.2'},'isDefault':True,'version':4}
            session.put.return_value.status_code=200;session.put.return_value.json.return_value={'datasource':{'uid':'existing-uid'}}
            self.assertEqual(update_wazuh(session,'https://grafana.invalid',settings),'existing-uid')
            session.post.assert_not_called()
            self.assertEqual(session.put.call_args.args[0],'https://grafana.invalid/api/datasources/uid/existing-uid')
            payload=session.put.call_args.kwargs['json']
            self.assertIs(payload['jsonData']['tlsSkipVerify'],False)
            self.assertEqual(payload['jsonData']['timeField'],'timestamp')
            self.assertEqual(payload['jsonData']['esVersion'],'7.10.2')
            self.assertTrue(payload['isDefault'])
            self.assertEqual(payload['version'],4)
            self.assertEqual(payload['secureJsonData']['tlsCACert'],ca.read_text())

    def test_missing_trust_and_lookup_denial_never_write(self):
        import tempfile
        from pathlib import Path
        from heist.monitoring.grafana.datasources import update_wazuh
        session=Mock()
        with self.assertRaises(KeyError):update_wazuh(session,'https://grafana.invalid',{'MONITORING_HOST':'10.0.0.103'})
        with tempfile.TemporaryDirectory() as directory:
            ca=Path(directory)/'ca.pem';ca.write_text('-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----')
            session.get.return_value.status_code=403
            with self.assertRaises(RuntimeError):update_wazuh(session,'https://grafana.invalid',{
                'MONITORING_HOST':'10.0.0.103','WAZUH_INDEXER_CA_FILE':str(ca),
                'WAZUH_INDEXER_USER':'reader','WAZUH_INDEXER_PASSWORD':'fixture-private'})
        session.put.assert_not_called();session.post.assert_not_called()
