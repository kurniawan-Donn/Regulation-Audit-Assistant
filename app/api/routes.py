"""
API Routes — Regulation to Audit (Tool 1), Gap Analysis (Tool 2),
Compliance Review (Tool 3), Settings, Diagnostics, dan Search.

Catatan arsitektur:
- Analisis AI yang lama (analyze, analyze-requirements, compliance/*)
  TIDAK dijalankan di request: endpoint memvalidasi input lalu men-submit
  job (lihat services/job_manager.py) dan langsung membalas 202 + job_id.
- Pekerjaan sinkron yang berat (ekstraksi PDF, export) dijalankan lewat
  run_in_threadpool supaya event loop tidak terblokir.
- Semua file hasil ditulis atomik; endpoint read-modify-write memegang
  lock per file (dependency _lock_*), karena job background juga bisa
  menulis file yang sama.
- Urutan route statis (bulk, batch-add) dideklarasikan sebelum route
  dinamis ({item_idx}).
"""

import json
import logging
import re
import time
from collections import Counter
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.config import settings
from app.models.schemas import (
    AddComplianceItemRequest,
    AddItemRequest,
    AddRequirementRequest,
    AnalyzeComplianceItemsRequest,
    AnalyzeRequirementsRequest,
    AnalyzeRequirementsResponse,
    AnalyzeResponse,
    AnalyzeSelectedRequest,
    AuditResultItem,
    BatchAddComplianceItemRequest,
    BulkActionResponse,
    BulkUpdateComplianceRequest,
    BulkUpdateRequest,
    ComplianceAnalyzeRequest,
    ComplianceBulkResponse,
    ComplianceItem,
    CompliancePreviewResponse,
    ComplianceResponse,
    ConnectionTestRequest,
    ConnectionTestResponse,
    DeleteComplianceItemsRequest,
    DeleteItemsRequest,
    DeleteRequirementsRequest,
    DiagnosticsResponse,
    EstimateRequest,
    EstimateResponse,
    JobAcceptedResponse,
    ParseContractResponse,
    ParsedContractClause,
    PreviewResponse,
    PreviewRetrieveResponse,
    RequirementItem,
    RequirementsBulkActionResponse,
    RuntimeSettingsResponse,
    RuntimeSettingsUpdate,
    SearchResponse,
    SearchResultItem,
    UpdateComplianceItemRequest,
    UpdateExecutiveSummaryRequest,
    UpdateItemRequest,
    UpdateRequirementRequest,
)
from app.prompts.aspects import (
    STATUS_KEPATUHAN_DEFAULT,
    find_aspect_insensitive,
    find_method_insensitive,
    is_valid_status_kepatuhan,
)
from app.services.ai_service import GeminiProvider, get_ai_provider
from app.services.analysis_jobs import (
    make_audit_worker,
    make_compliance_db_worker,
    make_compliance_items_worker,
    make_compliance_worker,
    make_requirements_worker,
)
from app.services.chunk_batcher import create_batches
from app.services.compliance_exporter import (
    build_compliance_filename,
    build_markdown_table,
    export_compliance_to_excel,
)
from app.services.compliance_pdf_exporter import (
    build_compliance_pdf_filename,
    export_compliance_to_pdf,
)
from app.services.compliance_review_analyzer import count_by_status
from app.services.contract_parser import parse_contract_structure
from app.services.cost_estimator import estimate as estimate_cost
from app.services.embedding_service import EmbeddingService
from app.services.excel_exporter import build_export_filename, export_results_to_excel
from app.services.job_manager import Worker, get_job_manager
from app.services.json_store import locked, read_json, write_json_atomic
from app.services.pdf_exporter import build_pdf_filename, export_results_to_pdf
from app.services.pdf_parser import PDFExtractionError, extract_pdf_text
from app.services.preview_cache import (
    cleanup_expired,
    compute_file_hash,
    generate_preview_id,
    load_parsed_by_hash,
    load_preview,
    save_parsed_by_hash,
    save_preview,
)
from app.services.regulation_db import get_regulation
from app.services.regulation_parser import parse_regulation_structure
from app.services.requirements_exporter import (
    build_requirements_filename,
    export_requirements_to_excel,
)
from app.services.requirements_pdf_exporter import (
    build_requirements_pdf_filename,
    export_requirements_to_pdf,
)
from app.services.runtime_settings import (
    PRESET_MODELS,
    get_effective_settings,
    get_settings_masked,
)
from app.services.runtime_settings import update_settings as update_runtime_settings
from app.services.structure_tree import assign_node_ids, build_tree
from app.services.text_processor import TextExtractionError, clean_text, extract_txt_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["audit"])

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
REQUIREMENTS_OUTPUT_DIR = OUTPUT_DIR / "requirements"
COMPLIANCE_OUTPUT_DIR = OUTPUT_DIR / "compliance"
COMPLIANCE_PREVIEW_DIR = Path("cache/compliance_previews")
ALLOWED_EXTENSIONS = {".pdf", ".txt"}
MIN_CHUNK_LENGTH = 15

# Semua ID hasil/preview adalah uuid4().hex. Validasi ketat ini juga
# mencegah path traversal (mis. backslash ter-decode dari %5C di Windows).
_ID_RE = re.compile(r"^[0-9a-f]{32}$")


# ===========================================================================
# HELPERS
# ===========================================================================

def _result_path(directory: Path, result_id: str, not_found: str) -> Path:
    if not _ID_RE.match(result_id or ""):
        raise HTTPException(status_code=404, detail=not_found)
    return directory / f"{result_id}.json"


def _audit_path(result_id: str) -> Path:
    return _result_path(OUTPUT_DIR, result_id, "Hasil analisis tidak ditemukan.")


def _requirements_path(result_id: str) -> Path:
    return _result_path(
        REQUIREMENTS_OUTPUT_DIR, result_id, "Hasil gap analysis tidak ditemukan."
    )


def _compliance_path(result_id: str) -> Path:
    return _result_path(
        COMPLIANCE_OUTPUT_DIR, result_id, "Hasil compliance review tidak ditemukan."
    )


def _load_json_result(path: Path, not_found: str) -> tuple[Path, dict]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=not_found)
    try:
        data = read_json(path)
    except Exception as exc:
        logger.exception("Gagal membaca %s", path)
        raise HTTPException(status_code=500, detail="Gagal membaca file hasil.") from exc
    return path, data


def _load_result_file(result_id: str) -> tuple[Path, dict]:
    return _load_json_result(_audit_path(result_id), "Hasil analisis tidak ditemukan.")


def _load_requirements_file(result_id: str) -> tuple[Path, dict]:
    return _load_json_result(
        _requirements_path(result_id), "Hasil gap analysis tidak ditemukan."
    )


