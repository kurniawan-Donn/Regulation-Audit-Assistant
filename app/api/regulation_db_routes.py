"""
API Routes untuk Regulation Database (RAG).

Endpoint:
- GET    /api/regulation-db/regulations         -> list semua regulasi
- POST   /api/regulation-db/upload              -> upload + index regulasi (202 + job_id; 409 kalau duplikat)
- POST   /api/regulation-db/regulations/{id}/reindex -> index ulang dari file sumber (202 + job_id)
- DELETE /api/regulation-db/regulations/{id}    -> hapus regulasi
- GET    /api/regulation-db/stats               -> statistik DB
- POST   /api/regulation-db/reset               -> reset DB (hapus semua)
- POST   /api/regulation-db/search              -> test retrieval (debug)
"""
import hashlib
import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.common import embedder_or_422, read_upload
from app.models.schemas import (
    JobAcceptedResponse,
    ListRegulationsResponse,
    RegulationDBStatsResponse,
    RegulationMeta,
    ResetDBRequest,
    ResetDBResponse,
    SearchDBResponse,
    SearchDBRequest,
    SearchDBResultItem,
    RegulationChunkItem,
    RegulationChunksResponse,
    RegulationChunksStats,
)
from app.services.analysis_jobs import (
    make_regulation_index_worker,
    make_regulation_reindex_worker,
    parse_regulation_file,
)
from app.services.embedding_service import EmbeddingError, EmbeddingService
from app.services.job_manager import get_job_manager
from app.services.pdf_parser import PDFExtractionError
from app.services.regulation_db import (
    RegulationDBError,
    delete_regulation,
    find_by_sha256,
    get_db_stats,
    get_regulation,
    list_regulations,
    query_relevant_chunks,
    reset_database,
)
from app.services.text_processor import TextExtractionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/regulation-db", tags=["regulation-db"])

RESET_CONFIRMATION = "HAPUS SEMUA"

ALLOWED_EXTENSIONS = {".pdf", ".txt"}


# =============================================================================
# LIST
# =============================================================================

@router.get("/regulations", response_model=ListRegulationsResponse)
async def get_regulations() -> ListRegulationsResponse:
    """List semua regulasi yang sudah di-index."""
    regs = list_regulations()
    return ListRegulationsResponse(
        regulations=[RegulationMeta(**r) for r in regs],
        total=len(regs),
    )

