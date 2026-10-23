# Membuat Rilis (Setup.exe untuk pengguna)

Installer Windows **tidak dibuat dengan tangan dan tidak disimpan di repo**. Ia dibangun otomatis oleh GitHub Actions dari kode pada tag versi, sehingga selalu sesuai dengan kode yang dirilis.

```
Perbaiki kode ──▶ PR & merge ke main ──▶ git tag v1.1.0 ──▶ GitHub Actions ──▶ Release v1.1.0
 (start.bat)        (test otomatis)        git push tag        test + build        Setup.exe + ZIP
                                                                                       │
                              Aplikasi pengguna: "Versi 1.1.0 tersedia — Unduh" ◀──────┘
```

## Alur sehari-hari

1. **Kerjakan perbaikan seperti biasa** — uji dengan `start.bat`, commit, PR, merge ke `main`. Pengguna belum terpengaruh.
2. **Saat siap dibagikan**, beri tag versi pada `main` yang terbaru:

   ```bash
   git switch main && git pull
   git tag v1.1.0
   git push origin v1.1.0
   ```

3. Workflow **Release** (`.github/workflows/release.yml`) berjalan di Windows (±10–15 menit):
   - menjalankan seluruh test — bila gagal, **tidak ada rilis**;
   - membangun bundel (Python embeddable resmi + semua paket) dan uji asap: server dari bundel harus menjawab `/health`;
   - membuat `AuditAssistant-1.1.0-Setup.exe`, `AuditAssistant-1.1.0-Portable.zip`, dan `SHA256SUMS.txt`;
   - menerbitkan **GitHub Release v1.1.0** dengan catatan perubahan otomatis.
4. Dalam beberapa jam aplikasi pengguna menampilkan spanduk **"Versi 1.1.0 tersedia"** (cek di-cache 6 jam; Pengaturan → Tentang → *Periksa pembaruan* untuk langsung).

## Penomoran versi

`MAYOR.MINOR.PATCH` — mis. `1.1.0` fitur baru, `1.1.1` perbaikan kecil, `2.0.0` perubahan besar.

- Versi aplikasi berasal dari **tag**. Build menulisnya ke salinan `app/version.py` di dalam paket.
- Setelah merilis, perbarui `app/version.py` di repo ke versi yang sama (agar `start.bat` dan Docker menampilkan versi yang benar) lewat PR biasa.
- Tag yang sudah terbit jangan dipindah; untuk koreksi buat versi baru (`v1.1.1`).

## Uji paket sebelum rilis

- **PR** yang mengubah `installer/`, `scripts/build_installer.py`, `scripts/launch.py`, `requirements.txt`, atau workflow rilis otomatis membangun paket tanpa menerbitkan rilis. Unduh hasilnya dari tab **Actions → Release → Artifacts**.
- Manual dari tab **Actions → Release → Run workflow**.
- Lokal (Windows, Python 3.13): `python -m scripts.build_installer --skip-setup` membuat ZIP portable di `dist/`; pasang [Inno Setup 6.5+](https://jrsoftware.org/isdl.php) untuk ikut membuat Setup.exe.

## Isi paket

| Bagian | Lokasi setelah dipasang |
|---|---|
| Program (Python bawaan, paket, kode) | `%LOCALAPPDATA%\Programs\Audit Assistant` — diganti setiap update |
| Data pengguna (DB regulasi, temuan, riwayat, pengaturan & API key, log) | `%LOCALAPPDATA%\Audit Assistant` — tidak disentuh update/uninstall |
| Pengaturan lanjutan (opsional) | `%LOCALAPPDATA%\Audit Assistant\.env` (mis. `PORT`, `UPDATE_CHECK=false`) |

Klik ikon saat aplikasi sudah berjalan hanya membuka browser ke aplikasi yang sama (tidak menjalankan server kedua). Log server: `%LOCALAPPDATA%\Audit Assistant\logs\server.log`.

## Catatan

- **Windows SmartScreen**: tanpa sertifikat *code signing* (berbayar), pengguna melihat *Windows protected your PC* saat pertama menjalankan Setup → **More info → Run anyway**. Peringatan berkurang seiring makin banyak unduhan; bila perlu hilang sama sekali, beli sertifikat code signing dan tambahkan langkah penandatanganan di workflow.
- **Jaringan tanpa internet**: cek pembaruan gagal diam-diam (aplikasi tetap jalan); matikan dengan `UPDATE_CHECK=false`.
- Terjemahan wizard `installer/Indonesian.isl` berasal dari repositori Inno Setup (terjemahan komunitas) dan membutuhkan Inno Setup 6.5+.
