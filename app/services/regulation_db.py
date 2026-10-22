"""
Regulation Database — wrapper LanceDB untuk menyimpan & retrieve
regulasi yang sudah di-index.

Menggunakan LanceDB (embedded, serverless, no C++ compiler required).

Struktur:
- Data tersimpan di data/lancedb/
- 1 table: "regulations" — setiap row = 1 chunk
- Kolom: id, vector, text, + metadata columns
- Registry (metadata regulasi) disimpan di data/regulations.json
- Salinan file sumber disimpan di data/regulation_sources/{id}{ext}
  supaya regulasi bisa di-index ulang saat parser/embedding diperbaiki.

Retrieval (INDEX_VERSION 2):
- Teks yang di-embed diberi header konteks "<nama regulasi> <Pasal/ayat>",
  sehingga chunk ayat pendek ("(2) ... sebagaimana dimaksud pada ayat (1)")
  tetap bermakna; vektor dinormalisasi; jarak cosine.
- Index full-text (FTS) di kolom text → query hybrid (vektor + kata kunci,
  digabung dengan Reciprocal Rank Fusion). Kata kunci membantu istilah
  spesifik ("Pusat Data", "subkontrak", "Pasal 30") yang kadang meleset
  di pencarian semantik murni.
"""

import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import lancedb
import numpy as np
import pyarrow as pa

from app.prompts.compliance_review_prompt import format_regulation_ref
from app.services.json_store import locked, write_json_atomic
from app.services.regulation_parser import PARSER_VERSION

logger = logging.getLogger(__name__)

LANCEDB_DIR = Path("data/lancedb")
REGISTRY_FILE = Path("data/regulations.json")
SOURCES_DIR = Path("data/regulation_sources")
TABLE_NAME = "regulations"

# Naikkan setiap kali cara membangun index berubah (teks embedding, normalisasi,
# FTS). Regulasi dengan versi lebih lama ditandai needs_reindex.
INDEX_VERSION = 2

_EMBED_TEXT_MAX_CHARS = 6000
_FTS_QUERY_MAX_TERMS = 64

# Hybrid search (LanceDB) mengambil `limit` kandidat dari pencarian vektor DAN
# kata kunci, baru menggabungkannya (RRF). Kolam kecil (= top_k) membuang chunk
# yang cukup bagus di keduanya tapi bukan juara di salah satunya — mis. PADK
# "3. Uji Tuntas" untuk "sebelum memilih penyedia jasa TI". Ambil kolam besar
# lalu potong ke top_k. Eval 25 query: label benar di top-5 24/25 → 25/25.
_HYBRID_MIN_CANDIDATES = 40


def hybrid_candidate_pool(top_k: int) -> int:
    return max(top_k, _HYBRID_MIN_CANDIDATES)


class RegulationDBError(Exception):
    """Error umum dari Regulation DB."""


class DuplicateRegulationError(RegulationDBError):
    """File yang sama persis (SHA-256) sudah ada di database."""

    def __init__(self, existing: dict):
        super().__init__(
            f"File ini sudah ada di database sebagai '{existing.get('name')}'."
        )
        self.existing = existing


# =============================================================================
# SCHEMA
# =============================================================================

def _get_schema(vector_dim: int = 768) -> pa.Schema:
    """Arrow schema untuk table regulations."""
    return pa.schema([
        pa.field("id", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), vector_dim)),
        pa.field("text", pa.string()),
        pa.field("regulation_id", pa.string()),
        pa.field("regulation_name", pa.string()),
        pa.field("chunk_index", pa.int32()),
        pa.field("source_file", pa.string()),
        pa.field("source_type", pa.string()),
        pa.field("lampiran", pa.string()),
        pa.field("bab", pa.string()),
        pa.field("bagian", pa.string()),
        pa.field("pasal", pa.string()),
        pa.field("ayat", pa.string()),
        pa.field("butir", pa.string()),
        pa.field("page_start", pa.int32()),
        pa.field("page_end", pa.int32()),
    ])


