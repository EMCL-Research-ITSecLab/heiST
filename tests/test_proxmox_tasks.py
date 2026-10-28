import unittest
from unittest.mock import Mock

from backend.proxmox_tasks import wait_for_task


class ProxmoxTaskTests(unittest.TestCase):
    def test_waits_for_success_before_returning_clone_response(self):
        api = Mock(side_effect=[{'data': {'status': 'running'}}, {'data': {'status': 'stopped', 'exitstatus': 'OK'}}])
        sleep = Mock()
        response = {'data': 'UPID:pilot:clone:123:'}
        self.assertEqual(wait_for_task(api, 'pilot', response, sleep=sleep), response)
        self.assertEqual(api.call_count, 2)
        sleep.assert_called_once()
        self.assertIn('UPID%3Apilot%3Aclone%3A123%3A/status', api.call_args.args[1])

    def test_worker_failure_cannot_be_treated_as_a_completed_clone(self):
        api = Mock(return_value={'data': {'status': 'stopped', 'exitstatus': 'disk import failed'}})
        with self.assertRaisesRegex(RuntimeError, 'disk import failed'):
            wait_for_task(api, 'pilot', {'data': 'UPID:task'})

    def test_deadline_prevents_configuring_an_unfinished_clone(self):
        api = Mock(return_value={'data': {'status': 'running'}})
        sleep = Mock()
        with self.assertRaises(TimeoutError):
            wait_for_task(api, 'pilot', {'data': 'UPID:task'}, timeout=2,
                          clock=Mock(side_effect=[0, 1, 2]), sleep=sleep)
        self.assertEqual(api.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_missing_or_unexpected_status_fails_closed(self):
        for response in ({}, {'data': None}, {'data': {'status': 'unknown'}}, {'data': {'status': 'stopped'}}):
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                wait_for_task(Mock(return_value=response), 'pilot', {'data': 'UPID:task'})

    def test_invalid_identifiers_and_limits_are_rejected_before_polling(self):
        api = Mock()
        for response in ({}, {'data': None}, {'data': 'success'}):
            with self.assertRaises(ValueError):
                wait_for_task(api, 'pilot', response)
        for value in (0, -1, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                wait_for_task(api, 'pilot', {'data': 'UPID:task'}, timeout=value)
        api.assert_not_called()
