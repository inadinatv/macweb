"""GitHub Pages için repo köküne index.html üretir.

Kullanıcının İNADİNA TV şablonunu (src/fixbet/templates/index.html) kullanır ve:
  * 7/24 kanal listesini güncel adresle üretir (ad, marka, ikon, durum),
  * günün maçlarını **gerçek kaynak verisinden** gömer (uydurma/sabit maç yok),
  * istemcinin taze veri çekebilmesi için output/today_matches.json yolunu verir.

Sayfa tasarımı tek yerden (şablon) yönetilir; ``python fixbet.py run`` her
çalıştığında index.html bu şablondan yeniden yazılır.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from html import escape
from typing import Any

from . import channels, config, extras, scraper
from .models import Match

REPO_ROOT = config.ROOT
TEMPLATE = config.ROOT / "src" / "fixbet" / "templates" / "index.html"
INDEX_OUT = REPO_ROOT / "index.html"
# İstemci tarafı tazeleme: GitHub Pages ile aynı kökten okunan gerçek veri dosyası
MATCHES_SOURCE = "output/today_matches.json"

# Kanal adı -> ikon (marka bazlı, görsel amaçlı)
_ICON_RULES: list[tuple[list[str], str]] = [
    (["bein", "beın"], "⚽"),
    (["s sport"], "🏀"),
    (["smartspor", "smart spor"], "🏟️"),
    (["tivibu"], "📺"),
    (["tabii", "tabıı"], "📡"),
    (["euro"], "🚴"),
    (["a spor"], "⚽"),
    (["trt"], "🇹🇷"),
    (["atv", "tv 8", "tv8"], "📺"),
]


def channel_icon(name: str) -> str:
    """Kanal adına uygun emoji simgesini üretir."""
    low = (name or "").lower().replace("ı", "i").replace("ş", "s")
    for keywords, icon in _ICON_RULES:
        if any(kw in low for kw in keywords):
            return icon
    return "📡"


def ordered_channels(channels_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Kanal listesini marka sırasına göre düzleştirir (gruplu, okunur sıra)."""
    if not channels_data:
        return []
    by_brand = channels_data.get("by_brand") or {}
    if by_brand:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for group in by_brand.values():
            for ch in group:
                cid = ch.get("channel_id") or ch.get("name") or ""
                if cid in seen:
                    continue
                seen.add(cid)
                out.append(ch)
        return out
    return list(channels_data.get("channels") or [])


