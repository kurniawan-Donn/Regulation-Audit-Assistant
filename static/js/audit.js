/**
 * Tool 1 — Regulation to Audit: upload, tree pilihan bagian, estimasi biaya,
 * analisis (job), tabel kertas kerja, filter, tambah baris, export.
 */

import {
    $,
    $$,
    escapeAttr,
    escapeHtml,
    formatDuration,
    formatFileSize,
    formatIdr,
    onThemeChange,
    showToast,
    state,
    treeState,
} from './core.js';
import { runJob } from './jobs.js';
import { saveToHistory } from './history.js';

// ============================================================
// ============ TOOL 1: REGULATION TO AUDIT ===================
// ============================================================

const form = $('#uploadForm');
const statusEl = $('#status');
const submitBtn = $('#submitBtn');
export const resultSection = $('#resultSection');
const resultBody = $('#resultBody');
const summaryRow = $('#summaryRow');
const aspectsBox = $('#aspectsBox');
const filterBadge = $('#filterBadge');
export const previewExpiredBanner = $('#previewExpiredBanner');
const chunkErrorsBox = $('#chunkErrorsBox');
export const exportBtn = $('#exportBtn');
export const exportPdfBtn = $('#exportPdfBtn');
export const copyBtn = $('#copyBtn');
const clearResultBtn = $('#clearResultBtn');
const changeFilterBtn = $('#changeFilterBtn');
const resetBtn = $('#resetBtn');
const fileInput = $('#fileInput');
const uploadZone = $('#uploadZone');
const fileNameDisplay = $('#fileNameDisplay');
export const searchInput = $('#searchInput');
const filterBtns = $$('.filter-btn');
const emptyState = $('#emptyState');
const progressContainer = $('#progressContainer');
const progressBar = $('#progressBar');
const progressText = $('#progressText');
const chartContainer = $('#chartContainer');
const donutChart = $('#donutChart');
const donutInner = $('#donutInner');
const chartLegend = $('#chartLegend');
const progressBadge = $('#progressBadge');
export const statusFilterSelect = $('#statusFilter');
const bulkToolbar = $('#bulkToolbar');
const bulkCount = $('#bulkCount');
const bulkStatusSelect = $('#bulkStatusSelect');
const bulkDeleteBtn = $('#bulkDeleteBtn');
const bulkClearBtn = $('#bulkClearBtn');
const addRowBtn = $('#addRowBtn');
const selectAllCheckbox = $('#selectAllCheckbox');

export const addRowModalOverlay = $('#addRowModalOverlay');
const addRowModalClose = $('#addRowModalClose');
const addRowCancelBtn = $('#addRowCancelBtn');
const addRowSaveBtn = $('#addRowSaveBtn');
const addRowReferensi = $('#addRowReferensi');
const addRowAspek = $('#addRowAspek');
const addRowStruktur = $('#addRowStruktur');
const addRowKetentuan = $('#addRowKetentuan');
const addRowPemeriksaan = $('#addRowPemeriksaan');
const addRowMetode = $('#addRowMetode');
const addRowBukti = $('#addRowBukti');
const addRowCatatan = $('#addRowCatatan');

export const treeModalOverlay = $('#treeModalOverlay');
const treeModalClose = $('#treeModalClose');
const treeModalSub = $('#treeModalSub');
const treeSelectAll = $('#treeSelectAll');
const treeClearAll = $('#treeClearAll');
const treeSelectedCount = $('#treeSelectedCount');
const treeContainer = $('#treeContainer');
const treeCancelBtn = $('#treeCancelBtn');
const treeAnalyzeBtn = $('#treeAnalyzeBtn');
const treeEstimate = $('#treeEstimate');

