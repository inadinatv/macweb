"""Güncel site adresini (ayna alan adı) takip eden modül.

fixbettv tarzı siteler numaralı alan adları kullanır (fixbettv84.com,
fixbettv85.com, ...). Bu modül:
  * config/mirrors.yml içindeki kalıp ve aralıklardaki adayları denetler,
  * HTTP 200 dönen ve "maç izle" işareti taşıyan adresleri bulur,
  * en güvenilir/güncel adresi seçip config/current_site.yml dosyasına yazar.
"""
from __future__ import annotations

import concurrent.futures as cf
import time
from datetime import datetime, timezone
from typing import Any

import requests

from . import config


def _probe(domain: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Tek bir alan adını denetler ve sonucu döndürür."""
    checks = settings.get("health_checks", {})
    timeout = checks.get("timeout_seconds", 8)
    expect = checks.get("expect_status", 200)
    must_contain = checks.get("must_contain_any", [])
    headers = settings.get("data_source", {}).get("headers", {})

    result: dict[str, Any] = {
        "domain": domain,
        "url": f"https://{domain}/",
        "healthy": False,
        "status": None,
        "reason": "",
    }
    try:
        resp = requests.get(
            result["url"],
            timeout=timeout,
            headers=headers,
            allow_redirects=checks.get("follow_redirects", True),
        )
        result["status"] = resp.status_code
        if resp.status_code != expect:
            result["reason"] = f"HTTP {resp.status_code} (beklenen {expect})"
            return result
        # İçerikte beklenen işaretlerden en az biri mi var?
        text = resp.text[:120000]
        if must_contain and not any(tok in text for tok in must_contain):
            result["reason"] = "Sayfa içeriği maç izleme işaretini taşımıyor"
            return result
        result["healthy"] = True
        result["reason"] = "OK"
        # Olası yönlendirmelerden sonra nihai etki alanı
        result["domain"] = resp.url.split("/")[2] if "//" in resp.url else domain
        result["url"] = resp.url
    except requests.exceptions.RequestException as exc:  # ağ/DNS hatası
        result["reason"] = type(exc).__name__
    return result


def _candidate_domains(mirrors: dict[str, Any]) -> list[tuple[str, int]]:
    """{'kalıp': {n: str}} şeklinde tarama numaralarını üretir.

    Önce bilinen son numaranın çevresindeki pencere, sonra tüm aralık taranır.
    """
    patterns = mirrors.get("patterns", [])
    rng = mirrors.get("range_numbers", {})
    start = rng.get("start", 1)
    end = rng.get("end", 200)
    window = int(mirrors.get("scan_window", 12))
    preferred = int(mirrors.get("preferred_number", 0))

    numbers = list(range(start, end + 1))

    # Pencereyi öne al (önce bilinen adresin çevresi taranır)
    if preferred:
        surround = list(range(preferred - window, preferred + window + 1))
        numbers = [n for n in surround if n in numbers] + [
            n for n in numbers if n not in surround
        ]

    out: list[tuple[str, int]] = []
    for pat in patterns:
        for n in numbers:
            out.append((pat.format(n=n), n))
    return out


def check_current_site() -> dict[str, Any]:
    """Aday alan adlarını tarar ve güncel site adresini current_site.yml'e yazar."""
    mirrors = config.load_mirrors()
    settings = config.load_settings()

    candidates = _candidate_domains(mirrors)
    workers = min(24, max(8, len(candidates)))

    results: list[dict[str, Any]] = []
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(lambda c: _probe(c[0], settings), candidates):
            results.append(res)

    active = [r for r in results if r["healthy"]]

    # Tercih edilen numara daha öncelikli olsun diye sırala
    active.sort(key=lambda r: abs(_num(r["domain"], mirrors) - mirrors.get("preferred_number", 0)))

    previous = config.load_current_site()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    primary = active[0] if active else {
        "domain": None,
        "url": None,
        "healthy": False,
        "reason": "Hiçbir aday adres çalışmıyor",
    }
    # Eğer hiçbir alan adı bulunamadıysa, önceki bilinen adresi koru
    if not active and previous.get("current_address"):
        primary = {
            "domain": previous.get("base_domain"),
            "url": previous.get("current_address"),
            "healthy": False,
            "reason": "İzleme başarısız, son bilinen adres korunuyor",
        }

    data = {
        "base_domain": primary["domain"],
        "current_address": primary["url"],
        "healthy": bool(active),
        "mirror_now": primary["domain"],
        "state": "OK" if active else "DOWN",
        "active_mirrors": [r["domain"] for r in active],
        "last_checked": now_iso,
        "note": primary["reason"],
        "probed": len(results),
    }
    config.save_current_site(data)
    return data


def _num(domain: str, mirrors: dict[str, Any]) -> int:
    """Alan adındaki numarayı çıkarır (fixbettv84 -> 84). Yoksa 0."""
    for pat in mirrors.get("patterns", []):
        prefix = pat.replace("{n}", "")
        body = domain.split(".")[0]
        if body.startswith(prefix):
            rest = body[len(prefix):]
            if rest.isdigit():
                return int(rest)
    # Genel: sayıları süz
    nums = [c for c in domain if c.isdigit()]
    return int("".join(nums)) if nums else 0


def log(data: dict[str, Any]) -> None:
    """git/console için kısa özet çıktısı."""
    ts = time.strftime("%H:%M:%S")
    state = data.get("state")
    addr = data.get("current_address")
    print(f"[{ts}] site:{state} address={addr} mirror={data.get('mirror_now')}")
