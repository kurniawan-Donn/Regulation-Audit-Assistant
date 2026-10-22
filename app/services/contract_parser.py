"""
Contract Parser Service.

Mem-parse dokumen kontrak/MoU/Addendum perbankan Indonesia menjadi
list of chunk per klausul.

Format kontrak yang didukung (fleksibel):
- "Pasal X" (X bisa angka + suffix huruf: 6A, 12B)
- Judul pasal UPPERCASE di baris berikutnya
- Ayat: "(N)" di awal baris
- Butir: "a)", "b)", atau "a.", "b)"

Berbeda dari regulation_parser yang menangani POJK/PADK, parser ini
dirancang untuk dokumen bisnis yang formatting PDF-nya sering
berantakan (kata terpotong per baris, typo OCR).
"""

import re
from typing import Optional, TypedDict

# =============================================================================
# PATTERN
# =============================================================================

# "Pasal 6", "Pasal 6A", "Pasal 12B"
_P_PASAL = re.compile(r"^Pasal\s+(\d+[A-Za-z]?)\s*$", re.IGNORECASE)

# "Pasal 6: Judul" (inline)
_P_PASAL_INLINE = re.compile(r"^Pasal\s+(\d+[A-Za-z]?)\s*[:\-]?\s*(.*)$", re.IGNORECASE)

# Ayat: "(1)", "(2)", "(1) teks"
_P_AYAT = re.compile(r"^\((\d+[a-zA-Z]?)\)\s*(.*)$")

# Butir: "a)", "b)" atau "a.", "b)"
_P_BUTIR = re.compile(r"^([a-z])[.)]\s+(.+)$")

# "PASAL 1" — kadang ditulis uppercase
_P_PASAL_UPPER = re.compile(r"^PASAL\s+(\d+[A-Za-z]?)\s*$")


# =============================================================================
# TYPES
# =============================================================================

class ContractChunk(TypedDict):
    pasal: Optional[str]        # "Pasal 6A"
    pasal_judul: Optional[str]  # "PENGAKHIRAN PERJANJIAN"
    ayat: Optional[str]         # "(1)"
    huruf: Optional[str]        # "a)"
    text: str                   # isi teks gabungan


# =============================================================================
# PRE-CLEANING (khusus kontrak)
# =============================================================================

def pre_clean_contract_text(raw_text: str) -> str:
    """
    Pre-clean khusus kontrak:
    - Gabungkan baris yang terpotong (kata tunggal di baris sendiri)
    - Normalisasi whitespace
    - Hapus nomor halaman
    """
    if not raw_text:
        return ""

    text = raw_text.replace("\xa0", " ")
    text = text.replace("\x0c", "\n")

    # Hapus nomor halaman: "- 5 -", "5", "Page 5 of 20"
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip baris nomor halaman
        if re.match(r"^[-–]?\s*\d{1,3}\s*[-–]?$", stripped):
            continue
        if re.match(r"^Page\s+\d+\s+of\s+\d+$", stripped, re.IGNORECASE):
            continue
        cleaned_lines.append(stripped)

    # Gabung baris yang terpotong
    # Heuristik: baris yang diakhiri kata (bukan titik) dan baris berikut
    # diawali huruf kecil → gabung
    merged = []
    i = 0
    while i < len(cleaned_lines):
        current = cleaned_lines[i]
        if not current:
            merged.append("")
            i += 1
            continue

        # Cek apakah baris berikutnya adalah lanjutan
        while i + 1 < len(cleaned_lines):
            next_line = cleaned_lines[i + 1]
            if not next_line:
                break
            # Kalau current tidak diakhiri tanda baca DAN next diawali huruf kecil
            # atau current sangat pendek (1-2 kata) → gabung
            if (not re.search(r"[.:;!?]$", current) and
                next_line and next_line[0].islower()):
                current = current + " " + next_line
                i += 1
            elif len(current.split()) <= 2 and next_line and next_line[0].islower():
                current = current + " " + next_line
                i += 1
            else:
                break

        merged.append(current)
        i += 1

    return "\n".join(merged)


# =============================================================================
# PARSER
# =============================================================================

def parse_contract_structure(text: str) -> list[ContractChunk]:
    """
    Parse teks kontrak menjadi list chunk per klausul.

    Return: list of ContractChunk dengan metadata pasal/ayat/huruf.
    """
    text = pre_clean_contract_text(text)

    current_pasal: Optional[str] = None
    current_pasal_judul: Optional[str] = None
    current_ayat: Optional[str] = None
    current_huruf: Optional[str] = None

    buffer: list[str] = []
    chunks: list[ContractChunk] = []

    def flush() -> None:
        content = "\n".join(buffer).strip()
        buffer.clear()
        if len(content) < 5:
            return
        chunks.append(ContractChunk(
            pasal=current_pasal,
            pasal_judul=current_pasal_judul,
            ayat=current_ayat,
            huruf=current_huruf,
            text=content,
        ))

    lines = text.split("\n")

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        # --- Pasal heading: "Pasal 6" atau "PASAL 6" ---
        m = _P_PASAL.match(line) or _P_PASAL_UPPER.match(line)
        if m:
            flush()
            current_pasal = f"Pasal {m.group(1)}"
            current_pasal_judul = None
            current_ayat = None
            current_huruf = None

            # Cek baris berikutnya: kalau UPPERCASE dan pendek → judul pasal
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and next_line.isupper() and 3 < len(next_line) < 120:
                    current_pasal_judul = next_line
            continue

        # --- Pasal inline: "Pasal 6: Judul" ---
        m = _P_PASAL_INLINE.match(line)
        if m and not _P_PASAL.match(line):
            flush()
            current_pasal = f"Pasal {m.group(1)}"
            judul = m.group(2).strip()
            current_pasal_judul = judul if judul else None
            current_ayat = None
            current_huruf = None
            continue

        # --- Ayat: "(1)" ---
        m = _P_AYAT.match(line)
        if m:
            flush()
            current_ayat = f"({m.group(1)})"
            current_huruf = None
            remainder = m.group(2).strip()
            if remainder:
                buffer.append(remainder)
            continue

        # --- Butir: "a)" atau "a." ---
        m = _P_BUTIR.match(line)
        if m:
            flush()
            current_huruf = f"{m.group(1)})"
            buffer.append(f"{m.group(1)}) {m.group(2)}")
            continue

        # --- Konten biasa ---
        buffer.append(line)

    flush()
    return chunks