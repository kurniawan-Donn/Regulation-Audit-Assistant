"""
Retrieval regulasi per unit klausul untuk Compliance Review.

Sebelumnya mode upload mengirim 100 chunk regulasi PERTAMA ke AI (biasanya
Ketentuan Umum), sehingga pasal yang relevan bisa tidak pernah terlihat.
Sekarang kedua mode memakai retrieval semantik yang sama: setiap unit
klausul mendapat top-K chunk regulasi paling relevan miliknya sendiri.

- Mode database: query ke LanceDB (lihat regulation_db.query_relevant_chunks).
- Mode upload: chunk regulasi di-embed sekali (dengan header konteks
  "<regulasi> <pasal/ayat>"), disimpan sebagai .npy di samping preview,
  lalu dicari dengan cosine similarity di memori.
"""

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.services.embedding_service import EmbeddingService
from app.services.regulation_db import (
    RegulationDBError,
    query_relevant_chunks,
    regulation_embed_text,
)

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
MAX_TOP_K = 10

_QUERY_MAX_CHARS = 2000

ProgressFn = Callable[[int, int], None]


def unit_query_text(unit: dict) -> str:
    judul = unit.get("judul") or ""
    return f"{judul}\n{unit['text']}".strip()[:_QUERY_MAX_CHARS]


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


# =============================================================================
# MODE DATABASE
# =============================================================================

def _chunk_from_db_hit(hit: dict) -> dict:
    meta = hit.get("metadata", {})
    distance = hit.get("distance")
    # Mode hybrid memberi skor RRF; mode vektor memberi jarak cosine.
    score = hit.get("score")
    if score is None and distance is not None:
        score = 1.0 - float(distance)
    return {
        "key": f"db:{hit.get('id', '')}",
        "text": hit.get("text", ""),
        "source": meta.get("regulation_name") or meta.get("source_file") or "",
        "lampiran": meta.get("lampiran") or None,
        "bab": meta.get("bab") or None,
        "bagian": meta.get("bagian") or None,
        "pasal": meta.get("pasal") or None,
        "ayat": meta.get("ayat") or None,
        "page_start": meta.get("page_start") or None,
        "score": None if score is None else round(float(score), 4),
    }


def retrieve_from_db(
    units: list[dict],
    embedder: EmbeddingService,
    regulation_ids: list[str],
    top_k: int = DEFAULT_TOP_K,
    on_progress: ProgressFn | None = None,
) -> None:
    """Isi unit["regulations"] dari Regulation Database (in-place), pencarian hybrid."""
    queries = [unit_query_text(u) for u in units]
    vectors = embedder.embed_batch(queries, task_type="RETRIEVAL_QUERY")
    for i, (unit, vec) in enumerate(zip(units, vectors)):
        if on_progress:
            on_progress(i, len(units))
        try:
            hits = query_relevant_chunks(
                query_embedding=vec, regulation_ids=regulation_ids, top_k=top_k,
                query_text=queries[i],
            )
        except RegulationDBError as exc:
            logger.warning("Retrieval gagal untuk unit %d: %s", i, exc)
            hits = []
        unit["regulations"] = [_chunk_from_db_hit(h) for h in hits]


# =============================================================================
# MODE UPLOAD (in-memory)
# =============================================================================

def retrieval_candidates(regulation_chunks: list[dict]) -> list[dict]:
    """
    Chunk regulasi yang layak dikutip: yang punya struktur (Lampiran/BAB/Pasal).
    Halaman judul peraturan ("PERATURAN ... TENTANG ...") dibuang, kecuali
    dokumennya memang tidak berstruktur sama sekali.
    """
    structured = [
        c for c in regulation_chunks
        if c.get("lampiran") or c.get("bab") or c.get("pasal")
    ]
    return structured or list(regulation_chunks)


def embed_regulation_chunks(
    chunks: list[dict],
    embedder: EmbeddingService,
    cache_path: Path | None = None,
    on_batch_done: ProgressFn | None = None,
) -> np.ndarray:
    """
    Embed chunk regulasi (RETRIEVAL_DOCUMENT) → matriks ternormalisasi.
    Kalau cache_path ada dan cocok jumlah barisnya, embedding dipakai ulang.
    """
    if cache_path is not None and cache_path.exists():
        try:
            cached = np.load(cache_path)
            if cached.shape[0] == len(chunks):
                return cached
        except Exception as exc:
            logger.warning("Cache embedding %s tidak terbaca: %s", cache_path, exc)

    vectors = embedder.embed_batch(
        [regulation_embed_text(c) for c in chunks],
        task_type="RETRIEVAL_DOCUMENT",
        on_batch_done=on_batch_done,
    )
    matrix = _normalize_rows(np.asarray(vectors, dtype=np.float32))

    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(".tmp.npy")
            np.save(tmp, matrix)
            tmp.replace(cache_path)
        except Exception as exc:
            logger.warning("Gagal simpan cache embedding %s: %s", cache_path, exc)
    return matrix


def _chunk_from_local(index: int, chunk: dict, score: float) -> dict:
    source = chunk.get("source_file") or ""
    return {
        "key": f"local:{index}",
        "text": chunk.get("text", ""),
        "source": Path(source).stem if source else "",
        "lampiran": chunk.get("lampiran"),
        "bab": chunk.get("bab"),
        "bagian": chunk.get("bagian"),
        "pasal": chunk.get("pasal"),
        "ayat": chunk.get("ayat"),
        "page_start": chunk.get("page_start"),
        "score": round(float(score), 4),
    }


def retrieve_local(
    units: list[dict],
    embedder: EmbeddingService,
    regulation_chunks: list[dict],
    regulation_matrix: np.ndarray,
    top_k: int = DEFAULT_TOP_K,
) -> None:
    """Isi unit["regulations"] dengan top-K chunk regulasi (cosine) — in-place."""
    if not units:
        return
    query = _normalize_rows(np.asarray(
        embedder.embed_batch([unit_query_text(u) for u in units], task_type="RETRIEVAL_QUERY"),
        dtype=np.float32,
    ))
    scores = query @ regulation_matrix.T
    k = min(top_k, regulation_matrix.shape[0])
    for unit, row in zip(units, scores):
        best = np.argsort(-row)[:k]
        unit["regulations"] = [
            _chunk_from_local(int(i), regulation_chunks[int(i)], row[int(i)]) for i in best
        ]
