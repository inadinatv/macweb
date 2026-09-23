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
from zoneinfo import ZoneInfo

from . import channels, config, extras, scraper, standings, scores
from .models import Match
from .match_state import STATUS_LABELS, STATUS_LOOKUP, display_score, score_pair

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


def score_sync_payload() -> dict[str, Any]:
    """İstemci tarafı canlı skor senkronizasyonu için yapılandırma.

    Sayfa, botun kalıcı snapshot'ını beklemeden ESPN'in herkese açık
    scoreboard API'sini doğrudan okuyarak aktif maçları ~10 saniyede bir tazeler.
    Burada yalnızca scores.yml'deki gerçek lig/takım eşleşme tablosu gömülür;
    sayfa kendi başına hiçbir skor UYDURMAZ, sadece kaynaktan okur.
    """
    try:
        cfg = scores.load_config()
    except Exception:  # noqa: BLE001 - yapılandırma okunamazsa senkron kapalı kalır
        return {"enabled": False, "leagues": [], "aliases": {}, "toleranceMinutes": 45}
    leagues = [{"name": l.get("name") or "", "league": l.get("name") or "",
                "sport": l.get("sport") or "", "path": l.get("path") or ""}
               for l in cfg.get("leagues", []) if l.get("path")]
    return {
        "enabled": bool(cfg.get("enabled", False)) and bool(leagues),
        "leagues": leagues,
        "aliases": cfg.get("team_aliases", {}) or {},
        "toleranceMinutes": int(cfg.get("max_start_difference_minutes", 45)),
    }


