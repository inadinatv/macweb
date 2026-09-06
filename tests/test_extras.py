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


SEL_BASE = "https://www.sporcafe-aaaa.xyz"
PLAYER = "https://main.uxsyplayer1234abcd.click"


def _selcuk_panel(**over):
    panel = {
        "id": "selcuk", "name": "SELÇUK SPOR", "icon": "🎥",
        "base_url": SEL_BASE,
        "entry_urls": ["https://www.sporcafe-old.xyz/"],
        "mirror": {"pattern": "sporcafe{n}.xyz", "preferred_number": 8, "scan_window": 2,
                   "must_contain_any": ["uxsyplayer"]},
        "health_path": "/",
        "player": {
            "domain_pattern": r"https?://(main\.uxsyplayer[0-9a-zA-Z\-]+\.click)",
            "default_base": "https://main.uxsyplayerDEFAULT.click",
            "stream_base_patterns": [r"this\.adsBaseUrl\s*=\s*['\"]([^'\"]+)"],
            "stream_template": "{stream_base}{slug}/playlist.m3u8",
        },
        "page_template": "{player_base}/index.php?id={slug}",
        "embed_template": "{player_base}/index.php?id={slug}",
        "referrer": "{base_url}/",
        "channels": [
            {"slug": "selcukbeinsports1", "name": "BEIN SPORTS 1"},
            {"slug": "selcukssport", "name": "S SPORT"},
        ],
    }
    panel.update(over)
    return panel


class RedirectNet(FakeNet):
    """url -> ("redirect", hedef) girdileri yönlendirme gibi davranır."""

    def __call__(self, url: str, headers: dict, timeout: float):
        self.calls.append((url, dict(headers)))
        entry = self.pages.get(url)
        if entry and entry[0] == "redirect":
            target = entry[1]
            status, body = self.pages.get(target, (404, ""))
            return extras.FetchResult(status, target, body)
        if entry:
            return extras.FetchResult(entry[0], url, entry[1])
        return None


def test_stream_from_rules_builds_playlist_url():
    rules = _selcuk_panel()["player"]
    fmt = {"slug": "selcukssport"}
    assert extras.stream_from_rules("x; this.adsBaseUrl = 'https://cdn.sel/live/'; y", rules, fmt) \
        == "https://cdn.sel/live/selcukssport/playlist.m3u8"
    assert extras.stream_from_rules("<html>reklam</html>", rules, fmt) is None
    # kural yoksa / şablon boşsa None
    assert extras.stream_from_rules("this.adsBaseUrl = 'https://x/'", None, fmt) is None
    print("OK: stream_from_rules_builds_playlist_url")


def test_selcuk_two_stage_resolution():
    """Ana sayfa → oynatıcı sunucusu → adsBaseUrl → {stream_base}{slug}/playlist.m3u8"""
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    net = FakeNet({
        SEL_BASE + "/": (200, f'<iframe src="{PLAYER}/index.php?id=selcukbeinsports1"></iframe> uxsyplayer'),
        PLAYER + "/index.php?id=selcukbeinsports1": (200, "this.adsBaseUrl = 'https://cdn.sel/hls/';"),
        PLAYER + "/index.php?id=selcukssport": (200, "<html>sadece reklam</html>"),
    })
    out = extras.resolve_panel(_selcuk_panel(), None, net, extras.DEFAULT_HEADERS, 5, now, 6)
    assert out["healthy"] is True and out["base_url"] == SEL_BASE
    assert out["player_base"] == PLAYER
    # sağlık kontrolü health_path ("/") üzerinden yapıldı, ana sayfa ikinci kez çekilmedi
    assert net.calls[0][0] == SEL_BASE + "/"
    assert sum(1 for u, _ in net.calls if u == SEL_BASE + "/") == 1
    by = {c["slug"]: c for c in out["channels"]}
    bs1 = by["selcukbeinsports1"]
    assert bs1["fresh"] is True
    assert [s["url"] for s in bs1["sources"]] == [
        "https://cdn.sel/hls/selcukbeinsports1/playlist.m3u8",
        PLAYER + "/index.php?id=selcukbeinsports1",
    ]
    assert bs1["referrer"] == SEL_BASE + "/"
    # oynatıcı isteğinde Referer = site
    hdr = next(h for u, h in net.calls if u == PLAYER + "/index.php?id=selcukbeinsports1")
    assert hdr["Referer"] == SEL_BASE + "/"
    ss = by["selcukssport"]
    assert ss["resolved"] is False
    assert [s["type"] for s in ss["sources"]] == ["embed"]  # yalnızca oynatıcı sayfası yedeği
    print("OK: selcuk_two_stage_resolution")


