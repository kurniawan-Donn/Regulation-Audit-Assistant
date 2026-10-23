/**
 * Tur interaktif untuk pengguna baru.
 */

import {
    $,
    showToast,
    state,
    switchPage,
} from './core.js';
import { closeSettings, openSettings, switchSettingsView } from './settings.js';
import { closeComplianceAddRowModal, complianceAddRowModalOverlay } from './compliance.js';

// ============================================================
// INTERACTIVE TOUR
// ============================================================

// v2: tampilan baru (Beranda + sidebar berkelompok) — tur ditampilkan sekali lagi.
const TOUR_STORAGE_KEY = 'rta_tour_seen_v2';

    const TOUR_STEPS = [
    {
        selector: null,
        title: 'Selamat Datang di Audit Assistant!',
        text: 'Tur singkat 30 detik untuk mengenal fitur utama aplikasi. Klik <b>Lanjut</b> untuk mulai, atau <b>Lewati</b> kalau sudah familiar.',
        position: 'center',
    },
    {
        selector: '.home-flow',
        title: 'Mulai dari Beranda',
        text: 'Ikuti <b>alur kerja</b> ini: isi Database Regulasi → pahami ketentuannya → uji kontrak → susun kertas kerja. Klik langkah mana pun untuk langsung ke alatnya.',
        position: 'bottom',
        beforeShow: () => {
            switchPage('home');
        },
    },
    {
        selector: '.sidebar-nav',
        title: 'Alat Dikelompokkan',
        text: '• <b>Analisis Dokumen</b> — Regulation to Audit, Gap Analysis, Compliance Review<br>• <b>Pengetahuan Regulasi</b> — Database, Tanya &amp; Bandingkan Regulasi<br>• <b>Cari Global</b> — cari lintas hasil analisis',
        position: 'right',
    },
    {
        selector: '#settingsToggle',
        title: 'Pengaturan',
        text: 'Atur <b>API Key</b>, <b>model AI</b>, <b>prompt</b>, dan <b>tema</b> di sini. Juga ada riwayat dan diagnostik server.',
        position: 'right',
    },
    {
        selector: '#apiKeyInput',
        title: 'Model & API Key',
        text: 'Masukkan <b>API Key Gemini</b> di sini, pilih <b>model</b>, dan klik <b>Test Koneksi</b> untuk memastikan API key valid.',
        position: 'left',
        beforeShow: () => {
            openSettings();
            switchSettingsView('model-ai');
        },
    },
    {
        selector: '.prompt-tool-tabs',
        title: 'Prompt Editor',
        text: 'Kustomisasi <b>perilaku AI</b> lewat Prompt Editor. Ada 4 preset siap pakai (Default, Ketat, Ringkas, Detail) atau bisa edit manual.',
        position: 'left',
        beforeShow: () => {
            switchSettingsView('prompt-editor');
        },
    },
    {
        selector: '#gapUploadCard',
        title: 'Gap Analysis',
        text: 'Tool kedua: ekstrak <b>daftar persyaratan</b> dari regulasi untuk checklist kepatuhan. Bisa filter kata kunci untuk hemat biaya AI.',
        position: 'fixed-bottom-right',
        beforeShow: () => {
            closeSettings();
            switchPage('gap-analysis');
        },
    },
    {
        selector: '#globalSearchInput',
        title: 'Cari Global',
        text: 'Cari <b>ketentuan atau persyaratan</b> di seluruh analisis yang pernah dibuat. Hasil di-group per dokumen, klik untuk buka.',
        position: 'bottom',
        beforeShow: () => {
            switchPage('search');
        },
    },
    {
        selector: null,
        title: 'Siap Digunakan!',
        text: 'Tur bisa dibuka lagi kapan saja dari menu <b>Pengaturan → Panduan Penggunaan</b>. Selamat bekerja!',
        position: 'center',
        beforeShow: () => {
            switchPage('home');
        },
    },
];

const tourState = {
    active: false,
    currentIndex: 0,
    resizeHandler: null,
};

