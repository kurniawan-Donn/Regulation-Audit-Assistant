"""
Buku Panduan Pengguna: halaman /panduan, PDF, dan gambar yang dirujuk tersedia.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_halaman_panduan_tersedia(client):
    res = client.get("/panduan")
    assert res.status_code == 200
    assert "Buku Panduan Pengguna" in res.text


def test_semua_gambar_dan_pdf_panduan_ada():
    html = (ROOT / "templates/panduan.html").read_text(encoding="utf-8")
    refs = set(re.findall(r'(?:src|href)="(/static/panduan/[^"]+)"', html))
    assert any(r.endswith(".pdf") for r in refs)
    missing = [r for r in refs if not (ROOT / r.lstrip("/")).is_file()]
    assert not missing, f"Berkas panduan hilang: {missing}"


def test_tautan_panduan_di_aplikasi():
    index = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    assert 'href="/panduan"' in index
    assert "/static/panduan/Panduan_Pengguna_Audit_Assistant.pdf" in index
