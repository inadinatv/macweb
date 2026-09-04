"""index.html üretimi (GitHub Pages) testleri."""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fixbet import categorizer, parser
from fixbet import site

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "matches.php")


def _get_matches():
    with open(FIXTURE, encoding="utf-8") as fh:
        raw = fh.read()
    matches = parser.parse(raw)
    matches = categorizer.enrich(matches)
    return categorizer.classify(matches, datetime(2026, 9, 4, 20, 8))


def test_match_groups_html():
    matches = _get_matches()
    html = site._match_groups_html(matches)
    assert "CANLI" in html             # 20:00 maçları canlı
    assert "YAKLAŞAN" in html          # 22:00 yaklaşan
    assert "İstanbul Başakşehir" in html
    assert "Trendyol Süper Lig" in html
    print("OK: match_groups_html")


def test_template_markers():
    """Şablonun yer tutucuları tam olmalı."""
    tpl = site.TEMPLATE.read_text(encoding="utf-8")
    for tok in ("{{STREAM_LINKS}}", "{{CHANNEL_NAMES}}", "{{MATCHES_HTML}}",
                "{{SITE_ADDR}}", "{{UPDATED_AT}}"):
        assert tok in tpl, f"eksik yer tutucu: {tok}"
    # BOT_START/BOT_END blokları korunmuş olmalı
    assert "/*BOT_START*/" in tpl and "/*BOT_END*/" in tpl
    print("OK: template_markers")


def test_render_fills_markers():
    matches = _get_matches()
    html = site.TEMPLATE.read_text(encoding="utf-8")
    stream_links = '["https://x.com/channel.html?id=as"]'
    html = (html.replace("{{SITE_ADDR}}", "https://x.com")
                .replace("{{UPDATED_AT}}", "2026-09-04 21:00")
                .replace("{{STREAM_LINKS}}", stream_links)
                .replace("{{CHANNEL_NAMES}}", '["A SPOR"]')
                .replace("{{MATCHES_HTML}}", site._match_groups_html(matches)))
    assert "{{STREAM_LINKS}}" not in html
    assert "{{MATCHES_HTML}}" not in html
    assert "https://x.com" in html
    print("OK: render_fills_markers")


if __name__ == "__main__":
    test_match_groups_html()
    test_template_markers()
    test_render_fills_markers()
    print("\nSİTE TESTLERİ GEÇTİ ✅")
