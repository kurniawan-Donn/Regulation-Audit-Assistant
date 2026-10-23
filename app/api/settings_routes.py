"""
Route pengaturan runtime (model, API key, batching), uji koneksi AI,
dan diagnostik server.
"""

import logging
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from app.config import settings as app_config
from app.models.schemas import (
    ConnectionTestRequest,
    ConnectionTestResponse,
    DiagnosticsResponse,
    RuntimeSettingsResponse,
    RuntimeSettingsUpdate,
)
from app.services.ai_service import GeminiProvider
from app.services.runtime_settings import (
    PRESET_MODELS,
    get_effective_settings,
    get_settings_masked,
)
from app.services.runtime_settings import update_settings as update_runtime_settings
from app.api.common import (
    OUTPUT_DIR,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["settings"])


# ===========================================================================
# SETTINGS
# ===========================================================================

@router.get("/settings", response_model=RuntimeSettingsResponse)
async def get_runtime_settings_endpoint() -> RuntimeSettingsResponse:
    data = get_settings_masked()
    return RuntimeSettingsResponse(
        gemini_api_key_masked=data.get("gemini_api_key_masked", ""),
        gemini_api_key_set=bool(data.get("gemini_api_key_set", False)),
        gemini_model=str(data.get("gemini_model", "")),
        gemini_max_output_tokens=int(data.get("gemini_max_output_tokens", 8192)),
        gemini_min_seconds_between_requests=float(
            data.get("gemini_min_seconds_between_requests", 4.5)
        ),
        max_chars_per_batch=int(data.get("max_chars_per_batch", 6000)),
        theme=str(data.get("theme", "auto")),
        preset_models=list(PRESET_MODELS),
        demo_mode=app_config.demo_mode,
    )


@router.put("/settings", response_model=RuntimeSettingsResponse)
async def update_runtime_settings_endpoint(
    payload: RuntimeSettingsUpdate,
) -> RuntimeSettingsResponse:
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    update_runtime_settings(updates)
    return await get_runtime_settings_endpoint()


@router.post("/settings/test-connection", response_model=ConnectionTestResponse)
async def test_connection(payload: ConnectionTestRequest) -> ConnectionTestResponse:
    runtime = get_effective_settings()
    api_key = (payload.api_key or "").strip() or runtime.get("gemini_api_key", "")
    model = (payload.model or "").strip() or runtime.get("gemini_model", "")

    if not api_key:
        return ConnectionTestResponse(
            ok=False, message="API key belum diisi.",
            model_tested=model or "-", latency_ms=0,
        )
    if not model:
        return ConnectionTestResponse(
            ok=False, message="Model belum dipilih.",
            model_tested="-", latency_ms=0,
        )

    def _ping() -> str:
        # Provider sendiri (client terisolasi) — tidak mengganggu job yang sedang jalan.
        provider = GeminiProvider(
            api_key=api_key,
            model_name=model,
            timeout_seconds=30,
            max_network_retries=0,
            max_output_tokens=1024,
            min_seconds_between_requests=0,
        )
        return provider.generate_text("", "Balas dengan satu kata: OK").strip()

    start = time.time()
    try:
        text = await run_in_threadpool(_ping)
        latency = int((time.time() - start) * 1000)
        return ConnectionTestResponse(
            ok=True,
            message=f"Koneksi berhasil. Response: '{text[:60]}'",
            model_tested=model,
            latency_ms=latency,
        )
    except Exception as exc:
        latency = int((time.time() - start) * 1000)
        return ConnectionTestResponse(
            ok=False,
            message=f"Gagal: {str(exc)[:300]}",
            model_tested=model,
            latency_ms=latency,
        )


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def get_diagnostics() -> DiagnosticsResponse:
    from app.config import settings as app_settings

    previews_dir = Path("cache/previews")
    previews_count = 0
    cache_size = 0
    if previews_dir.exists():
        for f in previews_dir.glob("*.json"):
            previews_count += 1
            try:
                cache_size += f.stat().st_size
            except Exception:
                pass

    outputs_count = 0
    if OUTPUT_DIR.exists():
        outputs_count = len(list(OUTPUT_DIR.glob("*.json")))

    runtime = get_effective_settings()
    ai_ok = bool(runtime.get("gemini_api_key", "").strip())
    ai_message = "API key tersedia." if ai_ok else "API key belum diisi."

    return DiagnosticsResponse(
        server_ok=True,
        ai_ok=ai_ok,
        ai_message=ai_message,
        model_name=runtime.get("gemini_model", "-"),
        cache_previews_count=previews_count,
        cache_size_mb=round(cache_size / (1024 * 1024), 2),
        outputs_count=outputs_count,
        app_version="1.0.0",
        app_env=app_settings.app_env,
    )
