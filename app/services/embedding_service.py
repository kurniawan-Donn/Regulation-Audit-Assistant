"""
Embedding Service — generate vector embedding untuk teks
menggunakan Gemini API (SDK google-genai terbaru).

Model default: gemini-embedding-001 (GA sejak Jan 2026).
- Output dimensionality: 768 (dipotong dari default 3072 untuk hemat storage & kompatibel LanceDB)
- text-embedding-004 sudah di-deprecate Jan 14, 2026 — jangan dipakai lagi.

Digunakan oleh Regulation DB untuk:
- Embed dokumen regulasi (task_type="RETRIEVAL_DOCUMENT")
- Embed query pencarian (task_type="RETRIEVAL_QUERY")
"""

import logging

from google import genai
from google.genai import types

from app.config import settings
from app.services.runtime_settings import get_effective_settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Raised ketika embedding gagal."""


# Gemini API batch limit = 100 per request
BATCH_SIZE = 50

# Output dimension — harus match dengan LanceDB schema di regulation_db.py
OUTPUT_DIMENSIONALITY = 768


class EmbeddingService:
    """
    Service untuk generate embedding.

    Instance-based supaya client di-inisialisasi sekali dengan api_key yang tepat.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        runtime = get_effective_settings()
        self.api_key = (
            api_key
            or runtime.get("gemini_api_key")
            or settings.gemini_api_key
        )

        # SDK baru tidak butuh prefix "models/"
        raw_model = (
            model
            or getattr(settings, "gemini_embedding_model", "gemini-embedding-001")
        )
        self.model = raw_model.replace("models/", "")

        if not self.api_key:
            raise ValueError(
                "API key belum diisi. Buka Pengaturan → Model & AI untuk mengisi."
            )

        self.client = genai.Client(api_key=self.api_key)

    # -------------------------------------------------------------------------
    # SINGLE TEXT
    # -------------------------------------------------------------------------

    def embed_text(self, text: str) -> list[float]:
        """Embed 1 teks (document). Return list float 768-dimensi."""
        if not text or not text.strip():
            raise EmbeddingError("Teks kosong, tidak bisa di-embed.")

        try:
            result = self.client.models.embed_content(
                model=self.model,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=OUTPUT_DIMENSIONALITY,
                ),
            )
            return result.embeddings[0].values
        except Exception as exc:
            raise EmbeddingError(f"Gagal embed: {exc}") from exc

    def embed_query(self, query: str) -> list[float]:
        """Embed query untuk retrieval (task_type berbeda)."""
        if not query or not query.strip():
            raise EmbeddingError("Query kosong.")

        try:
            result = self.client.models.embed_content(
                model=self.model,
                contents=query,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=OUTPUT_DIMENSIONALITY,
                ),
            )
            return result.embeddings[0].values
        except Exception as exc:
            raise EmbeddingError(f"Gagal embed query: {exc}") from exc

    # -------------------------------------------------------------------------
    # BATCH
    # -------------------------------------------------------------------------

    def embed_batch(
        self,
        texts: list[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]:
        """
        Embed banyak teks sekaligus (handle batching Gemini).

        Args:
            texts: list string
            task_type: "RETRIEVAL_DOCUMENT" (index) atau "RETRIEVAL_QUERY" (search)

        Returns:
            list of embedding vectors (same length as input)
        """
        if not texts:
            return []

        # Normalisasi format task_type
        formatted_task_type = task_type.upper()
        if "RETRIEVAL_" not in formatted_task_type:
            formatted_task_type = f"RETRIEVAL_{formatted_task_type}"

        # Filter empty
        cleaned = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
        if not cleaned:
            raise EmbeddingError("Semua teks kosong.")

        all_embeddings: list[list[float] | None] = [None] * len(texts)

        for batch_start in range(0, len(cleaned), BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, len(cleaned))
            batch = cleaned[batch_start:batch_end]
            batch_texts = [t for _, t in batch]

            try:
                result = self.client.models.embed_content(
                    model=self.model,
                    contents=batch_texts,
                    config=types.EmbedContentConfig(
                        task_type=formatted_task_type,
                        output_dimensionality=OUTPUT_DIMENSIONALITY,
                    ),
                )

                embeddings = [e.values for e in result.embeddings]

                for j, (orig_idx, _) in enumerate(batch):
                    all_embeddings[orig_idx] = embeddings[j]

            except Exception as exc:
                raise EmbeddingError(
                    f"Gagal embed batch {batch_start}-{batch_end}: {exc}"
                ) from exc

        if any(e is None for e in all_embeddings):
            raise EmbeddingError("Ada teks yang gagal di-embed.")

        return all_embeddings  # type: ignore