"""
Compliance Review Analyzer Service.

Alur (v2):
1. Kontrak → unit klausul (group_contract_units): chunk kontrak digabung
   per (Pasal, Ayat), sehingga butir "a) ..." direview bersama ayat induknya.
2. Tiap unit mendapat regulasi relevannya sendiri (lihat compliance_retrieval).
3. Unit direview per batch kecil (review_batch). Setiap unit diberi ID (K1..)
   dan setiap chunk regulasi diberi ID (R1..). AI wajib menjawab per
   klausul_id dan menyebut regulasi_ids yang dikutip, sehingga:
   - hasil dicocokkan berdasarkan ID, bukan urutan;
   - regulasi_ref disusun dari metadata chunk yang BENAR-BENAR dikutip
     (bukan teks karangan AI);
   - kutipan ke ID yang tidak diberikan terdeteksi sebagai halusinasi.
4. Apa pun yang tidak bisa dipastikan (status tak dikenal, klausul dilewati
   AI, batch gagal) menjadi status PERLU VERIFIKASI — tidak pernah
   disamarkan sebagai "TIDAK RELEVAN".
"""

from typing import Any

from app.prompts.compliance_review_prompt import (
    COMPLIANCE_SYSTEM_PROMPT,
    EXECUTIVE_SUMMARY_SYSTEM_PROMPT,
    build_compliance_batch_prompt,
    build_executive_summary_prompt,
    format_regulation_ref,
)
from app.services.ai_service import AIProvider


class ComplianceAnalysisError(Exception):
    """Raised jika response AI tidak berbentuk list atau error analisis."""


# =============================================================================
# STATUS
# =============================================================================

STATUS_PATUH = "PATUH"
STATUS_PATUH_CATATAN = "PATUH DENGAN CATATAN"
STATUS_TIDAK_PATUH = "TIDAK PATUH"
STATUS_TIDAK_RELEVAN = "TIDAK RELEVAN"
STATUS_PERLU_VERIFIKASI = "PERLU VERIFIKASI"

# Urutan ini dipakai juga untuk dropdown export Excel.
STATUS_OPTIONS = [
    STATUS_PATUH,
    STATUS_PATUH_CATATAN,
    STATUS_TIDAK_PATUH,
    STATUS_TIDAK_RELEVAN,
    STATUS_PERLU_VERIFIKASI,
]
VALID_STATUSES = set(STATUS_OPTIONS)

# Status yang berupa putusan substantif → wajib didukung kutipan regulasi.
_VERDICT_STATUSES = {STATUS_PATUH, STATUS_PATUH_CATATAN, STATUS_TIDAK_PATUH}

_STATUS_ALIASES = {
    "compliant": STATUS_PATUH,
    "patuh": STATUS_PATUH,
    "partially compliant": STATUS_PATUH_CATATAN,
    "patuh dengan catatan": STATUS_PATUH_CATATAN,
    "patuh dgn catatan": STATUS_PATUH_CATATAN,
    "partial": STATUS_PATUH_CATATAN,
    "non-compliant": STATUS_TIDAK_PATUH,
    "noncompliant": STATUS_TIDAK_PATUH,
    "tidak patuh": STATUS_TIDAK_PATUH,
    "tidak relevan": STATUS_TIDAK_RELEVAN,
    "not relevant": STATUS_TIDAK_RELEVAN,
    "n/a": STATUS_TIDAK_RELEVAN,
    "perlu verifikasi": STATUS_PERLU_VERIFIKASI,
}

KLAUSUL_TEXT_MAX = 1500
ANALISIS_MAX = 2500


def normalize_status(status: Any) -> str | None:
    """Normalisasi status AI ke salah satu status valid; None kalau tidak dikenali."""
    if not isinstance(status, str) or not status.strip():
        return None
    s = status.strip()
    if s.upper() in VALID_STATUSES:
        return s.upper()
    return _STATUS_ALIASES.get(s.lower())


def count_by_status(items: list[dict]) -> dict[str, int]:
    """Hitung jumlah per status."""
    counts = {
        "total_patuh": 0,
        "total_patuh_catatan": 0,
        "total_tidak_patuh": 0,
        "total_tidak_relevan": 0,
        "total_perlu_verifikasi": 0,
    }
    key_by_status = {
        STATUS_PATUH: "total_patuh",
        STATUS_PATUH_CATATAN: "total_patuh_catatan",
        STATUS_TIDAK_PATUH: "total_tidak_patuh",
        STATUS_TIDAK_RELEVAN: "total_tidak_relevan",
    }
    for item in items:
        key = key_by_status.get(item.get("status", ""), "total_perlu_verifikasi")
        counts[key] += 1
    return counts


# =============================================================================
# UNIT KLAUSUL
# =============================================================================

def contract_unit_ref(pasal: str | None, ayat: str | None) -> str:
    if not pasal:
        return "Pembukaan / Para Pihak"
    return f"{pasal} ayat {ayat}" if ayat else pasal


def group_contract_units(contract_chunks: list[dict]) -> list[dict]:
    """
    Gabungkan chunk kontrak yang berurutan dengan (pasal, ayat) sama menjadi
    satu unit review. Butir "a) ..." (field huruf) ikut unit ayat/pasal-nya.

    Return list unit: {klausul_ref, judul, text}.
    """
    units: list[dict] = []
    current_key: tuple | None = None
    for chunk in contract_chunks:
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        # Baris judul pasal ("KEWAJIBAN PIHAK KEDUA") yang tersimpan sebagai
        # chunk tersendiri bukan klausul — judulnya sudah ada di field judul.
        if text == (chunk.get("pasal_judul") or "").strip():
            continue
        key = (chunk.get("pasal"), chunk.get("ayat"))
        if units and key == current_key:
            units[-1]["text"] += "\n" + text
            continue
        current_key = key
        units.append({
            "klausul_ref": contract_unit_ref(*key),
            "judul": chunk.get("pasal_judul") or "",
            "text": text,
        })
    return units


