/**
 * Editor prompt AI (preset, blok Core/Locked/User Instructions, preview).
 */

import {
    $,
    $$,
    escapeAttr,
    escapeHtml,
    showToast,
} from './core.js';

    // ====== PROMPT EDITOR REFS ======
const promptWarningBanner = $('#promptWarningBanner');
const promptToolTabs = $$('.prompt-tool-tab');
const promptLoading = $('#promptLoading');
const promptEditorContent = $('#promptEditorContent');
const corePromptTextarea = $('#corePromptTextarea');
const coreCustomBadge = $('#coreCustomBadge');
const resetCoreBtn = $('#resetCoreBtn');
const lockedToggleBtn = $('#lockedToggleBtn');
const lockedToggleArrow = $('#lockedToggleArrow');
const lockedBody = $('#lockedBody');
const lockedPromptPre = $('#lockedPromptPre');
const userInstructionsTextarea = $('#userInstructionsTextarea');
const resetUserBtn = $('#resetUserBtn');
const previewPromptBtn = $('#previewPromptBtn');
const resetAllPromptBtn = $('#resetAllPromptBtn');
const savePromptBtn = $('#savePromptBtn');
const presetSelect = $('#presetSelect');
const applyPresetBtn = $('#applyPresetBtn');
export const promptPreviewOverlay = $('#promptPreviewOverlay');
const promptPreviewClose = $('#promptPreviewClose');
const promptPreviewCloseBtn = $('#promptPreviewCloseBtn');
const promptPreviewPre = $('#promptPreviewPre');
const promptPreviewStats = $('#promptPreviewStats');

    // ============================================================
// PROMPT EDITOR
// ============================================================

const PROMPT_WARNING_KEY = 'rta_prompt_warning_seen';

function shouldShowPromptWarning() {
    return !localStorage.getItem(PROMPT_WARNING_KEY);
}

function dismissPromptWarningForever() {
    localStorage.setItem(PROMPT_WARNING_KEY, '1');
}

export async function loadPromptStatus(tool) {
    const targetTool = tool || promptState.currentTool;
    promptState.currentTool = targetTool;
    promptState.loading = true;
    promptState.dirty = false;

    // Update tab active state
    promptToolTabs.forEach(tab => {
        tab.classList.toggle('active', tab.dataset.promptTool === targetTool);
    });

    if (promptLoading) promptLoading.style.display = 'flex';
    if (promptEditorContent) promptEditorContent.style.display = 'none';
    loadPromptPresets(targetTool);

    try {
        const res = await fetch(`/api/prompts/${targetTool}`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        promptState.status = data;
        renderPromptEditor(data);
    } catch (err) {
        showToast(`Gagal memuat prompt: ${err.message}`, 'error');
        if (promptLoading) {
            promptLoading.innerHTML = `
                    <i class="fas fa-exclamation-circle" style="color:var(--warn);"></i>
                    Gagal memuat prompt. Coba lagi.
                `;
        }
    } finally {
        promptState.loading = false;
    }
}

    async function loadPromptPresets(tool) {
    try {
        const res = await fetch(`/api/prompts/${tool}/presets`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        promptState.presets = data.presets || [];

        // Isi dropdown
        if (presetSelect) {
            presetSelect.innerHTML = `<option value="">— Pilih Preset —</option>` +
                promptState.presets.map(p =>
                    `<option value="${escapeAttr(p.id)}" title="${escapeAttr(p.description)}">${escapeHtml(p.name)}</option>`
                ).join('');
            presetSelect.value = '';
        }
        if (applyPresetBtn) applyPresetBtn.disabled = true;
    } catch (err) {
        console.warn('Gagal memuat preset:', err);
        if (presetSelect) {
            presetSelect.innerHTML = `<option value="">— Gagal memuat —</option>`;
        }
    }
}

function renderPromptEditor(data) {
    if (promptLoading) promptLoading.style.display = 'none';
    if (promptEditorContent) promptEditorContent.style.display = 'flex';

    // Warning banner
    if (promptWarningBanner) {
        if (shouldShowPromptWarning()) {
            promptWarningBanner.style.display = 'flex';
            // Auto-hide after 10s + set flag
            setTimeout(() => {
                promptWarningBanner.style.display = 'none';
                dismissPromptWarningForever();
            }, 10000);
        } else {
            promptWarningBanner.style.display = 'none';
        }
    }

    // Blok 1: Core
    if (corePromptTextarea) {
        // Kalau user belum pernah edit, tampilkan default.
        // Kalau sudah edit, tampilkan override.
        corePromptTextarea.value = data.core_is_customized
            ? (data.core_override || '')
            : (data.default_core || '');
        corePromptTextarea.dataset.defaultCore = data.default_core || '';
        corePromptTextarea.dataset.isCustomized = data.core_is_customized ? '1' : '0';
    }

    if (coreCustomBadge) {
        coreCustomBadge.style.display = data.core_is_customized ? 'inline-block' : 'none';
    }

    // Blok 2: Locked
    if (lockedPromptPre) {
        lockedPromptPre.textContent = data.locked_block || '';
    }

    // Blok 3: User Instructions
    if (userInstructionsTextarea) {
        userInstructionsTextarea.value = data.user_instructions || '';
    }

    // Reset dirty state
    promptState.dirty = false;
    if (savePromptBtn) savePromptBtn.disabled = true;

    // Reset accordion state
    if (lockedBody) lockedBody.style.display = 'none';
    if (lockedToggleArrow) lockedToggleArrow.classList.remove('open');
    if (presetSelect) presetSelect.value = '';
    if (applyPresetBtn) applyPresetBtn.disabled = true;
    promptState.presetApplied = false;
}

function markPromptDirty() {
    if (!promptState.dirty) {
        promptState.dirty = true;
        if (savePromptBtn) savePromptBtn.disabled = false;
    }
}

// Tab switcher
promptToolTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        const tool = tab.dataset.promptTool;
        if (tool === promptState.currentTool) return;

        // Cek dirty state sebelum switch
        if (promptState.dirty) {
            if (!confirm('Ada perubahan yang belum disimpan. Yakin pindah tab? Perubahan akan hilang.')) {
                return;
            }
        }
        loadPromptStatus(tool);
    });
});

    // Preset dropdown — enable tombol "Terapkan"
