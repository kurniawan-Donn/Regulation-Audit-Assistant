"""
Daftar Temuan (findings register): temuan audit lintas alat dalam satu tempat.

Temuan dikirim dari hasil Compliance Review (klausul yang tidak/sebagian patuh)
dan Gap Analysis (persyaratan yang tidak/sebagian sesuai), atau ditulis
manual. Formatnya mengikuti kertas kerja temuan audit yang lazim: kondisi,
kriteria, rekomendasi, tingkat risiko, dan status tindak lanjut.

Disimpan di data/findings.json (ditulis atomik di bawah lock).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.json_store import locked, read_json, write_json_atomic

FINDINGS_FILE = Path("data") / "findings.json"

RISK_LEVELS = ("Tinggi", "Sedang", "Rendah")
FOLLOW_UP_STATUSES = ("Terbuka", "Dalam Proses", "Selesai")
EDITABLE_FIELDS = (
    "judul", "kondisi", "kriteria", "rekomendasi", "risiko",
    "status", "pic", "target_date", "tanggapan",
)

# Status sumber yang dianggap temuan (dipakai saat "kirim semua temuan").
COMPLIANCE_FINDING_RISK = {
    "TIDAK PATUH": "Tinggi",
    "PATUH DENGAN CATATAN": "Sedang",
    "PERLU VERIFIKASI": "Sedang",
}
GAP_FINDING_RISK = {
    "tidak sesuai": "Tinggi",
    "sebagian sesuai": "Sedang",
}

_RECOMMENDATION_RE = re.compile(r"\s*REKOMENDASI\s*:\s*", re.IGNORECASE)
_TITLE_MAX = 120


class FindingNotFound(LookupError):
    pass


class SourceNotFound(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict:
    if not FINDINGS_FILE.exists():
        return {"next_number": 1, "items": []}
    return read_json(FINDINGS_FILE)


def _save(data: dict) -> None:
    write_json_atomic(FINDINGS_FILE, data)


def _fingerprint(source_type: str, result_id: str, *parts: str) -> str:
    raw = "\x1f".join([source_type, result_id, *[(p or "").strip().lower() for p in parts]])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _title(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= _TITLE_MAX else text[: _TITLE_MAX - 1].rstrip() + "…"


def split_recommendation(analysis: str) -> tuple[str, str]:
    """'… REKOMENDASI: …' → (kondisi, rekomendasi)."""
    parts = _RECOMMENDATION_RE.split(analysis or "", maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return (analysis or "").strip(), ""


def _from_compliance(result: dict, index: int, item: dict) -> dict:
    kondisi, rekomendasi = split_recommendation(item.get("analisis", ""))
    status = (item.get("status") or "").upper()
    klausul = " ".join(p for p in (item.get("klausul_ref"), item.get("klausul_text")) if p)
    return {
        "judul": _title(f"{item.get('klausul_ref') or 'Klausul'}: {item.get('klausul_text') or ''}"),
        "kondisi": kondisi or klausul,
        "kriteria": item.get("regulasi_ref") or "",
        "rekomendasi": rekomendasi,
        "risiko": COMPLIANCE_FINDING_RISK.get(status, "Rendah"),
        "source": {
            "type": "compliance_review",
            "result_id": result.get("result_id", ""),
            "nama": result.get("contract_filename", ""),
            "ref": item.get("klausul_ref", ""),
            "status": item.get("status", ""),
            "item_index": index,
        },
        "fingerprint": _fingerprint(
            "compliance_review", result.get("result_id", ""),
            item.get("klausul_ref", ""), item.get("klausul_text", ""), item.get("regulasi_ref", ""),
        ),
    }


def _from_gap(result: dict, index: int, item: dict) -> dict:
    status = (item.get("status_gap") or "").strip()
    catatan = (item.get("catatan") or "").strip()
    kondisi = f"Persyaratan dinilai {status.lower() or 'belum dinilai'}."
    if catatan:
        kondisi += f" Catatan: {catatan}"
    return {
        "judul": _title(item.get("persyaratan", "")),
        "kondisi": kondisi,
        "kriteria": " — ".join(p for p in (item.get("referensi"), item.get("persyaratan")) if p),
        "rekomendasi": "",
        "risiko": GAP_FINDING_RISK.get(status.lower(), "Rendah"),
        "source": {
            "type": "gap_analysis",
            "result_id": result.get("result_id", ""),
            "nama": result.get("filename", ""),
            "ref": item.get("referensi", ""),
            "status": status,
            "item_index": index,
        },
        "fingerprint": _fingerprint(
            "gap_analysis", result.get("result_id", ""),
            item.get("persyaratan", ""), item.get("referensi", ""),
        ),
    }


def candidates_from_result(source_type: str, result: dict, indices: list[int] | None) -> list[dict]:
    """
    Calon temuan dari satu hasil. indices=None → semua baris berstatus temuan
    (Tidak Patuh / dengan Catatan / Perlu Verifikasi; Tidak / Sebagian Sesuai).
    """
    if source_type == "compliance_review":
        rows = result.get("items") or []
        is_finding = lambda it: (it.get("status") or "").upper() in COMPLIANCE_FINDING_RISK  # noqa: E731
        build = _from_compliance
    elif source_type == "gap_analysis":
        rows = result.get("requirements") or []
        is_finding = lambda it: (it.get("status_gap") or "").strip().lower() in GAP_FINDING_RISK  # noqa: E731
        build = _from_gap
    else:
        raise SourceNotFound(source_type)

    if indices is None:
        picked = [(i, r) for i, r in enumerate(rows) if is_finding(r)]
    else:
        picked = [(i, rows[i]) for i in sorted(set(indices)) if 0 <= i < len(rows)]
    return [build(result, i, r) for i, r in picked]


def _new_finding(data: dict, fields: dict) -> dict:
    number = int(data.get("next_number") or 1)
    data["next_number"] = number + 1
    now = _now()
    finding = {
        "id": uuid.uuid4().hex,
        "nomor": number,
        "judul": "",
        "kondisi": "",
        "kriteria": "",
        "rekomendasi": "",
        "risiko": "Sedang",
        "status": "Terbuka",
        "pic": "",
        "target_date": "",
        "tanggapan": "",
        "source": {"type": "manual"},
        "fingerprint": "",
        "created_at": now,
        "updated_at": now,
    }
    finding.update(fields)
    return finding


def add_from_result(source_type: str, result: dict, indices: list[int] | None) -> dict:
    """Tambahkan temuan dari hasil analisis; temuan yang sama tidak dobel."""
    candidates = candidates_from_result(source_type, result, indices)
    with locked(FINDINGS_FILE):
        data = _load()
        existing = {f.get("fingerprint") for f in data["items"] if f.get("fingerprint")}
        added = []
        for cand in candidates:
            if cand["fingerprint"] in existing:
                continue
            existing.add(cand["fingerprint"])
            finding = _new_finding(data, cand)
            data["items"].append(finding)
            added.append(finding)
        if added:
            _save(data)
    return {"added": added, "skipped": len(candidates) - len(added), "candidates": len(candidates)}


def _clean(fields: dict) -> dict:
    out = {k: (str(v).strip() if v is not None else "") for k, v in fields.items() if k in EDITABLE_FIELDS}
    if "risiko" in out and out["risiko"] not in RISK_LEVELS:
        raise ValueError(f"Risiko harus salah satu dari: {', '.join(RISK_LEVELS)}.")
    if "status" in out and out["status"] not in FOLLOW_UP_STATUSES:
        raise ValueError(f"Status harus salah satu dari: {', '.join(FOLLOW_UP_STATUSES)}.")
    if out.get("target_date") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", out["target_date"]):
        raise ValueError("Target tanggal harus berformat YYYY-MM-DD.")
    return out


def add_manual(fields: dict) -> dict:
    cleaned = _clean(fields)
    if not cleaned.get("judul"):
        raise ValueError("Judul temuan wajib diisi.")
    with locked(FINDINGS_FILE):
        data = _load()
        finding = _new_finding(data, cleaned)
        data["items"].append(finding)
        _save(data)
    return finding


def update_finding(finding_id: str, fields: dict) -> dict:
    cleaned = _clean(fields)
    with locked(FINDINGS_FILE):
        data = _load()
        for finding in data["items"]:
            if finding["id"] == finding_id:
                finding.update(cleaned)
                finding["updated_at"] = _now()
                _save(data)
                return finding
    raise FindingNotFound(finding_id)


def delete_finding(finding_id: str) -> None:
    with locked(FINDINGS_FILE):
        data = _load()
        remaining = [f for f in data["items"] if f["id"] != finding_id]
        if len(remaining) == len(data["items"]):
            raise FindingNotFound(finding_id)
        data["items"] = remaining
        _save(data)


def list_findings() -> dict:
    with locked(FINDINGS_FILE):
        items = list(_load()["items"])
    items.sort(key=lambda f: f.get("nomor", 0))
    summary = {
        "total": len(items),
        "by_status": {s: sum(1 for f in items if f.get("status") == s) for s in FOLLOW_UP_STATUSES},
        "by_risk": {r: sum(1 for f in items if f.get("risiko") == r) for r in RISK_LEVELS},
    }
    return {"items": items, "summary": summary}


# =============================================================================
# PENGATURAN LAPORAN (diingat agar auditor tidak mengetik ulang)
# =============================================================================

REPORT_META_FIELDS = ("judul", "auditee", "disusun_oleh", "tanggal", "ringkasan", "statuses", "risks")


def get_report_meta() -> dict:
    with locked(FINDINGS_FILE):
        return dict(_load().get("report") or {})


def save_report_meta(meta: dict) -> None:
    with locked(FINDINGS_FILE):
        data = _load()
        data["report"] = {k: meta[k] for k in REPORT_META_FIELDS if k in meta}
        _save(data)