// ====== PROGRESS HELPERS (Tool 1) ======
export function setStatus(text, isError) {
    if (!statusEl) return;
    statusEl.className = 'status-text';
    if (isError === true) {
        statusEl.classList.add('error');
        statusEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${escapeHtml(text)}`;
    } else if (isError === false) {
        statusEl.classList.add('success');
        statusEl.innerHTML = `<i class="fas fa-check-circle"></i> ${escapeHtml(text)}`;
    } else {
        statusEl.textContent = text;
    }
}

function setProgress(percent, text) {
    if (!progressContainer) return;
    progressContainer.style.display = 'block';
    progressBar.style.width = percent + '%';
    progressText.textContent = text || `${Math.round(percent)}%`;
    if (percent >= 100) {
        setTimeout(() => {
            progressContainer.style.display = 'none';
            progressText.textContent = '';
        }, 1500);
    }
}

function hideProgress() {
    if (!progressContainer) return;
    progressContainer.style.display = 'none';
    progressText.textContent = '';
    progressBar.style.width = '0%';
}

// ====== UPLOAD (Tool 1) ======
if (uploadZone) {
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });
    uploadZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
    });
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            updateFileNameDisplay();
            setStatus(`File dipilih: ${e.dataTransfer.files[0].name}`, false);
        }
    });
}
if (fileInput) fileInput.addEventListener('change', updateFileNameDisplay);

export function updateFileNameDisplay() {
    if (!fileNameDisplay) return;
    if (fileInput && fileInput.files.length) {
        fileNameDisplay.textContent = `📄 ${fileInput.files[0].name} (${formatFileSize(fileInput.files[0].size)})`;
        fileNameDisplay.style.display = 'block';
    } else {
        fileNameDisplay.textContent = '';
        fileNameDisplay.style.display = 'none';
    }
}

// ====== SUMMARY / PROGRESS / FILTER / DONUT (Tool 1) ======
export function renderSummary(data) {
    if (!summaryRow) return;
    const total = data.total_ketentuan || 0;
    const valid = data.total_valid || 0;
    const flagged = data.total_flagged || 0;
    const chunks = data.total_chunks || 0;
    const batches = data.total_batches || 0;

    summaryRow.innerHTML = `
            <div class="stat"><strong>${total}</strong><span>Ketentuan</span></div>
            <div class="stat stat-valid"><strong>${valid}</strong><span>Valid</span></div>
            <div class="stat stat-flagged"><strong>${flagged}</strong><span>Perlu Ditinjau</span></div>
            <div class="stat"><strong>${chunks}</strong><span>Potongan Dianalisis</span></div>
            <div class="stat"><strong>${batches}</strong><span>Pemanggilan API</span></div>
        `;

    const byAspect = data.total_by_aspect || {};
    const entries = Object.entries(byAspect).sort((a, b) => b[1] - a[1]);
    if (aspectsBox) {
        if (entries.length === 0) {
            aspectsBox.style.display = 'none';
        } else {
            aspectsBox.style.display = 'block';
            aspectsBox.innerHTML = `
                    <h4><i class="fas fa-layer-group"></i> Distribusi per Aspek</h4>
                    <div class="aspects-chips">
                        ${entries.map(([name, count]) =>
                            `<span class="aspect-chip">${escapeHtml(name)} <b>${count}</b></span>`
                        ).join('')}
                    </div>
                `;
        }
    }
    updateDonutChart();
}

export function updateProgressBadge() {
    if (!progressBadge) return;
    if (!state.currentData || !state.currentData.results) {
        progressBadge.style.display = 'none';
        return;
    }
    const results = state.currentData.results;
    const total = results.length;
    if (total === 0) {
        progressBadge.style.display = 'none';
        return;
    }
    const audited = results.filter(r => (r.status_kepatuhan || 'Belum Diaudit') !== 'Belum Diaudit').length;
    const percent = Math.round((audited / total) * 100);

    progressBadge.style.display = 'inline-flex';
    progressBadge.classList.toggle('complete', audited === total && total > 0);

    progressBadge.innerHTML = `
            <span class="progress-badge-text">${audited} / ${total} diperiksa</span>
            <div class="progress-badge-bar">
                <div class="progress-badge-fill" style="width: ${percent}%"></div>
            </div>
            <span class="progress-badge-pct">${percent}%</span>
        `;
}

export function renderFilterBadge(labels) {
    if (!filterBadge) return;
    if (!labels || labels.length === 0) {
        filterBadge.style.display = 'none';
        return;
    }
    filterBadge.style.display = 'flex';
    filterBadge.innerHTML = `
            <i class="fas fa-filter"></i>
            <span>Analisis terbatas pada:</span>
            <span class="filter-chips">
                ${labels.map(l => `<span class="filter-chip">${escapeHtml(l)}</span>`).join('')}
            </span>
        `;
}

export function updateDonutChart() {
    if (!chartContainer || !donutChart || !donutInner || !chartLegend) return;
    if (!state.currentData) {
        chartContainer.style.display = 'none';
        return;
    }
    const valid = state.currentData.total_valid || 0;
    const flagged = state.currentData.total_flagged || 0;
    const total = valid + flagged;
    if (total === 0) {
        chartContainer.style.display = 'none';
        return;
    }
    chartContainer.style.display = 'flex';
    const validPercent = Math.round((valid / total) * 100);
    const flaggedPercent = 100 - validPercent;
    const validColor = getComputedStyle(document.documentElement).getPropertyValue('--success').trim();
    const warnColor = getComputedStyle(document.documentElement).getPropertyValue('--warn').trim();
    donutChart.style.background = `conic-gradient(${validColor} 0% ${validPercent}%, ${warnColor} ${validPercent}% 100%)`;
    donutInner.textContent = validPercent + '%';
    chartLegend.innerHTML = `
            <div class="chart-legend-item">
                <div class="chart-legend-dot valid"></div>
                <span>Valid: ${valid} (${validPercent}%)</span>
            </div>
            <div class="chart-legend-item">
                <div class="chart-legend-dot flagged"></div>
                <span>Perlu Ditinjau: ${flagged} (${flaggedPercent}%)</span>
            </div>
        `;
}

export function renderChunkErrors(errors) {
    if (!chunkErrorsBox) return;
    if (!errors || errors.length === 0) {
        chunkErrorsBox.style.display = 'none';
        return;
    }
    chunkErrorsBox.style.display = 'block';
    const lines = errors.map(e => {
        const ref = [e.lampiran, e.bab, e.pasal, e.ayat].filter(Boolean).join(' / ')
            || '(referensi tidak diketahui)';
        const countInfo = e.affected_count > 1 ? ` (${e.affected_count} potongan)` : '';
        return `<li>${escapeHtml(ref)}${countInfo}: ${escapeHtml(e.error)}</li>`;
    }).join('');
    chunkErrorsBox.innerHTML = `
            <strong><i class="fas fa-triangle-exclamation"></i> ${errors.length} batch gagal dianalisis</strong>
            <div style="font-size:0.78rem; color:var(--text-muted);">
                Bagian lain tetap ditampilkan. Detail error:
            </div>
            <ul>${lines}</ul>
        `;
}

// ====== TABLE (Tool 1) ======
export function renderTable(results) {
    if (!resultBody) return;
    const filtered = applyFilter(results || []);
    if (filtered.length === 0) {
        resultBody.innerHTML = '';
        if (emptyState) emptyState.style.display = 'block';
        updateBulkToolbar();
        updateSelectAllCheckbox();
        return;
    }
    if (emptyState) emptyState.style.display = 'none';

    resultBody.innerHTML = filtered.map((item, i) => {
        const isFlagged = !item.is_valid;
        const notes = item.validation_notes || [];
        const notesBadge = notes.length
            ? `<span class="validity-badge" title="${escapeAttr(notes.join('; '))}">⚠ ${notes.length}</span>`
            : '';
        const realIdx = (state.currentData.results || []).indexOf(item);
        const isChecked = state.selectedRows.has(realIdx);

        const cell = (field, value, multiline) => `
                <td class="editable-cell" data-idx="${realIdx}" data-field="${field}">
                    <div class="cell-content ${multiline ? 'multiline' : ''}"
                         contenteditable="true"
                         spellcheck="false"
                         data-original="${escapeAttr(value)}">${escapeHtml(value)}</div>
                </td>`;

        return `
                <tr class="${isFlagged ? 'flagged' : 'valid-row'} ${isChecked ? 'selected-row' : ''}" data-idx="${realIdx}">
                    <td class="row-checkbox-cell">
                        <input type="checkbox" class="row-checkbox"
                               data-row-idx="${realIdx}"
                               ${isChecked ? 'checked' : ''} />
                    </td>
                    <td class="row-no">${i + 1}${notesBadge}</td>
                    ${cell('referensi_regulasi', item.referensi_regulasi || '', false)}
                    ${cell('aspek', item.aspek || '', false)}
                    ${cell('bab_pasal_ayat', item.bab_pasal_ayat || '', false)}
                    ${cell('point_ketentuan', item.point_ketentuan || '', true)}
                    ${cell('pemeriksaan', item.pemeriksaan || '', true)}
                    ${cell('metode_audit', item.metode_audit || '', false)}
                    ${cell('kebutuhan_bukti', item.kebutuhan_bukti || '', true)}
                    ${cell('status_kepatuhan', item.status_kepatuhan || 'Belum Diaudit', false)}
                    ${cell('catatan_temuan', item.catatan_temuan || '', true)}
                    <td class="actions-cell">
                        <button class="row-action-btn" data-delete-idx="${realIdx}" title="Hapus baris">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
    }).join('');

    resultBody.querySelectorAll('.cell-content[contenteditable="true"]').forEach(el => {
        el.addEventListener('focus', () => el.classList.add('editing'));
        el.addEventListener('blur', onCellBlur);
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

    resultBody.querySelectorAll('.row-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
            const idx = parseInt(cb.dataset.rowIdx, 10);
            if (cb.checked) state.selectedRows.add(idx);
            else state.selectedRows.delete(idx);
            cb.closest('tr').classList.toggle('selected-row', cb.checked);
            updateBulkToolbar();
            updateSelectAllCheckbox();
        });
    });

    resultBody.querySelectorAll('[data-delete-idx]').forEach(btn => {
        btn.addEventListener('click', () => {
            const idx = parseInt(btn.dataset.deleteIdx, 10);
            deleteSingleRow(idx);
        });
    });

    updateBulkToolbar();
    updateSelectAllCheckbox();
}

