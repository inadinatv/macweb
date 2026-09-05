"""Ekstra paneller: doğrudan m3u8/HLS kaynaklı kanal grupları (Atom Spor, Selçuk Spor …).

config/extra_channels.yml içindeki panelleri okur ve her kanal için:
  * kanal/oynatıcı sayfasından m3u8 yayın adresini çıkarır (düz link, göreli link,
    URL-encoded, base64/atob, iç içe iframe'ler) ya da sayfadaki yayın kökünden
    (``this.adsBaseUrl = '…'`` gibi) şablonla kurar,
  * çıkaramazsa son başarılı çözümü (belirli bir süre) korur,
  * yedek m3u8 şablonunu ve (istenirse) sayfayı iframe yedeği olarak ekler,
  * panelin adresi değiştiyse bilinen giriş adreslerini (yönlendirme) ve numaralı
    ayna taramasını dener (atomsportv501 → 502 …, sporcafe8 → …),
  * iki aşamalı sitelerde (Selçuk) ana sayfadan oynatıcı sunucusunu bulur
    (``player.domain_pattern`` → ``{player_base}``).

Sonuç output/extra_channels.json dosyasına yazılır; sayfa (index.html) bu
kanalları kendi HLS oynatıcısında açar ve kaynakları sırayla dener.
"""
from __future__ import annotations

import base64
import concurrent.futures as cf
import json
import os
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

from . import config

EXTRA_CONFIG = config.CONFIG_DIR / "extra_channels.yml"
EXTRA_OUTPUT = config.OUTPUT_DIR / "extra_channels.json"
# Sayfanın canlı tazeleme için okuduğu yol (GitHub Pages köküne göre)
EXTRA_SOURCE = "output/extra_channels.json"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}


@dataclass
class FetchResult:
    status: int
    url: str      # yönlendirmeler sonrası nihai adres
    text: str


# fetch(url, headers, timeout) -> FetchResult | None  (ağ hatası → None)
Fetcher = Callable[[str, dict[str, str], float], "FetchResult | None"]


def _http_get(url: str, headers: dict[str, str], timeout: float) -> FetchResult | None:
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        return FetchResult(resp.status_code, resp.url, resp.text)
    except requests.exceptions.RequestException:
        return None


# ---------------------------------------------------------------------------
# m3u8 çıkarma
# ---------------------------------------------------------------------------
_M3U8_ABS = re.compile(r'(https?://[^\s\'"<>\\]+\.m3u8[^\s\'"<>\\]*)', re.I)
_M3U8_REL = re.compile(r'[\'"](/[^\s\'"<>]+\.m3u8[^\s\'"<>]*)[\'"]', re.I)
_M3U8_ENC = re.compile(r'(https?%3A%2F%2F[^\s\'"<>]+(?:%2E|\.)m3u8[^\s\'"<>]*)', re.I)
_ATOB = re.compile(r'atob\(\s*[\'"]([A-Za-z0-9+/=]+)[\'"]\s*\)')
_B64_LONG = re.compile(r'[\'"]([A-Za-z0-9+/=]{40,})[\'"]')
_IFRAME = re.compile(r'<iframe[^>]+src=["\'](https?://[^"\']+)["\']', re.I)
_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _b64_text(blob: str) -> str | None:
    try:
        return base64.b64decode(blob, validate=False).decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001 - bozuk base64 yoksayılır
        return None


def find_m3u8(text: str, base_url: str) -> str | None:
    """Sayfa/script metninden ilk m3u8 adresini çıkarır (yoksa None)."""
    if not text:
        return None
    # JSON içinde kaçışlı eğik çizgiler (https:\/\/...) sık görülür
    plain = text.replace("\\/", "/")

    m = _M3U8_ABS.search(plain)
    if m:
        return m.group(1)

    m = _M3U8_REL.search(plain)
    if m:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}{m.group(1)}"

    m = _M3U8_ENC.search(plain)
    if m:
        return urllib.parse.unquote(m.group(1))

    for blob in _ATOB.findall(plain):
        decoded = _b64_text(blob)
        if decoded:
            hit = _M3U8_ABS.search(decoded.replace("\\/", "/"))
            if hit:
                return hit.group(1)

    for blob in _B64_LONG.findall(plain):
        decoded = _b64_text(blob)
        if decoded and ".m3u8" in decoded:
            hit = _M3U8_ABS.search(decoded.replace("\\/", "/"))
            if hit:
                return hit.group(1)
    return None


