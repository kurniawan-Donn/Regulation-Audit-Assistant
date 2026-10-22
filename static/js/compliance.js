/**
 * Tool 3 — Compliance Review: mode upload/database, analisis (job), tabel
 * status, import klausul, ringkasan eksekutif, export.
 */

import {
    $,
    $$,
    escapeAttr,
    escapeHtml,
    formatFileSize,
    onPageEnter,
    showToast,
    state,
} from './core.js';
import { runJob } from './jobs.js';
import { saveToHistory } from './history.js';

    // ============================================================
// COMPLIANCE REVIEW (Tool 3)
// ============================================================

const COMPLIANCE_STATUS_OPTIONS = [
    "PATUH",
    "PATUH DENGAN CATATAN",
    "TIDAK PATUH",
    "TIDAK RELEVAN",
    "PERLU VERIFIKASI",
];

export const complianceState = {
    previewId: null,
    resultId: null,
    data: null,
    searchQuery: '',
    statusFilter: '',
    selectedRows: new Set(),
    contractFile: null,
    regulationFiles: [],
    pendingAnalysisIndices: [],  
};

// ---- DOM Refs ----
const complianceUploadForm = $('#complianceUploadForm');
const complianceContractZone = $('#complianceContractZone');
const complianceContractFile = $('#complianceContractFile');
const complianceContractFileName = $('#complianceContractFileName');
const complianceRegulationZone = $('#complianceRegulationZone');
const complianceRegulationFiles = $('#complianceRegulationFiles');
const complianceRegulationFileNames = $('#complianceRegulationFileNames');
const complianceNamaKontrak = $('#complianceNamaKontrak');
const complianceFilterKontrak = $('#complianceFilterKontrak');
const complianceSubmitBtn = $('#complianceSubmitBtn');
const complianceResetBtn = $('#complianceResetBtn');
const complianceStatusEl = $('#complianceStatus');
const complianceProgressContainer = $('#complianceProgressContainer');
const complianceProgressBar = $('#complianceProgressBar');
const complianceProgressText = $('#complianceProgressText');
export const complianceResultSection = $('#complianceResultSection');
const complianceResultMeta = $('#complianceResultMeta');
const complianceSummaryGrid = $('#complianceSummaryGrid');
export const complianceSearchInput = $('#complianceSearchInput');
export const complianceStatusFilter = $('#complianceStatusFilter');
const complianceBulkToolbar = $('#complianceBulkToolbar');
const complianceBulkCount = $('#complianceBulkCount');
const complianceBulkStatusSelect = $('#complianceBulkStatusSelect');
const complianceBulkDeleteBtn = $('#complianceBulkDeleteBtn');
const complianceBulkClearBtn = $('#complianceBulkClearBtn');
const complianceAddRowBtn = $('#complianceAddRowBtn');
const complianceSelectAllCheckbox = $('#complianceSelectAllCheckbox');
const complianceResultBody = $('#complianceResultBody');
const complianceEmptyState = $('#complianceEmptyState');
const complianceCopyMdBtn = $('#complianceCopyMdBtn');
export const complianceExportBtn = $('#complianceExportBtn');
const complianceClearResultBtn = $('#complianceClearResultBtn');
const complianceExecutiveSummary = $('#complianceExecutiveSummary');
const complianceExecutiveSummaryEdit = $('#complianceExecutiveSummaryEdit');
const complianceExecutiveSummaryTextarea = $('#complianceExecutiveSummaryTextarea');
const complianceEditSummaryBtn = $('#complianceEditSummaryBtn');
const complianceCancelSummaryBtn = $('#complianceCancelSummaryBtn');
const complianceSaveSummaryBtn = $('#complianceSaveSummaryBtn');
const compliancePendingBanner = $('#compliancePendingBanner');
const compliancePendingText = $('#compliancePendingText');
const complianceAnalyzePendingBtn = $('#complianceAnalyzePendingBtn');
const complianceDismissPendingBtn = $('#complianceDismissPendingBtn');

// Add row modal
export const complianceAddRowModalOverlay = $('#complianceAddRowModalOverlay');
const complianceAddRowModalClose = $('#complianceAddRowModalClose');
const complianceAddRowCancelBtn = $('#complianceAddRowCancelBtn');
const complianceAddRowSaveBtn = $('#complianceAddRowSaveBtn');
const complianceAddKlausulRef = $('#complianceAddKlausulRef');
const complianceAddKlausulText = $('#complianceAddKlausulText');
const complianceAddRegulasiRef = $('#complianceAddRegulasiRef');
const complianceAddStatus = $('#complianceAddStatus');
const complianceAddAnalisis = $('#complianceAddAnalisis');

// ---- Status helpers ----
function complianceStatusClass(status) {
    if (status === 'PATUH') return 'status-patuh';
    if (status === 'PATUH DENGAN CATATAN') return 'status-catatan';
    if (status === 'TIDAK PATUH') return 'status-tidak-patuh';
    if (status === 'TIDAK RELEVAN') return 'status-tidak-relevan';
    return 'status-verifikasi';
}

function complianceStatusLabel(status) {
    if (status === 'PATUH') return 'Patuh';
    if (status === 'PATUH DENGAN CATATAN') return 'Patuh dengan Catatan';
    if (status === 'TIDAK PATUH') return 'Tidak Patuh';
    if (status === 'TIDAK RELEVAN') return 'Tidak Relevan';
    return 'Perlu Verifikasi';
}

function complianceRowClass(status) {
    if (status === 'PATUH') return 'row-patuh';
    if (status === 'PATUH DENGAN CATATAN') return 'row-catatan';
    if (status === 'TIDAK PATUH') return 'row-tidak-patuh';
    if (status === 'TIDAK RELEVAN') return 'row-tidak-relevan';
    return 'row-verifikasi';
}

