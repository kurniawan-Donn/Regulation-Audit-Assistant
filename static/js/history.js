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
import {
    gapCopyBtn,
    gapExportBtn,
    gapExportPdfBtn,
    gapResultSection,
    gapStatusFilter,
    renderGapChunkErrors,
    renderGapSummary,
    renderGapTable,
} from './gap.js';

const historyList = $('#historyList');
const historyClearAll = $('#historyClearAll');

// ====== RIWAYAT (dari server) ======
// Sumber kebenaran: hasil tersimpan di outputs/ (GET /api/history). Dulu
// riwayat disimpan lengkap di localStorage: hilang saat cache dibersihkan,
// tidak terlihat dari browser lain, dan bisa melampaui kuota ±5 MB.
const LEGACY_STORAGE_KEY = 'rta_history';

const TYPE_META = {
    regulation_audit: { label: 'Audit', icon: 'fa-clipboard-check', cls: 'badge-audit' },
    gap_analysis: { label: 'Gap', icon: 'fa-magnifying-glass-chart', cls: 'badge-gap' },
    compliance_review: { label: 'Compliance', icon: 'fa-scale-balanced', cls: 'badge-compliance' },
};

let refreshing = null;

/** Muat ulang daftar riwayat dari server; aman dipanggil berkali-kali. */
export function refreshHistory() {
    if (refreshing) return refreshing;
    refreshing = (async () => {
        try {
            const res = await fetch('/api/history');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            // Statistik diratakan ke entri supaya pemakai lama (total_tidak_patuh, dst.) tetap jalan.
            state.history = data.items.map(item => ({ ...item, ...item.stats }));
            // Salinan lama di browser tidak dipakai lagi — hasilnya sudah ada di server.
            try { localStorage.removeItem(LEGACY_STORAGE_KEY); } catch (_) { /* storage diblokir */ }
            renderHistory();
            document.dispatchEvent(new CustomEvent('history:updated'));
        } catch (err) {
            console.warn('Gagal memuat riwayat:', err);
        } finally {
            refreshing = null;
        }
    })();
    return refreshing;
}

// Alat lain (mis. Gap Analysis) cukup mengirim event ini setelah hasil baru tersimpan.
document.addEventListener('history:changed', () => refreshHistory());

function historyMeta(h) {
    const date = new Date(h.tanggal).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' });
    if (h.type === 'compliance_review') {
        return `
            <span><i class="fas fa-list"></i> ${h.total_items || 0}</span>
            <span><i class="fas fa-check-circle" style="color:var(--success)"></i> ${h.total_patuh || 0}</span>
            <span><i class="fas fa-exclamation-triangle" style="color:var(--warn)"></i> ${h.total_tidak_patuh || 0}</span>
            <span>${date}</span>`;
    }
    if (h.type === 'gap_analysis') {
        return `
            <span><i class="fas fa-list"></i> ${h.total_requirements || 0} persyaratan</span>
            <span><i class="fas fa-check-double"></i> ${h.total_dinilai || 0} dinilai</span>
            <span>${date}</span>`;
    }
    return `
        <span><i class="fas fa-list"></i> ${h.total_ketentuan || 0}</span>
        <span><i class="fas fa-check-circle" style="color:var(--success)"></i> ${h.total_valid || 0}</span>
        <span><i class="fas fa-exclamation-triangle" style="color:var(--warn)"></i> ${h.total_flagged || 0}</span>
        <span>${date}</span>`;
}

