"""Public-IP HTTP transport for the optional HLS service.

Validate the addresses used by the actual socket, not just a preliminary DNS
lookup. Host headers, TLS SNI and certificate verification keep the original
hostname. No global DNS monkey patch; no insecure TLS or environment proxy.
"""
from __future__ import annotations

import ipaddress
import socket

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError


class _PublicSocket:
    def _new_conn(self):
        sock = None
        try:
            addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise OSError("Non-public upstream address")
            # Connect the exact checked sockaddr. Resolving the hostname again
            # here would reintroduce a DNS-rebinding / check-use race.
            for family, kind, protocol, _, address in addresses[:4]:
                try:
                    sock = socket.socket(family, kind, protocol)
                    for option in self.socket_options or []:
                        sock.setsockopt(*option)
                    if self.timeout is None or isinstance(self.timeout, (int, float)):
                        sock.settimeout(self.timeout)
                    if self.source_address:
                        sock.bind(self.source_address)
                    sock.connect(address)
                    return sock
                except OSError:
                    if sock is not None:
                        sock.close()
                        sock = None
            raise OSError("Upstream connection failed")
        except (OSError, ValueError) as exc:
            raise NewConnectionError(self, "Public upstream connection failed") from exc


class _HTTPConnection(_PublicSocket, HTTPConnection):
    pass


class _HTTPSConnection(_PublicSocket, HTTPSConnection):
    pass


class _HTTPPool(HTTPConnectionPool):
    ConnectionCls = _HTTPConnection


class _HTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _HTTPSConnection


class _PublicAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _HTTPPool, "https": _HTTPSPool}


def public_get(url: str, **kwargs):
    """requests-compatible streamed GET; response.close also releases its session."""
    session = requests.Session()
    session.trust_env = False
    adapter = _PublicAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    try:
        response = session.get(url, **kwargs)
    except Exception:
        session.close()
        raise
    close_response = response.close

    def close():
        try:
            close_response()
        finally:
            session.close()
    response.close = close
    return response
