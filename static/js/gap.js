/**
 * Tool 2 — Gap Analysis: ekstraksi persyaratan, tabel, status gap, export.
 */

import {
    $,
    escapeAttr,
    escapeHtml,
    formatFileSize,
    renderMarkdownLite,
    showToast,
    state,
} from './core.js';
import { runJob } from './jobs.js';

// ============================================================
// ============ TOOL 2: GAP ANALYSIS =========================
// ============================================================

const gapForm = $('#gapUploadForm');
const gapUploadZone = $('#gapUploadZone');
const gapFileInput = $('#gapFileInput');
const gapFileNameDisplay = $('#gapFileNameDisplay');
const gapNamaRegulasi = $('#gapNamaRegulasi');
const gapFilterInput = $('#gapFilterInput');
const gapSubmitBtn = $('#gapSubmitBtn');
const gapResetBtn = $('#gapResetBtn');
const gapStatusEl = $('#gapStatus');
const gapProgressContainer = $('#gapProgressContainer');
const gapProgressBar = $('#gapProgressBar');
const gapProgressText = $('#gapProgressText');
export const gapResultSection = $('#gapResultSection');
const gapFilterBadge = $('#gapFilterBadge');
const gapChunkErrorsBox = $('#gapChunkErrorsBox');
const gapSummaryRow = $('#gapSummaryRow');
export const gapSearchInput = $('#gapSearchInput');
export const gapStatusFilter = $('#gapStatusFilter');
const gapBulkToolbar = $('#gapBulkToolbar');
const gapBulkCount = $('#gapBulkCount');
const gapBulkStatusSelect = $('#gapBulkStatusSelect');
const gapBulkDeleteBtn = $('#gapBulkDeleteBtn');
const gapBulkClearBtn = $('#gapBulkClearBtn');
const gapAddRowBtn = $('#gapAddRowBtn');
const gapSelectAllCheckbox = $('#gapSelectAllCheckbox');
const gapResultBody = $('#gapResultBody');
const gapEmptyState = $('#gapEmptyState');
export const gapExportBtn = $('#gapExportBtn');
export const gapCopyBtn = $('#gapCopyBtn');
const gapClearResultBtn = $('#gapClearResultBtn');

export const gapAddRowModalOverlay = $('#gapAddRowModalOverlay');
const gapAddRowModalClose = $('#gapAddRowModalClose');
const gapAddRowCancelBtn = $('#gapAddRowCancelBtn');
const gapAddRowSaveBtn = $('#gapAddRowSaveBtn');
const gapAddPersyaratan = $('#gapAddPersyaratan');
const gapAddReferensi = $('#gapAddReferensi');
const gapAddCatatan = $('#gapAddCatatan');

export function updateGapFileNameDisplay() {
    if (!gapFileNameDisplay) return;
    if (gapFileInput && gapFileInput.files.length) {
        gapFileNameDisplay.textContent = `📄 ${gapFileInput.files[0].name} (${formatFileSize(gapFileInput.files[0].size)})`;
        gapFileNameDisplay.style.display = 'block';
    } else {
        gapFileNameDisplay.textContent = '';
        gapFileNameDisplay.style.display = 'none';
    }
}

if (gapUploadZone) {
    gapUploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        gapUploadZone.classList.add('dragover');
    });
    gapUploadZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        gapUploadZone.classList.remove('dragover');
    });
    gapUploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        gapUploadZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            gapFileInput.files = e.dataTransfer.files;
            updateGapFileNameDisplay();
            setGapStatus(`File dipilih: ${e.dataTransfer.files[0].name}`, false);
        }
    });
}
if (gapFileInput) gapFileInput.addEventListener('change', updateGapFileNameDisplay);

