"""
Keamanan dasar aplikasi.

1. Autentikasi (opsional, aktif kalau APP_PASSWORD diisi):
   HTTP Basic Auth untuk SELURUH aplikasi (UI, API, file export), kecuali
   /health. Browser menampilkan dialog login bawaan dan otomatis mengirim
   kredensial untuk request berikutnya — tidak perlu halaman login.
   Gunakan di balik HTTPS (reverse proxy) kalau diakses lewat jaringan.

2. Anti-CSRF:
   Request yang mengubah data (POST/PUT/PATCH/DELETE ke /api) wajib membawa
   header `X-Requested-With: RAA`. Situs lain tidak bisa menambahkan header
   custom pada request lintas-origin tanpa izin CORS (yang tidak kita buka),
   sehingga browser korban tidak bisa dipakai untuk memicu aksi — penting
   karena Basic Auth dikirim otomatis oleh browser.

3. Security headers standar di semua response; response /api tidak di-cache.
"""

import base64
import binascii
import ipaddress
import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

logger = logging.getLogger(__name__)

CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "RAA"

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_PUBLIC_PATHS = {"/health"}

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}


def auth_enabled() -> bool:
    return bool(settings.app_password)


def is_loopback_host(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _credentials_ok(header_value: str | None) -> bool:
    if not header_value or not header_value.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header_value[6:].strip()).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    username, sep, password = decoded.partition(":")
    if not sep:
        return False
    # compare_digest untuk keduanya: waktu respons tidak membocorkan isi.
    user_ok = secrets.compare_digest(username.encode(), settings.app_username.encode())
    pass_ok = secrets.compare_digest(password.encode(), settings.app_password.encode())
    return user_ok and pass_ok


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if auth_enabled() and path not in _PUBLIC_PATHS:
            if not _credentials_ok(request.headers.get("authorization")):
                return self._with_headers(JSONResponse(
                    {"detail": "Autentikasi diperlukan."},
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Audit Assistant", charset="UTF-8"'},
                ), path)

        if (
            path.startswith("/api/")
            and request.method not in _SAFE_METHODS
            and request.headers.get(CSRF_HEADER) != CSRF_VALUE
        ):
            logger.warning("Request %s %s ditolak: header anti-CSRF tidak ada.", request.method, path)
            return self._with_headers(JSONResponse(
                {"detail": "Permintaan ditolak: header keamanan tidak ada. Muat ulang halaman."},
                status_code=403,
            ), path)

        response = await call_next(request)
        return self._with_headers(response, path)

    @staticmethod
    def _with_headers(response: Response, path: str) -> Response:
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
