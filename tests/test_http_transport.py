"""The real connecting socket cannot bypass preliminary public-DNS validation."""
import socket
import sys
from pathlib import Path

import pytest
from urllib3.exceptions import NewConnectionError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fixbet import http_transport as http


def address(ip):
    return (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (ip, 443))


def test_connection_pins_checked_ip_but_retains_tls_hostname(monkeypatch):
    lookups, connected = [], []
    def lookup(host, port, **kwargs):
        lookups.append(host)
        return [address('8.8.8.8' if len(lookups) == 1 else '127.0.0.1')]
    class Socket:
        def setsockopt(self, *args):
            pass
        def settimeout(self, timeout):
            assert timeout == 5
        def connect(self, value):
            connected.append(value)
    monkeypatch.setattr(http.socket, 'getaddrinfo', lookup)
    monkeypatch.setattr(http.socket, 'socket', lambda *args: Socket())
    connection = http._HTTPSConnection('cdn.test', port=443, timeout=5)
    connection._new_conn()
    assert lookups == ['cdn.test']
    assert connected == [('8.8.8.8', 443)]
    assert connection.host == 'cdn.test'  # parent HTTPSConnection owns SNI / verification


def test_dns_becoming_private_at_connect_is_rejected(monkeypatch):
    monkeypatch.setattr(http.socket, 'getaddrinfo', lambda *a, **k: [address('127.0.0.1')])
    def no_socket(*args):
        pytest.fail('must validate before creating a socket')
    monkeypatch.setattr(http.socket, 'socket', no_socket)
    with pytest.raises(NewConnectionError):
        http._HTTPConnection('cdn.test', port=80, timeout=5)._new_conn()


def test_mixed_public_private_dns_fallback_is_rejected(monkeypatch):
    monkeypatch.setattr(http.socket, 'getaddrinfo', lambda *a, **k: [address('8.8.8.8'), address('169.254.169.254')])
    with pytest.raises(NewConnectionError):
        http._HTTPConnection('cdn.test', port=80, timeout=5)._new_conn()


def test_adapter_is_scoped_and_https_still_verifies_certificates():
    import urllib3
    normal = urllib3.PoolManager()
    adapter = http._PublicAdapter()
    assert adapter.poolmanager.pool_classes_by_scheme['https'].ConnectionCls is http._HTTPSConnection
    assert normal.pool_classes_by_scheme['https'].ConnectionCls is not http._HTTPSConnection
    assert http._HTTPSConnection.connect is http.HTTPSConnection.connect


def test_real_https_transport_preserves_sni_host_and_rejects_wrong_cert(monkeypatch, tmp_path):
    import shutil
    import ssl
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import requests

    if not shutil.which('openssl'):
        pytest.skip('openssl is needed for a temporary local test CA')
    cert, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-keyout', str(key), '-out', str(cert), '-subj', '/CN=stream.test',
                    '-addext', 'subjectAltName=DNS:stream.test'], check=True, capture_output=True, timeout=10)
    observed = {'sni': [], 'host': []}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed['host'].append(self.headers['Host'])
            self.send_response(200)
            self.send_header('Content-Length', '8')
            self.end_headers()
            self.wfile.write(b'#EXTM3U\n')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    context.set_servername_callback(lambda _sock, name, _ctx: observed['sni'].append(name))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    lookup, connect = socket.getaddrinfo, socket.socket.connect
    def test_dns(host, port, **kwargs):
        return [address('8.8.8.8')] if host in ('stream.test', 'wrong.test') else lookup(host, port, **kwargs)
    def test_connect(sock, peer):
        # Only the test injects this wire mapping. Production connects the exact
        # public address; no loopback exception exists in http_transport.py.
        return connect(sock, server.server_address if peer == ('8.8.8.8', 443) else peer)
    monkeypatch.setattr(socket, 'getaddrinfo', test_dns)
    monkeypatch.setattr(socket.socket, 'connect', test_connect)
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')  # must not bypass our adapter
    try:
        with http.public_get('https://stream.test/manifest', stream=True, timeout=(2, 2), verify=str(cert)) as response:
            assert response.content == b'#EXTM3U\n'
        assert observed['sni'] == ['stream.test']
        assert observed['host'] == ['stream.test']
        with pytest.raises(requests.exceptions.SSLError):
            http.public_get('https://wrong.test/manifest', timeout=(2, 2), verify=str(cert))
        assert observed['host'] == ['stream.test']
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