function updateBulkToolbar() {
    if (!bulkToolbar) return;
    const count = state.selectedRows.size;
    if (count === 0) {
        bulkToolbar.style.display = 'none';
    } else {
        bulkToolbar.style.display = 'flex';
        bulkCount.textContent = `${count} dipilih`;
    }
    if (bulkStatusSelect) bulkStatusSelect.value = '';
}

function updateSelectAllCheckbox() {
    if (!selectAllCheckbox) return;
    if (!state.currentData || !state.currentData.results) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
        return;
    }
    const visibleFiltered = applyFilter(state.currentData.results);
    const visibleIndices = visibleFiltered.map(it => state.currentData.results.indexOf(it));
    const selectedVisible = visibleIndices.filter(i => state.selectedRows.has(i));
    const all = visibleIndices.length > 0 && selectedVisible.length === visibleIndices.length;
    const partial = selectedVisible.length > 0 && !all;
    selectAllCheckbox.checked = all;
    selectAllCheckbox.indeterminate = partial;
}

if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener('change', (e) => {
        if (!state.currentData || !state.currentData.results) return;
        const visibleFiltered = applyFilter(state.currentData.results);
        const visibleIndices = visibleFiltered.map(it => state.currentData.results.indexOf(it));
        if (e.target.checked) visibleIndices.forEach(i => state.selectedRows.add(i));
        else visibleIndices.forEach(i => state.selectedRows.delete(i));
        renderTable(state.currentData.results);
    });
}

if (bulkClearBtn) {
    bulkClearBtn.addEventListener('click', () => {
        state.selectedRows.clear();
        renderTable(state.currentData.results);
    });
}

if (bulkStatusSelect) {
    bulkStatusSelect.addEventListener('change', async () => {
        const newStatus = bulkStatusSelect.value;
        if (!newStatus || state.selectedRows.size === 0) return;
        const indices = Array.from(state.selectedRows);
        bulkStatusSelect.disabled = true;

        try {
            const res = await fetch(`/api/results/${state.currentResultId}/items/bulk`, {
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
                if (state.currentData.results[i]) state.currentData.results[i].status_kepatuhan = newStatus;
            });
            state.currentData.total_ketentuan = data.total_ketentuan;
            state.currentData.total_valid = data.total_valid;
            state.currentData.total_flagged = data.total_flagged;
            state.currentData.total_by_aspect = data.total_by_aspect;

            state.selectedRows.clear();
            renderSummary(state.currentData);
            renderTable(state.currentData.results);
            updateProgressBadge();
            persistHistory();
            showToast(`${data.affected} baris diperbarui.`, 'success');
        } catch (err) {
            showToast(`Gagal update: ${err.message}`, 'error');
        } finally {
            bulkStatusSelect.disabled = false;
            bulkStatusSelect.value = '';
        }
    });
}

if (bulkDeleteBtn) {
    bulkDeleteBtn.addEventListener('click', async () => {
        if (state.selectedRows.size === 0) return;
        if (!confirm(`Hapus ${state.selectedRows.size} baris terpilih?`)) return;
        const indices = Array.from(state.selectedRows);
        bulkDeleteBtn.disabled = true;
        try {
            const res = await fetch(`/api/results/${state.currentResultId}/items`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_indices: indices }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            await reloadResult();
            state.selectedRows.clear();
            updateBulkToolbar();
            showToast(`${indices.length} baris dihapus.`, 'success');
        } catch (err) {
            showToast(`Gagal menghapus: ${err.message}`, 'error');
        } finally {
            bulkDeleteBtn.disabled = false;
        }
    });
}

