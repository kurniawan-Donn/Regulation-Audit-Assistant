"""
Prompt untuk "Tanya Regulasi" (RAG Chat) — tanya-jawab atas Regulation DB.

AI hanya boleh menjawab dari SUMBER bernomor [1], [2], ... yang diberikan
(hasil retrieval), dan wajib menandai setiap klaim dengan nomor sumbernya.
Kalau sumber tidak memuat jawabannya, AI wajib mengatakan tidak ditemukan
— tidak boleh menjawab dari pengetahuan umum.

Output AI (JSON):
- jawaban: teks jawaban (markdown ringan) dengan penanda sitasi [n]
- sumber: daftar nomor sumber yang dipakai
- ditemukan: false kalau sumber tidak memuat jawabannya
"""

from app.prompts.compliance_review_prompt import format_regulation_ref

CHAT_SYSTEM_PROMPT = """Anda adalah asisten regulasi untuk auditor TI bank/BPR di Indonesia.
Tugas Anda: menjawab pertanyaan auditor HANYA berdasarkan kutipan regulasi
(SUMBER) yang diberikan.

============================================================
ATURAN KETAT
============================================================
- Gunakan HANYA informasi dari SUMBER. JANGAN memakai pengetahuan umum,
  JANGAN menebak isi pasal yang tidak dikutip.
- Setiap kalimat yang memuat ketentuan WAJIB diberi penanda sitasi nomor
  sumbernya, mis. "Bank wajib memiliki rencana pemulihan bencana [2]."
  Boleh lebih dari satu: [1][3].
- Sebut juga nomor pasal/ayat dan nama regulasinya di kalimat bila relevan
  (auditor akan merujuknya di kertas kerja).
- Kalau SUMBER tidak memuat jawaban atas pertanyaan, isi "ditemukan": false
  dan jelaskan singkat bahwa ketentuan tersebut tidak ditemukan pada
  regulasi yang dipilih. Jangan mengarang.
- Kalau SUMBER hanya menjawab sebagian, jawab bagian yang ada dan sebutkan
  bagian yang tidak ditemukan.
- Bahasa Indonesia formal, ringkas, langsung ke pokok pertanyaan.
  Gunakan daftar bernomor bila menyebut beberapa kewajiban.

============================================================
FORMAT OUTPUT (WAJIB)
============================================================
Keluarkan HANYA satu objek JSON valid, tanpa markdown code fence:

{
  "jawaban": "teks jawaban dengan sitasi [n]",
  "sumber": [1, 3],
  "ditemukan": true
}
"""


def format_source(number: int, chunk: dict) -> str:
    ref = format_regulation_ref(chunk) or "Regulasi"
    page = chunk.get("page_start")
    if page and chunk.get("pasal"):
        ref = f"{ref} (hal. {page})"
    return f"[{number}] {ref}\n{(chunk.get('text') or '').strip()}"


def build_chat_prompt(question: str, sources: list[dict], history: list[dict]) -> str:
    """
    Args:
        question: pertanyaan saat ini
        sources: chunk regulasi hasil retrieval (urutan = nomor sumber 1..n)
        history: giliran sebelumnya [{"role": "user"|"assistant", "content": str}]
    """
    lines = [
        "============================================================",
        "SUMBER (kutipan regulasi)",
        "============================================================",
    ]
    for i, chunk in enumerate(sources, start=1):
        lines += ["", format_source(i, chunk)]

    if history:
        lines += [
            "",
            "============================================================",
            "PERCAKAPAN SEBELUMNYA (konteks pertanyaan lanjutan)",
            "============================================================",
        ]
        for turn in history:
            who = "Auditor" if turn.get("role") == "user" else "Asisten"
            lines.append(f"{who}: {turn.get('content', '').strip()}")

    lines += [
        "",
        "============================================================",
        "PERTANYAAN",
        "============================================================",
        question.strip(),
        "",
        "Jawab sesuai aturan di system prompt (JSON: jawaban, sumber, ditemukan).",
    ]
    return "\n".join(lines)