// DOM refs
const tourRoot = $('#tourRoot');
const tourHighlight = $('#tourHighlight');
const tourOverlayFull = $('#tourOverlayFull');
const tourTooltip = $('#tourTooltip');
const tourArrow = $('#tourArrow');
const tourStepCounter = $('#tourStepCounter');
const tourTitle = $('#tourTitle');
const tourText = $('#tourText');
const tourNextBtn = $('#tourNextBtn');
const tourPrevBtn = $('#tourPrevBtn');
const tourSkipBtn = $('#tourSkipBtn');
const tourCloseBtn = $('#tourCloseBtn');
const tourProgressDots = $('#tourProgressDots');
const startTourBtn = $('#startTourBtn');

function startTour(force = false) {
    if (tourState.active) return;
    if (!force && localStorage.getItem(TOUR_STORAGE_KEY)) return;

    tourState.active = true;
    tourState.currentIndex = 0;

    if (tourRoot) tourRoot.style.display = 'block';
    if (tourRoot) tourRoot.setAttribute('aria-hidden', 'false');

    // Render dots
    renderTourDots();

    // Attach resize listener
    if (!tourState.resizeHandler) {
        tourState.resizeHandler = () => {
            if (tourState.active) {
                positionTourForStep(TOUR_STEPS[tourState.currentIndex]);
            }
        };
        window.addEventListener('resize', tourState.resizeHandler);
        window.addEventListener('scroll', tourState.resizeHandler, true);
    }

    goToTourStep(0);
}

    function endTour(markSeen = true) {
    tourState.active = false;
    if (tourRoot) tourRoot.style.display = 'none';
    if (tourRoot) tourRoot.setAttribute('aria-hidden', 'true');
    if (tourHighlight) tourHighlight.classList.add('tour-highlight-hidden');
    if (tourOverlayFull) tourOverlayFull.style.display = 'none';
    if (markSeen) localStorage.setItem(TOUR_STORAGE_KEY, '1');

    // Cleanup: pastikan kembali ke halaman utama & tutup panel
    try {
        closeSettings();
        switchPage('home');
    } catch (err) {
        console.warn('Tour cleanup error:', err);
    }
}

    function goToTourStep(index) {
    if (index < 0 || index >= TOUR_STEPS.length) return;
    tourState.currentIndex = index;

    const step = TOUR_STEPS[index];

    // Update counter & content
    if (tourStepCounter) {
        tourStepCounter.textContent = `${index + 1} / ${TOUR_STEPS.length}`;
    }
    if (tourTitle) tourTitle.textContent = step.title;
    if (tourText) tourText.innerHTML = step.text;

    // Update buttons
    if (tourPrevBtn) tourPrevBtn.disabled = index === 0;
    if (tourNextBtn) {
        tourNextBtn.innerHTML = (index === TOUR_STEPS.length - 1)
            ? 'Selesai <i class="fas fa-check"></i>'
            : 'Lanjut <i class="fas fa-arrow-right"></i>';
    }

    // Update dots
    updateTourDots();

    // Jalankan beforeShow (kalau ada) — mis. buka panel, switch page
    if (typeof step.beforeShow === 'function') {
        try {
            step.beforeShow();
        } catch (err) {
            console.warn('Tour beforeShow error:', err);
        }
        // Delay sebentar supaya animasi panel selesai, baru ukur posisi
        setTimeout(() => positionTourForStep(step), 350);
    } else {
        positionTourForStep(step);
    }
}

    function positionTourForStep(step) {
    if (!step) return;

    // Step tanpa target — overlay full + tooltip di center
    if (!step.selector) {
        if (tourHighlight) tourHighlight.classList.add('tour-highlight-hidden');
        if (tourOverlayFull) tourOverlayFull.style.display = 'block';
        positionTooltipCenter();
        return;
    }

    const target = document.querySelector(step.selector);
    if (!target) {
        if (tourHighlight) tourHighlight.classList.add('tour-highlight-hidden');
        if (tourOverlayFull) tourOverlayFull.style.display = 'block';
        positionTooltipCenter();
        return;
    }

    // Scroll ke target kalau perlu (biar highlight kelihatan)
    const rect0 = target.getBoundingClientRect();
    const needsScroll = rect0.top < 10 || rect0.bottom > window.innerHeight - 10;
    if (needsScroll) {
        target.scrollIntoView({ behavior: 'instant', block: 'center' });
    }

    // Re-measure setelah scroll
    const rect = target.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
        if (tourHighlight) tourHighlight.classList.add('tour-highlight-hidden');
        if (tourOverlayFull) tourOverlayFull.style.display = 'block';
        positionTooltipCenter();
        return;
    }

    // Highlight
    if (tourOverlayFull) tourOverlayFull.style.display = 'none';
    if (tourHighlight) {
        tourHighlight.classList.remove('tour-highlight-hidden');
        const padding = 6;
        tourHighlight.style.top = (rect.top - padding) + 'px';
        tourHighlight.style.left = (rect.left - padding) + 'px';
        tourHighlight.style.width = (rect.width + padding * 2) + 'px';
        tourHighlight.style.height = (rect.height + padding * 2) + 'px';
    }

    // Posisi tooltip
    // Special case: target lebar → fixed bottom-right (tidak nutup target)
    const viewportW = window.innerWidth;
    const isWideTarget = rect.width > viewportW * 0.55;

    if (step.position === 'fixed-bottom-right' || (isWideTarget && step.position !== 'bottom' && step.position !== 'top')) {
        positionTooltipFixedBottomRight();
        return;
    }

    positionTooltipNear(rect, step.position || 'right');
}