export function setGapStatus(text, isError) {
    if (!gapStatusEl) return;
    gapStatusEl.className = 'status-text';
    if (isError === true) {
        gapStatusEl.classList.add('error');
        gapStatusEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${escapeHtml(text)}`;
    } else if (isError === false) {
        gapStatusEl.classList.add('success');
        gapStatusEl.innerHTML = `<i class="fas fa-check-circle"></i> ${escapeHtml(text)}`;
    } else {
        gapStatusEl.textContent = text;
    }
}

function setGapProgress(percent, text) {
    if (!gapProgressContainer) return;
    gapProgressContainer.style.display = 'block';
    gapProgressBar.style.width = percent + '%';
    gapProgressText.textContent = text || `${Math.round(percent)}%`;
    if (percent >= 100) {
        setTimeout(() => {
            gapProgressContainer.style.display = 'none';
            gapProgressText.textContent = '';
        }, 1500);
    }
}

function hideGapProgress() {
    if (!gapProgressContainer) return;
    gapProgressContainer.style.display = 'none';
    gapProgressText.textContent = '';
    gapProgressBar.style.width = '0%';
}

function gapApplyFilter(items) {
    let filtered = [...items];
    if (state.gapStatusFilter) {
        filtered = filtered.filter(it => {
            const status = it.status_gap || 'Belum Dinilai';
            if (state.gapStatusFilter === 'Belum Dinilai') {
                return !it.status_gap;
            }
            return it.status_gap === state.gapStatusFilter;
        });
    }
    if (state.gapSearchQuery) {
        const q = state.gapSearchQuery.toLowerCase();
        filtered = filtered.filter(it =>
            (it.persyaratan || '').toLowerCase().includes(q) ||
            (it.referensi || '').toLowerCase().includes(q) ||
            (it.catatan || '').toLowerCase().includes(q)
        );
    }
    return filtered;
}

function statusGapClass(status) {
    if (!status) return 'empty';
    const s = status.toLowerCase();
    if (s === 'sesuai') return 'sesuai';
    if (s === 'sebagian sesuai') return 'sebagian';
    if (s === 'tidak sesuai') return 'tidak';
    if (s === 'n/a') return 'na';
    return 'empty';
}

export function renderGapTable(items) {
    if (!gapResultBody) return;
    const filtered = gapApplyFilter(items || []);
    if (filtered.length === 0) {
        gapResultBody.innerHTML = '';
        if (gapEmptyState) gapEmptyState.style.display = 'block';
        updateGapBulkToolbar();
        updateGapSelectAll();
        return;
    }
    if (gapEmptyState) gapEmptyState.style.display = 'none';

    gapResultBody.innerHTML = filtered.map((item, i) => {
        const realIdx = (state.gapData.requirements || []).indexOf(item);
        const isChecked = state.gapSelectedRows.has(realIdx);
        const status = item.status_gap || '';
        const statusLabel = status || 'Belum Dinilai';
        const statusCls = statusGapClass(status);

        const cell = (field, value, multiline, extraCls = '') => `
                <td class="editable-cell ${extraCls}" data-idx="${realIdx}" data-field="${field}">
                    <div class="cell-content ${multiline ? 'multiline' : ''}"
                         contenteditable="true"
                         spellcheck="false"
                         data-original="${escapeAttr(value)}">${escapeHtml(value)}</div>
                </td>`;

        const catatanCell = `
                <td class="editable-cell" data-idx="${realIdx}" data-field="catatan">
                    <div class="cell-content multiline"
                         contenteditable="true"
                         spellcheck="false"
                         data-original="${escapeAttr(item.catatan || '')}">${renderMarkdownLite(item.catatan || '')}</div>
                </td>`;

        return `
                <tr class="${isChecked ? 'selected-row' : ''}" data-idx="${realIdx}">
                    <td class="row-checkbox-cell">
                        <input type="checkbox" class="row-checkbox"
                               data-row-idx="${realIdx}"
                               ${isChecked ? 'checked' : ''} />
                    </td>
                    <td class="row-no">${i + 1}</td>
                    ${cell('persyaratan', item.persyaratan || '', true, 'col-persyaratan')}
                    ${cell('referensi', item.referensi || '', true, 'col-referensi')}
                    ${catatanCell}
                    <td class="editable-cell col-status" data-idx="${realIdx}" data-field="status_gap">
                        <div class="cell-content"
                             contenteditable="true"
                             spellcheck="false"
                             data-original="${escapeAttr(status)}">
                            <span class="status-pill ${statusCls}">${escapeHtml(statusLabel)}</span>
                        </div>
                    </td>
                    <td class="actions-cell">
                        <button class="row-action-btn" data-delete-idx="${realIdx}" title="Hapus">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
    }).join('');

    gapResultBody.querySelectorAll('.cell-content[contenteditable="true"]').forEach(el => {
        el.addEventListener('focus', () => el.classList.add('editing'));
        el.addEventListener('blur', onGapCellBlur);
        el.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                el.textContent = el.dataset.original || '';
                el.blur();
            }
            if (e.key === 'Enter' && !el.classList.contains('multiline')) {
                e.preventDefault();
                el.blur();
            }
        });
    });

    gapResultBody.querySelectorAll('.row-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
            const idx = parseInt(cb.dataset.rowIdx, 10);
            if (cb.checked) state.gapSelectedRows.add(idx);
            else state.gapSelectedRows.delete(idx);
            cb.closest('tr').classList.toggle('selected-row', cb.checked);
            updateGapBulkToolbar();
            updateGapSelectAll();
        });
    });

    gapResultBody.querySelectorAll('[data-delete-idx]').forEach(btn => {
        btn.addEventListener('click', () => {
            const idx = parseInt(btn.dataset.deleteIdx, 10);
            gapDeleteSingleRow(idx);
        });
    });

    updateGapBulkToolbar();
    updateGapSelectAll();
}

