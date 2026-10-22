"""
Phase 9 - Testing Menyeluruh: Filtering Ketentuan Non-TI.

Mencakup skenario testing wajib dari brief (section 17, Phase 9):
10. Requirement yang tidak relevan dengan audit TI
"""

from unittest.mock import patch

from app.services.ai_service import AIProvider
from app.services.audit_analyzer import analyze_chunk
from app.services.validator import validate_results


class _AlwaysNonRelevantProvider(AIProvider):
    """Mensimulasikan AI yang benar mengikuti instruksi: [] untuk ketentuan non-TI."""

    def generate_text(self, system_prompt, user_prompt, expect_json=False):
        return "[]"


def test_10_chunk_non_it_menghasilkan_list_kosong():
    chunk = {
        "bab": "BAB VII",
        "pasal": "Pasal 35",
        "ayat": "(1)",
        "text": "Pegawai berhak atas cuti tahunan paling sedikit 12 (dua belas) hari kerja.",
    }
    provider = _AlwaysNonRelevantProvider()

    result = analyze_chunk(chunk, provider)

    assert result == []


def test_10_validator_tidak_error_untuk_list_kosong():
    validated = validate_results([], source_text="teks apapun")
    assert validated == []


@patch("app.api.routes.get_ai_provider", return_value=_AlwaysNonRelevantProvider())
@patch("app.services.analysis_jobs.analyze_chunks_batch")
def test_10_seluruh_dokumen_non_relevan_tetap_sukses(mock_analyze, _mock_provider, run_job, preview_id):
    """
    Kasus realistis: dokumen yang diupload ternyata tidak mengandung ketentuan
    TI sama sekali. Job HARUS tetap sukses dengan total_ketentuan=0,
    BUKAN dianggap error.
    """
    mock_analyze.return_value = []

    job, data = run_job("POST", "/api/analyze", json={
        "preview_id": preview_id,
        "selected_chunk_indices": list(range(50)),
    })

    assert job["status"] == "succeeded", job
    assert data["total_ketentuan"] == 0
    assert data["total_valid"] == 0
    assert data["total_flagged"] == 0
    assert data["chunk_errors"] == []
