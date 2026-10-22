@echo off
rem Jalankan Audit Assistant (Windows): klik dua kali file ini.
rem Pertama kali: membuat venv & memasang paket (beberapa menit). Berikutnya langsung jalan.
setlocal
cd /d "%~dp0"
title Audit Assistant

if not exist "venv\Scripts\python.exe" (
    echo [Audit Assistant] Menyiapkan lingkungan Python pertama kali...
    where py >nul 2>nul && py -3 -m venv venv
    if not exist "venv\Scripts\python.exe" python -m venv venv
)
if not exist "venv\Scripts\python.exe" (
    echo [Audit Assistant] Python 3.11+ tidak ditemukan.
    echo Pasang dari https://www.python.org/downloads/ ^(centang "Add python.exe to PATH"^), lalu jalankan file ini lagi.
    pause
    exit /b 1
)

"venv\Scripts\python.exe" -m scripts.launch %*
if errorlevel 1 pause
