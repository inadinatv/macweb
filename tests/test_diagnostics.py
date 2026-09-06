"""Tanılama ve yayımlanmış kaynak kaydı testleri."""
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fixbet import diagnostics, extras, web


class Response:
    def __init__(self, url, body, content_type='text/plain', acao='*'):
        self.url, self.body = url, body
        self.status_code = 200
        self.headers = {'Content-Type': content_type}
        if acao:
            self.headers['Access-Control-Allow-Origin'] = acao
        self.history = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, size):
        yield self.body


def test_diagnostics_redact_urls_detect_playlist_and_cors(monkeypatch):
    root = 'https://cdn.test/master.m3u8?token=secret'
    master = b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1920x1080\nmedia.m3u8?auth=secret\n'
    media = b'#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\ns.jpg?auth=secret\n'
    ts = (bytes([0x47]) + bytes(187)) * 8
    monkeypatch.setattr(diagnostics, '_probe', lambda data: {'checked': False})
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        if 'master' in url:
            return Response(url, master)
        if 'media.m3u8' in url:
            return Response(url, media)
        return Response(url, ts, 'image/jpeg', acao=None)
    out = diagnostics.inspect_context(root, {'User-Agent': 'Test'}, 'https://page.test', fetch)
    assert out['requests'][0]['playlist_type'] == 'master'
    assert out['requests'][0]['declared_resolutions'] == ['1920x1080']
    assert out['requests'][1]['playlist_type'] == 'media'
    assert out['requests'][2]['payload_type'] == 'mpeg-ts'
    assert out['requests'][2]['cors_allows_page_origin'] is False
    assert 'secret' not in json.dumps(out)
    assert all(c[1]['headers']['User-Agent'] == 'Test' for c in calls)


def test_diagnostics_network_failure_is_not_mislabelled_cors():
    def fetch(*args, **kwargs):
        raise requests.exceptions.SSLError('secret')
    out = diagnostics.inspect_context('https://cdn.test/hls?token=secret', {}, 'https://page.test', fetch)
    assert out['requests'][0]['error'] == 'SSLError'
    assert 'cors_allows_page_origin' not in out['requests'][0]
    assert 'secret' not in json.dumps(out)


def test_remote_registry_cache_keeps_last_good_data(monkeypatch):
    url = 'https://example.test/extra_channels.json'
    data = {'panels':[{'id':'atom','channels':[{'id':'atom:one','sources':[{'type':'hls','url':'https://cdn.test/m.m3u8'}]}]}]}
    monkeypatch.setattr(web.config, 'load_settings', lambda: {'playback': {'registry_url': url}})
    monkeypatch.setattr(web, 'validate_url', lambda *args: url)
    monkeypatch.setattr(web, 'public_get', lambda *args, **kwargs: Response(url, json.dumps(data).encode()))
    registry = web.PublishedRegistry()
    assert registry() == data
    def fail(*args, **kwargs):
        raise requests.Timeout()
    monkeypatch.setattr(web, 'public_get', fail)
    registry.next_check = 0
    assert registry() == data


def test_extra_cli_does_not_shadow_site_module(monkeypatch, tmp_path):
    from fixbet import main, site
    monkeypatch.setattr(main, 'refresh_extras', lambda now: {'panels': [], 'total': 0})
    monkeypatch.setattr(main, 'load_matches_from_output', lambda now: [])
    monkeypatch.setattr(main.config, 'OUTPUT_DIR', tmp_path)
    calls = []
    monkeypatch.setattr(site, 'build_index_html', lambda *args, **kwargs: calls.append(True))
    assert main.main(['extras']) == 0
    assert calls == [True]