// ---- Progress helpers ----
function setComplianceStatus(text, isError) {
    if (!complianceStatusEl) return;
    complianceStatusEl.className = 'status-text';
    if (isError === true) {
        complianceStatusEl.classList.add('error');
        complianceStatusEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${escapeHtml(text)}`;
    } else if (isError === false) {
        complianceStatusEl.classList.add('success');
        complianceStatusEl.innerHTML = `<i class="fas fa-check-circle"></i> ${escapeHtml(text)}`;
    } else {
        complianceStatusEl.textContent = text;
    }
}

function setComplianceProgress(percent, text) {
    if (!complianceProgressContainer) return;
    complianceProgressContainer.style.display = 'block';
    complianceProgressBar.style.width = percent + '%';
    complianceProgressText.textContent = text || `${Math.round(percent)}%`;
    if (percent >= 100) {
        setTimeout(() => {
            complianceProgressContainer.style.display = 'none';
            complianceProgressText.textContent = '';
        }, 1500);
    }
}

function hideComplianceProgress() {
    if (!complianceProgressContainer) return;
    complianceProgressContainer.style.display = 'none';
    complianceProgressText.textContent = '';
    complianceProgressBar.style.width = '0%';
}

// ---- Upload UI ----
function updateContractFileNameDisplay() {
    if (!complianceContractFileName) return;
    if (complianceContractFile && complianceContractFile.files.length) {
        complianceContractFileName.textContent = `📄 ${complianceContractFile.files[0].name} (${formatFileSize(complianceContractFile.files[0].size)})`;
        complianceContractFileName.style.display = 'block';
    } else {
        complianceContractFileName.textContent = '';
        complianceContractFileName.style.display = 'none';
    }
}

        function updateRegulationFileNamesDisplay() {
    if (!complianceRegulationFileNames) return;

    const files = complianceRegulationFiles
        ? Array.from(complianceRegulationFiles.files)
        : [];

    // Hapus class multi dulu
    complianceRegulationFileNames.classList.remove('multi');

    if (!files.length) {
        complianceRegulationFileNames.innerHTML = '';
        complianceRegulationFileNames.style.display = 'none';
        return;
    }

    // Kalau cuma 1 file — display inline biasa
    if (files.length === 1) {
        const f = files[0];
        complianceRegulationFileNames.textContent =
            `📄 ${f.name} (${formatFileSize(f.size)})`;
        complianceRegulationFileNames.style.display = 'block';
        return;
    }

    // Multi file — tampilkan sebagai list
    complianceRegulationFileNames.classList.add('multi');
    complianceRegulationFileNames.innerHTML = files.map(f =>
        `<div class="file-item">📄 ${escapeHtml(f.name)} <span style="color:var(--text-soft); font-size:0.72rem;">(${formatFileSize(f.size)})</span></div>`
    ).join('');
    complianceRegulationFileNames.style.display = 'block';
}

// Drag & drop: contract
if (complianceContractZone) {
    complianceContractZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        complianceContractZone.classList.add('dragover');
    });
    complianceContractZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        complianceContractZone.classList.remove('dragover');
    });
    complianceContractZone.addEventListener('drop', (e) => {
        e.preventDefault();
        complianceContractZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            complianceContractFile.files = e.dataTransfer.files;
            updateContractFileNameDisplay();
        }
    });
}
if (complianceContractFile) {
    complianceContractFile.addEventListener('change', updateContractFileNameDisplay);
}

// Drag & drop: regulations
    if (complianceRegulationZone) {
    complianceRegulationZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        complianceRegulationZone.classList.add('dragover');
    });
    complianceRegulationZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        complianceRegulationZone.classList.remove('dragover');
    });
    complianceRegulationZone.addEventListener('drop', (e) => {
        e.preventDefault();
        complianceRegulationZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            // Gunakan DataTransfer API untuk preserve multiple files (fix Chrome bug)
            const dt = new DataTransfer();
            for (let i = 0; i < e.dataTransfer.files.length; i++) {
                dt.items.add(e.dataTransfer.files[i]);
            }
            complianceRegulationFiles.files = dt.files;
            updateRegulationFileNamesDisplay();
        }
    });
}

if (complianceRegulationFiles) {
    complianceRegulationFiles.addEventListener('change', updateRegulationFileNamesDisplay);
}

// ---- Summary Grid ----
export function renderComplianceSummary(data) {
    if (!complianceSummaryGrid) return;
    complianceSummaryGrid.innerHTML = `
            <div class="compliance-stat stat-total">
                <strong>${data.total_items || 0}</strong>
                <span>Total Klausul</span>
            </div>
            <div class="compliance-stat stat-patuh">
                <strong>${data.total_patuh || 0}</strong>
                <span>Patuh</span>
            </div>
            <div class="compliance-stat stat-catatan">
                <strong>${data.total_patuh_catatan || 0}</strong>
                <span>Patuh dgn Catatan</span>
            </div>
            <div class="compliance-stat stat-tidak-patuh">
                <strong>${data.total_tidak_patuh || 0}</strong>
                <span>Tidak Patuh</span>
            </div>
            <div class="compliance-stat stat-tidak-relevan">
                <strong>${data.total_tidak_relevan || 0}</strong>
                <span>Tidak Relevan</span>
            </div>
            <div class="compliance-stat stat-verifikasi" title="AI tidak memberi putusan yang andal — wajib dicek auditor">
                <strong>${data.total_perlu_verifikasi || 0}</strong>
                <span>Perlu Verifikasi</span>
            </div>
        `;
}

export function renderComplianceMeta(data) {
    if (!complianceResultMeta) return;
    const contract = escapeHtml(data.contract_filename || '-');
    const regs = (data.regulation_filenames || []).length;
    const filterInfo = data.filter_applied
        ? ` <span class="meta-sep">•</span> Filter: <b>${escapeHtml(data.filter_applied)}</b>`
        : '';
    complianceResultMeta.innerHTML = `
            Kontrak: <b>${contract}</b>
            <span class="meta-sep">•</span>
            Regulasi: <b>${regs} file</b>
            <span class="meta-sep">•</span>
            Klausul dianalisis: <b>${data.total_contract_chunks || 0}</b>
            ${filterInfo}
            ${(data.warnings || []).map(w =>
                `<div class="compliance-warning"><i class="fas fa-triangle-exclamation"></i> ${escapeHtml(w)}</div>`
            ).join('')}
        `;
}

// ---- Tabel ----
function complianceApplyFilter(items) {
    let filtered = [...items];

    if (complianceState.statusFilter) {
        filtered = filtered.filter(it => it.status === complianceState.statusFilter);
    }

    if (complianceState.searchQuery) {
        const q = complianceState.searchQuery.toLowerCase();
        filtered = filtered.filter(it =>
            (it.klausul_ref || '').toLowerCase().includes(q) ||
            (it.klausul_text || '').toLowerCase().includes(q) ||
            (it.regulasi_ref || '').toLowerCase().includes(q) ||
            (it.analisis || '').toLowerCase().includes(q)
        );
    }

    return filtered;
}

    // ============================================================
// PENDING ANALYSIS BANNER
// ============================================================

function showPendingAnalysisBanner(indices) {
    complianceState.pendingAnalysisIndices = indices || [];
    if (!compliancePendingBanner) return;

    if (complianceState.pendingAnalysisIndices.length === 0) {
        compliancePendingBanner.style.display = 'none';
        return;
    }

    compliancePendingBanner.style.display = 'flex';
    if (compliancePendingText) {
        const n = complianceState.pendingAnalysisIndices.length;
        compliancePendingText.textContent = `${n} klausul baru diimpor tanpa analisis AI.`;
    }
}

export function hidePendingAnalysisBanner() {
    if (compliancePendingBanner) compliancePendingBanner.style.display = 'none';
    complianceState.pendingAnalysisIndices = [];
}

if (complianceDismissPendingBtn) {
    complianceDismissPendingBtn.addEventListener('click', () => {
        hidePendingAnalysisBanner();
        showToast('Banner disembunyikan. Klik "Tambah Klausul" kapan saja untuk analisis.', 'info');
    });
}

if (complianceAnalyzePendingBtn) {
    complianceAnalyzePendingBtn.addEventListener('click', async () => {
        const indices = complianceState.pendingAnalysisIndices;
        if (!indices.length) {
            showToast('Tidak ada klausul untuk dianalisis.', 'info');
            return;
        }

        complianceAnalyzePendingBtn.disabled = true;
        complianceAnalyzePendingBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menganalisis...';

        try {
            const run = await runJob(`/api/compliance/${complianceState.resultId}/analyze-items`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_indices: indices }),
            }, {
                cancelAnchor: complianceAnalyzePendingBtn,
            });

            if (!run.ok) throw new Error(run.error);

            const affected = (run.job.extra && run.job.extra.affected) || 0;
            await reloadComplianceResult();

            // Highlight rows yang baru dianalisis
            setTimeout(() => {
                indices.forEach(idx => {
                    const row = document.querySelector(`#complianceResultBody tr[data-idx="${idx}"]`);
                    if (row) {
                        row.classList.add('new-row-highlight');
                        setTimeout(() => row.classList.remove('new-row-highlight'), 3500);
                    }
                });
            }, 300);

            hidePendingAnalysisBanner();
            showToast(`${affected} klausul berhasil dianalisis AI.`, 'success');
        } catch (err) {
            showToast(`Gagal analisis: ${err.message}`, 'error');
        } finally {
            complianceAnalyzePendingBtn.disabled = false;
            complianceAnalyzePendingBtn.innerHTML = '<i class="fas fa-wand-magic-sparkles"></i> Analisis Sekarang';
        }
    });
}

    export function renderComplianceTable(items) {
    if (!complianceResultBody) return;
    const filtered = complianceApplyFilter(items || []);

    if (filtered.length === 0) {
        complianceResultBody.innerHTML = '';
        if (complianceEmptyState) complianceEmptyState.style.display = 'block';
        updateComplianceBulkToolbar();
        updateComplianceSelectAll();
        return;
    }
    if (complianceEmptyState) complianceEmptyState.style.display = 'none';

    complianceResultBody.innerHTML = filtered.map((item, i) => {
        const realIdx = (complianceState.data.items || []).indexOf(item);
        const isChecked = complianceState.selectedRows.has(realIdx);
        const status = item.status || 'PERLU VERIFIKASI';
        const statusClass = complianceStatusClass(status);
        const reviewNotes = (item.validation_notes || []).join(' ');
        const reviewBadge = item.needs_review
            ? `<span class="compliance-review-badge" title="${escapeAttr(reviewNotes || 'Perlu ditinjau auditor')}">
                       <i class="fas fa-flag"></i> Tinjau
                   </span>`
            : '';
        const rowClass = complianceRowClass(status);

        // Custom cell untuk kolom Klausul — gabungkan ref + text
        const klausulRef = item.klausul_ref || '';
        const klausulText = item.klausul_text || '';

        const klausulCell = `
                <td class="editable-cell compliance-klausul-ref" data-idx="${realIdx}">
                    <div class="cell-content multiline compliance-klausul-ref-line"
                         contenteditable="true"
                         spellcheck="false"
                         data-field="klausul_ref"
                         data-original="${escapeAttr(klausulRef)}"
                         title="Referensi klausul (mis. Pasal 6A ayat (1))">${escapeHtml(klausulRef)}</div>
                    <div class="cell-content multiline compliance-klausul-text-line"
                         contenteditable="true"
                         spellcheck="false"
                         data-field="klausul_text"
                         data-original="${escapeAttr(klausulText)}">${escapeHtml(klausulText)}</div>
                </td>`;

        // Cell biasa untuk field lain
                    // Cell biasa dengan placeholder
        const textCell = (field, value, extraCls = '') => {
            const isEmpty = !value || !value.trim();
            const placeholder = field === 'regulasi_ref'
                ? '⚠ Belum ada regulasi acuan — isi manual atau jalankan "Analisis AI" untuk baris ini'
                : (field === 'analisis'
                    ? '⚠ Belum dianalisis — isi manual atau jalankan "Analisis AI" untuk baris ini'
                    : '');
            const displayContent = isEmpty && placeholder
                ? `<span class="cell-placeholder">${placeholder}</span>`
                : escapeHtml(value);

            return `
                    <td class="editable-cell ${extraCls}" data-idx="${realIdx}">
                        <div class="cell-content multiline ${isEmpty && placeholder ? 'is-empty' : ''}"
                             contenteditable="true"
                             spellcheck="false"
                             data-field="${field}"
                             data-original="${escapeAttr(value)}">${displayContent}</div>
                    </td>`;
        };

        const statusCell = `
                <td class="editable-cell" data-idx="${realIdx}" data-field="status">
                    <div class="cell-content"
                         contenteditable="false"
                         data-original="${escapeAttr(status)}">
                        <span class="compliance-status-pill ${statusClass}">${escapeHtml(complianceStatusLabel(status))}</span>
                        ${reviewBadge}
                    </div>
                </td>`;

        return `
                <tr class="${rowClass} ${isChecked ? 'selected-row' : ''}" data-idx="${realIdx}">
                    <td class="row-checkbox-cell">
                        <input type="checkbox" class="row-checkbox"
                               data-row-idx="${realIdx}"
                               ${isChecked ? 'checked' : ''} />
                    </td>
                    <td class="row-no">${i + 1}</td>
                    ${klausulCell}
                    ${textCell('regulasi_ref', item.regulasi_ref || '')}
                    ${statusCell}
                    ${textCell('analisis', item.analisis || '')}
                    <td class="actions-cell">
                        <button class="row-action-btn" data-delete-idx="${realIdx}" title="Hapus">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
    }).join('');

    // Attach editable listeners
    complianceResultBody.querySelectorAll('.cell-content[contenteditable="true"]').forEach(el => {
        el.addEventListener('focus', () => el.classList.add('editing'));
        el.addEventListener('blur', onComplianceCellBlur);
        el.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                el.textContent = el.dataset.original || '';
                el.blur();
            }
        });
    });

    // Attach row checkbox
    complianceResultBody.querySelectorAll('.row-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
            const idx = parseInt(cb.dataset.rowIdx, 10);
            if (cb.checked) complianceState.selectedRows.add(idx);
            else complianceState.selectedRows.delete(idx);
            cb.closest('tr').classList.toggle('selected-row', cb.checked);
            updateComplianceBulkToolbar();
            updateComplianceSelectAll();
        });
    });

    // Attach delete
    complianceResultBody.querySelectorAll('[data-delete-idx]').forEach(btn => {
        btn.addEventListener('click', () => {
            const idx = parseInt(btn.dataset.deleteIdx, 10);
            deleteComplianceSingleRow(idx);
        });
    });

    // Attach status pill click
    complianceResultBody.querySelectorAll('.compliance-status-pill').forEach(pill => {
        pill.addEventListener('click', (e) => {
            e.stopPropagation();
            const td = pill.closest('td');
            const idx = parseInt(td.dataset.idx, 10);
            showComplianceStatusMenu(pill, idx);
        });
    });

    updateComplianceBulkToolbar();
    updateComplianceSelectAll();
}

// Status dropdown menu
function showComplianceStatusMenu(anchorEl, itemIdx) {
    // Hapus menu lama kalau ada
    document.querySelectorAll('.compliance-status-menu').forEach(m => m.remove());

    const menu = document.createElement('div');
    menu.className = 'compliance-status-menu';
    menu.innerHTML = COMPLIANCE_STATUS_OPTIONS.map(s =>
        `<button class="compliance-status-option" data-status="${escapeAttr(s)}">
                <span class="compliance-status-pill ${complianceStatusClass(s)}">${escapeHtml(complianceStatusLabel(s))}</span>
            </button>`
    ).join('');

    document.body.appendChild(menu);

    const rect = anchorEl.getBoundingClientRect();
    menu.style.top = (rect.bottom + 4 + window.scrollY) + 'px';
    menu.style.left = (rect.left + window.scrollX) + 'px';

    menu.querySelectorAll('.compliance-status-option').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const newStatus = btn.dataset.status;
            menu.remove();
            await updateComplianceItemStatus(itemIdx, newStatus);
        });
    });

    // Close on click outside
    setTimeout(() => {
        document.addEventListener('click', function closeMenu() {
            menu.remove();
            document.removeEventListener('click', closeMenu);
        }, { once: true });
    }, 10);
}

async function updateComplianceItemStatus(itemIdx, newStatus) {
    if (!complianceState.resultId) return;
    try {
        const res = await fetch(`/api/compliance/${complianceState.resultId}/items/${itemIdx}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const updated = await res.json();
        if (complianceState.data.items[itemIdx]) {
            Object.assign(complianceState.data.items[itemIdx], updated);
        }
        // Recompute summary
        recomputeComplianceCounts();
        renderComplianceSummary(complianceState.data);
        renderComplianceTable(complianceState.data.items);
        persistComplianceHistory();
        showToast(`Status diubah: ${complianceStatusLabel(newStatus)}`, 'success');
    } catch (err) {
        showToast(`Gagal ubah status: ${err.message}`, 'error');
    }
}

function recomputeComplianceCounts() {
    if (!complianceState.data || !complianceState.data.items) return;
    const items = complianceState.data.items;
    let patuh = 0, catatan = 0, tidak = 0, relevan = 0, verifikasi = 0;
    items.forEach(it => {
        if (it.status === 'PATUH') patuh++;
        else if (it.status === 'PATUH DENGAN CATATAN') catatan++;
        else if (it.status === 'TIDAK PATUH') tidak++;
        else if (it.status === 'TIDAK RELEVAN') relevan++;
        else verifikasi++;
    });
    complianceState.data.total_items = items.length;
    complianceState.data.total_patuh = patuh;
    complianceState.data.total_patuh_catatan = catatan;
    complianceState.data.total_tidak_patuh = tidak;
    complianceState.data.total_tidak_relevan = relevan;
    complianceState.data.total_perlu_verifikasi = verifikasi;
}

    async function onComplianceCellBlur(e) {
    const el = e.target;
    el.classList.remove('editing');
    if (el.querySelector('.cell-placeholder')) {
        el.innerHTML = `<span class="cell-placeholder">${el.querySelector('.cell-placeholder').textContent}</span>`;
        return;
    }

    const newValue = (el.innerText || '').trim();
    const original = el.dataset.original || '';
    if (newValue === original) return;

            const td = el.closest('td');
    const idx = parseInt(td.dataset.idx, 10);
    const field = el.dataset.field || td.dataset.field;
    if (!complianceState.data || !complianceState.data.items[idx]) return;

    complianceState.data.items[idx][field] = newValue;

    try {
        const res = await fetch(`/api/compliance/${complianceState.resultId}/items/${idx}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [field]: newValue }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const updated = await res.json();
        Object.assign(complianceState.data.items[idx], updated);
        el.dataset.original = newValue;
        el.classList.add('saved-flash');
        setTimeout(() => el.classList.remove('saved-flash'), 800);
        persistComplianceHistory();
        showToast('Tersimpan', 'success');
    } catch (err) {
        complianceState.data.items[idx][field] = original;
        el.textContent = original;
        showToast(`Gagal menyimpan: ${err.message}`, 'error');
    }
}

// ---- Bulk toolbar ----
function updateComplianceBulkToolbar() {
    if (!complianceBulkToolbar) return;
    const count = complianceState.selectedRows.size;
    if (count === 0) {
        complianceBulkToolbar.style.display = 'none';
    } else {
        complianceBulkToolbar.style.display = 'flex';
        complianceBulkCount.textContent = `${count} dipilih`;
    }
    if (complianceBulkStatusSelect) complianceBulkStatusSelect.value = '';
}

function updateComplianceSelectAll() {
    if (!complianceSelectAllCheckbox) return;
    if (!complianceState.data || !complianceState.data.items) {
        complianceSelectAllCheckbox.checked = false;
        complianceSelectAllCheckbox.indeterminate = false;
        return;
    }
    const visible = complianceApplyFilter(complianceState.data.items);
    const visibleIndices = visible.map(it => complianceState.data.items.indexOf(it));
    const selectedVisible = visibleIndices.filter(i => complianceState.selectedRows.has(i));
    const all = visibleIndices.length > 0 && selectedVisible.length === visibleIndices.length;
    const partial = selectedVisible.length > 0 && !all;
    complianceSelectAllCheckbox.checked = all;
    complianceSelectAllCheckbox.indeterminate = partial;
}

if (complianceSelectAllCheckbox) {
    complianceSelectAllCheckbox.addEventListener('change', (e) => {
        if (!complianceState.data || !complianceState.data.items) return;
        const visible = complianceApplyFilter(complianceState.data.items);
        const visibleIndices = visible.map(it => complianceState.data.items.indexOf(it));
        if (e.target.checked) visibleIndices.forEach(i => complianceState.selectedRows.add(i));
        else visibleIndices.forEach(i => complianceState.selectedRows.delete(i));
        renderComplianceTable(complianceState.data.items);
    });
}

if (complianceBulkClearBtn) {
    complianceBulkClearBtn.addEventListener('click', () => {
        complianceState.selectedRows.clear();
        renderComplianceTable(complianceState.data.items);
    });
}

if (complianceBulkStatusSelect) {
    complianceBulkStatusSelect.addEventListener('change', async () => {
        const newStatus = complianceBulkStatusSelect.value;
        if (!newStatus || complianceState.selectedRows.size === 0) return;

        const indices = Array.from(complianceState.selectedRows);
        complianceBulkStatusSelect.disabled = true;

        try {
            const res = await fetch(`/api/compliance/${complianceState.resultId}/items/bulk`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_indices: indices, status: newStatus }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();

            indices.forEach(i => {
                if (complianceState.data.items[i]) {
                    complianceState.data.items[i].status = newStatus;
                    complianceState.data.items[i].needs_review = newStatus === 'PERLU VERIFIKASI';
                }
            });
            complianceState.data.total_patuh = data.total_patuh;
            complianceState.data.total_patuh_catatan = data.total_patuh_catatan;
            complianceState.data.total_tidak_patuh = data.total_tidak_patuh;
            complianceState.data.total_tidak_relevan = data.total_tidak_relevan;
            complianceState.data.total_perlu_verifikasi = data.total_perlu_verifikasi || 0;

            complianceState.selectedRows.clear();
            renderComplianceSummary(complianceState.data);
            renderComplianceTable(complianceState.data.items);
            showToast(`${data.affected} klausul diubah ke ${complianceStatusLabel(newStatus)}.`, 'success');
        } catch (err) {
            showToast(`Gagal update: ${err.message}`, 'error');
        } finally {
            complianceBulkStatusSelect.disabled = false;
            complianceBulkStatusSelect.value = '';
        }
    });
}

if (complianceBulkDeleteBtn) {
    complianceBulkDeleteBtn.addEventListener('click', async () => {
        if (complianceState.selectedRows.size === 0) return;
        if (!confirm(`Hapus ${complianceState.selectedRows.size} klausul terpilih?`)) return;

        const indices = Array.from(complianceState.selectedRows);
        complianceBulkDeleteBtn.disabled = true;

        try {
            const res = await fetch(`/api/compliance/${complianceState.resultId}/items`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_indices: indices }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            await reloadComplianceResult();
            complianceState.selectedRows.clear();
            showToast(`${indices.length} klausul dihapus.`, 'success');
        } catch (err) {
            showToast(`Gagal menghapus: ${err.message}`, 'error');
        } finally {
            complianceBulkDeleteBtn.disabled = false;
        }
    });
}

async function deleteComplianceSingleRow(idx) {
    if (!complianceState.data || !complianceState.data.items[idx]) return;
    if (!confirm('Hapus klausul ini?')) return;

    try {
        const res = await fetch(`/api/compliance/${complianceState.resultId}/items`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_indices: [idx] }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        await reloadComplianceResult();
        complianceState.selectedRows.clear();
        showToast('Klausul dihapus.', 'success');
    } catch (err) {
        showToast(`Gagal menghapus: ${err.message}`, 'error');
    }
}

    function persistComplianceHistory() {
    if (!complianceState.data) return;
    // Hasil sudah disimpan server; cukup segarkan angka di daftar riwayat.
    const entry = state.history.find(h => h.id === complianceState.resultId);
    if (entry) {
        const d = complianceState.data;
        entry.total_items = d.total_items;
        entry.total_patuh = d.total_patuh;
        entry.total_patuh_catatan = d.total_patuh_catatan;
        entry.total_tidak_patuh = d.total_tidak_patuh;
        entry.total_tidak_relevan = d.total_tidak_relevan;
        entry.total_perlu_verifikasi = d.total_perlu_verifikasi || 0;
    }
}

    function highlightNewComplianceRows(startIdx, count) {
    if (count <= 0) return;
    setTimeout(() => {
        const rows = [];
        for (let i = 0; i < count; i++) {
            const row = document.querySelector(`#complianceResultBody tr[data-idx="${startIdx + i}"]`);
            if (row) rows.push(row);
        }
        if (rows.length === 0) return;

        // Scroll ke row pertama
        rows[0].scrollIntoView({ behavior: 'smooth', block: 'center' });

        // Flash animation
        rows.forEach(row => {
            row.classList.add('new-row-highlight');
            setTimeout(() => row.classList.remove('new-row-highlight'), 3500);
        });
    }, 300);
}

