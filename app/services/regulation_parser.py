"""
Regulation Structure Parser — State Machine.

DESAIN:
- Setiap baris dicek terhadap sekumpulan regex terurut (prioritas).
- Kalau match → transisi state (set field bab/bagian/pasal/ayat/butir).
- Kalau tidak match → masuk buffer konten.
- Buffer di-flush jadi chunk setiap ada heading baru.

DETERMINISTIK: input sama → output sama. Tidak ada "melihat 5 baris ke belakang".

POST-FILTER:
Setelah parsing, dua jenis chunk dibuang:
1. Cover page (mengandung "SALINAN PERATURAN", "MEMUTUSKAN", dll.)
2. Daftar Isi (density pola nomor halaman tinggi).
"""

import hashlib
import re
from typing import Optional, TypedDict

# ===== Page marker dari pdf_parser =====
_PAGE_MARKER = re.compile(r"^@@PAGE_(\d+)@@$")

# ===== H marker dari pdf_parser (dipakai sebagai "boost" fallback) =====
_H_MARKER = re.compile(r"^@@H@@\s+(.*)$")

# =============================================================================
# PATTERN UNTUK KLASIFIKASI HEADING (urutan prioritas penting!)
# =============================================================================

# Prioritas 1: LAMPIRAN X (HANYA huruf besar)
_P_LAMPIRAN = re.compile(r"^LAMPIRAN\s+([IVXLCDM]+)\b")

# Prioritas 2: BAB X (sendiri di baris)
_P_BAB_ONLY = re.compile(r"^BAB\s+([IVXLCDM]+)\s*$", re.IGNORECASE)
# BAB X JUDUL (inline)
_P_BAB_INLINE = re.compile(r"^BAB\s+([IVXLCDM]+)\s+(\S.+)$", re.IGNORECASE)

# Prioritas 3: I. JUDUL / II. JUDUL (Roman + kapital) — untuk PADK Lampiran
_P_ROMAN = re.compile(r"^([IVXLCDM]+)\.\s+(\S.*)$")

# Prioritas 4: Bagian Kesatu / Bagian Pertama
_P_BAGIAN_KATA = re.compile(r"^Bagian\s+\S+", re.IGNORECASE)

# Prioritas 5: A. JUDUL (Huruf kapital + titik + kapital)
_P_LETTER_UPPER = re.compile(r"^([A-Z])\.\s+(\S.*)$")

# Prioritas 6: Pasal X (POJK gaya klasik)
_P_PASAL = re.compile(r"^Pasal\s+\d+[A-Za-z]?\b", re.IGNORECASE)

# Prioritas 7: 1. JUDUL (angka + titik + kapital) — heading
_P_NUMBER_HEADING = re.compile(r"^(\d+)\.\s+([A-Z].*)$")

# Prioritas 8: (1) / Ayat (1) — ayat
_P_AYAT = re.compile(r"^(?:Ayat\s*)?\((\d+[a-zA-Z]?)\)\s*(.*)$", re.IGNORECASE)

# Prioritas 9: a. teks — butir (lowercase)
_P_BUTIR = re.compile(r"^([a-z])\.\s+(.+)$")

# Pola NEGATIF: cek apa "1. X" adalah konten list, bukan heading
_P_NUMBER_LIST = re.compile(r"^\d+\.\s+[a-z]")

# Batas panjang maksimum untuk judul heading (hindari paragraf panjang)
_MAX_HEADING_LEN = 150


# =============================================================================
# POST-PROCESSING CONSTANTS
# =============================================================================

# Threshold split chunk raksasa
_MAX_CHUNK_CHARS = 4000         # turun: split lebih agresif
_TARGET_CHUNK_CHARS = 2000      # turun: sub-chunk lebih granular
_CHUNK_OVERLAP_CHARS = 150      # turun proporsional
_MIN_CHUNK_CHARS = 20           # tetap (jangan naikkan — ayat pendek legit)
_MIN_WORDS_MEANINGFUL = 3       # tetap
_TOC_MAX_LEN = 80               # threshold TOC fragment (naik dari 50)

class RegulationChunk(TypedDict):
    lampiran: Optional[str]
    bab: Optional[str]
    bagian: Optional[str]
    pasal: Optional[str]
    ayat: Optional[str]
    butir: Optional[str]
    huruf: list[str]
    page_start: Optional[int]
    page_end: Optional[int]
    text: str


