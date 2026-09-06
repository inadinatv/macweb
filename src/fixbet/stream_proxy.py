"""İsteğe bağlı HLS taşıma katmanı: CORS / Referer / Origin tarayıcıda taklit edilmez.

Açık URL proxy'si değildir. İlk istek kayıtlı bir kanal/kaynak seçer; devamındaki
playlist/segment/key istekleri süreli HMAC biletleri kullanır. Her redirect ve her
alt URI panelin açık alan adı izin listesine uymak zorundadır.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import socket
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode, urljoin, urlsplit

import requests

from . import extras
from .http_transport import public_get

log = logging.getLogger(__name__)
PLAYLIST_LIMIT = 1024 * 1024
SEGMENT_LIMIT = 32 * 1024 * 1024
REDIRECTS = {301, 302, 303, 307, 308}
URI_ATTRIBUTE = re.compile(r'((?:\bURI|\bSERVER-URI)=")([^"]+)(")')


class StreamError(Exception):
    def __init__(self, message: str, status: int = 502, code: str = "upstream_error"):
        super().__init__(message)
        self.status, self.code = status, code


def safe_url(url: str) -> str:
    """Loglara erişim token'ı, kullanıcı bilgisi veya query yazma."""
    p = urlsplit(url)
    return f"{p.scheme}://{p.hostname or ''}{p.path}" + ("?…" if p.query else "")


def validate_url(url: str, allowed_hosts: list[str], resolver: Callable = socket.getaddrinfo) -> str:
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        valid_port = p.port in (None, 443 if p.scheme == "https" else 80)
    except ValueError as exc:
        raise StreamError("Geçersiz yayın adresi.", 400, "invalid_url") from exc
    # Tam alan adı eşleşmesi. Wildcard, kullanıcı bilgisi, yerel ağ ve özel port yok.
    if (p.scheme not in ("http", "https") or not valid_port or p.username or p.password
            or host not in {h.lower() for h in allowed_hosts} or "\\" in url
            or any(ord(c) < 32 for c in url)):
        raise StreamError("Bu yayın alanına erişim izni tanımlı değil.", 403, "host_not_allowed")
    try:
        addresses = resolver(host, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise StreamError("Yayın alan adı çözülemedi.", 502, "dns_error") from exc
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise StreamError("Yerel/özel ağ adreslerine erişilemez.", 403, "private_address")
    return url


class Tickets:
    def __init__(self, secret: bytes | None = None, clock: Callable = time.time):
        self.secret = secret or os.urandom(32)
        self.clock = clock

    def sign(self, channel: str, source: int, url: str) -> str:
        data = json.dumps([channel, source, url, int(self.clock()) + 6 * 3600], separators=(",", ":")).encode()
        blob = base64.urlsafe_b64encode(data).rstrip(b"=")
        sig = hmac.new(self.secret, blob, hashlib.sha256).hexdigest()
        return blob.decode() + "." + sig

    def verify(self, ticket: str) -> tuple[str, int, str]:
        try:
            if len(ticket) > 16000:
                raise ValueError("length")
            blob, sig = ticket.rsplit(".", 1)
            expected = hmac.new(self.secret, blob.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                raise ValueError("signature")
            channel, source, url, expires = json.loads(base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4)))
            if (not isinstance(channel, str) or type(source) is not int or not isinstance(url, str)
                    or type(expires) is not int or expires < self.clock()):
                raise ValueError("expiry/schema")
            return channel, source, url
        except (ValueError, TypeError, UnicodeError) as exc:
            raise StreamError("Yayın bağlantısı geçersiz veya süresi dolmuş. Yeniden deneyin.", 403, "invalid_ticket") from exc