function positionTooltipCenter() {
    if (!tourTooltip) return;
    const tooltipRect = tourTooltip.getBoundingClientRect();
    const viewportW = window.innerWidth;
    const viewportH = window.innerHeight;
    const top = (viewportH - tooltipRect.height) / 2;
    const left = (viewportW - tooltipRect.width) / 2;

    tourTooltip.style.top = top + 'px';
    tourTooltip.style.left = left + 'px';

    // Arrow tersembunyi
    if (tourArrow) tourArrow.setAttribute('data-arrow', 'none');
}

    function positionTooltipFixedBottomRight() {
    if (!tourTooltip) return;

    const GAP = 20;
    const tooltipRect = tourTooltip.getBoundingClientRect();
    const viewportW = window.innerWidth;
    const viewportH = window.innerHeight;

    const top = viewportH - tooltipRect.height - GAP;
    const left = viewportW - tooltipRect.width - GAP;

    tourTooltip.style.top = top + 'px';
    tourTooltip.style.left = left + 'px';

    // Arrow tersembunyi (tidak menempel ke target)
    if (tourArrow) tourArrow.setAttribute('data-arrow', 'none');
}

    function positionTooltipNear(targetRect, preferred) {
    if (!tourTooltip) return;

    const tooltipRect = tourTooltip.getBoundingClientRect();
    const GAP = 18;
    const ARROW_SIZE = 14;
    const viewportW = window.innerWidth;
    const viewportH = window.innerHeight;

    const MIN_TOP = 10;
    const MIN_LEFT = 10;
    const MAX_TOP = viewportH - tooltipRect.height - 10;
    const MAX_LEFT = viewportW - tooltipRect.width - 10;

    // Urutan kandidat: preferred dulu, lalu fallback
    const candidates = [preferred, 'right', 'left', 'bottom', 'top'];
    let chosen = null;

    for (const pos of candidates) {
        if (pos === 'right') {
            // Cek horizontal — wajib muat
            const left = targetRect.right + GAP;
            if (left + tooltipRect.width <= viewportW - 10 && left >= MIN_LEFT) {
                // Vertical — center ke target, lalu clamp
                let top = targetRect.top + (targetRect.height - tooltipRect.height) / 2;
                top = Math.max(MIN_TOP, Math.min(top, MAX_TOP));
                chosen = { top, left, arrow: 'left' };
                break;
            }
        } else if (pos === 'left') {
            const left = targetRect.left - tooltipRect.width - GAP;
            if (left >= MIN_LEFT) {
                let top = targetRect.top + (targetRect.height - tooltipRect.height) / 2;
                top = Math.max(MIN_TOP, Math.min(top, MAX_TOP));
                chosen = { top, left, arrow: 'right' };
                break;
            }
        } else if (pos === 'bottom') {
            const top = targetRect.bottom + GAP;
            if (top + tooltipRect.height <= viewportH - 10 && top >= MIN_TOP) {
                let left = targetRect.left + (targetRect.width - tooltipRect.width) / 2;
                left = Math.max(MIN_LEFT, Math.min(left, MAX_LEFT));
                chosen = { top, left, arrow: 'top' };
                break;
            }
        } else if (pos === 'top') {
            const top = targetRect.top - tooltipRect.height - GAP;
            if (top >= MIN_TOP) {
                let left = targetRect.left + (targetRect.width - tooltipRect.width) / 2;
                left = Math.max(MIN_LEFT, Math.min(left, MAX_LEFT));
                chosen = { top, left, arrow: 'bottom' };
                break;
            }
        }
    }

    // Fallback: center kalau tidak ada yang muat
    if (!chosen) {
        positionTooltipCenter();
        return;
    }

    // Apply posisi
    tourTooltip.style.top = chosen.top + 'px';
    tourTooltip.style.left = chosen.left + 'px';

    // Position arrow
    if (tourArrow) {
        tourArrow.setAttribute('data-arrow', chosen.arrow);
        tourArrow.style.top = '';
        tourArrow.style.left = '';
        tourArrow.style.right = '';
        tourArrow.style.bottom = '';

        const arrowOffset = ARROW_SIZE / 2;
        if (chosen.arrow === 'left') {
            tourArrow.style.left = -arrowOffset + 'px';
            const arrowTop = targetRect.top + targetRect.height / 2 - chosen.top - arrowOffset;
            tourArrow.style.top = Math.max(10, Math.min(arrowTop, tooltipRect.height - 24)) + 'px';
        } else if (chosen.arrow === 'right') {
            tourArrow.style.right = -arrowOffset + 'px';
            const arrowTop = targetRect.top + targetRect.height / 2 - chosen.top - arrowOffset;
            tourArrow.style.top = Math.max(10, Math.min(arrowTop, tooltipRect.height - 24)) + 'px';
        } else if (chosen.arrow === 'top') {
            tourArrow.style.top = -arrowOffset + 'px';
            const arrowLeft = targetRect.left + targetRect.width / 2 - chosen.left - arrowOffset;
            tourArrow.style.left = Math.max(10, Math.min(arrowLeft, tooltipRect.width - 24)) + 'px';
        } else if (chosen.arrow === 'bottom') {
            tourArrow.style.bottom = -arrowOffset + 'px';
            const arrowLeft = targetRect.left + targetRect.width / 2 - chosen.left - arrowOffset;
            tourArrow.style.left = Math.max(10, Math.min(arrowLeft, tooltipRect.width - 24)) + 'px';
        }
    }
}