# =============================================================================
# STATE
# =============================================================================

class _State:
    __slots__ = (
        "lampiran", "bab", "bagian", "pasal", "ayat", "butir",
        "buffer", "buffer_page_start", "current_page",
        "chunks", "awaiting_bab_title",
    )

    def __init__(self):
        self.lampiran: Optional[str] = None
        self.bab: Optional[str] = None
        self.bagian: Optional[str] = None
        self.pasal: Optional[str] = None
        self.ayat: Optional[str] = None
        self.butir: Optional[str] = None

        self.buffer: list[str] = []
        self.buffer_page_start: Optional[int] = None
        self.current_page: Optional[int] = None

        self.chunks: list[RegulationChunk] = []

        # Flag: baru saja set "BAB V" sendiri (menunggu judul di baris berikut)
        self.awaiting_bab_title = False

    def reset_below(self, level: str) -> None:
        """Reset semua field di bawah level tertentu (transisi naik/turun)."""
        if level == "lampiran":
            self.bab = self.bagian = self.pasal = self.ayat = self.butir = None
        elif level == "bab":
            self.bagian = self.pasal = self.ayat = self.butir = None
        elif level == "bagian":
            self.pasal = self.ayat = self.butir = None
        elif level == "pasal":
            self.ayat = self.butir = None
        elif level == "ayat":
            self.butir = None

    def flush(self) -> None:
        """Keluarkan isi buffer sebagai chunk (kalau memenuhi syarat)."""
        content = "\n".join(self.buffer).strip()
        self.buffer.clear()
        if len(content) < 15:
            self.buffer_page_start = None
            return

        self.chunks.append(RegulationChunk(
            lampiran=self.lampiran,
            bab=self.bab,
            bagian=self.bagian,
            pasal=self.pasal,
            ayat=self.ayat,
            butir=self.butir,
            huruf=re.findall(r"^([a-z])\.\s+", content, re.MULTILINE),
            page_start=self.buffer_page_start,
            page_end=self.current_page,
            text=content,
        ))
        self.buffer_page_start = None

    def append(self, line: str) -> None:
        if self.buffer_page_start is None:
            self.buffer_page_start = self.current_page
        self.buffer.append(line)


# =============================================================================
# KLASIFIKASI HEADING (deterministik, prioritas berurut)
# =============================================================================

