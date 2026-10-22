"""
Regulation Database — wrapper LanceDB untuk menyimpan & retrieve
regulasi yang sudah di-index.

Menggunakan LanceDB (embedded, serverless, no C++ compiler required).

Struktur:
- Data tersimpan di data/lancedb/
- 1 table: "regulations" — setiap row = 1 chunk
- Kolom: id, vector, text, + metadata columns
- Registry (metadata regulasi) disimpan di data/regulations.json
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import lancedb
import pyarrow as pa

logger = logging.getLogger(__name__)

LANCEDB_DIR = Path("data/lancedb")
REGISTRY_FILE = Path("data/regulations.json")
TABLE_NAME = "regulations"


class RegulationDBError(Exception):
    """Error umum dari Regulation DB."""


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
    """Buka table; buat kalau belum ada."""
    db = _get_db()
    if TABLE_NAME in db.table_names():
        return db.open_table(TABLE_NAME)
    return None


def _get_or_create_table():
    """Buka table atau buat kalau belum ada."""
    db = _get_db()
    if TABLE_NAME in db.table_names():
        return db.open_table(TABLE_NAME)
    # Buat table kosong dengan schema
    schema = _get_schema()
    return db.create_table(TABLE_NAME, schema=schema)


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
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_regulations() -> list[dict]:
    """Ambil semua regulasi yang tersimpan di database."""
    registry = _load_registry()
    return registry.get("regulations", [])


def get_regulation(regulation_id: str) -> dict | None:
    """Ambil 1 regulasi berdasarkan ID."""
    for reg in list_regulations():
        if reg.get("id") == regulation_id:
            return reg
    return None


def count_chunks_in_collection(regulation_id: str | None = None) -> int:
    """Hitung total chunks (opsional filter per regulasi)."""
    try:
        tbl = _get_table()
        if tbl is None:
            return 0
        if regulation_id:
            # Escape single quote untuk SQL filter
            safe_id = regulation_id.replace("'", "''")
            result = tbl.search().where(f"regulation_id = '{safe_id}'").to_list()
            return len(result)
        return tbl.count_rows()
    except Exception as exc:
        logger.warning("Gagal hitung chunks: %s", exc)
        return 0


# =============================================================================
# ADD REGULATION
# =============================================================================

def add_regulation(
    name: str,
    filename: str,
    chunks: list[dict],
    embeddings: list[list[float]],
    source_type: str = "manual",
) -> dict:
    """
    Tambah regulasi baru ke database.

    Args:
        name: nama regulasi (mis. "POJK 11/2022")
        filename: nama file asli
        chunks: list chunk dari parse_regulation_structure
        embeddings: list embedding (same length as chunks)
        source_type: "manual" | "preload"

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

    # Build rows
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

    # Insert ke LanceDB
    try:
        tbl = _get_table()
        if tbl is None:
            # Buat table dengan data pertama
            schema = _get_schema()
            db = _get_db()
            db.create_table(TABLE_NAME, data=rows, schema=schema)
        else:
            tbl.add(rows)
    except Exception as exc:
        raise RegulationDBError(f"Gagal simpan ke LanceDB: {exc}") from exc

    # Save registry
    reg_meta = {
        "id": regulation_id,
        "name": name,
        "filename": filename,
        "total_chunks": len(chunks),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_type": source_type,
    }

    registry = _load_registry()
    registry.setdefault("regulations", []).append(reg_meta)
    _save_registry(registry)

    logger.info(
        "Regulasi '%s' ditambahkan: %d chunks (id=%s)",
        name, len(chunks), regulation_id,
    )

    return reg_meta


# =============================================================================
# DELETE
# =============================================================================

def delete_regulation(regulation_id: str) -> bool:
    """Hapus regulasi (chunks + registry). Return True kalau berhasil."""
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

    registry = _load_registry()
    registry["regulations"] = [
        r for r in registry.get("regulations", [])
        if r.get("id") != regulation_id
    ]
    _save_registry(registry)

    logger.info("Regulasi dihapus: %s (id=%s)", reg.get("name"), regulation_id)
    return True


# =============================================================================
# QUERY / RETRIEVE
# =============================================================================

def query_relevant_chunks(
    query_embedding: list[float],
    regulation_ids: list[str] | None = None,
    top_k: int = 5,
) -> list[dict]:
    """
    Cari chunk paling relevan dari database.

    Args:
        query_embedding: embedding dari query
        regulation_ids: filter ke regulasi tertentu (None = semua)
        top_k: jumlah chunk yang dikembalikan

    Returns:
        list of dict: {id, text, metadata, distance}
    """
    tbl = _get_table()
    if tbl is None:
        return []

    try:
        query_vec = [float(x) for x in query_embedding]
        search = tbl.search(query_vec).limit(top_k)

        # Apply filter kalau ada
        if regulation_ids and len(regulation_ids) > 0:
            if len(regulation_ids) == 1:
                safe_id = regulation_ids[0].replace("'", "''")
                search = search.where(f"regulation_id = '{safe_id}'")
            else:
                # IN clause
                ids_str = ", ".join(
                    f"'{rid.replace(chr(39), chr(39)*2)}'"
                    for rid in regulation_ids
                )
                search = search.where(f"regulation_id IN ({ids_str})")

        results = search.to_list()
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
    _save_registry({"regulations": []})
    logger.info("Database regulasi direset.")