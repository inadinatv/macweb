"""7/24 kanal listesini güncel adresin ana sayfasından çeker.

Sitenin ana sayfasındaki ".channel-item" öğeleri (id -> kanal adı) ayrıştırılır,
marka/gruba göre kategorize edilir ve izleyici bağlantıları üretilir.
"""
from __future__ import annotations

import re
from typing import Any

import requests
from bs4 import BeautifulSoup

from . import config, scraper

# Kanal grubu (marka) sınıflandırması — adlardaki anahtar kelimelerle eşleşir.
BRAND_RULES: list[tuple[str, list[str]]] = [
    ("Bein Sports", ["bein", "beın"]),
    ("S Sport", ["s sport"]),
    ("SmartSpor", ["smartspor", "smart spor"]),
    ("Tivibu Spor", ["tivibu"]),
    ("TRT", ["trt"]),
    ("A Spor", ["a spor"]),
    ("Eurosport", ["euro"]),
    ("Tabii Spor", ["tabii", "tabıı"]),
    ("Genel (Ulusal)", ["atv", "tv 8", "tv8", "trt 1"]),
]


def _brand(name: str) -> str:
    low = name.lower().replace("ı", "i").replace("ş", "s")
    for brand, keywords in BRAND_RULES:
        for kw in keywords:
            if kw in low:
                return brand
    return "Diğer"


def fetch_channels() -> list[dict[str, Any]]:
    """Güncel adresin ana sayfasını çekip kanal listesini döndürür.

    Adres yoksa veya sayfa çekilemezse config/channels.yml'deki sabit listeyi kullanır.
    """
    settings = config.load_settings()
    headers = settings.get("data_source", {}).get("headers", {})
    timeout = settings.get("data_source", {}).get("timeout_seconds", 15)
    base = scraper.current_base_url()

    if base:
        try:
            resp = requests.get(f"{base}/", timeout=timeout, headers=headers)
            if resp.status_code == 200:
                found = _parse_home(resp.text)
                if found:
                    for ch in found:
                        if base:
                            ch["url"] = f"{base}/channel.html?id={ch['channel_id']}"
                    return found
        except requests.exceptions.RequestException:
            pass

    # Yedek: config/channels.yml sabit listesi
    channels = config.load_channels().get("channels", {})
    out = []
    for cid, name in channels.items():
        out.append({
            "channel_id": cid,
            "name": name,
            "status": "7/24",
            "brand": _brand(name),
            "url": (f"{base}/channel.html?id={cid}" if base else None),
        })
    return out


def _parse_home(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in soup.select(".channel-item"):
        name_el = a.select_one(".channel-name")
        status_el = a.select_one(".channel-status")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        cid = a.get("href", "").split("id=")[-1]
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append({
            "channel_id": cid,
            "name": name,
            "status": (status_el.get_text(strip=True) if status_el else "7/24"),
            "brand": _brand(name),
        })
    return out


def categorize(channels: list[dict[str, Any]]) -> dict[str, Any]:
    """Kanalları marka/brand bazında gruplar."""
    by_brand: dict[str, list[dict[str, Any]]] = {}
    for ch in channels:
        by_brand.setdefault(ch["brand"], []).append(ch)

    # Marka sırası: bilinen marka sıralamasına göre, bilinmeyenler sona.
    known_order = [b for b, _ in BRAND_RULES]
    ordered: dict[str, list[dict[str, Any]]] = {}
    for brand in known_order:
        if brand in by_brand:
            ordered[brand] = sorted(by_brand[brand], key=lambda x: x["name"].lower())
    for brand in sorted(set(by_brand) - set(known_order)):
        ordered[brand] = sorted(by_brand[brand], key=lambda x: x["name"].lower())

    return {
        "total": len(channels),
        "by_brand": ordered,
        "channels": sorted(channels, key=lambda x: x["name"].lower()),
    }
