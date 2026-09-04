"""Çıktı üreticileri: JSON, Markdown ve kendi kendine yeten HTML paneli."""
from __future__ import annotations

import json
import os
from datetime import datetime
from html import escape
from typing import Any

from . import config
from .models import Match

OUTPUT = config.OUTPUT_DIR


def write_json_data(matches: list[Match], categorized: dict[str, Any], site: dict[str, Any],
                    channels_data: dict[str, Any] | None = None) -> str:
    """Tüm maçları ve kategorize edilmiş yapıyı JSON olarak yazar."""
    os.makedirs(OUTPUT, exist_ok=True)
    payload = {
        "site": site,
        "categories": categorized,
        # bireysel maç listesi (izleyici bağlantıları dahil)
        "matches": [m.to_dict() for m in matches],
        "channels": channels_data or {},
    }
    path = OUTPUT / "matches.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    # Sadece canlı maçlar
    with open(OUTPUT / "live_matches.json", "w", encoding="utf-8") as fh:
        json.dump({"site": site, "live": categorized["live"]}, fh, ensure_ascii=False, indent=2)
    # Günün maçları
    with open(OUTPUT / "today_matches.json", "w", encoding="utf-8") as fh:
        json.dump({"site": site, "date": categorized["meta"]["date"], "matches": payload["matches"]},
                  fh, ensure_ascii=False, indent=2)
    # 7/24 kanallar ayrı dosya
    with open(OUTPUT / "channels.json", "w", encoding="utf-8") as fh:
        json.dump({"site": site, "channels": channels_data or {}}, fh, ensure_ascii=False, indent=2)
    return str(path)


def write_markdown(categorized: dict[str, Any], site: dict[str, Any],
                   channels_data: dict[str, Any] | None = None) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    addr = site.get("current_address") or "—"
    lines = [
        "# ⚽ Fixbet TV — Günün Maçları",
        "",
        f"> **Güncel adres:** {addr}  \n> **Güncellenme:** {now}  \n> **Toplam maç:** {categorized['counts']['total']}  |  "
        f"**Canlı:** {categorized['counts']['live']}  |  **Yaklaşan:** {categorized['counts']['upcoming']}",
        "",
    ]

    def block(title: str, items: list[dict]) -> None:
        if not items:
            return
        lines.append(f"## {title}")
        lines.append("")
        for m in items:
            emoji = "🔴" if m["status"] == "live" else ("⏰" if m["status"] == "upcoming" else "✅")
            mod = " ★ **Günün Maçı**" if m.get("is_match_of_day") else ""
            url = m.get("url") or ""
            link = f"<{url}>" if url else ""
            lines.append(f"- {emoji} **{m['home']} vs {m['away']}** — `{m['time']}` | {m['league']}"
                         f"{mod} {link}")
        lines.append("")

    block("🔴 CANLI", categorized["live"])
    block("⏰ YAKLAŞAN", categorized["upcoming"])
    block("✅ BİTTİ", categorized["finished"])
    block("⭐ GÜNÜN MAÇI", categorized["match_of_the_day"])

    # Lige göre
    lines.append("---")
    lines.append("## 🏆 Lig Bazlı")
    lines.append("")
    for league, group in categorized["by_league"].items():
        lines.append(f"### {league}")
        for m in group:
            emoji = "🔴" if m["status"] == "live" else "⏰"
            lines.append(f"- {emoji} {m['home']} vs {m['away']} — {m['time']}")
        lines.append("")

    # 7/24 kanallar
    if channels_data and channels_data.get("channels"):
        lines.append("---")
        lines.append(f"## 📺 7/24 KANALLAR ({channels_data.get('total', len(channels_data['channels']))})")
        lines.append("")
        for brand, group in channels_data["by_brand"].items():
            lines.append(f"### {brand}")
            for ch in group:
                url = ch.get("url") or ""
                link = f" <{url}>" if url else ""
                lines.append(f"- **{ch['name']}** — `{ch['status']}`{link}")
            lines.append("")

    path = OUTPUT / "matches.md"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return str(path)


