#!/usr/bin/env bash
# Jalankan Audit Assistant (macOS / Linux): ./start.sh
# Pertama kali: membuat venv & memasang paket (beberapa menit). Berikutnya langsung jalan.
set -e
cd "$(dirname "$0")"

if [ ! -x venv/bin/python ]; then
    PY="$(command -v python3 || command -v python || true)"
    if [ -z "$PY" ]; then
        echo "[Audit Assistant] Python 3.11+ tidak ditemukan. Pasang dari https://www.python.org/downloads/ lalu jalankan lagi."
        exit 1
    fi
    echo "[Audit Assistant] Menyiapkan lingkungan Python pertama kali..."
    "$PY" -m venv venv
fi

exec venv/bin/python -m scripts.launch "$@"