def test_selcuk_entry_url_redirect_and_player_fallback():
    """Site adı değişti: eski giriş adresi yeni adrese yönlendiriyor; oynatıcı adı
    sayfada bulunamazsa son bilinen / varsayılan oynatıcı kullanılır."""
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    new_base = "https://www.sporcafe-bbbb.xyz"
    net = RedirectNet({
        # SEL_BASE kapalı (None); eski giriş adresi yeni siteye yönlendiriyor
        "https://www.sporcafe-old.xyz/": ("redirect", new_base + "/"),
        new_base + "/": (200, "<html>uxsyplayer yükleniyor (alan adı script içinde)</html>"),
        "https://main.uxsyplayerPREV.click/index.php?id=selcukbeinsports1": (200, "this.adsBaseUrl='https://cdn2/';"),
    })
    previous = {"base_url": SEL_BASE, "player_base": "https://main.uxsyplayerPREV.click", "channels": []}
    out = extras.resolve_panel(_selcuk_panel(), previous, net, extras.DEFAULT_HEADERS, 5, now, 6)
    assert out["base_url"] == new_base and out["healthy"] is True
    assert out["player_base"] == "https://main.uxsyplayerPREV.click"  # son bilinen oynatıcı korunur
    bs1 = out["channels"][0]
    assert bs1["sources"][0]["url"] == "https://cdn2/selcukbeinsports1/playlist.m3u8"

    # hiç önceki yoksa yapılandırmadaki varsayılan oynatıcı
    net2 = RedirectNet({new_base + "/": (200, "uxsyplayer")})
    out2 = extras.resolve_panel(_selcuk_panel(base_url=new_base), None, net2, extras.DEFAULT_HEADERS, 5, now, 6)
    assert out2["player_base"] == "https://main.uxsyplayerDEFAULT.click"
    assert out2["channels"][0]["sources"][-1]["url"].startswith("https://main.uxsyplayerDEFAULT.click/index.php?id=")
    print("OK: selcuk_entry_url_redirect_and_player_fallback")


def test_selcuk_mirror_scan_numbered():
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    net = FakeNet({
        "https://sporcafe9.xyz/": (200, f'src="{PLAYER}/x.js" uxsyplayer'),
    })
    panel = _selcuk_panel(entry_urls=[])
    out = extras.resolve_panel(panel, None, net, extras.DEFAULT_HEADERS, 5, now, 6)
    assert out["base_url"] == "https://sporcafe9.xyz" and out["healthy"] is True
    assert out["player_base"] == PLAYER
    # www.sporcafe-<hex> adreslerinden numara türetilmez, tarama preferred_number çevresinde
    assert extras._num_in("https://www.sporcafe-0c2608ad69.xyz") == 0
    assert extras.mirror_candidates(panel["mirror"], SEL_BASE)[0] == "sporcafe10.xyz"
    print("OK: selcuk_mirror_scan_numbered")


def test_refresh_writes_output_and_site_embeds_extra():
    """Gerçek yapılandırma dosyasıyla uçtan uca: output json + index.html."""
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    cfg = extras.load_config()
    assert cfg["panels"][0]["id"] == "atom"
    assert len(cfg["panels"][0]["channels"]) == 14

    sel_cfg = next(p for p in cfg["panels"] if p["id"] == "selcuk")
    assert len(sel_cfg["channels"]) == 14
    sel_base = sel_cfg["base_url"]
    player = "https://main.uxsyplayerNEW.click"
    net = FakeNet({
        BASE + "/": (200, '<a href="matches?id=bein-sports-1">BEIN</a>'),
        BASE + "/matches?id=bein-sports-1": (200, 'src:"https://edge.x/bs1/index.m3u8"'),
        # Selçuk: ana sayfa oynatıcı alan adını verir, oynatıcı sayfası adsBaseUrl taşır
        sel_base + "/": (200, f'<script src="{player}/embed.js"></script> uxsyplayer'),
        player + "/index.php?id=selcukbeinsports1": (200, "this.adsBaseUrl = 'https://cdn.sel/hls/';"),
    })
    with tempfile.TemporaryDirectory() as tmp:
        orig_out, orig_idx = extras.EXTRA_OUTPUT, site.INDEX_OUT
        extras.EXTRA_OUTPUT = Path(tmp) / "extra_channels.json"
        site.INDEX_OUT = Path(tmp) / "index.html"
        try:
            data = extras.refresh(now, fetch=net)
            assert extras.EXTRA_OUTPUT.exists()
            saved = json.loads(extras.EXTRA_OUTPUT.read_text(encoding="utf-8"))
            assert saved["total"] == 28 and saved["panels"][0]["resolved"] == 1
            assert saved["source"] == "output/extra_channels.json"
            sel = saved["panels"][1]
            assert sel["id"] == "selcuk" and sel["player_base"] == player and sel["resolved"] == 1
            sbs1 = sel["channels"][0]
            assert sbs1["sources"][0]["url"] == "https://cdn.sel/hls/selcukbeinsports1/playlist.m3u8"
            assert sbs1["sources"][-1] == {"type": "embed", "label": "Site",
                                           "url": player + "/index.php?id=selcukbeinsports1"}
            assert sbs1["referrer"] == sel_base + "/"

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
    assert '"selcuk:selcukbeinsports1"' in html and "SELÇUK SPOR" in html
    assert "https://cdn.sel/hls/selcukbeinsports1/playlist.m3u8" in html
    assert 'const extraSource = "output/extra_channels.json"' in html
    assert 'id="hlsVideo"' in html and "hls.min.js" in html
    # noscript listesi
    assert "⚡ ATOM SPOR" in html and "⚡ SELÇUK SPOR" in html
    payload = site.extra_payload(data)
    assert payload["panels"][0]["channels"][0]["sources"][0]["type"] == "hls"
    assert payload["panels"][0]["channels"][0]["page_url"] == BASE + "/matches?id=bein-sports-1"
    assert payload["panels"][0]["channels"][0]["referrer"] == BASE + "/"
    print("OK: refresh_writes_output_and_site_embeds_extra")


