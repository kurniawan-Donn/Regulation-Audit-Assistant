"""
Regulation to IT Audit Assistant - Application Entry Point.

Jalankan dengan `python -m app` (default 127.0.0.1:8000, lihat app/__main__.py).
"""

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.job_routes import router as job_router
from app.api.prompt_routes import router as prompt_router
from app.api.regulation_db_routes import router as regulation_db_router
from app.api.routes import router as audit_router
from app.config import settings
from app.security import SecurityMiddleware, auth_enabled
from app.services.job_manager import get_job_manager, shutdown_job_manager
from app.services.preview_cache import cleanup_expired

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    manager = get_job_manager()
    manager.recover_and_cleanup()
    try:
        removed = cleanup_expired()
        if removed:
            logger.info("Membersihkan %d file cache kedaluwarsa.", removed)
    except Exception:
        logger.exception("Gagal membersihkan cache kedaluwarsa.")
    if not auth_enabled():
        logger.warning(
            "APP_PASSWORD belum diisi: aplikasi TANPA autentikasi. "
            "Aman hanya jika diakses dari komputer ini (127.0.0.1)."
        )
    yield
    shutdown_job_manager()


app = FastAPI(
    title=settings.app_name,
    description=(
        "MVP untuk membantu auditor IT mengubah ketentuan regulasi "
        "menjadi prosedur pemeriksaan audit."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(SecurityMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Error tak terduga: detail hanya di log server, client mendapat kode pelacakan."""
    error_id = uuid.uuid4().hex[:8]
    logger.exception("Error tak tertangani [%s] %s %s", error_id, request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Terjadi kesalahan internal (kode: {error_id}). Detail tercatat di log server."},
    )


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

static_dir = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(audit_router)
app.include_router(prompt_router)
app.include_router(regulation_db_router)
app.include_router(job_router)


@app.get("/")
def read_root() -> FileResponse:
    return FileResponse(TEMPLATES_DIR / "index.html")


@app.get("/panduan")
def read_guide() -> FileResponse:
    """Buku Panduan Pengguna (halaman mandiri, bisa dicetak ke PDF)."""
    return FileResponse(TEMPLATES_DIR / "panduan.html")


DEMO_SAMPLE_CONTRACT = PROJECT_ROOT / "scripts" / "compliance_eval" / "kontrak_uji_penyedia_ti.txt"


@app.get("/demo/contoh-kontrak.txt")
def demo_sample_contract() -> FileResponse:
    """Contoh kontrak untuk dicoba pengunjung demo (hanya di Mode Demo)."""
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Tidak ditemukan.")
    return FileResponse(DEMO_SAMPLE_CONTRACT, filename="contoh_kontrak_penyedia_jasa_ti.txt",
                        media_type="text/plain; charset=utf-8")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
