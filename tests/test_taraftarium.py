"""Taraftarium24 EXTRA paneli: kanal ID keşfi ve ayna takibi.

Bu testler ağa çıkmaz. Sağlık/kanal sayfaları küçük bir sahte HTTP katmanıyla
simüle edilir; gerçek alan adı değiştiğinde resolver'ın yeni ana sayfa rotasını
öne alması korunur.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fixbet import extras  # noqa: E402


BASE = "https://taraftarium24bedava.com"


class FakeNet:
    def __init__(self, pages: dict[str, tuple[int, str]]):
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict, timeout: float):
        self.calls.append(url)
        if url not in self.pages:
            return None
        status, body = self.pages[url]
        return extras.FetchResult(status, url, body)


def panel() -> dict:
    return {
        "id": "taraftarium",
        "name": "TARAFTARIUM24",
        "icon": "📺",
        "base_url": BASE,
        "entry_urls": [BASE + "/"],
        "mirror": {
            "patterns": ["taraftarium{n}bedava.com", "taraftarium{n}.xyz"],
            "preferred_number": 24,
            "scan_window": 2,
            "must_contain_any": ["bein-sports-1"],
        },
        "health_path": "/",
        "page_route": "/channel/watch/",
        "page_templates": [
            "{base_url}/channel/watch/{slug}",
            "{base_url}/mac-izle/{slug}",
        ],
        "page_template": "{base_url}/channel/watch/{slug}",
        "embed_fallback": True,
        "referrer": "{base_url}/",
        "channels": [
            {"slug": "bein-sports-1", "name": "BEIN SPORTS 1"},
            {"slug": "s-sport", "name": "S SPORT"},
        ],
    }


def test_home_links_are_used_before_configured_routes():
    html = (
        '<a href="/mac-izle/bein-sports-1">BEIN</a>'
        '<a href="/channel/watch/s-sport++">S SPORT</a>'
    )
    assert extras._discover_page_urls(html, BASE, "bein-sports-1") == [
        BASE + "/mac-izle/bein-sports-1"
    ]
    # Kullanıcının verdiği ++ soneki eski linkte bulunsa da URL'ye taşınmaz.
    assert extras._discover_page_urls(html, BASE, "s-sport") == [
        BASE + "/channel/watch/s-sport++"
    ]


def test_taraftarium_panel_resolves_ids_and_keeps_embed_fallback():
    # Ana sayfada ESKI /mac-izle bağlantıları var; kanal linki yine de
    # /channel/watch rotasına sabitlenmelidir (page_route).
    home = (
        '<html><a href="/mac-izle/bein-sports-1">bein-sports-1</a>'
        '<a href="/mac-izle/s-sport">s-sport</a></html>'
    )
    net = FakeNet({
        BASE + "/": (200, home),
        # Sabit rota m3u8'i doğrudan veriyor:
        BASE + "/channel/watch/bein-sports-1": (
            200, 'file: "https://cdn.example/bs1/index.m3u8"'
        ),
        # s-sport: sabit rotada m3u8 yok; eski /mac-izle rotası yalnızca
        # m3u8 çıkarımı için yedek olarak kullanılır, bağlantıya yansıtılmaz:
        BASE + "/channel/watch/s-sport": (200, "<p>oynatıcı sayfası</p>"),
        BASE + "/mac-izle/s-sport": (200, 'file: "https://cdn.example/ss/index.m3u8"'),
        BASE + "/mac-izle/bein-sports-1": (200, 'file: "https://cdn.example/bs1-old/index.m3u8"'),
    })
    out = extras.resolve_panel(
        panel(), None, net, extras.DEFAULT_HEADERS, 5,
        datetime(2026, 9, 10, 12, tzinfo=timezone.utc), 6,
    )
    assert out["base_url"] == BASE
    assert out["healthy"] is True
    by_slug = {ch["slug"]: ch for ch in out["channels"]}
    bs1 = by_slug["bein-sports-1"]
    # Kanal linki /channel/watch/bein-sports-1 ile biter (ana sayfadaki
    # /mac-izle bağlantısına rağmen).
    assert bs1["page_url"] == BASE + "/channel/watch/bein-sports-1"
    assert bs1["resolved_url"] == "https://cdn.example/bs1/index.m3u8"
    assert bs1["sources"][-1]["type"] == "embed"
    assert bs1["sources"][-1]["url"] == BASE + "/channel/watch/bein-sports-1"

    ss = by_slug["s-sport"]
    # Eski rota m3u8 sağlasa bile bağlantı sabit rotada kalır.
    assert ss["page_url"] == BASE + "/channel/watch/s-sport"
    assert ss["resolved_url"] == "https://cdn.example/ss/index.m3u8"
    assert ss["sources"][-1]["type"] == "embed"
    assert ss["sources"][-1]["url"] == BASE + "/channel/watch/s-sport"


def test_taraftarium_mirror_families_scan():
    candidates = extras.mirror_candidates(panel()["mirror"], BASE)
    assert candidates[0] == "taraftarium26bedava.com"
    assert "taraftarium26.xyz" in candidates
    assert "taraftarium22bedava.com" in candidates


def test_repository_panel_and_menu_are_configured():
    cfg = extras.load_config()
    tara = next(p for p in cfg["panels"] if p["id"] == "taraftarium")
    slugs = {ch["slug"] for ch in tara["channels"]}
    assert {"bein-sports-1", "bein-sports-max-2", "s-sport-2", "trt-spor", "trt-1", "a-spor"} <= slugs
    # Kanal bağlantısı /channel/watch rotasına sabitli olmalı:
    # link her zaman https://…/channel/watch/<slug> ile biter.
    route = str(tara.get("page_route") or "").strip().strip("/").lower()
    assert route == "channel/watch"
    templates = tara.get("page_templates") or [tara.get("page_template")]
    assert str(templates[0]).strip().endswith("/channel/watch/{slug}")
    template = (extras.config.ROOT / "src" / "fixbet" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "⚡ EXTRA PANELLER" in template
