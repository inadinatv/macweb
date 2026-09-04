"""Ham HTML'i (matches.php / matches2.php) yapılandırılmış Maç listesine çevirir."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from . import config
from .models import Match

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
    parts = event.split("|")
    league = parts[-1].strip() if len(parts) > 1 else event.strip()
    return league, is_mod


def _parse_rich(soup: BeautifulSoup, mod_token: str) -> list[Match]:
    matches: list[Match] = []
    for a in soup.select("a[href*='channel?id=']"):
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
        tstr = time_m.group(1).replace("h", ":").replace(".", ":") if time_m else ""

        match_id = a["href"].split("id=", 1)[-1]
        imgs = a.find_all("img")
        logo_home = imgs[0]["src"] if imgs else None
        logo_away = imgs[-1]["src"] if len(imgs) > 1 else None

        m = Match(
            match_id=match_id,
            home=home_el.get_text(strip=True),
            away=away_el.get_text(strip=True),
            league=league,
            time=tstr,
            sport=(date_el.get_text(strip=True) if date_el else ""),
            is_match_of_day=is_mod,
            channel_id=match_id,
            logo_home=logo_home,
            logo_away=logo_away,
            raw_event=event,
        )
        matches.append(m)
    return matches


def _parse_simple(soup: BeautifulSoup) -> list[Match]:
    matches: list[Match] = []
    settings = config.load_settings()
    mod_token = settings.get("categorize", {}).get("match_of_day_token", _MOD_TOKEN)
    for a in soup.select("a[href*='channel?id=']"):
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
        match_id = a["href"].split("id=", 1)[-1]

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
        ))
    return matches