async function deleteSingleRow(idx) {
    if (!state.currentData || !state.currentData.results[idx]) return;
    if (!confirm('Hapus baris ini?')) return;
    try {
        const res = await fetch(`/api/results/${state.currentResultId}/items`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_indices: [idx] }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        await reloadResult();
        state.selectedRows.clear();
        showToast('Baris dihapus.', 'success');
    } catch (err) {
        showToast(`Gagal menghapus: ${err.message}`, 'error');
    }
}

async function reloadResult() {
    try {
        const res = await fetch(`/api/results/${state.currentResultId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        state.currentData = data;
        renderSummary(data);
        renderFilterBadge(data.filter_applied || []);
        renderChunkErrors(data.chunk_errors || []);
        renderTable(data.results || []);
        updateProgressBadge();
        updateDonutChart();
        persistHistory();
    } catch (err) {
        showToast(`Gagal memuat ulang: ${err.message}`, 'error');
    }
}

async function onCellBlur(e) {
    const el = e.target;
    el.classList.remove('editing');
    const newValue = (el.innerText || '').trim();
    const original = el.dataset.original || '';
    if (newValue === original) return;

    const idx = parseInt(el.closest('td').dataset.idx, 10);
    const field = el.closest('td').dataset.field;
    if (!state.currentData || !state.currentData.results[idx]) return;

    state.currentData.results[idx][field] = newValue;

    try {
        const res = await fetch(`/api/results/${state.currentResultId}/items/${idx}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [field]: newValue }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const updated = await res.json();
        Object.assign(state.currentData.results[idx], updated);
        el.dataset.original = newValue;
        el.classList.add('saved-flash');
        setTimeout(() => el.classList.remove('saved-flash'), 800);
        showToast('Tersimpan', 'success');
        if (field === 'status_kepatuhan') updateProgressBadge();
        persistHistory();
    } catch (err) {
        state.currentData.results[idx][field] = original;
        el.textContent = original;
        showToast(`Gagal menyimpan: ${err.message}`, 'error');
    }
}

function persistHistory() {
    const hIdx = state.history.findIndex(h => h.id === state.currentResultId);
    if (hIdx >= 0) {
        state.history[hIdx].results = state.currentData.results;
        state.history[hIdx].total_ketentuan = state.currentData.total_ketentuan;
        state.history[hIdx].total_valid = state.currentData.total_valid;
        state.history[hIdx].total_flagged = state.currentData.total_flagged;
        state.history[hIdx].total_by_aspect = state.currentData.total_by_aspect;
        localStorage.setItem('rta_history', JSON.stringify(state.history));
    }
}

// ====== ADD ROW MODAL (Tool 1) ======
function openAddRowModal() {
    if (addRowReferensi) addRowReferensi.value = '';
    if (addRowAspek) addRowAspek.value = '';
    if (addRowStruktur) addRowStruktur.value = '';
    if (addRowKetentuan) addRowKetentuan.value = '';
    if (addRowPemeriksaan) addRowPemeriksaan.value = '';
    if (addRowMetode) addRowMetode.value = '';
    if (addRowBukti) addRowBukti.value = '';
    if (addRowCatatan) addRowCatatan.value = '';
    if (state.currentData?.results?.length > 0) {
        const sample = state.currentData.results[0];
        if (sample.referensi_regulasi && addRowReferensi) addRowReferensi.value = sample.referensi_regulasi;
    }
    if (addRowModalOverlay) addRowModalOverlay.style.display = 'flex';
    if (addRowReferensi) addRowReferensi.focus();
}

export function closeAddRowModal() {
    if (addRowModalOverlay) addRowModalOverlay.style.display = 'none';
}

if (addRowBtn) addRowBtn.addEventListener('click', openAddRowModal);
if (addRowModalClose) addRowModalClose.addEventListener('click', closeAddRowModal);
if (addRowCancelBtn) addRowCancelBtn.addEventListener('click', closeAddRowModal);
if (addRowModalOverlay) {
    addRowModalOverlay.addEventListener('click', (e) => {
        if (e.target === addRowModalOverlay) closeAddRowModal();
    });
}

if (addRowSaveBtn) {
    addRowSaveBtn.addEventListener('click', async () => {
        const ketVal = addRowKetentuan ? addRowKetentuan.value.trim() : '';
        const perVal = addRowPemeriksaan ? addRowPemeriksaan.value.trim() : '';
        if (!ketVal && !perVal) {
            showToast('Isi minimal salah satu: Ketentuan atau Prosedur Pemeriksaan.', 'error');
            return;
        }
        addRowSaveBtn.disabled = true;
        addRowSaveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';
        const payload = {
            referensi_regulasi: addRowReferensi ? addRowReferensi.value.trim() : '',
            aspek: addRowAspek ? addRowAspek.value.trim() : '',
            bab_pasal_ayat: addRowStruktur ? addRowStruktur.value.trim() : '',
            point_ketentuan: ketVal,
            pemeriksaan: perVal,
            metode_audit: addRowMetode ? addRowMetode.value.trim() : '',
            kebutuhan_bukti: addRowBukti ? addRowBukti.value.trim() : '',
            catatan_temuan: addRowCatatan ? addRowCatatan.value.trim() : '',
        };
        try {
            const res = await fetch(`/api/results/${state.currentResultId}/items`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const newItem = await res.json();
            state.currentData.results.push(newItem);
            state.currentData.total_ketentuan = (state.currentData.total_ketentuan || 0) + 1;
            if (newItem.is_valid) state.currentData.total_valid = (state.currentData.total_valid || 0) + 1;
            closeAddRowModal();
            renderSummary(state.currentData);
            renderTable(state.currentData.results);
            updateProgressBadge();
            persistHistory();
            showToast('Baris baru ditambahkan.', 'success');
        } catch (err) {
            showToast(`Gagal menambah: ${err.message}`, 'error');
        } finally {
            addRowSaveBtn.disabled = false;
            addRowSaveBtn.innerHTML = '<i class="fas fa-plus"></i> Tambah Baris';
        }
    });
}

// ====== FILTER & SEARCH (Tool 1) ======
function applyFilter(results) {
    let filtered = [...results];
    if (state.filter === 'valid') filtered = filtered.filter(r => r.is_valid);
    else if (state.filter === 'flagged') filtered = filtered.filter(r => !r.is_valid);
    if (state.statusFilter) {
        filtered = filtered.filter(r =>
            (r.status_kepatuhan || 'Belum Diaudit') === state.statusFilter
        );
    }
    if (state.searchQuery) {
        const q = state.searchQuery.toLowerCase();
        filtered = filtered.filter(r =>
            (r.referensi_regulasi || '').toLowerCase().includes(q) ||
            (r.aspek || '').toLowerCase().includes(q) ||
            (r.bab_pasal_ayat || '').toLowerCase().includes(q) ||
            (r.point_ketentuan || '').toLowerCase().includes(q) ||
            (r.pemeriksaan || '').toLowerCase().includes(q) ||
            (r.metode_audit || '').toLowerCase().includes(q) ||
            (r.kebutuhan_bukti || '').toLowerCase().includes(q) ||
            (r.catatan_temuan || '').toLowerCase().includes(q)
        );
    }
    return filtered;
}

filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        filterBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.filter = btn.dataset.filter;
        if (state.currentData) {
            renderTable(state.currentData.results || []);
            updateSelectAllCheckbox();
        }
    });
});

