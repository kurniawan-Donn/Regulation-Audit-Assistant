"""
Bangun paket Windows Audit Assistant: Setup.exe (Inno Setup) + ZIP portable.

Paket membawa Python "embeddable" resmi + semua dependensi, jadi pengguna tidak
perlu memasang Python, Git, atau menjalankan pip. Dijalankan oleh workflow
rilis (.github/workflows/release.yml) saat tag vX.Y.Z didorong, atau manual:

    python -m scripts.build_installer [--version 1.2.3] [--skip-setup] [--no-smoke]

Harus dijalankan dengan Python Windows x64 yang versinya sama dengan Python
yang dibundel (versi interpreter ini dipakai untuk mengunduh Python embeddable).

Hasil di dist/:
    AuditAssistant-<versi>-Setup.exe      (butuh Inno Setup 6 / ISCC.exe)
    AuditAssistant-<versi>-Portable.zip
    SHA256SUMS.txt
"""

from __future__ import annotations

import argparse
import compileall
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
BUNDLE = BUILD / "bundle"
CACHE = BUILD / "cache"
DIST = ROOT / "dist"
ISS = ROOT / "installer" / "AuditAssistant.iss"

APP_DIRS = ("app", "static", "templates")
SCRIPT_FILES = ("launch.py", "backup.py")
# Dibuang dari site-packages: tidak dipakai saat berjalan, hanya menambah ukuran.
PRUNE_TEST_DIRS_IN = ("numpy", "pyarrow", "pandas")
PRUNE_PATHS = ("bin", "pyarrow/include")
DEV_ONLY_PACKAGES = ("pytest",)

PORTABLE_LAUNCHER = """@echo off
rem Audit Assistant (portable): klik dua kali file ini. Data disimpan di folder userdata.
cd /d "%~dp0"
title Audit Assistant
"python\\python.exe" -m scripts.launch --portable %*
if errorlevel 1 pause
"""

VERSION_RE = re.compile(r"^v?(\d+\.\d+\.\d+)$")


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


