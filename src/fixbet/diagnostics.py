"""HLS HTTP tanılaması. Tarayıcı ve kaynak-site istek bağlamlarını karşılaştırır.

Gerçek tarayıcı CORS kontrolünün yerine geçmez. ffprobe varsa ilk segmentin
codec/track bilgisini de raporlar. Query/token, cookie veya key içeriği loglanmaz.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from . import extras
from .stream_proxy import safe_url

LIMIT = 4 * 1024 * 1024


def _probe(data: bytes) -> dict:
    executable = shutil.which("ffprobe")
    if not executable:
        return {"checked": False, "reason": "ffprobe kurulu değil; codec'ler ancak playlist bildiriminden görülebilir"}
    try:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.bin"
            path.write_bytes(data)
            result = subprocess.run([executable, "-v", "error", "-show_streams", "-of", "json", str(path)],
                                    capture_output=True, timeout=10, check=False)
        data = json.loads(result.stdout or b"{}")
        return {"checked": result.returncode == 0, "tracks": [
            {k: stream[k] for k in ("codec_name", "codec_type", "profile", "width", "height", "channels", "sample_rate") if k in stream}
            for stream in data.get("streams", [])]}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"checked": False, "reason": "örnek segment çözümlenemedi (şifreli veya init eksik olabilir)"}


def inspect_context(url: str, headers: dict, page_origin: str, fetch=requests.get) -> dict:
    requests_log = []
    visited = set()

    def read(url, kind, depth=0):
        if url in visited or len(requests_log) >= 8 or urlsplit(url).scheme not in ("http", "https"):
            return
        visited.add(url)
        row = {"kind": kind, "url": safe_url(url)}
        requests_log.append(row)
        try:
            with fetch(url, headers=headers, timeout=(5, 8), stream=True, allow_redirects=True) as response:
                final = response.url
                acao = response.headers.get("Access-Control-Allow-Origin")
                row.update({"http_status": response.status_code, "final_url": safe_url(final),
                    "redirects": [{"status": r.status_code, "url": safe_url(r.url), "allow_origin": r.headers.get("Access-Control-Allow-Origin")} for r in response.history],
                    "mime": response.headers.get("Content-Type"), "allow_origin": acao,
                    "cors_allows_page_origin": acao in ("*", page_origin),
                    "mixed_content": page_origin.startswith("https:") and (url.startswith("http:") or final.startswith("http:"))})
                if response.status_code != 200:
                    return
                body = bytearray()
                for chunk in response.iter_content(16384):
                    body.extend(chunk)
                    if len(body) >= LIMIT:
                        row["sample_truncated"] = True
                        break
                row["sample_bytes"] = len(body)
            text = body.decode("utf-8-sig", errors="replace")
            if extras.is_hls_playlist(text):
                master = "#EXT-X-STREAM-INF:" in text
                row["playlist_type"] = "master" if master else "media"
                row["declared_codecs"] = re.findall(r'CODECS="([^"]+)"', text)
                row["declared_resolutions"] = re.findall(r'RESOLUTION=([0-9]+x[0-9]+)', text)
                row["target_duration"] = (re.findall(r'#EXT-X-TARGETDURATION:(\d+)', text) or [None])[0]
                row["encrypted"] = bool(re.search(r'#EXT-X-KEY:METHOD=(?!NONE)', text))
                uris = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
                if depth < 2 and uris:
                    read(urljoin(final, uris[0]), "media" if master else "segment", depth + 1)
                for tag, label in (("KEY", "key"), ("MAP", "init")):
                    uri = re.search(r'#EXT-X-' + tag + r':[^\n]*URI="([^"]+)"', text)
                    if uri:
                        read(urljoin(final, uri[1]), label, depth + 1)
            elif kind == "segment":
                row["payload_type"] = "mpeg-ts" if len(body) > 376 and body[0] == body[188] == body[376] == 0x47 else (
                    "mp4" if body[4:8] in (b"ftyp", b"styp", b"moof") else "unknown/encrypted")
                row["media_probe"] = _probe(bytes(body))
        except requests.RequestException as exc:
            row["error"] = type(exc).__name__  # exception metni token içerebilir
            row["note"] = "Ağ/TLS isteği tamamlanamadı; bu sonuç tek başına CORS veya codec hatasını kanıtlamaz."
    read(url, "manifest")
    return {"requests": requests_log}


def diagnose(channel_id: str, source: int = 0, page_origin: str = "https://inadinatv.github.io") -> dict:
    channel = next((c for c in extras.flatten(extras.load_or_build()) if c.get("id") == channel_id), None)
    if not channel or source < 0 or source >= len(channel.get("sources", [])):
        raise ValueError("Kanal veya kaynak bulunamadı")
    src = channel["sources"][source]
    if src.get("type") != "hls":
        raise ValueError("Bu kaynak HLS değil, bir player sayfası")
    browser = dict(extras.DEFAULT_HEADERS, Origin=page_origin, Referer=page_origin.rstrip("/") + "/macweb/")
    referrer = channel.get("referrer") or channel.get("page_url") or ""
    origin = extras._origin(referrer)
    source_headers = dict(extras.DEFAULT_HEADERS, Referer=referrer, Origin=origin)
    panel = next((p for p in extras.load_config().get("panels", []) if p.get("id") == channel_id.split(":", 1)[0]), {})
    for name, value in (panel.get("playback", {}).get("headers") or {}).items():
        source_headers[name] = extras._fmt(str(value), {"referrer": referrer, "origin": origin, "page_url": channel.get("page_url") or referrer})
    return {"channel": channel_id, "url": safe_url(src["url"]),
            "note": "HTTP karşılaştırmasıdır; harici player'ın tam HAR kaydı değildir. CORS tarayıcıda ayrıca doğrulanmalıdır.",
            "browser_context": inspect_context(src["url"], browser, page_origin),
            "source_context": inspect_context(src["url"], source_headers, page_origin)}