async function reloadComplianceResult() {
    try {
        const res = await fetch(`/api/compliance/${complianceState.resultId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        complianceState.data = data;
        renderComplianceSummary(data);
        renderComplianceMeta(data);
        renderComplianceTable(data.items);
        renderComplianceExecutiveSummary(data.executive_summary || '');
    } catch (err) {
        showToast(`Gagal memuat ulang: ${err.message}`, 'error');
    }
}

// ---- Search / Filter ----
if (complianceSearchInput) {
    complianceSearchInput.addEventListener('input', (e) => {
        complianceState.searchQuery = e.target.value;
        if (complianceState.data) renderComplianceTable(complianceState.data.items);
    });
}

if (complianceStatusFilter) {
    complianceStatusFilter.addEventListener('change', (e) => {
        complianceState.statusFilter = e.target.value;
        if (complianceState.data) renderComplianceTable(complianceState.data.items);
    });
}

// ---- Executive Summary ----
export function renderComplianceExecutiveSummary(text) {
    if (!complianceExecutiveSummary) return;
    if (!text) {
        complianceExecutiveSummary.innerHTML = '<em>Belum ada ringkasan eksekutif.</em>';
        return;
    }
    // Konversi markdown ringan
    let html = escapeHtml(text);
    // Bold **text**
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Split per baris
    const lines = html.split('\n');
    const rendered = lines.map(line => {
        const trimmed = line.trim();
        if (!trimmed) return '<span class="summary-line">&nbsp;</span>';
        // Heading: diawali ** atau angka+.
        if (/^\d+\./.test(trimmed) || trimmed.startsWith('<strong>')) {
            return `<span class="summary-heading">${trimmed}</span>`;
        }
        return `<span class="summary-line">${trimmed}</span>`;
    }).join('');
    complianceExecutiveSummary.innerHTML = rendered;
}

if (complianceEditSummaryBtn) {
    complianceEditSummaryBtn.addEventListener('click', () => {
        if (!complianceState.data) return;
        complianceExecutiveSummaryTextarea.value = complianceState.data.executive_summary || '';
        complianceExecutiveSummary.style.display = 'none';
        complianceExecutiveSummaryEdit.style.display = 'flex';
        complianceExecutiveSummaryTextarea.focus();
    });
}

if (complianceCancelSummaryBtn) {
    complianceCancelSummaryBtn.addEventListener('click', () => {
        complianceExecutiveSummary.style.display = 'block';
        complianceExecutiveSummaryEdit.style.display = 'none';
    });
}

if (complianceSaveSummaryBtn) {
    complianceSaveSummaryBtn.addEventListener('click', async () => {
        const newSummary = complianceExecutiveSummaryTextarea.value;
        complianceSaveSummaryBtn.disabled = true;
        complianceSaveSummaryBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';

        try {
            const res = await fetch(`/api/compliance/${complianceState.resultId}/executive-summary`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ executive_summary: newSummary }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            complianceState.data.executive_summary = data.executive_summary;
            renderComplianceExecutiveSummary(data.executive_summary);
            complianceExecutiveSummary.style.display = 'block';
            complianceExecutiveSummaryEdit.style.display = 'none';
            persistComplianceHistory();
            showToast('Ringkasan eksekutif tersimpan.', 'success');
        } catch (err) {
            showToast(`Gagal menyimpan: ${err.message}`, 'error');
        } finally {
            complianceSaveSummaryBtn.disabled = false;
            complianceSaveSummaryBtn.innerHTML = '<i class="fas fa-floppy-disk"></i> Simpan';
        }
    });
}

    // ---- Import PDF: DOM refs ----
const complianceInsertAfter = $('#complianceInsertAfter');
const complianceModalTabs = $$('.compliance-modal-tab');
const complianceModalTabContents = $$('.compliance-modal-tab-content');
const complianceImportZone = $('#complianceImportZone');
const complianceImportFile = $('#complianceImportFile');
const complianceImportPreviewWrap = $('#complianceImportPreviewWrap');
const complianceImportPreview = $('#complianceImportPreview');

// State untuk import PDF
const complianceImportState = {
    activeTab: 'manual',   // 'manual' | 'pdf'
    parsedClauses: [],     // dari /api/compliance/parse-contract
    selectedIndices: new Set(),
};

function switchComplianceModalTab(tabName) {
    complianceImportState.activeTab = tabName;

    complianceModalTabs.forEach(tab => {
        tab.classList.toggle('active', tab.dataset.complianceTab === tabName);
    });
    complianceModalTabContents.forEach(content => {
        content.style.display = content.dataset.complianceTabContent === tabName ? 'flex' : 'none';
    });

    // Update tombol save label
    if (complianceAddRowSaveBtn) {
        if (tabName === 'pdf') {
            const count = complianceImportState.selectedIndices.size;
            complianceAddRowSaveBtn.innerHTML = count > 0
                ? `<i class="fas fa-plus"></i> Impor ${count} Klausul`
                : '<i class="fas fa-plus"></i> Impor Klausul';
        } else {
            complianceAddRowSaveBtn.innerHTML = '<i class="fas fa-plus"></i> Tambah Klausul';
        }
    }
}

complianceModalTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        switchComplianceModalTab(tab.dataset.complianceTab);
    });
});

// ---- Import PDF: upload handler ----
if (complianceImportZone) {
    complianceImportZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        complianceImportZone.classList.add('dragover');
    });
    complianceImportZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        complianceImportZone.classList.remove('dragover');
    });
    complianceImportZone.addEventListener('drop', (e) => {
        e.preventDefault();
        complianceImportZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            complianceImportFile.files = e.dataTransfer.files;
            handleImportFileSelected();
        }
    });
}

if (complianceImportFile) {
    complianceImportFile.addEventListener('change', handleImportFileSelected);
}

async function handleImportFileSelected() {
    if (!complianceImportFile || !complianceImportFile.files.length) return;

    const file = complianceImportFile.files[0];
    if (file.size > 10 * 1024 * 1024) {
        showToast('File terlalu besar. Maks 10 MB.', 'error');
        return;
    }

    complianceImportPreviewWrap.style.display = 'block';
    complianceImportPreview.innerHTML = `
            <div class="compliance-import-loading">
                <i class="fas fa-spinner fa-spin"></i> Mem-parse ${escapeHtml(file.name)}...
            </div>
        `;

    try {
        const fd = new FormData();
        fd.append('file', file);

        const res = await fetch('/api/compliance/parse-contract', {
            method: 'POST',
            body: fd,
        });
        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.detail || `HTTP ${res.status}`);
        }

        complianceImportState.parsedClauses = data.clauses || [];
        complianceImportState.selectedIndices = new Set();

        // Default: pilih semua
        complianceImportState.parsedClauses.forEach((_, i) => {
            complianceImportState.selectedIndices.add(i);
        });

        renderComplianceImportPreview(data.filename);
        switchComplianceModalTab('pdf');
    } catch (err) {
        complianceImportPreview.innerHTML = `
                <div class="compliance-import-loading" style="color:var(--warn);">
                    <i class="fas fa-exclamation-circle"></i>
                    Gagal parse: ${escapeHtml(err.message)}
                </div>
            `;
    }
}

function renderComplianceImportPreview(filename) {
    const clauses = complianceImportState.parsedClauses;
    if (!clauses.length) {
        complianceImportPreview.innerHTML = `
                <div class="compliance-import-loading">
                    <i class="fas fa-info-circle"></i>
                    Tidak ada klausul terdeteksi.
                </div>
            `;
        return;
    }

    const itemsHtml = clauses.map((c, i) => {
        const ref = c.klausul_ref || c.pasal || `Klausul ${i + 1}`;
        const text = (c.text || '').slice(0, 200) + ((c.text || '').length > 200 ? '...' : '');
        const checked = complianceImportState.selectedIndices.has(i) ? 'checked' : '';
        return `
                <label class="compliance-import-item" data-import-idx="${i}">
                    <input type="checkbox" data-import-check="${i}" ${checked} />
                    <div class="compliance-import-item-body">
                        <div class="compliance-import-item-ref">${escapeHtml(ref)}</div>
                        <div class="compliance-import-item-text">${escapeHtml(text)}</div>
                    </div>
                </label>
            `;
    }).join('');

    complianceImportPreview.innerHTML = `
            <div class="compliance-import-preview-header">
                <div>
                    <strong>${escapeHtml(filename)}</strong>
                    <span class="preview-count">
                        <span id="complianceImportSelectedCount">${complianceImportState.selectedIndices.size}</span>
                        / ${clauses.length} dipilih
                    </span>
                </div>
                <div class="compliance-import-preview-actions">
                    <button type="button" id="complianceImportSelectAll">Pilih Semua</button>
                    <button type="button" id="complianceImportClearAll">Kosongkan</button>
                </div>
            </div>
            ${itemsHtml}
        `;

    // Attach checkbox listeners
    complianceImportPreview.querySelectorAll('[data-import-check]').forEach(cb => {
        cb.addEventListener('change', (e) => {
            e.stopPropagation();
            const i = parseInt(cb.dataset.importCheck, 10);
            if (cb.checked) complianceImportState.selectedIndices.add(i);
            else complianceImportState.selectedIndices.delete(i);
            updateImportSelectedCount();
        });
    });

    // Klik row = toggle checkbox
    complianceImportPreview.querySelectorAll('.compliance-import-item').forEach(item => {
        item.addEventListener('click', (e) => {
            if (e.target.tagName === 'INPUT') return;
            const cb = item.querySelector('input[type="checkbox"]');
            if (cb) {
                cb.checked = !cb.checked;
                cb.dispatchEvent(new Event('change'));
            }
        });
    });

    // Select all / clear
    const selectAllBtn = document.getElementById('complianceImportSelectAll');
    const clearAllBtn = document.getElementById('complianceImportClearAll');

    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', (e) => {
            e.preventDefault();
            complianceImportState.selectedIndices = new Set(clauses.map((_, i) => i));
            complianceImportPreview.querySelectorAll('[data-import-check]').forEach(cb => {
                cb.checked = true;
            });
            updateImportSelectedCount();
        });
    }
    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', (e) => {
            e.preventDefault();
            complianceImportState.selectedIndices.clear();
            complianceImportPreview.querySelectorAll('[data-import-check]').forEach(cb => {
                cb.checked = false;
            });
            updateImportSelectedCount();
        });
    }
}

function updateImportSelectedCount() {
    const countEl = document.getElementById('complianceImportSelectedCount');
    if (countEl) {
        countEl.textContent = complianceImportState.selectedIndices.size;
    }
    // Update tombol save
    if (complianceAddRowSaveBtn && complianceImportState.activeTab === 'pdf') {
        const count = complianceImportState.selectedIndices.size;
        complianceAddRowSaveBtn.innerHTML = count > 0
            ? `<i class="fas fa-plus"></i> Impor ${count} Klausul`
            : '<i class="fas fa-plus"></i> Impor Klausul';
    }
}

// ---- Modal Open / Close ----
function openComplianceAddRowModal() {
    // Reset manual tab
    if (complianceAddKlausulRef) complianceAddKlausulRef.value = '';
    if (complianceAddKlausulText) complianceAddKlausulText.value = '';
    if (complianceAddRegulasiRef) complianceAddRegulasiRef.value = '';
    if (complianceAddStatus) complianceAddStatus.value = 'TIDAK RELEVAN';
    if (complianceAddAnalisis) complianceAddAnalisis.value = '';

    // Reset insert after
    if (complianceInsertAfter) complianceInsertAfter.value = '';

    // Reset import state
    complianceImportState.parsedClauses = [];
    complianceImportState.selectedIndices = new Set();
    if (complianceImportFile) complianceImportFile.value = '';
    if (complianceImportPreviewWrap) complianceImportPreviewWrap.style.display = 'none';
    if (complianceImportPreview) complianceImportPreview.innerHTML = '';

    // Switch ke tab manual
    switchComplianceModalTab('manual');

    if (complianceAddRowModalOverlay) complianceAddRowModalOverlay.style.display = 'flex';
    if (complianceAddKlausulRef) complianceAddKlausulRef.focus();
}

export function closeComplianceAddRowModal() {
    if (complianceAddRowModalOverlay) complianceAddRowModalOverlay.style.display = 'none';

    if (complianceImportFile) complianceImportFile.value = '';
    complianceImportState.parsedClauses = [];
    complianceImportState.selectedIndices = new Set();
    complianceImportState.activeTab = 'manual';
}

if (complianceAddRowBtn) complianceAddRowBtn.addEventListener('click', openComplianceAddRowModal);
if (complianceAddRowModalClose) complianceAddRowModalClose.addEventListener('click', closeComplianceAddRowModal);
if (complianceAddRowCancelBtn) complianceAddRowCancelBtn.addEventListener('click', closeComplianceAddRowModal);
if (complianceAddRowModalOverlay) {
    complianceAddRowModalOverlay.addEventListener('click', (e) => {
        if (e.target === complianceAddRowModalOverlay) closeComplianceAddRowModal();
    });
}

    if (complianceAddRowSaveBtn) {
    complianceAddRowSaveBtn.addEventListener('click', async () => {
        const tab = complianceImportState.activeTab;

        // Baca insert_after
        let insertAfter = null;
        if (complianceInsertAfter && complianceInsertAfter.value.trim()) {
            const v = parseInt(complianceInsertAfter.value, 10);
            if (!isNaN(v) && v >= 0) insertAfter = v;
        }

        if (tab === 'manual') {
            // === MODE MANUAL ===
            if (!complianceAddKlausulRef.value.trim() && !complianceAddAnalisis.value.trim()) {
                showToast('Isi minimal: Klausul atau Analisis.', 'error');
                return;
            }

            complianceAddRowSaveBtn.disabled = true;
            complianceAddRowSaveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';

            const payload = {
                klausul_ref: complianceAddKlausulRef ? complianceAddKlausulRef.value.trim() : '',
                klausul_text: complianceAddKlausulText ? complianceAddKlausulText.value.trim() : '',
                regulasi_ref: complianceAddRegulasiRef ? complianceAddRegulasiRef.value.trim() : '',
                status: complianceAddStatus ? complianceAddStatus.value : 'TIDAK RELEVAN',
                analisis: complianceAddAnalisis ? complianceAddAnalisis.value.trim() : '',
                insert_after: insertAfter,
            };

            try {
                const res = await fetch(`/api/compliance/${complianceState.resultId}/items`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                await reloadComplianceResult();
                closeComplianceAddRowModal();
                const posMsg = insertAfter !== null ? ` (setelah baris ${insertAfter})` : ' di akhir';
                showToast(`Klausul ditambahkan${posMsg}.`, 'success');
            } catch (err) {
                showToast(`Gagal menambah: ${err.message}`, 'error');
            } finally {
                complianceAddRowSaveBtn.disabled = false;
                complianceAddRowSaveBtn.innerHTML = '<i class="fas fa-plus"></i> Tambah Klausul';
            }

        } else {
            // === MODE IMPORT PDF ===
            const selected = complianceImportState.selectedIndices;
            if (selected.size === 0) {
                showToast('Pilih minimal 1 klausul untuk diimpor.', 'error');
                return;
            }

            const itemsToImport = Array.from(selected)
                .sort((a, b) => a - b)
                .map(i => complianceImportState.parsedClauses[i])
                .filter(Boolean)
                .map(c => ({
                    klausul_ref: c.klausul_ref || c.pasal || '',
                    klausul_text: c.text || '',
                    regulasi_ref: '',
                    // Belum dianalisis → bukan "Tidak Relevan"
                    status: 'PERLU VERIFIKASI',
                    analisis: '',
                }));

            complianceAddRowSaveBtn.disabled = true;
            console.log('🔍 [DEBUG] itemsToImport:', JSON.parse(JSON.stringify(itemsToImport)));
            complianceAddRowSaveBtn.disabled = true;
            complianceAddRowSaveBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Mengimpor ${itemsToImport.length} klausul...`;

            try {
                const res = await fetch(`/api/compliance/${complianceState.resultId}/items/batch-add`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        items: itemsToImport,
                        insert_after: insertAfter,
                    }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                                    const data = await res.json();
                await reloadComplianceResult();
                closeComplianceAddRowModal();

                // Kumpulkan indices yang baru diimpor
                const firstNewIdx = (insertAfter !== null)
                    ? insertAfter
                    : (complianceState.data.items.length - data.affected);
                const newIndices = [];
                for (let k = 0; k < data.affected; k++) {
                    newIndices.push(firstNewIdx + k);
                }

                // Highlight row baru
                highlightNewComplianceRows(firstNewIdx, data.affected);

                // Tampilkan banner pending analysis
                showPendingAnalysisBanner(newIndices);

                const posMsg = insertAfter !== null ? ` setelah baris ${insertAfter}` : ' di akhir';
                showToast(`${data.affected} klausul diimpor${posMsg}. Klik "Analisis Sekarang" untuk AI.`, 'success');
            } catch (err) {
                showToast(`Gagal import: ${err.message}`, 'error');
            } finally {
                complianceAddRowSaveBtn.disabled = false;
                complianceAddRowSaveBtn.innerHTML = '<i class="fas fa-plus"></i> Tambah Klausul';
            }
        }
    });
}

