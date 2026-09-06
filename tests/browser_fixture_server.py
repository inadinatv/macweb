"""Sadece browser testleri için yerel HLS kaynağı + gerçek Macweb proxy.

Üretim ayarını DEĞİŞTİRMEZ. SSRF korumasının DNS bağımlılığı yalnızca bu testte
injekte edilir; loopback test kaynağına erişmemize izin verir.
"""
import json
import re
import signal
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fixbet import config
from fixbet.stream_proxy import StreamProxy
from fixbet.web import make_handler

HLS = ROOT / "tests/fixtures/hls"
REQUESTS = []


class Source(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/requests":
            body = json.dumps(REQUESTS).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        headers_ok = self.headers.get("Referer") == "https://source.test/player" and self.headers.get("Origin") == "https://source.test" and self.headers.get("User-Agent") == "ExternalSource/1.0"
        REQUESTS.append({"path": self.path, "range": self.headers.get("Range"), "headers_ok": headers_ok})
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ts/master.m3u8?token=redirect%2Bsignature")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return
        protected = path.startswith(("/encrypted/", "/protected-range/"))
        # Manifest herkese açık olsa bile key/segmentler gerekli header'lar
        # olmadan açılamaz: yalnızca ilk m3u8'i proxy'lemek yetmez.
        if protected and not path.endswith(".m3u8") and not headers_ok:
            self.send_response(403)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return
        local = HLS / path.replace("/protected-range/", "/range/").lstrip("/")
        if not local.resolve().is_relative_to(HLS) or not local.is_file():
            self.send_response(404)
            self.end_headers()
            return
        body = local.read_bytes()
        status = 200
        extra = {}
        if self.headers.get("Range"):
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers["Range"])
            if match:
                start = int(match[1]); end = int(match[2] or len(body) - 1)
                extra["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
                body = body[start:end+1]
                status = 206
        content_type = "application/octet-stream"
        if local.suffix == ".m3u8":
            content_type = "text/plain"  # hls.js içerikten algılar, uzantı/MIME varsaymaz
        if local.suffix == ".jpg":
            content_type = "image/jpeg"  # gerçek MPEG-TS, Atom benzeri URI/MIME
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Accept-Ranges", "bytes")
        for name, value in extra.items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass


def main():
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Source)
    source_url = f"http://127.0.0.1:{upstream.server_port}"
    channels = []
    for name, path in [("ts", "/redirect?ID=one"), ("fmp4", "/fmp4/master.m3u8"),
                       ("range", "/range/media.m3u8"), ("encrypted", "/encrypted/media.m3u8"),
                       ("range-proxy", "/protected-range/media.m3u8")]:
        channels.append({"id": "test:" + name, "name": "Test " + name, "referrer": "https://source.test/player",
                         "sources": [{"type": "hls", "url": source_url + path, "requires_proxy": name == "range-proxy"}]})
    registry = {"panels": [{"id": "test", "name": "Test", "channels": channels}]}
    settings = {"panels": [{"id": "test", "playback": {"allowed_hosts": ["127.0.0.1"], "headers": {
        "Referer": "{referrer}", "Origin": "{origin}", "User-Agent": "ExternalSource/1.0"}}}]}
    # Proxy URL doğrulamasındaki standart port kuralı test portları için de korunur:
    # upstream fetch bağımlılığı HTTP loopback URL'lerine çevirir, bilet/URI'ler
    # normal portlu public-looking test adı taşır. Üretime test istisnası eklenmez.
    import requests
    public_root = "http://stream.test"
    proxy_registry = json.loads(json.dumps(registry).replace(source_url, public_root))
    def fetch(url, **kwargs):
        response = requests.get(url.replace(public_root, source_url), **kwargs)
        return response
    dns = lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))]
    settings["panels"][0]["playback"]["allowed_hosts"] = ["stream.test"]
    proxy = StreamProxy(registry=lambda: proxy_registry, settings=lambda: settings, fetch=fetch, resolver=dns)
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        html = (ROOT / "index.html").read_text()
        html = re.sub(r"let extraData = [^\n]+;", "let extraData = " + json.dumps(registry) + ";", html)
        html = re.sub(r"const playbackConfig = [^\n]+;", "const playbackConfig = {};", html)
        (root / "index.html").write_text(html)
        (root / "output").mkdir()
        (root / "output/extra_channels.json").write_text(json.dumps(registry))
        (root / "output/today_matches.json").write_text((ROOT / "output/today_matches.json").read_text())
        config.ROOT = root
        web = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(proxy))
        for server in (upstream, web):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        print(json.dumps({"page": f"http://127.0.0.1:{web.server_port}", "upstream": source_url}), flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            for server in (upstream, web):
                server.shutdown(); server.server_close()


if __name__ == "__main__":
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    main()
