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


# ---------------------------------------------------------------------------
# Takım adı tekrarı + sıra bölgeleri (Avrupa hattı / küme düşme hattı)
# ---------------------------------------------------------------------------

SUPERLIG = [
    # (takım, O, G, B, M, A, Y, P) — hepsi kendi içinde tutarlı gerçek biçim
    ("Galatasaray", 5, 4, 1, 0, 13, 6, 13),
    ("Beşiktaş", 5, 4, 0, 1, 12, 4, 12),
    ("Amed SK", 5, 3, 1, 1, 12, 5, 10),
    ("Kasımpaşa", 5, 2, 3, 0, 7, 5, 9),
    ("Ç. Rizespor", 5, 3, 0, 2, 5, 4, 9),
    ("Kocaelispor", 5, 3, 0, 2, 5, 4, 9),
    ("Alanyaspor", 5, 2, 2, 1, 6, 5, 8),
    ("Trabzonspor", 5, 2, 1, 2, 9, 5, 7),
    ("Çorum FK", 5, 2, 1, 2, 12, 10, 7),
    ("Gaziantep FK", 4, 2, 1, 1, 7, 5, 7),
    ("Gençlerbirliği", 5, 2, 1, 2, 5, 9, 7),
    ("Fenerbahçe", 4, 2, 0, 2, 8, 6, 6),
    ("Başakşehir", 5, 1, 1, 3, 6, 11, 4),
    ("Samsunspor", 5, 1, 1, 3, 6, 11, 4),
    ("Erzurumspor FK", 5, 1, 1, 3, 2, 11, 4),
    ("Konyaspor", 5, 1, 0, 4, 4, 8, 3),
    ("Eyüpspor", 5, 1, 0, 4, 2, 8, 3),
    ("Göztepe", 5, 0, 2, 3, 9, 13, 2),
]


def standings_html(teams=SUPERLIG):
    """iddaa/mackolik biçiminde tablo: takım adı hücrede İKİ kez basılır.

    Kaynak, masaüstü ve mobil görünüm için adı yan yana yazar; ``get_text()``
    bunları ayraçsız yapıştırır ("GalatasarayGalatasaray"). Test bu bozuk
    biçimi birebir üretir.
    """
    head = "".join(f"<th>{h}</th>" for h in ("#", "Takım", "O", "G", "B", "M", "A", "Y", "Av", "P"))
    body = ""
    for i, (name, played, wins, draws, losses, gf, ga, points) in enumerate(teams, start=1):
        body += (
            "<tr>"
            f"<td>{i}</td>"
            '<td class="team-cell"><a href="/takim/ornek">'
            f'<img src="//file.mackolikfeeds.com/teams/ornek{i}" alt="{name}" />'
            f'<span class="d-none d-sm-inline">{name}</span><span class="d-sm-none">{name}</span>'
            "</a></td>"
            f"<td>{played}</td><td>{wins}</td><td>{draws}</td><td>{losses}</td>"
            f"<td>{gf}</td><td>{ga}</td><td>{gf - ga}</td><td>{points}</td>"
            "</tr>")
    return f"<html><body><table class='standings'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></body></html>"


def refresh_html(html, monkeypatch, tmp_path, cfg=None):
    """Ağsız: HTML kaynağı sabitlenir, iddaa/mackolik ayrıştırıcısı çalışır."""
    monkeypatch.setattr(standings, "STANDINGS_OUTPUT", tmp_path / "standings.json")
    monkeypatch.setattr(standings, "_fetch_html", lambda url, timeout: html)
    settings = dict(CFG)
    settings.update(cfg or {})
    return standings.refresh(now=NOW, write=False, settings=settings)


def test_dedupe_team_name_collapses_repetition_without_touching_other_text():
    assert standings.dedupe_team_name("GalatasarayGalatasaray") == "Galatasaray"
    assert standings.dedupe_team_name("Amed SKAmed SK") == "Amed SK"
    assert standings.dedupe_team_name("Amed SK Amed SK") == "Amed SK"
    assert standings.dedupe_team_name("Ç. RizesporÇ. Rizespor") == "Ç. Rizespor"
    # Tekrar yoksa ad aynen kalır (kısaltılmaz/uydurulmaz)
    for name in ("Fenerbahçe", "Beşiktaş", "Kocaelispor", "Erzurumspor FK", "İstanbul Başakşehir"):
        assert standings.dedupe_team_name(name) == name
    assert standings.dedupe_team_name("") == ""
    assert standings.dedupe_team_name(None) == ""


