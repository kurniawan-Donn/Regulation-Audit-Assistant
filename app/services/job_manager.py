"""
Job Manager — menjalankan analisis AI yang lama di background thread.

Kenapa:
Analisis dokumen besar bisa makan 15–30 menit. Sebelumnya dijalankan
langsung di request HTTP (dan memblokir event loop), sehingga server
tidak merespons siapa pun, progress bar hanya simulasi, dan hasil hilang
kalau koneksi putus. Sekarang:

    POST /api/analyze  ->  202 {job_id}
    GET  /api/jobs/{job_id}         -> status + progres nyata
    POST /api/jobs/{job_id}/cancel  -> minta berhenti di batas batch berikutnya

Desain:
- ThreadPoolExecutor dengan worker terbatas (default 1) → job antre,
  sekaligus menjaga rate limit Gemini tidak dilanggar oleh job paralel.
- State job disimpan di memori DAN di cache/jobs/{id}.json (atomik),
  supaya status tetap bisa dibaca setelah halaman di-reload.
- Saat server start, job yang tercatat "queued/running" ditandai gagal
  (thread-nya sudah mati bersama proses lama).
- Pembatalan bersifat kooperatif: worker memanggil ctx.check_cancelled()
  di antara batch. Worker boleh menyimpan hasil parsial.
"""

import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.services.json_store import read_json, write_json_atomic

logger = logging.getLogger(__name__)

JOBS_DIR = Path("cache/jobs")
JOB_TTL_SECONDS = 7 * 24 * 3600

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

ACTIVE_STATUSES = {STATUS_QUEUED, STATUS_RUNNING}


class JobCancelled(Exception):
    """Dilempar oleh ctx.check_cancelled() saat user membatalkan job."""


class JobFailure(Exception):
    """Kegagalan yang pesannya aman & berguna untuk ditampilkan ke user."""


@dataclass
class JobOutcome:
    """Nilai kembali worker."""
    result_id: str | None = None
    result_url: str | None = None
    message: str = ""
    # True jika worker berhenti karena dibatalkan tapi tetap menyimpan hasil parsial.
    cancelled: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobRecord:
    job_id: str
    kind: str
    status: str = STATUS_QUEUED
    progress_done: int = 0
    progress_total: int = 0
    message: str = "Menunggu giliran..."
    result_id: str | None = None
    result_url: str | None = None
    error: str | None = None
    partial: bool = False
    cancel_requested: bool = False
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class JobContext:
    """Handle yang diterima worker untuk melapor progres & cek pembatalan."""

    def __init__(self, manager: "JobManager", job_id: str, cancel_event: threading.Event):
        self._manager = manager
        self.job_id = job_id
        self._cancel_event = cancel_event

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise JobCancelled()

    def progress(
        self,
        done: int | None = None,
        total: int | None = None,
        message: str | None = None,
    ) -> None:
        self._manager._update(
            self.job_id,
            progress_done=done,
            progress_total=total,
            message=message,
        )


Worker = Callable[[JobContext], JobOutcome]


