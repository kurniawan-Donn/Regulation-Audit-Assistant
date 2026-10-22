"""
Bandingkan Regulasi: padankan ketentuan dua regulasi di Regulation DB
(mis. POJK lama vs pengganti, PBI vs PADG pelaksananya).

Tanpa panggilan AI — memakai vektor yang sudah tersimpan + perbandingan teks:

1. Untuk tiap chunk A, ambil beberapa kandidat B dengan cosine tertinggi.
2. Kemiripan teks (difflib atas kata, tanpa frasa baku "Huruf a Cukup
   jelas.") terhadap kandidat itu:
   - >= IDENTICAL_RATIO → "identik"
   - >= CHANGED_RATIO   → "berubah" (beserta diff kata); rasio di bawah
     STRONG_CHANGED_RATIO juga harus didukung cosine >= SEMANTIC_THRESHOLD
     (kalimat baku seperti "mulai berlaku pada tanggal…" mirip di semua regulasi)
3. Kalau rumusannya berbeda jauh tapi cosine >= SEMANTIC_THRESHOLD dan
   pasangan itu saling-terdekat (atau cosine >= STRONG_SEMANTIC) → "padanan"
   (topik sama, rumusan beda) — skor ditampilkan, auditor yang menilai.
4. Sisanya "hanya_a" (dengan kandidat terdekat sebagai petunjuk); chunk B
   yang tidak dekat dengan chunk A mana pun → "hanya_b".

Kalibrasi ambang (data/lancedb, 6 regulasi, Gemini 768-dim): cosine antar
regulasi yang tak berhubungan menumpuk di ~0.78; pada >= 0.85 hampir nol
(0–1%) yang lolos, sementara PBI→PADG pelaksananya masih 74%. Syarat
saling-terdekat membuang sebagian besar padanan keliru di rentang 0.85–0.88.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

import numpy as np

from app.prompts.compliance_review_prompt import format_regulation_ref
from app.services.regulation_db import load_regulation_rows

IDENTICAL_RATIO = 0.95
CHANGED_RATIO = 0.6
STRONG_CHANGED_RATIO = 0.8
SEMANTIC_THRESHOLD = 0.85
STRONG_SEMANTIC = 0.88
NEAREST_HINT = 0.8
CANDIDATES = 3
# Diff kata dibatasi supaya respons tetap ringan untuk chunk yang sangat panjang.
_MAX_DIFF_TOKENS = 1500

STATUSES = ("identik", "berubah", "padanan", "hanya_a", "hanya_b")


class CompareError(Exception):
    """Regulasi tidak bisa dibandingkan (mis. belum ada chunk)."""


def _tokens(text: str) -> list[str]:
    return (text or "").split()


# "Huruf a Cukup jelas." / "Ayat (2) Cukup jelas." / "TAMBAHAN LEMBARAN NEGARA
# REPUBLIK INDONESIA NOMOR …" — sama di setiap regulasi.
_BOILERPLATE_RE = re.compile(
    r"\b(?:(?:huruf\s+\w+|ayat\s*\(\w+\)|angka\s+\w+|pasal\s+\w+)\s+)?cukup\s+jelas\.?"
    r"|\btambahan\s+lembaran\s+negara\s+republik\s+indonesia(?:\s+nomor)?",
    re.IGNORECASE,
)
_MIN_CONTENT_TOKENS = 4


def _norm_tokens(text: str) -> list[str]:
    return re.findall(r"\w+", _BOILERPLATE_RE.sub(" ", text or "").lower())


def text_ratio(a: str, b: str) -> float:
    """
    Kemiripan rumusan 0..1 (abaikan huruf besar/kecil, tanda baca, dan frasa
    baku "Cukup jelas"). Teks yang isinya hampir hanya frasa baku → 0.
    """
    ta, tb = _norm_tokens(a), _norm_tokens(b)
    if len(ta) < _MIN_CONTENT_TOKENS or len(tb) < _MIN_CONTENT_TOKENS:
        return 1.0 if ta == tb and ta else 0.0
    matcher = SequenceMatcher(None, ta, tb, autojunk=False)
    if matcher.real_quick_ratio() < CHANGED_RATIO or matcher.quick_ratio() < CHANGED_RATIO:
        return matcher.quick_ratio()
    return matcher.ratio()


def word_diff(a: str, b: str) -> list[dict]:
    """
    Diff per kata A → B: [{op: "eq"|"del"|"ins", text}]. Perbandingan
    mengabaikan huruf besar/kecil; teks yang ditampilkan tetap teks asli.
    """
    ta, tb = _tokens(a)[:_MAX_DIFF_TOKENS], _tokens(b)[:_MAX_DIFF_TOKENS]
    matcher = SequenceMatcher(None, [t.lower() for t in ta], [t.lower() for t in tb], autojunk=False)
    out: list[dict] = []

    def push(op: str, words: list[str]) -> None:
        if not words:
            return
        if out and out[-1]["op"] == op:
            out[-1]["text"] += " " + " ".join(words)
        else:
            out.append({"op": op, "text": " ".join(words)})

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            push("eq", tb[j1:j2])
        else:
            push("del", ta[i1:i2])
            push("ins", tb[j1:j2])
    return out


def _unit_vectors(rows: list[dict]) -> np.ndarray:
    mat = np.asarray([r["vector"] for r in rows], dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def _chunk_view(row: dict) -> dict:
    meta = {k: row.get(k) for k in ("lampiran", "bab", "bagian", "pasal", "ayat", "page_start")}
    return {
        "id": row.get("id", ""),
        "chunk_index": int(row.get("chunk_index") or 0),
        "reference": format_regulation_ref(meta) or f"Bagian {int(row.get('chunk_index') or 0) + 1}",
        "page_start": int(row.get("page_start") or 0) or None,
        "text": row.get("text", "") or "",
    }


def compare_regulations(regulation_a: dict, regulation_b: dict) -> dict:
    """Bandingkan dua regulasi (dict registry: id, name). Lihat docstring modul."""
    rows_a = [r for r in load_regulation_rows(regulation_a["id"]) if (r.get("text") or "").strip()]
    rows_b = [r for r in load_regulation_rows(regulation_b["id"]) if (r.get("text") or "").strip()]
    for reg, rows in ((regulation_a, rows_a), (regulation_b, rows_b)):
        if not rows:
            raise CompareError(f"Regulasi '{reg.get('name')}' belum memiliki isi yang ter-index.")

    sim = _unit_vectors(rows_a) @ _unit_vectors(rows_b).T
    k = min(CANDIDATES, len(rows_b))
    top_b = np.argsort(-sim, axis=1)[:, :k]
    best_a_for_b = sim.argmax(axis=0)

    items: list[dict] = []
    covered_b: set[int] = set()
    for i, row_a in enumerate(rows_a):
        best_j, best_ratio = int(top_b[i, 0]), -1.0
        for j in top_b[i]:
            ratio = text_ratio(row_a["text"], rows_b[int(j)]["text"])
            if ratio > best_ratio:
                best_j, best_ratio = int(j), ratio

        text_match = best_ratio >= STRONG_CHANGED_RATIO or (
            best_ratio >= CHANGED_RATIO and sim[i, best_j] >= SEMANTIC_THRESHOLD
        )
        if text_match:
            j = best_j
            status = "identik" if best_ratio >= IDENTICAL_RATIO else "berubah"
        else:
            j = int(top_b[i, 0])
            cos = sim[i, j]
            mutual = int(best_a_for_b[j]) == i
            status = "padanan" if cos >= STRONG_SEMANTIC or (cos >= SEMANTIC_THRESHOLD and mutual) else "hanya_a"

        item = {
            "status": status,
            "a": _chunk_view(row_a),
            "b": None,
            "nearest": None,
            "similarity": round(float(sim[i, j]), 3),
            "text_ratio": round(best_ratio, 3) if text_match else None,
            "diff": [],
        }
        if status == "hanya_a":
            if sim[i, j] >= NEAREST_HINT:
                item["nearest"] = _chunk_view(rows_b[j])
        else:
            covered_b.add(j)
            item["b"] = _chunk_view(rows_b[j])
        if text_match and best_ratio < 1.0:
            item["diff"] = word_diff(row_a["text"], rows_b[j]["text"])
        items.append(item)

    # Chunk B yang tidak dipasangkan dan tidak dekat dengan chunk A mana pun.
    best_sim_for_b = sim.max(axis=0)
    for j, row_b in enumerate(rows_b):
        if j in covered_b or best_sim_for_b[j] >= SEMANTIC_THRESHOLD:
            continue
        items.append({
            "status": "hanya_b",
            "a": None,
            "b": _chunk_view(row_b),
            "nearest": None,
            "similarity": round(float(best_sim_for_b[j]), 3),
            "text_ratio": None,
            "diff": [],
        })

    summary = {s: 0 for s in STATUSES}
    for item in items:
        summary[item["status"]] += 1

    return {
        "regulation_a": {"id": regulation_a["id"], "name": regulation_a.get("name", ""), "total_chunks": len(rows_a)},
        "regulation_b": {"id": regulation_b["id"], "name": regulation_b.get("name", ""), "total_chunks": len(rows_b)},
        "summary": summary,
        "thresholds": {
            "identical_ratio": IDENTICAL_RATIO,
            "changed_ratio": CHANGED_RATIO,
            "semantic": SEMANTIC_THRESHOLD,
            "strong_semantic": STRONG_SEMANTIC,
        },
        "items": items,
    }
