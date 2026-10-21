"""Validated local avatars and bounded downloads for API suggestions."""
import http.client
import io
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_BYTES = 10 * 1024 * 1024
AVATAR_ERROR = 'Avatar: maximal 10 MB und ein gültiges Bild.'


def prepare_avatar(content):
    if len(content) > MAX_AVATAR_BYTES:
        raise ValueError(AVATAR_ERROR)
    try:
        with Image.open(io.BytesIO(content)) as img:
            if img.width * img.height > 20000000:
                raise ValueError(AVATAR_ERROR)
            img.load()
            img = ImageOps.exif_transpose(img)
            img.thumbnail((256, 256))
            img = img.convert('RGBA')
            img.info.clear()
            output = io.BytesIO()
            img.save(output, 'PNG')
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError(AVATAR_ERROR) from error


def download_avatar(url):
    # Resolve and pin each connection, including redirects, to a public address.
    # Keep the original hostname for TLS certificate verification and SNI.
    from . import valid_http_url

    deadline = time.monotonic() + 10
    try:
        for redirect_count in range(4):
            if not valid_http_url(url):
                raise ValueError('Ungültige Bild-URL.')
            parsed = urlsplit(url)
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
            resolved = [ipaddress.ip_address(address[4][0]) for address in addresses]
            if not resolved or any(not address.is_global or address.is_multicast
                                   or (getattr(address, 'ipv4_mapped', None) and not address.ipv4_mapped.is_global)
                                   for address in resolved):
                raise ValueError('Bild-URLs müssen auf öffentliche Server verweisen.')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('Zeitlimit für das Bild überschritten.')
            connection_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
            connection = connection_class(parsed.hostname, port, timeout=min(5, remaining))
            address = addresses[0][4][0]
            connection._create_connection = lambda target, timeout, source_address=None: socket.create_connection(
                (address, port), timeout, source_address)
            response = None
            try:
                path = parsed.path or '/'
                if parsed.query:
                    path += '?' + parsed.query
                connection.request('GET', path, headers={'Accept': 'image/*', 'Accept-Encoding': 'identity'})
                download_socket = connection.sock
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location')
                    if not location or redirect_count == 3:
                        raise ValueError('Zu viele oder ungültige Bild-Weiterleitungen.')
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise ValueError('Bild konnte nicht geladen werden.')
                length = response.getheader('Content-Length')
                if length is not None and (not length.isdecimal() or int(length) > MAX_AVATAR_BYTES):
                    raise ValueError(AVATAR_ERROR)
                content = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError('Zeitlimit für das Bild überschritten.')
                    if download_socket:
                        download_socket.settimeout(min(5, remaining))
                    chunk = response.read1(min(65536, MAX_AVATAR_BYTES + 1 - len(content)))
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > MAX_AVATAR_BYTES:
                        raise ValueError(AVATAR_ERROR)
                return prepare_avatar(content)
            finally:
                if response is not None:
                    response.close()
                connection.close()
    except (OSError, http.client.HTTPException, UnicodeError) as error:
        raise ValueError('Bild konnte nicht geladen werden.') from error