@router.get(
    "/regulations/{regulation_id}/chunks",
    response_model=RegulationChunksResponse,
)
async def get_regulation_chunks(
    regulation_id: str,
    page: int = Query(1, ge=1, description="Halaman (mulai 1)"),
    page_size: int = Query(20, ge=1, le=100, description="Item per halaman"),
    search: str = Query("", description="Filter by text substring (case-insensitive)"),
    anomaly: str = Query("", description="Filter: '' | 'short' | 'long' | 'duplicate'"),
) -> RegulationChunksResponse:
    """
    Lihat semua chunks dari 1 regulasi (untuk audit kualitas database).

    - `search`: cari substring di text
    - `anomaly`: filter hanya chunk dengan anomali tertentu
    - `page`, `page_size`: pagination
    """
    # Validasi regulasi ada
    reg = get_regulation(regulation_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Regulasi tidak ditemukan.")

    # Load semua chunks dari LanceDB
    try:
        from app.services.regulation_db import _get_table
        table = _get_table()
        if table is None:
            raise HTTPException(status_code=500, detail="Database tidak siap.")

        # Ambil semua chunks untuk regulasi ini
        safe_id = regulation_id.replace("'", "''")
        result = table.search().where(f"regulation_id = '{safe_id}'").to_list()
    except Exception as exc:
        raise _internal_error("memuat chunks", exc) from exc

    if not result:
        return RegulationChunksResponse(
            regulation_id=regulation_id,
            regulation_name=reg.get("name", ""),
            page=page,
            page_size=page_size,
            total=0,
            total_unfiltered=0,
            total_pages=0,
            stats=RegulationChunksStats(),
            items=[],
            filter_search=search,
            filter_anomaly=anomaly,
        )

    # Sort by chunk_index
    result.sort(key=lambda c: c.get("chunk_index", 0))

    # Deteksi duplikat (text[:500].lower() hash)
    seen_hashes: dict[str, int] = {}
    duplicate_ids: set[str] = set()
    for c in result:
        text = (c.get("text", "") or "").strip().lower()
        if not text:
            continue
        key = hashlib.md5(text[:500].encode("utf-8")).hexdigest()
        if key in seen_hashes:
            duplicate_ids.add(c.get("id", ""))
        else:
            seen_hashes[key] = 1

    # Build enriched items + stats
    enriched: list[dict] = []
    for c in result:
        text = c.get("text", "") or ""
        char_count = len(text)
        word_count = len(text.split())
        chunk_id = c.get("id", "")

        # Anomaly classification
        is_anomaly = False
        reason = ""

        if chunk_id in duplicate_ids:
            is_anomaly = True
            reason = "duplicate"
        elif char_count < 50:
            is_anomaly = True
            reason = "short"
        elif char_count > 4000:
            is_anomaly = True
            reason = "long"

        # Build referensi string
        ref_parts = [
            c.get("lampiran") or "",
            c.get("bab") or "",
            c.get("bagian") or "",
            c.get("pasal") or "",
            c.get("ayat") or "",
        ]
        referensi = " / ".join([p for p in ref_parts if p])

        enriched.append({
            "id": chunk_id,
            "text": text,
            "referensi": referensi,
            "page_start": int(c.get("page_start") or 0),
            "page_end": int(c.get("page_end") or 0),
            "char_count": char_count,
            "word_count": word_count,
            "is_anomaly": is_anomaly,
            "anomaly_reason": reason,
        })

    # Stats (dari semua chunks, sebelum filter)
    all_chars = [e["char_count"] for e in enriched]
    stats = RegulationChunksStats(
        total_chunks=len(enriched),
        min_char=min(all_chars) if all_chars else 0,
        max_char=max(all_chars) if all_chars else 0,
        avg_char=round(sum(all_chars) / len(all_chars), 1) if all_chars else 0.0,
        total_char=sum(all_chars),
        anomaly_short=sum(1 for e in enriched if e["anomaly_reason"] == "short"),
        anomaly_long=sum(1 for e in enriched if e["anomaly_reason"] == "long"),
        anomaly_duplicate=sum(1 for e in enriched if e["anomaly_reason"] == "duplicate"),
    )

    # Filter: anomaly
    filtered = enriched
    if anomaly in ("short", "long", "duplicate"):
        filtered = [e for e in filtered if e["anomaly_reason"] == anomaly]

    # Filter: search
    search_lower = search.strip().lower()
    if search_lower:
        filtered = [
            e for e in filtered
            if search_lower in e["text"].lower() or search_lower in e["referensi"].lower()
        ]

    total_unfiltered = len(enriched)
    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    page_items = filtered[start:end]

    return RegulationChunksResponse(
        regulation_id=regulation_id,
        regulation_name=reg.get("name", ""),
        page=page,
        page_size=page_size,
        total=total,
        total_unfiltered=total_unfiltered,
        total_pages=total_pages,
        stats=stats,
        items=[RegulationChunkItem(**e) for e in page_items],
        filter_search=search,
        filter_anomaly=anomaly,
    )

# =============================================================================
# UPLOAD + INDEX
# =============================================================================

@router.post("/upload", response_model=JobAcceptedResponse, status_code=202)
async def upload_regulation(
    file: UploadFile = File(...),
    name: str = Form(...),
) -> JobAcceptedResponse:
    """
    Upload regulasi (PDF/TXT) → parse (langsung) → embed + simpan ke LanceDB
    (background job; hasil di job.extra["regulation"]).

    Args:
        file: file PDF/TXT
        name: nama regulasi (mis. "POJK 11/2022") — untuk display
    """
    # --- Validasi ---
    if not name or not name.strip():
        raise HTTPException(status_code=422, detail="Nama regulasi wajib diisi.")
    name = name.strip()[:200]

    file_bytes, extension = await read_upload(file)

    # --- Cek duplikat (file yang sama persis) ---
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()
    existing = find_by_sha256(file_sha256)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"File ini sudah ada di database sebagai '{existing.get('name')}'.",
        )

    # --- Extract + parse (berat, di threadpool). File sementara langsung dihapus;
    # salinan permanen disimpan Regulation DB setelah index berhasil. ---
    def _extract_and_parse() -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            temp_path = Path(tmp) / f"upload{extension}"
            temp_path.write_bytes(file_bytes)
            return parse_regulation_file(temp_path)

    try:
        chunks = await run_in_threadpool(_extract_and_parse)
    except (PDFExtractionError, TextExtractionError) as exc:
        raise HTTPException(status_code=422, detail=f"Gagal extract: {exc}") from exc

    if not chunks:
        raise HTTPException(
            status_code=422,
            detail="Tidak ada teks yang bisa di-parse dari dokumen ini.",
        )

    # --- Embed + simpan: jalan di background job (bisa puluhan detik) ---
    svc = embedder_or_422()
    worker = make_regulation_index_worker(
        name=name,
        filename=file.filename or "unknown",
        chunks=chunks,
        embedder=svc,
        source_bytes=file_bytes,
        file_sha256=file_sha256,
    )
    return _submit("regulation_index", worker, total=len(chunks))


# =============================================================================
# INDEX ULANG
# =============================================================================

