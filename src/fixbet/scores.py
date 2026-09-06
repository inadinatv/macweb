"""Programı bozmadan gerçek durum/skor ekler (ikincil ESPN scoreboard).

Kanal kimliği etkinlik kimliği DEĞİLDİR. Eşleşme aynı spor + yapılandırılmış lig +
yerel tarih + başlangıç saati + iki takımın açık isim eşleşmesiyle yapılır.
Belirsizlikte skor eklenmez. Kaynak kesilirse aynı maçın son bilinen skoru ve
zaman damgası korunur; canlı snapshot saat geçince final diye etiketlenmez.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import re
from datetime import datetime, time, timedelta, timezone
from typing import Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from . import config
from .match_state import SCORE_STATUSES, fold, normalize_status, score_pair
from .models import Match

log = logging.getLogger(__name__)
API_BASE = "https://site.api.espn.com/apis/site/v2/sports/"
OUTCOME_FIELDS = ("status", "status_source", "raw_status", "score_home", "score_away", "score_source",
                  "score_updated_at", "event_id", "starts_at", "fetched_at")


def load_config() -> dict:
    return config._read(config.CONFIG_DIR / "scores.yml")


def start_time(match: Match, day: datetime, tz: ZoneInfo) -> datetime | None:
    if match.starts_at:
        try:
            d = datetime.fromisoformat(match.starts_at.replace("Z", "+00:00"))
            if d.tzinfo:
                return d
        except ValueError:
            pass
    try:
        t = datetime.strptime(match.time, "%H:%M").time()
        return datetime.combine(day.date(), t, tzinfo=tz)
    except ValueError:
        return None


def _identity(m: Match) -> tuple:
    return (fold(m.sport), fold(m.league), fold(m.home), fold(m.away), m.time)


def _fetch(url: str, timeout: float) -> dict:
    response = requests.get(url, headers={"Accept": "application/json", "User-Agent": "macweb-scoreboard/1.0"}, timeout=(5, timeout))
    response.raise_for_status()
    return response.json()


def espn_status(status: dict) -> str | None:
    typ = status.get("type") or {}
    if not isinstance(typ, dict):
        return None
    # İptal/erteleme/DEVRE, genel pre/in/post alanından ÖNCE değerlendirilir.
    for field in ("name", "description", "shortDetail"):
        normalized = normalize_status(typ.get(field))
        if normalized:
            return normalized
    if typ.get("state") == "in":
        return "live"
    if typ.get("state") == "pre":
        return "upcoming"
    # Bilinmeyen bir post durumu otomatik final sayılmaz (walkover vb.).
    return None


def competitions(data: dict) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError("scoreboard events alanı eksik")
    result = []
    for event in data["events"]:
        if not isinstance(event, dict):
            continue
        for comp in event.get("competitions") or []:
            if not isinstance(comp, dict):
                continue
            rows = comp.get("competitors") or []
            home = [c for c in rows if isinstance(c, dict) and c.get("homeAway") == "home"]
            away = [c for c in rows if isinstance(c, dict) and c.get("homeAway") == "away"]
            if len(home) != 1 or len(away) != 1:
                continue
            try:
                date = datetime.fromisoformat(str(comp.get("date") or event.get("date") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if not date.tzinfo:
                continue
            status = comp.get("status") or event.get("status") or {}
            if not isinstance(status, dict):
                continue
            state = espn_status(status)
            if not state:
                continue
            result.append({"id": str(comp.get("id") or event.get("id") or ""), "start": date,
                           "home": home[0], "away": away[0], "status": state,
                           "raw_status": str((status.get("type") or {}).get("name") or "")})
    return result


def _names(competitor: dict, canonical: Callable) -> set[str]:
    team = competitor.get("team") or {}
    if not isinstance(team, dict):
        return set()
    # abbreviations (MAN, UTD vb.) belirsizdir; bilerek eşleştirmiyoruz.
    return {canonical(team.get(key)) for key in ("displayName", "shortDisplayName", "name") if team.get(key)}


def enrich(matches: list[Match], now: datetime, previous: list[Match] | None = None,
           fetch: Callable | None = None, settings: dict | None = None) -> list[Match]:
    cfg = settings if settings is not None else load_config()
    tz = ZoneInfo(config.load_settings().get("bot", {}).get("timezone", "Europe/Istanbul"))
    now = now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz)
    stamp = now.isoformat(timespec="seconds")
    previous_by_key = {}
    for old in previous or []:
        previous_by_key.setdefault(_identity(old), []).append(old)
    # Sonucun kaynağı ve yaşı kaybolmaz. Önceki liste caller tarafından aynı güne
    # sınırlandırılır (load_matches_from_output); tekrar oynanan başka güne taşınmaz.
    for match in matches:
        if match.score_source == "source" and not match.score_updated_at:
            match.score_updated_at = stamp
        if match.status_source != "schedule" or match.score_source:
            continue
        old = previous_by_key.get(_identity(match), [])
        if len(old) == 1 and old[0].status_source != "schedule":
            for field in OUTCOME_FIELDS:
                setattr(match, field, getattr(old[0], field))

    if not cfg.get("enabled", False):
        return matches
    leagues = {(fold(l.get("sport")), fold(l.get("name"))): l.get("path", "") for l in cfg.get("leagues", [])}
    groups: dict[str, list[Match]] = {}
    for match in matches:
        path = leagues.get((fold(match.sport), fold(match.league)), "")
        if path and re.fullmatch(r"[a-z-]+/[a-z0-9.\-]+", path) and match.status_source != "source":
            groups.setdefault(path, []).append(match)
    # ESPN dates UTC günlerini seçer. Türkiye'de gece yarısı maçları için komşu
    # UTC gününü de sorgula, sonra başlangıcı yerel takvim gününe göre doğrula.
    start = datetime.combine(now.date(), time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(now.date(), time.max, tzinfo=tz).astimezone(timezone.utc)
    dates = start.strftime("%Y%m%d") + "-" + end.strftime("%Y%m%d")
    fetch = fetch or _fetch

    def load(path: str):
        url = API_BASE + path + "/scoreboard?" + urlencode({"dates": dates, "limit": 1000})
        try:
            return path, competitions(fetch(url, float(cfg.get("request_timeout_seconds", 8))))
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            log.warning("Skor kaynağı okunamadı (%s, %s); son bilinen veri korunuyor.", path, type(exc).__name__)
            return path, []

    workers = max(1, min(8, int(cfg.get("max_workers", 4))))
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        results = dict(pool.map(load, groups))
    tolerance = timedelta(minutes=max(0, min(180, float(cfg.get("max_start_difference_minutes", 45)))))
    for path, group in groups.items():
        aliases = {fold(k): fold(v) for k, v in (cfg.get("team_aliases", {}).get(path) or {}).items()}

        def canonical(name):
            key = fold(name)
            return aliases.get(key, key)

        for match in group:
            scheduled = start_time(match, now, tz)
            if not scheduled:
                continue
            candidates = [c for c in results[path]
                          if c["start"].astimezone(tz).date() == now.date()
                          and abs(c["start"] - scheduled) <= tolerance
                          and canonical(match.home) in _names(c["home"], canonical)
                          and canonical(match.away) in _names(c["away"], canonical)]
            if len(candidates) != 1:
                continue
            found = candidates[0]
            if match.status == "finished" and match.status_source != "schedule" and found["status"] in ("upcoming", "live", "halftime"):
                # Gecikmiş scoreboard/cache yanıtı doğrulanmış finali geriye alamaz.
                continue
            h, a = score_pair(found["home"].get("score"), found["away"].get("score"))
            prior_status = match.status
            match.status, match.status_source = found["status"], "espn"
            match.raw_status, match.event_id = found["raw_status"], found["id"]
            match.starts_at, match.fetched_at = found["start"].isoformat(), stamp
            if match.status not in SCORE_STATUSES:
                # Sağlayıcının maç öncesi varsayılan 0-0'ını saklama/gösterme.
                match.score_home = match.score_away = None
                match.score_source = match.score_updated_at = ""
            elif h is not None:
                match.score_home, match.score_away = h, a
                match.score_source, match.score_updated_at = "espn", stamp
            elif prior_status != match.status:
                # Eksik final skorunu son canlı skorla doldurmak yanlış sonuç üretir.
                match.score_home = match.score_away = None
                match.score_source = match.score_updated_at = ""
    return matches
