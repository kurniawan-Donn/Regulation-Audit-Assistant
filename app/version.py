"""
Versi aplikasi — satu-satunya sumber nomor versi.

Saat rilis (git tag vX.Y.Z), workflow `.github/workflows/release.yml` menulis
ulang nilai ini di salinan yang dibundel ke installer; di repo nilainya adalah
versi rilis terakhir.
"""

__version__ = "1.1.0"
