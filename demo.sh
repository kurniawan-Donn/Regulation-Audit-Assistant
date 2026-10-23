#!/usr/bin/env bash
# Demo Audit Assistant lewat internet (macOS / Linux): ./demo.sh
set -e
cd "$(dirname "$0")"
if [ ! -x venv/bin/python ]; then
    echo "[Audit Assistant] Jalankan ./start.sh sekali terlebih dahulu untuk menyiapkan aplikasi."
    exit 1
fi
exec venv/bin/python -m scripts.demo "$@"