# =============================================================================
# CONNECTION (singleton)
# =============================================================================

_db = None


def _get_db():
    global _db
    if _db is None:
        LANCEDB_DIR.mkdir(parents=True, exist_ok=True)
        _db = lancedb.connect(str(LANCEDB_DIR))
    return _db


def _get_table():
    """Buka table; None kalau belum ada."""
    db = _get_db()
    if TABLE_NAME in db.table_names():
        return db.open_table(TABLE_NAME)
    return None


def _has_fts_index(tbl) -> bool:
    try:
        return any(idx.index_type == "FTS" for idx in tbl.list_indices())
    except Exception:
        return False


def rebuild_fts_index() -> None:
    """
    (Re)build index full-text di kolom text. Dipanggil setelah add/delete:
    tabel kecil (ribuan baris), jadi rebuild penuh murah dan selalu konsisten.
    Tanpa stemming/stop-word bahasa Inggris — teksnya bahasa Indonesia.
    """
    from lancedb.index import FTS

    tbl = _get_table()
    if tbl is None or tbl.count_rows() == 0:
        return
    try:
        tbl.create_index(
            "text",
            config=FTS(stem=False, remove_stop_words=False, lower_case=True, ascii_folding=True),
            replace=True,
        )
    except Exception as exc:  # retrieval tetap jalan (vektor saja)
        logger.warning("Gagal membangun index FTS: %s", exc)


# =============================================================================
# TEKS EMBEDDING
# =============================================================================

def regulation_embed_text(chunk: dict) -> str:
    """
    Teks yang di-embed untuk satu chunk regulasi: header konteks + isi.
    chunk["source"] (atau source_file) = nama regulasi.
    """
    header = format_regulation_ref(chunk)
    return f"{header}\n{chunk.get('text', '')}".strip()[:_EMBED_TEXT_MAX_CHARS]


def normalize_vectors(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


# =============================================================================
# REGISTRY
# =============================================================================

def _load_registry() -> dict:
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_FILE.exists():
        return {"regulations": []}
    try:
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"regulations": []}


def _save_registry(data: dict) -> None:
    write_json_atomic(REGISTRY_FILE, data)


def _update_registry_entry(regulation_id: str, **changes) -> dict | None:
    with locked(REGISTRY_FILE):
        registry = _load_registry()
        for reg in registry.get("regulations", []):
            if reg.get("id") == regulation_id:
                reg.update(changes)
                _save_registry(registry)
                return reg
    return None


def needs_reindex(reg: dict) -> bool:
    return (
        reg.get("parser_version") != PARSER_VERSION
        or reg.get("index_version") != INDEX_VERSION
    )


def source_path(reg: dict) -> Path | None:
    raw = reg.get("source_path")
    if not raw:
        return None
    path = Path(raw)
    return path if path.exists() else None


def list_regulations() -> list[dict]:
    """Ambil semua regulasi yang tersimpan di database (+ status index)."""
    registry = _load_registry()
    regs = []
    for reg in registry.get("regulations", []):
        regs.append({
            **reg,
            "has_source": source_path(reg) is not None,
            "needs_reindex": needs_reindex(reg),
        })
    return regs


def get_regulation(regulation_id: str) -> dict | None:
    """Ambil 1 regulasi berdasarkan ID."""
    for reg in list_regulations():
        if reg.get("id") == regulation_id:
            return reg
    return None


def find_by_sha256(file_sha256: str) -> dict | None:
    for reg in list_regulations():
        if reg.get("file_sha256") == file_sha256:
            return reg
    return None


def store_source_file(regulation_id: str, data: bytes, extension: str) -> Path:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCES_DIR / f"{regulation_id}{extension.lower()}"
    path.write_bytes(data)
    return path


