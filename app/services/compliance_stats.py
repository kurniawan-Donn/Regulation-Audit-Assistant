"""
Statistik hasil Compliance Review: persentase per status, Tingkat Kepatuhan,
dan rincian per regulasi acuan.

Dipakai ekspor Excel/PDF. Tampilan web menghitung ulang di browser dengan rumus
yang sama (static/js/compliance-stats.js) karena status bisa diubah langsung di
tabel — keduanya diuji agar hasilnya identik.

Definisi:
- Persentase status   = jumlah status / total klausul (dibulatkan dengan metode
                        sisa terbesar sehingga totalnya tepat 100%).
- Tingkat Kepatuhan   = (Patuh + Patuh dgn Catatan) / klausul relevan, dengan
                        klausul relevan = total − Tidak Relevan.
- Per regulasi        = klausul yang merujuk regulasi itu (satu klausul bisa
                        merujuk lebih dari satu regulasi); porsi = rujukan / total
                        klausul, status dihitung dari klausul yang merujuknya.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.compliance_review_analyzer import (
    STATUS_PATUH,
    STATUS_PATUH_CATATAN,
    STATUS_PERLU_VERIFIKASI,
    STATUS_TIDAK_PATUH,
    STATUS_TIDAK_RELEVAN,
)

# (kunci, status, label) — urutan sama dengan kartu ringkasan di layar.
STATUS_SPECS: tuple[tuple[str, str, str], ...] = (
    ("patuh", STATUS_PATUH, "Patuh"),
    ("catatan", STATUS_PATUH_CATATAN, "Patuh dgn Catatan"),
    ("tidak_patuh", STATUS_TIDAK_PATUH, "Tidak Patuh"),
    ("tidak_relevan", STATUS_TIDAK_RELEVAN, "Tidak Relevan"),
    ("verifikasi", STATUS_PERLU_VERIFIKASI, "Perlu Verifikasi"),
)
_KEY_BY_STATUS = {status: key for key, status, _ in STATUS_SPECS}

# Warna untuk ekspor (hex tanpa '#'), sama dengan tampilan web (tema terang).
STATUS_COLORS = {
    "patuh": "15803D",
    "catatan": "F59E0B",
    "tidak_patuh": "C2410C",
    "tidak_relevan": "8A93A6",
    "verifikasi": "2563EB",
}
def score_color(score: int | None) -> str:
    """Warna Tingkat Kepatuhan (sama dengan layar): >=80 hijau, >=50 kuning, <50 merah."""
    if score is None:
        return STATUS_COLORS["tidak_relevan"]
    if score >= 80:
        return STATUS_COLORS["patuh"]
    return STATUS_COLORS["catatan"] if score >= 50 else STATUS_COLORS["tidak_patuh"]


# Warna per regulasi acuan — sama dengan REG_COLORS di static/js/compliance.js.
REG_COLORS = ("4F46E5", "0D9488", "9333EA", "DB2777", "0891B2", "65A30D", "B45309", "475569")

_FILE_EXT_RE = re.compile(r"\.(pdf|txt)$", re.IGNORECASE)


def regulation_label(name: str) -> str:
    """Nama regulasi untuk ditampilkan: 'POJK_11_2022.pdf' -> 'POJK_11_2022'."""
    return _FILE_EXT_RE.sub("", (name or "").strip())


def round_half_up(value: float) -> int:
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def percentages(counts: list[int]) -> list[int]:
    """Persen bulat yang jumlahnya tepat 100 (metode sisa terbesar)."""
    total = sum(counts)
    if total <= 0:
        return [0] * len(counts)
    raw = [c * 100 / total for c in counts]
    floors = [int(r) for r in raw]
    remaining = 100 - sum(floors)
    # Sisa terbesar dapat +1; seri -> urutan lebih awal didahulukan (stabil).
    order = sorted(range(len(counts)), key=lambda i: (-(raw[i] - floors[i]), i))
    for i in order[:remaining]:
        floors[i] += 1
    return floors


def _status_key(item: dict) -> str:
    return _KEY_BY_STATUS.get(item.get("status", ""), "verifikasi")


def _status_breakdown(items: list[dict]) -> list[dict[str, Any]]:
    counts = [sum(1 for it in items if _status_key(it) == key) for key, _, _ in STATUS_SPECS]
    pcts = percentages(counts)
    return [
        {"key": key, "status": status, "label": label, "count": n, "percent": p}
        for (key, status, label), n, p in zip(STATUS_SPECS, counts, pcts)
    ]


def item_sources(item: dict, known_labels: list[str]) -> list[str]:
    """
    Regulasi yang dirujuk klausul. Hasil baru menyimpan `regulasi_sumber`;
    hasil lama dicocokkan dari teks `regulasi_ref` (nama regulasi ada di awal
    setiap rujukan, mis. "POJK 11/2022 Pasal 20 ayat (3)").
    """
    stored = item.get("regulasi_sumber")
    if stored:
        return list(dict.fromkeys(regulation_label(s) for s in stored if s))
    ref = (item.get("regulasi_ref") or "").lower()
    return [label for label in known_labels if label and label.lower() in ref]


def compliance_stats(items: list[dict], regulation_names: list[str] | None = None) -> dict[str, Any]:
    total = len(items)
    statuses = _status_breakdown(items)
    by_key = {s["key"]: s["count"] for s in statuses}
    relevant = total - by_key["tidak_relevan"]
    compliant = by_key["patuh"] + by_key["catatan"]

    labels = list(dict.fromkeys(regulation_label(n) for n in (regulation_names or []) if n))
    sources = [item_sources(it, labels) for it in items]
    for found in sources:                       # regulasi yang dirujuk tapi tak terdaftar
        for label in found:
            if label not in labels:
                labels.append(label)

    regulations = []
    for label in labels:
        referencing = [it for it, found in zip(items, sources) if label in found]
        regulations.append({
            "name": label,
            "referenced": len(referencing),
            "share": round_half_up(len(referencing) * 100 / total) if total else 0,
            "statuses": _status_breakdown(referencing),
        })

    return {
        "total": total,
        "statuses": statuses,
        "relevant": relevant,
        "compliant": compliant,
        "score": round_half_up(compliant * 100 / relevant) if relevant else None,
        "regulations": regulations,
        # Klausul yang dinilai (bukan Tidak Relevan) tanpa rujukan regulasi yang dikenali.
        "unattributed": sum(
            1 for it, found in zip(items, sources)
            if not found and _status_key(it) != "tidak_relevan"
        ),
    }
