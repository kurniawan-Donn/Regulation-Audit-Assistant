"""
Excel Exporter untuk Compliance Review.

Output: 2 sheet:
1. "Compliance Review" — 5 kolom (No, Klausul, Regulasi, Status, Analisis)
2. "Ringkasan Eksekutif" — teks ringkasan
"""

import re
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from app.services.compliance_review_analyzer import STATUS_OPTIONS, STATUS_PERLU_VERIFIKASI

HEADER_FILL = PatternFill(start_color="1E2761", end_color="1E2761", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)

# Warna per status
STATUS_FILLS = {
    "PATUH": PatternFill(start_color="E3F3EA", end_color="E3F3EA", fill_type="solid"),
    "PATUH DENGAN CATATAN": PatternFill(start_color="FFF8E1", end_color="FFF8E1", fill_type="solid"),
    "TIDAK PATUH": PatternFill(start_color="FBEAE8", end_color="FBEAE8", fill_type="solid"),
    "TIDAK RELEVAN": PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid"),
    STATUS_PERLU_VERIFIKASI: PatternFill(start_color="EDE7F6", end_color="EDE7F6", fill_type="solid"),
}

COLUMNS = [
    ("No", 5),
    ("Klausul / Pasal & Ayat Perjanjian", 32),
    ("Regulasi Acuan Terkait", 30),
    ("Status Kepatuhan", 22),
    ("Analisis Hukum & Rekomendasi Perbaikan", 70),
]

_COL_STATUS = 4


def _safe_filename_component(text: str) -> str:
    text = (text or "").strip() or "kontrak"
    text = re.sub(r"[^\w\-.]+", "_", text)
    return text.strip("_")[:80] or "kontrak"


def build_compliance_filename(nama_kontrak: str) -> str:
    return f"compliance_review_{_safe_filename_component(nama_kontrak)}.xlsx"


def _strip_markdown(text: str) -> str:
    """Bersihkan **bold** dan format markdown lain untuk Excel."""
    if not text:
        return ""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return text.strip()


def analisis_with_validation_notes(item: dict[str, Any]) -> str:
    """Analisis + catatan validasi otomatis (kalau baris perlu ditinjau auditor)."""
    analisis = _strip_markdown(item.get("analisis", ""))
    notes = [n for n in item.get("validation_notes") or [] if n and n not in analisis]
    if item.get("needs_review") and notes:
        analisis = f"{analisis}\n\n[Perlu verifikasi] " + " ".join(notes)
    return analisis.strip()


def export_compliance_to_excel(
    items: list[dict[str, Any]],
    executive_summary: str,
    output_path: str,
) -> str:
    """Tulis hasil compliance review ke file xlsx."""
    wb = Workbook()

    # ============================================================
    # SHEET 1: Compliance Review
    # ============================================================
    ws: Worksheet = wb.active
    ws.title = "Compliance Review"

    # Header
    for col_idx, (header, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[1].height = 30

    # Data
    for i, item in enumerate(items, start=1):
        row_idx = i + 1
        status = item.get("status", "")

        # Kolom 2: gabung klausul_ref + klausul_text
        klausul_ref = item.get("klausul_ref", "")
        klausul_text = _strip_markdown(item.get("klausul_text", ""))
        klausul_full = f"{klausul_ref}\n\n{klausul_text}" if klausul_text else klausul_ref

        values = [
            i,
            klausul_full,
            item.get("regulasi_ref", ""),
            status,
            analisis_with_validation_notes(item),
        ]

        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            if col_idx == 1:
                cell.alignment = Alignment(horizontal="center", vertical="top")
            elif col_idx == _COL_STATUS:
                cell.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
                # Warna per status
                if status in STATUS_FILLS:
                    cell.fill = STATUS_FILLS[status]
                cell.font = Font(bold=True, size=9)
            else:
                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)

    # Data validation dropdown untuk Status
    options = ",".join(STATUS_OPTIONS)
    dv = DataValidation(
        type="list",
        formula1=f'"{options}"',
        allow_blank=False,
        showDropDown=False,
    )
    dv.error = "Pilih salah satu status."
    dv.errorTitle = "Status tidak valid"
    ws.add_data_validation(dv)
    last_row = max(2, len(items) + 1)
    dv.add(f"{get_column_letter(_COL_STATUS)}2:{get_column_letter(_COL_STATUS)}{last_row}")

    ws.freeze_panes = "A2"
    last_col_letter = get_column_letter(len(COLUMNS))
    ws.auto_filter.ref = f"A1:{last_col_letter}{last_row}"

    # ============================================================
    # SHEET 2: Ringkasan Eksekutif
    # ============================================================
    ws2: Worksheet = wb.create_sheet("Ringkasan Eksekutif")

    ws2.column_dimensions["A"].width = 120

    # Title
    title_cell = ws2.cell(row=1, column=1, value="RINGKASAN EKSEKUTIF")
    title_cell.font = Font(bold=True, size=14, color="1E2761")
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    ws2.row_dimensions[1].height = 28

    # Summary text
    summary_clean = _strip_markdown(executive_summary or "Tidak ada ringkasan.")

    # Split per baris untuk formatting
    lines = summary_clean.split("\n")
    row = 3
    for line in lines:
        cell = ws2.cell(row=row, column=1, value=line)
        cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        cell.font = Font(size=10)

        # Bold untuk baris yang diawali ** atau angka tebal
        if line.strip().startswith("**") or re.match(r"^\d+\.", line.strip()):
            cell.font = Font(size=10, bold=True)

        # Set row height untuk wrapped text
        ws2.row_dimensions[row].height = max(15, min(80, len(line) // 2))
        row += 1

    # ============================================================
    # Save
    # ============================================================
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


def build_markdown_table(items: list[dict[str, Any]]) -> str:
    """Build markdown table untuk copy ke dokumen lain."""
    lines = [
        "| No | Klausul / Pasal & Ayat Perjanjian | Regulasi Acuan Terkait | Status Kepatuhan | Analisis Hukum & Rekomendasi Perbaikan |",
        "|---|---|---|---|---|",
    ]

    for i, item in enumerate(items, start=1):
        klausul_ref = item.get("klausul_ref", "").replace("|", "\\|")
        klausul_text = _strip_markdown(item.get("klausul_text", "")).replace("|", "\\|").replace("\n", " ")
        klausul_full = f"**{klausul_ref}**<br>{klausul_text}" if klausul_text else f"**{klausul_ref}**"

        regulasi = item.get("regulasi_ref", "").replace("|", "\\|")
        status = item.get("status", "")
        analisis = _strip_markdown(item.get("analisis", "")).replace("|", "\\|").replace("\n", " ")

        lines.append(
            f"| {i} | {klausul_full} | {regulasi} | **{status}** | {analisis} |"
        )

    return "\n".join(lines)