if (statusFilterSelect) {
    statusFilterSelect.addEventListener('change', (e) => {
        state.statusFilter = e.target.value;
        if (state.currentData) {
            renderTable(state.currentData.results || []);
            updateSelectAllCheckbox();
        }
    });
}

if (searchInput) {
    searchInput.addEventListener('input', (e) => {
        state.searchQuery = e.target.value;
        if (state.currentData) {
            renderTable(state.currentData.results || []);
            updateSelectAllCheckbox();
        }
    });
}

// ====== EXPORT & COPY (Tool 1) ======
if (exportBtn) {
    exportBtn.addEventListener('click', () => {
        if (state.currentResultId) {
            window.location.href = `/api/export/${state.currentResultId}`;
            showToast('Mengekspor ke Excel...', 'info');
        }
    });
}

if (copyBtn) {
    copyBtn.addEventListener('click', () => {
        if (!state.currentData || !state.currentData.results) return;
        const results = state.currentData.results;
        let text = `HASIL ANALISIS REGULASI\n`;
        text += `Nama: ${state.currentData.nama || state.currentData.filename || '-'}\n`;
        text += `Total: ${results.length} ketentuan\n`;
        text += `${'='.repeat(60)}\n\n`;
        results.forEach((r, i) => {
            text += `[${i + 1}] ${r.referensi_regulasi || '-'}\n`;
            text += `    Aspek: ${r.aspek || '-'}\n`;
            text += `    Struktur: ${r.bab_pasal_ayat || '-'}\n`;
            text += `    Ketentuan: ${r.point_ketentuan}\n`;
            text += `    Pemeriksaan: ${r.pemeriksaan}\n`;
            text += `    Metode: ${r.metode_audit || '-'}\n`;
            text += `    Bukti: ${r.kebutuhan_bukti || '-'}\n`;
            text += `    Status: ${r.status_kepatuhan || 'Belum Diaudit'}\n`;
            if (r.catatan_temuan) text += `    Catatan: ${r.catatan_temuan}\n`;
            text += `\n`;
        });
        navigator.clipboard.writeText(text).then(() => {
            showToast('Seluruh hasil disalin ke clipboard.', 'success');
        }).catch(() => showToast('Gagal menyalin.', 'error'));
    });
}

    if (clearResultBtn) {
    clearResultBtn.addEventListener('click', () => {
        resultSection.style.display = 'none';
        state.currentResultId = null;
        state.currentData = null;
        state.selectedRows.clear();
        exportBtn.disabled = true;
        exportPdfBtn.disabled = true;
        copyBtn.disabled = true;
        previewExpiredBanner.style.display = 'none';
        setStatus('Hasil ditutup. Silakan upload regulasi baru.', false);
        showToast('Hasil analisis ditutup.', 'info');
    });
}

    if (resetBtn) {
    resetBtn.addEventListener('click', () => {
        fileInput.value = '';
        fileNameDisplay.textContent = '';
        fileNameDisplay.style.display = 'none';
        const namaInput = document.getElementById('namaRegulasi');
        if (namaInput) namaInput.value = '';
        state.currentResultId = null;
        state.currentData = null;
        state.selectedRows = new Set();
        resultSection.style.display = 'none';
        exportBtn.disabled = true;
        exportPdfBtn.disabled = true;
        copyBtn.disabled = true;
        previewExpiredBanner.style.display = 'none';
        setStatus('Menunggu file...', false);
        showToast('Form dibersihkan.', 'info');
    });
}

// ====== TREE MODAL ======
function isLeaf(node) {
    return !node.children || node.children.length === 0;
}
function collectLeaves(node) {
    if (isLeaf(node)) return [node];
    const out = [];
    for (const c of node.children) out.push(...collectLeaves(c));
    return out;
}
function isNodeFullySelected(node) {
    const leaves = collectLeaves(node);
    if (leaves.length === 0) return false;
    return leaves.every(l => treeState.selectedLeaves.has(l.id));
}
function isNodePartiallySelected(node) {
    const leaves = collectLeaves(node);
    const sel = leaves.filter(l => treeState.selectedLeaves.has(l.id)).length;
    return sel > 0 && sel < leaves.length;
}
function toggleNode(node, forceCheck) {
    const leaves = collectLeaves(node);
    const isFully = isNodeFullySelected(node);
    const shouldCheck = forceCheck === undefined ? !isFully : forceCheck;
    for (const leaf of leaves) {
        if (shouldCheck) treeState.selectedLeaves.add(leaf.id);
        else treeState.selectedLeaves.delete(leaf.id);
    }
}
function findNodeById(tree, id) {
    for (const node of tree) {
        if (node.id === id) return node;
        const found = findNodeById(node.children || [], id);
        if (found) return found;
    }
    return null;
}
function getSelectedChunkIndices() {
    const set = new Set();
    for (const leafId of treeState.selectedLeaves) {
        const leaf = findNodeById(treeState.tree, leafId);
        if (leaf) leaf.chunk_indices.forEach(i => set.add(i));
    }
    return Array.from(set).sort((a, b) => a - b);
}
function getTopmostSelectedLabels() {
    const labels = [];
    function walk(node, parentSelected) {
        const isFully = isNodeFullySelected(node);
        if (isFully && !parentSelected) {
            labels.push(node.label);
            return;
        }
        for (const c of node.children || []) walk(c, isFully);
    }
    for (const root of treeState.tree) walk(root, false);
    return labels;
}
function countSelectedLeaves() { return treeState.selectedLeaves.size; }

