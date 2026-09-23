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
          date="2026-09-06T17:00Z", id="123", neutral=False, clock=""):
    # Away önce gelebilir. Array sırasını kullanmak skorları ters bağlar.
    return {"id": id, "date": date, "competitions": [{"id": id, "date": date,
        "neutralSite": neutral,
        "status": {"displayClock": clock, "type": {"name": status, "state": "post", "completed": True}},
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


def test_espn_live_clock_is_persisted_and_cleared_on_final():
    live = enrich([match()], [event("STATUS_IN_PROGRESS", clock="63'")])[0]
    assert live.status == "live" and live.status_clock == "63'"
    final = enrich([match()], [event("STATUS_FULL_TIME", clock="90'")], previous=[live])[0]
    assert final.status == "finished" and final.status_clock == ""


def test_mackolik_clock_and_status_use_provider_timestamps():
    base = int(datetime.fromisoformat("2026-09-06T17:00:00+00:00").timestamp() * 1000)
    payload = {"data": {"matches": {
        "live": {"id": "live", "mstUtc": base, "lastUpdated": base + 17 * 60_000,
                 "periodStart": base, "periodId": 1, "status": "minutes", "state": "live",
                 "substate": "none", "homeTeam": {"name": "Ev"}, "awayTeam": {"name": "Dep"},
                 "score": {"home": "1", "away": "0"}},
        "half": {"id": "half", "mstUtc": base, "lastUpdated": base + 48 * 60_000,
                 "periodStart": None, "periodId": 10, "status": "state", "state": "live",
                 "substate": "halfTime", "statusBoxContent": "İY",
                 "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"},
                 "score": {"home": "2", "away": "1"}},
    }}}
    rows = scores._mackolik_competitions(payload, scores.ZoneInfo("Europe/Istanbul"))
    by_id = {row["id"]: row for row in rows}
    assert by_id["live"]["status"] == "live" and by_id["live"]["clock"] == "18'"
    assert by_id["half"]["status"] == "halftime" and by_id["half"]["clock"] == "İY"


def test_neutral_site_swapped_sides_still_bind_scores_to_correct_teams():
    # Turnuva (tarafsız saha): sağlayıcı programın "ev" takımını away listeler.
    swapped = event(home="Chelsea", away="Manchester United", pair=("1", "3"), neutral=True)
    m = enrich([match()], [swapped])[0]
    assert (m.score_home, m.score_away) == (3, 1)  # skor kendi takımına döner
    # Tarafsız saha DEĞİLSE taraf değişimi eşleşme sayılmaz (farklı maç olabilir).
    not_neutral = event(home="Chelsea", away="Manchester United", pair=("1", "3"))
    m = enrich([match()], [not_neutral])[0]
    assert m.score_home is None and m.status_source == "schedule"


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


def test_espn_date_range_error_retries_with_local_single_day():
    calls = []
    def fetch(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise requests.HTTPError("range unsupported")
        return {"events": [event()]}
    row = scores.enrich([match()], NOW, fetch=fetch, settings=CFG)[0]
    assert row.status == "finished" and row.score_home == 2
    assert len(calls) == 2 and "dates=20260906" in calls[1]


def test_mackolik_match_miss_falls_back_to_espn_for_same_league(monkeypatch):
    cfg = dict(CFG, leagues=[{"name": "Premier", "sport": "Futbol", "path": "soccer/tur.1"}])
    base = int(datetime.fromisoformat("2026-09-06T17:00:00+00:00").timestamp() * 1000)
    monkeypatch.setattr(scores, "_fetch_mackolik", lambda *args: {"data": {"matches": {
        "other": {"id": "other", "mstUtc": base, "state": "post", "substate": "fullTime",
                  "status": "state", "statusBoxContent": "MS", "competitionId": scores.MACKOLIK_COMP_MAP["soccer/tur.1"],
                  "homeTeam": {"name": "Başka"}, "awayTeam": {"name": "Takımlar"},
                  "score": {"home": "4", "away": "0"}}
    }}})
    row = scores.enrich([match(home="Manchester United")], NOW,
                        fetch=lambda *args: {"events": [event(clock="90'")]}, settings=cfg)[0]
    assert row.status_source == row.score_source == "espn"
    assert (row.score_home, row.score_away) == (2, 1)


def test_confirmed_final_wins_over_other_providers_lagging_live_state(monkeypatch):
    cfg = dict(CFG, leagues=[{"name": "Premier", "sport": "Futbol", "path": "soccer/tur.1"}])
    base = int(datetime.fromisoformat("2026-09-06T17:00:00+00:00").timestamp() * 1000)
    monkeypatch.setattr(scores, "_fetch_mackolik", lambda *args: {"data": {"matches": {
        "m": {"id": "m", "mstUtc": base, "lastUpdated": base + 88 * 60_000,
              "periodStart": base + 45 * 60_000, "periodId": 2, "state": "live", "substate": "none",
              "status": "minutes", "competitionId": scores.MACKOLIK_COMP_MAP["soccer/tur.1"],
              "homeTeam": {"name": "Manchester United"}, "awayTeam": {"name": "Chelsea"},
              "score": {"home": "2", "away": "1"}}
    }}})
    row = scores.enrich([match(home="Manchester United")], NOW,
                        fetch=lambda *args: {"events": [event("STATUS_FULL_TIME", pair=("2", "1"))]},
                        settings=cfg)[0]
    assert row.status == "finished" and row.status_source == "espn"
    assert (row.score_home, row.score_away, row.status_clock) == (2, 1, "")


def test_unconfigured_football_league_uses_exact_mackolik_fallback(monkeypatch):
    base = int(datetime.fromisoformat("2026-09-06T17:00:00+00:00").timestamp() * 1000)
    monkeypatch.setattr(scores, "_fetch_mackolik", lambda *args: {"data": {"matches": {
        "m": {"id": "m", "mstUtc": base, "lastUpdated": base + 62 * 60_000,
              "periodStart": base + 45 * 60_000, "periodId": 2, "state": "live", "substate": "none",
              "status": "minutes", "homeTeam": {"name": "Manchester United"},
              "awayTeam": {"name": "Chelsea"}, "score": {"home": "3", "away": "2"}}
    }}})
    cfg = {"enabled": True, "leagues": [], "team_aliases": {}, "mackolik_all_football": True}
    row = scores.enrich([match(home="Manchester United")], NOW,
                        fetch=lambda *args: (_ for _ in ()).throw(AssertionError("ESPN çağrılmamalı")), settings=cfg)[0]
    assert row.status == "live" and row.status_source == "mackolik"
    assert (row.score_home, row.score_away, row.status_clock) == (3, 2, "63'")


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
