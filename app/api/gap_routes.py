"""
Route Tool 2 — Gap Analysis: ekstraksi persyaratan (job), operasi baris,
dan export Excel/PDF. Memakai preview yang sama dengan Tool 1.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.models.schemas import (
    AddRequirementRequest,
    AnalyzeRequirementsRequest,
    AnalyzeRequirementsResponse,
    BulkUpdateRequest,
    DeleteRequirementsRequest,
    JobAcceptedResponse,
    RequirementItem,
    RequirementsBulkActionResponse,
    UpdateRequirementRequest,
)
from app.services.analysis_jobs import (
    make_requirements_worker,
)
from app.services.chunk_batcher import create_batches
from app.services.preview_cache import (
    load_preview,
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
    get_effective_settings,
)
from app.api.common import (
    MIN_CHUNK_LENGTH,
    REQUIREMENTS_OUTPUT_DIR,
    ai_provider_or_422,
    load_requirements_file,
    lock_requirements_result,
    save_result_file,
    submit_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["gap-analysis"])


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

    provider = ai_provider_or_422()

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
    return submit_job("gap_analysis", worker, total=len(batches))


@router.get("/requirements/{result_id}", response_model=AnalyzeRequirementsResponse)
async def get_requirements(result_id: str) -> AnalyzeRequirementsResponse:
    _, data = load_requirements_file(result_id)
    return AnalyzeRequirementsResponse(**data)


# ----- BULK (statis) — DEKLARASI DULU -----

@router.patch(
    "/requirements/{result_id}/items/bulk",
    response_model=RequirementsBulkActionResponse,
)
async def bulk_update_requirements(
    result_id: str, payload: BulkUpdateRequest,
    _lock: None = Depends(lock_requirements_result),
) -> RequirementsBulkActionResponse:
    path, data = load_requirements_file(result_id)
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
    save_result_file(path, data)

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
    _lock: None = Depends(lock_requirements_result),
) -> RequirementItem:
    path, data = load_requirements_file(result_id)
    items = data.get("requirements", [])

    if item_idx < 0 or item_idx >= len(items):
        raise HTTPException(
            status_code=404,
            detail=f"Item index {item_idx} tidak ada (jumlah: {len(items)}).",
        )

    update_data = payload.model_dump(exclude_unset=True)
    items[item_idx].update(update_data)
    data["requirements"] = items
    save_result_file(path, data)
    return RequirementItem(**items[item_idx])


@router.post(
    "/requirements/{result_id}/items",
    response_model=RequirementItem,
)
async def add_requirement_item(
    result_id: str, payload: AddRequirementRequest,
    _lock: None = Depends(lock_requirements_result),
) -> RequirementItem:
    path, data = load_requirements_file(result_id)
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
    save_result_file(path, data)
    return RequirementItem(**new_item)


@router.delete(
    "/requirements/{result_id}/items",
    response_model=RequirementsBulkActionResponse,
)
async def delete_requirement_items(
    result_id: str, payload: DeleteRequirementsRequest,
    _lock: None = Depends(lock_requirements_result),
) -> RequirementsBulkActionResponse:
    path, data = load_requirements_file(result_id)
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
    save_result_file(path, data)

    return RequirementsBulkActionResponse(
        affected=len(indices),
        total_requirements=len(items),
    )


@router.get("/export-requirements/{result_id}")
async def export_requirements(result_id: str) -> FileResponse:
    _, data = load_requirements_file(result_id)
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
    _, data = load_requirements_file(result_id)
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
