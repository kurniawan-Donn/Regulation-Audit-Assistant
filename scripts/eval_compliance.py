"""
Evaluasi akurasi Compliance Review terhadap set uji berlabel.

Set uji: scripts/compliance_eval/ (kontrak 16 klausul + label status per
klausul terhadap POJK 11/2022). Menjalankan pipeline asli (mode database:
retrieval Regulation DB -> Gemini -> validasi) lewat API, lalu melaporkan:

- akurasi ketat   : status = label utama
- akurasi longgar : status termasuk 'acceptable' (klausul abu-abu)
- critical miss   : label TIDAK PATUH tetapi dinilai PATUH / TIDAK RELEVAN
                    (ketidakpatuhan yang lolos — kesalahan paling berbahaya)
- false alarm     : label PATUH tetapi dinilai TIDAK PATUH
- sitasi benar    : rujukan regulasi memuat pasal yang diharapkan
- perlu verifikasi: jawaban yang tidak lolos validasi sistem

Laporan disimpan di cache/eval_reports/ dan dibandingkan dengan laporan
sebelumnya, supaya efek perubahan prompt/model/parser terlihat sebagai angka.

Cara pakai:
    python -m scripts.eval_compliance                  # jalankan (memanggil Gemini)
    python -m scripts.eval_compliance --result-id ID   # nilai hasil yang sudah ada (gratis)
    python -m scripts.eval_compliance --min-lenient 0.8 --max-critical 0   # gerbang mutu
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).with_name("compliance_eval")
EXPECTED_FILE = EVAL_DIR / "expected.json"
REPORT_DIR = Path("cache/eval_reports")

STATUSES = ["PATUH", "PATUH DENGAN CATATAN", "TIDAK PATUH", "TIDAK RELEVAN", "PERLU VERIFIKASI"]
MISSED_NONCOMPLIANCE = {"PATUH", "TIDAK RELEVAN"}


# =============================================================================
# PENILAIAN (murni — tanpa AI, dipakai juga oleh test)
# =============================================================================

def _norm_ref(ref: str) -> str:
    return re.sub(r"\s+", " ", (ref or "").strip()).lower()


def _cites(regulasi_ref: str, pasal_list: list[str]) -> bool:
    """'Pasal 3' tidak boleh cocok dengan 'Pasal 30'."""
    return any(re.search(rf"\b{re.escape(p)}\b", regulasi_ref or "", re.IGNORECASE) for p in pasal_list)


def score(result: dict, cases: list[dict]) -> dict:
    items_by_ref: dict[str, list[dict]] = {}
    for item in result.get("items") or []:
        items_by_ref.setdefault(_norm_ref(item.get("klausul_ref", "")), []).append(item)

    rows = []
    confusion: dict[str, dict[str, int]] = {}
    for case in cases:
        matches = items_by_ref.get(_norm_ref(case["clause"]), [])
        item = matches[0] if matches else None
        predicted = (item.get("status") or "").upper() if item else "TIDAK DINILAI"
        expected = case["expected"]
        acceptable = set(case.get("acceptable") or [expected])
        regulasi_ref = item.get("regulasi_ref", "") if item else ""
        row = {
            "clause": case["clause"],
            "expected": expected,
            "predicted": predicted,
            "ok_strict": predicted == expected,
            "ok_lenient": predicted in acceptable,
            "critical_miss": expected == "TIDAK PATUH" and predicted in MISSED_NONCOMPLIANCE,
            "false_alarm": expected == "PATUH" and predicted == "TIDAK PATUH",
            "citation_ok": _cites(regulasi_ref, case["pasal"]) if case.get("pasal") and item else None,
            "regulasi_ref": regulasi_ref,
            "needs_review": bool(item and item.get("needs_review")),
            "analisis": (item.get("analisis") or "")[:400] if item else "",
        }
        rows.append(row)
        confusion.setdefault(expected, {}).setdefault(predicted, 0)
        confusion[expected][predicted] += 1

    n = len(rows)
    cited = [r for r in rows if r["citation_ok"] is not None]
    metrics = {
        "n": n,
        "strict_accuracy": round(sum(r["ok_strict"] for r in rows) / n, 3) if n else 0.0,
        "lenient_accuracy": round(sum(r["ok_lenient"] for r in rows) / n, 3) if n else 0.0,
        "critical_miss": sum(r["critical_miss"] for r in rows),
        "false_alarm": sum(r["false_alarm"] for r in rows),
        "citation_accuracy": round(sum(r["citation_ok"] for r in cited) / len(cited), 3) if cited else None,
        "perlu_verifikasi": sum(r["predicted"] == "PERLU VERIFIKASI" for r in rows),
        "not_assessed": sum(r["predicted"] == "TIDAK DINILAI" for r in rows),
        "needs_review": sum(r["needs_review"] for r in rows),
    }
    return {"metrics": metrics, "confusion": confusion, "cases": rows}


# =============================================================================
# MENJALANKAN PIPELINE ASLI
# =============================================================================

def _run_review(client, regulation_id: str, top_k: int | None) -> dict:
    contract_path = EVAL_DIR / json.loads(EXPECTED_FILE.read_text(encoding="utf-8"))["contract_file"]
    data = {"regulation_ids": regulation_id, "nama_kontrak": "Set uji Compliance Review"}
    if top_k:
        data["top_k_per_clause"] = str(top_k)
    with open(contract_path, "rb") as f:
        res = client.post(
            "/api/compliance/analyze-from-db",
            files={"contract_file": (contract_path.name, f, "text/plain")},
            data=data,
        )
    if res.status_code != 202:
        raise SystemExit(f"Gagal memulai review: {res.status_code} {res.text}")
    job_id = res.json()["job_id"]
    last_message = None
    while True:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            break
        if job.get("message") != last_message:
            last_message = job.get("message")
            print(f"  {job.get('progress_done', 0)}/{job.get('progress_total', 0)} {last_message or ''}")
        time.sleep(2)
    if job["status"] != "succeeded":
        raise SystemExit(f"Review gagal: {job.get('error') or job['status']}")
    return client.get(f"/api/compliance/{job['result_id']}").json()


def _previous_report() -> dict | None:
    reports = sorted(REPORT_DIR.glob("compliance_*.json"))
    return json.loads(reports[-1].read_text(encoding="utf-8")) if reports else None


def _print_report(report: dict, previous: dict | None) -> None:
    m = report["metrics"]
    print(f"\nModel: {report['model']}  ·  Regulasi: {report['regulation']}  ·  {m['n']} klausul")
    print(f"{'Klausul':<10} {'Label':<22} {'Hasil AI':<22} {'':<3} Sitasi")
    for r in report["cases"]:
        mark = "✓" if r["ok_strict"] else ("≈" if r["ok_lenient"] else "✗")
        if r["critical_miss"]:
            mark = "!!"
        cite = {True: "✓", False: "✗", None: "-"}[r["citation_ok"]]
        print(f"{r['clause']:<10} {r['expected']:<22} {r['predicted']:<22} {mark:<3} {cite}")

    def fmt(key, value):
        if value is None:
            return "-"
        return f"{value:.0%}" if isinstance(value, float) else str(value)

    print("\nMetrik" + (" (Δ vs laporan sebelumnya)" if previous else ""))
    labels = {
        "strict_accuracy": "Akurasi ketat",
        "lenient_accuracy": "Akurasi longgar",
        "critical_miss": "Critical miss",
        "false_alarm": "False alarm",
        "citation_accuracy": "Sitasi benar",
        "perlu_verifikasi": "Perlu verifikasi",
        "not_assessed": "Tidak dinilai",
    }
    for key, label in labels.items():
        line = f"  {label:<18} {fmt(key, m[key])}"
        prev = (previous or {}).get("metrics", {}).get(key)
        if previous and prev is not None and m[key] is not None and prev != m[key]:
            delta = m[key] - prev
            line += f"   ({'+' if delta > 0 else ''}{delta:.0%})" if isinstance(m[key], float) else f"   ({'+' if delta > 0 else ''}{delta})"
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--result-id", help="Nilai hasil Compliance Review yang sudah ada (tanpa memanggil AI).")
    parser.add_argument("--top-k", type=int, help="Jumlah kutipan regulasi per klausul (default aplikasi).")
    parser.add_argument("--keep", action="store_true", help="Jangan hapus hasil review dari Riwayat setelah dinilai.")
    parser.add_argument("--min-lenient", type=float, help="Gagal (exit 1) bila akurasi longgar di bawah nilai ini.")
    parser.add_argument("--max-critical", type=int, help="Gagal (exit 1) bila critical miss melebihi nilai ini.")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.regulation_db import list_regulations
    from app.services.result_history import delete_result
    from app.services.runtime_settings import get_effective_settings

    spec = json.loads(EXPECTED_FILE.read_text(encoding="utf-8"))
    regulation = next(
        (r for r in list_regulations() if r["name"].startswith(spec["regulation_name_prefix"])), None,
    )
    if regulation is None:
        print(f"Regulasi '{spec['regulation_name_prefix']}…' tidak ada di Regulation DB.", file=sys.stderr)
        return 2

    started = time.time()
    with TestClient(app, headers={"X-Requested-With": "RAA"}) as client:
        if args.result_id:
            res = client.get(f"/api/compliance/{args.result_id}")
            if res.status_code != 200:
                print(f"Hasil {args.result_id} tidak ditemukan.", file=sys.stderr)
                return 2
            result = res.json()
        else:
            print(f"Menjalankan Compliance Review set uji terhadap {regulation['name']} …")
            result = _run_review(client, regulation["id"], args.top_k)

    scored = score(result, spec["cases"])
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": get_effective_settings().get("gemini_model", ""),
        "regulation": regulation["name"],
        "result_id": result.get("result_id", ""),
        "duration_s": round(time.time() - started, 1),
        "label_status": spec.get("label_status", ""),
        **scored,
    }

    previous = _previous_report()
    _print_report(report, previous)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = REPORT_DIR / f"compliance_{stamp}.json"
    out.write_text(json.dumps({**report, "raw_result": result}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nLaporan: {out}")

    if not args.result_id and not args.keep and result.get("result_id"):
        delete_result("compliance_review", result["result_id"])   # jangan mengotori Riwayat pengguna

    m = scored["metrics"]
    failed = (
        (args.min_lenient is not None and m["lenient_accuracy"] < args.min_lenient)
        or (args.max_critical is not None and m["critical_miss"] > args.max_critical)
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
