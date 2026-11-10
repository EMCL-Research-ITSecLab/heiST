"""Health must distinguish running processes, fresh evidence and coverage."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch

from heist.monitoring.health import (capture_configuration, containers, dashboards, database_backup, eve_health,
                                    prometheus_targets, proxmox_storage, publish, receipt, remote_checks,
                                    resources, sanitize, sensor_interfaces, services, vector_transport)


NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


def snapshot(state='ok', **extra):
    return {'schema': 1, 'checked_at': NOW.isoformat(),
            'checks': [{'id': 'host.sensor', 'label': 'Sensor', 'state': state, 'summary': 'Checked', **extra}]}


class HealthTests(unittest.TestCase):
    def test_vector_transport_detects_wrong_certificate_without_sending_events(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)/'vector.toml'
            config.write_text('[sinks.clickhouse]\nendpoint="https://monitor.invalid:8443"\n[sinks.clickhouse.tls]\nca_file="/private/ca.pem"\n')
            run = Mock(return_value=subprocess.CompletedProcess([], 0, 'argv[]=vector --config '+str(config)))
            connection = Mock()
            connection.__enter__ = Mock(return_value=connection)
            connection.__exit__ = Mock(return_value=False)
            connect = Mock(return_value=connection)
            trust = Mock()
            trust.wrap_socket.side_effect = ssl.SSLCertVerificationError('untrusted fixture certificate')
            result = vector_transport(run=run, connect=connect, context=Mock(return_value=trust))
            self.assertEqual(result['state'], 'failed')
            self.assertIn('4 failed', result['summary'])
            trust.wrap_socket.assert_called_with(connection, server_hostname='monitor.invalid')
            connection.send.assert_not_called()

    def test_vector_transport_refuses_disabled_verification_before_connecting(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)/'vector.toml'
            config.write_text('[sinks.clickhouse]\nendpoint="https://monitor.invalid:8443"\n[sinks.clickhouse.tls]\nca_file="/private/ca.pem"\nverify_certificate=false\n')
            run = Mock(return_value=subprocess.CompletedProcess([], 0, '--config '+str(config)))
            connect = Mock()
            self.assertEqual(vector_transport(run=run, connect=connect)['state'], 'failed')
            connect.assert_not_called()

    def test_vector_transport_reports_unresolved_units_as_unknown(self):
        result = vector_transport(run=Mock(return_value=subprocess.CompletedProcess([], 1, '')))
        self.assertEqual(result['state'], 'unknown')
        self.assertIn('4 unverified', result['summary'])

    def test_old_or_incomplete_source_backup_is_not_hidden_by_successful_archive_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);generation=root/'20261110T120000Z-backup-aaaaaaaaaaaa';generation.mkdir()
            (generation/'database.backup').write_bytes(b'PGDMPfixture')
            value={'schema':1,'created_at':NOW.isoformat(),'bytes':12,'sha256':'a'*64,'secret':'private'}
            (generation/'metadata.json').write_text(json.dumps(value))
            (root/'latest.backup').symlink_to(generation.name+'/database.backup')
            status=database_backup(root=root,now=NOW)
            self.assertEqual(status['state'],'ok');self.assertNotIn('private',json.dumps(status))
            self.assertEqual(database_backup(root=root,now=NOW+timedelta(minutes=31))['state'],'failed')
            (generation/'database.backup').write_bytes(b'incomplete')
            self.assertEqual(database_backup(root=root,now=NOW)['state'],'failed')
            (root/'latest.backup').unlink();(root/'latest.backup').symlink_to('/etc/passwd')
            self.assertEqual(database_backup(root=root,now=NOW)['state'],'failed')

    def test_prometheus_requires_every_expected_job_and_fresh_successful_scrapes(self):
        jobs=['monitoring-vm','proxmox-node','proxmox-pve','apache','webserver-node','database-node','postgres']
        targets=[{'labels':{'job':job},'health':'up','lastScrape':NOW.isoformat(),'scrapeUrl':'private'} for job in jobs]
        client=Mock();response=client.getresponse.return_value;response.status=200
        response.read.return_value=json.dumps({'status':'success','data':{'activeTargets':targets}}).encode()
        self.assertEqual(prometheus_targets(connection=client,now=NOW)['state'],'ok')
        self.assertEqual(client.request.call_args.args,('GET','/api/v1/targets?state=active'))
        self.assertEqual(prometheus_targets(connection=client,now=NOW+timedelta(minutes=4))['state'],'failed')
        targets.pop();response.read.return_value=json.dumps({'status':'success','data':{'activeTargets':targets}}).encode()
        value=prometheus_targets(connection=client,now=NOW)
        self.assertEqual(value['state'],'failed');self.assertNotIn('private',json.dumps(value))
        response.status=302
        self.assertEqual(prometheus_targets(connection=client,now=NOW)['state'],'failed')

    def test_proxmox_capacity_detects_full_and_inactive_stores_without_exposing_paths(self):
        run=Mock()
        for store,state in [({'enabled':1,'active':1,'used':90,'total':100},'warning'),
                            ({'enabled':1,'active':1,'used':99,'total':100},'failed'),
                            ({'enabled':1,'active':0},'failed')]:
            run.return_value=subprocess.CompletedProcess([],0,json.dumps([dict(store,path='private')]))
            value=proxmox_storage(run=run,node='pilot')
            self.assertEqual(value['state'],state);self.assertNotIn('private',json.dumps(value))
        run.return_value=subprocess.CompletedProcess([],0,'[]')
        self.assertEqual(proxmox_storage(run=run,node='pilot')['state'],'unknown')
        self.assertEqual(run.call_args.args[0],['pvesh','get','/nodes/pilot/storage','--output-format','json'])

    def test_resource_pressure_is_visible_and_missing_counters_remain_unknown(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'meminfo').write_text('MemTotal: 1000 kB\nMemAvailable: 10 kB\n')
            result=resources('host',proc=root,statvfs=lambda path:SimpleNamespace(f_files=100,f_favail=1),load=lambda:(9,0,0),cpus=lambda:2)
            self.assertTrue(all(c['state']=='failed' for c in result))
            (root/'meminfo').write_text('invalid')
            result=resources('host',proc=root,statvfs=lambda path:SimpleNamespace(f_files=0),load=lambda:(0,0,0),cpus=lambda:None)
            self.assertTrue(all(c['state']=='unknown' for c in result))

    def test_snapshot_freshness_and_unknown_coverage_never_claim_success(self):
        self.assertEqual(sanitize(snapshot(), now=NOW)['status'], 'ok')
        self.assertEqual(sanitize(snapshot('unknown'), now=NOW)['status'], 'unknown')
        self.assertEqual(sanitize(snapshot('failed'), now=NOW)['status'], 'failed')
        self.assertEqual(sanitize(snapshot(), now=NOW+timedelta(seconds=181))['status'], 'stale')
        with self.assertRaises(ValueError):
            sanitize(snapshot(), now=NOW-timedelta(seconds=31))
        value = snapshot()
        value['checked_at'] = '2026-11-10T12:00:00'
        with self.assertRaises(ValueError):
            sanitize(value, now=NOW)

    def test_receipts_are_bounded_and_only_named_fields_are_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'status.json'
            settings = {'HEIST_MONITORING_STATUS_FILE': str(path)}
            self.assertEqual(receipt({})['status'], 'not configured')
            self.assertEqual(receipt(settings)['status'], 'unavailable')
            path.write_text(json.dumps(snapshot(password='private')))
            self.assertNotIn('private', json.dumps(receipt(settings, now=NOW)))
            for body in ('[]', 'null', '{}', 'x'*65537):
                path.write_text(body)
                self.assertEqual(receipt(settings)['status'], 'unavailable')

    def test_invalid_or_duplicate_checks_are_rejected(self):
        for change in ({'state': 'healthy'}, {'id': '../secret'}, {'summary': 'x'*401}, {'label': None}):
            value = snapshot()
            value['checks'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                sanitize(value, now=NOW)
        value = snapshot()
        value['checks'] *= 2
        with self.assertRaises(ValueError):
            sanitize(value, now=NOW)

    def test_systemd_missing_unit_does_not_hide_other_observations(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 1,
            'Id=backend.service\nLoadState=loaded\nActiveState=active\n\n'
            'Id=suricata-dmz.service\nLoadState=not-found\nActiveState=inactive\n'))
        checks = {c['id']:c for c in services('host', run=run)}
        self.assertEqual(checks['host.service.backend.service']['state'], 'ok')
        self.assertEqual(checks['host.service.suricata-dmz.service']['state'], 'failed')
        self.assertEqual(checks['host.service.vector-dmz.service']['state'], 'unknown')
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_idle_successful_oneshot_is_healthy_but_never_run_is_unknown(self):
        for start, state in [('Tue 2026-11-10 12:00:00 UTC', 'ok'), ('', 'unknown')]:
            run = Mock(return_value=subprocess.CompletedProcess([], 0,
                'Id=heist-expiry.service\nLoadState=loaded\nActiveState=inactive\nResult=success\nExecMainStartTimestamp='+start))
            value = next(c for c in services('host', run=run) if c['id']=='host.service.heist-expiry.service')
            self.assertEqual(value['state'], state)

    def test_eve_heartbeat_uses_stats_even_without_traffic_and_excludes_event_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'eve_dmz.json'
            for drops, expected in [(0, 'ok'), (2, 'warning')]:
                path.write_text(json.dumps({'event_type':'stats','timestamp':NOW.isoformat(),
                    'stats':{'capture':{'kernel_packets':0,'kernel_drops':drops}}, 'payload':'private'})+'\n')
                result = eve_health('dmz', root=Path(directory), now=NOW)
                self.assertEqual(result['state'], expected)
                self.assertNotIn('private', json.dumps(result))
                self.assertEqual(eve_health('dmz', root=Path(directory), now=NOW+timedelta(minutes=5))['state'], 'unknown')
            path.write_text('{"event_type":"flow","src_ip":"private"}\n')
            self.assertEqual(eve_health('dmz', root=Path(directory), now=NOW)['state'], 'unknown')

    def test_nfqueue_heartbeat_does_not_require_af_packet_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'eve_backend.json').write_text(json.dumps({
                'event_type':'stats', 'timestamp':NOW.isoformat(),
                'stats':{'ips':{},'decoder':{'pkts':12}}}))
            value = eve_health('backend',root=Path(directory),now=NOW)
            self.assertEqual(value['state'],'ok')
            self.assertIn('Queue loss',value['summary'])

    def test_shared_capture_fanout_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'suricata-ctf.yaml').write_text('af-packet:\n  - interface: ctf\n    cluster-id: 99\n')
            for group, expected in [(99, 'failed'), (100, 'ok')]:
                (root/'suricata-dmz.yaml').write_text('af-packet:\n  - interface: dmz\n    cluster-id: '+str(group)+' # generated\n')
                self.assertEqual(capture_configuration(root=root)['state'], expected)

    def test_dummy_interface_unknown_operstate_is_not_a_false_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'suricata-ctf.yaml').write_text('af-packet:\n  - interface: ctf_monitoring\n')
            (root/'ctf_monitoring').mkdir()
            (root/'ctf_monitoring/flags').write_text('0x1003')
            (root/'ctf_monitoring/operstate').write_text('unknown')
            checks = sensor_interfaces(config_root=root, net_root=root)
            self.assertEqual(checks[0]['state'], 'ok')
            self.assertEqual(checks[1]['state'], 'failed')

    def test_grafana_inventory_is_readonly_and_empty_dashboards_are_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'grafana.db'
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE dashboard (is_folder INTEGER)')
            db.commit()
            self.assertEqual(dashboards(path)['state'], 'failed')
            db.execute('INSERT INTO dashboard VALUES (0)')
            db.commit()
            self.assertEqual(dashboards(path)['state'], 'ok')
            db.close()
            missing = Path(directory)/'missing.db'
            self.assertEqual(dashboards(missing)['state'], 'unknown')
            self.assertFalse(missing.exists())

    def test_containerized_wazuh_does_not_require_host_manager_unit(self):
        run = Mock(return_value=subprocess.CompletedProcess([],0,
            'single-node-wazuh.manager-1\trunning\tUp 1 hour\n'
            'single-node-wazuh.indexer-1\trunning\tUp 1 hour (unhealthy)\n'))
        result = containers(run=run)
        self.assertEqual([c['state'] for c in result], ['ok','failed','failed'])
        self.assertFalse(any('wazuh-manager.service' in c['label'] for c in services('monitoring', run=run)))

    def test_remote_roles_cannot_be_duplicated_or_used_as_arbitrary_commands(self):
        with self.assertRaises(ValueError):
            remote_checks({'remotes': [{'role':'shell','host':'example.invalid'}]})
        with patch('heist.remote.SSH') as ssh:
            ssh.return_value.run.side_effect = subprocess.TimeoutExpired('ssh',15)
            checks = remote_checks({'remotes':[{'role':'monitoring','host':'example.invalid'}]})
            self.assertEqual(checks[0]['state'],'unknown')
            self.assertEqual(ssh.return_value.run.call_args.args[0],['sudo','-n','python3','-','--role','monitoring'])
            self.assertEqual(ssh.return_value.run.call_args.kwargs['timeout'],15)

    def test_atomic_publication_has_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory, patch('heist.monitoring.health.sanitize', side_effect=lambda value:value):
            path=Path(directory)/'status.json'
            publish(path,snapshot())
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(json.loads(path.read_text())['schema'],1)
            self.assertEqual(list(Path(directory).glob('.status-*')),[])
