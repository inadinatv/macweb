"""Ekstra paneller (Atom Spor vb. m3u8 kaynakları) testleri — ağ kullanılmaz.

Sahte bir HTTP katmanıyla:
  * kanal sayfasından m3u8 çıkarma (düz, göreli, encoded, base64, iframe),
  * adres değişiminde numaralı ayna taraması (atomsportv501 → 503),
  * çıkarılamayan kanalda son çözümün korunması + yedek kaynaklar,
  * output/extra_channels.json ve index.html'e gömme
senaryoları doğrulanır.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fixbet import extras, site  # noqa: E402

BASE = "https://atomsportv501.top"


def _panel(**over):
    panel = {
        "id": "atom", "name": "ATOM SPOR", "icon": "⚛️",
        "base_url": BASE,
        "mirror": {"pattern": "atomsportv{n}.top", "preferred_number": 501, "scan_window": 3},
        "page_template": "{base_url}/kanal/{slug}",
        "fallback_template": "https://tv.atomspor.workers.dev/?ID={slug}",
        "embed_fallback": True,
        "referrer": "{base_url}",
        "channels": [
            {"slug": "bein-sports-1", "name": "BEIN SPORTS 1"},
            {"slug": "s-sport", "name": "S SPORT"},
            {"slug": "tv-8-5", "name": "TV 8,5"},
        ],
    }
    panel.update(over)
    return panel


class FakeNet:
    """url -> (status, body) tablosu; istenen URL'leri kaydeder."""

    def __init__(self, pages: dict[str, tuple[int, str]]):
        self.pages = pages
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, headers: dict, timeout: float):
        self.calls.append((url, dict(headers)))
        if url in self.pages:
            status, body = self.pages[url]
            return extras.FetchResult(status, url, body)
        return None  # DNS / bağlantı hatası gibi


HOME = "<html><a href='/kanal/bein-sports-1'>bein</a></html>"
# Sağlık kontrolü ilk kanalın sayfasında yapılır: slug ya da m3u8 izi taşımalı
HEALTH = BASE + "/kanal/bein-sports-1"


def test_find_m3u8_variants():
    assert extras.find_m3u8('var s="https://cdn.x/live/b1/playlist.m3u8?token=1";', BASE) \
        == "https://cdn.x/live/b1/playlist.m3u8?token=1"
    # JSON kaçışlı eğik çizgiler
    assert extras.find_m3u8('{"file":"https:\\/\\/cdn.x\\/a.m3u8"}', BASE) == "https://cdn.x/a.m3u8"
    # göreli
    assert extras.find_m3u8("source: '/hls/ss.m3u8'", BASE + "/kanal/s-sport") == BASE + "/hls/ss.m3u8"
    # URL encoded
    assert extras.find_m3u8("player?u=https%3A%2F%2Fcdn.x%2Fenc%2Findex.m3u8", BASE) == "https://cdn.x/enc/index.m3u8"
    # atob(base64)
    b64 = base64.b64encode(b"https://cdn.x/b64/index.m3u8").decode()
    assert extras.find_m3u8(f"var u = atob('{b64}');", BASE) == "https://cdn.x/b64/index.m3u8"
    # uzun base64 dizesi (atob olmadan)
    long_b64 = base64.b64encode(b"{'src':'https://cdn.x/long/chunklist.m3u8','x':1}").decode()
    assert extras.find_m3u8(f'data-cfg="{long_b64}"', BASE) == "https://cdn.x/long/chunklist.m3u8"
    assert extras.find_m3u8("<html>no stream here</html>", BASE) is None
    print("OK: find_m3u8_variants")


def test_extract_follows_iframes():
    net = FakeNet({
        BASE + "/kanal/bein-sports-1": (200, '<iframe src="https://player.x/embed/1"></iframe>'),
        "https://player.x/embed/1": (200, '<iframe src="https://inner.x/p?id=1"></iframe>'),
        "https://inner.x/p?id=1": (200, 'hls.loadSource("https://edge.x/bs1/index.m3u8")'),
    })
    url = extras.extract_m3u8_from_page(BASE + "/kanal/bein-sports-1", BASE, net)
    assert url == "https://edge.x/bs1/index.m3u8"
    # iframe isteklerinde Referer bir üst sayfadır
    assert net.calls[1][1]["Referer"] == BASE + "/kanal/bein-sports-1"
    assert net.calls[2][1]["Referer"] == "https://player.x/embed/1"
    print("OK: extract_follows_iframes")