def matches_payload(matches: list[Match], channel_list: list[dict[str, Any]],
                    date: str) -> list[dict[str, Any]]:
    """Maçları sayfanın kullandığı sade JSON biçimine çevirir (gerçek veri)."""
    names_by_id: dict[str, str] = {}
    for ch in channel_list:
        cid = ch.get("channel_id") or ""
        if cid:
            names_by_id[cid] = ch.get("name") or cid.upper()
    base = scraper.current_base_url()
    tz = ZoneInfo(config.load_settings().get("bot", {}).get("timezone", "Europe/Istanbul"))
    out: list[dict[str, Any]] = []
    for m in matches:
        stream = m.url or (f"{base}/channel.html?id={m.channel_id or m.match_id}" if base else "")
        cid = m.channel_id or m.match_id
        starts_at = m.starts_at
        if not starts_at:
            try:
                starts_at = datetime.strptime(f"{date} {m.time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz).isoformat()
            except ValueError:
                starts_at = ""
        home_score, away_score = score_pair(m.score_home, m.score_away)
        out.append({
            "id": m.match_id,
            "home": m.home,
            "away": m.away,
            "league": m.league,
            "time": m.time,
            "sport": m.sport or "Spor",
            "status": m.status,
            "statusSource": m.status_source,
            "rawStatus": m.raw_status,
            "statusClock": m.status_clock or "",
            "scoreHome": home_score,
            "scoreAway": away_score,
            "scoreSource": m.score_source,
            "scoreUpdatedAt": m.score_updated_at,
            "eventId": m.event_id,
            "startsAt": starts_at,
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
        cls = "live" if m.status in ("live", "halftime", "started") else ("up" if m.status == "upcoming" else "done")
        mod = ' ★ Günün Maçı' if m.is_match_of_day else ""
        return (
            f'<li class="match-row {cls}">'
            f'<b>{escape(m.time or "--:--")}</b> '
            f'{escape(m.home)} {escape(display_score(m) or "-")} {escape(m.away)} '
            f'<span class="match-league">({escape(m.league)})</span>'
            f'<span class="match-badge {cls}">{_badge_label(m.status)}{escape(mod)}</span>'
            f'</li>'
        )

    if not matches:
        return '<p class="empty-msg">Bugün için maç listesi alınamadı.</p>'
    items = sorted(matches, key=lambda x: (x.time or "99:99"))
    return '<ul class="match-list">' + "".join(card(m) for m in items) + "</ul>"


def _badge_label(status: str) -> str:
    return STATUS_LABELS.get(status, "YAKLAŞAN")


def _js(value: Any) -> str:
    """JSON'u <script> içine güvenle gömer (</script> kaçışı ile)."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def extra_payload(extra_data: dict[str, Any] | None) -> dict[str, Any]:
    """Ekstra panelleri (m3u8 veya panel oynatıcısı) sade JSON'a indirger."""
    panels: list[dict[str, Any]] = []
    for p in (extra_data or {}).get("panels", []):
        chans = []
        for c in p.get("channels", []):
            sources = [dict(s, type=s.get("type") or "hls", label=s.get("label") or "")
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
                "page_url": c.get("page_url") or "",
                "referrer": c.get("referrer") or "",
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


def standings_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    """Puan durumunu sayfanın beklediği sade JSON'a indirger.

    Yalnızca tablonun göstereceği alanlar bırakılır; sayısal değerler kaynaktan
    geldiği gibi aktarılır (hiçbir değer burada hesaplanmaz/uydurulmaz).
    """
    keep = ("rank", "team", "abbr", "logo", "played", "wins", "draws", "losses",
            "goalsFor", "goalsAgainst", "diff", "points", "note", "zone", "zoneLabel")
    leagues = []
    for lg in (data or {}).get("leagues", []):
        rows = [{k: r.get(k) for k in keep} for r in lg.get("rows", []) if isinstance(r, dict) and r.get("team")]
        if not rows:
            continue
        leagues.append({"id": lg.get("id") or "", "name": lg.get("name") or "",
                        "sport": lg.get("sport") or "Futbol", "season": lg.get("season") or "",
                        "updated_at": lg.get("updated_at") or "", "rows": rows})
    return {"source": (data or {}).get("source") or "", "generated_at": (data or {}).get("generated_at") or "",
            "leagues": leagues}


# Sıra bölgesi renkleri (noscript tablosu + açıklama satırı) — arayüzdeki CSS ile aynı tonlar.
_ZONE_COLORS = {
    "champions": ("#ffcc33", "rgba(255,204,51,0.14)"),
    "europa": ("#7dffc0", "rgba(0,255,136,0.12)"),
    "qualify": ("#7dffc0", "rgba(0,255,136,0.12)"),
    "relegation": ("#ff9ba7", "rgba(255,45,122,0.14)"),
    "relegate": ("#ff9ba7", "rgba(255,45,122,0.14)"),
}
_ZONE_FALLBACK_LABELS = {"champions": "Şampiyonlar Ligi", "europa": "Avrupa kupaları",
                         "qualify": "Avrupa kupaları", "relegation": "Küme düşme hattı",
                         "relegate": "Küme düşme hattı"}


def zone_legend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ardışık aynı bölgeleri birleştirip ``(kind, aralık, etiket)`` listesi üretir.

    Örnek: 1 → Şampiyonlar Ligi, 2-3 → Avrupa kupaları, 16-18 → Küme düşme hattı.
    Bölgesiz satırlar atlanır; hiçbir sayısal değer üretilmez.
    """
    groups: list[dict[str, Any]] = []
    for r in rows:
        zone = str(r.get("zone") or "").strip()
        if not zone:
            continue
        rank = r.get("rank")
        label = str(r.get("zoneLabel") or _ZONE_FALLBACK_LABELS.get(zone, ""))
        if groups and groups[-1]["zone"] == zone and groups[-1]["label"] == label:
            groups[-1]["to"] = rank if isinstance(rank, int) else groups[-1]["to"]
            continue
        groups.append({"zone": zone, "label": label,
                       "from": rank if isinstance(rank, int) else None,
                       "to": rank if isinstance(rank, int) else None})
    return groups


def _zone_range_text(group: dict[str, Any]) -> str:
    first, last = group.get("from"), group.get("to")
    if isinstance(first, int) and isinstance(last, int) and first != last:
        return f"{first}-{last}"
    return str(first if first is not None else "-")


def _zone_legend_html(rows: list[dict[str, Any]]) -> str:
    """Bölge açıklaması: hangi sıralar Avrupa hattı, hangi sıralar küme düşme hattı."""
    groups = zone_legend(rows)
    if not groups:
        return ""
    items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;margin:0 10px 4px 0;">'
        f'<i style="width:10px;height:10px;border-radius:3px;display:inline-block;'
        f'background:{_ZONE_COLORS.get(g["zone"], ("#fff", "#fff"))[0]};"></i>'
        f'<b style="color:{_ZONE_COLORS.get(g["zone"], ("#ece7f8", "#fff"))[0]};">{escape(_zone_range_text(g))}</b>'
        f'<span style="opacity:.8;">{escape(g["label"])}</span></span>'
        for g in groups)
    return (f'<p style="margin:6px 0 0;font-size:12px;color:#c9c0de;display:flex;flex-wrap:wrap;">{items}</p>')


def _noscript_standings_row(r: dict[str, Any]) -> str:
    """Tek satır: bölge varsa sıra hücresi renkli şerit + satır zemini ile işaretlenir."""
    zone = str(r.get("zone") or "").strip()
    color, tint = _ZONE_COLORS.get(zone, ("", ""))
    label = str(r.get("zoneLabel") or _ZONE_FALLBACK_LABELS.get(zone, ""))
    cell = "padding:4px 6px;border-bottom:1px solid rgba(255,255,255,0.07);"
    rank_style = cell + (f"color:{color};font-weight:800;box-shadow:inset 3px 0 0 {color};" if color else "")
    row_style = f' style="background:{tint};"' if tint else ""
    team_title = f' title="{escape(label)}"' if label else ""

    def num(key: str) -> str:
        value = r.get(key)
        return escape(str(value if value is not None else "-"))

    # ▲ yükseliş (Avrupa) hattı, ▼ küme düşme hattı — arayüzdeki CSS ::after ile aynı işaret
    arrow = {"champions": "▲", "europa": "▲", "qualify": "▲",
             "relegation": "▼", "relegate": "▼"}.get(zone, "")
    arrow_html = f' <span style="color:{color};">{arrow}</span>' if arrow and color else ""
    return (
        f'<tr{row_style}>'
        f'<td style="{rank_style}">{escape(str(r.get("rank") or "-"))}</td>'
        f'<td style="{cell}"{team_title}>{escape(str(r.get("team") or ""))}{arrow_html}</td>'
        f'<td style="{cell}text-align:right;">{num("played")}</td>'
        f'<td style="{cell}text-align:right;">{num("wins")}</td>'
        f'<td style="{cell}text-align:right;">{num("draws")}</td>'
        f'<td style="{cell}text-align:right;">{num("losses")}</td>'
        f'<td style="{cell}text-align:right;">{num("diff")}</td>'
        f'<td style="{cell}text-align:right;"><b>{num("points")}</b></td>'
        f'</tr>')


def _standings_groups_html(data: dict[str, Any] | None) -> str:
    """Puan durumunu JS'siz ortam (noscript) için okunur HTML tablosuna çevirir."""
    payload = standings_payload(data)
    blocks: list[str] = []
    for lg in payload["leagues"]:
        rows = "".join(_noscript_standings_row(r) for r in lg["rows"])
        blocks.append(
            f'<h3 style="margin:14px 0 6px;">🏆 {escape(lg["name"])} — PUAN DURUMU</h3>'
            '<table style="border-collapse:collapse;width:100%;font-size:13px;color:#f4efff;">'
            '<thead><tr style="color:#ff2d7a;">'
            + "".join(f'<th style="padding:4px 6px;text-align:{align};border-bottom:1px solid rgba(255,255,255,0.12);">{h}</th>'
                      for h, align in (("SIRA", "left"), ("TAKIM", "left"), ("O", "right"), ("G", "right"),
                                       ("B", "right"), ("M", "right"), ("AV", "right"), ("P", "right")))
            + f'</tr></thead><tbody>{rows}</tbody></table>' + _zone_legend_html(lg["rows"]))
    if not blocks:
        return ('<h3 style="margin:14px 0 6px;">🏆 PUAN DURUMU</h3>'
                '<p class="empty-msg">Puan durumu verisi henüz alınamadı.</p>')
    return "".join(blocks)


def build_index_html(matches: list[Match], channels_data: dict[str, Any] | None = None,
                     now: datetime | None = None, extra_data: dict[str, Any] | None = None,
                     standings_data: dict[str, Any] | None = None) -> str | None:
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
    if standings_data is None:
        standings_data = standings.load_or_build(now)

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
        "{{SCORE_SYNC_JSON}}": _js(score_sync_payload()),
        "{{MATCH_STATUS_JSON}}": _js({"aliases": STATUS_LOOKUP, "labels": STATUS_LABELS,
                                      "graceMinutes": int(config.load_settings().get("categorize", {}).get("live_grace_minutes", 0))}),
        "{{MATCH_TIMEZONE_JSON}}": _js(config.load_settings().get("bot", {}).get("timezone", "Europe/Istanbul")),
        "{{MATCHES_JSON}}": _js(matches_payload(matches, channel_list, now.strftime("%Y-%m-%d"))),
        "{{MATCHES_HTML}}": _match_groups_html(matches),
        "{{PLAYBACK_JSON}}": _js({"proxy_url": config.load_settings().get("playback", {}).get("proxy_url", "")}),
        "{{EXTRA_SOURCE}}": extras.EXTRA_SOURCE,
        "{{EXTRA_JSON}}": _js(extra_payload(extra_data)),
        "{{EXTRA_HTML}}": _extra_groups_html(extra_data),
        "{{STANDINGS_SOURCE}}": standings.STANDINGS_SOURCE,
        "{{STANDINGS_JSON}}": _js(standings_payload(standings_data)),
        "{{STANDINGS_HTML}}": _standings_groups_html(standings_data),
    }
    for token, value in replacements.items():
        html = html.replace(token, value)

    os.makedirs(INDEX_OUT.parent, exist_ok=True)
    INDEX_OUT.write_text(html, encoding="utf-8")
    return str(INDEX_OUT)