def rewrite_playlist(text: str, final_url: str, rewrite: Callable[[str], str]) -> str:
    """Master + media; TS/fMP4, ses, altyazı, key, MAP, LL-HLS ve byte-range.

    Çözümleme redirect SONRASI adrese göre yapılır. İmzalı query'ler yeniden
    decode edilmez; segment uzantısı .jpg olsa dahi değiştirilmez.
    """
    if not extras.is_hls_playlist(text):
        raise StreamError("Kaynak HLS listesi yerine farklı bir içerik döndürdü.", 502, "not_hls")

    def uri(value: str) -> str:
        if value.startswith("data:"):
            return value  # inline key; ağ isteği oluşturmaz
        if "{$" in value:
            raise StreamError("Bu playlist'in değişken URI biçimi desteklenmiyor.", 422, "playlist_variables")
        return rewrite(urljoin(final_url, value))

    lines = []
    for line in text.lstrip("\ufeff").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            lines.append(URI_ATTRIBUTE.sub(lambda m: m[1] + uri(m[2]) + m[3], line))
        elif stripped:
            lines.append(uri(stripped))
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def media_type(first: bytes, upstream_type: str, url: str) -> str:
    if len(first) > 376 and first[0] == first[188] == first[376] == 0x47:
        return "video/mp2t"
    if len(first) >= 8 and first[4:8] in (b"ftyp", b"styp", b"moof", b"moov"):
        return "video/mp4"
    if upstream_type.split(";")[0].lower() in ("text/html", "application/xhtml+xml") or first.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise StreamError("Yayın yerine bir HTML hata/erişim sayfası geldi.", 502, "html_response")
    if first.startswith((b"\xff\xd8\xff", b"\x89PNG")):
        raise StreamError("Segment gerçek bir resim döndürdü; medya verisi bulunamadı.", 502, "image_response")
    path = urlsplit(url).path.lower()
    if path.endswith((".m4s", ".mp4")):
        return "video/mp4"
    if path.endswith(".ts"):
        return "video/mp2t"
    return "application/octet-stream" if upstream_type.startswith("image/") else upstream_type or "application/octet-stream"


@dataclass
class ProxyResponse:
    status: int
    headers: dict[str, str]
    chunks: object
    close: Callable