// ---- Copy Markdown ----
if (complianceCopyMdBtn) {
    complianceCopyMdBtn.addEventListener('click', async () => {
        if (!complianceState.resultId) return;
        try {
            const res = await fetch(`/api/compliance/${complianceState.resultId}/markdown`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            await navigator.clipboard.writeText(data.markdown);
            showToast('Markdown disalin ke clipboard.', 'success');
        } catch (err) {
            showToast(`Gagal copy: ${err.message}`, 'error');
        }
    });
}

// ---- Export Excel ----
if (complianceExportBtn) {
    complianceExportBtn.addEventListener('click', () => {
        if (complianceState.resultId) {
            window.location.href = `/api/compliance/export/${complianceState.resultId}`;
            showToast('Mengekspor ke Excel...', 'info');
        }
    });
}
    export const complianceExportPdfBtn = $('#complianceExportPdfBtn');
if (complianceExportPdfBtn) {
    complianceExportPdfBtn.addEventListener('click', () => {
        if (complianceState.resultId) {
            window.location.href = `/api/compliance/export-pdf/${complianceState.resultId}`;
            showToast('Mengekspor ke PDF...', 'info');
        }
    });
}

// ---- Clear Result ----
if (complianceClearResultBtn) {
    complianceClearResultBtn.addEventListener('click', () => {
        complianceResultSection.style.display = 'none';
        complianceState.resultId = null;
        complianceState.data = null;
        complianceState.selectedRows.clear();
        hidePendingAnalysisBanner();
        if (complianceExportBtn) complianceExportBtn.disabled = true;
        setComplianceStatus('Hasil ditutup. Upload kontrak baru.', false);
    });
}

   if (complianceResetBtn) {
    complianceResetBtn.addEventListener('click', () => {
        // Reset file kontrak
        if (complianceContractFile) complianceContractFile.value = '';
        if (complianceContractFileName) {
            complianceContractFileName.textContent = '';
            complianceContractFileName.style.display = 'none';
        }

        // Reset file regulasi manual
        if (complianceRegulationFiles) complianceRegulationFiles.value = '';
        if (complianceRegulationFileNames) {
            complianceRegulationFileNames.innerHTML = '';
            complianceRegulationFileNames.style.display = 'none';
            complianceRegulationFileNames.classList.remove('multi');
        }

        // Reset input text
        if (complianceNamaKontrak) complianceNamaKontrak.value = '';
        if (complianceFilterKontrak) complianceFilterKontrak.value = '';

        // Reset DB selection
        complianceModeState.dbSelectedIds.clear();
        if (complianceDbList) {
            complianceDbList.querySelectorAll('[data-db-check-id]').forEach(cb => {
                cb.checked = false;
                const label = cb.closest('.compliance-db-item');
                if (label) label.classList.remove('selected');
            });
        }

        // Reset mode ke manual
        switchComplianceMode('manual');

        // Reset result state
        complianceState.resultId = null;
        complianceState.data = null;
        complianceState.selectedRows = new Set();
        complianceResultSection.style.display = 'none';
        hidePendingAnalysisBanner();

        if (complianceExportBtn) complianceExportBtn.disabled = true;
        if (complianceExportPdfBtn) complianceExportPdfBtn.disabled = true;

        setComplianceStatus('Menunggu file...', false);
        showToast('Form dibersihkan.', 'info');
    });
}

// ---- Main Submit Handler ----
    if (complianceUploadForm) {
    complianceUploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        // === Validasi shared: kontrak ===
        if (!complianceContractFile || !complianceContractFile.files.length) {
            setComplianceStatus('Pilih file kontrak terlebih dahulu.', true);
            showToast('File kontrak belum dipilih.', 'error');
            return;
        }

        const contractFile = complianceContractFile.files[0];
        if (contractFile.size > 10 * 1024 * 1024) {
            setComplianceStatus('Kontrak terlalu besar. Maks 10MB.', true);
            showToast('File kontrak terlalu besar.', 'error');
            return;
        }

        // === Validasi per mode ===
        if (complianceModeState.current === 'manual') {
            if (!complianceRegulationFiles || !complianceRegulationFiles.files.length) {
                setComplianceStatus('Pilih minimal 1 file regulasi.', true);
                showToast('File regulasi belum dipilih.', 'error');
                return;
            }
        } else {
            // Database mode
            if (complianceModeState.dbSelectedIds.size === 0) {
                setComplianceStatus('Pilih minimal 1 regulasi dari database.', true);
                showToast('Belum ada regulasi dipilih dari database.', 'error');
                return;
            }
        }

        complianceSubmitBtn.disabled = true;
        complianceResultSection.style.display = 'none';
        setComplianceStatus('Memproses dokumen...', null);
        setComplianceProgress(10, 'Meng-upload file...');

        const namaInput = complianceNamaKontrak ? complianceNamaKontrak.value.trim() : '';
        const filterInput = complianceFilterKontrak ? complianceFilterKontrak.value.trim() : '';

        try {
            let data;

            if (complianceModeState.current === 'manual') {
                // ============ MODE MANUAL (existing flow) ============
                setComplianceProgress(20, 'Mem-parse kontrak & regulasi...');

                const fd = new FormData();
                fd.append('contract_file', contractFile);
                Array.from(complianceRegulationFiles.files).forEach(f => {
                    fd.append('regulation_files', f);
                });

                const previewRes = await fetch('/api/compliance/preview', {
                    method: 'POST',
                    body: fd,
                });
                const previewData = await previewRes.json();

                if (!previewRes.ok) {
                    setComplianceStatus(`Gagal: ${previewData.detail || 'Error.'}`, true);
                    showToast('Gagal preview: ' + (previewData.detail || 'Server error'), 'error');
                    hideComplianceProgress();
                    return;
                }

                setComplianceProgress(50, `Kontrak: ${previewData.total_contract_chunks} klausul. AI menganalisis...`);
                setComplianceStatus('AI sedang melakukan compliance review...', null);

                const run = await runJob('/api/compliance/analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preview_id: previewData.preview_id,
                        nama_kontrak: namaInput || contractFile.name.replace(/\.[^.]+$/, ''),
                        filter_kontrak: filterInput || null,
                    }),
                }, {
                    cancelAnchor: complianceProgressText,
                    onProgress: (job, pct, label) => setComplianceProgress(50 + pct * 0.5, label),
                });

                if (!run.ok) {
                    setComplianceStatus(`Gagal: ${run.error}`, true);
                    showToast(run.cancelled ? 'Compliance review dibatalkan.' : 'Gagal analisis: ' + run.error,
                        run.cancelled ? 'info' : 'error');
                    hideComplianceProgress();
                    return;
                }
                data = run.data;
            } else {
                // ============ MODE DATABASE (RAG) ============
                setComplianceProgress(20, 'Menyiapkan regulasi dari database...');

                const regIds = Array.from(complianceModeState.dbSelectedIds);
                if (regIds.length === 0) {
                    setComplianceStatus('Pilih minimal 1 regulasi.', true);
                    hideComplianceProgress();
                    return;
                }

                setComplianceProgress(35, `Retrieving ${regIds.length} regulasi relevan...`);
                setComplianceStatus('AI menganalisis dengan RAG (retrieval + review)...', null);

                const fd = new FormData();
                fd.append('contract_file', contractFile);
                fd.append('regulation_ids', regIds.join(','));
                if (namaInput) fd.append('nama_kontrak', namaInput);
                if (filterInput) fd.append('filter_kontrak', filterInput);
                fd.append('top_k_per_clause', '5');

                const run = await runJob('/api/compliance/analyze-from-db', {
                    method: 'POST',
                    body: fd,
                }, {
                    cancelAnchor: complianceProgressText,
                    onProgress: (job, pct, label) => setComplianceProgress(35 + pct * 0.65, label),
                });

                if (!run.ok) {
                    setComplianceStatus(`Gagal: ${run.error}`, true);
                    showToast(run.cancelled ? 'Compliance review dibatalkan.' : 'Gagal analisis: ' + run.error,
                        run.cancelled ? 'info' : 'error');
                    hideComplianceProgress();
                    return;
                }
                data = run.data;
            }

            // === SUKSES — render hasil ===
            setComplianceProgress(100, 'Selesai!');
            setComplianceStatus(`Selesai. ${data.total_items} klausul dianalisis.`, false);

            complianceState.previewId = data.preview_id || '';
            complianceState.resultId = data.result_id;
            complianceState.data = data;
            complianceState.selectedRows = new Set();
            complianceState.searchQuery = '';
            complianceState.statusFilter = '';
            if (complianceSearchInput) complianceSearchInput.value = '';
            if (complianceStatusFilter) complianceStatusFilter.value = '';

            hidePendingAnalysisBanner();

            renderComplianceSummary(data);
            renderComplianceMeta(data);
            renderComplianceTable(data.items || []);
            renderComplianceExecutiveSummary(data.executive_summary || '');

            if (complianceExportBtn) complianceExportBtn.disabled = false;
            if (complianceExportPdfBtn) complianceExportPdfBtn.disabled = false;

            complianceResultSection.style.display = 'block';
            complianceResultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

            saveToHistory(data, 'compliance_review');
            showToast('Compliance review selesai! 🎉', 'success');

        } catch (err) {
            setComplianceStatus(`Gagal: ${err.message}`, true);
            showToast('Gagal terhubung ke server.', 'error');
        } finally {
            complianceSubmitBtn.disabled = false;
            if (complianceModeState.current === 'database') {
                complianceSubmitBtn.innerHTML = '<i class="fas fa-database"></i> Analisis (Database)';
            } else {
                complianceSubmitBtn.innerHTML = '<i class="fas fa-gavel"></i> Mulai Compliance Review';
            }
            setTimeout(hideComplianceProgress, 2000);
        }
    });
}

