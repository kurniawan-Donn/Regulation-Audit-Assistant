/**
 * Beranda: sapaan, ringkasan angka, alur kerja, aktivitas terakhir, dan tips.
 * Tombol mana pun dengan data-goto="<halaman>" (di seluruh app) pindah halaman.
 */

import { $, escapeHtml, onPageEnter, state, switchPage } from './core.js';
import { loadHistory, refreshHistory } from './history.js';
import { openSettings, switchSettingsView } from './settings.js';

const RECENT_LIMIT = 5;

const TIPS = [
    'Tekan <kbd>Ctrl</kbd> + <kbd>K</kbd> untuk langsung mencari di tabel halaman yang sedang dibuka.',
    'Upload regulasi sekali ke <b>Database Regulasi</b> — setelah itu Compliance Review, Tanya Regulasi, dan Bandingkan Regulasi bisa langsung memakainya.',
    'Di <b>Tanya Regulasi</b>, klik angka sitasi <b>[1]</b> untuk membuka kutipan pasal aslinya.',
    'Hasil <b>Padanan</b> di Bandingkan Regulasi adalah kandidat — cek teks kedua pasal sebelum dipakai di kertas kerja.',
    'Status <b>Perlu Verifikasi</b> di Compliance Review berarti rujukan AI tidak bisa dicocokkan dengan regulasi — periksa manual.',
    'Isi <b>Filter Klausul</b> atau kata kunci untuk membatasi analisis ke bagian tertentu dan menghemat biaya AI.',
    'Mode gelap bisa diaktifkan cepat lewat tombol <i class="fas fa-moon"></i> di bawah sidebar.',
    'Semua hasil analisis bisa diekspor ke <b>Excel</b> dan <b>PDF</b> siap lampir di kertas kerja.',
];

const homeGreeting = $('#homeGreeting');
const homeStatRegs = $('#homeStatRegs');
const homeStatChunks = $('#homeStatChunks');
const homeStatHistory = $('#homeStatHistory');
const homeStatFindings = $('#homeStatFindings');
const homeRecent = $('#homeRecent');
const homeTip = $('#homeTip');
const homeTipNext = $('#homeTipNext');

let tipIndex = Math.floor(Math.random() * TIPS.length);

const numberFmt = new Intl.NumberFormat('id-ID');
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

// Angka "menghitung naik" saat Beranda dibuka.
function countUp(el, target) {
    if (!el) return;
    if (reduceMotion.matches || target <= 0) {
        el.textContent = numberFmt.format(target);
        return;
    }
    const start = performance.now();
    const duration = 650;
    const tick = now => {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 3);
        el.textContent = numberFmt.format(Math.round(target * eased));
        if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
}

function greeting() {
    const hour = new Date().getHours();
    const salam = hour < 11 ? 'Selamat pagi' : hour < 15 ? 'Selamat siang' : hour < 18 ? 'Selamat sore' : 'Selamat malam';
    const today = new Date().toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    return `<i class="fas fa-sun"></i> ${salam} · ${escapeHtml(today)}`;
}

// ====== Mulai cepat (pengguna baru) ======
const ONBOARDING_HIDDEN_KEY = 'rta_onboarding_hidden';
const homeOnboarding = $('#homeOnboarding');
const homeOnboardingProgress = $('#homeOnboardingProgress');
const onboarding = { apiKey: null, regulations: null };

function onboardingHidden() {
    try { return localStorage.getItem(ONBOARDING_HIDDEN_KEY) === '1'; } catch (_) { return false; }
}

function renderOnboarding() {
    if (!homeOnboarding) return;
    // Tunggu sampai status API key & database diketahui supaya kartu tidak berkedip.
    if (onboarding.apiKey === null || onboarding.regulations === null) return;
    const done = {
        'api-key': onboarding.apiKey,
        regulation: onboarding.regulations > 0,
        analysis: (state.history || []).length > 0,
    };
    const count = Object.values(done).filter(Boolean).length;
    homeOnboarding.hidden = onboardingHidden() || count === 3;
    homeOnboardingProgress.textContent = `${count} dari 3 langkah selesai`;
    homeOnboarding.querySelectorAll('[data-step]').forEach(li => {
        li.classList.toggle('is-done', !!done[li.dataset.step]);
    });
}

async function loadApiKeyStatus() {
    try {
        const res = await fetch('/api/settings');
        if (!res.ok) return;
        onboarding.apiKey = !!(await res.json()).gemini_api_key_set;
        renderOnboarding();
    } catch (_) { /* biarkan kartu tersembunyi */ }
}

$('#homeOnboardingHide')?.addEventListener('click', () => {
    try { localStorage.setItem(ONBOARDING_HIDDEN_KEY, '1'); } catch (_) { /* storage diblokir */ }
    homeOnboarding.hidden = true;
});

