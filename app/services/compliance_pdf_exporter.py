"""
PDF Exporter untuk Compliance Review Tool.

Output: A4 landscape dengan:
- Halaman 1: Tabel compliance (6 kolom)
- Halaman terakhir: Ringkasan Eksekutif
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.enums import TA_CENTER

from app.services.compliance_exporter import analisis_with_validation_notes
from app.services.compliance_review_analyzer import STATUS_PERLU_VERIFIKASI

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
MARGIN_LEFT = 0.9 * cm
MARGIN_RIGHT = 0.9 * cm
MARGIN_TOP = 1.3 * cm
MARGIN_BOTTOM = 1.3 * cm

COLOR_PRIMARY = colors.HexColor("#1E2761")
COLOR_TEXT = colors.HexColor("#2B2E3A")
COLOR_MUTED = colors.HexColor("#64748B")
COLOR_BORDER = colors.HexColor("#D9E0F0")

# Warna per status
COLOR_STATUS_FILLS = {
    "PATUH": colors.HexColor("#E3F3EA"),
    "PATUH DENGAN CATATAN": colors.HexColor("#FFF8E1"),
    "TIDAK PATUH": colors.HexColor("#FBEAE8"),
    "TIDAK RELEVAN": colors.HexColor("#F1F5F9"),
    STATUS_PERLU_VERIFIKASI: colors.HexColor("#EDE7F6"),
}

COL_WIDTHS = [
    0.9 * cm,   # No
    3.5 * cm,   # Klausul Ref
    5.5 * cm,   # Klausul Text
    4.5 * cm,   # Regulasi
    2.8 * cm,   # Status
    9.5 * cm,   # Analisis
]

HEADERS = [
    "No", "Klausul / Pasal & Ayat", "Kutipan Klausul",
    "Regulasi Acuan", "Status", "Analisis & Rekomendasi",
]


def _safe_filename_component(text: str) -> str:
    text = (text or "").strip() or "kontrak"
    text = re.sub(r"[^\w\-.]+", "_", text)
    return text.strip("_")[:80] or "kontrak"


def build_compliance_pdf_filename(nama_kontrak: str) -> str:
    return f"compliance_review_{_safe_filename_component(nama_kontrak)}.pdf"


def _escape_xml(text: str) -> str:
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _strip_markdown(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return text.strip()


def _build_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontSize=15, leading=18,
            textColor=COLOR_PRIMARY, alignment=TA_CENTER,
            fontName="Helvetica-Bold", spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontSize=9, leading=12,
            textColor=COLOR_MUTED, alignment=TA_CENTER, spaceAfter=10,
        ),
        "section_title": ParagraphStyle(
            "section_title", parent=base["Heading1"], fontSize=13, leading=16,
            textColor=COLOR_PRIMARY, fontName="Helvetica-Bold", spaceAfter=8,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base["Normal"], fontSize=6.5, leading=8.5,
            textColor=COLOR_TEXT, wordWrap="CJK",
        ),
        "cell_muted": ParagraphStyle(
            "cell_muted", parent=base["Normal"], fontSize=6, leading=8,
            textColor=COLOR_MUTED, wordWrap="CJK",
        ),
        "cell_center": ParagraphStyle(
            "cell_center", parent=base["Normal"], fontSize=6.5, leading=8.5,
            textColor=COLOR_TEXT, alignment=TA_CENTER,
        ),
        "header": ParagraphStyle(
            "header", parent=base["Normal"], fontSize=6.5, leading=8.5,
            textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_CENTER,
        ),
        "summary_body": ParagraphStyle(
            "summary_body", parent=base["Normal"], fontSize=9, leading=13,
            textColor=COLOR_TEXT,
        ),
        "summary_heading": ParagraphStyle(
            "summary_heading", parent=base["Normal"], fontSize=10, leading=14,
            textColor=COLOR_PRIMARY, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=2,
        ),
    }


def _build_header_flowables(summary: dict, styles: dict, nama_kontrak: str, regulation_filenames: list) -> list:
    flowables = [
        Paragraph("COMPLIANCE REVIEW — KONTRAK vs REGULASI", styles["title"]),
        Paragraph(
            f"Kontrak: {_escape_xml(nama_kontrak)}",
            styles["subtitle"],
        ),
    ]

    now_str = datetime.now().strftime("%d %B %Y, %H:%M")
    regs_str = ", ".join(regulation_filenames[:3])
    if len(regulation_filenames) > 3:
        regs_str += f" (+{len(regulation_filenames) - 3} lainnya)"

    meta = [
        [
            Paragraph("Tanggal Cetak", styles["cell_muted"]),
            Paragraph(_escape_xml(now_str), styles["cell"]),
            Paragraph("Total Klausul", styles["cell_muted"]),
            Paragraph(str(summary["total_items"]), styles["cell"]),
        ],
        [
            Paragraph("Regulasi Acuan", styles["cell_muted"]),
            Paragraph(_escape_xml(regs_str or "-"), styles["cell"]),
            Paragraph("Patuh / Tidak", styles["cell_muted"]),
            Paragraph(
                f"{summary['total_patuh']} / {summary['total_tidak_patuh']}",
                styles["cell"],
            ),
        ],
    ]
    meta_table = Table(meta, colWidths=[3 * cm, 10 * cm, 3.5 * cm, 4 * cm], hAlign="LEFT")
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    flowables.append(meta_table)
    flowables.append(Spacer(1, 5 * 12))
    return flowables


def _build_compliance_table(items: list[dict], styles: dict) -> Table:
    data = [[Paragraph(h, styles["header"]) for h in HEADERS]]

    for i, item in enumerate(items, start=1):
        data.append([
            Paragraph(str(i), styles["cell_center"]),
            Paragraph(_escape_xml(item.get("klausul_ref", "") or "-"), styles["cell"]),
            Paragraph(_escape_xml(item.get("klausul_text", "") or "-"), styles["cell_muted"]),
            Paragraph(_escape_xml(item.get("regulasi_ref", "") or "-"), styles["cell"]),
            Paragraph(_escape_xml(item.get("status", "")), styles["cell_center"]),
            Paragraph(_escape_xml(analisis_with_validation_notes(item)), styles["cell"]),
        ])

    table = Table(data, colWidths=COL_WIDTHS, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 1), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.25, COLOR_BORDER),
    ]

    # Highlight kolom status per baris
    for i, item in enumerate(items, start=1):
        status = item.get("status", "")
        if status in COLOR_STATUS_FILLS:
            style_cmds.append(("BACKGROUND", (4, i), (4, i), COLOR_STATUS_FILLS[status]))

    table.setStyle(TableStyle(style_cmds))
    return table


def _build_summary_flowables(executive_summary: str, styles: dict) -> list:
    flowables = [Paragraph("RINGKASAN EKSEKUTIF", styles["section_title"])]

    if not executive_summary:
        flowables.append(Paragraph("Tidak ada ringkasan.", styles["subtitle"]))
        return flowables

    # Split per baris, bold heading (yang diawali angka tebal atau **text**)
    lines = executive_summary.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            flowables.append(Spacer(1, 4))
            continue

        # Cek heading: "1. ...", "**...**"
        is_heading = bool(re.match(r"^\d+\.", stripped)) or stripped.startswith("**")
        text_clean = _strip_markdown(stripped)

        # Escape + preserve whitespace
        escaped = _escape_xml(text_clean)

        if is_heading:
            flowables.append(Paragraph(escaped, styles["summary_heading"]))
        else:
            # Preserve indentation
            indent_spaces = len(line) - len(line.lstrip())
            if indent_spaces > 0:
                escaped = "&nbsp;" * (indent_spaces // 2) + escaped
            flowables.append(Paragraph(escaped, styles["summary_body"]))

    return flowables


def _draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(COLOR_MUTED)
    page_num = canvas.getPageNumber()
    footer_text = (
        f"Regulation to IT Audit Assistant  |  Halaman {page_num}  |  "
        f"Dicetak: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )
    canvas.drawCentredString(PAGE_WIDTH / 2, 0.7 * cm, footer_text)
    canvas.restoreState()


def export_compliance_to_pdf(
    items: list[dict[str, Any]],
    output_path: str,
    executive_summary: str = "",
    nama_kontrak: str = "",
    regulation_filenames: list | None = None,
) -> str:
    """Tulis compliance review ke PDF (tabel + ringkasan eksekutif)."""
    styles = _build_styles()
    regulation_filenames = regulation_filenames or []

    summary = {
        "total_items": len(items),
        "total_patuh": sum(1 for i in items if i.get("status") == "PATUH"),
        "total_tidak_patuh": sum(1 for i in items if i.get("status") == "TIDAK PATUH"),
    }

    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(A4),
        leftMargin=MARGIN_LEFT, rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        title=f"Compliance Review — {nama_kontrak}",
        author="Regulation to IT Audit Assistant",
    )

    flowables = _build_header_flowables(summary, styles, nama_kontrak, regulation_filenames)

    if items:
        flowables.append(_build_compliance_table(items, styles))
    else:
        flowables.append(Paragraph("Tidak ada item untuk ditampilkan.", styles["subtitle"]))

    # Halaman terpisah untuk Ringkasan Eksekutif
    if executive_summary:
        flowables.append(PageBreak())
        flowables.extend(_build_summary_flowables(executive_summary, styles))

    doc.build(flowables, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return output_path