@router.post(
    "/regulations/{regulation_id}/reindex",
    response_model=JobAcceptedResponse,
    status_code=202,
)
async def reindex_regulation_endpoint(regulation_id: str) -> JobAcceptedResponse:
    """
    Index ulang satu regulasi dari file sumbernya dengan parser & embedding
    terbaru (lihat needs_reindex di daftar regulasi).
    """
    reg = get_regulation(regulation_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Regulasi tidak ditemukan.")
    if not reg.get("has_source"):
        raise HTTPException(
            status_code=422,
            detail="File sumber regulasi ini tidak tersimpan. Hapus lalu upload ulang regulasinya.",
        )
    worker = make_regulation_reindex_worker(regulation=reg, embedder=embedder_or_422())
    return _submit("regulation_reindex", worker, total=reg.get("total_chunks", 0))


def _internal_error(action: str, exc: Exception) -> HTTPException:
    """Detail error database hanya di log; client mendapat pesan + kode pelacakan."""
    error_id = uuid.uuid4().hex[:8]
    logger.error("Gagal %s [%s]: %s", action, error_id, exc, exc_info=exc)
    return HTTPException(
        status_code=500,
        detail=f"Gagal {action} (kode: {error_id}). Detail tercatat di log server.",
    )


def _submit(kind: str, worker, total: int) -> JobAcceptedResponse:
    rec = get_job_manager().submit(kind, worker, total=total)
    return JobAcceptedResponse(
        job_id=rec.job_id,
        kind=rec.kind,
        status=rec.status,
        status_url=f"/api/jobs/{rec.job_id}",
    )


# =============================================================================
# DELETE
# =============================================================================

@router.delete("/regulations/{regulation_id}", response_model=ResetDBResponse)
async def delete_regulation_endpoint(regulation_id: str) -> ResetDBResponse:
    """Hapus regulasi dari database."""
    reg = get_regulation(regulation_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Regulasi tidak ditemukan.")

    try:
        success = delete_regulation(regulation_id)
    except RegulationDBError as exc:
        raise _internal_error("hapus regulasi", exc) from exc

    if not success:
        raise HTTPException(status_code=500, detail="Gagal menghapus regulasi.")

    return ResetDBResponse(
        success=True,
        message=f"Regulasi '{reg.get('name')}' berhasil dihapus.",
    )


# =============================================================================
# STATS
# =============================================================================

@router.get("/stats", response_model=RegulationDBStatsResponse)
async def get_stats() -> RegulationDBStatsResponse:
    """Statistik database regulasi."""
    stats = get_db_stats()
    return RegulationDBStatsResponse(**stats)


# =============================================================================
# RESET
# =============================================================================

@router.post("/reset", response_model=ResetDBResponse)
async def reset_db_endpoint(payload: ResetDBRequest) -> ResetDBResponse:
    """
    Hapus SELURUH database regulasi (index, registry, file sumber).
    Wajib konfirmasi eksplisit di body: {"confirm": "HAPUS SEMUA"}.
    """
    if payload.confirm != RESET_CONFIRMATION:
        raise HTTPException(
            status_code=422,
            detail=f"Konfirmasi tidak cocok. Kirim confirm = '{RESET_CONFIRMATION}'.",
        )
    logger.warning("Reset Regulation DB atas permintaan pengguna.")
    try:
        reset_database()
    except Exception as exc:
        raise _internal_error("reset database", exc) from exc

    return ResetDBResponse(
        success=True,
        message="Database regulasi berhasil direset.",
    )


# =============================================================================
# SEARCH (debug / test retrieval)
# =============================================================================

@router.post("/search", response_model=SearchDBResponse)
async def search_db(payload: SearchDBRequest) -> SearchDBResponse:
    """
    Test retrieval: cari chunk regulasi yang relevan dengan query.
    Berguna untuk debug kualitas embedding.
    """
    query = payload.query.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Query minimal 2 karakter.")

    try:
        svc = EmbeddingService()
        query_vec = await run_in_threadpool(svc.embed_query, query)
    except EmbeddingError as exc:
        raise HTTPException(status_code=502, detail=f"Gagal embed query: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        chunks = await run_in_threadpool(
            query_relevant_chunks,
            query_embedding=query_vec,
            regulation_ids=payload.regulation_ids,
            top_k=payload.top_k,
            query_text=query,
        )
    except RegulationDBError as exc:
        raise _internal_error("pencarian regulasi", exc) from exc

    results: list[SearchDBResultItem] = []
    for c in chunks:
        meta = c.get("metadata", {})
        ref_parts = [
            meta.get("lampiran") or "",
            meta.get("bab") or "",
            meta.get("bagian") or "",
            meta.get("pasal") or "",
            meta.get("ayat") or "",
        ]
        referensi = " / ".join([p for p in ref_parts if p])

        results.append(SearchDBResultItem(
            id=c.get("id", ""),
            text=c.get("text", ""),
            regulation_name=meta.get("regulation_name", ""),
            referensi=referensi,
            distance=c.get("distance"),
            page_start=int(meta.get("page_start") or 0),
            page_end=int(meta.get("page_end") or 0),
        ))

    return SearchDBResponse(
        query=query,
        total=len(results),
        results=results,
    )