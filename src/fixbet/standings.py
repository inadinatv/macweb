"""Lig puan durumu: gerçek kaynaktan (ESPN + iddaa/mackolik) çekilen PUAN DURUMU tablosu.

Sayfadaki **LİG PUANI** modalı bu modülün ürettiği ``output/standings.json``
dosyasını ve index.html'e gömülen kopyayı gösterir.

İlkeler:
  * Sayfa asla uydurma/sabit puan tablosu göstermez; satır yoksa tablo boştur.
  * Sıra, O/G/B/M, averaj ve puan değerleri kaynaktan geldiği gibi yazılır.
  * Kaynak bir lig için erişilemezse o ligin **son bilinen** tablosu korunur
    (``output/standings.json``); ağ tamamen kesikse dosya olduğu gibi kalır.
  * Yalnızca kaynak averaj alanını hiç vermediğinde (attığı - yediği) farkı
    hesaplanır; puan eksikse G*3+B kuralı uygulanır.

Sunum katmanı (sayısal verilere dokunmaz):
  * **Takım adı tekilleştirme**: iddaa/mackolik adı aynı hücrede iki kez basar
    (masaüstü + mobil görünüm); ``dedupe_team_name`` yapışık tekrarı çözer, yoksa
    ``"GalatasarayGalatasaray"`` gibi bozuk adlar sayfaya basılır.
  * **Sıra bölgeleri**: ``config/standings.yml → zones`` (yoksa ``DEFAULT_ZONES``)
    üst sıraları (Şampiyonlar Ligi / Avrupa hattı) ve alt sıraları (küme düşme
    hattı) işaretler; her satıra ``zone`` + ``zoneLabel`` yazılır ve arayüz bu
    satırları renkli şerit/rozet + açıklamalı gösterir.

Canlı yenilenebilir sistem:
  * Türkiye Süper Lig için **birincil kaynak iddaa.com**, ikincil mackolik.com,
    üçüncül ESPN'dir. Diğer ligler için ESPN kullanılır.
  * Her kaynak için ayrı timeout/retry uygulanır; başarı oranı artar.
  * Başarısız kaynak otomatik olarak bir sonrakine düşer (fallback).
  * Sonuçlar ``output/standings.json``'a yazılır ve istemci her 5 dakikada
    bir bu dosyayı tazeler (yenilenebilir canlı).
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import re
import time
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
STANDINGS_SOURCE = "output/standings.json"

# Canlı kaynaklar
IDDAA_STANDINGS_URL = "https://www.iddaa.com/lig-analiz/puan-durumu/turkiye-super-lig"
MACKOLIK_STANDINGS_URL = "https://www.mackolik.com/puan-durumu/t%C3%BCrkiye-trendyol-s%C3%BCper-lig/482ofyysbdbeoxauk19yg7tdt"

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

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
}


def load_config() -> dict:
    return config._read(STANDINGS_CONFIG)


def _fetch(url: str, timeout: float) -> dict:
    response = requests.get(url, headers={"Accept": "application/json",
                                          "User-Agent": "macweb-standings/1.0"},
                            timeout=(5, timeout))
    response.raise_for_status()
    return response.json()


def _fetch_html(url: str, timeout: float) -> str:
    """HTML kaynağı çeker (iddaa/mackolik için)."""
    # Kısa yeniden deneme: canlı yenilenebilir sistem ağ dalgalanmasına dayanıklı.
    last: Exception | None = None
    for attempt in range(2):
        try:
            r = requests.get(url, headers=_BROWSER_HEADERS, timeout=(5, timeout))
            r.raise_for_status()
            # iddaa/mackolik bazen 403 döndürebilir; kısa bekleme ile tekrar dene
            if r.status_code == 403 and attempt == 0:
                time.sleep(0.6)
                continue
            return r.text
        except requests.RequestException as exc:
            last = exc
            if attempt == 0:
                time.sleep(0.4)
                continue
            raise
    raise RuntimeError(f"HTML çekilemedi {url}: {last}")


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(round(float(str(value).strip().replace("−", "-").replace("+", ""))))
    except (TypeError, ValueError, AttributeError):
        return None


def _parse_int_cell(text: str) -> int | None:
    t = str(text or "").strip().replace("−", "-").replace("–", "-")
    # Remove non-digit prefix/suffix but keep leading minus
    m = re.search(r"-?\d+", t)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Takım adı temizliği
# ---------------------------------------------------------------------------
# iddaa/mackolik takım adını aynı hücrede iki kez basar (masaüstü + mobil görünüm):
#   <a><span class="d-sm-block">Galatasaray</span><span class="d-none">Galatasaray</span></a>
# BeautifulSoup `get_text()` bu iki kopyayı ayraçsız yapıştırır ve tabloda
# "GalatasarayGalatasaray" görünür. Aşağıdaki yardımcı YALNIZCA metni tekilleştirir;
# hiçbir sayısal alana (O/G/B/M/AV/P) uygulanmaz.

def dedupe_team_name(text: Any) -> str:
    """Yapışık/ardışık tekrar eden takım adını tek kopyaya indirger.

    ``"GalatasarayGalatasaray" -> "Galatasaray"``, ``"Amed SK Amed SK" -> "Amed SK"``.
    Tekrar yoksa metin (yalnızca boşlukları düzeltilmiş olarak) aynen döner.
    """
    raw = str(text if text is not None else "")
    t = re.sub(r"\s+", " ", raw).strip()
    if not t:
        return ""

    # 1) Kelime düzeyinde tekrar: "Amed SK Amed SK" -> "Amed SK"
    tokens = t.split(" ")
    total = len(tokens)
    for size in range(1, total // 2 + 1):
        if total % size:
            continue
        unit = tokens[:size]
        if all(tokens[i * size:(i + 1) * size] == unit for i in range(1, total // size)):
            return " ".join(unit)

    # 2) Ayraçsız (yapışık) tekrar: "GalatasarayGalatasaray" -> "Galatasaray"
    length = len(t)
    for size in range(2, length // 2 + 1):          # tek harfli takım adı olmaz
        if length % size:
            continue
        unit = t[:size]
        if unit.strip() and unit * (length // size) == t:
            return unit.strip()

    return t


# ---------------------------------------------------------------------------
# Sıra bölgeleri (zone): Avrupa hattı / küme düşme hattı
# ---------------------------------------------------------------------------
# Sunum katmanıdır: kaynak sıra sayısını vermezse işaret BASILMAZ ve hiçbir
# sayısal değer (O/G/B/M/AV/P) bu yüzden değiştirilmez.

DEFAULT_ZONES: dict[str, Any] = {
    "top": [
        {"count": 1, "kind": "champions", "label": "Şampiyonlar Ligi"},
        {"count": 2, "kind": "europa", "label": "Avrupa kupaları"},
    ],
    "bottom": [
        {"count": 3, "kind": "relegation", "label": "Küme düşme hattı"},
    ],
}
# Çok kısa tablolarda (ör. tek maçlık grup) üst/alt bölge anlamsız olur.
MIN_ROWS_FOR_ZONES = 8


def zone_rules(cfg: dict | None, path: str) -> dict:
    """Lig için bölge kuralları: ``zones.<path>`` yoksa ``default_zones``/varsayılan."""
    cfg = cfg if isinstance(cfg, dict) else {}
    table = cfg.get("zones")
    rules = table.get(path) if isinstance(table, dict) else None
    if rules is None:
        rules = cfg.get("default_zones")
    if rules is None:
        rules = DEFAULT_ZONES
    return rules if isinstance(rules, dict) else {}


def _zone_entries(raw: Any, fallback_kind: str, fallback_label: str) -> list[dict]:
    entries: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            count, kind, label = item.get("count"), item.get("kind"), item.get("label")
        else:                                   # kısayol: yalnızca sıra sayısı (ör. `- 3`)
            count, kind, label = item, None, None
        count = _int(count)
        if not count or count < 1:
            continue
        entries.append({"kind": str(kind or fallback_kind),
                        "label": str(label or fallback_label)})
        entries[-1]["count"] = count
    return entries


def zone_rank_map(rules: Any, total: int) -> dict[int, dict]:
    """``sıra -> {kind, label}`` eşlemesi; ``top`` 1'den, ``bottom`` son sıradan başlar."""
    if not isinstance(rules, dict) or total < MIN_ROWS_FOR_ZONES:
        return {}
    zones: dict[int, dict] = {}
    rank = 1
    for entry in _zone_entries(rules.get("top"), "europa", "Avrupa kupaları"):
        for _ in range(entry["count"]):
            if rank > total:
                break
            zones[rank] = entry
            rank += 1
    rank = total
    for entry in _zone_entries(rules.get("bottom"), "relegation", "Küme düşme hattı"):
        for _ in range(entry["count"]):
            if rank < 1:
                break
            zones.setdefault(rank, entry)       # üst bölge önceliklidir
            rank -= 1
    return zones