# =============================================================================
# VERSI & KONFIGURASI
# =============================================================================
def current_app_version() -> str:
    text = (ROOT / "app" / "version.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)  # type: ignore[union-attr]


def resolve_version(explicit: str | None) -> str:
    """--version > tag Git di CI (GITHUB_REF_NAME=v1.2.3) > app/version.py."""
    candidates = [explicit, os.environ.get("GITHUB_REF_NAME") if os.environ.get("GITHUB_REF_TYPE") == "tag" else None]
    for value in candidates:
        if value:
            m = VERSION_RE.match(value.strip())
            if not m:
                raise SystemExit(f"Versi tidak valid: {value!r} (format: 1.2.3 atau v1.2.3)")
            return m.group(1)
    return current_app_version()


def runtime_requirements(text: str) -> list[str]:
    """Isi requirements.txt tanpa paket khusus pengembangan (pytest)."""
    keep = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[\[=<>!~;\s]", line, maxsplit=1)[0].lower()
        if name not in DEV_ONLY_PACKAGES:
            keep.append(line)
    return keep


def pth_content(python_tag: str) -> str:
    """Isi pythonXY._pth: stdlib + site-packages + folder aplikasi (..), site aktif."""
    return "\n".join([
        f"{python_tag}.zip",
        ".",
        "Lib\\site-packages",
        "..",
        "import site",
        "",
    ])


def set_bundle_version(version_file: Path, version: str) -> None:
    text = version_file.read_text(encoding="utf-8")
    version_file.write_text(re.sub(r'__version__\s*=\s*"[^"]*"', f'__version__ = "{version}"', text),
                            encoding="utf-8")


# =============================================================================
# LANGKAH BUILD
# =============================================================================
def download(url: str, dest: Path) -> Path:
    if dest.exists():
        log(f"Pakai cache {dest.name}")
        return dest
    log(f"Mengunduh {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as res, open(tmp, "wb") as fh:
        shutil.copyfileobj(res, fh)
    tmp.replace(dest)
    return dest


def prepare_python(target: Path) -> None:
    v = sys.version_info
    full = f"{v.major}.{v.minor}.{v.micro}"
    tag = f"python{v.major}{v.minor}"
    url = f"https://www.python.org/ftp/python/{full}/python-{full}-embed-amd64.zip"
    archive = download(url, CACHE / f"python-{full}-embed-amd64.zip")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(target)
    (target / f"{tag}._pth").write_text(pth_content(tag), encoding="utf-8")
    log(f"Python {full} embeddable siap")


def install_packages(site_packages: Path) -> None:
    reqs = runtime_requirements((ROOT / "requirements.txt").read_text(encoding="utf-8"))
    req_file = BUILD / "requirements-runtime.txt"
    req_file.write_text("\n".join(reqs) + "\n", encoding="utf-8")
    log(f"Memasang {len(reqs)} paket ke bundel")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
         "--only-binary=:all:", "--target", str(site_packages), "-r", str(req_file)],
        check=True,
    )
    for rel in PRUNE_PATHS:
        shutil.rmtree(site_packages / rel, ignore_errors=True)
    for pkg in PRUNE_TEST_DIRS_IN:
        base = site_packages / pkg
        if base.exists():
            for tests in [p for p in base.rglob("tests") if p.is_dir()]:
                shutil.rmtree(tests, ignore_errors=True)


def copy_app(bundle: Path, version: str) -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in APP_DIRS:
        shutil.copytree(ROOT / name, bundle / name, ignore=ignore)
    (bundle / "scripts").mkdir()
    (bundle / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    for name in SCRIPT_FILES:
        shutil.copy2(ROOT / "scripts" / name, bundle / "scripts" / name)
    shutil.copy2(ROOT / "installer" / "audit-assistant.ico", bundle / "audit-assistant.ico")
    (bundle / "Audit Assistant.bat").write_text(PORTABLE_LAUNCHER.replace("\n", "\r\n"), encoding="utf-8")
    set_bundle_version(bundle / "app" / "version.py", version)


def precompile(bundle: Path) -> None:
    # Bytecode untuk versi Python yang sama -> start pertama lebih cepat.
    compileall.compile_dir(str(bundle), quiet=2, workers=0)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def smoke_test(bundle: Path) -> None:
    """Jalankan server dari bundel (Python bawaan, folder data kosong) dan cek /health."""
    python = bundle / "python" / "python.exe"
    subprocess.run([str(python), "-c", "import app.main, lancedb, fitz, docx, openpyxl, reportlab, google.genai"],
                   check=True, cwd=bundle)
    port = free_port()
    with tempfile.TemporaryDirectory() as home:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV"))}
        env.update(PORT=str(port), HOST="127.0.0.1", DEBUG="false", AUDIT_ASSISTANT_INSTALL="installer")
        proc = subprocess.Popen([str(python), "-m", "app"], cwd=home, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            deadline = time.time() + 90
            while time.time() < deadline:
                if proc.poll() is not None:
                    raise SystemExit("Uji asap gagal: server berhenti.\n" + proc.stdout.read().decode(errors="replace"))
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as res:
                        if json.loads(res.read()).get("app") == "audit-assistant":
                            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as page:
                                assert page.status == 200
                            log("Uji asap OK: server dari bundel menjawab /health dan halaman utama")
                            return
                except OSError:
                    time.sleep(0.5)
            raise SystemExit("Uji asap gagal: /health tidak menjawab dalam 90 detik.")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def make_portable_zip(bundle: Path, out: Path) -> Path:
    log(f"Membuat {out.name}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                zf.write(path, Path("Audit Assistant") / path.relative_to(bundle))
    return out


def find_iscc(explicit: str | None) -> Path | None:
    candidates = [explicit, shutil.which("iscc"), shutil.which("ISCC")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs")):
        if base:
            candidates.append(str(Path(base) / "Inno Setup 6" / "ISCC.exe"))
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return None


def make_setup(iscc: Path, bundle: Path, version: str) -> Path:
    log("Mengompilasi installer (Inno Setup)")
    subprocess.run([str(iscc), "/Q", f"/DAppVersion={version}", f"/DBundleDir={bundle}",
                    f"/DOutputDir={DIST}", str(ISS)], check=True)
    return DIST / f"AuditAssistant-{version}-Setup.exe"


def write_checksums(files: list[Path]) -> Path:
    lines = []
    for f in files:
        lines.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
    out = DIST / "SHA256SUMS.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Bangun Setup.exe & ZIP portable Audit Assistant.")
    parser.add_argument("--version", help="Versi rilis, mis. 1.2.3 (default: tag Git di CI / app/version.py).")
    parser.add_argument("--skip-setup", action="store_true", help="Hanya ZIP portable (tanpa Inno Setup).")
    parser.add_argument("--require-setup", action="store_true", help="Gagal bila Inno Setup tidak ditemukan.")
    parser.add_argument("--no-smoke", action="store_true", help="Lewati uji asap server dari bundel.")
    parser.add_argument("--iscc", help="Path ISCC.exe (default: cari otomatis).")
    args = parser.parse_args()

    if platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("Build paket harus dijalankan di Windows x64.")
    version = resolve_version(args.version)
    log(f"Versi {version}")

    shutil.rmtree(BUNDLE, ignore_errors=True)
    BUNDLE.mkdir(parents=True)
    DIST.mkdir(exist_ok=True)

    prepare_python(BUNDLE / "python")
    install_packages(BUNDLE / "python" / "Lib" / "site-packages")
    copy_app(BUNDLE, version)
    precompile(BUNDLE)
    if not args.no_smoke:
        smoke_test(BUNDLE)

    outputs = [make_portable_zip(BUNDLE, DIST / f"AuditAssistant-{version}-Portable.zip")]
    if not args.skip_setup:
        iscc = find_iscc(args.iscc)
        if iscc:
            outputs.append(make_setup(iscc, BUNDLE, version))
        elif args.require_setup:
            raise SystemExit("Inno Setup (ISCC.exe) tidak ditemukan. Pasang dari https://jrsoftware.org/isdl.php")
        else:
            log("Inno Setup tidak ditemukan - Setup.exe dilewati (ZIP portable tetap dibuat).")
    outputs.append(write_checksums(outputs))
    for f in outputs:
        log(f"Hasil: {f.relative_to(ROOT)} ({f.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
