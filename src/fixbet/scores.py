"""Programı bozmadan gerçek durum/skor ekler — çok kaynaklı canlı sistem.

Kaynaklar:
  * Türkiye Süper Lig (ve 1. Lig) için birincil: Mackolik livescore (anlık, Türkçe)
  * Diğer ligler ve fallback: ESPN scoreboard (uluslararası)
  * Her ikisi de aynı eşleşme mantığını kullanır (lig + tarih + saat + takım adı).
  * Belirsizlikte skor eklenmez; kaynak kesilirse son bilinen skor korunur.

Yenilenebilir canlı sistem:
  * Her pipeline çalışmasında taze skor çekilir.
  * İstemci sayfada ayrıca yayımlanmış snapshot'ı ve canlı scoreboard'u tazeler.
  * Mackolik + ESPN birlikte okunur; yedek seçimi lig değil maç bazında yapılır.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from . import config
from .match_state import (
    ACTIVE_STATUSES,
    SCORE_STATUSES,
    fold,
    normalize_status,
    score_pair,
)
from .models import Match

log = logging.getLogger(__name__)
API_BASE = "https://site.api.espn.com/apis/site/v2/sports/"
MACKOLIK_LIVESCORE_URL = "https://www.mackolik.com/perform/p0/ajax/components/competition/livescores/json"
MACKOLIK_FOOTBALL_FALLBACK = "mackolik/all-football"

# Mackolik competition IDs — Süper Lig odaklı; diğer ligler ESPN'e düşer.
MACKOLIK_COMP_MAP = {
    "soccer/tur.1": "482ofyysbdbeoxauk19yg7tdt",
    "soccer/tur.2": "2o9svokc5s7diish3ycrzk7jm",
}

OUTCOME_FIELDS = ("status", "status_source", "raw_status", "status_clock", "score_home", "score_away", "score_source",
                  "score_updated_at", "event_id", "starts_at", "fetched_at")

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
    "Referer": "https://www.mackolik.com/",
    "X-Requested-With": "XMLHttpRequest",
}


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


def _fetch_mackolik(date_str: str, timeout: float) -> dict:
    """Mackolik livescore JSON'u çeker (tarih: YYYY-MM-DD)."""
    last: Exception | None = None
    # Mackolik bazen 403 verirse referer ile tekrar dene
    for attempt in range(2):
        try:
            url = f"{MACKOLIK_LIVESCORE_URL}?sports[]=Soccer&matchDate={date_str}"
            r = requests.get(url, headers=_BROWSER_HEADERS, timeout=(5, timeout))
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            last = exc
            if attempt == 0:
                time.sleep(0.5)
                continue
            raise
    raise RuntimeError(f"mackolik çekilemedi {date_str}: {last}")


def _epoch_ms(value) -> int | None:
    """Sağlayıcının milisaniye epoch alanını güvenli biçimde okur."""
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return None
    return stamp if stamp > 0 else None


