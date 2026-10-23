"""
Demo lewat internet: Mode Demo (aksi berisiko diblokir), folder demo terpisah
dari data kerja, dan parsing link Cloudflare.
"""

import json
from pathlib import Path

import pytest

from app.config import settings
from scripts import demo


@pytest.fixture
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)


@pytest.mark.parametrize("method,path", [
    ("PUT", "/api/settings"),
    ("POST", "/api/settings/test-connection"),
    ("PUT", "/api/prompts/regulation_audit"),
    ("POST", "/api/prompts/regulation_audit/reset"),
    ("POST", "/api/regulation-db/upload"),
    ("POST", "/api/regulation-db/reset"),
    ("DELETE", "/api/regulation-db/regulations/abc"),
    ("POST", "/api/regulation-db/regulations/abc/reindex"),
    ("DELETE", f"/api/history/compliance_review/{'a' * 32}"),
    ("POST", "/api/history/clear"),
])
def test_aksi_berisiko_diblokir_di_mode_demo(client, demo_mode, method, path):
    res = client.request(method, path, json={})
    assert res.status_code == 403
    assert res.json()["detail"] == "Dinonaktifkan di mode demo."


def test_pemakaian_biasa_tetap_jalan_di_mode_demo(client, demo_mode):
    assert client.get("/api/settings").json()["demo_mode"] is True
    assert client.post("/api/findings", json={"judul": "Temuan demo"}).status_code == 201
    preview = client.post("/api/prompts/regulation_audit/preview", json={})
    assert preview.json().get("detail") != "Dinonaktifkan di mode demo."
    res = client.get("/demo/contoh-kontrak.txt")
    assert res.status_code == 200 and "PIHAK KEDUA" in res.text


def test_tanpa_mode_demo_tidak_ada_blokir_dan_contoh(client):
    assert client.get("/api/settings").json()["demo_mode"] is False
    assert client.get("/demo/contoh-kontrak.txt").status_code == 404
    res = client.post("/api/history/clear", json={"confirm": "salah"})
    assert res.status_code == 422                     # ditangani endpoint, bukan diblokir


def test_folder_demo_hanya_berisi_database_regulasi(tmp_path):
    root, demo_dir = tmp_path / "app", tmp_path / "app" / "demo_workspace"
    (root / "data/lancedb/regulations.lance").mkdir(parents=True)
    (root / "data/lancedb/regulations.lance/x.bin").write_bytes(b"v")
    (root / "data/regulations.json").write_text("{}", encoding="utf-8")
    (root / "data/findings.json").write_text('{"items": ["rahasia"]}', encoding="utf-8")
    (root / "data/settings.json").write_text('{"gemini_api_key": "rahasia", "theme": "dark"}', encoding="utf-8")
    (root / "outputs/compliance").mkdir(parents=True)
    (root / "outputs/compliance/x.json").write_text("{}", encoding="utf-8")

    assert demo.prepare_workspace(root, demo_dir) is True
    assert (demo_dir / "data/lancedb/regulations.lance/x.bin").exists()
    assert (demo_dir / "data/regulations.json").exists()
    assert not (demo_dir / "data/findings.json").exists()          # temuan asli tidak ikut
    assert list((demo_dir / "outputs").iterdir()) == []            # hasil analisis tidak ikut
    assert json.loads((demo_dir / "data/settings.json").read_text(encoding="utf-8")) == {"theme": "dark"}

    (demo_dir / "data/findings.json").write_text("{}", encoding="utf-8")   # dibuat pengunjung
    assert demo.prepare_workspace(root, demo_dir) is False         # dipakai ulang
    assert demo.prepare_workspace(root, demo_dir, reset=True) is True
    assert not (demo_dir / "data/findings.json").exists()          # --reset kembali bersih


def test_link_cloudflare_dan_password(monkeypatch):
    line = "2026-10-23T07:00:00Z INF |  https://kuda-terbang-123.trycloudflare.com                       |"
    assert demo.parse_tunnel_url(line) == "https://kuda-terbang-123.trycloudflare.com"
    assert demo.parse_tunnel_url("INF Starting tunnel") is None

    monkeypatch.setattr(demo, "read_env_value", lambda key: "")
    a, b = demo.demo_password(), demo.demo_password()
    assert len(a) == 10 and a != b and not set(a) & set("l1o0")
    monkeypatch.setattr(demo, "read_env_value", lambda key: "tetap123" if key == "DEMO_PASSWORD" else "")
    assert demo.demo_password() == "tetap123"


def test_api_key_demo_tidak_dari_folder_lain(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(demo, "read_env_value", lambda key: "kunci-demo" if key == "DEMO_GEMINI_API_KEY" else "kunci-utama")
    assert demo.demo_api_key(tmp_path) == "kunci-demo"
    monkeypatch.setattr(demo, "read_env_value", lambda key: "")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/settings.json").write_text('{"gemini_api_key": "dari-ui"}', encoding="utf-8")
    assert demo.demo_api_key(tmp_path) == "dari-ui"
    assert demo.demo_api_key(Path(tmp_path / "kosong")) == ""
