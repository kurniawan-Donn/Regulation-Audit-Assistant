"""
Regresi parser regulasi (Fase 2).

Prinsip yang diuji: TIDAK ADA TEKS ISI YANG HILANG, dan label
Pasal/Ayat tidak tertipu rujukan silang.
"""

import re

from app.services.regulation_parser import parse_regulation_structure
from app.services.text_processor import clean_text


def _parse(text: str) -> list[dict]:
    return parse_regulation_structure(clean_text(text))


def _all_text(chunks: list[dict]) -> str:
    return re.sub(r"\s+", " ", " ".join(c["text"] for c in chunks))


def _find(chunks: list[dict], needle: str) -> dict:
    for c in chunks:
        if needle in re.sub(r"\s+", " ", c["text"]):
            return c
    raise AssertionError(f"Teks tidak ditemukan di chunk mana pun: {needle!r}")


HEADER = "PERATURAN CONTOH\nTENTANG\nTATA KELOLA\n\nBAB I\nKETENTUAN UMUM\n\n"


def test_teks_sebaris_dengan_penanda_ayat_tidak_hilang():
    chunks = _parse(HEADER + """Pasal 20

(1) Lembaga wajib memiliki kebijakan keamanan informasi tertulis.

(2) Kebijakan sebagaimana dimaksud pada ayat (1) wajib dikomunikasikan.

Pasal 21

(1) Lembaga wajib menerapkan pengendalian akses terhadap sistem informasi.
""")
    c = _find(chunks, "Lembaga wajib memiliki kebijakan keamanan informasi tertulis")
    assert (c["pasal"], c["ayat"]) == ("Pasal 20", "(1)")
    c = _find(chunks, "wajib dikomunikasikan")
    assert (c["pasal"], c["ayat"]) == ("Pasal 20", "(2)")
    c = _find(chunks, "menerapkan pengendalian akses")
    assert (c["pasal"], c["ayat"]) == ("Pasal 21", "(1)")


def test_butir_tetap_satu_chunk_dengan_ayatnya():
    chunks = _parse(HEADER + """Pasal 3

(1) Bank wajib melakukan pemetaan atas aspek paling sedikit:
a. proses bisnis;
b. struktur organisasi; dan
c. kebijakan, standar, dan prosedur.

(2) Bank memastikan terciptanya sinergi.
""")
    c = _find(chunks, "a. proses bisnis;")
    assert c["ayat"] == "(1)"
    assert "b. struktur organisasi" in c["text"]
    assert "c. kebijakan, standar, dan prosedur." in c["text"]
    assert c["huruf"] == ["a", "b", "c"]


def test_penanda_yang_berdiri_sendiri_digabung_dengan_teksnya():
    # Pola PDF justified: penanda di satu baris, teks di baris berikutnya.
    chunks = _parse(HEADER + """Pasal 3
(1)
Dalam menerapkan tata kelola TI, Bank wajib
melakukan
pemetaan atas aspek paling sedikit:
a.
proses bisnis;
b.
struktur organisasi.
(2)
Bank memastikan terciptanya sinergi.
""")
    c = _find(chunks, "Dalam menerapkan tata kelola TI, Bank wajib melakukan pemetaan")
    assert c["ayat"] == "(1)"
    assert "a. proses bisnis;" in c["text"]
    assert _find(chunks, "Bank memastikan terciptanya sinergi")["ayat"] == "(2)"


def test_rujukan_silang_di_awal_baris_bukan_heading_pasal():
    chunks = _parse(HEADER + """Pasal 10

(1) Bank yang melanggar ketentuan sebagaimana dimaksud dalam
Pasal 8 ayat (1), dikenai sanksi administratif berupa teguran tertulis.

(2) Selain sanksi sebagaimana dimaksud pada
ayat (1), Bank dikenai sanksi administratif berupa denda.
""")
    c = _find(chunks, "Pasal 8 ayat (1), dikenai sanksi administratif")
    assert (c["pasal"], c["ayat"]) == ("Pasal 10", "(1)")
    c = _find(chunks, "ayat (1), Bank dikenai sanksi administratif berupa denda")
    assert (c["pasal"], c["ayat"]) == ("Pasal 10", "(2)")
    assert not any(c["pasal"] == "Pasal 8" for c in chunks)


def test_nomor_ayat_dalam_rujukan_tidak_memicu_ayat_baru():
    chunks = _parse(HEADER + """Pasal 3
(1)
Bank wajib memiliki kebijakan.
(2)
Bank memastikan sinergi.
(3)
Bank wajib menerapkan kebijakan sebagaimana dimaksud pada ayat
(1)
huruf c secara konsisten dan berkesinambungan.
(4)
Bank wajib melakukan kaji ulang secara berkala.
""")
    c = _find(chunks, "huruf c secara konsisten")
    assert c["ayat"] == "(3)"
    assert _find(chunks, "kaji ulang secara berkala")["ayat"] == "(4)"
    ayat_labels = [c["ayat"] for c in chunks if c["pasal"] == "Pasal 3"]
    assert ayat_labels == ["(1)", "(2)", "(3)", "(4)"]


def test_ayat_sisipan_amandemen_diterima():
    chunks = _parse(HEADER + """Pasal 5

(1) Ketentuan pertama yang berlaku umum.

(2) Ketentuan kedua yang berlaku umum.

(2a) Ketentuan sisipan hasil perubahan peraturan.

(3) Ketentuan ketiga yang berlaku umum.
""")
    assert _find(chunks, "Ketentuan sisipan")["ayat"] == "(2a)"
    assert _find(chunks, "Ketentuan ketiga")["ayat"] == "(3)"