class _SafeMap(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _fmt(template: str | None, mapping: dict[str, str]) -> str:
    """Şablonu doldurur; bilinmeyen/boş bir yer tutucu kalırsa "" döner."""
    if not template:
        return ""
    out = str(template).format_map(_SafeMap({k: v for k, v in mapping.items() if v}))
    return "" if _PLACEHOLDER.search(out) else out


def stream_from_rules(text: str, rules: dict[str, Any] | None, fmt: dict[str, str]) -> str | None:
    """Sayfadaki yayın kökünden (``this.adsBaseUrl = '…'``) şablonla m3u8 kurar.

    rules: {"stream_base_patterns": [regex, …], "stream_template": "{stream_base}{slug}/playlist.m3u8"}
    """
    if not rules or not text:
        return None
    patterns = rules.get("stream_base_patterns") or []
    template = rules.get("stream_template") or ""
    if not patterns or not template:
        return None
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        base = m.group(1) if m.groups() else m.group(0)
        url = _fmt(template, dict(fmt, stream_base=base))
        if url:
            return url
    return None


def extract_m3u8_from_page(url: str, referrer: str | None, fetch: Fetcher,
                           headers: dict[str, str] | None = None, timeout: float = 8,
                           depth: int = 2, rules: dict[str, Any] | None = None,
                           fmt: dict[str, str] | None = None) -> str | None:
    """Sayfayı (ve iç içe iframe'lerini) tarayıp m3u8 adresini bulur/kurar."""
    hdrs = dict(headers or DEFAULT_HEADERS)
    if referrer:
        hdrs["Referer"] = referrer
    res = fetch(url, hdrs, timeout)
    if res is None or res.status != 200:
        return None
    built = stream_from_rules(res.text, rules, fmt or {})
    if built:
        return built
    found = find_m3u8(res.text, res.url or url)
    if found:
        return found
    if depth <= 0:
        return None
    for src in _IFRAME.findall(res.text)[:6]:
        found = extract_m3u8_from_page(src, url, fetch, headers, timeout, depth - 1, rules, fmt)
        if found:
            return found
    return None


# ---------------------------------------------------------------------------
# Yapılandırma / durum
# ---------------------------------------------------------------------------
def load_config() -> dict[str, Any]:
    return config._read(EXTRA_CONFIG)  # noqa: SLF001 - aynı paket içi yardımcı


def load_output() -> dict[str, Any]:
    """Önceki çalışmanın çıktısı (son bilinen adresler + çözümlenmiş m3u8'ler)."""
    if not EXTRA_OUTPUT.exists():
        return {}
    try:
        return json.loads(EXTRA_OUTPUT.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        return {}


def write_output(data: dict[str, Any]) -> str:
    os.makedirs(EXTRA_OUTPUT.parent, exist_ok=True)
    EXTRA_OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(EXTRA_OUTPUT)


def _utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _fresh(iso: str | None, now: datetime, hours: float | None) -> bool:
    """resolved_at zaman damgası hâlâ geçerli mi? (hours None → süresiz)"""
    if not iso:
        return False
    if hours is None:
        return True
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts) <= timedelta(hours=float(hours))


def _origin(url: str) -> str:
    p = urllib.parse.urlparse(url)
    if p.scheme and p.netloc:
        return f"{p.scheme}://{p.netloc}"
    return url.rstrip("/")


def _num_in(domain: str | None) -> int:
    body = (domain or "").split("//")[-1].split("/")[0]
    body = body[4:] if body.startswith("www.") else body
    body = body.split(".")[0]
    digits = "".join(c for c in body if c.isdigit())
    return int(digits) if digits and "-" not in body else 0


def _first_slug(panel: dict[str, Any]) -> str:
    for ch in panel.get("channels") or []:
        slug = str(ch.get("slug") or ch.get("id") or "").strip()
        if slug:
            return slug
    return ""


# ---------------------------------------------------------------------------
# Adres (ayna) seçimi
# ---------------------------------------------------------------------------
@dataclass
class Probe:
    origin: str   # sağlıklı bulunan adresin kökü (yönlendirme sonrası)
    url: str
    text: str     # sağlık sayfasının içeriği (oynatıcı sunucusu buradan da bulunabilir)


def mirror_candidates(mirror: dict[str, Any], known: str | None) -> list[str]:
    """Bilinen adres + tercih edilen numara çevresindeki adayları üretir.

    Yüksek numaralar (yeni aynalar) önce denenir.
    """
    pattern = str(mirror.get("pattern") or "")
    if "{n}" not in pattern:
        return []
    window = int(mirror.get("scan_window", 10))
    centers: list[int] = []
    for c in (_num_in(known), int(mirror.get("preferred_number", 0) or 0)):
        if c and c not in centers:
            centers.append(c)
    numbers: set[int] = set()
    for c in centers:
        numbers.update(n for n in range(c - window, c + window + 1) if n > 0)
    return [pattern.format(n=n) for n in sorted(numbers, reverse=True)]


def _health_target(base: str, panel: dict[str, Any]) -> tuple[str, list[str]]:
    """Sağlık kontrolü için (url, aranacak işaretler) döndürür.

    * ``health_path`` verilmişse o yol (ör. "/" + ``must_contain_any`` işaretleri),
    * yoksa ilk kanalın sayfası (park sayfaları slug/m3u8 izi taşımadığı için elenir),
    * o da kurulamıyorsa ana sayfa.
    """
    tokens = [str(t) for t in ((panel.get("mirror") or {}).get("must_contain_any") or [])]
    health_path = panel.get("health_path")
    if health_path:
        return base.rstrip("/") + "/" + str(health_path).lstrip("/"), tokens
    slug = _first_slug(panel)
    page = _fmt(panel.get("page_template"), {"base_url": base, "slug": slug}) if slug else ""
    if page:
        return page, tokens or ([slug] + ["m3u8"])
    return base.rstrip("/") + "/", tokens


def _probe_base(candidate: str, panel: dict[str, Any], fetch: Fetcher,
                headers: dict[str, str], timeout: float) -> Probe | None:
    """Aday adres sağlıklıysa nihai kökünü (yönlendirme sonrası) döndürür."""
    if not candidate:
        return None
    base = _origin(candidate if "://" in candidate else "https://" + candidate)
    url, tokens = _health_target(base, panel)
    res = fetch(url, dict(headers), timeout)
    if res is None or res.status != 200:
        return None
    text = res.text or ""
    if tokens and not any(tok in text for tok in tokens):
        return None
    final = res.url or url
    return Probe(_origin(final), final, text)


def choose_base_url(panel: dict[str, Any], previous: dict[str, Any] | None, fetch: Fetcher | None,
                    headers: dict[str, str], timeout: float) -> tuple[str, bool | None, str]:
    """(base_url, healthy, sağlık sayfası HTML) döndürür. fetch None ise ağ kullanılmaz.

    Sıra: son bilinen adres → yapılandırmadaki adres → bilinen giriş adresleri
    (``entry_urls``, yönlendirmeleri izlenir) → numaralı ayna taraması.
    Hiçbiri sağlıklı değilse son bilinen adres korunur (healthy=False).
    """
    prev_base = str((previous or {}).get("base_url") or "").strip()
    cfg_base = str(panel.get("base_url") or "").strip()
    known = prev_base or cfg_base
    if fetch is None:
        return (_origin(known) if known else ""), None, ""

    ordered: list[str] = []
    for cand in [prev_base, cfg_base, *(str(u) for u in (panel.get("entry_urls") or []))]:
        cand = cand.strip()
        if cand and cand not in ordered:
            ordered.append(cand)
    for cand in ordered:
        probe = _probe_base(cand, panel, fetch, headers, timeout)
        if probe:
            return probe.origin, True, probe.text

    candidates = mirror_candidates(panel.get("mirror") or {}, known)
    if candidates:
        workers = min(16, max(4, len(candidates)))
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda d: _probe_base(d, panel, fetch, headers, timeout), candidates))
        for probe in results:  # yüksek numara (yeni ayna) önce
            if probe:
                return probe.origin, True, probe.text

    return (_origin(known) if known else ""), False, ""


