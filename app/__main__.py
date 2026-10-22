"""
Jalankan server: `python -m app`

Host/port dari .env (HOST, PORT; default 127.0.0.1:8000 — hanya komputer ini).
Bind ke alamat jaringan (mis. 0.0.0.0) DITOLAK kalau APP_PASSWORD kosong,
kecuali ALLOW_INSECURE_REMOTE=true.
"""

import sys

import uvicorn

from app.config import settings
from app.security import is_loopback_host


def main() -> int:
    if not is_loopback_host(settings.host) and not settings.app_password:
        if not settings.allow_insecure_remote:
            print(
                f"Menolak menjalankan di {settings.host}: aplikasi akan terbuka untuk "
                "jaringan TANPA autentikasi.\n"
                "Isi APP_PASSWORD di .env (dan pasang HTTPS), atau gunakan HOST=127.0.0.1.",
                file=sys.stderr,
            )
            return 1
        print("PERINGATAN: berjalan di jaringan tanpa autentikasi (ALLOW_INSECURE_REMOTE=true).",
              file=sys.stderr)

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
