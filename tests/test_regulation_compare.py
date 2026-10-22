"""
Bandingkan Regulasi: klasifikasi identik / berubah / padanan / hanya_a /
hanya_b. Vektor disusun manual (cosine diketahui); LanceDB asli di direktori
sementara (fixture `client` menjalankan app di tmp cwd).
"""

import numpy as np
import pytest

from app.services.regulation_compare import text_ratio, word_diff

DIM = 768

T_DEFINISI = ("Dalam Peraturan ini yang dimaksud dengan Sistem Informasi adalah keterpaduan "
              "antara komponen teknologi informasi yang dipergunakan untuk mengelola data.")
T_EVALUASI_A = ("Penyelenggara melakukan evaluasi secara berkala terhadap rencana strategis "
                "keamanan siber paling sedikit 1 (satu) kali dalam 1 (satu) tahun.")
T_EVALUASI_B = ("Penyelenggara wajib melakukan evaluasi secara berkala terhadap rencana strategis "
                "keamanan siber paling sedikit 2 (dua) kali dalam 1 (satu) tahun.")
T_AUDIT_A = "Penyelenggara melakukan audit keamanan siber secara independen oleh auditor internal maupun eksternal."
T_AUDIT_B = "Audit dilaksanakan oleh pihak independen yang kompeten terhadap pengamanan sistem."
T_SANKSI = "Pelanggaran atas ketentuan ini dikenakan sanksi administratif berupa teguran tertulis."
T_SIMULASI = "Bank menyusun skenario simulasi gangguan layanan untuk menguji kesiapan tim tanggap insiden."
T_DATA = "Penyelenggara menyampaikan laporan data insiden kepada otoritas melalui sistem pelaporan daring."


def _e(i: int) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def _mix(base: np.ndarray, cos: float, other: int) -> list[float]:
    """Vektor satuan dengan cosine `cos` terhadap `base` (satuan, tegak lurus e_other)."""
    return (base * cos + _e(other) * np.sqrt(1 - cos ** 2)).tolist()


@pytest.fixture
def compare_db(client):
    from app.services import regulation_db

    regulation_db._db = None  # koneksi baru di cwd sementara
    b_audit = np.array(_mix(_e(2), 0.9, 5), dtype=np.float32)
    reg_a = regulation_db.add_regulation(
        name="Lama 1/2020", filename="lama.txt",
        chunks=[
            {"pasal": "Pasal 1", "text": T_DEFINISI},
            {"pasal": "Pasal 2", "text": T_EVALUASI_A},
            {"pasal": "Pasal 3", "text": T_AUDIT_A},
            {"pasal": "Pasal 4", "text": T_SANKSI},
            {"pasal": "Pasal 5", "text": T_SIMULASI},
        ],
        embeddings=[
            _e(0).tolist(), _e(1).tolist(), _e(2).tolist(), _e(3).tolist(),
            # cosine 0.86 ke B Pasal 3, tapi B Pasal 3 lebih dekat ke A Pasal 3 (0.9):
            # bukan pasangan saling-terdekat → tidak dianggap padanan.
            _mix(b_audit, 0.86, 7),
        ],
    )
    reg_b = regulation_db.add_regulation(
        name="Baru 2/2024", filename="baru.txt",
        chunks=[
            {"pasal": "Pasal 1", "text": T_DEFINISI},
            {"pasal": "Pasal 2", "text": T_EVALUASI_B},
            {"pasal": "Pasal 3", "text": T_AUDIT_B},
            {"pasal": "Pasal 9", "text": T_DATA},
        ],
        embeddings=[_e(0).tolist(), _e(1).tolist(), b_audit.tolist(), _e(6).tolist()],
    )
    yield client, reg_a, reg_b
    regulation_db._db = None


def _compare(client, a, b):
    return client.post("/api/regulation-db/compare", json={"regulation_a": a, "regulation_b": b})


def test_klasifikasi_perbandingan(compare_db):
    client, reg_a, reg_b = compare_db
    res = _compare(client, reg_a["id"], reg_b["id"])
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["summary"] == {"identik": 1, "berubah": 1, "padanan": 1, "hanya_a": 2, "hanya_b": 1}
    by_ref = {(i["a"] or {}).get("reference") or "B:" + i["b"]["reference"]: i for i in data["items"]}

    assert by_ref["Pasal 1"]["status"] == "identik"
    assert by_ref["Pasal 1"]["text_ratio"] == 1.0 and by_ref["Pasal 1"]["diff"] == []

    berubah = by_ref["Pasal 2"]
    assert berubah["status"] == "berubah" and berubah["b"]["reference"] == "Pasal 2"
    dels = " ".join(s["text"] for s in berubah["diff"] if s["op"] == "del")
    ins = " ".join(s["text"] for s in berubah["diff"] if s["op"] == "ins")
    assert "1 (satu) kali" in dels or "(satu)" in dels
    assert "wajib" in ins and "(dua)" in ins

    padanan = by_ref["Pasal 3"]
    assert padanan["status"] == "padanan" and padanan["b"]["reference"] == "Pasal 3"
    assert padanan["similarity"] == pytest.approx(0.9, abs=1e-3)
    assert padanan["text_ratio"] is None

    assert by_ref["Pasal 4"]["status"] == "hanya_a" and by_ref["Pasal 4"]["nearest"] is None
    # Cosine 0.86 tapi bukan saling-terdekat → hanya_a, kandidat terdekat sebagai petunjuk.
    tidak_mutual = by_ref["Pasal 5"]
    assert tidak_mutual["status"] == "hanya_a"
    assert tidak_mutual["nearest"]["reference"] == "Pasal 3"

    assert by_ref["B:Pasal 9"]["status"] == "hanya_b" and by_ref["B:Pasal 9"]["a"] is None
    # Urutan: ketentuan A sesuai urutan pasal, lalu yang hanya ada di B.
    assert [i["status"] for i in data["items"]][-1] == "hanya_b"


def test_bandingkan_regulasi_sama_atau_tidak_ada(compare_db):
    client, reg_a, _ = compare_db
    assert _compare(client, reg_a["id"], reg_a["id"]).status_code == 422
    assert _compare(client, reg_a["id"], "tidak-ada").status_code == 404


def test_text_ratio_abaikan_frasa_baku():
    a = "Huruf a Cukup jelas. Huruf b Cukup jelas. Huruf c Kesesuaian rencana TI dengan rencana bisnis."
    b = "Huruf a Cukup jelas. Huruf b Cukup jelas. Huruf c Cukup jelas. Huruf d Cukup jelas."
    assert text_ratio(a, b) == 0.0
    assert text_ratio("Pasal 5 Cukup jelas.", "Cukup jelas.") == 0.0
    assert text_ratio(T_DEFINISI, T_DEFINISI.upper()) == 1.0


def test_word_diff_mempertahankan_teks_asli():
    diff = word_diff("Bank wajib melapor dalam 5 hari.", "Bank wajib segera melapor dalam 3 hari.")
    assert diff == [
        {"op": "eq", "text": "Bank wajib"},
        {"op": "ins", "text": "segera"},
        {"op": "eq", "text": "melapor dalam"},
        {"op": "del", "text": "5"},
        {"op": "ins", "text": "3"},
        {"op": "eq", "text": "hari."},
    ]
