"""Refresh Kodaman channel IDs from its public, rendered KANALLAR menu.

The scheduled refresh opens the public homepage in a headless browser, clicks
its visible KANALLAR tab, and reads only links rendered inside #channels-content.
It does not inspect scripts for hidden IDs, private APIs, or stream URLs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import re
from pathlib import Path
import subprocess
from typing import Callable
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import requests

from . import config

DEFAULT_HOST = "kodamantv21.com"
HOST_RE = re.compile(r"^kodamantv(?P<number>\d+)\.com$", re.IGNORECASE)
CHANNEL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ROTATION_NOTICE = "bir sonraki alan adimiz bir sayi artarak devam edecektir"
OUTPUT_PATH = config.OUTPUT_DIR / "kodaman_channels.json"
MENU_SCRIPT = Path(__file__).with_name("kodaman_visible_menu.mjs")


class PublicSourceUnavailable(RuntimeError):
    """The public Kodaman homepage or rendered channel menu could not be verified."""


@dataclass(frozen=True)
class PublicPage:
    url: str
    status_code: int
    text: str


PageFetcher = Callable[[str], PublicPage]
MenuFetcher = Callable[[str], tuple[str, list[dict[str, str]]]]


def _host_number(host: str | None) -> int | None:
    if not host:
        return None
    match = HOST_RE.fullmatch(host.lower().rstrip("."))
    return int(match.group("number")) if match else None


def _validated_url(url: str) -> str:
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = -1
    host = (parts.hostname or "").lower()
    if (parts.scheme.lower() != "https" or not _host_number(host) or
            parts.username is not None or parts.password is not None or port not in (None, 443)):
        raise ValueError("Kodaman kaynağı yalnızca HTTPS kodamantv<N>.com alan adları olabilir")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def _origin(url: str) -> str:
    clean = _validated_url(url)
    parts = urlsplit(clean)
    return f"https://{parts.netloc}"


def fetch_public_page(url: str) -> PublicPage:
    """Fetch a public page and follow redirects only within the numbered domain family."""
    current = _validated_url(url)
    headers = {"User-Agent": "Macweb-Kodaman-Public-ID-Refresh/1.0"}
    for _ in range(6):
        response = requests.get(current, headers=headers, timeout=15, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            if not location:
                raise PublicSourceUnavailable("Kodaman redirect yanıtında hedef yok")
            current = _validated_url(urljoin(current, location))
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
    """Small static-HTML parser retained for deterministic fixtures/fallbacks."""

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
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", channel_id) if part) or channel_id


def extract_visible_channels(html: str, base_url: str) -> list[dict[str, str]]:
    """Return unique safe channel IDs from visible same-site iframe/link references."""
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
        found.setdefault(channel_id, clean_label or _default_name(channel_id))
    return [{"id": channel_id, "name": name} for channel_id, name in found.items()]


def normalize_menu_channels(items: object, base_url: str) -> list[dict[str, str]]:
    """Validate rendered-menu rows and keep only same-site /channel?id links."""
    origin = _origin(base_url)
    host = urlsplit(origin).hostname
    if not isinstance(items, list) or len(items) > 100:
        return []
    found: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        href = str(item.get("href") or "").strip()
        absolute = urljoin(origin + "/", href)
        parts = urlsplit(absolute)
        if parts.scheme != "https" or parts.hostname != host or parts.path.rstrip("/") != "/channel":
            continue
        values = parse_qs(parts.query).get("id", [])
        if not values:
            continue
        channel_id = values[0].strip()
        if not CHANNEL_ID_RE.fullmatch(channel_id):
            continue
        name = " ".join(unescape(str(item.get("name") or "")).split())
        name = re.sub(r"^7/24\s*", "", name, flags=re.IGNORECASE).strip()[:64]
        if channel_id not in found:
            found[channel_id] = name or _default_name(channel_id)
    return [{"id": channel_id, "name": name} for channel_id, name in found.items()]


def fetch_visible_channel_menu(base_url: str) -> tuple[str, list[dict[str, str]]]:
    """Render the public page, click its visible KANALLAR tab, and collect menu links."""
    safe_base = _origin(_validated_url(base_url))
    repo_root = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["node", str(MENU_SCRIPT), safe_base + "/"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublicSourceUnavailable(f"Görünür kanal menüsü tarayıcıda açılamadı ({type(exc).__name__})") from exc
    if result.returncode != 0:
        raise PublicSourceUnavailable("Görünür KANALLAR menüsü alınamadı")
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("catalog payload is not an object")
        menu_base = _origin(_validated_url(str(payload.get("base_url") or safe_base)))
        channels = normalize_menu_channels(payload.get("channels"), menu_base)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise PublicSourceUnavailable("Görünür KANALLAR menüsü doğrulanamadı") from exc
    if not channels:
        raise PublicSourceUnavailable("Görünür KANALLAR menüsünde geçerli public kanal bağlantısı yok")
    return menu_base, channels


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


def _try_home(host: str, fetcher: PageFetcher, menu_fetcher: MenuFetcher | None = None):
    try:
        page = fetcher(f"https://{host}/")
    except Exception:
        return None
    if page.status_code >= 400:
        return None
    try:
        base_url = _origin(_validated_url(page.url))
    except ValueError:
        return None
    if not _looks_like_kodaman(page.text):
        return None
    if menu_fetcher is None:
        channels = extract_visible_channels(page.text, base_url)
    else:
        try:
            base_url, channels = menu_fetcher(base_url)
            base_url = _origin(_validated_url(base_url))
        except Exception:
            return None
    if not channels:
        return None
    return page, base_url, channels


def _read_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def refresh_manifest(path: Path | None = None, fetcher: PageFetcher = fetch_public_page,
                     now: datetime | None = None, menu_fetcher: MenuFetcher | None = None) -> tuple[dict, bool]:
    """Refresh from the rendered public KANALLAR menu; preserve last good data on failure.

    The optional menu_fetcher is used by the scheduled CLI to render the public
    page and click KANALLAR. At most the current numbered domain and the immediately
    following number are checked; no per-channel player probes are made.
    """
    target = path or OUTPUT_PATH
    old = _read_manifest(target)
    old_base = str(old.get("base_url") or f"https://{DEFAULT_HOST}")
    try:
        current_host = urlsplit(_validated_url(old_base)).hostname or DEFAULT_HOST
    except ValueError:
        current_host = DEFAULT_HOST

    result = _try_home(current_host, fetcher, menu_fetcher)
    if result is None:
        next_host = _next_host(current_host)
        result = _try_home(next_host, fetcher, menu_fetcher) if next_host else None
    elif _has_rotation_notice(result[0].text):
        next_host = _next_host(urlsplit(result[1]).hostname or current_host)
        next_result = _try_home(next_host, fetcher, menu_fetcher) if next_host else None
        if next_result and next_result[2]:
            result = next_result

    if result is None:
        raise PublicSourceUnavailable("Kodaman ana sayfası veya görünür KANALLAR menüsü doğrulanamadı; son iyi manifest korundu")

    _page, base_url, public_channels = result
    channels = [{"id": item["id"], "name": item["name"], "status": "listed"} for item in public_channels]
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
