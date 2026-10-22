/**
 * Database Regulasi (RAG): upload & index, daftar, index ulang, detail chunk.
 */

import {
    $,
    $$,
    escapeAttr,
    escapeHtml,
    formatFileSize,
    onPageEnter,
    showToast,
} from './core.js';
import { runJob } from './jobs.js';

// ============================================================
// END OF COMPLIANCE MODE SELECTOR
// ============================================================

// ============================================================
// REGULATION DATABASE (RAG)
// ============================================================

const regDbState = {
    stats: null,
    regulations: [],
    loading: false,
};

// ---- DOM Refs ----
const regdbStatTotal = $('#regdbStatTotal');
const regdbStatChunks = $('#regdbStatChunks');
const regdbStatSize = $('#regdbStatSize');
const regdbUploadForm = $('#regdbUploadForm');
const regdbNameInput = $('#regdbNameInput');
const regdbFileInput = $('#regdbFileInput');
const regdbFileDisplay = $('#regdbFileDisplay');
const regdbFileInputWrap = document.querySelector('.regdb-file-input-wrap');
const regdbSubmitBtn = $('#regdbSubmitBtn');
const regdbStatusEl = $('#regdbStatus');
const regdbProgressContainer = $('#regdbProgressContainer');
const regdbProgressBar = $('#regdbProgressBar');
const regdbProgressText = $('#regdbProgressText');
const regdbListContainer = $('#regdbListContainer');
const regdbRefreshBtn = $('#regdbRefreshBtn');
const regdbResetBtn = $('#regdbResetBtn');