def test_resolve_panel_online_and_sources_order():
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    net = FakeNet({
        BASE + "/kanal/bein-sports-1": (200, 'src:"https://edge.x/bs1/index.m3u8"'),
        BASE + "/kanal/s-sport": (200, "<html>player gelmedi</html>"),
        BASE + "/kanal/tv-8-5": (500, ""),
    })
    out = extras.resolve_panel(_panel(), None, net, extras.DEFAULT_HEADERS, 5, now, 6)
    assert out["base_url"] == BASE and out["healthy"] is True
    assert out["resolved"] == 1 and out["fresh"] == 1 and out["total"] == 3
    # ana sayfaya değil, ilk kanalın sayfasına sağlık isteği atıldı
    assert net.calls[0][0] == HEALTH
    by = {c["slug"]: c for c in out["channels"]}

    bs1 = by["bein-sports-1"]
    assert bs1["id"] == "atom:bein-sports-1" and bs1["resolved"] is True and bs1["fresh"] is True
    assert [s["url"] for s in bs1["sources"]] == [
        "https://edge.x/bs1/index.m3u8",
        "https://tv.atomspor.workers.dev/?ID=bein-sports-1",
        BASE + "/kanal/bein-sports-1",
    ]
    assert [s["type"] for s in bs1["sources"]] == ["hls", "hls", "embed"]
    assert bs1["sources"][0]["label"] == "Kaynak 1" and bs1["sources"][2]["label"] == "Site"
    assert bs1["icon"] == "⚽" and bs1["panel_name"] == "ATOM SPOR"

    ss = by["s-sport"]
    assert ss["resolved"] is False
    assert ss["sources"][0]["url"] == "https://tv.atomspor.workers.dev/?ID=s-sport"  # yedek m3u8 önde
    assert ss["sources"][-1]["type"] == "embed"
    print("OK: resolve_panel_online_and_sources_order")


def test_mirror_scan_when_address_changes():
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    new_base = "https://atomsportv503.top"
    net = FakeNet({
        # 501 kapalı (None), 502 var ama park sayfası (slug/m3u8 izi yok), 503 sağlıklı
        "https://atomsportv502.top/kanal/bein-sports-1": (200, "<html>park sayfası</html>"),
        new_base + "/kanal/bein-sports-1": (200, 'file: "https://edge.x/new/bs1.m3u8"'),
    })
    out = extras.resolve_panel(_panel(), None, net, extras.DEFAULT_HEADERS, 5, now, 6)
    assert out["base_url"] == new_base, out["base_url"]
    assert out["healthy"] is True
    bs1 = next(c for c in out["channels"] if c["slug"] == "bein-sports-1")
    assert bs1["sources"][0]["url"] == "https://edge.x/new/bs1.m3u8"
    assert bs1["page_url"] == new_base + "/kanal/bein-sports-1"
    assert bs1["referrer"] == new_base
    # adaylar yüksek numaradan başlar (yeni ayna önce)
    cands = extras.mirror_candidates(_panel()["mirror"], BASE)
    assert cands[0] == "atomsportv504.top" and cands[-1] == "atomsportv498.top"
    print("OK: mirror_scan_when_address_changes")