if (presetSelect) {
    presetSelect.addEventListener('change', () => {
        if (applyPresetBtn) applyPresetBtn.disabled = !presetSelect.value;
    });
}

// Apply preset
if (applyPresetBtn) {
    applyPresetBtn.addEventListener('click', () => {
        const presetId = presetSelect ? presetSelect.value : '';
        if (!presetId) return;

        const preset = promptState.presets.find(p => p.id === presetId);
        if (!preset) {
            showToast('Preset tidak ditemukan.', 'error');
            return;
        }

        // Cek apakah core textarea sudah diedit
        if (!corePromptTextarea) return;
        const currentValue = corePromptTextarea.value.trim();
        const defaultValue = (corePromptTextarea.dataset.defaultCore || '').trim();
        const hasEdits = currentValue !== defaultValue;

        if (hasEdits) {
            const ok = confirm(
                `Terapkan preset "${preset.name}"?\n\n` +
                `Ini akan MENGGANTI isi "Prompt Inti" saat ini.\n` +
                `Perubahan Anda yang belum disimpan akan hilang.`
            );
            if (!ok) return;
        }

        // Apply
        corePromptTextarea.value = preset.core_text;
        markPromptDirty();
        promptState.presetApplied = true;

        // Update badge: preset ini mungkin = default atau custom
        if (coreCustomBadge) {
            // Tampilkan badge "Diubah" kalau preset bukan default
            const isDefault = preset.core_text.trim() === defaultValue;
            coreCustomBadge.style.display = isDefault ? 'none' : 'inline-block';
            corePromptTextarea.dataset.isCustomized = isDefault ? '0' : '1';
        }

        showToast(`Preset "${preset.name}" diterapkan. Klik Simpan untuk menerapkan.`, 'success');
    });
}

// Core textarea → track dirty
if (corePromptTextarea) {
    corePromptTextarea.addEventListener('input', () => {
        markPromptDirty();
        // Update badge preview (kalau user ubah isi ≠ default)
        const currentValue = corePromptTextarea.value;
        const defaultValue = corePromptTextarea.dataset.defaultCore || '';
        const isDifferent = currentValue.trim() !== defaultValue.trim();
        if (coreCustomBadge) {
            // Tampilkan badge "Diubah" kalau beda dari default
            // (belum tentu disimpan, tapi indikatif)
            if (isDifferent) coreCustomBadge.style.display = 'inline-block';
            else if (corePromptTextarea.dataset.isCustomized !== '1') {
                coreCustomBadge.style.display = 'none';
            }
        }
    });
}

// User instructions textarea → track dirty
if (userInstructionsTextarea) {
    userInstructionsTextarea.addEventListener('input', markPromptDirty);
}

// Locked accordion toggle
if (lockedToggleBtn) {
    lockedToggleBtn.addEventListener('click', () => {
        const isOpen = lockedBody && lockedBody.style.display !== 'none';
        if (lockedBody) lockedBody.style.display = isOpen ? 'none' : 'block';
        if (lockedToggleArrow) lockedToggleArrow.classList.toggle('open', !isOpen);
    });
}

// Reset Core
if (resetCoreBtn) {
    resetCoreBtn.addEventListener('click', () => {
        if (!confirm('Reset Prompt Inti ke default? Perubahan Anda akan hilang.')) return;
        if (!corePromptTextarea) return;
        const defaultCore = corePromptTextarea.dataset.defaultCore || '';
        corePromptTextarea.value = defaultCore;
        corePromptTextarea.dataset.isCustomized = '0';
        if (coreCustomBadge) coreCustomBadge.style.display = 'none';
        markPromptDirty();
        showToast('Prompt inti direset ke default. Klik Simpan untuk menerapkan.', 'info');
    });
}

