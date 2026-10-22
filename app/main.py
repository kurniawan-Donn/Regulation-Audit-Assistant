"""
Regulation to IT Audit Assistant - Application Entry Point.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.prompt_routes import router as prompt_router
from app.api.regulation_db_routes import router as regulation_db_router
from app.api.routes import router as audit_router
from app.config import settings

app = FastAPI(
    title=settings.app_name,
    description=(
        "MVP untuk membantu auditor IT mengubah ketentuan regulasi "
        "menjadi prosedur pemeriksaan audit."
    ),
    version="1.0.0",
)

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

static_dir = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(audit_router)
app.include_router(prompt_router)
app.include_router(regulation_db_router)


@app.get("/")
def read_root() -> FileResponse:
    return FileResponse(TEMPLATES_DIR / "index.html")


@app.get("/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "env": settings.app_env,
    }