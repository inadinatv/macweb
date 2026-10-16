"""Kodaman visible public KANALLAR menu refresh tests."""
import json
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402
from fixbet import kodaman  # noqa: E402
from fixbet.kodaman import (  # noqa: E402
    PublicPage,
    PublicSourceUnavailable,
    _next_host,
    _validated_url,
    extract_visible_channels,
    fetch_visible_channel_menu,
    normalize_menu_channels,
    refresh_manifest,
)


MENU_ROWS = [
    {"name": "7/24 BEIN SPORTS 1", "href": "channel?id=zirve"},
    {"name": "7/24 BEIN SPORTS 2", "href": "channel?id=b2"},
    {"name": "7/24 BEIN SPORTS 3", "href": "channel?id=b3"},
    {"name": "7/24 BEIN SPORTS 4", "href": "channel?id=b4"},
    {"name": "7/24 BEIN SPORTS 5", "href": "channel?id=b5"},
    {"name": "7/24 BEIN SPORTS MAX 1", "href": "channel?id=bm1"},
    {"name": "7/24 BEIN SPORTS MAX 2", "href": "channel?id=bm2"},
    {"name": "7/24 S SPORT", "href": "channel?id=ss"},
    {"name": "7/24 S SPORT 2", "href": "channel?id=ss2"},
    {"name": "7/24 SMART SPOR", "href": "channel?id=smarts"},
    {"name": "7/24 SMART SPOR 2", "href": "channel?id=sms2"},
    {"name": "7/24 TIVIBU SPOR 1", "href": "channel?id=t1"},
    {"name": "7/24 TIVIBU SPOR 2", "href": "channel?id=t2"},
    {"name": "7/24 TIVIBU SPOR 3", "href": "channel?id=t3"},
    {"name": "7/24 TIVIBU SPOR 4", "href": "channel?id=t4"},
    {"name": "7/24 TRT SPOR", "href": "channel?id=trtspor"},
    {"name": "7/24 TRT SPOR YILDIZ", "href": "channel?id=trtspor2"},
    {"name": "7/24 TRT 1", "href": "channel?id=trt1"},
    {"name": "7/24 A SPOR", "href": "channel?id=as"},
    {"name": "7/24 ATV", "href": "channel?id=atv"},
    {"name": "7/24 TV 8", "href": "channel?id=tv8"},
    {"name": "7/24 TV 8,5", "href": "channel?id=tv85"},
    {"name": "7/24 EURO SPORT 1", "href": "channel?id=eu1"},
    {"name": "7/24 EURO SPORT 2", "href": "channel?id=eu2"},
    {"name": "7/24 TABII SPOR", "href": "channel?id=ex7"},
    {"name": "7/24 TABII SPOR 1", "href": "channel?id=ex1"},
    {"name": "7/24 TABII SPOR 2", "href": "channel?id=ex2"},
    {"name": "7/24 TABII SPOR 3", "href": "channel?id=ex3"},
    {"name": "7/24 TABII SPOR 4", "href": "channel?id=ex4"},
    {"name": "7/24 TABII SPOR 5", "href": "channel?id=ex5"},
    {"name": "7/24 TABII SPOR 6", "href": "channel?id=ex6"},
]


def test_visible_menu_rows_normalize_all_31_public_channels():
    channels = normalize_menu_channels(MENU_ROWS, "https://kodamantv21.com/")
    assert len(channels) == 31
    assert channels[0] == {"id": "zirve", "name": "BEIN SPORTS 1"}
    assert channels[5] == {"id": "bm1", "name": "BEIN SPORTS MAX 1"}
    assert channels[24] == {"id": "ex7", "name": "TABII SPOR"}
    assert all(not channel["name"].startswith("7/24") for channel in channels)
    assert len({channel["id"] for channel in channels}) == 31


def test_menu_normalizer_rejects_external_bad_and_non_channel_links():
    rows = MENU_ROWS[:1] + [
        {"name": "External", "href": "https://example.com/channel?id=outside"},
        {"name": "Counter", "href": "/sayac"},
        {"name": "Bad ID", "href": "channel?id=bad%2Fid"},
        {"name": "Duplicate", "href": "channel?id=zirve"},
    ]
    assert normalize_menu_channels(rows, "https://kodamantv21.com/") == [
        {"id": "zirve", "name": "BEIN SPORTS 1"}
    ]


