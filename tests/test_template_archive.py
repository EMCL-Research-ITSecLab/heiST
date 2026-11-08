"""Read-only template export rejects foreign identities and uncovered storage."""
import stat
from types import SimpleNamespace
import unittest
from heist.maintenance.template_archive import inspect

UUID = '6b702369-cf89-47fe-847e-4b38e9478066'


class TemplateArchiveTests(unittest.TestCase):
    def setUp(self):
        self.configuration = ('name: course-template\ntemplate: 1\nsmbios1: uuid='+UUID+
                              '\nsata0: local-lvm:base-123-disk-0\n')
        self.readonly = '1\n'
        self.status = 'status: stopped\n'
        self.size = '8388608\n'
        self.path = '/dev/pve/base-123-disk-0'
        self.calls = []

    def command(self, args):
        self.calls.append(args)
        if args[:2] == ['qm', 'status']:return self.status
        if args[:2] == ['qm', 'config']:return self.configuration
        if args[:2] == ['pvesm', 'path']:return self.path+'\n'
        if args[:2] == ['blockdev', '--getro']:return self.readonly
        if args[:2] == ['blockdev', '--getsize64']:return self.size
        raise AssertionError('Unexpected command: '+repr(args))

    def inspect(self, identifier=123, expected=UUID, mode=stat.S_IFBLK):
        return inspect(identifier, expected, run=self.command,
                       metadata=lambda _: SimpleNamespace(st_mode=mode, st_rdev=1234))

    def test_archive_has_native_disk_mapping_and_omitted_legacy_size_is_supported(self):
        value = self.inspect()
        self.assertEqual(value.disks, (('sata0',self.path,'local-lvm',8388608,1234),))
        self.assertEqual(value.archive_configuration(), self.configuration+'#qmdump#map:sata0:drive-sata0:local-lvm:raw:\n')
        self.assertTrue(all(args[0] in ('qm','pvesm','blockdev') for args in self.calls))
        self.assertTrue(all('set' not in args and 'start' not in args for args in self.calls))

    def test_foreign_non_template_and_running_guest_are_refused(self):
        with self.assertRaisesRegex(RuntimeError,'identity'):
            self.inspect(expected='5898f7b2-d8bd-42e0-a43e-d90f0f7d19b6')
        self.configuration = self.configuration.replace('template: 1','template: 0')
        with self.assertRaisesRegex(RuntimeError,'identity'):self.inspect()
        self.status = 'status: running'
        with self.assertRaisesRegex(RuntimeError,'stopped'):self.inspect()

    def test_writable_file_passthrough_excluded_or_unmanaged_disks_are_refused(self):
        original = self.configuration
        for value in ('local-lvm:base-123-disk-0,backup=0','local-lvm:base-123-disk-0,shared=1',
                      '/dev/foreign','local:cloudinit','local:disk;command'):
            self.configuration = original.replace('local-lvm:base-123-disk-0', value)
            with self.subTest(value=value),self.assertRaises(RuntimeError):self.inspect()
        self.configuration = original
        self.readonly = '0\n'
        with self.assertRaisesRegex(RuntimeError,'already be read-only'):self.inspect()
        self.readonly = '1\n'
        with self.assertRaisesRegex(RuntimeError,'raw block'):self.inspect(mode=stat.S_IFREG)
        self.size = '0'
        with self.assertRaisesRegex(RuntimeError,'capacity'):self.inspect()

    def test_locks_duplicate_keys_and_external_state_are_refused(self):
        original = self.configuration
        for extra in ('lock: backup\n','sata0: duplicate\n','args: external\n',
                      'unused0: local:disk\n','net30: provisioning\n','hostpci0: 0000:00:01\n'):
            self.configuration = original+extra
            with self.subTest(extra=extra),self.assertRaises(RuntimeError):self.inspect()

    def test_changed_state_and_invalid_id_are_refused_before_export(self):
        calls = iter(('status: stopped','status: running'))
        run = self.command
        def changing(args):
            return next(calls) if args[:2] == ['qm','status'] else run(args)
        with self.assertRaisesRegex(RuntimeError,'changed'):
            inspect(123,UUID,run=changing,metadata=lambda _:SimpleNamespace(st_mode=stat.S_IFBLK,st_rdev=1))
        for identifier in (True,99,1000000000,'123'):
            with self.subTest(identifier=identifier),self.assertRaises(ValueError):self.inspect(identifier)
