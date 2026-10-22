"""
Riwayat analisis dari hasil yang tersimpan di server (outputs/).

Sebelumnya riwayat hanya hidup di localStorage browser — hilang saat cache
dibersihkan, tidak terlihat dari browser lain, dan bisa melampaui kuota ±5 MB.
Sumber kebenaran sekarang file hasil itu sendiri; modul ini hanya meringkasnya.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.services.json_store import locked, read_json

logger = logging.getLogger(__name__)

# Folder yang sama dengan tempat worker analysis_jobs menulis hasil.
OUTPUT_DIR = Path("outputs")
KIND_DIRS: dict[str, Path] = {
    "regulation_audit": OUTPUT_DIR,
    "gap_analysis": OUTPUT_DIR / "requirements",
    "compliance_review": OUTPUT_DIR / "compliance",
}
ID_RE = re.compile(r"^[0-9a-f]{32}$")

# Ringkasan per file di-cache berdasarkan (mtime, size): daftar riwayat sering
# dibuka, file hasil bisa ratusan KB dan jarang berubah.
_cache: dict[str, tuple[tuple[float, int], dict]] = {}
_cache_lock = threading.Lock()


class UnknownKind(ValueError):
    pass


def _summarize(kind: str, data: dict) -> tuple[str, dict]:
    """(nama, statistik) untuk satu hasil."""
    if kind == "regulation_audit":
        return data.get("filename") or "Tanpa nama", {
            "total_ketentuan": int(data.get("total_ketentuan") or 0),
            "total_valid": int(data.get("total_valid") or 0),
            "total_flagged": int(data.get("total_flagged") or 0),
        }
    if kind == "gap_analysis":
        reqs = data.get("requirements") or []
        statuses = [str(r.get("status_gap") or "").strip().lower() for r in reqs]
        return data.get("filename") or "Tanpa nama", {
            "total_requirements": int(data.get("total_requirements") or len(reqs)),
            "total_dinilai": sum(1 for s in statuses if s),
            "total_perlu_tindak": sum(1 for s in statuses if s.startswith("tidak")),
        }
    return data.get("contract_filename") or "Compliance Review", {
        "total_items": int(data.get("total_items") or 0),
        "total_patuh": int(data.get("total_patuh") or 0),
        "total_patuh_catatan": int(data.get("total_patuh_catatan") or 0),
        "total_tidak_patuh": int(data.get("total_tidak_patuh") or 0),
        "total_tidak_relevan": int(data.get("total_tidak_relevan") or 0),
        "total_perlu_verifikasi": int(data.get("total_perlu_verifikasi") or 0),
    }


def _iso_from_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _entry(kind: str, path: Path) -> dict | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    key = str(path.resolve())
    sig = (stat.st_mtime, stat.st_size)
    with _cache_lock:
        cached = _cache.get(key)
    if cached and cached[0] == sig:
        return cached[1]

    try:
        data = read_json(path)
    except Exception:  # file rusak / sedang ditulis — lewati, jangan gagalkan daftar
        logger.warning("Riwayat: gagal membaca %s", path)
        return None

    nama, stats = _summarize(kind, data)
    updated_at = _iso_from_ts(stat.st_mtime)
    entry = {
        "id": path.stem,
        "type": kind,
        "nama": nama,
        # created_at baru ada sejak riwayat server; hasil lama memakai waktu file.
        "tanggal": data.get("created_at") or updated_at,
        "updated_at": updated_at,
        "stats": stats,
        "regulation_filenames": list(data.get("regulation_filenames") or []),
    }
    with _cache_lock:
        _cache[key] = (sig, entry)
    return entry


def list_history(limit: int | None = None) -> list[dict]:
    """Semua hasil tersimpan, terbaru dulu."""
    entries: list[dict] = []
    for kind, directory in KIND_DIRS.items():
        if not directory.is_dir():
            continue
        for path in directory.glob("*.json"):
            if not ID_RE.match(path.stem):
                continue
            entry = _entry(kind, path)
            if entry:
                entries.append(entry)
    entries.sort(key=lambda e: e["tanggal"], reverse=True)
    return entries[:limit] if limit else entries


def _result_files(kind: str, result_id: str) -> list[Path]:
    directory = KIND_DIRS[kind]
    # ID tervalidasi ketat (32 hex) → glob tidak bisa keluar dari folder.
    return [p for p in directory.glob(f"{result_id}.*") if p.is_file()]


def delete_result(kind: str, result_id: str) -> bool:
    """Hapus hasil beserta file ekspornya (.xlsx/.pdf). False kalau tidak ada."""
    if kind not in KIND_DIRS:
        raise UnknownKind(kind)
    if not ID_RE.match(result_id or ""):
        return False
    json_path = KIND_DIRS[kind] / f"{result_id}.json"
    if not json_path.exists():
        return False
    with locked(json_path):
        for path in _result_files(kind, result_id):
            path.unlink(missing_ok=True)
    with _cache_lock:
        _cache.pop(str(json_path.resolve()), None)
    logger.info("Riwayat: hasil %s %s dihapus", kind, result_id)
    return True


def clear_history() -> int:
    """Hapus semua hasil tersimpan. Mengembalikan jumlah hasil yang dihapus."""
    count = 0
    for entry in list_history():
        if delete_result(entry["type"], entry["id"]):
            count += 1
    return count
