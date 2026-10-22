"""
Database Quality Analyzer.

Script diagnostic untuk menganalisis kualitas data yang tersimpan di
Regulation Database (LanceDB).

GRATIS — tidak memanggil API. Baca langsung dari LanceDB.

Analisis yang dilakukan:
- Statistik per regulasi: total chunks, char, word, page coverage
- Deteksi anomali: chunk kosong, terlalu pendek, terlalu panjang
- Deteksi duplikat
- Distribusi ukuran chunk (histogram)
- Sample chunk terbesar & terkecil
- Rekomendasi otomatis

Cara pakai:
    python -m scripts.analyze_db_quality                      # semua regulasi
    python -m scripts.analyze_db_quality --reg-id <id>        # 1 regulasi
    python -m scripts.analyze_db_quality --export report.json # export JSON
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


# =============================================================================
# ANSI COLORS
# =============================================================================

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"


# =============================================================================
# THRESHOLDS (untuk deteksi anomali)
# =============================================================================

MIN_CHUNK_CHARS = 20         # < 20 char = anomali (terlalu pendek)
MAX_CHUNK_CHARS = 8000       # > 8000 char = anomali (terlalu panjang, mungkin gabungan)
MIN_CHUNKS_PER_PAGE = 0.3    # < 0.3 chunk per halaman = kehilangan data
MAX_CHUNKS_PER_PAGE = 10     # > 10 chunk per halaman = over-splitting


# =============================================================================
# HELPERS
# =============================================================================

def _bar(value: int, max_value: int, width: int = 30, char: str = "█") -> str:
    """Buat bar visual."""
    if max_value <= 0:
        return ""
    filled = int((value / max_value) * width)
    return char * filled + "░" * (width - filled)


def _truncate(text: str, max_len: int = 80) -> str:
    """Potong teks panjang."""
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _hbar_distribution(values: list[int], buckets: int = 8) -> list[tuple[str, int]]:
    """Buat histogram distribusi."""
    if not values:
        return []

    min_v = min(values)
    max_v = max(values)

    if min_v == max_v:
        return [(f"Semua: {min_v}", len(values))]

    step = (max_v - min_v) / buckets
    result = []
    for i in range(buckets):
        low = int(min_v + i * step)
        high = int(min_v + (i + 1) * step)
        count = sum(1 for v in values if low <= v < high or (i == buckets - 1 and v == high))
        label = f"{low:>5} - {high:>5}"
        result.append((label, count))
    return result


def _median(values: list[int]) -> float:
    if not values:
        return 0
    sorted_v = sorted(values)
    n = len(sorted_v)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_v[mid - 1] + sorted_v[mid]) / 2
    return sorted_v[mid]


# =============================================================================
# ANALYZER
# =============================================================================

def analyze_regulation(reg_meta: dict, all_chunks: list[dict]) -> dict:
    """Analisis 1 regulasi."""
    reg_id = reg_meta["id"]
    reg_name = reg_meta["name"]

    # Filter chunks milik regulasi ini
    chunks = [c for c in all_chunks if c.get("regulation_id") == reg_id]

    if not chunks:
        return {
            "regulation_id": reg_id,
            "regulation_name": reg_name,
            "total_chunks": 0,
            "error": "Tidak ada chunks di database",
        }

    # Text stats
    texts = [c.get("text", "") for c in chunks]
    char_counts = [len(t) for t in texts]
    word_counts = [len(t.split()) for t in texts]

    # Page stats
    pages_start = [c.get("page_start", 0) for c in chunks if c.get("page_start", 0) > 0]
    pages_end = [c.get("page_end", 0) for c in chunks if c.get("page_end", 0) > 0]

    max_page = max(pages_end) if pages_end else 0
    page_coverage = max_page if max_page > 0 else 0

    # Anomali
    empty_chunks = sum(1 for c, t in zip(chunks, texts) if not t.strip())
    too_short = sum(1 for cc in char_counts if 0 < cc < MIN_CHUNK_CHARS)
    too_long = sum(1 for cc in char_counts if cc > MAX_CHUNK_CHARS)

    # Duplikat (exact match)
    text_counter = Counter(t.strip().lower() for t in texts if t.strip())
    duplicates = sum(count - 1 for count in text_counter.values() if count > 1)

    # Chunks per page
    chunks_per_page = len(chunks) / page_coverage if page_coverage > 0 else 0

    # Sample
    chunk_with_len = [(i, c, len(c.get("text", ""))) for i, c in enumerate(chunks)]
    sorted_by_len = sorted(chunk_with_len, key=lambda x: x[2])

    sample_smallest = [
        {
            "index": i,
            "chars": n,
            "referensi": _build_referensi(c),
            "text": _truncate(c.get("text", ""), 200),
        }
        for i, c, n in sorted_by_len[:5]
    ]
    sample_largest = [
        {
            "index": i,
            "chars": n,
            "referensi": _build_referensi(c),
            "text": _truncate(c.get("text", ""), 200),
        }
        for i, c, n in sorted_by_len[-5:][::-1]
    ]

    # Distribution
    distribution = _hbar_distribution(char_counts)

    # Determine status
    issues = []
    if empty_chunks > 0:
        issues.append(f"{empty_chunks} chunk kosong")
    if too_short > 0:
        issues.append(f"{too_short} chunk terlalu pendek (<{MIN_CHUNK_CHARS} char)")
    if too_long > 0:
        issues.append(f"{too_long} chunk terlalu panjang (>{MAX_CHUNK_CHARS} char)")
    if duplicates > 0:
        issues.append(f"{duplicates} chunk duplikat")
    if page_coverage > 0 and chunks_per_page < MIN_CHUNKS_PER_PAGE:
        issues.append(f"Chunks per page rendah ({chunks_per_page:.2f}) — mungkin kehilangan data")
    if chunks_per_page > MAX_CHUNKS_PER_PAGE:
        issues.append(f"Chunks per page tinggi ({chunks_per_page:.2f}) — over-splitting")

    status = "OK" if not issues else "WARNING"

    return {
        "regulation_id": reg_id,
        "regulation_name": reg_name,
        "filename": reg_meta.get("filename", ""),
        "created_at": reg_meta.get("created_at", ""),
        "total_chunks": len(chunks),
        "status": status,
        "issues": issues,
        "char_stats": {
            "min": min(char_counts),
            "max": max(char_counts),
            "avg": round(sum(char_counts) / len(char_counts), 1),
            "median": _median(char_counts),
            "total": sum(char_counts),
        },
        "word_stats": {
            "min": min(word_counts),
            "max": max(word_counts),
            "avg": round(sum(word_counts) / len(word_counts), 1),
            "median": _median(word_counts),
            "total": sum(word_counts),
        },
        "page_stats": {
            "page_start_min": min(pages_start) if pages_start else 0,
            "page_end_max": max_page,
            "page_coverage": page_coverage,
            "chunks_per_page": round(chunks_per_page, 2),
        },
        "anomalies": {
            "empty": empty_chunks,
            "too_short": too_short,
            "too_long": too_long,
            "duplicates": duplicates,
        },
        "distribution": distribution,
        "sample_smallest": sample_smallest,
        "sample_largest": sample_largest,
    }


def _build_referensi(chunk: dict) -> str:
    parts = [
        chunk.get("lampiran") or "",
        chunk.get("bab") or "",
        chunk.get("bagian") or "",
        chunk.get("pasal") or "",
        chunk.get("ayat") or "",
    ]
    return " / ".join([p for p in parts if p]) or "(no ref)"


# =============================================================================
# REPORT PRINTING
# =============================================================================

def print_report(analyses: list[dict]) -> None:
    """Print report ke terminal dengan warna."""

    print()
    print(f"{C.BOLD}{C.CYAN}{'═' * 78}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  DATABASE QUALITY REPORT{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'═' * 78}{C.RESET}")
    print()

    # Global summary
    total_regs = len(analyses)
    total_chunks = sum(a.get("total_chunks", 0) for a in analyses)
    regs_with_issues = sum(1 for a in analyses if a.get("status") != "OK")

    print(f"  {C.BOLD}Regulasi total:{C.RESET}      {total_regs}")
    print(f"  {C.BOLD}Chunks total:{C.RESET}        {total_chunks:,}")
    print(f"  {C.BOLD}Regulasi warning:{C.RESET}    {regs_with_issues}/{total_regs} "
          f"({C.YELLOW if regs_with_issues else C.GREEN}"
          f"{'⚠ Ada masalah' if regs_with_issues else '✓ Semua OK'}{C.RESET})")
    print()

    # Per regulasi detail
    for i, a in enumerate(analyses, start=1):
        if "error" in a:
            print(f"  {C.RED}✗ {a['regulation_name']}: {a['error']}{C.RESET}")
            continue

        status_color = C.GREEN if a["status"] == "OK" else C.YELLOW
        status_icon = "✓" if a["status"] == "OK" else "⚠"

        print(f"{C.BOLD}{'─' * 78}{C.RESET}")
        print(f"{C.BOLD}#{i}. {a['regulation_name']}{C.RESET}")
        print(f"   File: {C.DIM}{a['filename']}{C.RESET}")
        print(f"   Status: {status_color}{status_icon} {a['status']}{C.RESET}")
        print()

        # Chunks
        print(f"   {C.BOLD}Chunks:{C.RESET} {a['total_chunks']:,}")

        # Char stats
        cs = a["char_stats"]
        print(f"   {C.BOLD}Character count:{C.RESET}")
        print(f"     Min: {cs['min']:,}  |  Max: {cs['max']:,}  |  "
              f"Avg: {cs['avg']:,}  |  Median: {cs['median']}")
        print(f"     Total: {cs['total']:,} karakter")

        # Word stats
        ws = a["word_stats"]
        print(f"   {C.BOLD}Word count:{C.RESET}")
        print(f"     Min: {ws['min']}  |  Max: {ws['max']}  |  "
              f"Avg: {ws['avg']}  |  Median: {ws['median']}")
        print(f"     Total: {ws['total']:,} kata")

        # Page stats
        ps = a["page_stats"]
        if ps["page_coverage"] > 0:
            print(f"   {C.BOLD}Page coverage:{C.RESET}")
            print(f"     Range: hal. {ps['page_start_min']} - {ps['page_end_max']}")
            print(f"     Total: {ps['page_coverage']} halaman")
            print(f"     Chunks/page: {ps['chunks_per_page']:.2f}")

        # Anomalies
        an = a["anomalies"]
        if any(an.values()):
            print(f"   {C.BOLD}{C.YELLOW}Anomali:{C.RESET}")
            if an["empty"] > 0:
                print(f"     {C.RED}✗ {an['empty']} chunk KOSONG{C.RESET}")
            if an["too_short"] > 0:
                print(f"     {C.YELLOW}⚠ {an['too_short']} chunk terlalu pendek (<{MIN_CHUNK_CHARS} char){C.RESET}")
            if an["too_long"] > 0:
                print(f"     {C.YELLOW}⚠ {an['too_long']} chunk terlalu panjang (>{MAX_CHUNK_CHARS} char){C.RESET}")
            if an["duplicates"] > 0:
                print(f"     {C.YELLOW}⚠ {an['duplicates']} chunk duplikat{C.RESET}")

        # Distribution
        print(f"   {C.BOLD}Distribusi ukuran (char):{C.RESET}")
        max_count = max((c for _, c in a["distribution"]), default=1)
        for label, count in a["distribution"]:
            bar = _bar(count, max_count, width=25)
            color = C.GREEN if count > 0 else C.DIM
            print(f"     {label}  {color}{bar}{C.RESET} {count}")

        # Sample smallest
        print(f"   {C.BOLD}5 chunk TERKECIL:{C.RESET}")
        for s in a["sample_smallest"]:
            print(f"     {C.DIM}[{s['chars']} char] {s['referensi']}{C.RESET}")
            print(f"       {C.DIM}{s['text']}{C.RESET}")

        # Sample largest
        print(f"   {C.BOLD}5 chunk TERBESAR:{C.RESET}")
        for s in a["sample_largest"]:
            print(f"     {C.DIM}[{s['chars']} char] {s['referensi']}{C.RESET}")
            print(f"       {C.DIM}{s['text']}{C.RESET}")

        # Issues
        if a["issues"]:
            print(f"   {C.BOLD}{C.YELLOW}Issues:{C.RESET}")
            for issue in a["issues"]:
                print(f"     • {issue}")

        print()

    # Footer
    print(f"{C.BOLD}{C.CYAN}{'═' * 78}{C.RESET}")
    print()


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze Regulation Database quality"
    )
    parser.add_argument(
        "--reg-id",
        help="Analyze specific regulation by ID (default: semua)",
    )
    parser.add_argument(
        "--export",
        help="Export report to JSON file",
    )
    args = parser.parse_args()

    # Import service
    try:
        from app.services.regulation_db import (
            list_regulations,
            get_regulation,
            _get_table,
        )
    except Exception as exc:
        print(f"{C.RED}✗ Gagal import service: {exc}{C.RESET}")
        return 1

    # Get regulations
    if args.reg_id:
        reg = get_regulation(args.reg_id)
        if not reg:
            print(f"{C.RED}✗ Regulasi tidak ditemukan: {args.reg_id}{C.RESET}")
            return 1
        regs = [reg]
    else:
        regs = list_regulations()

    if not regs:
        print(f"{C.YELLOW}⚠ Database kosong. Upload regulasi dulu.{C.RESET}")
        return 0

    # Get ALL chunks from LanceDB
    print(f"{C.DIM}Loading chunks dari database...{C.RESET}")
    try:
        table = _get_table()
        if table is None:
            print(f"{C.RED}✗ Table tidak ada.{C.RESET}")
            return 1

                # Ambil semua rows — LanceDB 0.39+ pakai to_arrow()
        try:
            arrow_table = table.to_arrow()
            all_chunks = arrow_table.to_pylist()
        except AttributeError:
            # Fallback untuk versi LanceDB lama
            all_chunks = table.to_pandas().to_dict(orient="records")

        print(f"{C.DIM}Loaded {len(all_chunks):,} chunks.{C.RESET}")
    except Exception as exc:
        print(f"{C.RED}✗ Gagal baca table: {exc}{C.RESET}")
        return 1

    # Analyze each regulation
    analyses = []
    for reg in regs:
        analysis = analyze_regulation(reg, all_chunks)
        analyses.append(analysis)

    # Print report
    print_report(analyses)

    # Export JSON
    if args.export:
        export_path = Path(args.export)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(
            json.dumps(analyses, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"{C.GREEN}✓ Report disimpan di: {export_path}{C.RESET}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())