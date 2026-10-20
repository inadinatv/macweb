import base64
import io
import json

import pytest
from urllib.error import HTTPError
from unittest.mock import patch

from tools.pydroid_channel_sync_bot import (
    ChannelSyncBot,
    GitHubManifest,
    clean_channel_name,
    extract_public_iframe_url,
    normalize_manifest,
)


def test_accepts_public_https_url_and_single_iframe_src():
    assert extract_public_iframe_url("https://embed.example/watch?id=123") == "https://embed.example/watch?id=123"
    assert extract_public_iframe_url('<iframe src="https://embed.example/watch?id=123" allowfullscreen></iframe>') == "https://embed.example/watch?id=123"


@pytest.mark.parametrize(
    "value",
    [
        "http://embed.example/watch",
        "https://user:pass@embed.example/watch",
        "https://localhost/watch",
        "https://127.0.0.1/watch",
        "https://10.0.0.5/watch",
        "https://embed.example/watch?access_token=private",
        '<iframe src="https://embed.example/a"></iframe><iframe src="https://embed.example/b"></iframe>',
        '<iframe src="https://embed.example/a"></iframe><script>alert(1)</script>',
        "<script>alert(1)</script>",
    ],
)
def test_rejects_unsafe_or_non_public_iframe_values(value):
    with pytest.raises(ValueError):
        extract_public_iframe_url(value)


def test_channel_names_are_trimmed_and_control_characters_removed():
    assert clean_channel_name("  Kanal\n  İki  ") == "Kanal İki"
    with pytest.raises(ValueError):
        clean_channel_name("   ")
    with pytest.raises(ValueError):
        clean_channel_name("x" * 49)


def test_manifest_uses_only_five_slots_and_safe_values():
    manifest = normalize_manifest({
        "updatedAt": "2026-10-20T10:00:00Z",
        "channel1": {"name": "Kanal 1", "iframeUrl": "https://embed.example/1"},
        "channel2": {"name": "HTTP", "iframeUrl": "http://embed.example/2"},
        "channel5": {"name": "Kanal 5", "iframeUrl": "https://embed.example/5"},
        "channel6": {"name": "Fazla", "iframeUrl": "https://embed.example/6"},
    })
    assert list(manifest) == ["channel1", "channel5", "updatedAt"]
    assert manifest["channel1"]["iframeUrl"] == "https://embed.example/1"
    assert "channel6" not in manifest


def test_telegram_access_is_private_and_restricted_to_numeric_admin_id():
    bot = ChannelSyncBot({
        "telegram_bot_token": "test-token",
        "github_token": "test-github-token",
        "admin_telegram_user_id": 123456,
    })
    assert bot.require_private_admin({"id": 123456}, {"type": "private"})
    assert not bot.require_private_admin({"id": 123457}, {"type": "private"})
    assert not bot.require_private_admin({"id": 123456}, {"type": "group"})


def test_github_conflict_retry_preserves_other_channels(monkeypatch):
    remote_doc = {
        "channel1": {"name": "Mevcut", "iframeUrl": "https://embed.example/1"},
    }
    sha = "sha-1"
    conflict_once = True
    successful_put_payloads = []

    class Response:
        def __init__(self, payload, status=200):
            self.status = status
            self.payload = json.dumps(payload).encode("utf-8")

        def read(self):
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def api(request, timeout=0):
        nonlocal remote_doc, sha, conflict_once
        if request.get_method() == "GET":
            encoded = base64.b64encode(json.dumps(remote_doc).encode("utf-8")).decode("ascii")
            return Response({"sha": sha, "content": encoded})
        payload = json.loads(request.data.decode("utf-8"))
        if conflict_once:
            conflict_once = False
            remote_doc["channel2"] = {"name": "Eşzamanlı", "iframeUrl": "https://embed.example/2"}
            sha = "sha-2"
            raise HTTPError(request.full_url, 409, "Conflict", None, io.BytesIO(b""))
        successful_put_payloads.append(payload)
        remote_doc = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
        sha = "sha-3"
        return Response({"content": {"sha": sha}}, status=200)

    with patch("tools.pydroid_channel_sync_bot.urlopen", side_effect=api):
        updated = GitHubManifest("test-github-token").set_channel(3, "Yeni Kanal", "https://embed.example/3")

    assert updated["channel1"]["name"] == "Mevcut"
    assert updated["channel2"]["name"] == "Eşzamanlı"
    assert updated["channel3"]["name"] == "Yeni Kanal"
    assert successful_put_payloads[0]["sha"] == "sha-2"
    assert successful_put_payloads[0]["branch"] == "main"
