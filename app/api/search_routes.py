"""
Route pencarian global lintas hasil Regulation to Audit & Gap Analysis.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    SearchResponse,
    SearchResultItem,
)
from app.api.common import (
    OUTPUT_DIR,
    REQUIREMENTS_OUTPUT_DIR,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["search"])


# ===========================================================================
# SEARCH GLOBAL
# ===========================================================================

def _extract_snippet(text: str, query: str, radius: int = 60) -> str:
    if not text:
        return ""
    lowered = text.lower()
    q_lower = query.lower()
    pos = lowered.find(q_lower)
    if pos < 0:
        return text[:radius * 2] + ("..." if len(text) > radius * 2 else "")

    start = max(0, pos - radius)
    end = min(len(text), pos + len(query) + radius)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def _search_in_file(path: Path, query: str, source: str, date_min_ts: float | None) -> list[dict]:
    if not path.exists():
        return []

    if date_min_ts is not None:
        try:
            if path.stat().st_mtime < date_min_ts:
                return []
        except Exception:
            pass

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    result_id = path.stem
    filename = data.get("filename", "unknown")
    try:
        created_iso = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except Exception:
        created_iso = ""

    q_lower = query.lower()
    matches: list[dict] = []

    if source == "regulation_audit":
        items = data.get("results", [])
        for idx, item in enumerate(items):
            searchable = " ".join([
                item.get("referensi_regulasi", ""),
                item.get("aspek", ""),
                item.get("bab_pasal_ayat", ""),
                item.get("point_ketentuan", ""),
                item.get("pemeriksaan", ""),
                item.get("metode_audit", ""),
                item.get("kebutuhan_bukti", ""),
                item.get("catatan_temuan", ""),
            ]).lower()

            if q_lower not in searchable:
                continue

            title_field = item.get("point_ketentuan", "") or item.get("pemeriksaan", "")
            snippet = _extract_snippet(title_field, query)

            matches.append({
                "source": source,
                "result_id": result_id,
                "filename": filename,
                "item_index": idx,
                "title": (item.get("point_ketentuan", "")[:150] or "(tanpa judul)"),
                "snippet": snippet,
                "referensi": item.get("bab_pasal_ayat", ""),
                "aspek": item.get("aspek", ""),
                "status": item.get("status_kepatuhan", ""),
                "created_at": created_iso,
                "raw_item": item,
            })

    elif source == "gap_analysis":
        items = data.get("requirements", [])
        for idx, item in enumerate(items):
            searchable = " ".join([
                item.get("persyaratan", ""),
                item.get("referensi", ""),
                item.get("catatan", ""),
            ]).lower()

            if q_lower not in searchable:
                continue

            title_field = item.get("persyaratan", "")
            snippet = _extract_snippet(title_field, query)

            matches.append({
                "source": source,
                "result_id": result_id,
                "filename": filename,
                "item_index": idx,
                "title": (item.get("persyaratan", "")[:150] or "(tanpa judul)"),
                "snippet": snippet,
                "referensi": item.get("referensi", ""),
                "aspek": "",
                "status": item.get("status_gap", ""),
                "created_at": created_iso,
                "raw_item": item,
            })

    return matches


@router.get("/search", response_model=SearchResponse)
async def search_global(
    q: str = Query(..., min_length=2),
    tools: str = Query("all"),
    days: int | None = Query(None, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
) -> SearchResponse:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Query minimal 2 karakter.")

    if tools == "all":
        tools_searched = ["regulation_audit", "gap_analysis"]
    elif tools in ("regulation_audit", "gap_analysis"):
        tools_searched = [tools]
    else:
        raise HTTPException(
            status_code=422,
            detail="Parameter 'tools' harus 'all', 'regulation_audit', atau 'gap_analysis'.",
        )

    date_min_ts: float | None = None
    if days:
        cutoff = datetime.now() - timedelta(days=days)
        date_min_ts = cutoff.timestamp()

    all_matches: list[dict] = []

    if "regulation_audit" in tools_searched and OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.glob("*.json"):
            all_matches.extend(_search_in_file(f, query, "regulation_audit", date_min_ts))

    if "gap_analysis" in tools_searched:
        req_dir = REQUIREMENTS_OUTPUT_DIR
        if req_dir.exists():
            for f in req_dir.glob("*.json"):
                all_matches.extend(_search_in_file(f, query, "gap_analysis", date_min_ts))

    all_matches.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    total_before_limit = len(all_matches)
    all_matches = all_matches[:limit]

    by_doc: dict[str, int] = {}
    for m in all_matches:
        key = f"{m['source']}::{m['filename']}"
        by_doc[key] = by_doc.get(key, 0) + 1

    results = [SearchResultItem(**m) for m in all_matches]

    return SearchResponse(
        query=query,
        total=total_before_limit,
        results=results,
        by_document=by_doc,
        tools_searched=tools_searched,
        date_filter_days=days,
    )
