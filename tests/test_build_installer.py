"""
Skrip build paket Windows (scripts/build_installer.py): bagian yang bisa diuji
tanpa mengunduh Python atau menjalankan Inno Setup.
"""

import pytest

from scripts import build_installer as build


def test_versi_dari_argumen_tag_atau_file(monkeypatch):
    monkeypatch.delenv("GITHUB_REF_TYPE", raising=False)
    assert build.resolve_version("v1.4.2") == "1.4.2"
    assert build.resolve_version("2.0.0") == "2.0.0"
    assert build.resolve_version(None) == build.current_app_version()

    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", "v3.1.0")
    assert build.resolve_version(None) == "3.1.0"
    with pytest.raises(SystemExit):
        build.resolve_version("versi-baru")


def test_paket_pengembang_tidak_dibundel():
    reqs = build.runtime_requirements(
        "# komentar\nfastapi==0.115.0\nuvicorn[standard]==0.30.6\npytest==8.3.3\n\nlancedb==0.39.0\n"
    )
    assert reqs == ["fastapi==0.115.0", "uvicorn[standard]==0.30.6", "lancedb==0.39.0"]


def test_requirements_repo_terbaca():
    reqs = build.runtime_requirements((build.ROOT / "requirements.txt").read_text(encoding="utf-8"))
    names = " ".join(reqs)
    assert "fastapi" in names and "lancedb" in names and "pytest" not in names


def test_python_bawaan_melihat_folder_aplikasi():
    pth = build.pth_content("python313").splitlines()
    assert pth[0] == "python313.zip"
    assert "Lib\site-packages" in pth and ".." in pth and "import site" in pth


def test_versi_ditulis_ke_salinan_bundel(tmp_path):
    f = tmp_path / "version.py"
    f.write_text('"""doc"""\n\n__version__ = "1.0.0"\n', encoding="utf-8")
    build.set_bundle_version(f, "1.7.3")
    assert '__version__ = "1.7.3"' in f.read_text(encoding="utf-8")


def test_script_installer_memakai_file_yang_ada():
    iss = build.ISS.read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in iss and "--installed" in iss
    for name in ("audit-assistant.ico", "Indonesian.isl"):
        assert name in iss and (build.ISS.parent / name).exists()
    assert "scripts.launch" in iss