class StreamProxy:
    def __init__(self, registry: Callable = extras.load_or_build, settings: Callable = extras.load_config,
                 fetch: Callable = public_get, resolver: Callable = socket.getaddrinfo,
                 secret: bytes | None = None):
        self.registry, self.settings, self.fetch, self.resolver = registry, settings, fetch, resolver
        self.tickets = Tickets(secret)

    def context(self, channel: str, source: int) -> tuple[dict, dict, dict, list[str]]:
        ch = next((c for c in extras.flatten(self.registry()) if c.get("id") == channel), None)
        if not ch or source < 0 or source >= len(ch.get("sources", [])):
            raise StreamError("Yayın kaynağı bulunamadı. Listeyi yenileyin.", 404, "unknown_source")
        src = ch["sources"][source]
        if src.get("type") != "hls":
            raise StreamError("Bu kaynak bir HLS yayını değil.", 400, "invalid_source")
        panel_id = channel.split(":", 1)[0]
        panel = next((p for p in self.settings().get("panels", []) if p.get("id") == panel_id), {})
        playback = panel.get("playback") or {}
        referrer = ch.get("referrer") or ch.get("page_url") or ""
        origin = extras._origin(referrer) if referrer else ""
        headers = dict(extras.DEFAULT_HEADERS, Accept="*/*", **{"Accept-Encoding": "identity"})
        # Referer/Origin/User-Agent yalnızca bu güvenilir backend tarafından gönderilir.
        for name, value in (playback.get("headers") or {}).items():
            headers[str(name)] = extras._fmt(str(value), {"referrer": referrer, "origin": origin, "page_url": ch.get("page_url") or referrer})
        for name, value in (src.get("headers") or {}).items():
            if str(name).lower() not in {"host", "connection", "content-length", "transfer-encoding"}:
                headers[str(name)] = str(value)
        # Gizli header'lar yalnızca hizmet ortamından okunur, JSON/index'e yazılmaz.
        for name, env_name in (playback.get("header_env") or {}).items():
            if os.environ.get(env_name):
                headers[str(name)] = os.environ[env_name]
        private = bool(playback.get("header_env")) or any(n.lower() in ("authorization", "cookie", "proxy-authorization") for n in headers)
        return ch, dict(src, _requires_https=private), headers, list(playback.get("allowed_hosts") or [])

    def open(self, channel: str = "", source: int = 0, ticket: str = "", byte_range: str = "") -> ProxyResponse:
        target = ""
        if ticket:
            channel, source, target = self.tickets.verify(ticket)
        _, src, headers, hosts = self.context(channel, source)
        url = target or src["url"]
        def guard(target_url):
            validate_url(target_url, hosts, self.resolver)
            if src.get("_requires_https") and urlsplit(target_url).scheme != "https":
                raise StreamError("Gizli yayın header'ları yalnızca HTTPS kaynağına gönderilebilir.", 403, "https_required")
        if byte_range:
            if not re.fullmatch(r"bytes=(?:\d+-\d*|-\d+)", byte_range):
                raise StreamError("Geçersiz byte-range isteği.", 416, "invalid_range")
            headers["Range"] = byte_range
        response = None
        try:
            for hop in range(6):
                guard(url)
                response = self.fetch(url, headers=headers, timeout=(5, 20), stream=True, allow_redirects=False)
                if response.status_code not in REDIRECTS:
                    break
                location = response.headers.get("Location")
                response.close()
                if not location or hop == 5:
                    raise StreamError("Yayın yönlendirme zinciri tamamlanamadı.", 502, "redirect_error")
                url = urljoin(url, location)
            if response.status_code not in (200, 206):
                status = response.status_code
                raise StreamError(f"Yayın kaynağı HTTP {status} döndürdü.", status if 400 <= status < 500 else 502, "upstream_http")
            iterator = response.iter_content(chunk_size=16 * 1024)
            first = next(iterator, b"")
            content_type = response.headers.get("Content-Type", "")
            decoded = first.decode("utf-8-sig", errors="replace").lstrip()
            out_headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
            if decoded.startswith("#EXTM3U"):
                buf = bytearray(first)
                for chunk in iterator:
                    buf.extend(chunk)
                    if len(buf) > PLAYLIST_LIMIT:
                        raise StreamError("HLS listesi boyut sınırını aştı.", 502, "playlist_too_large")
                response.close()

                def child(child_url: str) -> str:
                    guard(child_url)
                    return "?" + urlencode({"ticket": self.tickets.sign(channel, source, child_url)})

                body = rewrite_playlist(buf.decode("utf-8-sig"), url, child).encode()
                out_headers.update({"Content-Type": "application/vnd.apple.mpegurl; charset=utf-8", "Content-Length": str(len(body))})
                return ProxyResponse(200, out_headers, iter([body]), lambda: None)
            out_headers["Content-Type"] = media_type(first, content_type, url)
            length = response.headers.get("Content-Length", "")
            if length.isdigit() and int(length) > SEGMENT_LIMIT:
                raise StreamError("Medya parçası boyut sınırını aştı.", 502, "segment_too_large")
            for header in ("Content-Length", "Content-Range", "Accept-Ranges"):
                if response.headers.get(header) and (header != "Content-Length" or response.headers.get("Content-Encoding", "identity") == "identity"):
                    out_headers[header] = response.headers[header]

            def chunks():
                total = len(first)
                try:
                    yield first
                    for chunk in iterator:
                        total += len(chunk)
                        if total > SEGMENT_LIMIT:
                            raise StreamError("Medya parçası boyut sınırını aştı.", 502, "segment_too_large")
                        yield chunk
                finally:
                    response.close()

            return ProxyResponse(response.status_code, out_headers, chunks(), response.close)
        except Exception as exc:
            if response is not None:
                response.close()
            if isinstance(exc, StreamError):
                raise
            if isinstance(exc, requests.Timeout):
                raise StreamError("Yayın isteği zaman aşımına uğradı.", 504, "upstream_timeout") from exc
            if isinstance(exc, requests.RequestException):
                # requests hata metinleri URL token'ı içerebilir: ham exception loglama.
                log.warning("Yayın bağlantısı kurulamadı: %s (%s)", safe_url(url), type(exc).__name__)
                raise StreamError("Yayın bağlantısı kurulamadı (ağ/TLS).", 502, "connection_error") from exc
            raise