def _classify(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Return (level, value) atau (None, None).
    Level: "lampiran" | "bab" | "bagian" | "pasal" | "ayat" | "butir"
    """
    t = text.strip()
    if not t or len(t) > 300:
        return None, None

    # 1. LAMPIRAN X
    m = _P_LAMPIRAN.match(t)
    if m:
        return "lampiran", f"Lampiran {m.group(1).upper()}"

    # 2. BAB X (sendiri)
    m = _P_BAB_ONLY.match(t)
    if m:
        return "bab", t

    # 3. BAB X JUDUL (inline)
    m = _P_BAB_INLINE.match(t)
    if m and len(t) <= _MAX_HEADING_LEN:
        return "bab", t

    # 4. I. JUDUL (Roman numeral + Kapital) — untuk PADK Lampiran
    m = _P_ROMAN.match(t)
    if m and len(t) <= _MAX_HEADING_LEN:
        rest = m.group(2)
        if rest and rest[0].isupper():
            # Hindari false positive: "I. Pendahuluan ini..." (kalimat panjang)
            if not t.rstrip().endswith((",", ";", ":")):
                return "bab", t

    # 5. Bagian Kesatu / Bagian Pertama
    if _P_BAGIAN_KATA.match(t):
        return "bagian", t

    # 6. A. JUDUL (Kapital + titik + Kapital)
    m = _P_LETTER_UPPER.match(t)
    if m and len(t) <= _MAX_HEADING_LEN:
        rest = m.group(2)
        if rest and rest[0].isupper():
            if not t.rstrip().endswith((",", ";", ":")):
                return "bagian", t

    # 7. Pasal X
    if _P_PASAL.match(t):
        return "pasal", t

    # 8. 1. JUDUL (angka + titik + Kapital, pendek, bukan list)
    m = _P_NUMBER_HEADING.match(t)
    if m and len(t) <= _MAX_HEADING_LEN:
        if not _P_NUMBER_LIST.match(t):
            if not t.rstrip().endswith((",", ";", ":")):
                return "pasal", t

    # 9. (1) / Ayat (1)
    m = _P_AYAT.match(t)
    if m:
        return "ayat", f"({m.group(1)})"

    # 10. a. teks (butir)
    m = _P_BUTIR.match(t)
    if m:
        return "butir", m.group(1) + "."

    return None, None


# =============================================================================
# TRANSISI STATE
# =============================================================================

def _apply_transition(state: _State, level: str, value: str) -> None:
    """Update state sesuai heading baru."""
    if level == "lampiran":
        state.lampiran = value
        state.reset_below("lampiran")
    elif level == "bab":
        state.bab = value
        state.reset_below("bab")
    elif level == "bagian":
        state.bagian = value
        state.reset_below("bagian")
    elif level == "pasal":
        state.pasal = value
        state.reset_below("pasal")
    elif level == "ayat":
        state.ayat = value
        state.reset_below("ayat")
    elif level == "butir":
        state.butir = value


# =============================================================================
# MAIN PARSER
# =============================================================================

def _parse(text: str) -> list[RegulationChunk]:
    state = _State()

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        # --- Page marker ---
        m = _PAGE_MARKER.match(line)
        if m:
            state.current_page = int(m.group(1))
            continue

        # --- Strip H marker (kalau ada) ---
        m = _H_MARKER.match(line)
        h_marker_present = False
        if m:
            line = m.group(1).strip()
            h_marker_present = True

        # --- Cek apakah ini judul BAB yang baru di-set ("BAB V" + judul) ---
        if state.awaiting_bab_title:
            state.awaiting_bab_title = False
            # Baris berikut harus uppercase, pendek, dan bukan heading baru
            if line.isupper() and len(line) < 150:
                level_check, _ = _classify(line)
                if level_check is None:
                    state.bab = f"{state.bab} — {line}"
                    continue

        # --- Klasifikasi heading ---
        level, value = _classify(line)

        if level is not None:
            # Flush konten sebelum heading baru
            state.flush()
            _apply_transition(state, level, value)

            # Special case: "BAB V" sendiri → tunggu judul
            if level == "bab" and _P_BAB_ONLY.match(line):
                state.awaiting_bab_title = True
            continue

        # --- Bukan heading, masuk konten ---
        state.append(line)

    state.flush()
    return state.chunks


# =============================================================================
# POST-FILTER: buang cover page & Daftar Isi
# =============================================================================

_COVER_KEYWORDS = (
    "SALINAN PERATURAN",
    "SALINAN INI SESUAI",
    "DENGAN RAHMAT TUHAN",
    "MEMUTUSKAN:",
    "MENIMBANG :",
    "MENGINGAT :",
)


def _is_cover_chunk(chunk: RegulationChunk) -> bool:
    """Deteksi chunk cover/legal preamble."""
    head = chunk["text"][:400].upper()
    return any(kw in head for kw in _COVER_KEYWORDS)


def _is_toc_chunk(chunk: RegulationChunk) -> bool:
    """
    Deteksi chunk Daftar Isi.
    Ciri: > 50% baris diakhiri angka, atau > 30% baris hanya angka/Roman.
    """
    text = chunk["text"]
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 5:
        return False

    ends_digit = sum(1 for l in lines if l and l[-1].isdigit())
    ratio_end_digit = ends_digit / len(lines)

    pure_num = sum(
        1 for l in lines
        if re.match(r"^[IVXLCDM]+\.?$", l) or re.match(r"^\d+\.?$", l)
    )
    ratio_pure = pure_num / len(lines)

    return ratio_end_digit > 0.5 or ratio_pure > 0.3


def _filter_chunks(chunks: list[RegulationChunk]) -> list[RegulationChunk]:
    """Buang cover page & TOC dari list chunk."""
    return [
        c for c in chunks
        if not _is_cover_chunk(c) and not _is_toc_chunk(c)
    ]

def _join_broken_lines(text: str) -> str:
    """
    Gabungkan baris yang terpotong per-kata (umum di PDF justified text).

    Heuristik:
    - Kalau baris pendek (<= 5 kata) DAN baris berikutnya diawali huruf kecil
      DAN tidak diakhiri tanda baca akhir (. ! ? : ;) → gabung dengan spasi
    - Kalau baris diakhiri tanda baca → biarkan (akhir kalimat)
    """
    if not text:
        return text

    lines = text.split("\n")
    result: list[str] = []
    buffer = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buffer:
                result.append(buffer)
                buffer = ""
            result.append("")
            continue

        if not buffer:
            buffer = stripped
            continue

        # Cek apakah buffer perlu digabung dengan baris ini
        buffer_ends_punct = bool(re.search(r"[.!?:;]\s*$", buffer))
        line_starts_lower = stripped[0].islower() if stripped else False
        buffer_word_count = len(buffer.split())

        if not buffer_ends_punct and line_starts_lower and buffer_word_count <= 8:
            buffer = buffer + " " + stripped
        else:
            result.append(buffer)
            buffer = stripped

    if buffer:
        result.append(buffer)

      
    merged_text = "\n".join(result)
    merged_text = re.sub(r"@@PAGE_\d+@@\s*", "", merged_text)

    return merged_text

# =============================================================================
# POST-PROCESSING
# =============================================================================

def _is_noise_chunk(chunk: RegulationChunk) -> bool:
    """
    Deteksi chunk noise yang tidak berguna untuk retrieval.
    """
    text = chunk.get("text", "").strip()
    text_len = len(text)

    # Rule 1: Sangat pendek (< 20 char) — noise kecuali ada metadata pasal+ayat
    if text_len < _MIN_CHUNK_CHARS:
        if chunk.get("pasal") and chunk.get("ayat"):
            return False
        return True

    # Rule 2: TOC fragment — diakhiri angka (nomor halaman)
    # Threshold 80 char — beberapa TOC entry bisa sampai 60-70 char
    if text_len < _TOC_MAX_LEN:
        # Pattern: text diakhiri nomor 1-3 digit (page number)
        if re.search(r"\s+\d{1,3}\s*$", text):
            return True

    # Rule 3: Terlalu sedikit kata untuk chunk kecil
    if text_len < 50:
        if len(text.split()) < _MIN_WORDS_MEANINGFUL:
            return True

    return False


def _split_text_by_paragraph(text: str, target: int, overlap: int) -> list[str]:
    """
    Split text jadi beberapa bagian ~target char.

    Strategi:
    1. Cari paragraph break (\\n\\n) terdekat dari target
    2. Kalau tidak ada, cari sentence break (. ! ?)
    3. Kalau tidak ada juga, hard split di target
    """
    if len(text) <= target:
        return [text]

    chunks: list[str] = []
    start = 0
    text_len = len(text)
    max_iterations = 500  # safety guard

    iteration = 0
    while start < text_len and iteration < max_iterations:
        iteration += 1

        # Kalau sisa text <= target, ambil semua dan selesai
        if text_len - start <= target:
            remaining = text[start:].strip()
            if remaining:
                chunks.append(remaining)
            break

        # Cari paragraph break terdekat
        ideal_end = start + target
        search_end = min(start + target + 500, text_len)
        search_region = text[start:search_end]

        # Prioritas 1: paragraph break (\n\n)
        best_pos = -1
        best_distance = 999999

        for match in re.finditer(r"\n\s*\n", search_region):
            pos = match.start()
            distance = abs(pos - target)
            if distance < best_distance:
                best_distance = distance
                best_pos = pos

        if best_pos > 0:
            end = start + best_pos
            segment = text[start:end].strip()
            if segment:
                chunks.append(segment)
            # Next start dengan overlap
            new_start = end - overlap
            if new_start <= start:  # prevent infinite loop
                new_start = end
            start = new_start
            continue

        # Prioritas 2: sentence break (. ! ?)
        best_pos = -1
        best_distance = 999999

        for match in re.finditer(r"[.!?]\s+", search_region):
            pos = match.start()
            distance = abs(pos - target)
            if distance < best_distance:
                best_distance = distance
                best_pos = pos

        if best_pos > 0:
            end = start + best_pos + 1  # include punctuation
            segment = text[start:end].strip()
            if segment:
                chunks.append(segment)
            new_start = end - overlap
            if new_start <= start:
                new_start = end
            start = new_start
            continue

        end = start + target
        search_back = max(start, end - 50)
        last_space = text.rfind(" ", search_back, end)
        if last_space > start + target * 0.8:
            end = last_space

        segment = text[start:end].strip()
        if segment:
            chunks.append(segment)
        start = end - overlap
        if start < 0:
            start = 0

    return [c for c in chunks if c and c.strip()]


def _split_large_chunk(chunk: RegulationChunk) -> list[RegulationChunk]:
    """
    Split chunk > MAX_CHUNK_CHARS jadi beberapa sub-chunks.

    Sub-chunks inherit metadata dari parent. Text di-split by paragraph
    boundary terdekat.
    """
    text = chunk.get("text", "")
    if len(text) <= _MAX_CHUNK_CHARS:
        return [chunk]

    sub_texts = _split_text_by_paragraph(
        text,
        target=_TARGET_CHUNK_CHARS,
        overlap=_CHUNK_OVERLAP_CHARS,
    )

    result: list[RegulationChunk] = []
    for sub_text in sub_texts:
        result.append(RegulationChunk(
            lampiran=chunk.get("lampiran"),
            bab=chunk.get("bab"),
            bagian=chunk.get("bagian"),
            pasal=chunk.get("pasal"),
            ayat=chunk.get("ayat"),
            butir=chunk.get("butir"),
            huruf=chunk.get("huruf", []),
            page_start=chunk.get("page_start"),
            page_end=chunk.get("page_end"),
            text=sub_text,
        ))
    return result


def _deduplicate_chunks(chunks: list[RegulationChunk]) -> list[RegulationChunk]:
    """
    Buang chunk dengan text yang sudah pernah muncul.

    Untuk chunk panjang (> 500 char), pakai 500 char pertama sebagai
    key dedup (supaya tidak strict berlebihan).
    """
    seen: set[str] = set()
    result: list[RegulationChunk] = []

    for chunk in chunks:
        text = chunk.get("text", "").strip().lower()
        if not text:
            continue

        # Key untuk dedup — 500 char pertama
        key_text = text[:500] if len(text) > 500 else text
        key = hashlib.md5(key_text.encode("utf-8")).hexdigest()

        if key in seen:
            continue
        seen.add(key)
        result.append(chunk)

    return result


def _post_process_chunks(chunks: list[RegulationChunk]) -> list[RegulationChunk]:
    """
    Post-processing pipeline untuk kualitas chunk:

    Step 1: Filter noise (chunk pendek, TOC fragments)
    Step 2: Split chunk raksasa (> 8.000 char)
    Step 3: Deduplikat

    Return: list chunk yang sudah bersih & optimal untuk retrieval.
    """
    if not chunks:
        return []

    # Step 1: Filter noise
    before = len(chunks)
    filtered = [c for c in chunks if not _is_noise_chunk(c)]
    noise_removed = before - len(filtered)

    # Step 2: Split raksasa
    expanded: list[RegulationChunk] = []
    split_count = 0
    for c in filtered:
        if len(c.get("text", "")) > _MAX_CHUNK_CHARS:
            split_count += 1
        expanded.extend(_split_large_chunk(c))

    # Step 3: Dedup
    deduped = _deduplicate_chunks(expanded)
    duplicates_removed = len(expanded) - len(deduped)

    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        "Post-process: %d → %d chunks (noise: -%d, split: %d besar, dup: -%d)",
        before, len(deduped), noise_removed, split_count, duplicates_removed,
    )

    return deduped

def parse_regulation_structure(text: str) -> list[RegulationChunk]:
    """
    Parse teks regulasi → list chunk terstruktur.

    Pipeline:
    1. Pre-clean: gabungkan baris terpotong (PDF justified)
    2. Parse: state machine deteksi struktur
    3. Filter: buang cover page & TOC
    4. Post-process: filter noise, split raksasa, dedup
    """
    # Step 1: Pre-clean
    text = _join_broken_lines(text)

    # Step 2: Parse struktur
    raw_chunks = _parse(text)

    # Step 3: Filter cover & TOC
    filtered = _filter_chunks(raw_chunks)

    # Step 4: Post-process (noise, split, dedup)
    return _post_process_chunks(filtered)