def _mackolik_clock(entry: dict) -> str:
    """Mackolik canlı futbol saatini ``63'`` / ``İY`` biçimine getirir.

    ``status=minutes`` yanıtında ekranda gösterilecek dakika ayrı bir alan olarak
    gelmez. Sağlayıcının kendi ``lastUpdated`` ve devre başlangıcı
    ``periodStart`` damgaları kullanılır; böylece çalıştıran makinenin saati
    skor dakikasını ileri/geri oynatmaz.
    """
    state = _mackolik_status(entry)
    if state == "halftime":
        return "İY"
    if state != "live":
        return ""

    box = str(entry.get("statusBoxContent") or "").strip().rstrip("'")
    if re.fullmatch(r"\d{1,3}(?:\+\d{1,2})?", box):
        return f"{box}'"

    started = _epoch_ms(entry.get("periodStart"))
    updated = _epoch_ms(entry.get("lastUpdated"))
    if started is None or updated is None or updated < started:
        return ""
    try:
        period = int(entry.get("periodId"))
    except (TypeError, ValueError):
        period = 1

    # Mackolik futbolunda 1=ilk yarı, 2=ikinci yarı. Uzatma dönemleri görülürse
    # bilinen tabanlardan devam eder; bilinmeyen bir dönem yanlış dakika üretmez.
    base = {1: 0, 2: 45, 3: 90, 4: 105}.get(period)
    if base is None:
        return ""
    minute = base + int((updated - started) // 60_000) + 1
    return f"{min(130, max(1, minute))}'"


def espn_status(status: dict) -> str | None:
    typ = status.get("type") or {}
    if not isinstance(typ, dict):
        return None
    for field in ("name", "description", "shortDetail", "detail"):
        normalized = normalize_status(typ.get(field))
        if normalized:
            return normalized
    if typ.get("state") == "in":
        return "live"
    if typ.get("state") == "pre":
        return "upcoming"
    return None


def _mackolik_status(entry: dict) -> str | None:
    """Mackolik durum alanlarını normalize edilmiş status'e çevirir."""
    # Check explicit aliases first via box/substate
    box = entry.get("statusBoxContent")
    sub = entry.get("substate")
    state = entry.get("state")
    status = entry.get("status")

    # Box content like "MS", "İY", "45", "90+3"
    if box is not None:
        b = str(box).strip()
        if b:
            norm = normalize_status(b)
            if norm:
                return norm
            # Minute pattern -> live
            if re.match(r"^\d+(\+\d+)?'?$", b.strip()):
                return "live"
            if b.lower() in ("ms", "ms "):
                return "finished"
            if b.lower() in ("iy", "i.y.", "ht"):
                return "halftime"

    if sub is not None:
        s = str(sub).strip()
        if s:
            # substate values: fullTime, halfTime, postponed, cancelled etc.
            norm = normalize_status(s)
            if norm:
                return norm
            if s.lower() in ("fulltime", "full time", "ft"):
                return "finished"
            if s.lower() in ("halftime", "half time", "ht"):
                return "halftime"
            if s.lower() in ("firsthalf", "secondhalf", "overtime"):
                return "live"

    if state is not None:
        st = str(state).strip().lower()
        if st == "pre":
            return "upcoming"
        if st in ("post", "ended", "completed", "final"):
            return "finished"
        if st in ("inprogress", "live", "progress", "in_progress"):
            return "live"

    if status == "timestamp":
        return "upcoming"
    if status == "state" and state in ("post", "ended", "completed", "final"):
        return "finished"

    # Fallback via statusBoxContent alias already handled
    return None


def _mackolik_competitions(data: dict, tz: ZoneInfo) -> list[dict]:
    """Mackolik livescore JSON'undan ESPN-benzeri competition listesi üretir."""
    if not isinstance(data, dict):
        raise ValueError("mackolik data sözlük değil")
    # Data may be wrapped as {"status":"success","data":{"matches": {...}, "competitions": {...}}}
    inner = data
    if "data" in data and isinstance(data["data"], dict):
        inner = data["data"]
    matches = inner.get("matches")
    if not isinstance(matches, dict):
        # Sometimes matches is list? but observed dict keyed by id
        if isinstance(inner.get("matches"), list):
            matches = {m.get("id", str(i)): m for i, m in enumerate(inner["matches"]) if isinstance(m, dict)}
        else:
            raise ValueError("mackolik matches alanı eksik")

    result: list[dict] = []
    for mid, entry in matches.items():
        if not isinstance(entry, dict):
            continue
        mst = entry.get("mstUtc")
        if mst is None:
            continue
        try:
            ts = int(mst)
            # mstUtc is ms since epoch UTC
            start = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            continue
        home_team = entry.get("homeTeam") or {}
        away_team = entry.get("awayTeam") or {}
        home_name = str(home_team.get("name") or "").strip()
        away_name = str(away_team.get("name") or "").strip()
        if not home_name or not away_name:
            continue
        status = _mackolik_status(entry)
        # If status couldn't be determined, infer from score/state
        if not status:
            # If score present and state post -> finished, else if pre -> upcoming
            score = entry.get("score") or {}
            if score.get("home") not in (None, "", " ") and entry.get("state") == "post":
                status = "finished"
            elif entry.get("state") == "pre":
                status = "upcoming"
            else:
                continue

        # Skip unknown post states that are not finales (walkover etc.) similar to ESPN logic: if status is None we already continued
        # But ensure non-SCORE_STATUSES upcoming etc. not filtered? We keep all statuses that normalize_status maps, like postponed.
        # If status is upcoming/live/halftime/finished/postponed etc., keep; if still None skip already.

        # Build competitor-like structures for matching
        score_obj = entry.get("score") or entry.get("scores") or {}
        if isinstance(score_obj, dict):
            home_score = score_obj.get("home") if score_obj.get("home") is not None else score_obj.get("currentHome")
            away_score = score_obj.get("away") if score_obj.get("away") is not None else score_obj.get("currentAway")
        elif isinstance(score_obj, str) and "-" in score_obj:
            parts = score_obj.split("-")
            home_score, away_score = parts[0].strip(), parts[1].strip()
        else:
            home_score = away_score = None

        if home_score is None:
            home_score = entry.get("homeScore") if entry.get("homeScore") is not None else entry.get("scoreHome")
        if away_score is None:
            away_score = entry.get("awayScore") if entry.get("awayScore") is not None else entry.get("scoreAway")

        home_comp = {"team": {"displayName": home_name, "name": home_name, "shortDisplayName": home_name}, "score": str(home_score) if home_score not in (None, "") else None}
        away_comp = {"team": {"displayName": away_name, "name": away_name, "shortDisplayName": away_name}, "score": str(away_score) if away_score not in (None, "") else None}

        raw = str(entry.get("statusBoxContent") or entry.get("substate") or entry.get("state") or "")

        # competitionId for filtering per league if needed
        comp_id = entry.get("competitionId") or ""

        result.append({
            "id": str(entry.get("id") or mid),
            "start": start,
            "home": home_comp,
            "away": away_comp,
            "status": status,
            "neutral": False,
            "raw_status": raw,
            "clock": _mackolik_clock(entry),
            "competitionId": str(comp_id),
            # Keep original for debug
            "_raw": entry,
        })
    return result


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
            typ = status.get("type") or {}
            clock = str(status.get("displayClock") or typ.get("shortDetail") or "").strip()
            if state == "halftime":
                clock = "İY"
            elif state not in ACTIVE_STATUSES:
                clock = ""
            result.append({"id": str(comp.get("id") or event.get("id") or ""), "start": date,
                           "home": home[0], "away": away[0], "status": state,
                           "neutral": bool(comp.get("neutralSite")),
                           "raw_status": str(typ.get("name") or ""), "clock": clock})
    return result


def _names(competitor: dict, canonical: Callable) -> set[str]:
    team = competitor.get("team") or {}
    if not isinstance(team, dict):
        return set()
    # abbreviations belirsizdir; bilerek eşleştirmiyoruz.
    # Mackolik için displayName zaten düzgün Türkçe; fold + alias ile eşle.
    names = set()
    for key in ("displayName", "shortDisplayName", "name"):
        val = team.get(key)
        if val:
            names.add(canonical(val))
            # Also try without FK/SK suffix for Turkish teams
            folded = canonical(val)
            # Remove common suffixes for broader matching
            for suffix in (" fk", " sk", " as", " spor", "spor"):
                if folded.endswith(suffix):
                    names.add(folded[: -len(suffix)].strip())
                    break
    return names


def enrich(matches: list[Match], now: datetime, previous: list[Match] | None = None,
           fetch: Callable | None = None, settings: dict | None = None) -> list[Match]:
    cfg = settings if settings is not None else load_config()
    tz = ZoneInfo(config.load_settings().get("bot", {}).get("timezone", "Europe/Istanbul"))
    now = now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz)
    stamp = now.isoformat(timespec="seconds")
    previous_by_key = {}
    for old in previous or []:
        previous_by_key.setdefault(_identity(old), []).append(old)
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
        if not path and cfg.get("mackolik_all_football", True) and fold(match.sport) == "futbol":
            path = MACKOLIK_FOOTBALL_FALLBACK
        if path and re.fullmatch(r"[a-z-]+/[a-z0-9.\-]+", path) and match.status_source != "source":
            groups.setdefault(path, []).append(match)

    if not groups:
        return matches

    # --- Mackolik denemesi (Türk ligleri için birincil) ---
    mackolik_results: dict[str, list[dict]] = {}
    football_paths = [p for p in groups if p in MACKOLIK_COMP_MAP or p == MACKOLIK_FOOTBALL_FALLBACK]
    if football_paths:
        try:
            timeout = float(cfg.get("request_timeout_seconds", 8))
            # Mackolik tarih parametresi yerel tarihe göre
            date_str = now.date().isoformat()
            # For live continuity, also check tomorrow's early matches? But we query today only; matching will filter by now.date().
            # For robustness, if now is after 23:00, also fetch next day? Not needed; ESPN logic uses range 2 days.
            # Keep simple: fetch today.
            m_data = _fetch_mackolik(date_str, timeout)
            comps = _mackolik_competitions(m_data, tz)
            # Filter per path by competitionId if mapping exists, otherwise keep all and let name matching decide
            for path in football_paths:
                wanted_id = MACKOLIK_COMP_MAP.get(path)
                if wanted_id:
                    filtered = [c for c in comps if c.get("competitionId") == wanted_id]
                    # If filtered empty but we had comps, perhaps id changed; fallback to name matching across all
                    if filtered:
                        mackolik_results[path] = filtered
                    else:
                        # Fallback: use all comps but matching will still narrow by team names
                        mackolik_results[path] = comps
                else:
                    mackolik_results[path] = comps
            log.info("Mackolik skor çekildi (%s maç, %s lig)", len(comps), len(football_paths))
        except Exception as exc:
            log.warning("Mackolik skor kaynağı okunamadı (%s); ESPN'e düşülüyor.", type(exc).__name__)
            mackolik_results = {}

    # --- ESPN için hazırlık (UTC tarih aralığı) ---
    start = datetime.combine(now.date(), dtime.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(now.date(), dtime.max, tzinfo=tz).astimezone(timezone.utc)
    dates = start.strftime("%Y%m%d") + "-" + end.strftime("%Y%m%d")
    fetch = fetch or _fetch

    # ESPN her yapılandırılmış lig için okunur. Mackolik'in bir ligde herhangi bir
    # maç döndürmüş olması, aynı ligdeki başka bir karşılaşmanın ESPN yedeğini
    # kapatmamalıdır; sağlayıcı seçimi aşağıda maç başına yapılır.
    espn_paths = [path for path in groups if path != MACKOLIK_FOOTBALL_FALLBACK]
    def load(path: str):
        # Bazı ESPN ligleri UTC gün aralığını kabul ederken bazı turnuvalar (örn.
        # UEFA Kadınlar Şampiyonlar Ligi) sadece tek YYYYMMDD kabul ediyor.
        query_days = [dates]
        local_day = now.strftime("%Y%m%d")
        if local_day not in query_days:
            query_days.append(local_day)
        last: Exception | None = None
        for query_day in query_days:
            url = API_BASE + path + "/scoreboard?" + urlencode({"dates": query_day, "limit": 1000})
            try:
                return path, competitions(fetch(url, float(cfg.get("request_timeout_seconds", 8))))
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                last = exc
        log.warning("Skor kaynağı okunamadı (%s, %s); son bilinen veri korunuyor.",
                    path, type(last).__name__ if last else "unknown")
        return path, []

    workers = max(1, min(8, int(cfg.get("max_workers", 4))))
    espn_results: dict[str, list[dict]] = {}
    if espn_paths:
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            espn_results = dict(pool.map(load, espn_paths))

    tolerance = timedelta(minutes=max(0, min(180, float(cfg.get("max_start_difference_minutes", 45)))))
    for path, group in groups.items():
        aliases = {fold(k): fold(v) for k, v in (cfg.get("team_aliases", {}).get(path) or {}).items()}

        def canonical(name):
            key = fold(name)
            # Direct alias
            if key in aliases:
                return aliases[key]
            # Also try stripping FK/SK for both sides
            for suffix in (" fk", " sk", " as"):
                if key.endswith(suffix):
                    base = key[: -len(suffix)].strip()
                    if base in aliases:
                        return aliases[base]
                    # Also return base for matching if alias not found
                    # We return base folded for broader matching; but keep original if no alias
            return key

        def orientation(comp, match):
            if canonical(match.home) in _names(comp["home"], canonical) and canonical(match.away) in _names(comp["away"], canonical):
                return "straight"
            if comp.get("neutral") and canonical(match.home) in _names(comp["away"], canonical) \
                    and canonical(match.away) in _names(comp["home"], canonical):
                return "swapped"
            return None

        for match in group:
            scheduled = start_time(match, now, tz)
            if not scheduled:
                continue
            # İki sağlayıcı da okunur. Belirsizlik bir sağlayıcıda skor üretmez;
            # diğeri yine kesin eşleşme bulabilir. Durumlar çelişirse final veya
            # oynanmayacak durum, gecikmiş canlı/başlamadı kaydından üstündür.
            provider_picks: list[tuple[dict, str, str]] = []
            providers = (("mackolik", mackolik_results.get(path, [])),
                         ("espn", espn_results.get(path, [])))
            for src_tag, provider_rows in providers:
                candidates = [(c, orientation(c, match)) for c in provider_rows
                              if c["start"].astimezone(tz).date() == now.date()
                              and abs(c["start"] - scheduled) <= tolerance]
                candidates = [(c, o) for c, o in candidates if o]
                if len(candidates) > 1:
                    candidates.sort(key=lambda x: abs(x[0]["start"] - scheduled))
                    first = abs(candidates[0][0]["start"] - scheduled)
                    second = abs(candidates[1][0]["start"] - scheduled)
                    candidates = [candidates[0]] if first != second else []
                if len(candidates) == 1:
                    provider_picks.append((candidates[0][0], candidates[0][1], src_tag))
            if not provider_picks:
                continue
            status_rank = {"finished": 4, "postponed": 4, "cancelled": 4, "abandoned": 4,
                           "suspended": 4, "live": 3, "halftime": 3, "upcoming": 1}
            picked = max(provider_picks, key=lambda row: status_rank.get(row[0]["status"], 0))
            found, side, src_tag = picked
            if match.status == "finished" and match.status_source != "schedule" and found["status"] in ("upcoming", "live", "halftime"):
                continue
            ours_home, ours_away = (found["home"], found["away"]) if side == "straight" else (found["away"], found["home"])
            h, a = score_pair(ours_home.get("score"), ours_away.get("score"))
            prior_status = match.status
            match.status, match.status_source = found["status"], src_tag
            match.raw_status, match.event_id = found["raw_status"], found["id"]
            match.starts_at, match.fetched_at = found["start"].isoformat(), stamp
            match.status_clock = found.get("clock", "") if match.status in ACTIVE_STATUSES else ""
            if match.status not in SCORE_STATUSES:
                match.score_home = match.score_away = None
                match.score_source = match.score_updated_at = ""
            elif h is not None:
                match.score_home, match.score_away = h, a
                match.score_source, match.score_updated_at = src_tag, stamp
            elif prior_status != match.status:
                match.score_home = match.score_away = None
                match.score_source = match.score_updated_at = ""
    return matches
