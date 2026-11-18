"""
Statistik Compliance Review (app/services/compliance_stats.py): persentase
status, Tingkat Kepatuhan, rincian per regulasi — dan kesetaraan dengan
perhitungan di browser (static/js/compliance-stats.js).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.compliance_stats import compliance_stats, percentages, regulation_label, score_color

ROOT = Path(__file__).resolve().parent.parent

P, C, T, R, V = "PATUH", "PATUH DENGAN CATATAN", "TIDAK PATUH", "TIDAK RELEVAN", "PERLU VERIFIKASI"


def _item(status, sumber=None, ref=""):
    item = {"status": status, "regulasi_ref": ref}
    if sumber is not None:
        item["regulasi_sumber"] = sumber
    return item


# Hasil 2 regulasi: sebagian baru (regulasi_sumber), sebagian lama (hanya teks rujukan).
SAMPLE_ITEMS = [
    _item(P, ["POJK 11/2022"]),
    _item(P, ["POJK 11/2022", "PADK 1 Tahun 2026"]),
    _item(C, ["PADK 1 Tahun 2026"]),
    _item(C, ref="PADK 1 Tahun 2026 Lampiran I / BAB V (hal. 57)"),
    _item(C, ref="POJK 11/2022 Pasal 20 ayat (3); PADK 1 Tahun 2026 Lampiran II"),
    _item(T, ["POJK 11/2022"]),
    _item(R),
    _item(V, []),
    _item("STATUS ANEH", []),
]
SAMPLE_REGS = ["POJK 11/2022.pdf", "PADK 1 Tahun 2026", "SEOJK 21/2017.txt"]


@pytest.mark.parametrize("counts", [[7, 13, 0, 3, 0], [1, 1, 1], [2, 1, 0, 0, 0], [0, 0, 0], [5], [1, 2, 3, 4, 5]])
def test_persen_bulat_selalu_berjumlah_100(counts):
    pcts = percentages(counts)
    assert sum(pcts) == (100 if sum(counts) else 0)
    assert all(abs(p - c * 100 / max(sum(counts), 1)) < 1 for p, c in zip(pcts, counts))


def test_persen_dari_total_dan_tingkat_kepatuhan():
    s = compliance_stats(SAMPLE_ITEMS, SAMPLE_REGS)
    counts = {x["key"]: (x["count"], x["percent"]) for x in s["statuses"]}
    assert s["total"] == 9
    # 22,2 + 33,3 + 11,1 + 11,1 + 22,2: sisa terbesar (33,3) dibulatkan ke atas -> total 100
    assert counts == {"patuh": (2, 22), "catatan": (3, 34), "tidak_patuh": (1, 11),
                      "tidak_relevan": (1, 11), "verifikasi": (2, 22)}
    # (Patuh + Catatan) / (total - Tidak Relevan) = 5 / 8
    assert (s["compliant"], s["relevant"], s["score"]) == (5, 8, 63)


def test_rincian_per_regulasi_baru_dan_hasil_lama():
    regs = {r["name"]: r for r in compliance_stats(SAMPLE_ITEMS, SAMPLE_REGS)["regulations"]}
    assert list(regs) == ["POJK 11/2022", "PADK 1 Tahun 2026", "SEOJK 21/2017"]   # ekstensi file dibuang
    pojk, padk, seojk = regs.values()
    assert (pojk["referenced"], pojk["share"]) == (4, 44)          # 3 tersimpan + 1 dari teks rujukan
    assert (padk["referenced"], padk["share"]) == (4, 44)
    assert {x["key"]: x["count"] for x in pojk["statuses"]}["tidak_patuh"] == 1
    assert seojk["referenced"] == 0 and seojk["share"] == 0         # tetap tampil walau tidak dirujuk


def test_klausul_tanpa_rujukan_dihitung_terpisah():
    s = compliance_stats(SAMPLE_ITEMS, SAMPLE_REGS)
    assert s["unattributed"] == 2           # dua Perlu Verifikasi tanpa rujukan; Tidak Relevan tidak dihitung


def test_satu_regulasi_dan_regulasi_di_luar_daftar():
    s = compliance_stats([_item(P, ["POJK 11/2022"]), _item(T, ["SEOJK 29"])], ["POJK 11/2022"])
    assert [r["name"] for r in s["regulations"]] == ["POJK 11/2022", "SEOJK 29"]
    assert compliance_stats([_item(P, ["A"])], ["A"])["regulations"][0]["share"] == 100


def test_kosong_dan_semua_tidak_relevan():
    assert compliance_stats([], [])["score"] is None
    s = compliance_stats([_item(R), _item(R)], [])
    assert s["score"] is None and s["relevant"] == 0 and s["regulations"] == []


def test_label_dan_warna_skor():
    assert regulation_label("POJK 11 - 03 - 2022.pdf") == "POJK 11 - 03 - 2022"
    assert regulation_label("POJK 11/2022") == "POJK 11/2022"       # bukan nama file -> utuh
    assert score_color(85) != score_color(60) != score_color(20)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js tidak tersedia")
def test_perhitungan_browser_identik_dengan_server(tmp_path):
    module = tmp_path / "compliance-stats.mjs"
    module.write_text((ROOT / "static" / "js" / "compliance-stats.js").read_text(encoding="utf-8"), encoding="utf-8")
    cases = [
        (SAMPLE_ITEMS, SAMPLE_REGS),
        ([_item(R), _item(R)], []),
        ([], ["X"]),
        ([_item(P, ["A"])] * 3 + [_item(C, ["B"])] * 3 + [_item(T, ["A", "B"])], ["A.txt", "B"]),
    ]
    script = (
        f"const m = await import({json.dumps(module.as_uri())});"
        f"const cases = {json.dumps(cases)};"
        "console.log(JSON.stringify(cases.map(([items, regs]) => m.complianceStats(items, regs))));"
    )
    out = subprocess.run(["node", "--input-type=module", "-e", script],
                         capture_output=True, text=True, check=True, timeout=60)
    from_js = json.loads(out.stdout)
    from_py = [compliance_stats(items, regs) for items, regs in cases]
    assert from_js == json.loads(json.dumps(from_py))
