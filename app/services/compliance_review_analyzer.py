"""
Compliance Review Analyzer Service.

Menghubungkan prompt compliance_review_prompt.py dengan AI provider
untuk menganalisis klausul kontrak terhadap regulasi acuan.
"""

from app.prompts.compliance_review_prompt import (
    COMPLIANCE_SYSTEM_PROMPT,
    EXECUTIVE_SUMMARY_SYSTEM_PROMPT,
    build_compliance_user_prompt,
    build_executive_summary_prompt,
)
from app.services.ai_service import AIProvider


class ComplianceAnalysisError(Exception):
    """Raised jika response AI tidak berbentuk list atau error analisis."""


# =============================================================================
# MAIN ANALYSIS
# =============================================================================

def analyze_compliance(
    contract_chunks: list[dict],
    regulation_chunks: list[dict],
    provider: AIProvider,
) -> list[dict]:
    """
    Analisis compliance antara klausul kontrak vs regulasi acuan.

    Args:
        contract_chunks: hasil parse_contract_structure
        regulation_chunks: hasil parse_regulation_structure
        provider: AIProvider instance

    Returns:
        List of dict dengan 5 field: klausul_ref, klausul_text,
        regulasi_ref, status, analisis.

    Raises:
        ComplianceAnalysisError: kalau response tidak valid.
    """
    if not contract_chunks:
        return []

    user_prompt = build_compliance_user_prompt(
        contract_chunks=contract_chunks,
        regulation_chunks=regulation_chunks,
    )

    result = provider.generate_json(COMPLIANCE_SYSTEM_PROMPT, user_prompt)

    if not isinstance(result, list):
        raise ComplianceAnalysisError(
            f"Response AI harus JSON array, dapat: {type(result).__name__}"
        )

    return result


# =============================================================================
# EXECUTIVE SUMMARY
# =============================================================================

def generate_executive_summary(
    compliance_items: list[dict],
    provider: AIProvider,
) -> str:
    """
    Generate ringkasan eksekutif dari hasil compliance review.

    Return: string markdown ringan.
    """
    if not compliance_items:
        return ""

    user_prompt = build_executive_summary_prompt(compliance_items)

    # Executive summary tidak butuh JSON, jadi pakai generate_text
    try:
        summary = provider.generate_text(
            EXECUTIVE_SUMMARY_SYSTEM_PROMPT,
            user_prompt,
            expect_json=False,
        )
        return (summary or "").strip()
    except Exception as exc:
        # Summary optional — kalau gagal, tidak gagalkan seluruh proses
        return f"(Gagal generate ringkasan eksekutif: {exc})"


# =============================================================================
# POST-PROCESSING
# =============================================================================

# Kategori status valid
_VALID_STATUSES = {
    "PATUH",
    "PATUH DENGAN CATATAN",
    "TIDAK PATUH",
    "TIDAK RELEVAN",
}

# Normalisasi status (AI kadang menulis variant)
_STATUS_ALIASES = {
    "compliant": "PATUH",
    "patuh": "PATUH",
    "ok": "PATUH",
    "partially compliant": "PATUH DENGAN CATATAN",
    "patuh dengan catatan": "PATUH DENGAN CATATAN",
    "partial": "PATUH DENGAN CATATAN",
    "non-compliant": "TIDAK PATUH",
    "tidak patuh": "TIDAK PATUH",
    "noncompliant": "TIDAK PATUH",
    "tidak relevan": "TIDAK RELEVAN",
    "not relevant": "TIDAK RELEVAN",
    "n/a": "TIDAK RELEVAN",
}


def normalize_status(status: str) -> str:
    """Normalisasi status ke salah satu dari 4 kategori valid."""
    if not status:
        return "TIDAK RELEVAN"

    s = status.strip().upper()

    # Cek langsung
    if s in _VALID_STATUSES:
        return s

    # Cek alias
    s_lower = status.strip().lower()
    if s_lower in _STATUS_ALIASES:
        return _STATUS_ALIASES[s_lower]

    # Cek substring
    if "tidak patuh" in s_lower or "non-compliant" in s_lower:
        return "TIDAK PATUH"
    if "patuh dengan catatan" in s_lower or "partially" in s_lower:
        return "PATUH DENGAN CATATAN"
    if "relevan" in s_lower or "n/a" in s_lower:
        return "TIDAK RELEVAN"
    if "patuh" in s_lower:
        return "PATUH"

    return "TIDAK RELEVAN"


def normalize_compliance_items(raw_items: list) -> list[dict]:
    """
    Bersihkan & normalisasi item hasil AI:
    - Pastikan 5 field ada
    - Normalisasi status
    - Trim panjang teks
    """
    cleaned: list[dict] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        cleaned.append({
            "klausul_ref": str(item.get("klausul_ref", "")).strip()[:200],
            "klausul_text": str(item.get("klausul_text", "")).strip()[:500],
            "regulasi_ref": str(item.get("regulasi_ref", "")).strip()[:300],
            "status": normalize_status(item.get("status", "")),
            "analisis": str(item.get("analisis", "")).strip()[:1500],
        })

    return cleaned


def count_by_status(items: list[dict]) -> dict[str, int]:
    """Hitung jumlah per status."""
    counts = {
        "total_patuh": 0,
        "total_patuh_catatan": 0,
        "total_tidak_patuh": 0,
        "total_tidak_relevan": 0,
    }
    for item in items:
        s = item.get("status", "")
        if s == "PATUH":
            counts["total_patuh"] += 1
        elif s == "PATUH DENGAN CATATAN":
            counts["total_patuh_catatan"] += 1
        elif s == "TIDAK PATUH":
            counts["total_tidak_patuh"] += 1
        else:
            counts["total_tidak_relevan"] += 1
    return counts