def channel_payload(channel_list: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Şablondaki JS dizilerini üretir: bağlantı, ad, marka, ikon, durum."""
    links: list[str] = []
    names: list[str] = []
    brands: list[str] = []
    icons: list[str] = []
    statuses: list[str] = []
    for ch in channel_list:
        url = ch.get("url") or ""
        if not url:
            continue
        links.append(url)
        names.append(ch.get("name") or "")
        brands.append(ch.get("brand") or "Diğer")
        icons.append(channel_icon(ch.get("name") or ""))
        statuses.append(ch.get("status") or "7/24")
    return {"links": links, "names": names, "brands": brands, "icons": icons, "statuses": statuses}


_FOLD = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
                       "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"})


def fold_key(text: str) -> str:
    """Sayfadaki norm() ile birebir aynı anahtar biçimi (Türkçe harf katlaması)."""
    return str(text or "").lower().translate(_FOLD)


def live_window(settings: dict[str, Any] | None = None) -> dict[str, int]:
    """Spor bazlı canlı yayın penceresi (dakika) — istemci de aynı tabloyu kullanır."""
    settings = settings if settings is not None else config.load_settings()
    cat = settings.get("categorize", {}) or {}
    table: dict[str, int] = {"default": int(cat.get("live_window_minutes", 120))}
    for sport, minutes in (cat.get("live_window_by_sport") or {}).items():
        table[fold_key(sport)] = int(minutes)
    return table


def matches_payload(matches: list[Match], channel_list: list[dict[str, Any]],
                    date: str) -> list[dict[str, Any]]:
    """Maçları sayfanın kullandığı sade JSON biçimine çevirir (gerçek veri)."""
    names_by_id: dict[str, str] = {}
    for ch in channel_list:
        cid = ch.get("channel_id") or ""
        if cid:
            names_by_id[cid] = ch.get("name") or cid.upper()
    base = scraper.current_base_url()
    out: list[dict[str, Any]] = []
    for m in matches:
        stream = m.url or (f"{base}/channel.html?id={m.channel_id or m.match_id}" if base else "")
        cid = m.channel_id or m.match_id
        out.append({
            "id": m.match_id,
            "home": m.home,
            "away": m.away,
            "league": m.league,
            "time": m.time,
            "sport": m.sport or "Spor",
            "status": m.status,
            "isMod": bool(m.is_match_of_day),
            "channelId": cid,
            "channelName": names_by_id.get(cid, (cid or "").upper()),
            "streamUrl": stream,
            "logoHome": m.logo_home or "",
            "logoAway": m.logo_away or "",
            "date": date,
        })
    out.sort(key=lambda x: (x["time"] or "99:99"))
    return out


def _match_groups_html(matches: list[Match]) -> str:
    """Maçları JS'siz ortam (noscript) için okunur HTML listesine çevirir."""
    def card(m: Match) -> str:
        cls = "live" if m.status in ("live", "started") else ("up" if m.status == "upcoming" else "done")
        mod = ' ★ Günün Maçı' if m.is_match_of_day else ""
        return (
            f'<li class="match-row {cls}">'
            f'<b>{escape(m.time or "--:--")}</b> '
            f'{escape(m.home)} - {escape(m.away)} '
            f'<span class="match-league">({escape(m.league)})</span>'
            f'<span class="match-badge {cls}">{_badge_label(m.status)}{escape(mod)}</span>'
            f'</li>'
        )

    if not matches:
        return '<p class="empty-msg">Bugün için maç listesi alınamadı.</p>'
    items = sorted(matches, key=lambda x: (x.time or "99:99"))
    return '<ul class="match-list">' + "".join(card(m) for m in items) + "</ul>"


def _badge_label(status: str) -> str:
    if status in ("live", "started"):
        return "CANLI"
    if status == "upcoming":
        return "YAKLAŞAN"
    return "BİTTİ"


def _js(value: Any) -> str:
    """JSON'u <script> içine güvenle gömer (</script> kaçışı ile)."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def extra_payload(extra_data: dict[str, Any] | None) -> dict[str, Any]:
    """Ekstra panelleri (m3u8 kanallar) sayfanın beklediği sade JSON'a indirger."""
    panels: list[dict[str, Any]] = []
    for p in (extra_data or {}).get("panels", []):
        chans = []
        for c in p.get("channels", []):
            sources = [{"type": s.get("type") or "hls", "url": s.get("url") or "", "label": s.get("label") or ""}
                       for s in c.get("sources", []) if s.get("url")]
            if not sources:
                continue
            chans.append({
                "id": c.get("id") or f"{p.get('id')}:{c.get('slug')}",
                "slug": c.get("slug") or "",
                "name": c.get("name") or "",
                "icon": c.get("icon") or channel_icon(c.get("name") or ""),
                "panel_name": p.get("name") or p.get("id") or "EXTRA",
                "resolved": bool(c.get("resolved")),
                "sources": sources,
            })
        panels.append({"id": p.get("id") or "extra", "name": p.get("name") or "EXTRA",
                       "icon": p.get("icon") or "⚡", "channels": chans})
    return {"updated_at": (extra_data or {}).get("updated_at") or "", "panels": panels}


def _extra_groups_html(extra_data: dict[str, Any] | None) -> str:
    """Ekstra (m3u8) kanalları JS'siz ortam için düz bağlantı listesine çevirir."""
    blocks: list[str] = []
    for p in (extra_data or {}).get("panels", []):
        items = []
        for c in p.get("channels", []):
            first = next((s.get("url") for s in c.get("sources", []) if s.get("url")), "")
            if not first:
                continue
            items.append(f'<li><a href="{escape(first)}" target="_blank" rel="noopener">{escape(c.get("name") or "")}</a> '
                         f'<small>(m3u8)</small></li>')
        if items:
            blocks.append(f'<h3 style="margin:14px 0 6px;">⚡ {escape(p.get("name") or "EXTRA")}</h3>'
                          f'<ul class="match-list">{"".join(items)}</ul>')
    return "".join(blocks)


def build_index_html(matches: list[Match], channels_data: dict[str, Any] | None = None,
                     now: datetime | None = None, extra_data: dict[str, Any] | None = None) -> str | None:
    """index.html üretir ve repo köküne yazar. Şablon yoksa None döner."""
    if not TEMPLATE.exists():
        return None

    base = scraper.current_base_url()
    now = now or datetime.now()

    if channels_data is None:
        channels_data = channels.categorize(channels.fetch_channels())
    channel_list = ordered_channels(channels_data)
    payload = channel_payload(channel_list)
    if extra_data is None:
        extra_data = extras.load_or_build(now)

    html = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "{{SITE_ADDR}}": escape(base or ""),
        "{{UPDATED_AT}}": escape(now.strftime("%Y-%m-%d %H:%M")),
        "{{MATCHES_SOURCE}}": MATCHES_SOURCE,
        "{{STREAM_LINKS}}": _js(payload["links"]),
        "{{CHANNEL_NAMES}}": _js(payload["names"]),
        "{{CHANNEL_BRANDS}}": _js(payload["brands"]),
        "{{CHANNEL_ICONS}}": _js(payload["icons"]),
        "{{CHANNEL_STATUSES}}": _js(payload["statuses"]),
        "{{LIVE_WINDOW_JSON}}": _js(live_window()),
        "{{MATCHES_JSON}}": _js(matches_payload(matches, channel_list, now.strftime("%Y-%m-%d"))),
        "{{MATCHES_HTML}}": _match_groups_html(matches),
        "{{EXTRA_SOURCE}}": extras.EXTRA_SOURCE,
        "{{EXTRA_JSON}}": _js(extra_payload(extra_data)),
        "{{EXTRA_HTML}}": _extra_groups_html(extra_data),
    }
    for token, value in replacements.items():
        html = html.replace(token, value)

    os.makedirs(INDEX_OUT.parent, exist_ok=True)
    INDEX_OUT.write_text(html, encoding="utf-8")
    return str(INDEX_OUT)
