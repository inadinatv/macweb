"""Maç veri modeli."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Match:
    match_id: str                      # channel?id=<match_id>
    home: str
    away: str
    league: str
    time: str                          # "HH:MM"
    sport: str
    is_match_of_day: bool = False
    channel_id: str = ""               # kanal eşlemesi
    logo_home: str | None = None
    logo_away: str | None = None
    status: str = "upcoming"           # live | upcoming | finished
    started: bool = False
    raw_event: str = ""
    url: str | None = None             # player bağlantısı
    fetched_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
