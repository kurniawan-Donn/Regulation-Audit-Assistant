/**
 * Pemberitahuan versi baru (GitHub Releases).
 *
 * Server mengecek rilis terbaru (/api/update-check, di-cache beberapa jam).
 * Bila ada versi lebih baru, spanduk kecil tampil dengan tautan unduhan yang
 * sesuai cara pemasangan; disembunyikan per versi setelah ditutup pengguna.
 */

import { $, escapeHtml } from './core.js';

const DISMISS_KEY = 'rta_update_dismissed';
const FIRST_CHECK_DELAY_MS = 2500;

const banner = $('#updateBanner');
const bannerText = $('#updateBannerText');
const bannerLink = $('#updateBannerLink');
const bannerClose = $('#updateBannerClose');
const aboutUpdate = $('#aboutUpdate');
const checkBtn = $('#checkUpdateBtn');

let lastInfo = null;

function readDismissed() {
    try { return localStorage.getItem(DISMISS_KEY); } catch { return null; }
}

function writeDismissed(version) {
    try { localStorage.setItem(DISMISS_KEY, version); } catch { /* abaikan */ }
}

function linkLabel(kind) {
    return kind === 'installer' || kind === 'portable' ? 'Unduh' : 'Lihat rilis';
}

function renderBanner(info) {
    if (!banner) return;
    const show = info.enabled && info.update_available && info.url && readDismissed() !== info.latest;
    banner.hidden = !show;
    if (!show) return;
    bannerText.innerHTML = `<b>Versi ${escapeHtml(info.latest)} tersedia</b> — Anda memakai ${escapeHtml(info.current)}.`;
    bannerLink.href = info.url;
    bannerLink.textContent = linkLabel(info.install_kind);
}

function renderAbout(info) {
    if (!aboutUpdate) return;
    if (!info.enabled) {
        aboutUpdate.textContent = 'Pengecekan dimatikan';
    } else if (info.error) {
        aboutUpdate.textContent = 'Tidak dapat mengecek (offline?)';
    } else if (info.update_available) {
        aboutUpdate.innerHTML = `<a href="${escapeHtml(info.url)}" target="_blank" rel="noopener">`
            + `Versi ${escapeHtml(info.latest)} tersedia</a>`;
    } else if (info.latest) {
        aboutUpdate.textContent = 'Sudah versi terbaru';
    } else {
        aboutUpdate.textContent = 'Belum ada rilis';
    }
}

async function fetchUpdate(force = false) {
    const res = await fetch(`/api/update-check${force ? '?force=true' : ''}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function refresh(force = false) {
    try {
        lastInfo = await fetchUpdate(force);
    } catch {
        if (aboutUpdate) aboutUpdate.textContent = 'Tidak dapat mengecek';
        return;
    }
    renderBanner(lastInfo);
    renderAbout(lastInfo);
}

export function initUpdateCheck() {
    bannerClose?.addEventListener('click', () => {
        if (lastInfo?.latest) writeDismissed(lastInfo.latest);
        banner.hidden = true;
    });
    checkBtn?.addEventListener('click', async () => {
        checkBtn.disabled = true;
        if (aboutUpdate) aboutUpdate.textContent = 'Memeriksa…';
        try {
            await refresh(true);
        } finally {
            checkBtn.disabled = false;
        }
    });
    setTimeout(() => refresh(false), FIRST_CHECK_DELAY_MS);
}
