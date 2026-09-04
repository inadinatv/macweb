"""7/24 kanalların çekilmesi ve marka kategorizasyonu testleri."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fixbet import channels

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "home.html")


def test_parse_home():
    with open(FIXTURE, encoding="utf-8") as fh:
        html = fh.read()
    found = channels._parse_home(html)
    assert len(found) == 10, f"beklenen 10 kanal, {len(found)} bulundu"
    ids = [c["channel_id"] for c in found]
    assert "zirve" in ids and "trtspor" in ids
    assert found[0]["name"] == "BEIN SPORTS 1"
    assert found[0]["status"] == "7/24"
    print("OK: parse_home")


def test_brand():
    assert channels._brand("BEIN SPORTS 1") == "Bein Sports"
    assert channels._brand("TRT SPOR") == "TRT"
    assert channels._brand("TABII SPOR 1") == "Tabii Spor"
    assert channels._brand("EURO SPORT 1") == "Eurosport"
    print("OK: brand")


def test_categorize():
    with open(FIXTURE, encoding="utf-8") as fh:
        html = fh.read()
    found = channels._parse_home(html)
    cat = channels.categorize(found)
    assert cat["total"] == 10
    assert "Bein Sports" in cat["by_brand"]
    assert "TRT" in cat["by_brand"]
    # her marka grubunda en az 1 kanal
    assert all(len(v) >= 1 for v in cat["by_brand"].values())
    print("OK: categorize")


if __name__ == "__main__":
    test_parse_home()
    test_brand()
    test_categorize()
    print("\nKANAL TESTLERİ GEÇTİ ✅")
