"""
Helper bersama untuk route API: konstanta storage, validasi ID hasil,
baca/simpan file hasil (atomik), lock per file, submit job, dan ekstraksi
teks dari file upload.

Catatan arsitektur:
- Analisis AI yang lama TIDAK dijalankan di request: endpoint memvalidasi
  input lalu men-submit job (services/job_manager.py) dan membalas 202.
- Pekerjaan sinkron yang berat (ekstraksi PDF, export) dijalankan lewat
  run_in_threadpool supaya event loop tidak terblokir.
- Endpoint read-modify-write memegang lock per file (dependency lock_*),
  karena job background juga bisa menulis file yang sama.
"""

import logging
import re
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import settings
from app.models.schemas import JobAcceptedResponse
from app.services.ai_service import AIProvider, get_ai_provider
from app.services.embedding_service import EmbeddingService
from app.services.job_manager import Worker, get_job_manager
from app.services.json_store import locked, read_json, write_json_atomic
from app.services.pdf_parser import extract_pdf_text
from app.services.text_processor import extract_txt_text

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("outputs")
REQUIREMENTS_OUTPUT_DIR = OUTPUT_DIR / "requirements"
COMPLIANCE_OUTPUT_DIR = OUTPUT_DIR / "compliance"
COMPLIANCE_PREVIEW_DIR = Path("cache/compliance_previews")
ALLOWED_EXTENSIONS = {".pdf", ".txt"}
MIN_CHUNK_LENGTH = 15

# Semua ID hasil/preview adalah uuid4().hex. Validasi ketat ini juga
# mencegah path traversal (mis. backslash ter-decode dari %5C di Windows).
ID_RE = re.compile(r"^[0-9a-f]{32}$")


# ===========================================================================
# HELPERS
# ===========================================================================

def result_path(directory: Path, result_id: str, not_found: str) -> Path:
    if not ID_RE.match(result_id or ""):
        raise HTTPException(status_code=404, detail=not_found)
    return directory / f"{result_id}.json"


def audit_path(result_id: str) -> Path:
    return result_path(OUTPUT_DIR, result_id, "Hasil analisis tidak ditemukan.")


def requirements_path(result_id: str) -> Path:
    return result_path(
        REQUIREMENTS_OUTPUT_DIR, result_id, "Hasil gap analysis tidak ditemukan."
    )


def compliance_path(result_id: str) -> Path:
    return result_path(
        COMPLIANCE_OUTPUT_DIR, result_id, "Hasil compliance review tidak ditemukan."
    )


def load_json_result(path: Path, not_found: str) -> tuple[Path, dict]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=not_found)
    try:
        data = read_json(path)
    except Exception as exc:
        logger.exception("Gagal membaca %s", path)
        raise HTTPException(status_code=500, detail="Gagal membaca file hasil.") from exc
    return path, data


def load_result_file(result_id: str) -> tuple[Path, dict]:
    return load_json_result(audit_path(result_id), "Hasil analisis tidak ditemukan.")


def load_requirements_file(result_id: str) -> tuple[Path, dict]:
    return load_json_result(
        requirements_path(result_id), "Hasil gap analysis tidak ditemukan."
    )


def load_compliance_result(result_id: str) -> tuple[Path, dict]:
    return load_json_result(
        compliance_path(result_id), "Hasil compliance review tidak ditemukan."
    )


def save_result_file(path: Path, data: dict) -> None:
    write_json_atomic(path, data)


# Dependency lock untuk endpoint read-modify-write. Dijalankan di event loop
# (async generator) supaya acquire & release terjadi di thread yang sama.
# Handler di event loop tidak saling interleave (body-nya tanpa await), jadi
# lock ini terutama menjaga dari penulisan oleh job background di thread lain.
async def lock_audit_result(result_id: str) -> AsyncIterator[None]:
    with locked(audit_path(result_id)):
        yield


async def lock_requirements_result(result_id: str) -> AsyncIterator[None]:
    with locked(requirements_path(result_id)):
        yield


async def lock_compliance_result(result_id: str) -> AsyncIterator[None]:
    with locked(compliance_path(result_id)):
        yield


def submit_job(kind: str, worker: Worker, total: int) -> JobAcceptedResponse:
    rec = get_job_manager().submit(kind, worker, total=total)
    return JobAcceptedResponse(
        job_id=rec.job_id,
        kind=rec.kind,
        status=rec.status,
        status_url=f"/api/jobs/{rec.job_id}",
    )


def extract_text(path: Path, extension: str) -> str:
    """Ekstraksi teks (sinkron, berat) — panggil lewat run_in_threadpool."""
    if extension == ".pdf":
        return extract_pdf_text(str(path))
    return extract_txt_text(str(path))


def extract_bytes(data: bytes, extension: str) -> str:
    """
    Ekstraksi teks dari isi file upload lewat file sementara yang LANGSUNG
    dihapus. File upload (bisa berisi kontrak rahasia) tidak pernah disimpan
    permanen; yang di-cache hanya hasil parse-nya (dengan TTL).
    """
    with tempfile.TemporaryDirectory(prefix="raa_upload_") as tmp:
        path = Path(tmp) / f"upload{extension}"
        path.write_bytes(data)
        return extract_text(path, extension)


# ===========================================================================
# LAYANAN AI (gagal cepat 422 kalau API key belum diisi)
# ===========================================================================

def ai_provider_or_422() -> AIProvider:
    try:
        return get_ai_provider()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def embedder_or_422() -> EmbeddingService:
    try:
        return EmbeddingService()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ===========================================================================
# UPLOAD
# ===========================================================================

async def read_upload(file: UploadFile, label: str = "File") -> tuple[bytes, str]:
    """
    Validasi & baca file upload (format .pdf/.txt, tidak kosong, ukuran maks).
    Return (isi file, ekstensi). `label` dipakai di pesan error ("Kontrak", dst.).
    """
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format {label.lower()} tidak didukung: '{extension}'. Gunakan .pdf atau .txt.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"{label} kosong.")
    max_size_mb = settings.max_upload_size_mb
    if len(data) > max_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"Ukuran {label.lower()} melebihi batas {max_size_mb} MB.",
        )
    return data, extension