if __name__ == "__main__":
    test_find_m3u8_variants()
    test_extract_follows_iframes()
    test_resolve_panel_online_and_sources_order()
    test_mirror_scan_when_address_changes()
    test_previous_resolution_is_kept_when_fresh()
    test_static_url_channel_and_disabled_panel()
    test_stream_from_rules_builds_playlist_url()
    test_selcuk_two_stage_resolution()
    test_selcuk_entry_url_redirect_and_player_fallback()
    test_selcuk_mirror_scan_numbered()
    test_refresh_writes_output_and_site_embeds_extra()
    print("\nEKSTRA PANEL TESTLERİ GEÇTİ ✅")


def test_direct_playlist_redirect_keeps_master_not_first_variant():
    master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=7000000,CODECS="avc1.640028,mp4a.40.2"\ntracks-v1a1/mono.m3u8\n'
    final = 'https://cdn.test/live/master.m3u8?token=a%2Bb'
    assert extras.find_m3u8(master, final) == final
    def redirected(url, headers, timeout):
        return extras.FetchResult(200, final, master, {'Content-Type': 'application/vnd.apple.mpegurl'})
    assert extras.extract_m3u8_from_page('https://worker.test/?ID=channel', BASE, redirected) == final
    media = '#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nhttps://seg.test/one.jpg\n'
    assert extras.find_m3u8(media, final) == final
    assert extras.find_m3u8('src="../live/index.m3u8?token=a%2Bb&amp;n=1"', 'https://cdn.test/player/p') == 'https://cdn.test/live/index.m3u8?token=a%2Bb&n=1'
    assert extras.find_m3u8('src="//cdn.test/live/index.m3u8"', BASE) == 'https://cdn.test/live/index.m3u8'


def test_relative_iframe_uses_redirected_parent_and_referer():
    calls = []
    def fetch(url, headers, timeout):
        calls.append((url, headers))
        if len(calls) == 1:
            return extras.FetchResult(200, 'https://site.test/new/page', '<iframe src="../embed/player"></iframe>')
        return extras.FetchResult(200, url, 'file="https://cdn.test/live/master.m3u8"')
    assert extras.extract_m3u8_from_page(BASE + '/old', BASE, fetch) == 'https://cdn.test/live/master.m3u8'
    assert calls[1][0] == 'https://site.test/embed/player'
    assert calls[1][1]['Referer'] == 'https://site.test/new/page'


def test_worker_is_resolved_even_when_channel_page_is_unavailable():
    panel = _panel(resolve_fallback=True)
    now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
    final = 'https://cdn.test/live/mono.m3u8'
    def fetch(url, headers, timeout):
        if url.startswith('https://tv.atomspor.workers.dev/'):
            return extras.FetchResult(200, final, '#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nhttps://seg.test/s.jpg\n')
        return None
    ch = extras.resolve_channel(panel, {'base_url': BASE, 'healthy': False}, panel['channels'][0], None,
                                fetch, extras.DEFAULT_HEADERS, 3, now, 6)
    assert ch['resolved_url'] == final
    assert ch['sources'][0]['url'] == final
    assert ch['sources'][1]['url'].startswith('https://tv.atomspor.workers.dev/')
    assert ch['sources'][0]['mime_type'] == 'application/vnd.apple.mpegurl'


def test_signed_query_and_encoded_scheme_are_not_corrupted():
    direct = 'https://cdn.test/index.m3u8?auth=a%2Bb&not=0&copy=1'
    assert extras.find_m3u8('src="' + direct + '"', BASE) == direct
    assert extras.find_m3u8('src="https%3A%2F%2Fcdn.test%2Findex.m3u8%3Fauth%3Da%252Bb"', BASE) == 'https://cdn.test/index.m3u8?auth=a%2Bb'
