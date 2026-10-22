"""
Regulation Structure Parser — State Machine.

DESAIN:
- Setiap baris dicek terhadap sekumpulan regex terurut (prioritas).
- Kalau match → transisi state (set field lampiran/bab/bagian/pasal/ayat).
- Kalau tidak match → masuk buffer konten.
- Buffer di-flush jadi chunk setiap ada heading baru.

PRINSIP: TIDAK ADA TEKS YANG HILANG.
- Teks yang sebaris dengan penanda ayat ("(1) Bank wajib ...") tetap
  menjadi isi chunk ayat tersebut.
- Butir (a., b., ...) dan item bernomor di dalam Pasal adalah isi list,
  bukan heading — tetap satu chunk dengan ayat/pasal induknya.
  (Field `butir` dipertahankan di schema demi kompatibilitas, selalu None.)
- Rujukan silang yang terpotong di awal baris ("Pasal 8 ayat (1), dikenai
  ...", "ayat (1), Bank ...", atau "(1)" di tengah kalimat) bukan heading:
  heading Pasal harus satu baris penuh, dan nomor ayat harus berurutan.

DETERMINISTIK: input sama → output sama. Tidak ada "melihat 5 baris ke belakang".

POST-FILTER:
Setelah parsing, dua jenis chunk dibuang:
1. Cover page (mengandung "SALINAN PERATURAN", "MEMUTUSKAN", dll.)
2. Daftar Isi (density pola nomor halaman tinggi).
"""

import hashlib
import re
from typing import Optional, TypedDict

# Naikkan setiap kali perilaku parser berubah: cache parse (preview_cache)
# memakai nilai ini untuk membuang hasil parse versi lama.
# v2: teks sebaris penanda ayat/butir tidak lagi hilang, rujukan silang
#     bukan heading, stempel "Salinan" & Daftar Isi dibersihkan per baris,
#     nomor halaman terlacak, bagian PENJELASAN dipisah.
# v3: judul BAB multi-baris digabung (tidak lagi jadi chunk isi sampah).
PARSER_VERSION = 3

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

# Prioritas 6: Pasal X (POJK gaya klasik) — HARUS satu baris penuh.
# Baris seperti "Pasal 8 ayat (1), dikenai sanksi ..." adalah rujukan silang
# yang kebetulan terpotong di awal baris, BUKAN heading.
_P_PASAL = re.compile(r"^Pasal\s+(\d+[A-Z]?)\s*$")

# Prioritas 7: 1. JUDUL (angka + titik + kapital) — heading (gaya PADK Lampiran)
_P_NUMBER_HEADING = re.compile(r"^(\d+)\.\s+([A-Z].*)$")

# Prioritas 8: ayat — "(1) teks..." atau "Ayat (1)" (A kapital).
# "ayat (1), Bank dikenai ..." (huruf kecil) adalah rujukan silang → konten.
_P_AYAT_PAREN = re.compile(r"^\((\d+)([a-z]?)\)(?:\s+(.*))?$")
_P_AYAT_WORD = re.compile(r"^Ayat\s*\((\d+)([a-z]?)\)(?:\s+(.*))?$")

# Penanda list yang berdiri sendiri di satu baris (umum di PDF justified):
# "(1)" / "a." / "1." / "1)" — digabung dengan baris berikutnya saat pre-clean.
_P_LONE_MARKER = re.compile(r"^(\(\d+[a-z]?\)|[a-z]\.|\d+\.|\d+\))$")

# Pola NEGATIF: cek apa "1. X" adalah konten list, bukan heading
_P_NUMBER_LIST = re.compile(r"^\d+\.\s+[a-z]")

# Heading tidak pernah diakhiri tanda baca kalimat/list.
_HEADING_BAD_ENDINGS = (".", ",", ";", ":")

_P_PENJELASAN = re.compile(r"^PENJELASAN$")

# Judul BAB paling banyak sekian baris (setelah baris "BAB X").
_MAX_BAB_TITLE_LINES = 3

# Stempel "Salinan ini sesuai dengan aslinya / <jabatan> / ttd / <nama>" yang
# dicetak di tengah halaman. Kalau tidak dibuang, chunk Pasal yang memuatnya
# ikut terbuang oleh filter cover.
_P_SALINAN_STAMP = re.compile(r"^salinan ini sesuai dengan aslinya", re.IGNORECASE)
_P_TTD = re.compile(r"^ttd\.?$", re.IGNORECASE)
_SALINAN_STAMP_MAX_LINES = 6

