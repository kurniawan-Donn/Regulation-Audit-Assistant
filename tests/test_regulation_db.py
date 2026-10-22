"""
Regulation DB (Fase 2 — RAG): file sumber, cek duplikat, index ulang,
pencarian hybrid. Embedding di-mock; LanceDB asli di direktori sementara
(fixture `client` menjalankan app di tmp cwd).
"""

import re
import zlib
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from tests.conftest import wait_for_job


class _KeywordEmbedder:
    def embed_batch(self, texts, task_type="RETRIEVAL_DOCUMENT", on_batch_done=None):
        out = []
        for text in texts:
            v = np.zeros(768, dtype=np.float32)
            for w in re.findall(r"[a-z]{4,}", text.lower()):
                v[zlib.crc32(w.encode()) % 768] += 1.0
            out.append(v.tolist())
        if on_batch_done:
            on_batch_done(len(texts), len(texts))
        return out

    def embed_query(self, text):
        return self.embed_batch([text], task_type="RETRIEVAL_QUERY")[0]


@pytest.fixture
def db_client(client):
    from app.services import regulation_db

    regulation_db._db = None  # koneksi baru di cwd sementara
    with patch("app.api.common.EmbeddingService", return_value=_KeywordEmbedder()):
        yield client
    regulation_db._db = None


def _upload(client, path: str, name: str):
    with open(path, "rb") as f:
        return client.post(
            "/api/regulation-db/upload",
            files={"file": (Path(path).name, f, "text/plain")},
            data={"name": name},
        )


def _upload_ok(client, path: str, name: str) -> dict:
    res = _upload(client, path, name)
    assert res.status_code == 202, res.text
    job = wait_for_job(client, res.json()["job_id"])
    assert job["status"] == "succeeded", job
    return job["extra"]["regulation"]


def test_upload_menyimpan_sumber_hash_dan_versi(db_client, sample_txt_path):
    from app.services.regulation_db import INDEX_VERSION
    from app.services.regulation_parser import PARSER_VERSION

    reg = _upload_ok(db_client, sample_txt_path, "Contoh 1/2026")
    assert len(reg["file_sha256"]) == 64
    assert Path(reg["source_path"]).exists()
    assert (reg["parser_version"], reg["index_version"]) == (PARSER_VERSION, INDEX_VERSION)

    listed = db_client.get("/api/regulation-db/regulations").json()["regulations"][0]
    assert listed["has_source"] is True and listed["needs_reindex"] is False


def test_upload_file_yang_sama_ditolak_409(db_client, sample_txt_path):
    _upload_ok(db_client, sample_txt_path, "Contoh 1/2026")
    res = _upload(db_client, sample_txt_path, "Nama Lain")
    assert res.status_code == 409
    assert "Contoh 1/2026" in res.json()["detail"]


def test_pencarian_hybrid_menemukan_pasal_dengan_label(db_client, sample_txt_path):
    _upload_ok(db_client, sample_txt_path, "Contoh 1/2026")
    res = db_client.post("/api/regulation-db/search", json={
        "query": "prosedur pengelolaan insiden keamanan informasi", "top_k": 3,
    })
    assert res.status_code == 200, res.text
    top = res.json()["results"][0]
    assert top["regulation_name"] == "Contoh 1/2026"
    assert "Pasal 22" in top["referensi"]


def test_query_hybrid_dipakai_saat_ada_teks_dan_index_fts(db_client, sample_txt_path):
    from app.services import regulation_db

    _upload_ok(db_client, sample_txt_path, "Contoh 1/2026")
    assert regulation_db._has_fts_index(regulation_db._get_table())
    vec = _KeywordEmbedder().embed_query("hak akses pengguna")
    hybrid = regulation_db.query_relevant_chunks(vec, top_k=3, query_text="otorisasi akses")
    vector = regulation_db.query_relevant_chunks(vec, top_k=3)
    assert hybrid[0]["score"] is not None and hybrid[0]["distance"] is None
    assert vector[0]["distance"] is not None