function updateGapBulkToolbar() {
    if (!gapBulkToolbar) return;
    const count = state.gapSelectedRows.size;
    if (count === 0) gapBulkToolbar.style.display = 'none';
    else {
        gapBulkToolbar.style.display = 'flex';
        gapBulkCount.textContent = `${count} dipilih`;
    }
    if (gapBulkStatusSelect) gapBulkStatusSelect.value = '';
}

function updateGapSelectAll() {
    if (!gapSelectAllCheckbox) return;
    if (!state.gapData || !state.gapData.requirements) {
        gapSelectAllCheckbox.checked = false;
        gapSelectAllCheckbox.indeterminate = false;
        return;
    }
    const visible = gapApplyFilter(state.gapData.requirements);
    const visibleIndices = visible.map(it => state.gapData.requirements.indexOf(it));
    const selectedVisible = visibleIndices.filter(i => state.gapSelectedRows.has(i));
    const all = visibleIndices.length > 0 && selectedVisible.length === visibleIndices.length;
    const partial = selectedVisible.length > 0 && !all;
    gapSelectAllCheckbox.checked = all;
    gapSelectAllCheckbox.indeterminate = partial;
}

if (gapSelectAllCheckbox) {
    gapSelectAllCheckbox.addEventListener('change', (e) => {
        if (!state.gapData || !state.gapData.requirements) return;
        const visible = gapApplyFilter(state.gapData.requirements);
        const visibleIndices = visible.map(it => state.gapData.requirements.indexOf(it));
        if (e.target.checked) visibleIndices.forEach(i => state.gapSelectedRows.add(i));
        else visibleIndices.forEach(i => state.gapSelectedRows.delete(i));
        renderGapTable(state.gapData.requirements);
    });
}

if (gapBulkClearBtn) {
    gapBulkClearBtn.addEventListener('click', () => {
        state.gapSelectedRows.clear();
        renderGapTable(state.gapData.requirements);
    });
}

