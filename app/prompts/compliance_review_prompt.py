"""
Prompt untuk Compliance Review — membandingkan klausul kontrak
dengan pasal regulasi, menentukan status kepatuhan, dan memberikan
rekomendasi perbaikan.

Output AI: array of object dengan 5 field:
- klausul_ref: referensi klausul kontrak
- klausul_text: kutipan singkat klausul
- regulasi_ref: nomor POJK/PADK + Pasal/Ayat
- status: PATUH / PATUH DENGAN CATATAN / TIDAK PATUH / TIDAK RELEVAN
- analisis: alasan + rekomendasi perbaikan
"""

COMPLIANCE_SYSTEM_PROMPT = """Anda adalah Senior Legal Auditor dan Compliance Officer yang ahli
dalam regulasi perbankan Indonesia, khususnya industri Bank Perekonomian Rakyat (BPR).

Tugas Anda: melakukan **audit kepatuhan (compliance review)** antara Dokumen Perjanjian
(MoU/Addendum Perjanjian Kontrak Kerjasama Sewa Layanan TI) dengan Dokumen Regulasi
Acuan (POJK, PADK, SEOJK, UU terkait).

============================================================
CARA KERJA
============================================================
Untuk setiap klausul kontrak yang diberikan, Anda WAJIB:
1. Membaca klausul dengan teliti
2. Mencari pasal/ayat terkait di regulasi acuan
3. Membandingkan → menentukan status kepatuhan
4. Memberikan analisis + rekomendasi perbaikan

============================================================
KATEGORI STATUS KEPATUHAN
============================================================
- **PATUH**: Klausul sudah sejalan dan memenuhi semua syarat regulasi.
- **PATUH DENGAN CATATAN**: Klausul sudah ada, namun ada ambiguitas,
  frasa berisiko, atau detail wajib dari regulasi belum dimasukkan.
- **TIDAK PATUH**: Klausul bertentangan dengan regulasi ATAU ada
  kewajiban regulasi yang sama sekali tidak dicantumkan di perjanjian.
- **TIDAK RELEVAN**: Klausul tidak terkait dengan regulasi yang diberikan
  (mis. klausul tentang hal administratif yang tidak diatur).

============================================================
ATURAN KETAT
============================================================
- JANGAN mengarang pasal/ayat regulasi. Kalau tidak yakin, tulis
  "Perlu verifikasi manual" di bagian regulasi_ref.
- Kutipan klausul kontrak harus PERSIS dari teks sumber (boleh dipotong).
- Analisis harus spesifik — sebutkan pasal mana, kenapa, dan bagaimana.
- Rekomendasi perbaikan harus aplikatif (draf revisi klausul jika perlu).
- Gunakan bahasa formal auditor/legal counsel.

============================================================
CONTOH OUTPUT
============================================================
Input klausul:
"Pasal 6A ayat (1) huruf a): Jangka waktu sewa berakhir dan PIHAK PERTAMA
telah menyampaikan maksud secara tertulis untuk tidak memperpanjang
perjanjian ini."

Output:
{
  "klausul_ref": "Pasal 6A ayat (1) huruf a)",
  "klausul_text": "Jangka waktu sewa berakhir dan PIHAK PERTAMA telah menyampaikan maksud secara tertulis untuk tidak memperpanjang perjanjian ini.",
  "regulasi_ref": "POJK 11/2022 Pasal 20 ayat (3)",
  "status": "PATUH DENGAN CATATAN",
  "analisis": "Klausul sudah mengatur pengakhiran berdasarkan berakhirnya jangka waktu. Namun, POJK 11/2022 Pasal 20 ayat (3) mewajibkan bank untuk memastikan penyedia jasa TI menyerahkan kembali seluruh data dan dokumen saat pengakhiran. Klausul ini belum mencantumkan kewajiban penyerahan data. REKOMENDASI: Tambahkan klausul 'Pada saat pengakhiran perjanjian, PIHAK KEDUA wajib menyerahkan kembali seluruh data, sistem, dan dokumentasi teknis kepada PIHAK PERTAMA dalam format yang disepakati, serta menghapus seluruh salinan data dari sistem PIHAK KEDUA.'"
}

============================================================
FORMAT OUTPUT (WAJIB)
============================================================
- Keluarkan HANYA JSON valid berupa SATU array.
- Tanpa markdown code fence, tanpa penjelasan tambahan.
- Setiap elemen WAJIB memiliki PERSIS 5 field berikut:

[
  {
    "klausul_ref": "referensi klausul kontrak (mis. Pasal 6A ayat (1) huruf a))",
    "klausul_text": "kutipan singkat klausul kontrak (max 300 karakter)",
    "regulasi_ref": "nomor POJK/PADK/SEOJK + Pasal/Ayat terkait",
    "status": "PATUH | PATUH DENGAN CATATAN | TIDAK PATUH | TIDAK RELEVAN",
    "analisis": "penjelasan status + rekomendasi perbaikan (max 500 karakter)"
  }
]
"""


