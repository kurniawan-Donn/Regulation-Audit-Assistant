"""
Prompt untuk Compliance Review — membandingkan klausul kontrak
dengan pasal regulasi, menentukan status kepatuhan, dan memberikan
rekomendasi perbaikan.

Input (per batch): beberapa klausul kontrak berlabel K1, K2, ...; tiap
klausul membawa daftar regulasi relevannya sendiri berlabel R1, R2, ...
(hasil retrieval). AI hanya boleh mengutip ID regulasi yang diberikan
untuk klausul tersebut.

Output AI: array of object dengan 4 field:
- klausul_id: ID klausul (K1, K2, ...)
- regulasi_ids: daftar ID regulasi yang dikutip (R1, R3, ...)
- status: PATUH / PATUH DENGAN CATATAN / TIDAK PATUH / TIDAK RELEVAN
- analisis: alasan + rekomendasi perbaikan

Teks klausul dan referensi regulasi lengkap disusun oleh aplikasi dari
dokumen sumber — AI tidak perlu (dan tidak boleh) menuliskannya ulang.
"""

COMPLIANCE_SYSTEM_PROMPT = """Anda adalah Senior Legal Auditor dan Compliance Officer yang ahli
dalam regulasi perbankan Indonesia, khususnya industri Bank Perekonomian Rakyat (BPR).

Tugas Anda: melakukan **audit kepatuhan (compliance review)** antara Dokumen Perjanjian
(MoU/Addendum Perjanjian Kontrak Kerjasama Sewa Layanan TI) dengan Dokumen Regulasi
Acuan (POJK, PADK, SEOJK, UU terkait).

============================================================
CARA KERJA
============================================================
Anda menerima beberapa klausul kontrak berlabel K1, K2, dst. Di bawah setiap
klausul tercantum REGULASI RELEVAN untuk klausul itu, berlabel R1, R2, dst.

Untuk SETIAP klausul, Anda WAJIB:
1. Membaca klausul dengan teliti
2. Membandingkannya HANYA dengan regulasi yang dicantumkan di bawah klausul itu
3. Menentukan status kepatuhan
4. Memberikan analisis + rekomendasi perbaikan

============================================================
KATEGORI STATUS KEPATUHAN
============================================================
- **PATUH**: Klausul sudah sejalan dan memenuhi semua syarat regulasi.
- **PATUH DENGAN CATATAN**: Klausul sudah ada, namun ada ambiguitas,
  frasa berisiko, atau detail wajib dari regulasi belum dimasukkan.
- **TIDAK PATUH**: Klausul bertentangan dengan regulasi ATAU ada
  kewajiban regulasi terkait yang sama sekali tidak dicantumkan.
- **TIDAK RELEVAN**: Tidak ada regulasi yang dicantumkan yang benar-benar
  mengatur substansi klausul ini (mis. klausul administratif).

============================================================
ATURAN KETAT
============================================================
- Kutip regulasi HANYA dengan ID (R1, R2, ...) yang dicantumkan di bawah
  klausul tersebut. JANGAN mengarang ID, nomor pasal, atau isi regulasi.
- Status PATUH / PATUH DENGAN CATATAN / TIDAK PATUH WAJIB menyebut minimal
  satu ID regulasi di "regulasi_ids".
- Kalau tidak ada regulasi yang relevan → status TIDAK RELEVAN dengan
  "regulasi_ids": [].
- Setiap klausul (K1, K2, ...) WAJIB muncul tepat satu kali di output.
- Analisis harus spesifik — sebut pasal regulasi yang dikutip, kenapa, dan
  bagaimana. Rekomendasi harus aplikatif (draf revisi klausul jika perlu).
- ID (K1, R1, ...) HANYA untuk field "klausul_id" dan "regulasi_ids".
  Di dalam teks "analisis", sebut regulasi dengan nomor pasalnya
  (mis. "Pasal 30 ayat (3)") dan klausul dengan "klausul ini" — auditor
  tidak melihat ID tersebut.
- Gunakan bahasa formal auditor/legal counsel.

============================================================
CONTOH OUTPUT
============================================================
Input:
=== K1: Pasal 6A ayat (1) ===
Jangka waktu sewa berakhir dan PIHAK PERTAMA telah menyampaikan maksud
secara tertulis untuk tidak memperpanjang perjanjian ini.
Regulasi relevan untuk K1: R1, R2

Output:
[
  {
    "klausul_id": "K1",
    "regulasi_ids": ["R2"],
    "status": "PATUH DENGAN CATATAN",
    "analisis": "Klausul sudah mengatur pengakhiran berdasarkan berakhirnya jangka waktu. Namun, Pasal 20 ayat (3) mewajibkan bank memastikan penyedia jasa TI menyerahkan kembali seluruh data dan dokumen saat pengakhiran, dan hal ini belum dicantumkan. REKOMENDASI: Tambahkan klausul 'Pada saat pengakhiran perjanjian, PIHAK KEDUA wajib menyerahkan kembali seluruh data, sistem, dan dokumentasi teknis kepada PIHAK PERTAMA serta menghapus seluruh salinan data dari sistem PIHAK KEDUA.'"
  }
]

============================================================
FORMAT OUTPUT (WAJIB)
============================================================
- Keluarkan HANYA JSON valid berupa SATU array.
- Tanpa markdown code fence, tanpa penjelasan tambahan.
- Setiap elemen WAJIB memiliki PERSIS 4 field berikut:

[
  {
    "klausul_id": "K1",
    "regulasi_ids": ["R1"],
    "status": "PATUH | PATUH DENGAN CATATAN | TIDAK PATUH | TIDAK RELEVAN",
    "analisis": "penjelasan status + rekomendasi perbaikan (max 800 karakter)"
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
- Item berstatus PERLU VERIFIKASI belum dianalisis dengan andal: JANGAN
  menyimpulkan isinya. Kalau (dan hanya kalau) ada item seperti itu,
  sebutkan jumlahnya dalam satu kalimat catatan di akhir
- Bahasa formal, objektif, dan ringkas
"""


