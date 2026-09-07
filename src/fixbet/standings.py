"""Lig puan durumu: gerçek kaynaktan (ESPN standings) çekilen PUAN DURUMU tablosu.

Sayfadaki **LİG PUANI** modalı bu modülün ürettiği ``output/standings.json``
dosyasını ve index.html'e gömülen kopyayı gösterir.

Skor modülündeki (``scores.py``) ilkeler aynen geçerlidir:
  * Sayfa asla uydurma/sabit puan tablosu göstermez; satır yoksa tablo boştur.
  * Sıra, O/G/B/M, averaj ve puan değerleri kaynaktan geldiği gibi yazılır.
  * Kaynak bir lig için erişilemezse o ligin **son bilinen** tablosu korunur
    (``output/standings.json``); ağ tamamen kesikse dosya olduğu gibi kalır.
  * Yalnızca kaynak averaj alanını hiç vermediğinde (attığı - yediği) farkı
    hesaplanır; puan eksikse G*3+B kuralı uygulanır. Bu iki türetme de
    kaynağın kendi sayılarından yapılır, yeni sayı uydurulmaz.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import re
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from . import config

log = logging.getLogger(__name__)
API_BASE = "https://site.api.espn.com/apis/v2/sports/"
STANDINGS_CONFIG = config.CONFIG_DIR / "standings.yml"
STANDINGS_OUTPUT = config.OUTPUT_DIR / "standings.json"
# Sayfanın canlı tazeleme için okuduğu yol (GitHub Pages köküne göre)
STANDINGS_SOURCE = "output/standings.json"

# fetch(url, timeout) -> dict  (scores.py ile aynı imza)
Fetcher = Callable[[str, float], dict]

_STAT_ALIASES = {
    "played": ("gamesPlayed", "gamesplayed", "played"),
    "wins": ("wins",),
    "draws": ("ties", "draws"),
    "losses": ("losses",),
    "goalsFor": ("pointsFor", "pointsfor", "goalsFor"),
    "goalsAgainst": ("pointsAgainst", "pointsagainst", "goalsAgainst"),
    "diff": ("pointDifferential", "pointdifferential", "goalDifference"),
    "points": ("points",),
    "rank": ("rank", "playoffSeed"),
}


def load_config() -> dict:
    return config._read(STANDINGS_CONFIG)


def _fetch(url: str, timeout: float) -> dict:
    response = requests.get(url, headers={"Accept": "application/json",
                                          "User-Agent": "macweb-standings/1.0"},
                            timeout=(5, timeout))
    response.raise_for_status()
    return response.json()


def _int(value: Any) -> int | None:
    """Kaynak sayısını tam sayıya çevirir; sayı olmayan değeri None yapar."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def stat_map(stats: Any) -> dict[str, int | None]:
    """ESPN stats dizisini {alan: sayı} haritasına indirger.

    Her istatistiğin ``name`` (veya ``type``) anahtarı kullanılır; aynı alanın
    bilinen tüm adları (ör. soccer'da beraberlik = ``ties``) tek anahtara bağlanır.
    """
    raw: dict[str, Any] = {}
    for item in stats or []:
        if not isinstance(item, dict):
            continue
        key = item.get("name") or item.get("type")
        if key and key not in raw:
            raw[str(key)] = item.get("value")
    out: dict[str, int | None] = {}
    for field, names in _STAT_ALIASES.items():
        out[field] = next((v for v in (_int(raw.get(n)) for n in names) if v is not None), None)
    return out


def parse_entry(entry: dict, display: Callable[[str], str]) -> dict | None:
    """Tek bir takım satırını normalize eder; takım adı/O yoksa satırı atar."""
    if not isinstance(entry, dict):
        return None
    team = entry.get("team") or {}
    if not isinstance(team, dict):
        return None
    name = next((str(team[k]).strip() for k in ("displayName", "shortDisplayName", "name", "location")
                 if team.get(k)), "")
    if not name:
        return None
    row = stat_map(entry.get("stats"))
    # O (oynanan maç) yoksa satır anlamsız; eksik alan uydurulmaz, satır atlanır.
    if row["played"] is None:
        return None
    wins, draws, losses = row["wins"], row["draws"], row["losses"]
    if None in (wins, draws, losses):
        return None
    gf, ga = row["goalsFor"], row["goalsAgainst"]
    diff = row["diff"]
    if diff is None and gf is not None and ga is not None:
        diff = gf - ga
    points = row["points"]
    if points is None:
        points = wins * 3 + draws
    note = entry.get("note") or {}
    logos = team.get("logos") or []
    logo = next((l.get("href") for l in logos if isinstance(l, dict) and l.get("href")), "")
    return {
        "rank": row["rank"],
        "team": display(name),
        "sourceTeam": name,
        "abbr": str(team.get("abbreviation") or ""),
        "logo": str(logo or ""),
        "played": row["played"],
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goalsFor": gf,
        "goalsAgainst": ga,
        "diff": diff,
        "points": points,
        "note": str(note.get("description") or "") if isinstance(note, dict) else "",
    }


def _sort_key(row: dict, index: int) -> tuple:
    """Kaynak sırası varsa onu, yoksa puan → averaj → atılan gol → ad sırasını kullan."""
    return (row["rank"] if row["rank"] is not None else 999,
            -(row["points"] or 0), -(row["diff"] or 0), -(row["goalsFor"] or 0),
            row["team"], index)