def write_html(categorized: dict[str, Any], site: dict[str, Any],
               channels_data: dict[str, Any] | None = None) -> str:
    """Kendi kendine yeterli (inline CSS/JS) HTML paneli üretir."""
    now = datetime.now()
    addr = site.get("current_address") or "—"
    c = categorized["counts"]

    def item(m: dict) -> str:
        cls = {"live": "live", "started": "live", "upcoming": "up", "finished": "done"}.get(m["status"], "up")
        badge = {"live": "CANLI", "started": "CANLI", "upcoming": "YAKLAŞAN", "finished": "BİTTİ"}.get(m["status"], "")
        status_color = {"live": "#e74c3c", "upcoming": "#2e86de", "finished": "#7f8c8d"}.get(m["status"], "#2e86de")
        mod = '<span class="mod">★ GÜNÜN MAÇI</span>' if m.get("is_match_of_day") else ""
        url = m.get("url") or ""
        link = f'<a class="watch" href="{escape(url)}" target="_blank">▶ izle</a>' if url else ""
        logos = ""
        if m.get("logo_home") or m.get("logo_away"):
            logos = (f'<span class="lg">{m.get("logo_home","")}<img src="{escape(m.get("logo_home") or "")}"></span>'
                     if m.get("logo_home") else "")
        return (
            f'<div class="row {cls}"><span class="time">{escape(m["time"] or "--:--")}</span>'
            f'<span class="teams"><b>{escape(m["home"])}</b> vs <b>{escape(m["away"])}</b></span>'
            f'<span class="lg">{escape(m.get("league") or "")}</span>'
            f'<span class="st" style="color:{status_color}">{badge}</span>{mod}{link}</div>'
        )

    def section(title: str, items: list[dict], accent: str = "#2e86de") -> str:
        if not items:
            return ""
        head = f'<h3 style="color:{accent}">{title} <span>({len(items)})</span></h3>'
        body = "".join(item(m) for m in items)
        return head + body

    sport_sections = "".join(
        section(f"🏆 {escape(sport)}", group, "#8e44ad")
        for sport, group in categorized["by_sport"].items()
    )

    league_html = "".join(
        f'<details><summary>{escape(league)} ({len(group)})</summary>'
        + "".join(item(m) for m in group) + "</details>"
        for league, group in categorized["by_league"].items()
    )

    # 7/24 kanallar bölümü
    channels_html = ""
    if channels_data and channels_data.get("channels"):
        total = channels_data.get("total", len(channels_data["channels"]))
        brand_blocks = ""
        for brand, group in channels_data["by_brand"].items():
            rows = "".join(
                f'<div class="row ch"><span class="badge">{escape(ch["status"])}</span>'
                f'<span class="teams">{escape(ch["name"])}</span>'
                + (f'<a class="watch" href="{escape(ch["url"])}" target="_blank">▶ izle</a>' if ch.get("url") else "")
                + "</div>"
                for ch in group
            )
            brand_blocks += (
                f'<details open><summary>{escape(brand)} ({len(group)})</summary>{rows}</details>'
            )
        channels_html = (
            f'<h3 style="color:#16a085">📺 7/24 KANALLAR <span>({total})</span></h3>'
            + brand_blocks
        )

    html = f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fixbet TV — Güncel Maçlar</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f1420;color:#e6e9f0;padding:20px}}
