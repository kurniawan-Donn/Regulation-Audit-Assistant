"""
Fase 1 — Background jobs, penulisan atomik, dan smoke test endpoint
Compliance Review + Regulation DB (semua AI/embedding di-mock).
"""

import json
import threading
import time
from unittest.mock import patch

import pytest

from app.services.ai_service import AIProvider
from app.services.job_manager import JobFailure, JobManager, JobOutcome
from app.services.json_store import update_json, write_json_atomic
from tests.conftest import wait_for_job


class _FakeProvider(AIProvider):
    def generate_text(self, system_prompt, user_prompt, expect_json=False):
        return "[]"


def _wait(manager: JobManager, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job and job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.01)
    raise AssertionError("job tidak selesai")


# ---------------------------------------------------------------------------
# JobManager
# ---------------------------------------------------------------------------

@pytest.fixture
def manager(tmp_path):
    m = JobManager(max_workers=1, jobs_dir=tmp_path / "jobs")
    yield m
    m.shutdown()


def test_job_sukses_melapor_progres_dan_hasil(manager):
    def worker(ctx):
        for i in range(3):
            ctx.progress(i + 1, 3, f"langkah {i + 1}")
        return JobOutcome(result_id="r1", result_url="/x/r1", message="ok")

    rec = manager.submit("test", worker, total=3)
    job = _wait(manager, rec.job_id)

    assert job["status"] == "succeeded"
    assert job["progress_done"] == 3
    assert job["result_url"] == "/x/r1"
    # Status juga tersimpan di disk (bertahan saat halaman reload)
    on_disk = json.loads((manager._jobs_dir / f"{rec.job_id}.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "succeeded"


def test_job_failure_pesan_aman_untuk_user(manager):
    def worker(ctx):
        raise JobFailure("API key salah")

    job = _wait(manager, manager.submit("test", worker).job_id)
    assert job["status"] == "failed"
    assert job["error"] == "API key salah"


def test_cancel_job_yang_sedang_berjalan(manager):
    started = threading.Event()

    def worker(ctx):
        started.set()
        while True:
            ctx.check_cancelled()
            time.sleep(0.01)

    rec = manager.submit("test", worker)
    assert started.wait(2)
    manager.cancel(rec.job_id)
    job = _wait(manager, rec.job_id)
    assert job["status"] == "cancelled"


def test_cancel_job_yang_masih_antre(manager):
    gate = threading.Event()

    def blocking(ctx):
        gate.wait(5)
        return JobOutcome()

    first = manager.submit("test", blocking)
    second = manager.submit("test", lambda ctx: JobOutcome())
    assert manager.get(second.job_id)["queue_position"] >= 1

    manager.cancel(second.job_id)
    gate.set()
    assert _wait(manager, second.job_id)["status"] == "cancelled"
    assert _wait(manager, first.job_id)["status"] == "succeeded"


def test_job_yatim_ditandai_gagal_saat_restart(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    orphan = {"job_id": "a" * 32, "kind": "x", "status": "running", "created_at": time.time()}
    (jobs_dir / f"{'a' * 32}.json").write_text(json.dumps(orphan), encoding="utf-8")

    m = JobManager(jobs_dir=jobs_dir)
    m.recover_and_cleanup()
    job = m.get("a" * 32)
    m.shutdown()
    assert job["status"] == "failed"
    assert "restart" in job["error"]


def test_get_job_id_tidak_valid(manager):
    assert manager.get("../../etc") is None


# ---------------------------------------------------------------------------
# JSON store
# ---------------------------------------------------------------------------

def test_write_json_atomic_tidak_meninggalkan_file_temp(tmp_path):
    path = tmp_path / "out" / "x.json"
    write_json_atomic(path, {"a": 1})
    write_json_atomic(path, {"a": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2}
    assert [p.name for p in path.parent.iterdir()] == ["x.json"]


def test_update_json_paralel_tidak_kehilangan_update(tmp_path):
    path = tmp_path / "counter.json"
    write_json_atomic(path, {"n": 0})

    def bump():
        for _ in range(25):
            update_json(path, lambda d: d.__setitem__("n", d["n"] + 1))

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert json.loads(path.read_text(encoding="utf-8"))["n"] == 100


# ---------------------------------------------------------------------------
# Endpoint: analyze (Tool 1) — pembatalan menyimpan hasil parsial
# ---------------------------------------------------------------------------

@patch("app.api.common.get_ai_provider", return_value=_FakeProvider())
@patch("app.api.audit_routes.get_effective_settings", return_value={"max_chars_per_batch": 50})
@patch("app.services.analysis_jobs.analyze_chunks_batch")
def test_analyze_cancel_menyimpan_hasil_parsial(mock_analyze, _s, _p, client, preview_id):
    first_batch_done = threading.Event()
    release = threading.Event()

    def slow_batch(batch, provider, referensi_regulasi=""):
        if first_batch_done.is_set():
            release.wait(5)
        first_batch_done.set()
        return []

    mock_analyze.side_effect = slow_batch

    res = client.post("/api/analyze", json={
        "preview_id": preview_id, "selected_chunk_indices": list(range(50)),
    })
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]

    assert first_batch_done.wait(5)
    client.post(f"/api/jobs/{job_id}/cancel")
    release.set()
    job = wait_for_job(client, job_id)

    assert job["status"] == "cancelled"
    assert job["partial"] is True
    data = client.get(job["result_url"]).json()
    assert any("Dibatalkan" in e["error"] for e in data["chunk_errors"])


def test_analyze_preview_tidak_ada_langsung_404(client):
    res = client.post("/api/analyze", json={
        "preview_id": "f" * 32, "selected_chunk_indices": [0],
    })
    assert res.status_code == 404


def test_result_id_path_traversal_ditolak(client):
    for bad in ("..%5C..%5Cdata%5Csettings", "..", "abc"):
        assert client.get(f"/api/results/{bad}").status_code == 404
        assert client.get(f"/api/compliance/{bad}").status_code == 404


# ---------------------------------------------------------------------------
# Endpoint: Gap Analysis (Tool 2)
# ---------------------------------------------------------------------------

@patch("app.api.common.get_ai_provider", return_value=_FakeProvider())
@patch("app.services.analysis_jobs.analyze_chunks_for_requirements")
def test_gap_analysis_job(mock_req, _p, run_job, preview_id):
    mock_req.return_value = [{"persyaratan": "Wajib X", "referensi": "Pasal 20", "catatan": ""}]
    job, data = run_job("POST", "/api/analyze-requirements", json={"preview_id": preview_id})
    assert job["status"] == "succeeded"
    assert data["total_requirements"] >= 1
    assert data["requirements"][0]["persyaratan"] == "Wajib X"


# ---------------------------------------------------------------------------
# Endpoint: Regulation DB upload
# ---------------------------------------------------------------------------

@patch("app.services.analysis_jobs.add_regulation")
@patch("app.api.common.EmbeddingService")
def test_regulation_db_upload_job(mock_embed_cls, mock_add, client, sample_txt_path):
    mock_embed_cls.return_value.embed_batch.side_effect = (
        lambda texts, task_type, on_batch_done=None: [[0.0] * 768 for _ in texts]
    )
    mock_add.return_value = {
        "id": "b" * 32, "name": "Contoh", "filename": "x.txt", "total_chunks": 3,
        "created_at": "2026-01-01T00:00:00", "source_type": "manual",
    }

    with open(sample_txt_path, "rb") as f:
        res = client.post(
            "/api/regulation-db/upload",
            files={"file": ("x.txt", f, "text/plain")},
            data={"name": "Contoh"},
        )
    assert res.status_code == 202, res.text
    job = wait_for_job(client, res.json()["job_id"])

    assert job["status"] == "succeeded", job
    assert job["extra"]["regulation"]["name"] == "Contoh"
    assert mock_add.call_args.kwargs["name"] == "Contoh"
