"""Günün maçlarını kategorize eder: canlı / başladı / yaklaşan, spora ve lige göre gruplar."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import config, scraper
from .models import Match
from .match_state import ACTIVE_STATUSES, STATUS_LABELS, normalize_status

status_map = {**{key: label.lower() for key, label in STATUS_LABELS.items()},
              "live": "canlı", "started": "başladı", "upcoming": "yaklaşan", "finished": "bitti"}


def _hhmm_to_minutes(hhmm: str) -> int | None:
    try:
        h, m = hhmm.split(":")
        h, m = int(h), int(m)
        return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None
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
    settings = config.load_settings()
    cat = settings.get("categorize", {})
    tz = ZoneInfo(settings.get("bot", {}).get("timezone", "Europe/Istanbul"))
    local_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    grace = int(cat.get("live_grace_minutes", 0))
    now_min = local_now.hour * 60 + local_now.minute
    for m in matches:
        source_status = normalize_status(m.raw_status) or normalize_status(m.status)
        explicit = m.status_source != "schedule" or normalize_status(m.raw_status) or m.status not in ("upcoming", "live", "finished")
        if source_status and explicit:
            m.status = source_status
            if m.status_source == "schedule":
                m.status_source = "source"
            m.started = source_status in ACTIVE_STATUSES | {"finished", "suspended", "abandoned"}
            continue
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
        if m.starts_at:
            try:
                start = datetime.fromisoformat(m.starts_at.replace("Z", "+00:00"))
                if start.tzinfo:
                    elapsed = (local_now - start).total_seconds() // 60
            except ValueError:
                pass
        else:
            m.starts_at = (local_now - timedelta(minutes=elapsed)).replace(second=0, microsecond=0).isoformat()
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
    other = {s: [] for s in ("postponed", "cancelled", "suspended", "abandoned")}

    for m in matches:
        by_league.setdefault(m.league or cat.get("default_sport", "Bilinmiyor"), []).append(m)
        by_sport.setdefault(m.sport or cat.get("default_sport", "Spor"), []).append(m)
        if m.status in ACTIVE_STATUSES:
            live.append(m)
        elif m.status == "finished":
            finished.append(m)
        elif m.status in other:
            other[m.status].append(m)
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
            **{status: len(group) for status, group in other.items()},
        },
        **{status: bucket(group) for status, group in other.items()},
        "live": bucket(live),
        "upcoming": bucket(upcoming),
        "finished": bucket(finished),
        "match_of_the_day": bucket(match_of_day),
        "by_league": league_bucket(),
        "by_sport": sport_bucket(),
    }