def _load_compliance_result(result_id: str) -> tuple[Path, dict]:
    return _load_json_result(
        _compliance_path(result_id), "Hasil compliance review tidak ditemukan."
    )


def _save_result_file(path: Path, data: dict) -> None:
    write_json_atomic(path, data)


# Dependency lock untuk endpoint read-modify-write. Dijalankan di event loop
# (async generator) supaya acquire & release terjadi di thread yang sama.
# Handler di event loop tidak saling interleave (body-nya tanpa await), jadi
# lock ini terutama menjaga dari penulisan oleh job background di thread lain.
async def _lock_audit_result(result_id: str) -> AsyncIterator[None]:
    with locked(_audit_path(result_id)):
        yield


async def _lock_requirements_result(result_id: str) -> AsyncIterator[None]:
    with locked(_requirements_path(result_id)):
        yield


async def _lock_compliance_result(result_id: str) -> AsyncIterator[None]:
    with locked(_compliance_path(result_id)):
        yield


def _submit_job(kind: str, worker: Worker, total: int) -> JobAcceptedResponse:
    rec = get_job_manager().submit(kind, worker, total=total)
    return JobAcceptedResponse(
        job_id=rec.job_id,
        kind=rec.kind,
        status=rec.status,
        status_url=f"/api/jobs/{rec.job_id}",
    )


def _extract_text(path: Path, extension: str) -> str:
    """Ekstraksi teks (sinkron, berat) — panggil lewat run_in_threadpool."""
    if extension == ".pdf":
        return extract_pdf_text(str(path))
    return extract_txt_text(str(path))


def _recompute_summary(data: dict) -> dict:
    results = data.get("results", [])
    total_valid = sum(1 for r in results if r.get("is_valid", True))
    data["total_ketentuan"] = len(results)
    data["total_valid"] = total_valid
    data["total_flagged"] = len(results) - total_valid
    data["total_by_aspect"] = dict(
        Counter(r.get("aspek", "") for r in results if r.get("aspek"))
    )
    return data


# ===========================================================================
# PREVIEW
# ===========================================================================

@router.post("/preview", response_model=PreviewResponse)
async def preview_regulation(file: UploadFile = File(...)) -> PreviewResponse:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format file tidak didukung: '{extension}'. Gunakan .pdf atau .txt.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File kosong.")

    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(file_bytes) > max_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Ukuran file melebihi batas {settings.max_upload_size_mb} MB.",
        )

    file_hash = compute_file_hash(file_bytes)
    cached = load_parsed_by_hash(file_hash)

    from_cache = False
    parse_time_ms = 0

    if cached is not None:
        cleaned_text: str = cached.get("cleaned_text", "")
        chunks: list[dict] = cached.get("chunks", [])
        tree: list[dict] = cached.get("tree", [])
        from_cache = True
        logger.info("Preview loaded from cache (hash=%s)", file_hash[:12])
    else:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        temp_name = generate_preview_id()
        saved_path = UPLOAD_DIR / f"{temp_name}{extension}"
        saved_path.write_bytes(file_bytes)

        start_ts = time.time()
        try:
            raw_text = await run_in_threadpool(_extract_text, saved_path, extension)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail=f"File tidak ditemukan: {exc}") from exc
        except (PDFExtractionError, TextExtractionError) as exc:
            saved_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        cleaned_text = clean_text(raw_text)
        chunks = await run_in_threadpool(parse_regulation_structure, cleaned_text)

        if not chunks:
            saved_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422,
                detail="Tidak ada teks yang bisa dianalisis dari dokumen ini.",
            )

        tree = build_tree(chunks)
        assign_node_ids(tree)

        parse_time_ms = int((time.time() - start_ts) * 1000)

        save_parsed_by_hash(
            file_hash=file_hash,
            filename=file.filename or "unknown",
            cleaned_text=cleaned_text,
            chunks=chunks,
            tree=tree,
        )
        logger.info("Preview parsed & cached (hash=%s, %d ms)", file_hash[:12], parse_time_ms)

    preview_id = generate_preview_id()
    save_preview(
        preview_id=preview_id,
        filename=file.filename or "unknown",
        cleaned_text=cleaned_text,
        chunks=chunks,
        tree=tree,
    )

    return PreviewResponse(
        preview_id=preview_id,
        filename=file.filename or "unknown",
        total_chunks=len(chunks),
        tree=tree,
        from_cache=from_cache,
        parse_time_ms=parse_time_ms,
    )


@router.get("/preview/{preview_id}", response_model=PreviewRetrieveResponse)
async def get_preview(preview_id: str) -> PreviewRetrieveResponse:
    preview = load_preview(preview_id)
    if preview is None:
        raise HTTPException(
            status_code=404,
            detail="Preview tidak ditemukan atau sudah kedaluwarsa (>24 jam). "
                   "Silakan upload ulang file.",
        )
    return PreviewRetrieveResponse(
        preview_id=preview_id,
        filename=preview.get("filename", "unknown"),
        total_chunks=len(preview.get("chunks", [])),
        tree=preview.get("tree", []),
    )


