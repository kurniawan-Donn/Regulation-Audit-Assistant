<div align="center">

# 🛡️ Regulation to IT Audit Assistant

**Ubah regulasi OJK/BI menjadi kertas kerja audit TI yang siap pakai, dengan bantuan AI.**

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)
![License](https://img.shields.io/badge/license-MIT-yellow)
![Status](https://img.shields.io/badge/status-beta-orange)

[Fitur](#-fitur-utama) · [Instalasi](#-instalasi) · [Penggunaan](#-penggunaan) · [API](#-dokumentasi-api) · [Deployment](#-deployment) · [Kontribusi](#-kontribusi)

</div>

---

## 📖 Tentang

**Regulation to IT Audit Assistant** adalah aplikasi web untuk auditor TI internal bank, BPR, dan BPRS yang bekerja dengan regulasi seperti **POJK**, **PADK**, **SEOJK**, dan **PBI**. Aplikasi ini menyediakan dua alur kerja utama:

| Alur Kerja | Hasil |
|---|---|
| **Regulation to Audit** | Prosedur pemeriksaan lengkap dengan aspek, metode, dan kebutuhan bukti |
| **Gap Analysis** | Daftar persyaratan regulasi sebagai checklist kepatuhan |

**Mengapa memakai tools ini?**

- ⏱️ **Hemat waktu**: analisis dokumen 200 halaman selesai dalam 15–30 menit, bukan 2–3 hari.
- 🎯 **Konsisten**: struktur output seragam sesuai standar kertas kerja audit.
- 🔍 **Traceable**: setiap ketentuan memiliki referensi Lampiran/BAB/Pasal/Ayat/Halaman.
- 🛡️ **Anti-halusinasi**: referensi pasal divalidasi terhadap teks sumber.
- 💰 **Biaya terkendali**: caching, batching, dan estimasi biaya sebelum eksekusi.

**Prinsip desain**

- **Kertas kerja dulu, AI kemudian**: auditor tetap pengambil keputusan.
- **Flag, bukan perbaikan diam-diam**: hasil AI divalidasi dan ditandai, tidak diubah tanpa sepengetahuan pengguna.
- **Graceful degradation**: kegagalan satu batch tidak menggagalkan seluruh proses.
- **Kontrol penuh di tangan pengguna**: prompt, model, dan parameter dapat dikustomisasi.

---

## ✨ Fitur Utama

### 🔍 Parsing Regulasi
- **Parser dual-mode**: mendukung struktur POJK/PBI/SEOJK/UU (`BAB → Pasal → Ayat → Huruf`) dan PADK berlampiran (`Lampiran → I. → A. → 1. → a. → 1)`).
- **Pelacakan halaman**: setiap chunk memiliki `page_start` dan `page_end`.
- **Tree hierarki interaktif**: pilih bagian yang ingin dianalisis.
- **Pembersihan otomatis**: Daftar Isi dilewati dan nomor halaman dibuang dari konten.

### 🤖 Analisis AI
- **Gemini API**: default `gemini-2.5-flash`, model dapat diganti lewat UI.
- **Batching pintar**: banyak chunk per request untuk menghemat rate limit.
- **Validasi berlapis**: pengecekan anti-halusinasi dan controlled vocabulary.
- **Tahan gangguan**: retry otomatis untuk error transien dan penanganan error per batch.

### 📊 Kertas Kerja Audit
- **10 kolom** standar audit TI: No, Referensi, Aspek, BAB/Pasal/Ayat, Ketentuan, Pemeriksaan, Metode, Bukti, Status, Catatan.
- **Edit inline**: klik sel, ubah, lalu *blur* untuk menyimpan otomatis.
- **Progress tracking** dengan progress bar (contoh: "12/42 diperiksa (29%)").
- **Bulk action**: ubah status atau hapus banyak baris sekaligus.
- **Tambah baris manual** untuk temuan auditor di luar output AI.
- **Export Excel** (dropdown status + pewarnaan) dan **PDF** (A4 landscape).

### 📋 Gap Analysis
- **Ekstraksi persyaratan** ke 4 kolom: No, Persyaratan, Referensi, Catatan.
- **Catatan berformat markdown ringan**: cetak tebal dan nested list.
- **Filter kata kunci** untuk membatasi analisis dan menghemat biaya.
- **Status gap manual**: Sesuai / Sebagian / Tidak / N/A, dengan export Excel.

### 💬 Tanya Regulasi
- **Tanya-jawab atas Database Regulasi**: ajukan pertanyaan ("berapa lama batas pelaporan insiden TI?"), jawaban disusun **hanya dari kutipan regulasi** yang ditemukan.
- **Sitasi per kalimat** `[1]`, `[2]` → klik untuk membuka kutipan asli beserta rujukan Pasal/ayat dan halaman.
- **Anti-halusinasi**: sitasi ke sumber yang tidak ada dihapus dan ditandai; jawaban tanpa sitasi valid diberi catatan "verifikasi manual"; bila sumber tidak memuat jawabannya, AI wajib menyatakan *tidak ditemukan*.
- **Pertanyaan lanjutan** memakai konteks percakapan; filter per regulasi; salin jawaban + daftar sumber.

### 🚩 Daftar Temuan
- **Satu tempat untuk semua temuan**: klik *Kirim ke Temuan* di hasil Compliance Review (klausul Tidak Patuh / dengan Catatan / Perlu Verifikasi) atau Gap Analysis (Tidak / Sebagian Sesuai) — atau kirim baris terpilih. Tidak ada temuan dobel.
- Format kertas kerja temuan: **kondisi, kriteria (regulasi), rekomendasi**, tingkat **risiko**, **status tindak lanjut**, PIC, target, tanggapan — diedit langsung, tersimpan di server.
- Rekomendasi AI otomatis dipisahkan dari analisis; tautan kembali ke hasil asal; ekspor **Excel** (dropdown risiko & status + sheet ringkasan).
- **Laporan Hasil Audit** (Word yang dapat diedit / PDF): sampul, ringkasan eksekutif, ruang lingkup, tabel risiko × status, rincian setiap temuan, catatan. Ringkasan eksekutif bisa **didraf AI hanya dari temuan yang dimuat** lalu diedit; isi lainnya langsung dari data. Judul, auditee, dan ringkasan diingat untuk laporan berikutnya.

### 🔀 Bandingkan Regulasi
- **Bandingkan dua regulasi pasal demi pasal** (mis. POJK lama vs pengganti, PBI vs PADG pelaksananya) — tanpa AI, hasil dalam < 1 detik.
- Status per ketentuan: **Identik**, **Berubah** (diff kata: dihapus dicoret, baru disorot), **Padanan** (topik sama, rumusan beda — kandidat untuk diverifikasi), **Hanya di A** (kemungkinan dihapus, dengan kandidat terdekat), **Hanya di B** (ketentuan baru).
- Filter status, saring teks/pasal, ekspor CSV.

### 🎨 UI/UX
- **Beranda**: sapaan, ringkasan angka (regulasi di database, analisis tersimpan, temuan tidak patuh), alur kerja yang disarankan, aktivitas terakhir, dan tips.
- Sidebar dikelompokkan (*Analisis Dokumen*, *Pengetahuan Regulasi*), tiap fitur punya warna aksen sendiri; tipografi Plus Jakarta Sans.
- Mode **Light / Dark / Auto** (tombol cepat di bawah sidebar), responsif di desktop dan mobile, menghormati *reduced motion*.
- **Pencarian global** lintas semua analisis; `Ctrl+K` memfokuskan pencarian tabel di halaman aktif.
- **Interactive tour** 9 langkah untuk pengguna baru.

### ⚙️ Pengaturan Terintegrasi
- **Model & AI**: API key (masked), model, max tokens, rate limit, batch size.
- **Prompt AI**: 4 preset (Default, Ketat, Ringkas, Detail) dan editor 3 blok (Core / Locked / User Instructions).
- **Riwayat, Diagnostik, Panduan**, dan info versi.
- **Riwayat tersimpan di server**: semua hasil (Audit, Gap, Compliance) dibaca dari `outputs/`, jadi tidak hilang saat cache browser dibersihkan dan terlihat dari browser mana pun.

### 💰 Hemat Biaya
- **Cache tingkat file** (SHA-256, TTL 7 hari): unggah file yang sama tidak diparsing ulang.
- **Cache preview** (TTL 24 jam): analisis ulang tanpa unggah ulang.
- **Estimasi biaya** (karakter, token, request, Rupiah) sebelum data dikirim ke AI.

---

## 📋 Prasyarat

| Kebutuhan | Versi / Keterangan |
|---|---|
| Python | 3.11+ |
| pip | Versi terbaru |
| API key Gemini | [Buat di Google AI Studio](https://aistudio.google.com/app/apikey) |

---

## 🚀 Instalasi

**1. Clone repository**

```bash
git clone https://github.com/<username>/regulation-audit-assistant.git
cd regulation-audit-assistant
```

**2. Buat dan aktifkan virtual environment**

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

**3. Instal dependensi**

```bash
pip install -r requirements.txt
```

**4. Siapkan environment**

```bash
cp .env.example .env
```

Isi minimal `GEMINI_API_KEY` di file `.env`:

```env
GEMINI_API_KEY=your_api_key_here
```

> 💡 API key juga dapat diisi lewat **Pengaturan → Model & AI** setelah aplikasi berjalan.

### ⚙️ Konfigurasi

Prioritas: **Runtime settings (UI) > `.env` > default**.

```env
# Aplikasi
APP_NAME="Regulation to IT Audit Assistant"
APP_ENV=development
DEBUG=true

# Server & keamanan (lihat bagian "Keamanan" di bawah)
HOST=127.0.0.1
PORT=8000
APP_USERNAME=auditor
APP_PASSWORD=

# AI Provider
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_MAX_OUTPUT_TOKENS=8192
GEMINI_MIN_SECONDS_BETWEEN_REQUESTS=4.5

# Batching (semakin besar, semakin sedikit request)
MAX_CHARS_PER_BATCH=6000

# Upload
MAX_UPLOAD_SIZE_MB=10

# Estimasi biaya (sesuaikan dengan harga terbaru)
GEMINI_INPUT_PRICE_PER_1M_USD=0.30
GEMINI_OUTPUT_PRICE_PER_1M_USD=2.50
USD_TO_IDR=16000
```

**Pilihan model**

| Model | Kecepatan | Akurasi | Biaya | Cocok untuk |
|---|---|---|---|---|
| `gemini-2.5-flash` | Cepat | Baik | Murah | Default, semua kasus |
| `gemini-2.5-pro` | Sedang | Terbaik | Mahal | Dokumen kompleks |
| `gemini-2.0-flash` | Sangat cepat | Cukup | Sangat murah | Dokumen panjang, screening |
| `gemini-2.0-flash-lite` | Paling cepat | Dasar | Paling murah | Draft cepat |

> ℹ️ Ketersediaan dan harga model dapat berubah. Periksa [dokumentasi Gemini](https://ai.google.dev/gemini-api/docs/models) untuk informasi terbaru.

---

## ▶️ Penggunaan

Jalankan server:

```bash
python -m app
```

Secara default server hanya bisa diakses dari komputer ini (`127.0.0.1:8000`).
Buka **http://localhost:8000** di browser. Dokumentasi Swagger tersedia di **http://localhost:8000/docs**.

### Alur 1: Regulation to Audit

1. **Unggah** regulasi (PDF/TXT, maks. 10 MB).
2. Klik **Baca Struktur** (5–30 detik).
3. **Pilih bagian** di tree modal. Centang parent untuk memilih semua anaknya.
4. Periksa **estimasi biaya** di footer modal.
5. Klik **Analisis Bagian Terpilih** (1–5 menit).
6. **Review hasil** di tabel 10 kolom. Baris dengan badge ⚠️ ditandai oleh validator.
7. Isi **Status Kepatuhan** (Belum Diaudit / Patuh / Sebagian / Tidak / N/A) dan **Catatan / Temuan**.
8. **Export** ke Excel atau PDF.

### Alur 2: Gap Analysis

1. Buka **Gap Analysis** di sidebar dan unggah regulasi.
2. *(Opsional)* Isi **Batasi ke Bagian Tertentu**, misalnya `pengakhiran`, `keamanan siber`, atau `PPJTI`. Ini dapat menghemat biaya secara signifikan pada dokumen panjang.
3. Klik **Ekstrak Persyaratan**.
4. Isi status gap (Sesuai / Sebagian / Tidak / N/A), lalu **export Excel**.

### Alur 3: Pencarian Global

Buka **Cari Global**, ketik kata kunci (min. 2 karakter), lalu klik hasil untuk membuka dokumen asal dengan baris yang di-*highlight*.

### Alur 4: Kustomisasi Prompt & Model

- **Prompt**: *Pengaturan → Prompt AI* → pilih tool dan preset → ubah Prompt Inti / Instruksi Tambahan → **Preview Prompt Final** → **Simpan**.
- **Model**: *Pengaturan → Model & AI* → masukkan API key → pilih model → **Test Koneksi** → **Simpan**.

### Pintasan Keyboard

| Pintasan | Fungsi |
|---|---|
| `Ctrl + K` | Fokus ke kotak pencarian |
| `Esc` | Tutup modal / panel |

---

## 🏗️ Arsitektur

```text
┌──────────────────────────────────────────────────────┐
│              FRONTEND (Vanilla JS, no build)         │
└──────────────────────┬───────────────────────────────┘
                       │ REST API (JSON)
┌──────────────────────▼───────────────────────────────┐
│                   FASTAPI BACKEND                    │
│  ┌────────────────────────────────────────────────┐  │
│  │ Services: pdf_parser · regulation_parser ·     │  │
│  │ chunk_batcher · ai_service · audit_analyzer ·  │  │
│  │ validator · excel/pdf_exporter · caching       │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────┬───────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────┐
│ STORAGE (filesystem): uploads · outputs · cache ·    │
│ data (settings.json, prompts.json)                   │
└──────────────────────────────────────────────────────┘
```

| Layer | Teknologi |
|---|---|
| **Backend** | FastAPI 0.115, Pydantic v2, Uvicorn |
| **AI** | Google Gemini API (`google-generativeai`) |
| **Parsing PDF** | PyMuPDF (fitz) |
| **Export** | openpyxl (Excel), reportlab (PDF) |
| **Frontend** | Vanilla JS, HTML5, CSS3, Font Awesome 6 |
| **Storage** | Filesystem (JSON) |

---

## 📁 Struktur Folder

```text
regulation-audit-assistant/
├── app/
│   ├── __main__.py                 # `python -m app` (bind 127.0.0.1, guard keamanan)
│   ├── main.py                     # Aplikasi FastAPI, middleware, error handler
│   ├── config.py                   # Konfigurasi dari .env
│   ├── security.py                 # Basic Auth opsional, anti-CSRF, security headers
│   ├── api/
│   │   ├── routes.py               # Menggabungkan router per tool
│   │   ├── common.py               # Helper bersama (validasi ID & upload, lock, job)
│   │   ├── audit_routes.py         # Tool 1: preview, estimasi, analisis, export
│   │   ├── gap_routes.py           # Tool 2: Gap Analysis
│   │   ├── compliance_routes.py    # Tool 3: Compliance Review
│   │   ├── regulation_db_routes.py # Database Regulasi (RAG)
│   │   ├── settings_routes.py      # Pengaturan, uji koneksi, diagnostik
│   │   ├── search_routes.py        # Pencarian global
│   │   ├── job_routes.py           # Status & pembatalan background job
│   │   └── prompt_routes.py        # Editor prompt
│   ├── models/schemas.py           # Skema Pydantic
│   ├── prompts/                    # Prompt AI + controlled vocabulary
│   └── services/
│       ├── job_manager.py          # Background job (thread pool, status persisten)
│       ├── analysis_jobs.py        # Worker analisis untuk ketiga tool & index regulasi
│       ├── ai_service.py           # Provider Gemini (google-genai) + retry
│       ├── embedding_service.py    # Embedding Gemini
│       ├── regulation_parser.py    # Parser regulasi (state machine, PARSER_VERSION)
│       ├── contract_parser.py      # Parser kontrak
│       ├── regulation_db.py        # LanceDB: index, hybrid search, file sumber
│       ├── compliance_retrieval.py # Retrieval regulasi per klausul
│       ├── compliance_review_analyzer.py # Review per batch + validasi kutipan
│       ├── json_store.py           # Penulisan JSON atomik + lock per file
│       ├── preview_cache.py        # Cache preview/parse ber-TTL
│       └── ...                     # Exporter, validator, estimator, dst.
├── static/
│   ├── css/style.css
│   └── js/                         # ES modules (tanpa build step)
│       ├── main.js                 # Entry point & inisialisasi
│       ├── core.js                 # State, routing, tema, helper, anti-CSRF
│       ├── jobs.js                 # runJob(): progres nyata & batal
│       ├── audit.js / gap.js / compliance.js / regulation-db.js
│       └── settings.js / prompt-editor.js / history.js / search.js / tour.js / shortcuts.js
├── templates/index.html            # Single-page app
├── scripts/                        # Preload, index ulang, evaluasi retrieval
├── tests/
├── data/                           # Runtime: settings, LanceDB, file sumber regulasi (gitignored)
├── outputs/                        # Hasil analisis (gitignored)
├── cache/                          # Cache preview/parse/job (gitignored)
├── .env.example
├── requirements.txt
└── README.md
```

---

## 🔌 Dokumentasi API

Dokumentasi interaktif lengkap tersedia di `/docs` (Swagger UI).

### Preview & Analisis

| Method | Endpoint | Deskripsi |
|---|---|---|
| `POST` | `/api/preview` | Unggah dan parsing file (tanpa AI) |
| `GET` | `/api/preview/{id}` | Ambil preview dari cache |
| `POST` | `/api/estimate` | Estimasi biaya dan waktu |
| `POST` | `/api/analyze` | Analisis AI: Regulation to Audit → `202 {job_id}` |
| `POST` | `/api/analyze-requirements` | Analisis AI: Gap Analysis → `202 {job_id}` |

### Tanya Regulasi

| Method | Endpoint | Deskripsi |
|---|---|---|
| `POST` | `/api/chat` | Body `{question, regulation_ids?, history?}` → `{answer, found, cited, sources[], notes, needs_review}` |

### Bandingkan Regulasi

| Method | Endpoint | Deskripsi |
|---|---|---|
| `POST` | `/api/regulation-db/compare` | Body `{regulation_a, regulation_b}` → `{summary, thresholds, items[{status, a, b, nearest, similarity, text_ratio, diff[]}]}` |

### Daftar Temuan

| Method | Endpoint | Deskripsi |
|---|---|---|
| `GET` | `/api/findings` | Daftar temuan + ringkasan per status & risiko |
| `POST` | `/api/findings/from-source` | Body `{source_type, result_id, item_indices?}` — kirim baris hasil (tanpa `item_indices` = semua baris berstatus temuan) |
| `POST` | `/api/findings` | Temuan manual |
| `PATCH` | `/api/findings/{id}` | Ubah judul, kondisi, kriteria, rekomendasi, risiko, status, PIC, target, tanggapan |
| `DELETE` | `/api/findings/{id}` | Hapus temuan |
| `GET` | `/api/findings/export` | Unduh Excel |
| `GET` | `/api/findings/report/meta` | Pengaturan laporan terakhir |
| `POST` | `/api/findings/report/summary` | Draf ringkasan eksekutif (AI) dari temuan terpilih |
| `POST` | `/api/findings/report?format=docx\|pdf` | Body `{judul, auditee, disusun_oleh, tanggal, ringkasan, statuses, risks}` → Laporan Hasil Audit |

### Riwayat Analisis

| Method | Endpoint | Deskripsi |
|---|---|---|
| `GET` | `/api/history?limit=` | Ringkasan semua hasil tersimpan (terbaru dulu): `{items[{id, type, nama, tanggal, stats}], total}` |
| `DELETE` | `/api/history/{type}/{result_id}` | Hapus satu hasil beserta file ekspornya (`type`: `regulation_audit` / `gap_analysis` / `compliance_review`) |
| `POST` | `/api/history/clear` | Hapus semua hasil — wajib body `{"confirm": "HAPUS SEMUA"}` |

### Background Jobs

Semua proses AI yang lama (`/api/analyze`, `/api/analyze-requirements`,
`/api/compliance/analyze`, `/api/compliance/analyze-from-db`,
`/api/compliance/{id}/analyze-items`, `/api/regulation-db/upload`) berjalan
sebagai job di background. Endpoint langsung membalas `202` dengan `job_id`;
client mem-poll status, lalu mengambil hasil dari `result_url`.

| Method | Endpoint | Deskripsi |
|---|---|---|
| `GET` | `/api/jobs/{job_id}` | Status (`queued`/`running`/`succeeded`/`failed`/`cancelled`), progres, `result_url` |
| `POST` | `/api/jobs/{job_id}/cancel` | Batalkan job; batch yang sudah selesai disimpan sebagai hasil parsial |
| `GET` | `/api/jobs` | Daftar job yang sedang antre/berjalan |

Jumlah job paralel diatur lewat `MAX_CONCURRENT_JOBS` (default `1`, supaya rate limit Gemini aman).

### Manajemen Hasil

| Method | Endpoint | Deskripsi |
|---|---|---|
| `GET` | `/api/results/{id}` | Ambil hasil Regulation to Audit |
| `PATCH` | `/api/results/{id}/items/{idx}` | Edit satu item |
| `PATCH` | `/api/results/{id}/items/bulk` | Bulk update status/catatan |
| `POST` | `/api/results/{id}/items` | Tambah baris manual |
| `DELETE` | `/api/results/{id}/items` | Hapus baris terpilih |
| `GET` | `/api/requirements/{id}` | Ambil hasil Gap Analysis |
| `PATCH` | `/api/requirements/{id}/items/{idx}` | Edit satu persyaratan |
| `PATCH` | `/api/requirements/{id}/items/bulk` | Bulk update status gap |
| `POST` | `/api/requirements/{id}/items` | Tambah persyaratan |
| `DELETE` | `/api/requirements/{id}/items` | Hapus persyaratan |

### Export

| Method | Endpoint | Deskripsi |
|---|---|---|
| `GET` | `/api/export/{id}` | Excel (Regulation to Audit) |
| `GET` | `/api/export-pdf/{id}` | PDF (Regulation to Audit) |
| `GET` | `/api/export-requirements/{id}` | Excel (Gap Analysis) |

### Pengaturan, Prompt, Pencarian

| Method | Endpoint | Deskripsi |
|---|---|---|
| `GET` / `PUT` | `/api/settings` | Baca / ubah konfigurasi runtime (API key di-mask) |
| `POST` | `/api/settings/test-connection` | Uji koneksi Gemini |
| `GET` | `/api/diagnostics` | Info diagnostik server |
| `GET` / `PUT` | `/api/prompts/{tool}` | Baca / ubah prompt override |
| `POST` | `/api/prompts/{tool}/reset` | Reset prompt ke default |
| `POST` | `/api/prompts/{tool}/preview` | Preview prompt final |
| `GET` | `/api/prompts/{tool}/presets` | Daftar preset |
| `GET` | `/api/search` | Pencarian lintas dokumen |
| `GET` | `/health` | Health check |

- `{tool}` bernilai `regulation_audit` atau `gap_analysis`.
- Parameter `/api/search`: `q` (wajib, min. 2 karakter), `tools` (`all` / `regulation_audit` / `gap_analysis`), `days`, `limit` (default 100, maks. 500).

---

## 🌐 Deployment

| Opsi | Biaya | Kelebihan | Catatan |
|---|---|---|---|
| **Oracle Cloud Always Free** ⭐ | Gratis | Storage persisten, always-on | Setup 60–90 menit, perlu dasar SSH |
| **Railway** | Berbayar | Setup ±5 menit, tanpa urusan SSL | Pasang volume persisten |
| **Render (free)** | Gratis | Setup ±10 menit | Sleep saat idle; storage ephemeral |
| **VPS umum** | ±$5–6/bln | Setup cepat | Pilih region Singapore |
| **Docker** | — | Portabel | Lihat di bawah |

> ⚠️ **Vercel tidak cocok**: analisis AI berjalan lama, membutuhkan penyimpanan persisten, dan file unggahan bisa melebihi batas request.

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/
COPY templates/ ./templates/

RUN mkdir -p data outputs cache
EXPOSE 8000

# HOST=0.0.0.0 di container WAJIB disertai APP_PASSWORD (server menolak start tanpa itu).
ENV HOST=0.0.0.0 PORT=8000 DEBUG=false
CMD ["python", "-m", "app"]
```

```bash
docker build -t audit-assistant .
docker run -d -p 127.0.0.1:8000:8000 \
  -e GEMINI_API_KEY=your_api_key_here \
  -e APP_PASSWORD=ganti-dengan-password-kuat \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/outputs:/app/outputs \
  -v $(pwd)/cache:/app/cache \
  --name audit-app \
  audit-assistant
```

Publikasikan ke jaringan hanya lewat reverse proxy ber-HTTPS (mis. Caddy/Nginx):
Basic Auth mengirim password di setiap request, jadi tanpa HTTPS password bisa disadap.

### 🔒 Keamanan

| Aspek | Perilaku |
|---|---|
| **Akses** | Default bind `127.0.0.1`. `python -m app` menolak bind ke alamat jaringan tanpa `APP_PASSWORD` (kecuali `ALLOW_INSECURE_REMOTE=true`). |
| **Autentikasi** | Isi `APP_PASSWORD` (dan opsional `APP_USERNAME`) → seluruh UI, API, dan file export dilindungi HTTP Basic Auth. `/health` tetap publik. |
| **Anti-CSRF** | Request yang mengubah data ke `/api` wajib header `X-Requested-With: RAA` (frontend mengirimnya otomatis). |
| **File upload** | Tidak disimpan: di-parse dari file sementara lalu langsung dihapus. Yang disimpan hanya hasil parse (cache ber-TTL) dan, untuk Regulation DB, salinan file sumber agar bisa di-index ulang. |
| **Retensi cache** | Preview 24 jam; hasil parse & preview Compliance Review (berisi teks kontrak) 7 hari; status job 7 hari. Hasil analisis di `outputs/` disimpan sampai dihapus pengguna. |
| **Error** | Error tak terduga hanya mengembalikan kode pelacakan; detailnya di log server. |
| **Endpoint destruktif** | Reset Regulation DB wajib body `{"confirm": "HAPUS SEMUA"}`. |
| **API key** | Disimpan apa adanya di `data/settings.json` (tidak masuk git). Lindungi folder `data/`. |

### Kebutuhan Resource (±5 pengguna bersamaan)

| Resource | Minimum | Disarankan |
|---|---|---|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 2 GB | 4 GB |
| Storage | 20 GB | 50 GB |

Beban utama ada di Gemini API, bukan di server.

---

## 🧪 Testing

```bash
pytest tests/ -v
```

**Checklist manual setelah perubahan:**

- [ ] Unggah PDF → tree preview muncul
- [ ] Pilih bagian → analisis → hasil muncul
- [ ] Edit sel inline dan bulk update status tersimpan
- [ ] Export Excel (10 kolom) dan PDF (layout) benar
- [ ] Gap Analysis, Cari Global, Panel Pengaturan, dan Prompt Editor berfungsi
- [ ] Dark mode dan interactive tour berjalan normal

### Evaluasi akurasi AI

Jalankan setiap kali **prompt, model Gemini, parser, atau retrieval** diubah — supaya dampaknya terlihat sebagai angka, bukan tebakan.

```bash
# Compliance Review: 16 klausul kontrak penyedia jasa TI vs POJK 11/2022 (memanggil Gemini, ±2 menit)
python -m scripts.eval_compliance
# Retrieval Regulation DB: 25 query, hit@5 & MRR (embedding query di-cache)
python -m scripts.eval_retrieval
```

`eval_compliance` melaporkan akurasi ketat/longgar, **critical miss** (ketidakpatuhan yang dinilai patuh — kesalahan paling berbahaya), false alarm, dan ketepatan sitasi pasal; membandingkan otomatis dengan laporan sebelumnya (`cache/eval_reports/`). Opsi `--min-lenient 0.8 --max-critical 0` membuatnya gagal bila mutu turun. Set uji & alasan setiap label ada di `scripts/compliance_eval/expected.json` (draf — tinjau sebagai auditor).

| Versi | Akurasi ketat | Akurasi longgar | Critical miss | Sitasi benar |
|---|---|---|---|---|
| Sebelum daftar isi kontrak | 62% | 75% | 0 | 92% |
| Dengan daftar isi kontrak (2 run) | 81–88% | 94% | 0 | 92% |

---

## ❓ FAQ

<details>
<summary><b>Berapa biaya penggunaannya?</b></summary>

Tools ini gratis. Biaya hanya berasal dari Gemini API, dengan perkiraan **Rp 500–3.000 per dokumen 200 halaman** (bergantung model dan harga saat ini). Hemat dengan memilih bagian spesifik, memakai model yang lebih murah, dan memanfaatkan cache.
</details>

<details>
<summary><b>Apakah aman mengunggah dokumen?</b></summary>

Aplikasi tidak menyimpan data ke cloud pihak ketiga. Konten hanya dikirim ke Gemini API saat analisis. Aman untuk regulasi publik, tetapi **jangan unggah dokumen rahasia atau data klien**.
</details>

<details>
<summary><b>Bisa dipakai multi-user?</b></summary>

Belum ada sistem login. Tim kecil dapat mengakses satu instance bersamaan, tetapi data tidak terisolasi per pengguna. Kontribusi fitur multi-user sangat diterima.
</details>

<details>
<summary><b>Mengapa analisis lama?</b></summary>

Waktu bergantung pada jumlah chunk (±30–60 detik per batch), rate limit (jeda 4,5 detik antar request), dan model yang dipakai. Untuk dokumen besar, analisis per bagian.
</details>

<details>
<summary><b>Muncul error "Your project has been denied access"?</b></summary>

Periksa: (1) API key valid lewat **Test Koneksi**, (2) rate limit, tunggu 15–30 menit, (3) nama model valid, (4) status project Google Cloud.
</details>

<details>
<summary><b>Hasil kosong untuk pasal tertentu?</b></summary>

Kemungkinan pasal hanya berisi definisi, tidak relevan dengan audit TI, atau prompt/validasi terlalu ketat. Coba preset **Default** atau **Detail**, dan periksa `validation_notes` pada baris terkait.
</details>

<details>
<summary><b>Data hilang setelah restart?</b></summary>

Pada platform dengan storage ephemeral (mis. Render free tier), data hilang saat redeploy. Gunakan VPS atau volume persisten.
</details>

---

## ⚠️ Disclaimer

Aplikasi ini adalah **alat bantu**, bukan pengganti pertimbangan profesional auditor. **Hasil AI harus selalu diverifikasi** terhadap dokumen asli oleh auditor yang kompeten sebelum digunakan dalam keputusan audit formal.

- ✅ **Gunakan untuk**: regulasi publik (POJK, PADK, SEOJK, PBI), dokumen yang boleh dibagikan ke pihak ketiga, dan latihan/simulasi audit.
- ❌ **Jangan unggah**: dokumen rahasia klien, data sensitif nasabah/keuangan, dokumen internal perusahaan, atau file pribadi.
- API key disimpan di `data/settings.json` dalam bentuk teks biasa. Lindungi akses ke server dan jangan meng-commit folder `data/`.

Pengguna bertanggung jawab penuh atas keputusan audit yang dibuat berdasarkan hasil aplikasi ini.

---

## 🤝 Kontribusi

Kontribusi berupa laporan bug, fitur, dokumentasi, maupun perbaikan typo sangat diterima.

1. **Fork** repository ini.
2. Buat branch fitur:
```bash
   git checkout -b feature/nama-fitur
```
3. **Commit** perubahan dengan format `[kategori] Deskripsi singkat`:
```bash
   git commit -m "[feat] Tambah dukungan DOCX"
```
4. **Push** dan buka **Pull Request**:
```bash
   git push origin feature/nama-fitur
```

**Panduan gaya**

- **Python**: PEP 8, type hints pada fungsi publik, docstring Google style, format dengan `black app/`.
- **JavaScript**: Vanilla JS (ES2020+), gunakan `const`/`let`, nama variabel deskriptif.

**Ide kontribusi**

- **Backend**: dukungan DOCX, OCR untuk PDF hasil scan, RAG dengan vector DB, provider AI alternatif, perbandingan regulasi lama vs revisi.
- **Frontend**: PWA, mode offline, editor rich text untuk kolom catatan.
- **DevOps**: Docker Compose, CI/CD dengan GitHub Actions, monitoring, backup otomatis.
- **Keamanan**: autentikasi dan isolasi data multi-user.

**Melaporkan bug**: buka Issue dengan deskripsi (aktual vs harapan), langkah reproduksi, environment (OS, Python, browser), screenshot, dan log traceback.

---

## 📝 Changelog

### v1.0.0 — September 2026
- Parser dual-mode (POJK + PADK) dan tree hierarki interaktif
- Analisis AI dengan Gemini, validasi anti-halusinasi
- Kertas kerja audit 10 kolom (editable) dan Gap Analysis
- Export Excel dan PDF, pencarian global
- Panel pengaturan terintegrasi, prompt editor dengan 4 preset
- Cache SHA-256, interactive tour, mode Light/Dark

---

## 📄 Lisensi

Proyek ini dilisensikan di bawah [MIT License](LICENSE). Bebas digunakan, dimodifikasi, dan didistribusikan.

## 👤 Penulis

**[Dony Kurniawan]**
GitHub: [@username](https://github.com/kurniawan-Donn) · LinkedIn: [linkedin.com/in/username](https://linkedin.com/in/username) · Email: your.email@example.com

## 🙏 Ucapan Terima Kasih

[FastAPI](https://fastapi.tiangolo.com/) · [Google Gemini](https://ai.google.dev/) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [openpyxl](https://openpyxl.readthedocs.io/) · [reportlab](https://www.reportlab.com/) · [Font Awesome](https://fontawesome.com/) · komunitas auditor TI Indonesia.

<div align="center">

Dibuat dengan ❤️ untuk auditor Indonesia · ⭐ Beri bintang jika proyek ini bermanfaat!

[⬆ Kembali ke atas](#️-regulation-to-it-audit-assistant)

</div>
