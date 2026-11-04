"""Rehearse TLS and selective agent removal on an isolated monitoring appliance.

The certificate must have been copied through a trusted administration channel.
No existing agent is enrolled again or removed. Credentials stay in the private
test-host environment file and are never included in test output.
"""
import os
from pathlib import Path
import unittest

from heist.infrastructure.monitoring.wazuh import Wazuh


class MonitoringTests(unittest.TestCase):
    def test_verified_tls_enrollment_and_selective_idempotent_removal(self):
        from dotenv import dotenv_values
        values = dotenv_values(os.environ['HEIST_TEST_BACKEND_ENV'])
        certificate = os.environ['HEIST_TEST_MONITORING_CERTIFICATE']
        machine_id = int(os.environ['HEIST_TEST_AGENT_MACHINE_ID'])
        self.assertGreater(machine_id, 100)
        self.assertLess(machine_id, 2**31)
        arguments = (values['MONITORING_HOST'], values.get('WAZUH_API_PORT', '55000'),
                     values.get('WAZUH_API_USER', 'wazuh-wui'), values['WAZUH_API_PASSWORD'])
        client = Wazuh(*arguments, pinned_certificate=certificate)
        self.addCleanup(client.close)
        token = client.call('POST', '/security/user/authenticate', raw=True,
                            auth=client.credentials, params={'raw': 'true'})
        headers = {'Authorization': 'Bearer '+token}
        name = 'agent_'+str(machine_id)

        def inventory():
            result = client.call('GET', '/agents', headers=headers, params={'name': name})
            self.assertEqual(result.get('total_failed_items', 0), 0)
            self.assertIsInstance(result.get('affected_items'), list)
            return result['affected_items']

        self.assertEqual(inventory(), [], 'Choose an unused disposable agent name')
        # Enrollment returns a direct id/key object on supported Wazuh versions;
        # confirm with the inventory rather than assuming affected_items here.
        attempted = False
        try:
            attempted = True
            client.call('POST', '/agents', headers=headers, json={'name': name})
            agents = inventory()
            self.assertEqual(len(agents), 1)
            self.assertEqual(agents[0]['name'], name)
            self.assertNotEqual(str(agents[0]['id']), '000')
            self.assertTrue(client.remove_agent(machine_id))
            self.assertEqual(inventory(), [])
            self.assertTrue(client.remove_agent(machine_id))
        finally:
            if attempted:
                client.remove_agent(machine_id)


if __name__ == '__main__':
    if os.environ.get('HEIST_ISOLATED_MONITORING_TESTS') != '1':
        raise SystemExit('Requires HEIST_ISOLATED_MONITORING_TESTS=1 on a disposable monitoring appliance')
    for key in ('HEIST_TEST_BACKEND_ENV', 'HEIST_TEST_MONITORING_CERTIFICATE'):
        path = Path(os.environ.get(key, ''))
        if not path.is_absolute() or not path.is_file():
            raise SystemExit('Set '+key+' to a trusted private test-host file')
    if not os.environ.get('HEIST_TEST_AGENT_MACHINE_ID', '').isascii() or not os.environ['HEIST_TEST_AGENT_MACHINE_ID'].isdigit():
        raise SystemExit('Set HEIST_TEST_AGENT_MACHINE_ID to an unused disposable agent machine ID')
    unittest.main(verbosity=2)