def _match_domain(pattern: str, text: str) -> str:
    if not pattern or not text:
        return ""
    m = re.search(pattern, text)
    if not m:
        return ""
    dom = m.group(1) if m.groups() else m.group(0)
    if "://" not in dom:
        dom = "https://" + dom
    return _origin(dom)


def find_player_base(panel: dict[str, Any], base_url: str, healthy: bool | None, html: str,
                     previous: dict[str, Any] | None, fetch: Fetcher | None,
                     headers: dict[str, str], timeout: float) -> str:
    """İki aşamalı sitelerde oynatıcı sunucusunu bulur (``player.domain_pattern``).

    Sağlık sayfasında yoksa ana sayfa çekilir; o da olmazsa son bilinen ya da
    yapılandırmadaki varsayılan (``player.default_base``) kullanılır.
    """
    player = panel.get("player") or {}
    pattern = str(player.get("domain_pattern") or "")
    if not pattern:
        return ""
    found = _match_domain(pattern, html)
    if not found and fetch is not None and healthy and base_url:
        res = fetch(base_url.rstrip("/") + "/", dict(headers), timeout)
        if res is not None and res.status == 200:
            found = _match_domain(pattern, res.text or "")
    if found:
        return found
    return str((previous or {}).get("player_base") or player.get("default_base") or "").rstrip("/")


