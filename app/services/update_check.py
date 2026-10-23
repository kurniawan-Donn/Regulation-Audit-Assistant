"""
Pengecekan pembaruan aplikasi dari GitHub Releases.

Membandingkan versi yang berjalan dengan rilis terbaru di repositori dan
mengembalikan tautan unduhan yang cocok dengan cara aplikasi dipasang
(installer → Setup.exe, portable → ZIP, lainnya → halaman rilis).

Hasil disimpan di memori beberapa jam agar GitHub tidak dipanggil setiap kali
halaman dibuka; kegagalan jaringan tidak pernah mengganggu aplikasi.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any

import httpx

from app.config import settings
from app.version import __version__

logger = logging.getLogger(__name__)

CACHE_TTL_S = 6 * 60 * 60
ERROR_CACHE_TTL_S = 30 * 60
REQUEST_TIMEOUT_S = 4.0
NOTES_MAX_CHARS = 1500

# Cara aplikasi dipasang — diisi peluncur (scripts/launch.py) atau Dockerfile.
INSTALL_KIND_ENV = "AUDIT_ASSISTANT_INSTALL"
ASSET_SUFFIX = {"installer": "-Setup.exe", "portable": "-Portable.zip"}

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")

_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "ttl": 0.0, "result": None}


def parse_version(text: str) -> tuple[int, int, int] | None:
    """'v1.2.3' / '1.2.3-beta' -> (1, 2, 3); None bila bukan versi."""
    m = _VERSION_RE.match((text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a and b and a > b)


def install_kind() -> str:
    kind = os.environ.get(INSTALL_KIND_ENV, "").strip().lower()
    return kind if kind in ("installer", "portable", "docker") else "source"


def _download_url(release: dict, kind: str) -> str:
    suffix = ASSET_SUFFIX.get(kind)
    if suffix:
        for asset in release.get("assets") or []:
            if str(asset.get("name", "")).endswith(suffix):
                return asset.get("browser_download_url") or release.get("html_url", "")
    return release.get("html_url", "")


def _base_result() -> dict[str, Any]:
    return {
        "enabled": True,
        "current": __version__,
        "latest": None,
        "update_available": False,
        "url": None,
        "notes": "",
        "published_at": None,
        "install_kind": install_kind(),
        "error": None,
    }


def _fetch_latest() -> dict:
    url = f"https://api.github.com/repos/{settings.update_repo}/releases/latest"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"audit-assistant/{__version__}"}
    with httpx.Client(timeout=REQUEST_TIMEOUT_S, follow_redirects=True) as client:
        res = client.get(url, headers=headers)
    if res.status_code == 404:
        return {}                               # belum ada rilis
    res.raise_for_status()
    return res.json()


def check_for_update(force: bool = False) -> dict[str, Any]:
    """Status pembaruan (dari cache bila masih segar, kecuali force)."""
    result = _base_result()
    if not settings.update_check or settings.demo_mode:
        result["enabled"] = False
        return result

    with _lock:
        cached = _cache["result"]
        if not force and cached is not None and time.time() - _cache["at"] < _cache["ttl"]:
            return dict(cached)

        ttl = CACHE_TTL_S
        try:
            release = _fetch_latest()
            tag = str(release.get("tag_name") or "")
            if parse_version(tag):
                latest = ".".join(str(x) for x in parse_version(tag))  # type: ignore[union-attr]
                result.update(
                    latest=latest,
                    update_available=is_newer(latest, __version__),
                    url=_download_url(release, result["install_kind"]),
                    notes=(release.get("body") or "")[:NOTES_MAX_CHARS],
                    published_at=release.get("published_at"),
                )
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("Cek pembaruan gagal: %s", exc)
            result["error"] = "Tidak dapat menghubungi GitHub untuk mengecek pembaruan."
            ttl = ERROR_CACHE_TTL_S

        _cache.update(at=time.time(), ttl=ttl, result=dict(result))
        return result


def reset_cache() -> None:
    with _lock:
        _cache.update(at=0.0, ttl=0.0, result=None)
