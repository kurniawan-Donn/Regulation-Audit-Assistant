"""
Fase 2 — akurasi Compliance Review.

Semua AI & embedding di-mock:
- _KeywordEmbedder: bag-of-words hash → cosine mencerminkan kesamaan kata.
- _ScriptedProvider: membaca ID klausul (K1..) & regulasi (R1..) dari prompt
  dan menjawab sesuai skenario test.
"""

import json
import re
import zlib
from unittest.mock import patch

import numpy as np
import pytest

from app.services.ai_service import AIProvider, AIProviderError
from app.services.compliance_retrieval import embed_regulation_chunks, retrieve_local
from app.services.compliance_review_analyzer import (
    STATUS_PERLU_VERIFIKASI,
    count_by_status,
    group_contract_units,
    review_batch,
)
from tests.conftest import wait_for_job


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _KeywordEmbedder:
    def __init__(self):
        self.calls = 0

    def embed_batch(self, texts, task_type="RETRIEVAL_DOCUMENT", on_batch_done=None):
        self.calls += 1
        vectors = []
        for text in texts:
            v = np.zeros(768, dtype=np.float32)
            for word in re.findall(r"[a-z]{4,}", text.lower()):
                v[zlib.crc32(word.encode()) % 768] += 1.0
            vectors.append(v.tolist())
        if on_batch_done:
            on_batch_done(len(texts), len(texts))
        return vectors


def _parse_prompt(prompt: str) -> dict[str, list[str]]:
    """{"K1": ["R1", "R2"], ...} dari baris 'Regulasi relevan untuk K1: R1, R2'."""
    found = {}
    for kid, regs in re.findall(r"Regulasi relevan untuk (K\d+): (.*)", prompt):
        found[kid] = re.findall(r"R\d+", regs)
    return found


class _ScriptedProvider(AIProvider):
    """Default: setiap klausul PATUH dengan mengutip regulasi pertamanya."""

    def __init__(self, respond=None):
        self.prompts: list[str] = []
        self.respond = respond

    def generate_text(self, system_prompt, user_prompt, expect_json=False):
        if not expect_json:
            return "Ringkasan tiruan."
        self.prompts.append(user_prompt)
        clauses = _parse_prompt(user_prompt)
        if self.respond:
            return json.dumps(self.respond(clauses, user_prompt))
        return json.dumps([
            {"klausul_id": k, "regulasi_ids": regs[:1], "status": "PATUH", "analisis": f"ok {k}"}
            for k, regs in clauses.items()
        ])


def _unit(ref, text, regs=()):
    return {"klausul_ref": ref, "judul": "", "text": text, "regulations": list(regs)}


def _reg(key, pasal, ayat=None, text="isi", source="POJK 11/2022"):
    return {"key": key, "text": text, "source": source, "pasal": pasal, "ayat": ayat}


# ---------------------------------------------------------------------------
# Unit klausul
# ---------------------------------------------------------------------------

def test_butir_kontrak_digabung_ke_ayatnya():
    chunks = [
        {"pasal": None, "ayat": None, "huruf": None,
         "text": "Perjanjian ini dibuat oleh dan antara PT Bank Contoh, berkedudukan di Jakarta, "
                 "dalam hal ini diwakili oleh Direktur Utama, selanjutnya disebut PIHAK PERTAMA."},
        {"pasal": "Pasal 2", "pasal_judul": "KEWAJIBAN", "ayat": "(1)", "huruf": None,
         "text": "PIHAK KEDUA wajib:"},
        {"pasal": "Pasal 2", "pasal_judul": "KEWAJIBAN", "ayat": "(1)", "huruf": "a)",
         "text": "a) menjaga kerahasiaan data;"},
        {"pasal": "Pasal 2", "pasal_judul": "KEWAJIBAN", "ayat": "(2)", "huruf": None,
         "text": "PIHAK KEDUA menyediakan backup."},
    ]
    units = group_contract_units(chunks)
    assert [u["klausul_ref"] for u in units] == [
        "Pembukaan / Para Pihak", "Pasal 2 ayat (1)", "Pasal 2 ayat (2)",
    ]
    assert "a) menjaga kerahasiaan data;" in units[1]["text"]
    assert units[1]["judul"] == "KEWAJIBAN"


