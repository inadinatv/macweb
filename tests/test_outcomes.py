"""Maç sonucu alanlarının HTML -> model -> JSON -> şablon zinciri (ağsız)."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fixbet import categorizer, parser, reports, site
from fixbet.match_state import normalize_status, score_value
from fixbet.models import Match


def card(status="FT", home_score="2", away_score="1"):
    return f'''<a href="channel.html?id=ss2&amp;x=1" data-status="{status}">
      <div class="match-detail"><div class="date">Futbol</div>
        <div class="event">20:00 | Test Ligi</div>
        <div class="home">Ev Takımı <span class="score">{home_score}</span></div>
        <div class="away">Deplasman <span class="score">{away_score}</span></div>
      </div></a>'''


@pytest.mark.parametrize("raw,expected", [("FT", "finished"), ("MS", "finished"), ("HT", "halftime"),
    ("DEVRE ARASI", "halftime"), ("CANLI", "live"), ("İptal", "cancelled"), ("PST", "postponed"),
    ("STATUS_FULL_TIME", "finished"), ("STATUS_HALFTIME", "halftime"), ("1H", "live"), ("AET", "finished"),
    ("SUSP", "suspended"), ("Oynanmadı", "abandoned"), ("20:00 | Premier Lig", None)])
def test_status_vocabulary(raw, expected):
    assert normalize_status(raw) == expected


@pytest.mark.parametrize("value,expected", [(0, 0), ("0", 0), (" 12 ", 12), ("999", 999),
    (None, None), ("", None), (False, None), (True, None), (-1, None), ("-", None),
    ("2 (4)", None), (2.5, None), ("NaN", None), ("1e2", None)])
def test_score_normalization(value, expected):
    assert score_value(value) == expected


def test_html_status_and_team_score_order():
    m = parser.parse(card())[0]
    assert m.home == "Ev Takımı" and m.away == "Deplasman"
    assert m.match_id == "ss2" and m.channel_id == "ss2"
    assert m.status == "finished" and m.status_source == "source"
    assert m.raw_status == "FT" and (m.score_home, m.score_away) == (2, 1)
    # Saat henüz gelmemiş olsa bile gerçek final durumu ezilmez.
    categorizer.classify([m], datetime(2026, 9, 6, 10))
    assert m.status == "finished" and m.started


def test_score_fields_not_guessed_from_time_or_visibility():
    raw = card("", "", "").replace('<a href=', '<a class="hidden" style="display:none" href=')
    m = parser.parse(raw)[0]
    assert m.status_source == "schedule"
    assert m.score_home is None and m.score_away is None
    m = parser.parse(card("live", "0", "0"))[0]
    assert (m.score_home, m.score_away) == (0, 0)
    m = parser.parse(card("live", "", "1"))[0]
    assert m.score_home is None and m.score_away is None


def test_simple_source_and_dedicated_score_nodes():
    raw = '''<a href="channel?id=x" data-score-home="0" data-score-away="3">
      <div class="channel-name">Ev vs Dep</div><div class="channel-status">20:00 | Test Ligi | MS</div></a>'''
    m = parser.parse(raw)[0]
    assert m.status == "finished" and (m.score_home, m.score_away) == (0, 3)
    assert m.league == "Test Ligi"
    raw = card().replace('<span class="score">2</span>', '').replace('<span class="score">1</span>', '')
    raw = raw.replace('</a>', '<div class="match-score">5 - 4</div></a>')
    assert parser.parse(raw)[0].score_home == 5


@pytest.mark.parametrize("status", ["halftime", "live", "finished", "postponed", "cancelled", "suspended", "abandoned"])
def test_authoritative_status_survives_clock(status):
    m = Match("same-channel", "A", "B", "L", "10:00", "Futbol", status=status, status_source="source")
    categorizer.classify([m], datetime(2026, 9, 6, 23, 59))
    assert m.status == status
    c = categorizer.categorize([m], datetime(2026, 9, 6, 23, 59))
    bucket = "live" if status in ("live", "halftime") else status
    assert c["counts"][bucket] == 1
    if status in ("postponed", "cancelled", "suspended", "abandoned"):
        assert c["counts"]["upcoming"] == 0


def test_midnight_and_istanbul_start_is_serialized():
    m = Match("x", "A", "B", "L", "23:30", "Futbol")
    categorizer.classify([m], datetime(2026, 9, 6, 0, 30))
    assert m.status == "live"
    assert m.starts_at == "2026-09-05T23:30:00+03:00"
    assert site.matches_payload([m], [], "2026-09-06")[0]["startsAt"] == m.starts_at
    categorizer.classify([m], datetime(2026, 9, 6, 2, 30))
    assert m.status == "finished"


def test_outcome_serializes_and_roundtrips_without_field_loss(tmp_path, monkeypatch):
    m = parser.parse(card())[0]
    m.score_updated_at = "2026-09-06T22:00:00+03:00"
    m.event_id = "event-123"
    now = datetime(2026, 9, 6, 22)
    data = categorizer.categorize([m], now)
    monkeypatch.setattr(reports, "OUTPUT", tmp_path)
    reports.write_json_data([m], data, {}, {})
    saved = json.loads((tmp_path / "today_matches.json").read_text())
    restored = Match(**saved["matches"][0])
    assert restored == m
    assert saved["timezone"] == "Europe/Istanbul"
    row = site.matches_payload([m], [], "2026-09-06")[0]
    for key, value in {"statusSource": "source", "rawStatus": "FT", "scoreHome": 2, "scoreAway": 1,
                       "eventId": "event-123", "scoreUpdatedAt": m.score_updated_at}.items():
        assert row[key] == value
    assert "Ev Takımı 2 - 1 Deplasman" in site._match_groups_html([m])
    m.status = "upcoming"
    assert "2 - 1" not in site._match_groups_html([m])
