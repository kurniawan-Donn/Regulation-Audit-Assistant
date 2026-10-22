"""
Peluncur sekali klik (scripts/launch.py): deteksi port, instal ulang hanya
bila requirements berubah, dan penyiapan .env.
"""

import socket

import pytest

from scripts import launch


def test_port_yang_dipakai_dilewati():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        busy = server.getsockname()[1]
        assert launch.port_free("127.0.0.1", busy) is False
        picked = launch.pick_port("127.0.0.1", busy, attempts=10)
        assert picked != busy and busy < picked < busy + 10


def test_tidak_ada_port_kosong(monkeypatch):
    monkeypatch.setattr(launch, "port_free", lambda host, port: False)
    with pytest.raises(SystemExit):
        launch.pick_port("127.0.0.1", 8000, attempts=3)


def test_instal_hanya_saat_requirements_berubah(tmp_path, monkeypatch):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi==0.115.0\n", encoding="utf-8")
    stamp = tmp_path / ".requirements.sha256"
    monkeypatch.setattr(launch, "REQUIREMENTS", req)
    monkeypatch.setattr(launch, "STAMP", stamp)

    assert launch.needs_install() is True                 # belum pernah dipasang
    stamp.write_text(launch.requirements_hash(), encoding="utf-8")
    assert launch.needs_install() is False                 # tidak berubah → lewati pip
    req.write_text("fastapi==0.115.0\npython-docx==1.2.0\n", encoding="utf-8")
    assert launch.needs_install() is True                  # paket baru → pasang


def test_env_dibuat_dari_contoh_tanpa_menimpa(tmp_path, monkeypatch):
    example = tmp_path / ".env.example"
    env = tmp_path / ".env"
    example.write_text('HOST=127.0.0.1\nPORT=8123  # komentar\nAPP_NAME="Audit"\n', encoding="utf-8")
    monkeypatch.setattr(launch, "ENV_EXAMPLE", example)
    monkeypatch.setattr(launch, "ENV_FILE", env)

    assert launch.ensure_env_file() is True
    assert launch.read_env_value("PORT") == "8123"
    assert launch.read_env_value("APP_NAME") == "Audit"
    assert launch.read_env_value("TIDAK_ADA") == ""

    env.write_text("PORT=9000\n", encoding="utf-8")
    assert launch.ensure_env_file() is False                # .env yang ada tidak ditimpa
    assert launch.read_env_value("PORT") == "9000"