function updateSelectedCount() {
    const n = countSelectedLeaves();
    if (treeSelectedCount) {
        treeSelectedCount.textContent = `${n} bagian terpilih`;
        treeSelectedCount.classList.toggle('has-selection', n > 0);
    }
    if (treeAnalyzeBtn) treeAnalyzeBtn.disabled = n === 0;
    scheduleEstimate();
}

function renderTreeNode(node, depth) {
    const leaf = isLeaf(node);
    const expanded = treeState.expanded.has(node.id);
    const fullySel = isNodeFullySelected(node);
    const pageInfo = (node.page_start != null && node.page_end != null)
        ? `<span class="tree-page">hal. ${node.page_start}${node.page_end !== node.page_start ? '–' + node.page_end : ''}</span>`
        : '';
    const icon = leaf
        ? '<i class="fas fa-file-lines"></i>'
        : (expanded ? '<i class="fas fa-folder-open"></i>' : '<i class="fas fa-folder"></i>');
    const expandBtn = leaf
        ? '<span class="tree-expand-spacer"></span>'
        : `<button class="tree-expand" data-expand-id="${escapeAttr(node.id)}" type="button">${expanded ? '▼' : '▶'}</button>`;
    const childrenHtml = (!leaf && expanded)
        ? `<div class="tree-children">${node.children.map(c => renderTreeNode(c, depth + 1)).join('')}</div>`
        : '';
    const isChecked = fullySel ? 'checked' : '';
    const leafClass = leaf ? 'is-leaf-row' : '';
    return `
            <div class="tree-node" data-node-id="${escapeAttr(node.id)}" data-depth="${depth}">
                <div class="tree-node-row ${leafClass}" data-row-id="${escapeAttr(node.id)}">
                    ${expandBtn}
                    <input type="checkbox" class="tree-checkbox"
                           data-check-id="${escapeAttr(node.id)}"
                           ${isChecked} />
                    <span class="tree-icon">${icon}</span>
                    <span class="tree-label" title="${escapeAttr(node.label)}">${escapeHtml(node.label)}</span>
                    ${pageInfo}
                </div>
                ${childrenHtml}
            </div>
        `;
}

function renderTree() {
    if (!treeContainer) return;
    if (!treeState.tree || treeState.tree.length === 0) {
        treeContainer.innerHTML = '<p style="padding:1rem;text-align:center;color:var(--text-muted);">Struktur tidak terdeteksi.</p>';
        return;
    }
    treeContainer.innerHTML = treeState.tree.map(n => renderTreeNode(n, 0)).join('');
    treeContainer.querySelectorAll('.tree-checkbox').forEach(cb => {
        const id = cb.dataset.checkId;
        const node = findNodeById(treeState.tree, id);
        if (node && isNodePartiallySelected(node)) cb.indeterminate = true;
    });
    treeContainer.querySelectorAll('[data-expand-id]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const id = btn.dataset.expandId;
            if (treeState.expanded.has(id)) treeState.expanded.delete(id);
            else treeState.expanded.add(id);
            renderTree();
        });
    });
    treeContainer.querySelectorAll('.tree-checkbox').forEach(cb => {
        cb.addEventListener('change', (e) => {
            e.stopPropagation();
            const id = cb.dataset.checkId;
            const node = findNodeById(treeState.tree, id);
            if (!node) return;
            toggleNode(node, cb.checked);
            renderTree();
            updateSelectedCount();
        });
        cb.addEventListener('click', (e) => e.stopPropagation());
    });
    treeContainer.querySelectorAll('.tree-node-row').forEach(row => {
        row.addEventListener('click', (e) => {
            if (e.target.closest('.tree-checkbox') || e.target.closest('.tree-expand')) return;
            const id = row.dataset.rowId;
            const node = findNodeById(treeState.tree, id);
            if (!node) return;
            toggleNode(node);
            renderTree();
            updateSelectedCount();
        });
    });
}

    function openTreeModal(previewData, options = {}) {
    treeState.previewId = previewData.preview_id;
    treeState.filename = previewData.filename || 'unknown';
    treeState.tree = previewData.tree || [];
    treeState.totalChunks = previewData.total_chunks || 0;
    treeState.expanded = new Set();
    treeState.selectedLeaves = new Set();
    treeState.isReAnalyze = options.isReAnalyze || false;

    for (const root of treeState.tree) treeState.expanded.add(root.id);

    if (options.preSelectLabels && options.preSelectLabels.length > 0) {
        preSelectByLabels(options.preSelectLabels);
    }

    // Build cache badge
    const cacheBadge = previewData.from_cache
        ? `<span class="cache-badge cache-badge-hit"
                     title="File yang sama pernah dianalisis — parsing di-skip, langsung load dari cache.">
                   <i class="fas fa-bolt"></i> Cache
               </span>`
        : (previewData.parse_time_ms
            ? `<span class="cache-badge cache-badge-parsed"
                         title="File baru — parsing dijalankan dalam ${(previewData.parse_time_ms / 1000).toFixed(1)} detik.">
                       <i class="fas fa-cog"></i> Parsing ${(previewData.parse_time_ms / 1000).toFixed(1)}s
                   </span>`
            : '');

    const subText = treeState.isReAnalyze
        ? `${escapeHtml(previewData.filename)} • ${previewData.total_chunks} potongan • Mode: ubah bagian`
        : `${escapeHtml(previewData.filename)} • ${previewData.total_chunks} potongan teks`;

    if (treeModalSub) {
        treeModalSub.innerHTML = `${subText}${cacheBadge}`;
    }

    if (treeModalOverlay) treeModalOverlay.style.display = 'flex';
    renderTree();
    updateSelectedCount();
    if (treeState.selectedLeaves.size > 0) fetchEstimate();
}

