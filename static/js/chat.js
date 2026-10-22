/**
 * Tanya Regulasi (RAG Chat): tanya-jawab bersitasi atas Database Regulasi.
 * Percakapan disimpan di sessionStorage (per tab); beberapa giliran terakhir
 * dikirim ke server sebagai konteks pertanyaan lanjutan.
 */

import { $, escapeHtml, onPageEnter, renderMarkdownLite, showToast } from './core.js';

const HISTORY_TURNS_SENT = 6;
const STORAGE_KEY = 'rta_chat_session';

const chatThread = $('#chatThread');
const chatEmpty = $('#chatEmpty');
const chatForm = $('#chatForm');
const chatQuestion = $('#chatQuestion');
const chatSendBtn = $('#chatSendBtn');
const chatRegulationFilter = $('#chatRegulationFilter');
const chatClearBtn = $('#chatClearBtn');

const chatState = {
    // [{role: 'user'|'assistant', content, result?}] — result = response /api/chat
    turns: [],
    sending: false,
};

// ====== Penyimpanan sesi (aman bila storage diblokir) ======
function saveSession() {
    try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(chatState.turns));
    } catch (_) { /* storage tidak tersedia — percakapan tetap jalan di memori */ }
}

function loadSession() {
    try {
        const raw = sessionStorage.getItem(STORAGE_KEY);
        chatState.turns = raw ? JSON.parse(raw) : [];
    } catch (_) {
        chatState.turns = [];
    }
}

// ====== Daftar regulasi untuk filter ======
async function loadRegulationOptions() {
    if (!chatRegulationFilter) return;
    try {
        const res = await fetch('/api/regulation-db/regulations');
        if (!res.ok) return;
        const data = await res.json();
        const selected = chatRegulationFilter.value;
        chatRegulationFilter.innerHTML = '<option value="">Semua regulasi</option>' +
            data.regulations.map(r =>
                `<option value="${escapeHtml(r.id)}">${escapeHtml(r.name)}</option>`
            ).join('');
        chatRegulationFilter.value = data.regulations.some(r => r.id === selected) ? selected : '';
    } catch (_) { /* filter tetap "Semua regulasi" */ }
}

// ====== Render ======
function citationHtml(answerHtml, result) {
    // [n] → tombol yang menyorot sumber ke-n. Penanda yang tidak valid sudah
    // dihapus server; nomor di sini selalu ada di daftar sumber.
    return answerHtml.replace(/\[(\d{1,2})\]/g, (m, n) =>
        result.sources.some(s => s.number === Number(n))
            ? `<button type="button" class="chat-cite" data-cite="${n}" title="Lihat sumber ${n}">${n}</button>`
            : m
    );
}

function sourceHtml(source) {
    const page = source.page_start ? ` · hal. ${source.page_start}` : '';
    return `
        <details class="chat-source ${source.cited ? 'is-cited' : ''}" data-source="${source.number}">
            <summary>
                <span class="chat-source-num">${source.number}</span>
                <span class="chat-source-ref">${escapeHtml(source.reference || source.regulation_name)}${page}</span>
            </summary>
            <div class="chat-source-text">${escapeHtml(source.text)}</div>
        </details>`;
}

function assistantHtml(result) {
    const cited = result.sources.filter(s => s.cited);
    const others = result.sources.filter(s => !s.cited);
    const notes = (result.notes || []).map(n =>
        `<div class="chat-note"><i class="fas fa-flag"></i> ${escapeHtml(n)}</div>`).join('');
    const notFound = result.found ? '' :
        '<div class="chat-badge-notfound"><i class="fas fa-circle-question"></i> Tidak ditemukan di regulasi terpilih</div>';

    return `
        ${notFound}
        <div class="chat-answer">${citationHtml(renderMarkdownLite(result.answer), result)}</div>
        ${notes}
        ${cited.length ? `<div class="chat-sources-title">Sumber yang dikutip</div>${cited.map(sourceHtml).join('')}` : ''}
        ${others.length ? `
            <details class="chat-other-sources">
                <summary>Sumber lain yang diperiksa (${others.length})</summary>
                ${others.map(sourceHtml).join('')}
            </details>` : ''}
        <div class="chat-actions">
            <button type="button" class="btn btn-ghost btn-sm chat-copy"><i class="fas fa-copy"></i> Salin jawaban</button>
        </div>`;
}

