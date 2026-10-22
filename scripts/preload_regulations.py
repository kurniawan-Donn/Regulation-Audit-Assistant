"""
Preload Regulations Script.

Auto-index semua file regulasi (PDF/TXT) dari folder tertentu ke
Regulation Database (LanceDB).

Cara pakai:
    python -m scripts.preload_regulations <folder>

Contoh:
    python -m scripts.preload_regulations ./data/preload_regulations

Format nama file yang direkomendasikan:
    POJK_11_2022.pdf         -> "POJK 11/2022"
    PADK_43_2025.pdf         -> "PADK 43/2025"
    SEOJK_MRTI.pdf           -> "SEOJK MRTI"

Script akan otomatis:
- Deteksi nama regulasi dari nama file
- Skip file yang sudah ada di DB (berdasarkan filename)
- Parse → embed → simpan
- Tampilkan progress
"""

import sys
import time
from pathlib import Path


def _normalize_name(filename: str) -> str:
    """
    Konversi nama file ke nama regulasi yang readable.

    POJK_11_2022.pdf         -> "POJK 11/2022"
    PADK_43_PADK03_2025.pdf  -> "PADK 43 PADK03 2025"
    SEOJK_MRTI.pdf           -> "SEOJK MRTI"
    """
    stem = Path(filename).stem
    # Ganti underscore/dash jadi spasi
    name = stem.replace("_", " ").replace("-", " ")
    # Rapikan multiple spaces
    name = " ".join(name.split())

    # Coba pattern umum: NAMA_NOMOR_TAHUN
    # Contoh: POJK 11 2022 -> POJK 11/2022
    parts = name.split()
    if len(parts) >= 3:
        # Cek apakah parts[-1] adalah tahun (4 digit)
        if parts[-1].isdigit() and len(parts[-1]) == 4:
            # Cek apakah parts[-2] adalah nomor (1-3 digit)
            if parts[-2].isdigit() and len(parts[-2]) <= 3:
                prefix = " ".join(parts[:-2])
                return f"{prefix} {parts[-2]}/{parts[-1]}"

    return name


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.preload_regulations <folder>")
        print()
        print("Contoh:")
        print("  python -m scripts.preload_regulations ./data/preload_regulations")
        return 1

    folder = Path(sys.argv[1]).resolve()
    if not folder.exists() or not folder.is_dir():
        print(f"❌ Folder tidak ditemukan: {folder}")
        return 1

    # Import setelah cek argv (biar error message jelas)
    from app.services.embedding_service import EmbeddingService, EmbeddingError
    from app.services.pdf_parser import extract_pdf_text, PDFExtractionError
    from app.services.regulation_db import (
        add_regulation,
        get_db_stats,
        list_regulations,
        RegulationDBError,
    )
    from app.services.regulation_parser import parse_regulation_structure
    from app.services.text_processor import (
        clean_text,
        extract_txt_text,
        TextExtractionError,
    )

    # Cari file PDF/TXT
    files = sorted([
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in {".pdf", ".txt"}
    ])

    if not files:
        print(f"❌ Tidak ada file PDF/TXT di: {folder}")
        return 1

    print(f"📁 Folder: {folder}")
    print(f"📄 Ditemukan {len(files)} file")
    print()

    # Cek existing
    existing = {r.get("filename") for r in list_regulations()}
    files_to_process = [f for f in files if f.name not in existing]

    skipped = len(files) - len(files_to_process)
    if skipped > 0:
        print(f"⏭️  Skip {skipped} file yang sudah ada di DB")

    if not files_to_process:
        print("✅ Semua file sudah di-index. Tidak ada yang perlu diproses.")
        return 0

    print(f"🚀 Akan memproses {len(files_to_process)} file")
    print()

    # Init embedding service (cek API key sekali)
    try:
        svc = EmbeddingService()
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1

    success_count = 0
    fail_count = 0

    for i, f in enumerate(files_to_process, start=1):
        print(f"[{i}/{len(files_to_process)}] {f.name}")
        start_ts = time.time()

        # 1. Extract text
        try:
            if f.suffix.lower() == ".pdf":
                raw = extract_pdf_text(str(f))
            else:
                raw = extract_txt_text(str(f))
        except (PDFExtractionError, TextExtractionError) as exc:
            print(f"   ❌ Extract gagal: {exc}")
            fail_count += 1
            continue

        # 2. Clean + parse
        cleaned = clean_text(raw)
        chunks = parse_regulation_structure(cleaned)
        if not chunks:
            print(f"   ❌ Tidak ada chunk setelah parsing")
            fail_count += 1
            continue
        print(f"   📊 {len(chunks)} chunks")

        # 3. Embed
        try:
            texts = [c.get("text", "") for c in chunks]
            print(f"   🔄 Embedding... (ini bisa 10-60 detik)")
            embeddings = svc.embed_batch(texts, task_type="RETRIEVAL_DOCUMENT")
        except EmbeddingError as exc:
            print(f"   ❌ Embed gagal: {exc}")
            fail_count += 1
            continue

        # 4. Simpan
        name = _normalize_name(f.name)
        try:
            meta = add_regulation(
                name=name,
                filename=f.name,
                chunks=chunks,
                embeddings=embeddings,
                source_type="preload",
            )
        except RegulationDBError as exc:
            print(f"   ❌ Simpan gagal: {exc}")
            fail_count += 1
            continue

        elapsed = time.time() - start_ts
        print(f"   ✅ '{name}' ({len(chunks)} chunks, {elapsed:.1f}s)")
        print()
        success_count += 1

    # Summary
    print("=" * 60)
    print(f"✅ Sukses: {success_count}")
    print(f"❌ Gagal:  {fail_count}")

    stats = get_db_stats()
    print()
    print("📊 Database stats:")
    print(f"   Regulasi:  {stats['total_regulations']}")
    print(f"   Chunks:    {stats['total_chunks']}")
    print(f"   Ukuran:    {stats['db_size_mb']} MB")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())