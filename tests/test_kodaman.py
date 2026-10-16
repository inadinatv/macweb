"""Kodaman public-page ID refresh tests. Only visible iframe/link references are in scope."""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402
from fixbet.kodaman import (
    PublicPage,
    PublicSourceUnavailable,
    _next_host,
    _validated_url,
    extract_visible_channels,
    refresh_manifest,
)


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


def test_refresh_uses_public_next_domain_notice_and_checks_visible_player(tmp_path):
    homepage21 = '''<title>Kodaman TV</title>
      <a>Bir sonraki alan adımız bir sayı artarak devam edecektir.</a>
      <iframe src="/channel?id=old"></iframe>'''
    homepage22 = '''<title>Kodaman TV</title>
      <iframe src="/channel?id=zirve" title="Zirve Stream"></iframe>'''
    pages = {
        "https://kodamantv21.com/": PublicPage("https://kodamantv21.com/", 200, homepage21),
        "https://kodamantv22.com/": PublicPage("https://kodamantv22.com/", 200, homepage22),
        "https://kodamantv22.com/channel?id=zirve": PublicPage(
            "https://kodamantv22.com/channel?id=zirve", 200, "<html>Player page loaded</html>"
        ),
    }
    calls = []

    def fake_fetch(url):
        calls.append(url)
        if url not in pages:
            raise OSError("unavailable")
        return pages[url]

    manifest, changed = refresh_manifest(
        path=tmp_path / "kodaman_channels.json",
        fetcher=fake_fetch,
        now=datetime(2026, 10, 16, 19, 0, tzinfo=timezone.utc),
    )
    assert changed
    assert manifest["base_url"] == "https://kodamantv22.com"
    assert manifest["channels"] == [{"id": "zirve", "name": "Zirve Stream", "status": "page"}]
    assert calls == [
        "https://kodamantv21.com/",
        "https://kodamantv22.com/",
        "https://kodamantv22.com/channel?id=zirve",
    ]


def test_player_error_is_reported_without_exposing_stream_url(tmp_path):
    home = '''<title>Kodaman TV</title><iframe src="/channel?id=zirve"></iframe>'''
    pages = {
        "https://kodamantv21.com/": PublicPage("https://kodamantv21.com/", 200, home),
        "https://kodamantv21.com/channel?id=zirve": PublicPage(
            "https://kodamantv21.com/channel?id=zirve", 200, "Hay Aksi! hls:networkError_manifestLoadError"
        ),
    }

    def fake_fetch(url):
        if url not in pages:
            raise OSError("unavailable")
        return pages[url]

    manifest, _ = refresh_manifest(path=tmp_path / "manifest.json", fetcher=fake_fetch)
    assert manifest["channels"] == [{"id": "zirve", "name": "Zirve Stream", "status": "error"}]
    serialized = json.dumps(manifest)
    assert "m3u8" not in serialized and "stream_url" not in serialized


def test_failed_refresh_preserves_last_known_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    old = {"base_url": "https://kodamantv21.com", "updated_at": "old", "channels": [{"id": "zirve"}]}
    path.write_text(json.dumps(old), encoding="utf-8")

    def unavailable(_url):
        raise OSError("network down")

    with pytest.raises(PublicSourceUnavailable):
        refresh_manifest(path=path, fetcher=unavailable)
    assert json.loads(path.read_text(encoding="utf-8")) == old
