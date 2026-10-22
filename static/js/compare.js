/**
 * Bandingkan Regulasi: padanan ketentuan dua regulasi di Database Regulasi
 * (identik / berubah + diff kata / padanan / hanya di A / hanya di B).
 */

import { $, escapeHtml, onPageEnter, showToast } from './core.js';

const PAGE_SIZE = 100;
const STATUS_LABELS = {
    identik: 'Identik',
    berubah: 'Berubah',
    padanan: 'Padanan',
    hanya_a: 'Hanya di A',
    hanya_b: 'Hanya di B',
};

const compareForm = $('#compareForm');
const compareRegA = $('#compareRegA');
const compareRegB = $('#compareRegB');
const compareSwapBtn = $('#compareSwapBtn');
const compareRunBtn = $('#compareRunBtn');
const compareResult = $('#compareResult');
const compareTitle = $('#compareTitle');
const compareFilters = $('#compareFilters');
const compareSearch = $('#compareSearch');
const compareList = $('#compareList');
const compareEmpty = $('#compareEmpty');
const compareMoreBtn = $('#compareMoreBtn');
const compareExportBtn = $('#compareExportBtn');

const compareState = {
    result: null,
    filter: 'all',
    query: '',
    shown: PAGE_SIZE,
    running: false,
};

// ====== Pilihan regulasi ======
async function loadRegulationOptions() {
    if (!compareRegA) return;
    try {
        const res = await fetch('/api/regulation-db/regulations');
        if (!res.ok) return;
        const { regulations } = await res.json();
        const options = regulations.map(r =>
            `<option value="${escapeHtml(r.id)}">${escapeHtml(r.name)} (${r.total_chunks} bagian)</option>`
        ).join('');
        const empty = '<option value="">— Pilih regulasi —</option>';
        const [prevA, prevB] = [compareRegA.value, compareRegB.value];
        compareRegA.innerHTML = empty + options;
        compareRegB.innerHTML = empty + options;
        const has = id => regulations.some(r => r.id === id);
        compareRegA.value = has(prevA) ? prevA : (regulations[0]?.id || '');
        compareRegB.value = has(prevB) ? prevB : (regulations[1]?.id || '');
        compareRunBtn.disabled = regulations.length < 2;
    } catch (_) { /* daftar tetap kosong; tombol Bandingkan memberi pesan */ }
}

// ====== Render ======
function refHtml(chunk) {
    if (!chunk) return '<span class="cmp-none">—</span>';
    const page = chunk.page_start && !/hal\. \d/.test(chunk.reference) ? ` · hal. ${chunk.page_start}` : '';
    return `<span>${escapeHtml(chunk.reference)}${page}</span>`;
}

function diffHtml(diff) {
    return diff.map(seg => {
        const text = escapeHtml(seg.text);
        if (seg.op === 'del') return `<del>${text}</del>`;
        if (seg.op === 'ins') return `<ins>${text}</ins>`;
        return text;
    }).join(' ');
}

function scoreText(item) {
    if (item.text_ratio !== null && item.text_ratio !== undefined) {
        return `rumusan ${Math.round(item.text_ratio * 100)}% sama`;
    }
    if (item.status === 'padanan') return `kemiripan isi ${item.similarity.toFixed(2)}`;
    return '';
}

function textBlock(label, html) {
    return `<div><div class="cmp-col-label">${label}</div><div class="cmp-text">${html}</div></div>`;
}

function bodyHtml(item) {
    const { status, a, b } = item;
    if ((status === 'berubah' || status === 'identik') && item.diff.length) {
        return `${textBlock('Perubahan A → B', diffHtml(item.diff))}
            <details class="cmp-nearest"><summary>Lihat teks asli berdampingan</summary>
                <div class="cmp-cols">${textBlock('A', escapeHtml(a.text))}${textBlock('B', escapeHtml(b.text))}</div>
            </details>`;
    }
    if (a && b) {
        return `<div class="cmp-cols">${textBlock('A', escapeHtml(a.text))}${textBlock('B', escapeHtml(b.text))}</div>`;
    }
    const own = a || b;
    let html = textBlock(a ? 'A' : 'B', escapeHtml(own.text));
    if (item.nearest) {
        html += `<details class="cmp-nearest">
                <summary>Kandidat terdekat di B (kemiripan ${item.similarity.toFixed(2)}, di bawah ambang): ${escapeHtml(item.nearest.reference)}</summary>
                ${textBlock('B', escapeHtml(item.nearest.text))}
            </details>`;
    }
    return html;
}

function itemEl(item) {
    const el = document.createElement('details');
    el.className = `cmp-item st-${item.status}`;
    const refs = item.status === 'hanya_b'
        ? `<span class="cmp-none">tidak ada di A</span><span class="cmp-arrow">→</span>${refHtml(item.b)}`
        : `${refHtml(item.a)}<span class="cmp-arrow">→</span>${item.b ? refHtml(item.b) : '<span class="cmp-none">tidak ada di B</span>'}`;
    el.innerHTML = `
        <summary>
            <span class="cmp-badge cmp-${item.status}">${STATUS_LABELS[item.status]}</span>
            <span class="cmp-refs">${refs}</span>
            <span class="cmp-score">${scoreText(item)}</span>
        </summary>
        <div class="cmp-body"></div>`;
    // Isi (bisa panjang) baru dirender saat dibuka.
    el.addEventListener('toggle', () => {
        const body = el.querySelector('.cmp-body');
        if (el.open && !body.childElementCount) body.innerHTML = bodyHtml(item);
    });
    return el;
}

