"""
Fase 5 — Tanya Regulasi (RAG Chat): retrieval, sitasi tervalidasi, konteks
pertanyaan lanjutan. Embedding & AI di-mock; LanceDB asli di cwd sementara.
"""

import json
import re
import zlib
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from app.services.ai_service import AIProvider, AIProviderError
from app.services.regulation_chat import retrieval_query
from tests.conftest import wait_for_job


class _KeywordEmbedder:
    def __init__(self):
        self.queries: list[str] = []

    def embed_batch(self, texts, task_type="RETRIEVAL_DOCUMENT", on_batch_done=None):
        if task_type == "RETRIEVAL_QUERY":
            self.queries.extend(texts)
        out = []
        for text in texts:
            v = np.zeros(768, dtype=np.float32)
            for w in re.findall(r"[a-z]{4,}", text.lower()):
                v[zlib.crc32(w.encode()) % 768] += 1.0
            out.append(v.tolist())
        if on_batch_done:
            on_batch_done(len(texts), len(texts))
        return out


class _ChatProvider(AIProvider):
    """Menjawab dengan template; `make(prompt)` → dict JSON jawaban."""

    def __init__(self, make):
        self.make = make
        self.prompts: list[str] = []

    def generate_text(self, system_prompt, user_prompt, expect_json=False):
        self.prompts.append(user_prompt)
        return json.dumps(self.make(user_prompt))


def _source_number(prompt: str, needle: str) -> int:
    """Nomor [n] sumber yang memuat `needle` di prompt."""
    for block in prompt.split("\n\n"):
        m = re.match(r"\[(\d+)\]", block)
        if m and needle in block:
            return int(m.group(1))
    raise AssertionError(f"sumber dengan {needle!r} tidak ada di prompt")


@pytest.fixture
def chat_client(client, sample_txt_path):
    """Client dengan 1 regulasi contoh ter-index + embedder tiruan."""
    from app.services import regulation_db

    regulation_db._db = None
    embedder = _KeywordEmbedder()
    with patch("app.api.common.EmbeddingService", return_value=embedder):
        with open(sample_txt_path, "rb") as f:
            res = client.post(
                "/api/regulation-db/upload",
                files={"file": (Path(sample_txt_path).name, f, "text/plain")},
                data={"name": "Contoh 1/2026"},
            )
        assert res.status_code == 202, res.text
        job = wait_for_job(client, res.json()["job_id"])
        assert job["status"] == "succeeded", job
        client.regulation_id = job["extra"]["regulation"]["id"]
        client.embedder = embedder
        yield client
    regulation_db._db = None


def _ask(client, provider, **payload):
    with patch("app.api.common.get_ai_provider", return_value=provider):
        return client.post("/api/chat", json=payload)


def test_jawaban_bersitasi_dengan_rujukan_dari_database(chat_client):
    def make(prompt):
        n = _source_number(prompt, "3 (tiga) hari kerja")
        return {"jawaban": f"Insiden wajib dilaporkan paling lambat 3 hari kerja [{n}].",
                "sumber": [n], "ditemukan": True}

    res = _ask(chat_client, _ChatProvider(make), question="Berapa lama batas pelaporan insiden keamanan?")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["found"] is True and not data["needs_review"]
    cited = [s for s in data["sources"] if s["cited"]]
    assert len(cited) == 1 and data["cited"] == [cited[0]["number"]]
    assert cited[0]["reference"].startswith("Contoh 1/2026 Pasal 22")
    assert "3 (tiga) hari kerja" in cited[0]["text"]  # kutipan asli dari DB


def test_sitasi_ke_sumber_yang_tidak_ada_dihapus_dan_ditandai(chat_client):
    provider = _ChatProvider(lambda p: {
        "jawaban": "Bank wajib memiliki kebijakan keamanan [1][42].", "sumber": [1, 99], "ditemukan": True,
    })
    data = _ask(chat_client, provider, question="Apa kewajiban kebijakan keamanan informasi?").json()
    assert "[42]" not in data["answer"] and "[1]" in data["answer"]
    assert data["cited"] == [1]
    assert data["needs_review"]
    assert any("[42]" in n and "[99]" in n for n in data["notes"])


def test_jawaban_tanpa_sitasi_ditandai_perlu_ditinjau(chat_client):
    provider = _ChatProvider(lambda p: {"jawaban": "Bank wajib patuh.", "sumber": [], "ditemukan": True})
    data = _ask(chat_client, provider, question="Apa kewajiban bank?").json()
    assert data["needs_review"] and data["cited"] == []


def test_tidak_ditemukan_tidak_ditandai_sebagai_masalah(chat_client):
    provider = _ChatProvider(lambda p: {
        "jawaban": "Ketentuan mengenai kripto tidak ditemukan pada regulasi yang dipilih.",
        "sumber": [], "ditemukan": False,
    })
    data = _ask(chat_client, provider, question="Bagaimana aturan aset kripto?").json()
    assert data["found"] is False and not data["needs_review"]


def test_pertanyaan_lanjutan_pendek_memakai_konteks_sebelumnya(chat_client):
    provider = _ChatProvider(lambda p: {"jawaban": "Lihat [1].", "sumber": [1], "ditemukan": True})
    history = [
        {"role": "user", "content": "Apa kewajiban pengendalian akses sistem informasi?"},
        {"role": "assistant", "content": "Lembaga wajib menerapkan pengendalian akses [1]."},
    ]
    res = _ask(chat_client, provider, question="Apa saja cakupannya?", history=history)
    assert res.status_code == 200, res.text
    assert "pengendalian akses" in chat_client.embedder.queries[-1]
    assert "PERCAKAPAN SEBELUMNYA" in provider.prompts[-1]


def test_retrieval_query_hanya_menggabung_pertanyaan_pendek():
    history = [{"role": "user", "content": "Apa kewajiban backup?"}]
    assert retrieval_query("Apa sanksinya?", history) == "Apa kewajiban backup?\nApa sanksinya?"
    long_q = "Apa saja kewajiban bank terkait pusat data dan pusat pemulihan bencana di Indonesia?"
    assert retrieval_query(long_q, history) == long_q


def test_filter_regulasi_tidak_dikenal_404(chat_client):
    res = _ask(chat_client, _ChatProvider(lambda p: {}), question="Apa kewajiban bank?",
               regulation_ids=["f" * 32])
    assert res.status_code == 404


def test_error_ai_jadi_502_dengan_pesan_ramah(chat_client):
    class _Down(AIProvider):
        def generate_text(self, *a, **k):
            raise AIProviderError("Quota / rate limit Gemini API habis (429).")

    res = _ask(chat_client, _Down(), question="Apa kewajiban bank?")
    assert res.status_code == 502
    assert "Quota" in res.json()["detail"]


def test_tanpa_api_key_422(client):
    res = client.post("/api/chat", json={"question": "Apa kewajiban bank?"})
    assert res.status_code == 422