def adopt_source_file(regulation_id: str, path: Path, file_sha256: str) -> Path:
    """Salin file sumber untuk regulasi lama yang belum menyimpan sumbernya."""
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    dest = SOURCES_DIR / f"{regulation_id}{path.suffix.lower()}"
    shutil.copyfile(path, dest)
    _update_registry_entry(regulation_id, source_path=str(dest), file_sha256=file_sha256)
    return dest


def count_chunks_in_collection(regulation_id: str | None = None) -> int:
    """Hitung total chunks (opsional filter per regulasi)."""
    try:
        tbl = _get_table()
        if tbl is None:
            return 0
        if regulation_id:
            safe_id = regulation_id.replace("'", "''")
            return tbl.count_rows(f"regulation_id = '{safe_id}'")
        return tbl.count_rows()
    except Exception as exc:
        logger.warning("Gagal hitung chunks: %s", exc)
        return 0


# =============================================================================
# ADD / REPLACE
# =============================================================================

def _build_rows(
    regulation_id: str,
    name: str,
    filename: str,
    source_type: str,
    chunks: list[dict],
    embeddings: np.ndarray,
) -> list[dict]:
    rows: list[dict] = []
    for i, chunk in enumerate(chunks):
        rows.append({
            "id": f"{regulation_id}_{i}",
            "vector": [float(x) for x in embeddings[i]],
            "text": chunk.get("text", "") or "",
            "regulation_id": regulation_id,
            "regulation_name": name,
            "chunk_index": int(i),
            "source_file": filename,
            "source_type": source_type,
            "lampiran": chunk.get("lampiran") or "",
            "bab": chunk.get("bab") or "",
            "bagian": chunk.get("bagian") or "",
            "pasal": chunk.get("pasal") or "",
            "ayat": chunk.get("ayat") or "",
            "butir": chunk.get("butir") or "",
            "page_start": int(chunk.get("page_start") or 0),
            "page_end": int(chunk.get("page_end") or 0),
        })
    return rows


def _insert_rows(rows: list[dict]) -> None:
    tbl = _get_table()
    if tbl is None:
        _get_db().create_table(TABLE_NAME, data=rows, schema=_get_schema())
    else:
        tbl.add(rows)


def add_regulation(
    name: str,
    filename: str,
    chunks: list[dict],
    embeddings: list[list[float]],
    source_type: str = "manual",
    source_bytes: bytes | None = None,
    file_sha256: str = "",
) -> dict:
    """
    Tambah regulasi baru ke database.

    Args:
        name: nama regulasi (mis. "POJK 11/2022")
        filename: nama file asli
        chunks: list chunk dari parse_regulation_structure
        embeddings: embedding dari regulation_embed_text(chunk) (same length)
        source_type: "manual" | "preload"
        source_bytes: isi file asli — disimpan agar bisa di-index ulang
        file_sha256: hash file asli — untuk cek duplikat

    Returns:
        dict metadata regulasi yang baru dibuat
    """
    if not chunks:
        raise RegulationDBError("Tidak ada chunk untuk disimpan.")
    if len(chunks) != len(embeddings):
        raise RegulationDBError(
            f"Jumlah chunk ({len(chunks)}) != embedding ({len(embeddings)})."
        )

    regulation_id = uuid.uuid4().hex
    rows = _build_rows(
        regulation_id, name, filename, source_type, chunks, normalize_vectors(embeddings)
    )
    try:
        _insert_rows(rows)
    except Exception as exc:
        raise RegulationDBError(f"Gagal simpan ke LanceDB: {exc}") from exc
    rebuild_fts_index()

    reg_meta = {
        "id": regulation_id,
        "name": name,
        "filename": filename,
        "total_chunks": len(chunks),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_type": source_type,
        "file_sha256": file_sha256,
        "parser_version": PARSER_VERSION,
        "index_version": INDEX_VERSION,
    }
    if source_bytes is not None:
        reg_meta["source_path"] = str(
            store_source_file(regulation_id, source_bytes, Path(filename).suffix)
        )

    with locked(REGISTRY_FILE):
        registry = _load_registry()
        registry.setdefault("regulations", []).append(reg_meta)
        _save_registry(registry)

    logger.info(
        "Regulasi '%s' ditambahkan: %d chunks (id=%s)",
        name, len(chunks), regulation_id,
    )
    return reg_meta