# ---------------------------------------------------------------------------
# Kanal çözümleme
# ---------------------------------------------------------------------------
def _channel_icon(name: str) -> str:
    from .site import channel_icon  # döngüsel içe aktarmayı önlemek için yerel

    return channel_icon(name)


def resolve_channel(panel: dict[str, Any], ctx: dict[str, Any], ch: dict[str, Any],
                    previous: dict[str, Any] | None, fetch: Fetcher | None, headers: dict[str, str],
                    timeout: float, now: datetime, keep_hours: float | None) -> dict[str, Any]:
    """Tek kanal için kaynak listesini üretir.

    ctx: {"base_url", "healthy", "player_base"} — panel düzeyinde bulunan adresler.
    """
    slug = str(ch.get("slug") or ch.get("id") or "").strip()
    name = str(ch.get("name") or slug).strip()
    panel_id = str(panel.get("id") or "extra")
    base_url = str(ctx.get("base_url") or "").rstrip("/")
    healthy = ctx.get("healthy")
    fmt = {"base_url": base_url, "slug": slug, "player_base": str(ctx.get("player_base") or "").rstrip("/")}

    page_url = _fmt(panel.get("page_template"), fmt) if slug else ""
    if panel.get("embed_template"):
        embed_url = _fmt(panel.get("embed_template"), fmt) if slug else ""
    else:
        embed_url = page_url if panel.get("embed_fallback") else ""
    fallback = _fmt(panel.get("fallback_template"), fmt) if slug else ""
    static = str(ch.get("url") or "").strip()
    referrer = _fmt(panel.get("referrer"), fmt) or (base_url + "/" if base_url else "")
    rules = panel.get("player") or None

    # Adres kapalıysa (healthy=False) kanal başına boşuna istek atılmaz; son çözüm/yedek kullanılır
    resolved, resolved_at, stale = "", None, False
    if page_url and fetch is not None and healthy is not False:
        resolved = extract_m3u8_from_page(page_url, referrer, fetch, headers, timeout,
                                          rules=rules, fmt=fmt) or ""
        if resolved:
            resolved_at = now.isoformat(timespec="seconds")
    if not resolved and previous:
        prev_url, prev_at = previous.get("resolved_url"), previous.get("resolved_at")
        if prev_url and _fresh(prev_at, now, keep_hours):
            resolved, resolved_at, stale = str(prev_url), prev_at, True

    sources: list[dict[str, str]] = []

    def add(url: str, typ: str) -> None:
        if url and all(s["url"] != url for s in sources):
            sources.append({"type": typ, "url": url, "label": ""})

    add(static, "hls")
    add(resolved, "hls")
    add(fallback, "hls")
    add(embed_url, "embed")
    n = 0
    for s in sources:
        if s["type"] == "hls":
            n += 1
            s["label"] = f"Kaynak {n}"
        else:
            s["label"] = "Site"

    return {
        "id": f"{panel_id}:{slug}",
        "slug": slug,
        "name": name,
        "panel": panel_id,
        "panel_name": str(panel.get("name") or panel_id.upper()),
        "icon": _channel_icon(name),
        "logo": str(panel.get("logo") or ch.get("logo") or ""),
        "page_url": page_url,
        "referrer": referrer,
        "sources": sources,
        # resolved: siteden çıkarılmış bir m3u8 var (taze ya da korunan); stale: bu çalışmada yenilenemedi
        "resolved": bool(resolved),
        "fresh": bool(resolved) and not stale,
        "resolved_url": resolved or None,
        "resolved_at": resolved_at,
        "stale": stale,
    }


