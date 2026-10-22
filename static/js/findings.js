/**
 * Daftar Temuan: kirim baris Compliance Review / Gap Analysis sebagai temuan,
 * lalu kelola risiko, status tindak lanjut, PIC, dan target — semua tersimpan
 * di server (data/findings.json) dan bisa diekspor ke Excel.
 */

import { $, escapeAttr, escapeHtml, onPageEnter, showToast, state } from './core.js';
import { complianceState } from './compliance.js';
import { loadHistory, refreshHistory } from './history.js';

const RISKS = ['Tinggi', 'Sedang', 'Rendah'];
const STATUSES = ['Terbuka', 'Dalam Proses', 'Selesai'];
const SOURCE_LABELS = {
    compliance_review: 'Compliance Review',
    gap_analysis: 'Gap Analysis',
    manual: 'Manual',
};

const NO_FINDINGS_HINT = {
    compliance_review: 'Tidak ada klausul Tidak Patuh, Patuh dengan Catatan, atau Perlu Verifikasi. ' +
        'Untuk klausul lain, centang barisnya lalu klik Kirim ke Temuan.',
    gap_analysis: 'Belum ada persyaratan berstatus Tidak Sesuai / Sebagian Sesuai. ' +
        'Isi Status Gap dulu, atau centang barisnya lalu klik Kirim ke Temuan.',
};

const findingsList = $('#findingsList');
const findingsEmpty = $('#findingsEmpty');
const findingsNoMatch = $('#findingsNoMatch');
const findingsSummary = $('#findingsSummary');
const findingsSearch = $('#findingsSearch');
const findingsStatusFilter = $('#findingsStatusFilter');
const findingsRiskFilter = $('#findingsRiskFilter');
const findingsAddBtn = $('#findingsAddBtn');
const findingsExportBtn = $('#findingsExportBtn');
const findingsNavBadge = $('#findingsNavBadge');

const findingsState = {
    items: [],
    summary: null,
    query: '',
    status: '',
    risk: '',
    openIds: new Set(),
};

const slug = text => (text || '').toLowerCase().replace(/\s+/g, '-');
const code = n => `T-${String(n).padStart(3, '0')}`;

// ====== Kirim dari hasil analisis ======
export async function sendToFindings(sourceType, resultId, indices = null) {
    if (!resultId) {
        showToast('Buka hasil analisis terlebih dahulu.', 'error');
        return;
    }
    try {
        const res = await fetch('/api/findings/from-source', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_type: sourceType, result_id: resultId, item_indices: indices }),
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 422 && indices === null) {
            // Bukan galat: hasil ini belum punya baris berstatus temuan.
            showToast(NO_FINDINGS_HINT[sourceType], 'info');
            return;
        }
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        const added = data.added.length;
        const parts = [];
        if (added) parts.push(`${added} temuan ditambahkan ke Daftar Temuan`);
        if (data.skipped) parts.push(`${data.skipped} sudah ada sebelumnya`);
        showToast(parts.join(' · ') || 'Tidak ada temuan baru.', added ? 'success' : 'info');
        await loadFindings();
    } catch (err) {
        showToast(`Gagal mengirim ke Daftar Temuan: ${err.message}`, 'error');
    }
}

function bindSendButtons() {
    $('#complianceSendFindingsBtn')?.addEventListener('click', () =>
        sendToFindings('compliance_review', complianceState.resultId));
    $('#complianceBulkFindingsBtn')?.addEventListener('click', () =>
        sendToFindings('compliance_review', complianceState.resultId, [...complianceState.selectedRows]));
    $('#gapSendFindingsBtn')?.addEventListener('click', () =>
        sendToFindings('gap_analysis', state.gapResultId));
    $('#gapBulkFindingsBtn')?.addEventListener('click', () =>
        sendToFindings('gap_analysis', state.gapResultId, [...(state.gapSelectedRows || [])]));
}

// ====== Data ======
export async function loadFindings() {
    try {
        const res = await fetch('/api/findings');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        findingsState.items = data.items;
        findingsState.summary = data.summary;
        updateNavBadge();
        if (state.currentPage === 'findings') render();
    } catch (err) {
        console.warn('Gagal memuat Daftar Temuan:', err);
    }
}

