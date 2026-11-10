"""Authenticated telemetry probes must not turn outages or missing data green."""
from datetime import datetime, timedelta, timezone
import importlib
import json
import unittest
from unittest.mock import Mock, patch
import requests

from heist.monitoring import agents
from heist.monitoring.health import sanitize_agents
from heist.monitoring.pipeline import HTTPS, TITLES, clickhouse, grafana

NOW = datetime(2026,11,10,12,tzinfo=timezone.utc)


class PipelineTests(unittest.TestCase):
    def settings(self,prefix):
        return {'MONITORING_HOST':'monitoring.example.invalid',prefix+'_USER':'reader',prefix+'_PASSWORD':'private'}

    def test_https_is_verified_bounded_and_does_not_follow_redirects(self):
        session=Mock();reply=session.get.return_value
        reply.status_code=200;reply.iter_content.return_value=[b'{"database":"ok"}']
        client=HTTPS(self.settings('GRAFANA'),'GRAFANA',3000,session=session)
        self.assertEqual(client.get('/api/health'),{'database':'ok'})
        self.assertFalse(session.trust_env)
        self.assertIs(session.get.call_args.kwargs['verify'],True)
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
        self.assertEqual(session.get.call_args.kwargs['timeout'],(3,5))
        reply.close.assert_called_once()
        for status,body in [(302,b'{}'),(200,b'x'*65537),(200,b'invalid')]:
            reply.status_code=status;reply.iter_content.return_value=[body]
            with self.assertRaises((RuntimeError,ValueError)):client.get('/api/health')

    def test_missing_auth_wrong_host_and_relative_ca_fail_closed(self):
        for changes in ({'MONITORING_HOST':'https://evil.invalid/path'},{'GRAFANA_CA_FILE':'../ca.pem'}):
            with self.assertRaises(ValueError):HTTPS({**self.settings('GRAFANA'),**changes},'GRAFANA',3000)
        self.assertEqual(grafana({})[0]['state'],'unknown')
        self.assertEqual(clickhouse({})[0]['state'],'unknown')

    def test_grafana_requires_authenticated_health_and_all_expected_dashboards(self):
        client=Mock();factory=Mock(return_value=client)
        for titles,state in [(TITLES,'ok'),(TITLES[:1],'failed')]:
            client.get.side_effect=[{'database':'ok'},[{'title':title} for title in titles]]
            result=grafana(self.settings('GRAFANA'),client_factory=factory)
            self.assertEqual(result[-1]['state'],state)
        client.get.side_effect=requests.exceptions.SSLError('private')
        self.assertEqual(grafana(self.settings('GRAFANA'),client_factory=factory)[0]['state'],'failed')
        self.assertNotIn('private',json.dumps(grafana(self.settings('GRAFANA'),client_factory=factory)))

    def test_clickhouse_heartbeat_checks_distinct_tables_without_selecting_student_events(self):
        client=Mock();client.get.side_effect=[{'samples':'3','latest':str(int(NOW.timestamp()))},
            {'samples':'0','latest':'0'},{'samples':1,'latest':int((NOW-timedelta(minutes=4)).timestamp())}]
        result=clickhouse(self.settings('CLICKHOUSE'),client_factory=Mock(return_value=client),now=NOW)
        self.assertEqual([c['state'] for c in result],['ok','failed','failed'])
        for call in client.get.call_args_list:
            params=call.kwargs['params']
            self.assertEqual(params['readonly'],1)
            self.assertIn("event_type='stats'",params['query'])
            self.assertNotIn('payload',params['query'])
        client.close.assert_called_once()

    def test_invalid_sink_response_and_future_clock_are_not_healthy(self):
        client=Mock()
        for body in ({'samples':'x'}, {'samples':1,'latest':int((NOW+timedelta(minutes=5)).timestamp())}):
            client.get.side_effect=None;client.get.return_value=body
            result=clickhouse(self.settings('CLICKHOUSE'),client_factory=Mock(return_value=client),now=NOW)
            self.assertTrue(all(c['state']=='failed' for c in result))

    def test_agent_collection_closes_transport_and_does_not_expose_credentials(self):
        client=Mock();client.agents.side_effect=RuntimeError('private')
        settings={'MONITORING_HOST':'host','WAZUH_API_USER':'reader','WAZUH_API_PASSWORD':'private'}
        value,status=agents.collect(settings,client_factory=Mock(return_value=client))
        self.assertEqual(value['status'],'unavailable')
        self.assertEqual(status['state'],'failed')
        self.assertNotIn('private',json.dumps((value,status)))
        client.close.assert_called_once()

    def test_instance_projection_excludes_other_instances_and_detects_stale_agents(self):
        inventory={'status':'ready','agents':[{'machine_id':12,'status':'active','last_keepalive':NOW.isoformat()},
                   {'machine_id':99,'status':'active','last_keepalive':NOW.isoformat()}]}
        snapshot={'status':'unknown','checked_at':NOW.isoformat(),'agent_inventory':inventory,'checks':[]}
        machines=[{'id':12,'status':'running'},{'id':13,'status':'stopped'}]
        value=agents.instance(machines,{},snapshot=snapshot,now=NOW)
        self.assertEqual([m['machine_id'] for m in value['machines']],[12,13])
        self.assertEqual([m['agent_status'] for m in value['machines']],['active','missing'])
        self.assertEqual(value['command_delivery'],'unverified')
        self.assertEqual(agents.instance(machines,{},snapshot=snapshot,now=NOW+timedelta(minutes=4))['machines'][0]['agent_status'],'stale')
        snapshot['status']='stale'
        self.assertTrue(all(m['agent_status']=='unknown' for m in agents.instance(machines,{},snapshot=snapshot,now=NOW)['machines']))

    def test_agent_receipt_rejects_future_duplicate_and_private_fields(self):
        item={'machine_id':1,'status':'active','last_keepalive':NOW.isoformat(),'secret':'private'}
        value=sanitize_agents({'status':'ready','agents':[item]},NOW)
        self.assertNotIn('private',json.dumps(value))
        with self.assertRaises(ValueError):sanitize_agents({'status':'ready','agents':[item,item]},NOW)
        item['last_keepalive']=(NOW+timedelta(minutes=1)).isoformat()
        with self.assertRaises(ValueError):sanitize_agents({'status':'ready','agents':[item]},NOW)

    def test_grafana_operator_utility_cannot_disable_tls_process_wide(self):
        original=requests.Session.request
        module=importlib.import_module('heist.monitoring.grafana.grafana_updater')
        self.assertIs(requests.Session.request,original)
        with patch.object(module,'ADMIN_PASS','fixture-password'):
            session=module.get_session()
            for invalid in (False,0,None,'../ca.pem'):
                with self.assertRaises(ValueError):session.get('https://example.invalid',verify=invalid)
            session.close()
