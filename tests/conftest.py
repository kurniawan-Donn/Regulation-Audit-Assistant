"""
Shared pytest fixtures.
"""

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

SAMPLE_DIR = Path(__file__).parent / "sample_files"


@pytest.fixture(autouse=True)
def _no_real_ai_credentials(tmp_path, monkeypatch):
    """
    Test TIDAK boleh memakai API key asli (dari .env atau data/settings.json):
    jalur AI/embedding yang lupa di-mock harus gagal cepat (422/ValueError),
    bukan diam-diam memanggil Gemini dengan kuota pengguna.
    """
    from app.config import settings
    from app.services import runtime_settings

    monkeypatch.setattr(settings, "gemini_api_key", "")
    # Test tidak memanggil GitHub; test cek pembaruan menyalakannya sendiri + mock.
    monkeypatch.setattr(settings, "update_check", False)
    settings_dir = tmp_path / "_runtime_settings"
    monkeypatch.setattr(runtime_settings, "SETTINGS_DIR", settings_dir)
    monkeypatch.setattr(runtime_settings, "SETTINGS_FILE", settings_dir / "settings.json")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    TestClient yang berjalan di direktori kerja sementara, supaya test
    tidak menulis ke outputs/, cache/, uploads/, data/ milik aplikasi
    (semua path storage di app relatif terhadap cwd).
    """
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.chdir(tmp_path)
    # Header anti-CSRF yang juga dikirim frontend (lihat app/security.py).
    with TestClient(app, headers={"X-Requested-With": "RAA"}) as test_client:
        yield test_client


@pytest.fixture
def sample_txt_path() -> str:
    return str(SAMPLE_DIR / "sample_regulation.txt")


@pytest.fixture
def sample_pdf_path() -> str:
    return str(SAMPLE_DIR / "sample_regulation.pdf")


@pytest.fixture
def sample_contract_path() -> str:
    return str(Path(__file__).parent / "sample_contract_micro.txt")


def wait_for_job(client, job_id: str, timeout: float = 10.0) -> dict:
    """Poll /api/jobs/{id} sampai status final."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = client.get(f"/api/jobs/{job_id}")
        assert res.status_code == 200, res.text
        job = res.json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} tidak selesai dalam {timeout} detik")


@pytest.fixture
def run_job(client):
    """Kirim request yang membalas 202 + job_id, tunggu selesai, kembalikan (job, result)."""
    def _run(method: str, url: str, **kwargs):
        res = client.request(method, url, **kwargs)
        assert res.status_code == 202, res.text
        job = wait_for_job(client, res.json()["job_id"])
        result = None
        if job.get("result_url"):
            r = client.get(job["result_url"])
            assert r.status_code == 200, r.text
            result = r.json()
        return job, result
    return _run


@pytest.fixture
def preview_id(client, sample_txt_path) -> str:
    with open(sample_txt_path, "rb") as f:
        res = client.post("/api/preview", files={"file": ("sample_regulation.txt", f, "text/plain")})
    assert res.status_code == 200, res.text
    return res.json()["preview_id"]