function recomputeSummary() {
    const items = findingsState.items;
    findingsState.summary = {
        total: items.length,
        by_status: Object.fromEntries(STATUSES.map(s => [s, items.filter(f => f.status === s).length])),
        by_risk: Object.fromEntries(RISKS.map(r => [r, items.filter(f => f.risiko === r).length])),
    };
}

function updateNavBadge() {
    if (!findingsNavBadge) return;
    const open = findingsState.items.filter(f => f.status !== 'Selesai').length;
    findingsNavBadge.hidden = open === 0;
    findingsNavBadge.textContent = open;
    findingsNavBadge.title = `${open} temuan belum selesai`;
}

// ====== Render ======
function renderSummary() {
    const s = findingsState.summary || { total: 0, by_status: {}, by_risk: {} };
    const tile = (label, value, tone, filter) => `
        <button type="button" class="findings-stat tone-${tone}" ${filter ? `data-filter-${filter[0]}="${escapeAttr(filter[1])}"` : 'data-filter-reset'}>
            <strong>${value}</strong><span>${label}</span>
        </button>`;
    findingsSummary.innerHTML = [
        tile('Total temuan', s.total, 'slate'),
        tile('Terbuka', s.by_status.Terbuka || 0, 'orange', ['status', 'Terbuka']),
        tile('Dalam proses', s.by_status['Dalam Proses'] || 0, 'sky', ['status', 'Dalam Proses']),
        tile('Selesai', s.by_status.Selesai || 0, 'teal', ['status', 'Selesai']),
        tile('Risiko tinggi', s.by_risk.Tinggi || 0, 'rose', ['risk', 'Tinggi']),
    ].join('');
}

function options(values, current) {
    return values.map(v => `<option value="${escapeAttr(v)}" ${v === current ? 'selected' : ''}>${escapeHtml(v)}</option>`).join('');
}

function sourceHtml(src) {
    const label = SOURCE_LABELS[src.type] || 'Manual';
    if (!src.type || src.type === 'manual') {
        return `<span class="finding-source"><i class="fas fa-pen"></i> Ditulis manual</span>`;
    }
    const detail = [src.nama, src.ref].filter(Boolean).join(' · ');
    return `
        <button type="button" class="finding-source is-link" data-open-source title="Buka hasil asal">
            <i class="fas fa-arrow-up-right-from-square"></i> ${escapeHtml(label)}${detail ? `: ${escapeHtml(detail)}` : ''}
        </button>`;
}

function field(name, label, value, rows) {
    return `
        <label class="finding-field">
            <span>${label}</span>
            <textarea data-field="${name}" rows="${rows}">${escapeHtml(value || '')}</textarea>
        </label>`;
}

function cardHtml(f) {
    const open = findingsState.openIds.has(f.id) ? 'open' : '';
    return `
        <details class="finding-card risk-${slug(f.risiko)} status-${slug(f.status)}" data-id="${escapeAttr(f.id)}" ${open}>
            <summary>
                <span class="finding-code">${code(f.nomor)}</span>
                <span class="finding-pill risk-pill risk-${slug(f.risiko)}">${escapeHtml(f.risiko)}</span>
                <span class="finding-title">${escapeHtml(f.judul || '(tanpa judul)')}</span>
                <span class="finding-meta">${f.pic ? `<i class="fas fa-user"></i> ${escapeHtml(f.pic)}` : ''}${f.target_date ? ` <i class="fas fa-calendar"></i> ${escapeHtml(f.target_date)}` : ''}</span>
                <span class="finding-pill status-pill-f status-${slug(f.status)}">${escapeHtml(f.status)}</span>
            </summary>
            <div class="finding-body">
                <label class="finding-field finding-field-wide">
                    <span>Judul temuan</span>
                    <input type="text" data-field="judul" value="${escapeAttr(f.judul || '')}" />
                </label>
                <div class="finding-grid">
                    ${field('kondisi', 'Kondisi — apa yang ditemukan', f.kondisi, 4)}
                    ${field('kriteria', 'Kriteria — regulasi acuan', f.kriteria, 4)}
                    ${field('rekomendasi', 'Rekomendasi', f.rekomendasi, 3)}
                    ${field('tanggapan', 'Tanggapan / tindak lanjut', f.tanggapan, 3)}
                </div>
                <div class="finding-controls">
                    <label class="finding-field"><span>Risiko</span>
                        <select data-field="risiko">${options(RISKS, f.risiko)}</select></label>
                    <label class="finding-field"><span>Status</span>
                        <select data-field="status">${options(STATUSES, f.status)}</select></label>
                    <label class="finding-field"><span>PIC</span>
                        <input type="text" data-field="pic" value="${escapeAttr(f.pic || '')}" placeholder="Nama / unit" /></label>
                    <label class="finding-field"><span>Target</span>
                        <input type="date" data-field="target_date" value="${escapeAttr(f.target_date || '')}" /></label>
                </div>
                <div class="finding-footer">
                    ${sourceHtml(f.source || {})}
                    <span class="finding-saved" aria-live="polite"></span>
                    <button type="button" class="btn btn-ghost btn-sm finding-delete" data-delete>
                        <i class="fas fa-trash"></i> Hapus
                    </button>
                </div>
            </div>
        </details>`;
}

