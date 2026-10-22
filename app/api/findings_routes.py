"""
Daftar Temuan: temuan audit lintas Compliance Review & Gap Analysis.

Endpoint:
- GET    /api/findings                 -> daftar + ringkasan
- POST   /api/findings/from-source     -> kirim baris hasil analisis (tanpa dobel)
- POST   /api/findings                 -> temuan manual
- PATCH  /api/findings/{id}            -> ubah field (risiko, status, PIC, ...)
- DELETE /api/findings/{id}            -> hapus temuan
- GET    /api/findings/export          -> Excel
"""

import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.api.common import load_compliance_result, load_requirements_file
from app.models.schemas import (
    AddFindingsFromSourceRequest,
    AddFindingsFromSourceResponse,
    Finding,
    FindingFields,
    FindingsResponse,
    ResetDBResponse,
)
from app.services import findings as store
from app.services.findings_exporter import export_findings_to_excel

router = APIRouter(prefix="/api/findings", tags=["findings"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("", response_model=FindingsResponse)
async def get_findings() -> FindingsResponse:
    return FindingsResponse(**await run_in_threadpool(store.list_findings))


@router.post("/from-source", response_model=AddFindingsFromSourceResponse)
async def add_from_source(payload: AddFindingsFromSourceRequest) -> AddFindingsFromSourceResponse:
    # Isi temuan diambil dari hasil tersimpan di server, bukan dari klien.
    if payload.source_type == "compliance_review":
        _, result = load_compliance_result(payload.result_id)
    else:
        _, result = load_requirements_file(payload.result_id)

    outcome = await run_in_threadpool(
        store.add_from_result, payload.source_type, result, payload.item_indices,
    )
    if outcome["candidates"] == 0:
        raise HTTPException(
            status_code=422,
            detail=(
                "Tidak ada baris berstatus temuan untuk dikirim."
                if payload.item_indices is None else "Baris yang dipilih tidak ditemukan."
            ),
        )
    return AddFindingsFromSourceResponse(**outcome)


@router.post("", response_model=Finding, status_code=201)
async def create_finding(payload: FindingFields) -> Finding:
    try:
        finding = await run_in_threadpool(store.add_manual, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Finding(**finding)


@router.patch("/{finding_id}", response_model=Finding)
async def patch_finding(finding_id: str, payload: FindingFields) -> Finding:
    try:
        finding = await run_in_threadpool(
            store.update_finding, finding_id, payload.model_dump(exclude_none=True),
        )
    except store.FindingNotFound as exc:
        raise HTTPException(status_code=404, detail="Temuan tidak ditemukan.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Finding(**finding)


@router.delete("/{finding_id}", response_model=ResetDBResponse)
async def remove_finding(finding_id: str) -> ResetDBResponse:
    try:
        await run_in_threadpool(store.delete_finding, finding_id)
    except store.FindingNotFound as exc:
        raise HTTPException(status_code=404, detail="Temuan tidak ditemukan.") from exc
    return ResetDBResponse(success=True, message="Temuan dihapus.")


@router.get("/export")
async def export_findings() -> Response:
    data = await run_in_threadpool(store.list_findings)
    if not data["items"]:
        raise HTTPException(status_code=422, detail="Daftar Temuan masih kosong.")

    def _build() -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "temuan.xlsx"
            export_findings_to_excel(data["items"], str(path))
            return path.read_bytes()

    content = await run_in_threadpool(_build)
    filename = f"daftar_temuan_{date.today().isoformat()}.xlsx"
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
