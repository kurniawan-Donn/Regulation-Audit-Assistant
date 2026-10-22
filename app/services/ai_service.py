"""
AI Service - abstraksi provider AI.

Desain:

    AIProvider (abstract)
        |
        +-- GeminiProvider   <- dipakai sekarang (SDK google-genai)

Provider lain (OpenAIProvider, AnthropicProvider, LocalLLMProvider) tinggal
dibuat sebagai subclass baru dari AIProvider tanpa mengubah kode yang
memanggilnya (routes.py, dsb. cukup memanggil get_ai_provider()).

Dua lapis retry yang berbeda tujuannya:
1. Retry jaringan (di dalam GeminiProvider.generate_text) - untuk error
   transient seperti timeout, service unavailable, rate limit.
2. Retry parsing (di dalam AIProvider.generate_json) - untuk kasus
   response AI berhasil didapat tapi bukan JSON valid.

Runtime Settings:
Provider membaca API key + model dari runtime settings (data/settings.json)
dengan prioritas tertinggi, fallback ke .env.

Thread-safety:
Setiap GeminiProvider memegang genai.Client miliknya sendiri (bukan
konfigurasi global), jadi beberapa job yang berjalan paralel dengan API key
berbeda tidak saling menimpa.
"""

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import settings

# Kode HTTP dari Gemini yang layak di-retry di level jaringan.
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

# Error jaringan murni (sebelum ada response HTTP) — juga di-retry.
_RETRYABLE_NETWORK_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


def _humanize_google_error(exc: genai_errors.APIError) -> str:
    """Ubah APIError Gemini menjadi pesan yang lebih bisa ditindaklanjuti user."""
    code = getattr(exc, "code", None)
    msg = getattr(exc, "message", None) or str(exc)
    lowered = msg.lower()

    if code == 429 or "quota" in lowered:
        return (
            "Quota / rate limit Gemini API habis (429). "
            "Solusi: tunggu 15–60 menit, cek quota di "
            "https://aistudio.google.com/app/apikey, atau ganti API key."
        )

    if code == 403:
        return (
            "Akses ke Gemini API ditolak (403 — Permission Denied). "
            "Kemungkinan: (a) API key sudah di-disable, "
            "(b) restriction API key terlalu ketat, "
            "(c) model tidak valid, atau (d) project di-suspend. "
            "Cek Google Cloud Console → APIs & Services → Credentials."
        )

    if code == 401 or ("api key" in lowered and code == 400):
        return (
            "API key tidak valid atau tidak dikenali. "
            "Pastikan API key di panel Pengaturan sudah benar."
        )

    if code == 404 or "model" in lowered:
        return (
            f"Model Gemini tidak dikenali. Cek model di panel Pengaturan. "
            f"Detail: {msg}"
        )

    return f"Gagal memanggil Gemini API ({code}): {msg}"


class AIProviderError(Exception):
    """Error umum saat memanggil AI provider (network, timeout, API error, dll)."""


class AIResponseParsingError(AIProviderError):
    """Response AI berhasil didapat tetapi tetap bukan JSON valid setelah semua retry."""


class AIProvider(ABC):
    """Kontrak yang wajib dipenuhi setiap provider AI."""

    @abstractmethod
    def generate_text(
        self, system_prompt: str, user_prompt: str, expect_json: bool = False
    ) -> str:
        """
        Kirim system prompt + user prompt ke AI, kembalikan raw text response.

        Args:
            system_prompt: instruksi peran/tugas AI.
            user_prompt: konten yang diminta untuk dianalisis.
            expect_json: jika True, provider yang mendukung "JSON mode"
                native (seperti Gemini) akan memaksa output berupa JSON.

        Raises:
            AIProviderError: jika request gagal setelah semua retry.
        """
        raise NotImplementedError

    def generate_json(
        self, system_prompt: str, user_prompt: str, max_retries: int = 2
    ) -> Any:
        """
        Sama seperti generate_text(), tapi hasilnya di-parse menjadi object
        Python (list/dict) hasil json.loads().

        Jika hasil bukan JSON valid, prompt dikirim ulang dengan peringatan
        tambahan, maksimal `max_retries` kali.

        Raises:
            AIResponseParsingError: jika tetap gagal setelah semua retry.
            AIProviderError: jika request ke AI sendiri gagal (bukan soal parsing).
        """
        current_user_prompt = user_prompt
        last_parse_error: Exception | None = None

        for attempt in range(max_retries + 1):
            raw_text = self.generate_text(
                system_prompt, current_user_prompt, expect_json=True
            )
            try:
                return _parse_json_response(raw_text)
            except (json.JSONDecodeError, ValueError) as exc:
                last_parse_error = exc
                current_user_prompt = (
                    f"{user_prompt}\n\n"
                    "PERINGATAN: Response Anda sebelumnya BUKAN JSON valid. "
                    "Keluarkan HANYA JSON valid, tanpa markdown code fence, "
                    "tanpa penjelasan tambahan di luar JSON."
                )

        raise AIResponseParsingError(
            f"Gagal mendapatkan JSON valid dari AI setelah {max_retries + 1} "
            f"percobaan. Error parsing terakhir: {last_parse_error}"
        )


def _parse_json_response(raw_text: str) -> Any:
    """Bersihkan markdown code fence (jika ada) lalu parse sebagai JSON."""
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    if not text:
        raise ValueError("Response AI kosong.")
    return json.loads(text)


