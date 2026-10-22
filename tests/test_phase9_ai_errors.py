"""
Phase 9 - Testing Menyeluruh: Error Handling AI.

Mencakup skenario testing wajib dari brief (section 17, Phase 9):
7. AI timeout
8. API error
9. Invalid JSON dari AI

Semua di-mock (tidak memanggil Gemini API sungguhan) supaya deterministik
dan tidak butuh API key/network untuk dijalankan sebagai bagian test suite.
"""

from unittest.mock import patch

import httpx
import pytest
from google.genai import errors as genai_errors

from app.services.ai_service import (
    AIProvider,
    AIProviderError,
    AIResponseParsingError,
    GeminiProvider,
)


class _FakeProvider(AIProvider):
    def generate_text(self, system_prompt, user_prompt, expect_json=False):
        return "[]"


def _api_error(cls, code: int, message: str):
    return cls(code, {"error": {"code": code, "message": message, "status": "X"}})


@patch("app.services.ai_service.genai.Client")
def test_7_ai_timeout_habiskan_retry_lalu_error(mock_client_class):
    mock_client_class.return_value.models.generate_content.side_effect = httpx.ReadTimeout(
        "simulasi timeout"
    )
    provider = GeminiProvider(
        api_key="fake-key", max_network_retries=1, retry_backoff_seconds=0,
        min_seconds_between_requests=0,
    )

    with pytest.raises(AIProviderError):
        provider.generate_text("system", "user")

    # 1 percobaan awal + 1 retry = 2 panggilan
    assert mock_client_class.return_value.models.generate_content.call_count == 2


@patch("app.services.ai_service.genai.Client")
def test_7b_server_503_di_retry(mock_client_class):
    mock_client_class.return_value.models.generate_content.side_effect = _api_error(
        genai_errors.ServerError, 503, "simulasi unavailable"
    )
    provider = GeminiProvider(
        api_key="fake-key", max_network_retries=2, retry_backoff_seconds=0,
        min_seconds_between_requests=0,
    )

    with pytest.raises(AIProviderError):
        provider.generate_text("system", "user")

    assert mock_client_class.return_value.models.generate_content.call_count == 3


@patch("app.services.ai_service.genai.Client")
def test_8_api_error_non_retryable_langsung_gagal(mock_client_class):
    """Error non-transient (mis. API key ditolak) TIDAK boleh di-retry, harus langsung gagal."""
    mock_client_class.return_value.models.generate_content.side_effect = _api_error(
        genai_errors.ClientError, 403, "simulasi API key ditolak"
    )
    provider = GeminiProvider(
        api_key="fake-key", max_network_retries=2, retry_backoff_seconds=0,
        min_seconds_between_requests=0,
    )

    with pytest.raises(AIProviderError, match="403"):
        provider.generate_text("system", "user")

    # Error non-transient -> tidak boleh retry -> hanya 1 kali panggilan
    assert mock_client_class.return_value.models.generate_content.call_count == 1


def test_9_invalid_json_habiskan_retry_lalu_error():
    class _AlwaysBadJSON(AIProvider):
        def __init__(self):
            self.call_count = 0

        def generate_text(self, system_prompt, user_prompt, expect_json=False):
            self.call_count += 1
            return "ini teks biasa, bukan JSON sama sekali"

    provider = _AlwaysBadJSON()

    with pytest.raises(AIResponseParsingError):
        provider.generate_json("system", "user", max_retries=2)

    assert provider.call_count == 3  # percobaan awal + 2 retry


@patch("app.api.common.get_ai_provider", return_value=_FakeProvider())
@patch("app.services.analysis_jobs.analyze_chunks_batch")
def test_ai_error_di_satu_chunk_tidak_menggagalkan_seluruh_request(
    mock_analyze, _mock_provider, run_job, preview_id
):
    """Kombinasi skenario 7/8: error AI di satu batch tercatat di chunk_errors, job tetap sukses."""
    mock_analyze.side_effect = AIProviderError("simulasi Gemini down")

    job, data = run_job("POST", "/api/analyze", json={
        "preview_id": preview_id,
        "selected_chunk_indices": list(range(50)),
    })

    assert job["status"] == "succeeded", job
    assert data["total_ketentuan"] == 0
    assert len(data["chunk_errors"]) > 0
    assert all("simulasi Gemini down" in e["error"] for e in data["chunk_errors"])