if (gapBulkStatusSelect) {
    gapBulkStatusSelect.addEventListener('change', async () => {
        const newStatus = gapBulkStatusSelect.value;
        if (!newStatus || state.gapSelectedRows.size === 0) return;
        const indices = Array.from(state.gapSelectedRows);
        gapBulkStatusSelect.disabled = true;
        try {
            const res = await fetch(`/api/requirements/${state.gapResultId}/items/bulk`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_indices: indices, status_kepatuhan: newStatus }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            indices.forEach(i => {
                if (state.gapData.requirements[i]) state.gapData.requirements[i].status_gap = newStatus;
            });
            state.gapSelectedRows.clear();
            renderGapSummary(state.gapData);
            renderGapTable(state.gapData.requirements);
            showToast(`${data.affected} baris diperbarui.`, 'success');
        } catch (err) {
            showToast(`Gagal update: ${err.message}`, 'error');
        } finally {
            gapBulkStatusSelect.disabled = false;
            gapBulkStatusSelect.value = '';
        }
    });
}

if (gapBulkDeleteBtn) {
    gapBulkDeleteBtn.addEventListener('click', async () => {
        if (state.gapSelectedRows.size === 0) return;
        if (!confirm(`Hapus ${state.gapSelectedRows.size} baris terpilih?`)) return;
        const indices = Array.from(state.gapSelectedRows);
        gapBulkDeleteBtn.disabled = true;
        try {
            const res = await fetch(`/api/requirements/${state.gapResultId}/items`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_indices: indices }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            await gapReload();
            state.gapSelectedRows.clear();
            updateGapBulkToolbar();
            showToast(`${indices.length} baris dihapus.`, 'success');
        } catch (err) {
            showToast(`Gagal menghapus: ${err.message}`, 'error');
        } finally {
            gapBulkDeleteBtn.disabled = false;
        }
    });
}

async function gapDeleteSingleRow(idx) {
    if (!state.gapData || !state.gapData.requirements[idx]) return;
    if (!confirm('Hapus baris ini?')) return;
    try {
        const res = await fetch(`/api/requirements/${state.gapResultId}/items`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_indices: [idx] }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        await gapReload();
        state.gapSelectedRows.clear();
        showToast('Baris dihapus.', 'success');
    } catch (err) {
        showToast(`Gagal menghapus: ${err.message}`, 'error');
    }
}

async function gapReload() {
    try {
        const res = await fetch(`/api/requirements/${state.gapResultId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        state.gapData = data;
        renderGapSummary(data);
        renderGapTable(data.requirements || []);
        renderGapChunkErrors(data.chunk_errors || []);
    } catch (err) {
        showToast(`Gagal memuat ulang: ${err.message}`, 'error');
    }
}

async function onGapCellBlur(e) {
    const el = e.target;
    el.classList.remove('editing');
    const newValue = (el.innerText || '').trim();
    const original = el.dataset.original || '';
    if (newValue === original) return;

    const idx = parseInt(el.closest('td').dataset.idx, 10);
    const field = el.closest('td').dataset.field;
    if (!state.gapData || !state.gapData.requirements[idx]) return;

    state.gapData.requirements[idx][field] = newValue;

    try {
        const res = await fetch(`/api/requirements/${state.gapResultId}/items/${idx}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [field]: newValue }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const updated = await res.json();
        Object.assign(state.gapData.requirements[idx], updated);
        el.dataset.original = newValue;
        el.classList.add('saved-flash');
        setTimeout(() => el.classList.remove('saved-flash'), 800);
        showToast('Tersimpan', 'success');
        if (field === 'status_gap' || field === 'catatan') {
            renderGapTable(state.gapData.requirements);
        }
        renderGapSummary(state.gapData);
    } catch (err) {
        state.gapData.requirements[idx][field] = original;
        el.textContent = original;
        showToast(`Gagal menyimpan: ${err.message}`, 'error');
    }
}

