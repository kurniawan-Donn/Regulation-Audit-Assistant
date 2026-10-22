"""
API Routes — versi lengkap dengan semua fix:
- Urutan route bulk > item_idx untuk semua tools
- Compliance: bulk-add, parse-contract, insert-after
- Import lengkap
"""

import json
import logging
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from fastapi.responses import FileResponse

from app.config import settings
from app.models.schemas import (
    AddComplianceItemRequest,
    AddItemRequest,
    AddRequirementRequest,
    AnalyzeRequirementsRequest,
    AnalyzeRequirementsResponse,
    AnalyzeResponse,
    AnalyzeSelectedRequest,
    AuditResultItem,
    BatchAddComplianceItemRequest,
    BulkActionResponse,
    BulkUpdateComplianceRequest,
    BulkUpdateRequest,
    ChunkError,
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
    ParsedContractClause,
    ParseContractResponse,
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
    AnalyzeComplianceItemsRequest,
)
from app.prompts.aspects import (
    STATUS_KEPATUHAN_DEFAULT,
    find_aspect_insensitive,
    find_method_insensitive,
    is_valid_status_kepatuhan,
)
from app.services.ai_service import (
    AIProviderError,
    AIResponseParsingError,
    get_ai_provider,
)
from app.services.audit_analyzer import AuditAnalysisError, analyze_chunks_batch
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
from app.services.compliance_review_analyzer import (
    ComplianceAnalysisError,
    analyze_compliance,
    count_by_status,
    generate_executive_summary,
    normalize_compliance_items,
)
from app.services.contract_parser import parse_contract_structure
from app.services.cost_estimator import estimate as estimate_cost
from app.services.excel_exporter import build_export_filename, export_results_to_excel
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
from app.services.regulation_parser import parse_regulation_structure
from app.services.requirements_analyzer import (
    RequirementsAnalysisError,
    analyze_chunks_for_requirements,
)
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
from app.services.validator import validate_results

from app.services.embedding_service import EmbeddingError, EmbeddingService
from app.services.regulation_db import (
    RegulationDBError,
    get_regulation,
    query_relevant_chunks as query_reg_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["audit"])

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
ALLOWED_EXTENSIONS = {".pdf", ".txt"}
MIN_CHUNK_LENGTH = 15


# ===========================================================================
# HELPERS
# ===========================================================================

def _load_result_file(result_id: str) -> tuple[Path, dict]:
    path = OUTPUT_DIR / f"{result_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Hasil analisis tidak ditemukan.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal membaca hasil: {exc}") from exc
    return path, data


def _load_requirements_file(result_id: str) -> tuple[Path, dict]:
    path = OUTPUT_DIR / "requirements" / f"{result_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Hasil gap analysis tidak ditemukan.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal membaca hasil: {exc}") from exc
    return path, data