def test_duplicated_team_cell_is_written_once_and_localized(monkeypatch, tmp_path):
    # depo yapılandırmasındaki görünen ad eşlemesiyle uçtan uca: tekrar temizlenir,
    # sonra Türkçe ad uygulanır (Amed SK → Amed SFK).
    repo_names = standings.load_config().get("display_names")
    out = refresh_html(standings_html(), monkeypatch, tmp_path, {"display_names": repo_names})
    rows = rows_of(out)
    assert len(rows) == 18, "18 takımın hepsi okunmalı"
    names = [r["team"] for r in rows]
    assert names[0] == "Galatasaray", "yapışık tekrar temizlenmeli: " + names[0]
    assert not any(n != standings.dedupe_team_name(n) for n in names), "tekrarlı ad kaldı"
    assert "Amed SFK" in names, "temizlenen ad display_names ile eşleşmeli"
    assert "Çaykur Rizespor" in names and "Erzurum BB" in names
    # sayılar kaynaktan geldiği gibi kalır (ad temizliği değeri değiştirmez)
    top = rows[0]
    assert (top["played"], top["wins"], top["draws"], top["losses"]) == (5, 4, 1, 0)
    assert (top["goalsFor"], top["goalsAgainst"], top["diff"], top["points"]) == (13, 6, 7, 13)
    assert top["logo"] == "https://file.mackolikfeeds.com/teams/ornek1", "logo https'e tamamlanmalı"


def test_top_three_and_bottom_three_are_marked_as_zones(monkeypatch, tmp_path):
    rows = rows_of(refresh_html(standings_html(), monkeypatch, tmp_path))
    zones = {r["rank"]: (r["zone"], r["zoneLabel"]) for r in rows}
    assert zones[1] == ("champions", "Şampiyonlar Ligi"), "lider Avrupa'nın bir üst hattında olmalı"
    assert zones[2] == ("europa", "Avrupa kupaları")
    assert zones[3] == ("europa", "Avrupa kupaları")
    assert zones[16] == zones[17] == zones[18] == ("relegation", "Küme düşme hattı")
    for rank in range(4, 16):
        assert zones[rank] == ("", ""), f"{rank}. sıra işaretsiz olmalı"


def test_zone_rules_come_from_config_and_can_be_disabled(monkeypatch, tmp_path):
    custom = {"zones": {"soccer/tur.1": {"top": [{"count": 4, "kind": "europa", "label": "Avrupa"}],
                                         "bottom": [{"count": 2, "kind": "relegation", "label": "Düşme"}]}}}
    rows = {r["rank"]: r["zone"] for r in rows_of(refresh_html(standings_html(), monkeypatch, tmp_path, custom))}
    assert [rows[i] for i in range(1, 6)] == ["europa"] * 4 + [""], "yapılandırma 4 sıra istedi"
    assert rows[17] == rows[18] == "relegation" and rows[16] == ""

    disabled = {"zones": {"soccer/tur.1": {}}}
    rows = rows_of(refresh_html(standings_html(), monkeypatch, tmp_path, disabled))
    assert all(r["zone"] == "" and r["zoneLabel"] == "" for r in rows), "bölge kapatılınca işaret basılmamalı"


def test_zones_are_not_marked_on_short_tables():
    rules = standings.DEFAULT_ZONES
    assert standings.zone_rank_map(rules, 18)[1]["kind"] == "champions"
    assert standings.zone_rank_map(rules, 6) == {}, "6 takımlık tabloda bölge anlamsız"
    # alt bölge üst bölgenin üzerine yazmaz
    tight = standings.zone_rank_map(rules, 8)
    assert tight[1]["kind"] == "champions" and tight[8]["kind"] == "relegation"
    assert 4 not in tight and 5 not in tight


