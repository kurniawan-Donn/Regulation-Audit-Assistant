"""
Riwayat analisis dari server (GET/DELETE /api/history, POST /api/history/clear).
Fixture `client` menjalankan app di cwd sementara → outputs/ kosong & terisolasi.
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from app.services.ai_service import AIProvider

AUDIT_ID = "a" * 32
GAP_ID = "b" * 32
COMP_ID = "c" * 32


class _FakeProvider(AIProvider):
    def generate_text(self, system_prompt, user_prompt, expect_json=False):
        return "{}"


def _write(path: Path, data: dict, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _seed() -> None:
    now = time.time()
    _write(Path("outputs") / f"{AUDIT_ID}.json", {
        "result_id": AUDIT_ID, "filename": "POJK 11.pdf",
        "total_ketentuan": 38, "total_valid": 36, "total_flagged": 2, "results": [],
    }, mtime=now - 3600)
    Path("outputs", f"{AUDIT_ID}.pdf").write_bytes(b"%PDF")
    _write(Path("outputs/requirements") / f"{GAP_ID}.json", {
        "result_id": GAP_ID, "filename": "PADK 43.pdf", "total_requirements": 3,
        "requirements": [{"status_gap": "Sesuai"}, {"status_gap": "Tidak Sesuai"}, {"status_gap": ""}],
    }, mtime=now - 60)
    _write(Path("outputs/compliance") / f"{COMP_ID}.json", {
        "result_id": COMP_ID, "contract_filename": "MoU Vendor.pdf",
        "regulation_filenames": ["POJK 11.pdf"], "created_at": "2020-01-01T00:00:00+00:00",
        "total_items": 5, "total_patuh": 1, "total_patuh_catatan": 2, "total_tidak_patuh": 2,
        "items": [],
    })
    Path("outputs/compliance", f"{COMP_ID}.xlsx").write_bytes(b"x")
    # Bukan hasil analisis: nama tidak sesuai pola ID → diabaikan.
    _write(Path("outputs") / "catatan.json", {"x": 1})


def test_daftar_riwayat_dari_file_hasil(client):
    _seed()
    res = client.get("/api/history")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] == 3
    # Terbaru dulu: gap (1 menit lalu), audit (1 jam lalu), compliance (created_at 2020).
    assert [i["type"] for i in data["items"]] == ["gap_analysis", "regulation_audit", "compliance_review"]

    by_type = {i["type"]: i for i in data["items"]}
    assert by_type["regulation_audit"]["nama"] == "POJK 11.pdf"
    assert by_type["regulation_audit"]["stats"] == {"total_ketentuan": 38, "total_valid": 36, "total_flagged": 2}
    assert by_type["gap_analysis"]["stats"] == {"total_requirements": 3, "total_dinilai": 2, "total_perlu_tindak": 1}
    comp = by_type["compliance_review"]
    assert comp["nama"] == "MoU Vendor.pdf"
    assert comp["tanggal"].startswith("2020-01-01")          # created_at menang atas waktu file
    assert comp["stats"]["total_tidak_patuh"] == 2
    assert comp["regulation_filenames"] == ["POJK 11.pdf"]


def test_riwayat_kosong_dan_limit(client):
    assert client.get("/api/history").json() == {"items": [], "total": 0}
    _seed()
    assert len(client.get("/api/history?limit=2").json()["items"]) == 2


def test_hapus_hasil_beserta_file_ekspor(client):
    _seed()
    res = client.delete(f"/api/history/regulation_audit/{AUDIT_ID}")
    assert res.status_code == 200, res.text
    assert not Path("outputs", f"{AUDIT_ID}.json").exists()
    assert not Path("outputs", f"{AUDIT_ID}.pdf").exists()
    assert client.get(f"/api/results/{AUDIT_ID}").status_code == 404
    assert {i["id"] for i in client.get("/api/history").json()["items"]} == {GAP_ID, COMP_ID}


def test_hapus_tidak_ada_atau_tidak_valid_404(client):
    _seed()
    assert client.delete(f"/api/history/regulation_audit/{'d' * 32}").status_code == 404
    assert client.delete("/api/history/regulation_audit/..%2F..%2Fdata").status_code == 404
    assert client.delete(f"/api/history/jenis_lain/{AUDIT_ID}").status_code == 404
    # Jenis salah untuk ID yang ada → tidak menghapus file jenis lain.
    assert client.delete(f"/api/history/gap_analysis/{AUDIT_ID}").status_code == 404
    assert Path("outputs", f"{AUDIT_ID}.json").exists()


def test_hapus_semua_wajib_konfirmasi(client):
    _seed()
    assert client.post("/api/history/clear", json={"confirm": "ya"}).status_code == 422
    assert client.get("/api/history").json()["total"] == 3

    res = client.post("/api/history/clear", json={"confirm": "HAPUS SEMUA"})
    assert res.status_code == 200, res.text
    assert "3" in res.json()["message"]
    assert client.get("/api/history").json()["total"] == 0
    assert not Path("outputs/compliance", f"{COMP_ID}.xlsx").exists()
    assert Path("outputs", "catatan.json").exists()           # file lain tidak tersentuh


def test_ringkasan_ikut_berubah_setelah_hasil_diedit(client):
    _seed()
    assert client.get("/api/history").json()["items"][0]["stats"]["total_dinilai"] == 2
    path = Path("outputs/requirements") / f"{GAP_ID}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["requirements"][2]["status_gap"] = "Sebagian"
    _write(path, data, mtime=time.time() + 5)                # mtime baru → cache diperbarui
    gap = next(i for i in client.get("/api/history").json()["items"] if i["type"] == "gap_analysis")
    assert gap["stats"]["total_dinilai"] == 3


@patch("app.api.common.get_ai_provider", return_value=_FakeProvider())
@patch("app.services.analysis_jobs.analyze_chunks_for_requirements")
def test_hasil_baru_mencatat_created_at_dan_muncul_di_riwayat(mock_req, _p, run_job, client, preview_id):
    mock_req.return_value = [{"persyaratan": "Wajib X", "referensi": "Pasal 20", "catatan": ""}]
    job, data = run_job("POST", "/api/analyze-requirements", json={"preview_id": preview_id})
    assert job["status"] == "succeeded"
    assert data["created_at"]

    items = client.get("/api/history").json()["items"]
    assert items[0]["id"] == data["result_id"]
    assert items[0]["type"] == "gap_analysis"
    assert items[0]["tanggal"] == data["created_at"]
