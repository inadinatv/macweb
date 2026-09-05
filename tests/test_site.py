"""index.html üretimi (GitHub Pages) testleri."""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fixbet import categorizer, channels, parser  # noqa: E402
from fixbet import site  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "matches.php")
HOME_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "home.html")


def _get_matches():
    with open(FIXTURE, encoding="utf-8") as fh:
        raw = fh.read()
    matches = parser.parse(raw)
    matches = categorizer.enrich(matches)
    return categorizer.classify(matches, datetime(2026, 9, 4, 20, 8))


def _get_channels():
    with open(HOME_FIXTURE, encoding="utf-8") as fh:
        html = fh.read()
    found = channels._parse_home(html)
    for ch in found:
        ch["url"] = f"https://fixbettv84.com/channel.html?id={ch['channel_id']}"
    return channels.categorize(found)


def test_template_markers():
    """Şablonun yer tutucuları tam olmalı."""
    tpl = site.TEMPLATE.read_text(encoding="utf-8")
    for tok in ("{{STREAM_LINKS}}", "{{CHANNEL_NAMES}}", "{{CHANNEL_BRANDS}}",
                "{{CHANNEL_ICONS}}", "{{CHANNEL_STATUSES}}", "{{MATCHES_JSON}}",
                "{{MATCHES_SOURCE}}", "{{LIVE_WINDOW_JSON}}", "{{MATCHES_HTML}}",
                "{{SITE_ADDR}}", "{{UPDATED_AT}}",
                "{{EXTRA_SOURCE}}", "{{EXTRA_JSON}}", "{{EXTRA_HTML}}"):
        assert tok in tpl, f"eksik yer tutucu: {tok}"
    assert "/*BOT_START*/" in tpl and "/*BOT_END*/" in tpl
    print("OK: template_markers")


def test_no_server_text_and_no_fake_matches():
    """'Sunucu:' yazısı ve uydurma maç listesi kaldırıldı."""
    tpl = site.TEMPLATE.read_text(encoding="utf-8")
    assert "Sunucu" not in tpl
    assert "CANLI MAÇLAR" not in tpl
    assert "liveMatchesData" not in tpl
    # tek gerçek maç sekmesi: günün maçları
    assert 'data-tab="matchesTab"' in tpl
    assert 'data-tab="channelsTab"' in tpl
    # ekstra (m3u8) paneli
    assert 'data-tab="extraTab"' in tpl
    print("OK: no_server_text_and_no_fake_matches")


def test_extra_panel_and_hls_player():
    """⚡ EXTRA sekmesi + m3u8 (HLS) oynatıcı şablonda mevcut."""
    tpl = site.TEMPLATE.read_text(encoding="utf-8")
    for tok in ('id="extraGrid"', 'id="panelRow"', 'id="hlsVideo"', 'id="playerError"',
                'id="sourceRow"', 'id="nextSourceBtn"', 'id="retryStreamBtn"',
                "hls.min.js", "function playExtra", "function playSource",
                "function refreshExtra", "canPlayType", "Hls.isSupported", "#extra="):
        assert tok in tpl, f"eksik: {tok}"
    # extra kart tıklaması yayını HLS oynatıcıda açar ve player'e kaydırır
    assert "card.onclick = () => playExtra(ch.id, true);" in tpl
    print("OK: extra_panel_and_hls_player")


def test_view_toggle_and_compact_cards():
    """Izgara / yatay liste seçeneği ve küçültülmüş kanal kartları."""
    tpl = site.TEMPLATE.read_text(encoding="utf-8")
    assert 'data-view="grid"' in tpl and 'data-view="list"' in tpl
    assert ".channel-grid.view-list" in tpl
    assert "minmax(104px" in tpl          # kartlar küçültüldü
    assert "min-height: 84px" in tpl
    assert "function setView" in tpl
    print("OK: view_toggle_and_compact_cards")


def test_channel_click_scrolls_to_player():
    """Kanal kartına tıklama yayını açar ve player'e kaydırır."""
    tpl = site.TEMPLATE.read_text(encoding="utf-8")
    for tok in ('id="playerContainer"', 'id="playerWrap"', "player-flash",
                "scrollIntoView", "function playChannel", "card.onclick"):
        assert tok in tpl, f"eksik: {tok}"
    # kart tıklaması playChannel(..., true) -> kaydırma
    assert "card.onclick = () => playChannel(i, true);" in tpl
    print("OK: channel_click_scrolls_to_player")