def apply_zones(rows: list[dict], rules: Any) -> list[dict]:
    """Satırlara ``zone``/``zoneLabel`` alanlarını yazar (renk/rozet bu alanları kullanır)."""
    zones = zone_rank_map(rules, len(rows or []))
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        info = zones.get(row.get("rank")) if isinstance(row.get("rank"), int) else None
        row["zone"] = str(info["kind"]) if info else ""
        row["zoneLabel"] = str(info["label"]) if info else ""
    return rows


def stat_map(stats: Any) -> dict[str, int | None]:
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
    if not isinstance(entry, dict):
        return None
    team = entry.get("team") or {}
    if not isinstance(team, dict):
        return None
    name = next((str(team[k]).strip() for k in ("displayName", "shortDisplayName", "name", "location")
                 if team.get(k)), "")
    if not name:
        return None
    clean_name = dedupe_team_name(name) or name
    row = stat_map(entry.get("stats"))
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
        "team": display(clean_name),
        "sourceTeam": clean_name,
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
    return (row["rank"] if row["rank"] is not None else 999,
            -(row["points"] or 0), -(row["diff"] or 0), -(row["goalsFor"] or 0),
            row["team"], index)


def parse_league(data: Any, league: dict, display: Callable[[str], str]) -> list[dict]:
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
    apply_zones(rows, zone_rules(cfg, path))
    return {
        "id": path,
        "name": str(league.get("name") or path),
        "sport": str(league.get("sport") or "Futbol"),
        "season": season,
        "updated_at": fetched_at,
        "teams": len(rows),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Canlı kaynaklar: iddaa & mackolik HTML ayrıştırıcıları
# ---------------------------------------------------------------------------

def _normalize_header(text: str) -> str:
    t = str(text or "").strip().lower()
    t = t.replace("ı", "i").replace("İ", "i").replace("ş", "s").replace("ğ", "g").replace("ü", "u").replace("ö", "o").replace("ç", "c")
    t = re.sub(r"\s+", " ", t).strip()
    # Common header aliases
    if t in ("poz", "#", "sira", "sıra", "rank", "no"):
        return "rank"
    if "takim" in t or "team" in t:
        return "team"
    if t == "o":
        return "played"
    if t == "g":
        return "wins"
    if t == "b":
        return "draws"
    if t == "m":
        return "losses"
    if t in ("a", "ag") or "attig" in t or "ag:" in t:
        # Attığı / AG
        if ":" in t or "ag:yg" in t:
            return "gf_ga"
        # For mackolik "A" single column
        return "goalsFor"
    if t in ("y", "yg") or "yedig" in t:
        return "goalsAgainst"
    if t in ("ag:yg", "ag- yg", "ag/yg"):
        return "gf_ga"
    if "+/-" in t or "av" in t or "averaj" in t:
        return "diff"
    if t == "p" or "puan" in t:
        return "points"
    if "form" in t:
        return "form"
    return t


def _extract_rows_from_table(table, display: Callable[[str], str]) -> list[dict]:
    """Başlık satırına göre tabloyu ayrıştırır; başlık yoksa sabit sırayı dener."""
    # Başlık satırını bul
    header_cells = []
    header_row = None
    # thead varsa onu kullan
    thead = table.find("thead")
    if thead:
        tr = thead.find("tr")
        if tr:
            header_row = tr
            header_cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
    if not header_cells:
        # İlk satırı başlık kabul et, eğer "Poz" veya "#" içeriyorsa
        first_tr = table.find("tr")
        if first_tr:
            maybe = [c.get_text(" ", strip=True) for c in first_tr.find_all(["th", "td"])]
            txt = " ".join(maybe).lower()
            if any(k in txt for k in ("poz", "#", "takım", "takim", " o ", " g ", " b ")):
                header_cells = maybe
                header_row = first_tr
    # Header normalize
    headers = [_normalize_header(h) for h in header_cells] if header_cells else []
    has_header = bool(headers and "team" in headers)

    rows: list[dict] = []
    # Tüm satırlar
    trs = table.find_all("tr")
    start_idx = 1 if has_header else 0
    # If header_row was detected, skip it
    for tr in trs[start_idx:]:
        # Atla: eğer bu satır header_row ise zaten atlandı
        if header_row is not None and tr is header_row:
            continue
        tds = tr.find_all(["td", "th"])
        if not tds:
            continue
        # Hücre metinleri
        cells_text = [c.get_text(" ", strip=True) for c in tds]
        # Logo içeren hücreyi atlama: eğer hücrede img varsa ama metin boşsa
        # Genellikle boş logo kolonu olur — onu da hesaba kat
        # Eğer takım hücresinde link varsa, takım adını oradan al
        # Takım adını belirle: hücrelerden birinde en uzun metin ve harf içeren
        # Daha robust: takım adını <a> içinde ara
        # NOT: kaynak adı iki kez basar (masaüstü+mobil); dedupe_team_name tekilleştirir.
        team_name = ""
        team_cell_idx = -1
        for idx, c in enumerate(tds):
            a = c.find("a")
            if a is None:
                continue
            txt = dedupe_team_name(a.get_text(" ", strip=True))
            # Takım adları genellikle 3+ harf ve boşluk içerebilir; form hücreleri tek harfli G/B/M olur, onları ele
            if len(txt) >= 2 and not re.fullmatch(r"[GBM ]+", txt, flags=re.I):
                # Exclude if txt is just number or rank
                if not txt.isdigit():
                    team_name = txt
                    team_cell_idx = idx
                    break
        if not team_name:
            # Fallback: text-based detection
            for idx, txt in enumerate(cells_text):
                txt = dedupe_team_name(txt)
                if len(txt) >= 3 and re.search(r"[A-Za-zÇçĞğİıÖöŞşÜü]", txt):
                    # Check if this txt looks like team not header
                    if txt.lower() not in ("poz", "takım", "takim", "form"):
                        # If numeric rank before it, this is likely team column
                        team_name = txt
                        team_cell_idx = idx
                        break
            if not team_name:
                continue

        # Logo çıkar (img alt'ı temiz takım adı da verebilir)
        logo = ""
        if team_cell_idx >= 0:
            img = tds[team_cell_idx].find("img")
            if img:
                if not team_name:
                    team_name = dedupe_team_name(img.get("alt") or "")
                if img.get("src"):
                    src = str(img.get("src")).strip()
                    if src.startswith("//"):
                        src = "https:" + src
                    elif src.startswith("/"):
                        # Relative
                        src = "https://www.mackolik.com" + src if "mackolik" in str(table) else src
                    logo = src

        # Şimdi hücreleri header'lara eşle
        # Eğer headers varsa, cells_text ile headers aynı uzunlukta olmalı; logo boş kolon yüzünden kayma olabilir.
        # Düzeltme: eğer team_cell_idx ile headers'da team index uyuşmuyorsa, offset hesapla
        mapping: dict[str, str] = {}
        if has_header and len(headers) == len(cells_text):
            for h, txt in zip(headers, cells_text):
                if h and h not in mapping:
                    mapping[h] = txt
                else:
                    # Duplicate header (e.g., diff appears twice) — keep first non-empty?
                    if h == "diff" and "diff" in mapping:
                        # second diff is "Av", keep later if first empty
                        continue
        elif has_header:
            # Length mismatch — try to align by team column
            try:
                team_header_idx = headers.index("team")
            except ValueError:
                team_header_idx = 1
            offset = team_cell_idx - team_header_idx
            for idx, h in enumerate(headers):
                cell_idx = idx + offset
                if 0 <= cell_idx < len(cells_text):
                    txt = cells_text[cell_idx]
                    if h and h not in mapping:
                        mapping[h] = txt
        else:
            # No headers — fixed order fallback for iddaa/mackolik
            # Determine style by counting numeric cells
            # iddaa order: rank(0), team(1), O(2), G(3), B(4), M(5), GF:GA(6), diff(7), P(8)
            # mackolik order: rank(0), team(1), O(2), diff?(3), G(4), B(5), M(6), GF(7), GA(8), diff(9), P(10)
            # We can detect by cell count
            n = len(cells_text)
            # Remove leading empty if exists
            if cells_text and cells_text[0] == "":
                cells_text = cells_text[1:]
                if team_cell_idx >= 0:
                    team_cell_idx -= 1
                n = len(cells_text)
            # Now try to locate GF:GA pattern (contains ':')
            gf_ga_idx = -1
            for i, txt in enumerate(cells_text):
                if ":" in txt and re.search(r"\d+\s*:\s*\d+", txt):
                    gf_ga_idx = i
                    break
            if gf_ga_idx >= 0:
                # iddaa style
                # cells: rank, team, O, G, B, M, GF:GA, diff, P
                try:
                    mapping = {
                        "rank": cells_text[0] if len(cells_text) > 0 else "",
                        "team": team_name,
                        "played": cells_text[2] if len(cells_text) > 2 else "",
                        "wins": cells_text[3] if len(cells_text) > 3 else "",
                        "draws": cells_text[4] if len(cells_text) > 4 else "",
                        "losses": cells_text[5] if len(cells_text) > 5 else "",
                        "gf_ga": cells_text[gf_ga_idx],
                        "diff": cells_text[gf_ga_idx + 1] if gf_ga_idx + 1 < len(cells_text) else "",
                        "points": cells_text[gf_ga_idx + 2] if gf_ga_idx + 2 < len(cells_text) else "",
                    }
                except IndexError:
                    continue
            else:
                # Mackolik style or fallback
                # Find team index and then map subsequent
                # For mackolik, after team: O, +/- (maybe diff), G, B, M, A, Y, Av, P
                # Let's assume: rank at 0, team at 1, then O at 2, etc.
                # Use team_cell_idx to compute
                base = team_cell_idx + 1
                # Expect at least 7 numeric after team
                remaining = cells_text[base:]
                # Filter empties
                remaining = [r for r in remaining if r != ""]
                if len(remaining) >= 8:
                    # Map known positions: O, (maybe diff), G, B, M, GF, GA, diff, P
                    # Detect if there are 9 numbers: then pattern is O, diff1, G, B, M, GF, GA, diff, P
                    # If 8 numbers: O, G, B, M, GF, GA, diff, P
                    if len(remaining) == 9:
                        mapping = {
                            "rank": cells_text[0],
                            "team": team_name,
                            "played": remaining[0],
                            "diff_dup": remaining[1],
                            "wins": remaining[2],
                            "draws": remaining[3],
                            "losses": remaining[4],
                            "goalsFor": remaining[5],
                            "goalsAgainst": remaining[6],
                            "diff": remaining[7],
                            "points": remaining[8],
                        }
                    elif len(remaining) == 8:
                        mapping = {
                            "rank": cells_text[0],
                            "team": team_name,
                            "played": remaining[0],
                            "wins": remaining[1],
                            "draws": remaining[2],
                            "losses": remaining[3],
                            "goalsFor": remaining[4],
                            "goalsAgainst": remaining[5],
                            "diff": remaining[6],
                            "points": remaining[7],
                        }
                    else:
                        # Generic fallback: take last 8 as O,G,B,M,GF,GA,diff,P with possible extra
                        # Keep simple: assume last is points, second last diff etc.
                        continue
                else:
                    continue

        # Now build row dict from mapping
        raw_team = dedupe_team_name(team_name)
        if not raw_team:
            continue
        # Resolve display name
        team_disp = display(raw_team)

        # Extract numeric fields
        played = _parse_int_cell(mapping.get("played", ""))
        wins = _parse_int_cell(mapping.get("wins", ""))
        draws = _parse_int_cell(mapping.get("draws", ""))
        losses = _parse_int_cell(mapping.get("losses", ""))

        gf = _parse_int_cell(mapping.get("goalsFor", ""))
        ga = _parse_int_cell(mapping.get("goalsAgainst", ""))
        # If gf_ga combined exists, split
        if gf is None or ga is None:
            gf_ga = mapping.get("gf_ga", "")
            if gf_ga and ":" in str(gf_ga):
                parts = str(gf_ga).split(":")
                if len(parts) == 2:
                    gf = _parse_int_cell(parts[0]) if gf is None else gf
                    ga = _parse_int_cell(parts[1]) if ga is None else ga

        diff = _parse_int_cell(mapping.get("diff", ""))
        if diff is None and gf is not None and ga is not None:
            diff = gf - ga

        points = _parse_int_cell(mapping.get("points", ""))
        if points is None and wins is not None and draws is not None:
            points = wins * 3 + draws

        rank = _parse_int_cell(mapping.get("rank", ""))

        if played is None or wins is None or draws is None or losses is None:
            # Eksik satır uydurulmaz, atla
            continue

        # Note field may be in last column or extra; for now empty
        note = mapping.get("note", "") or ""
        # Handle logo
        abbr = ""

        rows.append({
            "rank": rank,
            "team": team_disp,
            "sourceTeam": raw_team,
            "abbr": abbr,
            "logo": logo,
            "played": played,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "goalsFor": gf,
            "goalsAgainst": ga,
            "diff": diff,
            "points": points,
            "note": str(note or ""),
        })

    return rows


def _parse_iddaa_html(html: str, display: Callable[[str], str]) -> list[dict]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    # iddaa sayfası Next.js; tablo genellikle <table> içinde
    tables = soup.find_all("table")
    candidate = None
    for t in tables:
        txt = t.get_text(" ", strip=True).lower()
        if "poz" in txt and "tak" in txt:
            candidate = t
            break
    if candidate is None:
        # Alternative: find table containing Galatasaray
        for t in tables:
            if "galatasaray" in t.get_text().lower():
                candidate = t
                break
    if candidate is None:
        # Fallback: try to find any table with many rows and numeric pattern
        for t in tables:
            rows = t.find_all("tr")
            if len(rows) >= 10:
                candidate = t
                break
    if candidate is None:
        raise ValueError("iddaa puan tablosu bulunamadı")
    rows = _extract_rows_from_table(candidate, display)
    if not rows:
        raise ValueError("iddaa satırları boş")
    # Sort fallback: if rank missing, sort by points etc. (but keep order)
    rows = [row for _, row in sorted(enumerate(rows), key=lambda pair: _sort_key(pair[1], pair[0]))]
    for i, r in enumerate(rows, start=1):
        if r["rank"] is None:
            r["rank"] = i
    return rows


def _parse_mackolik_html(html: str, display: Callable[[str], str]) -> list[dict]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    candidate = None
    for t in tables:
        txt = t.get_text(" ", strip=True).lower()
        if "takım" in txt or "takim" in txt:
            # Prefer table with many rows
            rows = t.find_all("tr")
            if len(rows) >= 10 and "galatasaray" in txt:
                candidate = t
                break
            if candidate is None and len(rows) >= 2:
                candidate = t
    if candidate is None:
        for t in tables:
            if "galatasaray" in t.get_text().lower():
                candidate = t
                break
    if candidate is None:
        # Fallback: any table with at least 2 rows (header+data) — yenilenebilir sistem testleri için
        for t in tables:
            if len(t.find_all("tr")) >= 2:
                candidate = t
                break
    if candidate is None:
        raise ValueError("mackolik puan tablosu bulunamadı")
    rows = _extract_rows_from_table(candidate, display)
    if not rows:
        raise ValueError("mackolik satırları boş")
    rows = [row for _, row in sorted(enumerate(rows), key=lambda pair: _sort_key(pair[1], pair[0]))]
    for i, r in enumerate(rows, start=1):
        if r["rank"] is None:
            r["rank"] = i
    return rows


def _fetch_iddaa_rows(timeout: float, display: Callable[[str], str]) -> list[dict]:
    html = _fetch_html(IDDAA_STANDINGS_URL, timeout)
    return _parse_iddaa_html(html, display)


def _fetch_mackolik_rows(timeout: float, display: Callable[[str], str]) -> list[dict]:
    html = _fetch_html(MACKOLIK_STANDINGS_URL, timeout)
    return _parse_mackolik_html(html, display)


def _rows_to_payload(rows: list[dict], league: dict, cfg: dict, fetched_at: str, source: str, season: str = "") -> dict:
    # Ensure rows sorted and ranked
    rows = [row for _, row in sorted(enumerate(rows), key=lambda pair: _sort_key(pair[1], pair[0]))]
    for position, row in enumerate(rows, start=1):
        if row["rank"] is None:
            row["rank"] = position
        # Validate consistency warning
        played, w, d, l = row["played"], row["wins"], row["draws"], row["losses"]
        if None not in (played, w, d, l) and w + d + l != played:
            log.warning("Puan tablosu tutarsız (%s): G+B+M=%s ama O=%s — kaynak değerleri korunuyor.", row["team"], w + d + l, played)
    # Season detection: try to infer current season string if not provided
    if not season:
        # e.g., 2026-27 Turkish Super Lig
        try:
            from datetime import date
            today = date.today()
            # Turkish season starts in August; season year is start year
            yr = today.year if today.month >= 8 else today.year - 1
            season = f"{yr}-{str(yr+1)[2:]} Turkish Super Lig"
        except Exception:
            season = ""
    apply_zones(rows, zone_rules(cfg, str(league.get("path") or "")))
    return {
        "id": str(league.get("path") or ""),
        "name": str(league.get("name") or ""),
        "sport": str(league.get("sport") or "Futbol"),
        "season": season,
        "updated_at": fetched_at,
        "teams": len(rows),
        "rows": rows,
        "_source": source,
    }


def sanitize_league(league: dict, cfg: dict | None = None) -> dict:
    """Kayıtlı/yeni bir lig tablosunu sunum için temizler.

    İki iş yapar, ikisi de **sunum katmanıdır**:
      1. Yapışık tekrar eden takım adlarını tekilleştirir
         (``"GalatasarayGalatasaray" -> "Galatasaray"``); temizlenen ad artık
         ``display_names`` ile eşleşebiliyorsa Türkçe görünen ad uygulanır.
      2. Sıra bölgelerini (Avrupa hattı / küme düşme hattı) ``zone``/``zoneLabel``
         alanlarıyla işaretler.

    O/G/B/M, averaj, puan ve sıra değerlerine **dokunulmaz**.
    """
    if not isinstance(league, dict):
        return league
    cfg = cfg if isinstance(cfg, dict) else {}
    path = str(league.get("id") or "")
    names = {str(k): str(v) for k, v in (cfg.get("display_names", {}).get(path) or {}).items()}
    rows = league.get("rows")
    if not isinstance(rows, list):
        return league
    for row in rows:
        if not isinstance(row, dict):
            continue
        team = str(row.get("team") or "")
        clean = dedupe_team_name(team)
        if clean and clean != team:
            row["team"] = clean
        source_team = str(row.get("sourceTeam") or "")
        clean_source = dedupe_team_name(source_team)
        if clean_source and clean_source != source_team:
            row["sourceTeam"] = clean_source
        mapped = names.get(str(row.get("team") or "")) or names.get(str(row.get("sourceTeam") or ""))
        if mapped:
            row["team"] = mapped
    apply_zones(rows, zone_rules(cfg, path))
    return league


def _valid_path(path: str) -> bool:
    return bool(re.fullmatch(r"[a-z-]+/[a-z0-9.\\-]+", path or ""))


def _previous(now: datetime | None = None) -> dict:
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

    - Trendyol Süper Lig için kaynak sırası: iddaa → mackolik → espn → önceki.
    - Diğer ligler için ESPN (veya varsa diğer kaynaklar).
    - Bir lig çekilemezse o ligin son bilinen tablosu aynen korunur.
    """
    cfg = settings if settings is not None else load_config()
    tz = ZoneInfo(config.load_settings().get("bot", {}).get("timezone", "Europe/Istanbul"))
    now = now or datetime.now(tz)
    now = now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz)
    stamp = now.isoformat(timespec="seconds")
    previous = _previous(now)
    prev_by_id = {l.get("id"): l for l in previous.get("leagues", []) if isinstance(l, dict)}

    leagues_out: list[dict] = []
    sources_used: list[str] = []

    if cfg.get("enabled", False):
        fetch = fetch or _fetch
        wanted = [l for l in cfg.get("leagues", []) if _valid_path(str(l.get("path") or ""))]
        timeout = float(cfg.get("request_timeout_seconds", 8))
        # Respect max_workers for ESPN fallback concurrency
        workers = max(1, min(8, int(cfg.get("max_workers", 4))))

        def load(league: dict):
            path = str(league.get("path") or "")
            names = {str(k): str(v) for k, v in (cfg.get("display_names", {}).get(path) or {}).items()}

            def display(name: str) -> str:
                return names.get(name, name)

            # Sadece Türkiye Süper Lig için canlı iddaa/mackolik öncelikli
            is_tur = path == "soccer/tur.1"
            if is_tur:
                # 1) iddaa
                try:
                    rows = _fetch_iddaa_rows(timeout, display)
                    if rows:
                        payload = _rows_to_payload(rows, league, cfg, stamp, source="iddaa")
                        log.info("Puan durumu iddaa'dan alındı (%s, %s takım)", path, len(rows))
                        return league, payload, "iddaa"
                except Exception as exc:
                    log.warning("iddaa puan durumu okunamadı (%s, %s); mackolik deneniyor.", path, type(exc).__name__)
                # 2) mackolik
                try:
                    rows = _fetch_mackolik_rows(timeout, display)
                    if rows:
                        payload = _rows_to_payload(rows, league, cfg, stamp, source="mackolik")
                        log.info("Puan durumu mackolik'ten alındı (%s, %s takım)", path, len(rows))
                        return league, payload, "mackolik"
                except Exception as exc:
                    log.warning("mackolik puan durumu okunamadı (%s, %s); espn’e düşülüyor.", path, type(exc).__name__)

            # 3) ESPN fallback (her lig için)
            url = API_BASE + str(league["path"]) + "/standings"
            try:
                data = fetch(url, timeout)
                payload = league_payload(data, league, cfg, stamp)
                # _source field ekle for tracking
                payload["_source"] = "espn"
                return league, payload, "espn"
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                log.warning("Puan durumu okunamadı (%s, %s); son bilinen tablo korunuyor.",
                            league["path"], type(exc).__name__)
                return league, None, "none"

        # Thread pool ile çek; ama iddaa/mackolik sıralı deneme zaten içinde
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(load, wanted))
            for league, payload, src in results:
                if payload:
                    # Gerçekten okunan kaynak etiketi için izlenir (_source alanı çıktıya sızmaz).
                    if src != "none":
                        sources_used.append(src)
                    payload.pop("_source", None)
                    leagues_out.append(payload)
                elif prev_by_id.get(league["path"]):
                    # Son bilinen tablo korunur; ad tekrarı/bölge işaretleri tazelenir.
                    leagues_out.append(sanitize_league(prev_by_id[league["path"]], cfg))
    else:
        leagues_out = [sanitize_league(lg, cfg) for lg in previous.get("leagues", [])
                       if isinstance(lg, dict)]

    # Üst düzey "source" etiketi dürüst olmalı: yalnızca GERÇEKTEN okunan kaynaklar
    # yazılır. Hiçbir kaynak okunamadıysa (son bilinen tablo korunuyorsa) o tablonun
    # kendi kaynağı korunur; birden fazla kaynak kullanıldıysa "mixed" olur.
    distinct = list(dict.fromkeys(src for src in sources_used if src))
    if not distinct:
        final_source = str(previous.get("source") or "espn")
    elif len(distinct) > 1:
        final_source = "mixed"
    else:
        final_source = distinct[0]
    if final_source not in ("iddaa", "mackolik", "espn", "mixed"):
        final_source = "espn"

    data = {"source": final_source, "generated_at": stamp, "leagues": leagues_out}
    if write:
        import os
        os.makedirs(STANDINGS_OUTPUT.parent, exist_ok=True)
        STANDINGS_OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def load_or_build(now: datetime | None = None) -> dict:
    """Son bilinen tabloyu yükler (çevrimdışı index üretimi için).

    Kayıtlı tablo eski bir sürümden geliyorsa burada da temizlenir: yapışık takım
    adı tekrarları tekilleştirilir, sıra bölgeleri işaretlenir (sayılar aynı kalır).
    """
    data = _previous(now)
    if not data:
        return {"source": "espn", "generated_at": "", "leagues": []}
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001 - yapılandırma okunamazsa tablo yine de gösterilir
        cfg = {}
    for league in data.get("leagues", []):
        sanitize_league(league, cfg)
    return data


def summary(data: dict | None) -> str:
    parts = []
    for league in (data or {}).get("leagues", []):
        rows = league.get("rows", [])
        leader = rows[0]["team"] if rows else "—"
        parts.append(f"{league.get('name')}: {league.get('teams', 0)} takım · lider {leader}")
    return " | ".join(parts) if parts else "puan durumu yok"
