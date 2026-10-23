"""
Cek pembaruan dari GitHub Releases (app/services/update_check.py): perbandingan
versi, tautan unduhan sesuai cara pemasangan, cache, dan kegagalan jaringan.
GitHub tidak pernah dipanggil sungguhan — _fetch_latest di-mock.
"""

import httpx
import pytest

from app.config import settings
from app.services import update_check
from app.version import __version__

RELEASE = {
    "tag_name": "v99.0.0",
    "html_url": "https://github.com/o/r/releases/tag/v99.0.0",
    "body": "Perbaikan penting.",
    "published_at": "2026-10-23T00:00:00Z",
    "assets": [
        {"name": "AuditAssistant-99.0.0-Portable.zip", "browser_download_url": "https://x/portable.zip"},
        {"name": "AuditAssistant-99.0.0-Setup.exe", "browser_download_url": "https://x/setup.exe"},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/sums.txt"},
    ],
}


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "update_check", True)
    monkeypatch.delenv(update_check.INSTALL_KIND_ENV, raising=False)
    update_check.reset_cache()
    yield
    update_check.reset_cache()


@pytest.fixture
def github(monkeypatch, enabled):
    calls = {"n": 0, "release": dict(RELEASE)}

    def fake_fetch():
        calls["n"] += 1
        return calls["release"]

    monkeypatch.setattr(update_check, "_fetch_latest", fake_fetch)
    return calls


@pytest.mark.parametrize("latest,current,expected", [
    ("1.2.0", "1.1.9", True),
    ("v1.10.0", "1.9.0", True),        # bandingkan angka, bukan teks
    ("1.0.0", "1.0.0", False),
    ("0.9.0", "1.0.0", False),
    ("bukan-versi", "1.0.0", False),
])
def test_perbandingan_versi(latest, current, expected):
    assert update_check.is_newer(latest, current) is expected


def test_versi_baru_installer_dapat_setup_exe(github, monkeypatch):
    monkeypatch.setenv(update_check.INSTALL_KIND_ENV, "installer")
    info = update_check.check_for_update()
    assert info["update_available"] is True
    assert info["latest"] == "99.0.0" and info["current"] == __version__
    assert info["url"] == "https://x/setup.exe"


def test_portable_dapat_zip_dan_sumber_dapat_halaman_rilis(github, monkeypatch):
    monkeypatch.setenv(update_check.INSTALL_KIND_ENV, "portable")
    assert update_check.check_for_update(force=True)["url"] == "https://x/portable.zip"
    monkeypatch.delenv(update_check.INSTALL_KIND_ENV)
    info = update_check.check_for_update(force=True)
    assert info["install_kind"] == "source"
    assert info["url"] == RELEASE["html_url"]


def test_sudah_terbaru(github):
    github["release"] = {**RELEASE, "tag_name": f"v{__version__}"}
    info = update_check.check_for_update()
    assert info["update_available"] is False and info["latest"] == __version__


def test_hasil_di_cache_kecuali_dipaksa(github):
    update_check.check_for_update()
    update_check.check_for_update()
    assert github["n"] == 1
    update_check.check_for_update(force=True)
    assert github["n"] == 2


def test_gagal_jaringan_tidak_mengganggu(enabled, monkeypatch):
    def boom():
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(update_check, "_fetch_latest", boom)
    info = update_check.check_for_update()
    assert info["update_available"] is False and info["error"]


def test_belum_ada_rilis(enabled, monkeypatch):
    monkeypatch.setattr(update_check, "_fetch_latest", lambda: {})
    info = update_check.check_for_update()
    assert info["latest"] is None and info["update_available"] is False and not info["error"]


def test_dimatikan_atau_mode_demo_tidak_memanggil_github(monkeypatch):
    monkeypatch.setattr(update_check, "_fetch_latest", lambda: pytest.fail("GitHub dipanggil"))
    monkeypatch.setattr(settings, "update_check", False)
    assert update_check.check_for_update()["enabled"] is False
    monkeypatch.setattr(settings, "update_check", True)
    monkeypatch.setattr(settings, "demo_mode", True)
    assert update_check.check_for_update()["enabled"] is False


def test_endpoint_update_check(client, github):
    res = client.get("/api/update-check")
    assert res.status_code == 200
    body = res.json()
    assert body["update_available"] is True and body["current"] == __version__


def test_versi_satu_sumber(client):
    assert client.get("/api/diagnostics").json()["app_version"] == __version__
    assert client.app.version == __version__
