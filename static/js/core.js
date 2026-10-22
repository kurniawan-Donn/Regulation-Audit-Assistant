/**
 * Inti aplikasi: header anti-CSRF, state global, helper DOM, routing halaman,
 * tema, utilitas format/escape, dan toast. Tidak bergantung pada modul lain —
 * modul fitur mendaftarkan hook lewat onPageEnter() / onThemeChange().
 */

// ====== KEAMANAN: header anti-CSRF ======
// Server menolak POST/PUT/PATCH/DELETE ke /api tanpa header ini (lihat
// app/security.py). Dipasang sekali di sini supaya semua fetch() aplikasi
// otomatis membawanya.
const CSRF_HEADER = 'X-Requested-With';
const CSRF_VALUE = 'RAA';
const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    const method = (init.method || (typeof input === 'object' && input.method) || 'GET').toUpperCase();
    const sameOriginApi = url.startsWith('/api/') || url.startsWith(`${location.origin}/api/`);
    if (sameOriginApi && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        const headers = new Headers(init.headers || {});
        headers.set(CSRF_HEADER, CSRF_VALUE);
        init = { ...init, headers };
    }
    return nativeFetch(input, init);
};

// ====== STATE ======
export const state = {
    currentPage: 'regulation-audit',
    currentResultId: null,
    currentData: null,
    filter: 'all',
    statusFilter: '',
    searchQuery: '',
    selectedRows: new Set(),
    gapResultId: null,
    gapData: null,
    gapSearchQuery: '',
    gapStatusFilter: '',
    gapSelectedRows: new Set(),
    theme: localStorage.getItem('rta_theme') || 'light',
    history: JSON.parse(localStorage.getItem('rta_history') || '[]'),
    isAnalyzing: false,
    settings: null,
};

export const treeState = {
    previewId: null,
    filename: '',
    tree: [],
    expanded: new Set(),
    selectedLeaves: new Set(),
    totalChunks: 0,
    isReAnalyze: false,
};

// ====== DOM HELPERS ======
export function $(sel) {
    return document.querySelector(sel);
}

export function $$(sel) {
    return document.querySelectorAll(sel);
}

// ====== HOOK MODUL FITUR ======
// core.js tidak meng-import modul fitur; modul fitur mendaftarkan diri di sini.
const pageEnterHooks = {};
const themeChangeHooks = [];

export function onPageEnter(pageName, fn) {
    (pageEnterHooks[pageName] = pageEnterHooks[pageName] || []).push(fn);
}

export function onThemeChange(fn) {
    themeChangeHooks.push(fn);
}

// ====== SIDEBAR / ROUTING ======
export const sidebar = $('#sidebar');
const sidebarOverlay = $('#sidebarOverlay');
const mobileMenuBtn = $('#mobileMenuBtn');
const mobileHeaderTitle = $('#mobileHeaderTitle');
const sidebarItems = $$('.sidebar-item');

// Halaman = <main class="page" id="page-{nama}">; judul untuk header mobile.
const PAGE_TITLES = {
    'regulation-audit': 'Regulation to Audit',
    'gap-analysis': 'Gap Analysis',
    'compliance-review': 'Compliance Review',
    'regulation-db': 'Database Regulasi',
    'chat': 'Tanya Regulasi',
    'search': 'Cari Global',
};

export function switchPage(pageName) {
    if (!PAGE_TITLES[pageName]) return;
    state.currentPage = pageName;

    document.querySelectorAll('main.page').forEach(page => {
        page.style.display = page.id === `page-${pageName}` ? '' : 'none';
    });

    sidebarItems.forEach(item => {
        item.classList.toggle('active', item.dataset.page === pageName);
    });

    if (mobileHeaderTitle) {
        mobileHeaderTitle.textContent = PAGE_TITLES[pageName];
    }

    closeMobileSidebar();
    localStorage.setItem('rta_current_page', pageName);
    (pageEnterHooks[pageName] || []).forEach(fn => fn());
    if (pageName !== 'compliance-review') {
        document.querySelectorAll('.compliance-status-menu').forEach(m => m.remove());
    }
}

sidebarItems.forEach(item => {
    item.addEventListener('click', () => {
        switchPage(item.dataset.page);
    });
});

function openMobileSidebar() {
    if (sidebar) sidebar.classList.add('open');
    if (sidebarOverlay) sidebarOverlay.classList.add('visible');
}

export function closeMobileSidebar() {
    if (sidebar) sidebar.classList.remove('open');
    if (sidebarOverlay) sidebarOverlay.classList.remove('visible');
}

if (mobileMenuBtn) mobileMenuBtn.addEventListener('click', openMobileSidebar);
if (sidebarOverlay) sidebarOverlay.addEventListener('click', closeMobileSidebar);

// ====== THEME ======
// applyTheme(state.theme) dipanggil di main.js setelah semua modul (dan hook-nya) dimuat.
function resolveTheme(pref) {
    if (pref === 'auto') {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return pref;
}

export function applyTheme(pref) {
    state.theme = pref;
    localStorage.setItem('rta_theme', pref);
    const resolved = resolveTheme(pref);
    document.documentElement.setAttribute('data-theme', resolved);
    document.documentElement.setAttribute('data-theme-pref', pref);
    document.querySelectorAll('input[name="theme"]').forEach(r => {
        r.checked = r.value === pref;
    });
    themeChangeHooks.forEach(fn => fn());
}

const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
darkModeQuery.addEventListener('change', () => {
    if (state.theme === 'auto') applyTheme('auto');
});

// ====== HELPERS ======
export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text == null ? '' : text);
    return div.innerHTML;
}

export function escapeAttr(text) {
    return String(text == null ? '' : text)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

export function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

export function formatIdr(value) {
    if (value < 1) return '< Rp 1';
    if (value < 1000) return `Rp ${Math.round(value)}`;
    if (value < 1_000_000) return `Rp ${(value / 1000).toFixed(1)}rb`;
    return `Rp ${(value / 1_000_000).toFixed(2)}jt`;
}

export function formatDuration(seconds) {
    if (seconds < 60) return `${seconds} detik`;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return s > 0 ? `${m} menit ${s} detik` : `${m} menit`;
}

export function renderMarkdownLite(text) {
    if (!text) return '';
    let s = escapeHtml(text);
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    const lines = s.split('\n');
    const rendered = lines.map(line => {
        const trimmed = line.trim();
        if (!trimmed) return '<span class="md-blank"></span>';
        const match = line.match(/^( +)/);
        const indent = match ? match[1].length : 0;
        let cls = 'md-line';
        if (indent >= 6) cls += ' md-indent-2';
        else if (indent >= 3) cls += ' md-indent-1';
        const content = line.replace(/^ +/, '');
        return `<span class="${cls}">${content}</span>`;
    }).join('');
    return `<div class="md-content">${rendered}</div>`;
}

// ====== TOAST ======
const toastContainer = $('#toastContainer');

export function showToast(message, type = 'info') {
    const icons = { success: 'fa-check-circle', error: 'fa-exclamation-circle', info: 'fa-info-circle' };
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<i class="fas ${icons[type] || icons.info}"></i> <span>${escapeHtml(message)}</span>`;
    if (toastContainer) {
        toastContainer.appendChild(toast);
        setTimeout(() => toast.remove(), 4200);
    }
}
