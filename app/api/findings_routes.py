"""
Daftar Temuan: temuan audit lintas Compliance Review & Gap Analysis.

Endpoint:
- GET    /api/findings                 -> daftar + ringkasan
- POST   /api/findings/from-source     -> kirim baris hasil analisis (tanpa dobel)
- POST   /api/findings                 -> temuan manual
- PATCH  /api/findings/{id}            -> ubah field (risiko, status, PIC, ...)
- DELETE /api/findings/{id}            -> hapus temuan
- GET    /api/findings/export          -> Excel
- GET    /api/findings/report/meta     -> pengaturan laporan terakhir
- POST   /api/findings/report/summary  -> draf ringkasan eksekutif (AI)
- POST   /api/findings/report?format=  -> Laporan Hasil Audit (docx | pdf)
"""

import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.api.common import ai_provider_or_422, load_compliance_result, load_requirements_file
from app.models.schemas import (
    AddFindingsFromSourceRequest,
    AddFindingsFromSourceResponse,
    AuditReportOptions,
    AuditReportSummaryResponse,
    Finding,
    FindingFields,
    FindingsResponse,
    ResetDBResponse,
)
from app.services import audit_report
from app.services import findings as store
from app.services.ai_service import AIProviderError
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


# =============================================================================
# LAPORAN HASIL AUDIT
# =============================================================================

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _prepared_report(options: AuditReportOptions) -> dict:
    data = await run_in_threadpool(store.list_findings)
    report = audit_report.prepare_report(data["items"], options.model_dump())
    if not report["findings"]:
        raise HTTPException(status_code=422, detail="Tidak ada temuan yang cocok dengan filter laporan.")
    return report


@router.get("/report/meta", response_model=AuditReportOptions)
async def get_report_meta() -> AuditReportOptions:
    return AuditReportOptions(**await run_in_threadpool(store.get_report_meta))


@router.post("/report/summary", response_model=AuditReportSummaryResponse)
async def report_summary(options: AuditReportOptions) -> AuditReportSummaryResponse:
    report = await _prepared_report(options)
    provider = ai_provider_or_422()
    try:
        result = await run_in_threadpool(audit_report.generate_summary, report, provider)
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not result["ringkasan"]:
        raise HTTPException(status_code=502, detail="AI tidak mengembalikan ringkasan. Coba lagi.")
    return AuditReportSummaryResponse(**result)


@router.post("/report")
async def download_report(
    options: AuditReportOptions,
    format: str = Query("docx", pattern="^(docx|pdf)$"),
) -> Response:
    report = await _prepared_report(options)
    await run_in_threadpool(store.save_report_meta, options.model_dump())
    builder = audit_report.build_docx if format == "docx" else audit_report.build_pdf

    def _build() -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"laporan.{format}"
            builder(report, str(path))
            return path.read_bytes()

    content = await run_in_threadpool(_build)
    filename = f"laporan_hasil_audit_{date.today().isoformat()}.{format}"
    return Response(
        content=content,
        media_type=DOCX_MEDIA_TYPE if format == "docx" else "application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

