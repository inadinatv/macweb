"""Statik sayfa + isteğe bağlı, izin listeli HLS hizmeti.

Üretimde HTTPS reverse proxy arkasında çalıştırın. GitHub Pages tek başına bu
Python hizmetini çalıştıramaz; dış hizmet URL'si settings.yml'de tanımlanabilir.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import requests

from . import config, extras
from .http_transport import public_get
from .stream_proxy import StreamError, StreamProxy, validate_url

log = logging.getLogger(__name__)
STATIC_FILES = {"index.html", "output/today_matches.json", "output/extra_channels.json", "output/channels.json"}


class PublishedRegistry:
    """Ayrı host edilen hizmet, botun yayımladığı aynı kaynak listesini izleyebilir.

    URL boşsa yerel output kullanılır. Başarısız bir yenileme çalışan kaydı silmez.
    Kullanıcı isteğinden URL alınmaz; yalnızca güvenilir deployment ayarıdır.
    """
    def __init__(self):
        self.data = None
        self.next_check = 0
        self.lock = threading.Lock()

    def __call__(self):
        url = config.load_settings().get("playback", {}).get("registry_url", "")
        if not url:
            return extras.load_or_build()
        with self.lock:
            if time.monotonic() >= self.next_check:
                self.next_check = time.monotonic() + 60
                try:
                    parsed = urlsplit(url)
                    if parsed.scheme != "https":
                        raise ValueError("HTTPS registry gerekli")
                    validate_url(url, [parsed.hostname or ""])
                    with public_get(url, timeout=(3, 5), stream=True, allow_redirects=False,
                                      headers={"Accept": "application/json"}) as response:
                        if response.status_code != 200:
                            raise ValueError("registry HTTP")
                        body = bytearray()
                        for chunk in response.iter_content(16384):
                            body.extend(chunk)
                            if len(body) > 1024 * 1024:
                                raise ValueError("registry boyutu")
                    data = json.loads(body)
                    if not isinstance(data, dict) or not isinstance(data.get("panels"), list) or not extras.flatten(data):
                        raise ValueError("registry şeması")
                    self.data = data
                except (requests.RequestException, ValueError, TypeError, AttributeError, StreamError) as exc:
                    log.warning("Yayın kaydı yenilenemedi (%s); son kayıt kullanılıyor.", type(exc).__name__)
            return self.data if self.data is not None else extras.load_or_build()


def make_handler(proxy: StreamProxy | None = None):
    proxy = proxy or StreamProxy(registry=PublishedRegistry(), secret=(os.environ["STREAM_PROXY_SECRET"].encode() if os.environ.get("STREAM_PROXY_SECRET") else None))
    slots = threading.BoundedSemaphore(32)

    class Handler(BaseHTTPRequestHandler):
        # Keep-alive gerektirmeyen, Content-Length olmayan hata/stream sonlarını da
        # doğru sonlandıran HTTP/1.0; reverse proxy istemci bağlantısını yönetebilir.
        server_version = "Macweb/1.0"

        def log_message(self, fmt, *args):
            # Standart access log query/HMAC biletini açığa çıkarır. Sadece yolu yaz.
            log.info("%s %s", self.command, urlsplit(self.path).path)

        def _origin(self):
            origin = self.headers.get("Origin", "")
            allowed = config.load_settings().get("playback", {}).get("allowed_origins", [])
            parsed = urlsplit(origin)
            same_host = parsed.scheme in ("http", "https") and parsed.netloc == self.headers.get("Host")
            if origin and origin not in allowed and not same_host:
                raise StreamError("Bu site için yayın hizmeti izni yok.", 403, "origin_not_allowed")
            return origin

        def _headers(self, status, headers):
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            try:
                origin = self._origin()
            except StreamError:
                origin = ""
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range, X-Stream-Error")
            self.end_headers()

        def _json(self, status, data, code=""):
            body = json.dumps(data, ensure_ascii=False).encode()
            headers = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body)), "Cache-Control": "no-store"}
            if code:
                headers["X-Stream-Error"] = code
            self._headers(status, headers)
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_OPTIONS(self):
            try:
                self._origin()
                self._headers(204, {"Access-Control-Allow-Methods": "GET, HEAD, OPTIONS", "Access-Control-Allow-Headers": "Range", "Access-Control-Max-Age": "600"})
            except StreamError as exc:
                self._json(exc.status, {"error": str(exc), "code": exc.code}, exc.code)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = urlsplit(self.path)
            if path.path == "/api/hls":
                return self._stream(path.query)
            if path.path == "/api/playback.json":
                try:
                    self._origin()
                    return self._json(200, {"proxy_url": "api/hls"})
                except StreamError as exc:
                    return self._json(exc.status, {"error": str(exc), "code": exc.code}, exc.code)
            name = path.path.lstrip("/") or "index.html"
            if name not in STATIC_FILES:
                return self._json(404, {"error": "Dosya bulunamadı."})
            file = config.ROOT / name
            if not file.is_file():
                return self._json(404, {"error": "Dosya bulunamadı."})
            body = file.read_bytes()
            self._headers(200, {"Content-Type": (mimetypes.guess_type(name)[0] or "application/octet-stream") + "; charset=utf-8",
                                "Content-Length": str(len(body)), "Cache-Control": "no-cache"})
            if self.command != "HEAD":
                self.wfile.write(body)

        def _stream(self, query):
            response = None
            acquired = False
            headers_sent = False
            try:
                self._origin()
                acquired = slots.acquire(blocking=False)
                if not acquired:
                    raise StreamError("Yayın hizmeti meşgul. Biraz sonra yeniden deneyin.", 503, "busy")
                params = parse_qs(query)
                if any(k not in {"channel", "source", "ticket"} for k in params):
                    raise StreamError("Geçersiz yayın isteği.", 400, "invalid_request")
                source = (params.get("source") or ["0"])[0]
                if not source.isdigit():
                    raise StreamError("Geçersiz kaynak numarası.", 400, "invalid_source")
                response = proxy.open(channel=(params.get("channel") or [""])[0], source=int(source),
                                      ticket=(params.get("ticket") or [""])[0], byte_range=self.headers.get("Range", ""))
                self._headers(response.status, response.headers)
                headers_sent = True
                if self.command != "HEAD":
                    for chunk in response.chunks:
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # kullanıcı kaynak değiştirdi; upstream finally'de kapatılır
            except StreamError as exc:
                log.warning("HLS: %s (%s)", str(exc), exc.code)
                if not headers_sent:
                    self._json(exc.status, {"error": str(exc), "code": exc.code}, exc.code)
            except Exception as exc:
                # Ham exception URL/header bilgisi içerebilir.
                log.error("HLS hizmet hatası: %s", type(exc).__name__)
                if not headers_sent:
                    self._json(502, {"error": "Yayın aktarımı tamamlanamadı.", "code": "stream_error"}, "stream_error")
            finally:
                if response:
                    response.close()
                if acquired:
                    slots.release()

    return Handler


def serve(host: str = "0.0.0.0", port: int = 8000):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    server = ThreadingHTTPServer((host, port), make_handler())
    print(f"Macweb web hizmeti: {host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
