(function() {
    // ====== STATE ======
    const state = {
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

    const treeState = {
        previewId: null,
        filename: '',
        tree: [],
        expanded: new Set(),
        selectedLeaves: new Set(),
        totalChunks: 0,
        isReAnalyze: false,
    };

    // ====== DOM HELPERS ======
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    // ====== SIDEBAR / ROUTING ======
    const sidebar = $('#sidebar');
    const sidebarOverlay = $('#sidebarOverlay');
    const mobileMenuBtn = $('#mobileMenuBtn');
    const mobileHeaderTitle = $('#mobileHeaderTitle');
    const sidebarItems = $$('.sidebar-item');
    const pageRegulationAudit = $('#page-regulation-audit');
    const pageGapAnalysis = $('#page-gap-analysis');
    const pageComplianceReview = $('#page-compliance-review');
    const pageRegulationDb = $('#page-regulation-db');
    const pageSearch = $('#page-search');

        const PAGE_TITLES = {
        'regulation-audit': 'Regulation to Audit',
        'gap-analysis': 'Gap Analysis',
        'compliance-review': 'Compliance Review',
        'regulation-db': 'Database Regulasi',
        'search': 'Cari Global',
    };

        function switchPage(pageName) {
        if (!PAGE_TITLES[pageName]) return;
        state.currentPage = pageName;

        if (pageRegulationAudit) {
            pageRegulationAudit.style.display = pageName === 'regulation-audit' ? '' : 'none';
        }
        if (pageGapAnalysis) {
            pageGapAnalysis.style.display = pageName === 'gap-analysis' ? '' : 'none';
        }
        if (pageComplianceReview) {
            pageComplianceReview.style.display = pageName === 'compliance-review' ? '' : 'none';
        }
        if (pageRegulationDb) {
            pageRegulationDb.style.display = pageName === 'regulation-db' ? '' : 'none';
        }
        if (pageSearch) {
            pageSearch.style.display = pageName === 'search' ? '' : 'none';
        }

        sidebarItems.forEach(item => {
            item.classList.toggle('active', item.dataset.page === pageName);
        });

        if (mobileHeaderTitle) {
            mobileHeaderTitle.textContent = PAGE_TITLES[pageName];
        }

        closeMobileSidebar();
        localStorage.setItem('rta_current_page', pageName);
        if (pageName === 'regulation-db') {
            loadRegulationDbPage();
        }
        if (pageName === 'compliance-review' && complianceModeState.current === 'database') {
            complianceModeState.dbLoaded = false;
        }
        if (pageName === 'search' && globalSearchInput) {
            setTimeout(() => globalSearchInput.focus(), 100);
        }
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

    function closeMobileSidebar() {
        if (sidebar) sidebar.classList.remove('open');
        if (sidebarOverlay) sidebarOverlay.classList.remove('visible');
    }

    if (mobileMenuBtn) mobileMenuBtn.addEventListener('click', openMobileSidebar);
    if (sidebarOverlay) sidebarOverlay.addEventListener('click', closeMobileSidebar);

    // ====== THEME ======
    function resolveTheme(pref) {
        if (pref === 'auto') {
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        return pref;
    }

    function applyTheme(pref) {
        state.theme = pref;
        localStorage.setItem('rta_theme', pref);
        const resolved = resolveTheme(pref);
        document.documentElement.setAttribute('data-theme', resolved);
        document.documentElement.setAttribute('data-theme-pref', pref);
        document.querySelectorAll('input[name="theme"]').forEach(r => {
            r.checked = r.value === pref;
        });
        updateDonutChart();
    }

    const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
    darkModeQuery.addEventListener('change', () => {
        if (state.theme === 'auto') applyTheme('auto');
    });

    // CATATAN: applyTheme(state.theme) TIDAK dipanggil di sini.
    // Panggilan dipindah ke bagian INITIAL STATE di paling bawah file,
    // karena updateDonutChart() butuh chartContainer yang dideklarasi
    // di blok Tool 1 (di bawah).

    document.querySelectorAll('input[name="theme"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            if (e.target.checked) {
                applyTheme(e.target.value);
                saveSettingsPartial({ theme: e.target.value });
            }
        });
    });

    // ====== HELPERS ======
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = String(text == null ? '' : text);
        return div.innerHTML;
    }

    function escapeAttr(text) {
        return String(text == null ? '' : text)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
    }

    function formatIdr(value) {
        if (value < 1) return '< Rp 1';
        if (value < 1000) return `Rp ${Math.round(value)}`;
        if (value < 1_000_000) return `Rp ${(value / 1000).toFixed(1)}rb`;
        return `Rp ${(value / 1_000_000).toFixed(2)}jt`;
    }

    function formatDuration(seconds) {
        if (seconds < 60) return `${seconds} detik`;
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return s > 0 ? `${m} menit ${s} detik` : `${m} menit`;
    }

    function renderMarkdownLite(text) {
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

    function showToast(message, type = 'info') {
        const icons = { success: 'fa-check-circle', error: 'fa-exclamation-circle', info: 'fa-info-circle' };
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `<i class="fas ${icons[type] || icons.info}"></i> <span>${escapeHtml(message)}</span>`;
        if (toastContainer) {
            toastContainer.appendChild(toast);
            setTimeout(() => toast.remove(), 4200);
        }
    }

    // ============================================================
    // ============ TOOL 1: REGULATION TO AUDIT ===================
    // ============================================================

    const form = $('#uploadForm');
    const statusEl = $('#status');
    const submitBtn = $('#submitBtn');
    const resultSection = $('#resultSection');
    const resultBody = $('#resultBody');
    const summaryRow = $('#summaryRow');
    const aspectsBox = $('#aspectsBox');
    const filterBadge = $('#filterBadge');
    const previewExpiredBanner = $('#previewExpiredBanner');
    const chunkErrorsBox = $('#chunkErrorsBox');
    const exportBtn = $('#exportBtn');
    const exportPdfBtn = $('#exportPdfBtn');
    const copyBtn = $('#copyBtn');
    const clearResultBtn = $('#clearResultBtn');
    const changeFilterBtn = $('#changeFilterBtn');
    const resetBtn = $('#resetBtn');
    const fileInput = $('#fileInput');
    const uploadZone = $('#uploadZone');
    const fileNameDisplay = $('#fileNameDisplay');
    const searchInput = $('#searchInput');
    const filterBtns = $$('.filter-btn');
    const emptyState = $('#emptyState');
    const progressContainer = $('#progressContainer');
    const progressBar = $('#progressBar');
    const progressText = $('#progressText');
    const chartContainer = $('#chartContainer');
    const donutChart = $('#donutChart');
    const donutInner = $('#donutInner');
    const chartLegend = $('#chartLegend');
    const progressBadge = $('#progressBadge');
    const statusFilterSelect = $('#statusFilter');
    const bulkToolbar = $('#bulkToolbar');
    const bulkCount = $('#bulkCount');
    const bulkStatusSelect = $('#bulkStatusSelect');
    const bulkDeleteBtn = $('#bulkDeleteBtn');
    const bulkClearBtn = $('#bulkClearBtn');
    const addRowBtn = $('#addRowBtn');
    const selectAllCheckbox = $('#selectAllCheckbox');

    const addRowModalOverlay = $('#addRowModalOverlay');
    const addRowModalClose = $('#addRowModalClose');
    const addRowCancelBtn = $('#addRowCancelBtn');
    const addRowSaveBtn = $('#addRowSaveBtn');
    const addRowReferensi = $('#addRowReferensi');
    const addRowAspek = $('#addRowAspek');
    const addRowStruktur = $('#addRowStruktur');
    const addRowKetentuan = $('#addRowKetentuan');
    const addRowPemeriksaan = $('#addRowPemeriksaan');
    const addRowMetode = $('#addRowMetode');
    const addRowBukti = $('#addRowBukti');
    const addRowCatatan = $('#addRowCatatan');

    const treeModalOverlay = $('#treeModalOverlay');
    const treeModalClose = $('#treeModalClose');
    const treeModalSub = $('#treeModalSub');
    const treeSelectAll = $('#treeSelectAll');
    const treeClearAll = $('#treeClearAll');
    const treeSelectedCount = $('#treeSelectedCount');
    const treeContainer = $('#treeContainer');
    const treeCancelBtn = $('#treeCancelBtn');
    const treeAnalyzeBtn = $('#treeAnalyzeBtn');
    const treeEstimate = $('#treeEstimate');

    const settingsToggle = $('#settingsToggle');
    const settingsPanel = $('#settingsPanel');
    const settingsOverlay = $('#settingsOverlay');
    const settingsClose = $('#settingsClose');
    const settingsBack = $('#settingsBack');
    const settingsTitleText = $('#settingsTitleText');
    const settingsViews = $$('.settings-view');
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
    const historyList = $('#historyList');
    const historyClearAll = $('#historyClearAll');
    const diagnosticsGrid = $('#diagnosticsGrid');
    const refreshDiagnosticsBtn = $('#refreshDiagnosticsBtn');
    const aboutVersion = $('#aboutVersion');
    const aboutAppVersion = $('#aboutAppVersion');
    const aboutEnv = $('#aboutEnv');
    const aboutModel = $('#aboutModel');

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
    const promptPreviewOverlay = $('#promptPreviewOverlay');
    const promptPreviewClose = $('#promptPreviewClose');
    const promptPreviewCloseBtn = $('#promptPreviewCloseBtn');
    const promptPreviewPre = $('#promptPreviewPre');
    const promptPreviewStats = $('#promptPreviewStats');

    // ====== PROGRESS HELPERS (Tool 1) ======
    function setStatus(text, isError) {
        if (!statusEl) return;
        statusEl.className = 'status-text';
        if (isError === true) {
            statusEl.classList.add('error');
            statusEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${escapeHtml(text)}`;
        } else if (isError === false) {
            statusEl.classList.add('success');
            statusEl.innerHTML = `<i class="fas fa-check-circle"></i> ${escapeHtml(text)}`;
        } else {
            statusEl.textContent = text;
        }
    }

    function setProgress(percent, text) {
        if (!progressContainer) return;
        progressContainer.style.display = 'block';
        progressBar.style.width = percent + '%';
        progressText.textContent = text || `${Math.round(percent)}%`;
        if (percent >= 100) {
            setTimeout(() => {
                progressContainer.style.display = 'none';
                progressText.textContent = '';
            }, 1500);
        }
    }

    function hideProgress() {
        if (!progressContainer) return;
        progressContainer.style.display = 'none';
        progressText.textContent = '';
        progressBar.style.width = '0%';
    }

    // ====== BACKGROUND JOBS ======
    // Analisis AI berjalan sebagai job di server: endpoint membalas 202 + job_id,
    // lalu kita poll /api/jobs/{id} untuk progres NYATA (per batch) sampai selesai.
    const JOB_POLL_MS = 1000;
    const JOB_MAX_POLL_FAILURES = 5;

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    async function readErrorDetail(res) {
        try {
            const body = await res.json();
            if (typeof body.detail === 'string') return body.detail;
            if (Array.isArray(body.detail)) return body.detail.map(d => d.msg).join('; ');
        } catch (_) { /* body bukan JSON */ }
        return `HTTP ${res.status}`;
    }

    function jobPercent(job) {
        if (job.status === 'queued' || !job.progress_total) return 3;
        return Math.max(3, Math.min(99, Math.round((job.progress_done / job.progress_total) * 100)));
    }

    function jobLabel(job) {
        if (job.status === 'queued') {
            return job.queue_position > 1
                ? `Menunggu antrean (posisi ${job.queue_position})...`
                : 'Menunggu giliran...';
        }
        return job.message || 'Memproses...';
    }

    function createJobCancelButton(jobId) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-ghost btn-sm job-cancel-btn';
        btn.innerHTML = '<i class="fas fa-stop"></i> Batalkan';
        btn.addEventListener('click', async () => {
            if (!confirm('Batalkan proses ini? Batch yang sudah selesai tetap disimpan sebagai hasil parsial (jika ada).')) return;
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Membatalkan...';
            try {
                await fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
            } catch (_) { /* polling akan tetap melaporkan status akhir */ }
        });
        return btn;
    }

    /**
     * Jalankan endpoint berbasis job dan tunggu sampai selesai.
     *
     * @param {string} url          endpoint yang membalas 202 {job_id}
     * @param {RequestInit} init    opsi fetch (method, body, headers)
     * @param {object} opts
     *   - onProgress(job, percent, label): dipanggil setiap poll
     *   - cancelAnchor: elemen; tombol "Batalkan" disisipkan setelahnya
     * @returns {Promise<{ok, job, data, partial, cancelled, error}>}
     *   data = isi GET job.result_url (hasil lengkap), jika ada.
     */
    async function runJob(url, init, opts = {}) {
        const res = await fetch(url, init);
        if (!res.ok) return { ok: false, error: await readErrorDetail(res) };
        const { job_id: jobId } = await res.json();

        let cancelBtn = null;
        if (opts.cancelAnchor) {
            cancelBtn = createJobCancelButton(jobId);
            opts.cancelAnchor.insertAdjacentElement('afterend', cancelBtn);
        }

        try {
            let failures = 0;
            for (;;) {
                await sleep(JOB_POLL_MS);
                let job;
                try {
                    const r = await fetch(`/api/jobs/${jobId}`);
                    if (!r.ok) throw new Error(await readErrorDetail(r));
                    job = await r.json();
                    failures = 0;
                } catch (err) {
                    if (++failures >= JOB_MAX_POLL_FAILURES) {
                        return { ok: false, error: `Koneksi ke server terputus (${err.message}). Proses mungkin masih berjalan di server.` };
                    }
                    continue;
                }

                if (opts.onProgress) opts.onProgress(job, jobPercent(job), jobLabel(job));

                const finishedWithResult = job.status === 'succeeded'
                    || (job.status === 'cancelled' && job.partial);
                if (finishedWithResult) {
                    let data = null;
                    if (job.result_url) {
                        const r = await fetch(job.result_url);
                        if (!r.ok) return { ok: false, job, error: await readErrorDetail(r) };
                        data = await r.json();
                    }
                    return { ok: true, job, data, partial: job.status === 'cancelled' };
                }
                if (job.status === 'failed') {
                    return { ok: false, job, error: job.error || 'Proses gagal.' };
                }
                if (job.status === 'cancelled') {
                    return { ok: false, job, cancelled: true, error: 'Dibatalkan oleh pengguna.' };
                }
            }
        } finally {
            if (cancelBtn) cancelBtn.remove();
        }
    }

    // ====== SETTINGS PANEL ======
    const SETTINGS_VIEW_TITLES = {
        'menu': 'Pengaturan',
        'model-ai': 'Model & AI',
        'prompt-editor': 'Prompt AI',
        'riwayat': 'Riwayat Analisis',
        'tampilan': 'Tampilan',
        'panduan': 'Panduan Penggunaan',
        'diagnostik': 'Diagnostik',
        'tentang': 'Tentang',
    };

    function openSettings() {
        if (!settingsPanel) return;
        settingsPanel.classList.add('open');
        settingsOverlay.classList.add('visible');
        switchSettingsView('menu');
        loadSettings();
    }

    function closeSettings() {
        if (!settingsPanel) return;
        settingsPanel.classList.remove('open');
        settingsOverlay.classList.remove('visible');
    }

    function switchSettingsView(viewName) {
        settingsViews.forEach(v => {
            v.style.display = v.dataset.view === viewName ? '' : 'none';
        });
        if (settingsTitleText) settingsTitleText.textContent = SETTINGS_VIEW_TITLES[viewName] || 'Pengaturan';
        if (settingsBack) settingsBack.style.display = viewName === 'menu' ? 'none' : 'inline-flex';
        if (viewName === 'riwayat') renderHistory();
        if (viewName === 'diagnostik') loadDiagnostics();
        if (viewName === 'tentang') loadAbout();
        if (viewName === 'prompt-editor') loadPromptStatus();
    }

    if (settingsToggle) settingsToggle.addEventListener('click', openSettings);
    if (settingsClose) settingsClose.addEventListener('click', closeSettings);
    if (settingsOverlay) settingsOverlay.addEventListener('click', closeSettings);
    if (settingsBack) settingsBack.addEventListener('click', () => switchSettingsView('menu'));

    document.querySelectorAll('.settings-menu li').forEach(li => {
        li.addEventListener('click', () => {
            const target = li.dataset.target;
            if (target) switchSettingsView(target);
        });
    });

    async function loadSettings() {
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

    function renderSettingsForm(data) {
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
            <div class="diag-item">
                <span><i class="fas ${icon}"></i> ${label}</span>
                <span>${status ? `<span class="diag-status ${status.ok ? 'ok' : 'err'}">${escapeHtml(status.text)}</span>` : escapeHtml(value)}</span>
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

    async function loadPromptStatus(tool) {
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
    function closePromptPreview() {
        if (promptPreviewOverlay) promptPreviewOverlay.style.display = 'none';
    }
    if (promptPreviewClose) promptPreviewClose.addEventListener('click', closePromptPreview);
    if (promptPreviewCloseBtn) promptPreviewCloseBtn.addEventListener('click', closePromptPreview);
    if (promptPreviewOverlay) {
        promptPreviewOverlay.addEventListener('click', (e) => {
            if (e.target === promptPreviewOverlay) closePromptPreview();
        });
    }

    // ====== HISTORY (Tool 1) ======
        function renderHistory() {
        if (!historyList) return;
        if (state.history.length === 0) {
            historyList.innerHTML = `
                <div class="history-empty">
                    <i class="fas fa-folder-open"></i>
                    <p>Belum ada riwayat analisis.</p>
                </div>`;
            return;
        }

        historyList.innerHTML = state.history.map(h => {
            const isCompliance = h.type === 'compliance_review';
            const typeBadge = isCompliance
                ? `<span class="history-type-badge badge-compliance"><i class="fas fa-scale-balanced"></i> Compliance</span>`
                : `<span class="history-type-badge badge-audit"><i class="fas fa-clipboard-check"></i> Audit</span>`;

            if (isCompliance) {
                return `
                    <div class="history-item" data-id="${escapeAttr(h.id)}" data-type="compliance_review">
                        <div class="history-item-info" data-action="load">
                            <div class="history-item-name">${typeBadge} ${escapeHtml(h.nama)}</div>
                            <div class="history-item-meta">
                                <span><i class="fas fa-list"></i> ${h.total_items || 0}</span>
                                <span><i class="fas fa-check-circle" style="color:var(--success)"></i> ${h.total_patuh || 0}</span>
                                <span><i class="fas fa-exclamation-triangle" style="color:var(--warn)"></i> ${h.total_tidak_patuh || 0}</span>
                                <span>${new Date(h.tanggal).toLocaleDateString('id-ID')}</span>
                            </div>
                        </div>
                        <button class="history-item-delete" data-action="delete" title="Hapus">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                `;
            }

            return `
                <div class="history-item" data-id="${escapeAttr(h.id)}" data-type="regulation_audit">
                    <div class="history-item-info" data-action="load">
                        <div class="history-item-name">${typeBadge} ${escapeHtml(h.nama)}</div>
                        <div class="history-item-meta">
                            <span><i class="fas fa-list"></i> ${h.total_ketentuan || 0}</span>
                            <span><i class="fas fa-check-circle" style="color:var(--success)"></i> ${h.total_valid || 0}</span>
                            <span><i class="fas fa-exclamation-triangle" style="color:var(--warn)"></i> ${h.total_flagged || 0}</span>
                            <span>${new Date(h.tanggal).toLocaleDateString('id-ID')}</span>
                        </div>
                    </div>
                    <button class="history-item-delete" data-action="delete" title="Hapus">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
        }).join('');

        historyList.querySelectorAll('.history-item').forEach(el => {
            const id = el.dataset.id;
            const type = el.dataset.type || 'regulation_audit';
            el.querySelector('[data-action="load"]').addEventListener('click', () => loadHistory(id, type));
            el.querySelector('[data-action="delete"]').addEventListener('click', () => deleteHistoryItem(id));
        });
    }

        function saveToHistory(data, type = 'regulation_audit') {
        let entry;

        if (type === 'compliance_review') {
            // === COMPLIANCE REVIEW ===
            entry = {
                id: data.result_id || Date.now().toString(36),
                type: 'compliance_review',
                nama: data.contract_filename || data.nama_kontrak || 'Compliance Review',
                tanggal: new Date().toISOString(),
                // Stats
                total_items: data.total_items || 0,
                total_patuh: data.total_patuh || 0,
                total_patuh_catatan: data.total_patuh_catatan || 0,
                total_tidak_patuh: data.total_tidak_patuh || 0,
                total_tidak_relevan: data.total_tidak_relevan || 0,
                total_perlu_verifikasi: data.total_perlu_verifikasi || 0,
                // Data lengkap
                items: data.items || [],
                executive_summary: data.executive_summary || '',
                regulation_filenames: data.regulation_filenames || [],
                preview_id: data.preview_id || '',
            };
        } else {
            // === REGULATION AUDIT (default) ===
            entry = {
                id: data.result_id || Date.now().toString(36),
                type: 'regulation_audit',
                nama: data.nama_regulasi || data.filename || data.nama || 'Tanpa Nama',
                tanggal: new Date().toISOString(),
                total_ketentuan: data.total_ketentuan || 0,
                total_valid: data.total_valid || 0,
                total_flagged: data.total_flagged || 0,
                results: data.results || [],
                chunk_errors: data.chunk_errors || [],
                total_chunks: data.total_chunks || 0,
                total_batches: data.total_batches || 0,
                total_by_aspect: data.total_by_aspect || {},
                filter_applied: data.filter_applied || [],
                preview_id: data.preview_id || '',
            };
        }

        state.history = state.history.filter(h => h.id !== entry.id);
        state.history.unshift(entry);
        if (state.history.length > 50) state.history = state.history.slice(0, 50);
        localStorage.setItem('rta_history', JSON.stringify(state.history));
        renderHistory();
    }

    function deleteHistoryItem(id) {
        state.history = state.history.filter(h => h.id !== id);
        localStorage.setItem('rta_history', JSON.stringify(state.history));
        renderHistory();
        showToast('Riwayat dihapus.', 'success');
    }

    function clearAllHistory() {
        if (state.history.length === 0) return;
        if (confirm('Hapus semua riwayat analisis?')) {
            state.history = [];
            localStorage.setItem('rta_history', JSON.stringify(state.history));
            renderHistory();
            showToast('Semua riwayat dihapus.', 'success');
        }
    }
    if (historyClearAll) historyClearAll.addEventListener('click', clearAllHistory);

        async function loadHistory(id, type = null) {
        const entry = state.history.find(h => h.id === id);
        if (!entry) return;

        const entryType = type || entry.type || 'regulation_audit';

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
            // === LOAD REGULATION AUDIT (existing logic) ===
            state.currentResultId = entry.id;
            state.currentData = entry;
            state.selectedRows = new Set();
            state.statusFilter = '';
            if (statusFilterSelect) statusFilterSelect.value = '';
            if (exportBtn) exportBtn.disabled = false;
            if (exportPdfBtn) exportPdfBtn.disabled = false;
            if (copyBtn) copyBtn.disabled = false;
            if (previewExpiredBanner) previewExpiredBanner.style.display = 'none';
            renderSummary(entry);
            renderFilterBadge(entry.filter_applied || []);
            renderChunkErrors(entry.chunk_errors || []);
            renderTable(entry.results || []);
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

    // ====== UPLOAD (Tool 1) ======
    if (uploadZone) {
        uploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadZone.classList.add('dragover');
        });
        uploadZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            uploadZone.classList.remove('dragover');
        });
        uploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                fileInput.files = e.dataTransfer.files;
                updateFileNameDisplay();
                setStatus(`File dipilih: ${e.dataTransfer.files[0].name}`, false);
            }
        });
    }
    if (fileInput) fileInput.addEventListener('change', updateFileNameDisplay);

    function updateFileNameDisplay() {
        if (!fileNameDisplay) return;
        if (fileInput && fileInput.files.length) {
            fileNameDisplay.textContent = `📄 ${fileInput.files[0].name} (${formatFileSize(fileInput.files[0].size)})`;
            fileNameDisplay.style.display = 'block';
        } else {
            fileNameDisplay.textContent = '';
            fileNameDisplay.style.display = 'none';
        }
    }

    // ====== SUMMARY / PROGRESS / FILTER / DONUT (Tool 1) ======
    function renderSummary(data) {
        if (!summaryRow) return;
        const total = data.total_ketentuan || 0;
        const valid = data.total_valid || 0;
        const flagged = data.total_flagged || 0;
        const chunks = data.total_chunks || 0;
        const batches = data.total_batches || 0;

        summaryRow.innerHTML = `
            <div class="stat"><strong>${total}</strong><span>Ketentuan</span></div>
            <div class="stat stat-valid"><strong>${valid}</strong><span>Valid</span></div>
            <div class="stat stat-flagged"><strong>${flagged}</strong><span>Perlu Ditinjau</span></div>
            <div class="stat"><strong>${chunks}</strong><span>Potongan Dianalisis</span></div>
            <div class="stat"><strong>${batches}</strong><span>Pemanggilan API</span></div>
        `;

        const byAspect = data.total_by_aspect || {};
        const entries = Object.entries(byAspect).sort((a, b) => b[1] - a[1]);
        if (aspectsBox) {
            if (entries.length === 0) {
                aspectsBox.style.display = 'none';
            } else {
                aspectsBox.style.display = 'block';
                aspectsBox.innerHTML = `
                    <h4><i class="fas fa-layer-group"></i> Distribusi per Aspek</h4>
                    <div class="aspects-chips">
                        ${entries.map(([name, count]) =>
                            `<span class="aspect-chip">${escapeHtml(name)} <b>${count}</b></span>`
                        ).join('')}
                    </div>
                `;
            }
        }
        updateDonutChart();
    }

    function updateProgressBadge() {
        if (!progressBadge) return;
        if (!state.currentData || !state.currentData.results) {
            progressBadge.style.display = 'none';
            return;
        }
        const results = state.currentData.results;
        const total = results.length;
        if (total === 0) {
            progressBadge.style.display = 'none';
            return;
        }
        const audited = results.filter(r => (r.status_kepatuhan || 'Belum Diaudit') !== 'Belum Diaudit').length;
        const percent = Math.round((audited / total) * 100);

        progressBadge.style.display = 'inline-flex';
        progressBadge.classList.toggle('complete', audited === total && total > 0);

        progressBadge.innerHTML = `
            <span class="progress-badge-text">${audited} / ${total} diperiksa</span>
            <div class="progress-badge-bar">
                <div class="progress-badge-fill" style="width: ${percent}%"></div>
            </div>
            <span class="progress-badge-pct">${percent}%</span>
        `;
    }

    function renderFilterBadge(labels) {
        if (!filterBadge) return;
        if (!labels || labels.length === 0) {
            filterBadge.style.display = 'none';
            return;
        }
        filterBadge.style.display = 'flex';
        filterBadge.innerHTML = `
            <i class="fas fa-filter"></i>
            <span>Analisis terbatas pada:</span>
            <span class="filter-chips">
                ${labels.map(l => `<span class="filter-chip">${escapeHtml(l)}</span>`).join('')}
            </span>
        `;
    }

    function updateDonutChart() {
        if (!chartContainer || !donutChart || !donutInner || !chartLegend) return;
        if (!state.currentData) {
            chartContainer.style.display = 'none';
            return;
        }
        const valid = state.currentData.total_valid || 0;
        const flagged = state.currentData.total_flagged || 0;
        const total = valid + flagged;
        if (total === 0) {
            chartContainer.style.display = 'none';
            return;
        }
        chartContainer.style.display = 'flex';
        const validPercent = Math.round((valid / total) * 100);
        const flaggedPercent = 100 - validPercent;
        const validColor = getComputedStyle(document.documentElement).getPropertyValue('--success').trim();
        const warnColor = getComputedStyle(document.documentElement).getPropertyValue('--warn').trim();
        donutChart.style.background = `conic-gradient(${validColor} 0% ${validPercent}%, ${warnColor} ${validPercent}% 100%)`;
        donutInner.textContent = validPercent + '%';
        chartLegend.innerHTML = `
            <div class="chart-legend-item">
                <div class="chart-legend-dot valid"></div>
                <span>Valid: ${valid} (${validPercent}%)</span>
            </div>
            <div class="chart-legend-item">
                <div class="chart-legend-dot flagged"></div>
                <span>Perlu Ditinjau: ${flagged} (${flaggedPercent}%)</span>
            </div>
        `;
    }

    function renderChunkErrors(errors) {
        if (!chunkErrorsBox) return;
        if (!errors || errors.length === 0) {
            chunkErrorsBox.style.display = 'none';
            return;
        }
        chunkErrorsBox.style.display = 'block';
        const lines = errors.map(e => {
            const ref = [e.lampiran, e.bab, e.pasal, e.ayat].filter(Boolean).join(' / ')
                || '(referensi tidak diketahui)';
            const countInfo = e.affected_count > 1 ? ` (${e.affected_count} potongan)` : '';
            return `<li>${escapeHtml(ref)}${countInfo}: ${escapeHtml(e.error)}</li>`;
        }).join('');
        chunkErrorsBox.innerHTML = `
            <strong><i class="fas fa-triangle-exclamation"></i> ${errors.length} batch gagal dianalisis</strong>
            <div style="font-size:0.78rem; color:var(--text-muted);">
                Bagian lain tetap ditampilkan. Detail error:
            </div>
            <ul>${lines}</ul>
        `;
    }

    // ====== TABLE (Tool 1) ======
    function renderTable(results) {
        if (!resultBody) return;
        const filtered = applyFilter(results || []);
        if (filtered.length === 0) {
            resultBody.innerHTML = '';
            if (emptyState) emptyState.style.display = 'block';
            updateBulkToolbar();
            updateSelectAllCheckbox();
            return;
        }
        if (emptyState) emptyState.style.display = 'none';

        resultBody.innerHTML = filtered.map((item, i) => {
            const isFlagged = !item.is_valid;
            const notes = item.validation_notes || [];
            const notesBadge = notes.length
                ? `<span class="validity-badge" title="${escapeAttr(notes.join('; '))}">⚠ ${notes.length}</span>`
                : '';
            const realIdx = (state.currentData.results || []).indexOf(item);
            const isChecked = state.selectedRows.has(realIdx);

            const cell = (field, value, multiline) => `
                <td class="editable-cell" data-idx="${realIdx}" data-field="${field}">
                    <div class="cell-content ${multiline ? 'multiline' : ''}"
                         contenteditable="true"
                         spellcheck="false"
                         data-original="${escapeAttr(value)}">${escapeHtml(value)}</div>
                </td>`;

            return `
                <tr class="${isFlagged ? 'flagged' : 'valid-row'} ${isChecked ? 'selected-row' : ''}" data-idx="${realIdx}">
                    <td class="row-checkbox-cell">
                        <input type="checkbox" class="row-checkbox"
                               data-row-idx="${realIdx}"
                               ${isChecked ? 'checked' : ''} />
                    </td>
                    <td class="row-no">${i + 1}${notesBadge}</td>
                    ${cell('referensi_regulasi', item.referensi_regulasi || '', false)}
                    ${cell('aspek', item.aspek || '', false)}
                    ${cell('bab_pasal_ayat', item.bab_pasal_ayat || '', false)}
                    ${cell('point_ketentuan', item.point_ketentuan || '', true)}
                    ${cell('pemeriksaan', item.pemeriksaan || '', true)}
                    ${cell('metode_audit', item.metode_audit || '', false)}
                    ${cell('kebutuhan_bukti', item.kebutuhan_bukti || '', true)}
                    ${cell('status_kepatuhan', item.status_kepatuhan || 'Belum Diaudit', false)}
                    ${cell('catatan_temuan', item.catatan_temuan || '', true)}
                    <td class="actions-cell">
                        <button class="row-action-btn" data-delete-idx="${realIdx}" title="Hapus baris">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

        resultBody.querySelectorAll('.cell-content[contenteditable="true"]').forEach(el => {
            el.addEventListener('focus', () => el.classList.add('editing'));
            el.addEventListener('blur', onCellBlur);
            el.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    el.textContent = el.dataset.original || '';
                    el.blur();
                }
                if (e.key === 'Enter' && !el.classList.contains('multiline')) {
                    e.preventDefault();
                    el.blur();
                }
            });
        });

        resultBody.querySelectorAll('.row-checkbox').forEach(cb => {
            cb.addEventListener('change', () => {
                const idx = parseInt(cb.dataset.rowIdx, 10);
                if (cb.checked) state.selectedRows.add(idx);
                else state.selectedRows.delete(idx);
                cb.closest('tr').classList.toggle('selected-row', cb.checked);
                updateBulkToolbar();
                updateSelectAllCheckbox();
            });
        });

        resultBody.querySelectorAll('[data-delete-idx]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.deleteIdx, 10);
                deleteSingleRow(idx);
            });
        });

        updateBulkToolbar();
        updateSelectAllCheckbox();
    }

    function updateBulkToolbar() {
        if (!bulkToolbar) return;
        const count = state.selectedRows.size;
        if (count === 0) {
            bulkToolbar.style.display = 'none';
        } else {
            bulkToolbar.style.display = 'flex';
            bulkCount.textContent = `${count} dipilih`;
        }
        if (bulkStatusSelect) bulkStatusSelect.value = '';
    }

    function updateSelectAllCheckbox() {
        if (!selectAllCheckbox) return;
        if (!state.currentData || !state.currentData.results) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
            return;
        }
        const visibleFiltered = applyFilter(state.currentData.results);
        const visibleIndices = visibleFiltered.map(it => state.currentData.results.indexOf(it));
        const selectedVisible = visibleIndices.filter(i => state.selectedRows.has(i));
        const all = visibleIndices.length > 0 && selectedVisible.length === visibleIndices.length;
        const partial = selectedVisible.length > 0 && !all;
        selectAllCheckbox.checked = all;
        selectAllCheckbox.indeterminate = partial;
    }

    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', (e) => {
            if (!state.currentData || !state.currentData.results) return;
            const visibleFiltered = applyFilter(state.currentData.results);
            const visibleIndices = visibleFiltered.map(it => state.currentData.results.indexOf(it));
            if (e.target.checked) visibleIndices.forEach(i => state.selectedRows.add(i));
            else visibleIndices.forEach(i => state.selectedRows.delete(i));
            renderTable(state.currentData.results);
        });
    }

    if (bulkClearBtn) {
        bulkClearBtn.addEventListener('click', () => {
            state.selectedRows.clear();
            renderTable(state.currentData.results);
        });
    }

    if (bulkStatusSelect) {
        bulkStatusSelect.addEventListener('change', async () => {
            const newStatus = bulkStatusSelect.value;
            if (!newStatus || state.selectedRows.size === 0) return;
            const indices = Array.from(state.selectedRows);
            bulkStatusSelect.disabled = true;

            try {
                const res = await fetch(`/api/results/${state.currentResultId}/items/bulk`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_indices: indices, status_kepatuhan: newStatus }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                const data = await res.json();
                indices.forEach(i => {
                    if (state.currentData.results[i]) state.currentData.results[i].status_kepatuhan = newStatus;
                });
                state.currentData.total_ketentuan = data.total_ketentuan;
                state.currentData.total_valid = data.total_valid;
                state.currentData.total_flagged = data.total_flagged;
                state.currentData.total_by_aspect = data.total_by_aspect;

                state.selectedRows.clear();
                renderSummary(state.currentData);
                renderTable(state.currentData.results);
                updateProgressBadge();
                persistHistory();
                showToast(`${data.affected} baris diperbarui.`, 'success');
            } catch (err) {
                showToast(`Gagal update: ${err.message}`, 'error');
            } finally {
                bulkStatusSelect.disabled = false;
                bulkStatusSelect.value = '';
            }
        });
    }

    if (bulkDeleteBtn) {
        bulkDeleteBtn.addEventListener('click', async () => {
            if (state.selectedRows.size === 0) return;
            if (!confirm(`Hapus ${state.selectedRows.size} baris terpilih?`)) return;
            const indices = Array.from(state.selectedRows);
            bulkDeleteBtn.disabled = true;
            try {
                const res = await fetch(`/api/results/${state.currentResultId}/items`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_indices: indices }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                await reloadResult();
                state.selectedRows.clear();
                updateBulkToolbar();
                showToast(`${indices.length} baris dihapus.`, 'success');
            } catch (err) {
                showToast(`Gagal menghapus: ${err.message}`, 'error');
            } finally {
                bulkDeleteBtn.disabled = false;
            }
        });
    }

    async function deleteSingleRow(idx) {
        if (!state.currentData || !state.currentData.results[idx]) return;
        if (!confirm('Hapus baris ini?')) return;
        try {
            const res = await fetch(`/api/results/${state.currentResultId}/items`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_indices: [idx] }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            await reloadResult();
            state.selectedRows.clear();
            showToast('Baris dihapus.', 'success');
        } catch (err) {
            showToast(`Gagal menghapus: ${err.message}`, 'error');
        }
    }

    async function reloadResult() {
        try {
            const res = await fetch(`/api/results/${state.currentResultId}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            state.currentData = data;
            renderSummary(data);
            renderFilterBadge(data.filter_applied || []);
            renderChunkErrors(data.chunk_errors || []);
            renderTable(data.results || []);
            updateProgressBadge();
            updateDonutChart();
            persistHistory();
        } catch (err) {
            showToast(`Gagal memuat ulang: ${err.message}`, 'error');
        }
    }

    async function onCellBlur(e) {
        const el = e.target;
        el.classList.remove('editing');
        const newValue = (el.innerText || '').trim();
        const original = el.dataset.original || '';
        if (newValue === original) return;

        const idx = parseInt(el.closest('td').dataset.idx, 10);
        const field = el.closest('td').dataset.field;
        if (!state.currentData || !state.currentData.results[idx]) return;

        state.currentData.results[idx][field] = newValue;

        try {
            const res = await fetch(`/api/results/${state.currentResultId}/items/${idx}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [field]: newValue }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const updated = await res.json();
            Object.assign(state.currentData.results[idx], updated);
            el.dataset.original = newValue;
            el.classList.add('saved-flash');
            setTimeout(() => el.classList.remove('saved-flash'), 800);
            showToast('Tersimpan', 'success');
            if (field === 'status_kepatuhan') updateProgressBadge();
            persistHistory();
        } catch (err) {
            state.currentData.results[idx][field] = original;
            el.textContent = original;
            showToast(`Gagal menyimpan: ${err.message}`, 'error');
        }
    }

    function persistHistory() {
        const hIdx = state.history.findIndex(h => h.id === state.currentResultId);
        if (hIdx >= 0) {
            state.history[hIdx].results = state.currentData.results;
            state.history[hIdx].total_ketentuan = state.currentData.total_ketentuan;
            state.history[hIdx].total_valid = state.currentData.total_valid;
            state.history[hIdx].total_flagged = state.currentData.total_flagged;
            state.history[hIdx].total_by_aspect = state.currentData.total_by_aspect;
            localStorage.setItem('rta_history', JSON.stringify(state.history));
        }
    }

    // ====== ADD ROW MODAL (Tool 1) ======
    function openAddRowModal() {
        if (addRowReferensi) addRowReferensi.value = '';
        if (addRowAspek) addRowAspek.value = '';
        if (addRowStruktur) addRowStruktur.value = '';
        if (addRowKetentuan) addRowKetentuan.value = '';
        if (addRowPemeriksaan) addRowPemeriksaan.value = '';
        if (addRowMetode) addRowMetode.value = '';
        if (addRowBukti) addRowBukti.value = '';
        if (addRowCatatan) addRowCatatan.value = '';
        if (state.currentData?.results?.length > 0) {
            const sample = state.currentData.results[0];
            if (sample.referensi_regulasi && addRowReferensi) addRowReferensi.value = sample.referensi_regulasi;
        }
        if (addRowModalOverlay) addRowModalOverlay.style.display = 'flex';
        if (addRowReferensi) addRowReferensi.focus();
    }

    function closeAddRowModal() {
        if (addRowModalOverlay) addRowModalOverlay.style.display = 'none';
    }

    if (addRowBtn) addRowBtn.addEventListener('click', openAddRowModal);
    if (addRowModalClose) addRowModalClose.addEventListener('click', closeAddRowModal);
    if (addRowCancelBtn) addRowCancelBtn.addEventListener('click', closeAddRowModal);
    if (addRowModalOverlay) {
        addRowModalOverlay.addEventListener('click', (e) => {
            if (e.target === addRowModalOverlay) closeAddRowModal();
        });
    }

    if (addRowSaveBtn) {
        addRowSaveBtn.addEventListener('click', async () => {
            const ketVal = addRowKetentuan ? addRowKetentuan.value.trim() : '';
            const perVal = addRowPemeriksaan ? addRowPemeriksaan.value.trim() : '';
            if (!ketVal && !perVal) {
                showToast('Isi minimal salah satu: Ketentuan atau Prosedur Pemeriksaan.', 'error');
                return;
            }
            addRowSaveBtn.disabled = true;
            addRowSaveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';
            const payload = {
                referensi_regulasi: addRowReferensi ? addRowReferensi.value.trim() : '',
                aspek: addRowAspek ? addRowAspek.value.trim() : '',
                bab_pasal_ayat: addRowStruktur ? addRowStruktur.value.trim() : '',
                point_ketentuan: ketVal,
                pemeriksaan: perVal,
                metode_audit: addRowMetode ? addRowMetode.value.trim() : '',
                kebutuhan_bukti: addRowBukti ? addRowBukti.value.trim() : '',
                catatan_temuan: addRowCatatan ? addRowCatatan.value.trim() : '',
            };
            try {
                const res = await fetch(`/api/results/${state.currentResultId}/items`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                const newItem = await res.json();
                state.currentData.results.push(newItem);
                state.currentData.total_ketentuan = (state.currentData.total_ketentuan || 0) + 1;
                if (newItem.is_valid) state.currentData.total_valid = (state.currentData.total_valid || 0) + 1;
                closeAddRowModal();
                renderSummary(state.currentData);
                renderTable(state.currentData.results);
                updateProgressBadge();
                persistHistory();
                showToast('Baris baru ditambahkan.', 'success');
            } catch (err) {
                showToast(`Gagal menambah: ${err.message}`, 'error');
            } finally {
                addRowSaveBtn.disabled = false;
                addRowSaveBtn.innerHTML = '<i class="fas fa-plus"></i> Tambah Baris';
            }
        });
    }

    // ====== FILTER & SEARCH (Tool 1) ======
    function applyFilter(results) {
        let filtered = [...results];
        if (state.filter === 'valid') filtered = filtered.filter(r => r.is_valid);
        else if (state.filter === 'flagged') filtered = filtered.filter(r => !r.is_valid);
        if (state.statusFilter) {
            filtered = filtered.filter(r =>
                (r.status_kepatuhan || 'Belum Diaudit') === state.statusFilter
            );
        }
        if (state.searchQuery) {
            const q = state.searchQuery.toLowerCase();
            filtered = filtered.filter(r =>
                (r.referensi_regulasi || '').toLowerCase().includes(q) ||
                (r.aspek || '').toLowerCase().includes(q) ||
                (r.bab_pasal_ayat || '').toLowerCase().includes(q) ||
                (r.point_ketentuan || '').toLowerCase().includes(q) ||
                (r.pemeriksaan || '').toLowerCase().includes(q) ||
                (r.metode_audit || '').toLowerCase().includes(q) ||
                (r.kebutuhan_bukti || '').toLowerCase().includes(q) ||
                (r.catatan_temuan || '').toLowerCase().includes(q)
            );
        }
        return filtered;
    }

    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.filter = btn.dataset.filter;
            if (state.currentData) {
                renderTable(state.currentData.results || []);
                updateSelectAllCheckbox();
            }
        });
    });

    if (statusFilterSelect) {
        statusFilterSelect.addEventListener('change', (e) => {
            state.statusFilter = e.target.value;
            if (state.currentData) {
                renderTable(state.currentData.results || []);
                updateSelectAllCheckbox();
            }
        });
    }

    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            state.searchQuery = e.target.value;
            if (state.currentData) {
                renderTable(state.currentData.results || []);
                updateSelectAllCheckbox();
            }
        });
    }

    // ====== EXPORT & COPY (Tool 1) ======
    if (exportBtn) {
        exportBtn.addEventListener('click', () => {
            if (state.currentResultId) {
                window.location.href = `/api/export/${state.currentResultId}`;
                showToast('Mengekspor ke Excel...', 'info');
            }
        });
    }

    if (copyBtn) {
        copyBtn.addEventListener('click', () => {
            if (!state.currentData || !state.currentData.results) return;
            const results = state.currentData.results;
            let text = `HASIL ANALISIS REGULASI\n`;
            text += `Nama: ${state.currentData.nama || state.currentData.filename || '-'}\n`;
            text += `Total: ${results.length} ketentuan\n`;
            text += `${'='.repeat(60)}\n\n`;
            results.forEach((r, i) => {
                text += `[${i + 1}] ${r.referensi_regulasi || '-'}\n`;
                text += `    Aspek: ${r.aspek || '-'}\n`;
                text += `    Struktur: ${r.bab_pasal_ayat || '-'}\n`;
                text += `    Ketentuan: ${r.point_ketentuan}\n`;
                text += `    Pemeriksaan: ${r.pemeriksaan}\n`;
                text += `    Metode: ${r.metode_audit || '-'}\n`;
                text += `    Bukti: ${r.kebutuhan_bukti || '-'}\n`;
                text += `    Status: ${r.status_kepatuhan || 'Belum Diaudit'}\n`;
                if (r.catatan_temuan) text += `    Catatan: ${r.catatan_temuan}\n`;
                text += `\n`;
            });
            navigator.clipboard.writeText(text).then(() => {
                showToast('Seluruh hasil disalin ke clipboard.', 'success');
            }).catch(() => showToast('Gagal menyalin.', 'error'));
        });
    }

        if (clearResultBtn) {
        clearResultBtn.addEventListener('click', () => {
            resultSection.style.display = 'none';
            state.currentResultId = null;
            state.currentData = null;
            state.selectedRows.clear();
            exportBtn.disabled = true;
            exportPdfBtn.disabled = true;
            copyBtn.disabled = true;
            previewExpiredBanner.style.display = 'none';
            setStatus('Hasil ditutup. Silakan upload regulasi baru.', false);
            showToast('Hasil analisis ditutup.', 'info');
        });
    }

        if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            fileInput.value = '';
            fileNameDisplay.textContent = '';
            fileNameDisplay.style.display = 'none';
            const namaInput = document.getElementById('namaRegulasi');
            if (namaInput) namaInput.value = '';
            state.currentResultId = null;
            state.currentData = null;
            state.selectedRows = new Set();
            resultSection.style.display = 'none';
            exportBtn.disabled = true;
            exportPdfBtn.disabled = true;
            copyBtn.disabled = true;
            previewExpiredBanner.style.display = 'none';
            setStatus('Menunggu file...', false);
            showToast('Form dibersihkan.', 'info');
        });
    }

    // ====== TREE MODAL ======
    function isLeaf(node) {
        return !node.children || node.children.length === 0;
    }
    function collectLeaves(node) {
        if (isLeaf(node)) return [node];
        const out = [];
        for (const c of node.children) out.push(...collectLeaves(c));
        return out;
    }
    function isNodeFullySelected(node) {
        const leaves = collectLeaves(node);
        if (leaves.length === 0) return false;
        return leaves.every(l => treeState.selectedLeaves.has(l.id));
    }
    function isNodePartiallySelected(node) {
        const leaves = collectLeaves(node);
        const sel = leaves.filter(l => treeState.selectedLeaves.has(l.id)).length;
        return sel > 0 && sel < leaves.length;
    }
    function toggleNode(node, forceCheck) {
        const leaves = collectLeaves(node);
        const isFully = isNodeFullySelected(node);
        const shouldCheck = forceCheck === undefined ? !isFully : forceCheck;
        for (const leaf of leaves) {
            if (shouldCheck) treeState.selectedLeaves.add(leaf.id);
            else treeState.selectedLeaves.delete(leaf.id);
        }
    }
    function findNodeById(tree, id) {
        for (const node of tree) {
            if (node.id === id) return node;
            const found = findNodeById(node.children || [], id);
            if (found) return found;
        }
        return null;
    }
    function getSelectedChunkIndices() {
        const set = new Set();
        for (const leafId of treeState.selectedLeaves) {
            const leaf = findNodeById(treeState.tree, leafId);
            if (leaf) leaf.chunk_indices.forEach(i => set.add(i));
        }
        return Array.from(set).sort((a, b) => a - b);
    }
    function getTopmostSelectedLabels() {
        const labels = [];
        function walk(node, parentSelected) {
            const isFully = isNodeFullySelected(node);
            if (isFully && !parentSelected) {
                labels.push(node.label);
                return;
            }
            for (const c of node.children || []) walk(c, isFully);
        }
        for (const root of treeState.tree) walk(root, false);
        return labels;
    }
    function countSelectedLeaves() { return treeState.selectedLeaves.size; }

    function updateSelectedCount() {
        const n = countSelectedLeaves();
        if (treeSelectedCount) {
            treeSelectedCount.textContent = `${n} bagian terpilih`;
            treeSelectedCount.classList.toggle('has-selection', n > 0);
        }
        if (treeAnalyzeBtn) treeAnalyzeBtn.disabled = n === 0;
        scheduleEstimate();
    }

    function renderTreeNode(node, depth) {
        const leaf = isLeaf(node);
        const expanded = treeState.expanded.has(node.id);
        const fullySel = isNodeFullySelected(node);
        const pageInfo = (node.page_start != null && node.page_end != null)
            ? `<span class="tree-page">hal. ${node.page_start}${node.page_end !== node.page_start ? '–' + node.page_end : ''}</span>`
            : '';
        const icon = leaf
            ? '<i class="fas fa-file-lines"></i>'
            : (expanded ? '<i class="fas fa-folder-open"></i>' : '<i class="fas fa-folder"></i>');
        const expandBtn = leaf
            ? '<span class="tree-expand-spacer"></span>'
            : `<button class="tree-expand" data-expand-id="${escapeAttr(node.id)}" type="button">${expanded ? '▼' : '▶'}</button>`;
        const childrenHtml = (!leaf && expanded)
            ? `<div class="tree-children">${node.children.map(c => renderTreeNode(c, depth + 1)).join('')}</div>`
            : '';
        const isChecked = fullySel ? 'checked' : '';
        const leafClass = leaf ? 'is-leaf-row' : '';
        return `
            <div class="tree-node" data-node-id="${escapeAttr(node.id)}" data-depth="${depth}">
                <div class="tree-node-row ${leafClass}" data-row-id="${escapeAttr(node.id)}">
                    ${expandBtn}
                    <input type="checkbox" class="tree-checkbox"
                           data-check-id="${escapeAttr(node.id)}"
                           ${isChecked} />
                    <span class="tree-icon">${icon}</span>
                    <span class="tree-label" title="${escapeAttr(node.label)}">${escapeHtml(node.label)}</span>
                    ${pageInfo}
                </div>
                ${childrenHtml}
            </div>
        `;
    }

    function renderTree() {
        if (!treeContainer) return;
        if (!treeState.tree || treeState.tree.length === 0) {
            treeContainer.innerHTML = '<p style="padding:1rem;text-align:center;color:var(--text-muted);">Struktur tidak terdeteksi.</p>';
            return;
        }
        treeContainer.innerHTML = treeState.tree.map(n => renderTreeNode(n, 0)).join('');
        treeContainer.querySelectorAll('.tree-checkbox').forEach(cb => {
            const id = cb.dataset.checkId;
            const node = findNodeById(treeState.tree, id);
            if (node && isNodePartiallySelected(node)) cb.indeterminate = true;
        });
        treeContainer.querySelectorAll('[data-expand-id]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = btn.dataset.expandId;
                if (treeState.expanded.has(id)) treeState.expanded.delete(id);
                else treeState.expanded.add(id);
                renderTree();
            });
        });
        treeContainer.querySelectorAll('.tree-checkbox').forEach(cb => {
            cb.addEventListener('change', (e) => {
                e.stopPropagation();
                const id = cb.dataset.checkId;
                const node = findNodeById(treeState.tree, id);
                if (!node) return;
                toggleNode(node, cb.checked);
                renderTree();
                updateSelectedCount();
            });
            cb.addEventListener('click', (e) => e.stopPropagation());
        });
        treeContainer.querySelectorAll('.tree-node-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('.tree-checkbox') || e.target.closest('.tree-expand')) return;
                const id = row.dataset.rowId;
                const node = findNodeById(treeState.tree, id);
                if (!node) return;
                toggleNode(node);
                renderTree();
                updateSelectedCount();
            });
        });
    }

        function openTreeModal(previewData, options = {}) {
        treeState.previewId = previewData.preview_id;
        treeState.filename = previewData.filename || 'unknown';
        treeState.tree = previewData.tree || [];
        treeState.totalChunks = previewData.total_chunks || 0;
        treeState.expanded = new Set();
        treeState.selectedLeaves = new Set();
        treeState.isReAnalyze = options.isReAnalyze || false;

        for (const root of treeState.tree) treeState.expanded.add(root.id);

        if (options.preSelectLabels && options.preSelectLabels.length > 0) {
            preSelectByLabels(options.preSelectLabels);
        }

        // Build cache badge
        const cacheBadge = previewData.from_cache
            ? `<span class="cache-badge cache-badge-hit"
                     title="File yang sama pernah dianalisis — parsing di-skip, langsung load dari cache.">
                   <i class="fas fa-bolt"></i> Cache
               </span>`
            : (previewData.parse_time_ms
                ? `<span class="cache-badge cache-badge-parsed"
                         title="File baru — parsing dijalankan dalam ${(previewData.parse_time_ms / 1000).toFixed(1)} detik.">
                       <i class="fas fa-cog"></i> Parsing ${(previewData.parse_time_ms / 1000).toFixed(1)}s
                   </span>`
                : '');

        const subText = treeState.isReAnalyze
            ? `${escapeHtml(previewData.filename)} • ${previewData.total_chunks} potongan • Mode: ubah bagian`
            : `${escapeHtml(previewData.filename)} • ${previewData.total_chunks} potongan teks`;

        if (treeModalSub) {
            treeModalSub.innerHTML = `${subText}${cacheBadge}`;
        }

        if (treeModalOverlay) treeModalOverlay.style.display = 'flex';
        renderTree();
        updateSelectedCount();
        if (treeState.selectedLeaves.size > 0) fetchEstimate();
    }

    function preSelectByLabels(labels) {
        function walk(node) {
            if (labels.includes(node.label)) {
                for (const leaf of collectLeaves(node)) treeState.selectedLeaves.add(leaf.id);
                treeState.expanded.add(node.id);
            }
            for (const child of node.children || []) walk(child);
        }
        for (const root of treeState.tree) walk(root);
    }

    function closeTreeModal() {
        if (treeModalOverlay) treeModalOverlay.style.display = 'none';
        treeState.previewId = null;
        treeState.tree = [];
        treeState.expanded = new Set();
        treeState.selectedLeaves = new Set();
        treeState.isReAnalyze = false;
        if (estimateDebounceTimer) clearTimeout(estimateDebounceTimer);
        if (estimateAbortController) estimateAbortController.abort();
    }

    if (treeModalClose) treeModalClose.addEventListener('click', closeTreeModal);
    if (treeCancelBtn) treeCancelBtn.addEventListener('click', closeTreeModal);
    if (treeModalOverlay) {
        treeModalOverlay.addEventListener('click', (e) => {
            if (e.target === treeModalOverlay) closeTreeModal();
        });
    }
    if (treeSelectAll) {
        treeSelectAll.addEventListener('click', () => {
            for (const root of treeState.tree) toggleNode(root, true);
            renderTree();
            updateSelectedCount();
        });
    }
    if (treeClearAll) {
        treeClearAll.addEventListener('click', () => {
            treeState.selectedLeaves.clear();
            renderTree();
            updateSelectedCount();
        });
    }

    // ====== ESTIMASI ======
    let estimateDebounceTimer = null;
    let estimateAbortController = null;

        // ====== PROMPT EDITOR STATE ======
    const promptState = {
        currentTool: 'regulation_audit',
        status: null,
        dirty: false,
        loading: false,
        presets: [],              // cache preset dari server
        presetApplied: false,     // true kalau user baru apply preset
    };

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

    async function fetchEstimate() {
        if (!treeState.previewId || !treeEstimate) return;
        const indices = getSelectedChunkIndices();
        if (indices.length === 0) {
            treeEstimate.classList.remove('has-data');
            treeEstimate.innerHTML = `
                <i class="fas fa-info-circle"></i>
                <span class="tree-estimate-text">Pilih bagian untuk melihat estimasi</span>
            `;
            return;
        }
        treeEstimate.classList.remove('has-data');
        treeEstimate.innerHTML = `
            <i class="fas fa-spinner fa-spin"></i>
            <span class="tree-estimate-text">Menghitung estimasi...</span>
        `;
        if (estimateAbortController) estimateAbortController.abort();
        estimateAbortController = new AbortController();
        try {
            const res = await fetch('/api/estimate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    preview_id: treeState.previewId,
                    selected_chunk_indices: indices,
                }),
                signal: estimateAbortController.signal,
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            renderEstimate(data);
        } catch (err) {
            if (err.name === 'AbortError') return;
            treeEstimate.classList.remove('has-data');
            treeEstimate.innerHTML = `
                <i class="fas fa-info-circle"></i>
                <span class="tree-estimate-text">${indices.length} bagian dipilih</span>
            `;
        }
    }

    function renderEstimate(data) {
        if (!treeEstimate) return;
        if (data.total_chunks === 0) {
            treeEstimate.classList.remove('has-data');
            treeEstimate.innerHTML = `
                <i class="fas fa-info-circle"></i>
                <span class="tree-estimate-text">Tidak ada chunk valid</span>
            `;
            return;
        }
        const chars = data.total_chars.toLocaleString('id-ID');
        const tokens = data.total_tokens.toLocaleString('id-ID');
        const costIdr = formatIdr(data.cost_idr);
        const time = formatDuration(data.time_seconds_estimate);
        treeEstimate.classList.add('has-data');
        treeEstimate.innerHTML = `
            <i class="fas fa-chart-line"></i>
            <span class="tree-estimate-text">
                <b>${data.total_chunks}</b> bagian
                <span class="estimate-sep">•</span>
                ~${chars} kar
                <span class="estimate-sep">•</span>
                <b>${data.estimated_batches}</b> request
                <span class="estimate-sep">•</span>
                ~${tokens} token
                <span class="estimate-sep">•</span>
                💵 ≈${costIdr}
                <span class="estimate-sep">•</span>
                ⏱️ ~${time}
            </span>
        `;
    }

    function scheduleEstimate() {
        if (estimateDebounceTimer) clearTimeout(estimateDebounceTimer);
        estimateDebounceTimer = setTimeout(fetchEstimate, 300);
    }

    // ====== ANALYZE (Tool 1) ======
    if (treeAnalyzeBtn) {
        treeAnalyzeBtn.addEventListener('click', async () => {
            const indices = getSelectedChunkIndices();
            if (indices.length === 0) {
                showToast('Pilih minimal 1 bagian.', 'error');
                return;
            }
            const labels = getTopmostSelectedLabels();
            const previewId = treeState.previewId;
            const isReAnalyze = treeState.isReAnalyze;

            let nama;
            if (isReAnalyze && state.currentData) {
                nama = state.currentData.nama || state.currentData.filename || '';
            } else {
                const namaInput = document.getElementById('namaRegulasi');
                nama = (namaInput ? namaInput.value.trim() : '') || treeState.filename.replace(/\.[^.]+$/, '');
            }

            closeTreeModal();
            state.isAnalyzing = true;
            if (submitBtn) submitBtn.disabled = true;
            if (!isReAnalyze && resultSection) resultSection.style.display = 'none';
            if (statusEl) {
                statusEl.className = 'status-text';
                statusEl.innerHTML = '<span class="spinner"></span> Menganalisis dengan AI...';
            }
            setProgress(3, 'Mengirim chunk ke AI...');

            try {
                const run = await runJob('/api/analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preview_id: previewId,
                        selected_chunk_indices: indices,
                        selected_labels: labels,
                        nama_regulasi: nama,
                    }),
                }, {
                    cancelAnchor: progressText,
                    onProgress: (job, pct, label) => setProgress(pct, label),
                });

                if (!run.ok) {
                    hideProgress();
                    setStatus(`Gagal: ${run.error}`, true);
                    showToast(run.cancelled ? 'Analisis dibatalkan.' : 'Analisis gagal: ' + run.error, run.cancelled ? 'info' : 'error');
                    return;
                }
                const data = run.data;
                setProgress(100, 'Selesai!');

                setStatus(run.partial
                    ? `Dibatalkan — hasil parsial: ${data.total_ketentuan} ketentuan. ${run.job.message}`
                    : `Selesai. ${data.total_ketentuan} ketentuan dari ${data.total_chunks} potongan (${data.total_batches} API call).`, false);
                data.nama = nama;
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
                renderChunkErrors(data.chunk_errors);
                renderTable(data.results);
                updateProgressBadge();
                if (resultSection) resultSection.style.display = 'block';
                if (!isReAnalyze && resultSection) resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
                saveToHistory(data);
                if (run.partial) showToast('Analisis dibatalkan — hasil parsial ditampilkan.', 'info');
                else showToast(isReAnalyze ? 'Analisis ulang selesai! 🎉' : 'Analisis selesai! 🎉', 'success');
            } catch (err) {
                setStatus(`Gagal: ${err.message}`, true);
                showToast('Gagal terhubung ke server.', 'error');
            } finally {
                if (submitBtn) submitBtn.disabled = false;
                state.isAnalyzing = false;
                setTimeout(hideProgress, 2000);
            }
        });
    }

    // ====== UBAH BAGIAN (Tool 1) ======
    if (changeFilterBtn) {
        changeFilterBtn.addEventListener('click', async () => {
            if (!state.currentData) return;
            const previewId = state.currentData.preview_id;
            if (!previewId) {
                if (previewExpiredBanner) previewExpiredBanner.style.display = 'flex';
                showToast('Preview tidak tersedia. Upload ulang file.', 'error');
                return;
            }
            changeFilterBtn.disabled = true;
            changeFilterBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Memuat...';
            try {
                const res = await fetch(`/api/preview/${previewId}`);
                if (!res.ok) {
                    if (res.status === 404) {
                        if (previewExpiredBanner) previewExpiredBanner.style.display = 'flex';
                        showToast('Preview kedaluwarsa. Upload ulang file.', 'error');
                    } else showToast('Gagal memuat preview.', 'error');
                    return;
                }
                const previewData = await res.json();
                openTreeModal(previewData, {
                    isReAnalyze: true,
                    preSelectLabels: state.currentData.filter_applied || [],
                });
            } catch (err) {
                showToast(`Gagal memuat preview: ${err.message}`, 'error');
            } finally {
                changeFilterBtn.disabled = false;
                changeFilterBtn.innerHTML = '<i class="fas fa-sliders"></i> Ubah Bagian';
            }
        });
    }

    // ====== FORM SUBMIT (Tool 1) ======
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (previewExpiredBanner) previewExpiredBanner.style.display = 'none';
            if (!fileInput.files.length) {
                setStatus('Silakan pilih file terlebih dahulu.', true);
                showToast('Pilih file terlebih dahulu!', 'error');
                return;
            }
            const file = fileInput.files[0];
            if (file.size > 10 * 1024 * 1024) {
                setStatus('File terlalu besar. Maksimal 10MB.', true);
                showToast('File terlalu besar!', 'error');
                return;
            }
            if (submitBtn) submitBtn.disabled = true;
            state.isAnalyzing = true;
            if (resultSection) resultSection.style.display = 'none';
            if (statusEl) {
                statusEl.className = 'status-text';
                statusEl.innerHTML = '<span class="spinner"></span> Membaca struktur dokumen...';
            }
            setProgress(20, 'Mengekstrak teks...');

            const fd = new FormData();
            fd.append('file', file);
            try {
                setProgress(50, 'Mendeteksi struktur...');
                const res = await fetch('/api/preview', { method: 'POST', body: fd });
                const data = await res.json();
                if (!res.ok) {
                    setStatus(`Gagal: ${data.detail || 'Error.'}`, true);
                    showToast('Gagal: ' + (data.detail || 'Server error'), 'error');
                    hideProgress();
                    return;
                }
                setProgress(100, 'Struktur siap.');
                setStatus(`Struktur: ${data.total_chunks} potongan. Pilih bagian.`, false);
                setTimeout(() => {
                    hideProgress();
                    openTreeModal(data, { isReAnalyze: false });
                }, 300);
            } catch (err) {
                setStatus(`Gagal: ${err.message}`, true);
                showToast('Gagal terhubung ke server.', 'error');
                hideProgress();
            } finally {
                if (submitBtn) submitBtn.disabled = false;
                state.isAnalyzing = false;
            }
        });
    }

    // ============================================================
    // ============ TOOL 2: GAP ANALYSIS =========================
    // ============================================================

    const gapForm = $('#gapUploadForm');
    const gapUploadZone = $('#gapUploadZone');
    const gapFileInput = $('#gapFileInput');
    const gapFileNameDisplay = $('#gapFileNameDisplay');
    const gapNamaRegulasi = $('#gapNamaRegulasi');
    const gapFilterInput = $('#gapFilterInput');
    const gapSubmitBtn = $('#gapSubmitBtn');
    const gapResetBtn = $('#gapResetBtn');
    const gapStatusEl = $('#gapStatus');
    const gapProgressContainer = $('#gapProgressContainer');
    const gapProgressBar = $('#gapProgressBar');
    const gapProgressText = $('#gapProgressText');
    const gapResultSection = $('#gapResultSection');
    const gapFilterBadge = $('#gapFilterBadge');
    const gapChunkErrorsBox = $('#gapChunkErrorsBox');
    const gapSummaryRow = $('#gapSummaryRow');
    const gapSearchInput = $('#gapSearchInput');
    const gapStatusFilter = $('#gapStatusFilter');
    const gapBulkToolbar = $('#gapBulkToolbar');
    const gapBulkCount = $('#gapBulkCount');
    const gapBulkStatusSelect = $('#gapBulkStatusSelect');
    const gapBulkDeleteBtn = $('#gapBulkDeleteBtn');
    const gapBulkClearBtn = $('#gapBulkClearBtn');
    const gapAddRowBtn = $('#gapAddRowBtn');
    const gapSelectAllCheckbox = $('#gapSelectAllCheckbox');
    const gapResultBody = $('#gapResultBody');
    const gapEmptyState = $('#gapEmptyState');
    const gapExportBtn = $('#gapExportBtn');
    const gapCopyBtn = $('#gapCopyBtn');
    const gapClearResultBtn = $('#gapClearResultBtn');

    const gapAddRowModalOverlay = $('#gapAddRowModalOverlay');
    const gapAddRowModalClose = $('#gapAddRowModalClose');
    const gapAddRowCancelBtn = $('#gapAddRowCancelBtn');
    const gapAddRowSaveBtn = $('#gapAddRowSaveBtn');
    const gapAddPersyaratan = $('#gapAddPersyaratan');
    const gapAddReferensi = $('#gapAddReferensi');
    const gapAddCatatan = $('#gapAddCatatan');

    function updateGapFileNameDisplay() {
        if (!gapFileNameDisplay) return;
        if (gapFileInput && gapFileInput.files.length) {
            gapFileNameDisplay.textContent = `📄 ${gapFileInput.files[0].name} (${formatFileSize(gapFileInput.files[0].size)})`;
            gapFileNameDisplay.style.display = 'block';
        } else {
            gapFileNameDisplay.textContent = '';
            gapFileNameDisplay.style.display = 'none';
        }
    }

    if (gapUploadZone) {
        gapUploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            gapUploadZone.classList.add('dragover');
        });
        gapUploadZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            gapUploadZone.classList.remove('dragover');
        });
        gapUploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            gapUploadZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                gapFileInput.files = e.dataTransfer.files;
                updateGapFileNameDisplay();
                setGapStatus(`File dipilih: ${e.dataTransfer.files[0].name}`, false);
            }
        });
    }
    if (gapFileInput) gapFileInput.addEventListener('change', updateGapFileNameDisplay);

    function setGapStatus(text, isError) {
        if (!gapStatusEl) return;
        gapStatusEl.className = 'status-text';
        if (isError === true) {
            gapStatusEl.classList.add('error');
            gapStatusEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${escapeHtml(text)}`;
        } else if (isError === false) {
            gapStatusEl.classList.add('success');
            gapStatusEl.innerHTML = `<i class="fas fa-check-circle"></i> ${escapeHtml(text)}`;
        } else {
            gapStatusEl.textContent = text;
        }
    }

    function setGapProgress(percent, text) {
        if (!gapProgressContainer) return;
        gapProgressContainer.style.display = 'block';
        gapProgressBar.style.width = percent + '%';
        gapProgressText.textContent = text || `${Math.round(percent)}%`;
        if (percent >= 100) {
            setTimeout(() => {
                gapProgressContainer.style.display = 'none';
                gapProgressText.textContent = '';
            }, 1500);
        }
    }

    function hideGapProgress() {
        if (!gapProgressContainer) return;
        gapProgressContainer.style.display = 'none';
        gapProgressText.textContent = '';
        gapProgressBar.style.width = '0%';
    }

    function gapApplyFilter(items) {
        let filtered = [...items];
        if (state.gapStatusFilter) {
            filtered = filtered.filter(it => {
                const status = it.status_gap || 'Belum Dinilai';
                if (state.gapStatusFilter === 'Belum Dinilai') {
                    return !it.status_gap;
                }
                return it.status_gap === state.gapStatusFilter;
            });
        }
        if (state.gapSearchQuery) {
            const q = state.gapSearchQuery.toLowerCase();
            filtered = filtered.filter(it =>
                (it.persyaratan || '').toLowerCase().includes(q) ||
                (it.referensi || '').toLowerCase().includes(q) ||
                (it.catatan || '').toLowerCase().includes(q)
            );
        }
        return filtered;
    }

    function statusGapClass(status) {
        if (!status) return 'empty';
        const s = status.toLowerCase();
        if (s === 'sesuai') return 'sesuai';
        if (s === 'sebagian sesuai') return 'sebagian';
        if (s === 'tidak sesuai') return 'tidak';
        if (s === 'n/a') return 'na';
        return 'empty';
    }

    function renderGapTable(items) {
        if (!gapResultBody) return;
        const filtered = gapApplyFilter(items || []);
        if (filtered.length === 0) {
            gapResultBody.innerHTML = '';
            if (gapEmptyState) gapEmptyState.style.display = 'block';
            updateGapBulkToolbar();
            updateGapSelectAll();
            return;
        }
        if (gapEmptyState) gapEmptyState.style.display = 'none';

        gapResultBody.innerHTML = filtered.map((item, i) => {
            const realIdx = (state.gapData.requirements || []).indexOf(item);
            const isChecked = state.gapSelectedRows.has(realIdx);
            const status = item.status_gap || '';
            const statusLabel = status || 'Belum Dinilai';
            const statusCls = statusGapClass(status);

            const cell = (field, value, multiline, extraCls = '') => `
                <td class="editable-cell ${extraCls}" data-idx="${realIdx}" data-field="${field}">
                    <div class="cell-content ${multiline ? 'multiline' : ''}"
                         contenteditable="true"
                         spellcheck="false"
                         data-original="${escapeAttr(value)}">${escapeHtml(value)}</div>
                </td>`;

            const catatanCell = `
                <td class="editable-cell" data-idx="${realIdx}" data-field="catatan">
                    <div class="cell-content multiline"
                         contenteditable="true"
                         spellcheck="false"
                         data-original="${escapeAttr(item.catatan || '')}">${renderMarkdownLite(item.catatan || '')}</div>
                </td>`;

            return `
                <tr class="${isChecked ? 'selected-row' : ''}" data-idx="${realIdx}">
                    <td class="row-checkbox-cell">
                        <input type="checkbox" class="row-checkbox"
                               data-row-idx="${realIdx}"
                               ${isChecked ? 'checked' : ''} />
                    </td>
                    <td class="row-no">${i + 1}</td>
                    ${cell('persyaratan', item.persyaratan || '', true, 'col-persyaratan')}
                    ${cell('referensi', item.referensi || '', true, 'col-referensi')}
                    ${catatanCell}
                    <td class="editable-cell col-status" data-idx="${realIdx}" data-field="status_gap">
                        <div class="cell-content"
                             contenteditable="true"
                             spellcheck="false"
                             data-original="${escapeAttr(status)}">
                            <span class="status-pill ${statusCls}">${escapeHtml(statusLabel)}</span>
                        </div>
                    </td>
                    <td class="actions-cell">
                        <button class="row-action-btn" data-delete-idx="${realIdx}" title="Hapus">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

        gapResultBody.querySelectorAll('.cell-content[contenteditable="true"]').forEach(el => {
            el.addEventListener('focus', () => el.classList.add('editing'));
            el.addEventListener('blur', onGapCellBlur);
            el.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    el.textContent = el.dataset.original || '';
                    el.blur();
                }
                if (e.key === 'Enter' && !el.classList.contains('multiline')) {
                    e.preventDefault();
                    el.blur();
                }
            });
        });

        gapResultBody.querySelectorAll('.row-checkbox').forEach(cb => {
            cb.addEventListener('change', () => {
                const idx = parseInt(cb.dataset.rowIdx, 10);
                if (cb.checked) state.gapSelectedRows.add(idx);
                else state.gapSelectedRows.delete(idx);
                cb.closest('tr').classList.toggle('selected-row', cb.checked);
                updateGapBulkToolbar();
                updateGapSelectAll();
            });
        });

        gapResultBody.querySelectorAll('[data-delete-idx]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.deleteIdx, 10);
                gapDeleteSingleRow(idx);
            });
        });

        updateGapBulkToolbar();
        updateGapSelectAll();
    }

    function updateGapBulkToolbar() {
        if (!gapBulkToolbar) return;
        const count = state.gapSelectedRows.size;
        if (count === 0) gapBulkToolbar.style.display = 'none';
        else {
            gapBulkToolbar.style.display = 'flex';
            gapBulkCount.textContent = `${count} dipilih`;
        }
        if (gapBulkStatusSelect) gapBulkStatusSelect.value = '';
    }

    function updateGapSelectAll() {
        if (!gapSelectAllCheckbox) return;
        if (!state.gapData || !state.gapData.requirements) {
            gapSelectAllCheckbox.checked = false;
            gapSelectAllCheckbox.indeterminate = false;
            return;
        }
        const visible = gapApplyFilter(state.gapData.requirements);
        const visibleIndices = visible.map(it => state.gapData.requirements.indexOf(it));
        const selectedVisible = visibleIndices.filter(i => state.gapSelectedRows.has(i));
        const all = visibleIndices.length > 0 && selectedVisible.length === visibleIndices.length;
        const partial = selectedVisible.length > 0 && !all;
        gapSelectAllCheckbox.checked = all;
        gapSelectAllCheckbox.indeterminate = partial;
    }

    if (gapSelectAllCheckbox) {
        gapSelectAllCheckbox.addEventListener('change', (e) => {
            if (!state.gapData || !state.gapData.requirements) return;
            const visible = gapApplyFilter(state.gapData.requirements);
            const visibleIndices = visible.map(it => state.gapData.requirements.indexOf(it));
            if (e.target.checked) visibleIndices.forEach(i => state.gapSelectedRows.add(i));
            else visibleIndices.forEach(i => state.gapSelectedRows.delete(i));
            renderGapTable(state.gapData.requirements);
        });
    }

    if (gapBulkClearBtn) {
        gapBulkClearBtn.addEventListener('click', () => {
            state.gapSelectedRows.clear();
            renderGapTable(state.gapData.requirements);
        });
    }

    if (gapBulkStatusSelect) {
        gapBulkStatusSelect.addEventListener('change', async () => {
            const newStatus = gapBulkStatusSelect.value;
            if (!newStatus || state.gapSelectedRows.size === 0) return;
            const indices = Array.from(state.gapSelectedRows);
            gapBulkStatusSelect.disabled = true;
            try {
                const res = await fetch(`/api/requirements/${state.gapResultId}/items/bulk`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_indices: indices, status_kepatuhan: newStatus }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                const data = await res.json();
                indices.forEach(i => {
                    if (state.gapData.requirements[i]) state.gapData.requirements[i].status_gap = newStatus;
                });
                state.gapSelectedRows.clear();
                renderGapSummary(state.gapData);
                renderGapTable(state.gapData.requirements);
                showToast(`${data.affected} baris diperbarui.`, 'success');
            } catch (err) {
                showToast(`Gagal update: ${err.message}`, 'error');
            } finally {
                gapBulkStatusSelect.disabled = false;
                gapBulkStatusSelect.value = '';
            }
        });
    }

    if (gapBulkDeleteBtn) {
        gapBulkDeleteBtn.addEventListener('click', async () => {
            if (state.gapSelectedRows.size === 0) return;
            if (!confirm(`Hapus ${state.gapSelectedRows.size} baris terpilih?`)) return;
            const indices = Array.from(state.gapSelectedRows);
            gapBulkDeleteBtn.disabled = true;
            try {
                const res = await fetch(`/api/requirements/${state.gapResultId}/items`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_indices: indices }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                await gapReload();
                state.gapSelectedRows.clear();
                updateGapBulkToolbar();
                showToast(`${indices.length} baris dihapus.`, 'success');
            } catch (err) {
                showToast(`Gagal menghapus: ${err.message}`, 'error');
            } finally {
                gapBulkDeleteBtn.disabled = false;
            }
        });
    }

    async function gapDeleteSingleRow(idx) {
        if (!state.gapData || !state.gapData.requirements[idx]) return;
        if (!confirm('Hapus baris ini?')) return;
        try {
            const res = await fetch(`/api/requirements/${state.gapResultId}/items`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_indices: [idx] }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            await gapReload();
            state.gapSelectedRows.clear();
            showToast('Baris dihapus.', 'success');
        } catch (err) {
            showToast(`Gagal menghapus: ${err.message}`, 'error');
        }
    }

    async function gapReload() {
        try {
            const res = await fetch(`/api/requirements/${state.gapResultId}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            state.gapData = data;
            renderGapSummary(data);
            renderGapTable(data.requirements || []);
            renderGapChunkErrors(data.chunk_errors || []);
        } catch (err) {
            showToast(`Gagal memuat ulang: ${err.message}`, 'error');
        }
    }

    async function onGapCellBlur(e) {
        const el = e.target;
        el.classList.remove('editing');
        const newValue = (el.innerText || '').trim();
        const original = el.dataset.original || '';
        if (newValue === original) return;

        const idx = parseInt(el.closest('td').dataset.idx, 10);
        const field = el.closest('td').dataset.field;
        if (!state.gapData || !state.gapData.requirements[idx]) return;

        state.gapData.requirements[idx][field] = newValue;

        try {
            const res = await fetch(`/api/requirements/${state.gapResultId}/items/${idx}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [field]: newValue }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const updated = await res.json();
            Object.assign(state.gapData.requirements[idx], updated);
            el.dataset.original = newValue;
            el.classList.add('saved-flash');
            setTimeout(() => el.classList.remove('saved-flash'), 800);
            showToast('Tersimpan', 'success');
            if (field === 'status_gap' || field === 'catatan') {
                renderGapTable(state.gapData.requirements);
            }
            renderGapSummary(state.gapData);
        } catch (err) {
            state.gapData.requirements[idx][field] = original;
            el.textContent = original;
            showToast(`Gagal menyimpan: ${err.message}`, 'error');
        }
    }

    function renderGapSummary(data) {
        if (!gapSummaryRow) return;
        const total = data.total_requirements || 0;
        const items = data.requirements || [];
        const dinilai = items.filter(it => it.status_gap && it.status_gap !== 'Belum Dinilai').length;
        const sesuai = items.filter(it => it.status_gap === 'Sesuai').length;
        const tidakSesuai = items.filter(it => it.status_gap === 'Tidak Sesuai' || it.status_gap === 'Sebagian Sesuai').length;
        const chunks = data.total_chunks_analyzed || 0;
        const batches = data.total_batches || 0;

        gapSummaryRow.innerHTML = `
            <div class="stat"><strong>${total}</strong><span>Persyaratan</span></div>
            <div class="stat"><strong>${dinilai}</strong><span>Sudah Dinilai</span></div>
            <div class="stat stat-valid"><strong>${sesuai}</strong><span>Sesuai</span></div>
            <div class="stat stat-flagged"><strong>${tidakSesuai}</strong><span>Perlu Tindak</span></div>
            <div class="stat"><strong>${chunks}</strong><span>Potongan Dianalisis</span></div>
            <div class="stat"><strong>${batches}</strong><span>Pemanggilan API</span></div>
        `;

        if (data.filter_applied && gapFilterBadge) {
            gapFilterBadge.style.display = 'flex';
            gapFilterBadge.innerHTML = `
                <i class="fas fa-filter"></i>
                <span>Filter:</span>
                <span class="filter-chips">
                    <span class="filter-chip">${escapeHtml(data.filter_applied)}</span>
                </span>
            `;
        } else if (gapFilterBadge) {
            gapFilterBadge.style.display = 'none';
        }
    }

    function renderGapChunkErrors(errors) {
        if (!gapChunkErrorsBox) return;
        if (!errors || errors.length === 0) {
            gapChunkErrorsBox.style.display = 'none';
            return;
        }
        gapChunkErrorsBox.style.display = 'block';
        const lines = errors.map(e => {
            const ref = [e.lampiran, e.bab, e.pasal, e.ayat].filter(Boolean).join(' / ')
                || '(referensi tidak diketahui)';
            const countInfo = e.affected_count > 1 ? ` (${e.affected_count} potongan)` : '';
            return `<li>${escapeHtml(ref)}${countInfo}: ${escapeHtml(e.error)}</li>`;
        }).join('');
        gapChunkErrorsBox.innerHTML = `
            <strong><i class="fas fa-triangle-exclamation"></i> ${errors.length} batch gagal</strong>
            <ul>${lines}</ul>
        `;
    }

    if (gapSearchInput) {
        gapSearchInput.addEventListener('input', (e) => {
            state.gapSearchQuery = e.target.value;
            if (state.gapData) renderGapTable(state.gapData.requirements);
        });
    }

    if (gapStatusFilter) {
        gapStatusFilter.addEventListener('change', (e) => {
            state.gapStatusFilter = e.target.value;
            if (state.gapData) renderGapTable(state.gapData.requirements);
        });
    }

    function openGapAddRowModal() {
        if (gapAddPersyaratan) gapAddPersyaratan.value = '';
        if (gapAddReferensi) gapAddReferensi.value = '';
        if (gapAddCatatan) gapAddCatatan.value = '';
        if (gapAddRowModalOverlay) gapAddRowModalOverlay.style.display = 'flex';
        if (gapAddPersyaratan) gapAddPersyaratan.focus();
    }
    function closeGapAddRowModal() {
        if (gapAddRowModalOverlay) gapAddRowModalOverlay.style.display = 'none';
    }

    if (gapAddRowBtn) gapAddRowBtn.addEventListener('click', openGapAddRowModal);
    if (gapAddRowModalClose) gapAddRowModalClose.addEventListener('click', closeGapAddRowModal);
    if (gapAddRowCancelBtn) gapAddRowCancelBtn.addEventListener('click', closeGapAddRowModal);
    if (gapAddRowModalOverlay) {
        gapAddRowModalOverlay.addEventListener('click', (e) => {
            if (e.target === gapAddRowModalOverlay) closeGapAddRowModal();
        });
    }

    if (gapAddRowSaveBtn) {
        gapAddRowSaveBtn.addEventListener('click', async () => {
            if (!gapAddPersyaratan.value.trim()) {
                showToast('Isi minimal kolom Persyaratan.', 'error');
                return;
            }
            gapAddRowSaveBtn.disabled = true;
            gapAddRowSaveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';
            try {
                const res = await fetch(`/api/requirements/${state.gapResultId}/items`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        persyaratan: gapAddPersyaratan.value.trim(),
                        referensi: gapAddReferensi ? gapAddReferensi.value.trim() : '',
                        catatan: gapAddCatatan ? gapAddCatatan.value.trim() : '',
                        status_gap: '',
                    }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                const newItem = await res.json();
                state.gapData.requirements.push(newItem);
                state.gapData.total_requirements = state.gapData.requirements.length;
                closeGapAddRowModal();
                renderGapSummary(state.gapData);
                renderGapTable(state.gapData.requirements);
                showToast('Persyaratan ditambahkan.', 'success');
            } catch (err) {
                showToast(`Gagal menambah: ${err.message}`, 'error');
            } finally {
                gapAddRowSaveBtn.disabled = false;
                gapAddRowSaveBtn.innerHTML = '<i class="fas fa-plus"></i> Tambah Persyaratan';
            }
        });
    }

    if (gapExportBtn) {
        gapExportBtn.addEventListener('click', () => {
            if (state.gapResultId) {
                window.location.href = `/api/export-requirements/${state.gapResultId}`;
                showToast('Mengekspor ke Excel...', 'info');
            }
        });
    }
        const gapExportPdfBtn = $('#gapExportPdfBtn');
    if (gapExportPdfBtn) {
        gapExportPdfBtn.addEventListener('click', () => {
            if (state.gapResultId) {
                window.location.href = `/api/export-requirements-pdf/${state.gapResultId}`;
                showToast('Mengekspor ke PDF...', 'info');
            }
        });
    }

        if (exportPdfBtn) {
        exportPdfBtn.addEventListener('click', () => {
            if (state.currentResultId) {
                window.location.href = `/api/export-pdf/${state.currentResultId}`;
                showToast('Mengekspor ke PDF...', 'info');
            }
        });
    }

    if (gapCopyBtn) {
        gapCopyBtn.addEventListener('click', () => {
            if (!state.gapData || !state.gapData.requirements) return;
            const items = state.gapData.requirements;
            let text = `DAFTAR PERSYARATAN REGULASI\n`;
            text += `Total: ${items.length} persyaratan\n`;
            text += `${'='.repeat(60)}\n\n`;
            items.forEach((it, i) => {
                text += `[${i + 1}] ${it.persyaratan}\n`;
                text += `    Referensi: ${it.referensi || '-'}\n`;
                if (it.catatan) text += `    Catatan: ${it.catatan}\n`;
                if (it.status_gap) text += `    Status Gap: ${it.status_gap}\n`;
                text += `\n`;
            });
            navigator.clipboard.writeText(text).then(() => {
                showToast('Disalin ke clipboard.', 'success');
            }).catch(() => showToast('Gagal menyalin.', 'error'));
        });
    }

    if (gapClearResultBtn) {
        gapClearResultBtn.addEventListener('click', () => {
            gapResultSection.style.display = 'none';
            state.gapResultId = null;
            state.gapData = null;
            state.gapSelectedRows.clear();
            gapExportBtn.disabled = true;
            gapCopyBtn.disabled = true;
            setGapStatus('Hasil ditutup. Upload regulasi baru.', false);
            showToast('Hasil ditutup.', 'info');
        });
    }

    if (gapResetBtn) {
        gapResetBtn.addEventListener('click', () => {
            gapFileInput.value = '';
            gapFileNameDisplay.textContent = '';
            gapFileNameDisplay.style.display = 'none';
            if (gapNamaRegulasi) gapNamaRegulasi.value = '';
            if (gapFilterInput) gapFilterInput.value = '';
            state.gapResultId = null;
            state.gapData = null;
            state.gapSelectedRows = new Set();
            gapResultSection.style.display = 'none';
            gapExportBtn.disabled = true;
            gapCopyBtn.disabled = true;
            setGapStatus('Menunggu file...', false);
            showToast('Form dibersihkan.', 'info');
        });
    }

    if (gapForm) {
        gapForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!gapFileInput.files.length) {
                setGapStatus('Pilih file terlebih dahulu.', true);
                showToast('Pilih file dulu!', 'error');
                return;
            }
            const file = gapFileInput.files[0];
            if (file.size > 10 * 1024 * 1024) {
                setGapStatus('File terlalu besar. Maks 10MB.', true);
                showToast('File terlalu besar!', 'error');
                return;
            }

            gapSubmitBtn.disabled = true;
            state.isAnalyzing = true;
            gapResultSection.style.display = 'none';
            setGapStatus('Membaca struktur dokumen...', null);
            setGapProgress(20, 'Mengekstrak teks...');

            const fd = new FormData();
            fd.append('file', file);

            try {
                setGapProgress(40, 'Mendeteksi struktur...');
                const previewRes = await fetch('/api/preview', { method: 'POST', body: fd });
                const previewData = await previewRes.json();

                if (!previewRes.ok) {
                    setGapStatus(`Gagal: ${previewData.detail || 'Error.'}`, true);
                    showToast('Gagal: ' + (previewData.detail || 'Server error'), 'error');
                    hideGapProgress();
                    return;
                }

                setGapProgress(60, 'Mengekstrak persyaratan dengan AI...');
                setGapStatus(`${previewData.total_chunks} potongan. AI menganalisis...`, null);

                const namaInput = gapNamaRegulasi ? gapNamaRegulasi.value.trim() : '';
                const filterText = gapFilterInput ? gapFilterInput.value.trim() : '';

                const run = await runJob('/api/analyze-requirements', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preview_id: previewData.preview_id,
                        nama_regulasi: namaInput || file.name.replace(/\.[^.]+$/, ''),
                        filter_text: filterText || null,
                    }),
                }, {
                    cancelAnchor: gapProgressText,
                    onProgress: (job, pct, label) => setGapProgress(60 + pct * 0.4, label),
                });

                if (!run.ok) {
                    setGapStatus(`Gagal: ${run.error}`, true);
                    showToast(run.cancelled ? 'Ekstraksi dibatalkan.' : 'Gagal: ' + run.error, run.cancelled ? 'info' : 'error');
                    hideGapProgress();
                    return;
                }
                const data = run.data;

                setGapProgress(100, 'Selesai!');
                setGapStatus(run.partial
                    ? `Dibatalkan — hasil parsial: ${data.total_requirements} persyaratan. ${run.job.message}`
                    : `Selesai. ${data.total_requirements} persyaratan dari ${data.total_chunks_analyzed} potongan.`, false);

                state.gapResultId = data.result_id;
                state.gapData = data;
                state.gapSelectedRows = new Set();
                state.gapStatusFilter = '';
                if (gapStatusFilter) gapStatusFilter.value = '';

                gapExportBtn.disabled = false;
                gapCopyBtn.disabled = false;
                renderGapSummary(data);
                renderGapChunkErrors(data.chunk_errors);
                renderGapTable(data.requirements);
                gapResultSection.style.display = 'block';
                gapResultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
                showToast(run.partial ? 'Dibatalkan — hasil parsial ditampilkan.' : 'Persyaratan berhasil diekstrak! 🎉',
                    run.partial ? 'info' : 'success');
            } catch (err) {
                setGapStatus(`Gagal: ${err.message}`, true);
                showToast('Gagal terhubung ke server.', 'error');
            } finally {
                gapSubmitBtn.disabled = false;
                state.isAnalyzing = false;
                setTimeout(hideGapProgress, 2000);
            }
        });
    }


        // ============================================================
    // COMPLIANCE REVIEW (Tool 3)
    // ============================================================

    const COMPLIANCE_STATUS_OPTIONS = [
        "PATUH",
        "PATUH DENGAN CATATAN",
        "TIDAK PATUH",
        "TIDAK RELEVAN",
        "PERLU VERIFIKASI",
    ];

    const complianceState = {
        previewId: null,
        resultId: null,
        data: null,
        searchQuery: '',
        statusFilter: '',
        selectedRows: new Set(),
        contractFile: null,
        regulationFiles: [],
        pendingAnalysisIndices: [],  
    };

    // ---- DOM Refs ----
    const complianceUploadForm = $('#complianceUploadForm');
    const complianceContractZone = $('#complianceContractZone');
    const complianceContractFile = $('#complianceContractFile');
    const complianceContractFileName = $('#complianceContractFileName');
    const complianceRegulationZone = $('#complianceRegulationZone');
    const complianceRegulationFiles = $('#complianceRegulationFiles');
    const complianceRegulationFileNames = $('#complianceRegulationFileNames');
    const complianceNamaKontrak = $('#complianceNamaKontrak');
    const complianceFilterKontrak = $('#complianceFilterKontrak');
    const complianceSubmitBtn = $('#complianceSubmitBtn');
    const complianceResetBtn = $('#complianceResetBtn');
    const complianceStatusEl = $('#complianceStatus');
    const complianceProgressContainer = $('#complianceProgressContainer');
    const complianceProgressBar = $('#complianceProgressBar');
    const complianceProgressText = $('#complianceProgressText');
    const complianceResultSection = $('#complianceResultSection');
    const complianceResultMeta = $('#complianceResultMeta');
    const complianceSummaryGrid = $('#complianceSummaryGrid');
    const complianceSearchInput = $('#complianceSearchInput');
    const complianceStatusFilter = $('#complianceStatusFilter');
    const complianceBulkToolbar = $('#complianceBulkToolbar');
    const complianceBulkCount = $('#complianceBulkCount');
    const complianceBulkStatusSelect = $('#complianceBulkStatusSelect');
    const complianceBulkDeleteBtn = $('#complianceBulkDeleteBtn');
    const complianceBulkClearBtn = $('#complianceBulkClearBtn');
    const complianceAddRowBtn = $('#complianceAddRowBtn');
    const complianceSelectAllCheckbox = $('#complianceSelectAllCheckbox');
    const complianceResultBody = $('#complianceResultBody');
    const complianceEmptyState = $('#complianceEmptyState');
    const complianceCopyMdBtn = $('#complianceCopyMdBtn');
    const complianceExportBtn = $('#complianceExportBtn');
    const complianceClearResultBtn = $('#complianceClearResultBtn');
    const complianceExecutiveSummary = $('#complianceExecutiveSummary');
    const complianceExecutiveSummaryEdit = $('#complianceExecutiveSummaryEdit');
    const complianceExecutiveSummaryTextarea = $('#complianceExecutiveSummaryTextarea');
    const complianceEditSummaryBtn = $('#complianceEditSummaryBtn');
    const complianceCancelSummaryBtn = $('#complianceCancelSummaryBtn');
    const complianceSaveSummaryBtn = $('#complianceSaveSummaryBtn');
    const compliancePendingBanner = $('#compliancePendingBanner');
    const compliancePendingText = $('#compliancePendingText');
    const complianceAnalyzePendingBtn = $('#complianceAnalyzePendingBtn');
    const complianceDismissPendingBtn = $('#complianceDismissPendingBtn');

    // Add row modal
    const complianceAddRowModalOverlay = $('#complianceAddRowModalOverlay');
    const complianceAddRowModalClose = $('#complianceAddRowModalClose');
    const complianceAddRowCancelBtn = $('#complianceAddRowCancelBtn');
    const complianceAddRowSaveBtn = $('#complianceAddRowSaveBtn');
    const complianceAddKlausulRef = $('#complianceAddKlausulRef');
    const complianceAddKlausulText = $('#complianceAddKlausulText');
    const complianceAddRegulasiRef = $('#complianceAddRegulasiRef');
    const complianceAddStatus = $('#complianceAddStatus');
    const complianceAddAnalisis = $('#complianceAddAnalisis');

    // ---- Status helpers ----
    function complianceStatusClass(status) {
        if (status === 'PATUH') return 'status-patuh';
        if (status === 'PATUH DENGAN CATATAN') return 'status-catatan';
        if (status === 'TIDAK PATUH') return 'status-tidak-patuh';
        if (status === 'TIDAK RELEVAN') return 'status-tidak-relevan';
        return 'status-verifikasi';
    }

    function complianceStatusLabel(status) {
        if (status === 'PATUH') return 'Patuh';
        if (status === 'PATUH DENGAN CATATAN') return 'Patuh dengan Catatan';
        if (status === 'TIDAK PATUH') return 'Tidak Patuh';
        if (status === 'TIDAK RELEVAN') return 'Tidak Relevan';
        return 'Perlu Verifikasi';
    }

    function complianceRowClass(status) {
        if (status === 'PATUH') return 'row-patuh';
        if (status === 'PATUH DENGAN CATATAN') return 'row-catatan';
        if (status === 'TIDAK PATUH') return 'row-tidak-patuh';
        if (status === 'TIDAK RELEVAN') return 'row-tidak-relevan';
        return 'row-verifikasi';
    }

    // ---- Progress helpers ----
    function setComplianceStatus(text, isError) {
        if (!complianceStatusEl) return;
        complianceStatusEl.className = 'status-text';
        if (isError === true) {
            complianceStatusEl.classList.add('error');
            complianceStatusEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${escapeHtml(text)}`;
        } else if (isError === false) {
            complianceStatusEl.classList.add('success');
            complianceStatusEl.innerHTML = `<i class="fas fa-check-circle"></i> ${escapeHtml(text)}`;
        } else {
            complianceStatusEl.textContent = text;
        }
    }

    function setComplianceProgress(percent, text) {
        if (!complianceProgressContainer) return;
        complianceProgressContainer.style.display = 'block';
        complianceProgressBar.style.width = percent + '%';
        complianceProgressText.textContent = text || `${Math.round(percent)}%`;
        if (percent >= 100) {
            setTimeout(() => {
                complianceProgressContainer.style.display = 'none';
                complianceProgressText.textContent = '';
            }, 1500);
        }
    }

    function hideComplianceProgress() {
        if (!complianceProgressContainer) return;
        complianceProgressContainer.style.display = 'none';
        complianceProgressText.textContent = '';
        complianceProgressBar.style.width = '0%';
    }

    // ---- Upload UI ----
    function updateContractFileNameDisplay() {
        if (!complianceContractFileName) return;
        if (complianceContractFile && complianceContractFile.files.length) {
            complianceContractFileName.textContent = `📄 ${complianceContractFile.files[0].name} (${formatFileSize(complianceContractFile.files[0].size)})`;
            complianceContractFileName.style.display = 'block';
        } else {
            complianceContractFileName.textContent = '';
            complianceContractFileName.style.display = 'none';
        }
    }

            function updateRegulationFileNamesDisplay() {
        if (!complianceRegulationFileNames) return;

        const files = complianceRegulationFiles
            ? Array.from(complianceRegulationFiles.files)
            : [];

        // Hapus class multi dulu
        complianceRegulationFileNames.classList.remove('multi');

        if (!files.length) {
            complianceRegulationFileNames.innerHTML = '';
            complianceRegulationFileNames.style.display = 'none';
            return;
        }

        // Kalau cuma 1 file — display inline biasa
        if (files.length === 1) {
            const f = files[0];
            complianceRegulationFileNames.textContent =
                `📄 ${f.name} (${formatFileSize(f.size)})`;
            complianceRegulationFileNames.style.display = 'block';
            return;
        }

        // Multi file — tampilkan sebagai list
        complianceRegulationFileNames.classList.add('multi');
        complianceRegulationFileNames.innerHTML = files.map(f =>
            `<div class="file-item">📄 ${escapeHtml(f.name)} <span style="color:var(--text-soft); font-size:0.72rem;">(${formatFileSize(f.size)})</span></div>`
        ).join('');
        complianceRegulationFileNames.style.display = 'block';
    }

    // Drag & drop: contract
    if (complianceContractZone) {
        complianceContractZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            complianceContractZone.classList.add('dragover');
        });
        complianceContractZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            complianceContractZone.classList.remove('dragover');
        });
        complianceContractZone.addEventListener('drop', (e) => {
            e.preventDefault();
            complianceContractZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                complianceContractFile.files = e.dataTransfer.files;
                updateContractFileNameDisplay();
            }
        });
    }
    if (complianceContractFile) {
        complianceContractFile.addEventListener('change', updateContractFileNameDisplay);
    }

    // Drag & drop: regulations
        if (complianceRegulationZone) {
        complianceRegulationZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            complianceRegulationZone.classList.add('dragover');
        });
        complianceRegulationZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            complianceRegulationZone.classList.remove('dragover');
        });
        complianceRegulationZone.addEventListener('drop', (e) => {
            e.preventDefault();
            complianceRegulationZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                // Gunakan DataTransfer API untuk preserve multiple files (fix Chrome bug)
                const dt = new DataTransfer();
                for (let i = 0; i < e.dataTransfer.files.length; i++) {
                    dt.items.add(e.dataTransfer.files[i]);
                }
                complianceRegulationFiles.files = dt.files;
                updateRegulationFileNamesDisplay();
            }
        });
    }

    if (complianceRegulationFiles) {
        complianceRegulationFiles.addEventListener('change', updateRegulationFileNamesDisplay);
    }

    // ---- Summary Grid ----
    function renderComplianceSummary(data) {
        if (!complianceSummaryGrid) return;
        complianceSummaryGrid.innerHTML = `
            <div class="compliance-stat stat-total">
                <strong>${data.total_items || 0}</strong>
                <span>Total Klausul</span>
            </div>
            <div class="compliance-stat stat-patuh">
                <strong>${data.total_patuh || 0}</strong>
                <span>Patuh</span>
            </div>
            <div class="compliance-stat stat-catatan">
                <strong>${data.total_patuh_catatan || 0}</strong>
                <span>Patuh dgn Catatan</span>
            </div>
            <div class="compliance-stat stat-tidak-patuh">
                <strong>${data.total_tidak_patuh || 0}</strong>
                <span>Tidak Patuh</span>
            </div>
            <div class="compliance-stat stat-tidak-relevan">
                <strong>${data.total_tidak_relevan || 0}</strong>
                <span>Tidak Relevan</span>
            </div>
            <div class="compliance-stat stat-verifikasi" title="AI tidak memberi putusan yang andal — wajib dicek auditor">
                <strong>${data.total_perlu_verifikasi || 0}</strong>
                <span>Perlu Verifikasi</span>
            </div>
        `;
    }

    function renderComplianceMeta(data) {
        if (!complianceResultMeta) return;
        const contract = escapeHtml(data.contract_filename || '-');
        const regs = (data.regulation_filenames || []).length;
        const filterInfo = data.filter_applied
            ? ` <span class="meta-sep">•</span> Filter: <b>${escapeHtml(data.filter_applied)}</b>`
            : '';
        complianceResultMeta.innerHTML = `
            Kontrak: <b>${contract}</b>
            <span class="meta-sep">•</span>
            Regulasi: <b>${regs} file</b>
            <span class="meta-sep">•</span>
            Klausul dianalisis: <b>${data.total_contract_chunks || 0}</b>
            ${filterInfo}
            ${(data.warnings || []).map(w =>
                `<div class="compliance-warning"><i class="fas fa-triangle-exclamation"></i> ${escapeHtml(w)}</div>`
            ).join('')}
        `;
    }

    // ---- Tabel ----
    function complianceApplyFilter(items) {
        let filtered = [...items];

        if (complianceState.statusFilter) {
            filtered = filtered.filter(it => it.status === complianceState.statusFilter);
        }

        if (complianceState.searchQuery) {
            const q = complianceState.searchQuery.toLowerCase();
            filtered = filtered.filter(it =>
                (it.klausul_ref || '').toLowerCase().includes(q) ||
                (it.klausul_text || '').toLowerCase().includes(q) ||
                (it.regulasi_ref || '').toLowerCase().includes(q) ||
                (it.analisis || '').toLowerCase().includes(q)
            );
        }

        return filtered;
    }

        // ============================================================
    // PENDING ANALYSIS BANNER
    // ============================================================

    function showPendingAnalysisBanner(indices) {
        complianceState.pendingAnalysisIndices = indices || [];
        if (!compliancePendingBanner) return;

        if (complianceState.pendingAnalysisIndices.length === 0) {
            compliancePendingBanner.style.display = 'none';
            return;
        }

        compliancePendingBanner.style.display = 'flex';
        if (compliancePendingText) {
            const n = complianceState.pendingAnalysisIndices.length;
            compliancePendingText.textContent = `${n} klausul baru diimpor tanpa analisis AI.`;
        }
    }

    function hidePendingAnalysisBanner() {
        if (compliancePendingBanner) compliancePendingBanner.style.display = 'none';
        complianceState.pendingAnalysisIndices = [];
    }

    if (complianceDismissPendingBtn) {
        complianceDismissPendingBtn.addEventListener('click', () => {
            hidePendingAnalysisBanner();
            showToast('Banner disembunyikan. Klik "Tambah Klausul" kapan saja untuk analisis.', 'info');
        });
    }

    if (complianceAnalyzePendingBtn) {
        complianceAnalyzePendingBtn.addEventListener('click', async () => {
            const indices = complianceState.pendingAnalysisIndices;
            if (!indices.length) {
                showToast('Tidak ada klausul untuk dianalisis.', 'info');
                return;
            }

            complianceAnalyzePendingBtn.disabled = true;
            complianceAnalyzePendingBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menganalisis...';

            try {
                const run = await runJob(`/api/compliance/${complianceState.resultId}/analyze-items`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_indices: indices }),
                }, {
                    cancelAnchor: complianceAnalyzePendingBtn,
                });

                if (!run.ok) throw new Error(run.error);

                const affected = (run.job.extra && run.job.extra.affected) || 0;
                await reloadComplianceResult();

                // Highlight rows yang baru dianalisis
                setTimeout(() => {
                    indices.forEach(idx => {
                        const row = document.querySelector(`#complianceResultBody tr[data-idx="${idx}"]`);
                        if (row) {
                            row.classList.add('new-row-highlight');
                            setTimeout(() => row.classList.remove('new-row-highlight'), 3500);
                        }
                    });
                }, 300);

                hidePendingAnalysisBanner();
                showToast(`${affected} klausul berhasil dianalisis AI.`, 'success');
            } catch (err) {
                showToast(`Gagal analisis: ${err.message}`, 'error');
            } finally {
                complianceAnalyzePendingBtn.disabled = false;
                complianceAnalyzePendingBtn.innerHTML = '<i class="fas fa-wand-magic-sparkles"></i> Analisis Sekarang';
            }
        });
    }

        function renderComplianceTable(items) {
        if (!complianceResultBody) return;
        const filtered = complianceApplyFilter(items || []);

        if (filtered.length === 0) {
            complianceResultBody.innerHTML = '';
            if (complianceEmptyState) complianceEmptyState.style.display = 'block';
            updateComplianceBulkToolbar();
            updateComplianceSelectAll();
            return;
        }
        if (complianceEmptyState) complianceEmptyState.style.display = 'none';

        complianceResultBody.innerHTML = filtered.map((item, i) => {
            const realIdx = (complianceState.data.items || []).indexOf(item);
            const isChecked = complianceState.selectedRows.has(realIdx);
            const status = item.status || 'PERLU VERIFIKASI';
            const statusClass = complianceStatusClass(status);
            const reviewNotes = (item.validation_notes || []).join(' ');
            const reviewBadge = item.needs_review
                ? `<span class="compliance-review-badge" title="${escapeAttr(reviewNotes || 'Perlu ditinjau auditor')}">
                       <i class="fas fa-flag"></i> Tinjau
                   </span>`
                : '';
            const rowClass = complianceRowClass(status);

            // Custom cell untuk kolom Klausul — gabungkan ref + text
            const klausulRef = item.klausul_ref || '';
            const klausulText = item.klausul_text || '';

            const klausulCell = `
                <td class="editable-cell compliance-klausul-ref" data-idx="${realIdx}">
                    <div class="cell-content multiline compliance-klausul-ref-line"
                         contenteditable="true"
                         spellcheck="false"
                         data-field="klausul_ref"
                         data-original="${escapeAttr(klausulRef)}"
                         title="Referensi klausul (mis. Pasal 6A ayat (1))">${escapeHtml(klausulRef)}</div>
                    <div class="cell-content multiline compliance-klausul-text-line"
                         contenteditable="true"
                         spellcheck="false"
                         data-field="klausul_text"
                         data-original="${escapeAttr(klausulText)}">${escapeHtml(klausulText)}</div>
                </td>`;

            // Cell biasa untuk field lain
                        // Cell biasa dengan placeholder
            const textCell = (field, value, extraCls = '') => {
                const isEmpty = !value || !value.trim();
                const placeholder = field === 'regulasi_ref'
                    ? '⚠ Belum ada regulasi acuan — isi manual atau jalankan "Analisis AI" untuk baris ini'
                    : (field === 'analisis'
                        ? '⚠ Belum dianalisis — isi manual atau jalankan "Analisis AI" untuk baris ini'
                        : '');
                const displayContent = isEmpty && placeholder
                    ? `<span class="cell-placeholder">${placeholder}</span>`
                    : escapeHtml(value);

                return `
                    <td class="editable-cell ${extraCls}" data-idx="${realIdx}">
                        <div class="cell-content multiline ${isEmpty && placeholder ? 'is-empty' : ''}"
                             contenteditable="true"
                             spellcheck="false"
                             data-field="${field}"
                             data-original="${escapeAttr(value)}">${displayContent}</div>
                    </td>`;
            };

            const statusCell = `
                <td class="editable-cell" data-idx="${realIdx}" data-field="status">
                    <div class="cell-content"
                         contenteditable="false"
                         data-original="${escapeAttr(status)}">
                        <span class="compliance-status-pill ${statusClass}">${escapeHtml(complianceStatusLabel(status))}</span>
                        ${reviewBadge}
                    </div>
                </td>`;

            return `
                <tr class="${rowClass} ${isChecked ? 'selected-row' : ''}" data-idx="${realIdx}">
                    <td class="row-checkbox-cell">
                        <input type="checkbox" class="row-checkbox"
                               data-row-idx="${realIdx}"
                               ${isChecked ? 'checked' : ''} />
                    </td>
                    <td class="row-no">${i + 1}</td>
                    ${klausulCell}
                    ${textCell('regulasi_ref', item.regulasi_ref || '')}
                    ${statusCell}
                    ${textCell('analisis', item.analisis || '')}
                    <td class="actions-cell">
                        <button class="row-action-btn" data-delete-idx="${realIdx}" title="Hapus">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

        // Attach editable listeners
        complianceResultBody.querySelectorAll('.cell-content[contenteditable="true"]').forEach(el => {
            el.addEventListener('focus', () => el.classList.add('editing'));
            el.addEventListener('blur', onComplianceCellBlur);
            el.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    el.textContent = el.dataset.original || '';
                    el.blur();
                }
            });
        });

        // Attach row checkbox
        complianceResultBody.querySelectorAll('.row-checkbox').forEach(cb => {
            cb.addEventListener('change', () => {
                const idx = parseInt(cb.dataset.rowIdx, 10);
                if (cb.checked) complianceState.selectedRows.add(idx);
                else complianceState.selectedRows.delete(idx);
                cb.closest('tr').classList.toggle('selected-row', cb.checked);
                updateComplianceBulkToolbar();
                updateComplianceSelectAll();
            });
        });

        // Attach delete
        complianceResultBody.querySelectorAll('[data-delete-idx]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.deleteIdx, 10);
                deleteComplianceSingleRow(idx);
            });
        });

        // Attach status pill click
        complianceResultBody.querySelectorAll('.compliance-status-pill').forEach(pill => {
            pill.addEventListener('click', (e) => {
                e.stopPropagation();
                const td = pill.closest('td');
                const idx = parseInt(td.dataset.idx, 10);
                showComplianceStatusMenu(pill, idx);
            });
        });

        updateComplianceBulkToolbar();
        updateComplianceSelectAll();
    }

    // Status dropdown menu
    function showComplianceStatusMenu(anchorEl, itemIdx) {
        // Hapus menu lama kalau ada
        document.querySelectorAll('.compliance-status-menu').forEach(m => m.remove());

        const menu = document.createElement('div');
        menu.className = 'compliance-status-menu';
        menu.innerHTML = COMPLIANCE_STATUS_OPTIONS.map(s =>
            `<button class="compliance-status-option" data-status="${escapeAttr(s)}">
                <span class="compliance-status-pill ${complianceStatusClass(s)}">${escapeHtml(complianceStatusLabel(s))}</span>
            </button>`
        ).join('');

        document.body.appendChild(menu);

        const rect = anchorEl.getBoundingClientRect();
        menu.style.top = (rect.bottom + 4 + window.scrollY) + 'px';
        menu.style.left = (rect.left + window.scrollX) + 'px';

        menu.querySelectorAll('.compliance-status-option').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const newStatus = btn.dataset.status;
                menu.remove();
                await updateComplianceItemStatus(itemIdx, newStatus);
            });
        });

        // Close on click outside
        setTimeout(() => {
            document.addEventListener('click', function closeMenu() {
                menu.remove();
                document.removeEventListener('click', closeMenu);
            }, { once: true });
        }, 10);
    }

    async function updateComplianceItemStatus(itemIdx, newStatus) {
        if (!complianceState.resultId) return;
        try {
            const res = await fetch(`/api/compliance/${complianceState.resultId}/items/${itemIdx}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: newStatus }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const updated = await res.json();
            if (complianceState.data.items[itemIdx]) {
                Object.assign(complianceState.data.items[itemIdx], updated);
            }
            // Recompute summary
            recomputeComplianceCounts();
            renderComplianceSummary(complianceState.data);
            renderComplianceTable(complianceState.data.items);
            persistComplianceHistory();
            showToast(`Status diubah: ${complianceStatusLabel(newStatus)}`, 'success');
        } catch (err) {
            showToast(`Gagal ubah status: ${err.message}`, 'error');
        }
    }

    function recomputeComplianceCounts() {
        if (!complianceState.data || !complianceState.data.items) return;
        const items = complianceState.data.items;
        let patuh = 0, catatan = 0, tidak = 0, relevan = 0, verifikasi = 0;
        items.forEach(it => {
            if (it.status === 'PATUH') patuh++;
            else if (it.status === 'PATUH DENGAN CATATAN') catatan++;
            else if (it.status === 'TIDAK PATUH') tidak++;
            else if (it.status === 'TIDAK RELEVAN') relevan++;
            else verifikasi++;
        });
        complianceState.data.total_items = items.length;
        complianceState.data.total_patuh = patuh;
        complianceState.data.total_patuh_catatan = catatan;
        complianceState.data.total_tidak_patuh = tidak;
        complianceState.data.total_tidak_relevan = relevan;
        complianceState.data.total_perlu_verifikasi = verifikasi;
    }

        async function onComplianceCellBlur(e) {
        const el = e.target;
        el.classList.remove('editing');
        if (el.querySelector('.cell-placeholder')) {
            el.innerHTML = `<span class="cell-placeholder">${el.querySelector('.cell-placeholder').textContent}</span>`;
            return;
        }

        const newValue = (el.innerText || '').trim();
        const original = el.dataset.original || '';
        if (newValue === original) return;

                const td = el.closest('td');
        const idx = parseInt(td.dataset.idx, 10);
        const field = el.dataset.field || td.dataset.field;
        if (!complianceState.data || !complianceState.data.items[idx]) return;

        complianceState.data.items[idx][field] = newValue;

        try {
            const res = await fetch(`/api/compliance/${complianceState.resultId}/items/${idx}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [field]: newValue }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const updated = await res.json();
            Object.assign(complianceState.data.items[idx], updated);
            el.dataset.original = newValue;
            el.classList.add('saved-flash');
            setTimeout(() => el.classList.remove('saved-flash'), 800);
            persistComplianceHistory();
            showToast('Tersimpan', 'success');
        } catch (err) {
            complianceState.data.items[idx][field] = original;
            el.textContent = original;
            showToast(`Gagal menyimpan: ${err.message}`, 'error');
        }
    }

    // ---- Bulk toolbar ----
    function updateComplianceBulkToolbar() {
        if (!complianceBulkToolbar) return;
        const count = complianceState.selectedRows.size;
        if (count === 0) {
            complianceBulkToolbar.style.display = 'none';
        } else {
            complianceBulkToolbar.style.display = 'flex';
            complianceBulkCount.textContent = `${count} dipilih`;
        }
        if (complianceBulkStatusSelect) complianceBulkStatusSelect.value = '';
    }

    function updateComplianceSelectAll() {
        if (!complianceSelectAllCheckbox) return;
        if (!complianceState.data || !complianceState.data.items) {
            complianceSelectAllCheckbox.checked = false;
            complianceSelectAllCheckbox.indeterminate = false;
            return;
        }
        const visible = complianceApplyFilter(complianceState.data.items);
        const visibleIndices = visible.map(it => complianceState.data.items.indexOf(it));
        const selectedVisible = visibleIndices.filter(i => complianceState.selectedRows.has(i));
        const all = visibleIndices.length > 0 && selectedVisible.length === visibleIndices.length;
        const partial = selectedVisible.length > 0 && !all;
        complianceSelectAllCheckbox.checked = all;
        complianceSelectAllCheckbox.indeterminate = partial;
    }

    if (complianceSelectAllCheckbox) {
        complianceSelectAllCheckbox.addEventListener('change', (e) => {
            if (!complianceState.data || !complianceState.data.items) return;
            const visible = complianceApplyFilter(complianceState.data.items);
            const visibleIndices = visible.map(it => complianceState.data.items.indexOf(it));
            if (e.target.checked) visibleIndices.forEach(i => complianceState.selectedRows.add(i));
            else visibleIndices.forEach(i => complianceState.selectedRows.delete(i));
            renderComplianceTable(complianceState.data.items);
        });
    }

    if (complianceBulkClearBtn) {
        complianceBulkClearBtn.addEventListener('click', () => {
            complianceState.selectedRows.clear();
            renderComplianceTable(complianceState.data.items);
        });
    }

    if (complianceBulkStatusSelect) {
        complianceBulkStatusSelect.addEventListener('change', async () => {
            const newStatus = complianceBulkStatusSelect.value;
            if (!newStatus || complianceState.selectedRows.size === 0) return;

            const indices = Array.from(complianceState.selectedRows);
            complianceBulkStatusSelect.disabled = true;

            try {
                const res = await fetch(`/api/compliance/${complianceState.resultId}/items/bulk`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_indices: indices, status: newStatus }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                const data = await res.json();

                indices.forEach(i => {
                    if (complianceState.data.items[i]) {
                        complianceState.data.items[i].status = newStatus;
                        complianceState.data.items[i].needs_review = newStatus === 'PERLU VERIFIKASI';
                    }
                });
                complianceState.data.total_patuh = data.total_patuh;
                complianceState.data.total_patuh_catatan = data.total_patuh_catatan;
                complianceState.data.total_tidak_patuh = data.total_tidak_patuh;
                complianceState.data.total_tidak_relevan = data.total_tidak_relevan;
                complianceState.data.total_perlu_verifikasi = data.total_perlu_verifikasi || 0;

                complianceState.selectedRows.clear();
                renderComplianceSummary(complianceState.data);
                renderComplianceTable(complianceState.data.items);
                showToast(`${data.affected} klausul diubah ke ${complianceStatusLabel(newStatus)}.`, 'success');
            } catch (err) {
                showToast(`Gagal update: ${err.message}`, 'error');
            } finally {
                complianceBulkStatusSelect.disabled = false;
                complianceBulkStatusSelect.value = '';
            }
        });
    }

    if (complianceBulkDeleteBtn) {
        complianceBulkDeleteBtn.addEventListener('click', async () => {
            if (complianceState.selectedRows.size === 0) return;
            if (!confirm(`Hapus ${complianceState.selectedRows.size} klausul terpilih?`)) return;

            const indices = Array.from(complianceState.selectedRows);
            complianceBulkDeleteBtn.disabled = true;

            try {
                const res = await fetch(`/api/compliance/${complianceState.resultId}/items`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_indices: indices }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                await reloadComplianceResult();
                complianceState.selectedRows.clear();
                showToast(`${indices.length} klausul dihapus.`, 'success');
            } catch (err) {
                showToast(`Gagal menghapus: ${err.message}`, 'error');
            } finally {
                complianceBulkDeleteBtn.disabled = false;
            }
        });
    }

    async function deleteComplianceSingleRow(idx) {
        if (!complianceState.data || !complianceState.data.items[idx]) return;
        if (!confirm('Hapus klausul ini?')) return;

        try {
            const res = await fetch(`/api/compliance/${complianceState.resultId}/items`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_indices: [idx] }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            await reloadComplianceResult();
            complianceState.selectedRows.clear();
            showToast('Klausul dihapus.', 'success');
        } catch (err) {
            showToast(`Gagal menghapus: ${err.message}`, 'error');
        }
    }

        function persistComplianceHistory() {
        if (!complianceState.data) return;
        const hIdx = state.history.findIndex(h => h.id === complianceState.resultId);
        if (hIdx >= 0) {
            const d = complianceState.data;
            state.history[hIdx].total_items = d.total_items;
            state.history[hIdx].total_patuh = d.total_patuh;
            state.history[hIdx].total_patuh_catatan = d.total_patuh_catatan;
            state.history[hIdx].total_tidak_patuh = d.total_tidak_patuh;
            state.history[hIdx].total_tidak_relevan = d.total_tidak_relevan;
            state.history[hIdx].total_perlu_verifikasi = d.total_perlu_verifikasi || 0;
            state.history[hIdx].items = d.items;
            state.history[hIdx].executive_summary = d.executive_summary || '';
            localStorage.setItem('rta_history', JSON.stringify(state.history));
        }
    }

        function highlightNewComplianceRows(startIdx, count) {
        if (count <= 0) return;
        setTimeout(() => {
            const rows = [];
            for (let i = 0; i < count; i++) {
                const row = document.querySelector(`#complianceResultBody tr[data-idx="${startIdx + i}"]`);
                if (row) rows.push(row);
            }
            if (rows.length === 0) return;

            // Scroll ke row pertama
            rows[0].scrollIntoView({ behavior: 'smooth', block: 'center' });

            // Flash animation
            rows.forEach(row => {
                row.classList.add('new-row-highlight');
                setTimeout(() => row.classList.remove('new-row-highlight'), 3500);
            });
        }, 300);
    }

    async function reloadComplianceResult() {
        try {
            const res = await fetch(`/api/compliance/${complianceState.resultId}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            complianceState.data = data;
            renderComplianceSummary(data);
            renderComplianceMeta(data);
            renderComplianceTable(data.items);
            renderComplianceExecutiveSummary(data.executive_summary || '');
        } catch (err) {
            showToast(`Gagal memuat ulang: ${err.message}`, 'error');
        }
    }

    // ---- Search / Filter ----
    if (complianceSearchInput) {
        complianceSearchInput.addEventListener('input', (e) => {
            complianceState.searchQuery = e.target.value;
            if (complianceState.data) renderComplianceTable(complianceState.data.items);
        });
    }

    if (complianceStatusFilter) {
        complianceStatusFilter.addEventListener('change', (e) => {
            complianceState.statusFilter = e.target.value;
            if (complianceState.data) renderComplianceTable(complianceState.data.items);
        });
    }

    // ---- Executive Summary ----
    function renderComplianceExecutiveSummary(text) {
        if (!complianceExecutiveSummary) return;
        if (!text) {
            complianceExecutiveSummary.innerHTML = '<em>Belum ada ringkasan eksekutif.</em>';
            return;
        }
        // Konversi markdown ringan
        let html = escapeHtml(text);
        // Bold **text**
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        // Split per baris
        const lines = html.split('\n');
        const rendered = lines.map(line => {
            const trimmed = line.trim();
            if (!trimmed) return '<span class="summary-line">&nbsp;</span>';
            // Heading: diawali ** atau angka+.
            if (/^\d+\./.test(trimmed) || trimmed.startsWith('<strong>')) {
                return `<span class="summary-heading">${trimmed}</span>`;
            }
            return `<span class="summary-line">${trimmed}</span>`;
        }).join('');
        complianceExecutiveSummary.innerHTML = rendered;
    }

    if (complianceEditSummaryBtn) {
        complianceEditSummaryBtn.addEventListener('click', () => {
            if (!complianceState.data) return;
            complianceExecutiveSummaryTextarea.value = complianceState.data.executive_summary || '';
            complianceExecutiveSummary.style.display = 'none';
            complianceExecutiveSummaryEdit.style.display = 'flex';
            complianceExecutiveSummaryTextarea.focus();
        });
    }

    if (complianceCancelSummaryBtn) {
        complianceCancelSummaryBtn.addEventListener('click', () => {
            complianceExecutiveSummary.style.display = 'block';
            complianceExecutiveSummaryEdit.style.display = 'none';
        });
    }

    if (complianceSaveSummaryBtn) {
        complianceSaveSummaryBtn.addEventListener('click', async () => {
            const newSummary = complianceExecutiveSummaryTextarea.value;
            complianceSaveSummaryBtn.disabled = true;
            complianceSaveSummaryBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';

            try {
                const res = await fetch(`/api/compliance/${complianceState.resultId}/executive-summary`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ executive_summary: newSummary }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                const data = await res.json();
                complianceState.data.executive_summary = data.executive_summary;
                renderComplianceExecutiveSummary(data.executive_summary);
                complianceExecutiveSummary.style.display = 'block';
                complianceExecutiveSummaryEdit.style.display = 'none';
                persistComplianceHistory();
                showToast('Ringkasan eksekutif tersimpan.', 'success');
            } catch (err) {
                showToast(`Gagal menyimpan: ${err.message}`, 'error');
            } finally {
                complianceSaveSummaryBtn.disabled = false;
                complianceSaveSummaryBtn.innerHTML = '<i class="fas fa-floppy-disk"></i> Simpan';
            }
        });
    }

        // ---- Import PDF: DOM refs ----
    const complianceInsertAfter = $('#complianceInsertAfter');
    const complianceModalTabs = $$('.compliance-modal-tab');
    const complianceModalTabContents = $$('.compliance-modal-tab-content');
    const complianceImportZone = $('#complianceImportZone');
    const complianceImportFile = $('#complianceImportFile');
    const complianceImportPreviewWrap = $('#complianceImportPreviewWrap');
    const complianceImportPreview = $('#complianceImportPreview');

    // State untuk import PDF
    const complianceImportState = {
        activeTab: 'manual',   // 'manual' | 'pdf'
        parsedClauses: [],     // dari /api/compliance/parse-contract
        selectedIndices: new Set(),
    };

    function switchComplianceModalTab(tabName) {
        complianceImportState.activeTab = tabName;

        complianceModalTabs.forEach(tab => {
            tab.classList.toggle('active', tab.dataset.complianceTab === tabName);
        });
        complianceModalTabContents.forEach(content => {
            content.style.display = content.dataset.complianceTabContent === tabName ? 'flex' : 'none';
        });

        // Update tombol save label
        if (complianceAddRowSaveBtn) {
            if (tabName === 'pdf') {
                const count = complianceImportState.selectedIndices.size;
                complianceAddRowSaveBtn.innerHTML = count > 0
                    ? `<i class="fas fa-plus"></i> Impor ${count} Klausul`
                    : '<i class="fas fa-plus"></i> Impor Klausul';
            } else {
                complianceAddRowSaveBtn.innerHTML = '<i class="fas fa-plus"></i> Tambah Klausul';
            }
        }
    }

    complianceModalTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            switchComplianceModalTab(tab.dataset.complianceTab);
        });
    });

    // ---- Import PDF: upload handler ----
    if (complianceImportZone) {
        complianceImportZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            complianceImportZone.classList.add('dragover');
        });
        complianceImportZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            complianceImportZone.classList.remove('dragover');
        });
        complianceImportZone.addEventListener('drop', (e) => {
            e.preventDefault();
            complianceImportZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                complianceImportFile.files = e.dataTransfer.files;
                handleImportFileSelected();
            }
        });
    }

    if (complianceImportFile) {
        complianceImportFile.addEventListener('change', handleImportFileSelected);
    }

    async function handleImportFileSelected() {
        if (!complianceImportFile || !complianceImportFile.files.length) return;

        const file = complianceImportFile.files[0];
        if (file.size > 10 * 1024 * 1024) {
            showToast('File terlalu besar. Maks 10 MB.', 'error');
            return;
        }

        complianceImportPreviewWrap.style.display = 'block';
        complianceImportPreview.innerHTML = `
            <div class="compliance-import-loading">
                <i class="fas fa-spinner fa-spin"></i> Mem-parse ${escapeHtml(file.name)}...
            </div>
        `;

        try {
            const fd = new FormData();
            fd.append('file', file);

            const res = await fetch('/api/compliance/parse-contract', {
                method: 'POST',
                body: fd,
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || `HTTP ${res.status}`);
            }

            complianceImportState.parsedClauses = data.clauses || [];
            complianceImportState.selectedIndices = new Set();

            // Default: pilih semua
            complianceImportState.parsedClauses.forEach((_, i) => {
                complianceImportState.selectedIndices.add(i);
            });

            renderComplianceImportPreview(data.filename);
            switchComplianceModalTab('pdf');
        } catch (err) {
            complianceImportPreview.innerHTML = `
                <div class="compliance-import-loading" style="color:var(--warn);">
                    <i class="fas fa-exclamation-circle"></i>
                    Gagal parse: ${escapeHtml(err.message)}
                </div>
            `;
        }
    }

    function renderComplianceImportPreview(filename) {
        const clauses = complianceImportState.parsedClauses;
        if (!clauses.length) {
            complianceImportPreview.innerHTML = `
                <div class="compliance-import-loading">
                    <i class="fas fa-info-circle"></i>
                    Tidak ada klausul terdeteksi.
                </div>
            `;
            return;
        }

        const itemsHtml = clauses.map((c, i) => {
            const ref = c.klausul_ref || c.pasal || `Klausul ${i + 1}`;
            const text = (c.text || '').slice(0, 200) + ((c.text || '').length > 200 ? '...' : '');
            const checked = complianceImportState.selectedIndices.has(i) ? 'checked' : '';
            return `
                <label class="compliance-import-item" data-import-idx="${i}">
                    <input type="checkbox" data-import-check="${i}" ${checked} />
                    <div class="compliance-import-item-body">
                        <div class="compliance-import-item-ref">${escapeHtml(ref)}</div>
                        <div class="compliance-import-item-text">${escapeHtml(text)}</div>
                    </div>
                </label>
            `;
        }).join('');

        complianceImportPreview.innerHTML = `
            <div class="compliance-import-preview-header">
                <div>
                    <strong>${escapeHtml(filename)}</strong>
                    <span class="preview-count">
                        <span id="complianceImportSelectedCount">${complianceImportState.selectedIndices.size}</span>
                        / ${clauses.length} dipilih
                    </span>
                </div>
                <div class="compliance-import-preview-actions">
                    <button type="button" id="complianceImportSelectAll">Pilih Semua</button>
                    <button type="button" id="complianceImportClearAll">Kosongkan</button>
                </div>
            </div>
            ${itemsHtml}
        `;

        // Attach checkbox listeners
        complianceImportPreview.querySelectorAll('[data-import-check]').forEach(cb => {
            cb.addEventListener('change', (e) => {
                e.stopPropagation();
                const i = parseInt(cb.dataset.importCheck, 10);
                if (cb.checked) complianceImportState.selectedIndices.add(i);
                else complianceImportState.selectedIndices.delete(i);
                updateImportSelectedCount();
            });
        });

        // Klik row = toggle checkbox
        complianceImportPreview.querySelectorAll('.compliance-import-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT') return;
                const cb = item.querySelector('input[type="checkbox"]');
                if (cb) {
                    cb.checked = !cb.checked;
                    cb.dispatchEvent(new Event('change'));
                }
            });
        });

        // Select all / clear
        const selectAllBtn = document.getElementById('complianceImportSelectAll');
        const clearAllBtn = document.getElementById('complianceImportClearAll');

        if (selectAllBtn) {
            selectAllBtn.addEventListener('click', (e) => {
                e.preventDefault();
                complianceImportState.selectedIndices = new Set(clauses.map((_, i) => i));
                complianceImportPreview.querySelectorAll('[data-import-check]').forEach(cb => {
                    cb.checked = true;
                });
                updateImportSelectedCount();
            });
        }
        if (clearAllBtn) {
            clearAllBtn.addEventListener('click', (e) => {
                e.preventDefault();
                complianceImportState.selectedIndices.clear();
                complianceImportPreview.querySelectorAll('[data-import-check]').forEach(cb => {
                    cb.checked = false;
                });
                updateImportSelectedCount();
            });
        }
    }

    function updateImportSelectedCount() {
        const countEl = document.getElementById('complianceImportSelectedCount');
        if (countEl) {
            countEl.textContent = complianceImportState.selectedIndices.size;
        }
        // Update tombol save
        if (complianceAddRowSaveBtn && complianceImportState.activeTab === 'pdf') {
            const count = complianceImportState.selectedIndices.size;
            complianceAddRowSaveBtn.innerHTML = count > 0
                ? `<i class="fas fa-plus"></i> Impor ${count} Klausul`
                : '<i class="fas fa-plus"></i> Impor Klausul';
        }
    }

    // ---- Modal Open / Close ----
    function openComplianceAddRowModal() {
        // Reset manual tab
        if (complianceAddKlausulRef) complianceAddKlausulRef.value = '';
        if (complianceAddKlausulText) complianceAddKlausulText.value = '';
        if (complianceAddRegulasiRef) complianceAddRegulasiRef.value = '';
        if (complianceAddStatus) complianceAddStatus.value = 'TIDAK RELEVAN';
        if (complianceAddAnalisis) complianceAddAnalisis.value = '';

        // Reset insert after
        if (complianceInsertAfter) complianceInsertAfter.value = '';

        // Reset import state
        complianceImportState.parsedClauses = [];
        complianceImportState.selectedIndices = new Set();
        if (complianceImportFile) complianceImportFile.value = '';
        if (complianceImportPreviewWrap) complianceImportPreviewWrap.style.display = 'none';
        if (complianceImportPreview) complianceImportPreview.innerHTML = '';

        // Switch ke tab manual
        switchComplianceModalTab('manual');

        if (complianceAddRowModalOverlay) complianceAddRowModalOverlay.style.display = 'flex';
        if (complianceAddKlausulRef) complianceAddKlausulRef.focus();
    }

    function closeComplianceAddRowModal() {
        if (complianceAddRowModalOverlay) complianceAddRowModalOverlay.style.display = 'none';

        if (complianceImportFile) complianceImportFile.value = '';
        complianceImportState.parsedClauses = [];
        complianceImportState.selectedIndices = new Set();
        complianceImportState.activeTab = 'manual';
    }

    if (complianceAddRowBtn) complianceAddRowBtn.addEventListener('click', openComplianceAddRowModal);
    if (complianceAddRowModalClose) complianceAddRowModalClose.addEventListener('click', closeComplianceAddRowModal);
    if (complianceAddRowCancelBtn) complianceAddRowCancelBtn.addEventListener('click', closeComplianceAddRowModal);
    if (complianceAddRowModalOverlay) {
        complianceAddRowModalOverlay.addEventListener('click', (e) => {
            if (e.target === complianceAddRowModalOverlay) closeComplianceAddRowModal();
        });
    }

        if (complianceAddRowSaveBtn) {
        complianceAddRowSaveBtn.addEventListener('click', async () => {
            const tab = complianceImportState.activeTab;

            // Baca insert_after
            let insertAfter = null;
            if (complianceInsertAfter && complianceInsertAfter.value.trim()) {
                const v = parseInt(complianceInsertAfter.value, 10);
                if (!isNaN(v) && v >= 0) insertAfter = v;
            }

            if (tab === 'manual') {
                // === MODE MANUAL ===
                if (!complianceAddKlausulRef.value.trim() && !complianceAddAnalisis.value.trim()) {
                    showToast('Isi minimal: Klausul atau Analisis.', 'error');
                    return;
                }

                complianceAddRowSaveBtn.disabled = true;
                complianceAddRowSaveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';

                const payload = {
                    klausul_ref: complianceAddKlausulRef ? complianceAddKlausulRef.value.trim() : '',
                    klausul_text: complianceAddKlausulText ? complianceAddKlausulText.value.trim() : '',
                    regulasi_ref: complianceAddRegulasiRef ? complianceAddRegulasiRef.value.trim() : '',
                    status: complianceAddStatus ? complianceAddStatus.value : 'TIDAK RELEVAN',
                    analisis: complianceAddAnalisis ? complianceAddAnalisis.value.trim() : '',
                    insert_after: insertAfter,
                };

                try {
                    const res = await fetch(`/api/compliance/${complianceState.resultId}/items`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || `HTTP ${res.status}`);
                    }
                    await reloadComplianceResult();
                    closeComplianceAddRowModal();
                    const posMsg = insertAfter !== null ? ` (setelah baris ${insertAfter})` : ' di akhir';
                    showToast(`Klausul ditambahkan${posMsg}.`, 'success');
                } catch (err) {
                    showToast(`Gagal menambah: ${err.message}`, 'error');
                } finally {
                    complianceAddRowSaveBtn.disabled = false;
                    complianceAddRowSaveBtn.innerHTML = '<i class="fas fa-plus"></i> Tambah Klausul';
                }

            } else {
                // === MODE IMPORT PDF ===
                const selected = complianceImportState.selectedIndices;
                if (selected.size === 0) {
                    showToast('Pilih minimal 1 klausul untuk diimpor.', 'error');
                    return;
                }

                const itemsToImport = Array.from(selected)
                    .sort((a, b) => a - b)
                    .map(i => complianceImportState.parsedClauses[i])
                    .filter(Boolean)
                    .map(c => ({
                        klausul_ref: c.klausul_ref || c.pasal || '',
                        klausul_text: c.text || '',
                        regulasi_ref: '',
                        // Belum dianalisis → bukan "Tidak Relevan"
                        status: 'PERLU VERIFIKASI',
                        analisis: '',
                    }));

                complianceAddRowSaveBtn.disabled = true;
                console.log('🔍 [DEBUG] itemsToImport:', JSON.parse(JSON.stringify(itemsToImport)));
                complianceAddRowSaveBtn.disabled = true;
                complianceAddRowSaveBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Mengimpor ${itemsToImport.length} klausul...`;

                try {
                    const res = await fetch(`/api/compliance/${complianceState.resultId}/items/batch-add`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            items: itemsToImport,
                            insert_after: insertAfter,
                        }),
                    });
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || `HTTP ${res.status}`);
                    }
                                        const data = await res.json();
                    await reloadComplianceResult();
                    closeComplianceAddRowModal();

                    // Kumpulkan indices yang baru diimpor
                    const firstNewIdx = (insertAfter !== null)
                        ? insertAfter
                        : (complianceState.data.items.length - data.affected);
                    const newIndices = [];
                    for (let k = 0; k < data.affected; k++) {
                        newIndices.push(firstNewIdx + k);
                    }

                    // Highlight row baru
                    highlightNewComplianceRows(firstNewIdx, data.affected);

                    // Tampilkan banner pending analysis
                    showPendingAnalysisBanner(newIndices);

                    const posMsg = insertAfter !== null ? ` setelah baris ${insertAfter}` : ' di akhir';
                    showToast(`${data.affected} klausul diimpor${posMsg}. Klik "Analisis Sekarang" untuk AI.`, 'success');
                } catch (err) {
                    showToast(`Gagal import: ${err.message}`, 'error');
                } finally {
                    complianceAddRowSaveBtn.disabled = false;
                    complianceAddRowSaveBtn.innerHTML = '<i class="fas fa-plus"></i> Tambah Klausul';
                }
            }
        });
    }

    // ---- Copy Markdown ----
    if (complianceCopyMdBtn) {
        complianceCopyMdBtn.addEventListener('click', async () => {
            if (!complianceState.resultId) return;
            try {
                const res = await fetch(`/api/compliance/${complianceState.resultId}/markdown`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                await navigator.clipboard.writeText(data.markdown);
                showToast('Markdown disalin ke clipboard.', 'success');
            } catch (err) {
                showToast(`Gagal copy: ${err.message}`, 'error');
            }
        });
    }

    // ---- Export Excel ----
    if (complianceExportBtn) {
        complianceExportBtn.addEventListener('click', () => {
            if (complianceState.resultId) {
                window.location.href = `/api/compliance/export/${complianceState.resultId}`;
                showToast('Mengekspor ke Excel...', 'info');
            }
        });
    }
        const complianceExportPdfBtn = $('#complianceExportPdfBtn');
    if (complianceExportPdfBtn) {
        complianceExportPdfBtn.addEventListener('click', () => {
            if (complianceState.resultId) {
                window.location.href = `/api/compliance/export-pdf/${complianceState.resultId}`;
                showToast('Mengekspor ke PDF...', 'info');
            }
        });
    }

    // ---- Clear Result ----
    if (complianceClearResultBtn) {
        complianceClearResultBtn.addEventListener('click', () => {
            complianceResultSection.style.display = 'none';
            complianceState.resultId = null;
            complianceState.data = null;
            complianceState.selectedRows.clear();
            hidePendingAnalysisBanner();
            if (complianceExportBtn) complianceExportBtn.disabled = true;
            setComplianceStatus('Hasil ditutup. Upload kontrak baru.', false);
        });
    }

       if (complianceResetBtn) {
        complianceResetBtn.addEventListener('click', () => {
            // Reset file kontrak
            if (complianceContractFile) complianceContractFile.value = '';
            if (complianceContractFileName) {
                complianceContractFileName.textContent = '';
                complianceContractFileName.style.display = 'none';
            }

            // Reset file regulasi manual
            if (complianceRegulationFiles) complianceRegulationFiles.value = '';
            if (complianceRegulationFileNames) {
                complianceRegulationFileNames.innerHTML = '';
                complianceRegulationFileNames.style.display = 'none';
                complianceRegulationFileNames.classList.remove('multi');
            }

            // Reset input text
            if (complianceNamaKontrak) complianceNamaKontrak.value = '';
            if (complianceFilterKontrak) complianceFilterKontrak.value = '';

            // Reset DB selection
            complianceModeState.dbSelectedIds.clear();
            if (complianceDbList) {
                complianceDbList.querySelectorAll('[data-db-check-id]').forEach(cb => {
                    cb.checked = false;
                    const label = cb.closest('.compliance-db-item');
                    if (label) label.classList.remove('selected');
                });
            }

            // Reset mode ke manual
            switchComplianceMode('manual');

            // Reset result state
            complianceState.resultId = null;
            complianceState.data = null;
            complianceState.selectedRows = new Set();
            complianceResultSection.style.display = 'none';
            hidePendingAnalysisBanner();

            if (complianceExportBtn) complianceExportBtn.disabled = true;
            if (complianceExportPdfBtn) complianceExportPdfBtn.disabled = true;

            setComplianceStatus('Menunggu file...', false);
            showToast('Form dibersihkan.', 'info');
        });
    }

    // ---- Main Submit Handler ----
        if (complianceUploadForm) {
        complianceUploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            // === Validasi shared: kontrak ===
            if (!complianceContractFile || !complianceContractFile.files.length) {
                setComplianceStatus('Pilih file kontrak terlebih dahulu.', true);
                showToast('File kontrak belum dipilih.', 'error');
                return;
            }

            const contractFile = complianceContractFile.files[0];
            if (contractFile.size > 10 * 1024 * 1024) {
                setComplianceStatus('Kontrak terlalu besar. Maks 10MB.', true);
                showToast('File kontrak terlalu besar.', 'error');
                return;
            }

            // === Validasi per mode ===
            if (complianceModeState.current === 'manual') {
                if (!complianceRegulationFiles || !complianceRegulationFiles.files.length) {
                    setComplianceStatus('Pilih minimal 1 file regulasi.', true);
                    showToast('File regulasi belum dipilih.', 'error');
                    return;
                }
            } else {
                // Database mode
                if (complianceModeState.dbSelectedIds.size === 0) {
                    setComplianceStatus('Pilih minimal 1 regulasi dari database.', true);
                    showToast('Belum ada regulasi dipilih dari database.', 'error');
                    return;
                }
            }

            complianceSubmitBtn.disabled = true;
            complianceResultSection.style.display = 'none';
            setComplianceStatus('Memproses dokumen...', null);
            setComplianceProgress(10, 'Meng-upload file...');

            const namaInput = complianceNamaKontrak ? complianceNamaKontrak.value.trim() : '';
            const filterInput = complianceFilterKontrak ? complianceFilterKontrak.value.trim() : '';

            try {
                let data;

                if (complianceModeState.current === 'manual') {
                    // ============ MODE MANUAL (existing flow) ============
                    setComplianceProgress(20, 'Mem-parse kontrak & regulasi...');

                    const fd = new FormData();
                    fd.append('contract_file', contractFile);
                    Array.from(complianceRegulationFiles.files).forEach(f => {
                        fd.append('regulation_files', f);
                    });

                    const previewRes = await fetch('/api/compliance/preview', {
                        method: 'POST',
                        body: fd,
                    });
                    const previewData = await previewRes.json();

                    if (!previewRes.ok) {
                        setComplianceStatus(`Gagal: ${previewData.detail || 'Error.'}`, true);
                        showToast('Gagal preview: ' + (previewData.detail || 'Server error'), 'error');
                        hideComplianceProgress();
                        return;
                    }

                    setComplianceProgress(50, `Kontrak: ${previewData.total_contract_chunks} klausul. AI menganalisis...`);
                    setComplianceStatus('AI sedang melakukan compliance review...', null);

                    const run = await runJob('/api/compliance/analyze', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            preview_id: previewData.preview_id,
                            nama_kontrak: namaInput || contractFile.name.replace(/\.[^.]+$/, ''),
                            filter_kontrak: filterInput || null,
                        }),
                    }, {
                        cancelAnchor: complianceProgressText,
                        onProgress: (job, pct, label) => setComplianceProgress(50 + pct * 0.5, label),
                    });

                    if (!run.ok) {
                        setComplianceStatus(`Gagal: ${run.error}`, true);
                        showToast(run.cancelled ? 'Compliance review dibatalkan.' : 'Gagal analisis: ' + run.error,
                            run.cancelled ? 'info' : 'error');
                        hideComplianceProgress();
                        return;
                    }
                    data = run.data;
                } else {
                    // ============ MODE DATABASE (RAG) ============
                    setComplianceProgress(20, 'Menyiapkan regulasi dari database...');

                    const regIds = Array.from(complianceModeState.dbSelectedIds);
                    if (regIds.length === 0) {
                        setComplianceStatus('Pilih minimal 1 regulasi.', true);
                        hideComplianceProgress();
                        return;
                    }

                    setComplianceProgress(35, `Retrieving ${regIds.length} regulasi relevan...`);
                    setComplianceStatus('AI menganalisis dengan RAG (retrieval + review)...', null);

                    const fd = new FormData();
                    fd.append('contract_file', contractFile);
                    fd.append('regulation_ids', regIds.join(','));
                    if (namaInput) fd.append('nama_kontrak', namaInput);
                    if (filterInput) fd.append('filter_kontrak', filterInput);
                    fd.append('top_k_per_clause', '5');

                    const run = await runJob('/api/compliance/analyze-from-db', {
                        method: 'POST',
                        body: fd,
                    }, {
                        cancelAnchor: complianceProgressText,
                        onProgress: (job, pct, label) => setComplianceProgress(35 + pct * 0.65, label),
                    });

                    if (!run.ok) {
                        setComplianceStatus(`Gagal: ${run.error}`, true);
                        showToast(run.cancelled ? 'Compliance review dibatalkan.' : 'Gagal analisis: ' + run.error,
                            run.cancelled ? 'info' : 'error');
                        hideComplianceProgress();
                        return;
                    }
                    data = run.data;
                }

                // === SUKSES — render hasil ===
                setComplianceProgress(100, 'Selesai!');
                setComplianceStatus(`Selesai. ${data.total_items} klausul dianalisis.`, false);

                complianceState.previewId = data.preview_id || '';
                complianceState.resultId = data.result_id;
                complianceState.data = data;
                complianceState.selectedRows = new Set();
                complianceState.searchQuery = '';
                complianceState.statusFilter = '';
                if (complianceSearchInput) complianceSearchInput.value = '';
                if (complianceStatusFilter) complianceStatusFilter.value = '';

                hidePendingAnalysisBanner();

                renderComplianceSummary(data);
                renderComplianceMeta(data);
                renderComplianceTable(data.items || []);
                renderComplianceExecutiveSummary(data.executive_summary || '');

                if (complianceExportBtn) complianceExportBtn.disabled = false;
                if (complianceExportPdfBtn) complianceExportPdfBtn.disabled = false;

                complianceResultSection.style.display = 'block';
                complianceResultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

                saveToHistory(data, 'compliance_review');
                showToast('Compliance review selesai! 🎉', 'success');

            } catch (err) {
                setComplianceStatus(`Gagal: ${err.message}`, true);
                showToast('Gagal terhubung ke server.', 'error');
            } finally {
                complianceSubmitBtn.disabled = false;
                if (complianceModeState.current === 'database') {
                    complianceSubmitBtn.innerHTML = '<i class="fas fa-database"></i> Analisis (Database)';
                } else {
                    complianceSubmitBtn.innerHTML = '<i class="fas fa-gavel"></i> Mulai Compliance Review';
                }
                setTimeout(hideComplianceProgress, 2000);
            }
        });
    }

    // ---- Cleanup on page change ----
    // (dipanggil di switchPage saat pindah away)

        // ============================================================
    // COMPLIANCE MODE SELECTOR (Manual vs Database)
    // ============================================================

    const complianceModeState = {
        current: 'manual',          // 'manual' | 'database'
        dbRegulations: [],
        dbSelectedIds: new Set(),
        dbLoaded: false,
    };

    const complianceModeBtns = $$('.compliance-mode-btn');
    const complianceModeManual = $('#complianceModeManual');
    const complianceModeDatabase = $('#complianceModeDatabase');
    const complianceDbLoading = $('#complianceDbLoading');
    const complianceDbEmpty = $('#complianceDbEmpty');
    const complianceDbList = $('#complianceDbList');
    const complianceDbCount = $('#complianceDbCount');

    // ---- Switch Mode ----
    function switchComplianceMode(mode) {
        complianceModeState.current = mode;

        // Update button state
        complianceModeBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.complianceMode === mode);
        });

        // Show/hide content
        if (complianceModeManual) {
            complianceModeManual.style.display = mode === 'manual' ? '' : 'none';
        }
        if (complianceModeDatabase) {
            complianceModeDatabase.style.display = mode === 'database' ? '' : 'none';
        }

        // Update tombol submit label
        if (complianceSubmitBtn) {
            if (mode === 'database') {
                complianceSubmitBtn.innerHTML = '<i class="fas fa-database"></i> Analisis (Database)';
            } else {
                complianceSubmitBtn.innerHTML = '<i class="fas fa-gavel"></i> Mulai Compliance Review';
            }
        }

        // Toggle required attribute
        if (complianceRegulationFiles) {
            if (mode === 'manual') {
                complianceRegulationFiles.setAttribute('required', 'required');
            } else {
                complianceRegulationFiles.removeAttribute('required');
            }
        }

        // Load DB list kalau mode database dan belum loaded
        if (mode === 'database' && !complianceModeState.dbLoaded) {
            loadComplianceDbList();
        }
    }

    // Attach click handlers
    complianceModeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const mode = btn.dataset.complianceMode;
            if (mode !== complianceModeState.current) {
                switchComplianceMode(mode);
            }
        });
    });

    // ---- Load DB List ----
    async function loadComplianceDbList() {
        if (!complianceDbList) return;

        if (complianceDbLoading) complianceDbLoading.style.display = 'flex';
        if (complianceDbEmpty) complianceDbEmpty.style.display = 'none';
        if (complianceDbList) complianceDbList.style.display = 'none';

        try {
            const res = await fetch('/api/regulation-db/regulations');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            complianceModeState.dbRegulations = data.regulations || [];
            complianceModeState.dbLoaded = true;

            if (complianceDbLoading) complianceDbLoading.style.display = 'none';

            if (complianceModeState.dbRegulations.length === 0) {
                if (complianceDbEmpty) complianceDbEmpty.style.display = 'flex';
                if (complianceDbCount) complianceDbCount.textContent = '(0 regulasi)';
                return;
            }

            renderComplianceDbList();
        } catch (err) {
            if (complianceDbLoading) {
                complianceDbLoading.innerHTML = `
                    <i class="fas fa-exclamation-circle" style="color:var(--warn);"></i>
                    Gagal memuat: ${escapeHtml(err.message)}
                `;
                complianceDbLoading.style.display = 'flex';
            }
        }
    }

    // ---- Render DB List ----
    function renderComplianceDbList() {
        if (!complianceDbList) return;

        const regs = complianceModeState.dbRegulations;

        if (complianceDbCount) {
            complianceDbCount.textContent = `(${regs.length} regulasi)`;
        }

        complianceDbList.style.display = 'flex';
        complianceDbList.innerHTML = regs.map(r => {
            const isSelected = complianceModeState.dbSelectedIds.has(r.id);
            const isPreload = r.source_type === 'preload';
            const badge = isPreload ? ' · Preload' : ' · Manual';

            return `
                <label class="compliance-db-item ${isSelected ? 'selected' : ''}"
                       data-db-reg-id="${escapeAttr(r.id)}">
                    <input type="checkbox"
                           data-db-check-id="${escapeAttr(r.id)}"
                           ${isSelected ? 'checked' : ''} />
                    <div class="compliance-db-item-icon">
                        <i class="fas fa-file-contract"></i>
                    </div>
                    <div class="compliance-db-item-body">
                        <div class="compliance-db-item-name">${escapeHtml(r.name)}</div>
                        <div class="compliance-db-item-meta">
                            <span><i class="fas fa-cubes"></i> ${(r.total_chunks || 0).toLocaleString('id-ID')} chunks</span>
                            <span>${badge}</span>
                        </div>
                    </div>
                </label>
            `;
        }).join('');

        // Attach checkbox listeners
        complianceDbList.querySelectorAll('[data-db-check-id]').forEach(cb => {
            cb.addEventListener('change', (e) => {
                e.stopPropagation();
                const regId = cb.dataset.dbCheckId;
                const label = cb.closest('.compliance-db-item');

                if (cb.checked) {
                    complianceModeState.dbSelectedIds.add(regId);
                    if (label) label.classList.add('selected');
                } else {
                    complianceModeState.dbSelectedIds.delete(regId);
                    if (label) label.classList.remove('selected');
                }
            });
        });

        // Click row = toggle
        complianceDbList.querySelectorAll('.compliance-db-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT') return;
                const cb = item.querySelector('input[type="checkbox"]');
                if (cb) {
                    cb.checked = !cb.checked;
                    cb.dispatchEvent(new Event('change'));
                }
            });
        });
    }

    // ============================================================
    // END OF COMPLIANCE MODE SELECTOR
    // ============================================================

    // ============================================================
    // REGULATION DATABASE (RAG)
    // ============================================================

    const regDbState = {
        stats: null,
        regulations: [],
        loading: false,
    };

    // ---- DOM Refs ----
    const regdbStatTotal = $('#regdbStatTotal');
    const regdbStatChunks = $('#regdbStatChunks');
    const regdbStatSize = $('#regdbStatSize');
    const regdbUploadForm = $('#regdbUploadForm');
    const regdbNameInput = $('#regdbNameInput');
    const regdbFileInput = $('#regdbFileInput');
    const regdbFileDisplay = $('#regdbFileDisplay');
    const regdbFileInputWrap = document.querySelector('.regdb-file-input-wrap');
    const regdbSubmitBtn = $('#regdbSubmitBtn');
    const regdbStatusEl = $('#regdbStatus');
    const regdbProgressContainer = $('#regdbProgressContainer');
    const regdbProgressBar = $('#regdbProgressBar');
    const regdbProgressText = $('#regdbProgressText');
    const regdbListContainer = $('#regdbListContainer');
    const regdbRefreshBtn = $('#regdbRefreshBtn');
    const regdbResetBtn = $('#regdbResetBtn');

    // ---- Status / Progress ----
    function setRegDbStatus(text, isError) {
        if (!regdbStatusEl) return;
        regdbStatusEl.className = 'status-text';
        if (isError === true) {
            regdbStatusEl.classList.add('error');
            regdbStatusEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${escapeHtml(text)}`;
        } else if (isError === false) {
            regdbStatusEl.classList.add('success');
            regdbStatusEl.innerHTML = `<i class="fas fa-check-circle"></i> ${escapeHtml(text)}`;
        } else {
            regdbStatusEl.textContent = text;
        }
    }

    function setRegDbProgress(percent, text) {
        if (!regdbProgressContainer) return;
        regdbProgressContainer.style.display = 'block';
        regdbProgressBar.style.width = percent + '%';
        regdbProgressText.textContent = text || `${Math.round(percent)}%`;
        if (percent >= 100) {
            setTimeout(() => {
                regdbProgressContainer.style.display = 'none';
                regdbProgressText.textContent = '';
            }, 1500);
        }
    }

    function hideRegDbProgress() {
        if (!regdbProgressContainer) return;
        regdbProgressContainer.style.display = 'none';
        regdbProgressText.textContent = '';
        regdbProgressBar.style.width = '0%';
    }

    // ---- Page Load ----
    async function loadRegulationDbPage() {
        await Promise.all([
            loadRegDbStats(),
            loadRegDbList(),
        ]);
    }

    // ---- Load Stats ----
    async function loadRegDbStats() {
        try {
            const res = await fetch('/api/regulation-db/stats');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            regDbState.stats = data;

            if (regdbStatTotal) {
                regdbStatTotal.textContent = data.total_regulations || 0;
            }
            if (regdbStatChunks) {
                regdbStatChunks.textContent = (data.total_chunks || 0).toLocaleString('id-ID');
            }
            if (regdbStatSize) {
                regdbStatSize.textContent = `${data.db_size_mb || 0} MB`;
            }
        } catch (err) {
            console.warn('Gagal load stats:', err);
            if (regdbStatTotal) regdbStatTotal.textContent = '—';
            if (regdbStatChunks) regdbStatChunks.textContent = '—';
            if (regdbStatSize) regdbStatSize.textContent = '—';
        }
    }

    // ---- Load List ----
    async function loadRegDbList() {
        if (!regdbListContainer) return;
        regdbListContainer.innerHTML = `
            <div class="regdb-loading">
                <i class="fas fa-spinner fa-spin"></i> Memuat...
            </div>
        `;

        try {
            const res = await fetch('/api/regulation-db/regulations');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            regDbState.regulations = data.regulations || [];
            renderRegDbList();
        } catch (err) {
            regdbListContainer.innerHTML = `
                <div class="regdb-empty">
                    <i class="fas fa-exclamation-circle"></i>
                    <strong>Gagal memuat data</strong>
                    <span>${escapeHtml(err.message)}</span>
                </div>
            `;
        }
    }

    // ---- Render List ----
    function renderRegDbList() {
        if (!regdbListContainer) return;

        const regs = regDbState.regulations;

        if (regs.length === 0) {
            regdbListContainer.innerHTML = `
                <div class="regdb-empty">
                    <i class="fas fa-database"></i>
                    <strong>Belum ada regulasi</strong>
                    <span>Upload regulasi pertama Anda di form atas.</span>
                </div>
            `;
            return;
        }

        regdbListContainer.innerHTML = regs.map(r => {
            const isPreload = r.source_type === 'preload';
            const badge = isPreload
                ? `<span class="regdb-item-badge regdb-badge-preload">Preload</span>`
                : `<span class="regdb-item-badge regdb-badge-manual">Manual</span>`;
            // Dibuat dengan parser/embedding versi lama → hasil retrieval kurang akurat.
            const staleBadge = r.needs_reindex
                ? `<span class="regdb-item-badge regdb-badge-stale"
                         title="${r.has_source
                             ? 'Di-index dengan parser/embedding versi lama. Klik Index Ulang.'
                             : 'Versi lama & file sumber tidak tersimpan — hapus lalu upload ulang.'}">Perlu index ulang</span>`
                : '';
            const reindexBtn = r.needs_reindex && r.has_source
                ? `<button class="regdb-item-reindex" data-reindex-reg-id="${escapeAttr(r.id)}" title="Index ulang dengan parser & embedding terbaru">
                       <i class="fas fa-rotate"></i>
                   </button>`
                : '';

            const date = r.created_at
                ? new Date(r.created_at).toLocaleDateString('id-ID', {
                    day: 'numeric', month: 'short', year: 'numeric'
                })
                : '—';

            return `
                <div class="regdb-item" data-reg-id="${escapeAttr(r.id)}">
                    <div class="regdb-item-icon ${isPreload ? 'preload' : ''}">
                        <i class="fas fa-file-contract"></i>
                    </div>
                    <div class="regdb-item-body">
                        <div class="regdb-item-name">
                            ${escapeHtml(r.name)}
                            ${badge}
                            ${staleBadge}
                        </div>
                        <div class="regdb-item-meta">
                            <span><i class="fas fa-cubes"></i> ${(r.total_chunks || 0).toLocaleString('id-ID')} chunks</span>
                            <span><i class="fas fa-file"></i> <code>${escapeHtml(r.filename || '-')}</code></span>
                            <span><i class="fas fa-calendar"></i> ${date}</span>
                        </div>
                    </div>
                    ${reindexBtn}
                    <button class="regdb-item-delete" data-delete-reg-id="${escapeAttr(r.id)}" title="Hapus regulasi">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
        }).join('');

        regdbListContainer.querySelectorAll('[data-reindex-reg-id]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                handleReindexRegulation(btn.dataset.reindexRegId, btn);
            });
        });

        // Attach delete handlers
        regdbListContainer.querySelectorAll('[data-delete-reg-id]').forEach(btn => {
            btn.addEventListener('click', () => {
                const regId = btn.dataset.deleteRegId;
                handleDeleteRegulation(regId);
            });
        });

                // Attach click → buka detail (kecuali tombol delete)
        regdbListContainer.querySelectorAll('.regdb-item').forEach(item => {
            item.addEventListener('click', (e) => {
                // Kalau yang diklik tombol delete / index ulang, skip
                if (e.target.closest('[data-delete-reg-id], [data-reindex-reg-id]')) return;

                const regId = item.dataset.regId;
                if (regId) openRegDbDetail(regId);
            });

            // Cursor pointer
            item.style.cursor = 'pointer';
            item.title = 'Klik untuk lihat detail chunks';
        });

    }

    // ---- Index Ulang Regulation ----
    async function handleReindexRegulation(regId, btn) {
        const reg = regDbState.regulations.find(r => r.id === regId);
        if (!reg) return;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        setRegDbStatus(`Mengindex ulang "${reg.name}"...`, null);
        try {
            const run = await runJob(`/api/regulation-db/regulations/${regId}/reindex`, { method: 'POST' }, {
                onProgress: (job, pct, label) => setRegDbProgress(pct, `${reg.name}: ${label}`),
            });
            hideRegDbProgress();
            if (!run.ok) {
                setRegDbStatus(`Gagal index ulang: ${run.error}`, true);
                showToast('Index ulang gagal: ' + run.error, 'error');
                return;
            }
            setRegDbStatus(run.job.message, false);
            showToast(run.job.message, 'success');
            await loadRegulationDbPage();
        } catch (err) {
            setRegDbStatus(`Gagal: ${err.message}`, true);
            showToast('Gagal terhubung ke server.', 'error');
        } finally {
            btn.disabled = false;
        }
    }

    // ---- Delete Regulation ----
    async function handleDeleteRegulation(regId) {
        const reg = regDbState.regulations.find(r => r.id === regId);
        if (!reg) return;

        const confirmed = confirm(
            `Hapus regulasi "${reg.name}" dari database?\n\n` +
            `${reg.total_chunks} chunks akan dihapus permanen.\n` +
            `Regulasi yang menggunakan ini di Compliance Review tidak akan ` +
            `terpengaruh (data review tetap tersimpan).`
        );
        if (!confirmed) return;

        try {
            const res = await fetch(`/api/regulation-db/regulations/${regId}`, {
                method: 'DELETE',
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            showToast(data.message || 'Regulasi dihapus.', 'success');
            await loadRegulationDbPage();
        } catch (err) {
            showToast(`Gagal menghapus: ${err.message}`, 'error');
        }
    }

    // ---- File Display ----
    if (regdbFileInput) {
        regdbFileInput.addEventListener('change', () => {
            if (!regdbFileDisplay) return;

            if (regdbFileInput.files.length) {
                const f = regdbFileInput.files[0];
                regdbFileDisplay.innerHTML = `
                    <i class="fas fa-file-check"></i>
                    <span>${escapeHtml(f.name)} (${formatFileSize(f.size)})</span>
                `;
                if (regdbFileInputWrap) regdbFileInputWrap.classList.add('has-file');
            } else {
                regdbFileDisplay.innerHTML = `
                    <i class="fas fa-file"></i>
                    <span>Klik untuk pilih file</span>
                `;
                if (regdbFileInputWrap) regdbFileInputWrap.classList.remove('has-file');
            }
        });
    }

    // ---- Auto-fill name dari filename ----
    if (regdbFileInput && regdbNameInput) {
        regdbFileInput.addEventListener('change', () => {
            if (!regdbNameInput.value.trim() && regdbFileInput.files.length) {
                const fname = regdbFileInput.files[0].name;
                const stem = fname.replace(/\.[^.]+$/, '');
                // Normalisasi: POJK_11_2022 -> POJK 11/2022
                let name = stem.replace(/_/g, ' ').replace(/-/g, ' ');
                name = name.replace(/\s+/g, ' ').trim();
                // Pattern NAMA NOMOR TAHUN
                const parts = name.split(' ');
                if (parts.length >= 3 && /^\d{4}$/.test(parts[parts.length - 1])
                    && /^\d{1,3}$/.test(parts[parts.length - 2])) {
                    name = parts.slice(0, -2).join(' ') + ' ' +
                           parts[parts.length - 2] + '/' + parts[parts.length - 1];
                }
                regdbNameInput.value = name;
            }
        });
    }

    // ---- Upload Handler ----
    if (regdbUploadForm) {
        regdbUploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            if (!regdbFileInput || !regdbFileInput.files.length) {
                showToast('Pilih file terlebih dahulu.', 'error');
                return;
            }
            if (!regdbNameInput || !regdbNameInput.value.trim()) {
                showToast('Isi nama regulasi terlebih dahulu.', 'error');
                return;
            }

            const file = regdbFileInput.files[0];
            if (file.size > 10 * 1024 * 1024) {
                showToast('File terlalu besar. Maks 10 MB.', 'error');
                return;
            }

            regdbSubmitBtn.disabled = true;
            regdbSubmitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Memproses...';
            setRegDbStatus('Meng-extract, embed, dan simpan ke database...', null);
            setRegDbProgress(15, 'Meng-extract teks...');

            const fd = new FormData();
            fd.append('file', file);
            fd.append('name', regdbNameInput.value.trim());

            try {
                const run = await runJob('/api/regulation-db/upload', {
                    method: 'POST',
                    body: fd,
                }, {
                    cancelAnchor: regdbProgressText,
                    onProgress: (job, pct, label) => setRegDbProgress(15 + pct * 0.85, label),
                });

                if (!run.ok) {
                    hideRegDbProgress();
                    setRegDbStatus(`Gagal: ${run.error}`, true);
                    showToast(run.cancelled ? 'Upload dibatalkan.' : 'Upload gagal: ' + run.error,
                        run.cancelled ? 'info' : 'error');
                    return;
                }
                setRegDbProgress(100, 'Selesai!');

                const regulation = run.job.extra.regulation;
                setRegDbStatus(run.job.message || 'Regulasi berhasil di-index.', false);
                showToast(`Regulasi "${regulation.name}" di-index (${regulation.total_chunks} chunks).`, 'success');

                // Reset form
                regdbNameInput.value = '';
                regdbFileInput.value = '';
                if (regdbFileDisplay) {
                    regdbFileDisplay.innerHTML = `
                        <i class="fas fa-file"></i>
                        <span>Klik untuk pilih file</span>
                    `;
                }
                if (regdbFileInputWrap) regdbFileInputWrap.classList.remove('has-file');

                // Refresh list + stats
                await loadRegulationDbPage();
            } catch (err) {
                setRegDbStatus(`Gagal: ${err.message}`, true);
                showToast('Gagal terhubung ke server.', 'error');
            } finally {
                regdbSubmitBtn.disabled = false;
                regdbSubmitBtn.innerHTML = '<i class="fas fa-plus"></i> Upload &amp; Index';
                setTimeout(hideRegDbProgress, 1500);
            }
        });
    }

    // ---- Refresh Button ----
    if (regdbRefreshBtn) {
        regdbRefreshBtn.addEventListener('click', async () => {
            regdbRefreshBtn.disabled = true;
            regdbRefreshBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Refresh...';
            await loadRegulationDbPage();
            regdbRefreshBtn.disabled = false;
            regdbRefreshBtn.innerHTML = '<i class="fas fa-rotate"></i> Refresh';
            showToast('Data di-refresh.', 'success');
        });
    }

    // ---- Reset DB Button ----
    if (regdbResetBtn) {
        regdbResetBtn.addEventListener('click', async () => {
            const total = regDbState.regulations.length;
            if (total === 0) {
                showToast('Database sudah kosong.', 'info');
                return;
            }

            // Confirm 2x (dangerous operation)
            const ok1 = confirm(
                `Hapus SEMUA ${total} regulasi dari database?\n\n` +
                `Ini akan menghapus semua data index regulasi.\n` +
                `Tindakan ini TIDAK BISA dibatalkan.`
            );
            if (!ok1) return;

            const ok2 = confirm(
                `Konfirmasi terakhir: Yakin hapus SEMUA regulasi dari database?`
            );
            if (!ok2) return;

            regdbResetBtn.disabled = true;
            regdbResetBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Reset...';

            try {
                const res = await fetch('/api/regulation-db/reset', {
                    method: 'POST',
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                const data = await res.json();
                showToast(data.message || 'Database direset.', 'success');
                await loadRegulationDbPage();
            } catch (err) {
                showToast(`Gagal reset: ${err.message}`, 'error');
            } finally {
                regdbResetBtn.disabled = false;
                regdbResetBtn.innerHTML = '<i class="fas fa-trash-can"></i> Reset DB';
            }
        });
    }


        // ============================================================
    // REGULATION DB — DETAIL VIEWER (Chunks)
    // ============================================================

    const regDbDetailState = {
        regulationId: null,
        regulationName: '',
        currentPage: 1,
        pageSize: 20,
        totalPages: 0,
        total: 0,
        search: '',
        anomaly: '',
        searchDebounceTimer: null,
        expandedChunks: new Set(),
    };

    // ---- DOM Refs ----
    const regdbDetailOverlay = $('#regdbDetailOverlay');
    const regdbDetailClose = $('#regdbDetailClose');
    const regdbDetailTitle = $('#regdbDetailTitle');
    const regdbDetailSubtitle = $('#regdbDetailSubtitle');
    const regdbDetailStats = $('#regdbDetailStats');
    const regdbDetailSearch = $('#regdbDetailSearch');
    const regdbDetailFilters = $$('.regdb-filter-btn');
    const regdbDetailLoading = $('#regdbDetailLoading');
    const regdbChunksList = $('#regdbChunksList');
    const regdbDetailEmpty = $('#regdbDetailEmpty');
    const regdbPageInfo = $('#regdbPageInfo');
    const regdbPrevPage = $('#regdbPrevPage');
    const regdbNextPage = $('#regdbNextPage');

    // ---- Open Detail Modal ----
    async function openRegDbDetail(regulationId) {
        const reg = regDbState.regulations.find(r => r.id === regulationId);
        if (!reg) {
            showToast('Regulasi tidak ditemukan.', 'error');
            return;
        }

        // Reset state
        regDbDetailState.regulationId = regulationId;
        regDbDetailState.regulationName = reg.name;
        regDbDetailState.currentPage = 1;
        regDbDetailState.search = '';
        regDbDetailState.anomaly = '';
        regDbDetailState.expandedChunks = new Set();

        // Update UI
        if (regdbDetailTitle) regdbDetailTitle.textContent = reg.name;
        if (regdbDetailSubtitle) {
            regdbDetailSubtitle.textContent = `${reg.filename} · ${(reg.total_chunks || 0).toLocaleString('id-ID')} chunks`;
        }

        // Reset filter buttons
        regdbDetailFilters.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.regdbFilter === '');
        });

        // Reset search
        if (regdbDetailSearch) regdbDetailSearch.value = '';

        // Reset body
        if (regdbChunksList) regdbChunksList.innerHTML = '';
        if (regdbDetailStats) regdbDetailStats.innerHTML = '';
        if (regdbDetailEmpty) regdbDetailEmpty.style.display = 'none';

        // Show modal
        if (regdbDetailOverlay) regdbDetailOverlay.style.display = 'flex';

        // Load data
        await loadRegDbChunks();
    }

    function closeRegDbDetail() {
        if (regdbDetailOverlay) regdbDetailOverlay.style.display = 'none';

        // Clear search debounce
        if (regDbDetailState.searchDebounceTimer) {
            clearTimeout(regDbDetailState.searchDebounceTimer);
            regDbDetailState.searchDebounceTimer = null;
        }

        // Reset state
        regDbDetailState.regulationId = null;
        regDbDetailState.expandedChunks = new Set();
    }

    // ---- Load Chunks ----
    async function loadRegDbChunks() {
        const { regulationId, currentPage, pageSize, search, anomaly } = regDbDetailState;
        if (!regulationId) return;

        // Loading state
        if (regdbDetailLoading) regdbDetailLoading.style.display = 'flex';
        if (regdbChunksList) regdbChunksList.innerHTML = '';
        if (regdbDetailEmpty) regdbDetailEmpty.style.display = 'none';

        // Build query
        const params = new URLSearchParams({
            page: String(currentPage),
            page_size: String(pageSize),
        });
        if (search) params.set('search', search);
        if (anomaly) params.set('anomaly', anomaly);

        try {
            const res = await fetch(`/api/regulation-db/regulations/${regulationId}/chunks?${params.toString()}`);
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }

            const data = await res.json();
            regDbDetailState.totalPages = data.total_pages;
            regDbDetailState.total = data.total;

            if (regdbDetailLoading) regdbDetailLoading.style.display = 'none';

            renderRegDbStats(data.stats, data.total, data.total_unfiltered);
            renderRegDbChunks(data.items || []);
            updateRegDbPagination(data.page, data.total_pages, data.total);

        } catch (err) {
            if (regdbDetailLoading) {
                regdbDetailLoading.innerHTML = `
                    <i class="fas fa-exclamation-circle" style="color:var(--warn);"></i>
                    Gagal memuat: ${escapeHtml(err.message)}
                `;
            }
        }
    }

    // ---- Render Stats ----
    function renderRegDbStats(stats, totalFiltered, totalUnfiltered) {
        if (!regdbDetailStats) return;

        const filterInfo = totalFiltered < totalUnfiltered
            ? `<span class="regdb-stat-mini"><strong>${totalFiltered}</strong><span>Terfilter dari ${totalUnfiltered}</span></span>`
            : '';

        const anomalyCount = (stats.anomaly_short || 0) + (stats.anomaly_long || 0) + (stats.anomaly_duplicate || 0);

        regdbDetailStats.innerHTML = `
            <div class="regdb-stat-mini">
                <strong>${stats.total_chunks || 0}</strong>
                <span>Total Chunks</span>
            </div>
            <div class="regdb-stat-mini">
                <strong>${stats.min_char}–${stats.max_char}</strong>
                <span>Min – Max Char</span>
            </div>
            <div class="regdb-stat-mini">
                <strong>${stats.avg_char}</strong>
                <span>Rata-rata Char</span>
            </div>
            <div class="regdb-stat-mini">
                <strong>${(stats.total_char || 0).toLocaleString('id-ID')}</strong>
                <span>Total Char</span>
            </div>
            ${anomalyCount > 0 ? `
                <div class="regdb-stat-mini warn">
                    <strong>${anomalyCount}</strong>
                    <span>Anomali Terdeteksi</span>
                </div>
            ` : `
                <div class="regdb-stat-mini">
                    <strong>0</strong>
                    <span>Anomali ✓</span>
                </div>
            `}
            ${filterInfo}
        `;
    }

    // ---- Render Chunks ----
    function renderRegDbChunks(items) {
        if (!regdbChunksList) return;

        if (!items || items.length === 0) {
            regdbChunksList.innerHTML = '';
            if (regdbDetailEmpty) regdbDetailEmpty.style.display = 'block';
            return;
        }

        if (regdbDetailEmpty) regdbDetailEmpty.style.display = 'none';

        // Hitung index global (untuk tampilan nomor)
        const startIdx = (regDbDetailState.currentPage - 1) * regDbDetailState.pageSize;

        regdbChunksList.innerHTML = items.map((chunk, i) => {
            const globalIdx = startIdx + i + 1;
            const expanded = regDbDetailState.expandedChunks.has(chunk.id);
            const isLong = chunk.text.length > 400;

            let cardClass = 'regdb-chunk-card';
            let badge = '';

            if (chunk.anomaly_reason === 'short') {
                cardClass += ' anomaly-short';
                badge = `<span class="regdb-chunk-badge badge-short">Pendek</span>`;
            } else if (chunk.anomaly_reason === 'long') {
                cardClass += ' anomaly-long';
                badge = `<span class="regdb-chunk-badge badge-long">Panjang</span>`;
            } else if (chunk.anomaly_reason === 'duplicate') {
                cardClass += ' anomaly-duplicate';
                badge = `<span class="regdb-chunk-badge badge-duplicate">Duplikat</span>`;
            }

            const pageInfo = (chunk.page_start > 0)
                ? `<span><i class="fas fa-file"></i> hal. ${chunk.page_start}${chunk.page_end !== chunk.page_start ? '-' + chunk.page_end : ''}</span>`
                : '';

            return `
                <div class="${cardClass}" data-chunk-id="${escapeAttr(chunk.id)}">
                    <div class="regdb-chunk-header">
                        <span class="regdb-chunk-index">#${globalIdx}</span>
                        <span class="regdb-chunk-ref" title="${escapeAttr(chunk.referensi)}">
                            ${escapeHtml(chunk.referensi || '(no reference)')}
                        </span>
                        ${badge}
                        <div class="regdb-chunk-meta">
                            <span><i class="fas fa-font"></i> ${chunk.char_count.toLocaleString('id-ID')}</span>
                            ${pageInfo}
                        </div>
                    </div>
                    <div class="regdb-chunk-body ${expanded ? 'expanded' : (isLong ? 'collapsed' : '')}"
                         data-chunk-body-id="${escapeAttr(chunk.id)}">
                        ${escapeHtml(chunk.text)}
                    </div>
                    ${isLong ? `
                        <button class="regdb-chunk-expand" data-chunk-expand-id="${escapeAttr(chunk.id)}">
                            ${expanded ? '▲ Sembunyikan' : '▼ Lihat Selengkapnya'}
                        </button>
                    ` : ''}
                </div>
            `;
        }).join('');

        // Attach expand listeners
        regdbChunksList.querySelectorAll('[data-chunk-expand-id]').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = btn.dataset.chunkExpandId;
                toggleRegDbChunkExpand(id);
            });
        });
    }

    function toggleRegDbChunkExpand(chunkId) {
        const body = regdbChunksList.querySelector(`[data-chunk-body-id="${CSS.escape(chunkId)}"]`);
        const btn = regdbChunksList.querySelector(`[data-chunk-expand-id="${CSS.escape(chunkId)}"]`);
        if (!body || !btn) return;

        const isExpanded = regDbDetailState.expandedChunks.has(chunkId);

        if (isExpanded) {
            regDbDetailState.expandedChunks.delete(chunkId);
            body.classList.remove('expanded');
            body.classList.add('collapsed');
            btn.innerHTML = '▼ Lihat Selengkapnya';
        } else {
            regDbDetailState.expandedChunks.add(chunkId);
            body.classList.add('expanded');
            body.classList.remove('collapsed');
            btn.innerHTML = '▲ Sembunyikan';
        }
    }

    // ---- Pagination ----
    function updateRegDbPagination(currentPage, totalPages, total) {
        if (regdbPageInfo) {
            if (total === 0) {
                regdbPageInfo.textContent = 'Tidak ada hasil';
            } else {
                regdbPageInfo.textContent = `Halaman ${currentPage} dari ${totalPages} (${total.toLocaleString('id-ID')} chunk)`;
            }
        }
        if (regdbPrevPage) regdbPrevPage.disabled = currentPage <= 1;
        if (regdbNextPage) regdbNextPage.disabled = currentPage >= totalPages;
    }

    if (regdbPrevPage) {
        regdbPrevPage.addEventListener('click', () => {
            if (regDbDetailState.currentPage > 1) {
                regDbDetailState.currentPage -= 1;
                regDbDetailState.expandedChunks = new Set();  // reset expand state
                loadRegDbChunks();
                // Scroll ke atas list
                const body = regdbChunksList?.parentElement;
                if (body) body.scrollTop = 0;
            }
        });
    }

    if (regdbNextPage) {
        regdbNextPage.addEventListener('click', () => {
            if (regDbDetailState.currentPage < regDbDetailState.totalPages) {
                regDbDetailState.currentPage += 1;
                regDbDetailState.expandedChunks = new Set();
                loadRegDbChunks();
                const body = regdbChunksList?.parentElement;
                if (body) body.scrollTop = 0;
            }
        });
    }

    // ---- Search (debounced) ----
    if (regdbDetailSearch) {
        regdbDetailSearch.addEventListener('input', (e) => {
            const value = e.target.value;

            if (regDbDetailState.searchDebounceTimer) {
                clearTimeout(regDbDetailState.searchDebounceTimer);
            }

            regDbDetailState.searchDebounceTimer = setTimeout(() => {
                regDbDetailState.search = value.trim();
                regDbDetailState.currentPage = 1;
                regDbDetailState.expandedChunks = new Set();
                loadRegDbChunks();
            }, 300);
        });

        // Enter untuk langsung search
        regdbDetailSearch.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                if (regDbDetailState.searchDebounceTimer) {
                    clearTimeout(regDbDetailState.searchDebounceTimer);
                }
                regDbDetailState.search = regdbDetailSearch.value.trim();
                regDbDetailState.currentPage = 1;
                loadRegDbChunks();
            }
        });
    }

    // ---- Filter buttons ----
    regdbDetailFilters.forEach(btn => {
        btn.addEventListener('click', () => {
            const filter = btn.dataset.regdbFilter || '';

            regdbDetailFilters.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            regDbDetailState.anomaly = filter;
            regDbDetailState.currentPage = 1;
            regDbDetailState.expandedChunks = new Set();
            loadRegDbChunks();
        });
    });

    // ---- Close handlers ----
    if (regdbDetailClose) {
        regdbDetailClose.addEventListener('click', closeRegDbDetail);
    }
    if (regdbDetailOverlay) {
        regdbDetailOverlay.addEventListener('click', (e) => {
            if (e.target === regdbDetailOverlay) closeRegDbDetail();
        });
    }

    // ESC key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && regdbDetailOverlay && regdbDetailOverlay.style.display === 'flex') {
            closeRegDbDetail();
            e.stopPropagation();
        }
    });

    // ============================================================
    // INTERACTIVE TOUR
    // ============================================================

    const TOUR_STORAGE_KEY = 'rta_tour_seen_v1';

        const TOUR_STEPS = [
        {
            selector: null,
            title: 'Selamat Datang di Audit Assistant!',
            text: 'Tur singkat 30 detik untuk mengenal fitur utama aplikasi. Klik <b>Lanjut</b> untuk mulai, atau <b>Lewati</b> kalau sudah familiar.',
            position: 'center',
        },
        {
            selector: '#uploadCard',
            title: 'Mulai dari Sini',
            text: 'Upload file regulasi (PDF atau TXT) di sini, lalu klik <b>"Baca Struktur Regulasi"</b> untuk memulai analisis.',
            position: 'fixed-bottom-right',   // card lebar → tooltip di kanan bawah
        },
        {
            selector: '.sidebar-nav',
            title: 'Tiga Tool Utama',
            text: 'Aplikasi punya 3 tool:<br>• <b>Regulation to Audit</b> — prosedur audit lengkap<br>• <b>Gap Analysis</b> — ekstrak persyaratan<br>• <b>Cari Global</b> — cari lintas dokumen',
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
                switchPage('regulation-audit');
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
            switchPage('regulation-audit');
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
        if (!localStorage.getItem(TOUR_STORAGE_KEY) && !state.isAnalyzing) {
            startTour(false);
        }
    }, 1200);

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

    // --- Focus search input saat pindah ke halaman search ---
    // (dipanggil di switchPage — kita tambah hook setelah fungsi ini didefinisikan)

    // ============================================================
    // KEYBOARD SHORTCUTS
    // ============================================================
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (promptPreviewOverlay && promptPreviewOverlay.style.display === 'flex') { closePromptPreview(); return; }
            if (gapAddRowModalOverlay && gapAddRowModalOverlay.style.display === 'flex') { closeGapAddRowModal(); return; }
            if (addRowModalOverlay && addRowModalOverlay.style.display === 'flex') { closeAddRowModal(); return; }
            if (treeModalOverlay && treeModalOverlay.style.display === 'flex') { closeTreeModal(); return; }
            if (settingsPanel && settingsPanel.classList.contains('open')) { closeSettings(); return; }
            if (sidebar && sidebar.classList.contains('open')) { closeMobileSidebar(); return; }
        }
        if (e.ctrlKey && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            if (state.currentPage === 'gap-analysis' && gapSearchInput) gapSearchInput.focus();
            else if (searchInput) searchInput.focus();
        }
    });

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
    const lastPage = localStorage.getItem('rta_current_page') || 'regulation-audit';
    switchPage(lastPage);

    loadSettings();

    console.log('%c🚀 Regulation to IT Audit Assistant v2', 'color:#1E2761;font-weight:bold;font-size:13px');
    console.log('%cTools: Regulation to Audit | Gap Analysis', 'color:#64748B');
    console.log('%cCtrl+K cari • Esc tutup modal/panel', 'color:#64748B');
})();