# ---------------------------------------------------------------------------
# review_batch: pencocokan ID & validasi
# ---------------------------------------------------------------------------

def test_hasil_dicocokkan_berdasarkan_id_bukan_urutan():
    units = [
        _unit("Pasal 1", "klausul satu", [_reg("a", "Pasal 10")]),
        _unit("Pasal 2", "klausul dua", [_reg("b", "Pasal 20", "(3)")]),
    ]
    provider = _ScriptedProvider(lambda clauses, _: [
        {"klausul_id": "K2", "regulasi_ids": ["R2"], "status": "TIDAK PATUH", "analisis": "dua"},
        {"klausul_id": "K1", "regulasi_ids": ["R1"], "status": "PATUH", "analisis": "satu"},
    ])
    items = review_batch(units, provider)
    assert [(i["klausul_ref"], i["status"], i["analisis"]) for i in items] == [
        ("Pasal 1", "PATUH", "satu"),
        ("Pasal 2", "TIDAK PATUH", "dua"),
    ]
    # regulasi_ref disusun dari metadata chunk yang dikutip
    assert items[1]["regulasi_ref"] == "POJK 11/2022 Pasal 20 ayat (3)"
    assert items[1]["klausul_text"] == "klausul dua"  # teks dari dokumen, bukan AI
    assert not items[0]["needs_review"]


def test_klausul_yang_dilewati_ai_menjadi_perlu_verifikasi():
    units = [_unit("Pasal 1", "satu", [_reg("a", "Pasal 1")]), _unit("Pasal 2", "dua")]
    provider = _ScriptedProvider(lambda clauses, _: [
        {"klausul_id": "K1", "regulasi_ids": ["R1"], "status": "PATUH", "analisis": "ok"},
    ])
    items = review_batch(units, provider)
    assert items[1]["status"] == STATUS_PERLU_VERIFIKASI
    assert items[1]["needs_review"]


def test_status_tidak_dikenal_tidak_disamarkan_sebagai_tidak_relevan():
    units = [_unit("Pasal 1", "satu", [_reg("a", "Pasal 1")])]
    provider = _ScriptedProvider(lambda clauses, _: [
        {"klausul_id": "K1", "regulasi_ids": ["R1"], "status": "SEBAGIAN", "analisis": "?"},
    ])
    item = review_batch(units, provider)[0]
    assert item["status"] == STATUS_PERLU_VERIFIKASI
    assert any("tidak dikenali" in n for n in item["validation_notes"])


def test_kutipan_regulasi_karangan_ai_ditandai():
    units = [
        _unit("Pasal 1", "satu", [_reg("a", "Pasal 1")]),
        _unit("Pasal 2", "dua", [_reg("b", "Pasal 2")]),
    ]
    provider = _ScriptedProvider(lambda clauses, _: [
        # R2 milik K2, bukan K1; R9 tidak pernah ada.
        {"klausul_id": "K1", "regulasi_ids": ["R2", "R9"], "status": "TIDAK PATUH",
         "regulasi_ref": "POJK 99/2030 Pasal 77", "analisis": "x"},
        {"klausul_id": "K2", "regulasi_ids": ["R2"], "status": "PATUH", "analisis": "y"},
    ])
    k1, k2 = review_batch(units, provider)
    assert k1["needs_review"]
    assert any("halusinasi" in n for n in k1["validation_notes"])
    assert any("Tidak ada kutipan regulasi yang valid" in n for n in k1["validation_notes"])
    assert not k2["needs_review"]


def test_tidak_relevan_tanpa_kutipan_tidak_ditandai():
    units = [_unit("Pembukaan", "PERJANJIAN KERJASAMA", [_reg("a", "Pasal 1")])]
    provider = _ScriptedProvider(lambda clauses, _: [
        {"klausul_id": "K1", "regulasi_ids": [], "status": "TIDAK RELEVAN", "analisis": "-"},
    ])
    item = review_batch(units, provider)[0]
    assert item["status"] == "TIDAK RELEVAN"
    assert not item["needs_review"]


