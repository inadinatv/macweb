"""Ham HTML'i (matches.php / matches2.php) yapılandırılmış Maç listesine çevirir."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from . import config
from .models import Match
from .match_state import normalize_status, score_pair

_MOD_TOKEN = '[Günün Maçı]'


def parse(raw_html: str) -> list[Match]:
    """HTML'i ayrıştırır; zengin (matches.php) ve basit (matches2.php) formatlarını tanır."""
    settings = config.load_settings()
    cat = settings.get("categorize", {})
    mod_token = cat.get("match_of_day_token", _MOD_TOKEN)

    soup = BeautifulSoup(raw_html or "", "html.parser")

    # 1) Zengin format: href="channel?id=..." + div.date/event/home/away
    rich = _parse_rich(soup, mod_token)
    if rich:
        return rich

    # 2) Basit format: href="channel?id=..." + .channel-name / .channel-status
    simple = _parse_simple(soup)
    return simple


def _norm_league(event: str, mod_token: str) -> tuple[str, bool]:
    """'20:00 | Trendyol Süper Lig [Günün Maçı]' -> ('Trendyol Süper Lig', True)"""
    is_mod = False
    if mod_token and mod_token in event:
        is_mod = True
        event = event.replace(mod_token, "").strip()
    parts = [p.strip() for p in event.split("|") if p.strip() and not normalize_status(p)]
    league = parts[-1] if parts else ""
    return league, is_mod


def _parse_rich(soup: BeautifulSoup, mod_token: str) -> list[Match]:
    matches: list[Match] = []
    for a in soup.select("a[href*='channel']"):
        match_id = _channel_id(a.get("href", ""))
        if not match_id:
            continue
        detail = a.select_one(".match-detail")
        if not detail:
            continue
        date_el = detail.select_one(".date")
        event_el = detail.select_one(".event")
        home_el = detail.select_one(".home")
        away_el = detail.select_one(".away")
        if not (event_el and home_el and away_el):
            continue
        event = event_el.get_text(strip=True)
        league, is_mod = _norm_league(event, mod_token)
        time_m = re.match(r"(\d{1,2}[:.hH]\d{2})", event)
        tstr = time_m.group(1).lower().replace("h", ":").replace(".", ":") if time_m else ""

        imgs = a.find_all("img")
        logo_home = (imgs[0].get("src") or imgs[0].get("data-src")) if imgs else None
        logo_away = (imgs[-1].get("src") or imgs[-1].get("data-src")) if len(imgs) > 1 else None

        m = Match(
            match_id=match_id,
            home=_team_name(home_el),
            away=_team_name(away_el),
            league=league,
            time=tstr,
            sport=(date_el.get_text(strip=True) if date_el else ""),
            is_match_of_day=is_mod,
            channel_id=match_id,
            logo_home=logo_home,
            logo_away=logo_away,
            raw_event=event,
            **_outcome(a),
        )
        matches.append(m)
    return matches


def _parse_simple(soup: BeautifulSoup) -> list[Match]:
    matches: list[Match] = []
    settings = config.load_settings()
    mod_token = settings.get("categorize", {}).get("match_of_day_token", _MOD_TOKEN)
    for a in soup.select("a[href*='channel']"):
        match_id = _channel_id(a.get("href", ""))
        if not match_id:
            continue
        name_el = a.select_one(".channel-name")
        status_el = a.select_one(".channel-status")
        if not (name_el and status_el):
            continue
        name = name_el.get_text(strip=True)
        status = status_el.get_text(strip=True)
        time_m = re.match(r"(\d{1,2}[:.]\d{2})", status)
        tstr = time_m.group(1).replace(".", ":") if time_m else ""
        # "Home vs Away" ayrıştır
        parts = re.split(r"\s+vs\.?\s+|\s+–\s+|\s+-\s+", name, maxsplit=1)
        home = parts[0].strip()
        away = parts[1].strip() if len(parts) > 1 else ""
        league, is_mod = _norm_league(status, mod_token)

        matches.append(Match(
            match_id=match_id,
            home=home,
            away=away,
            league=league,
            time=tstr,
            sport=settings.get("categorize", {}).get("default_sport", "Spor"),
            is_match_of_day=is_mod,
            channel_id=match_id,
            raw_event=status,
            **_outcome(a),
        ))
    return matches


def _channel_id(href: str) -> str:
    return (parse_qs(urlsplit(href).query).get("id") or [""])[0]


def _team_name(element) -> str:
    # Bazı sağlayıcılar skoru takım div'inin içine yerleştirir.
    clone = BeautifulSoup(str(element), "html.parser")
    for score in clone.select(".score, .home-score, .away-score, .score-home, .score-away"):
        score.decompose()
    return clone.get_text(" ", strip=True)


def _outcome(card) -> dict:
    """Sadece açık durum/skor alanlarını okur; saat, lig veya hidden sınıfını değil."""
    candidates = []
    for node in [card, *card.select("[data-status], [data-match-status]")]:
        candidates.extend([node.get("data-status"), node.get("data-match-status")])
    for node in card.select(".match-status, .status, .channel-status"):
        candidates.extend(node.get_text(" ", strip=True).split("|"))
    raw = next((str(v).strip() for v in candidates if normalize_status(v)), "")
    status = normalize_status(raw)

    def read(side):
        for node in [card, *card.select(f"[data-{side}-score], [data-score-{side}]")]:
            for attr in (f"data-{side}-score", f"data-score-{side}"):
                if node.has_attr(attr):
                    return node[attr]
        node = card.select_one(f".{side}-score, .score-{side}, .{side} .score")
        return node.get_text(strip=True) if node else None

    h, a = read("home"), read("away")
    if h is None and a is None:
        node = card.select_one(".match-score, .final-score")
        pair = re.fullmatch(r"\s*(\d{1,3})\s*[-–:]\s*(\d{1,3})\s*", node.get_text() if node else "")
        if pair:
            h, a = pair.groups()
    h, a = score_pair(h, a)
    return {
        "status": status or "upcoming", "status_source": "source" if status else "schedule",
        "raw_status": raw, "score_home": h, "score_away": a,
        "score_source": "source" if h is not None else "",
        "event_id": str(card.get("data-event-id") or ""),
    }
