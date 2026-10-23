"""
Runtime Settings Service.

Menyimpan konfigurasi user di data/settings.json (di luar .env).
Prioritas: runtime settings > .env > default.

API key di-mask saat keluar (hanya tampil 6 karakter awal + 4 akhir).
"""

import json
import logging
from pathlib import Path
from typing import Any

from app.config import settings as env_settings

logger = logging.getLogger(__name__)

SETTINGS_DIR = Path("data")
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

# Default values — dipakai kalau file tidak ada
_DEFAULTS: dict[str, Any] = {
    "gemini_api_key": "",
    "gemini_model": "gemini-3.7-flash",
    "gemini_max_output_tokens": 8192,
    "gemini_min_seconds_between_requests": 4.5,
    "max_chars_per_batch": 6000,
    "theme": "auto",
}

# Field yang boleh di-update user lewat UI
EDITABLE_FIELDS = {
    "gemini_api_key",
    "gemini_model",
    "gemini_max_output_tokens",
    "gemini_min_seconds_between_requests",
    "max_chars_per_batch",
    "theme",
}

# Preset model yang direkomendasikan
PRESET_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]


def _ensure_dir() -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    """
    Baca settings.json. Kalau file tidak ada, buat dengan default.
    Fallback ke .env untuk field yang belum di-set di file.
    """
    _ensure_dir()

    if not SETTINGS_FILE.exists():
        # Inisialisasi dari .env
        initial = dict(_DEFAULTS)
        initial["gemini_api_key"] = env_settings.gemini_api_key or ""
        initial["gemini_model"] = env_settings.gemini_model or _DEFAULTS["gemini_model"]
        initial["gemini_max_output_tokens"] = env_settings.gemini_max_output_tokens
        initial["gemini_min_seconds_between_requests"] = env_settings.gemini_min_seconds_between_requests
        initial["max_chars_per_batch"] = env_settings.max_chars_per_batch
        _write_raw(initial)
        return initial

    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Gagal baca settings.json: %s. Pakai default.", exc)
        return dict(_DEFAULTS)

    # Merge dengan default (kalau ada field baru)
    merged = dict(_DEFAULTS)
    merged.update(data)
    return merged


def _write_raw(data: dict[str, Any]) -> None:
    _ensure_dir()
    SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """
    Update settings.json dengan field yang diizinkan.
    Return settings setelah update (dengan API key di-mask).
    """
    current = load_settings()

    for key, value in updates.items():
        if key not in EDITABLE_FIELDS:
            continue
        if value is None:
            continue
        # Kalau user kirim API key kosong, jangan timpa (biar tidak sengaja kosongkan)
        if key == "gemini_api_key" and isinstance(value, str) and not value.strip():
            continue
        current[key] = value

    _write_raw(current)
    return current


def mask_api_key(key: str) -> str:
    """Mask API key: 'AQ.abc...xyz' -> 'AQ.ab...wxyz'."""
    if not key:
        return ""
    if len(key) <= 12:
        return "****"
    return f"{key[:6]}...{key[-4:]}"


def get_settings_masked() -> dict[str, Any]:
    """Ambil settings dengan API key di-mask (untuk response API)."""
    data = load_settings()
    masked = dict(data)
    # Status key harus sama dengan yang benar-benar dipakai AI: key dari .env /
    # variabel lingkungan (server tim, demo) juga dihitung, bukan hanya isian UI.
    key = get_effective_settings().get("gemini_api_key", "") or ""
    masked["gemini_api_key_masked"] = mask_api_key(key)
    masked["gemini_api_key_set"] = bool(key.strip())
    masked.pop("gemini_api_key", None)  # jangan kirim raw key ke frontend
    return masked


def get_effective_settings() -> dict[str, Any]:
    """
    Ambil settings efektif untuk dipakai service lain (dengan key asli).
    Priority: settings.json > .env > default.
    """
    data = load_settings()

    # Fallback ke .env kalau field kosong
    if not data.get("gemini_api_key"):
        data["gemini_api_key"] = env_settings.gemini_api_key or ""
    if not data.get("gemini_model"):
        data["gemini_model"] = env_settings.gemini_model or _DEFAULTS["gemini_model"]

    return data