export function renderHistory() {
    if (!historyList) return;
    if (state.history.length === 0) {
        historyList.innerHTML = `
                <div class="history-empty">
                    <i class="fas fa-folder-open"></i>
                    <p>Belum ada hasil analisis tersimpan.</p>
                </div>`;
        return;
    }

    historyList.innerHTML = state.history.map(h => {
        const meta = TYPE_META[h.type] || TYPE_META.regulation_audit;
        return `
                <div class="history-item" data-id="${escapeAttr(h.id)}" data-type="${escapeAttr(h.type)}">
                    <div class="history-item-info" data-action="load">
                        <div class="history-item-name">
                            <span class="history-type-badge ${meta.cls}"><i class="fas ${meta.icon}"></i> ${meta.label}</span>
                            ${escapeHtml(h.nama)}
                        </div>
                        <div class="history-item-meta">${historyMeta(h)}</div>
                    </div>
                    <button class="history-item-delete" data-action="delete" title="Hapus hasil ini dari server">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>`;
    }).join('');

    historyList.querySelectorAll('.history-item').forEach(el => {
        const { id, type } = el.dataset;
        el.querySelector('[data-action="load"]').addEventListener('click', () => loadHistory(id, type));
        el.querySelector('[data-action="delete"]').addEventListener('click', () => deleteHistoryItem(id));
    });
}

/** Dipanggil setelah analysis baru selesai — hasilnya sudah ditulis server. */
export function saveToHistory() {
    return refreshHistory();
}

async function deleteHistoryItem(id) {
    const entry = state.history.find(h => h.id === id);
    if (!entry) return;
    if (!confirm(`Hapus hasil "${entry.nama}" beserta file ekspornya dari server?\nTindakan ini tidak bisa dibatalkan.`)) return;
    try {
        const res = await fetch(`/api/history/${entry.type}/${entry.id}`, { method: 'DELETE' });
        if (!res.ok && res.status !== 404) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        showToast('Hasil analisis dihapus.', 'success');
    } catch (err) {
        showToast(`Gagal menghapus: ${err.message}`, 'error');
    }
    await refreshHistory();
}

async function clearAllHistory() {
    if (state.history.length === 0) return;
    const typed = prompt(
        `Ini akan menghapus SEMUA ${state.history.length} hasil analisis (beserta file ekspornya) dari server.\n` +
        'Ketik HAPUS SEMUA untuk melanjutkan.'
    );
    if (typed === null) return;
    if (typed.trim() !== 'HAPUS SEMUA') {
        showToast('Teks konfirmasi tidak cocok — tidak ada yang dihapus.', 'info');
        return;
    }
    try {
        const res = await fetch('/api/history/clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm: typed.trim() }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        showToast(data.message || 'Semua riwayat dihapus.', 'success');
    } catch (err) {
        showToast(`Tidak dihapus: ${err.message}`, 'error');
    }
    await refreshHistory();
}
if (historyClearAll) historyClearAll.addEventListener('click', clearAllHistory);

export async function loadHistory(id, type = null) {
    const entry = state.history.find(h => h.id === id);
    if (!entry) return;

    const entryType = type || entry.type || 'regulation_audit';

    if (entryType === 'gap_analysis') {
        try {
            const res = await fetch(`/api/requirements/${entry.id}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            state.gapResultId = data.result_id;
            state.gapData = data;
            state.gapSelectedRows = new Set();
            state.gapStatusFilter = '';
            if (gapStatusFilter) gapStatusFilter.value = '';
            switchPage('gap-analysis');
            if (gapExportBtn) gapExportBtn.disabled = false;
            if (gapExportPdfBtn) gapExportPdfBtn.disabled = false;
            if (gapCopyBtn) gapCopyBtn.disabled = false;
            renderGapSummary(data);
            renderGapChunkErrors(data.chunk_errors || []);
            renderGapTable(data.requirements || []);
            if (gapResultSection) {
                gapResultSection.style.display = 'block';
                setTimeout(() => gapResultSection.scrollIntoView({ behavior: 'smooth', block: 'start' }), 200);
            }
            closeSettings();
            showToast(`Dimuat dari riwayat: ${entry.nama}`, 'info');
        } catch (err) {
            showToast(`Gagal memuat: ${err.message}`, 'error');
        }
        return;
    }

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
        // === LOAD REGULATION AUDIT ===
        let data;
        try {
            const res = await fetch(`/api/results/${entry.id}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            data = await res.json();
        } catch (err) {
            showToast(`Gagal memuat: ${err.message}`, 'error');
            return;
        }
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
        renderChunkErrors(data.chunk_errors || []);
        renderTable(data.results || []);
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
