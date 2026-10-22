"""
Route Tool 1 — Regulation to Audit: preview & tree regulasi, estimasi
biaya, analisis (job), operasi baris hasil, dan export Excel/PDF.

Route statis (bulk) dideklarasikan sebelum route dinamis ({item_idx}).
"""

import logging
import time
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.models.schemas import (
    AddItemRequest,
    AnalyzeResponse,
    AnalyzeSelectedRequest,
    AuditResultItem,
    BulkActionResponse,
    BulkUpdateRequest,
    DeleteItemsRequest,
    EstimateRequest,
    EstimateResponse,
    JobAcceptedResponse,
    PreviewResponse,
    PreviewRetrieveResponse,
    UpdateItemRequest,
)
from app.prompts.aspects import (
    STATUS_KEPATUHAN_DEFAULT,
    find_aspect_insensitive,
    find_method_insensitive,
    is_valid_status_kepatuhan,
)
from app.services.analysis_jobs import (
    make_audit_worker,
)
from app.services.chunk_batcher import create_batches
from app.services.cost_estimator import estimate as estimate_cost
from app.services.excel_exporter import build_export_filename, export_results_to_excel
from app.services.pdf_exporter import build_pdf_filename, export_results_to_pdf
from app.services.pdf_parser import PDFExtractionError
from app.services.preview_cache import (
    compute_file_hash,
    generate_preview_id,
    load_parsed_by_hash,
    load_preview,
    save_parsed_by_hash,
    save_preview,
)
from app.services.regulation_parser import parse_regulation_structure
from app.services.runtime_settings import (
    get_effective_settings,
)
from app.services.structure_tree import assign_node_ids, build_tree
from app.services.text_processor import TextExtractionError, clean_text
from app.api.common import (
    MIN_CHUNK_LENGTH,
    OUTPUT_DIR,
    ai_provider_or_422,
    extract_bytes,
    load_result_file,
    lock_audit_result,
    read_upload,
    save_result_file,
    submit_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["audit"])


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
    file_bytes, extension = await read_upload(file)

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
        start_ts = time.time()
        try:
            raw_text = await run_in_threadpool(extract_bytes, file_bytes, extension)
        except (PDFExtractionError, TextExtractionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        cleaned_text = clean_text(raw_text)
        chunks = await run_in_threadpool(parse_regulation_structure, cleaned_text)

        if not chunks:
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

    provider = ai_provider_or_422()

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
    return submit_job("regulation_audit", worker, total=len(batches))


# ===========================================================================
# RESULT ITEM OPERATIONS (Tool 1)
# ===========================================================================

@router.get("/results/{result_id}", response_model=AnalyzeResponse)
async def get_results(result_id: str) -> AnalyzeResponse:
    _, data = load_result_file(result_id)
    return AnalyzeResponse(**data)


# ----- BULK (statis) — DEKLARASI DULU -----

@router.patch("/results/{result_id}/items/bulk", response_model=BulkActionResponse)
async def bulk_update_items(
    result_id: str, payload: BulkUpdateRequest,
    _lock: None = Depends(lock_audit_result),
) -> BulkActionResponse:
    path, data = load_result_file(result_id)
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
    save_result_file(path, data)

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
    _lock: None = Depends(lock_audit_result),
) -> AuditResultItem:
    path, data = load_result_file(result_id)
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
    save_result_file(path, data)
    return AuditResultItem(**item)


@router.post("/results/{result_id}/items", response_model=AuditResultItem)
async def add_result_item(
    result_id: str, payload: AddItemRequest,
    _lock: None = Depends(lock_audit_result),
) -> AuditResultItem:
    path, data = load_result_file(result_id)
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
    save_result_file(path, data)
    return AuditResultItem(**new_item)


@router.delete("/results/{result_id}/items", response_model=BulkActionResponse)
async def delete_result_items(
    result_id: str, payload: DeleteItemsRequest,
    _lock: None = Depends(lock_audit_result),
) -> BulkActionResponse:
    path, data = load_result_file(result_id)
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
    save_result_file(path, data)

    return BulkActionResponse(
        affected=len(indices),
        total_ketentuan=data["total_ketentuan"],
        total_valid=data["total_valid"],
        total_flagged=data["total_flagged"],
        total_by_aspect=data["total_by_aspect"],
    )


@router.get("/export/{result_id}")
async def export_to_excel(result_id: str) -> FileResponse:
    _, data = load_result_file(result_id)
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
    _, data = load_result_file(result_id)
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