def parse_league(data: Any, league: dict, display: Callable[[str], str]) -> list[dict]:
    """ESPN standings yanıtından satırları çıkarır (children'lı ve düz şema)."""
    if not isinstance(data, dict):
        raise ValueError("standings yanıtı sözlük değil")
    blocks: list[dict] = []
    if isinstance(data.get("standings"), dict):
        blocks.append(data["standings"])
    for child in data.get("children") or []:
        if isinstance(child, dict) and isinstance(child.get("standings"), dict):
            blocks.append(child["standings"])
    rows: list[dict] = []
    for block in blocks:
        entries = block.get("entries")
        if not isinstance(entries, list):
            continue
        parsed = [parse_entry(e, display) for e in entries]
        parsed = [p for p in parsed if p]
        if len(parsed) > len(rows):
            rows = parsed
    if not rows:
        raise ValueError("standings entries alanı boş")
    # Sıralama anahtarı özgün konuma ihtiyaç duyar; sort() sırasında liste boş
    # göründüğü için rows.index() KULLANILMAZ, konum enumerate ile taşınır.
    rows = [row for _, row in sorted(enumerate(rows), key=lambda pair: _sort_key(pair[1], pair[0]))]
    for position, row in enumerate(rows, start=1):
        if row["rank"] is None:
            row["rank"] = position
    return rows


def league_payload(data: Any, league: dict, cfg: dict, fetched_at: str) -> dict:
    path = str(league.get("path") or "")
    names = {str(k): str(v) for k, v in (cfg.get("display_names", {}).get(path) or {}).items()}

    def display(name: str) -> str:
        return names.get(name, name)

    rows = parse_league(data, league, display)
    season = ""
    for block in [data.get("standings")] + [c.get("standings") for c in data.get("children") or []
                                            if isinstance(c, dict)]:
        if isinstance(block, dict) and block.get("seasonDisplayName"):
            season = str(block["seasonDisplayName"])
            break
    for row in rows:
        played, w, d, l = row["played"], row["wins"], row["draws"], row["losses"]
        if None not in (played, w, d, l) and w + d + l != played:
            log.warning("Puan tablosu tutarsız (%s): G+B+M=%s ama O=%s — kaynak değerleri korunuyor.",
                        row["team"], w + d + l, played)
    return {
        "id": path,
        "name": str(league.get("name") or path),
        "sport": str(league.get("sport") or "Futbol"),
        "season": season,
        "updated_at": fetched_at,
        "teams": len(rows),
        "rows": rows,
    }


def _valid_path(path: str) -> bool:
    return bool(re.fullmatch(r"[a-z-]+/[a-z0-9.\-]+", path or ""))


def _previous(now: datetime | None = None) -> dict:
    """Son bilinen tabloyu okur (kaynak kesildiğinde korunacak veri)."""
    if not STANDINGS_OUTPUT.exists():
        return {}
    try:
        data = json.loads(STANDINGS_OUTPUT.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def refresh(now: datetime | None = None, fetch: Fetcher | None = None,
            write: bool = True, settings: dict | None = None) -> dict:
    """Puan durumunu yeniler ve output/standings.json'a yazar.

    Bir lig çekilemezse o ligin son bilinen tablosu aynen korunur; böylece ağ
    hatası sayfada "boş tablo"ya dönüşmez.
    """
    cfg = settings if settings is not None else load_config()
    tz = ZoneInfo(config.load_settings().get("bot", {}).get("timezone", "Europe/Istanbul"))
    now = now or datetime.now(tz)
    now = now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz)
    stamp = now.isoformat(timespec="seconds")
    previous = _previous(now)
    prev_by_id = {l.get("id"): l for l in previous.get("leagues", []) if isinstance(l, dict)}

    leagues_out: list[dict] = []
    if cfg.get("enabled", False):
        fetch = fetch or _fetch
        wanted = [l for l in cfg.get("leagues", []) if _valid_path(str(l.get("path") or ""))]
        timeout = float(cfg.get("request_timeout_seconds", 8))

        def load(league: dict):
            url = API_BASE + str(league["path"]) + "/standings"
            try:
                return league, league_payload(fetch(url, timeout), league, cfg, stamp)
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                log.warning("Puan durumu okunamadı (%s, %s); son bilinen tablo korunuyor.",
                            league["path"], type(exc).__name__)
                return league, None

        workers = max(1, min(8, int(cfg.get("max_workers", 4))))
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            for league, payload in pool.map(load, wanted):
                if payload:
                    leagues_out.append(payload)
                elif prev_by_id.get(league["path"]):
                    leagues_out.append(prev_by_id[league["path"]])
    else:
        leagues_out = list(previous.get("leagues", []))

    data = {"source": "espn", "generated_at": stamp, "leagues": leagues_out}
    if write:
        import os
        os.makedirs(STANDINGS_OUTPUT.parent, exist_ok=True)
        STANDINGS_OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def load_or_build(now: datetime | None = None) -> dict:
    """Ağ kullanmadan son bilinen puan durumunu döndürür (çevrimdışı üretim)."""
    data = _previous(now)
    return data or {"source": "espn", "generated_at": "", "leagues": []}


def summary(data: dict | None) -> str:
    parts = []
    for league in (data or {}).get("leagues", []):
        rows = league.get("rows", [])
        leader = rows[0]["team"] if rows else "—"
        parts.append(f"{league.get('name')}: {league.get('teams', 0)} takım · lider {leader}")
    return " | ".join(parts) if parts else "puan durumu yok"
