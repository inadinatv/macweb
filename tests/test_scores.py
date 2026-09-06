"""İkincil skor kaynağı: ESPN'in gerçek şemasıyla deterministik, ağsız testler."""
import copy
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fixbet import categorizer, scores
from fixbet.models import Match

NOW = datetime.fromisoformat("2026-09-06T21:00:00+03:00")
CFG = {"enabled": True, "max_workers": 2, "leagues": [{"name": "Premier", "sport": "Futbol", "path": "soccer/eng.1"}],
       "team_aliases": {"soccer/eng.1": {"Manchester Utd": "Manchester United"}}}


def match(**kwargs):
    base = dict(match_id="ss", home="Manchester Utd", away="Chelsea", league="Premier", time="20:00", sport="Futbol")
    return Match(**dict(base, **kwargs))


def event(status="STATUS_FULL_TIME", home="Manchester United", away="Chelsea", pair=("2", "1"),
          date="2026-09-06T17:00Z", id="123"):
    # Away önce gelebilir. Array sırasını kullanmak skorları ters bağlar.
    return {"id": id, "date": date, "competitions": [{"id": id, "date": date,
        "status": {"type": {"name": status, "state": "post", "completed": True}},
        "competitors": [
            {"homeAway": "away", "score": pair[1], "team": {"displayName": away}},
            {"homeAway": "home", "score": pair[0], "team": {"displayName": home}},
        ]}]}


def enrich(rows, events, **kwargs):
    return scores.enrich(rows, NOW, fetch=lambda url, timeout: {"events": events}, settings=CFG, **kwargs)


def test_correct_sides_aliases_and_real_status():
    m = enrich([match()], [event()])[0]
    assert (m.score_home, m.score_away) == (2, 1)
    assert m.status == "finished" and m.status_source == m.score_source == "espn"
    assert m.event_id == "123" and m.raw_status == "STATUS_FULL_TIME"
    assert m.starts_at == "2026-09-06T17:00:00+00:00"
    assert m.score_updated_at == NOW.isoformat()
    categorizer.classify([m], NOW)
    assert m.status == "finished"  # 20:00 + 1 saat diye yeniden canlıya dönmez


def test_no_channel_id_matching_or_reversed_teams():
    rows = [match(), match(home="Arsenal", away="Liverpool"), match(home="Chelsea", away="Manchester United")]
    enrich(rows, [event()])
    assert rows[0].score_home == 2
    assert all(m.score_home is None for m in rows[1:])


def test_ambiguous_wrong_date_time_sport_and_league_are_not_matched():
    for events in ([event(), event(id="124")], [event(date="2026-09-05T17:00Z")], [event(date="2026-09-06T12:00Z")]):
        m = enrich([match()], events)[0]
        assert m.score_home is None and m.status_source == "schedule"
    for changed in (match(sport="Basketbol"), match(league="Kadınlar Premier"), match(home="Manchester United U21")):
        assert enrich([changed], [event()])[0].score_home is None


def test_zero_scores_only_after_kickoff_and_non_played_statuses():
    expected = {"STATUS_IN_PROGRESS": "live", "STATUS_HALFTIME": "halftime", "STATUS_SCHEDULED": "upcoming",
                "STATUS_POSTPONED": "postponed", "STATUS_CANCELED": "cancelled", "STATUS_ABANDONED": "abandoned"}
    for raw, status in expected.items():
        m = enrich([match()], [event(raw, pair=("0", "0"))])[0]
        assert m.status == status
        assert m.score_home == (0 if status in ("live", "halftime") else None)
    m = enrich([match()], [event(pair=(None, "2"))])[0]
    assert m.status == "finished" and m.score_home is None and m.score_away is None


def test_source_failure_keeps_last_score_timestamp_but_does_not_invent_final():
    old = enrich([match()], [event("STATUS_IN_PROGRESS")])[0]
    stamp = old.score_updated_at
    def fail(*args):
        raise requests.Timeout("test")
    later = datetime.fromisoformat("2026-09-06T23:50:00+03:00")
    current = scores.enrich([match()], later, previous=[old], fetch=fail, settings=CFG)[0]
    categorizer.classify([current], later)
    assert current.status == "live" and current.score_home == 2
    assert current.score_updated_at == stamp
    current = scores.enrich([match()], later, previous=[old], fetch=lambda *a: {}, settings=CFG)[0]
    assert current.score_updated_at == stamp
    # Kaynak bitti dedi ama final skorunu vermedi: son canlı skor final yapılamaz.
    current = enrich([match()], [event(pair=(None, None))], previous=[old])[0]
    assert current.status == "finished" and current.score_home is None


def test_confirmed_final_preserved_and_primary_source_wins():
    old = enrich([match()], [event()])[0]
    current = enrich([match()], [], previous=[old])[0]
    assert current.status == "finished" and current.score_home == 2
    direct = match(status="halftime", status_source="source", raw_status="HT", score_home=4, score_away=3, score_source="source")
    current = enrich([direct], [event()], previous=[old])[0]
    assert current.status == "halftime" and current.score_home == 4


def test_one_request_per_league_and_no_request_for_unmapped_sport():
    calls = []
    def fetch(url, timeout):
        calls.append(url)
        return {"events": [event()]}
    scores.enrich([match(), match(home="A"), match(sport="Tenis")], NOW, fetch=fetch, settings=CFG)
    assert len(calls) == 1
    assert "soccer/eng.1/scoreboard" in calls[0]
    assert "dates=20260905-20260906" in calls[0]
    calls.clear()
    scores.enrich([match()], NOW, fetch=fetch, settings=dict(CFG, enabled=False))
    assert not calls


def test_midnight_utc_day_boundary():
    m = match(time="00:30")
    enrich([m], [event(date="2026-09-05T21:30Z")])
    assert m.score_home == 2


def test_unknown_post_state_and_missing_side_are_not_finals():
    unknown = event("STATUS_SOMETHING_NEW")
    assert scores.competitions({"events": [unknown]}) == []
    missing = copy.deepcopy(event())
    missing["competitions"][0]["competitors"].pop()
    assert scores.competitions({"events": [missing]}) == []


def test_out_of_order_scoreboard_does_not_regress_a_confirmed_final():
    old = enrich([match()], [event()])[0]
    current = enrich([match()], [event('STATUS_SCHEDULED', pair=('0','0'))], previous=[old])[0]
    assert current.status == 'finished' and (current.score_home, current.score_away) == (2, 1)


def test_secondary_score_failure_does_not_stop_pipeline(monkeypatch):
    from fixbet import main
    def fail(*args, **kwargs):
        raise ValueError('bad provider schema')
    monkeypatch.setattr(scores, 'enrich', fail)
    rows = [match()]
    assert main.refresh_scores(rows, NOW) is rows