def test_regulasi_yang_sama_hanya_dicantumkan_sekali_per_batch():
    shared = _reg("x", "Pasal 5", text="TEKS-REGULASI-BERSAMA")
    units = [_unit("Pasal 1", "satu", [shared]), _unit("Pasal 2", "dua", [shared])]
    provider = _ScriptedProvider()
    review_batch(units, provider)
    assert provider.prompts[0].count("TEKS-REGULASI-BERSAMA") == 1
    assert _parse_prompt(provider.prompts[0]) == {"K1": ["R1"], "K2": ["R1"]}


def test_count_by_status_memisahkan_perlu_verifikasi():
    counts = count_by_status([{"status": "TIDAK RELEVAN"}, {"status": STATUS_PERLU_VERIFIKASI}])
    assert counts["total_tidak_relevan"] == 1
    assert counts["total_perlu_verifikasi"] == 1


# ---------------------------------------------------------------------------
# Retrieval lokal (mode upload)
# ---------------------------------------------------------------------------

def test_retrieval_lokal_memilih_regulasi_relevan_dan_memakai_cache(tmp_path):
    reg_chunks = [{"text": f"ketentuan umum definisi istilah nomor {i}", "pasal": "Pasal 1",
                   "source_file": "POJK.pdf"} for i in range(120)]
    reg_chunks.append({"text": "bank wajib memastikan penyedia jasa menyerahkan kembali "
                               "seluruh data saat pengakhiran perjanjian",
                       "pasal": "Pasal 20", "ayat": "(3)", "source_file": "POJK.pdf"})
    embedder = _KeywordEmbedder()
    cache = tmp_path / "emb.npy"

    matrix = embed_regulation_chunks(reg_chunks, embedder, cache_path=cache)
    units = [_unit("Pasal 9", "pengakhiran perjanjian: penyedia jasa menyerahkan kembali seluruh data")]
    retrieve_local(units, embedder, reg_chunks, matrix, top_k=3)

    # Chunk relevan ada di posisi 121 — dulu terpotong oleh batas 100 chunk pertama.
    assert units[0]["regulations"][0]["pasal"] == "Pasal 20"
    assert units[0]["regulations"][0]["source"] == "POJK"

    calls = embedder.calls
    embed_regulation_chunks(reg_chunks, embedder, cache_path=cache)
    assert embedder.calls == calls  # embedding regulasi dipakai ulang dari cache


# ---------------------------------------------------------------------------
# Endpoint (job) — mode upload, mode database, analyze-items
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_ai():
    provider = _ScriptedProvider()
    embedder = _KeywordEmbedder()
    with patch("app.api.routes.get_ai_provider", return_value=provider), \
         patch("app.api.routes.EmbeddingService", return_value=embedder):
        yield provider


@pytest.fixture
def compliance_preview_id(client, sample_contract_path, sample_txt_path) -> str:
    with open(sample_contract_path, "rb") as c, open(sample_txt_path, "rb") as r:
        res = client.post("/api/compliance/preview", files=[
            ("contract_file", ("kontrak.txt", c, "text/plain")),
            ("regulation_files", ("regulasi_contoh.txt", r, "text/plain")),
        ])
    assert res.status_code == 200, res.text
    return res.json()["preview_id"]


def test_compliance_mode_upload(fake_ai, run_job, compliance_preview_id):
    job, data = run_job("POST", "/api/compliance/analyze", json={"preview_id": compliance_preview_id})
    assert job["status"] == "succeeded", job
    assert data["retrieval"]["mode"] == "upload"
    assert data["total_items"] >= 4
    assert data["total_items"] == sum(
        data[k] for k in ("total_patuh", "total_patuh_catatan", "total_tidak_patuh",
                          "total_tidak_relevan", "total_perlu_verifikasi")
    )
    item = next(i for i in data["items"] if i["klausul_ref"].startswith("Pasal 3"))
    assert item["status"] == "PATUH"
    assert item["regulasi_ref"].startswith("regulasi_contoh")  # nama sumber ikut di referensi
    assert "standar keamanan informasi" in item["klausul_text"]


