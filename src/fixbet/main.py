"""fixbet-bot CLI orkestratörü.

Kullanım:
    python -m fixbet.main run           # tam boru hattı: site -> maçlar -> kategori -> raporlar
    python -m fixbet.main update-site   # sadece güncel adresi güncelle (current_site.yml)
    python -m fixbet.main matches       # sadece maçları çek ve kategorize et
    python -m fixbet.main build-index   # output/ verisinden index.html üret (çevrimdışı)
    python -m fixbet.main extras        # sadece ekstra panelleri (m3u8) çözümle
    python -m fixbet.main serve [dk]    # sürekli çalışan izleme modu (aralık=dk dakika, vars. 5)
    python -m fixbet.main cat           # kategorize edilmiş özeti konsola yaz
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import categorizer, channels, config, domain_checker, extras, parser, reports, scraper, scores, site
from .models import Match

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
    site_info = domain_checker.check_current_site()
    domain_checker.log(site_info)

    # 2) Maç listesini çek
    try:
        raw = scraper.fetch_matches_html()
    except Exception as exc:  # kaynak geçici olarak erişilemezse önceki adresle devam
        print(f"[!] Kaynak çekilemedi: {exc} — önceki adresle devam ediliyor.")
        raw = ""

    matches = parser.parse(raw)
    if not matches:
        # Kaynak geçici olarak boş/erişilemez döndüyse sayfayı boşaltma:
        # aynı günün son gerçek maç listesini kullan.
        matches = load_matches_from_output(now)
        if matches:
            print(f"[!] Kaynak boş döndü — son gerçek liste kullanılıyor ({len(matches)} maç).")
    matches = categorizer.enrich(matches)
    matches = refresh_scores(matches, now)
    matches = categorizer.classify(matches, now)
    categorized = categorizer.categorize(matches, now)

    # 2b) 7/24 kanal listesi (güncel adresin ana sayfasından)
    channels_data = channels.categorize(channels.fetch_channels())

    # 2c) Ekstra paneller (Atom Spor vb. doğrudan m3u8 kaynakları) -> output/extra_channels.json
    extra_data = refresh_extras(now)

    # 2d) GitHub Pages için repo köküne index.html üret (güncel adres + maçlar + extra)
    site.build_index_html(matches, channels_data, extra_data=extra_data)

    # 3) Raporlar
    reports.write_json_data(matches, categorized, site_info, channels_data)
    reports.write_markdown(categorized, site_info, channels_data)
    reports.write_html(categorized, site_info, channels_data)

    # 4) Otomatik yayınlama (settings.yml -> git.autorelease)
    from . import publisher
    try:
        publisher.autorelease()
    except Exception as exc:
        print(f"[!] yayınlama adımı hatası: {exc}")

    return {"site": site_info, "categorized": categorized, "matches": matches, "now": now}


def refresh_scores(matches: list[Match], now: datetime) -> list[Match]:
    """İkincil skor kaynağındaki hata maç/kanal boru hattını durdurmasın."""
    try:
        return scores.enrich(matches, now, previous=load_matches_from_output(now))
    except Exception as exc:
        print(f"[!] Skor güncellemesi tamamlanamadı ({type(exc).__name__}); maç programı korunuyor.")
        return matches


def refresh_extras(now: datetime | None = None) -> dict:
    """Ekstra panellerin m3u8 adreslerini yeniler; hata olursa son çıktıyla devam eder."""
    try:
        data = extras.refresh(now)
        print(f"[extras] {extras.summary(data)}")
        return data
    except Exception as exc:  # noqa: BLE001 - ekstra panel ana akışı durdurmasın
        print(f"[!] Ekstra paneller çözümlenemedi: {exc} — son bilinen liste kullanılıyor.")
        return extras.load_or_build(now)


def load_matches_from_output(now: datetime | None = None) -> list[Match]:
    """output/today_matches.json içindeki son gerçek maç listesini Match olarak yükler.

    Yalnızca aynı günün verisi döner (bayat liste sayfaya basılmasın).
    """
    import json

    now = now or _now()
    path = config.OUTPUT_DIR / "today_matches.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    if data.get("date") != now.strftime("%Y-%m-%d"):
        return []
    fields = set(Match.__dataclass_fields__)
    return [Match(**{k: v for k, v in row.items() if k in fields})
            for row in data.get("matches", [])]


def build_index_from_output() -> str | None:
    """output/ altındaki son gerçek veriden index.html'i yeniden üretir (çevrimdışı).

    Şablon değiştiğinde veya ağ yokken sayfayı tazelemek için kullanılır:
        python fixbet.py build-index
    """
    import json

    now = _now()
    matches = load_matches_from_output(now)
    if not matches:
        print(f"[!] {config.OUTPUT_DIR / 'today_matches.json'} yok ya da bayat — "
              "önce 'python fixbet.py run' çalıştırın.")
        return None

    channels_data: dict = {}
    ch_path = config.OUTPUT_DIR / "channels.json"
    if ch_path.exists():
        channels_data = json.loads(ch_path.read_text(encoding="utf-8")).get("channels", {})

    matches = categorizer.classify(matches, now)
    extra_data = extras.load_or_build(now)
    out = site.build_index_html(matches, channels_data, now, extra_data=extra_data)
    live = sum(1 for m in matches if m.status == "live")
    print(f"index.html üretildi: {out}")
    print(f"  {len(matches)} maç ({live} canlı) · {channels_data.get('total', 0)} kanal · "
          f"{extra_data.get('total', 0)} extra (m3u8)")
    return out


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
    sub.add_parser("build-index", help="output/ verisinden index.html'i yeniden üret (çevrimdışı)")
    sub.add_parser("extras", help="Sadece ekstra panelleri (m3u8 kanallar) çözümle ve sayfayı güncelle")
    sub.add_parser("matches", help="Maçları çek ve kategorize et")
    sub.add_parser("cat", help="Özeti konsola bas")
    web_parser = sub.add_parser("web", help="Sayfa + isteğe bağlı HLS proxy hizmeti (HTTPS reverse proxy arkasında)")
    web_parser.add_argument("--host", default="0.0.0.0")
    web_parser.add_argument("--port", type=int, default=8000)
    diag_parser = sub.add_parser("diagnose-stream", help="HLS playlist/segment HTTP, MIME, CORS ve codec tanılaması")
    diag_parser.add_argument("channel_id", help="örn. atom:bein-sports-1")
    diag_parser.add_argument("--source", type=int, default=0)
    diag_parser.add_argument("--page-origin", default="https://inadinatv.github.io")

    s = sub.add_parser("serve", help="Sürekli izleme")
    s.add_argument("interval", nargs="?", type=int, default=5, help="dakika cinsinden aralık")

    args = parser_.parse_args(argv)

    if args.cmd == "diagnose-stream":
        import json
        from .diagnostics import diagnose
        try:
            result = diagnose(args.channel_id, args.source, args.page_origin)
        except ValueError as exc:
            print(f"[!] {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "web":
        from .web import serve as serve_web
        serve_web(args.host, args.port)
        return 0
    if args.cmd in (None, "run"):
        result = pipeline()
        _print_summary(result)
        return 0
    if args.cmd == "build-index":
        return 0 if build_index_from_output() else 1
    if args.cmd == "extras":
        now = _now()
        data = refresh_extras(now)
        print(f"Ekstra: {extras.summary(data)}")
        # Sayfayı da tazele (eldeki son maç/kanal verisiyle)
        matches = categorizer.classify(load_matches_from_output(now), now)
        import json as _json
        ch_path = config.OUTPUT_DIR / "channels.json"
        channels_data = (_json.loads(ch_path.read_text(encoding="utf-8")).get("channels", {})
                         if ch_path.exists() else {})
        site.build_index_html(matches, channels_data, now, extra_data=data)
        return 0
    if args.cmd == "update-site":
        site_info = domain_checker.check_current_site()
        domain_checker.log(site_info)
        return 0
    if args.cmd == "matches":
        now = _now()
        raw = scraper.fetch_matches_html()
        matches = parser.parse(raw)
        matches = categorizer.enrich(matches)
        matches = refresh_scores(matches, now)
        matches = categorizer.classify(matches, now)
        categorized = categorizer.categorize(matches, now)
        channels_data = channels.categorize(channels.fetch_channels())
        reports.write_json_data(matches, categorized, config.load_current_site(), channels_data)
        _print_summary({"categorized": categorized, "site": config.load_current_site()})
        return 0
    if args.cmd == "cat":
        now = _now()
        raw = scraper.fetch_matches_html()
        matches = refresh_scores(categorizer.enrich(parser.parse(raw)), now)
        matches = categorizer.classify(matches, now)
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