class JobManager:
    def __init__(self, max_workers: int = 1, jobs_dir: Path = JOBS_DIR):
        self._jobs_dir = jobs_dir
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers), thread_name_prefix="job"
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._futures: dict[str, Future] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _path(self, job_id: str) -> Path:
        return self._jobs_dir / f"{job_id}.json"

    def _persist(self, rec: JobRecord) -> None:
        try:
            write_json_atomic(self._path(rec.job_id), asdict(rec), indent=None)
        except Exception as exc:  # status di memori tetap valid
            logger.warning("Gagal simpan status job %s: %s", rec.job_id, exc)

    def _update(self, job_id: str, **changes: Any) -> JobRecord | None:
        # Persist di dalam lock: kalau ditulis di luar lock, update dari dua
        # thread (worker vs. cancel) bisa tersimpan terbalik → status basi di disk.
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return None
            for key, value in changes.items():
                if value is not None:
                    setattr(rec, key, value)
            snapshot = JobRecord(**asdict(rec))
            self._persist(snapshot)
        return snapshot

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self,
        kind: str,
        worker: Worker,
        total: int = 0,
        message: str = "Menunggu giliran...",
        extra: dict[str, Any] | None = None,
    ) -> JobRecord:
        job_id = uuid.uuid4().hex
        rec = JobRecord(
            job_id=job_id,
            kind=kind,
            progress_total=total,
            message=message,
            extra=dict(extra or {}),
        )
        cancel_event = threading.Event()
        with self._lock:
            self._jobs[job_id] = rec
            self._cancel_events[job_id] = cancel_event
        self._persist(rec)

        ctx = JobContext(self, job_id, cancel_event)
        future = self._executor.submit(self._run, job_id, worker, ctx)
        with self._lock:
            self._futures[job_id] = future
        logger.info("Job %s (%s) diantrikan.", job_id, kind)
        return JobRecord(**asdict(rec))

    def get(self, job_id: str) -> dict[str, Any] | None:
        if not _JOB_ID_RE.match(job_id or ""):
            return None
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is not None:
                data = asdict(rec)
                data["queue_position"] = self._queue_position_locked(rec)
                return data
        path = self._path(job_id)
        if not path.exists():
            return None
        try:
            data = read_json(path)
        except Exception:
            return None
        data["queue_position"] = 0
        return data

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        if not _JOB_ID_RE.match(job_id or ""):
            return None
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                return self.get(job_id)
            if rec.status not in ACTIVE_STATUSES:
                return asdict(rec)
            rec.cancel_requested = True
            self._cancel_events[job_id].set()
            future = self._futures.get(job_id)
            queued = rec.status == STATUS_QUEUED
        if queued and future is not None and future.cancel():
            self._update(
                job_id,
                status=STATUS_CANCELLED,
                message="Dibatalkan sebelum mulai.",
                finished_at=time.time(),
            )
        else:
            self._update(job_id, message="Membatalkan... (menunggu batch berjalan selesai)")
        return self.get(job_id)

    def list_active(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {**asdict(r), "queue_position": self._queue_position_locked(r)}
                for r in self._jobs.values()
                if r.status in ACTIVE_STATUSES
            ]

    def shutdown(self) -> None:
        with self._lock:
            events = list(self._cancel_events.values())
        for ev in events:
            ev.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _queue_position_locked(self, rec: JobRecord) -> int:
        if rec.status != STATUS_QUEUED:
            return 0
        ahead = [
            r for r in self._jobs.values()
            if r.status in ACTIVE_STATUSES and r.created_at < rec.created_at
        ]
        return len(ahead) + 1

    def _run(self, job_id: str, worker: Worker, ctx: JobContext) -> None:
        if ctx.cancelled:
            self._update(
                job_id, status=STATUS_CANCELLED,
                message="Dibatalkan sebelum mulai.", finished_at=time.time(),
            )
            return

        self._update(
            job_id, status=STATUS_RUNNING,
            message="Memulai...", started_at=time.time(),
        )
        try:
            outcome = worker(ctx)
        except JobCancelled:
            self._update(
                job_id, status=STATUS_CANCELLED,
                message="Dibatalkan oleh pengguna.", finished_at=time.time(),
            )
            return
        except JobFailure as exc:
            self._update(
                job_id, status=STATUS_FAILED, error=str(exc),
                message="Gagal.", finished_at=time.time(),
            )
            return
        except Exception:
            error_id = uuid.uuid4().hex[:8]
            logger.exception("Job %s gagal tak terduga [%s]", job_id, error_id)
            self._update(
                job_id, status=STATUS_FAILED,
                error=(
                    f"Terjadi kesalahan internal (kode: {error_id}). "
                    "Detail tercatat di log server."
                ),
                message="Gagal.", finished_at=time.time(),
            )
            return

        status = STATUS_CANCELLED if outcome.cancelled else STATUS_SUCCEEDED
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is not None:
                rec.extra.update(outcome.extra)
        self._update(
            job_id,
            status=status,
            result_id=outcome.result_id,
            result_url=outcome.result_url,
            partial=outcome.cancelled and bool(outcome.result_id),
            message=outcome.message or ("Dibatalkan." if outcome.cancelled else "Selesai."),
            finished_at=time.time(),
        )

    def recover_and_cleanup(self) -> None:
        """Tandai job yatim dari proses sebelumnya sebagai gagal; hapus yang kedaluwarsa."""
        if not self._jobs_dir.exists():
            return
        now = time.time()
        for path in self._jobs_dir.glob("*.json"):
            try:
                data = read_json(path)
            except Exception:
                continue
            if now - float(data.get("created_at") or 0) > JOB_TTL_SECONDS:
                path.unlink(missing_ok=True)
                continue
            if data.get("status") in ACTIVE_STATUSES and data.get("job_id") not in self._jobs:
                data["status"] = STATUS_FAILED
                data["error"] = "Server di-restart saat job berjalan. Silakan jalankan ulang."
                data["message"] = "Gagal."
                data["finished_at"] = now
                try:
                    write_json_atomic(path, data, indent=None)
                except Exception:
                    pass


_manager: JobManager | None = None
_manager_guard = threading.Lock()


def get_job_manager() -> JobManager:
    global _manager
    with _manager_guard:
        if _manager is None:
            from app.config import settings
            _manager = JobManager(max_workers=settings.max_concurrent_jobs)
        return _manager


def shutdown_job_manager() -> None:
    """Hentikan executor (dipanggil saat aplikasi shutdown)."""
    global _manager
    with _manager_guard:
        manager, _manager = _manager, None
    if manager is not None:
        manager.shutdown()