def test_compliance_batch_gagal_tidak_menggagalkan_seluruh_review(
    run_job, compliance_preview_id
):
    class _FlakyProvider(_ScriptedProvider):
        def generate_text(self, system_prompt, user_prompt, expect_json=False):
            if expect_json and "=== K1: Pasal 1 ===" in user_prompt:
                raise AIProviderError("simulasi Gemini down")
            return super().generate_text(system_prompt, user_prompt, expect_json)

    with patch("app.api.routes.get_ai_provider", return_value=_FlakyProvider()), \
         patch("app.api.routes.EmbeddingService", return_value=_KeywordEmbedder()), \
         patch("app.services.analysis_jobs.COMPLIANCE_UNITS_PER_BATCH", 1):
        job, data = run_job("POST", "/api/compliance/analyze", json={"preview_id": compliance_preview_id})

    assert job["status"] == "succeeded"
    failed = [i for i in data["items"] if i["status"] == STATUS_PERLU_VERIFIKASI]
    assert len(failed) == 1 and "simulasi Gemini down" in failed[0]["analisis"]
    assert data["total_patuh"] == data["total_items"] - 1


@patch("app.services.compliance_retrieval.query_relevant_chunks")
@patch("app.api.routes.get_regulation", return_value={"id": "a" * 32, "name": "POJK 11/2022"})
def test_compliance_mode_database_lalu_analyze_items(
    _get_reg, mock_query, fake_ai, client, run_job, sample_contract_path
):
    mock_query.return_value = [{
        "id": "a_1", "text": "Bank wajib menjaga kerahasiaan data nasabah.", "distance": 0.2,
        "metadata": {"regulation_name": "POJK 11/2022", "pasal": "Pasal 20", "ayat": "(1)"},
    }]
    with open(sample_contract_path, "rb") as f:
        job, data = run_job(
            "POST", "/api/compliance/analyze-from-db",
            files={"contract_file": ("kontrak.txt", f, "text/plain")},
            data={"regulation_ids": "a" * 32},
        )
    assert job["status"] == "succeeded", job
    assert data["retrieval"] == {"mode": "database", "regulation_ids": ["a" * 32], "top_k": 5}
    assert data["items"][1]["regulasi_ref"] == "POJK 11/2022 Pasal 20 ayat (1)"
    assert mock_query.call_args.kwargs["top_k"] == 5

    # Klausul baru (mis. hasil import) → "Analisis Sekarang" pada hasil mode database.
    rid = data["result_id"]
    res = client.post(f"/api/compliance/{rid}/items", json={
        "klausul_ref": "Pasal 9", "klausul_text": "PIHAK KEDUA menjaga kerahasiaan data.",
        "status": STATUS_PERLU_VERIFIKASI,
    })
    assert res.status_code == 200, res.text
    new_idx = data["total_items"]

    job, updated = run_job("POST", f"/api/compliance/{rid}/analyze-items", json={"item_indices": [new_idx]})
    assert job["status"] == "succeeded", job
    assert job["extra"]["affected"] == 1
    assert updated["items"][new_idx]["status"] == "PATUH"
    assert updated["items"][new_idx]["regulasi_ref"] == "POJK 11/2022 Pasal 20 ayat (1)"
    assert updated["total_perlu_verifikasi"] == 0


def test_edit_status_oleh_auditor_menandai_baris_sudah_ditinjau(
    fake_ai, client, run_job, compliance_preview_id
):
    _, data = run_job("POST", "/api/compliance/analyze", json={"preview_id": compliance_preview_id})
    rid = data["result_id"]
    res = client.patch(f"/api/compliance/{rid}/items/0", json={"status": STATUS_PERLU_VERIFIKASI})
    assert res.status_code == 200 and res.json()["needs_review"] is True
    res = client.patch(f"/api/compliance/{rid}/items/0", json={"status": "TIDAK RELEVAN"})
    assert res.status_code == 200 and res.json()["needs_review"] is False
    assert client.patch(f"/api/compliance/{rid}/items/0", json={"status": "NGAWUR"}).status_code == 422


