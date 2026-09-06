"""Kaynak durumları ve skorlar için tek sözlük (aynı sözlük JS'e de gömülür).

Saatten tahmin edilen durum gerçek maç sonucu değildir. ``status_source`` bu
ayrımı uçtan uca korur; bilinmeyen skor hiçbir zaman 0'a çevrilmez.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

STATUS_ALIASES = {
    "upcoming": ("upcoming", "scheduled", "not started", "ns", "tbd", "yaklasan", "baslamadi", "status scheduled"),
    "live": ("live", "in progress", "inprogress", "playing", "started", "canli", "simdi", "1h", "2h", "et", "pen live",
             "status in progress", "status first half", "status second half", "status overtime", "status shootout"),
    "halftime": ("halftime", "half time", "ht", "devre", "devre arasi", "iy", "status halftime"),
    "finished": ("finished", "ended", "full time", "fulltime", "final", "ft", "aet", "pen", "ms", "bitti", "mac sonu",
                 "status final", "status full time", "status final aet", "status final pen", "status end of extra time"),
    "postponed": ("postponed", "ppd", "pst", "ertelendi", "ertelenen", "status postponed"),
    "cancelled": ("cancelled", "canceled", "canc", "iptal", "iptal edildi", "status canceled", "status cancelled"),
    "suspended": ("suspended", "interrupted", "int", "susp", "durduruldu", "ara verildi", "status suspended", "status delayed"),
    "abandoned": ("abandoned", "abd", "oynanmadi", "yarida kaldi", "status abandoned"),
}
STATUS_LABELS = {
    "upcoming": "YAKLAŞAN", "live": "CANLI", "halftime": "DEVRE", "finished": "MS",
    "postponed": "Ertelendi", "cancelled": "İptal", "suspended": "Durduruldu", "abandoned": "Oynanmadı",
}
ACTIVE_STATUSES = {"live", "halftime"}
SCORE_STATUSES = ACTIVE_STATUSES | {"finished"}


def fold(text: Any) -> str:
    text = str(text or "").lower().replace("ı", "i")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", text, flags=re.UNICODE).strip()


STATUS_LOOKUP = {alias: status for status, aliases in STATUS_ALIASES.items() for alias in aliases}


def normalize_status(value: Any) -> str | None:
    return STATUS_LOOKUP.get(fold(value))


def score_value(value: Any) -> int | None:
    """0 geçerlidir; None, boş, bool, negatif, kesir veya belirsiz metin değildir."""
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    return int(text) if re.fullmatch(r"[0-9]{1,3}", text) else None


def score_pair(home: Any, away: Any) -> tuple[int | None, int | None]:
    h, a = score_value(home), score_value(away)
    return (h, a) if h is not None and a is not None else (None, None)


def display_score(match: Any) -> str:
    h, a = score_pair(match.score_home, match.score_away)
    return f"{h} - {a}" if match.status in SCORE_STATUSES and h is not None else ""