// ---- Cleanup on page change ----
// (dipanggil di switchPage saat pindah away)

    // ============================================================
// COMPLIANCE MODE SELECTOR (Manual vs Database)
// ============================================================

const complianceModeState = {
    current: 'manual',          // 'manual' | 'database'
    dbRegulations: [],
    dbSelectedIds: new Set(),
    dbLoaded: false,
};

const complianceModeBtns = $$('.compliance-mode-btn');
const complianceModeManual = $('#complianceModeManual');
const complianceModeDatabase = $('#complianceModeDatabase');
const complianceDbLoading = $('#complianceDbLoading');
const complianceDbEmpty = $('#complianceDbEmpty');
const complianceDbList = $('#complianceDbList');
const complianceDbCount = $('#complianceDbCount');

// ---- Switch Mode ----
function switchComplianceMode(mode) {
    complianceModeState.current = mode;

    // Update button state
    complianceModeBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.complianceMode === mode);
    });

    // Show/hide content
    if (complianceModeManual) {
        complianceModeManual.style.display = mode === 'manual' ? '' : 'none';
    }
    if (complianceModeDatabase) {
        complianceModeDatabase.style.display = mode === 'database' ? '' : 'none';
    }

    // Update tombol submit label
    if (complianceSubmitBtn) {
        if (mode === 'database') {
            complianceSubmitBtn.innerHTML = '<i class="fas fa-database"></i> Analisis (Database)';
        } else {
            complianceSubmitBtn.innerHTML = '<i class="fas fa-gavel"></i> Mulai Compliance Review';
        }
    }

    // Toggle required attribute
    if (complianceRegulationFiles) {
        if (mode === 'manual') {
            complianceRegulationFiles.setAttribute('required', 'required');
        } else {
            complianceRegulationFiles.removeAttribute('required');
        }
    }

    // Load DB list kalau mode database dan belum loaded
    if (mode === 'database' && !complianceModeState.dbLoaded) {
        loadComplianceDbList();
    }
}

