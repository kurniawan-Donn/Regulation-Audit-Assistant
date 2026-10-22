/**
 * Riwayat analisis (localStorage) untuk ketiga tool: simpan, tampilkan, buka ulang.
 */

import {
    $,
    escapeAttr,
    escapeHtml,
    showToast,
    state,
    switchPage,
} from './core.js';
import { closeSettings } from './settings.js';
import {
    copyBtn,
    exportBtn,
    exportPdfBtn,
    previewExpiredBanner,
    renderChunkErrors,
    renderFilterBadge,
    renderSummary,
    renderTable,
    resultSection,
    statusFilterSelect,
    updateDonutChart,
    updateProgressBadge,
} from './audit.js';
import {
    complianceExportBtn,
    complianceExportPdfBtn,
    complianceResultSection,
    complianceSearchInput,
    complianceState,
    complianceStatusFilter,
    hidePendingAnalysisBanner,
    renderComplianceExecutiveSummary,
    renderComplianceMeta,
    renderComplianceSummary,
    renderComplianceTable,
} from './compliance.js';

const historyList = $('#historyList');
const historyClearAll = $('#historyClearAll');

// ====== HISTORY (Tool 1) ======
    export function renderHistory() {
    if (!historyList) return;
    if (state.history.length === 0) {
        historyList.innerHTML = `
                <div class="history-empty">
                    <i class="fas fa-folder-open"></i>
                    <p>Belum ada riwayat analisis.</p>
                </div>`;
        return;
    }

    historyList.innerHTML = state.history.map(h => {
        const isCompliance = h.type === 'compliance_review';
        const typeBadge = isCompliance
            ? `<span class="history-type-badge badge-compliance"><i class="fas fa-scale-balanced"></i> Compliance</span>`
            : `<span class="history-type-badge badge-audit"><i class="fas fa-clipboard-check"></i> Audit</span>`;

        if (isCompliance) {
            return `
                    <div class="history-item" data-id="${escapeAttr(h.id)}" data-type="compliance_review">
                        <div class="history-item-info" data-action="load">
                            <div class="history-item-name">${typeBadge} ${escapeHtml(h.nama)}</div>
                            <div class="history-item-meta">
                                <span><i class="fas fa-list"></i> ${h.total_items || 0}</span>
                                <span><i class="fas fa-check-circle" style="color:var(--success)"></i> ${h.total_patuh || 0}</span>
                                <span><i class="fas fa-exclamation-triangle" style="color:var(--warn)"></i> ${h.total_tidak_patuh || 0}</span>
                                <span>${new Date(h.tanggal).toLocaleDateString('id-ID')}</span>
                            </div>
                        </div>
                        <button class="history-item-delete" data-action="delete" title="Hapus">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                `;
        }

        return `
                <div class="history-item" data-id="${escapeAttr(h.id)}" data-type="regulation_audit">
                    <div class="history-item-info" data-action="load">
                        <div class="history-item-name">${typeBadge} ${escapeHtml(h.nama)}</div>
                        <div class="history-item-meta">
                            <span><i class="fas fa-list"></i> ${h.total_ketentuan || 0}</span>
                            <span><i class="fas fa-check-circle" style="color:var(--success)"></i> ${h.total_valid || 0}</span>
                            <span><i class="fas fa-exclamation-triangle" style="color:var(--warn)"></i> ${h.total_flagged || 0}</span>
                            <span>${new Date(h.tanggal).toLocaleDateString('id-ID')}</span>
                        </div>
                    </div>
                    <button class="history-item-delete" data-action="delete" title="Hapus">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
    }).join('');

    historyList.querySelectorAll('.history-item').forEach(el => {
        const id = el.dataset.id;
        const type = el.dataset.type || 'regulation_audit';
        el.querySelector('[data-action="load"]').addEventListener('click', () => loadHistory(id, type));
        el.querySelector('[data-action="delete"]').addEventListener('click', () => deleteHistoryItem(id));
    });
}

    export function saveToHistory(data, type = 'regulation_audit') {
    let entry;

    if (type === 'compliance_review') {
        // === COMPLIANCE REVIEW ===
        entry = {
            id: data.result_id || Date.now().toString(36),
            type: 'compliance_review',
            nama: data.contract_filename || data.nama_kontrak || 'Compliance Review',
            tanggal: new Date().toISOString(),
            // Stats
            total_items: data.total_items || 0,
            total_patuh: data.total_patuh || 0,
            total_patuh_catatan: data.total_patuh_catatan || 0,
            total_tidak_patuh: data.total_tidak_patuh || 0,
            total_tidak_relevan: data.total_tidak_relevan || 0,
            total_perlu_verifikasi: data.total_perlu_verifikasi || 0,
            // Data lengkap
            items: data.items || [],
            executive_summary: data.executive_summary || '',
            regulation_filenames: data.regulation_filenames || [],
            preview_id: data.preview_id || '',
        };
    } else {
        // === REGULATION AUDIT (default) ===
        entry = {
            id: data.result_id || Date.now().toString(36),
            type: 'regulation_audit',
            nama: data.nama_regulasi || data.filename || data.nama || 'Tanpa Nama',
            tanggal: new Date().toISOString(),
            total_ketentuan: data.total_ketentuan || 0,
            total_valid: data.total_valid || 0,
            total_flagged: data.total_flagged || 0,
            results: data.results || [],
            chunk_errors: data.chunk_errors || [],
            total_chunks: data.total_chunks || 0,
            total_batches: data.total_batches || 0,
            total_by_aspect: data.total_by_aspect || {},
            filter_applied: data.filter_applied || [],
            preview_id: data.preview_id || '',
        };
    }

    state.history = state.history.filter(h => h.id !== entry.id);
    state.history.unshift(entry);
    if (state.history.length > 50) state.history = state.history.slice(0, 50);
    localStorage.setItem('rta_history', JSON.stringify(state.history));
    renderHistory();
}

function deleteHistoryItem(id) {
    state.history = state.history.filter(h => h.id !== id);
    localStorage.setItem('rta_history', JSON.stringify(state.history));
    renderHistory();
    showToast('Riwayat dihapus.', 'success');
}

function clearAllHistory() {
    if (state.history.length === 0) return;
    if (confirm('Hapus semua riwayat analisis?')) {
        state.history = [];
        localStorage.setItem('rta_history', JSON.stringify(state.history));
        renderHistory();
        showToast('Semua riwayat dihapus.', 'success');
    }
}
if (historyClearAll) historyClearAll.addEventListener('click', clearAllHistory);

    async function loadHistory(id, type = null) {
    const entry = state.history.find(h => h.id === id);
    if (!entry) return;

    const entryType = type || entry.type || 'regulation_audit';

    if (entryType === 'compliance_review') {
        // === LOAD COMPLIANCE REVIEW ===
        try {
            const res = await fetch(`/api/compliance/${entry.id}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            complianceState.resultId = data.result_id;
            complianceState.data = data;
            complianceState.selectedRows = new Set();
            hidePendingAnalysisBanner();
            complianceState.searchQuery = '';
            complianceState.statusFilter = '';

            if (complianceSearchInput) complianceSearchInput.value = '';
            if (complianceStatusFilter) complianceStatusFilter.value = '';

            // Switch ke halaman compliance
            switchPage('compliance-review');

            // Render
            renderComplianceSummary(data);
            renderComplianceMeta(data);
            renderComplianceTable(data.items || []);
            renderComplianceExecutiveSummary(data.executive_summary || '');

            if (complianceExportBtn) complianceExportBtn.disabled = false;
            if (complianceExportPdfBtn) complianceExportPdfBtn.disabled = false;
            if (complianceResultSection) {
                complianceResultSection.style.display = 'block';
                setTimeout(() => {
                    complianceResultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }, 200);
            }

            closeSettings();
            showToast(`Dimuat dari riwayat: ${entry.nama}`, 'info');
        } catch (err) {
            showToast(`Gagal memuat: ${err.message}`, 'error');
        }
    } else {
        // === LOAD REGULATION AUDIT (existing logic) ===
        state.currentResultId = entry.id;
        state.currentData = entry;
        state.selectedRows = new Set();
        state.statusFilter = '';
        if (statusFilterSelect) statusFilterSelect.value = '';
        if (exportBtn) exportBtn.disabled = false;
        if (exportPdfBtn) exportPdfBtn.disabled = false;
        if (copyBtn) copyBtn.disabled = false;
        if (previewExpiredBanner) previewExpiredBanner.style.display = 'none';
        renderSummary(entry);
        renderFilterBadge(entry.filter_applied || []);
        renderChunkErrors(entry.chunk_errors || []);
        renderTable(entry.results || []);
        updateProgressBadge();

        switchPage('regulation-audit');

        if (resultSection) {
            resultSection.style.display = 'block';
            resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        closeSettings();
        showToast(`Dimuat dari riwayat: ${entry.nama}`, 'info');
        updateDonutChart();
    }
}
