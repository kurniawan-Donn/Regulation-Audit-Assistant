"""
Phase 9 - Testing Menyeluruh: Ekstraksi & Struktur Dokumen.

Mencakup skenario testing wajib dari brief (section 17, Phase 9):
1. PDF berbasis teks
2. TXT
3. PDF panjang
4. PDF dengan struktur BAB/Pasal
5. File kosong
6. File corrupt
"""

import fitz
import pytest

from app.services.pdf_parser import PDFExtractionError, extract_pdf_text
from app.services.regulation_parser import parse_regulation_structure
from app.services.text_processor import TextExtractionError, clean_text, extract_txt_text


def test_1_pdf_text_based(sample_pdf_path):
    text = extract_pdf_text(sample_pdf_path)
    assert len(text.strip()) > 0
    assert "Pasal 20" in text


def test_2_txt(sample_txt_path):
    text = extract_txt_text(sample_txt_path)
    assert "Pasal 20" in text


def test_3_pdf_panjang(tmp_path):
    """PDF dengan banyak halaman, mensimulasikan dokumen regulasi tebal."""
    pdf_path = tmp_path / "long_regulation.pdf"
    num_pages = 60

    doc = fitz.open()
    for page_num in range(num_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(
            fitz.Rect(50, 50, 545, 792),
            f"Pasal {page_num + 1}\n\n"
            f"Lembaga wajib melakukan hal fiktif nomor {page_num + 1} "
            f"untuk keperluan pengujian dokumen panjang.",
            fontsize=11,
        )
    doc.save(str(pdf_path))
    doc.close()

    text = extract_pdf_text(str(pdf_path))
    assert f"Pasal {num_pages}" in text
    assert len(text) > 1000

    chunks = parse_regulation_structure(clean_text(text))
    assert len(chunks) >= num_pages, "Minimal harus ada 1 chunk per Pasal"


def test_4_pdf_dengan_struktur_bab_pasal(sample_pdf_path):
    text = extract_pdf_text(sample_pdf_path)
    cleaned = clean_text(text)
    chunks = parse_regulation_structure(cleaned)

    pasal_20_chunks = [c for c in chunks if c["pasal"] and "Pasal 20" in c["pasal"]]
    assert len(pasal_20_chunks) >= 1
    assert any(c["ayat"] == "(1)" for c in pasal_20_chunks)
    # Label BAB kini menyertakan judul, mis. "BAB V — KEAMANAN INFORMASI ...".
    assert any((c["bab"] or "").startswith("BAB V ") for c in chunks)


def test_5_file_kosong_txt(tmp_path):
    empty_path = tmp_path / "empty.txt"
    empty_path.write_text("")
    with pytest.raises(TextExtractionError):
        extract_txt_text(str(empty_path))


def test_5_file_kosong_pdf(tmp_path):
    """PDF valid secara format tapi halamannya kosong (tidak ada teks sama sekali)."""
    empty_pdf_path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)  # halaman kosong, tanpa teks apa pun
    doc.save(str(empty_pdf_path))
    doc.close()

    with pytest.raises(PDFExtractionError):
        extract_pdf_text(str(empty_pdf_path))


def test_6_file_corrupt_pdf(tmp_path):
    corrupt_path = tmp_path / "corrupt.pdf"
    corrupt_path.write_bytes(b"Ini bukan file PDF sama sekali, cuma teks acak 12345 #$%")

    with pytest.raises(PDFExtractionError):
        extract_pdf_text(str(corrupt_path))


def test_6_file_corrupt_via_api_returns_422_not_crash(client):
    """File korup diupload lewat endpoint HARUS menghasilkan error terkontrol (422), bukan crash 500."""
    res = client.post(
        "/api/analyze",
        files={"file": ("corrupt.pdf", b"bukan pdf valid sama sekali 12345", "application/pdf")},
    )
    assert res.status_code == 422
    assert "detail" in res.json()
