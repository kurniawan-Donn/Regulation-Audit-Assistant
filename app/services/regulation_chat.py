"""
Tanya Regulasi (RAG Chat) — tanya-jawab bersitasi atas Regulation DB.

Alur satu pertanyaan:
1. Retrieval hybrid (vektor + kata kunci) top-K chunk dari regulasi terpilih.
   Pertanyaan lanjutan yang pendek ("bagaimana sanksinya?") digabung dengan
   pertanyaan auditor sebelumnya supaya retrieval tetap tepat sasaran.
2. AI menjawab HANYA dari sumber bernomor [1]..[n] (prompts/chat_prompt.py).
3. Validasi sitasi: penanda [n] yang tidak merujuk sumber yang diberikan
   dibuang dan dicatat; jawaban "ditemukan" tanpa sitasi valid ditandai
   perlu ditinjau. Daftar sumber (rujukan pasal + halaman + kutipan)
   dikembalikan apa adanya dari database — bukan tulisan ulang AI.

Server tidak menyimpan percakapan; client mengirim beberapa giliran terakhir.
"""

import re

from app.prompts.chat_prompt import CHAT_SYSTEM_PROMPT, build_chat_prompt
from app.prompts.compliance_review_prompt import format_regulation_ref
from app.services.ai_service import AIProvider
from app.services.embedding_service import EmbeddingService
from app.services.regulation_db import query_relevant_chunks

DEFAULT_TOP_K = 8
MAX_HISTORY_TURNS = 6
_HISTORY_TURN_MAX_CHARS = 600
_SHORT_FOLLOW_UP_WORDS = 12
_ANSWER_MAX_CHARS = 6000

_RE_CITATION = re.compile(r"\[(\d{1,2})\]")


class ChatAnswerError(Exception):
    """Response AI tidak berbentuk jawaban yang bisa dipakai."""


def retrieval_query(question: str, history: list[dict]) -> str:
    """Pertanyaan lanjutan yang pendek diberi konteks pertanyaan auditor sebelumnya."""
    previous = [t["content"] for t in history if t.get("role") == "user" and t.get("content")]
    if previous and len(question.split()) < _SHORT_FOLLOW_UP_WORDS:
        return f"{previous[-1]}\n{question}"
    return question


def _trim_history(history: list[dict]) -> list[dict]:
    trimmed = []
    for turn in history[-MAX_HISTORY_TURNS:]:
        content = str(turn.get("content") or "").strip()
        if not content:
            continue
        if len(content) > _HISTORY_TURN_MAX_CHARS:
            content = content[:_HISTORY_TURN_MAX_CHARS] + "…"
        trimmed.append({"role": turn.get("role", "user"), "content": content})
    return trimmed


def _source_from_hit(number: int, hit: dict) -> dict:
    meta = hit.get("metadata", {})
    chunk = {
        "source": meta.get("regulation_name") or "",
        "lampiran": meta.get("lampiran") or None,
        "bab": meta.get("bab") or None,
        "bagian": meta.get("bagian") or None,
        "pasal": meta.get("pasal") or None,
        "ayat": meta.get("ayat") or None,
        "page_start": meta.get("page_start") or None,
        "text": hit.get("text", ""),
    }
    return {
        "number": number,
        "regulation_id": meta.get("regulation_id", ""),
        "regulation_name": chunk["source"],
        "reference": format_regulation_ref(chunk),
        "page_start": chunk["page_start"],
        "text": chunk["text"],
        "chunk": chunk,  # untuk prompt; dibuang sebelum dikirim ke client
    }


def answer_question(
    question: str,
    regulation_ids: list[str] | None,
    history: list[dict],
    embedder: EmbeddingService,
    provider: AIProvider,
    top_k: int = DEFAULT_TOP_K,
) -> dict:
    """
    Return:
        {answer, found, cited: [n], sources: [{number, reference, ...,
         cited}], notes: [str], needs_review: bool}

    Raises:
        ChatAnswerError, AIProviderError, EmbeddingError, RegulationDBError
    """
    history = _trim_history(history)
    query = retrieval_query(question, history)
    vector = embedder.embed_batch([query], task_type="RETRIEVAL_QUERY")[0]
    hits = query_relevant_chunks(
        query_embedding=vector,
        regulation_ids=regulation_ids or None,
        top_k=top_k,
        query_text=query,
    )
    sources = [_source_from_hit(i, h) for i, h in enumerate(hits, start=1)]

    if not sources:
        return {
            "answer": "Tidak ada kutipan regulasi yang ditemukan. Pastikan Database "
                      "Regulasi sudah berisi regulasi yang relevan.",
            "found": False,
            "cited": [],
            "sources": [],
            "notes": [],
            "needs_review": False,
        }

    prompt = build_chat_prompt(question, [s["chunk"] for s in sources], history)
    raw = provider.generate_json(CHAT_SYSTEM_PROMPT, prompt)
    if not isinstance(raw, dict) or not isinstance(raw.get("jawaban"), str):
        raise ChatAnswerError("Response AI bukan objek JSON berisi 'jawaban'.")

    answer, cited, notes = _validate_citations(raw, len(sources))
    found = bool(raw.get("ditemukan", True))
    if found and not cited:
        notes.append("Jawaban tidak menyertakan sitasi sumber yang valid — verifikasi manual.")

    for s in sources:
        s.pop("chunk")
        s["cited"] = s["number"] in cited

    return {
        "answer": answer[:_ANSWER_MAX_CHARS],
        "found": found,
        "cited": cited,
        "sources": sources,
        "notes": notes,
        "needs_review": bool(notes),
    }


def _validate_citations(raw: dict, n_sources: int) -> tuple[str, list[int], list[str]]:
    """
    Sitasi sah = nomor 1..n_sources. Penanda [n] yang tidak sah dihapus dari
    teks; daftar sitasi = gabungan penanda di teks dan field "sumber".
    """
    notes: list[str] = []
    invalid: set[int] = set()

    def keep_valid(match: re.Match) -> str:
        n = int(match.group(1))
        if 1 <= n <= n_sources:
            return match.group(0)
        invalid.add(n)
        return ""

    answer = _RE_CITATION.sub(keep_valid, raw["jawaban"]).strip()
    cited = {int(m) for m in _RE_CITATION.findall(answer)}

    for value in raw.get("sumber") or []:
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= n_sources:
            cited.add(n)
        else:
            invalid.add(n)

    if invalid:
        notes.append(
            "AI menyebut sumber yang tidak ada (" + ", ".join(f"[{n}]" for n in sorted(invalid))
            + ") — sitasi tersebut dihapus."
        )
    return answer, sorted(cited), notes
