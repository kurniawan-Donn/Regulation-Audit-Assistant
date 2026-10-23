# Pemasangan Server Tim

Panduan untuk admin yang memasang Audit Assistant di **VM kantor atau mini PC yang selalu menyala**, sehingga seluruh tim audit memakai satu aplikasi dan satu data bersama.

> Untuk uji coba di laptop sendiri cukup klik dua kali `start.bat` (lihat README).

## Gambaran

```
Laptop auditor ──HTTPS──▶ Caddy (port 443) ──▶ Audit Assistant (port 8000, internal)
                                                   │
                                                   ├─ data/     database regulasi, pengaturan, temuan
                                                   ├─ outputs/  hasil analisis & ekspor
                                                   └─ backups/  file backup
```

## 1. Syarat

- Linux (Ubuntu Server 22.04/24.04 LTS disarankan), 2 vCPU, 4 GB RAM, 30 GB disk.
- Docker Engine + Docker Compose plugin (`docker compose version` berhasil).
- Akses keluar ke `generativelanguage.googleapis.com:443`.
- Nama host di DNS internal, mis. `audit-assistant.kantor.local`, menunjuk ke IP server.

## 2. Pasang

```bash
git clone https://github.com/kurniawan-Donn/regulation-audit-assistant.git
cd regulation-audit-assistant
cp .env.example .env
nano .env
```

Isi minimal di `.env`:

```env
GEMINI_API_KEY=...            # sebaiknya dari project Google Cloud dengan billing aktif
APP_USERNAME=auditor
APP_PASSWORD=...              # password kuat — dibagikan ke anggota tim
SITE_ADDRESS=audit-assistant.kantor.local
TLS_MODE=internal             # lihat langkah 3
```

Jalankan:

```bash
docker compose -f docker-compose.server.yml up -d --build
docker compose -f docker-compose.server.yml ps        # keduanya "running" / "healthy"
```

Buka `https://audit-assistant.kantor.local` dari laptop tim, login dengan `APP_USERNAME` / `APP_PASSWORD`.

## 3. Sertifikat HTTPS — pilih salah satu

| Pilihan | `TLS_MODE` di `.env` | Catatan |
|---|---|---|
| **A. CA internal bank** (disarankan) | `/certs/server.crt /certs/server.key` | Minta sertifikat untuk `SITE_ADDRESS` ke TI, simpan di `deploy/certs/`. Browser kantor langsung percaya. |
| B. CA bawaan Caddy | `internal` (default) | Langsung jalan. Browser menampilkan peringatan sampai sertifikat root Caddy dipasang di laptop tim (langkah di bawah). |
| C. Let's Encrypt | alamat email admin | Hanya bila server punya domain publik dan port 80/443 terjangkau dari internet. |

Mengambil sertifikat root Caddy (pilihan B) untuk dipasang di laptop tim (*Trusted Root Certification Authorities*):

```bash
docker compose -f docker-compose.server.yml cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
```

## 4. Pindahkan data dari laptop

Di laptop yang selama ini dipakai (aplikasi dimatikan dulu):

```bash
venv\Scripts\python -m scripts.backup create        # Windows
# hasil: backups\audit-assistant-YYYYMMDD-HHMMSS.zip
```

Salin file .zip ke folder aplikasi di server, lalu (di host, bukan di dalam container — `data/` dan `outputs/` adalah folder yang dipasang ke container):

```bash
docker compose -f docker-compose.server.yml stop audit-assistant
[ -d data ] && mv data data_sebelum_restore            # simpan data lama, jangan ditimpa
[ -d outputs ] && mv outputs outputs_sebelum_restore
unzip audit-assistant-YYYYMMDD-HHMMSS.zip -x BACKUP_INFO.txt
sudo chown -R 1000 data outputs
docker compose -f docker-compose.server.yml start audit-assistant
```

API key tidak ikut backup (kecuali dibuat dengan `--with-env`); pastikan `GEMINI_API_KEY` sudah ada di `.env` server.

## 5. Backup rutin

Contoh cron harian pukul 19.00 (simpan 14 backup terakhir):

```cron
0 19 * * * cd /opt/regulation-audit-assistant && docker compose -f docker-compose.server.yml exec -T audit-assistant python -m scripts.backup create && ls -1t backups/*.zip | tail -n +15 | xargs -r rm
```

File backup ada di folder `backups/` server — ikutkan dalam backup VM/storage standar TI.

## 6. Pembaruan aplikasi

```bash
cd /opt/regulation-audit-assistant
docker compose -f docker-compose.server.yml exec -T audit-assistant python -m scripts.backup create
git pull
docker compose -f docker-compose.server.yml up -d --build
```

Data di `data/`, `outputs/`, `backups/` tidak tersentuh oleh pembaruan.

## 7. Akses dari luar kantor (opsional)

Server **tidak perlu** dibuka ke internet. Bila tim perlu akses saat dinas luar, gunakan VPN kantor. Alternatif tanpa membuka port: **Tailscale** (VPN privat) atau **Cloudflare Tunnel + Access** (login email; butuh domain di Cloudflare). Konsultasikan dengan TI/keamanan informasi terlebih dahulu.

## 8. Pemecahan masalah

| Gejala | Penyebab & solusi |
|---|---|
| `docker compose` berhenti: *required variable … is missing* | `APP_PASSWORD` atau `SITE_ADDRESS` belum diisi di `.env`. |
| Browser: *Your connection is not private* | Pilihan B tanpa root CA terpasang di laptop → pasang `caddy-root.crt`, atau pakai sertifikat CA internal (A). |
| Halaman 502 | Aplikasi belum siap / berhenti: `docker compose -f docker-compose.server.yml logs audit-assistant`. |
| Analisis gagal: *API key* / *quota* | Periksa `GEMINI_API_KEY`, billing, dan akses keluar ke `generativelanguage.googleapis.com`. |
| Izin ditolak menulis `data/` | Container berjalan sebagai UID 1000: `sudo chown -R 1000 data outputs cache backups`. |