homeOnboarding?.addEventListener('click', e => {
    if (e.target.closest('[data-onboarding-action="api-key"]')) {
        openSettings();
        switchSettingsView('model-ai');
    }
});

async function loadDbStats() {
    try {
        const res = await fetch('/api/regulation-db/stats');
        if (!res.ok) throw new Error();
        const stats = await res.json();
        onboarding.regulations = stats.total_regulations;
        renderOnboarding();
        countUp(homeStatRegs, stats.total_regulations);
        countUp(homeStatChunks, stats.total_chunks);
    } catch (_) {
        homeStatRegs.textContent = '–';
        homeStatChunks.textContent = '–';
    }
}

function renderHistoryStats() {
    const history = state.history || [];
    countUp(homeStatHistory, history.length);
    const findings = history
        .filter(h => h.type === 'compliance_review')
        .reduce((n, h) => n + (h.total_tidak_patuh || 0), 0);
    countUp(homeStatFindings, findings);
}

const RECENT_TYPES = {
    compliance_review: {
        icon: '<span class="home-tool-icon tone-teal"><i class="fas fa-scale-balanced"></i></span>',
        meta: e => `Compliance Review · ${e.total_items || 0} klausul · ${e.total_tidak_patuh || 0} tidak patuh`,
    },
    gap_analysis: {
        icon: '<span class="home-tool-icon tone-violet"><i class="fas fa-magnifying-glass-chart"></i></span>',
        meta: e => `Gap Analysis · ${e.total_requirements || 0} persyaratan`,
    },
    regulation_audit: {
        icon: '<span class="home-tool-icon tone-indigo"><i class="fas fa-clipboard-check"></i></span>',
        meta: e => `Regulation to Audit · ${e.total_ketentuan || 0} ketentuan`,
    },
};

function recentItemHtml(entry) {
    const kind = RECENT_TYPES[entry.type] || RECENT_TYPES.regulation_audit;
    const icon = kind.icon;
    const meta = kind.meta(entry);
    const date = new Date(entry.tanggal).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' });
    return `
        <button type="button" class="home-recent-item" data-history-id="${escapeHtml(entry.id)}" data-history-type="${entry.type || 'regulation_audit'}">
            ${icon}
            <span class="home-recent-text">
                <strong>${escapeHtml(entry.nama || 'Tanpa nama')}</strong>
                <span>${escapeHtml(meta)} · ${escapeHtml(date)}</span>
            </span>
            <i class="fas fa-chevron-right home-tool-go"></i>
        </button>`;
}

function renderRecent() {
    const recent = [...(state.history || [])]
        .sort((a, b) => new Date(b.tanggal) - new Date(a.tanggal))
        .slice(0, RECENT_LIMIT);
    if (!recent.length) {
        homeRecent.innerHTML = `
            <div class="home-recent-empty">
                <i class="fas fa-seedling"></i>
                Belum ada analisis. Hasil yang Anda buat akan muncul di sini.
                <div><button type="button" class="btn btn-primary btn-sm" data-goto="regulation-audit">
                    <i class="fas fa-plus"></i> Analisis pertama
                </button></div>
            </div>`;
        return;
    }
    homeRecent.innerHTML = recent.map(recentItemHtml).join('');
}

function showTip(step = 0) {
    tipIndex = (tipIndex + step + TIPS.length) % TIPS.length;
    homeTip.innerHTML = TIPS[tipIndex];
    // Ulang animasi masuk
    homeTip.style.animation = 'none';
    void homeTip.offsetWidth;
    homeTip.style.animation = '';
}

function refreshHome() {
    if (homeGreeting) homeGreeting.innerHTML = greeting();
    renderHistoryStats();
    renderRecent();
    loadDbStats();
    loadApiKeyStatus();
}

// Navigasi: tombol data-goto di mana pun.
document.addEventListener('click', e => {
    const goto = e.target.closest('[data-goto]');
    if (goto) {
        switchPage(goto.dataset.goto);
        window.scrollTo({ top: 0, behavior: 'smooth' });
        return;
    }
    const recent = e.target.closest('[data-history-id]');
    if (recent) loadHistory(recent.dataset.historyId, recent.dataset.historyType);
});

homeTipNext?.addEventListener('click', () => showTip(1));

if (homeTip) showTip();
onPageEnter('home', () => {
    refreshHome();
    refreshHistory();
});

// Riwayat dimuat dari server secara async — perbarui Beranda begitu datang.
document.addEventListener('history:updated', () => {
    if (state.currentPage !== 'home') return;
    renderHistoryStats();
    renderRecent();
    renderOnboarding();
});
