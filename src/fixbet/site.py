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
    """Maçları canlı/yaklaşan/günün maçı + lig bazında HTML'e çevirir."""

    def card(m: Match) -> str:
        cls = "live" if m.status in ("live", "started") else ("up" if m.status == "upcoming" else "done")
        badge = "CANLI" if m.status in ("live", "started") else ("YAKLAŞAN" if m.status == "upcoming" else "BİTTİ")
        mod = '<span class="match-badge mod">★ GÜNÜN MAÇI</span>' if m.is_match_of_day else ""
        watch = f'<a class="match-watch" href="{escape(m.url)}" target="_blank">▶ İZLE</a>' if m.url else ""
        return (
            f'<div class="match-card {cls}">'
            f'<span class="match-time">{escape(m.time or "--:--")}</span>'
            f'<span class="match-teams">{escape(m.home)} <b>vs</b> {escape(m.away)}'
            f'<span class="match-league">{escape(m.league)}</span></span>'
            f'<span class="match-badge {cls}">{badge}</span>{mod}{watch}'
            f'</div>'
        )

    def group(title: str, items: list[Match], accent: str) -> str:
        if not items:
            return ""
        title_html = f'<div class="match-group-title" style="color:{accent}">{title} <span>({len(items)})</span></div>'
        rows = "".join(card(m) for m in sorted(items, key=lambda x: (x.time or "99:99")))
        return f'<div class="match-group">{title_html}<div class="match-list">{rows}</div></div>'

    live = [m for m in matches if m.status in ("live", "started")]
    upcoming = [m for m in matches if m.status == "upcoming"]
    done = [m for m in matches if m.status == "finished"]
    mod = [m for m in matches if m.is_match_of_day]

    # Lig bazlı
    by_league: dict[str, list[Match]] = {}
    for m in matches:
        by_league.setdefault(m.league or "Diğer", []).append(m)
    league_html = "".join(group(f"🏆 {escape(lg)}", grp, "#ffcc33") for lg, grp in by_league.items())

    parts = [
        group("🔴 CANLI", live, "#ff2d7a"),
        group("⭐ GÜNÜN MAÇI", mod, "#ffcc33"),
        group("⏰ YAKLAŞAN", upcoming, "#00eaff"),
        group("✅ BİTTİ", done, "#8d84aa"),
    ]
    if not matches:
        parts.append('<div class="empty-msg">Bugün için maç listesi alınamadı. Bot çalıştığında burada güncellenir.</div>')
    return "\n".join(p for p in parts if p) + "\n" + league_html


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
