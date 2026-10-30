import unittest

from heist.backend.vm_settings import challenge_cpu_type


class VMCPUSettingTests(unittest.TestCase):
    def test_legacy_default_and_modern_operator_baselines(self):
        self.assertEqual(challenge_cpu_type({}), 'kvm64')
        for value in ('host', 'x86-64-v2-AES', 'custom-course-baseline'):
            self.assertEqual(challenge_cpu_type({'CHALLENGE_VM_CPU_TYPE': value}), value)

    def test_invalid_model_is_rejected_before_api_use(self):
        for value in ('', None, 'host,flags=+vmx', 'host; command', '../host', 'host model'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                challenge_cpu_type({'CHALLENGE_VM_CPU_TYPE': value})


if __name__ == '__main__':
    unittest.main()