.top{{background:linear-gradient(135deg,#1e2a3a,#131a27);border:1px solid #2a3648;border-radius:14px;padding:18px 22px;margin-bottom:18px}}
.top h1{{font-size:20px;color:#fff}}
.top .meta{{color:#9aa7bd;font-size:13px;margin-top:6px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}}
.card{{flex:1;min-width:120px;background:#182131;border:1px solid #2a3648;border-radius:12px;padding:14px;text-align:center}}
.card .n{{font-size:26px;font-weight:700}} .card .l{{color:#9aa7bd;font-size:12px;text-transform:uppercase}}
.live .n{{color:#e74c3c}} .up .n{{color:#2e86de}} .done .n{{color:#27ae60}} .modn .n{{color:#f1c40f}}
h3{{margin:22px 0 10px;font-size:15px}} h3 span{{color:#9aa7bd;font-weight:400}}
.row{{display:flex;align-items:center;gap:10px;background:#161f2e;border:1px solid #26324a;border-radius:9px;padding:9px 12px;margin-bottom:7px;font-size:13.5px;flex-wrap:wrap}}
.row .time{{width:44px;color:#9aa7bd;font-weight:600}}
.row .teams{{flex:1;min-width:150px}} .row .lg{{color:#7f8ea6;font-size:12px}}
.st{{font-weight:700;font-size:11px;padding:2px 7px;border-radius:20px;border:1px solid currentColor}}
.mod{{background:#f1c40f;color:#1a1a1a;font-size:10.5px;padding:2px 7px;border-radius:20px;font-weight:700}}
.watch{{color:#2ecc71;text-decoration:none;font-weight:600;font-size:12px;border:1px solid #2ecc71;padding:3px 9px;border-radius:6px}}
.watch:hover{{background:#2ecc71;color:#0f1420}}
.row.live{{border-color:#e74c3c;box-shadow:0 0 0 1px #e74c3c40}}
.row.done{{opacity:.55}}
.row.ch .badge{{background:#16a085;color:#fff;font-size:10px;padding:2px 8px;border-radius:20px;font-weight:700}}
details{{background:#161f2e;border:1px solid #26324a;border-radius:9px;padding:8px 12px;margin-bottom:7px}}
details summary{{cursor:pointer;font-weight:600;color:#cfe}} details .row{{margin-bottom:5px}}
.gec{{color:#9aa7bd;font-size:12px}}
</style></head><body>
<div class="top">
  <h1>⚽ Fixbet TV — Güncel Site &amp; Günün Maçları</h1>
  <div class="meta">
    <b>Güncel adres:</b> <a href="{escape(addr)}" style="color:#2ecc71">{escape(addr)}</a><br>
    <b>Güncellenme:</b> {now.strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp; <b>Ayna durumu:</b> {escape(str(site.get('state')))}
    {f'<br><b>Çalışan aynalar:</b> ' + escape(', '.join(site.get('active_mirrors') or [])) if site.get('active_mirrors') else ''}
  </div>
</div>
<div class="cards">
  <div class="card live"><div class="n">{c['live']}</div><div class="l">Canlı</div></div>
  <div class="card up"><div class="n">{c['upcoming']}</div><div class="l">Yaklaşan</div></div>
  <div class="card done"><div class="n">{c['finished']}</div><div class="l">Bitti</div></div>
  <div class="card modn"><div class="n">{c['match_of_day']}</div><div class="l">Günün Maçı</div></div>
  <div class="card"><div class="n">{c['total']}</div><div class="l">Toplam</div></div>
</div>
{section('🔴 CANLI YAYINLAR', categorized['live'], '#e74c3c')}
{section('⏰ BU GÜN YAKLAŞAN', categorized['upcoming'])}
{section('⭐ GÜNÜN MAÇI', categorized['match_of_the_day'], '#f1c40f')}
{section('✅ BİTTİ', categorized['finished'], '#27ae60')}
<h3 style="color:#8e44ad">🏆 Spor Kategorileri</h3>{sport_sections}
<h3>🏆 Lig Bazlı</h3>{league_html}
{channels_html}
<p class="gec" style="margin-top:18px">fixbet-bot · otomatik güncelleme · {now.strftime('%H:%M')}</p>
</body></html>"""

    path = OUTPUT / "report.html"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return str(path)
