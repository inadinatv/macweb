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
                "{{EXTRA_SOURCE}}", "{{EXTRA_JSON}}", "{{EXTRA_HTML}}",
                "{{STANDINGS_SOURCE}}", "{{STANDINGS_JSON}}", "{{STANDINGS_HTML}}"):
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


def test_league_standings_button_and_modal():
    """LİG PUANI butonu + PUAN DURUMU modalı ve gerçek puan tablosu gömülür."""
    tpl = site.TEMPLATE.read_text(encoding="utf-8")
    # buton saat widget'ının hemen yanında, kendi sınıfıyla (tab-btn değil)
    assert 'id="leagueBtn"' in tpl and "LİG PUANI" in tpl
    assert 'class="league-btn"' in tpl
    assert tpl.index('id="liveClock"') < tpl.index('id="leagueBtn"'), "buton saatten sonra gelmeli"
    assert tpl.count('class="tab-btn') == 3, "sekme sayısı değişmemeli"
    # modal: karartma, neon pembe kenar, kapatma butonu, başlık
    assert 'id="leagueModal"' in tpl and 'id="leagueModalClose"' in tpl
    assert "backdrop-filter: blur" in tpl
    assert "border: 2px solid var(--neon-pink)" in tpl
    assert 'class="modal-title" id="leagueModalTitle">PUAN DURUMU<' in tpl
    # sütunlar
    head = tpl[tpl.index('id="standingsTable"'):tpl.index('id="standingsBody"')]
    assert [c for c in ("SIRA", "TAKIM", "O", "G", "B", "M", "AV", "P")] == \
        [h for h in ("SIRA", "TAKIM", "O", "G", "B", "M", "AV", "P") if h in head]
    print("OK: league_standings_button_and_modal")


def test_standings_payload_and_noscript_table():
    """Puan durumu JSON'u sadeleşir ve JS'siz ortam için tabloya dönüşür."""
    data = {"source": "espn", "generated_at": "2026-09-07T22:47:00+03:00", "leagues": [{
        "id": "soccer/tur.1", "name": "Trendyol Süper Lig", "sport": "Futbol",
        "season": "2026-27 Turkish Super Lig", "updated_at": "2026-09-07T22:47:00+03:00", "teams": 1,
        "rows": [{"rank": 1, "team": "Galatasaray", "sourceTeam": "Galatasaray", "abbr": "GAL",
                  "logo": "https://a.espncdn.com/i/teamlogos/soccer/500/432.png", "played": 4,
                  "wins": 3, "draws": 1, "losses": 0, "goalsFor": 12, "goalsAgainst": 6,
                  "diff": 6, "points": 10, "note": "Champions League"}]}]}
    payload = site.standings_payload(data)
    row = payload["leagues"][0]["rows"][0]
    assert "sourceTeam" not in row, "iç alan sayfaya sızmamalı"
    assert (row["played"], row["points"], row["diff"]) == (4, 10, 6), "sayılar değişmemeli"

    html = site._standings_groups_html(data)
    assert "PUAN DURUMU" in html and "Galatasaray" in html
    assert "<th" in html and "SIRA" in html and "AV" in html
    # boş tablo: uydurma satır değil, dürüst mesaj
    empty = site._standings_groups_html({"leagues": []})
    assert "Galatasaray" not in empty and "henüz alınamadı" in empty
    assert site.standings_payload(None)["leagues"] == []
    print("OK: standings_payload_and_noscript_table")


def test_generated_index_embeds_real_standings():
    matches = _get_matches()
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        original = site.INDEX_OUT
        site.INDEX_OUT = Path(tmp) / "index.html"
        try:
            site.build_index_html(matches, _get_channels(), datetime(2026, 9, 4, 20, 8))
            html = site.INDEX_OUT.read_text(encoding="utf-8")
        finally:
            site.INDEX_OUT = original
    assert "{{" not in html
    assert 'const standingsSource = "output/standings.json"' in html
    assert '"source": "espn"' in html or '"source":"espn"' in html
    # output/standings.json doluysa lider tabloya gömülmüş olmalı
    from fixbet import standings
    seeded = standings.load_or_build()
    if seeded.get("leagues"):
        leader = seeded["leagues"][0]["rows"][0]["team"]
        assert leader in html, f"lider ({leader}) sayfaya gömülmedi"
        noscript = html[html.index("<noscript>"):html.index("</noscript>")]
        assert "PUAN DURUMU" in noscript and leader in noscript, "noscript puan tablosu yok"
    print("OK: generated_index_embeds_real_standings")


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
    test_league_standings_button_and_modal()
    test_standings_payload_and_noscript_table()
    test_generated_index_embeds_real_standings()
    print("\nSİTE TESTLERİ GEÇTİ ✅")
