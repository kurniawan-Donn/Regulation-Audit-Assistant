"""
Route Tool 3 — Compliance Review: preview kontrak + regulasi, analisis
(mode upload / database, job), operasi baris, ringkasan eksekutif,
dan export.

PENTING: route statis (bulk, batch-add) dideklarasikan sebelum route
dinamis ({item_idx}).
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.models.schemas import (
    AddComplianceItemRequest,
    AnalyzeComplianceItemsRequest,
    BatchAddComplianceItemRequest,
    BulkUpdateComplianceRequest,
    ComplianceAnalyzeRequest,
    ComplianceBulkResponse,
    ComplianceItem,
    CompliancePreviewResponse,
    ComplianceResponse,
    DeleteComplianceItemsRequest,
    JobAcceptedResponse,
    ParseContractResponse,
    ParsedContractClause,
    UpdateComplianceItemRequest,
    UpdateExecutiveSummaryRequest,
)
from app.services.analysis_jobs import (
    COMPLIANCE_UNITS_PER_BATCH,
    make_compliance_items_worker,
    make_compliance_review_worker,
)
from app.services.compliance_exporter import (
    build_compliance_filename,
    build_markdown_table,
    export_compliance_to_excel,
)
from app.services.compliance_pdf_exporter import (
    build_compliance_pdf_filename,
    export_compliance_to_pdf,
)
from app.services.compliance_retrieval import DEFAULT_TOP_K, MAX_TOP_K
from app.services.compliance_review_analyzer import (
    STATUS_PERLU_VERIFIKASI,
    STATUS_TIDAK_RELEVAN,
    VALID_STATUSES,
    count_by_status,
    group_contract_units,
)
from app.services.contract_parser import parse_contract_structure
from app.services.json_store import read_json, write_json_atomic
from app.services.pdf_parser import PDFExtractionError
from app.services.preview_cache import (
    generate_preview_id,
)
from app.services.regulation_db import get_regulation
from app.services.regulation_parser import parse_regulation_structure
from app.services.text_processor import TextExtractionError, clean_text
from app.api.common import (
    COMPLIANCE_OUTPUT_DIR,
    COMPLIANCE_PREVIEW_DIR,
    ID_RE,
    ai_provider_or_422,
    embedder_or_422,
    extract_bytes,
    load_compliance_result,
    lock_compliance_result,
    read_upload,
    save_result_file,
    submit_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["compliance"])


# ===========================================================================
# COMPLIANCE REVIEW (Tool 3)
# ===========================================================================

def _load_compliance_preview(preview_id: str) -> dict | None:
    if not ID_RE.match(preview_id or ""):
        return None
    path = COMPLIANCE_PREVIEW_DIR / f"{preview_id}.json"
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def _save_compliance_preview(preview_id: str, data: dict) -> None:
    write_json_atomic(COMPLIANCE_PREVIEW_DIR / f"{preview_id}.json", data, indent=None)


# Batas jumlah unit klausul per analisis. Tidak lagi dipotong diam-diam:
# kalau terlampaui, auditor mendapat peringatan di hasil.
MAX_CONTRACT_UNITS = 150


def _prepare_contract_units(
    contract_chunks: list[dict], filter_text: str
) -> tuple[list[dict], list[str]]:
    """Chunk kontrak → unit review (per Pasal/Ayat), terapkan filter & batas."""
    units = group_contract_units(contract_chunks)
    if filter_text:
        needle = filter_text.lower()
        units = [
            u for u in units
            if needle in f"{u['judul']} {u['klausul_ref']} {u['text']}".lower()
        ]
        if not units:
            raise HTTPException(
                status_code=422,
                detail=f"Tidak ada klausul yang cocok dengan filter '{filter_text}'.",
            )
    if not units:
        raise HTTPException(status_code=422, detail="Tidak ada klausul kontrak untuk dianalisis.")

    warnings: list[str] = []
    if len(units) > MAX_CONTRACT_UNITS:
        warnings.append(
            f"Kontrak memiliki {len(units)} klausul; hanya {MAX_CONTRACT_UNITS} klausul "
            "pertama yang dianalisis. Gunakan filter kata kunci untuk menganalisis sisanya."
        )
        units = units[:MAX_CONTRACT_UNITS]
    return units, warnings


def _set_compliance_status(item: dict, status: str) -> None:
    """Status diubah auditor: kecuali PERLU VERIFIKASI, baris dianggap sudah ditinjau."""
    item["status"] = status
    item["needs_review"] = status == STATUS_PERLU_VERIFIKASI


def _compliance_job_total(units: list[dict]) -> int:
    return -(-len(units) // COMPLIANCE_UNITS_PER_BATCH) + 2


# ===========================================================================
# COMPLIANCE — PREVIEW (upload kontrak + N regulasi)
# ===========================================================================

@router.post("/compliance/preview", response_model=CompliancePreviewResponse)
async def compliance_preview(
    contract_file: UploadFile = File(...),
    regulation_files: list[UploadFile] = File(...),
) -> CompliancePreviewResponse:
    """
    Upload 1 kontrak + N file regulasi.
    Parse keduanya tanpa AI, simpan preview.
    """
    contract_bytes, contract_ext = await read_upload(contract_file, "Kontrak")

    if not regulation_files:
        raise HTTPException(status_code=422, detail="Minimal 1 regulasi acuan harus di-upload.")

    preview_id = generate_preview_id()

    try:
        raw_contract = await run_in_threadpool(extract_bytes, contract_bytes, contract_ext)
    except (PDFExtractionError, TextExtractionError) as exc:
        raise HTTPException(status_code=422, detail=f"Kontrak: {exc}") from exc

    contract_chunks = parse_contract_structure(raw_contract)
    if not contract_chunks:
        raise HTTPException(
            status_code=422,
            detail="Tidak ada klausul yang bisa di-parse dari kontrak.",
        )

    all_regulation_chunks: list[dict] = []
    reg_filenames: list[str] = []

    for reg_file in regulation_files:
        reg_bytes, reg_ext = await read_upload(
            reg_file, f"Regulasi '{reg_file.filename or 'tanpa nama'}'"
        )

        try:
            raw_reg = await run_in_threadpool(extract_bytes, reg_bytes, reg_ext)
        except (PDFExtractionError, TextExtractionError):
            continue

        cleaned_reg = clean_text(raw_reg)
        reg_chunks = await run_in_threadpool(parse_regulation_structure, cleaned_reg)

        for c in reg_chunks:
            c["source_file"] = reg_file.filename or "unknown"

        all_regulation_chunks.extend(reg_chunks)
        reg_filenames.append(reg_file.filename or "unknown")

    if not all_regulation_chunks:
        raise HTTPException(
            status_code=422,
            detail="Tidak ada regulasi yang berhasil di-parse.",
        )

    preview_data = {
        "preview_id": preview_id,
        "contract_filename": contract_file.filename or "kontrak",
        "regulation_filenames": reg_filenames,
        "contract_chunks": contract_chunks,
        "regulation_chunks": all_regulation_chunks,
    }
    _save_compliance_preview(preview_id, preview_data)

    tree_preview = [
        {
            "pasal": c.get("pasal"),
            "ayat": c.get("ayat"),
            "huruf": c.get("huruf"),
            "preview": c.get("text", "")[:80],
        }
        for c in contract_chunks[:100]
    ]

    return CompliancePreviewResponse(
        preview_id=preview_id,
        contract_filename=contract_file.filename or "kontrak",
        regulation_filenames=reg_filenames,
        total_contract_chunks=len(contract_chunks),
        total_regulation_chunks=len(all_regulation_chunks),
        contract_tree_preview=tree_preview,
    )


# ===========================================================================
# COMPLIANCE — ANALYZE
# ===========================================================================

@router.post("/compliance/analyze", response_model=JobAcceptedResponse, status_code=202)
async def compliance_analyze(payload: ComplianceAnalyzeRequest) -> JobAcceptedResponse:
    """Analisis compliance review: kontrak vs regulasi."""
    preview = _load_compliance_preview(payload.preview_id)
    if preview is None:
        raise HTTPException(
            status_code=404,
            detail="Preview tidak ditemukan. Silakan upload ulang.",
        )

    contract_chunks = preview.get("contract_chunks", [])
    regulation_chunks = preview.get("regulation_chunks", [])

    if not contract_chunks or not regulation_chunks:
        raise HTTPException(status_code=500, detail="Preview tidak lengkap.")

    filter_text = (payload.filter_kontrak or "").strip()
    units, warnings = _prepare_contract_units(contract_chunks, filter_text)
    provider, embedder = ai_provider_or_422(), embedder_or_422()

    worker = make_compliance_review_worker(
        units=units,
        retrieval={"mode": "upload", "preview_id": payload.preview_id, "top_k": DEFAULT_TOP_K},
        regulation_chunks=regulation_chunks,
        embedder=embedder,
        provider=provider,
        preview_id=payload.preview_id,
        contract_filename=preview.get("contract_filename", ""),
        regulation_filenames=preview.get("regulation_filenames", []),
        filter_text=filter_text,
        warnings=warnings,
    )
    return submit_job("compliance_review", worker, total=_compliance_job_total(units))


@router.post("/compliance/analyze-from-db", response_model=JobAcceptedResponse, status_code=202)
async def compliance_analyze_from_db(
    contract_file: UploadFile = File(...),
    regulation_ids: str = Form(..., description="Comma-separated regulation IDs"),
    nama_kontrak: str = Form(None),
    filter_kontrak: str = Form(None),
    top_k_per_clause: int = Form(DEFAULT_TOP_K, description="Jumlah regulasi relevan per klausul"),
) -> JobAcceptedResponse:
    """
    Compliance review dengan regulasi dari Database (RAG mode).

    - Contract di-upload manual
    - Regulasi diambil dari Regulation Database via semantic retrieval
    - Untuk setiap klausul kontrak, cari top-K regulasi paling relevan
    """
    # --- Validasi contract ---
    contract_bytes, contract_ext = await read_upload(contract_file, "Kontrak")

    # --- Parse regulation_ids ---
    reg_ids = [rid.strip() for rid in regulation_ids.split(",") if rid.strip()]
    if not reg_ids:
        raise HTTPException(status_code=422, detail="Pilih minimal 1 regulasi dari database.")

    # Validasi semua ID ada di DB
    valid_regs = []
    for rid in reg_ids:
        reg = get_regulation(rid)
        if reg:
            valid_regs.append(reg)
    if not valid_regs:
        raise HTTPException(
            status_code=404,
            detail="Regulasi yang dipilih tidak ditemukan di database.",
        )

    # --- Extract + parse contract ---
    try:
        raw_contract = await run_in_threadpool(extract_bytes, contract_bytes, contract_ext)
    except (PDFExtractionError, TextExtractionError) as exc:
        raise HTTPException(status_code=422, detail=f"Kontrak: {exc}") from exc

    contract_chunks = parse_contract_structure(raw_contract)
    if not contract_chunks:
        raise HTTPException(
            status_code=422,
            detail="Tidak ada klausul yang bisa di-parse dari kontrak.",
        )

    filter_text = (filter_kontrak or "").strip()
    units, warnings = _prepare_contract_units(contract_chunks, filter_text)
    provider, embedder = ai_provider_or_422(), embedder_or_422()

    worker = make_compliance_review_worker(
        units=units,
        retrieval={
            "mode": "database",
            "regulation_ids": [r["id"] for r in valid_regs],
            "top_k": max(1, min(top_k_per_clause, MAX_TOP_K)),
        },
        regulation_chunks=[],
        embedder=embedder,
        provider=provider,
        preview_id="",  # mode database tidak memakai preview
        contract_filename=contract_file.filename or "kontrak",
        regulation_filenames=[r.get("name", "") for r in valid_regs if r.get("name")],
        filter_text=filter_text,
        warnings=warnings,
    )
    return submit_job("compliance_review", worker, total=_compliance_job_total(units))

# ===========================================================================
# COMPLIANCE — PARSE CONTRACT (untuk import manual)
# ===========================================================================

@router.post("/compliance/parse-contract", response_model=ParseContractResponse)
async def parse_contract_for_import(file: UploadFile = File(...)) -> ParseContractResponse:
    """
    Parse PDF/TXT kontrak → list klausul untuk preview di modal import.
    TIDAK menyimpan hasil, hanya return list.
    """
    file_bytes, ext = await read_upload(file)

    try:
        raw_text = await run_in_threadpool(extract_bytes, file_bytes, ext)
    except (PDFExtractionError, TextExtractionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    chunks = parse_contract_structure(raw_text)

    clauses = []
    for c in chunks:
        ref_parts = [p for p in (c.get("pasal"), c.get("ayat"), c.get("huruf")) if p]
        klausul_ref = " ".join(ref_parts) if ref_parts else ""

        clauses.append(ParsedContractClause(
            pasal=c.get("pasal"),
            ayat=c.get("ayat"),
            huruf=c.get("huruf"),
            text=c.get("text", ""),
            klausul_ref=klausul_ref,
        ))

    return ParseContractResponse(
        filename=file.filename or "unknown",
        total_clauses=len(clauses),
        clauses=clauses,
    )


# ===========================================================================
# COMPLIANCE — GET RESULT
# ===========================================================================

@router.get("/compliance/{result_id}", response_model=ComplianceResponse)
async def get_compliance_result(result_id: str) -> ComplianceResponse:
    _, data = load_compliance_result(result_id)
    return ComplianceResponse(**data)


# ===========================================================================
# COMPLIANCE — ITEM OPERATIONS
# PENTING: route STATIS (bulk) HARUS dideklarasikan SEBELUM route DINAMIS ({item_idx})
# ===========================================================================

# ----- BULK UPDATE STATUS (statis) — DEKLARASI DULU -----

@router.patch(
    "/compliance/{result_id}/items/bulk",
    response_model=ComplianceBulkResponse,
)
async def bulk_update_compliance_items(
    result_id: str,
    payload: BulkUpdateComplianceRequest,
    _lock: None = Depends(lock_compliance_result),
) -> ComplianceBulkResponse:
    """Bulk update status untuk banyak item sekaligus."""
    path, data = load_compliance_result(result_id)
    items = data.get("items", [])
    total = len(items)

    if payload.status and payload.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Status '{payload.status}' tidak valid.",
        )

    affected = 0
    for idx in payload.item_indices:
        if 0 <= idx < total:
            if payload.status:
                _set_compliance_status(items[idx], payload.status)
            affected += 1

    data["items"] = items
    counts = count_by_status(items)
    data.update(counts)

    save_result_file(path, data)

    return ComplianceBulkResponse(
        affected=affected,
        total_items=len(items),
        total_patuh=counts["total_patuh"],
        total_patuh_catatan=counts["total_patuh_catatan"],
        total_tidak_patuh=counts["total_tidak_patuh"],
        total_tidak_relevan=counts["total_tidak_relevan"],
        total_perlu_verifikasi=counts["total_perlu_verifikasi"],
    )


# ----- BATCH-ADD (statis) — DEKLARASI DULU -----

@router.post(
    "/compliance/{result_id}/items/batch-add",
    response_model=ComplianceBulkResponse,
)
async def batch_add_compliance_items(
    result_id: str,
    payload: BatchAddComplianceItemRequest,
    _lock: None = Depends(lock_compliance_result),
) -> ComplianceBulkResponse:
    """
    Tambah banyak klausul sekaligus (untuk import dari PDF).
    Bisa insert di posisi tertentu atau append di akhir.
    """
    path, data = load_compliance_result(result_id)
    items = data.get("items", [])
    total = len(items)

    # Tentukan posisi insert
    insert_pos = total  # default: append di akhir
    if payload.insert_after is not None:
        try:
            insert_pos = max(0, min(int(payload.insert_after), total))
        except (ValueError, TypeError):
            insert_pos = total

    # Prepare items baru
    new_items: list[dict] = []
    for it in payload.items:
        new_items.append({
            "klausul_ref": it.klausul_ref or "",
            "klausul_text": it.klausul_text or "",
            "regulasi_ref": it.regulasi_ref or "",
            "status": it.status or STATUS_TIDAK_RELEVAN,
            "analisis": it.analisis or "",
        })

    # Insert di posisi
    items[insert_pos:insert_pos] = new_items
    data["items"] = items
    data["total_items"] = len(items)
    counts = count_by_status(items)
    data.update(counts)

    save_result_file(path, data)

    return ComplianceBulkResponse(
        affected=len(new_items),
        total_items=len(items),
        total_patuh=counts["total_patuh"],
        total_patuh_catatan=counts["total_patuh_catatan"],
        total_tidak_patuh=counts["total_tidak_patuh"],
        total_tidak_relevan=counts["total_tidak_relevan"],
        total_perlu_verifikasi=counts["total_perlu_verifikasi"],
    )


# ----- ADD SINGLE (statis) — DEKLARASI DULU -----

@router.post("/compliance/{result_id}/items", response_model=ComplianceItem)
async def add_compliance_item(
    result_id: str,
    payload: AddComplianceItemRequest,
    _lock: None = Depends(lock_compliance_result),
) -> ComplianceItem:
    """Tambah 1 klausul manual. Support insert_after untuk posisi spesifik."""
    path, data = load_compliance_result(result_id)
    items = data.get("items", [])
    total = len(items)

    new_item = {
        "klausul_ref": payload.klausul_ref or "",
        "klausul_text": payload.klausul_text or "",
        "regulasi_ref": payload.regulasi_ref or "",
        "status": payload.status or STATUS_TIDAK_RELEVAN,
        "analisis": payload.analisis or "",
    }

    # Insert di posisi tertentu atau append di akhir
    insert_pos = total
    if payload.insert_after is not None:
        try:
            insert_pos = max(0, min(int(payload.insert_after), total))
        except (ValueError, TypeError):
            insert_pos = total

    items.insert(insert_pos, new_item)
    data["items"] = items
    data["total_items"] = len(items)
    counts = count_by_status(items)
    data.update(counts)

    save_result_file(path, data)
    return ComplianceItem(**new_item)


# ----- UPDATE SINGLE (DINAMIS) — DEKLARASI SETELAH BULK -----

@router.patch(
    "/compliance/{result_id}/items/{item_idx}",
    response_model=ComplianceItem,
)
async def update_compliance_item(
    result_id: str,
    item_idx: int,
    payload: UpdateComplianceItemRequest,
    _lock: None = Depends(lock_compliance_result),
) -> ComplianceItem:
    """Update 1 item compliance."""
    path, data = load_compliance_result(result_id)
    items = data.get("items", [])

    if item_idx < 0 or item_idx >= len(items):
        raise HTTPException(status_code=404, detail=f"Item {item_idx} tidak ada.")

    update_data = payload.model_dump(exclude_unset=True)

    new_status = update_data.pop("status", None)
    if new_status:
        if new_status not in VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Status '{new_status}' tidak valid.",
            )
        _set_compliance_status(items[item_idx], new_status)

    items[item_idx].update(update_data)
    data["items"] = items

    counts = count_by_status(items)
    data.update(counts)

    save_result_file(path, data)
    return ComplianceItem(**items[item_idx])


# ----- DELETE (statis) -----

@router.delete(
    "/compliance/{result_id}/items",
    response_model=ComplianceBulkResponse,
)
async def delete_compliance_items(
    result_id: str,
    payload: DeleteComplianceItemsRequest,
    _lock: None = Depends(lock_compliance_result),
) -> ComplianceBulkResponse:
    """Hapus item terpilih."""
    path, data = load_compliance_result(result_id)
    items = data.get("items", [])
    total = len(items)

    indices = sorted(
        {i for i in payload.item_indices if 0 <= i < total},
        reverse=True,
    )
    if not indices:
        raise HTTPException(status_code=422, detail="Tidak ada index valid.")

    for idx in indices:
        items.pop(idx)

    data["items"] = items
    data["total_items"] = len(items)
    counts = count_by_status(items)
    data.update(counts)

    save_result_file(path, data)

    return ComplianceBulkResponse(
        affected=len(indices),
        total_items=len(items),
        total_patuh=counts["total_patuh"],
        total_patuh_catatan=counts["total_patuh_catatan"],
        total_tidak_patuh=counts["total_tidak_patuh"],
        total_tidak_relevan=counts["total_tidak_relevan"],
        total_perlu_verifikasi=counts["total_perlu_verifikasi"],
    )


# ===========================================================================
# COMPLIANCE — EXECUTIVE SUMMARY
# ===========================================================================

@router.patch(
    "/compliance/{result_id}/executive-summary",
    response_model=ComplianceResponse,
)
async def update_executive_summary(
    result_id: str,
    payload: UpdateExecutiveSummaryRequest,
    _lock: None = Depends(lock_compliance_result),
) -> ComplianceResponse:
    """Update ringkasan eksekutif."""
    path, data = load_compliance_result(result_id)
    data["executive_summary"] = payload.executive_summary or ""
    save_result_file(path, data)
    return ComplianceResponse(**data)

@router.post(
    "/compliance/{result_id}/analyze-items",
    response_model=JobAcceptedResponse,
    status_code=202,
)
async def analyze_compliance_items(
    result_id: str,
    payload: AnalyzeComplianceItemsRequest,
) -> JobAcceptedResponse:
    """
    Analisis AI untuk baris tertentu (biasanya klausul hasil import PDF).
    Memakai cara retrieval yang sama dengan analisis awal (result["retrieval"]):
    regulasi dari preview upload, atau dari Regulation Database.
    """
    path, data = load_compliance_result(result_id)
    items = data.get("items", [])
    if not items:
        raise HTTPException(status_code=422, detail="Tidak ada item di result ini.")

    retrieval = dict(data.get("retrieval") or {})
    if not retrieval and data.get("preview_id"):
        # Hasil lama (sebelum info retrieval disimpan) — selalu mode upload.
        retrieval = {"mode": "upload", "preview_id": data["preview_id"], "top_k": DEFAULT_TOP_K}

    regulation_chunks: list[dict] = []
    if retrieval.get("mode") == "upload":
        preview = _load_compliance_preview(retrieval.get("preview_id", ""))
        if preview is None:
            raise HTTPException(
                status_code=404,
                detail="Preview regulasi sudah kedaluwarsa. Silakan upload ulang kontrak & regulasi.",
            )
        regulation_chunks = preview.get("regulation_chunks", [])
        if not regulation_chunks:
            raise HTTPException(status_code=422, detail="Preview tidak memiliki regulasi.")
    elif retrieval.get("mode") == "database":
        if not any(get_regulation(rid) for rid in retrieval.get("regulation_ids", [])):
            raise HTTPException(
                status_code=404,
                detail="Regulasi acuan hasil ini sudah tidak ada di database.",
            )
    else:
        raise HTTPException(
            status_code=422,
            detail="Hasil ini tidak menyimpan sumber regulasinya. Jalankan ulang analisis dari awal.",
        )

    valid_indices = sorted({i for i in payload.item_indices if 0 <= i < len(items)})
    if not valid_indices:
        raise HTTPException(status_code=422, detail="Tidak ada index valid.")

    units = [
        {
            "klausul_ref": items[idx].get("klausul_ref", ""),
            "judul": "",
            "text": items[idx].get("klausul_text", "") or items[idx].get("klausul_ref", ""),
        }
        for idx in valid_indices
    ]
    provider, embedder = ai_provider_or_422(), embedder_or_422()

    worker = make_compliance_items_worker(
        result_path=path,
        result_id=result_id,
        item_indices=valid_indices,
        units=units,
        original_texts=[items[idx].get("klausul_text", "") for idx in valid_indices],
        retrieval=retrieval,
        regulation_chunks=regulation_chunks,
        embedder=embedder,
        provider=provider,
    )
    return submit_job("compliance_items", worker, total=_compliance_job_total(units) - 1)
# ===========================================================================
# COMPLIANCE — MARKDOWN & EXPORT
# ===========================================================================

@router.get("/compliance/{result_id}/markdown")
async def get_compliance_markdown(result_id: str) -> dict:
    """Return markdown table + executive summary untuk copy."""
    _, data = load_compliance_result(result_id)
    items = data.get("items", [])
    summary = data.get("executive_summary", "")

    markdown = build_markdown_table(items)
    full = f"{markdown}\n\n---\n\n## Ringkasan Eksekutif\n\n{summary}"

    return {
        "markdown": full,
        "table_markdown": markdown,
        "executive_summary": summary,
    }


@router.get("/compliance/export/{result_id}")
async def export_compliance(result_id: str) -> FileResponse:
    """Export compliance review ke Excel (2 sheet)."""
    _, data = load_compliance_result(result_id)
    items = data.get("items", [])
    if not items:
        raise HTTPException(status_code=422, detail="Tidak ada item untuk diekspor.")

    nama_kontrak = data.get("contract_filename", "kontrak")
    excel_filename = build_compliance_filename(Path(nama_kontrak).stem)
    excel_path = COMPLIANCE_OUTPUT_DIR / f"{result_id}.xlsx"

    await run_in_threadpool(
        export_compliance_to_excel,
        items=items,
        executive_summary=data.get("executive_summary", ""),
        output_path=str(excel_path),
    )

    return FileResponse(
        path=str(excel_path),
        filename=excel_filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

@router.get("/compliance/export-pdf/{result_id}")
async def export_compliance_pdf(result_id: str) -> FileResponse:
    """Export compliance review ke PDF."""
    _, data = load_compliance_result(result_id)
    items = data.get("items", [])
    if not items:
        raise HTTPException(status_code=422, detail="Tidak ada item untuk diekspor.")

    nama_kontrak = data.get("contract_filename", "kontrak")
    pdf_filename = build_compliance_pdf_filename(Path(nama_kontrak).stem)
    pdf_path = COMPLIANCE_OUTPUT_DIR / f"{result_id}.pdf"

    await run_in_threadpool(export_compliance_to_pdf,
        items=items,
        output_path=str(pdf_path),
        executive_summary=data.get("executive_summary", ""),
        nama_kontrak=nama_kontrak,
        regulation_filenames=data.get("regulation_filenames", []),
    )

    return FileResponse(
        path=str(pdf_path),
        filename=pdf_filename,
        media_type="application/pdf",
    )
