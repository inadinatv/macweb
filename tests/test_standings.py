"""Puan durumu (standings) testleri: ESPN'in gerçek şemasıyla deterministik, ağsız.

Sayfanın gösterdiği her sayı kaynaktan gelmelidir; bu testler uydurma satır
üretilmediğini, eksik/bozuk verinin atlandığını ve kaynak kesildiğinde son
bilinen tablonun korunduğunu doğrular.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fixbet import standings

NOW = datetime.fromisoformat("2026-09-07T22:00:00+03:00")
CFG = {"enabled": True, "max_workers": 2,
       "leagues": [{"name": "Trendyol Süper Lig", "sport": "Futbol", "path": "soccer/tur.1"}],
       "display_names": {"soccer/tur.1": {"Besiktas": "Beşiktaş", "Fenerbahce": "Fenerbahçe"}}}


def stat(name, value):
    return {"name": name, "value": float(value), "displayValue": str(value), "type": name.lower()}


def entry(team, abbr, gp, w, d, l, gf, ga, gd, pts, rank, note=None, stats=None):
    """Gerçek ESPN entry biçimi: stats bir dizi, takım logosu/note isteğe bağlı."""
    e = {"team": {"id": str(rank), "displayName": team, "abbreviation": abbr,
                  "logos": [{"href": f"https://a.espncdn.com/i/teamlogos/soccer/500/{rank}.png"}]},
         "stats": stats if stats is not None else [
             stat("gamesPlayed", gp), stat("losses", l), stat("pointDifferential", gd),
             stat("points", pts), stat("pointsAgainst", ga), stat("pointsFor", gf),
             stat("ties", d), stat("wins", w), stat("rank", rank)]}
    if note:
        e["note"] = {"description": note, "rank": rank}
    return e


def payload(*entries):
    return {"name": "Turkish Super Lig",
            "children": [{"name": "2026/2027 Turkish Super Lig",
                          "standings": {"season": 2026, "seasonDisplayName": "2026-27 Turkish Super Lig",
                                        "entries": list(entries)}}],
            "season": {"year": 2026}}


def refresh(data=None, exc=None, cfg=None, **kwargs):
    def fetch(url, timeout):
        if exc:
            raise exc
        return data
    return standings.refresh(now=NOW, fetch=fetch, write=False, settings=cfg or CFG, **kwargs)


def rows_of(out):
    return out["leagues"][0]["rows"]


def test_parses_real_espn_shape_and_sorts_by_source_rank():
    out = refresh(payload(
        entry("Konyaspor", "KNY", 4, 0, 0, 4, 3, 8, -5, 0, 18, "Relegated"),
        entry("Besiktas", "BES", 4, 3, 0, 1, 9, 4, 5, 9, 2, "Champions League qualifying"),
        entry("Galatasaray", "GAL", 4, 3, 1, 0, 12, 6, 6, 10, 1, "Champions League"),
    ))
    rows = rows_of(out)
    assert [r["rank"] for r in rows] == [1, 2, 18], "kaynak sırası korunmalı"
    assert [r["team"] for r in rows] == ["Galatasaray", "Beşiktaş", "Konyaspor"]
    top = rows[0]
    assert (top["played"], top["wins"], top["draws"], top["losses"]) == (4, 3, 1, 0)
    assert (top["goalsFor"], top["goalsAgainst"], top["diff"], top["points"]) == (12, 6, 6, 10)
    assert top["note"] == "Champions League"
    assert top["logo"].endswith("/1.png")
    assert out["leagues"][0]["season"] == "2026-27 Turkish Super Lig"
    assert out["leagues"][0]["teams"] == 3
    assert out["source"] == "espn"
    assert "lider Galatasaray" in standings.summary(out)


def test_display_names_localize_team_without_touching_numbers():
    out = refresh(payload(entry("Fenerbahce", "FEN", 4, 2, 0, 2, 8, 6, 2, 6, 9),
                          entry("Amed SFK", "AMED", 4, 2, 1, 1, 7, 5, 2, 7, 5)))
    by_name = {r["team"]: r for r in rows_of(out)}
    assert "Fenerbahçe" in by_name, "Türkçe görünen ad uygulanmadı"
    assert by_name["Fenerbahçe"]["sourceTeam"] == "Fenerbahce"
    assert by_name["Fenerbahçe"]["points"] == 6
    # Eşlemesi olmayan takım kaynaktaki adıyla kalır (ad uydurulmaz)
    assert "Amed SFK" in by_name


def test_missing_played_or_record_drops_the_row_instead_of_inventing_it():
    no_played = entry("Goztepe", "GOZ", 0, 0, 0, 0, 0, 0, 0, 0, 17,
                      stats=[stat("wins", 1), stat("points", 3)])
    partial = entry("Samsunspor", "SAM", 4, 1, 1, 2, 5, 6, -1, 4, 13,
                    stats=[stat("gamesPlayed", 4), stat("wins", 1), stat("losses", 2),
                           stat("points", 4), stat("rank", 13)])
    out = refresh(payload(no_played, partial,
                          entry("Galatasaray", "GAL", 4, 3, 1, 0, 12, 6, 6, 10, 1)))
    rows = rows_of(out)
    assert [r["team"] for r in rows] == ["Galatasaray"], "eksik satırlar atlanmalı"


def test_goal_difference_and_points_derived_only_from_source_numbers():
    # Kaynak averaj/puan alanı hiç yoksa G/B ve attığı-yediği üzerinden türetilir.
    derived = entry("Trabzonspor", "TRAB", 4, 2, 1, 1, 9, 4, 0, 0, 4,
                    stats=[stat("gamesPlayed", 4), stat("wins", 2), stat("ties", 1),
                           stat("losses", 1), stat("pointsFor", 9), stat("pointsAgainst", 4),
                           stat("rank", 4)])
    row = rows_of(refresh(payload(derived)))[0]
    assert row["diff"] == 5, "averaj attığı-yediğinden hesaplanmalı"
    assert row["points"] == 7, "puan G*3+B kuralından hesaplanmalı"


def test_rank_falls_back_to_points_then_goal_difference():
    def norank(team, abbr, pts, gd):
        return entry(team, abbr, 4, 0, 0, 4, 0, 0, gd, pts, 0,
                     stats=[stat("gamesPlayed", 4), stat("wins", 0), stat("ties", 0),
                            stat("losses", 4), stat("points", pts), stat("pointDifferential", gd)])
    rows = rows_of(refresh(payload(norank("Kasimpasa", "KAS", 6, 1), norank("Alanyaspor", "ALA", 7, 1),
                                   norank("Genclerbirligi", "GEN", 6, -3))))
    assert [r["team"] for r in rows] == ["Alanyaspor", "Kasimpasa", "Genclerbirligi"]
    assert [r["rank"] for r in rows] == [1, 2, 3], "sıra yoksa sıralama pozisyonu yazılmalı"


def test_draws_read_from_either_ties_or_draws_key():
    ties = entry("Eyupspor", "EYU", 4, 1, 0, 3, 2, 6, -4, 3, 16)
    draws = entry("Goztepe", "GOZ", 4, 0, 1, 3, 7, 11, -4, 1, 17,
                  stats=[stat("gamesPlayed", 4), stat("wins", 0), stat("draws", 1),
                         stat("losses", 3), stat("pointsFor", 7), stat("pointsAgainst", 11),
                         stat("pointDifferential", -4), stat("points", 1), stat("rank", 17)])
    rows = {r["team"]: r for r in rows_of(refresh(payload(ties, draws)))}
    assert rows["Eyupspor"]["draws"] == 0 and rows["Goztepe"]["draws"] == 1


def test_flat_standings_schema_without_children_is_supported():
    flat = {"standings": {"seasonDisplayName": "2026-27 Turkish Super Lig",
                          "entries": [entry("Galatasaray", "GAL", 4, 3, 1, 0, 12, 6, 6, 10, 1)]}}
    assert rows_of(refresh(flat))[0]["team"] == "Galatasaray"


def test_inconsistent_record_is_kept_as_published_not_silently_fixed():
    # G+B+M != O ise kaynak değeri korunur (bot kendisi sayı üretmez).
    bad = entry("Goztepe", "GOZ", 4, 5, 0, 0, 7, 11, -4, 15, 17)
    rows = rows_of(refresh(payload(bad)))
    assert (rows[0]["wins"], rows[0]["played"], rows[0]["points"]) == (5, 4, 15)


def test_network_failure_keeps_last_known_table(monkeypatch, tmp_path):
    monkeypatch.setattr(standings, "STANDINGS_OUTPUT", tmp_path / "standings.json")
    standings.STANDINGS_OUTPUT.write_text(json.dumps(
        {"source": "espn", "generated_at": "2026-09-06T22:00:00+03:00",
         "leagues": [{"id": "soccer/tur.1", "name": "Trendyol Süper Lig", "sport": "Futbol",
                      "season": "2026-27 Turkish Super Lig", "updated_at": "2026-09-06T22:00:00+03:00",
                      "teams": 1,
                      "rows": [{"rank": 1, "team": "Galatasaray", "sourceTeam": "Galatasaray",
                                "abbr": "GAL", "logo": "", "played": 4, "wins": 3, "draws": 1,
                                "losses": 0, "goalsFor": 12, "goalsAgainst": 6, "diff": 6,
                                "points": 10, "note": ""}]}]}, ensure_ascii=False), encoding="utf-8")
    import requests
    out = refresh(exc=requests.ConnectionError("kapalı"))
    assert len(out["leagues"]) == 1, "kaynak kesilince son tablo korunmalı"
    assert rows_of(out)[0]["team"] == "Galatasaray"
    assert out["leagues"][0]["updated_at"] == "2026-09-06T22:00:00+03:00"


def test_empty_response_yields_no_league_and_no_invented_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(standings, "STANDINGS_OUTPUT", tmp_path / "missing.json")
    out = refresh(payload())
    assert out["leagues"] == []
    assert standings.summary(out) == "puan durumu yok"
    assert standings.load_or_build(NOW)["leagues"] == []


def test_malformed_paths_are_not_requested():
    cfg = {"enabled": True, "max_workers": 1,
           "leagues": [{"name": "X", "sport": "Futbol", "path": "../etc/passwd"},
                       {"name": "Y", "sport": "Futbol", "path": "soccer/tur.1"}]}
    called = []

    def fetch(url, timeout):
        called.append(url)
        return payload(entry("Galatasaray", "GAL", 4, 3, 1, 0, 12, 6, 6, 10, 1))
    standings.refresh(now=NOW, fetch=fetch, write=False, settings=cfg)
    assert called == [standings.API_BASE + "soccer/tur.1/standings"]


def test_disabled_config_returns_previous_table(monkeypatch, tmp_path):
    monkeypatch.setattr(standings, "STANDINGS_OUTPUT", tmp_path / "standings.json")
    standings.STANDINGS_OUTPUT.write_text(json.dumps(
        {"source": "espn", "generated_at": "", "leagues": [{"id": "soccer/tur.1", "name": "L", "rows": []}]}),
        encoding="utf-8")
    out = standings.refresh(now=NOW, fetch=lambda u, t: payload(), write=False,
                            settings={"enabled": False, "leagues": []})
    assert out["leagues"][0]["id"] == "soccer/tur.1"


def test_refresh_writes_output_file(monkeypatch, tmp_path):
    out_path = tmp_path / "standings.json"
    monkeypatch.setattr(standings, "STANDINGS_OUTPUT", out_path)
    standings.refresh(now=NOW, fetch=lambda u, t: payload(
        entry("Galatasaray", "GAL", 4, 3, 1, 0, 12, 6, 6, 10, 1)), write=True, settings=CFG)
    assert out_path.exists()
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["leagues"][0]["rows"][0]["team"] == "Galatasaray"


def test_repo_config_targets_superlig_only():
    cfg = standings.load_config()
    paths = [l["path"] for l in cfg.get("leagues", [])]
    assert paths == ["soccer/tur.1"], "yapılandırma yalnızca Trendyol Süper Lig içermeli"
    assert cfg.get("enabled") is True


def test_seeded_output_is_real_and_internally_consistent():
    """output/standings.json: her satır kendi içinde tutarlı olmalı (uydurma yok)."""
    data = standings.load_or_build(NOW)
    leagues = data.get("leagues") or []
    if not leagues:
        pytest.skip("output/standings.json henüz üretilmedi")
    rows = leagues[0]["rows"]
    assert len(rows) >= 18
    for r in rows:
        assert r["wins"] + r["draws"] + r["losses"] == r["played"], r["team"]
        assert r["goalsFor"] - r["goalsAgainst"] == r["diff"], r["team"]
        assert r["wins"] * 3 + r["draws"] == r["points"], r["team"]
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1)), "sıra 1..N olmalı"
    points = [r["points"] for r in rows]
    assert points == sorted(points, reverse=True), "tablo puana göre azalmalı"