def replace_regulation_chunks(
    regulation_id: str,
    chunks: list[dict],
    embeddings: list[list[float]],
) -> dict:
    """Index ulang: ganti seluruh chunk satu regulasi (ID regulasi tetap)."""
    reg = get_regulation(regulation_id)
    if reg is None:
        raise RegulationDBError("Regulasi tidak ditemukan.")
    if not chunks or len(chunks) != len(embeddings):
        raise RegulationDBError("Chunk/embedding untuk index ulang tidak valid.")

    rows = _build_rows(
        regulation_id, reg["name"], reg.get("filename", ""),
        reg.get("source_type", "manual"), chunks, normalize_vectors(embeddings),
    )
    try:
        tbl = _get_table()
        if tbl is not None:
            safe_id = regulation_id.replace("'", "''")
            tbl.delete(f"regulation_id = '{safe_id}'")
        _insert_rows(rows)
    except Exception as exc:
        raise RegulationDBError(f"Gagal mengganti chunk di LanceDB: {exc}") from exc
    rebuild_fts_index()

    updated = _update_registry_entry(
        regulation_id,
        total_chunks=len(chunks),
        parser_version=PARSER_VERSION,
        index_version=INDEX_VERSION,
        reindexed_at=datetime.now(timezone.utc).isoformat(),
    )
    logger.info("Regulasi '%s' di-index ulang: %d chunks", reg["name"], len(chunks))
    return updated or reg


# =============================================================================
# DELETE
# =============================================================================

def delete_regulation(regulation_id: str) -> bool:
    """Hapus regulasi (chunks + registry + file sumber). Return True kalau berhasil."""
    reg = get_regulation(regulation_id)
    if not reg:
        return False

    try:
        tbl = _get_table()
        if tbl is not None:
            safe_id = regulation_id.replace("'", "''")
            tbl.delete(f"regulation_id = '{safe_id}'")
    except Exception as exc:
        logger.warning("Gagal hapus chunks: %s", exc)
        raise RegulationDBError(f"Gagal hapus chunks: {exc}") from exc
    rebuild_fts_index()

    with locked(REGISTRY_FILE):
        registry = _load_registry()
        registry["regulations"] = [
            r for r in registry.get("regulations", [])
            if r.get("id") != regulation_id
        ]
        _save_registry(registry)

    src = source_path(reg)
    if src is not None:
        src.unlink(missing_ok=True)

    logger.info("Regulasi dihapus: %s (id=%s)", reg.get("name"), regulation_id)
    return True


# =============================================================================
# QUERY / RETRIEVE
# =============================================================================

def load_regulation_rows(regulation_id: str) -> list[dict]:
    """Semua chunk satu regulasi (termasuk vektor), urut chunk_index."""
    tbl = _get_table()
    if tbl is None:
        return []
    safe_id = regulation_id.replace("'", "''")
    try:
        rows = tbl.search().where(f"regulation_id = '{safe_id}'").limit(None).to_list()
    except Exception as exc:
        raise RegulationDBError(f"Gagal memuat chunk regulasi: {exc}") from exc
    rows.sort(key=lambda r: r.get("chunk_index", 0))
    return rows


def _fts_query_text(text: str) -> str:
    """Query FTS aman: hanya kata (tanpa operator/tanda baca), dibatasi panjangnya."""
    terms = re.findall(r"[0-9A-Za-zÀ-ÿ]{3,}", text or "")
    return " ".join(terms[:_FTS_QUERY_MAX_TERMS])