# =============================================================================
# REVIEW PER BATCH
# =============================================================================

def _unverified_item(unit: dict, reason: str) -> dict:
    return {
        "klausul_ref": unit["klausul_ref"],
        "klausul_text": unit["text"][:KLAUSUL_TEXT_MAX],
        "regulasi_ref": "",
        "status": STATUS_PERLU_VERIFIKASI,
        "analisis": reason,
        "validation_notes": [reason],
        "needs_review": True,
    }


def unverified_items(units: list[dict], reason: str) -> list[dict]:
    """Item PERLU VERIFIKASI untuk unit yang tidak bisa dianalisis (gagal/dibatalkan)."""
    return [_unverified_item(u, reason) for u in units]


def assign_batch_ids(units: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """
    Beri ID K1.. untuk unit dan R1.. untuk chunk regulasi (dedup lintas unit
    dalam satu batch, berdasarkan chunk["key"]).

    Return (unit_entries, reg_by_id) dengan unit_entries:
        {"id": "K1", "unit": unit, "reg_ids": ["R1", "R3"]}
    """
    reg_by_id: dict[str, dict] = {}
    id_by_key: dict[str, str] = {}
    entries: list[dict] = []
    for i, unit in enumerate(units, start=1):
        reg_ids: list[str] = []
        for chunk in unit.get("regulations", []):
            key = chunk.get("key") or id(chunk)
            rid = id_by_key.get(key)
            if rid is None:
                rid = f"R{len(reg_by_id) + 1}"
                id_by_key[key] = rid
                reg_by_id[rid] = chunk
            reg_ids.append(rid)
        entries.append({"id": f"K{i}", "unit": unit, "reg_ids": reg_ids})
    return entries, reg_by_id


def review_batch(units: list[dict], provider: AIProvider) -> list[dict]:
    """
    Review satu batch unit (masing-masing sudah membawa `regulations`).

    Return satu item per unit, URUTAN SAMA dengan `units`.

    Raises:
        ComplianceAnalysisError / AIProviderError: kalau seluruh batch gagal
        (pemanggil mengubahnya menjadi item PERLU VERIFIKASI).
    """
    if not units:
        return []

    entries, reg_by_id = assign_batch_ids(units)
    user_prompt = build_compliance_batch_prompt(entries, reg_by_id)
    result = provider.generate_json(COMPLIANCE_SYSTEM_PROMPT, user_prompt)

    if not isinstance(result, list):
        raise ComplianceAnalysisError(
            f"Response AI harus JSON array, dapat: {type(result).__name__}"
        )

    by_klausul_id: dict[str, dict] = {}
    for raw in result:
        if not isinstance(raw, dict):
            continue
        kid = str(raw.get("klausul_id", "")).strip().upper()
        if kid and kid not in by_klausul_id:
            by_klausul_id[kid] = raw

    items: list[dict] = []
    for entry in entries:
        raw = by_klausul_id.get(entry["id"])
        if raw is None:
            items.append(_unverified_item(
                entry["unit"], "AI tidak mengembalikan hasil untuk klausul ini."
            ))
            continue
        items.append(_validate_review(raw, entry, reg_by_id))
    return items


def _validate_review(raw: dict, entry: dict, reg_by_id: dict[str, dict]) -> dict:
    unit = entry["unit"]
    notes: list[str] = []

    status = normalize_status(raw.get("status"))
    if status is None:
        notes.append(f"Status dari AI tidak dikenali: {raw.get('status')!r}.")
        status = STATUS_PERLU_VERIFIKASI

    cited_raw = raw.get("regulasi_ids") or []
    if isinstance(cited_raw, str):
        cited_raw = [cited_raw]
    offered = set(entry["reg_ids"])
    cited: list[str] = []
    invalid: list[str] = []
    for rid in cited_raw:
        rid = str(rid).strip().upper()
        if rid in offered and rid not in cited:
            cited.append(rid)
        elif rid and rid not in offered:
            invalid.append(rid)
    if invalid:
        notes.append(
            "AI mengutip regulasi yang tidak diberikan untuk klausul ini "
            f"({', '.join(invalid)}) — kemungkinan halusinasi."
        )

    if cited:
        regulasi_ref = "; ".join(format_regulation_ref(reg_by_id[r]) for r in cited)
    else:
        regulasi_ref = str(raw.get("regulasi_ref") or "").strip()[:300]
        if status in _VERDICT_STATUSES:
            notes.append(
                "Tidak ada kutipan regulasi yang valid untuk putusan ini — "
                "verifikasi referensi secara manual."
            )

    return {
        "klausul_ref": unit["klausul_ref"],
        # Kutipan klausul diambil dari dokumen, bukan dari tulisan ulang AI.
        "klausul_text": unit["text"][:KLAUSUL_TEXT_MAX],
        "regulasi_ref": regulasi_ref,
        "status": status,
        "analisis": str(raw.get("analisis") or "").strip()[:ANALISIS_MAX],
        "validation_notes": notes,
        "needs_review": bool(notes) or status == STATUS_PERLU_VERIFIKASI,
    }


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