def test_espn_notes_also_produce_zones():
    out = refresh(payload(
        entry("Galatasaray", "GAL", 4, 3, 1, 0, 12, 6, 6, 10, 1, "Champions League"),
        entry("Besiktas", "BES", 4, 3, 0, 1, 9, 4, 5, 9, 2, "UEFA Europa League"),
        *[entry(f"T{i}", f"T{i}", 4, 1, 1, 2, 4, 5, -1, 4, i) for i in range(3, 18)],
        entry("Konyaspor", "KNY", 4, 0, 0, 4, 3, 8, -5, 0, 18, "Relegated")))
    rows = {r["rank"]: r for r in rows_of(out)}
    assert rows[1]["zone"] == "champions" and rows[1]["note"] == "Champions League", "kaynak notu korunmalı"
    assert rows[2]["zone"] == "europa"
    assert rows[18]["zone"] == "relegation" and rows[18]["note"] == "Relegated"
    assert rows[10]["zone"] == ""


def test_kept_previous_table_is_cleaned_and_keeps_its_real_source(monkeypatch, tmp_path):
    """Kaynak kesilince son tablo korunur; adı/bölgeleri tazelenir, kaynak etiketi bozulmaz."""
    monkeypatch.setattr(standings, "STANDINGS_OUTPUT", tmp_path / "standings.json")
    standings.STANDINGS_OUTPUT.write_text(json.dumps(
        {"source": "mackolik", "generated_at": "2026-09-13T22:00:00+03:00",
         "leagues": [{"id": "soccer/tur.1", "name": "Trendyol Süper Lig", "sport": "Futbol",
                      "season": "2026-27", "updated_at": "2026-09-13T22:00:00+03:00", "teams": 18,
                      "rows": [{"rank": i + 1,
                                "team": name + name, "sourceTeam": name + name, "abbr": "", "logo": "",
                                "played": 5, "wins": 2, "draws": 1, "losses": 2, "goalsFor": 6,
                                "goalsAgainst": 6, "diff": 0, "points": 7, "note": ""}
                               for i, name in enumerate(n for n, *_ in SUPERLIG)]}]},
        ensure_ascii=False), encoding="utf-8")
    import requests
    out = refresh(exc=requests.ConnectionError("kapalı"))
    rows = rows_of(out)
    assert out["source"] == "mackolik", "okunamayan turda kaynak etiketi uydurulmamalı"
    assert rows[0]["team"] == "Galatasaray", "korunan tabloda tekrarlı ad temizlenmeli"
    assert rows[0]["zone"] == "champions" and rows[17]["zone"] == "relegation"
    assert rows[0]["points"] == 7 and rows[0]["played"] == 5, "sayılar değişmemeli"
    assert rows_of(standings.load_or_build(NOW))[0]["team"] == "Galatasaray"


def test_repo_config_declares_superlig_zones():
    cfg = standings.load_config()
    rules = standings.zone_rules(cfg, "soccer/tur.1")
    assert rules, "config/standings.yml bölge tanımlamalı"
    top = standings.zone_rank_map(rules, 18)
    assert sorted(k for k, v in top.items() if v["kind"] == "relegation") == [16, 17, 18]
    assert sorted(k for k, v in top.items() if v["kind"] != "relegation") == [1, 2, 3]


def test_seeded_output_has_clean_names_and_zones():
    """output/standings.json: ad tekrarı yok, ilk 3 ve son 3 sıra işaretli."""
    data = standings.load_or_build(NOW)
    leagues = data.get("leagues") or []
    if not leagues or not leagues[0].get("rows"):
        pytest.skip("output/standings.json henüz üretilmedi")
    rows = leagues[0]["rows"]
    for r in rows:
        assert r["team"] == standings.dedupe_team_name(r["team"]), "tekrarlı takım adı: " + r["team"]
        assert "zone" in r and "zoneLabel" in r
    assert [r["zone"] for r in rows[:3]] == ["champions", "europa", "europa"]
    assert [r["zone"] for r in rows[-3:]] == ["relegation"] * 3
    assert all(r["zone"] == "" for r in rows[3:-3])
