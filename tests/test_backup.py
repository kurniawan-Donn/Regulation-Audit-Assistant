"""
Backup & pemulihan data (scripts/backup.py) — untuk pindah laptop → server.
"""

import json
import zipfile
from pathlib import Path

import pytest

from scripts.backup import create_backup, restore_backup


def _app(root: Path) -> None:
    (root / "data/lancedb/regulations.lance").mkdir(parents=True)
    (root / "data/lancedb/regulations.lance/data.bin").write_bytes(b"vec")
    (root / "data/findings.json").write_text('{"items": []}', encoding="utf-8")
    (root / "data/backup_before_reindex_20261022").mkdir()
    (root / "data/backup_before_reindex_20261022/old.json").write_text("{}", encoding="utf-8")
    (root / "outputs/compliance").mkdir(parents=True)
    (root / "outputs/compliance/abc.json").write_text("{}", encoding="utf-8")
    (root / "outputs/.gitkeep").write_text("", encoding="utf-8")
    (root / "cache").mkdir()
    (root / "cache/preview.json").write_text("{}", encoding="utf-8")
    (root / ".env").write_text("GEMINI_API_KEY=rahasia\n", encoding="utf-8")
    (root / "data/settings.json").write_text('{"gemini_api_key": "rahasia-ui", "theme": "dark"}', encoding="utf-8")


def test_backup_berisi_data_dan_hasil_tanpa_cache_dan_rahasia(tmp_path):
    _app(tmp_path)
    archive = create_backup(tmp_path, Path("backups"))
    assert archive.parent == tmp_path / "backups"
    names = set(zipfile.ZipFile(archive).namelist())
    assert {"data/lancedb/regulations.lance/data.bin", "data/findings.json",
            "outputs/compliance/abc.json", "BACKUP_INFO.txt"} <= names
    assert not any(n.startswith("cache/") for n in names)
    assert not any("backup_before_reindex" in n for n in names)
    assert ".env" not in names and "outputs/.gitkeep" not in names

    # API key yang diisi lewat UI tidak ikut; pengaturan lain tetap.
    settings = json.loads(zipfile.ZipFile(archive).read("data/settings.json"))
    assert settings == {"gemini_api_key": "", "theme": "dark"}

    with_env = create_backup(tmp_path, tmp_path / "lain", with_env=True)
    assert ".env" in zipfile.ZipFile(with_env).namelist()
    assert b"rahasia-ui" in zipfile.ZipFile(with_env).read("data/settings.json")


def test_restore_ke_server_baru_dan_tidak_menimpa_data_lama(tmp_path):
    laptop, server = tmp_path / "laptop", tmp_path / "server"
    laptop.mkdir()
    server.mkdir()
    _app(laptop)
    archive = create_backup(laptop, Path("backups"))

    # Server baru (kosong): langsung terpasang.
    assert restore_backup(server, archive) == []
    assert (server / "data/findings.json").read_text(encoding="utf-8") == '{"items": []}'
    assert (server / "outputs/compliance/abc.json").exists()

    # Restore kedua: data yang ada dipindah, bukan ditimpa.
    (server / "data/findings.json").write_text('{"items": ["baru"]}', encoding="utf-8")
    moved = restore_backup(server, archive)
    assert len(moved) == 2 and all("_sebelum_restore_" in m for m in moved)
    asides = [p for p in server.iterdir() if p.name.startswith("data_sebelum_restore_")]
    assert asides and (asides[0] / "findings.json").read_text(encoding="utf-8") == '{"items": ["baru"]}'


def test_restore_menolak_zip_berbahaya(tmp_path):
    bad = tmp_path / "jahat.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../luar.txt", "x")
    with pytest.raises(SystemExit):
        restore_backup(tmp_path / "app", bad)

    unknown = tmp_path / "asing.zip"
    with zipfile.ZipFile(unknown, "w") as zf:
        zf.writestr("app/main.py", "x")
    (tmp_path / "app").mkdir()
    with pytest.raises(SystemExit):
        restore_backup(tmp_path / "app", unknown)
