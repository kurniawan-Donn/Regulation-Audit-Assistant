"""
Phase 11 - Optimasi Rate Limit (Batching).

Menguji:
1. chunk_batcher.create_batches() - pengelompokan berdasarkan budget karakter
2. regulation_audit_prompt.build_batch_user_prompt() - format prompt multi-chunk
3. audit_analyzer.analyze_chunks_batch() - orkestrasi batch + AI
4. GeminiProvider - pacing antar-request (rate limiting) & max_output_tokens
"""

from unittest.mock import MagicMock, patch

import pytest

from app.prompts.regulation_audit_prompt import build_batch_user_prompt
from app.services.ai_service import AIProvider, GeminiProvider
from app.services.audit_analyzer import AuditAnalysisError, analyze_chunks_batch
from app.services.chunk_batcher import create_batches


def _make_chunk(text: str, pasal: str | None = None) -> dict:
    return {"bab": "BAB V", "bagian": None, "pasal": pasal, "ayat": None, "huruf": [], "text": text}


# ---------------------------------------------------------------------------
# create_batches()
# ---------------------------------------------------------------------------

def test_create_batches_kosong():
    assert create_batches([]) == []


def test_create_batches_menggabung_sesuai_budget():
    chunks = [_make_chunk("a" * 30, f"Pasal {i}") for i in range(5)]  # tiap chunk 30 char
    batches = create_batches(chunks, max_chars_per_batch=100)

    # 100 // 30 = 3 chunk per batch -> [3, 2]
    assert [len(b) for b in batches] == [3, 2]
    # Tidak ada chunk yang hilang atau berubah urutan
    flat = [c for batch in batches for c in batch]
    assert flat == chunks


def test_create_batches_chunk_besar_sendiri_tidak_dipotong():
    small = _make_chunk("x" * 10, "Pasal 1")
    huge = _make_chunk("y" * 500, "Pasal 2")  # jauh melebihi budget sendirian
    chunks = [small, huge, small]

    batches = create_batches(chunks, max_chars_per_batch=50)

    # huge harus jadi batch tersendiri, isinya utuh tidak terpotong
    huge_batches = [b for b in batches if huge in b]
    assert len(huge_batches) == 1
    assert len(huge_batches[0]) == 1
    assert huge_batches[0][0]["text"] == "y" * 500  # tidak terpotong


def test_create_batches_total_chunk_tidak_berubah():
    chunks = [_make_chunk("z" * 20, f"Pasal {i}") for i in range(37)]
    batches = create_batches(chunks, max_chars_per_batch=137)
    total = sum(len(b) for b in batches)
    assert total == len(chunks)


# ---------------------------------------------------------------------------
# build_batch_user_prompt()
# ---------------------------------------------------------------------------

def test_build_batch_user_prompt_mencakup_semua_chunk():
    chunks = [
        _make_chunk("Isi ketentuan pertama.", "Pasal 20"),
        _make_chunk("Isi ketentuan kedua.", "Pasal 21"),
    ]
    prompt = build_batch_user_prompt(chunks, referensi_regulasi="POJK Contoh")

    assert "POJK Contoh" in prompt
    assert "=== POTONGAN 1 ===" in prompt
    assert "=== POTONGAN 2 ===" in prompt
    assert "Pasal 20" in prompt
    assert "Pasal 21" in prompt
    assert "Isi ketentuan pertama." in prompt
    assert "Isi ketentuan kedua." in prompt
    assert "2 potongan" in prompt.lower() or "Analisis SEMUA 2 potongan" in prompt


# ---------------------------------------------------------------------------
# analyze_chunks_batch()
# ---------------------------------------------------------------------------

class _FakeProvider(AIProvider):
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.last_user_prompt = None

    def generate_text(self, system_prompt, user_prompt, expect_json=False):
        self.last_user_prompt = user_prompt
        return self._response_text


def test_analyze_chunks_batch_kosong_tidak_memanggil_ai():
    provider = _FakeProvider("harusnya tidak pernah dipanggil")
    result = analyze_chunks_batch([], provider)
    assert result == []
    assert provider.last_user_prompt is None  # AI tidak pernah dipanggil untuk batch kosong


