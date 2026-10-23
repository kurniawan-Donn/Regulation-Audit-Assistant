"""
Demo lewat internet dari laptop ini (dipanggil demo.bat / demo.sh).

1. Siapkan folder demo_workspace/ — salinan Regulation DB, prompt, dan
   pengaturan TANPA API key. Hasil analisis, Daftar Temuan, dan riwayat
   asli TIDAK ikut, sehingga pengunjung tidak melihat/mengubah data kerja.
2. Jalankan server dari folder itu dalam Mode Demo (DEMO_MODE=true) dengan
   password: aksi berisiko dinonaktifkan dan tampil spanduk peringatan.
3. Buat link HTTPS publik dengan Cloudflare Quick Tunnel (cloudflared,
   gratis tanpa akun) lalu tampilkan link + username + password.

    python -m scripts.demo [--reset] [--yes] [--no-browser]

Link berlaku selama jendela ini terbuka (berganti setiap kali dijalankan).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from scripts.launch import (
    ROOT,
    disable_quick_edit,
    install_requirements,
    log_tail,
    needs_install,
    pick_port,
    read_env_value,
    say,
    start_server,
    wait_healthy,
)

DEMO_DIR = ROOT / "demo_workspace"
TOOLS_DIR = ROOT / "tools"
DEMO_USERNAME = "demo"
# Yang disalin ke folder demo: database regulasi & prompt. BUKAN hasil/temuan.
COPY_FROM_DATA = ("lancedb", "regulations.json", "regulation_sources", "prompts.json")
SECRET_SETTINGS = ("gemini_api_key",)
TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # tanpa karakter yang mirip (l/1, o/0)


# =============================================================================
# FOLDER DEMO
# =============================================================================

def prepare_workspace(root: Path, demo_dir: Path, reset: bool = False) -> bool:
    """Buat folder demo dari data asli. True bila baru dibuat."""
    if demo_dir.exists() and not reset:
        return False
    if demo_dir.exists():
        shutil.rmtree(demo_dir)
    (demo_dir / "data").mkdir(parents=True)
    (demo_dir / "outputs").mkdir()
    for name in COPY_FROM_DATA:
        src = root / "data" / name
        if src.is_dir():
            shutil.copytree(src, demo_dir / "data" / name)
        elif src.is_file():
            shutil.copy2(src, demo_dir / "data" / name)
    settings_src = root / "data" / "settings.json"
    if settings_src.is_file():
        try:
            settings = json.loads(settings_src.read_text(encoding="utf-8"))
        except ValueError:
            settings = {}
        for key in SECRET_SETTINGS:
            settings.pop(key, None)
        (demo_dir / "data" / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return True


def demo_api_key(root: Path) -> str:
    """API key demo: DEMO_GEMINI_API_KEY > GEMINI_API_KEY (.env) > yang disimpan di Pengaturan."""
    for name in ("DEMO_GEMINI_API_KEY", "GEMINI_API_KEY"):
        value = os.environ.get(name) or read_env_value(name)
        if value:
            return value
    try:
        return json.loads((root / "data" / "settings.json").read_text(encoding="utf-8")).get("gemini_api_key", "")
    except (OSError, ValueError):
        return ""


def demo_password() -> str:
    """DEMO_PASSWORD dari .env, atau password acak baru setiap sesi."""
    return read_env_value("DEMO_PASSWORD") or "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(10))


# =============================================================================
# CLOUDFLARED
# =============================================================================

def cloudflared_asset() -> str | None:
    """Nama file rilis cloudflared untuk OS ini (None = pasang manual)."""
    system, machine = platform.system(), platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    if system == "Windows":
        return f"cloudflared-windows-{arch}.exe"
    if system == "Linux":
        return f"cloudflared-linux-{arch}"
    return None   # macOS: brew install cloudflared


def find_cloudflared() -> str | None:
    local = TOOLS_DIR / ("cloudflared.exe" if platform.system() == "Windows" else "cloudflared")
    if local.is_file():
        return str(local)
    return shutil.which("cloudflared")


def download_cloudflared(assume_yes: bool) -> str | None:
    asset = cloudflared_asset()
    if asset is None:
        say("cloudflared belum terpasang. Di macOS jalankan: brew install cloudflared")
        return None
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{asset}"
    say("Dibutuhkan cloudflared (alat resmi Cloudflare untuk membuat link publik, +-50 MB).")
    say(f"Sumber: {url}")
    if not assume_yes:
        answer = input("[Audit Assistant] Unduh sekarang? (y/N): ").strip().lower()
        if answer not in ("y", "ya", "yes"):
            say("Dibatalkan. Anda juga bisa memasangnya sendiri lalu menjalankan demo lagi.")
            return None
    TOOLS_DIR.mkdir(exist_ok=True)
    target = TOOLS_DIR / ("cloudflared.exe" if asset.endswith(".exe") else "cloudflared")
    tmp = target.with_suffix(target.suffix + ".part")
    say("Mengunduh cloudflared...")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(target)
    if not asset.endswith(".exe"):
        target.chmod(0o755)
    return str(target)


def parse_tunnel_url(line: str) -> str | None:
    match = TUNNEL_URL_RE.search(line)
    return match.group(0) if match else None


def start_tunnel(cloudflared: str, port: int, log_path: Path) -> tuple[subprocess.Popen, "queue.Queue[str]"]:
    proc = subprocess.Popen(
        [cloudflared, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    found: "queue.Queue[str]" = queue.Queue()

    def pump() -> None:
        with open(log_path, "a", encoding="utf-8") as log:
            for line in proc.stdout:              # terus dikuras supaya cloudflared tidak tersendat
                log.write(line)
                log.flush()
                url = parse_tunnel_url(line)
                if url:
                    found.put(url)

    threading.Thread(target=pump, daemon=True).start()
    return proc, found


def wait_public(url: str, timeout: float = 120) -> bool:
    """Tunggu link publik benar-benar menjawab (DNS Cloudflare butuh beberapa detik)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=5) as res:
                if res.status == 200:
                    return True
        except OSError:
            time.sleep(2)
    return False


