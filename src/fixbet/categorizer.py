"""Günün maçlarını kategorize eder: canlı / başladı / yaklaşan, spora ve lige göre gruplar."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from . import config, scraper
from .models import Match

status_map = {"live": "canlı", "started": "başladı", "upcoming": "yaklaşan", "finished": "bitti"}


def _hhmm_to_minutes(hhmm: str) -> int | None:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def live_window_minutes(sport: str, cat: dict[str, Any] | None = None) -> int:
    """Bir maçın ortalama yayın süresi (dakika) — "canlı" sayılacağı pencere.

    Eski davranış her maçı başlangıçtan 15 dk sonra "bitti" sayıyordu; bu yüzden
    canlı listesi neredeyse hiç dolmuyordu. Süre artık spora göre ayarlanabilir.
    """
    cat = cat if cat is not None else config.load_settings().get("categorize", {})
    default = int(cat.get("live_window_minutes", 120))
    by_sport = cat.get("live_window_by_sport") or {}
    key = str(sport or "").lower().replace("ı", "i").replace("İ", "i").replace("ş", "s") \
        .replace("ğ", "g").replace("ü", "u").replace("ö", "o").replace("ç", "c")
    for name, minutes in by_sport.items():
        if str(name).lower().replace("ı", "i").replace("İ", "i").replace("ş", "s") \
                .replace("ğ", "g").replace("ü", "u").replace("ö", "o").replace("ç", "c") == key:
            return int(minutes)
    return default


def classify(matches: list[Match], now: datetime) -> list[Match]:
    """Saate göre canlı / yaklaşan / bitti durumunu işaretler.

    * başlangıç saati ilerideyse -> yaklaşan
    * başlangıç + yayın penceresi içindeysek -> canlı
    * pencere dolduysa -> bitti
    Gece yarısını geçen maçlar (23:xx -> 00:xx) da doğru hesaplanır.
    """
    cat = config.load_settings().get("categorize", {})
    grace = int(cat.get("live_grace_minutes", 0))
    now_min = now.hour * 60 + now.minute
    for m in matches:
        mins = _hhmm_to_minutes(m.time)
        if mins is None:
            m.status = "upcoming"
            m.started = False
            continue
        # gece yarısı düzeltmesi: maç 20:00'den sonra, saat 03:00'ten önceyse
        if now_min < 3 * 60 and mins > 20 * 60:
            elapsed = now_min + 24 * 60 - mins
        else:
            elapsed = now_min - mins
        elapsed += grace
        if elapsed < 0:
            m.status = "upcoming"
            m.started = False
        elif elapsed <= live_window_minutes(m.sport, cat):
            m.status = "live"
            m.started = True
        else:
            m.status = "finished"
            m.started = True
    return matches


def enrich(matches: list[Match]) -> list[Match]:
    """Kanal adı ve izleyici bağlantısı ekler."""
    channels = config.load_channels().get("channels", {})
    base = scraper.current_base_url()
    for m in matches:
        m.channel_id = m.match_id
        # Kanal adı eşleşmesi (sadece bilinen id'lerde)
        if m.match_id in channels:
            m.league = m.league  # lig bilgisi korunur
        if base:
            m.url = f"{base}/channel.html?id={m.match_id}"
    return matches


def categorize(matches: list[Match], now: datetime) -> dict[str, Any]:
    """Günün maçlarını kategorize edip sözlük olarak döndürür."""
    settings = config.load_settings()
    cat = settings.get("categorize", {})

    by_league: dict[str, list[Match]] = {}
    by_sport: dict[str, list[Match]] = {}
    live: list[Match] = []
    finished: list[Match] = []
    upcoming: list[Match] = []
    match_of_day: list[Match] = []

    for m in matches:
        by_league.setdefault(m.league or cat.get("default_sport", "Bilinmiyor"), []).append(m)
        by_sport.setdefault(m.sport or cat.get("default_sport", "Spor"), []).append(m)
        if m.status == "live":
            live.append(m)
        elif m.status == "finished":
            finished.append(m)
        else:
            upcoming.append(m)
        if m.is_match_of_day:
            match_of_day.append(m)

    def bucket(group: list[Match]) -> list[dict]:
        return [m.to_dict() for m in sorted(group, key=lambda x: (x.time or "99:99"))]

    def league_bucket() -> dict[str, list[dict]]:
        out = {}
        for name, group in sorted(by_league.items()):
            out[name] = bucket(group)
        return out

    def sport_bucket() -> dict[str, list[dict]]:
        out = {}
        for name, group in sorted(by_sport.items()):
            out[name] = bucket(group)
        return out

    return {
        "meta": {
            "generated_at": now.isoformat(timespec="seconds"),
            "date": now.strftime("%Y-%m-%d"),
            "total_matches": len(matches),
        },
        "counts": {
            "total": len(matches),
            "live": len(live),
            "upcoming": len(upcoming),
            "finished": len(finished),
            "match_of_day": len(match_of_day),
        },
        "live": bucket(live),
        "upcoming": bucket(upcoming),
        "finished": bucket(finished),
        "match_of_the_day": bucket(match_of_day),
        "by_league": league_bucket(),
        "by_sport": sport_bucket(),
    }
