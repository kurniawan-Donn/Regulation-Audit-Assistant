"""
Preview Cache + File-Level Parse Cache.

Dua lapisan cache:

1. cache/previews/{preview_id}.json
   - Key: UUID random per upload
   - TTL: 24 jam
   - Dipakai untuk: re-analyze tanpa upload ulang (dalam 1 session)

2. cache/parsed/{sha256}.json
   - Key: SHA-256 dari byte content file
   - TTL: 7 hari
   - Dipakai untuk: skip parsing kalau file yang sama di-upload lagi
   - Komplemen dari lapisan 1, bukan replacement

Alur di /api/preview:
    file_bytes → hash → cek cache/parsed/{hash}.json
        ├─ ada    → load (skip parsing)
        └─ tidak  → parse, lalu save ke cache
    → lalu selalu save ke cache/previews/{uuid}.json (untuk re-analyze)
"""

import hashlib
import json
import time
import uuid
from pathlib import Path

from app.services.regulation_parser import PARSER_VERSION

PREVIEW_DIR = Path("cache/previews")
PARSED_DIR = Path("cache/parsed")

COMPLIANCE_PREVIEW_DIR = Path("cache/compliance_previews")

PREVIEW_TTL_SECONDS = 24 * 3600        # 24 jam
PARSED_TTL_SECONDS = 7 * 24 * 3600     # 7 hari
# Preview compliance dipakai ulang oleh "Analisis Sekarang" pada hasil yang
# sudah ada, jadi umurnya lebih panjang dari preview biasa.
COMPLIANCE_PREVIEW_TTL_SECONDS = 7 * 24 * 3600


# ===========================================================================
# LAPISAN 1 — Preview per session
# ===========================================================================

def generate_preview_id() -> str:
    return uuid.uuid4().hex


def _preview_path(preview_id: str) -> Path:
    return PREVIEW_DIR / f"{preview_id}.json"


def save_preview(
    preview_id: str,
    filename: str,
    cleaned_text: str,
    chunks: list[dict],
    tree: list[dict],
) -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    path = _preview_path(preview_id)
    payload = {
        "preview_id": preview_id,
        "filename": filename,
        "cleaned_text": cleaned_text,
        "chunks": chunks,
        "tree": tree,
        "created_at": time.time(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def load_preview(preview_id: str) -> dict | None:
    if not preview_id or not preview_id.isalnum():
        return None
    path = _preview_path(preview_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_preview(preview_id: str) -> None:
    path = _preview_path(preview_id)
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


# ===========================================================================
# LAPISAN 2 — Parsed by file hash
# ===========================================================================

def compute_file_hash(file_bytes: bytes) -> str:
    """Hitung SHA-256 dari byte content file."""
    return hashlib.sha256(file_bytes).hexdigest()


def _parsed_path(file_hash: str) -> Path:
    return PARSED_DIR / f"{file_hash}.json"


def load_parsed_by_hash(file_hash: str) -> dict | None:
    """
    Ambil hasil parsing dari cache berdasarkan hash file.
    Return None kalau tidak ada, sudah expired, atau error.
    """
    if not file_hash or len(file_hash) != 64:
        return None
    path = _parsed_path(file_hash)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        created = data.get("created_at", 0)
        # Hasil parse dari versi parser lain dianggap basi: perbaikan parser
        # harus langsung berlaku, bukan menunggu TTL 7 hari.
        stale = (
            time.time() - created > PARSED_TTL_SECONDS
            or data.get("parser_version") != PARSER_VERSION
        )
        if stale:
            path.unlink(missing_ok=True)
            return None
        return data
    except Exception:
        return None


def save_parsed_by_hash(
    file_hash: str,
    filename: str,
    cleaned_text: str,
    chunks: list[dict],
    tree: list[dict],
) -> Path:
    """Simpan hasil parsing ke cache berdasarkan hash file."""
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    path = _parsed_path(file_hash)
    payload = {
        "file_hash": file_hash,
        "parser_version": PARSER_VERSION,
        "filename": filename,
        "cleaned_text": cleaned_text,
        "chunks": chunks,
        "tree": tree,
        "created_at": time.time(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def get_parsed_cache_stats() -> dict:
    """Statistik cache parsed untuk endpoint diagnostik."""
    if not PARSED_DIR.exists():
        return {"count": 0, "size_mb": 0.0}
    count = 0
    size = 0
    for f in PARSED_DIR.glob("*.json"):
        count += 1
        try:
            size += f.stat().st_size
        except Exception:
            pass
    return {
        "count": count,
        "size_mb": round(size / (1024 * 1024), 2),
    }


# ===========================================================================
# CLEANUP
# ===========================================================================

def _remove_older_than(directory: Path, pattern: str, ttl_seconds: int, now: float) -> int:
    removed = 0
    if not directory.exists():
        return 0
    for f in directory.glob(pattern):
        try:
            if now - f.stat().st_mtime > ttl_seconds:
                f.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def cleanup_expired() -> int:
    """
    Hapus cache yang kedaluwarsa. Return total file terhapus.

    Termasuk preview Compliance Review (berisi teks kontrak lengkap + embedding
    regulasi) — data sensitif yang tidak boleh menumpuk tanpa batas.
    """
    now = time.time()
    return (
        _remove_older_than(PREVIEW_DIR, "*.json", PREVIEW_TTL_SECONDS, now)
        + _remove_older_than(PARSED_DIR, "*.json", PARSED_TTL_SECONDS, now)
        + _remove_older_than(COMPLIANCE_PREVIEW_DIR, "*.json", COMPLIANCE_PREVIEW_TTL_SECONDS, now)
        + _remove_older_than(COMPLIANCE_PREVIEW_DIR, "*.npy", COMPLIANCE_PREVIEW_TTL_SECONDS, now)
    )
