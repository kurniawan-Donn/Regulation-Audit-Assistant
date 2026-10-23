/**
 * Panel Pengaturan: model & API key, uji koneksi, tema, diagnostik, tentang.
 */

import {
    $,
    $$,
    applyTheme,
    escapeAttr,
    escapeHtml,
    showToast,
    state,
} from './core.js';
import { renderHistory } from './history.js';
import { loadPromptStatus } from './prompt-editor.js';


document.querySelectorAll('input[name="theme"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
        if (e.target.checked) {
            applyTheme(e.target.value);
            saveSettingsPartial({ theme: e.target.value });
        }
    });
});

const settingsToggle = $('#settingsToggle');
export const settingsPanel = $('#settingsPanel');
const settingsOverlay = $('#settingsOverlay');
const settingsCloseBtns = $$('.settings-close');
const settingsBack = $('#settingsBack');
const settingsTitleText = $('#settingsTitleText');
const settingsSubtitle = $('#settingsSubtitle');
const settingsViews = $$('.settings-view');
const settingsNavItems = $$('.settings-menu li');
const aiStatusCard = $('#aiStatusCard');
const aiStatusTitle = $('#aiStatusTitle');
const aiStatusText = $('#aiStatusText');
const apiKeyInput = $('#apiKeyInput');
const toggleApiKey = $('#toggleApiKey');
const toggleApiKeyIcon = $('#toggleApiKeyIcon');
const apiKeyHint = $('#apiKeyHint');
const modelSelect = $('#modelSelect');
const modelCustom = $('#modelCustom');
const maxTokensInput = $('#maxTokensInput');
const rateLimitInput = $('#rateLimitInput');
const batchSizeInput = $('#batchSizeInput');
const testConnectionBtn = $('#testConnectionBtn');
const saveSettingsBtn = $('#saveSettingsBtn');
const connectionStatus = $('#connectionStatus');
const diagnosticsGrid = $('#diagnosticsGrid');
const refreshDiagnosticsBtn = $('#refreshDiagnosticsBtn');
const aboutVersion = $('#aboutVersion');
const aboutAppVersion = $('#aboutAppVersion');
const aboutEnv = $('#aboutEnv');
const aboutModel = $('#aboutModel');

// ====== SETTINGS PANEL ======
// Desktop: navigasi bagian selalu tampil di kiri, konten di kanan.
// Ponsel: menu dulu ("menu"), lalu satu bagian layar penuh dengan tombol kembali.
const SETTINGS_VIEWS = {
    'model-ai': ['Model & AI', 'Kunci API, model Gemini, dan parameter pemrosesan.'],
    'prompt-editor': ['Prompt AI', 'Atur cara AI menyusun hasil untuk tiap alat.'],
    'tampilan': ['Tampilan', 'Pilih tema yang paling nyaman untuk mata Anda.'],
    'riwayat': ['Riwayat Analisis', 'Buka kembali hasil analisis yang tersimpan di browser ini.'],
    'diagnostik': ['Diagnostik', 'Status server, koneksi AI, dan penyimpanan.'],
    'panduan': ['Panduan', 'Alur kerja yang disarankan dan pintasan keyboard.'],
    'tentang': ['Tentang', 'Versi dan informasi aplikasi.'],
};
const desktopQuery = window.matchMedia('(min-width: 769px)');
let lastSettingsView = 'model-ai';

export function openSettings() {
    if (!settingsPanel) return;
    settingsPanel.classList.add('open');
    settingsOverlay.classList.add('visible');
    switchSettingsView(desktopQuery.matches ? lastSettingsView : 'menu');
    loadSettings();
}

export function closeSettings() {
    if (!settingsPanel) return;
    settingsPanel.classList.remove('open');
    settingsOverlay.classList.remove('visible');
}

export function switchSettingsView(viewName) {
    if (viewName === 'menu' && desktopQuery.matches) viewName = lastSettingsView;
    const atMenu = viewName === 'menu' || !SETTINGS_VIEWS[viewName];
    settingsPanel?.classList.toggle('at-menu', atMenu);
    settingsNavItems.forEach(li => li.classList.toggle('active', !atMenu && li.dataset.target === viewName));
    if (atMenu) return;

    lastSettingsView = viewName;
    settingsViews.forEach(v => {
        v.style.display = v.dataset.view === viewName ? '' : 'none';
    });
    const [title, subtitle] = SETTINGS_VIEWS[viewName];
    if (settingsTitleText) settingsTitleText.textContent = title;
    if (settingsSubtitle) settingsSubtitle.textContent = subtitle;
    if (viewName === 'riwayat') renderHistory();
    if (viewName === 'diagnostik') loadDiagnostics();
    if (viewName === 'tentang') loadAbout();
    if (viewName === 'prompt-editor') loadPromptStatus();
}

