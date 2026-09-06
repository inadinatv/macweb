"""HLS taşıması: playlist/segment/key/redirect/range ve SSRF sınırları (ağsız)."""
import copy
import json
import socket
import sys
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fixbet.stream_proxy import StreamProxy, StreamError, Tickets, rewrite_playlist, validate_url, safe_url
from fixbet.web import make_handler

ROOT = "https://worker.test/?ID=one"
FINAL = "https://cdn.test/live/master.m3u8?auth=a%2Bb"
REGISTRY = {"panels": [{"id": "atom", "channels": [{"id": "atom:one", "referrer": "https://site.test/",
    "sources": [{"type": "hls", "url": ROOT}, {"type": "embed", "url": "https://site.test/player"}]}]}]}
CONFIG = {"panels": [{"id": "atom", "playback": {"allowed_hosts": ["worker.test", "cdn.test", "seg.test"],
    "headers": {"Referer": "{referrer}", "Origin": "{origin}", "User-Agent": "SourcePlayer/1.0"}}}]}


def public_dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]


class Response:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code, self.body = status, body.encode() if isinstance(body, str) else body
        self.headers = headers or {}
        self.closed = False
    def iter_content(self, chunk_size):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i+chunk_size]
    def close(self):
        self.closed = True


class Network:
    def __init__(self, pages):
        self.pages, self.calls = pages, []
    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value


def proxy(net, **kwargs):
    return StreamProxy(registry=lambda: REGISTRY, settings=lambda: CONFIG, fetch=net, resolver=public_dns, **kwargs)


def ticket(url):
    return parse_qs(urlsplit(url).query)["ticket"][0]


def test_redirect_master_media_key_map_and_segment_use_same_context():
    master = '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",URI="audio/list.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=1000,CODECS="avc1.640028,mp4a.40.2"\nvideo/list.m3u8?sig=a%2Bb\n'
    media = '#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-KEY:METHOD=AES-128,URI="../key.bin?k=a%2Bb"\n#EXT-X-MAP:URI="init.mp4",BYTERANGE="500@0"\n#EXTINF:6,\nhttps://seg.test/one.jpg?token=signed\n#EXT-X-ENDLIST\n'
    ts = bytes([0x47]) + bytes(187)
    net = Network({ROOT: Response(302, headers={"Location": FINAL}),
        FINAL: Response(body=master, headers={"Content-Type": "text/plain"}),
        "https://cdn.test/live/video/list.m3u8?sig=a%2Bb": Response(body=media),
        "https://cdn.test/live/key.bin?k=a%2Bb": Response(body=b"0123456789abcdef"),
        "https://cdn.test/live/video/init.mp4": Response(body=b"\x00\x00\x00\x18ftypisom", headers={"Content-Type": "application/octet-stream"}),
        "https://seg.test/one.jpg?token=signed": Response(body=ts * 8, headers={"Content-Type": "image/jpeg"})})
    p = proxy(net)
    response = p.open("atom:one")
    text = b"".join(response.chunks).decode()
    assert response.headers["Content-Type"].startswith("application/vnd.apple.mpegurl")
    assert 'CODECS="avc1.640028,mp4a.40.2"' in text
    child = ticket(text.splitlines()[-1])
    assert p.tickets.verify(child)[2] == "https://cdn.test/live/video/list.m3u8?sig=a%2Bb"
    media_response = p.open(ticket=child)
    media_text = b"".join(media_response.chunks).decode()
    import re
    attrs = re.findall('URI="([^"]+)"', media_text)
    key = p.open(ticket=ticket(attrs[0]))
    assert b"".join(key.chunks) == b"0123456789abcdef"
    init = p.open(ticket=ticket(attrs[1]))
    assert init.headers["Content-Type"] == "video/mp4"
    b"".join(init.chunks)
    segment = p.open(ticket=ticket(next(l for l in media_text.splitlines() if l and not l.startswith("#"))))
    assert segment.headers["Content-Type"] == "video/mp2t"
    assert b"".join(segment.chunks) == ts * 8
    for _, kwargs in net.calls:
        assert kwargs["headers"]["Referer"] == "https://site.test/"
        assert kwargs["headers"]["Origin"] == "https://site.test"
        assert kwargs["headers"]["User-Agent"] == "SourcePlayer/1.0"
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] == (5, 20)
    assert all(value.closed for value in net.pages.values())


def test_playlist_all_uri_attributes_and_relative_resolution():
    text = '#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MAP:URI="../init.mp4"\n#EXT-X-PART:DURATION=1,URI="a.m4s"\n#EXT-X-PRELOAD-HINT:TYPE=PART,URI="b.m4s"\n#EXT-X-RENDITION-REPORT:URI="//cdn.test/other.m3u8",LAST-MSN=1\n#EXTINF:4,\n./one.ts?token=x%2By&n=2\n'
    seen = []
    def child(url):
        seen.append(url)
        return "?ticket=" + str(len(seen))
    output = rewrite_playlist(text, "https://cdn.test/path/video/list.m3u8", child)
    assert seen == ["https://cdn.test/path/init.mp4", "https://cdn.test/path/video/a.m4s", "https://cdn.test/path/video/b.m4s",
                    "https://cdn.test/other.m3u8", "https://cdn.test/path/video/one.ts?token=x%2By&n=2"]
    assert "#EXTINF:4," in output


