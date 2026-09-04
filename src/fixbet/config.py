"""Yapılandırma (YAML) yükleme / kaydetme yardımcıları."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Proje kökü:  <repo>/src/fixbet/config.py  ->  <repo>/
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
OUTPUT_DIR = ROOT / "output"

SETTINGS = CONFIG_DIR / "settings.yml"
MIRRORS = CONFIG_DIR / "mirrors.yml"
CHANNELS = CONFIG_DIR / "channels.yml"
CURRENT_SITE = CONFIG_DIR / "current_site.yml"  # <-- güncel adres dosyası (otomatik)


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_settings() -> dict[str, Any]:
    return _read(SETTINGS)


def load_mirrors() -> dict[str, Any]:
    return _read(MIRRORS)


def load_channels() -> dict[str, Any]:
    return _read(CHANNELS)


def load_current_site() -> dict[str, Any]:
    """Şu an bilinen en güncel site adresini döndürür (yoksa boş)."""
    return _read(CURRENT_SITE)


def save_current_site(data: dict[str, Any]) -> Path:
    """Güncel site adresini YAML dosyasına yazar (sürekli güncel tutar)."""
    os.makedirs(CURRENT_SITE.parent, exist_ok=True)
    header = (
        "# ============================================================\n"
        "#  GÜNCEL SİTE ADRESİ  (bot tarafından otomatik güncellenir)\n"
        "#  Bu dosya fixbet-bot tarafından yazılır; elle düzenlemeyin.\n"
        "#  Kaynak: config/mirrors.yml  +  sağlık kontrolü\n"
        "# ============================================================\n"
    )
    with open(CURRENT_SITE, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
    return CURRENT_SITE