def test_extracts_only_visible_same_site_channel_references():
    html = '''<!doctype html><title>Kodaman TV</title>
      <iframe src="channel?id=alpha-1" title="Alpha One"></iframe>
      <a href="/channel?id=beta_2">Beta Two</a>
      <iframe src="/sayac"></iframe>
      <iframe src="/channel?id=hidden" hidden></iframe>
      <div style="display:none"><a href="/channel?id=css-hidden">Hidden</a></div>
      <iframe src="https://example.com/channel?id=external"></iframe>
      <iframe src="/channel?id=bad%2Fid"></iframe>
      <script>const privateId = "channel?id=script-only";</script>'''
    channels = extract_visible_channels(html, "https://kodamantv21.com/")
    assert channels == [
        {"id": "alpha-1", "name": "Alpha One"},
        {"id": "beta_2", "name": "Beta Two"},
    ]


def test_host_validation_and_one_step_domain_progression():
    assert _next_host("kodamantv21.com") == "kodamantv22.com"
    assert _next_host("kodamantv22.com") == "kodamantv23.com"
    assert _next_host("example.com") is None
    assert _validated_url("https://kodamantv21.com/channel?id=zirve").startswith("https://kodamantv21.com/")
    with pytest.raises(ValueError):
        _validated_url("https://example.com/channel?id=zirve")
    with pytest.raises(ValueError):
        _validated_url("https://user@kodamantv21.com/")
    with pytest.raises(ValueError):
        _validated_url("https://kodamantv21.com:8443/")


def test_menu_fetcher_uses_browser_result_and_validates_catalog(monkeypatch):
    payload = {"base_url": "https://kodamantv22.com", "channels": MENU_ROWS[:2]}
    monkeypatch.setattr(
        kodaman.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""),
    )
    base_url, channels = fetch_visible_channel_menu("https://kodamantv21.com/")
    assert base_url == "https://kodamantv22.com"
    assert channels == [
        {"id": "zirve", "name": "BEIN SPORTS 1"},
        {"id": "b2", "name": "BEIN SPORTS 2"},
    ]


def test_refresh_uses_rendered_menu_and_does_not_probe_each_player(tmp_path):
    homepage21 = '''<title>Kodaman TV</title>
      <a>Bir sonraki alan adımız bir sayı artarak devam edecektir.</a>
      <iframe src="/channel?id=old-single-embed"></iframe>'''
    homepage22 = '<title>Kodaman TV</title><div id="channels-content"></div>'
    pages = {
        "https://kodamantv21.com/": PublicPage("https://kodamantv21.com/", 200, homepage21),
        "https://kodamantv22.com/": PublicPage("https://kodamantv22.com/", 200, homepage22),
    }
    http_calls = []
    menu_calls = []

    def fake_fetch(url):
        http_calls.append(url)
        if url not in pages:
            raise OSError("unexpected request")
        return pages[url]

    def fake_menu(base_url):
        menu_calls.append(base_url)
        return base_url, normalize_menu_channels(MENU_ROWS, base_url)

    manifest, changed = refresh_manifest(
        path=tmp_path / "kodaman_channels.json",
        fetcher=fake_fetch,
        menu_fetcher=fake_menu,
        now=datetime(2026, 10, 16, 19, 0, tzinfo=timezone.utc),
    )
    assert changed
    assert manifest["base_url"] == "https://kodamantv22.com"
    assert len(manifest["channels"]) == 31
    assert manifest["channels"][0] == {"id": "zirve", "name": "BEIN SPORTS 1", "status": "listed"}
    assert all(item["status"] == "listed" for item in manifest["channels"])
    assert http_calls == ["https://kodamantv21.com/", "https://kodamantv22.com/"]
    assert menu_calls == ["https://kodamantv21.com", "https://kodamantv22.com"]


def test_failed_visible_menu_refresh_preserves_last_known_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    old = {
        "base_url": "https://kodamantv21.com",
        "updated_at": "old",
        "channels": [{"id": row["href"].split("id=")[1], "name": row["name"], "status": "listed"} for row in MENU_ROWS],
    }
    path.write_text(json.dumps(old), encoding="utf-8")

    def fake_fetch(url):
        if url == "https://kodamantv21.com/":
            return PublicPage(url, 200, "<title>Kodaman TV</title>")
        raise OSError("next host unavailable")

    def empty_menu(_base_url):
        return "https://kodamantv21.com", []

    with pytest.raises(PublicSourceUnavailable):
        refresh_manifest(path=path, fetcher=fake_fetch, menu_fetcher=empty_menu)
    assert json.loads(path.read_text(encoding="utf-8")) == old