function preSelectByLabels(labels) {
    function walk(node) {
        if (labels.includes(node.label)) {
            for (const leaf of collectLeaves(node)) treeState.selectedLeaves.add(leaf.id);
            treeState.expanded.add(node.id);
        }
        for (const child of node.children || []) walk(child);
    }
    for (const root of treeState.tree) walk(root);
}

export function closeTreeModal() {
    if (treeModalOverlay) treeModalOverlay.style.display = 'none';
    treeState.previewId = null;
    treeState.tree = [];
    treeState.expanded = new Set();
    treeState.selectedLeaves = new Set();
    treeState.isReAnalyze = false;
    if (estimateDebounceTimer) clearTimeout(estimateDebounceTimer);
    if (estimateAbortController) estimateAbortController.abort();
}

if (treeModalClose) treeModalClose.addEventListener('click', closeTreeModal);
if (treeCancelBtn) treeCancelBtn.addEventListener('click', closeTreeModal);
if (treeModalOverlay) {
    treeModalOverlay.addEventListener('click', (e) => {
        if (e.target === treeModalOverlay) closeTreeModal();
    });
}
if (treeSelectAll) {
    treeSelectAll.addEventListener('click', () => {
        for (const root of treeState.tree) toggleNode(root, true);
        renderTree();
        updateSelectedCount();
    });
}
if (treeClearAll) {
    treeClearAll.addEventListener('click', () => {
        treeState.selectedLeaves.clear();
        renderTree();
        updateSelectedCount();
    });
}

// ====== ESTIMASI ======
let estimateDebounceTimer = null;
let estimateAbortController = null;

async function fetchEstimate() {
    if (!treeState.previewId || !treeEstimate) return;
    const indices = getSelectedChunkIndices();
    if (indices.length === 0) {
        treeEstimate.classList.remove('has-data');
        treeEstimate.innerHTML = `
                <i class="fas fa-info-circle"></i>
                <span class="tree-estimate-text">Pilih bagian untuk melihat estimasi</span>
            `;
        return;
    }
    treeEstimate.classList.remove('has-data');
    treeEstimate.innerHTML = `
            <i class="fas fa-spinner fa-spin"></i>
            <span class="tree-estimate-text">Menghitung estimasi...</span>
        `;
    if (estimateAbortController) estimateAbortController.abort();
    estimateAbortController = new AbortController();
    try {
        const res = await fetch('/api/estimate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                preview_id: treeState.previewId,
                selected_chunk_indices: indices,
            }),
            signal: estimateAbortController.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderEstimate(data);
    } catch (err) {
        if (err.name === 'AbortError') return;
        treeEstimate.classList.remove('has-data');
        treeEstimate.innerHTML = `
                <i class="fas fa-info-circle"></i>
                <span class="tree-estimate-text">${indices.length} bagian dipilih</span>
            `;
    }
}

function renderEstimate(data) {
    if (!treeEstimate) return;
    if (data.total_chunks === 0) {
        treeEstimate.classList.remove('has-data');
        treeEstimate.innerHTML = `
                <i class="fas fa-info-circle"></i>
                <span class="tree-estimate-text">Tidak ada chunk valid</span>
            `;
        return;
    }
    const chars = data.total_chars.toLocaleString('id-ID');
    const tokens = data.total_tokens.toLocaleString('id-ID');
    const costIdr = formatIdr(data.cost_idr);
    const time = formatDuration(data.time_seconds_estimate);
    treeEstimate.classList.add('has-data');
    treeEstimate.innerHTML = `
            <i class="fas fa-chart-line"></i>
            <span class="tree-estimate-text">
                <b>${data.total_chunks}</b> bagian
                <span class="estimate-sep">•</span>
                ~${chars} kar
                <span class="estimate-sep">•</span>
                <b>${data.estimated_batches}</b> request
                <span class="estimate-sep">•</span>
                ~${tokens} token
                <span class="estimate-sep">•</span>
                💵 ≈${costIdr}
                <span class="estimate-sep">•</span>
                ⏱️ ~${time}
            </span>
        `;
}

function scheduleEstimate() {
    if (estimateDebounceTimer) clearTimeout(estimateDebounceTimer);
    estimateDebounceTimer = setTimeout(fetchEstimate, 300);
}