def resolve_panel(panel: dict[str, Any], previous: dict[str, Any] | None, fetch: Fetcher | None,
                  headers: dict[str, str], timeout: float, now: datetime, keep_hours: float | None,
                  max_workers: int = 10) -> dict[str, Any]:
    base_url, healthy, html = choose_base_url(panel, previous, fetch, headers, timeout)
    player_base = find_player_base(panel, base_url, healthy, html, previous, fetch, headers, timeout)
    ctx = {"base_url": base_url, "healthy": healthy, "player_base": player_base}

    prev_channels = {c.get("slug"): c for c in (previous or {}).get("channels", [])}
    chans = [c for c in (panel.get("channels") or []) if (c.get("slug") or c.get("id"))]

    def work(ch: dict[str, Any]) -> dict[str, Any]:
        prev = prev_channels.get(str(ch.get("slug") or ch.get("id")))
        return resolve_channel(panel, ctx, ch, prev, fetch, headers, timeout, now, keep_hours)

    if fetch is not None and len(chans) > 1:
        with cf.ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(chans)))) as pool:
            channels = list(pool.map(work, chans))
    else:
        channels = [work(c) for c in chans]

    return {
        "id": str(panel.get("id") or "extra"),
        "name": str(panel.get("name") or "EXTRA"),
        "icon": str(panel.get("icon") or "⚡"),
        "base_url": base_url,
        "player_base": player_base,
        "healthy": healthy,
        "resolved": sum(1 for c in channels if c["resolved"]),
        "fresh": sum(1 for c in channels if c["fresh"]),
        "total": len(channels),
        "channels": channels,
    }


def _build(fetch: Fetcher | None, now: datetime | None, write: bool) -> dict[str, Any]:
    cfg = load_config()
    settings = cfg.get("settings") or {}
    timeout = float(settings.get("request_timeout_seconds", 8))
    max_workers = int(settings.get("max_workers", 10))
    keep_hours: float | None = float(settings.get("keep_resolved_hours", 6))
    if fetch is None:
        keep_hours = None  # çevrimdışı: eldeki son çözüm süresiz korunur
    headers = dict(DEFAULT_HEADERS)
    headers.update(settings.get("headers") or {})

    utc_now = _utc(now)
    previous = load_output()
    prev_panels = {p.get("id"): p for p in previous.get("panels", [])}

    panels = []
    for panel in cfg.get("panels") or []:
        if panel.get("enabled", True) is False:
            continue
        panels.append(resolve_panel(panel, prev_panels.get(panel.get("id")), fetch, headers,
                                    timeout, utc_now, keep_hours, max_workers))

    data = {
        "updated_at": utc_now.isoformat(timespec="seconds") if fetch is not None
        else (previous.get("updated_at") or utc_now.isoformat(timespec="seconds")),
        "source": EXTRA_SOURCE,
        "total": sum(len(p["channels"]) for p in panels),
        "panels": panels,
    }
    if write:
        write_output(data)
    return data


def refresh(now: datetime | None = None, fetch: Fetcher | None = None, write: bool = True) -> dict[str, Any]:
    """Ağ üzerinden tüm panelleri çözümler ve output/extra_channels.json'a yazar."""
    return _build(fetch or _http_get, now, write)


def load_or_build(now: datetime | None = None) -> dict[str, Any]:
    """Ağ kullanmadan: yapılandırma + son çıktıdaki çözümlerden listeyi üretir."""
    return _build(None, now, write=False)


def flatten(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in (data or {}).get("panels", []):
        out.extend(p.get("channels", []))
    return out


def summary(data: dict[str, Any]) -> str:
    parts = []
    for p in data.get("panels", []):
        state = {True: "OK", False: "DOWN", None: "offline"}.get(p.get("healthy"), "?")
        player = f" · player {p['player_base']}" if p.get("player_base") else ""
        parts.append(f"{p['name']}: {p.get('resolved', 0)}/{p.get('total', 0)} m3u8 "
                     f"({p.get('fresh', 0)} taze) · {p.get('base_url') or '—'}{player} [{state}]")
    return " | ".join(parts) if parts else "ekstra panel yok"