export function renderGapSummary(data) {
    if (!gapSummaryRow) return;
    const total = data.total_requirements || 0;
    const items = data.requirements || [];
    const dinilai = items.filter(it => it.status_gap && it.status_gap !== 'Belum Dinilai').length;
    const sesuai = items.filter(it => it.status_gap === 'Sesuai').length;
    const tidakSesuai = items.filter(it => it.status_gap === 'Tidak Sesuai' || it.status_gap === 'Sebagian Sesuai').length;
    const chunks = data.total_chunks_analyzed || 0;
    const batches = data.total_batches || 0;

    gapSummaryRow.innerHTML = `
            <div class="stat"><strong>${total}</strong><span>Persyaratan</span></div>
            <div class="stat"><strong>${dinilai}</strong><span>Sudah Dinilai</span></div>
            <div class="stat stat-valid"><strong>${sesuai}</strong><span>Sesuai</span></div>
            <div class="stat stat-flagged"><strong>${tidakSesuai}</strong><span>Perlu Tindak</span></div>
            <div class="stat"><strong>${chunks}</strong><span>Potongan Dianalisis</span></div>
            <div class="stat"><strong>${batches}</strong><span>Pemanggilan API</span></div>
        `;

    if (data.filter_applied && gapFilterBadge) {
        gapFilterBadge.style.display = 'flex';
        gapFilterBadge.innerHTML = `
                <i class="fas fa-filter"></i>
                <span>Filter:</span>
                <span class="filter-chips">
                    <span class="filter-chip">${escapeHtml(data.filter_applied)}</span>
                </span>
            `;
    } else if (gapFilterBadge) {
        gapFilterBadge.style.display = 'none';
    }
}

export function renderGapChunkErrors(errors) {
    if (!gapChunkErrorsBox) return;
    if (!errors || errors.length === 0) {
        gapChunkErrorsBox.style.display = 'none';
        return;
    }
    gapChunkErrorsBox.style.display = 'block';
    const lines = errors.map(e => {
        const ref = [e.lampiran, e.bab, e.pasal, e.ayat].filter(Boolean).join(' / ')
            || '(referensi tidak diketahui)';
        const countInfo = e.affected_count > 1 ? ` (${e.affected_count} potongan)` : '';
        return `<li>${escapeHtml(ref)}${countInfo}: ${escapeHtml(e.error)}</li>`;
    }).join('');
    gapChunkErrorsBox.innerHTML = `
            <strong><i class="fas fa-triangle-exclamation"></i> ${errors.length} batch gagal</strong>
            <ul>${lines}</ul>
        `;
}

if (gapSearchInput) {
    gapSearchInput.addEventListener('input', (e) => {
        state.gapSearchQuery = e.target.value;
        if (state.gapData) renderGapTable(state.gapData.requirements);
    });
}

if (gapStatusFilter) {
    gapStatusFilter.addEventListener('change', (e) => {
        state.gapStatusFilter = e.target.value;
        if (state.gapData) renderGapTable(state.gapData.requirements);
    });
}

function openGapAddRowModal() {
    if (gapAddPersyaratan) gapAddPersyaratan.value = '';
    if (gapAddReferensi) gapAddReferensi.value = '';
    if (gapAddCatatan) gapAddCatatan.value = '';
    if (gapAddRowModalOverlay) gapAddRowModalOverlay.style.display = 'flex';
    if (gapAddPersyaratan) gapAddPersyaratan.focus();
}
export function closeGapAddRowModal() {
    if (gapAddRowModalOverlay) gapAddRowModalOverlay.style.display = 'none';
}

if (gapAddRowBtn) gapAddRowBtn.addEventListener('click', openGapAddRowModal);
if (gapAddRowModalClose) gapAddRowModalClose.addEventListener('click', closeGapAddRowModal);
if (gapAddRowCancelBtn) gapAddRowCancelBtn.addEventListener('click', closeGapAddRowModal);
if (gapAddRowModalOverlay) {
    gapAddRowModalOverlay.addEventListener('click', (e) => {
        if (e.target === gapAddRowModalOverlay) closeGapAddRowModal();
    });
}

