/**
 * Entry point: memuat semua modul (urutan = urutan fitur di UI) lalu
 * menjalankan inisialisasi awal.
 */

import { applyTheme, state, switchPage } from './core.js';
import { loadSettings } from './settings.js';
import { setStatus, updateFileNameDisplay } from './audit.js';
import { setGapStatus, updateGapFileNameDisplay } from './gap.js';

import './core.js';
import './jobs.js';
import './history.js';
import './settings.js';
import './prompt-editor.js';
import './audit.js';
import './gap.js';
import './compliance.js';
import './regulation-db.js';
import './tour.js';
import './chat.js';
import './home.js';
import './compare.js';
import './search.js';
import './shortcuts.js';

// ============================================================
// INITIAL STATE
// ============================================================
setStatus('Menunggu file...', false);
setGapStatus('Menunggu file...', false);
updateFileNameDisplay();
updateGapFileNameDisplay();

// Apply theme — dipanggil di sini supaya chartContainer dkk sudah dideklarasi
applyTheme(state.theme);

// Restore halaman terakhir
const lastPage = localStorage.getItem('rta_current_page') || 'home';
switchPage(lastPage);

loadSettings();

console.log('%c🚀 Regulation to IT Audit Assistant v2', 'color:#1E2761;font-weight:bold;font-size:13px');
console.log('%cTools: Regulation to Audit | Gap Analysis', 'color:#64748B');
console.log('%cCtrl+K cari • Esc tutup modal/panel', 'color:#64748B');