def _save_result_file(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
            if extension == ".pdf":
                raw_text = extract_pdf_text(str(saved_path))
            else:
                raw_text = extract_txt_text(str(saved_path))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail=f"File tidak ditemukan: {exc}") from exc
        except (PDFExtractionError, TextExtractionError) as exc:
            saved_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        cleaned_text = clean_text(raw_text)
        chunks = parse_regulation_structure(cleaned_text)

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

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_regulation(payload: AnalyzeSelectedRequest) -> AnalyzeResponse:
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

    validated_results: list[dict] = []
    chunk_errors: list[ChunkError] = []

    for batch in batches:
        try:
            batch_result = analyze_chunks_batch(batch, provider, referensi_regulasi=referensi_regulasi)
        except (AIProviderError, AIResponseParsingError, AuditAnalysisError) as exc:
            lampirans = sorted({c["lampiran"] for c in batch if c.get("lampiran")})
            babs = sorted({c["bab"] for c in batch if c.get("bab")})
            pasals = sorted({c["pasal"] for c in batch if c.get("pasal")})
            chunk_errors.append(
                ChunkError(
                    lampiran=", ".join(lampirans) if lampirans else None,
                    bab=", ".join(babs) if babs else None,
                    pasal=", ".join(pasals) if pasals else None,
                    ayat=None,
                    error=str(exc),
                    affected_count=len(batch),
                )
            )
            continue

        validated_results.extend(validate_results(batch_result, source_text=cleaned_text))

    total_valid = sum(1 for r in validated_results if r["is_valid"])
    total_by_aspect = dict(
        Counter(r["aspek"] for r in validated_results if r.get("aspek"))
    )

    result_id = uuid.uuid4().hex

    response = AnalyzeResponse(
        result_id=result_id,
        filename=filename,
        preview_id=payload.preview_id,
        total_chunks=len(relevant_chunks),
        total_chunks_available=len(all_chunks),
        total_batches=len(batches),
        total_ketentuan=len(validated_results),
        total_valid=total_valid,
        total_flagged=len(validated_results) - total_valid,
        results=[AuditResultItem(**r) for r in validated_results],
        chunk_errors=chunk_errors,
        total_by_aspect=total_by_aspect,
        filter_applied=list(payload.selected_labels),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / f"{result_id}.json").write_text(
        response.model_dump_json(indent=2), encoding="utf-8"
    )

    return response


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

    export_results_to_excel(results, str(excel_path))

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

    export_results_to_pdf(
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

@router.post("/analyze-requirements", response_model=AnalyzeRequirementsResponse)
async def analyze_requirements(
    payload: AnalyzeRequirementsRequest,
) -> AnalyzeRequirementsResponse:
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

    all_requirements: list[dict] = []
    chunk_errors: list[ChunkError] = []

    for batch in batches:
        try:
            batch_result = analyze_chunks_for_requirements(
                batch, provider, referensi_regulasi=referensi_regulasi
            )
        except (AIProviderError, AIResponseParsingError, RequirementsAnalysisError) as exc:
            lampirans = sorted({c["lampiran"] for c in batch if c.get("lampiran")})
            babs = sorted({c["bab"] for c in batch if c.get("bab")})
            pasals = sorted({c["pasal"] for c in batch if c.get("pasal")})
            chunk_errors.append(
                ChunkError(
                    lampiran=", ".join(lampirans) if lampirans else None,
                    bab=", ".join(babs) if babs else None,
                    pasal=", ".join(pasals) if pasals else None,
                    ayat=None,
                    error=str(exc),
                    affected_count=len(batch),
                )
            )
            continue

        for item in batch_result:
            if not isinstance(item, dict):
                continue
            all_requirements.append({
                "persyaratan": str(item.get("persyaratan", "")).strip(),
                "referensi": str(item.get("referensi", "")).strip(),
                "catatan": str(item.get("catatan", "")).strip(),
                "status_gap": "",
            })

    result_id = uuid.uuid4().hex

    response = AnalyzeRequirementsResponse(
        result_id=result_id,
        filename=filename,
        preview_id=payload.preview_id,
        total_chunks_analyzed=len(selected_chunks),
        total_chunks_available=len(all_chunks),
        total_batches=len(batches),
        total_requirements=len(all_requirements),
        requirements=[RequirementItem(**r) for r in all_requirements],
        chunk_errors=chunk_errors,
        filter_applied=filter_text,
    )

    req_dir = OUTPUT_DIR / "requirements"
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / f"{result_id}.json").write_text(
        response.model_dump_json(indent=2), encoding="utf-8"
    )

    return response


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
    excel_path = OUTPUT_DIR / "requirements" / f"{result_id}.xlsx"

    export_requirements_to_excel(items, str(excel_path))

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
    pdf_path = OUTPUT_DIR / "requirements" / f"{result_id}.pdf"

    export_requirements_to_pdf(
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
    import google.generativeai as genai

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

    start = time.time()
    try:
        genai.configure(api_key=api_key)
        m = genai.GenerativeModel(model_name=model)
        resp = m.generate_content(
            "Balas dengan satu kata: OK",
            generation_config={"max_output_tokens": 1024, "temperature": 0},
        )

        candidate = resp.candidates[0] if resp.candidates else None
        finish_reason = getattr(candidate, "finish_reason", None)

        text = ""
        try:
            if candidate and candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        text += part.text
        except Exception:
            pass

        text = text.strip()
        latency = int((time.time() - start) * 1000)

        if not text:
            reason_str = str(finish_reason) if finish_reason else "tidak diketahui"
            return ConnectionTestResponse(
                ok=False,
                message=(
                    f"Model mengembalikan response kosong. "
                    f"finish_reason={reason_str}. "
                    f"Model '{model}' mungkin tidak valid."
                ),
                model_tested=model,
                latency_ms=latency,
            )

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
            message=f"Gagal: {type(exc).__name__} — {str(exc)[:200]}",
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
        req_dir = OUTPUT_DIR / "requirements"
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

COMPLIANCE_PREVIEW_DIR = Path("cache/compliance_previews")
COMPLIANCE_OUTPUT_DIR = OUTPUT_DIR / "compliance"


def _load_compliance_preview(preview_id: str) -> dict | None:
    path = COMPLIANCE_PREVIEW_DIR / f"{preview_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_compliance_preview(preview_id: str, data: dict) -> None:
    COMPLIANCE_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    path = COMPLIANCE_PREVIEW_DIR / f"{preview_id}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _load_compliance_result(result_id: str) -> tuple[Path, dict]:
    path = COMPLIANCE_OUTPUT_DIR / f"{result_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Hasil compliance review tidak ditemukan.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal membaca hasil: {exc}") from exc
    return path, data


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
        if contract_ext == ".pdf":
            raw_contract = extract_pdf_text(str(contract_path))
        else:
            raw_contract = extract_txt_text(str(contract_path))
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
            if reg_ext == ".pdf":
                raw_reg = extract_pdf_text(str(reg_path))
            else:
                raw_reg = extract_txt_text(str(reg_path))
        except (PDFExtractionError, TextExtractionError):
            continue

        cleaned_reg = clean_text(raw_reg)
        reg_chunks = parse_regulation_structure(cleaned_reg)

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

