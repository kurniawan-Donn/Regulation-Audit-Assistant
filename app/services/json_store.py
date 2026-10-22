"""
JSON Store — baca/tulis file JSON secara aman.

Dua jaminan:
1. Atomik: tulis ke file sementara di folder yang sama lalu os.replace().
   Kalau proses mati di tengah penulisan, file lama tetap utuh (tidak
   pernah ada file JSON setengah jadi).
2. Lock per file: operasi read-modify-write (edit sel, bulk update,
   hasil job background) diserialkan per path, jadi dua penulis tidak
   saling menimpa perubahan.

Lock bersifat in-process (threading). Cukup untuk 1 proses uvicorn;
untuk multi-worker perlu storage yang sesungguhnya (DB).
"""

import json
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = os.path.normcase(str(Path(path).resolve()))
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Kunci eksklusif untuk satu file JSON (re-entrant)."""
    lock = _lock_for(path)
    with lock:
        yield


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _replace_with_retry(src: str, dst: Path, attempts: int = 10) -> None:
    """
    os.replace() dengan retry singkat.

    Di Windows, replace ditolak (PermissionError/WinError 5) selama file
    tujuan sedang dibuka proses/thread lain — mis. request GET yang sedang
    membaca hasil, atau antivirus/indexer. Kondisi ini sementara.
    """
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.02 * (attempt + 1))


def write_text_atomic(path: Path, text: str) -> None:
    """Tulis teks secara atomik (temp file di folder yang sama + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_json_atomic(path: Path, data: Any, indent: int | None = 2) -> None:
    """Tulis JSON secara atomik."""
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=indent))


def update_json(path: Path, mutate: Callable[[Any], Any]) -> Any:
    """
    Read-modify-write di bawah lock.

    `mutate(data)` boleh mengubah data in-place dan/atau mengembalikan
    nilai apa pun; nilai itu diteruskan sebagai return value.
    """
    with locked(path):
        data = read_json(path)
        result = mutate(data)
        write_json_atomic(path, data)
        return result