def test_previous_resolution_is_kept_when_fresh():
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    fresh_at = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    old_at = (now - timedelta(hours=9)).isoformat(timespec="seconds")
    previous = {"base_url": BASE, "channels": [
        {"slug": "s-sport", "resolved_url": "https://edge.x/old/ss.m3u8", "resolved_at": fresh_at},
        {"slug": "tv-8-5", "resolved_url": "https://edge.x/old/tv85.m3u8", "resolved_at": old_at},
    ]}
    # site ayakta (ilk kanal sayfası açılıyor) ama diğer kanal sayfaları bu sefer açılmıyor
    net = FakeNet({HEALTH: (200, "<html>bein-sports-1 player</html>")})
    out = extras.resolve_panel(_panel(), previous, net, extras.DEFAULT_HEADERS, 5, now, 6)
    assert out["healthy"] is True
    by = {c["slug"]: c for c in out["channels"]}
    ss = by["s-sport"]
    assert ss["stale"] is True and ss["resolved"] is True and ss["fresh"] is False
    assert ss["sources"][0]["url"] == "https://edge.x/old/ss.m3u8"  # 2 saatlik çözüm korunur
    tv = by["tv-8-5"]
    assert tv["sources"][0]["url"] == "https://tv.atomspor.workers.dev/?ID=tv-8-5"  # 9 saatlik atılır
    # tamamen çevrimdışı (fetch=None): süre bakılmaksızın eldeki korunur, healthy None
    off = extras.resolve_panel(_panel(), previous, None, extras.DEFAULT_HEADERS, 5, now, None)
    assert off["healthy"] is None
    assert {c["slug"]: c["sources"][0]["url"] for c in off["channels"]}["tv-8-5"] == "https://edge.x/old/tv85.m3u8"
    print("OK: previous_resolution_is_kept_when_fresh")


def test_static_url_channel_and_disabled_panel():
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    panel = _panel(channels=[{"slug": "x", "name": "X", "url": "https://static.x/x.m3u8"}])
    out = extras.resolve_panel(panel, None, None, extras.DEFAULT_HEADERS, 5, now, None)
    srcs = [s["url"] for s in out["channels"][0]["sources"]]
    assert srcs[0] == "https://static.x/x.m3u8"
    assert "https://tv.atomspor.workers.dev/?ID=x" in srcs
    print("OK: static_url_channel_and_disabled_panel")


def test_refresh_writes_output_and_site_embeds_extra():
    """Gerçek yapılandırma dosyasıyla uçtan uca: output json + index.html."""
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    cfg = extras.load_config()
    assert cfg["panels"][0]["id"] == "atom"
    assert len(cfg["panels"][0]["channels"]) == 14

    net = FakeNet({
        BASE + "/kanal/bein-sports-1": (200, 'src:"https://edge.x/bs1/index.m3u8"'),
    })
    with tempfile.TemporaryDirectory() as tmp:
        orig_out, orig_idx = extras.EXTRA_OUTPUT, site.INDEX_OUT
        extras.EXTRA_OUTPUT = Path(tmp) / "extra_channels.json"
        site.INDEX_OUT = Path(tmp) / "index.html"
        try:
            data = extras.refresh(now, fetch=net)
            assert extras.EXTRA_OUTPUT.exists()
            saved = json.loads(extras.EXTRA_OUTPUT.read_text(encoding="utf-8"))
            assert saved["total"] == 14 and saved["panels"][0]["resolved"] == 1
            assert saved["source"] == "output/extra_channels.json"

            out = site.build_index_html([], {"total": 0, "by_brand": {}, "channels": []},
                                        datetime(2026, 9, 5, 15, 0), extra_data=data)
            html = Path(out).read_text(encoding="utf-8")
        finally:
            extras.EXTRA_OUTPUT, site.INDEX_OUT = orig_out, orig_idx

    assert "{{" not in html
    assert 'data-tab="extraTab"' in html and "⚡ EXTRA" in html
    assert '"atom:bein-sports-1"' in html
    assert "https://edge.x/bs1/index.m3u8" in html
    assert "https://tv.atomspor.workers.dev/?ID=s-sport" in html
    assert 'const extraSource = "output/extra_channels.json"' in html
    assert 'id="hlsVideo"' in html and "hls.min.js" in html
    # noscript listesi
    assert "⚡ ATOM SPOR" in html
    payload = site.extra_payload(data)
    assert payload["panels"][0]["channels"][0]["sources"][0]["type"] == "hls"
    assert "page_url" not in payload["panels"][0]["channels"][0]  # sayfaya gereksiz alan gömülmez
    print("OK: refresh_writes_output_and_site_embeds_extra")


if __name__ == "__main__":
    test_find_m3u8_variants()
    test_extract_follows_iframes()
    test_resolve_panel_online_and_sources_order()
    test_mirror_scan_when_address_changes()
    test_previous_resolution_is_kept_when_fresh()
    test_static_url_channel_and_disabled_panel()
    test_refresh_writes_output_and_site_embeds_extra()
    print("\nEKSTRA PANEL TESTLERİ GEÇTİ ✅")