// Reset User Instructions
if (resetUserBtn) {
    resetUserBtn.addEventListener('click', () => {
        if (!userInstructionsTextarea) return;
        if (!userInstructionsTextarea.value.trim()) {
            showToast('Instruksi tambahan sudah kosong.', 'info');
            return;
        }
        if (!confirm('Kosongkan Instruksi Tambahan?')) return;
        userInstructionsTextarea.value = '';
        markPromptDirty();
        showToast('Instruksi tambahan dikosongkan. Klik Simpan untuk menerapkan.', 'info');
    });
}

// Reset All
if (resetAllPromptBtn) {
    resetAllPromptBtn.addEventListener('click', async () => {
        if (!confirm('Reset SEMUA prompt ke default? Perubahan Anda akan hilang.')) return;

        resetAllPromptBtn.disabled = true;
        resetAllPromptBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Reset...';

        try {
            const res = await fetch(`/api/prompts/${promptState.currentTool}/reset`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ section: 'all' }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            promptState.status = data;
            renderPromptEditor(data);
            showToast('Semua prompt direset ke default.', 'success');
        } catch (err) {
            showToast(`Gagal reset: ${err.message}`, 'error');
        } finally {
            resetAllPromptBtn.disabled = false;
            resetAllPromptBtn.innerHTML = '<i class="fas fa-rotate-left"></i> Reset Semua';
        }
    });
}

// Save
if (savePromptBtn) {
    savePromptBtn.addEventListener('click', async () => {
        if (!corePromptTextarea || !userInstructionsTextarea) return;

        const currentValue = corePromptTextarea.value.trim();
        const defaultValue = (corePromptTextarea.dataset.defaultCore || '').trim();
        const isCustomized = currentValue !== defaultValue;

        // Validasi: kalau user kosongkan, tolak
        if (currentValue.length < 50 && isCustomized) {
            showToast('Prompt inti terlalu pendek. Minimal 50 karakter, atau klik Reset untuk pakai default.', 'error');
            return;
        }

        const payload = {
            // Kalau user set ke default (tidak diedit), kirim null → tidak ada override
            core_override: isCustomized ? currentValue : '',
            user_instructions: userInstructionsTextarea.value.trim(),
        };

        savePromptBtn.disabled = true;
        savePromptBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';

        try {
            const res = await fetch(`/api/prompts/${promptState.currentTool}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            promptState.status = data;
            promptState.dirty = false;
            renderPromptEditor(data);
            showToast('Prompt tersimpan.', 'success');
        } catch (err) {
            showToast(`Gagal menyimpan: ${err.message}`, 'error');
            savePromptBtn.disabled = false;
        } finally {
            savePromptBtn.innerHTML = '<i class="fas fa-floppy-disk"></i> Simpan';
        }
    });
}

// Preview
if (previewPromptBtn) {
    previewPromptBtn.addEventListener('click', async () => {
        previewPromptBtn.disabled = true;
        previewPromptBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Memuat...';

        try {
            const res = await fetch(`/api/prompts/${promptState.currentTool}/preview`, {
                method: 'POST',
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            if (promptPreviewPre) promptPreviewPre.textContent = data.final_prompt;
            if (promptPreviewStats) {
                const chars = data.total_chars.toLocaleString('id-ID');
                const tokens = Math.round(data.total_chars / 4).toLocaleString('id-ID');
                promptPreviewStats.textContent = `~${chars} karakter • ~${tokens} token`;
            }
            if (promptPreviewOverlay) promptPreviewOverlay.style.display = 'flex';
        } catch (err) {
            showToast(`Gagal memuat preview: ${err.message}`, 'error');
        } finally {
            previewPromptBtn.disabled = false;
            previewPromptBtn.innerHTML = '<i class="fas fa-eye"></i> Preview Prompt Final';
        }
    });
}

// Preview modal close handlers
export function closePromptPreview() {
    if (promptPreviewOverlay) promptPreviewOverlay.style.display = 'none';
}
if (promptPreviewClose) promptPreviewClose.addEventListener('click', closePromptPreview);
if (promptPreviewCloseBtn) promptPreviewCloseBtn.addEventListener('click', closePromptPreview);
if (promptPreviewOverlay) {
    promptPreviewOverlay.addEventListener('click', (e) => {
        if (e.target === promptPreviewOverlay) closePromptPreview();
    });
}

    // ====== PROMPT EDITOR STATE ======
const promptState = {
    currentTool: 'regulation_audit',
    status: null,
    dirty: false,
    loading: false,
    presets: [],              // cache preset dari server
    presetApplied: false,     // true kalau user baru apply preset
};
