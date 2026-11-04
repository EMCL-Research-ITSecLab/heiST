"""Execute the actual launch module with injected infrastructure boundaries."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from heist.platform.models import Challenge, ChallengeTemplate


class ColdLaunchFlagTests(unittest.TestCase):
    def launch(self, ready):
        from heist.platform.challenges import launch as launch_module
        instance = Challenge(challenge_id=10, template=ChallengeTemplate(5), subnet='10.128.0.0/28')
        self.assertEqual(instance.template.flags, [])
        noop = Mock()
        namespace = {name: noop for name in (
            'launch_timing_logger', 'require_available_template', 'acquire_exclusive_launch_lock', 'release_exclusive_launch_lock',
            'fetch_machines', 'fetch_networks_and_connections', 'start_dnsmasq_instances',
            'force_dhcp_renew_on_windows_machines', 'add_iptables_rules', 'finalize_launch')}
        namespace['renew_linux_entrypoints'] = Mock()
        flags = [{'id': 1, 'order_index': 1, 'user_specific': True, 'machine_template_id': 123,
                  'flag': 'synthetic-test-secret'}]

        def load_flags(template, connection):
            template.flags = flags

        def ready_instance(template, connection, user):
            if ready:
                instance.template = template
                return instance
            return None

        processed = Mock()
        namespace.update(
            template_guard=lambda *args, **kwargs: nullcontext(),
            os=SimpleNamespace(makedirs=Mock()),
            db_connection_context=lambda: nullcontext(object()),
            time=SimpleNamespace(time=lambda: 0, sleep=lambda seconds: None),
            print=lambda *args, **kwargs: None,
            ChallengeTemplate=ChallengeTemplate,
            fetch_user_vpn_ip=Mock(return_value='10.8.0.2'),
            fetch_user_email=Mock(return_value='pilot@example.test'),
            fetch_user_unique_id=Mock(return_value='test-student'),
            fetch_challenge_flags=load_flags,
            get_ready_challenge=ready_instance,
            try_attach_to_running_warmup=Mock(return_value=None),
            warmup_challenge=Mock(return_value=instance),
            add_running_challenge_to_user=Mock(),
            process_all_user_specific_flags=processed,
            stop_challenge=Mock())
        with patch.dict(launch_module.__dict__, namespace):
            launch_module.launch_challenge(5, 2, 'vpn-sensor', 'dmz-sensor')
        processed.assert_called_once_with(instance, 'pilot@example.test', 'test-student')
        self.assertEqual(processed.call_args.args[0].template.flags, flags)
        namespace['stop_challenge'].assert_not_called()
        self.assertEqual(namespace['warmup_challenge'].call_count, 0 if ready else 1)

    def test_cold_start_preserves_loaded_user_specific_flags(self):
        self.launch(ready=False)

    def test_ready_pool_start_preserves_loaded_user_specific_flags(self):
        self.launch(ready=True)