@router.post("/compliance/analyze", response_model=ComplianceResponse)
async def compliance_analyze(payload: ComplianceAnalyzeRequest) -> ComplianceResponse:
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

    try:
        raw_items = analyze_compliance(contract_chunks, regulation_chunks, provider)
    except (AIProviderError, AIResponseParsingError, ComplianceAnalysisError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Analisis compliance gagal: {exc}",
        ) from exc

    items = normalize_compliance_items(raw_items)
    counts = count_by_status(items)

    executive_summary = generate_executive_summary(items, provider)

    result_id = uuid.uuid4().hex

    response = ComplianceResponse(
        result_id=result_id,
        preview_id=payload.preview_id,
        contract_filename=preview.get("contract_filename", ""),
        regulation_filenames=preview.get("regulation_filenames", []),
        total_items=len(items),
        total_patuh=counts["total_patuh"],
        total_patuh_catatan=counts["total_patuh_catatan"],
        total_tidak_patuh=counts["total_tidak_patuh"],
        total_tidak_relevan=counts["total_tidak_relevan"],
        items=[ComplianceItem(**it) for it in items],
        executive_summary=executive_summary,
        total_contract_chunks=len(contract_chunks),
        total_regulation_chunks=len(regulation_chunks),
        total_batches=1,
        filter_applied=filter_text,
    )

    COMPLIANCE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (COMPLIANCE_OUTPUT_DIR / f"{result_id}.json").write_text(
        response.model_dump_json(indent=2), encoding="utf-8"
    )

    return response


