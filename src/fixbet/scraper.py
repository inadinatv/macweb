"""Maç listesini kaynağından (data-reality.com) çeker. Güncel adresi okur ve
maç bağlantısı için kullanır (player: https://<güncel-adres>/channel.html?id=...)."""
from __future__ import annotations

import time
from typing import Any

import requests

from . import config


def _get(url: str, settings: dict[str, Any]) -> str:
    headers = settings.get("data_source", {}).get("headers", {})
    timeout = settings.get("data_source", {}).get("timeout_seconds", 15)
    retries = int(settings.get("data_source", {}).get("retries", 3))
    last: Exception | None = None
    for _ in range(max(1, retries)):
        try:
            resp = requests.get(url, timeout=timeout, headers=headers)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.RequestException as exc:
            last = exc
            time.sleep(0.8)
    raise RuntimeError(f"{url} çekilemedi: {last}")


def fetch_matches_html() -> str:
    """Önce zengin formatı (matches.php), yoksa basit formatı dener."""
    settings = config.load_settings()
    ds = settings.get("data_source", {})
    primary = ds.get("primary")
    fallback = ds.get("fallback")
    if primary:
        try:
            return _get(primary, settings)
        except Exception:
            pass
    if fallback:
        return _get(fallback, settings)
    raise RuntimeError("Veri kaynağı ayarlanmamış (data_source.primary/fallback)")


def current_base_url() -> str:
    """Güncel izleme adresi (ör. https://fixbettv84.com) — yoksa boş."""
    cur = config.load_current_site()
    return (cur.get("current_address") or "").rstrip("/")


def player_url(match_id: str) -> str | None:
    """Match ID için tam izleyici bağlantısını üretir."""
    base = current_base_url()
    if not base:
        return None
    return f"{base}/channel.html?id={match_id}"
