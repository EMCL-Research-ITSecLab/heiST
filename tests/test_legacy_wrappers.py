"""Existing installer commands stay untouched until their checkpoint is verified."""
from pathlib import Path
import tempfile
import unittest

from heist.rollout.legacy import checkpoint_wrappers


class LegacyWrapperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root/'bin').mkdir()
        self.wrapper = self.root/'bin/update'
        self.original = f'''#!/usr/bin/env bash
set -e

cd "{self.root}" || {{
  echo "Failed to cd to {self.root}" >&2
  exit 1
}}

exec "{self.root}/.venv/bin/python" -m suricata.update.data.update "$@"
'''.encode()
        self.wrapper.write_bytes(self.original)

    def test_suricata_update_is_checkpointed_without_removing_or_changing_it(self):
        before = self.wrapper.stat()
        saved = checkpoint_wrappers(self.root, set(), set())
        self.assertEqual(saved, {'bin/update': self.original.hex()})
        self.assertEqual(self.wrapper.read_bytes(), self.original)
        self.assertEqual(self.wrapper.stat().st_ino, before.st_ino)
        self.assertEqual(self.wrapper.stat().st_mtime_ns, before.st_mtime_ns)

    def test_modified_commands_and_symlinks_are_not_accepted(self):
        self.wrapper.write_bytes(self.original+b'echo modified\n')
        self.assertEqual(checkpoint_wrappers(self.root, set(), set()), {})
        self.wrapper.unlink()
        destination = self.root/'other'
        destination.write_bytes(self.original)
        self.wrapper.symlink_to(destination)
        self.assertEqual(checkpoint_wrappers(self.root, set(), set()), {})

    def test_external_exception_is_scoped_to_the_exact_untracked_command(self):
        self.assertEqual(checkpoint_wrappers(self.root, {'bin/update'}, set()), {})
        self.wrapper.rename(self.root/'bin/other')
        self.assertEqual(checkpoint_wrappers(self.root, set(), set()), {})