def test_index_ulang_regulasi_usang(db_client, sample_txt_path, monkeypatch):
    from app.services import regulation_db

    reg = _upload_ok(db_client, sample_txt_path, "Contoh 1/2026")
    # Simulasikan parser diperbarui setelah regulasi di-index.
    monkeypatch.setattr(regulation_db, "PARSER_VERSION", 999)
    listed = db_client.get("/api/regulation-db/regulations").json()["regulations"][0]
    assert listed["needs_reindex"] is True

    res = db_client.post(f"/api/regulation-db/regulations/{reg['id']}/reindex")
    assert res.status_code == 202, res.text
    job = wait_for_job(db_client, res.json()["job_id"])
    assert job["status"] == "succeeded", job

    listed = db_client.get("/api/regulation-db/regulations").json()["regulations"][0]
    assert listed["id"] == reg["id"]  # ID tetap → hasil compliance lama tetap valid
    assert listed["needs_reindex"] is False
    assert regulation_db.count_chunks_in_collection(reg["id"]) == listed["total_chunks"]


def test_index_ulang_tanpa_file_sumber_422(db_client, sample_txt_path):
    from app.services import regulation_db

    reg = _upload_ok(db_client, sample_txt_path, "Contoh 1/2026")
    Path(reg["source_path"]).unlink()
    res = db_client.post(f"/api/regulation-db/regulations/{reg['id']}/reindex")
    assert res.status_code == 422
    assert regulation_db.get_regulation(reg["id"])["has_source"] is False


def test_hapus_regulasi_ikut_menghapus_file_sumber(db_client, sample_txt_path):
    reg = _upload_ok(db_client, sample_txt_path, "Contoh 1/2026")
    res = db_client.delete(f"/api/regulation-db/regulations/{reg['id']}")
    assert res.status_code == 200, res.text
    assert not Path(reg["source_path"]).exists()
    assert db_client.get("/api/regulation-db/regulations").json()["total"] == 0


def test_kolam_kandidat_hybrid_minimal_40():
    from app.services.regulation_db import hybrid_candidate_pool

    assert hybrid_candidate_pool(5) == 40
    assert hybrid_candidate_pool(8) == 40
    assert hybrid_candidate_pool(60) == 60


def test_hybrid_mengambil_kolam_besar_lalu_memotong_ke_top_k(db_client, sample_txt_path):
    """
    RRF menggabungkan kandidat vektor & kata kunci; kolam = top_k membuang chunk
    yang bagus di keduanya. Query harus meminta >= 40 kandidat ke LanceDB tapi
    tetap mengembalikan tepat top_k hasil.
    """
    from lancedb.query import LanceHybridQueryBuilder, LanceVectorQueryBuilder

    from app.services import regulation_db

    _upload_ok(db_client, sample_txt_path, "Contoh 1/2026")
    vec = _KeywordEmbedder().embed_query("pengendalian akses pengguna")

    limits = {"hybrid": [], "vector": []}
    orig_h, orig_v = LanceHybridQueryBuilder.limit, LanceVectorQueryBuilder.limit

    def spy_h(self, n):
        limits["hybrid"].append(n)
        return orig_h(self, n)

    def spy_v(self, n):
        limits["vector"].append(n)
        return orig_v(self, n)

    with patch.object(LanceHybridQueryBuilder, "limit", spy_h), \
         patch.object(LanceVectorQueryBuilder, "limit", spy_v):
        hybrid = regulation_db.query_relevant_chunks(vec, top_k=3, query_text="pengendalian akses")
        # Hybrid builder juga membuat sub-query vektor internal dengan limit yang sama.
        assert set(limits["vector"]) <= {40}
        limits["vector"].clear()
        vector = regulation_db.query_relevant_chunks(vec, top_k=3)

    assert limits["hybrid"] == [40]
    assert len(hybrid) == 3
    assert limits["vector"] == [3]   # mode vektor saja tidak berubah
    assert len(vector) == 3