if (settingsToggle) settingsToggle.addEventListener('click', openSettings);
settingsCloseBtns.forEach(btn => btn.addEventListener('click', closeSettings));
if (settingsOverlay) settingsOverlay.addEventListener('click', closeSettings);
if (settingsBack) settingsBack.addEventListener('click', () => switchSettingsView('menu'));

settingsNavItems.forEach(li => {
    const open = () => { if (li.dataset.target) switchSettingsView(li.dataset.target); };
    li.addEventListener('click', open);
    li.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            open();
        }
    });
});

// Layar berubah lebar saat panel terbuka: jangan tinggalkan panel di keadaan menu kosong.
desktopQuery.addEventListener('change', () => {
    if (settingsPanel?.classList.contains('open') && settingsPanel.classList.contains('at-menu')) {
        switchSettingsView(lastSettingsView);
    }
});

export async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        state.settings = data;
        renderSettingsForm(data);
    } catch (err) {
        console.warn('Gagal memuat settings:', err);
    }
}

function renderAiStatus(data) {
    if (!aiStatusCard) return;
    const ready = !!data.gemini_api_key_set;
    aiStatusCard.classList.toggle('is-ready', ready);
    aiStatusCard.classList.toggle('is-missing', !ready);
    aiStatusCard.querySelector('.ai-status-icon').innerHTML =
        `<i class="fas ${ready ? 'fa-circle-check' : 'fa-triangle-exclamation'}"></i>`;
    aiStatusTitle.textContent = ready ? 'AI siap dipakai' : 'API key belum diisi';
    aiStatusText.textContent = ready
        ? `Model aktif: ${data.gemini_model || '-'} · gunakan Test Koneksi untuk memastikan kuota tersedia.`
        : 'Masukkan API key Gemini di bawah agar fitur analisis dan Tanya Regulasi bisa berjalan.';
}

// Mode Demo: server menolak perubahan pengaturan; kunci form & tampilkan spanduk.
function applyDemoMode(data) {
    const demo = !!data.demo_mode;
    document.documentElement.classList.toggle('is-demo', demo);
    const banner = $('#demoBanner');
    if (banner) banner.hidden = !demo;
    [apiKeyInput, toggleApiKey, modelSelect, modelCustom, maxTokensInput, rateLimitInput,
        batchSizeInput, testConnectionBtn, saveSettingsBtn].forEach(el => { if (el) el.disabled = demo; });
    if (demo && aiStatusText) {
        aiStatusText.textContent = 'Mode Demo — pengaturan AI dikunci oleh pemilik demo.';
    }
}

function renderSettingsForm(data) {
    renderAiStatus(data);
    applyDemoMode(data);
    if (!apiKeyHint) return;
    if (data.gemini_api_key_set) {
        apiKeyHint.className = 'settings-hint ok';
        apiKeyHint.innerHTML = `
                <i class="fas fa-shield-halved"></i>
                API key tersimpan: <code>${escapeHtml(data.gemini_api_key_masked || '****')}</code>.
                Ketik key baru untuk mengganti, atau kosongkan untuk tidak mengubah.
            `;
        if (apiKeyInput) apiKeyInput.placeholder = data.gemini_api_key_masked || 'AQ.xxxx...xxxx';
    } else {
        apiKeyHint.className = 'settings-hint warn';
        apiKeyHint.innerHTML = `
                <i class="fas fa-triangle-exclamation"></i>
                Belum ada API key tersimpan. Masukkan API key Gemini untuk mulai analisis.
            `;
        if (apiKeyInput) apiKeyInput.placeholder = 'AQ.xxxxxxxxxxxxxxxxxxxx';
    }
    if (apiKeyInput) apiKeyInput.value = '';

    const presetModels = data.preset_models || [];
    const currentModel = data.gemini_model || '';
    const isCustom = currentModel && !presetModels.includes(currentModel);

    if (modelSelect) {
        modelSelect.innerHTML = presetModels.map(m =>
            `<option value="${escapeAttr(m)}">${escapeHtml(m)}</option>`
        ).join('') + `<option value="__custom__">— Kustom (ketik manual) —</option>`;

        if (isCustom) {
            modelSelect.value = '__custom__';
            if (modelCustom) {
                modelCustom.style.display = 'block';
                modelCustom.value = currentModel;
            }
        } else if (currentModel) {
            modelSelect.value = currentModel;
            if (modelCustom) modelCustom.style.display = 'none';
        } else if (presetModels.length > 0) {
            modelSelect.value = presetModels[0];
        }
    }

    if (maxTokensInput) maxTokensInput.value = data.gemini_max_output_tokens || 8192;
    if (rateLimitInput) rateLimitInput.value = data.gemini_min_seconds_between_requests || 4.5;
    if (batchSizeInput) batchSizeInput.value = data.max_chars_per_batch || 6000;

    if (saveSettingsBtn) saveSettingsBtn.disabled = true;
    if (connectionStatus) connectionStatus.style.display = 'none';
}

