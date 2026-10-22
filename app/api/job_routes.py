"""
API Routes untuk Background Jobs.

- GET  /api/jobs                  -> daftar job yang sedang antre/berjalan
- GET  /api/jobs/{job_id}         -> status + progres
- POST /api/jobs/{job_id}/cancel  -> minta pembatalan
"""

from fastapi import APIRouter, HTTPException

from app.models.schemas import JobStatusResponse
from app.services.job_manager import get_job_manager

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobStatusResponse])
async def list_active_jobs() -> list[JobStatusResponse]:
    return [JobStatusResponse(**j) for j in get_job_manager().list_active()]


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    job = get_job_manager().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    return JobStatusResponse(**job)


@router.post("/{job_id}/cancel", response_model=JobStatusResponse)
async def cancel_job(job_id: str) -> JobStatusResponse:
    job = get_job_manager().cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    return JobStatusResponse(**job)
