# Permintaan Penyediaan Server — Audit Assistant

**Kepada:** Divisi Teknologi Informasi
**Dari:** Satuan Kerja Audit Intern
**Perihal:** Penyediaan VM internal untuk aplikasi bantu audit TI (*Regulation to IT Audit Assistant*)

> Draf — sesuaikan nama unit, penanggung jawab, dan kebijakan internal sebelum dikirim.

---

## 1. Latar belakang

Satuan Kerja Audit Intern menggunakan aplikasi *Audit Assistant* untuk:

- mengubah ketentuan regulasi (POJK, PADK, SEOJK) menjadi prosedur dan kertas kerja audit TI;
- menguji kepatuhan perjanjian kerja sama penyedia jasa TI terhadap regulasi;
- mengelola daftar temuan dan menyusun Laporan Hasil Audit.

Saat ini aplikasi berjalan di laptop auditor, sehingga **tidak tersedia saat laptop mati** dan data (database regulasi, temuan, hasil analisis) **tidak dapat dipakai bersama** oleh tim. Kami memohon satu VM internal agar aplikasi tersedia terus-menerus untuk tim audit, dengan data tersimpan di infrastruktur bank.

## 2. Spesifikasi yang dibutuhkan

| Komponen | Kebutuhan |
|---|---|
| Sistem operasi | Linux (Ubuntu Server 22.04/24.04 LTS atau setara) |
| CPU / RAM | 2 vCPU / 4 GB RAM |
| Disk | 30 GB (aplikasi ±2 GB; data tumbuh ±1–2 GB/tahun) |
| Perangkat lunak | Docker Engine + Docker Compose plugin |
| GPU | Tidak perlu (pemrosesan AI dilakukan oleh layanan Gemini API) |
| Ketersediaan | Jam kerja; tidak kritikal (bukan sistem layanan nasabah) |

## 3. Jaringan

| Arah | Tujuan | Port | Keterangan |
|---|---|---|---|
| Masuk | Dari jaringan internal kantor (segmen tim audit) | 443 (HTTPS), 80 (redirect) | Tidak perlu diakses dari internet |
| Keluar | `generativelanguage.googleapis.com` | 443 | Layanan AI Google Gemini |
| Keluar | `pypi.org`, `files.pythonhosted.org`, Docker Hub | 443 | Hanya saat instalasi/pembaruan |

Nama host yang diusulkan: `audit-assistant.<domain-internal>` (DNS internal).

## 4. Pengendalian keamanan

- **Autentikasi:** login (Basic Auth) wajib; aplikasi menolak berjalan di jaringan tanpa password.
- **Enkripsi:** HTTPS melalui reverse proxy Caddy — mohon sertifikat dari **CA internal bank** (alternatif: CA bawaan Caddy).
- **Kontainer:** aplikasi berjalan sebagai pengguna non-root; hanya reverse proxy yang membuka port.
- **Data tersimpan di VM:** database regulasi (dokumen publik), hasil analisis, daftar temuan, dan pengaturan — di folder `data/`, `outputs/`, `cache/`.
- **Data yang keluar:** potongan teks regulasi dan klausul kontrak dikirim ke Gemini API untuk dianalisis. Kami akan memakai **Gemini API berbayar** (billing aktif) karena pada layanan tanpa biaya Google dapat memakai konten untuk pengembangan produk, sedangkan pada layanan berbayar tidak.
- **Lokasi data:** VM di pusat data bank di Indonesia (selaras POJK 11/POJK.03/2022 Pasal 35 tentang penempatan Sistem Elektronik).
- **Rahasia:** API key dan password disimpan di file `.env` di VM (hak akses hanya admin).

## 5. Backup & pemeliharaan

- Backup harian folder data dengan perintah bawaan (`python -m scripts.backup create`) atau mekanisme backup VM standar TI.
- Pembaruan aplikasi: `git pull` lalu `docker compose -f docker-compose.server.yml up -d --build` (±5 menit, di luar jam sibuk).
- Penanggung jawab aplikasi: *[nama, Satuan Kerja Audit Intern]* · Penanggung jawab infrastruktur: *[nama, Divisi TI]*.

## 6. Lampiran

- Panduan instalasi untuk admin: `docs/SERVER_TIM.md`
- Kode sumber & konfigurasi: repositori `regulation-audit-assistant`