[apiKeyInput, modelCustom, maxTokensInput, rateLimitInput, batchSizeInput].forEach(el => {
    if (!el) return;
    el.addEventListener('input', () => { if (saveSettingsBtn) saveSettingsBtn.disabled = false; });
});

if (modelSelect) {
    modelSelect.addEventListener('change', () => {
        if (modelSelect.value === '__custom__') {
            if (modelCustom) {
                modelCustom.style.display = 'block';
                modelCustom.focus();
            }
        } else {
            if (modelCustom) modelCustom.style.display = 'none';
        }
        if (saveSettingsBtn) saveSettingsBtn.disabled = false;
    });
}

if (toggleApiKey) {
    toggleApiKey.addEventListener('click', () => {
        if (!apiKeyInput) return;
        const isPassword = apiKeyInput.type === 'password';
        apiKeyInput.type = isPassword ? 'text' : 'password';
        if (toggleApiKeyIcon) {
            toggleApiKeyIcon.className = isPassword ? 'fas fa-eye-slash' : 'fas fa-eye';
        }
    });
}

if (testConnectionBtn) {
    testConnectionBtn.addEventListener('click', async () => {
        if (connectionStatus) connectionStatus.style.display = 'none';
        testConnectionBtn.disabled = true;
        testConnectionBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menguji...';

        const payload = {};
        const newKey = apiKeyInput ? apiKeyInput.value.trim() : '';
        if (newKey) payload.api_key = newKey;

        const modelValue = modelSelect && modelSelect.value === '__custom__'
            ? (modelCustom ? modelCustom.value.trim() : '')
            : (modelSelect ? modelSelect.value : '');
        if (modelValue) payload.model = modelValue;

        try {
            const res = await fetch('/api/settings/test-connection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json();

            if (connectionStatus) {
                connectionStatus.style.display = 'flex';
                if (data.ok) {
                    connectionStatus.className = 'connection-status ok';
                    connectionStatus.innerHTML = `
                            <i class="fas fa-check-circle"></i>
                            <div>
                                <strong>Koneksi berhasil!</strong><br>
                                Model: ${escapeHtml(data.model_tested)} • Latency: ${data.latency_ms}ms<br>
                                ${escapeHtml(data.message)}
                            </div>
                        `;
                } else {
                    connectionStatus.className = 'connection-status err';
                    connectionStatus.innerHTML = `
                            <i class="fas fa-exclamation-circle"></i>
                            <div>
                                <strong>Koneksi gagal.</strong><br>
                                ${escapeHtml(data.message)}
                            </div>
                        `;
                }
            }
        } catch (err) {
            if (connectionStatus) {
                connectionStatus.style.display = 'flex';
                connectionStatus.className = 'connection-status err';
                connectionStatus.innerHTML = `
                        <i class="fas fa-exclamation-circle"></i>
                        <div>Gagal terhubung ke server: ${escapeHtml(err.message)}</div>
                    `;
            }
        } finally {
            testConnectionBtn.disabled = false;
            testConnectionBtn.innerHTML = '<i class="fas fa-plug"></i> Test Koneksi';
        }
    });
}

if (saveSettingsBtn) {
    saveSettingsBtn.addEventListener('click', async () => {
        saveSettingsBtn.disabled = true;
        saveSettingsBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';

        const payload = {};
        const newKey = apiKeyInput ? apiKeyInput.value.trim() : '';
        if (newKey) payload.gemini_api_key = newKey;

        const modelValue = modelSelect && modelSelect.value === '__custom__'
            ? (modelCustom ? modelCustom.value.trim() : '')
            : (modelSelect ? modelSelect.value : '');
        if (modelValue) payload.gemini_model = modelValue;

        const maxTok = parseInt(maxTokensInput ? maxTokensInput.value : '', 10);
        if (!isNaN(maxTok) && maxTok > 0) payload.gemini_max_output_tokens = maxTok;

        const rateLim = parseFloat(rateLimitInput ? rateLimitInput.value : '');
        if (!isNaN(rateLim) && rateLim >= 0) payload.gemini_min_seconds_between_requests = rateLim;

        const batchSz = parseInt(batchSizeInput ? batchSizeInput.value : '', 10);
        if (!isNaN(batchSz) && batchSz > 0) payload.max_chars_per_batch = batchSz;

        try {
            const res = await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            state.settings = data;
            renderSettingsForm(data);
            showToast('Pengaturan tersimpan.', 'success');
        } catch (err) {
            showToast(`Gagal menyimpan: ${err.message}`, 'error');
        } finally {
            saveSettingsBtn.innerHTML = '<i class="fas fa-floppy-disk"></i> Simpan';
        }
    });
}

async function saveSettingsPartial(partial) {
    try {
        await fetch('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(partial),
        });
    } catch (err) {
        console.warn('Silent save failed:', err);
    }
}

