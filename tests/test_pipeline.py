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
    # "şimdi" 20:45 olsun -> 18:30 bitti, 20:00 canlı, 21:00/22:00 yaklaşan
    now = datetime(2026, 9, 4, 20, 8)
    matches = categorizer.classify(matches, now)
    # sıra: [zirve20:00, ss2-18:30, b2-20:00, ss2-21:00, b3-22:00, ss-22:00]
    assert matches[1].status == "finished"      # 18:30 Olimpia (bitti)
    assert matches[2].status == "live"          # 20:00 Lyon (canlı)
    assert matches[0].status == "live"          # 20:00 zirve (canlı)
    assert matches[4].status == "upcoming"      # 22:00 Ipswich (yaklaşan)
    print("OK: classify")


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


if __name__ == "__main__":
    test_parse_rich()
    test_classify_canli()
    test_categorize_groups()
    print("\nTÜM TESTLER GEÇTİ ✅")
