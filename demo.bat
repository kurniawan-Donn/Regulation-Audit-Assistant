@echo off
rem Demo Audit Assistant lewat internet: klik dua kali file ini.
rem Membuat link publik sementara (Cloudflare) + password; berlaku selama jendela ini terbuka.
setlocal
cd /d "%~dp0"
title Audit Assistant - DEMO

if not exist "venv\Scripts\python.exe" (
    echo [Audit Assistant] Jalankan start.bat sekali terlebih dahulu untuk menyiapkan aplikasi.
    pause
    exit /b 1
)

"venv\Scripts\python.exe" -m scripts.demo %*
if errorlevel 1 pause