function messageEl(turn) {
    const el = document.createElement('div');
    el.className = `chat-msg chat-msg-${turn.role}`;
    if (turn.role === 'user') {
        el.innerHTML = `<div class="chat-bubble">${escapeHtml(turn.content)}</div>`;
    } else if (turn.error) {
        el.innerHTML = `<div class="chat-bubble chat-error"><i class="fas fa-triangle-exclamation"></i> ${escapeHtml(turn.error)}</div>`;
    } else {
        el.innerHTML = `<div class="chat-bubble">${assistantHtml(turn.result)}</div>`;
        el._result = turn.result;
    }
    return el;
}

function renderThread() {
    if (!chatThread) return;
    chatThread.querySelectorAll('.chat-msg').forEach(m => m.remove());
    if (chatEmpty) chatEmpty.style.display = chatState.turns.length ? 'none' : '';
    chatState.turns.forEach(t => chatThread.appendChild(messageEl(t)));
    chatThread.scrollTop = chatThread.scrollHeight;
}

// ====== Kirim pertanyaan ======
async function sendQuestion(question) {
    question = question.trim();
    if (question.length < 3 || chatState.sending) return;

    // Konteks: giliran sukses terakhir (jawaban error tidak dikirim).
    const history = chatState.turns
        .filter(t => !t.error)
        .slice(-HISTORY_TURNS_SENT)
        .map(t => ({ role: t.role, content: t.role === 'user' ? t.content : t.result.answer }));

    chatState.sending = true;
    chatSendBtn.disabled = true;
    chatState.turns.push({ role: 'user', content: question });
    renderThread();
    chatQuestion.value = '';

    const pending = document.createElement('div');
    pending.className = 'chat-msg chat-msg-assistant';
    pending.innerHTML = '<div class="chat-bubble chat-pending"><span class="spinner"></span> Mencari di regulasi & menyusun jawaban…</div>';
    chatThread.appendChild(pending);
    chatThread.scrollTop = chatThread.scrollHeight;

    const regulationId = chatRegulationFilter ? chatRegulationFilter.value : '';
    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question,
                regulation_ids: regulationId ? [regulationId] : [],
                history,
            }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const detail = typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`;
            chatState.turns.push({ role: 'assistant', error: detail });
        } else {
            chatState.turns.push({ role: 'assistant', content: data.answer, result: data });
        }
    } catch (err) {
        chatState.turns.push({ role: 'assistant', error: `Gagal terhubung ke server (${err.message}).` });
    } finally {
        chatState.sending = false;
        chatSendBtn.disabled = false;
        saveSession();
        renderThread();
        chatQuestion.focus();
    }
}

function copyAnswer(result) {
    const cited = result.sources.filter(s => s.cited);
    const refs = cited.map(s => `[${s.number}] ${s.reference}${s.page_start ? ` (hal. ${s.page_start})` : ''}`);
    const text = result.answer + (refs.length ? `\n\nSumber:\n${refs.join('\n')}` : '');
    navigator.clipboard.writeText(text)
        .then(() => showToast('Jawaban + sumber disalin.', 'success'))
        .catch(() => showToast('Gagal menyalin ke clipboard.', 'error'));
}

// ====== Event ======
if (chatForm) {
    chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        sendQuestion(chatQuestion.value);
    });
}

if (chatQuestion) {
    chatQuestion.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendQuestion(chatQuestion.value);
        }
    });
}

if (chatThread) {
    chatThread.addEventListener('click', (e) => {
        const example = e.target.closest('.chat-example');
        if (example) {
            sendQuestion(example.textContent);
            return;
        }
        const cite = e.target.closest('.chat-cite');
        if (cite) {
            const msg = cite.closest('.chat-msg');
            const source = msg && msg.querySelector(`.chat-source[data-source="${cite.dataset.cite}"]`);
            if (source) {
                const other = source.closest('.chat-other-sources');
                if (other) other.open = true;
                source.open = true;
                source.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                source.classList.add('is-highlighted');
                setTimeout(() => source.classList.remove('is-highlighted'), 1600);
            }
            return;
        }
        const copy = e.target.closest('.chat-copy');
        if (copy) {
            const msg = copy.closest('.chat-msg');
            if (msg && msg._result) copyAnswer(msg._result);
        }
    });
}

if (chatClearBtn) {
    chatClearBtn.addEventListener('click', () => {
        chatState.turns = [];
        saveSession();
        renderThread();
        chatQuestion.focus();
    });
}

loadSession();
renderThread();

onPageEnter('chat', () => {
    loadRegulationOptions();
    setTimeout(() => chatQuestion && chatQuestion.focus(), 100);
});
