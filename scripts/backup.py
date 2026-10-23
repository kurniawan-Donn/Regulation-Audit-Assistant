"""
Backup & pemulihan data Audit Assistant — juga untuk pindah laptop → server.

Yang dibackup: data/ (Regulation DB, pengaturan, prompt, Daftar Temuan) dan
outputs/ (hasil analisis + ekspor). cache/ tidak (bisa dibuat ulang), begitu
pula folder data/backup_* lama. Rahasia (.env dan API key di
data/settings.json) hanya ikut bila diminta --with-env — tanpa itu, isi ulang
API key di Pengaturan setelah restore.

    python -m scripts.backup create [--out backups] [--with-env]
    python -m scripts.backup restore backups/audit-assistant-20261023-0900.zip

Hentikan server saat backup/restore agar database tidak sedang ditulis.
Restore tidak menimpa: folder lama dipindah ke <nama>_sebelum_restore_<waktu>.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

INCLUDED_DIRS = ("data", "outputs")
SKIP_DIR_PREFIXES = ("backup_",)          # mis. data/backup_before_reindex_20261022
SKIP_NAMES = {"__pycache__", ".gitkeep"}
MANIFEST = "BACKUP_INFO.txt"
# Pengaturan yang diisi lewat UI juga menyimpan API key — dikosongkan kecuali --with-env.
SETTINGS_FILE = "data/settings.json"
SECRET_SETTINGS = ("gemini_api_key",)


def _skip(rel: Path) -> bool:
    parts = rel.parts
    if any(p in SKIP_NAMES for p in parts):
        return True
    # Hanya subfolder langsung di bawah data/ / outputs/ yang dicek prefiksnya.
    return len(parts) > 2 and parts[1].startswith(SKIP_DIR_PREFIXES)


def _without_secrets(settings_path: Path) -> str:
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "{}"
    for key in SECRET_SETTINGS:
        if key in data:
            data[key] = ""
    return json.dumps(data, ensure_ascii=False, indent=2)


def create_backup(root: Path, out_dir: Path, with_env: bool = False) -> Path:
    out_dir = out_dir if out_dir.is_absolute() else root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"audit-assistant-{datetime.now():%Y%m%d-%H%M%S}.zip"
    count = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in INCLUDED_DIRS:
            base = root / name
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                rel = path.relative_to(root)
                if not path.is_file() or _skip(rel):
                    continue
                if rel.as_posix() == SETTINGS_FILE and not with_env:
                    zf.writestr(SETTINGS_FILE, _without_secrets(path))
                else:
                    zf.write(path, rel.as_posix())
                count += 1
        if with_env and (root / ".env").is_file():
            zf.write(root / ".env", ".env")
            count += 1
        zf.writestr(MANIFEST, (
            f"Backup Audit Assistant\nDibuat: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"Isi: {', '.join(INCLUDED_DIRS)}{' + .env' if with_env else ''} ({count} file)\n"
            "Pulihkan: python -m scripts.backup restore <file.zip>\n"
        ))
    return target


def restore_backup(root: Path, archive: Path) -> list[str]:
    """Pulihkan backup. Folder yang sudah ada dipindah dulu (tidak ditimpa)."""
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if n != MANIFEST]
        for n in names:
            # Tolak path di luar folder aplikasi (zip slip).
            dest = (root / n).resolve()
            if root.resolve() not in dest.parents and dest != root.resolve():
                raise SystemExit(f"Isi backup tidak valid: {n}")
            if not (n.split("/")[0] in INCLUDED_DIRS or n == ".env"):
                raise SystemExit(f"Isi backup tidak dikenal: {n}")

        stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        moved = []
        tops = {n.split("/")[0] for n in names}
        for top in sorted(tops):
            existing = root / top
            if existing.exists():
                aside = root / f"{top}_sebelum_restore_{stamp}"
                existing.rename(aside)
                moved.append(f"{top} -> {aside.name}")
        zf.extractall(root, members=names)
    return moved


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup & pemulihan data Audit Assistant.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_create = sub.add_parser("create", help="Buat file backup .zip")
    p_create.add_argument("--out", default="backups", help="Folder tujuan (default: backups)")
    p_create.add_argument("--with-env", action="store_true",
                          help="Ikutkan .env (berisi API key & password) — simpan file backup dengan aman")
    p_restore = sub.add_parser("restore", help="Pulihkan dari file backup .zip")
    p_restore.add_argument("archive", help="Path file backup .zip")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    if args.cmd == "create":
        target = create_backup(root, Path(args.out), args.with_env)
        size_mb = target.stat().st_size / 1_048_576
        print(f"Backup dibuat: {target} ({size_mb:.1f} MB)")
        return 0

    archive = Path(args.archive)
    if not archive.is_file():
        print(f"File tidak ditemukan: {archive}", file=sys.stderr)
        return 2
    moved = restore_backup(root, archive)
    for line in moved:
        print(f"Data lama dipindahkan: {line}")
    print("Pemulihan selesai. Jalankan ulang aplikasi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