// ====== DIAGNOSTIK ======
async function loadDiagnostics() {
    if (!diagnosticsGrid) return;
    diagnosticsGrid.innerHTML = `
            <div class="diag-loading">
                <i class="fas fa-spinner fa-spin"></i> Memuat diagnostik...
            </div>
        `;
    try {
        const res = await fetch('/api/diagnostics');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderDiagnostics(data);
    } catch (err) {
        diagnosticsGrid.innerHTML = `
                <div class="diag-item">
                    <span><i class="fas fa-exclamation-circle"></i> Error</span>
                    <span class="diag-status err">${escapeHtml(err.message)}</span>
                </div>
            `;
    }
}

function renderDiagnostics(data) {
    if (!diagnosticsGrid) return;
    const item = (label, icon, value, status) => `
            <div class="diag-item${status ? (status.ok ? ' is-ok' : ' is-err') : ''}">
                <span class="diag-icon"><i class="fas ${icon}"></i></span>
                <span class="diag-text">
                    <small>${label}</small>
                    ${status ? `<span class="diag-status ${status.ok ? 'ok' : 'err'}">${escapeHtml(status.text)}</span>` : `<strong>${escapeHtml(value)}</strong>`}
                </span>
            </div>
        `;
    diagnosticsGrid.innerHTML = [
        item('Status Server', 'fa-server', '', { ok: data.server_ok, text: data.server_ok ? 'Online' : 'Offline' }),
        item('Koneksi AI', 'fa-robot', '', { ok: data.ai_ok, text: data.ai_message }),
        item('Model Aktif', 'fa-microchip', data.model_name),
        item('Preview Cache', 'fa-database', `${data.cache_previews_count} file • ${data.cache_size_mb} MB`),
        item('Hasil Tersimpan', 'fa-file-lines', `${data.outputs_count} file`),
        item('Environment', 'fa-tag', data.app_env),
        item('Versi Aplikasi', 'fa-code-branch', data.app_version),
    ].join('');
}
if (refreshDiagnosticsBtn) refreshDiagnosticsBtn.addEventListener('click', loadDiagnostics);

// ====== TENTANG ======
async function loadAbout() {
    try {
        const res = await fetch('/api/diagnostics');
        if (!res.ok) return;
        const data = await res.json();
        if (aboutVersion) aboutVersion.textContent = data.app_version;
        if (aboutAppVersion) aboutAppVersion.textContent = data.app_version;
        if (aboutEnv) aboutEnv.textContent = data.app_env;
        if (aboutModel) aboutModel.textContent = data.model_name;
    } catch (err) {
        console.warn('About load failed:', err);
    }
}
