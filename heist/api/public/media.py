"""Bounded image uploads and public media serving, isolated from private VM artifacts."""
import os
from pathlib import Path
import re
import struct
import tempfile
import uuid
import zlib

from flask import Blueprint, current_app, send_file
from .errors import ApiError

blueprint = Blueprint('media', __name__)
MAX_BYTES = 2*1024*1024


def dimensions(width, height):
    if not 1 <= width <= 2048 or not 1 <= height <= 2048:
        raise ApiError('Images must be between 1 and 2048 pixels on each side')


def png(data):
    offset, seen_header, seen_pixels, ended = 8, False, False, False
    while offset+12 <= len(data):
        length = struct.unpack('!I', data[offset:offset+4])[0]
        end = offset+12+length
        if end > len(data):
            raise ApiError('Invalid PNG image')
        kind, value = data[offset+4:offset+8], data[offset+8:offset+8+length]
        checksum = struct.unpack('!I', data[offset+8+length:end])[0]
        if zlib.crc32(kind+value) & 0xffffffff != checksum:
            raise ApiError('Invalid PNG checksum')
        if not seen_header:
            if kind != b'IHDR' or length != 13:
                raise ApiError('Invalid PNG header')
            dimensions(*struct.unpack('!II', value[:8]))
            seen_header = True
        if kind in (b'acTL', b'fcTL', b'fdAT'):
            raise ApiError('Use a static image instead of an animation')
        seen_pixels = seen_pixels or kind == b'IDAT' and length > 0
        offset = end
        if kind == b'IEND':
            ended = length == 0 and offset == len(data)
            break
    if not seen_header or not seen_pixels or not ended:
        raise ApiError('Incomplete PNG image')


def gif(data):
    if len(data) < 14:
        raise ApiError('Invalid GIF image')
    dimensions(*struct.unpack('<HH', data[6:10]))
    offset = 13 + (3*(2**((data[10] & 7)+1)) if data[10] & 128 else 0)
    frames = 0
    while offset < len(data):
        marker = data[offset]
        offset += 1
        if marker == 0x3b:
            if frames != 1 or offset != len(data):
                raise ApiError('Use a complete static GIF image')
            return
        if marker == 0x21:
            offset += 1  # extension label; following blocks are length-prefixed
        elif marker == 0x2c:
            if offset+9 >= len(data):
                raise ApiError('Invalid GIF frame')
            dimensions(*struct.unpack('<HH', data[offset+4:offset+8]))
            packed = data[offset+8]
            offset += 9 + (3*(2**((packed & 7)+1)) if packed & 128 else 0)
            offset += 1  # LZW minimum code size
            frames += 1
            if frames > 1:
                raise ApiError('Use a static image instead of an animation')
        else:
            raise ApiError('Invalid GIF block')
        while True:
            if offset >= len(data):
                raise ApiError('Incomplete GIF image')
            size = data[offset]
            offset += 1
            if size == 0:
                break
            offset += size
    raise ApiError('Incomplete GIF image')


def jpeg(data):
    if not data.endswith(b'\xff\xd9'):
        raise ApiError('Incomplete JPEG image')
    offset = 2
    while offset+4 <= len(data):
        if data[offset] != 0xff:
            raise ApiError('Invalid JPEG marker')
        while offset < len(data) and data[offset] == 0xff:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
            continue
        if offset+2 > len(data):
            break
        size = struct.unpack('!H', data[offset:offset+2])[0]
        if size < 2 or offset+size > len(data):
            raise ApiError('Invalid JPEG segment')
        if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
            if size < 8:
                raise ApiError('Invalid JPEG dimensions')
            height, width = struct.unpack('!HH', data[offset+3:offset+7])
            dimensions(width, height)
            return
        if marker == 0xda:
            break
        offset += size
    raise ApiError('JPEG dimensions are missing')


def image_format(data):
    if not data or len(data) > MAX_BYTES:
        raise ApiError('Choose an image no larger than 2 MiB')
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        png(data)
        return 'png', 'image/png'
    if data.startswith((b'GIF87a', b'GIF89a')):
        gif(data)
        return 'gif', 'image/gif'
    if data.startswith(b'\xff\xd8'):
        jpeg(data)
        return 'jpg', 'image/jpeg'
    raise ApiError('Choose a PNG, JPEG or static GIF image')


def media_directory(kind, *, create=False):
    if kind not in ('avatars', 'challenge_images'):
        raise ApiError('Media not found', 404)
    root = Path(current_app.config['DATA_ROOT'])
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('Configure an absolute web data root')
    path = root/'media'/kind
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ApiError('Media storage is unavailable', 503)
    if create:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    return path


def save_image(upload, kind, user_id):
    if upload is None:
        raise ApiError('Choose an image to upload')
    data = upload.stream.read(MAX_BYTES+1)
    extension, _ = image_format(data)
    directory = media_directory(kind, create=True)
    name = str(user_id)+'_'+uuid.uuid4().hex+'.'+extension
    descriptor, temporary = tempfile.mkstemp(prefix='.pending-', dir=directory)
    target = directory/name
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return '/api/media/'+kind+'/'+name


def remove_owned_image(url, kind, user_id):
    prefix = '/api/media/'+kind+'/'+str(user_id)+'_'
    if not isinstance(url, str) or not url.startswith(prefix):
        return
    name = url.rsplit('/', 1)[-1]
    if re.fullmatch(str(user_id)+r'_[a-f0-9]{32}\.(?:png|jpg|gif)', name):
        path = media_directory(kind)/name
        if not path.is_symlink():
            path.unlink(missing_ok=True)


@blueprint.get('/media/<kind>/<filename>')
def get_media(kind, filename):
    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:png|jpe?g|gif)', filename, re.I) is None:
        raise ApiError('Media not found', 404)
    path = media_directory(kind)/filename
    if path.is_symlink() or not path.is_file():
        raise ApiError('Media not found', 404)
    mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif'}[path.suffix[1:].lower()]
    return send_file(path, mimetype=mime, conditional=True, max_age=86400)