def format_regulation_ref(chunk: dict) -> str:
    """
    Referensi regulasi yang dapat dibaca dari metadata chunk, mis.
    "POJK 11/2022 Pasal 20 ayat (3)" atau, untuk lampiran PADK,
    "PADK 43/2025 Lampiran I / BAB V / 1. Pengelolaan Aset (hal. 54)".
    """
    source = (chunk.get("source") or chunk.get("source_file") or "").strip()
    parts: list[str] = []
    if chunk.get("lampiran"):
        parts.append(chunk["lampiran"])
        for key in ("bab", "bagian"):
            if chunk.get(key):
                parts.append(str(chunk[key]).split(" — ")[0])
    pasal = chunk.get("pasal")
    if pasal:
        parts.append(pasal + (f" ayat {chunk['ayat']}" if chunk.get("ayat") else ""))
    elif not parts and chunk.get("bab"):
        parts.append(str(chunk["bab"]).split(" — ")[0])

    ref = " / ".join(parts)
    # Lazim ditulis "Penjelasan Pasal 30 ayat (3)", bukan "Penjelasan / Pasal ...".
    if ref.startswith("Penjelasan / "):
        ref = "Penjelasan " + ref[len("Penjelasan / "):]
    page = chunk.get("page_start")
    if page and not pasal:
        ref = f"{ref} (hal. {page})" if ref else f"hal. {page}"
    return " ".join(p for p in (source, ref) if p).strip()


def _regulation_header(rid: str, chunk: dict) -> str:
    return f"[{rid}] {format_regulation_ref(chunk) or 'Regulasi'}"


def build_compliance_batch_prompt(entries: list[dict], reg_by_id: dict[str, dict]) -> str:
    """
    Bangun user prompt untuk satu batch klausul.

    Args:
        entries: [{"id": "K1", "unit": {klausul_ref, judul, text}, "reg_ids": ["R1", ...]}]
        reg_by_id: {"R1": chunk regulasi (text + metadata)}

    Teks regulasi dicantumkan sekali (dedup), lalu tiap klausul menyebut
    ID regulasi yang relevan untuknya.
    """
    lines = [
        "Berikut adalah **regulasi acuan** dan **klausul-klausul kontrak** untuk dianalisis.",
        "",
        "============================================================",
        "REGULASI ACUAN",
        "============================================================",
    ]
    if not reg_by_id:
        lines.append("(Tidak ada regulasi relevan yang ditemukan untuk batch ini.)")
    for rid, chunk in reg_by_id.items():
        lines.append("")
        lines.append(_regulation_header(rid, chunk))
        lines.append((chunk.get("text") or "").strip())

    lines += [
        "",
        "============================================================",
        "KLAUSUL KONTRAK (yang diaudit)",
        "============================================================",
    ]
    for entry in entries:
        unit = entry["unit"]
        lines.append("")
        lines.append(f"=== {entry['id']}: {unit['klausul_ref']} ===")
        if unit.get("judul"):
            lines.append(f"Judul pasal: {unit['judul']}")
        lines.append(unit["text"])
        reg_list = ", ".join(entry["reg_ids"]) if entry["reg_ids"] else "(tidak ada)"
        lines.append(f"Regulasi relevan untuk {entry['id']}: {reg_list}")

    ids = ", ".join(e["id"] for e in entries)
    lines += [
        "",
        "============================================================",
        "TUGAS",
        "============================================================",
        f"Lakukan compliance review untuk SETIAP klausul berikut: {ids}.",
        "Keluarkan SATU JSON array dengan tepat satu elemen per klausul "
        "(4 field per elemen), sesuai instruksi pada system prompt.",
    ]
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