def test_daftar_definisi_bernomor_di_dalam_pasal_bukan_heading():
    chunks = _parse(HEADER + """Pasal 1

Dalam Peraturan ini yang dimaksud dengan:
1. Lembaga adalah pihak yang menyelenggarakan kegiatan jasa keuangan.
2. Teknologi Informasi adalah perangkat keras, perangkat lunak, dan
   infrastruktur pendukung yang digunakan Lembaga.
""")
    c = _find(chunks, "2. Teknologi Informasi adalah perangkat keras, perangkat lunak, dan infrastruktur")
    assert c["pasal"] == "Pasal 1"
    assert "1. Lembaga adalah pihak" in c["text"]


def test_lampiran_padk_judul_bernomor_vs_kalimat_bernomor():
    chunks = _parse("""LAMPIRAN I
PERATURAN ANGGOTA DEWAN KOMISIONER

BAB V
PENGAMANAN INFORMASI

1. Pengelolaan Aset
a. aset BPR yang terkait dengan informasi harus diidentifikasikan;
b. aset tersebut dicatat agar dapat dilindungi.
2. BPR dan BPR Syariah menempatkan Sistem Elektronik berupa
Pusat Data dan Pusat Pemulihan Bencana di wilayah Indonesia.
""")
    judul = _find(chunks, "a. aset BPR yang terkait")
    assert judul["pasal"] == "1. Pengelolaan Aset"
    assert judul["text"].startswith("1. Pengelolaan Aset")  # judul juga ada di isi
    kalimat = _find(chunks, "menempatkan Sistem Elektronik berupa Pusat Data")
    assert "Pusat Pemulihan Bencana di wilayah Indonesia" in _all_text(chunks)
    assert kalimat["pasal"] == "1. Pengelolaan Aset"  # kalimat, bukan judul baru


def test_stempel_salinan_di_tengah_dokumen_tidak_membuang_pasal():
    chunks = _parse(HEADER + """Pasal 4
BPR menyesuaikan kebijakan dan prosedur penyelenggaraan TI.
@@PAGE_3@@
Salinan ini sesuai dengan aslinya
Kepala Direktorat Pengembangan Hukum
Departemen Hukum
ttd.
Aat Windradi
Pasal 5
BPR menyusun pedoman penyelenggaraan TI sesuai kebutuhan.
""")
    c = _find(chunks, "BPR menyesuaikan kebijakan dan prosedur")
    assert c["pasal"] == "Pasal 4"
    assert "Aat Windradi" not in _all_text(chunks)
    assert _find(chunks, "BPR menyusun pedoman")["pasal"] == "Pasal 5"


def test_daftar_isi_yang_menempel_di_pasal_hanya_baris_tocnya_dibuang():
    chunks = _parse(HEADER + """Pasal 4
BPR menyesuaikan kebijakan dan prosedur penyelenggaraan TI sesuai ketentuan.
DAFTAR ISI
Tata Kelola TI 3
Arsitektur TI 4
Manajemen Risiko TI 5
Keamanan Siber 7
Pengelolaan Data 9
Penutup 12
""")
    c = _find(chunks, "BPR menyesuaikan kebijakan dan prosedur")
    assert c["pasal"] == "Pasal 4"
    assert "Arsitektur TI 4" not in c["text"]


def test_penjelasan_dipisah_dari_batang_tubuh():
    chunks = _parse(HEADER + """Pasal 2
(1) Bank wajib menerapkan tata kelola TI secara efektif.

PENJELASAN
ATAS PERATURAN CONTOH

Pasal 2
Ayat (1)
Penerapan tata kelola TI merupakan bagian dari tata kelola Bank.
""")
    body = _find(chunks, "Bank wajib menerapkan tata kelola TI")
    penj = _find(chunks, "merupakan bagian dari tata kelola Bank")
    assert body["lampiran"] is None
    assert (penj["lampiran"], penj["pasal"], penj["ayat"]) == ("Penjelasan", "Pasal 2", "(1)")


def test_nomor_halaman_terlacak():
    chunks = _parse(HEADER + """@@PAGE_5@@
Pasal 3
(1) Bank wajib memiliki kebijakan tata kelola TI yang memadai.
@@PAGE_6@@
(2) Bank memastikan terciptanya sinergi pada seluruh aspek.
""")
    assert _find(chunks, "kebijakan tata kelola TI")["page_start"] == 5
    assert _find(chunks, "terciptanya sinergi")["page_start"] == 6
    assert "@@" not in _all_text(chunks)


def test_cache_parse_versi_lama_dianggap_basi(tmp_path, monkeypatch):
    from app.services import preview_cache

    monkeypatch.setattr(preview_cache, "PARSED_DIR", tmp_path)
    file_hash = "a" * 64
    preview_cache.save_parsed_by_hash(file_hash, "x.txt", "teks", [], [])
    assert preview_cache.load_parsed_by_hash(file_hash) is not None

    monkeypatch.setattr(preview_cache, "PARSER_VERSION", preview_cache.PARSER_VERSION + 1)
    assert preview_cache.load_parsed_by_hash(file_hash) is None
    assert not (tmp_path / f"{file_hash}.json").exists()