def test_range_and_mime_and_abort_cleanup():
    net = Network({ROOT: Response(206, body=b"\x00\x00\x00\x18moofxxxx", headers={"Content-Length": "12", "Content-Range": "bytes 0-11/200", "Accept-Ranges": "bytes"})})
    p = proxy(net)
    response = p.open("atom:one", byte_range="bytes=0-11")
    assert response.status == 206 and response.headers["Content-Range"] == "bytes 0-11/200"
    assert response.headers["Content-Type"] == "video/mp4"
    assert net.calls[0][1]["headers"]["Range"] == "bytes=0-11"
    response.close()
    assert net.pages[ROOT].closed
    with pytest.raises(StreamError) as exc:
        p.open("atom:one", byte_range="bytes=0-10,30-40")
    assert exc.value.status == 416


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "https://cdn.test:444/", "https://cdn.test@evil.test/", "https://evil.test/", "file:///etc/passwd", "https://cdn.test\\@evil.test/"])
def test_ssrf_urls_are_rejected(url):
    with pytest.raises(StreamError):
        validate_url(url, ["cdn.test"], public_dns)


def test_private_dns_and_redirects_do_not_fetch_forbidden_target():
    private = lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
    with pytest.raises(StreamError) as exc:
        validate_url("https://cdn.test/", ["cdn.test"], private)
    assert exc.value.code == "private_address"
    net = Network({ROOT: Response(302, headers={"Location": "http://169.254.169.254/"})})
    with pytest.raises(StreamError):
        proxy(net).open("atom:one")
    assert len(net.calls) == 1 and net.pages[ROOT].closed


def test_tickets_cannot_be_changed_reused_after_expiry_or_select_arbitrary_source():
    clock = [100]
    t = Tickets(b"test-key", lambda: clock[0])
    signed = t.sign("atom:one", 0, "https://cdn.test/one.ts?token=secret")
    assert t.verify(signed)[2].endswith("token=secret")
    with pytest.raises(StreamError):
        t.verify(signed[:-1] + ("0" if signed[-1] != "0" else "1"))
    clock[0] += 7 * 3600
    with pytest.raises(StreamError):
        t.verify(signed)
    for channel, index in (("unknown", 0), ("atom:one", 1), ("atom:one", -1), ("atom:one", 100)):
        with pytest.raises(StreamError):
            proxy(Network({})).open(channel, index)
    assert "secret" not in safe_url("https://user:password@cdn.test/p?token=secret")


@pytest.mark.parametrize("response,code,status", [(Response(403), "upstream_http", 403),
    (Response(404), "upstream_http", 404), (Response(500), "upstream_http", 502),
    (Response(body="<html>denied</html>", headers={"Content-Type": "text/html"}), "html_response", 502),
    (Response(body=b"\xff\xd8\xffreal-image"), "image_response", 502),
    (requests.Timeout(), "upstream_timeout", 504)])
def test_actionable_errors(response, code, status):
    with pytest.raises(StreamError) as exc:
        proxy(Network({ROOT: response})).open("atom:one")
    assert (exc.value.code, exc.value.status) == (code, status)


def test_http_origin_errors_and_static_files_do_not_expose_repository():
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(proxy(Network({}))))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def request(path, method="GET", headers=None):
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            conn.request(method, path, headers=headers or {})
            res = conn.getresponse()
            result = (res.status, dict(res.getheaders()), res.read())
            conn.close()
            return result
        assert request("/.git/config")[0] == 404
        assert request("/config/extra_channels.yml")[0] == 404
        assert request("/api/playback.json")[0] == 200
        assert request("/api/hls?url=http://example.com")[0] == 400
        assert request("/api/hls?channel=atom:one", headers={"Origin": "https://evil.test"})[0] == 403
        status, headers, _ = request("/api/hls", "OPTIONS", {"Origin": "https://inadinatv.github.io"})
        assert status == 204 and headers["Access-Control-Allow-Origin"] == "https://inadinatv.github.io"
        assert headers["Access-Control-Allow-Headers"] == "Range"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_private_headers_cannot_downgrade_to_plain_http():
    config = {'panels':[{'id':'atom','playback':{'allowed_hosts':['cdn.test'],
              'headers': {'Authorization':'test-only'}}}]}
    data = {'panels':[{'channels':[{'id':'atom:test','sources':[{'type':'hls','url':'http://cdn.test/master.m3u8'}]}]}]}
    def no_fetch(*args, **kwargs):
        pytest.fail('No private header may be sent over HTTP')
    proxy = StreamProxy(registry=lambda:data, settings=lambda:config, fetch=no_fetch, resolver=lambda *a,**k: [(socket.AF_INET,socket.SOCK_STREAM,0,'',('8.8.8.8',80))])
    with pytest.raises(StreamError) as error:
        proxy.open('atom:test')
    assert error.value.code == 'https_required'
