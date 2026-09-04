"""fixbet-bot CLI orkestratörü.

Kullanım:
    python -m fixbet.main run           # tam boru hattı: site -> maçlar -> kategori -> raporlar
    python -m fixbet.main update-site   # sadece güncel adresi güncelle (current_site.yml)
    python -m fixbet.main matches       # sadece maçları çek ve kategorize et
    python -m fixbet.main serve [dk]    # sürekli çalışan izleme modu (aralık=dk dakika, vars. 5)
    python -m fixbet.main cat           # kategorize edilmiş özeti konsola yaz
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import categorizer, config, domain_checker, parser, reports, scraper

TZ = ZoneInfo("Europe/Istanbul")


def _now() -> datetime:
    settings = config.load_settings()
    tz_name = settings.get("bot", {}).get("timezone", "Europe/Istanbul")
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.now()


def pipeline() -> dict:
    """Tam boru hattı çalıştırır ve sonuçları döndürür."""
    now = _now()

    # 1) Güncel site adresini güncelle
    site = domain_checker.check_current_site()
    domain_checker.log(site)

    # 2) Maç listesini çek
    try:
        raw = scraper.fetch_matches_html()
    except Exception as exc:  # kaynak geçici olarak erişilemezse önceki adresle devam
        print(f"[!] Kaynak çekilemedi: {exc} — önceki adresle devam ediliyor.")
        raw = ""

    matches = parser.parse(raw)
    matches = categorizer.enrich(matches)
    matches = categorizer.classify(matches, now)
    categorized = categorizer.categorize(matches, now)

    # 2b) 7/24 kanal listesi (güncel adresin ana sayfasından)
    from . import channels
    channels_data = channels.categorize(channels.fetch_channels())

    # 3) Raporlar
    reports.write_json_data(matches, categorized, site, channels_data)
    reports.write_markdown(categorized, site, channels_data)
    reports.write_html(categorized, site, channels_data)

    # 4) Otomatik yayınlama (settings.yml -> git.autorelease)
    from . import publisher
    try:
        publisher.autorelease()
    except Exception as exc:
        print(f"[!] yayınlama adımı hatası: {exc}")

    return {"site": site, "categorized": categorized, "matches": matches, "now": now}


def _print_summary(result: dict) -> None:
    c = result["categorized"]["counts"]
    addr = result["site"].get("current_address") or "—"
    print(f"Adres : {addr}")
    print(f"Toplam : {c['total']} | Canlı: {c['live']} | Yaklaşan: {c['upcoming']} | "
          f"Bitti: {c['finished']} | Günün Maçı: {c['match_of_day']}")


def serve(interval_minutes: int) -> None:
    """Sürekli çalışan izleme modu."""
    interval = max(1, interval_minutes) * 60
    while True:
        started = time.time()
        print(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====")
        try:
            result = pipeline()
            _print_summary(result)
        except Exception as exc:
            print(f"[!] Döngü hatası: {exc}")
        elapsed = time.time() - started
        sleep_for = max(5, interval - elapsed)
        print(f"Beklenecek: {sleep_for:.0f} sn")
        time.sleep(sleep_for)


def main(argv: list[str] | None = None) -> int:
    parser_ = argparse.ArgumentParser(prog="fixbet", description=__doc__)
    sub = parser_.add_subparsers(dest="cmd")

    p = sub.add_parser("run", help="Tam boru hattı")
    p.add_argument("--quiet", action="store_true")

    sub.add_parser("update-site", help="Sadece güncel adresi güncelle")
    sub.add_parser("matches", help="Maçları çek ve kategorize et")
    sub.add_parser("cat", help="Özeti konsola bas")

    s = sub.add_parser("serve", help="Sürekli izleme")
    s.add_argument("interval", nargs="?", type=int, default=5, help="dakika cinsinden aralık")

    args = parser_.parse_args(argv)

    if args.cmd in (None, "run"):
        result = pipeline()
        _print_summary(result)
        return 0
    if args.cmd == "update-site":
        site = domain_checker.check_current_site()
        domain_checker.log(site)
        return 0
    if args.cmd == "matches":
        now = _now()
        raw = scraper.fetch_matches_html()
        matches = parser.parse(raw)
        matches = categorizer.enrich(matches)
        matches = categorizer.classify(matches, now)
        categorized = categorizer.categorize(matches, now)
        from . import channels
        channels_data = channels.categorize(channels.fetch_channels())
        reports.write_json_data(matches, categorized, config.load_current_site(), channels_data)
        _print_summary({"categorized": categorized, "site": config.load_current_site()})
        return 0
    if args.cmd == "cat":
        now = _now()
        raw = scraper.fetch_matches_html()
        matches = categorizer.classify(categorizer.enrich(parser.parse(raw)), now)
        categorized = categorizer.categorize(matches, now)
        _print_summary({"categorized": categorized, "site": config.load_current_site()})
        return 0
    if args.cmd == "serve":
        serve(args.interval)
        return 0

    parser_.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
