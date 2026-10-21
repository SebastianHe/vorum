import io
import socket

import pytest
from PIL import Image

import vorum.avatars as avatars


@pytest.fixture
def avatar_server(monkeypatch):
    image = io.BytesIO()
    Image.new('RGB', (800, 600), 'red').save(image, 'JPEG')
    responses = []
    requests = []
    connections = []

    class Response(io.BytesIO):
        def __init__(self, content=image.getvalue(), status=200, headers=None):
            super().__init__(content)
            self.status = status
            self.headers = headers or {}

        def getheader(self, name):
            return self.headers.get(name)

    class Connection:
        sock = None

        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port
            self.timeout = timeout
            self.closed = False
            connections.append(self)

        def request(self, method, path, headers):
            requests.append((self.host, method, path, headers))

        def getresponse(self):
            return responses.pop(0) if responses else Response()

        def close(self):
            self.closed = True

    monkeypatch.setattr(avatars.socket, 'getaddrinfo', lambda *args, **kwargs:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', args[1]))])
    monkeypatch.setattr(avatars.http.client, 'HTTPConnection', Connection)
    monkeypatch.setattr(avatars.http.client, 'HTTPSConnection', Connection)
    return Response, responses, requests, connections


def test_download_converts_resizes_and_pins_public_address(avatar_server, monkeypatch):
    _, _, requests, connections = avatar_server
    content = avatars.download_avatar('https://images.example.org/avatar.jpg?size=800')
    with Image.open(io.BytesIO(content)) as image:
        assert image.format == 'PNG' and image.size == (256, 192)
    assert requests[0][2] == '/avatar.jpg?size=800'
    assert requests[0][3]['Accept-Encoding'] == 'identity'
    monkeypatch.setattr(avatars.socket, 'create_connection', lambda target, timeout, source: target)
    assert connections[0]._create_connection(('images.example.org', 443), 5) == ('93.184.216.34', 443)
    assert connections[0].closed


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', 'fd00::1', '::ffff:127.0.0.1', '224.0.0.1'])
def test_download_blocks_nonpublic_addresses(avatar_server, monkeypatch, address):
    monkeypatch.setattr(avatars.socket, 'getaddrinfo', lambda *args, **kwargs:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))])
    with pytest.raises(ValueError):
        avatars.download_avatar('https://internal.example.org/avatar')
    assert not avatar_server[2]


def test_redirects_are_followed_and_revalidated(avatar_server, monkeypatch):
    Response, responses, requests, _ = avatar_server
    responses.append(Response(status=302, headers={'Location': '/resized.png'}))
    assert avatars.download_avatar('http://images.example.org/original')
    assert requests[-1][2] == '/resized.png'
    responses.append(Response(status=302, headers={'Location': 'http://127.0.0.1/private'}))
    original = avatars.socket.getaddrinfo
    monkeypatch.setattr(avatars.socket, 'getaddrinfo', lambda host, *args, **kwargs:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))]
                        if host == '127.0.0.1' else original(host, *args, **kwargs))
    with pytest.raises(ValueError):
        avatars.download_avatar('https://images.example.org/original')
    assert requests[-1][2] == '/original'


@pytest.mark.parametrize('case', ['html', 'svg', 'truncated', 'large_header', 'large_stream', 'pixel_limit', 'redirect_loop', 'bad_redirect', 'not_found', 'timeout'])
def test_download_rejects_invalid_or_unbounded_images(avatar_server, monkeypatch, case):
    Response, responses, _, connections = avatar_server
    if case == 'html':
        responses.append(Response(b'<html>not an image</html>'))
    elif case == 'svg':
        responses.append(Response(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'))
    elif case == 'truncated':
        image = io.BytesIO()
        Image.new('RGB', (800, 600)).save(image, 'JPEG')
        responses.append(Response(image.getvalue()[:100]))
    elif case == 'large_header':
        responses.append(Response(headers={'Content-Length': str(avatars.MAX_AVATAR_BYTES + 1)}))
    elif case == 'large_stream':
        monkeypatch.setattr(avatars, 'MAX_AVATAR_BYTES', 100)
        responses.append(Response(b'x' * 101))
    elif case == 'pixel_limit':
        image = io.BytesIO()
        Image.new('1', (5000, 4001)).save(image, 'PNG')
        responses.append(Response(image.getvalue()))
    elif case == 'redirect_loop':
        responses.extend(Response(status=302, headers={'Location': '/again'}) for _ in range(4))
    elif case == 'bad_redirect':
        responses.append(Response(status=302, headers={'Location': 'file:///etc/passwd'}))
    elif case == 'not_found':
        responses.append(Response(status=404))
    elif case == 'timeout':
        monkeypatch.setattr(avatars.socket, 'getaddrinfo', lambda *args, **kwargs: (_ for _ in ()).throw(socket.timeout()))
    with pytest.raises(ValueError):
        avatars.download_avatar('https://images.example.org/avatar')
    assert all(connection.closed for connection in connections)
