"""
Route "Tanya Regulasi" (RAG Chat): tanya-jawab bersitasi atas Regulation DB.

Satu pertanyaan = 1 embedding + 1 panggilan AI (beberapa detik), jadi
dijalankan langsung di threadpool — tidak lewat background job.
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.api.common import ai_provider_or_422, embedder_or_422, internal_error
from app.models.schemas import ChatRequest, ChatResponse
from app.services.ai_service import AIProviderError, AIResponseParsingError
from app.services.embedding_service import EmbeddingError
from app.services.regulation_chat import ChatAnswerError, answer_question
from app.services.regulation_db import RegulationDBError, get_regulation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    question = payload.question.strip()
    if len(question) < 3:
        raise HTTPException(status_code=422, detail="Pertanyaan minimal 3 karakter.")

    regulation_ids = [rid for rid in payload.regulation_ids if get_regulation(rid)]
    if payload.regulation_ids and not regulation_ids:
        raise HTTPException(status_code=404, detail="Regulasi yang dipilih tidak ditemukan di database.")

    provider, embedder = ai_provider_or_422(), embedder_or_422()
    history = [t.model_dump() for t in payload.history]

    try:
        result = await run_in_threadpool(
            answer_question, question, regulation_ids, history, embedder, provider,
        )
    except EmbeddingError as exc:
        raise HTTPException(status_code=502, detail=f"Gagal memproses pertanyaan: {exc}") from exc
    except (AIResponseParsingError, ChatAnswerError) as exc:
        logger.warning("Jawaban AI tidak valid: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="AI tidak mengembalikan jawaban yang valid. Coba ulangi pertanyaan.",
        ) from exc
    except AIProviderError as exc:
        # Pesan sudah dibuat ramah pengguna oleh ai_service (quota, API key, dst.).
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RegulationDBError as exc:
        raise internal_error("mencari di database regulasi", exc) from exc

    return ChatResponse(**result)