def test_analyze_chunks_batch_menggabung_hasil():
    chunks = [_make_chunk("Ketentuan A", "Pasal 1"), _make_chunk("Ketentuan B", "Pasal 2")]
    fake = _FakeProvider(
        '[{"referensi_regulasi": "X", "bab_pasal_ayat": "Pasal 1", '
        '"point_ketentuan": "A", "pemeriksaan": "Periksa A."},'
        '{"referensi_regulasi": "X", "bab_pasal_ayat": "Pasal 2", '
        '"point_ketentuan": "B", "pemeriksaan": "Periksa B."}]'
    )
    result = analyze_chunks_batch(chunks, fake, referensi_regulasi="X")

    assert len(result) == 2
    assert "Pasal 1" in fake.last_user_prompt
    assert "Pasal 2" in fake.last_user_prompt


def test_analyze_chunks_batch_raise_jika_bukan_list():
    chunks = [_make_chunk("Ketentuan A", "Pasal 1")]
    fake = _FakeProvider('{"bukan": "list"}')
    with pytest.raises(AuditAnalysisError):
        analyze_chunks_batch(chunks, fake)


# ---------------------------------------------------------------------------
# GeminiProvider - rate limit pacing & max_output_tokens
# ---------------------------------------------------------------------------

@patch("app.services.ai_service.genai.Client")
@patch("app.services.ai_service.time.sleep")
@patch("app.services.ai_service.time.time")
def test_rate_limit_pacing_menunggu_jika_terlalu_cepat(mock_time, mock_sleep, mock_model_class):
    fake_response = MagicMock()
    fake_response.candidates = [MagicMock()]
    fake_response.text = "ok"
    mock_model_class.return_value.models.generate_content.return_value = fake_response

    # Simulasikan: waktu saat ini 1.0 detik setelah request sebelumnya,
    # padahal jarak minimum di-set 4.5 detik -> harus sleep ~3.5 detik.
    mock_time.side_effect = [1.0, 1.0]  # dipanggil di _wait_for_rate_limit lalu setelah request

    provider = GeminiProvider(api_key="fake-key", min_seconds_between_requests=4.5)
    provider._last_request_time = 0.0  # anggap request sebelumnya di t=0

    provider.generate_text("system", "user")

    mock_sleep.assert_called_once()
    waited = mock_sleep.call_args[0][0]
    assert waited == pytest.approx(3.5, abs=0.01)


@patch("app.services.ai_service.genai.Client")
@patch("app.services.ai_service.time.sleep")
@patch("app.services.ai_service.time.time")
def test_rate_limit_pacing_tidak_menunggu_jika_sudah_cukup_lama(mock_time, mock_sleep, mock_model_class):
    fake_response = MagicMock()
    fake_response.candidates = [MagicMock()]
    fake_response.text = "ok"
    mock_model_class.return_value.models.generate_content.return_value = fake_response

    mock_time.side_effect = [10.0, 10.0]  # 10 detik berlalu, lebih dari cukup

    provider = GeminiProvider(api_key="fake-key", min_seconds_between_requests=4.5)
    provider._last_request_time = 0.0

    provider.generate_text("system", "user")

    mock_sleep.assert_not_called()


@patch("app.services.ai_service.genai.Client")
def test_max_output_tokens_diteruskan_ke_generation_config(mock_model_class):
    fake_response = MagicMock()
    fake_response.candidates = [MagicMock()]
    fake_response.text = "ok"
    mock_model_class.return_value.models.generate_content.return_value = fake_response

    provider = GeminiProvider(api_key="fake-key", max_output_tokens=12345, min_seconds_between_requests=0)
    provider.generate_text("system", "user")

    _, kwargs = mock_model_class.return_value.models.generate_content.call_args
    assert kwargs["config"].max_output_tokens == 12345


@patch("app.services.ai_service.genai.Client")
def test_automatic_function_calling_dimatikan(mock_client_class):
    fake_response = MagicMock()
    fake_response.candidates = [MagicMock()]
    fake_response.text = "ok"
    mock_client_class.return_value.models.generate_content.return_value = fake_response

    GeminiProvider(api_key="fake-key", min_seconds_between_requests=0).generate_text("s", "u")

    _, kwargs = mock_client_class.return_value.models.generate_content.call_args
    assert kwargs["config"].automatic_function_calling.disable is True
