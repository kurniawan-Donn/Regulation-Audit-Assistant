"""
Peluncur sekali klik (dipanggil start.bat / start.sh dengan Python dari venv).

1. Pasang/perbarui dependensi bila requirements.txt berubah sejak terakhir.
2. Buat .env dari .env.example bila belum ada.
3. Pilih port bebas (mulai dari PORT di .env, default 8000).
4. Jalankan server (`python -m app`), tunggu /health, buka browser.
5. Tetap berjalan sampai jendela ditutup / Ctrl+C.

    python -m scripts.launch [--no-browser] [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = Path(sys.prefix) / ".requirements.sha256"     # di dalam venv yang sedang dipakai
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
DEFAULT_PORT = 8000
HEALTH_TIMEOUT_S = 90


def say(message: str) -> None:
    print(f"[Audit Assistant] {message}", flush=True)


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def needs_install() -> bool:
    return not STAMP.exists() or STAMP.read_text(encoding="utf-8").strip() != requirements_hash()


def install_requirements() -> None:
    say("Memasang paket yang dibutuhkan (hanya saat pertama kali / ada pembaruan)...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(REQUIREMENTS)],
        check=True,
    )
    STAMP.write_text(requirements_hash(), encoding="utf-8")


def ensure_env_file() -> bool:
    """Salin .env.example -> .env bila belum ada. True kalau baru dibuat."""
    if ENV_FILE.exists() or not ENV_EXAMPLE.exists():
        return False
    shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
    return True


def read_env_value(key: str) -> str:
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].split("#", 1)[0].strip().strip('"').strip("'")
    return ""


def port_free(host: str, port: int) -> bool:
    """
    Port dianggap terpakai bila ada yang menjawab koneksi ATAU bind gagal.
    Tanpa SO_REUSEADDR: di Windows opsi itu membolehkan bind ke port yang sedang
    dipakai, sehingga server kedua gagal start padahal port dianggap kosong.
    """
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex((probe_host, port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(host: str, preferred: int, attempts: int = 20) -> int:
    for port in range(preferred, preferred + attempts):
        if port_free(host, port):
            return port
    raise SystemExit(f"Tidak ada port kosong di {preferred}-{preferred + attempts - 1}.")


def wait_healthy(url: str, proc: subprocess.Popen, timeout: float = HEALTH_TIMEOUT_S) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as res:
                if res.status == 200:
                    # Pastikan yang menjawab memang server kita, bukan proses lain di
                    # port yang sama: proses kita harus tetap hidup sesaat kemudian.
                    time.sleep(1.0)
                    return proc.poll() is None
        except OSError:
            time.sleep(0.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Jalankan Audit Assistant.")
    parser.add_argument("--no-browser", action="store_true", help="Jangan buka browser otomatis.")
    parser.add_argument("--check", action="store_true", help="Hanya siapkan (paket & .env), tanpa menjalankan server.")
    args = parser.parse_args()
    os.chdir(ROOT)

    if sys.version_info < (3, 11):
        say(f"Butuh Python 3.11 atau lebih baru (terpasang: {sys.version.split()[0]}). "
            "Hapus folder venv, pasang Python terbaru dari https://www.python.org/downloads/, lalu jalankan lagi.")
        return 1

    if needs_install():
        install_requirements()
    if ensure_env_file():
        say("File pengaturan .env dibuat dari .env.example.")
    if args.check:
        say("Siap dijalankan.")
        return 0

    host = read_env_value("HOST") or "127.0.0.1"
    try:
        preferred = int(read_env_value("PORT") or DEFAULT_PORT)
    except ValueError:
        preferred = DEFAULT_PORT
    bind_host = "127.0.0.1" if host in ("localhost", "") else host
    port = pick_port(bind_host, preferred)
    if port != preferred:
        say(f"Port {preferred} sedang dipakai - memakai port {port}.")

    url = f"http://{'localhost' if bind_host in ('127.0.0.1', '0.0.0.0') else bind_host}:{port}"
    # DEBUG=true di .env hanya menyalakan auto-reload untuk pengembang; peluncur
    # untuk pemakai menjalankan server biasa (variabel lingkungan menang atas .env).
    env = {**os.environ, "PORT": str(port), "DEBUG": "false", "PYTHONUNBUFFERED": "1"}
    say(f"Menjalankan server di {url} ...")
    proc = subprocess.Popen([sys.executable, "-m", "app"], cwd=ROOT, env=env)
    try:
        if not wait_healthy(url, proc):
            say("Server gagal dijalankan - lihat pesan di atas.")
            proc.terminate()
            return proc.wait() or 1
        say(f"Siap! Buka {url} di browser. Tutup jendela ini (atau Ctrl+C) untuk berhenti.")
        if not args.no_browser:
            webbrowser.open(url)
        return proc.wait()
    except KeyboardInterrupt:
        say("Menghentikan server...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
