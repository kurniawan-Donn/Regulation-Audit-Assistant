/**
 * Pencarian global lintas hasil analisis (Ctrl+K).
 */

import {
    $,
    escapeAttr,
    onPageEnter,
    showToast,
    state,
    switchPage,
} from './core.js';
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
    updateProgressBadge,
} from './audit.js';
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

    // ====== SEARCH GLOBAL STATE ======
const searchState = {
    query: '',
    tool: 'all',
    days: '',
    loading: false,
    debounceTimer: null,
    abortController: null,
};

// ====== SEARCH GLOBAL DOM REFS ======
const globalSearchInput = $('#globalSearchInput');
const globalSearchClear = $('#globalSearchClear');
const globalSearchTool = $('#globalSearchTool');
const globalSearchDays = $('#globalSearchDays');
const searchResultSection = $('#searchResultSection');
const searchResultCount = $('#searchResultCount');
const searchGroupedResults = $('#searchGroupedResults');
const searchEmptyState = $('#searchEmptyState');
const searchHintSection = $('#searchHintSection');

// ============================================================
// SEARCH GLOBAL
// ============================================================

const SEARCH_DEBOUNCE_MS = 350;

function escapeHtmlSearch(text) {
    const div = document.createElement('div');
    div.textContent = String(text == null ? '' : text);
    return div.innerHTML;
}

function highlightQuery(text, query) {
    if (!text) return '';
    const escaped = escapeHtmlSearch(text);
    if (!query) return escaped;

    // Escape query untuk regex
    const safe = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    try {
        const regex = new RegExp(`(${safe})`, 'gi');
        return escaped.replace(regex, '<mark>$1</mark>');
    } catch (err) {
        return escaped;
    }
}

function formatRelativeDate(isoStr) {
    if (!isoStr) return '';
    try {
        const d = new Date(isoStr);
        const now = new Date();
        const diffMs = now - d;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        if (diffDays === 0) return 'Hari ini';
        if (diffDays === 1) return 'Kemarin';
        if (diffDays < 7) return `${diffDays} hari lalu`;
        if (diffDays < 30) return `${Math.floor(diffDays / 7)} minggu lalu`;
        if (diffDays < 365) return `${Math.floor(diffDays / 30)} bulan lalu`;
        return d.toLocaleDateString('id-ID');
    } catch (err) {
        return '';
    }
}

function sourceLabel(source) {
    if (source === 'regulation_audit') return 'Regulation to Audit';
    if (source === 'gap_analysis') return 'Gap Analysis';
    return source;
}

function sourceIcon(source) {
    if (source === 'regulation_audit') return 'fa-clipboard-check';
    if (source === 'gap_analysis') return 'fa-magnifying-glass-chart';
    return 'fa-file';
}