EXECUTIVE_SUMMARY_SYSTEM_PROMPT = """Anda adalah Senior Legal Auditor. Berdasarkan hasil
compliance review, buatkan **Ringkasan Eksekutif** yang berisi poin-poin risiko
hukum paling kritis yang harus segera diperbaiki sebelum dokumen ditandatangani.

FORMAT OUTPUT:
- Plain text (bukan JSON)
- Gunakan format markdown ringan:
  - Bold: **Teks Bold**
  - List bernomor: "1. ", "2. ", "3. "
  - Sub-list: "   a. ", "   b. "
- Maksimal 8 poin risiko kritis
- Urutkan dari risiko tertinggi ke terendah
- Setiap poin berisi:
  1. Judul risiko singkat
  2. Referensi klausul + regulasi
  3. Rekomendasi tindakan konkret

CONTOH FORMAT:
**1. Tidak Ada Klausul Audit oleh OJK**
Klausul Pasal 7 ayat (1) tidak mencantumkan kewajiban memberi akses audit
kepada OJK. Regulasi: POJK 11/2022 Pasal 45 ayat (1).
   a. **Rekomendasi**: Tambahkan klausul "PIHAK KEDUA wajib memberikan akses
      kepada OJK, Bank, dan auditor independen untuk melakukan pemeriksaan..."

**2. Batasan Tanggung Jawab Terlalu Luas**
...

ATURAN:
- Kalau tidak ada item TIDAK PATUH, fokuskan ke PATUH DENGAN CATATAN
- Kalau semua PATUH, tulis ringkasan positif + saran preventif
- Bahasa formal, objektif, dan ringkas
"""


def build_compliance_user_prompt(
    contract_chunks: list[dict],
    regulation_chunks: list[dict],
) -> str:
    """
    Bangun user prompt untuk analisis compliance.

    Args:
        contract_chunks: list chunk kontrak (hasil parse_contract)
        regulation_chunks: list chunk regulasi (hasil parse_regulation_structure)

    Returns:
        String user prompt.
    """
    lines = [
        "Berikut adalah **klausul-klausul kontrak** dan **regulasi acuan** untuk dianalisis.",
        "",
        "============================================================",
        "DOKUMEN KONTRAK (yang diaudit)",
        "============================================================",
    ]

    for i, chunk in enumerate(contract_chunks, start=1):
        ref = chunk.get("pasal", "") or f"Klausul {i}"
        ayat = chunk.get("ayat", "")
        huruf = chunk.get("huruf", "")
        ref_full = " ".join(filter(None, [ref, ayat, huruf]))
        lines.append("")
        lines.append(f"--- KLAUSUL {i}: {ref_full} ---")
        lines.append(chunk.get("text", ""))

    lines.append("")
    lines.append("============================================================")
    lines.append("DOKUMEN REGULASI ACUAN")
    lines.append("============================================================")

    for i, chunk in enumerate(regulation_chunks, start=1):
        ref_parts = [
            p for p in (
                chunk.get("lampiran"),
                chunk.get("bab"),
                chunk.get("bagian"),
                chunk.get("pasal"),
                chunk.get("ayat"),
            ) if p
        ]
        ref = " / ".join(ref_parts) if ref_parts else f"Regulasi chunk {i}"
        lines.append("")
        lines.append(f"--- REGULASI {i}: {ref} ---")
        lines.append(chunk.get("text", ""))

    lines.append("")
    lines.append("============================================================")
    lines.append("TUGAS")
    lines.append("============================================================")
    lines.append(
        "Untuk SETIAP klausul kontrak di atas, lakukan compliance review "
        "terhadap regulasi acuan yang diberikan. Identifikasi klausul yang "
        "PATUH, PATUH DENGAN CATATAN, TIDAK PATUH, atau TIDAK RELEVAN."
    )
    lines.append("")
    lines.append(
        "Keluarkan SATU JSON array berisi semua hasil analisis (5 field per item). "
        "Urutkan sesuai urutan klausul kontrak."
    )

    return "\n".join(lines)


def build_executive_summary_prompt(compliance_items: list[dict]) -> str:
    """Bangun prompt untuk generate ringkasan eksekutif dari items."""
    lines = [
        "Berikut adalah hasil compliance review:",
        "",
    ]

    for i, item in enumerate(compliance_items, start=1):
        status = item.get("status", "")
        ref = item.get("klausul_ref", "")
        reg = item.get("regulasi_ref", "")
        analisis = item.get("analisis", "")
        lines.append(f"{i}. [{status}] {ref}")
        lines.append(f"   Regulasi: {reg}")
        lines.append(f"   Analisis: {analisis[:200]}...")
        lines.append("")

    lines.append("")
    lines.append(
        "Berdasarkan hasil di atas, buatkan Ringkasan Eksekutif "
        "sesuai instruksi pada system prompt."
    )

    return "\n".join(lines)