// ====== ANALYZE (Tool 1) ======
if (treeAnalyzeBtn) {
    treeAnalyzeBtn.addEventListener('click', async () => {
        const indices = getSelectedChunkIndices();
        if (indices.length === 0) {
            showToast('Pilih minimal 1 bagian.', 'error');
            return;
        }
        const labels = getTopmostSelectedLabels();
        const previewId = treeState.previewId;
        const isReAnalyze = treeState.isReAnalyze;

        let nama;
        if (isReAnalyze && state.currentData) {
            nama = state.currentData.nama || state.currentData.filename || '';
        } else {
            const namaInput = document.getElementById('namaRegulasi');
            nama = (namaInput ? namaInput.value.trim() : '') || treeState.filename.replace(/\.[^.]+$/, '');
        }

        closeTreeModal();
        state.isAnalyzing = true;
        if (submitBtn) submitBtn.disabled = true;
        if (!isReAnalyze && resultSection) resultSection.style.display = 'none';
        if (statusEl) {
            statusEl.className = 'status-text';
            statusEl.innerHTML = '<span class="spinner"></span> Menganalisis dengan AI...';
        }
        setProgress(3, 'Mengirim chunk ke AI...');

        try {
            const run = await runJob('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    preview_id: previewId,
                    selected_chunk_indices: indices,
                    selected_labels: labels,
                    nama_regulasi: nama,
                }),
            }, {
                cancelAnchor: progressText,
                onProgress: (job, pct, label) => setProgress(pct, label),
            });

            if (!run.ok) {
                hideProgress();
                setStatus(`Gagal: ${run.error}`, true);
                showToast(run.cancelled ? 'Analisis dibatalkan.' : 'Analisis gagal: ' + run.error, run.cancelled ? 'info' : 'error');
                return;
            }
            const data = run.data;
            setProgress(100, 'Selesai!');

            setStatus(run.partial
                ? `Dibatalkan — hasil parsial: ${data.total_ketentuan} ketentuan. ${run.job.message}`
                : `Selesai. ${data.total_ketentuan} ketentuan dari ${data.total_chunks} potongan (${data.total_batches} API call).`, false);
            data.nama = nama;
            state.currentResultId = data.result_id;
            state.currentData = data;
            state.selectedRows = new Set();
            state.statusFilter = '';
            if (statusFilterSelect) statusFilterSelect.value = '';
            if (exportBtn) exportBtn.disabled = false;
            if (exportPdfBtn) exportPdfBtn.disabled = false;
            if (copyBtn) copyBtn.disabled = false;
            if (previewExpiredBanner) previewExpiredBanner.style.display = 'none';
            renderSummary(data);
            renderFilterBadge(data.filter_applied || []);
            renderChunkErrors(data.chunk_errors);
            renderTable(data.results);
            updateProgressBadge();
            if (resultSection) resultSection.style.display = 'block';
            if (!isReAnalyze && resultSection) resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
            saveToHistory(data);
            if (run.partial) showToast('Analisis dibatalkan — hasil parsial ditampilkan.', 'info');
            else showToast(isReAnalyze ? 'Analisis ulang selesai! 🎉' : 'Analisis selesai! 🎉', 'success');
        } catch (err) {
            setStatus(`Gagal: ${err.message}`, true);
            showToast('Gagal terhubung ke server.', 'error');
        } finally {
            if (submitBtn) submitBtn.disabled = false;
            state.isAnalyzing = false;
            setTimeout(hideProgress, 2000);
        }
    });
}

// ====== UBAH BAGIAN (Tool 1) ======
if (changeFilterBtn) {
    changeFilterBtn.addEventListener('click', async () => {
        if (!state.currentData) return;
        const previewId = state.currentData.preview_id;
        if (!previewId) {
            if (previewExpiredBanner) previewExpiredBanner.style.display = 'flex';
            showToast('Preview tidak tersedia. Upload ulang file.', 'error');
            return;
        }
        changeFilterBtn.disabled = true;
        changeFilterBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Memuat...';
        try {
            const res = await fetch(`/api/preview/${previewId}`);
            if (!res.ok) {
                if (res.status === 404) {
                    if (previewExpiredBanner) previewExpiredBanner.style.display = 'flex';
                    showToast('Preview kedaluwarsa. Upload ulang file.', 'error');
                } else showToast('Gagal memuat preview.', 'error');
                return;
            }
            const previewData = await res.json();
            openTreeModal(previewData, {
                isReAnalyze: true,
                preSelectLabels: state.currentData.filter_applied || [],
            });
        } catch (err) {
            showToast(`Gagal memuat preview: ${err.message}`, 'error');
        } finally {
            changeFilterBtn.disabled = false;
            changeFilterBtn.innerHTML = '<i class="fas fa-sliders"></i> Ubah Bagian';
        }
    });
}

// ====== FORM SUBMIT (Tool 1) ======
if (form) {
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (previewExpiredBanner) previewExpiredBanner.style.display = 'none';
        if (!fileInput.files.length) {
            setStatus('Silakan pilih file terlebih dahulu.', true);
            showToast('Pilih file terlebih dahulu!', 'error');
            return;
        }
        const file = fileInput.files[0];
        if (file.size > 10 * 1024 * 1024) {
            setStatus('File terlalu besar. Maksimal 10MB.', true);
            showToast('File terlalu besar!', 'error');
            return;
        }
        if (submitBtn) submitBtn.disabled = true;
        state.isAnalyzing = true;
        if (resultSection) resultSection.style.display = 'none';
        if (statusEl) {
            statusEl.className = 'status-text';
            statusEl.innerHTML = '<span class="spinner"></span> Membaca struktur dokumen...';
        }
        setProgress(20, 'Mengekstrak teks...');

        const fd = new FormData();
        fd.append('file', file);
        try {
            setProgress(50, 'Mendeteksi struktur...');
            const res = await fetch('/api/preview', { method: 'POST', body: fd });
            const data = await res.json();
            if (!res.ok) {
                setStatus(`Gagal: ${data.detail || 'Error.'}`, true);
                showToast('Gagal: ' + (data.detail || 'Server error'), 'error');
                hideProgress();
                return;
            }
            setProgress(100, 'Struktur siap.');
            setStatus(`Struktur: ${data.total_chunks} potongan. Pilih bagian.`, false);
            setTimeout(() => {
                hideProgress();
                openTreeModal(data, { isReAnalyze: false });
            }, 300);
        } catch (err) {
            setStatus(`Gagal: ${err.message}`, true);
            showToast('Gagal terhubung ke server.', 'error');
            hideProgress();
        } finally {
            if (submitBtn) submitBtn.disabled = false;
            state.isAnalyzing = false;
        }
    });
}

    if (exportPdfBtn) {
    exportPdfBtn.addEventListener('click', () => {
        if (state.currentResultId) {
            window.location.href = `/api/export-pdf/${state.currentResultId}`;
            showToast('Mengekspor ke PDF...', 'info');
        }
    });
}

onThemeChange(updateDonutChart);