def test_compliance_cancel_menyimpan_hasil_parsial(client, compliance_preview_id):
    import threading

    first_done = threading.Event()
    release = threading.Event()

    class _SlowProvider(_ScriptedProvider):
        def generate_text(self, system_prompt, user_prompt, expect_json=False):
            if expect_json and first_done.is_set():
                release.wait(5)
            out = super().generate_text(system_prompt, user_prompt, expect_json)
            first_done.set()
            return out

    with patch("app.api.routes.get_ai_provider", return_value=_SlowProvider()), \
         patch("app.api.routes.EmbeddingService", return_value=_KeywordEmbedder()), \
         patch("app.services.analysis_jobs.COMPLIANCE_UNITS_PER_BATCH", 1):
        res = client.post("/api/compliance/analyze", json={"preview_id": compliance_preview_id})
        job_id = res.json()["job_id"]
        assert first_done.wait(5)
        client.post(f"/api/jobs/{job_id}/cancel")
        release.set()
        job = wait_for_job(client, job_id)

    assert job["status"] == "cancelled" and job["partial"]
    data = client.get(job["result_url"]).json()
    assert data["total_perlu_verifikasi"] >= 1
    assert any("dibatalkan" in w for w in data["warnings"])


def test_chunk_judul_pasal_kontrak_bukan_unit_klausul():
    chunks = [
        {"pasal": "Pasal 2", "pasal_judul": "KEWAJIBAN PIHAK KEDUA", "ayat": None,
         "text": "KEWAJIBAN PIHAK KEDUA"},
        {"pasal": "Pasal 2", "pasal_judul": "KEWAJIBAN PIHAK KEDUA", "ayat": "(1)",
         "text": "PIHAK KEDUA wajib menjaga kerahasiaan data."},
    ]
    assert [u["klausul_ref"] for u in group_contract_units(chunks)] == ["Pasal 2 ayat (1)"]


def test_halaman_judul_regulasi_tidak_jadi_kandidat_kutipan():
    from app.services.compliance_retrieval import retrieval_candidates

    chunks = [
        {"text": "PERATURAN CONTOH TENTANG TATA KELOLA"},
        {"text": "Bank wajib ...", "bab": "BAB V", "pasal": "Pasal 20"},
    ]
    assert retrieval_candidates(chunks) == [chunks[1]]
    assert retrieval_candidates(chunks[:1]) == chunks[:1]  # dokumen tanpa struktur


def test_pembukaan_yang_hanya_judul_tidak_direview():
    chunks = [
        {"pasal": None, "ayat": None, "text": "PERJANJIAN KERJASAMA SEWA LAYANAN TEKNOLOGI INFORMASI"},
        {"pasal": "Pasal 1", "ayat": None, "text": "PIHAK KEDUA menyediakan layanan TI."},
    ]
    assert [u["klausul_ref"] for u in group_contract_units(chunks)] == ["Pasal 1"]


def test_id_internal_di_analisis_diganti_referensi_pasal():
    units = [
        _unit("Pasal 2", "kerahasiaan", [
            _reg("a", "Pasal 30", "(3)"),
            {**_reg("b", "Pasal 32", "(4)"), "lampiran": "Penjelasan"},
        ]),
    ]
    provider = _ScriptedProvider(lambda clauses, _: [{
        "klausul_id": "K1", "regulasi_ids": ["R1", "R2"], "status": "TIDAK PATUH",
        "analisis": "Klausul K1 belum memuat kewajiban Pasal 30 ayat (3) (R1) "
                    "serta penyerahan data sesuai R2 (lihat juga R9).",
    }])
    item = review_batch(units, provider)[0]
    assert item["analisis"] == (
        "Klausul ini belum memuat kewajiban Pasal 30 ayat (3) "
        "serta penyerahan data sesuai Penjelasan Pasal 32 ayat (4) (lihat juga R9)."
    )
    assert item["regulasi_ref"] == "POJK 11/2022 Pasal 30 ayat (3); POJK 11/2022 Penjelasan Pasal 32 ayat (4)"