// ---- Status / Progress ----
function setRegDbStatus(text, isError) {
    if (!regdbStatusEl) return;
    regdbStatusEl.className = 'status-text';
    if (isError === true) {
        regdbStatusEl.classList.add('error');
        regdbStatusEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${escapeHtml(text)}`;
    } else if (isError === false) {
        regdbStatusEl.classList.add('success');
        regdbStatusEl.innerHTML = `<i class="fas fa-check-circle"></i> ${escapeHtml(text)}`;
    } else {
        regdbStatusEl.textContent = text;
    }
}

function setRegDbProgress(percent, text) {
    if (!regdbProgressContainer) return;
    regdbProgressContainer.style.display = 'block';
    regdbProgressBar.style.width = percent + '%';
    regdbProgressText.textContent = text || `${Math.round(percent)}%`;
    if (percent >= 100) {
        setTimeout(() => {
            regdbProgressContainer.style.display = 'none';
            regdbProgressText.textContent = '';
        }, 1500);
    }
}

function hideRegDbProgress() {
    if (!regdbProgressContainer) return;
    regdbProgressContainer.style.display = 'none';
    regdbProgressText.textContent = '';
    regdbProgressBar.style.width = '0%';
}

// ---- Page Load ----
async function loadRegulationDbPage() {
    await Promise.all([
        loadRegDbStats(),
        loadRegDbList(),
    ]);
}

// ---- Load Stats ----
async function loadRegDbStats() {
    try {
        const res = await fetch('/api/regulation-db/stats');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        regDbState.stats = data;

        if (regdbStatTotal) {
            regdbStatTotal.textContent = data.total_regulations || 0;
        }
        if (regdbStatChunks) {
            regdbStatChunks.textContent = (data.total_chunks || 0).toLocaleString('id-ID');
        }
        if (regdbStatSize) {
            regdbStatSize.textContent = `${data.db_size_mb || 0} MB`;
        }
    } catch (err) {
        console.warn('Gagal load stats:', err);
        if (regdbStatTotal) regdbStatTotal.textContent = '—';
        if (regdbStatChunks) regdbStatChunks.textContent = '—';
        if (regdbStatSize) regdbStatSize.textContent = '—';
    }
}

// ---- Load List ----
async function loadRegDbList() {
    if (!regdbListContainer) return;
    regdbListContainer.innerHTML = `
            <div class="regdb-loading">
                <i class="fas fa-spinner fa-spin"></i> Memuat...
            </div>
        `;

    try {
        const res = await fetch('/api/regulation-db/regulations');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        regDbState.regulations = data.regulations || [];
        renderRegDbList();
    } catch (err) {
        regdbListContainer.innerHTML = `
                <div class="regdb-empty">
                    <i class="fas fa-exclamation-circle"></i>
                    <strong>Gagal memuat data</strong>
                    <span>${escapeHtml(err.message)}</span>
                </div>
            `;
    }
}

// ---- Render List ----
function renderRegDbList() {
    if (!regdbListContainer) return;

    const regs = regDbState.regulations;

    if (regs.length === 0) {
        regdbListContainer.innerHTML = `
                <div class="regdb-empty">
                    <i class="fas fa-database"></i>
                    <strong>Belum ada regulasi</strong>
                    <span>Upload regulasi pertama Anda di form atas.</span>
                </div>
            `;
        return;
    }

    regdbListContainer.innerHTML = regs.map(r => {
        const isPreload = r.source_type === 'preload';
        const badge = isPreload
            ? `<span class="regdb-item-badge regdb-badge-preload">Preload</span>`
            : `<span class="regdb-item-badge regdb-badge-manual">Manual</span>`;
        // Dibuat dengan parser/embedding versi lama → hasil retrieval kurang akurat.
        const staleBadge = r.needs_reindex
            ? `<span class="regdb-item-badge regdb-badge-stale"
                         title="${r.has_source
                             ? 'Di-index dengan parser/embedding versi lama. Klik Index Ulang.'
                             : 'Versi lama & file sumber tidak tersimpan — hapus lalu upload ulang.'}">Perlu index ulang</span>`
            : '';
        const reindexBtn = r.needs_reindex && r.has_source
            ? `<button class="regdb-item-reindex" data-reindex-reg-id="${escapeAttr(r.id)}" title="Index ulang dengan parser & embedding terbaru">
                       <i class="fas fa-rotate"></i>
                   </button>`
            : '';

        const date = r.created_at
            ? new Date(r.created_at).toLocaleDateString('id-ID', {
                day: 'numeric', month: 'short', year: 'numeric'
            })
            : '—';

        return `
                <div class="regdb-item" data-reg-id="${escapeAttr(r.id)}">
                    <div class="regdb-item-icon ${isPreload ? 'preload' : ''}">
                        <i class="fas fa-file-contract"></i>
                    </div>
                    <div class="regdb-item-body">
                        <div class="regdb-item-name">
                            ${escapeHtml(r.name)}
                            ${badge}
                            ${staleBadge}
                        </div>
                        <div class="regdb-item-meta">
                            <span><i class="fas fa-cubes"></i> ${(r.total_chunks || 0).toLocaleString('id-ID')} chunks</span>
                            <span><i class="fas fa-file"></i> <code>${escapeHtml(r.filename || '-')}</code></span>
                            <span><i class="fas fa-calendar"></i> ${date}</span>
                        </div>
                    </div>
                    ${reindexBtn}
                    <button class="regdb-item-delete" data-delete-reg-id="${escapeAttr(r.id)}" title="Hapus regulasi">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
    }).join('');

    regdbListContainer.querySelectorAll('[data-reindex-reg-id]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            handleReindexRegulation(btn.dataset.reindexRegId, btn);
        });
    });

    // Attach delete handlers
    regdbListContainer.querySelectorAll('[data-delete-reg-id]').forEach(btn => {
        btn.addEventListener('click', () => {
            const regId = btn.dataset.deleteRegId;
            handleDeleteRegulation(regId);
        });
    });

            // Attach click → buka detail (kecuali tombol delete)
    regdbListContainer.querySelectorAll('.regdb-item').forEach(item => {
        item.addEventListener('click', (e) => {
            // Kalau yang diklik tombol delete / index ulang, skip
            if (e.target.closest('[data-delete-reg-id], [data-reindex-reg-id]')) return;

            const regId = item.dataset.regId;
            if (regId) openRegDbDetail(regId);
        });

        // Cursor pointer
        item.style.cursor = 'pointer';
        item.title = 'Klik untuk lihat detail chunks';
    });

}

// ---- Index Ulang Regulation ----
async function handleReindexRegulation(regId, btn) {
    const reg = regDbState.regulations.find(r => r.id === regId);
    if (!reg) return;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    setRegDbStatus(`Mengindex ulang "${reg.name}"...`, null);
    try {
        const run = await runJob(`/api/regulation-db/regulations/${regId}/reindex`, { method: 'POST' }, {
            onProgress: (job, pct, label) => setRegDbProgress(pct, `${reg.name}: ${label}`),
        });
        hideRegDbProgress();
        if (!run.ok) {
            setRegDbStatus(`Gagal index ulang: ${run.error}`, true);
            showToast('Index ulang gagal: ' + run.error, 'error');
            return;
        }
        setRegDbStatus(run.job.message, false);
        showToast(run.job.message, 'success');
        await loadRegulationDbPage();
    } catch (err) {
        setRegDbStatus(`Gagal: ${err.message}`, true);
        showToast('Gagal terhubung ke server.', 'error');
    } finally {
        btn.disabled = false;
    }
}

// ---- Delete Regulation ----
async function handleDeleteRegulation(regId) {
    const reg = regDbState.regulations.find(r => r.id === regId);
    if (!reg) return;

    const confirmed = confirm(
        `Hapus regulasi "${reg.name}" dari database?\n\n` +
        `${reg.total_chunks} chunks akan dihapus permanen.\n` +
        `Regulasi yang menggunakan ini di Compliance Review tidak akan ` +
        `terpengaruh (data review tetap tersimpan).`
    );
    if (!confirmed) return;

    try {
        const res = await fetch(`/api/regulation-db/regulations/${regId}`, {
            method: 'DELETE',
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        showToast(data.message || 'Regulasi dihapus.', 'success');
        await loadRegulationDbPage();
    } catch (err) {
        showToast(`Gagal menghapus: ${err.message}`, 'error');
    }
}

// ---- File Display ----
if (regdbFileInput) {
    regdbFileInput.addEventListener('change', () => {
        if (!regdbFileDisplay) return;

        if (regdbFileInput.files.length) {
            const f = regdbFileInput.files[0];
            regdbFileDisplay.innerHTML = `
                    <i class="fas fa-file-check"></i>
                    <span>${escapeHtml(f.name)} (${formatFileSize(f.size)})</span>
                `;
            if (regdbFileInputWrap) regdbFileInputWrap.classList.add('has-file');
        } else {
            regdbFileDisplay.innerHTML = `
                    <i class="fas fa-file"></i>
                    <span>Klik untuk pilih file</span>
                `;
            if (regdbFileInputWrap) regdbFileInputWrap.classList.remove('has-file');
        }
    });
}

// ---- Auto-fill name dari filename ----
if (regdbFileInput && regdbNameInput) {
    regdbFileInput.addEventListener('change', () => {
        if (!regdbNameInput.value.trim() && regdbFileInput.files.length) {
            const fname = regdbFileInput.files[0].name;
            const stem = fname.replace(/\.[^.]+$/, '');
            // Normalisasi: POJK_11_2022 -> POJK 11/2022
            let name = stem.replace(/_/g, ' ').replace(/-/g, ' ');
            name = name.replace(/\s+/g, ' ').trim();
            // Pattern NAMA NOMOR TAHUN
            const parts = name.split(' ');
            if (parts.length >= 3 && /^\d{4}$/.test(parts[parts.length - 1])
                && /^\d{1,3}$/.test(parts[parts.length - 2])) {
                name = parts.slice(0, -2).join(' ') + ' ' +
                       parts[parts.length - 2] + '/' + parts[parts.length - 1];
            }
            regdbNameInput.value = name;
        }
    });
}

// ---- Upload Handler ----
if (regdbUploadForm) {
    regdbUploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (!regdbFileInput || !regdbFileInput.files.length) {
            showToast('Pilih file terlebih dahulu.', 'error');
            return;
        }
        if (!regdbNameInput || !regdbNameInput.value.trim()) {
            showToast('Isi nama regulasi terlebih dahulu.', 'error');
            return;
        }

        const file = regdbFileInput.files[0];
        if (file.size > 10 * 1024 * 1024) {
            showToast('File terlalu besar. Maks 10 MB.', 'error');
            return;
        }

        regdbSubmitBtn.disabled = true;
        regdbSubmitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Memproses...';
        setRegDbStatus('Meng-extract, embed, dan simpan ke database...', null);
        setRegDbProgress(15, 'Meng-extract teks...');

        const fd = new FormData();
        fd.append('file', file);
        fd.append('name', regdbNameInput.value.trim());

        try {
            const run = await runJob('/api/regulation-db/upload', {
                method: 'POST',
                body: fd,
            }, {
                cancelAnchor: regdbProgressText,
                onProgress: (job, pct, label) => setRegDbProgress(15 + pct * 0.85, label),
            });

            if (!run.ok) {
                hideRegDbProgress();
                setRegDbStatus(`Gagal: ${run.error}`, true);
                showToast(run.cancelled ? 'Upload dibatalkan.' : 'Upload gagal: ' + run.error,
                    run.cancelled ? 'info' : 'error');
                return;
            }
            setRegDbProgress(100, 'Selesai!');

            const regulation = run.job.extra.regulation;
            setRegDbStatus(run.job.message || 'Regulasi berhasil di-index.', false);
            showToast(`Regulasi "${regulation.name}" di-index (${regulation.total_chunks} chunks).`, 'success');

            // Reset form
            regdbNameInput.value = '';
            regdbFileInput.value = '';
            if (regdbFileDisplay) {
                regdbFileDisplay.innerHTML = `
                        <i class="fas fa-file"></i>
                        <span>Klik untuk pilih file</span>
                    `;
            }
            if (regdbFileInputWrap) regdbFileInputWrap.classList.remove('has-file');

            // Refresh list + stats
            await loadRegulationDbPage();
        } catch (err) {
            setRegDbStatus(`Gagal: ${err.message}`, true);
            showToast('Gagal terhubung ke server.', 'error');
        } finally {
            regdbSubmitBtn.disabled = false;
            regdbSubmitBtn.innerHTML = '<i class="fas fa-plus"></i> Upload &amp; Index';
            setTimeout(hideRegDbProgress, 1500);
        }
    });
}

// ---- Refresh Button ----
if (regdbRefreshBtn) {
    regdbRefreshBtn.addEventListener('click', async () => {
        regdbRefreshBtn.disabled = true;
        regdbRefreshBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Refresh...';
        await loadRegulationDbPage();
        regdbRefreshBtn.disabled = false;
        regdbRefreshBtn.innerHTML = '<i class="fas fa-rotate"></i> Refresh';
        showToast('Data di-refresh.', 'success');
    });
}

// ---- Reset DB Button ----
if (regdbResetBtn) {
    regdbResetBtn.addEventListener('click', async () => {
        const total = regDbState.regulations.length;
        if (total === 0) {
            showToast('Database sudah kosong.', 'info');
            return;
        }

        // Confirm 2x (dangerous operation)
        const ok1 = confirm(
            `Hapus SEMUA ${total} regulasi dari database?\n\n` +
            `Ini akan menghapus semua data index regulasi.\n` +
            `Tindakan ini TIDAK BISA dibatalkan.`
        );
        if (!ok1) return;

        const typed = prompt(
            'Konfirmasi terakhir: ketik HAPUS SEMUA untuk menghapus seluruh regulasi ' +
            '(termasuk file sumbernya).'
        );
        if (typed === null) return;
        if (typed.trim() !== 'HAPUS SEMUA') {
            showToast('Konfirmasi tidak cocok — database tidak direset.', 'info');
            return;
        }

        regdbResetBtn.disabled = true;
        regdbResetBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Reset...';

        try {
            const res = await fetch('/api/regulation-db/reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ confirm: 'HAPUS SEMUA' }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            showToast(data.message || 'Database direset.', 'success');
            await loadRegulationDbPage();
        } catch (err) {
            showToast(`Gagal reset: ${err.message}`, 'error');
        } finally {
            regdbResetBtn.disabled = false;
            regdbResetBtn.innerHTML = '<i class="fas fa-trash-can"></i> Reset DB';
        }
    });
}


    // ============================================================
// REGULATION DB — DETAIL VIEWER (Chunks)
// ============================================================

const regDbDetailState = {
    regulationId: null,
    regulationName: '',
    currentPage: 1,
    pageSize: 20,
    totalPages: 0,
    total: 0,
    search: '',
    anomaly: '',
    searchDebounceTimer: null,
    expandedChunks: new Set(),
};

// ---- DOM Refs ----
const regdbDetailOverlay = $('#regdbDetailOverlay');
const regdbDetailClose = $('#regdbDetailClose');
const regdbDetailTitle = $('#regdbDetailTitle');
const regdbDetailSubtitle = $('#regdbDetailSubtitle');
const regdbDetailStats = $('#regdbDetailStats');
const regdbDetailSearch = $('#regdbDetailSearch');
const regdbDetailFilters = $$('.regdb-filter-btn');
const regdbDetailLoading = $('#regdbDetailLoading');
const regdbChunksList = $('#regdbChunksList');
const regdbDetailEmpty = $('#regdbDetailEmpty');
const regdbPageInfo = $('#regdbPageInfo');
const regdbPrevPage = $('#regdbPrevPage');
const regdbNextPage = $('#regdbNextPage');

// ---- Open Detail Modal ----
async function openRegDbDetail(regulationId) {
    const reg = regDbState.regulations.find(r => r.id === regulationId);
    if (!reg) {
        showToast('Regulasi tidak ditemukan.', 'error');
        return;
    }

    // Reset state
    regDbDetailState.regulationId = regulationId;
    regDbDetailState.regulationName = reg.name;
    regDbDetailState.currentPage = 1;
    regDbDetailState.search = '';
    regDbDetailState.anomaly = '';
    regDbDetailState.expandedChunks = new Set();

    // Update UI
    if (regdbDetailTitle) regdbDetailTitle.textContent = reg.name;
    if (regdbDetailSubtitle) {
        regdbDetailSubtitle.textContent = `${reg.filename} · ${(reg.total_chunks || 0).toLocaleString('id-ID')} chunks`;
    }

    // Reset filter buttons
    regdbDetailFilters.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.regdbFilter === '');
    });

    // Reset search
    if (regdbDetailSearch) regdbDetailSearch.value = '';

    // Reset body
    if (regdbChunksList) regdbChunksList.innerHTML = '';
    if (regdbDetailStats) regdbDetailStats.innerHTML = '';
    if (regdbDetailEmpty) regdbDetailEmpty.style.display = 'none';

    // Show modal
    if (regdbDetailOverlay) regdbDetailOverlay.style.display = 'flex';

    // Load data
    await loadRegDbChunks();
}

function closeRegDbDetail() {
    if (regdbDetailOverlay) regdbDetailOverlay.style.display = 'none';

    // Clear search debounce
    if (regDbDetailState.searchDebounceTimer) {
        clearTimeout(regDbDetailState.searchDebounceTimer);
        regDbDetailState.searchDebounceTimer = null;
    }

    // Reset state
    regDbDetailState.regulationId = null;
    regDbDetailState.expandedChunks = new Set();
}

// ---- Load Chunks ----
async function loadRegDbChunks() {
    const { regulationId, currentPage, pageSize, search, anomaly } = regDbDetailState;
    if (!regulationId) return;

    // Loading state
    if (regdbDetailLoading) regdbDetailLoading.style.display = 'flex';
    if (regdbChunksList) regdbChunksList.innerHTML = '';
    if (regdbDetailEmpty) regdbDetailEmpty.style.display = 'none';

    // Build query
    const params = new URLSearchParams({
        page: String(currentPage),
        page_size: String(pageSize),
    });
    if (search) params.set('search', search);
    if (anomaly) params.set('anomaly', anomaly);

    try {
        const res = await fetch(`/api/regulation-db/regulations/${regulationId}/chunks?${params.toString()}`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        const data = await res.json();
        regDbDetailState.totalPages = data.total_pages;
        regDbDetailState.total = data.total;

        if (regdbDetailLoading) regdbDetailLoading.style.display = 'none';

        renderRegDbStats(data.stats, data.total, data.total_unfiltered);
        renderRegDbChunks(data.items || []);
        updateRegDbPagination(data.page, data.total_pages, data.total);

    } catch (err) {
        if (regdbDetailLoading) {
            regdbDetailLoading.innerHTML = `
                    <i class="fas fa-exclamation-circle" style="color:var(--warn);"></i>
                    Gagal memuat: ${escapeHtml(err.message)}
                `;
        }
    }
}

// ---- Render Stats ----
function renderRegDbStats(stats, totalFiltered, totalUnfiltered) {
    if (!regdbDetailStats) return;

    const filterInfo = totalFiltered < totalUnfiltered
        ? `<span class="regdb-stat-mini"><strong>${totalFiltered}</strong><span>Terfilter dari ${totalUnfiltered}</span></span>`
        : '';

    const anomalyCount = (stats.anomaly_short || 0) + (stats.anomaly_long || 0) + (stats.anomaly_duplicate || 0);

    regdbDetailStats.innerHTML = `
            <div class="regdb-stat-mini">
                <strong>${stats.total_chunks || 0}</strong>
                <span>Total Chunks</span>
            </div>
            <div class="regdb-stat-mini">
                <strong>${stats.min_char}–${stats.max_char}</strong>
                <span>Min – Max Char</span>
            </div>
            <div class="regdb-stat-mini">
                <strong>${stats.avg_char}</strong>
                <span>Rata-rata Char</span>
            </div>
            <div class="regdb-stat-mini">
                <strong>${(stats.total_char || 0).toLocaleString('id-ID')}</strong>
                <span>Total Char</span>
            </div>
            ${anomalyCount > 0 ? `
                <div class="regdb-stat-mini warn">
                    <strong>${anomalyCount}</strong>
                    <span>Anomali Terdeteksi</span>
                </div>
            ` : `
                <div class="regdb-stat-mini">
                    <strong>0</strong>
                    <span>Anomali ✓</span>
                </div>
            `}
            ${filterInfo}
        `;
}

// ---- Render Chunks ----
function renderRegDbChunks(items) {
    if (!regdbChunksList) return;

    if (!items || items.length === 0) {
        regdbChunksList.innerHTML = '';
        if (regdbDetailEmpty) regdbDetailEmpty.style.display = 'block';
        return;
    }

    if (regdbDetailEmpty) regdbDetailEmpty.style.display = 'none';

    // Hitung index global (untuk tampilan nomor)
    const startIdx = (regDbDetailState.currentPage - 1) * regDbDetailState.pageSize;

    regdbChunksList.innerHTML = items.map((chunk, i) => {
        const globalIdx = startIdx + i + 1;
        const expanded = regDbDetailState.expandedChunks.has(chunk.id);
        const isLong = chunk.text.length > 400;

        let cardClass = 'regdb-chunk-card';
        let badge = '';

        if (chunk.anomaly_reason === 'short') {
            cardClass += ' anomaly-short';
            badge = `<span class="regdb-chunk-badge badge-short">Pendek</span>`;
        } else if (chunk.anomaly_reason === 'long') {
            cardClass += ' anomaly-long';
            badge = `<span class="regdb-chunk-badge badge-long">Panjang</span>`;
        } else if (chunk.anomaly_reason === 'duplicate') {
            cardClass += ' anomaly-duplicate';
            badge = `<span class="regdb-chunk-badge badge-duplicate">Duplikat</span>`;
        }

        const pageInfo = (chunk.page_start > 0)
            ? `<span><i class="fas fa-file"></i> hal. ${chunk.page_start}${chunk.page_end !== chunk.page_start ? '-' + chunk.page_end : ''}</span>`
            : '';

        return `
                <div class="${cardClass}" data-chunk-id="${escapeAttr(chunk.id)}">
                    <div class="regdb-chunk-header">
                        <span class="regdb-chunk-index">#${globalIdx}</span>
                        <span class="regdb-chunk-ref" title="${escapeAttr(chunk.referensi)}">
                            ${escapeHtml(chunk.referensi || '(no reference)')}
                        </span>
                        ${badge}
                        <div class="regdb-chunk-meta">
                            <span><i class="fas fa-font"></i> ${chunk.char_count.toLocaleString('id-ID')}</span>
                            ${pageInfo}
                        </div>
                    </div>
                    <div class="regdb-chunk-body ${expanded ? 'expanded' : (isLong ? 'collapsed' : '')}"
                         data-chunk-body-id="${escapeAttr(chunk.id)}">
                        ${escapeHtml(chunk.text)}
                    </div>
                    ${isLong ? `
                        <button class="regdb-chunk-expand" data-chunk-expand-id="${escapeAttr(chunk.id)}">
                            ${expanded ? '▲ Sembunyikan' : '▼ Lihat Selengkapnya'}
                        </button>
                    ` : ''}
                </div>
            `;
    }).join('');

    // Attach expand listeners
    regdbChunksList.querySelectorAll('[data-chunk-expand-id]').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.chunkExpandId;
            toggleRegDbChunkExpand(id);
        });
    });
}

function toggleRegDbChunkExpand(chunkId) {
    const body = regdbChunksList.querySelector(`[data-chunk-body-id="${CSS.escape(chunkId)}"]`);
    const btn = regdbChunksList.querySelector(`[data-chunk-expand-id="${CSS.escape(chunkId)}"]`);
    if (!body || !btn) return;

    const isExpanded = regDbDetailState.expandedChunks.has(chunkId);

    if (isExpanded) {
        regDbDetailState.expandedChunks.delete(chunkId);
        body.classList.remove('expanded');
        body.classList.add('collapsed');
        btn.innerHTML = '▼ Lihat Selengkapnya';
    } else {
        regDbDetailState.expandedChunks.add(chunkId);
        body.classList.add('expanded');
        body.classList.remove('collapsed');
        btn.innerHTML = '▲ Sembunyikan';
    }
}

// ---- Pagination ----
function updateRegDbPagination(currentPage, totalPages, total) {
    if (regdbPageInfo) {
        if (total === 0) {
            regdbPageInfo.textContent = 'Tidak ada hasil';
        } else {
            regdbPageInfo.textContent = `Halaman ${currentPage} dari ${totalPages} (${total.toLocaleString('id-ID')} chunk)`;
        }
    }
    if (regdbPrevPage) regdbPrevPage.disabled = currentPage <= 1;
    if (regdbNextPage) regdbNextPage.disabled = currentPage >= totalPages;
}

if (regdbPrevPage) {
    regdbPrevPage.addEventListener('click', () => {
        if (regDbDetailState.currentPage > 1) {
            regDbDetailState.currentPage -= 1;
            regDbDetailState.expandedChunks = new Set();  // reset expand state
            loadRegDbChunks();
            // Scroll ke atas list
            const body = regdbChunksList?.parentElement;
            if (body) body.scrollTop = 0;
        }
    });
}

if (regdbNextPage) {
    regdbNextPage.addEventListener('click', () => {
        if (regDbDetailState.currentPage < regDbDetailState.totalPages) {
            regDbDetailState.currentPage += 1;
            regDbDetailState.expandedChunks = new Set();
            loadRegDbChunks();
            const body = regdbChunksList?.parentElement;
            if (body) body.scrollTop = 0;
        }
    });
}

// ---- Search (debounced) ----
if (regdbDetailSearch) {
    regdbDetailSearch.addEventListener('input', (e) => {
        const value = e.target.value;

        if (regDbDetailState.searchDebounceTimer) {
            clearTimeout(regDbDetailState.searchDebounceTimer);
        }

        regDbDetailState.searchDebounceTimer = setTimeout(() => {
            regDbDetailState.search = value.trim();
            regDbDetailState.currentPage = 1;
            regDbDetailState.expandedChunks = new Set();
            loadRegDbChunks();
        }, 300);
    });

    // Enter untuk langsung search
    regdbDetailSearch.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (regDbDetailState.searchDebounceTimer) {
                clearTimeout(regDbDetailState.searchDebounceTimer);
            }
            regDbDetailState.search = regdbDetailSearch.value.trim();
            regDbDetailState.currentPage = 1;
            loadRegDbChunks();
        }
    });
}

// ---- Filter buttons ----
regdbDetailFilters.forEach(btn => {
    btn.addEventListener('click', () => {
        const filter = btn.dataset.regdbFilter || '';

        regdbDetailFilters.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        regDbDetailState.anomaly = filter;
        regDbDetailState.currentPage = 1;
        regDbDetailState.expandedChunks = new Set();
        loadRegDbChunks();
    });
});

// ---- Close handlers ----
if (regdbDetailClose) {
    regdbDetailClose.addEventListener('click', closeRegDbDetail);
}
if (regdbDetailOverlay) {
    regdbDetailOverlay.addEventListener('click', (e) => {
        if (e.target === regdbDetailOverlay) closeRegDbDetail();
    });
}

// ESC key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && regdbDetailOverlay && regdbDetailOverlay.style.display === 'flex') {
        closeRegDbDetail();
        e.stopPropagation();
    }
});

onPageEnter('regulation-db', loadRegulationDbPage);
