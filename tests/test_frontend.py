"""index.html arayüz testlerini (node + jsdom) çalıştırır.

Sayfanın kendi JavaScript'i jsdom içinde çalıştırılır; node veya jsdom kurulu
değilse test atlanır (CI'da `npm install` ile kurulur).
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _skip(reason):
    try:
        import pytest
        pytest.skip(reason)
    except ImportError:
        print(f"SKIP: {reason}")


def test_frontend_jsdom():
    node = shutil.which("node")
    if not node:
        _skip("node bulunamadı (arayüz testleri atlandı)")
        return
    if not os.path.isdir(os.path.join(ROOT, "node_modules", "jsdom")):
        _skip("jsdom kurulu değil: npm install")
        return
    res = subprocess.run(
        [node, "--test", "tests/frontend.test.mjs"],
        cwd=ROOT, capture_output=True, text=True,
    )
    print(res.stdout[-4000:])
    assert res.returncode == 0, f"arayüz testleri başarısız:\n{res.stdout[-4000:]}\n{res.stderr[-2000:]}"
    print("OK: frontend (jsdom)")


if __name__ == "__main__":
    test_frontend_jsdom()
    print("\nARAYÜZ TESTLERİ GEÇTİ ✅")