def copy_to_clipboard(text: str) -> bool:
    if platform.system() != "Windows":
        return False
    try:
        subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


# =============================================================================
# MAIN
# =============================================================================

def stop(*procs: subprocess.Popen | None) -> None:
    for proc in procs:
        if proc and proc.poll() is None:
            proc.terminate()
    for proc in procs:
        if proc:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo Audit Assistant lewat internet.")
    parser.add_argument("--reset", action="store_true", help="Buat ulang folder demo dari data terbaru.")
    parser.add_argument("--yes", action="store_true", help="Setujui unduhan cloudflared tanpa bertanya.")
    parser.add_argument("--no-browser", action="store_true", help="Jangan buka link demo di browser.")
    args = parser.parse_args()
    os.chdir(ROOT)
    disable_quick_edit()

    if needs_install():
        install_requirements()

    api_key = demo_api_key(ROOT)
    if not api_key:
        say("API key Gemini belum ada. Isi GEMINI_API_KEY (atau DEMO_GEMINI_API_KEY) di file .env, lalu ulangi.")
        return 1

    cloudflared = find_cloudflared() or download_cloudflared(args.yes)
    if not cloudflared:
        return 1

    if prepare_workspace(ROOT, DEMO_DIR, reset=args.reset):
        say("Folder demo dibuat: salinan Database Regulasi (tanpa hasil analisis & temuan Anda).")

    password = demo_password()
    port = pick_port("127.0.0.1", 8100)
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "DEBUG": "false",
        "DEMO_MODE": "true",
        "APP_USERNAME": DEMO_USERNAME,
        "APP_PASSWORD": password,
        "GEMINI_API_KEY": api_key,
        "PYTHONUNBUFFERED": "1",
    }
    say("Menjalankan server demo...")
    server_log = DEMO_DIR / "server.log"
    server = start_server(DEMO_DIR, env, server_log)
    tunnel = None
    try:
        if not wait_healthy(f"http://127.0.0.1:{port}", server):
            say(f"Server demo gagal dijalankan. Akhir log ({server_log}):")
            print(log_tail(server_log), flush=True)
            return 1
        say("Membuat link publik (Cloudflare)...")
        tunnel, found = start_tunnel(cloudflared, port, DEMO_DIR / "cloudflared.log")
        try:
            url = found.get(timeout=60)
        except queue.Empty:
            say(f"Link publik tidak didapat. Lihat {DEMO_DIR / 'cloudflared.log'}.")
            return 1
        if not wait_public(url):
            say("Link dibuat; DNS Cloudflare masih menyebar - bila belum terbuka, coba lagi 1-2 menit.")

        share = f"Link     : {url}\nUsername : {DEMO_USERNAME}\nPassword : {password}"
        line = "=" * 64
        print(f"\n{line}\n  DEMO SIAP - bagikan ke peserta:\n\n"
              + "\n".join(f"  {s}" for s in share.splitlines())
              + f"\n\n  Link berlaku selama jendela ini terbuka. Ctrl+C untuk berhenti.\n{line}\n", flush=True)
        if copy_to_clipboard(share):
            say("Link, username, dan password sudah disalin ke clipboard (Ctrl+V untuk menempel).")
        say(f"Log: {server_log} dan {DEMO_DIR / 'cloudflared.log'}")
        if not args.no_browser:
            webbrowser.open(url)

        while server.poll() is None and tunnel.poll() is None:
            time.sleep(1)
        say("Server atau tunnel berhenti.")
        return 1
    except KeyboardInterrupt:
        say("Menghentikan demo...")
        return 0
    finally:
        stop(tunnel, server)


if __name__ == "__main__":
    raise SystemExit(main())