function filtered() {
    const q = findingsState.query.trim().toLowerCase();
    return findingsState.items.filter(f => {
        if (findingsState.status && f.status !== findingsState.status) return false;
        if (findingsState.risk && f.risiko !== findingsState.risk) return false;
        if (!q) return true;
        return ['judul', 'kondisi', 'kriteria', 'rekomendasi', 'pic', 'tanggapan']
            .some(k => (f[k] || '').toLowerCase().includes(q))
            || code(f.nomor).toLowerCase().includes(q);
    });
}

function render() {
    if (!findingsList) return;
    renderSummary();
    const items = filtered();
    const empty = findingsState.items.length === 0;
    findingsEmpty.style.display = empty ? '' : 'none';
    findingsNoMatch.style.display = !empty && items.length === 0 ? '' : 'none';
    findingsExportBtn.disabled = empty;
    findingsList.innerHTML = items.map(cardHtml).join('');
}

// ====== Edit ======
async function saveField(card, fieldName, value) {
    const id = card.dataset.id;
    const saved = card.querySelector('.finding-saved');
    saved.textContent = 'Menyimpan…';
    try {
        const res = await fetch(`/api/findings/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [fieldName]: value }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        const idx = findingsState.items.findIndex(f => f.id === id);
        if (idx >= 0) findingsState.items[idx] = data;
        recomputeSummary();
        updateNavBadge();
        renderSummary();
        updateCardHeader(card, data);
        saved.innerHTML = '<i class="fas fa-check"></i> Tersimpan';
    } catch (err) {
        saved.textContent = '';
        showToast(`Gagal menyimpan: ${err.message}`, 'error');
    }
}

function updateCardHeader(card, f) {
    card.className = `finding-card risk-${slug(f.risiko)} status-${slug(f.status)}`;
    const riskPill = card.querySelector('.risk-pill');
    riskPill.className = `finding-pill risk-pill risk-${slug(f.risiko)}`;
    riskPill.textContent = f.risiko;
    const statusPill = card.querySelector('.status-pill-f');
    statusPill.className = `finding-pill status-pill-f status-${slug(f.status)}`;
    statusPill.textContent = f.status;
    card.querySelector('.finding-title').textContent = f.judul || '(tanpa judul)';
    card.querySelector('.finding-meta').innerHTML =
        (f.pic ? `<i class="fas fa-user"></i> ${escapeHtml(f.pic)}` : '') +
        (f.target_date ? ` <i class="fas fa-calendar"></i> ${escapeHtml(f.target_date)}` : '');
}

async function deleteFinding(card) {
    const f = findingsState.items.find(x => x.id === card.dataset.id);
    if (!f || !confirm(`Hapus temuan ${code(f.nomor)} "${f.judul}"?`)) return;
    try {
        const res = await fetch(`/api/findings/${f.id}`, { method: 'DELETE' });
        if (!res.ok && res.status !== 404) throw new Error(`HTTP ${res.status}`);
        findingsState.items = findingsState.items.filter(x => x.id !== f.id);
        recomputeSummary();
        updateNavBadge();
        render();
        showToast(`Temuan ${code(f.nomor)} dihapus.`, 'success');
    } catch (err) {
        showToast(`Gagal menghapus: ${err.message}`, 'error');
    }
}

async function openSource(card) {
    const f = findingsState.items.find(x => x.id === card.dataset.id);
    const src = f?.source;
    if (!src?.result_id) return;
    if (!state.history.some(h => h.id === src.result_id)) await refreshHistory();
    if (!state.history.some(h => h.id === src.result_id)) {
        showToast('Hasil asal temuan ini sudah tidak ada di server.', 'error');
        return;
    }
    loadHistory(src.result_id, src.type);
}

async function addManual() {
    try {
        const res = await fetch('/api/findings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ judul: 'Temuan baru', risiko: 'Sedang', status: 'Terbuka' }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        findingsState.items.push(data);
        findingsState.openIds.add(data.id);
        Object.assign(findingsState, { query: '', status: '', risk: '' });
        findingsSearch.value = findingsStatusFilter.value = findingsRiskFilter.value = '';
        recomputeSummary();
        updateNavBadge();
        render();
        const input = findingsList.querySelector(`[data-id="${data.id}"] input[data-field="judul"]`);
        input?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        input?.select();
    } catch (err) {
        showToast(`Gagal menambah temuan: ${err.message}`, 'error');
    }
}

// ====== Event ======
findingsList?.addEventListener('change', e => {
    const el = e.target.closest('[data-field]');
    const card = e.target.closest('.finding-card');
    if (el && card) saveField(card, el.dataset.field, el.value);
});

findingsList?.addEventListener('click', e => {
    const card = e.target.closest('.finding-card');
    if (!card) return;
    if (e.target.closest('[data-delete]')) deleteFinding(card);
    else if (e.target.closest('[data-open-source]')) openSource(card);
});

findingsList?.addEventListener('toggle', e => {
    const card = e.target.closest?.('.finding-card');
    if (!card) return;
    if (card.open) findingsState.openIds.add(card.dataset.id);
    else findingsState.openIds.delete(card.dataset.id);
}, true);

findingsSummary?.addEventListener('click', e => {
    const tile = e.target.closest('.findings-stat');
    if (!tile) return;
    findingsState.status = tile.dataset.filterStatus || '';
    findingsState.risk = tile.dataset.filterRisk || '';
    findingsStatusFilter.value = findingsState.status;
    findingsRiskFilter.value = findingsState.risk;
    render();
});

let searchTimer = null;
findingsSearch?.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        findingsState.query = findingsSearch.value;
        render();
    }, 200);
});
findingsStatusFilter?.addEventListener('change', () => { findingsState.status = findingsStatusFilter.value; render(); });
findingsRiskFilter?.addEventListener('change', () => { findingsState.risk = findingsRiskFilter.value; render(); });
findingsAddBtn?.addEventListener('click', addManual);
findingsExportBtn?.addEventListener('click', () => { window.location.href = '/api/findings/export'; });

// ====== Laporan Hasil Audit ======
const reportModal = $('#reportModalOverlay');
const reportFields = {
    judul: $('#reportJudul'),
    auditee: $('#reportAuditee'),
    disusun_oleh: $('#reportDisusun'),
    tanggal: $('#reportTanggal'),
    ringkasan: $('#reportRingkasan'),
};
const reportStatusChecks = $('#reportStatusChecks');
const reportRiskChecks = $('#reportRiskChecks');
const reportCount = $('#reportCount');
const reportSummaryBtn = $('#reportSummaryBtn');
const reportSummaryNote = $('#reportSummaryNote');
const reportDocxBtn = $('#reportDocxBtn');
const reportPdfBtn = $('#reportPdfBtn');

const checkedValues = box => [...box.querySelectorAll('input:checked')].map(i => i.value);
const setChecked = (box, values) => box.querySelectorAll('input').forEach(i => { i.checked = values.includes(i.value); });
const todayIso = () => new Date().toISOString().slice(0, 10);

function reportOptions() {
    const opts = Object.fromEntries(Object.entries(reportFields).map(([k, el]) => [k, el.value.trim()]));
    opts.statuses = checkedValues(reportStatusChecks);
    opts.risks = checkedValues(reportRiskChecks);
    return opts;
}

function updateReportCount() {
    const { statuses, risks } = reportOptions();
    const picked = findingsState.items.filter(f => statuses.includes(f.status) && risks.includes(f.risiko));
    const byRisk = RISKS.map(r => `${r} ${picked.filter(f => f.risiko === r).length}`).join(' · ');
    reportCount.textContent = picked.length
        ? `${picked.length} temuan akan dimuat (${byRisk}), urut dari risiko tertinggi.`
        : 'Tidak ada temuan yang cocok dengan pilihan ini.';
    reportCount.classList.toggle('is-empty', !picked.length);
    [reportDocxBtn, reportPdfBtn, reportSummaryBtn].forEach(b => { b.disabled = !picked.length; });
}

async function openReportModal() {
    if (!findingsState.items.length) {
        showToast('Daftar Temuan masih kosong — kirim temuan dulu dari Compliance Review atau Gap Analysis.', 'info');
        return;
    }
    let meta = {};
    try {
        const res = await fetch('/api/findings/report/meta');
        if (res.ok) meta = await res.json();
    } catch (_) { /* pakai isian kosong */ }
    reportFields.judul.value = meta.judul || '';
    reportFields.auditee.value = meta.auditee || '';
    reportFields.disusun_oleh.value = meta.disusun_oleh || '';
    reportFields.tanggal.value = todayIso();          // laporan baru = tanggal hari ini
    reportFields.ringkasan.value = meta.ringkasan || '';
    setChecked(reportStatusChecks, meta.statuses?.length ? meta.statuses : STATUSES);
    setChecked(reportRiskChecks, meta.risks?.length ? meta.risks : RISKS);
    reportSummaryNote.hidden = true;
    updateReportCount();
    reportModal.style.display = 'flex';
    reportFields.judul.focus();
}

function closeReportModal() {
    reportModal.style.display = 'none';
}

async function draftSummary() {
    if (reportFields.ringkasan.value.trim() &&
        !confirm('Ganti ringkasan yang sudah ada dengan draf baru dari AI?')) return;
    const original = reportSummaryBtn.innerHTML;
    reportSummaryBtn.disabled = true;
    reportSummaryBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyusun…';
    try {
        const res = await fetch('/api/findings/report/summary', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(reportOptions()),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        reportFields.ringkasan.value = data.ringkasan;
        reportSummaryNote.hidden = false;
        reportSummaryNote.innerHTML = [
            '<i class="fas fa-circle-info"></i> Draf AI — baca dan sesuaikan sebelum laporan diunduh.',
            ...(data.notes || []).map(n => `<br><i class="fas fa-triangle-exclamation"></i> ${escapeHtml(n)}`),
        ].join('');
    } catch (err) {
        showToast(`Gagal menyusun ringkasan: ${err.message}`, 'error');
    } finally {
        reportSummaryBtn.innerHTML = original;
        updateReportCount();
    }
}

async function downloadReport(format) {
    const btn = format === 'docx' ? reportDocxBtn : reportPdfBtn;
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyusun…';
    try {
        const res = await fetch(`/api/findings/report?format=${format}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(reportOptions()),
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || `HTTP ${res.status}`);
        }
        const blob = await res.blob();
        const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '')?.[1]
            || `laporan_hasil_audit.${format}`;
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = name;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        showToast(`Laporan ${format === 'docx' ? 'Word' : 'PDF'} diunduh.`, 'success');
    } catch (err) {
        showToast(`Gagal menyusun laporan: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = original;
        updateReportCount();
    }
}

$('#findingsReportBtn')?.addEventListener('click', openReportModal);
$('#reportModalClose')?.addEventListener('click', closeReportModal);
$('#reportCancelBtn')?.addEventListener('click', closeReportModal);
reportModal?.addEventListener('click', e => { if (e.target === reportModal) closeReportModal(); });
document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && reportModal?.style.display === 'flex') closeReportModal();
});
reportStatusChecks?.addEventListener('change', updateReportCount);
reportRiskChecks?.addEventListener('change', updateReportCount);
reportSummaryBtn?.addEventListener('click', draftSummary);
reportDocxBtn?.addEventListener('click', () => downloadReport('docx'));
reportPdfBtn?.addEventListener('click', () => downloadReport('pdf'));

bindSendButtons();
onPageEnter('findings', () => {
    render();
    loadFindings();
});
loadFindings();
