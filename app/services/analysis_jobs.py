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
from app.services.compliance_review_analyzer import (
    ComplianceAnalysisError,
    analyze_compliance,
    count_by_status,
    generate_executive_summary,
    normalize_compliance_items,
)
from app.services.embedding_service import EmbeddingError, EmbeddingService
from app.services.job_manager import JobCancelled, JobContext, JobFailure, JobOutcome
from app.services.json_store import update_json, write_text_atomic
from app.services.regulation_db import (
    RegulationDBError,
    add_regulation,
    query_relevant_chunks,
)
from app.services.requirements_analyzer import (
    RequirementsAnalysisError,
    analyze_chunks_for_requirements,
)
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

def _run_compliance_analysis(
    ctx: JobContext,
    contract_chunks: list[dict],
    regulation_chunks: list[dict],
    provider: AIProvider,
    step: int,
    total: int,
) -> list[dict]:
    ctx.check_cancelled()
    ctx.progress(step, total, f"AI me-review {len(contract_chunks)} klausul kontrak...")
    try:
        raw_items = analyze_compliance(contract_chunks, regulation_chunks, provider)
    except (*_BATCH_ERRORS, ComplianceAnalysisError) as exc:
        raise JobFailure(f"Analisis compliance gagal: {exc}") from exc
    return normalize_compliance_items(raw_items)


def _save_compliance_result(
    ctx: JobContext,
    *,
    items: list[dict],
    provider: AIProvider,
    preview_id: str,
    contract_filename: str,
    regulation_filenames: list[str],
    total_contract_chunks: int,
    total_regulation_chunks: int,
    filter_text: str,
    step: int,
    total: int,
) -> JobOutcome:
    ctx.check_cancelled()
    ctx.progress(step, total, "Menyusun ringkasan eksekutif...")
    executive_summary = generate_executive_summary(items, provider)

    counts = count_by_status(items)
    result_id = uuid.uuid4().hex
    response = ComplianceResponse(
        result_id=result_id,
        preview_id=preview_id,
        contract_filename=contract_filename,
        regulation_filenames=regulation_filenames,
        total_items=len(items),
        total_patuh=counts["total_patuh"],
        total_patuh_catatan=counts["total_patuh_catatan"],
        total_tidak_patuh=counts["total_tidak_patuh"],
        total_tidak_relevan=counts["total_tidak_relevan"],
        items=[ComplianceItem(**it) for it in items],
        executive_summary=executive_summary,
        total_contract_chunks=total_contract_chunks,
        total_regulation_chunks=total_regulation_chunks,
        total_batches=1,
        filter_applied=filter_text,
    )
    write_text_atomic(
        COMPLIANCE_OUTPUT_DIR / f"{result_id}.json", response.model_dump_json(indent=2)
    )
    ctx.progress(total, total, "Selesai.")
    return JobOutcome(
        result_id=result_id,
        result_url=f"/api/compliance/{result_id}",
        message=f"{len(items)} klausul dianalisis.",
    )


def make_compliance_worker(
    *,
    preview_id: str,
    contract_filename: str,
    regulation_filenames: list[str],
    contract_chunks: list[dict],
    regulation_chunks: list[dict],
    provider: AIProvider,
    filter_text: str,
):
    def worker(ctx: JobContext) -> JobOutcome:
        total = 2
        items = _run_compliance_analysis(
            ctx, contract_chunks, regulation_chunks, provider, step=0, total=total
        )
        return _save_compliance_result(
            ctx,
            items=items,
            provider=provider,
            preview_id=preview_id,
            contract_filename=contract_filename,
            regulation_filenames=regulation_filenames,
            total_contract_chunks=len(contract_chunks),
            total_regulation_chunks=len(regulation_chunks),
            filter_text=filter_text,
            step=1,
            total=total,
        )

    return worker


