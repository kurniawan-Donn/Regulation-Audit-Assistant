"""
Riwayat analisis dari hasil yang tersimpan di server.

Endpoint:
- GET    /api/history                     -> daftar hasil (terbaru dulu)
- DELETE /api/history/{type}/{result_id}  -> hapus satu hasil (+ file ekspornya)
- POST   /api/history/clear               -> hapus semua hasil (konfirmasi eksplisit)
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app.models.schemas import ClearHistoryRequest, HistoryResponse, ResetDBResponse
from app.services.result_history import (
    KIND_DIRS,
    clear_history,
    delete_result,
    list_history,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["history"])

CLEAR_CONFIRMATION = "HAPUS SEMUA"


@router.get("/history", response_model=HistoryResponse)
async def get_history(limit: int | None = Query(None, ge=1, le=1000)) -> HistoryResponse:
    items = await run_in_threadpool(list_history, limit)
    return HistoryResponse(items=items, total=len(items))


@router.delete("/history/{kind}/{result_id}", response_model=ResetDBResponse)
async def delete_history_item(kind: str, result_id: str) -> ResetDBResponse:
    if kind not in KIND_DIRS:
        raise HTTPException(status_code=404, detail="Jenis hasil tidak dikenal.")
    if not await run_in_threadpool(delete_result, kind, result_id):
        raise HTTPException(status_code=404, detail="Hasil analisis tidak ditemukan.")
    return ResetDBResponse(success=True, message="Hasil analisis dihapus.")


@router.post("/history/clear", response_model=ResetDBResponse)
async def clear_history_endpoint(payload: ClearHistoryRequest) -> ResetDBResponse:
    if payload.confirm != CLEAR_CONFIRMATION:
        raise HTTPException(
            status_code=422,
            detail=f"Konfirmasi tidak cocok. Kirim confirm = '{CLEAR_CONFIRMATION}'.",
        )
    count = await run_in_threadpool(clear_history)
    logger.warning("Semua riwayat analisis dihapus atas permintaan pengguna (%d hasil).", count)
    return ResetDBResponse(success=True, message=f"{count} hasil analisis dihapus.")