async function performGlobalSearch() {
    const query = (searchState.query || '').trim();

    // Update clear button visibility
    if (globalSearchClear) {
        globalSearchClear.style.display = query.length > 0 ? 'flex' : 'none';
    }

    // Kalau query < 2 karakter, sembunyikan hasil, tampilkan hint
    if (query.length < 2) {
        if (searchResultSection) searchResultSection.style.display = 'none';
        if (searchHintSection) searchHintSection.style.display = 'block';
        return;
    }

    if (searchState.loading) return;
    searchState.loading = true;

    // Cancel request sebelumnya
    if (searchState.abortController) searchState.abortController.abort();
    searchState.abortController = new AbortController();

    // Loading state
    if (searchHintSection) searchHintSection.style.display = 'none';
    if (searchResultSection) searchResultSection.style.display = 'block';
    if (searchGroupedResults) {
        searchGroupedResults.innerHTML = `
                <div class="search-loading">
                    <i class="fas fa-spinner fa-spin"></i> Mencari...
                </div>
            `;
    }
    if (searchEmptyState) searchEmptyState.style.display = 'none';

    // Build URL
    const params = new URLSearchParams();
    params.set('q', query);
    params.set('tools', searchState.tool || 'all');
    if (searchState.days) params.set('days', searchState.days);
    params.set('limit', '200');

    try {
        const res = await fetch(`/api/search?${params.toString()}`, {
            signal: searchState.abortController.signal,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        renderSearchResults(data);
    } catch (err) {
        if (err.name === 'AbortError') return;
        if (searchGroupedResults) {
            searchGroupedResults.innerHTML = `
                    <div class="search-loading" style="color:var(--warn);">
                        <i class="fas fa-exclamation-circle"></i>
                        Gagal mencari: ${escapeHtmlSearch(err.message)}
                    </div>
                `;
        }
    } finally {
        searchState.loading = false;
    }
}

function renderSearchResults(data) {
    const results = data.results || [];
    const total = data.total || 0;

    if (searchResultCount) {
        searchResultCount.textContent = total === 0
            ? 'Tidak ada hasil'
            : `${total} hasil ditemukan`;
    }

    if (results.length === 0) {
        if (searchGroupedResults) searchGroupedResults.innerHTML = '';
        if (searchEmptyState) searchEmptyState.style.display = 'block';
        return;
    }
    if (searchEmptyState) searchEmptyState.style.display = 'none';

    // Group by (source::filename)
    const groups = {};
    for (const r of results) {
        const key = `${r.source}::${r.filename}::${r.result_id}`;
        if (!groups[key]) {
            groups[key] = {
                source: r.source,
                filename: r.filename,
                result_id: r.result_id,
                items: [],
            };
        }
        groups[key].items.push(r);
    }

    // Render
    const html = Object.values(groups).map(g => {
        const itemsHtml = g.items.map(item => {
            const highlightedTitle = highlightQuery(item.title || '(tanpa judul)', data.query);
            const highlightedSnippet = highlightQuery(item.snippet || '', data.query);

            const metaParts = [];
            if (item.referensi) {
                metaParts.push(`<span><i class="fas fa-book"></i> ${escapeHtmlSearch(item.referensi)}</span>`);
            }
            if (item.aspek) {
                metaParts.push(`<span><i class="fas fa-layer-group"></i> ${escapeHtmlSearch(item.aspek)}</span>`);
            }
            if (item.status && item.status !== 'Belum Diaudit' && item.status !== '') {
                metaParts.push(`<span><i class="fas fa-circle-check"></i> ${escapeHtmlSearch(item.status)}</span>`);
            }
            metaParts.push(`<span><i class="fas fa-hashtag"></i> Item #${item.item_index + 1}</span>`);

            return `
                    <div class="search-result-item"
                         data-source="${escapeAttr(g.source)}"
                         data-result-id="${escapeAttr(g.result_id)}"
                         data-item-index="${item.item_index}">
                        <div class="search-result-item-body">
                            <div class="search-result-item-title">${highlightedTitle}</div>
                            <div class="search-result-item-snippet">${highlightedSnippet}</div>
                            <div class="search-result-item-meta">${metaParts.join('')}</div>
                        </div>
                        <i class="fas fa-arrow-right search-result-item-arrow"></i>
                    </div>
                `;
        }).join('');

        return `
                <div class="search-group">
                    <div class="search-group-header">
                        <i class="fas ${sourceIcon(g.source)}"></i>
                        <span class="search-group-source">${sourceLabel(g.source)}</span>
                        <span>${escapeHtmlSearch(g.filename)}</span>
                        <span class="search-group-count">${g.items.length} hasil</span>
                    </div>
                    ${itemsHtml}
                </div>
            `;
    }).join('');

    if (searchGroupedResults) searchGroupedResults.innerHTML = html;

    // Attach click handlers
    searchGroupedResults.querySelectorAll('.search-result-item').forEach(el => {
        el.addEventListener('click', () => {
            const source = el.dataset.source;
            const resultId = el.dataset.resultId;
            const itemIndex = parseInt(el.dataset.itemIndex, 10);
            handleSearchResultClick(source, resultId, itemIndex);
        });
    });
}

async function handleSearchResultClick(source, resultId, itemIndex) {
    // Navigate ke halaman tool yang sesuai
    if (source === 'regulation_audit') {
        switchPage('regulation-audit');
        // Load result
        try {
            const res = await fetch(`/api/results/${resultId}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
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
            if (resultSection) {
                resultSection.style.display = 'block';
                resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
            // Highlight item yang di-klik dengan scroll + flash
            highlightItemInTable(itemIndex);
        } catch (err) {
            showToast(`Gagal memuat dokumen: ${err.message}`, 'error');
        }
    } else if (source === 'gap_analysis') {
        switchPage('gap-analysis');
        try {
            const res = await fetch(`/api/requirements/${resultId}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            state.gapResultId = data.result_id;
            state.gapData = data;
            state.gapSelectedRows = new Set();
            state.gapStatusFilter = '';
            if (gapStatusFilter) gapStatusFilter.value = '';
            if (gapExportBtn) gapExportBtn.disabled = false;
            if (gapExportPdfBtn) gapExportPdfBtn.disabled = false;
            if (gapCopyBtn) gapCopyBtn.disabled = false;
            renderGapSummary(data);
            renderGapChunkErrors(data.chunk_errors || []);
            renderGapTable(data.requirements || []);
            if (gapResultSection) {
                gapResultSection.style.display = 'block';
                gapResultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
            // Highlight item
            highlightGapItemInTable(itemIndex);
        } catch (err) {
            showToast(`Gagal memuat dokumen: ${err.message}`, 'error');
        }
    }

    showToast('Dokumen dibuka. Lihat baris yang di-highlight.', 'info');
}

function highlightItemInTable(idx) {
    setTimeout(() => {
        const row = document.querySelector(`#resultBody tr[data-idx="${idx}"]`);
        if (!row) return;
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.classList.add('search-highlight-row');
        setTimeout(() => row.classList.remove('search-highlight-row'), 2500);
    }, 300);
}

function highlightGapItemInTable(idx) {
    setTimeout(() => {
        const row = document.querySelector(`#gapResultBody tr[data-idx="${idx}"]`);
        if (!row) return;
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.classList.add('search-highlight-row');
        setTimeout(() => row.classList.remove('search-highlight-row'), 2500);
    }, 300);
}

// --- Input handler (debounced) ---
if (globalSearchInput) {
    globalSearchInput.addEventListener('input', (e) => {
        searchState.query = e.target.value;
        if (searchState.debounceTimer) clearTimeout(searchState.debounceTimer);
        searchState.debounceTimer = setTimeout(performGlobalSearch, SEARCH_DEBOUNCE_MS);
    });

    // Enter untuk langsung search
    globalSearchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (searchState.debounceTimer) clearTimeout(searchState.debounceTimer);
            performGlobalSearch();
        }
    });
}

// --- Clear button ---
if (globalSearchClear) {
    globalSearchClear.addEventListener('click', () => {
        if (globalSearchInput) globalSearchInput.value = '';
        searchState.query = '';
        globalSearchClear.style.display = 'none';
        if (searchResultSection) searchResultSection.style.display = 'none';
        if (searchHintSection) searchHintSection.style.display = 'block';
        if (globalSearchInput) globalSearchInput.focus();
    });
}

// --- Filter handlers ---
if (globalSearchTool) {
    globalSearchTool.addEventListener('change', (e) => {
        searchState.tool = e.target.value;
        if (searchState.query && searchState.query.trim().length >= 2) {
            performGlobalSearch();
        }
    });
}

if (globalSearchDays) {
    globalSearchDays.addEventListener('change', (e) => {
        searchState.days = e.target.value;
        if (searchState.query && searchState.query.trim().length >= 2) {
            performGlobalSearch();
        }
    });
}

onPageEnter('search', () => {
    if (globalSearchInput) setTimeout(() => globalSearchInput.focus(), 100);
});
