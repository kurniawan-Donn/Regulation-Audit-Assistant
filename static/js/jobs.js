/**
 * Background job: runJob() menjalankan endpoint 202 + job_id, mem-poll progres
 * nyata, dan menampilkan tombol Batalkan.
 */

// ====== BACKGROUND JOBS ======
// Analisis AI berjalan sebagai job di server: endpoint membalas 202 + job_id,
// lalu kita poll /api/jobs/{id} untuk progres NYATA (per batch) sampai selesai.
const JOB_POLL_MS = 1000;
const JOB_MAX_POLL_FAILURES = 5;

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function readErrorDetail(res) {
    try {
        const body = await res.json();
        if (typeof body.detail === 'string') return body.detail;
        if (Array.isArray(body.detail)) return body.detail.map(d => d.msg).join('; ');
    } catch (_) { /* body bukan JSON */ }
    return `HTTP ${res.status}`;
}

function jobPercent(job) {
    if (job.status === 'queued' || !job.progress_total) return 3;
    return Math.max(3, Math.min(99, Math.round((job.progress_done / job.progress_total) * 100)));
}

function jobLabel(job) {
    if (job.status === 'queued') {
        return job.queue_position > 1
            ? `Menunggu antrean (posisi ${job.queue_position})...`
            : 'Menunggu giliran...';
    }
    return job.message || 'Memproses...';
}

function createJobCancelButton(jobId) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-ghost btn-sm job-cancel-btn';
    btn.innerHTML = '<i class="fas fa-stop"></i> Batalkan';
    btn.addEventListener('click', async () => {
        if (!confirm('Batalkan proses ini? Batch yang sudah selesai tetap disimpan sebagai hasil parsial (jika ada).')) return;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Membatalkan...';
        try {
            await fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
        } catch (_) { /* polling akan tetap melaporkan status akhir */ }
    });
    return btn;
}

/**
 * Jalankan endpoint berbasis job dan tunggu sampai selesai.
 *
 * @param {string} url          endpoint yang membalas 202 {job_id}
 * @param {RequestInit} init    opsi fetch (method, body, headers)
 * @param {object} opts
 *   - onProgress(job, percent, label): dipanggil setiap poll
 *   - cancelAnchor: elemen; tombol "Batalkan" disisipkan setelahnya
 * @returns {Promise<{ok, job, data, partial, cancelled, error}>}
 *   data = isi GET job.result_url (hasil lengkap), jika ada.
 */
export async function runJob(url, init, opts = {}) {
    const res = await fetch(url, init);
    if (!res.ok) return { ok: false, error: await readErrorDetail(res) };
    const { job_id: jobId } = await res.json();

    let cancelBtn = null;
    if (opts.cancelAnchor) {
        cancelBtn = createJobCancelButton(jobId);
        opts.cancelAnchor.insertAdjacentElement('afterend', cancelBtn);
    }

    try {
        let failures = 0;
        for (;;) {
            await sleep(JOB_POLL_MS);
            let job;
            try {
                const r = await fetch(`/api/jobs/${jobId}`);
                if (!r.ok) throw new Error(await readErrorDetail(r));
                job = await r.json();
                failures = 0;
            } catch (err) {
                if (++failures >= JOB_MAX_POLL_FAILURES) {
                    return { ok: false, error: `Koneksi ke server terputus (${err.message}). Proses mungkin masih berjalan di server.` };
                }
                continue;
            }

            if (opts.onProgress) opts.onProgress(job, jobPercent(job), jobLabel(job));

            const finishedWithResult = job.status === 'succeeded'
                || (job.status === 'cancelled' && job.partial);
            if (finishedWithResult) {
                let data = null;
                if (job.result_url) {
                    const r = await fetch(job.result_url);
                    if (!r.ok) return { ok: false, job, error: await readErrorDetail(r) };
                    data = await r.json();
                }
                return { ok: true, job, data, partial: job.status === 'cancelled' };
            }
            if (job.status === 'failed') {
                return { ok: false, job, error: job.error || 'Proses gagal.' };
            }
            if (job.status === 'cancelled') {
                return { ok: false, job, cancelled: true, error: 'Dibatalkan oleh pengguna.' };
            }
        }
    } finally {
        if (cancelBtn) cancelBtn.remove();
    }
}