# Heading yang tidak boleh "menelan" baris lanjutan saat pre-clean.
_NON_MERGEABLE_HEADINGS = {"lampiran", "bab", "bagian", "pasal"}

# Baris yang diawali penanda list adalah item baru — tidak pernah disambung
# ke baris sebelumnya walau diawali huruf kecil ("a. proses bisnis;").
_P_LIST_ITEM_START = re.compile(r"^(\(\d+[a-z]?\)|[a-z]\.|\d+[.)])\s")

# Kata sambung yang boleh huruf kecil di dalam judul ("Kebijakan dan Prosedur ...").
_TITLE_STOPWORDS = {
    "dan", "atau", "dan/atau", "terhadap", "dalam", "oleh", "untuk", "yang",
    "dengan", "di", "ke", "dari", "atas", "serta", "pada", "bagi", "antara",
    "sebagai", "tentang", "mengenai", "melalui",
}

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
        "chunks", "bab_title_lines_left",
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

        # Sisa baris judul yang masih boleh digabung ke BAB yang baru di-set
        # ("BAB VIII" / "PENGELOLAAN DATA ..." / "DALAM PENYELENGGARAAN TI BANK").
        self.bab_title_lines_left = 0

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

def _looks_like_heading_title(t: str) -> bool:
    return len(t) <= _MAX_HEADING_LEN and not t.rstrip().endswith(_HEADING_BAD_ENDINGS)


def _is_title_case_phrase(phrase: str) -> bool:
    """
    Judul: "Pengelolaan Aset", "Uji Tuntas (Due Diligence) terhadap PPJTI".
    Kalimat: "BPR dan BPR Syariah menempatkan Sistem Elektronik berupa".
    Judul tidak memuat koma dan tidak punya kata huruf kecil selain kata sambung.
    """
    if "," in phrase:
        return False
    for word in phrase.split():
        w = word.strip("()[]\"'")
        if w and w[0].islower() and w.lower() not in _TITLE_STOPWORDS:
            return False
    return True


