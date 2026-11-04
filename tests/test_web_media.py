"""Untrusted image boundaries and isolation from private appliance artifacts."""
import base64
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock
import zlib

from werkzeug.datastructures import FileStorage
from heist.api.public import create_app
from heist.api.public.errors import ApiError
from heist.api.public.media import MAX_BYTES, image_format, remove_owned_image, save_image


def png(width=1, height=1):
    def chunk(kind, data):
        return struct.pack('!I', len(data))+kind+data+struct.pack('!I', zlib.crc32(kind+data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0))+chunk(b'IDAT', zlib.compress(b'\0\xff\0\0'))+chunk(b'IEND', b'')


class PublicMediaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.factory = Mock(side_effect=AssertionError('Public images must not open a database session'))
        self.app = create_app({'TESTING': True, 'WEB_SESSION_SECRET': 'a'*64, 'DATA_ROOT': str(self.root)}, repository_factory=self.factory)

    def test_sniffing_accepts_static_formats_and_rejects_corruption_oversize_and_animation(self):
        self.assertEqual(image_format(png()), ('png', 'image/png'))
        gif = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==')
        self.assertEqual(image_format(gif), ('gif', 'image/gif'))
        for data in (b'', b'<svg onload="alert(1)"></svg>', b'x'*(MAX_BYTES+1), png()[:-1], png()+b'extra', png(2049), gif[:-1]):
            with self.subTest(data=data[:20]), self.assertRaises(ApiError):
                image_format(data)
        corrupted = bytearray(png())
        corrupted[20] ^= 1
        with self.assertRaises(ApiError):
            image_format(bytes(corrupted))

    def test_upload_uses_generated_private_name_and_only_removes_owner_images(self):
        with self.app.app_context():
            url = save_image(FileStorage(stream=io.BytesIO(png()), filename='../../private.php', content_type='text/html'), 'avatars', 12)
            path = self.root/'media/avatars'/url.rsplit('/', 1)[-1]
            self.assertEqual(path.read_bytes(), png())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('private', url)
            remove_owned_image(url, 'avatars', 13)
            self.assertTrue(path.exists())
            remove_owned_image(url, 'avatars', 12)
            self.assertFalse(path.exists())

    def test_media_is_public_cacheable_and_cannot_expose_private_files_or_symlinks(self):
        directory = self.root/'media/avatars'
        directory.mkdir(parents=True)
        (directory/'sample.png').write_bytes(png())
        (self.root/'secret').write_text('private-token')
        (directory/'link.png').symlink_to(self.root/'secret')
        client = self.app.test_client()
        # Invalid cookies do not turn a public image into a database-dependent route.
        client.set_cookie('__Host-heist_session', 'a'*64, secure=True)
        result = client.get('/api/media/avatars/sample.png', base_url='https://localhost')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, png())
        self.assertEqual(result.mimetype, 'image/png')
        self.assertEqual(result.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn('public', result.headers['Cache-Control'])
        self.assertNotIn('Set-Cookie', result.headers)
        result.close()
        for path in ('avatars/link.png', 'avatars/secret', 'artifacts/image.png', 'avatars/..%2fsecret.png'):
            result = client.get('/api/media/'+path, base_url='https://localhost')
            self.assertIn(result.status_code, (404, 503))
            self.assertNotIn(b'private-token', result.data)
        self.factory.assert_not_called()

    def test_storage_parent_links_and_relative_roots_are_rejected(self):
        (self.root/'media').symlink_to(self.root/'outside')
        with self.app.app_context(), self.assertRaises(ApiError):
            save_image(FileStorage(stream=io.BytesIO(png())), 'avatars', 1)
        self.app.config['DATA_ROOT'] = 'relative'
        with self.app.app_context(), self.assertRaises(ValueError):
            save_image(FileStorage(stream=io.BytesIO(png())), 'avatars', 1)