def make_compliance_db_worker(
    *,
    contract_filename: str,
    contract_chunks: list[dict],
    regulation_ids: list[str],
    regulation_names: list[str],
    top_k_per_clause: int,
    embedder: EmbeddingService,
    provider: AIProvider,
    filter_text: str,
):
    def worker(ctx: JobContext) -> JobOutcome:
        n = len(contract_chunks)
        # Langkah: 1 embed + n retrieval + 1 analisis + 1 ringkasan
        total = n + 3

        ctx.progress(0, total, f"Membuat embedding {n} klausul kontrak...")
        try:
            contract_embeddings = embedder.embed_batch(
                [c.get("text", "") for c in contract_chunks],
                task_type="RETRIEVAL_QUERY",
            )
        except EmbeddingError as exc:
            raise JobFailure(f"Gagal embed kontrak: {exc}") from exc

        retrieved: list[dict] = []
        seen_ids: set[str] = set()
        for i, emb in enumerate(contract_embeddings):
            ctx.check_cancelled()
            ctx.progress(1 + i, total, f"Mencari regulasi relevan untuk klausul {i + 1}/{n}...")
            try:
                hits = query_relevant_chunks(
                    query_embedding=emb,
                    regulation_ids=regulation_ids,
                    top_k=top_k_per_clause,
                )
            except RegulationDBError as exc:
                logger.warning("Retrieval gagal untuk chunk %d: %s", i, exc)
                continue

            for hit in hits:
                if hit["id"] in seen_ids:
                    continue
                seen_ids.add(hit["id"])
                meta = hit.get("metadata", {})
                retrieved.append({
                    "lampiran": meta.get("lampiran") or None,
                    "bab": meta.get("bab") or None,
                    "bagian": meta.get("bagian") or None,
                    "pasal": meta.get("pasal") or None,
                    "ayat": meta.get("ayat") or None,
                    "butir": meta.get("butir") or None,
                    "text": hit.get("text", ""),
                    "source_file": meta.get("regulation_name", "Unknown"),
                    "page_start": meta.get("page_start") or 0,
                    "page_end": meta.get("page_end") or 0,
                    "_retrieval_distance": hit.get("distance"),
                })

        if not retrieved:
            raise JobFailure(
                "Tidak ada regulasi relevan yang ditemukan. Coba pilih regulasi lain."
            )
        logger.info(
            "RAG retrieval: %d contract chunks → %d unique regulation chunks", n, len(retrieved)
        )

        items = _run_compliance_analysis(
            ctx, contract_chunks, retrieved, provider, step=n + 1, total=total
        )
        return _save_compliance_result(
            ctx,
            items=items,
            provider=provider,
            preview_id="",  # RAG mode tidak memakai preview
            contract_filename=contract_filename,
            regulation_filenames=regulation_names,
            total_contract_chunks=n,
            total_regulation_chunks=len(retrieved),
            filter_text=filter_text,
            step=n + 2,
            total=total,
        )

    return worker


def make_compliance_items_worker(
    *,
    result_path: Path,
    result_id: str,
    item_indices: list[int],
    contract_chunks: list[dict],
    regulation_chunks: list[dict],
    provider: AIProvider,
):
    def worker(ctx: JobContext) -> JobOutcome:
        items_result = _run_compliance_analysis(
            ctx, contract_chunks, regulation_chunks, provider, step=0, total=1
        )

        def apply(data: dict[str, Any]) -> int:
            items = data.get("items", [])
            affected = 0
            # Map berdasarkan urutan (AI diminta menjaga urutan input).
            for i, idx in enumerate(item_indices):
                if i >= len(items_result) or idx >= len(items):
                    break
                res = items_result[i]
                items[idx]["regulasi_ref"] = res.get("regulasi_ref", "")
                items[idx]["status"] = res.get("status", "TIDAK RELEVAN")
                items[idx]["analisis"] = res.get("analisis", "")
                affected += 1
            data["items"] = items
            data.update(count_by_status(items))
            return affected

        try:
            affected = update_json(result_path, apply)
        except FileNotFoundError as exc:
            raise JobFailure("Hasil compliance review sudah tidak ada.") from exc

        ctx.progress(1, 1, "Selesai.")
        return JobOutcome(
            result_id=result_id,
            result_url=f"/api/compliance/{result_id}",
            message=f"{affected} klausul dianalisis.",
            extra={"affected": affected},
        )

    return worker


# =============================================================================
# REGULATION DB — index regulasi baru
# =============================================================================

def make_regulation_index_worker(
    *,
    name: str,
    filename: str,
    chunks: list[dict],
    embedder: EmbeddingService,
):
    def worker(ctx: JobContext) -> JobOutcome:
        n = len(chunks)
        ctx.progress(0, n, f"Membuat embedding {n} chunk...")

        def on_batch_done(done: int, total: int) -> None:
            ctx.check_cancelled()
            ctx.progress(done, total, f"Embedding {done}/{total} chunk...")

        try:
            embeddings = embedder.embed_batch(
                [c.get("text", "") for c in chunks],
                task_type="RETRIEVAL_DOCUMENT",
                on_batch_done=on_batch_done,
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
            )
        except RegulationDBError as exc:
            raise JobFailure(f"Gagal simpan ke database: {exc}") from exc

        logger.info("Regulasi '%s' diupload: %d chunks", name, n)
        return JobOutcome(
            result_id=meta["id"],
            message=f"Berhasil index {n} chunk dari '{name}'.",
            extra={"regulation": meta},
        )

    return worker
