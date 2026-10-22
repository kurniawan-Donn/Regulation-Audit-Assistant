"""
API Routes untuk Prompt Editor.

Endpoint:
- GET  /api/prompts/{tool}              -> status lengkap prompt
- PUT  /api/prompts/{tool}              -> update override
- POST /api/prompts/{tool}/reset        -> reset ke default
- POST /api/prompts/{tool}/preview      -> preview prompt final

Tool yang didukung:
- "regulation_audit"  (Tool 1)
- "gap_analysis"      (Tool 2)
"""

import logging

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    PromptPreviewResponse,
    PromptResetRequest,
    PromptStatusResponse,
    PromptUpdateRequest,
    PromptPresetInfo,
    PromptPresetsResponse,
)
from app.services.prompt_manager import (
    SUPPORTED_TOOLS,
    get_full_status,
    preview_final_prompt,
    reset_prompt,
    update_prompt,
)

from app.prompts.prompt_presets import get_presets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


def _validate_tool(tool: str) -> None:
    if tool not in SUPPORTED_TOOLS:
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{tool}' tidak dikenal. "
                   f"Tool yang tersedia: {', '.join(SUPPORTED_TOOLS)}.",
        )


@router.get("/{tool}", response_model=PromptStatusResponse)
async def get_prompt_status(tool: str) -> PromptStatusResponse:
    """Ambil status lengkap prompt untuk tool tertentu."""
    _validate_tool(tool)
    status = get_full_status(tool)
    return PromptStatusResponse(**status)


@router.put("/{tool}", response_model=PromptStatusResponse)
async def update_prompt_endpoint(
    tool: str,
    payload: PromptUpdateRequest,
) -> PromptStatusResponse:
    """
    Update prompt override.
    - core_override: None = tidak diubah; "" = reset ke default;
      string = set override baru (min 50 char).
    - user_instructions: None = tidak diubah; string = set baru.
    """
    _validate_tool(tool)
    try:
        update_prompt(
            tool=tool,
            core_override=payload.core_override,
            user_instructions=payload.user_instructions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    status = get_full_status(tool)
    return PromptStatusResponse(**status)


@router.post("/{tool}/reset", response_model=PromptStatusResponse)
async def reset_prompt_endpoint(
    tool: str,
    payload: PromptResetRequest,
) -> PromptStatusResponse:
    """
    Reset prompt ke default.
    section: "core" | "user" | "all"
    """
    _validate_tool(tool)
    if payload.section not in ("core", "user", "all"):
        raise HTTPException(
            status_code=422,
            detail="Section harus salah satu dari: 'core', 'user', 'all'.",
        )
    try:
        reset_prompt(tool=tool, section=payload.section)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    status = get_full_status(tool)
    return PromptStatusResponse(**status)


@router.post("/{tool}/preview", response_model=PromptPreviewResponse)
async def preview_prompt_endpoint(tool: str) -> PromptPreviewResponse:
    """Bangun prompt final (yang akan dikirim ke AI) untuk preview."""
    _validate_tool(tool)
    try:
        final = preview_final_prompt(tool)
    except Exception as exc:
        logger.exception("Gagal build preview prompt untuk %s", tool)
        raise HTTPException(
            status_code=500,
            detail="Gagal membangun preview prompt. Detail tercatat di log server.",
        ) from exc

    return PromptPreviewResponse(
        tool=tool,
        final_prompt=final,
        total_chars=len(final),
    )

@router.get("/{tool}/presets", response_model=PromptPresetsResponse)
async def get_prompt_presets(tool: str) -> PromptPresetsResponse:
    """Ambil daftar preset prompt untuk tool tertentu."""
    _validate_tool(tool)
    presets = get_presets(tool)
    return PromptPresetsResponse(
        tool=tool,
        presets=[
            PromptPresetInfo(
                id=p["id"],
                name=p["name"],
                description=p["description"],
                core_text=p["core_text"],
            )
            for p in presets
        ],
    )