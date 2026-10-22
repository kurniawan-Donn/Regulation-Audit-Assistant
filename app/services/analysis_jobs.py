"""
Worker untuk job analisis AI yang berjalan di background (lihat job_manager).

Pembagian tanggung jawab:
- Endpoint (routes.py) melakukan validasi CEPAT yang bisa langsung gagal
  (preview ada, chunk dipilih, API key terisi) lalu men-submit job.
- Fungsi make_*_worker() di sini membungkus pekerjaan LAMA (panggilan AI,
  embedding) sebagai closure yang dijalankan JobManager di thread terpisah,
  sambil melapor progres dan menghormati pembatalan di antara batch.

Semua hasil disimpan dengan penulisan atomik (json_store).
"""

import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.schemas import (
    AnalyzeRequirementsResponse,
    AnalyzeResponse,
    AuditResultItem,
    ChunkError,
    ComplianceItem,
    ComplianceResponse,
    RequirementItem,
)
from app.services.ai_service import AIProvider, AIProviderError, AIResponseParsingError
from app.services.audit_analyzer import AuditAnalysisError, analyze_chunks_batch
from app.services.compliance_retrieval import (
    DEFAULT_TOP_K,
    embed_regulation_chunks,
    retrieval_candidates,
    retrieve_from_db,
    retrieve_local,
)
from app.prompts.compliance_review_prompt import build_contract_outline
from app.services.compliance_review_analyzer import (
    ComplianceAnalysisError,
    count_by_status,
    generate_executive_summary,
    review_batch,
    unverified_items,
)
from app.services.embedding_service import EmbeddingError, EmbeddingService
from app.services.job_manager import JobCancelled, JobContext, JobFailure, JobOutcome
from app.services.json_store import update_json, write_text_atomic
from app.services.pdf_parser import PDFExtractionError, extract_pdf_text
from app.services.regulation_db import (
    RegulationDBError,
    add_regulation,
    regulation_embed_text,
    replace_regulation_chunks,
    source_path,
)
from app.services.regulation_parser import parse_regulation_structure
from app.services.requirements_analyzer import (
    RequirementsAnalysisError,
    analyze_chunks_for_requirements,
)
from app.services.text_processor import TextExtractionError, clean_text, extract_txt_text
from app.services.validator import validate_results

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("outputs")
REQUIREMENTS_DIR = OUTPUT_DIR / "requirements"
COMPLIANCE_OUTPUT_DIR = OUTPUT_DIR / "compliance"

_BATCH_ERRORS = (AIProviderError, AIResponseParsingError)


