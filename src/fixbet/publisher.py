"""Otomatik yayınlama (commit + push) yardımcı modülü.

GitHub Actions içinde çalışırken output/ ve config/current_site.yml dosyalarında
değişiklik olduysa bunları kendi kendine commit edip push eder.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import config


def _run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} başarısız: {res.stderr.strip()}")
    return res.stdout.strip()


def autorelease() -> bool:
    """settings.yml'deki git.autorelease=true ve değişiklik varsa push eder."""
    settings = config.load_settings()
    git = settings.get("git", {})
    if not git.get("autorelease"):
        return False

    root = Path(config.ROOT)
    try:
        _run(["git", "-C", str(root), "add", "-A"])
        dirty = _run(["git", "-C", str(root), "status", "--porcelain"])
        if not dirty:
            print("[publisher] değişiklik yok, push gerekmiyor")
            return False
        msg = f"{git.get('message_prefix', '[bot] güncelleme')} {Path('output').as_posix()}/{config.OUTPUT_DIR.name}"
        _run(["git", "-C", str(root), "commit", "-m", msg, "--allow-empty"])
        branch = git.get("target_branch", "main")
        # repo'nun upstream'ine push
        _run(["git", "-C", str(root), "push", "origin", f"HEAD:{branch}"])
        print("[publisher] push başarılı")
        return True
    except Exception as exc:
        print(f"[publisher] push başarısız: {exc}")
        return False
