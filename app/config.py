"""
Application configuration.

Semua nilai dibaca dari environment variable (.env).
Modul ini menjadi satu-satunya sumber konfigurasi agar tidak ada
nilai konfigurasi yang tersebar di banyak file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Regulation to IT Audit Assistant"
    app_env: str = "development"
    debug: bool = True
        # --- Embedding (untuk RAG / Regulation DB) ---
    gemini_embedding_model: str = "gemini-embedding-001"
    lancedb_dir: str = "data/lancedb"
    regulation_db_registry: str = "data/regulations.json"

    # AI provider
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_max_output_tokens: int = 8192
    gemini_min_seconds_between_requests: float = 4.5

    # Batching
    max_chars_per_batch: int = 6000

    # Background jobs — jumlah analisis AI yang boleh jalan bersamaan.
    # Default 1: job lain antre, supaya rate limit Gemini tidak terlampaui.
    max_concurrent_jobs: int = 1

    # Upload settings
    max_upload_size_mb: int = 10

    # --- Pricing untuk estimasi biaya (USD per 1 juta token) ---
    gemini_input_price_per_1m_usd: float = 0.30
    gemini_output_price_per_1m_usd: float = 2.50
    usd_to_idr: float = 16000.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()