if (gapAddRowSaveBtn) {
    gapAddRowSaveBtn.addEventListener('click', async () => {
        if (!gapAddPersyaratan.value.trim()) {
            showToast('Isi minimal kolom Persyaratan.', 'error');
            return;
        }
        gapAddRowSaveBtn.disabled = true;
        gapAddRowSaveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';
        try {
            const res = await fetch(`/api/requirements/${state.gapResultId}/items`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    persyaratan: gapAddPersyaratan.value.trim(),
                    referensi: gapAddReferensi ? gapAddReferensi.value.trim() : '',
                    catatan: gapAddCatatan ? gapAddCatatan.value.trim() : '',
                    status_gap: '',
                }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const newItem = await res.json();
            state.gapData.requirements.push(newItem);
            state.gapData.total_requirements = state.gapData.requirements.length;
            closeGapAddRowModal();
            renderGapSummary(state.gapData);
            renderGapTable(state.gapData.requirements);
            showToast('Persyaratan ditambahkan.', 'success');
        } catch (err) {
            showToast(`Gagal menambah: ${err.message}`, 'error');
        } finally {
            gapAddRowSaveBtn.disabled = false;
            gapAddRowSaveBtn.innerHTML = '<i class="fas fa-plus"></i> Tambah Persyaratan';
        }
    });
}

if (gapExportBtn) {
    gapExportBtn.addEventListener('click', () => {
        if (state.gapResultId) {
            window.location.href = `/api/export-requirements/${state.gapResultId}`;
            showToast('Mengekspor ke Excel...', 'info');
        }
    });
}
    export const gapExportPdfBtn = $('#gapExportPdfBtn');
if (gapExportPdfBtn) {
    gapExportPdfBtn.addEventListener('click', () => {
        if (state.gapResultId) {
            window.location.href = `/api/export-requirements-pdf/${state.gapResultId}`;
            showToast('Mengekspor ke PDF...', 'info');
        }
    });
}

if (gapCopyBtn) {
    gapCopyBtn.addEventListener('click', () => {
        if (!state.gapData || !state.gapData.requirements) return;
        const items = state.gapData.requirements;
        let text = `DAFTAR PERSYARATAN REGULASI\n`;
        text += `Total: ${items.length} persyaratan\n`;
        text += `${'='.repeat(60)}\n\n`;
        items.forEach((it, i) => {
            text += `[${i + 1}] ${it.persyaratan}\n`;
            text += `    Referensi: ${it.referensi || '-'}\n`;
            if (it.catatan) text += `    Catatan: ${it.catatan}\n`;
            if (it.status_gap) text += `    Status Gap: ${it.status_gap}\n`;
            text += `\n`;
        });
        navigator.clipboard.writeText(text).then(() => {
            showToast('Disalin ke clipboard.', 'success');
        }).catch(() => showToast('Gagal menyalin.', 'error'));
    });
}

if (gapClearResultBtn) {
    gapClearResultBtn.addEventListener('click', () => {
        gapResultSection.style.display = 'none';
        state.gapResultId = null;
        state.gapData = null;
        state.gapSelectedRows.clear();
        gapExportBtn.disabled = true;
        gapCopyBtn.disabled = true;
        setGapStatus('Hasil ditutup. Upload regulasi baru.', false);
        showToast('Hasil ditutup.', 'info');
    });
}

if (gapResetBtn) {
    gapResetBtn.addEventListener('click', () => {
        gapFileInput.value = '';
        gapFileNameDisplay.textContent = '';
        gapFileNameDisplay.style.display = 'none';
        if (gapNamaRegulasi) gapNamaRegulasi.value = '';
        if (gapFilterInput) gapFilterInput.value = '';
        state.gapResultId = null;
        state.gapData = null;
        state.gapSelectedRows = new Set();
        gapResultSection.style.display = 'none';
        gapExportBtn.disabled = true;
        gapCopyBtn.disabled = true;
        setGapStatus('Menunggu file...', false);
        showToast('Form dibersihkan.', 'info');
    });
}