def _batch_chunk_error(batch: list[dict], error: str) -> ChunkError:
    lampirans = sorted({c["lampiran"] for c in batch if c.get("lampiran")})
    babs = sorted({c["bab"] for c in batch if c.get("bab")})
    pasals = sorted({c["pasal"] for c in batch if c.get("pasal")})
    return ChunkError(
        lampiran=", ".join(lampirans) if lampirans else None,
        bab=", ".join(babs) if babs else None,
        pasal=", ".join(pasals) if pasals else None,
        ayat=None,
        error=error,
        affected_count=len(batch),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cancelled_chunk_error(remaining: list[list[dict]]) -> ChunkError:
    return ChunkError(
        error="Dibatalkan pengguna — bagian ini belum dianalisis.",
        affected_count=sum(len(b) for b in remaining),
    )


# =============================================================================
# TOOL 1 — Regulation to Audit
# =============================================================================

def make_audit_worker(
    *,
    preview_id: str,
    filename: str,
    cleaned_text: str,
    relevant_chunks: list[dict],
    total_chunks_available: int,
    batches: list[list[dict]],
    provider: AIProvider,
    referensi_regulasi: str,
    selected_labels: list[str],
):
    def worker(ctx: JobContext) -> JobOutcome:
        validated_results: list[dict] = []
        chunk_errors: list[ChunkError] = []
        total = len(batches)
        processed = 0

        for i, batch in enumerate(batches):
            if ctx.cancelled:
                break
            ctx.progress(i, total, f"Menganalisis batch {i + 1}/{total}...")
            try:
                batch_result = analyze_chunks_batch(
                    batch, provider, referensi_regulasi=referensi_regulasi
                )
            except (*_BATCH_ERRORS, AuditAnalysisError) as exc:
                chunk_errors.append(_batch_chunk_error(batch, str(exc)))
            else:
                validated_results.extend(
                    validate_results(batch_result, source_text=cleaned_text)
                )
            processed = i + 1

        cancelled = processed < total
        if cancelled:
            if processed == 0:
                raise JobCancelled()
            chunk_errors.append(_cancelled_chunk_error(batches[processed:]))

        total_valid = sum(1 for r in validated_results if r["is_valid"])
        result_id = uuid.uuid4().hex
        response = AnalyzeResponse(
            result_id=result_id,
            created_at=_now_iso(),
            filename=filename,
            preview_id=preview_id,
            total_chunks=len(relevant_chunks),
            total_chunks_available=total_chunks_available,
            total_batches=total,
            total_ketentuan=len(validated_results),
            total_valid=total_valid,
            total_flagged=len(validated_results) - total_valid,
            results=[AuditResultItem(**r) for r in validated_results],
            chunk_errors=chunk_errors,
            total_by_aspect=dict(
                Counter(r["aspek"] for r in validated_results if r.get("aspek"))
            ),
            filter_applied=list(selected_labels),
        )
        write_text_atomic(OUTPUT_DIR / f"{result_id}.json", response.model_dump_json(indent=2))

        ctx.progress(processed, total, "Selesai.")
        return JobOutcome(
            result_id=result_id,
            result_url=f"/api/results/{result_id}",
            cancelled=cancelled,
            message=(
                f"Dibatalkan setelah {processed}/{total} batch — hasil parsial disimpan."
                if cancelled else
                f"{len(validated_results)} ketentuan dari {total} batch."
            ),
        )

    return worker


# =============================================================================
# TOOL 2 — Gap Analysis
# =============================================================================

def make_requirements_worker(
    *,
    preview_id: str,
    filename: str,
    selected_chunks: list[dict],
    total_chunks_available: int,
    batches: list[list[dict]],
    provider: AIProvider,
    referensi_regulasi: str,
    filter_text: str,
):
    def worker(ctx: JobContext) -> JobOutcome:
        all_requirements: list[dict] = []
        chunk_errors: list[ChunkError] = []
        total = len(batches)
        processed = 0

        for i, batch in enumerate(batches):
            if ctx.cancelled:
                break
            ctx.progress(i, total, f"Mengekstrak persyaratan batch {i + 1}/{total}...")
            try:
                batch_result = analyze_chunks_for_requirements(
                    batch, provider, referensi_regulasi=referensi_regulasi
                )
            except (*_BATCH_ERRORS, RequirementsAnalysisError) as exc:
                chunk_errors.append(_batch_chunk_error(batch, str(exc)))
            else:
                for item in batch_result:
                    if not isinstance(item, dict):
                        continue
                    all_requirements.append({
                        "persyaratan": str(item.get("persyaratan", "")).strip(),
                        "referensi": str(item.get("referensi", "")).strip(),
                        "catatan": str(item.get("catatan", "")).strip(),
                        "status_gap": "",
                    })
            processed = i + 1

        cancelled = processed < total
        if cancelled:
            if processed == 0:
                raise JobCancelled()
            chunk_errors.append(_cancelled_chunk_error(batches[processed:]))

        result_id = uuid.uuid4().hex
        response = AnalyzeRequirementsResponse(
            result_id=result_id,
            created_at=_now_iso(),
            filename=filename,
            preview_id=preview_id,
            total_chunks_analyzed=len(selected_chunks),
            total_chunks_available=total_chunks_available,
            total_batches=total,
            total_requirements=len(all_requirements),
            requirements=[RequirementItem(**r) for r in all_requirements],
            chunk_errors=chunk_errors,
            filter_applied=filter_text,
        )
        write_text_atomic(
            REQUIREMENTS_DIR / f"{result_id}.json", response.model_dump_json(indent=2)
        )

        ctx.progress(processed, total, "Selesai.")
        return JobOutcome(
            result_id=result_id,
            result_url=f"/api/requirements/{result_id}",
            cancelled=cancelled,
            message=(
                f"Dibatalkan setelah {processed}/{total} batch — hasil parsial disimpan."
                if cancelled else
                f"{len(all_requirements)} persyaratan dari {total} batch."
            ),
        )

    return worker


# =============================================================================
# TOOL 3 — Compliance Review
# =============================================================================

COMPLIANCE_UNITS_PER_BATCH = 5
COMPLIANCE_PREVIEW_DIR = Path("cache/compliance_previews")


def compliance_embedding_cache_path(preview_id: str) -> Path:
    return COMPLIANCE_PREVIEW_DIR / f"{preview_id}.emb.npy"


def _retrieve_for_units(
    ctx: JobContext,
    units: list[dict],
    retrieval: dict[str, Any],
    regulation_chunks: list[dict],
    embedder: EmbeddingService,
    step: int,
    total: int,
) -> None:
    """Isi unit["regulations"] sesuai mode retrieval (database / upload)."""
    ctx.check_cancelled()
    top_k = int(retrieval.get("top_k") or DEFAULT_TOP_K)
    try:
        if retrieval.get("mode") == "database":
            ctx.progress(step, total, f"Mencari regulasi relevan untuk {len(units)} klausul...")
            retrieve_from_db(
                units, embedder, retrieval.get("regulation_ids") or [], top_k,
                on_progress=lambda i, n: ctx.check_cancelled(),
            )
            return

        def on_batch_done(done: int, n: int) -> None:
            ctx.check_cancelled()
            ctx.progress(step, total, f"Embedding regulasi {done}/{n} chunk...")

        candidates = retrieval_candidates(regulation_chunks)
        matrix = embed_regulation_chunks(
            candidates,
            embedder,
            cache_path=compliance_embedding_cache_path(retrieval["preview_id"]),
            on_batch_done=on_batch_done,
        )
        ctx.check_cancelled()
        ctx.progress(step, total, f"Mencocokkan {len(units)} klausul dengan regulasi...")
        retrieve_local(units, embedder, candidates, matrix, top_k)
    except EmbeddingError as exc:
        raise JobFailure(f"Gagal membuat embedding untuk retrieval regulasi: {exc}") from exc


def _review_units(
    ctx: JobContext,
    units: list[dict],
    provider: AIProvider,
    step: int,
    total: int,
) -> tuple[list[dict], bool]:
    """
    Review unit per batch kecil. Batch yang gagal → item PERLU VERIFIKASI
    (batch lain tetap jalan). Return (items, cancelled).
    """
    size = COMPLIANCE_UNITS_PER_BATCH
    batches = [units[i:i + size] for i in range(0, len(units), size)]
    # Tiap batch hanya melihat 5 klausul; daftar isi memberi konteks kontrak utuh.
    outline = build_contract_outline(units)
    items: list[dict] = []
    for bi, batch in enumerate(batches):
        if ctx.cancelled:
            if bi == 0:
                raise JobCancelled()
            for rest in batches[bi:]:
                items += unverified_items(rest, "Belum dianalisis — proses dibatalkan pengguna.")
            return items, True

        first = bi * size + 1
        ctx.progress(
            step + bi, total,
            f"AI me-review klausul {first}–{first + len(batch) - 1} dari {len(units)}...",
        )
        try:
            items += review_batch(batch, provider, outline)
        except (*_BATCH_ERRORS, ComplianceAnalysisError) as exc:
            logger.warning("Batch compliance %d gagal: %s", bi, exc)
            items += unverified_items(batch, f"Analisis AI gagal untuk klausul ini: {exc}")
    return items, False


def _unique_regulation_count(units: list[dict]) -> int:
    return len({c["key"] for u in units for c in u.get("regulations", [])})


def make_compliance_review_worker(
    *,
    units: list[dict],
    retrieval: dict[str, Any],
    regulation_chunks: list[dict],
    embedder: EmbeddingService,
    provider: AIProvider,
    preview_id: str,
    contract_filename: str,
    regulation_filenames: list[str],
    filter_text: str,
    warnings: list[str],
):
    """
    Compliance review lengkap (mode upload maupun database):
    retrieval per klausul → review per batch → ringkasan eksekutif.
    """
    def worker(ctx: JobContext) -> JobOutcome:
        n_batches = -(-len(units) // COMPLIANCE_UNITS_PER_BATCH)
        total = n_batches + 2  # retrieval + batch review + ringkasan

        _retrieve_for_units(ctx, units, retrieval, regulation_chunks, embedder, 0, total)
        items, cancelled = _review_units(ctx, units, provider, 1, total)

        result_warnings = list(warnings)
        if cancelled:
            result_warnings.append(
                "Proses dibatalkan — sebagian klausul belum dianalisis (status PERLU VERIFIKASI)."
            )
            executive_summary = ""
        else:
            ctx.progress(total - 1, total, "Menyusun ringkasan eksekutif...")
            executive_summary = generate_executive_summary(items, provider)

        counts = count_by_status(items)
        result_id = uuid.uuid4().hex
        response = ComplianceResponse(
            result_id=result_id,
            created_at=_now_iso(),
            preview_id=preview_id,
            contract_filename=contract_filename,
            regulation_filenames=regulation_filenames,
            total_items=len(items),
            items=[ComplianceItem(**it) for it in items],
            executive_summary=executive_summary,
            total_contract_chunks=len(units),
            total_regulation_chunks=_unique_regulation_count(units),
            total_batches=n_batches,
            filter_applied=filter_text,
            retrieval=retrieval,
            warnings=result_warnings,
            **counts,
        )
        write_text_atomic(
            COMPLIANCE_OUTPUT_DIR / f"{result_id}.json", response.model_dump_json(indent=2)
        )
        ctx.progress(total, total, "Selesai.")

        flagged = sum(1 for it in items if it["needs_review"])
        message = f"{len(items)} klausul dianalisis"
        if flagged:
            message += f", {flagged} perlu verifikasi auditor"
        return JobOutcome(
            result_id=result_id,
            result_url=f"/api/compliance/{result_id}",
            cancelled=cancelled,
            message=message + ".",
        )

    return worker


def make_compliance_items_worker(
    *,
    result_path: Path,
    result_id: str,
    item_indices: list[int],
    units: list[dict],
    original_texts: list[str],
    retrieval: dict[str, Any],
    regulation_chunks: list[dict],
    embedder: EmbeddingService,
    provider: AIProvider,
):
    """Analisis AI untuk baris tertentu (mis. klausul hasil import) pada hasil yang sudah ada."""
    def worker(ctx: JobContext) -> JobOutcome:
        n_batches = -(-len(units) // COMPLIANCE_UNITS_PER_BATCH)
        total = n_batches + 1
        _retrieve_for_units(ctx, units, retrieval, regulation_chunks, embedder, 0, total)
        reviewed, cancelled = _review_units(ctx, units, provider, 1, total)
        if cancelled:
            raise JobCancelled()

        def apply(data: dict[str, Any]) -> dict[str, int]:
            items = data.get("items", [])
            affected = skipped = 0
            for idx, original, res in zip(item_indices, original_texts, reviewed):
                # Baris bisa saja dihapus/diubah selama job berjalan: jangan
                # menimpa baris yang klausulnya sudah bukan yang dianalisis.
                if idx >= len(items) or items[idx].get("klausul_text", "") != original:
                    skipped += 1
                    continue
                for field in ("regulasi_ref", "status", "analisis", "validation_notes", "needs_review"):
                    items[idx][field] = res[field]
                affected += 1
            data["items"] = items
            data.update(count_by_status(items))
            return {"affected": affected, "skipped": skipped}

        try:
            stats = update_json(result_path, apply)
        except FileNotFoundError as exc:
            raise JobFailure("Hasil compliance review sudah tidak ada.") from exc

        ctx.progress(total, total, "Selesai.")
        message = f"{stats['affected']} klausul dianalisis."
        if stats["skipped"]:
            message += f" {stats['skipped']} dilewati karena barisnya berubah selama analisis."
        return JobOutcome(
            result_id=result_id,
            result_url=f"/api/compliance/{result_id}",
            message=message,
            extra=stats,
        )

    return worker


# =============================================================================
# REGULATION DB — index regulasi baru
# =============================================================================

def parse_regulation_file(path: Path) -> list[dict]:
    """File regulasi (PDF/TXT) → chunk terstruktur (sinkron, berat)."""
    if path.suffix.lower() == ".pdf":
        raw_text = extract_pdf_text(str(path))
    else:
        raw_text = extract_txt_text(str(path))
    return parse_regulation_structure(clean_text(raw_text))


def embed_regulation_for_index(
    name: str,
    chunks: list[dict],
    embedder: EmbeddingService,
    on_batch_done=None,
) -> list[list[float]]:
    """Embedding chunk untuk Regulation DB: header "<nama> <Pasal/ayat>" + isi."""
    return embedder.embed_batch(
        [regulation_embed_text({**c, "source": name}) for c in chunks],
        task_type="RETRIEVAL_DOCUMENT",
        on_batch_done=on_batch_done,
    )


def _embedding_progress(ctx: JobContext):
    def on_batch_done(done: int, total: int) -> None:
        ctx.check_cancelled()
        ctx.progress(done, total, f"Embedding {done}/{total} chunk...")
    return on_batch_done


def make_regulation_index_worker(
    *,
    name: str,
    filename: str,
    chunks: list[dict],
    embedder: EmbeddingService,
    source_bytes: bytes,
    file_sha256: str,
):
    def worker(ctx: JobContext) -> JobOutcome:
        n = len(chunks)
        ctx.progress(0, n, f"Membuat embedding {n} chunk...")
        try:
            embeddings = embed_regulation_for_index(
                name, chunks, embedder, _embedding_progress(ctx)
            )
        except EmbeddingError as exc:
            raise JobFailure(f"Gagal embed: {exc}") from exc

        ctx.check_cancelled()
        ctx.progress(n, n, "Menyimpan ke database...")
        try:
            meta = add_regulation(
                name=name,
                filename=filename,
                chunks=chunks,
                embeddings=embeddings,
                source_type="manual",
                source_bytes=source_bytes,
                file_sha256=file_sha256,
            )
        except RegulationDBError as exc:
            logger.exception("Gagal simpan regulasi '%s' ke database", name)
            raise JobFailure("Gagal menyimpan ke database regulasi. Detail tercatat di log server.") from exc

        logger.info("Regulasi '%s' diupload: %d chunks", name, n)
        return JobOutcome(
            result_id=meta["id"],
            message=f"Berhasil index {n} chunk dari '{name}'.",
            extra={"regulation": meta},
        )

    return worker


def make_regulation_reindex_worker(*, regulation: dict, embedder: EmbeddingService):
    """Index ulang satu regulasi dari file sumbernya (parser & embedding terbaru)."""
    def worker(ctx: JobContext) -> JobOutcome:
        src = source_path(regulation)
        if src is None:
            raise JobFailure("File sumber regulasi tidak tersimpan — upload ulang regulasi ini.")
        ctx.progress(0, 0, "Membaca & mem-parse ulang dokumen...")
        try:
            chunks = parse_regulation_file(src)
        except (PDFExtractionError, TextExtractionError) as exc:
            raise JobFailure(f"Gagal membaca file sumber: {exc}") from exc
        if not chunks:
            raise JobFailure("Tidak ada teks yang bisa di-parse dari file sumber.")

        try:
            embeddings = embed_regulation_for_index(
                regulation["name"], chunks, embedder, _embedding_progress(ctx)
            )
        except EmbeddingError as exc:
            raise JobFailure(f"Gagal embed: {exc}") from exc

        ctx.check_cancelled()
        ctx.progress(len(chunks), len(chunks), "Mengganti index di database...")
        try:
            meta = replace_regulation_chunks(regulation["id"], chunks, embeddings)
        except RegulationDBError as exc:
            logger.exception("Gagal index ulang regulasi %s", regulation["id"])
            raise JobFailure("Gagal mengganti index di database. Detail tercatat di log server.") from exc

        old = regulation.get("total_chunks", 0)
        return JobOutcome(
            result_id=regulation["id"],
            message=f"'{regulation['name']}' di-index ulang: {old} → {len(chunks)} chunk.",
            extra={"regulation": meta},
        )

    return worker
