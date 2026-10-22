"""
Fase 3 — keamanan & kebersihan data.
"""

import base64
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings


def _basic(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def raw_client(tmp_path, monkeypatch):
    """Client TANPA header anti-CSRF default (untuk menguji penolakan)."""
    from app.main import app

    monkeypatch.chdir(tmp_path)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Anti-CSRF & security headers
# ---------------------------------------------------------------------------

def test_request_ubah_data_tanpa_header_csrf_ditolak(raw_client):
    res = raw_client.put("/api/settings", json={"theme": "dark"})
    assert res.status_code == 403
    res = raw_client.put("/api/settings", json={"theme": "dark"},
                         headers={"X-Requested-With": "RAA"})
    assert res.status_code == 200


def test_get_tidak_butuh_header_csrf(raw_client):
    assert raw_client.get("/api/settings").status_code == 200


def test_security_headers_dan_no_store(raw_client):
    res = raw_client.get("/api/settings")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Cache-Control"] == "no-store"
    assert "X-Frame-Options" in raw_client.get("/").headers


# ---------------------------------------------------------------------------
# Basic Auth (aktif kalau APP_PASSWORD diisi)
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "app_username", "auditor")
    monkeypatch.setattr(settings, "app_password", "rahasia-123")


def test_tanpa_password_aplikasi_terbuka(raw_client):
    assert raw_client.get("/").status_code == 200


def test_auth_wajib_untuk_ui_api_dan_static(auth_on, raw_client):
    for path in ("/", "/api/settings", "/static/js/main.js"):
        res = raw_client.get(path)
        assert res.status_code == 401, path
        assert res.headers["WWW-Authenticate"].startswith("Basic")


def test_auth_kredensial_salah_ditolak(auth_on, raw_client):
    assert raw_client.get("/", headers=_basic("auditor", "salah")).status_code == 401
    assert raw_client.get("/", headers=_basic("admin", "rahasia-123")).status_code == 401
    assert raw_client.get("/", headers={"Authorization": "Basic !!!"}).status_code == 401


def test_auth_kredensial_benar_diterima(auth_on, raw_client):
    assert raw_client.get("/api/settings", headers=_basic("auditor", "rahasia-123")).status_code == 200


def test_health_tetap_publik(auth_on, raw_client):
    res = raw_client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}  # tidak membocorkan info lingkungan


# ---------------------------------------------------------------------------
# Entry point: bind jaringan tanpa password ditolak
# ---------------------------------------------------------------------------

def test_bind_jaringan_tanpa_password_ditolak(monkeypatch):
    from app import __main__ as entry

    monkeypatch.setattr(settings, "host", "0.0.0.0")
    monkeypatch.setattr(settings, "app_password", "")
    monkeypatch.setattr(settings, "allow_insecure_remote", False)
    with patch("app.__main__.uvicorn.run") as run:
        assert entry.main() == 1
        run.assert_not_called()


def test_bind_lokal_atau_dengan_password_diizinkan(monkeypatch):
    from app import __main__ as entry

    with patch("app.__main__.uvicorn.run") as run:
        monkeypatch.setattr(settings, "host", "127.0.0.1")
        monkeypatch.setattr(settings, "app_password", "")
        assert entry.main() == 0
        monkeypatch.setattr(settings, "host", "0.0.0.0")
        monkeypatch.setattr(settings, "app_password", "rahasia-123")
        assert entry.main() == 0
        assert run.call_count == 2


# ---------------------------------------------------------------------------
# Kebersihan data
# ---------------------------------------------------------------------------

def test_upload_tidak_meninggalkan_file(client, sample_txt_path, sample_contract_path):
    with open(sample_txt_path, "rb") as f:
        assert client.post("/api/preview", files={"file": ("r.txt", f, "text/plain")}).status_code == 200
    with open(sample_contract_path, "rb") as c, open(sample_txt_path, "rb") as r:
        res = client.post("/api/compliance/preview", files=[
            ("contract_file", ("k.txt", c, "text/plain")),
            ("regulation_files", ("r.txt", r, "text/plain")),
        ])
        assert res.status_code == 200
    with open(sample_contract_path, "rb") as c:
        assert client.post("/api/compliance/parse-contract",
                           files={"file": ("k.txt", c, "text/plain")}).status_code == 200
    uploads = Path("uploads")
    assert not uploads.exists() or not any(uploads.iterdir())


def test_preview_compliance_kedaluwarsa_ikut_dibersihkan(tmp_path, monkeypatch):
    import os
    import time

    from app.services import preview_cache

    monkeypatch.chdir(tmp_path)
    d = Path("cache/compliance_previews")
    d.mkdir(parents=True)
    old_json, old_npy, fresh = d / "a.json", d / "a.emb.npy", d / "b.json"
    for f in (old_json, old_npy, fresh):
        f.write_text("x")
    stale = time.time() - preview_cache.COMPLIANCE_PREVIEW_TTL_SECONDS - 60
    os.utime(old_json, (stale, stale))
    os.utime(old_npy, (stale, stale))

    assert preview_cache.cleanup_expired() == 2
    assert not old_json.exists() and not old_npy.exists() and fresh.exists()


# ---------------------------------------------------------------------------
# Error generik & endpoint destruktif
# ---------------------------------------------------------------------------

def test_error_tak_terduga_tidak_membocorkan_detail(tmp_path, monkeypatch):
    from app.main import app

    monkeypatch.chdir(tmp_path)
    with patch("app.api.settings_routes.get_settings_masked", side_effect=RuntimeError("rahasia-internal /path/x")):
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.get("/api/settings")
    assert res.status_code == 500
    assert "rahasia-internal" not in res.text
    assert "kode:" in res.json()["detail"]


def test_reset_db_wajib_konfirmasi(client):
    from app.services import regulation_db

    regulation_db._db = None
    assert client.post("/api/regulation-db/reset", json={}).status_code == 422
    assert client.post("/api/regulation-db/reset", json={"confirm": "ya"}).status_code == 422
    res = client.post("/api/regulation-db/reset", json={"confirm": "HAPUS SEMUA"})
    assert res.status_code == 200, res.text
    regulation_db._db = None
