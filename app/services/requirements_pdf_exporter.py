"""
PDF Exporter untuk Gap Analysis Tool.

Output: 1 dokumen A4 landscape, kolom:
No | Persyaratan | Referensi | Catatan | Status Gap
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
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.enums import TA_CENTER

# =============================================================================
# KONFIGURASI
# =============================================================================

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
MARGIN_LEFT = 0.9 * cm
MARGIN_RIGHT = 0.9 * cm
MARGIN_TOP = 1.3 * cm
MARGIN_BOTTOM = 1.3 * cm

COLOR_PRIMARY = colors.HexColor("#1E2761")
COLOR_TEXT = colors.HexColor("#2B2E3A")
COLOR_MUTED = colors.HexColor("#64748B")
COLOR_BORDER = colors.HexColor("#D9E0F0")
COLOR_STATUS_BG = colors.HexColor("#FFF8E1")

COL_WIDTHS = [
    0.9 * cm,   # No
    6.0 * cm,   # Persyaratan
    5.0 * cm,   # Referensi
    10.0 * cm,  # Catatan
    3.5 * cm,   # Status Gap
]

HEADERS = ["No", "Persyaratan", "Referensi", "Catatan", "Status Gap"]


def _safe_filename_component(text: str) -> str:
    text = (text or "").strip() or "regulasi"
    text = re.sub(r"[^\w\-.]+", "_", text)
    return text.strip("_")[:80] or "regulasi"


def build_requirements_pdf_filename(referensi_regulasi: str) -> str:
    return f"gap_analysis_{_safe_filename_component(referensi_regulasi)}.pdf"


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
    }


def _build_header_flowables(summary: dict, styles: dict, referensi: str) -> list:
    flowables = [
        Paragraph("DAFTAR PERSYARATAN — GAP ANALYSIS", styles["title"]),
        Paragraph(
            f"Berdasarkan: {_escape_xml(referensi or 'Dokumen Regulasi')}",
            styles["subtitle"],
        ),
    ]

    now_str = datetime.now().strftime("%d %B %Y, %H:%M")
    meta = [
        [
            Paragraph("Tanggal Cetak", styles["cell_muted"]),
            Paragraph(_escape_xml(now_str), styles["cell"]),
            Paragraph("Total Persyaratan", styles["cell_muted"]),
            Paragraph(str(summary["total_items"]), styles["cell"]),
        ],
    ]
    meta_table = Table(meta, colWidths=[3 * cm, 8 * cm, 3.5 * cm, 4 * cm], hAlign="LEFT")
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    flowables.append(meta_table)
    flowables.append(Spacer(1, 5 * 12))
    return flowables


def _build_table(items: list[dict], styles: dict) -> Table:
    data = [[Paragraph(h, styles["header"]) for h in HEADERS]]

    for i, item in enumerate(items, start=1):
        data.append([
            Paragraph(str(i), styles["cell_center"]),
            Paragraph(_escape_xml(_strip_markdown(item.get("persyaratan", ""))), styles["cell"]),
            Paragraph(_escape_xml(item.get("referensi", "") or "-"), styles["cell"]),
            Paragraph(_escape_xml(_strip_markdown(item.get("catatan", ""))), styles["cell_muted"]),
            Paragraph(_escape_xml(item.get("status_gap", "") or "Belum Dinilai"), styles["cell_center"]),
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
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]

    # Highlight baris dengan status
    for i, item in enumerate(items, start=1):
        status = item.get("status_gap", "")
        if status and status not in ("Belum Dinilai", ""):
            style_cmds.append(("BACKGROUND", (4, i), (4, i), COLOR_STATUS_BG))

    table.setStyle(TableStyle(style_cmds))
    return table


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


def export_requirements_to_pdf(
    items: list[dict[str, Any]],
    output_path: str,
    referensi_regulasi: str = "",
    filename: str = "",
) -> str:
    """Tulis persyaratan ke PDF."""
    styles = _build_styles()
    summary = {"total_items": len(items)}

    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(A4),
        leftMargin=MARGIN_LEFT, rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        title=f"Gap Analysis — {referensi_regulasi or filename}",
        author="Regulation to IT Audit Assistant",
    )

    flowables = _build_header_flowables(summary, styles, referensi_regulasi)

    if items:
        flowables.append(_build_table(items, styles))
    else:
        flowables.append(Paragraph("Tidak ada persyaratan.", styles["subtitle"]))

    doc.build(flowables, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return output_path