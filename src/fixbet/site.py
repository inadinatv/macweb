"""GitHub Pages için repo köküne index.html üretir.

Kullanıcının mevcut İNADİNA TV şablonunu (src/fixbet/templates/index.html)
kullanır ve:
  * Ölü/sabit alan adı yerine GÜNCEL site adresini (config/current_site.yml)
    bağlar,
  * 7/24 kanal listesini güncel adresle üretir,
  * Günün maçlarını (canlı / yaklaşan / günün maçı / lig bazlı) gömer.

Böylece GitHub Pages'te gösterilen index.html git'e push edildiği için
her zaman güncel adresi ve maçları gösterir.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from html import escape
from typing import Any

from . import channels, config, scraper
from .models import Match

REPO_ROOT = config.ROOT
TEMPLATE = config.ROOT / "src" / "fixbet" / "templates" / "index.html"
INDEX_OUT = REPO_ROOT / "index.html"


def _match_groups_html(matches: list[Match]) -> str:
    """Maçları canlı/yaklaşan/günün maçı + lig bazında, zengin ve kategorize HTML'e çevirir.

    Her maç kartı oynatıcıya bağlanır (bütünleşik), takım logoları gösterilir,
    ve istemci (client) tarafı yeniden canlı durumu hesaplayabilmesi için
    data-time / data-status / data-stream öznitelikleri taşır.
    """
    def logo_img(url: str | None) -> str:
        if not url:
            return ""
        return (f'<span class="team-logo"><img loading="lazy" src="{escape(url)}" '
                f'alt="" onerror="this.style.display=\'none\'"></span>')

    def card(m: Match) -> str:
        cls = "live" if m.status in ("live", "started") else ("up" if m.status == "upcoming" else "done")
        # Client, saate göre yeniden hesaplasın diye gerçek durumu da ekle
        mod = '<span class="match-badge mod" data-is-mod="1">★ GÜNÜN MAÇI</span>' if m.is_match_of_day else ""
        stream = m.url or ""
        watch = (
            f'<button class="match-watch" data-stream="{escape(stream)}" title="{escape(m.home)} vs {escape(m.away)}">'
            f'▶ İZLE</button>' if stream else ""
        )
        # İlk 5 canlı/başlayan maça otomatik canlı işareti (badge JS ile güncellenir)
        return (
            f'<div class="match-card {cls}" data-time="{escape(m.time or "")}" data-status="{m.status}" '
            f'data-league="{escape(m.league)}">'
            f'<span class="match-time">{escape(m.time or "--:--")}</span>'
            f'<span class="match-teams">{logo_img(m.logo_home)}'
            f'<span class="mt-name"><b>{escape(m.home)}</b><span class="mt-vs">vs</span><b>{escape(m.away)}</b></span>'
            f'{logo_img(m.logo_away)}'
            f'<span class="match-league">{escape(m.league)}</span></span>'
            f'<span class="match-badge {cls}" data-badge>{_badge_label(m.status)}</span>{mod}{watch}'
            f'</div>'
        )

    def group(title: str, items: list[Match], accent: str, gkey: str = "") -> str:
        if not items:
            return ""
        gid = f' data-group="{gkey}"' if gkey else ""
        title_html = (f'<div class="match-group-title" style="color:{accent}">'
                      f'<span>{title} <span class="mcount">({len(items)})</span></span></div>')
        rows = "".join(card(m) for m in sorted(items, key=lambda x: (x.time or "99:99")))
        return f'<div class="match-group"{gid}>{title_html}<div class="match-list">{rows}</div></div>'

    live = [m for m in matches if m.status in ("live", "started")]
    upcoming = [m for m in matches if m.status == "upcoming"]
    done = [m for m in matches if m.status == "finished"]
    mod = [m for m in matches if m.is_match_of_day]
    sport_groups: dict[str, list[Match]] = {}
    for m in matches:
        sport_groups.setdefault(m.sport or "Spor", []).append(m)

    # Lig bazlı
    by_league: dict[str, list[Match]] = {}
    for m in matches:
        by_league.setdefault(m.league or "Diğer", []).append(m)
    league_html = "".join(group(f"🏆 {escape(lg)}", grp, "#ffcc33") for lg, grp in by_league.items())

    # Filtre sekmeleri (client tarafı grupları gösterir/gizler)
    filter_bar = (
        '<div class="match-filters" id="matchFilters">'
        '<button class="mf-btn active" data-mf="all">Tümü</button>'
        '<button class="mf-btn" data-mf="live">🔴 Canlı</button>'
        '<button class="mf-btn" data-mf="mod">⭐ Günün Maçı</button>'
        '<button class="mf-btn" data-mf="upcoming">⏰ Yaklaşan</button>'
        '<button class="mf-btn" data-mf="done">✅ Bitti</button>'
        '</div>'
    )

    parts = [
        group("🔴 CANLI", live, "#ff2d7a", "live"),
        group("⭐ GÜNÜN MAÇI", mod, "#ffcc33", "mod"),
        group("⏰ YAKLAŞAN", upcoming, "#00eaff", "upcoming"),
        group("✅ BİTTİ", done, "#8d84aa", "done"),
        group("🏆 LİG BAZLI", matches, "#ffcc33"),
    ]
    if not matches:
        parts.append('<div class="empty-msg">Bugün için maç listesi alınamadı. Bot çalıştığında burada güncellenir.</div>')
    return filter_bar + "\n" + "\n".join(p for p in parts if p)


def _badge_label(status: str) -> str:
    if status in ("live", "started"):
        return "CANLI"
    if status == "upcoming":
        return "YAKLAŞAN"
    return "BİTTİ"


def _channels_js(channel_list: list[dict[str, Any]]) -> tuple[str, str]:
    """Kanal listesinden streamLinks + channelNames JS dizilerini üretir."""
    links = [ch.get("url") or "" for ch in channel_list]
    names = [ch.get("name", "") for ch in channel_list]
    return json.dumps(links, ensure_ascii=False), json.dumps(names, ensure_ascii=False)


def build_index_html(matches: list[Match], channels_data: dict[str, Any] | None = None) -> str | None:
    """index.html üretir ve repo köküne yazar. Şablon yoksa None döner."""
    if not TEMPLATE.exists():
        return None

    base = scraper.current_base_url()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if channels_data is None:
        channels_data = channels.categorize(channels.fetch_channels())
    channel_list = channels_data.get("channels", [])
    stream_links, channel_names = _channels_js(channel_list)

    matches_html = _match_groups_html(matches)
    site_addr = base or "—"

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("{{SITE_ADDR}}", escape(site_addr))
    html = html.replace("{{UPDATED_AT}}", escape(now))
    html = html.replace("{{STREAM_LINKS}}", stream_links)
    html = html.replace("{{CHANNEL_NAMES}}", channel_names)
    html = html.replace("{{MATCHES_HTML}}", matches_html)

    os.makedirs(INDEX_OUT.parent, exist_ok=True)
    INDEX_OUT.write_text(html, encoding="utf-8")
    return str(INDEX_OUT)
