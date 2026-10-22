"""
Index ulang Regulation DB dengan parser & embedding terbaru.

Cara pakai:
    python -m scripts.reindex_regulations [--all] [--dry-run]
        [--search-dir uploads --search-dir data/preload_regulations]

Langkah:
1. Regulasi lama yang belum menyimpan file sumber: cari file sumbernya di
   --search-dir dengan MENCOCOKKAN ISI (bukan nama file — salinan upload
   lama bernama acak db_<uuid>.pdf). File yang cocok disalin ke
   data/regulation_sources/ dan hash-nya dicatat di registry.
2. Regulasi dengan needs_reindex (atau semua, dengan --all) di-parse ulang,
   di-embed ulang (header konteks), dan chunk-nya diganti. ID regulasi
   tetap, sehingga hasil Compliance Review lama tetap merujuk regulasi yang sama.

Backup data/lancedb + data/regulations.json dulu sebelum menjalankan.
"""

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import regulation_db  # noqa: E402
from app.services.analysis_jobs import (  # noqa: E402
    embed_regulation_for_index,
    parse_regulation_file,
)
from app.services.embedding_service import EmbeddingService  # noqa: E402
from app.services.pdf_parser import PDFExtractionError, extract_pdf_text  # noqa: E402
from app.services.text_processor import (  # noqa: E402
    TextExtractionError,
    clean_text,
    extract_txt_text,
)

_MATCH_MIN_SCORE = 0.6
_MATCH_MIN_MARGIN = 0.2


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _candidate_files(dirs: list[str]) -> dict[str, Path]:
    """sha256 → path (file identik hanya dihitung sekali)."""
    found: dict[str, Path] = {}
    for d in dirs:
        for path in sorted(Path(d).glob("*")):
            if path.suffix.lower() not in (".pdf", ".txt") or not path.is_file():
                continue
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            found.setdefault(sha, path)
    return found


def _read_text(path: Path) -> str:
    raw = extract_pdf_text(str(path)) if path.suffix.lower() == ".pdf" else extract_txt_text(str(path))
    return _norm(clean_text(raw))


def adopt_missing_sources(search_dirs: list[str], dry_run: bool) -> None:
    missing = [r for r in regulation_db.list_regulations() if not r["has_source"]]
    if not missing:
        return
    print(f"{len(missing)} regulasi belum menyimpan file sumber — mencocokkan isi...")
    candidates = _candidate_files(search_dirs)
    texts: dict[str, str] = {}
    for sha, path in candidates.items():
        try:
            texts[sha] = _read_text(path)
        except (PDFExtractionError, TextExtractionError):
            continue  # mis. PDF hasil scan tanpa teks — bukan kandidat

    tbl = regulation_db._get_table()
    rows = tbl.search().select(["regulation_id", "text"]).to_list() if tbl is not None else []
    for reg in missing:
        probes = [
            _norm(r["text"])[:60] for r in rows
            if r["regulation_id"] == reg["id"] and len(r["text"]) > 80
        ]
        if not probes:
            print(f"  ? {reg['name']}: tidak ada chunk untuk dicocokkan — lewati")
            continue
        scores = sorted(
            ((sum(p in texts[sha] for p in probes) / len(probes), sha) for sha in texts),
            reverse=True,
        )
        best, sha = scores[0]
        second = scores[1][0] if len(scores) > 1 else 0.0
        if best < _MATCH_MIN_SCORE or best - second < _MATCH_MIN_MARGIN:
            print(f"  ✗ {reg['name']}: tidak ada file yang cocok meyakinkan "
                  f"(terbaik {best:.2f}, kedua {second:.2f}) — upload ulang manual")
            continue
        print(f"  ✓ {reg['name']} ← {candidates[sha]} (skor {best:.2f}, kedua {second:.2f})")
        if not dry_run:
            regulation_db.adopt_source_file(reg["id"], candidates[sha], sha)


def reindex(reindex_all: bool, dry_run: bool) -> None:
    embedder = EmbeddingService()
    regs = [
        r for r in regulation_db.list_regulations()
        if r["has_source"] and (reindex_all or r["needs_reindex"])
    ]
    print(f"{len(regs)} regulasi akan di-index ulang.")
    for reg in regs:
        t0 = time.time()
        chunks = parse_regulation_file(regulation_db.source_path(reg))
        print(f"  • {reg['name']}: {reg.get('total_chunks')} → {len(chunks)} chunk", end="", flush=True)
        if dry_run:
            print(" (dry-run)")
            continue
        embeddings = embed_regulation_for_index(reg["name"], chunks, embedder)
        regulation_db.replace_regulation_chunks(reg["id"], chunks, embeddings)
        print(f"  [{time.time() - t0:.1f} dtk]")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="index ulang semua, bukan hanya yang usang")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--search-dir", action="append",
                        default=None, help="folder pencarian file sumber regulasi lama")
    args = parser.parse_args()

    adopt_missing_sources(args.search_dir or ["uploads", "data/preload_regulations"], args.dry_run)
    reindex(args.all, args.dry_run)
    print("Selesai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
