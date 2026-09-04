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


def classify(matches: list[Match], now: datetime) -> list[Match]:
    """Saate göre canlı / başladı / yaklaşan / bitti durumunu işaretler."""
    now_min = now.hour * 60 + now.minute
    for m in matches:
        mins = _hhmm_to_minutes(m.time)
        if mins is None:
            m.status = "upcoming"
            m.started = False
            continue
        if mins <= now_min - 15:            # maç süresi dolmuş
            m.status = "finished"
            m.started = True
        elif mins <= now_min:               # yayın başlamış
            m.status = "live"
            m.started = True
        else:
            m.status = "upcoming"
            m.started = False
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