// Attach click handlers
complianceModeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const mode = btn.dataset.complianceMode;
        if (mode !== complianceModeState.current) {
            switchComplianceMode(mode);
        }
    });
});

// ---- Load DB List ----
async function loadComplianceDbList() {
    if (!complianceDbList) return;

    if (complianceDbLoading) complianceDbLoading.style.display = 'flex';
    if (complianceDbEmpty) complianceDbEmpty.style.display = 'none';
    if (complianceDbList) complianceDbList.style.display = 'none';

    try {
        const res = await fetch('/api/regulation-db/regulations');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        complianceModeState.dbRegulations = data.regulations || [];
        complianceModeState.dbLoaded = true;

        if (complianceDbLoading) complianceDbLoading.style.display = 'none';

        if (complianceModeState.dbRegulations.length === 0) {
            if (complianceDbEmpty) complianceDbEmpty.style.display = 'flex';
            if (complianceDbCount) complianceDbCount.textContent = '(0 regulasi)';
            return;
        }

        renderComplianceDbList();
    } catch (err) {
        if (complianceDbLoading) {
            complianceDbLoading.innerHTML = `
                    <i class="fas fa-exclamation-circle" style="color:var(--warn);"></i>
                    Gagal memuat: ${escapeHtml(err.message)}
                `;
            complianceDbLoading.style.display = 'flex';
        }
    }
}

