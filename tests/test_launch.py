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


def test_keluaran_server_ke_file_log_bukan_konsol(tmp_path):
    """Server tidak menulis ke jendela konsol: klik di jendela (QuickEdit) tak lagi membekukannya."""
    import os

    log_path = tmp_path / "logs" / "server.log"
    proc = launch.start_server(tmp_path, dict(os.environ), log_path,
                               args=("-c", "print('INFO: GET /api/settings 200'); print('Pasal 30 — ayat (3)')"))
    assert proc.wait(timeout=30) == 0
    proc.log_file.close()
    text = log_path.read_text(encoding="utf-8")
    assert "GET /api/settings 200" in text and "Pasal 30 — ayat (3)" in text
    assert launch.log_tail(log_path, lines=1) == "Pasal 30 — ayat (3)"
    assert launch.log_tail(tmp_path / "tidak-ada.log") == ""


def test_matikan_quickedit_aman_di_luar_konsol():
    # Di pytest stdin bukan jendela konsol: tidak boleh error, cukup False.
    assert launch.disable_quick_edit() in (True, False)


# ---------------------------------------------------------------------------
# Versi paket (Setup.exe / ZIP portable)
# ---------------------------------------------------------------------------
def test_lokasi_data_versi_paket(tmp_path, monkeypatch):
    assert launch.app_home("portable") == launch.ROOT / "userdata"
    monkeypatch.delenv(launch.HOME_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert launch.app_home("installed") == tmp_path / "Audit Assistant"
    monkeypatch.setenv(launch.HOME_ENV, str(tmp_path / "khusus"))
    assert launch.app_home("installed") == tmp_path / "khusus"


def test_pengaturan_dibaca_dari_env_folder_data(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=8456\n", encoding="utf-8")
    assert launch.read_env_value("PORT", env_file) == "8456"
    assert launch.read_env_value("PORT", tmp_path / "tidak-ada.env") == ""


def _serve_json(body: bytes):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_klik_ikon_kedua_kali_membuka_instance_yang_berjalan(tmp_path):
    assert launch.running_instance(tmp_path) is None                  # belum pernah jalan

    server = _serve_json(b'{"status": "ok", "app": "audit-assistant"}')
    try:
        port = server.server_address[1]
        launch.write_instance(tmp_path, port, pid=1234)
        assert launch.running_instance(tmp_path) == f"http://localhost:{port}"
    finally:
        server.shutdown()
        server.server_close()
    assert launch.running_instance(tmp_path) is None                  # sudah mati -> jalankan baru

    launch.clear_instance(tmp_path)
    assert not (tmp_path / launch.INSTANCE_FILE).exists()
    launch.clear_instance(tmp_path)                                   # aman bila tidak ada


def test_port_milik_aplikasi_lain_tidak_dianggap_instance(tmp_path):
    server = _serve_json(b'{"status": "ok"}')
    try:
        launch.write_instance(tmp_path, server.server_address[1], pid=1)
        assert launch.running_instance(tmp_path) is None
    finally:
        server.shutdown()
        server.server_close()