function filteredItems() {
    const { result, filter } = compareState;
    const q = compareState.query.trim().toLowerCase();
    return result.items.filter(item => {
        if (filter !== 'all' && item.status !== filter) return false;
        if (!q) return true;
        return [item.a, item.b].some(c => c &&
            (c.reference.toLowerCase().includes(q) || c.text.toLowerCase().includes(q)));
    });
}

function renderFilters() {
    const { summary } = compareState.result;
    const total = Object.values(summary).reduce((n, v) => n + v, 0);
    const chips = [['all', 'Semua', total], ...Object.entries(STATUS_LABELS).map(([k, label]) => [k, label, summary[k] || 0])];
    compareFilters.innerHTML = chips.map(([key, label, count]) =>
        `<button type="button" class="cmp-filter ${compareState.filter === key ? 'is-active' : ''}" data-filter="${key}"
            aria-pressed="${compareState.filter === key}">${label}<b>${count}</b></button>`
    ).join('');
}

function renderList() {
    const items = filteredItems();
    compareList.innerHTML = '';
    const frag = document.createDocumentFragment();
    items.slice(0, compareState.shown).forEach(item => frag.appendChild(itemEl(item)));
    compareList.appendChild(frag);
    compareEmpty.style.display = items.length ? 'none' : '';
    const rest = items.length - compareState.shown;
    compareMoreBtn.style.display = rest > 0 ? '' : 'none';
    compareMoreBtn.textContent = `Tampilkan ${Math.min(rest, PAGE_SIZE)} lagi (sisa ${rest})`;
}

function renderResult() {
    const { regulation_a: a, regulation_b: b } = compareState.result;
    compareTitle.innerHTML = `<span>A: ${escapeHtml(a.name)}</span><span class="cmp-vs">vs</span><span>B: ${escapeHtml(b.name)}</span>`;
    compareResult.style.display = '';
    renderFilters();
    renderList();
}

// ====== Aksi ======
async function runCompare() {
    if (compareState.running) return;
    const [idA, idB] = [compareRegA.value, compareRegB.value];
    if (!idA || !idB) {
        showToast('Pilih dua regulasi untuk dibandingkan.', 'error');
        return;
    }
    if (idA === idB) {
        showToast('Pilih dua regulasi yang berbeda.', 'error');
        return;
    }
    compareState.running = true;
    compareRunBtn.disabled = true;
    compareRunBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Membandingkan…';
    try {
        const res = await fetch('/api/regulation-db/compare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ regulation_a: idA, regulation_b: idB }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `Gagal membandingkan (HTTP ${res.status}).`);
        Object.assign(compareState, { result: data, filter: 'all', query: '', shown: PAGE_SIZE });
        compareSearch.value = '';
        renderResult();
        compareResult.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) {
        showToast(err.message || 'Gagal membandingkan regulasi.', 'error');
    } finally {
        compareState.running = false;
        compareRunBtn.disabled = false;
        compareRunBtn.innerHTML = '<i class="fas fa-code-compare"></i> Bandingkan';
    }
}

function csvCell(value) {
    const s = String(value ?? '');
    return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function exportCsv() {
    const { result } = compareState;
    if (!result) return;
    const header = ['Status', `Referensi A (${result.regulation_a.name})`, 'Teks A',
        `Referensi B (${result.regulation_b.name})`, 'Teks B', 'Rumusan sama (%)', 'Kemiripan isi'];
    const rows = filteredItems().map(item => [
        STATUS_LABELS[item.status],
        item.a?.reference, item.a?.text,
        item.b?.reference, item.b?.text,
        item.text_ratio !== null && item.text_ratio !== undefined ? Math.round(item.text_ratio * 100) : '',
        item.similarity ?? '',
    ]);
    const csv = [header, ...rows].map(r => r.map(csvCell).join(',')).join('\r\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `perbandingan_${result.regulation_a.name}_vs_${result.regulation_b.name}.csv`
        .replace(/[^\w.-]+/g, '_');
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ====== Event ======
compareForm?.addEventListener('submit', e => {
    e.preventDefault();
    runCompare();
});

compareSwapBtn?.addEventListener('click', () => {
    [compareRegA.value, compareRegB.value] = [compareRegB.value, compareRegA.value];
});

compareFilters?.addEventListener('click', e => {
    const btn = e.target.closest('[data-filter]');
    if (!btn) return;
    compareState.filter = btn.dataset.filter;
    compareState.shown = PAGE_SIZE;
    renderFilters();
    renderList();
});

let searchTimer = null;
compareSearch?.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        compareState.query = compareSearch.value;
        compareState.shown = PAGE_SIZE;
        renderList();
    }, 200);
});

compareMoreBtn?.addEventListener('click', () => {
    compareState.shown += PAGE_SIZE;
    renderList();
});

compareExportBtn?.addEventListener('click', exportCsv);

onPageEnter('compare', loadRegulationOptions);
