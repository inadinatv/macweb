"""Kodaman TV public-page channel ID refresh.

Only visible ``iframe`` and ``a`` references to ``/channel?id=...`` in the
homepage are considered. This module deliberately does not inspect scripts,
private APIs, load-balancer metadata, or direct stream URLs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import re
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urljoin, urlsplit, urlunsplit

import requests

from . import config

DEFAULT_HOST = "kodamantv21.com"
HOST_RE = re.compile(r"^kodamantv(?P<number>\d+)\.com$", re.IGNORECASE)
CHANNEL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ROTATION_NOTICE = "bir sonraki alan adimiz bir sayi artarak devam edecektir"
CHANNEL_ERROR_MARKERS = (
    "hay aksi",
    "hls:networkerror",
    "manifestloaderror",
    "yayini yenileyin",
    "yayın açılamadı",
)
OUTPUT_PATH = config.OUTPUT_DIR / "kodaman_channels.json"


class PublicSourceUnavailable(RuntimeError):
    """The public Kodaman homepage could not be verified safely."""


@dataclass(frozen=True)
class PublicPage:
    url: str
    status_code: int
    text: str


PageFetcher = Callable[[str], PublicPage]


def _host_number(host: str | None) -> int | None:
    if not host:
        return None
    match = HOST_RE.fullmatch(host.lower().rstrip("."))
    return int(match.group("number")) if match else None


def _validated_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not _host_number(parts.hostname):
        raise ValueError("Kodaman kaynağı yalnızca HTTPS kodamantv<N>.com alan adları olabilir")
    return urlunsplit(("https", parts.netloc.lower(), parts.path or "/", parts.query, ""))


def _origin(url: str) -> str:
    clean = _validated_url(url)
    parts = urlsplit(clean)
    return f"https://{parts.netloc}"


def fetch_public_page(url: str) -> PublicPage:
    """Fetch one public page and follow redirects only within the numbered domain family."""
    current = _validated_url(url)
    headers = {"User-Agent": "Macweb-Kodaman-Public-ID-Refresh/1.0"}
    for _ in range(6):
        response = requests.get(current, headers=headers, timeout=15, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            if not location:
                raise PublicSourceUnavailable("Kodaman redirect yanıtında hedef yok")
            destination = _validated_url(urljoin(current, location))
            current = destination
            continue
        if response.status_code >= 400:
            raise PublicSourceUnavailable(f"Kodaman public sayfası HTTP {response.status_code}")
        return PublicPage(url=current, status_code=response.status_code, text=response.text)
    raise PublicSourceUnavailable("Kodaman yönlendirme zinciri sınırı aştı")


def _attrs_visible(attrs: dict[str, str | None]) -> bool:
    if "hidden" in attrs or str(attrs.get("aria-hidden", "")).lower() == "true":
        return False
    style = re.sub(r"\s+", "", str(attrs.get("style", "")).lower())
    return "display:none" not in style and "visibility:hidden" not in style


class _VisibleRefParser(HTMLParser):
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr", "iframe"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str]] = []
        self.stack: list[tuple[str, bool]] = []
        self.anchor: tuple[str, str] | None = None
        self.anchor_text: list[str] = []

    def _parent_hidden(self) -> bool:
        return any(hidden for _, hidden in self.stack)

    def handle_starttag(self, tag: str, pairs: list[tuple[str, str | None]]) -> None:
        attrs = dict(pairs)
        hidden = self._parent_hidden() or not _attrs_visible(attrs)
        if not hidden and tag == "iframe" and attrs.get("src"):
            label = str(attrs.get("title") or attrs.get("aria-label") or "").strip()
            self.refs.append((str(attrs["src"]), label))
        elif not hidden and tag == "a" and attrs.get("href"):
            self.anchor = (str(attrs["href"]), str(attrs.get("title") or attrs.get("aria-label") or "").strip())
            self.anchor_text = []
        if tag not in self._VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag: str, pairs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, pairs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.anchor is not None and not self._parent_hidden():
            self.anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.anchor is not None:
            href, label = self.anchor
            text = " ".join(" ".join(self.anchor_text).split())
            self.refs.append((href, label or text))
            self.anchor = None
            self.anchor_text = []
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def _default_name(channel_id: str) -> str:
    if channel_id.lower() == "zirve":
        return "Zirve Stream"
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", channel_id) if part) or channel_id


def extract_visible_channels(html: str, base_url: str) -> list[dict[str, str]]:
    """Return unique safe channel IDs referenced by visible iframe/link elements."""
    origin = _origin(base_url)
    host = urlsplit(origin).hostname
    parser = _VisibleRefParser()
    parser.feed(html or "")
    found: dict[str, str] = {}
    for ref, label in parser.refs:
        absolute = urljoin(origin + "/", ref)
        parts = urlsplit(absolute)
        if parts.scheme != "https" or parts.hostname != host or parts.path.rstrip("/") != "/channel":
            continue
        values = parse_qs(parts.query).get("id", [])
        if not values:
            continue
        channel_id = values[0].strip()
        if not CHANNEL_ID_RE.fullmatch(channel_id):
            continue
        clean_label = " ".join(unescape(label).split())[:64] if label else ""
        if channel_id not in found or (clean_label and clean_label.lower() != channel_id.lower()):
            found[channel_id] = clean_label or found.get(channel_id) or _default_name(channel_id)
    return [{"id": channel_id, "name": name} for channel_id, name in found.items()]


def _normalized_copy(html: str) -> str:
    text = re.sub(r"<[^>]*>", " ", unescape(html or ""))
    text = " ".join(text.lower().split())
    return (text.replace("ı", "i").replace("ş", "s").replace("ğ", "g")
                .replace("ü", "u").replace("ö", "o").replace("ç", "c"))


def _has_rotation_notice(html: str) -> bool:
    return ROTATION_NOTICE in _normalized_copy(html)


def _looks_like_kodaman(html: str) -> bool:
    text = _normalized_copy(html)
    return "kodaman" in text or "canli mac yayinlari" in text or "zirve stream" in text


def _next_host(host: str) -> str | None:
    number = _host_number(host)
    return f"kodamantv{number + 1}.com" if number is not None else None


def _try_home(host: str, fetcher: PageFetcher) -> tuple[PublicPage, str, list[dict[str, str]]] | None:
    try:
        page = fetcher(f"https://{host}/")
    except Exception:
        return None
    if page.status_code >= 400:
        return None
    try:
        final_url = _validated_url(page.url)
    except ValueError:
        return None
    if not _looks_like_kodaman(page.text):
        return None
    base_url = _origin(final_url)
    return page, base_url, extract_visible_channels(page.text, base_url)


def _check_player(base_url: str, channel_id: str, fetcher: PageFetcher) -> str:
    player_url = f"{base_url}/channel?id={quote(channel_id, safe='')}"
    try:
        page = fetcher(player_url)
    except Exception:
        return "unknown"
    if page.status_code >= 400 or any(marker in _normalized_copy(page.text) for marker in CHANNEL_ERROR_MARKERS):
        return "error"
    return "page"


def _read_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def refresh_manifest(path: Path | None = None, fetcher: PageFetcher = fetch_public_page,
                     now: datetime | None = None) -> tuple[dict, bool]:
    """Refresh the manifest from public homepage references; preserve it on source failure.

    At most the current numbered domain and the immediately following number are
    checked. The next number is considered only when the current host is unavailable
    or the page publicly states that its domain number will increase.
    """
    target = path or OUTPUT_PATH
    old = _read_manifest(target)
    old_base = str(old.get("base_url") or f"https://{DEFAULT_HOST}")
    try:
        current_host = urlsplit(_validated_url(old_base)).hostname or DEFAULT_HOST
    except ValueError:
        current_host = DEFAULT_HOST

    result = _try_home(current_host, fetcher)
    if result is None:
        next_host = _next_host(current_host)
        result = _try_home(next_host, fetcher) if next_host else None
    elif _has_rotation_notice(result[0].text):
        next_host = _next_host(urlsplit(result[1]).hostname or current_host)
        next_result = _try_home(next_host, fetcher) if next_host else None
        # Prefer the next domain only when it is a Kodaman page with visible IDs.
        if next_result and next_result[2]:
            result = next_result

    if result is None:
        raise PublicSourceUnavailable("Kodaman ana sayfası doğrulanamadı; son iyi manifest korundu")

    page, base_url, public_channels = result
    channels = []
    for item in public_channels:
        channels.append({
            "id": item["id"],
            "name": item["name"],
            "status": _check_player(base_url, item["id"], fetcher),
        })

    comparable = {"base_url": base_url, "channels": channels}
    old_comparable = {"base_url": old.get("base_url"), "channels": old.get("channels", [])}
    if comparable == old_comparable and old.get("updated_at"):
        return {**comparable, "updated_at": old["updated_at"]}, False

    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = {**comparable, "updated_at": timestamp}
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return manifest, True
