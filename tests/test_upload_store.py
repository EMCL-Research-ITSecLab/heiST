import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from heist.artifacts.uploads import UploadError, UploadStore
from heist.files import maintenance_lock


class UploadStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'store'
        self.store = UploadStore(self.root, clock=lambda: 1000)
        self.store.CHUNK_BYTES = 4

    def create(self, size=7):
        return self.store.create(1, 'machine.ova', size, 'linux')['id']

    def test_out_of_order_duplicate_restart_seal_and_quarantine(self):
        identifier = self.create()
        self.store.put(1, identifier, 1, io.BytesIO(b'efg'))
        self.store.put(1, identifier, 0, io.BytesIO(b'abcd'))
        self.store.put(1, identifier, 0, io.BytesIO(b'abcd'))
        restarted = UploadStore(self.root, clock=lambda: 1000)
        self.assertEqual(restarted.status(1, identifier)['received'], [0, 1])
        self.assertEqual(restarted.seal(1, identifier)['state'], 'SEALED')
        self.assertEqual(restarted.seal(1, identifier)['state'], 'SEALED')
        self.assertEqual((self.root/'1'/identifier/'payload.ova').read_bytes(), b'abcdefg')
        with self.assertRaises(UploadError):
            restarted.cancel(1, identifier)
        with self.assertRaises(UploadError):
            restarted.put(1, identifier, 0, io.BytesIO(b'abcd'))

    def test_owner_size_index_conflict_and_missing_chunks(self):
        identifier = self.create()
        for owner, index, data in ((2, 0, b'abcd'), (1, -1, b'abcd'), (1, True, b'abcd'),
                                   (1, 2, b'abcd'), (1, 0, b'abc'), (1, 1, b'abcd')):
            with self.subTest(owner=owner, index=index, data=data), self.assertRaises(UploadError):
                self.store.put(owner, identifier, index, io.BytesIO(data))
        self.store.put(1, identifier, 0, io.BytesIO(b'abcd'))
        with self.assertRaises(UploadError):
            self.store.put(1, identifier, 0, io.BytesIO(b'wxyz'))
        with self.assertRaises(UploadError):
            self.store.seal(1, identifier)
        self.assertFalse((self.root/'1'/identifier/'payload.ova').exists())

    def test_durable_chunk_receipt_recovers_after_interrupted_metadata_write(self):
        identifier = self.create()
        with patch('heist.artifacts.uploads.write_json', side_effect=OSError('disk fault')):
            with self.assertRaises(OSError):
                self.store.put(1, identifier, 0, io.BytesIO(b'abcd'))
        self.assertEqual(self.store.status(1, identifier)['received'], [])
        self.assertEqual(self.store.put(1, identifier, 0, io.BytesIO(b'abcd'))['received'], [0])

    def test_corrupt_chunk_never_seals_and_cancel_is_repeatable(self):
        identifier = self.create(size=4)
        self.store.put(1, identifier, 0, io.BytesIO(b'abcd'))
        (self.root/'1'/identifier/'0.chunk').write_bytes(b'bad!')
        with self.assertRaises(UploadError):
            self.store.seal(1, identifier)
        self.assertFalse((self.root/'1'/identifier/'payload.ova').exists())
        self.assertEqual(self.store.cancel(1, identifier)['state'], 'CANCELLED')
        self.assertEqual(self.store.cancel(1, identifier)['state'], 'CANCELLED')
        self.assertFalse((self.root/'1'/identifier/'0.chunk').exists())

    def test_limits_expiry_quota_and_storage_failure(self):
        for owner, name, size, guest in ((True, 'a.ova', 1, 'linux'), (1, '../a.ova', 1, 'linux'),
                                         (1, 'a.ovf', 1, 'linux'), (1, 'a.ova', 0, 'linux'),
                                         (1, 'a.ova', True, 'linux'), (1, 'a.ova', 1, 'other')):
            with self.subTest(name=name, size=size), self.assertRaises(UploadError):
                self.store.create(owner, name, size, guest)
        identifier = self.create()
        self.create()
        with self.assertRaises(UploadError):
            self.create()
        self.store.clock = lambda: 1000+self.store.EXPIRY_SECONDS
        with self.assertRaises(UploadError):
            self.store.put(1, identifier, 0, io.BytesIO(b'abcd'))
        self.store.cancel(1, identifier)
        with patch('heist.artifacts.uploads.shutil.disk_usage') as usage:
            usage.return_value.free = 0
            with self.assertRaises(UploadError):
                self.create()

    def test_seal_crash_before_receipt_can_be_retried_or_cancelled_without_leaking_payload(self):
        identifier = self.create(size=4)
        self.store.put(1, identifier, 0, io.BytesIO(b'abcd'))
        with patch('heist.artifacts.uploads.write_json', side_effect=OSError('receipt fault')):
            with self.assertRaises(OSError):
                self.store.seal(1, identifier)
        self.assertEqual(self.store.status(1, identifier)['state'], 'RECEIVING')
        self.assertTrue((self.root/'1'/identifier/'payload.ova').exists())
        self.assertEqual(self.store.seal(1, identifier)['state'], 'SEALED')
        other = self.create(size=4)
        self.store.put(1, other, 0, io.BytesIO(b'efgh'))
        with patch('heist.artifacts.uploads.write_json', side_effect=OSError('receipt fault')):
            with self.assertRaises(OSError):
                self.store.seal(1, other)
        self.store.cancel(1, other)
        self.assertFalse((self.root/'1'/other/'payload.ova').exists())

    def test_concurrent_operation_cannot_bypass_upload_lease(self):
        identifier = self.create()
        with maintenance_lock(self.root/'1'/identifier):
            with self.assertRaises(BlockingIOError):
                self.store.put(1, identifier, 0, io.BytesIO(b'abcd'))
            with self.assertRaises(BlockingIOError):
                self.store.seal(1, identifier)
        self.assertEqual(self.store.put(1, identifier, 0, io.BytesIO(b'abcd'))['received'], [0])

    def test_stable_host_identity_rejects_different_transfer_metadata(self):
        identity='f'*32
        value=self.store.create(1,'stable.ova',4,'linux',identifier=identity)
        self.assertEqual(self.store.create(1,'stable.ova',4,'linux',identifier=identity),value)
        with self.assertRaises(UploadError):
            self.store.create(1,'different.ova',4,'linux',identifier=identity)
        self.assertEqual(self.store.status(1,identity)['name'],'stable.ova')