if (gapForm) {
    gapForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!gapFileInput.files.length) {
            setGapStatus('Pilih file terlebih dahulu.', true);
            showToast('Pilih file dulu!', 'error');
            return;
        }
        const file = gapFileInput.files[0];
        if (file.size > 10 * 1024 * 1024) {
            setGapStatus('File terlalu besar. Maks 10MB.', true);
            showToast('File terlalu besar!', 'error');
            return;
        }

        gapSubmitBtn.disabled = true;
        state.isAnalyzing = true;
        gapResultSection.style.display = 'none';
        setGapStatus('Membaca struktur dokumen...', null);
        setGapProgress(20, 'Mengekstrak teks...');

        const fd = new FormData();
        fd.append('file', file);

        try {
            setGapProgress(40, 'Mendeteksi struktur...');
            const previewRes = await fetch('/api/preview', { method: 'POST', body: fd });
            const previewData = await previewRes.json();

            if (!previewRes.ok) {
                setGapStatus(`Gagal: ${previewData.detail || 'Error.'}`, true);
                showToast('Gagal: ' + (previewData.detail || 'Server error'), 'error');
                hideGapProgress();
                return;
            }

            setGapProgress(60, 'Mengekstrak persyaratan dengan AI...');
            setGapStatus(`${previewData.total_chunks} potongan. AI menganalisis...`, null);

            const namaInput = gapNamaRegulasi ? gapNamaRegulasi.value.trim() : '';
            const filterText = gapFilterInput ? gapFilterInput.value.trim() : '';

            const run = await runJob('/api/analyze-requirements', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    preview_id: previewData.preview_id,
                    nama_regulasi: namaInput || file.name.replace(/\.[^.]+$/, ''),
                    filter_text: filterText || null,
                }),
            }, {
                cancelAnchor: gapProgressText,
                onProgress: (job, pct, label) => setGapProgress(60 + pct * 0.4, label),
            });

            if (!run.ok) {
                setGapStatus(`Gagal: ${run.error}`, true);
                showToast(run.cancelled ? 'Ekstraksi dibatalkan.' : 'Gagal: ' + run.error, run.cancelled ? 'info' : 'error');
                hideGapProgress();
                return;
            }
            const data = run.data;

            setGapProgress(100, 'Selesai!');
            setGapStatus(run.partial
                ? `Dibatalkan — hasil parsial: ${data.total_requirements} persyaratan. ${run.job.message}`
                : `Selesai. ${data.total_requirements} persyaratan dari ${data.total_chunks_analyzed} potongan.`, false);

            state.gapResultId = data.result_id;
            state.gapData = data;
            state.gapSelectedRows = new Set();
            state.gapStatusFilter = '';
            if (gapStatusFilter) gapStatusFilter.value = '';

            gapExportBtn.disabled = false;
            gapCopyBtn.disabled = false;
            renderGapSummary(data);
            renderGapChunkErrors(data.chunk_errors);
            renderGapTable(data.requirements);
            gapResultSection.style.display = 'block';
            gapResultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
            document.dispatchEvent(new CustomEvent('history:changed'));
            showToast(run.partial ? 'Dibatalkan — hasil parsial ditampilkan.' : 'Persyaratan berhasil diekstrak! 🎉',
                run.partial ? 'info' : 'success');
        } catch (err) {
            setGapStatus(`Gagal: ${err.message}`, true);
            showToast('Gagal terhubung ke server.', 'error');
        } finally {
            gapSubmitBtn.disabled = false;
            state.isAnalyzing = false;
            setTimeout(hideGapProgress, 2000);
        }
    });
}
