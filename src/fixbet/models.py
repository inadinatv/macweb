"""Maç veri modeli."""
from __future__ import annotations

from dataclasses import asdict, dataclass


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
    status: str = "upcoming"           # normalize edilmiş durum (match_state.py)
    started: bool = False
    raw_event: str = ""
    url: str | None = None             # player bağlantısı
    fetched_at: str = ""
    status_source: str = "schedule"    # schedule = saat tahmini; source / espn = gerçek durum
    raw_status: str = ""               # sağlayıcının özgün durum kodu
    score_home: int | None = None
    score_away: int | None = None
    score_source: str = ""
    score_updated_at: str = ""
    event_id: str = ""                 # gerçek etkinlik kimliği; match_id bir KANAL kimliğidir
    starts_at: str = ""                # saat dilimli ISO başlangıcı (varsa sağlayıcıdan)

    def to_dict(self) -> dict:
        return asdict(self)