@router.post("/compliance/analyze-from-db", response_model=ComplianceResponse)
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
        if contract_ext == ".pdf":
            raw_contract = extract_pdf_text(str(contract_path))
        else:
            raw_contract = extract_txt_text(str(contract_path))
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

    # --- RAG RETRIEVAL ---
    # Untuk setiap contract chunk, cari top-K regulation chunks
    try:
        svc = EmbeddingService()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 1. Embed semua contract chunks (batch)
    contract_texts = [c.get("text", "") for c in contract_chunks]
    try:
        contract_embeddings = svc.embed_batch(
            contract_texts, task_type="RETRIEVAL_QUERY"
        )
    except EmbeddingError as exc:
        raise HTTPException(status_code=502, detail=f"Gagal embed contract: {exc}") from exc

    # 2. Untuk setiap contract chunk, retrieve top-K regulation chunks
    retrieved_regulation_chunks: list[dict] = []
    seen_chunk_ids: set[str] = set()

    for i, contract_emb in enumerate(contract_embeddings):
        try:
            hits = query_reg_db(
                query_embedding=contract_emb,
                regulation_ids=reg_ids,
                top_k=top_k_per_clause,
            )
        except RegulationDBError as exc:
            logger.warning("Retrieval gagal untuk chunk %d: %s", i, exc)
            continue

        for hit in hits:
            if hit["id"] not in seen_chunk_ids:
                seen_chunk_ids.add(hit["id"])
                # Konversi format metadata ke chunk format yang dipahami analyze_compliance
                meta = hit.get("metadata", {})
                retrieved_regulation_chunks.append({
                    "lampiran": meta.get("lampiran") or None,
                    "bab": meta.get("bab") or None,
                    "bagian": meta.get("bagian") or None,
                    "pasal": meta.get("pasal") or None,
                    "ayat": meta.get("ayat") or None,
                    "butir": meta.get("butir") or None,
                    "text": hit.get("text", ""),
                    "source_file": meta.get("regulation_name", "Unknown"),
                    "page_start": meta.get("page_start") or 0,
                    "page_end": meta.get("page_end") or 0,
                    "_retrieval_distance": hit.get("distance"),
                })

    if not retrieved_regulation_chunks:
        raise HTTPException(
            status_code=422,
            detail="Tidak ada regulasi relevan yang ditemukan. Coba pilih regulasi lain.",
        )

    logger.info(
        "RAG retrieval: %d contract chunks → %d unique regulation chunks",
        len(contract_chunks), len(retrieved_regulation_chunks),
    )

    # --- ANALYZE ---
    try:
        provider = get_ai_provider()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        raw_items = analyze_compliance(
            contract_chunks,
            retrieved_regulation_chunks,
            provider,
        )
    except (AIProviderError, AIResponseParsingError, ComplianceAnalysisError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Analisis compliance gagal: {exc}",
        ) from exc

    items = normalize_compliance_items(raw_items)
    counts = count_by_status(items)
    executive_summary = generate_executive_summary(items, provider)

    result_id = uuid.uuid4().hex

    # Ambil nama regulasi yang dipakai (untuk display)
    regulation_names = [r.get("name", "") for r in valid_regs if r.get("name")]

    response = ComplianceResponse(
        result_id=result_id,
        preview_id="",  # tidak pakai preview (RAG mode)
        contract_filename=contract_file.filename or "kontrak",
        regulation_filenames=regulation_names,
        total_items=len(items),
        total_patuh=counts["total_patuh"],
        total_patuh_catatan=counts["total_patuh_catatan"],
        total_tidak_patuh=counts["total_tidak_patuh"],
        total_tidak_relevan=counts["total_tidak_relevan"],
        items=[ComplianceItem(**it) for it in items],
        executive_summary=executive_summary,
        total_contract_chunks=len(contract_chunks),
        total_regulation_chunks=len(retrieved_regulation_chunks),
        total_batches=1,
        filter_applied=filter_text,
    )

    # Simpan metadata RAG ke response (opsional, untuk debugging)
    COMPLIANCE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (COMPLIANCE_OUTPUT_DIR / f"{result_id}.json").write_text(
        response.model_dump_json(indent=2), encoding="utf-8"
    )

    return response

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
        if ext == ".pdf":
            raw_text = extract_pdf_text(str(temp_path))
        else:
            raw_text = extract_txt_text(str(temp_path))
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

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return ComplianceItem(**items[item_idx])


# ----- DELETE (statis) -----

@router.delete(
    "/compliance/{result_id}/items",
    response_model=ComplianceBulkResponse,
)
async def delete_compliance_items(
    result_id: str,
    payload: DeleteComplianceItemsRequest,
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

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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
) -> ComplianceResponse:
    """Update ringkasan eksekutif."""
    path, data = _load_compliance_result(result_id)
    data["executive_summary"] = payload.executive_summary or ""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return ComplianceResponse(**data)

@router.post(
    "/compliance/{result_id}/analyze-items",
    response_model=ComplianceBulkResponse,
)
async def analyze_compliance_items(
    result_id: str,
    payload: AnalyzeComplianceItemsRequest,
) -> ComplianceBulkResponse:
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

    try:
        raw_items = analyze_compliance(contract_chunks_to_analyze, regulation_chunks, provider)
    except (AIProviderError, AIResponseParsingError, ComplianceAnalysisError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Analisis AI gagal: {exc}",
        ) from exc

    normalized = normalize_compliance_items(raw_items)

    # Map hasil ke item berdasarkan urutan (AI harus return dengan urutan yang sama)
    affected = 0
    for i, idx in enumerate(valid_indices):
        if i >= len(normalized):
            break
        result_item = normalized[i]
        # Update field yang relevan — JANGAN overwrite klausul_ref/text user
        items[idx]["regulasi_ref"] = result_item.get("regulasi_ref", "")
        items[idx]["status"] = result_item.get("status", "TIDAK RELEVAN")
        items[idx]["analisis"] = result_item.get("analisis", "")
        affected += 1

    data["items"] = items
    counts = count_by_status(items)
    data.update(counts)

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return ComplianceBulkResponse(
        affected=affected,
        total_items=len(items),
        total_patuh=counts["total_patuh"],
        total_patuh_catatan=counts["total_patuh_catatan"],
        total_tidak_patuh=counts["total_tidak_patuh"],
        total_tidak_relevan=counts["total_tidak_relevan"],
    )
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

    export_compliance_to_excel(
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

    export_compliance_to_pdf(
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