// ---- Render DB List ----
function renderComplianceDbList() {
    if (!complianceDbList) return;

    const regs = complianceModeState.dbRegulations;

    if (complianceDbCount) {
        complianceDbCount.textContent = `(${regs.length} regulasi)`;
    }

    complianceDbList.style.display = 'flex';
    complianceDbList.innerHTML = regs.map(r => {
        const isSelected = complianceModeState.dbSelectedIds.has(r.id);
        const isPreload = r.source_type === 'preload';
        const badge = isPreload ? ' · Preload' : ' · Manual';

        return `
                <label class="compliance-db-item ${isSelected ? 'selected' : ''}"
                       data-db-reg-id="${escapeAttr(r.id)}">
                    <input type="checkbox"
                           data-db-check-id="${escapeAttr(r.id)}"
                           ${isSelected ? 'checked' : ''} />
                    <div class="compliance-db-item-icon">
                        <i class="fas fa-file-contract"></i>
                    </div>
                    <div class="compliance-db-item-body">
                        <div class="compliance-db-item-name">${escapeHtml(r.name)}</div>
                        <div class="compliance-db-item-meta">
                            <span><i class="fas fa-cubes"></i> ${(r.total_chunks || 0).toLocaleString('id-ID')} chunks</span>
                            <span>${badge}</span>
                        </div>
                    </div>
                </label>
            `;
    }).join('');

    // Attach checkbox listeners
    complianceDbList.querySelectorAll('[data-db-check-id]').forEach(cb => {
        cb.addEventListener('change', (e) => {
            e.stopPropagation();
            const regId = cb.dataset.dbCheckId;
            const label = cb.closest('.compliance-db-item');

            if (cb.checked) {
                complianceModeState.dbSelectedIds.add(regId);
                if (label) label.classList.add('selected');
            } else {
                complianceModeState.dbSelectedIds.delete(regId);
                if (label) label.classList.remove('selected');
            }
        });
    });

    // Click row = toggle
    complianceDbList.querySelectorAll('.compliance-db-item').forEach(item => {
        item.addEventListener('click', (e) => {
            if (e.target.tagName === 'INPUT') return;
            const cb = item.querySelector('input[type="checkbox"]');
            if (cb) {
                cb.checked = !cb.checked;
                cb.dispatchEvent(new Event('change'));
            }
        });
    });
}

onPageEnter('compliance-review', () => {
    if (complianceModeState.current === 'database') complianceModeState.dbLoaded = false;
});
