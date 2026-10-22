/**
 * Shortcut keyboard global.
 */

import { closeMobileSidebar, sidebar, state } from './core.js';
import { closeSettings, settingsPanel } from './settings.js';
import { closePromptPreview, promptPreviewOverlay } from './prompt-editor.js';
import {
    addRowModalOverlay,
    closeAddRowModal,
    closeTreeModal,
    searchInput,
    treeModalOverlay,
} from './audit.js';
import { closeGapAddRowModal, gapAddRowModalOverlay, gapSearchInput } from './gap.js';

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