function renderTourDots() {
    if (!tourProgressDots) return;
    tourProgressDots.innerHTML = TOUR_STEPS.map((_, i) =>
        `<div class="tour-dot" data-dot-index="${i}"></div>`
    ).join('');
}

function updateTourDots() {
    if (!tourProgressDots) return;
    tourProgressDots.querySelectorAll('.tour-dot').forEach((dot, i) => {
        dot.classList.toggle('active', i === tourState.currentIndex);
    });
}

// --- Event listeners ---
if (tourNextBtn) {
    tourNextBtn.addEventListener('click', () => {
        if (tourState.currentIndex >= TOUR_STEPS.length - 1) {
            endTour(true);
            showToast('Tur selesai! 🎉', 'success');
        } else {
            goToTourStep(tourState.currentIndex + 1);
        }
    });
}

if (tourPrevBtn) {
    tourPrevBtn.addEventListener('click', () => {
        if (tourState.currentIndex > 0) {
            goToTourStep(tourState.currentIndex - 1);
        }
    });
}

if (tourSkipBtn) {
    tourSkipBtn.addEventListener('click', () => {
        endTour(true);
        showToast('Tur dilewati. Buka lagi dari Pengaturan → Panduan.', 'info');
    });
}

if (tourCloseBtn) {
    tourCloseBtn.addEventListener('click', () => {
        endTour(true);
    });
}

if (startTourBtn) {
    startTourBtn.addEventListener('click', () => {
        closeSettings();
        setTimeout(() => startTour(true), 250);
    });
}

// ESC untuk tutup tour
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (complianceAddRowModalOverlay && complianceAddRowModalOverlay.style.display === 'flex') 
            { closeComplianceAddRowModal(); return; }
        if (tourState.active) {
            endTour(true);
            e.stopPropagation();
        }
    }
});

// Auto-trigger saat pertama kali buka
setTimeout(() => {
    // Datang lewat tautan langsung ke halaman tertentu → jangan tutupi dengan tur.
    const deepLinked = /^#\/[\w-]+$/.test(location.hash);
    if (!localStorage.getItem(TOUR_STORAGE_KEY) && !state.isAnalyzing && !deepLinked) {
        startTour(false);
    }
}, 1200);
