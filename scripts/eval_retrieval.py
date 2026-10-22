"""
Evaluasi kualitas retrieval Regulation DB.

Menjalankan set query (scripts/retrieval_eval_set.json) terhadap SELURUH
regulasi di database dan melaporkan hit@K serta MRR@10 untuk dua kriteria:
- ketat  : label rujukan chunk benar (pasal / judul bagian) — yang dipakai
           sebagai kutipan di Compliance Review;
- longgar: isi chunk relevan (memuat frasa kunci "evidence").

Cara pakai:
    python -m scripts.eval_retrieval [--mode vector|hybrid] [--k 5] [--db-dir data/lancedb]

Embedding query di-cache di cache/eval_query_embeddings.json supaya
perbandingan antar-index memakai vektor query yang identik (dan tidak
memanggil API berulang).
"""

import argparse
import json
import sys
from pathlib import Path

EVAL_SET = Path(__file__).with_name("retrieval_eval_set.json")
QUERY_CACHE = Path("cache/eval_query_embeddings.json")


def _query_embeddings(queries: list[str]) -> list[list[float]]:
    from app.config import settings
    from app.services.embedding_service import EmbeddingService

    cache = {}
    if QUERY_CACHE.exists():
        cache = json.loads(QUERY_CACHE.read_text(encoding="utf-8"))
    key = settings.gemini_embedding_model
    missing = [q for q in queries if f"{key}|{q}" not in cache]
    if missing:
        vectors = EmbeddingService().embed_batch(missing, task_type="RETRIEVAL_QUERY")
        for q, v in zip(missing, vectors):
            cache[f"{key}|{q}"] = [round(float(x), 7) for x in v]
        QUERY_CACHE.parent.mkdir(parents=True, exist_ok=True)
        QUERY_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return [cache[f"{key}|{q}"] for q in queries]


def _is_hit(case: dict, meta: dict) -> bool:
    """Kriteria ketat: regulasi benar DAN label pasal/judul bagian benar."""
    if case["regulation"].lower() not in (meta.get("regulation_name") or "").lower():
        return False
    pasal = (meta.get("pasal") or "").strip()
    if pasal and pasal in case.get("pasal", []):
        return True
    labels = " ".join(meta.get(k) or "" for k in ("pasal", "bagian", "bab")).lower()
    return any(h.lower() in labels for h in case.get("heading", []))


def _is_content_hit(case: dict, result: dict) -> bool:
    """Kriteria longgar: regulasi benar DAN teks chunk memuat frasa kunci."""
    meta = result["metadata"]
    if case["regulation"].lower() not in (meta.get("regulation_name") or "").lower():
        return False
    text = " ".join((result.get("text") or "").lower().split())
    return any(e in text for e in case.get("evidence", []))


def _rank(results: list[dict], predicate) -> int | None:
    return next((i + 1 for i, r in enumerate(results) if predicate(r)), None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["vector", "hybrid"], default="hybrid")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--db-dir", default="data/lancedb")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.services import regulation_db

    regulation_db.LANCEDB_DIR = Path(args.db_dir)
    regulation_db._db = None

    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))["queries"]
    vectors = _query_embeddings([c["query"] for c in cases])

    stats = {"ketat": [0, 0.0], "longgar": [0, 0.0]}
    for case, vec in zip(cases, vectors):
        results = regulation_db.query_relevant_chunks(
            query_embedding=vec,
            regulation_ids=None,
            top_k=10,
            query_text=case["query"] if args.mode == "hybrid" else None,
        )
        rank = _rank(results, lambda r: _is_hit(case, r["metadata"]))
        content_rank = _rank(results, lambda r: _is_content_hit(case, r))
        for name, rk in (("ketat", rank), ("longgar", content_rank)):
            if rk is not None and rk <= args.k:
                stats[name][0] += 1
            stats[name][1] += 1.0 / rk if rk else 0.0
        if args.verbose or rank is None or rank > args.k:
            top = results[0]["metadata"] if results else {}
            print(
                f"  {'HIT ' if rank and rank <= args.k else 'MISS'} {case['id']:<26} "
                f"rank={rank or '-':<3} isi={content_rank or '-':<3} "
                f"top1={top.get('regulation_name', '')} "
                f"{top.get('pasal', '') or top.get('bab', '')}"
            )

    n = len(cases)
    print(f"mode={args.mode} db={args.db_dir} n={n}")
    for name, (hits, rr) in stats.items():
        print(f"  {name:<8} hit@{args.k}={hits}/{n} ({hits / n:.0%})  MRR@10={rr / n:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