class GeminiProvider(AIProvider):
    """
    Implementasi AIProvider menggunakan Google Gemini API (SDK google-genai).

    Membaca api_key & model dari runtime settings (data/settings.json)
    dengan prioritas tertinggi, fallback ke .env.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        timeout_seconds: int = 120,
        max_network_retries: int = 2,
        retry_backoff_seconds: float = 2.0,
        max_output_tokens: int | None = None,
        min_seconds_between_requests: float | None = None,
    ) -> None:
        # Baca dari runtime settings (prioritas tertinggi).
        # Import di dalam __init__ untuk hindari circular import.
        try:
            from app.services.runtime_settings import get_effective_settings
            runtime = get_effective_settings()
        except Exception:
            runtime = {}

        self._api_key = (
            api_key
            or runtime.get("gemini_api_key")
            or settings.gemini_api_key
        )
        self._model_name = (
            model_name
            or runtime.get("gemini_model")
            or settings.gemini_model
        )
        self._timeout_seconds = timeout_seconds
        self._max_network_retries = max_network_retries
        self._retry_backoff_seconds = retry_backoff_seconds

        if max_output_tokens is not None:
            self._max_output_tokens = max_output_tokens
        else:
            self._max_output_tokens = int(
                runtime.get("gemini_max_output_tokens", settings.gemini_max_output_tokens)
            )

        if min_seconds_between_requests is not None:
            self._min_seconds_between_requests = min_seconds_between_requests
        else:
            self._min_seconds_between_requests = float(
                runtime.get(
                    "gemini_min_seconds_between_requests",
                    settings.gemini_min_seconds_between_requests,
                )
            )

        self._last_request_time: float = 0.0

        if not self._api_key:
            raise ValueError(
                "GEMINI_API_KEY belum diset. Silakan masukkan di panel Pengaturan "
                "atau isi file .env (lihat .env.example)."
            )

        self._client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=int(self._timeout_seconds * 1000)),
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    def _wait_for_rate_limit(self) -> None:
        """
        Jeda otomatis sebelum tiap request, supaya jarak antar-request ke
        Gemini tidak lebih rapat dari `min_seconds_between_requests`.

        Pengaman terhadap limit RPM (requests per minute) free tier.
        """
        if self._min_seconds_between_requests <= 0:
            return
        elapsed = time.time() - self._last_request_time
        remaining = self._min_seconds_between_requests - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def generate_text(
        self, system_prompt: str, user_prompt: str, expect_json: bool = False
    ) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system_prompt or None,
            temperature=0,
            max_output_tokens=self._max_output_tokens,
            response_mime_type="application/json" if expect_json else None,
        )

        last_error: Exception | None = None

        for attempt in range(self._max_network_retries + 1):
            self._wait_for_rate_limit()
            try:
                response = self._client.models.generate_content(
                    model=self._model_name,
                    contents=user_prompt,
                    config=config,
                )
                self._last_request_time = time.time()
                return _extract_text_from_response(response)

            except genai_errors.APIError as exc:
                self._last_request_time = time.time()
                last_error = exc
                if exc.code in _RETRYABLE_STATUS_CODES:
                    if attempt < self._max_network_retries:
                        time.sleep(self._retry_backoff_seconds * (attempt + 1))
                        continue
                    raise AIProviderError(
                        f"Gemini API gagal setelah {attempt + 1} percobaan "
                        f"(timeout/unavailable/rate limit): {_humanize_google_error(exc)}"
                    ) from exc
                raise AIProviderError(_humanize_google_error(exc)) from exc

            except _RETRYABLE_NETWORK_EXCEPTIONS as exc:
                self._last_request_time = time.time()
                last_error = exc
                if attempt < self._max_network_retries:
                    time.sleep(self._retry_backoff_seconds * (attempt + 1))
                    continue
                raise AIProviderError(
                    f"Gemini API gagal setelah {attempt + 1} percobaan "
                    f"(jaringan/timeout): {exc}"
                ) from exc

            except AIProviderError:
                raise

            except Exception as exc:
                self._last_request_time = time.time()
                raise AIProviderError(f"Gagal memanggil Gemini API: {exc}") from exc

        raise AIProviderError(f"Gemini API gagal: {last_error}")


def _extract_text_from_response(response: Any) -> str:
    """Ambil teks dari response Gemini, dengan pesan error yang jelas jika gagal."""
    if not getattr(response, "candidates", None):
        feedback = getattr(response, "prompt_feedback", None)
        raise AIProviderError(
            "Gemini tidak mengembalikan kandidat response. Kemungkinan "
            f"konten diblokir oleh safety filter. Detail: {feedback}"
        )
    try:
        text = response.text
    except Exception as exc:
        raise AIProviderError(
            f"Gagal membaca teks dari response Gemini: {exc}"
        ) from exc

    if not text:
        finish_reason = getattr(response.candidates[0], "finish_reason", None)
        raise AIProviderError(
            f"Gemini mengembalikan response kosong (finish_reason={finish_reason})."
        )
    return text


def get_ai_provider() -> AIProvider:
    """
    Factory function — baca runtime settings setiap kali dipanggil.
    Jadi kalau user ubah API key/model di panel Pengaturan, langsung
    berlaku untuk request berikutnya tanpa restart server.
    """
    return GeminiProvider()
