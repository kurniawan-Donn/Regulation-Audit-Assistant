"""
PDF Exporter untuk Compliance Review Tool.

Output: A4 landscape dengan:
- Halaman 1: statistik (Tingkat Kepatuhan, % per status, per regulasi acuan)
  lalu tabel compliance (6 kolom)
- Halaman terakhir: Ringkasan Eksekutif
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.graphics.shapes import Drawing, Rect
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
from app.services.compliance_stats import REG_COLORS, STATUS_COLORS, compliance_stats, score_color

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


def _hex(color: str) -> colors.Color:
    return colors.HexColor(f"#{color}")


def _stacked_bar(statuses: list[dict], width: float, height: float) -> Drawing:
    """Bar bertumpuk per status (lebar segmen sebanding jumlah klausul)."""
    drawing = Drawing(width, height)
    total = sum(s["count"] for s in statuses)
    if not total:
        drawing.add(Rect(0, 0, width, height, fillColor=COLOR_BORDER, strokeColor=None))
        return drawing
    x = 0.0
    for s in statuses:
        if not s["count"]:
            continue
        w = width * s["count"] / total
        drawing.add(Rect(x, 0, w, height, fillColor=_hex(STATUS_COLORS[s["key"]]), strokeColor=colors.white,
                         strokeWidth=0.6))
        x += w
    return drawing


def _build_stats_flowables(stats: dict, styles: dict) -> list:
    """Tingkat Kepatuhan + % per status + rincian per regulasi acuan."""
    usable = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT - 12      # frame punya padding 6 pt kiri/kanan
    score = stats["score"]
    big = ParagraphStyle("score", parent=styles["cell"], fontSize=20, leading=23,
                         fontName="Helvetica-Bold", textColor=_hex(score_color(score)))
    label = ParagraphStyle("kicker", parent=styles["cell_muted"], fontSize=6.5, fontName="Helvetica-Bold")

    score_cell = [
        Paragraph("TINGKAT KEPATUHAN", label),
        Paragraph("-" if score is None else f"{score}%", big),
        Paragraph(f"{stats['compliant']} dari {stats['relevant']} klausul relevan "
                  "Patuh / Patuh dgn Catatan", styles["cell_muted"]),
    ]
    status_cells = []
    for s in stats["statuses"]:
        color = _hex(STATUS_COLORS[s["key"]])
        num = ParagraphStyle(f"n_{s['key']}", parent=styles["cell_center"], fontSize=13, leading=15,
                             fontName="Helvetica-Bold", textColor=color)
        status_cells.append([
            Paragraph(f"{s['percent']}%", num),
            Paragraph(f"{_escape_xml(s['label'])} ({s['count']})", styles["cell_center"]),
        ])
    score_w = 6.2 * cm
    cell_w = (usable - score_w) / len(status_cells)
    top = Table([[score_cell, *status_cells]], colWidths=[score_w] + [cell_w] * len(status_cells))
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("LINEAFTER", (0, 0), (0, 0), 0.5, COLOR_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, s in enumerate(stats["statuses"], start=1):
        style.append(("LINEABOVE", (i, 0), (i, 0), 2.5, _hex(STATUS_COLORS[s["key"]])))
    top.setStyle(TableStyle(style))

    flowables = [top, Spacer(1, 4), _stacked_bar(stats["statuses"], usable, 7), Spacer(1, 8)]

    if stats["regulations"]:
        header = ["Regulasi acuan", "Dirujuk", "Porsi", "Sebaran status"] + [s["label"] for s in stats["statuses"]]
        rows = [[Paragraph(_escape_xml(h), styles["header"]) for h in header]]
        bar_w = 5.2 * cm
        for i, reg in enumerate(stats["regulations"]):
            reg_color = _hex(REG_COLORS[i % len(REG_COLORS)])
            name_style = ParagraphStyle(f"r{i}", parent=styles["cell"], fontName="Helvetica-Bold",
                                        textColor=reg_color)
            rows.append([
                Paragraph(_escape_xml(reg["name"]), name_style),
                Paragraph(f"{reg['referenced']} dari {stats['total']}", styles["cell_center"]),
                Paragraph(f"<b>{reg['share']}%</b>", styles["cell_center"]),
                _stacked_bar(reg["statuses"], bar_w - 0.3 * cm, 6) if reg["referenced"] else "",
                *[Paragraph(f"{s['percent']}% ({s['count']})", styles["cell_center"]) for s in reg["statuses"]],
            ])
        fixed = [1.9 * cm, 1.4 * cm, bar_w] + [1.9 * cm] * len(stats["statuses"])
        reg_table = Table(rows, colWidths=[usable - sum(fixed)] + fixed, repeatRows=1)
        reg_style = [
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for i, s in enumerate(stats["statuses"], start=4):
            reg_style.append(("BACKGROUND", (i, 0), (i, 0), _hex(STATUS_COLORS[s["key"]])))
        for i in range(len(stats["regulations"])):
            reg_style.append(("LINEBEFORE", (0, i + 1), (0, i + 1), 3, _hex(REG_COLORS[i % len(REG_COLORS)])))
        reg_table.setStyle(TableStyle(reg_style))
        flowables.append(reg_table)

        notes = []
        if len(stats["regulations"]) > 1:
            notes.append("Satu klausul bisa merujuk lebih dari satu regulasi, sehingga jumlah porsi bisa melebihi 100%.")
        if stats["unattributed"]:
            notes.append(f"{stats['unattributed']} klausul tanpa rujukan regulasi yang dikenali.")
        if notes:
            flowables.append(Spacer(1, 3))
            flowables.append(Paragraph(_escape_xml(" ".join(notes)), styles["cell_muted"]))

    flowables.append(Spacer(1, 12))
    return flowables


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
            Paragraph("Tingkat Kepatuhan", styles["cell_muted"]),
            Paragraph(
                "-" if summary["score"] is None else f"{summary['score']}%",
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
    flowables.append(Spacer(1, 10))
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

    stats = compliance_stats(items, regulation_filenames)
    summary = {"total_items": len(items), "score": stats["score"]}

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
        flowables.extend(_build_stats_flowables(stats, styles))

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