def _classify(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Klasifikasi heading STRUKTURAL yang tidak butuh konteks.
    Return (level, value) atau (None, None).
    Level: "lampiran" | "bab" | "bagian" | "pasal" | "number_heading"

    Ayat ditangani terpisah (_match_ayat) karena validasinya butuh state
    (urutan nomor ayat). Butir (a., b., ...) sengaja TIDAK dianggap heading:
    butir adalah isi list milik ayat/pasal-nya dan tetap satu chunk dengannya.
    """
    t = text.strip()
    if not t or len(t) > 300:
        return None, None

    # 1. LAMPIRAN X
    m = _P_LAMPIRAN.match(t)
    if m:
        return "lampiran", f"Lampiran {m.group(1).upper()}"

    # 1b. PENJELASAN (bagian penjelasan POJK/PBI) — setara Lampiran, supaya
    # "Pasal 1 ... Cukup jelas." di penjelasan tidak tercampur dengan batang tubuh.
    if _P_PENJELASAN.match(t):
        return "lampiran", "Penjelasan"

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
    if m and _looks_like_heading_title(t):
        rest = m.group(2)
        if rest and rest[0].isupper():
            return "bab", t

    # 5. Bagian Kesatu / Bagian Pertama
    if _P_BAGIAN_KATA.match(t):
        return "bagian", t

    # 6. A. JUDUL (Kapital + titik + Kapital)
    m = _P_LETTER_UPPER.match(t)
    if m and _looks_like_heading_title(t):
        rest = m.group(2)
        if rest and rest[0].isupper():
            return "bagian", t

    # 7. Pasal X (satu baris penuh)
    m = _P_PASAL.match(t)
    if m:
        return "pasal", f"Pasal {m.group(1)}"

    # 8. 1. JUDUL (angka + titik + Kapital, pendek, bukan list)
    m = _P_NUMBER_HEADING.match(t)
    if (
        m
        and _looks_like_heading_title(t)
        and not _P_NUMBER_LIST.match(t)
        and _is_title_case_phrase(m.group(2))
    ):
        return "number_heading", t

    return None, None


def _match_ayat(text: str) -> Optional[tuple[int, str, str]]:
    """
    Cocokkan penanda ayat di awal baris.
    Return (nomor, sufiks, inline_text) atau None.
    """
    t = text.strip()
    m = _P_AYAT_PAREN.match(t) or _P_AYAT_WORD.match(t)
    if not m:
        return None
    return int(m.group(1)), m.group(2) or "", (m.group(3) or "").strip()


def _is_next_ayat(state: "_State", number: int, suffix: str) -> bool:
    """
    Validasi urutan ayat supaya "(1)" di tengah rujukan silang
    ("... sebagaimana dimaksud pada ayat / (1) huruf c ...") tidak dianggap
    ayat baru. Ayat sah: (1) di awal pasal, (n+1) setelah (n), atau ayat
    sisipan amandemen (2a) setelah (2).
    """
    if state.ayat is None:
        # Tanpa konteks pasal (mis. potongan dokumen) → terima apa adanya.
        return number == 1 or state.pasal is None
    m = re.match(r"^\((\d+)", state.ayat)
    current = int(m.group(1)) if m else 0
    if suffix:
        return number in (current, current + 1)
    return number == current + 1


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
        if m:
            line = m.group(1).strip()

        # --- Cek apakah ini judul BAB yang baru di-set ("BAB V" + judul) ---
        if state.bab_title_lines_left:
            # Baris judul harus uppercase, pendek, dan bukan heading baru.
            # Judul bisa terpotong jadi 2–3 baris; tanpa ini baris kedua
            # menjadi chunk "isi" sampah (mis. "DALAM PENYELENGGARAAN TI BANK").
            if line.isupper() and len(line) < 150 and _classify(line)[0] is None:
                sep = " — " if state.bab_title_lines_left == _MAX_BAB_TITLE_LINES else " "
                state.bab = f"{state.bab}{sep}{line}"
                state.bab_title_lines_left -= 1
                continue
            state.bab_title_lines_left = 0

        # --- Ayat: butuh validasi urutan; teks sebaris DISIMPAN sebagai isi ---
        ayat = _match_ayat(line)
        if ayat is not None:
            number, suffix, inline_text = ayat
            if _is_next_ayat(state, number, suffix):
                state.flush()
                _apply_transition(state, "ayat", f"({number}{suffix})")
                if inline_text:
                    state.append(line)
                continue
            # Bukan ayat baru (rujukan silang) → konten biasa
            state.append(line)
            continue

        # --- Klasifikasi heading struktural ---
        level, value = _classify(line)

        # "1. Judul" adalah heading hanya di luar Pasal (gaya PADK Lampiran).
        # Di dalam Pasal, "1. ..." adalah item list (mis. daftar definisi).
        keep_heading_text = False
        if level == "number_heading":
            if state.pasal and state.pasal.startswith("Pasal "):
                level = None
            else:
                level = "pasal"
                # Judul bernomor juga disimpan sebagai baris pertama isi chunk.
                keep_heading_text = True

        if level is not None:
            # Flush konten sebelum heading baru
            state.flush()
            _apply_transition(state, level, value)
            if keep_heading_text:
                state.append(line)

            # Special case: "BAB V" sendiri → tunggu judul
            if level == "bab" and _P_BAB_ONLY.match(line):
                state.bab_title_lines_left = _MAX_BAB_TITLE_LINES
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


def _is_front_matter(chunk: RegulationChunk) -> bool:
    return not (chunk.get("lampiran") or chunk.get("bab") or chunk.get("pasal"))


def _is_cover_chunk(chunk: RegulationChunk) -> bool:
    """
    Deteksi chunk cover/legal preamble (Menimbang/Mengingat/Memutuskan).
    Hanya berlaku untuk chunk SEBELUM struktur pertama (tanpa lampiran/bab/
    pasal) — chunk Pasal yang kebetulan memuat kata kunci tidak dibuang.
    """
    if not _is_front_matter(chunk):
        return False
    head = chunk["text"][:400].upper()
    return any(kw in head for kw in _COVER_KEYWORDS)


def _is_toc_line(line: str) -> bool:
    return (
        bool(re.search(r"\s\d{1,3}$", line))
        or bool(re.match(r"^[IVXLCDM]+\.?$", line))
        or bool(re.match(r"^\d+\.?$", line))
    )


def _is_toc_chunk(chunk: RegulationChunk) -> bool:
    """
    Deteksi chunk yang didominasi Daftar Isi.
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


def _strip_toc_lines(chunk: RegulationChunk) -> Optional[RegulationChunk]:
    """
    Daftar Isi sering tergabung dengan isi Pasal sebelumnya (mis. Pasal
    terakhir sebelum Lampiran). Buang hanya baris-baris bergaya TOC, bukan
    seluruh chunk. Return None kalau tidak ada isi yang tersisa.
    """
    kept = [
        l for l in chunk["text"].split("\n")
        if l.strip() and not _is_toc_line(l.strip())
    ]
    text = "\n".join(kept).strip()
    if len(text) < _MIN_CHUNK_CHARS:
        return None
    return RegulationChunk(**{**chunk, "text": text})


def _filter_chunks(chunks: list[RegulationChunk]) -> list[RegulationChunk]:
    """Buang cover page; bersihkan baris Daftar Isi dari chunk."""
    result: list[RegulationChunk] = []
    for c in chunks:
        if _is_cover_chunk(c):
            continue
        if _is_toc_chunk(c):
            stripped = _strip_toc_lines(c)
            if stripped is not None:
                result.append(stripped)
            continue
        result.append(c)
    return result

def _strip_salinan_stamps(lines: list[str]) -> list[str]:
    """Buang blok stempel "Salinan ini sesuai dengan aslinya ... ttd / <nama>"."""
    result: list[str] = []
    i = 0
    while i < len(lines):
        if _P_SALINAN_STAMP.match(lines[i].strip()):
            window = lines[i + 1: i + 1 + _SALINAN_STAMP_MAX_LINES]
            ttd_at = next(
                (j for j, l in enumerate(window) if _P_TTD.match(l.strip())), None
            )
            # Lewati sampai baris nama setelah "ttd" (kalau ketemu).
            i += 1 + (ttd_at + 2 if ttd_at is not None else 0)
            continue
        result.append(lines[i])
        i += 1
    return result


def _attach_lone_markers(lines: list[str]) -> list[str]:
    """
    PDF justified sering memisahkan penanda list dari teksnya:
        "(1)" / "Dalam menerapkan ..."   →  "(1) Dalam menerapkan ..."
        "a."  / "proses bisnis;"         →  "a. proses bisnis;"
    Penanda digabung dengan baris teks berikutnya (melewati baris kosong,
    tapi tidak melewati page marker / heading).
    """
    result: list[str] = []
    pending: Optional[str] = None
    for line in lines:
        stripped = line.strip()
        if pending is not None:
            if not stripped:
                continue
            if stripped.startswith("@@") or _P_LONE_MARKER.match(stripped):
                result.append(pending)
                pending = None
            else:
                result.append(f"{pending} {stripped}")
                pending = None
                continue
        if _P_LONE_MARKER.match(stripped):
            pending = stripped
            continue
        result.append(line)
    if pending is not None:
        result.append(pending)
    return result


def _join_broken_lines(text: str) -> str:
    """
    Gabungkan baris yang terpotong (umum di PDF justified text, yang bisa
    memecah satu kalimat menjadi satu kata per baris).

    Heuristik:
    - Penanda list yang berdiri sendiri digabung dengan teksnya.
    - Baris berikutnya digabung ke buffer kalau diawali huruf kecil DAN
      buffer belum diakhiri tanda baca akhir (. ! ? : ;) DAN buffer bukan
      heading struktural (BAB / Pasal / dsb.).
    - Page marker dipertahankan di barisnya sendiri (dipakai _parse untuk
      melacak nomor halaman) dan tidak memutus kalimat.
    """
    if not text:
        return text

    lines = _attach_lone_markers(_strip_salinan_stamps(text.split("\n")))
    result: list[str] = []
    buffer = ""
    held_markers: list[str] = []   # page marker yang muncul di tengah kalimat

    def emit_buffer() -> None:
        nonlocal buffer
        if buffer:
            result.append(buffer)
            buffer = ""
        result.extend(held_markers)
        held_markers.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            emit_buffer()
            result.append("")
            continue

        if _PAGE_MARKER.match(stripped):
            if buffer:
                held_markers.append(stripped)
            else:
                result.append(stripped)
            continue

        # Penanda font tebal (@@H@@) pada baris lanjutan kalimat ("@@H@@ jaringan
        # komunikasi ...") bukan heading — buang penandanya supaya bisa disambung.
        h = _H_MARKER.match(stripped)
        if h and h.group(1)[:1].islower():
            stripped = h.group(1).strip()

        if not buffer:
            buffer = stripped
            continue

        buffer_ends_punct = bool(re.search(r"[.!?:;]\s*$", buffer))
        line_starts_lower = stripped[0].islower() and not _P_LIST_ITEM_START.match(stripped)
        # "1. BPR wajib memastikan ..." yang terpotong BOLEH disambung (lalu
        # terbaca sebagai kalimat); BAB/Pasal/dll. tidak.
        buffer_is_heading = _classify(buffer)[0] in _NON_MERGEABLE_HEADINGS

        if not buffer_ends_punct and line_starts_lower and not buffer_is_heading:
            buffer = buffer + " " + stripped
        else:
            emit_buffer()
            buffer = stripped

    emit_buffer()
    return "\n".join(result)

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