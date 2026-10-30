import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class CachedAgentTests(unittest.TestCase):
    def test_verified_packages_reach_only_the_matching_local_installer(self):
        for kind, extension, command in (('deb_amd', 'deb', 'dpkg'), ('rpm_amd', 'rpm', 'rpm')):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                package = root / ('agent.' + extension)
                package.write_bytes(b'reviewed package fixture')
                checksum = root / (package.name + '.sha256')
                checksum.write_text(hashlib.sha256(package.read_bytes()).hexdigest() + '\n')
                result = self.run_installer(kind, root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / 'trace').read_text().splitlines(), ['--install', str(package)])

    def test_changed_or_symlinked_packages_never_reach_the_installer(self):
        for unsafe in ('changed', 'symlink', 'missing', 'invalid-checksum'):
            with self.subTest(unsafe=unsafe), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                package = root / 'agent.deb'
                package.write_bytes(b'original')
                checksum = root / 'agent.deb.sha256'
                checksum.write_text(hashlib.sha256(b'original').hexdigest() + '\n')
                if unsafe == 'changed':
                    package.write_bytes(b'changed')
                elif unsafe == 'symlink':
                    package.rename(root / 'elsewhere')
                    package.symlink_to(root / 'elsewhere')
                elif unsafe == 'missing':
                    checksum.unlink()
                else:
                    checksum.write_text('not a digest\n')
                result = self.run_installer('deb_amd', root)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / 'trace').exists())

    def run_installer(self, kind, root):
        for command in ('dpkg', 'rpm'):
            installer = root / command
            installer.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$INSTALL_TRACE"\n')
            installer.chmod(0o755)
        helper = Path(__file__).resolve().parents[1] / 'heist/monitoring/wazuh/agent/linux/config/install_cached_agent.sh'
        return subprocess.run(['bash', str(helper), kind, str(root)], capture_output=True, text=True,
                              env={**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                                   'INSTALL_TRACE': str(root / 'trace')})
