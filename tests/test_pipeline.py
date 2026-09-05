"""offline (örnek veri) ile boru hattını sınayan basit test."""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fixbet import categorizer, parser  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "matches.php")


def test_parse_rich():
    with open(FIXTURE, encoding="utf-8") as fh:
        raw = fh.read()
    matches = parser.parse(raw)
    assert len(matches) == 6, f"beklenen 6 maç, {len(matches)} bulundu"
    first = matches[0]
    assert first.match_id == "zirve"
    assert first.home == "İstanbul Başakşehir"
    assert first.away == "Galatasaray"
    assert first.league == "Trendyol Süper Lig"
    assert first.is_match_of_day is True
    assert first.sport == "Futbol"
    assert first.time == "20:00"
    # son maç (22:00) günün maçı olmamalı
    assert matches[-1].is_match_of_day is False
    print("OK: parse_rich")


def test_classify_canli():
    with open(FIXTURE, encoding="utf-8") as fh:
        raw = fh.read()
    matches = parser.parse(raw)
    # "şimdi" 20:08 -> 18:30 ve 20:00 canlı (yayın penceresi içinde), 21:00/22:00 yaklaşan
    now = datetime(2026, 9, 4, 20, 8)
    matches = categorizer.classify(matches, now)
    # sıra: [zirve20:00, ss2-18:30, b2-20:00, ss2-21:00, b3-22:00, ss-22:00]
    assert matches[0].status == "live"          # 20:00 Başakşehir (canlı)
    assert matches[1].status == "live"          # 18:30 Olimpia (basketbol 135 dk -> 20:45'e kadar canlı)
    assert matches[2].status == "live"          # 20:00 Lyon (canlı)
    assert matches[3].status == "upcoming"      # 21:00 Olimpiakos
    assert matches[4].status == "upcoming"      # 22:00 Ipswich
    assert matches[5].status == "upcoming"      # 22:00 Real Betis
    print("OK: classify")


def test_classify_finished_and_midnight():
    """Yayın penceresi dolan maç biter; gece yarısını geçen maç da doğru hesaplanır."""
    from fixbet.models import Match

    with open(FIXTURE, encoding="utf-8") as fh:
        raw = fh.read()
    matches = categorizer.classify(parser.parse(raw), datetime(2026, 9, 4, 23, 30))
    by_time = {m.time: m for m in matches}
    assert by_time["18:30"].status == "finished"   # basketbol 18:30 + 135 dk = 20:45
    assert by_time["20:00"].status == "finished"   # futbol 20:00 + 120 dk = 22:00
    assert by_time["22:00"].status == "live"       # futbol 22:00 + 120 dk = 24:00

    # 23:30'da başlayan maç 00:30'da hâlâ canlı
    late = [Match(match_id="x", home="A", away="B", league="L", time="23:30", sport="Futbol")]
    categorizer.classify(late, datetime(2026, 9, 5, 0, 30))
    assert late[0].status == "live", f"beklenen live, gelen {late[0].status}"
    print("OK: classify_finished_and_midnight")


def test_categorize_groups():
    with open(FIXTURE, encoding="utf-8") as fh:
        raw = fh.read()
    matches = parser.parse(raw)
    now = datetime(2026, 9, 4, 20, 8)
    matches = categorizer.classify(matches, now)
    cat = categorizer.categorize(matches, now)
    assert cat["counts"]["total"] == 6
    assert "Trendyol Süper Lig" in cat["by_league"]
    assert "Futbol" in cat["by_sport"]
    assert "Basketbol" in cat["by_sport"]
    assert len(cat["match_of_the_day"]) == 1
    print("OK: categorize")


def test_load_matches_from_output():
    """Kaynak boş dönerse aynı günün son gerçek listesi yedek olarak kullanılır."""
    import json
    from datetime import timedelta

    from fixbet import config
    from fixbet import main as bot
    from fixbet.models import Match

    path = os.path.join(str(config.OUTPUT_DIR), "today_matches.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    day = datetime.strptime(data["date"], "%Y-%m-%d")

    matches = bot.load_matches_from_output(day)
    assert len(matches) == len(data["matches"]), "yedek liste eksik yüklendi"
    assert all(isinstance(m, Match) for m in matches)
    assert matches[0].home and matches[0].away

    # farklı bir gün için bayat veri döndürülmez
    assert bot.load_matches_from_output(day - timedelta(days=30)) == []
    print("OK: load_matches_from_output")


if __name__ == "__main__":
    test_parse_rich()
    test_classify_canli()
    test_classify_finished_and_midnight()
    test_categorize_groups()
    test_load_matches_from_output()
    print("\nTÜM TESTLER GEÇTİ ✅")