@router.post("/estimate", response_model=EstimateResponse)
async def estimate_cost_endpoint(payload: EstimateRequest) -> EstimateResponse:
    preview = load_preview(payload.preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Preview tidak ditemukan atau sudah kedaluwarsa.")

    all_chunks = preview.get("chunks", [])
    valid_indices = [i for i in payload.selected_chunk_indices if 0 <= i < len(all_chunks)]
    selected = [all_chunks[i] for i in valid_indices]
    selected = [c for c in selected if len(c.get("text", "").strip()) >= MIN_CHUNK_LENGTH]

    est = estimate_cost(selected)
    return EstimateResponse(
        total_chunks=est.total_chunks,
        total_chars=est.total_chars,
        estimated_batches=est.estimated_batches,
        input_tokens=est.input_tokens,
        output_tokens=est.output_tokens,
        total_tokens=est.total_tokens,
        cost_usd=est.cost_usd,
        cost_idr=est.cost_idr,
        time_seconds_estimate=est.time_seconds_estimate,
        model_name=est.model_name,
    )


# ===========================================================================
# ANALYZE (Tool 1)
# ===========================================================================

@router.post("/analyze", response_model=JobAcceptedResponse, status_code=202)
async def analyze_regulation(payload: AnalyzeSelectedRequest) -> JobAcceptedResponse:
    preview = load_preview(payload.preview_id)
    if preview is None:
        raise HTTPException(
            status_code=404,
            detail="Preview tidak ditemukan atau sudah kedaluwarsa. Silakan upload ulang.",
        )

    all_chunks: list[dict] = preview.get("chunks", [])
    cleaned_text: str = preview.get("cleaned_text", "")
    filename: str = preview.get("filename", "unknown")

    if not all_chunks:
        raise HTTPException(status_code=500, detail="Preview tidak memiliki chunk.")

    valid_indices = [i for i in payload.selected_chunk_indices if 0 <= i < len(all_chunks)]
    if not valid_indices:
        raise HTTPException(
            status_code=422,
            detail="Tidak ada chunk valid yang dipilih. Pastikan filter diisi.",
        )

    filtered_chunks = [all_chunks[i] for i in valid_indices]
    relevant_chunks = [c for c in filtered_chunks if len(c["text"].strip()) >= MIN_CHUNK_LENGTH]
    if not relevant_chunks:
        raise HTTPException(
            status_code=422,
            detail="Chunk yang dipilih terlalu pendek untuk dianalisis.",
        )

    runtime = get_effective_settings()
    max_chars_per_batch = int(runtime.get("max_chars_per_batch", 6000))
    batches = create_batches(relevant_chunks, max_chars_per_batch=max_chars_per_batch)

    try:
        provider = get_ai_provider()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    referensi_regulasi = (
        payload.nama_regulasi.strip()
        if payload.nama_regulasi and payload.nama_regulasi.strip()
        else Path(filename).stem
    )

    worker = make_audit_worker(
        preview_id=payload.preview_id,
        filename=filename,
        cleaned_text=cleaned_text,
        relevant_chunks=relevant_chunks,
        total_chunks_available=len(all_chunks),
        batches=batches,
        provider=provider,
        referensi_regulasi=referensi_regulasi,
        selected_labels=list(payload.selected_labels),
    )
    return _submit_job("regulation_audit", worker, total=len(batches))


# ===========================================================================
# RESULT ITEM OPERATIONS (Tool 1)
# ===========================================================================

@router.get("/results/{result_id}", response_model=AnalyzeResponse)
async def get_results(result_id: str) -> AnalyzeResponse:
    _, data = _load_result_file(result_id)
    return AnalyzeResponse(**data)


# ----- BULK (statis) — DEKLARASI DULU -----

@router.patch("/results/{result_id}/items/bulk", response_model=BulkActionResponse)
async def bulk_update_items(
    result_id: str, payload: BulkUpdateRequest,
    _lock: None = Depends(_lock_audit_result),
) -> BulkActionResponse:
    path, data = _load_result_file(result_id)
    results = data.get("results", [])
    total = len(results)

    if payload.status_kepatuhan is not None and not is_valid_status_kepatuhan(
        payload.status_kepatuhan
    ):
        raise HTTPException(
            status_code=422,
            detail=f"Status '{payload.status_kepatuhan}' tidak dikenali.",
        )

    updates: dict = {}
    if payload.status_kepatuhan is not None:
        updates["status_kepatuhan"] = payload.status_kepatuhan
    if payload.catatan_temuan is not None:
        updates["catatan_temuan"] = payload.catatan_temuan

    if not updates:
        raise HTTPException(status_code=422, detail="Tidak ada field yang di-update.")

    affected = 0
    for idx in payload.item_indices:
        if 0 <= idx < total:
            results[idx].update(updates)
            affected += 1

    data["results"] = results
    _recompute_summary(data)
    _save_result_file(path, data)

    return BulkActionResponse(
        affected=affected,
        total_ketentuan=data["total_ketentuan"],
        total_valid=data["total_valid"],
        total_flagged=data["total_flagged"],
        total_by_aspect=data["total_by_aspect"],
    )


# ----- SINGLE (dinamis) — DEKLARASI SETELAH BULK -----

@router.patch("/results/{result_id}/items/{item_idx}", response_model=AuditResultItem)
async def update_result_item(
    result_id: str, item_idx: int, payload: UpdateItemRequest,
    _lock: None = Depends(_lock_audit_result),
) -> AuditResultItem:
    path, data = _load_result_file(result_id)
    results = data.get("results", [])

    if item_idx < 0 or item_idx >= len(results):
        raise HTTPException(
            status_code=404,
            detail=f"Item index {item_idx} tidak ada (jumlah: {len(results)}).",
        )

    item = results[item_idx]
    update_data = payload.model_dump(exclude_unset=True)

    if update_data.get("aspek"):
        canonical = find_aspect_insensitive(update_data["aspek"])
        if canonical is None:
            raise HTTPException(
                status_code=422,
                detail=f"Aspek '{update_data['aspek']}' tidak ada di daftar aspek resmi.",
            )
        update_data["aspek"] = canonical

    if update_data.get("metode_audit"):
        canonical = find_method_insensitive(update_data["metode_audit"])
        if canonical is None:
            raise HTTPException(
                status_code=422,
                detail=f"Metode '{update_data['metode_audit']}' tidak ada di daftar metode resmi.",
            )
        update_data["metode_audit"] = canonical

    if update_data.get("status_kepatuhan") and not is_valid_status_kepatuhan(
        update_data["status_kepatuhan"]
    ):
        raise HTTPException(
            status_code=422,
            detail=f"Status '{update_data['status_kepatuhan']}' tidak dikenali.",
        )

    item.update(update_data)
    results[item_idx] = item
    data["results"] = results
    _recompute_summary(data)
    _save_result_file(path, data)
    return AuditResultItem(**item)


@router.post("/results/{result_id}/items", response_model=AuditResultItem)
async def add_result_item(
    result_id: str, payload: AddItemRequest,
    _lock: None = Depends(_lock_audit_result),
) -> AuditResultItem:
    path, data = _load_result_file(result_id)
    results = data.get("results", [])

    status = payload.status_kepatuhan or STATUS_KEPATUHAN_DEFAULT
    if not is_valid_status_kepatuhan(status):
        raise HTTPException(status_code=422, detail=f"Status '{status}' tidak dikenali.")

    new_item = {
        "referensi_regulasi": payload.referensi_regulasi or "",
        "aspek": payload.aspek or "",
        "bab_pasal_ayat": payload.bab_pasal_ayat or "",
        "point_ketentuan": payload.point_ketentuan or "",
        "pemeriksaan": payload.pemeriksaan or "",
        "metode_audit": payload.metode_audit or "",
        "kebutuhan_bukti": payload.kebutuhan_bukti or "",
        "status_kepatuhan": status,
        "catatan_temuan": payload.catatan_temuan or "",
        "is_valid": True,
        "validation_notes": ["Baris ditambahkan manual oleh auditor"],
    }

    results.append(new_item)
    data["results"] = results
    _recompute_summary(data)
    _save_result_file(path, data)
    return AuditResultItem(**new_item)


@router.delete("/results/{result_id}/items", response_model=BulkActionResponse)
async def delete_result_items(
    result_id: str, payload: DeleteItemsRequest,
    _lock: None = Depends(_lock_audit_result),
) -> BulkActionResponse:
    path, data = _load_result_file(result_id)
    results = data.get("results", [])
    total = len(results)

    indices = sorted(
        {i for i in payload.item_indices if 0 <= i < total},
        reverse=True,
    )
    if not indices:
        raise HTTPException(status_code=422, detail="Tidak ada index valid untuk dihapus.")

    for idx in indices:
        results.pop(idx)

    data["results"] = results
    _recompute_summary(data)
    _save_result_file(path, data)

    return BulkActionResponse(
        affected=len(indices),
        total_ketentuan=data["total_ketentuan"],
        total_valid=data["total_valid"],
        total_flagged=data["total_flagged"],
        total_by_aspect=data["total_by_aspect"],
    )


@router.get("/export/{result_id}")
async def export_to_excel(result_id: str) -> FileResponse:
    _, data = _load_result_file(result_id)
    results = data.get("results", [])
    if not results:
        raise HTTPException(status_code=422, detail="Tidak ada hasil untuk diekspor.")

    referensi_regulasi = (
        results[0].get("referensi_regulasi")
        or Path(data.get("filename", "regulasi")).stem
    )
    excel_filename = build_export_filename(referensi_regulasi)
    excel_path = OUTPUT_DIR / f"{result_id}.xlsx"

    await run_in_threadpool(export_results_to_excel, results, str(excel_path))

    return FileResponse(
        path=str(excel_path),
        filename=excel_filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/export-pdf/{result_id}")
async def export_to_pdf(result_id: str) -> FileResponse:
    _, data = _load_result_file(result_id)
    results = data.get("results", [])
    if not results:
        raise HTTPException(status_code=422, detail="Tidak ada hasil untuk diekspor.")

    referensi_regulasi = (
        results[0].get("referensi_regulasi")
        or Path(data.get("filename", "regulasi")).stem
    )
    pdf_filename = build_pdf_filename(referensi_regulasi)
    pdf_path = OUTPUT_DIR / f"{result_id}.pdf"

    await run_in_threadpool(export_results_to_pdf,
        results=results,
        output_path=str(pdf_path),
        referensi_regulasi=referensi_regulasi,
        filename=data.get("filename", ""),
    )

    return FileResponse(
        path=str(pdf_path),
        filename=pdf_filename,
        media_type="application/pdf",
    )


# ===========================================================================
# GAP ANALYSIS (Tool 2)
# ===========================================================================

@router.post("/analyze-requirements", response_model=JobAcceptedResponse, status_code=202)
async def analyze_requirements(
    payload: AnalyzeRequirementsRequest,
) -> JobAcceptedResponse:
    preview = load_preview(payload.preview_id)
    if preview is None:
        raise HTTPException(
            status_code=404,
            detail="Preview tidak ditemukan atau sudah kedaluwarsa. Silakan upload ulang.",
        )

    all_chunks: list[dict] = preview.get("chunks", [])
    filename: str = preview.get("filename", "unknown")

    if not all_chunks:
        raise HTTPException(status_code=500, detail="Preview tidak memiliki chunk.")

    filter_text = (payload.filter_text or "").strip()
    if filter_text:
        needle = filter_text.lower()
        selected_chunks = [
            c for c in all_chunks
            if needle in c.get("text", "").lower()
            or needle in " ".join(filter(None, [
                c.get("lampiran"), c.get("bab"), c.get("bagian"),
                c.get("pasal"), c.get("ayat"), c.get("butir"),
            ])).lower()
        ]
    else:
        selected_chunks = all_chunks

    selected_chunks = [
        c for c in selected_chunks
        if len(c.get("text", "").strip()) >= MIN_CHUNK_LENGTH
    ]

    if not selected_chunks:
        raise HTTPException(
            status_code=422,
            detail=(
                "Tidak ada chunk yang cocok dengan filter. "
                "Coba ubah kata kunci atau kosongkan filter."
            ),
        )

    runtime = get_effective_settings()
    max_chars_per_batch = int(runtime.get("max_chars_per_batch", 6000))
    batches = create_batches(selected_chunks, max_chars_per_batch=max_chars_per_batch)

    try:
        provider = get_ai_provider()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    referensi_regulasi = (
        payload.nama_regulasi.strip()
        if payload.nama_regulasi and payload.nama_regulasi.strip()
        else Path(filename).stem
    )

    worker = make_requirements_worker(
        preview_id=payload.preview_id,
        filename=filename,
        selected_chunks=selected_chunks,
        total_chunks_available=len(all_chunks),
        batches=batches,
        provider=provider,
        referensi_regulasi=referensi_regulasi,
        filter_text=filter_text,
    )
    return _submit_job("gap_analysis", worker, total=len(batches))


@router.get("/requirements/{result_id}", response_model=AnalyzeRequirementsResponse)
async def get_requirements(result_id: str) -> AnalyzeRequirementsResponse:
    _, data = _load_requirements_file(result_id)
    return AnalyzeRequirementsResponse(**data)


# ----- BULK (statis) — DEKLARASI DULU -----

@router.patch(
    "/requirements/{result_id}/items/bulk",
    response_model=RequirementsBulkActionResponse,
)
async def bulk_update_requirements(
    result_id: str, payload: BulkUpdateRequest,
    _lock: None = Depends(_lock_requirements_result),
) -> RequirementsBulkActionResponse:
    path, data = _load_requirements_file(result_id)
    items = data.get("requirements", [])
    total = len(items)

    updates: dict = {}
    if payload.status_kepatuhan is not None:
        updates["status_gap"] = payload.status_kepatuhan
    if payload.catatan_temuan is not None:
        updates["catatan"] = payload.catatan_temuan

    if not updates:
        raise HTTPException(status_code=422, detail="Tidak ada field yang di-update.")

    affected = 0
    for idx in payload.item_indices:
        if 0 <= idx < total:
            items[idx].update(updates)
            affected += 1

    data["requirements"] = items
    _save_result_file(path, data)

    return RequirementsBulkActionResponse(
        affected=affected,
        total_requirements=len(items),
    )


# ----- SINGLE (dinamis) — DEKLARASI SETELAH BULK -----

@router.patch(
    "/requirements/{result_id}/items/{item_idx}",
    response_model=RequirementItem,
)
async def update_requirement_item(
    result_id: str, item_idx: int, payload: UpdateRequirementRequest,
    _lock: None = Depends(_lock_requirements_result),
) -> RequirementItem:
    path, data = _load_requirements_file(result_id)
    items = data.get("requirements", [])

    if item_idx < 0 or item_idx >= len(items):
        raise HTTPException(
            status_code=404,
            detail=f"Item index {item_idx} tidak ada (jumlah: {len(items)}).",
        )

    update_data = payload.model_dump(exclude_unset=True)
    items[item_idx].update(update_data)
    data["requirements"] = items
    _save_result_file(path, data)
    return RequirementItem(**items[item_idx])


@router.post(
    "/requirements/{result_id}/items",
    response_model=RequirementItem,
)
async def add_requirement_item(
    result_id: str, payload: AddRequirementRequest,
    _lock: None = Depends(_lock_requirements_result),
) -> RequirementItem:
    path, data = _load_requirements_file(result_id)
    items = data.get("requirements", [])

    new_item = {
        "persyaratan": payload.persyaratan or "",
        "referensi": payload.referensi or "",
        "catatan": payload.catatan or "",
        "status_gap": payload.status_gap or "",
    }
    items.append(new_item)
    data["requirements"] = items
    data["total_requirements"] = len(items)
    _save_result_file(path, data)
    return RequirementItem(**new_item)


@router.delete(
    "/requirements/{result_id}/items",
    response_model=RequirementsBulkActionResponse,
)
async def delete_requirement_items(
    result_id: str, payload: DeleteRequirementsRequest,
    _lock: None = Depends(_lock_requirements_result),
) -> RequirementsBulkActionResponse:
    path, data = _load_requirements_file(result_id)
    items = data.get("requirements", [])
    total = len(items)

    indices = sorted(
        {i for i in payload.item_indices if 0 <= i < total},
        reverse=True,
    )
    if not indices:
        raise HTTPException(status_code=422, detail="Tidak ada index valid untuk dihapus.")

    for idx in indices:
        items.pop(idx)

    data["requirements"] = items
    data["total_requirements"] = len(items)
    _save_result_file(path, data)

    return RequirementsBulkActionResponse(
        affected=len(indices),
        total_requirements=len(items),
    )


@router.get("/export-requirements/{result_id}")
async def export_requirements(result_id: str) -> FileResponse:
    _, data = _load_requirements_file(result_id)
    items = data.get("requirements", [])
    if not items:
        raise HTTPException(status_code=422, detail="Tidak ada persyaratan untuk diekspor.")

    nama_file = Path(data.get("filename", "regulasi")).stem
    excel_filename = build_requirements_filename(nama_file)
    excel_path = REQUIREMENTS_OUTPUT_DIR / f"{result_id}.xlsx"

    await run_in_threadpool(export_requirements_to_excel, items, str(excel_path))

    return FileResponse(
        path=str(excel_path),
        filename=excel_filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

@router.get("/export-requirements-pdf/{result_id}")
async def export_requirements_to_pdf_endpoint(result_id: str) -> FileResponse:
    """Export gap analysis ke PDF."""
    _, data = _load_requirements_file(result_id)
    items = data.get("requirements", [])
    if not items:
        raise HTTPException(status_code=422, detail="Tidak ada persyaratan untuk diekspor.")

    referensi = ""
    if items:
        referensi = items[0].get("referensi", "") or ""
    if not referensi:
        referensi = Path(data.get("filename", "regulasi")).stem

    pdf_filename = build_requirements_pdf_filename(referensi)
    pdf_path = REQUIREMENTS_OUTPUT_DIR / f"{result_id}.pdf"

    await run_in_threadpool(export_requirements_to_pdf,
        items=items,
        output_path=str(pdf_path),
        referensi_regulasi=referensi,
        filename=data.get("filename", ""),
    )

    return FileResponse(
        path=str(pdf_path),
        filename=pdf_filename,
        media_type="application/pdf",
    )


# ===========================================================================
# SETTINGS
# ===========================================================================

@router.get("/settings", response_model=RuntimeSettingsResponse)
async def get_runtime_settings_endpoint() -> RuntimeSettingsResponse:
    data = get_settings_masked()
    return RuntimeSettingsResponse(
        gemini_api_key_masked=data.get("gemini_api_key_masked", ""),
        gemini_api_key_set=bool(data.get("gemini_api_key_set", False)),
        gemini_model=str(data.get("gemini_model", "")),
        gemini_max_output_tokens=int(data.get("gemini_max_output_tokens", 8192)),
        gemini_min_seconds_between_requests=float(
            data.get("gemini_min_seconds_between_requests", 4.5)
        ),
        max_chars_per_batch=int(data.get("max_chars_per_batch", 6000)),
        theme=str(data.get("theme", "auto")),
        preset_models=list(PRESET_MODELS),
    )


@router.put("/settings", response_model=RuntimeSettingsResponse)
async def update_runtime_settings_endpoint(
    payload: RuntimeSettingsUpdate,
) -> RuntimeSettingsResponse:
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    update_runtime_settings(updates)
    return await get_runtime_settings_endpoint()


@router.post("/settings/test-connection", response_model=ConnectionTestResponse)
async def test_connection(payload: ConnectionTestRequest) -> ConnectionTestResponse:
    runtime = get_effective_settings()
    api_key = (payload.api_key or "").strip() or runtime.get("gemini_api_key", "")
    model = (payload.model or "").strip() or runtime.get("gemini_model", "")

    if not api_key:
        return ConnectionTestResponse(
            ok=False, message="API key belum diisi.",
            model_tested=model or "-", latency_ms=0,
        )
    if not model:
        return ConnectionTestResponse(
            ok=False, message="Model belum dipilih.",
            model_tested="-", latency_ms=0,
        )

    def _ping() -> str:
        # Provider sendiri (client terisolasi) — tidak mengganggu job yang sedang jalan.
        provider = GeminiProvider(
            api_key=api_key,
            model_name=model,
            timeout_seconds=30,
            max_network_retries=0,
            max_output_tokens=1024,
            min_seconds_between_requests=0,
        )
        return provider.generate_text("", "Balas dengan satu kata: OK").strip()

    start = time.time()
    try:
        text = await run_in_threadpool(_ping)
        latency = int((time.time() - start) * 1000)
        return ConnectionTestResponse(
            ok=True,
            message=f"Koneksi berhasil. Response: '{text[:60]}'",
            model_tested=model,
            latency_ms=latency,
        )
    except Exception as exc:
        latency = int((time.time() - start) * 1000)
        return ConnectionTestResponse(
            ok=False,
            message=f"Gagal: {str(exc)[:300]}",
            model_tested=model,
            latency_ms=latency,
        )


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def get_diagnostics() -> DiagnosticsResponse:
    from app.config import settings as app_settings
    from app.services.preview_cache import get_parsed_cache_stats

    previews_dir = Path("cache/previews")
    previews_count = 0
    cache_size = 0
    if previews_dir.exists():
        for f in previews_dir.glob("*.json"):
            previews_count += 1
            try:
                cache_size += f.stat().st_size
            except Exception:
                pass

    outputs_count = 0
    if OUTPUT_DIR.exists():
        outputs_count = len(list(OUTPUT_DIR.glob("*.json")))

    parsed_stats = get_parsed_cache_stats()

    runtime = get_effective_settings()
    ai_ok = bool(runtime.get("gemini_api_key", "").strip())
    ai_message = "API key tersedia." if ai_ok else "API key belum diisi."

    return DiagnosticsResponse(
        server_ok=True,
        ai_ok=ai_ok,
        ai_message=ai_message,
        model_name=runtime.get("gemini_model", "-"),
        cache_previews_count=previews_count,
        cache_size_mb=round(cache_size / (1024 * 1024), 2),
        outputs_count=outputs_count,
        app_version="1.0.0",
        app_env=app_settings.app_env,
    )


# ===========================================================================
# SEARCH GLOBAL
# ===========================================================================

def _extract_snippet(text: str, query: str, radius: int = 60) -> str:
    if not text:
        return ""
    lowered = text.lower()
    q_lower = query.lower()
    pos = lowered.find(q_lower)
    if pos < 0:
        return text[:radius * 2] + ("..." if len(text) > radius * 2 else "")

    start = max(0, pos - radius)
    end = min(len(text), pos + len(query) + radius)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def _search_in_file(path: Path, query: str, source: str, date_min_ts: float | None) -> list[dict]:
    if not path.exists():
        return []

    if date_min_ts is not None:
        try:
            if path.stat().st_mtime < date_min_ts:
                return []
        except Exception:
            pass

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    result_id = path.stem
    filename = data.get("filename", "unknown")
    try:
        created_iso = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except Exception:
        created_iso = ""

    q_lower = query.lower()
    matches: list[dict] = []

    if source == "regulation_audit":
        items = data.get("results", [])
        for idx, item in enumerate(items):
            searchable = " ".join([
                item.get("referensi_regulasi", ""),
                item.get("aspek", ""),
                item.get("bab_pasal_ayat", ""),
                item.get("point_ketentuan", ""),
                item.get("pemeriksaan", ""),
                item.get("metode_audit", ""),
                item.get("kebutuhan_bukti", ""),
                item.get("catatan_temuan", ""),
            ]).lower()

            if q_lower not in searchable:
                continue

            title_field = item.get("point_ketentuan", "") or item.get("pemeriksaan", "")
            snippet = _extract_snippet(title_field, query)

            matches.append({
                "source": source,
                "result_id": result_id,
                "filename": filename,
                "item_index": idx,
                "title": (item.get("point_ketentuan", "")[:150] or "(tanpa judul)"),
                "snippet": snippet,
                "referensi": item.get("bab_pasal_ayat", ""),
                "aspek": item.get("aspek", ""),
                "status": item.get("status_kepatuhan", ""),
                "created_at": created_iso,
                "raw_item": item,
            })

    elif source == "gap_analysis":
        items = data.get("requirements", [])
        for idx, item in enumerate(items):
            searchable = " ".join([
                item.get("persyaratan", ""),
                item.get("referensi", ""),
                item.get("catatan", ""),
            ]).lower()

            if q_lower not in searchable:
                continue

            title_field = item.get("persyaratan", "")
            snippet = _extract_snippet(title_field, query)

            matches.append({
                "source": source,
                "result_id": result_id,
                "filename": filename,
                "item_index": idx,
                "title": (item.get("persyaratan", "")[:150] or "(tanpa judul)"),
                "snippet": snippet,
                "referensi": item.get("referensi", ""),
                "aspek": "",
                "status": item.get("status_gap", ""),
                "created_at": created_iso,
                "raw_item": item,
            })

    return matches


@router.get("/search", response_model=SearchResponse)
async def search_global(
    q: str = Query(..., min_length=2),
    tools: str = Query("all"),
    days: int | None = Query(None, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
) -> SearchResponse:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Query minimal 2 karakter.")

    if tools == "all":
        tools_searched = ["regulation_audit", "gap_analysis"]
    elif tools in ("regulation_audit", "gap_analysis"):
        tools_searched = [tools]
    else:
        raise HTTPException(
            status_code=422,
            detail="Parameter 'tools' harus 'all', 'regulation_audit', atau 'gap_analysis'.",
        )

    date_min_ts: float | None = None
    if days:
        cutoff = datetime.now() - timedelta(days=days)
        date_min_ts = cutoff.timestamp()

    all_matches: list[dict] = []

    if "regulation_audit" in tools_searched and OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.glob("*.json"):
            all_matches.extend(_search_in_file(f, query, "regulation_audit", date_min_ts))

    if "gap_analysis" in tools_searched:
        req_dir = REQUIREMENTS_OUTPUT_DIR
        if req_dir.exists():
            for f in req_dir.glob("*.json"):
                all_matches.extend(_search_in_file(f, query, "gap_analysis", date_min_ts))

    all_matches.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    total_before_limit = len(all_matches)
    all_matches = all_matches[:limit]

    by_doc: dict[str, int] = {}
    for m in all_matches:
        key = f"{m['source']}::{m['filename']}"
        by_doc[key] = by_doc.get(key, 0) + 1

    results = [SearchResultItem(**m) for m in all_matches]

    return SearchResponse(
        query=query,
        total=total_before_limit,
        results=results,
        by_document=by_doc,
        tools_searched=tools_searched,
        date_filter_days=days,
    )


# ===========================================================================
# COMPLIANCE REVIEW (Tool 3)
# ===========================================================================

def _load_compliance_preview(preview_id: str) -> dict | None:
    if not _ID_RE.match(preview_id or ""):
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
    contract_ext = Path(contract_file.filename or "").suffix.lower()
    if contract_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format kontrak tidak didukung: '{contract_ext}'. Gunakan .pdf atau .txt.",
        )

    contract_bytes = await contract_file.read()
    if not contract_bytes:
        raise HTTPException(status_code=400, detail="File kontrak kosong.")

    max_size = settings.max_upload_size_mb * 1024 * 1024
    if len(contract_bytes) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"Ukuran kontrak melebihi {settings.max_upload_size_mb} MB.",
        )

    if not regulation_files:
        raise HTTPException(status_code=422, detail="Minimal 1 regulasi acuan harus di-upload.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    preview_id = generate_preview_id()

    contract_path = UPLOAD_DIR / f"{preview_id}_contract{contract_ext}"
    contract_path.write_bytes(contract_bytes)

    try:
        raw_contract = await run_in_threadpool(_extract_text, contract_path, contract_ext)
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
        reg_ext = Path(reg_file.filename or "").suffix.lower()
        if reg_ext not in ALLOWED_EXTENSIONS:
            continue

        reg_bytes = await reg_file.read()
        if not reg_bytes:
            continue

        reg_path = UPLOAD_DIR / f"{preview_id}_reg_{len(reg_filenames)}{reg_ext}"
        reg_path.write_bytes(reg_bytes)

        try:
            raw_reg = await run_in_threadpool(_extract_text, reg_path, reg_ext)
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
    if filter_text:
        needle = filter_text.lower()
        contract_chunks = [
            c for c in contract_chunks
            if needle in c.get("text", "").lower()
        ]
        if not contract_chunks:
            raise HTTPException(
                status_code=422,
                detail=f"Tidak ada klausul yang cocok dengan filter '{filter_text}'.",
            )

    MAX_CONTRACT = 50
    MAX_REGULATION = 100
    contract_chunks = contract_chunks[:MAX_CONTRACT]
    regulation_chunks = regulation_chunks[:MAX_REGULATION]

    try:
        provider = get_ai_provider()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    worker = make_compliance_worker(
        preview_id=payload.preview_id,
        contract_filename=preview.get("contract_filename", ""),
        regulation_filenames=preview.get("regulation_filenames", []),
        contract_chunks=contract_chunks,
        regulation_chunks=regulation_chunks,
        provider=provider,
        filter_text=filter_text,
    )
    return _submit_job("compliance_review", worker, total=2)


@router.post("/compliance/analyze-from-db", response_model=JobAcceptedResponse, status_code=202)
async def compliance_analyze_from_db(
    contract_file: UploadFile = File(...),
    regulation_ids: str = Form(..., description="Comma-separated regulation IDs"),
    nama_kontrak: str = Form(None),
    filter_kontrak: str = Form(None),
    top_k_per_clause: int = Form(3, description="Jumlah regulasi relevan per klausul"),
) -> ComplianceResponse:
    """
    Compliance review dengan regulasi dari Database (RAG mode).

    - Contract di-upload manual
    - Regulasi diambil dari Regulation Database via semantic retrieval
    - Untuk setiap klausul kontrak, cari top-K regulasi paling relevan
    """
    # --- Validasi contract ---
    contract_ext = Path(contract_file.filename or "").suffix.lower()
    if contract_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format kontrak tidak didukung: '{contract_ext}'. Gunakan .pdf atau .txt.",
        )

    contract_bytes = await contract_file.read()
    if not contract_bytes:
        raise HTTPException(status_code=400, detail="File kontrak kosong.")

    max_size = settings.max_upload_size_mb * 1024 * 1024
    if len(contract_bytes) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"Ukuran kontrak melebihi {settings.max_upload_size_mb} MB.",
        )

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
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    preview_id = generate_preview_id()
    contract_path = UPLOAD_DIR / f"{preview_id}_contract{contract_ext}"
    contract_path.write_bytes(contract_bytes)

    try:
        raw_contract = await run_in_threadpool(_extract_text, contract_path, contract_ext)
    except (PDFExtractionError, TextExtractionError) as exc:
        raise HTTPException(status_code=422, detail=f"Kontrak: {exc}") from exc

    contract_chunks = parse_contract_structure(raw_contract)
    if not contract_chunks:
        raise HTTPException(
            status_code=422,
            detail="Tidak ada klausul yang bisa di-parse dari kontrak.",
        )

    # Filter kontrak
    filter_text = (filter_kontrak or "").strip()
    if filter_text:
        needle = filter_text.lower()
        contract_chunks = [c for c in contract_chunks if needle in c.get("text", "").lower()]
        if not contract_chunks:
            raise HTTPException(
                status_code=422,
                detail=f"Tidak ada klausul cocok dengan filter '{filter_text}'.",
            )

    # Batasi
    MAX_CONTRACT = 50
    contract_chunks = contract_chunks[:MAX_CONTRACT]

    # --- Siapkan service (gagal cepat kalau API key belum diisi) ---
    try:
        svc = EmbeddingService()
        provider = get_ai_provider()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    worker = make_compliance_db_worker(
        contract_filename=contract_file.filename or "kontrak",
        contract_chunks=contract_chunks,
        regulation_ids=reg_ids,
        regulation_names=[r.get("name", "") for r in valid_regs if r.get("name")],
        top_k_per_clause=top_k_per_clause,
        embedder=svc,
        provider=provider,
        filter_text=filter_text,
    )
    return _submit_job("compliance_review", worker, total=len(contract_chunks) + 3)

# ===========================================================================
# COMPLIANCE — PARSE CONTRACT (untuk import manual)
# ===========================================================================

@router.post("/compliance/parse-contract", response_model=ParseContractResponse)
async def parse_contract_for_import(file: UploadFile = File(...)) -> ParseContractResponse:
    """
    Parse PDF/TXT kontrak → list klausul untuk preview di modal import.
    TIDAK menyimpan hasil, hanya return list.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format tidak didukung: '{ext}'. Gunakan .pdf atau .txt.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File kosong.")

    if len(file_bytes) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"File melebihi {settings.max_upload_size_mb} MB.",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    temp_id = generate_preview_id()
    temp_path = UPLOAD_DIR / f"{temp_id}_import{ext}"
    temp_path.write_bytes(file_bytes)

    try:
        raw_text = await run_in_threadpool(_extract_text, temp_path, ext)
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
    _, data = _load_compliance_result(result_id)
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
    _lock: None = Depends(_lock_compliance_result),
) -> ComplianceBulkResponse:
    """Bulk update status untuk banyak item sekaligus."""
    path, data = _load_compliance_result(result_id)
    items = data.get("items", [])
    total = len(items)

    valid_statuses = {"PATUH", "PATUH DENGAN CATATAN", "TIDAK PATUH", "TIDAK RELEVAN"}

    if payload.status and payload.status not in valid_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"Status '{payload.status}' tidak valid.",
        )

    affected = 0
    for idx in payload.item_indices:
        if 0 <= idx < total:
            if payload.status:
                items[idx]["status"] = payload.status
            affected += 1

    data["items"] = items
    counts = count_by_status(items)
    data.update(counts)

    _save_result_file(path, data)

    return ComplianceBulkResponse(
        affected=affected,
        total_items=len(items),
        total_patuh=counts["total_patuh"],
        total_patuh_catatan=counts["total_patuh_catatan"],
        total_tidak_patuh=counts["total_tidak_patuh"],
        total_tidak_relevan=counts["total_tidak_relevan"],
    )


# ----- BATCH-ADD (statis) — DEKLARASI DULU -----

@router.post(
    "/compliance/{result_id}/items/batch-add",
    response_model=ComplianceBulkResponse,
)
async def batch_add_compliance_items(
    result_id: str,
    payload: BatchAddComplianceItemRequest,
    _lock: None = Depends(_lock_compliance_result),
) -> ComplianceBulkResponse:
    """
    Tambah banyak klausul sekaligus (untuk import dari PDF).
    Bisa insert di posisi tertentu atau append di akhir.
    """
    path, data = _load_compliance_result(result_id)
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
            "status": it.status or "TIDAK RELEVAN",
            "analisis": it.analisis or "",
        })

    # Insert di posisi
    items[insert_pos:insert_pos] = new_items
    data["items"] = items
    data["total_items"] = len(items)
    counts = count_by_status(items)
    data.update(counts)

    _save_result_file(path, data)

    return ComplianceBulkResponse(
        affected=len(new_items),
        total_items=len(items),
        total_patuh=counts["total_patuh"],
        total_patuh_catatan=counts["total_patuh_catatan"],
        total_tidak_patuh=counts["total_tidak_patuh"],
        total_tidak_relevan=counts["total_tidak_relevan"],
    )


# ----- ADD SINGLE (statis) — DEKLARASI DULU -----

@router.post("/compliance/{result_id}/items", response_model=ComplianceItem)
async def add_compliance_item(
    result_id: str,
    payload: AddComplianceItemRequest,
    _lock: None = Depends(_lock_compliance_result),
) -> ComplianceItem:
    """Tambah 1 klausul manual. Support insert_after untuk posisi spesifik."""
    path, data = _load_compliance_result(result_id)
    items = data.get("items", [])
    total = len(items)

    new_item = {
        "klausul_ref": payload.klausul_ref or "",
        "klausul_text": payload.klausul_text or "",
        "regulasi_ref": payload.regulasi_ref or "",
        "status": payload.status or "TIDAK RELEVAN",
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

    _save_result_file(path, data)
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
    _lock: None = Depends(_lock_compliance_result),
) -> ComplianceItem:
    """Update 1 item compliance."""
    path, data = _load_compliance_result(result_id)
    items = data.get("items", [])

    if item_idx < 0 or item_idx >= len(items):
        raise HTTPException(status_code=404, detail=f"Item {item_idx} tidak ada.")

    update_data = payload.model_dump(exclude_unset=True)

    if update_data.get("status"):
        valid_statuses = {"PATUH", "PATUH DENGAN CATATAN", "TIDAK PATUH", "TIDAK RELEVAN"}
        if update_data["status"] not in valid_statuses:
            raise HTTPException(
                status_code=422,
                detail=f"Status '{update_data['status']}' tidak valid.",
            )

    items[item_idx].update(update_data)
    data["items"] = items

    counts = count_by_status(items)
    data.update(counts)

    _save_result_file(path, data)
    return ComplianceItem(**items[item_idx])


# ----- DELETE (statis) -----

@router.delete(
    "/compliance/{result_id}/items",
    response_model=ComplianceBulkResponse,
)
async def delete_compliance_items(
    result_id: str,
    payload: DeleteComplianceItemsRequest,
    _lock: None = Depends(_lock_compliance_result),
) -> ComplianceBulkResponse:
    """Hapus item terpilih."""
    path, data = _load_compliance_result(result_id)
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

    _save_result_file(path, data)

    return ComplianceBulkResponse(
        affected=len(indices),
        total_items=len(items),
        total_patuh=counts["total_patuh"],
        total_patuh_catatan=counts["total_patuh_catatan"],
        total_tidak_patuh=counts["total_tidak_patuh"],
        total_tidak_relevan=counts["total_tidak_relevan"],
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
    _lock: None = Depends(_lock_compliance_result),
) -> ComplianceResponse:
    """Update ringkasan eksekutif."""
    path, data = _load_compliance_result(result_id)
    data["executive_summary"] = payload.executive_summary or ""
    _save_result_file(path, data)
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
    Analisis AI untuk item tertentu saja (biasanya hasil import PDF).
    Reuse preview dari result — pakai regulation_chunks yang sama.

    Item yang dianalisis: yang belum punya analisis/status TIDAK RELEVAN.
    """
    path, data = _load_compliance_result(result_id)
    items = data.get("items", [])
    total = len(items)

    if not items:
        raise HTTPException(status_code=422, detail="Tidak ada item di result ini.")

    # Ambil preview_id untuk load regulation chunks
    preview_id = data.get("preview_id", "")
    if not preview_id:
        raise HTTPException(
            status_code=422,
            detail="Result tidak memiliki preview_id. Coba re-analyze dari awal.",
        )

    preview = _load_compliance_preview(preview_id)
    if preview is None:
        raise HTTPException(
            status_code=404,
            detail="Preview sudah kedaluwarsa. Silakan upload ulang kontrak.",
        )

    regulation_chunks = preview.get("regulation_chunks", [])
    if not regulation_chunks:
        raise HTTPException(status_code=422, detail="Preview tidak memiliki regulasi.")

    # Ambil item yang valid untuk dianalisis
    valid_indices = sorted(
        {i for i in payload.item_indices if 0 <= i < total}
    )
    if not valid_indices:
        raise HTTPException(status_code=422, detail="Tidak ada index valid.")

    # Convert items ke format contract_chunks
    contract_chunks_to_analyze: list[dict] = []
    for idx in valid_indices:
        it = items[idx]
        contract_chunks_to_analyze.append({
            "pasal": it.get("klausul_ref", ""),
            "ayat": None,
            "huruf": None,
            "text": (it.get("klausul_ref", "") + "\n\n" + it.get("klausul_text", "")).strip(),
        })

    # Batasi regulasi
    MAX_REGULATION = 100
    regulation_chunks = regulation_chunks[:MAX_REGULATION]

    try:
        provider = get_ai_provider()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    worker = make_compliance_items_worker(
        result_path=path,
        result_id=result_id,
        item_indices=valid_indices,
        contract_chunks=contract_chunks_to_analyze,
        regulation_chunks=regulation_chunks,
        provider=provider,
    )
    return _submit_job("compliance_items", worker, total=1)
# ===========================================================================
# COMPLIANCE — MARKDOWN & EXPORT
# ===========================================================================

@router.get("/compliance/{result_id}/markdown")
async def get_compliance_markdown(result_id: str) -> dict:
    """Return markdown table + executive summary untuk copy."""
    _, data = _load_compliance_result(result_id)
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
    _, data = _load_compliance_result(result_id)
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
    _, data = _load_compliance_result(result_id)
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

# ---------------------------------------------------------------------------
# Cleanup preview lama saat modul diimport
# ---------------------------------------------------------------------------
try:
    _cleaned = cleanup_expired()
    if _cleaned:
        logger.info("Cleaned %d expired preview(s).", _cleaned)
except Exception:
    pass