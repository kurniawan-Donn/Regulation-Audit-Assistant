"""
Set uji & penilaian evaluasi Compliance Review (scripts/eval_compliance.py).
Tanpa AI: penilaian diuji dengan hasil sintetis.
"""

import json
from pathlib import Path

from scripts.eval_compliance import EVAL_DIR, EXPECTED_FILE, STATUSES, score

SPEC = json.loads(EXPECTED_FILE.read_text(encoding="utf-8"))


def _result(statuses: dict[str, tuple[str, str]]) -> dict:
    return {"items": [
        {"klausul_ref": ref, "status": status, "regulasi_ref": reg_ref, "analisis": "…"}
        for ref, (status, reg_ref) in statuses.items()
    ]}


def test_set_uji_konsisten_dengan_kontrak():
    from app.api.compliance_routes import _prepare_contract_units
    from app.services.contract_parser import parse_contract_structure

    text = (EVAL_DIR / SPEC["contract_file"]).read_text(encoding="utf-8")
    units, _ = _prepare_contract_units(parse_contract_structure(text), "")
    refs = {u["klausul_ref"] for u in units}
    clauses = [c["clause"] for c in SPEC["cases"]]
    assert len(clauses) == len(set(clauses)) == 16
    assert set(clauses) <= refs                                  # setiap label punya klausul
    for case in SPEC["cases"]:
        assert case["expected"] in STATUSES
        assert case["expected"] in case["acceptable"]
        assert set(case["acceptable"]) <= set(STATUSES)
        assert case["why"]


def test_penilaian_sempurna():
    perfect = _result({
        c["clause"]: (c["expected"], " ; ".join(f"POJK 11 {p} ayat (3)" for p in c["pasal"]))
        for c in SPEC["cases"]
    })
    m = score(perfect, SPEC["cases"])["metrics"]
    assert m["strict_accuracy"] == m["lenient_accuracy"] == 1.0
    assert m["critical_miss"] == m["false_alarm"] == m["not_assessed"] == 0
    assert m["citation_accuracy"] == 1.0


def test_critical_miss_false_alarm_dan_longgar():
    cases = [
        {"clause": "Pasal 5", "expected": "TIDAK PATUH", "acceptable": ["TIDAK PATUH"], "pasal": ["Pasal 30"]},
        {"clause": "Pasal 2", "expected": "PATUH", "acceptable": ["PATUH"], "pasal": ["Pasal 30"]},
        {"clause": "Pasal 6", "expected": "TIDAK PATUH",
         "acceptable": ["TIDAK PATUH", "PATUH DENGAN CATATAN"], "pasal": ["Pasal 30"]},
        {"clause": "Pasal 9", "expected": "TIDAK RELEVAN", "acceptable": ["TIDAK RELEVAN"], "pasal": []},
    ]
    result = _result({
        "Pasal 5": ("PATUH", "POJK 11 Pasal 3 ayat (1)"),          # lolos ketidakpatuhan + sitasi salah
        "Pasal 2": ("TIDAK PATUH", "POJK 11 Pasal 30 ayat (3)"),   # alarm palsu
        "pasal  6": ("PATUH DENGAN CATATAN", "POJK 11 Pasal 30"),  # cocok walau beda spasi/huruf
    })
    report = score(result, cases)
    m = report["metrics"]
    assert m["strict_accuracy"] == 0.0
    assert m["lenient_accuracy"] == 0.25
    assert m["critical_miss"] == 1 and m["false_alarm"] == 1
    assert m["not_assessed"] == 1                                 # Pasal 9 tidak ada di hasil
    rows = {r["clause"]: r for r in report["cases"]}
    assert rows["Pasal 5"]["citation_ok"] is False                # "Pasal 3" ≠ "Pasal 30"
    assert rows["Pasal 9"]["citation_ok"] is None
    assert report["confusion"]["TIDAK PATUH"] == {"PATUH": 1, "PATUH DENGAN CATATAN": 1}


def test_skrip_bisa_diimpor_sebagai_modul():
    assert Path(EXPECTED_FILE).exists()