def test_channel_payload():
    """Kanal verisi marka/ikon/durum ile birlikte üretiliyor."""
    data = _get_channels()
    ordered = site.ordered_channels(data)
    assert len(ordered) == 10, f"beklenen 10 kanal, {len(ordered)} bulundu"
    payload = site.channel_payload(ordered)
    assert len(payload["links"]) == 10
    assert payload["names"][0] == "BEIN SPORTS 1"
    assert payload["brands"][0] == "Bein Sports"
    assert payload["icons"][0] == "⚽"
    assert payload["statuses"][0] == "7/24"
    assert site.channel_icon("S SPORT 2") == "🏀"
    assert site.channel_icon("TRT SPOR") == "🇹🇷"
    assert site.channel_icon("Bilinmeyen Kanal") == "📡"
    print("OK: channel_payload")


def test_matches_payload_is_real():
    """Maç verisi gerçek alanlardan gelir, kanal adıyla eşleşir."""
    matches = _get_matches()
    ordered = site.ordered_channels(_get_channels())
    rows = site.matches_payload(matches, ordered, "2026-09-04")
    assert len(rows) == len(matches)
    first = rows[0]
    for key in ("id", "home", "away", "league", "time", "sport", "status",
                "isMod", "channelId", "channelName", "streamUrl", "date"):
        assert key in first, f"eksik alan: {key}"
    zirve = next(r for r in rows if r["id"] == "zirve")
    assert zirve["channelName"] == "BEIN SPORTS 1"
    assert zirve["streamUrl"].endswith("channel.html?id=zirve")
    assert zirve["isMod"] is True
    assert zirve["date"] == "2026-09-04"
    # listede olmayan kanal kimliği büyük harfle yazılır
    assert first["channelName"] == "SS2"
    # saate göre sıralı
    times = [r["time"] for r in rows]
    assert times == sorted(times)
    print("OK: matches_payload_is_real")


def test_live_window_table():
    """Bot ile sayfa aynı canlı yayın penceresini kullanır."""
    table = site.live_window()
    assert table["default"] == 120
    assert table["futbol"] == 120
    assert table["voleybol"] == 150
    assert table["buz hokeyi"] == 130
    # sınıflandırma da aynı pencereyi kullanıyor (now = 20:08)
    matches = _get_matches()
    by_time = {m.time: m for m in matches}
    assert by_time["18:30"].status == "live"      # basketbol 18:30 + 135 dk > 20:08
    assert by_time["20:00"].status == "live"
    assert by_time["21:00"].status == "upcoming"
    assert by_time["22:00"].status == "upcoming"
    print("OK: live_window_table")


def test_match_groups_html():
    matches = _get_matches()
    html = site._match_groups_html(matches)
    assert "CANLI" in html
    assert "İstanbul Başakşehir" in html
    assert "Trendyol Süper Lig" in html
    print("OK: match_groups_html")


def test_build_index_html_fills_everything():
    """Üretilen sayfada yer tutucu kalmaz, gerçek veri gömülür."""
    from pathlib import Path

    matches = _get_matches()
    with tempfile.TemporaryDirectory() as tmp:
        original = site.INDEX_OUT
        site.INDEX_OUT = Path(tmp) / "index.html"
        try:
            out = site.build_index_html(matches, _get_channels(), datetime(2026, 9, 4, 20, 8))
            assert out and site.INDEX_OUT.exists()
            html = site.INDEX_OUT.read_text(encoding="utf-8")
        finally:
            site.INDEX_OUT = original

    assert "{{" not in html, "doldurulmamış yer tutucu kaldı"
    assert "Sunucu" not in html
    assert '"BEIN SPORTS 1"' in html
    assert "channel.html?id=zirve" in html
    assert "İstanbul Başakşehir" in html
    assert "output/today_matches.json" in html
    # ekstra panel (config/extra_channels.yml) gömülür
    assert "output/extra_channels.json" in html
    assert '"atom:bein-sports-1"' in html
    assert "tv.atomspor.workers.dev/?ID=bein-sports-1" in html
    print("OK: build_index_html_fills_everything")


if __name__ == "__main__":
    test_template_markers()
    test_no_server_text_and_no_fake_matches()
    test_extra_panel_and_hls_player()
    test_view_toggle_and_compact_cards()
    test_channel_click_scrolls_to_player()
    test_channel_payload()
    test_matches_payload_is_real()
    test_live_window_table()
    test_match_groups_html()
    test_build_index_html_fills_everything()
    print("\nSİTE TESTLERİ GEÇTİ ✅")