def query_relevant_chunks(
    query_embedding: list[float],
    regulation_ids: list[str] | None = None,
    top_k: int = 5,
    query_text: str | None = None,
) -> list[dict]:
    """
    Cari chunk paling relevan dari database.

    Args:
        query_embedding: embedding dari query
        regulation_ids: filter ke regulasi tertentu (None = semua)
        top_k: jumlah chunk yang dikembalikan
        query_text: teks query asli; kalau ada (dan index FTS tersedia),
            pencarian dilakukan hybrid (vektor + kata kunci, RRF).

    Returns:
        list of dict: {id, text, metadata, distance, score}
        - distance: jarak cosine (mode vektor saja)
        - score: skor relevansi RRF (mode hybrid)
    """
    tbl = _get_table()
    if tbl is None:
        return []

    where = None
    if regulation_ids:
        ids_str = ", ".join(f"'{rid.replace(chr(39), chr(39) * 2)}'" for rid in regulation_ids)
        where = f"regulation_id IN ({ids_str})"

    query_vec = [float(x) for x in query_embedding]
    fts_text = _fts_query_text(query_text or "")
    try:
        hybrid = bool(fts_text) and _has_fts_index(tbl)
        if hybrid:
            search = (
                tbl.search(query_type="hybrid")
                .vector(query_vec)
                .text(fts_text)
                .distance_type("cosine")
            )
            limit = hybrid_candidate_pool(top_k)
        else:
            # Cosine: vektor Gemini 768-dim (hasil potong dari 3072) tidak
            # ternormalisasi di index lama, jadi L2 bias terhadap panjang vektor.
            search = tbl.search(query_vec).distance_type("cosine")
            limit = top_k
        if where:
            search = search.where(where)
        results = search.limit(limit).to_list()[:top_k]
    except Exception as exc:
        raise RegulationDBError(f"Gagal query LanceDB: {exc}") from exc

    chunks: list[dict] = []
    for row in results:
        chunks.append({
            "id": row.get("id", ""),
            "text": row.get("text", ""),
            "metadata": {
                "regulation_id": row.get("regulation_id", ""),
                "regulation_name": row.get("regulation_name", ""),
                "chunk_index": row.get("chunk_index", 0),
                "source_file": row.get("source_file", ""),
                "source_type": row.get("source_type", ""),
                "lampiran": row.get("lampiran", ""),
                "bab": row.get("bab", ""),
                "bagian": row.get("bagian", ""),
                "pasal": row.get("pasal", ""),
                "ayat": row.get("ayat", ""),
                "butir": row.get("butir", ""),
                "page_start": row.get("page_start", 0),
                "page_end": row.get("page_end", 0),
            },
            "distance": row.get("_distance"),
            "score": row.get("_relevance_score"),
        })

    return chunks


# =============================================================================
# STATS
# =============================================================================

def get_db_stats() -> dict:
    """Statistik database regulasi."""
    regs = list_regulations()

    total_size = 0
    if LANCEDB_DIR.exists():
        for f in LANCEDB_DIR.rglob("*"):
            if f.is_file():
                try:
                    total_size += f.stat().st_size
                except Exception:
                    pass

    try:
        tbl = _get_table()
        total_chunks = tbl.count_rows() if tbl is not None else 0
    except Exception:
        total_chunks = 0

    return {
        "total_regulations": len(regs),
        "total_chunks": total_chunks,
        "db_size_mb": round(total_size / (1024 * 1024), 2),
    }


def reset_database() -> None:
    """Hapus SELURUH database regulasi. Untuk maintenance."""
    global _db

    try:
        db = _get_db()
        if TABLE_NAME in db.table_names():
            db.drop_table(TABLE_NAME)
    except Exception as exc:
        logger.warning("Gagal drop table: %s", exc)

    _db = None
    with locked(REGISTRY_FILE):
        _save_registry({"regulations": []})
    if SOURCES_DIR.exists():
        shutil.rmtree(SOURCES_DIR, ignore_errors=True)
    logger.info("Database regulasi direset.")
