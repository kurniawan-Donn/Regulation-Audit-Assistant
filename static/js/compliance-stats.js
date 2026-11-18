/**
 * Statistik hasil Compliance Review — cerminan app/services/compliance_stats.py
 * (dipakai ekspor Excel/PDF). Dihitung di browser karena status bisa diubah
 * langsung di tabel. Test tests/test_compliance_stats.py memastikan hasil
 * kedua implementasi identik.
 */

export const STATUS_SPECS = [
    { key: 'patuh', status: 'PATUH', label: 'Patuh' },
    { key: 'catatan', status: 'PATUH DENGAN CATATAN', label: 'Patuh dgn Catatan' },
    { key: 'tidak_patuh', status: 'TIDAK PATUH', label: 'Tidak Patuh' },
    { key: 'tidak_relevan', status: 'TIDAK RELEVAN', label: 'Tidak Relevan' },
    { key: 'verifikasi', status: 'PERLU VERIFIKASI', label: 'Perlu Verifikasi' },
];
const KEY_BY_STATUS = Object.fromEntries(STATUS_SPECS.map(s => [s.status, s.key]));

export function regulationLabel(name) {
    return String(name || '').trim().replace(/\.(pdf|txt)$/i, '');
}

export function roundHalfUp(value) {
    return value >= 0 ? Math.floor(value + 0.5) : -Math.floor(-value + 0.5);
}

/** Persen bulat yang jumlahnya tepat 100 (metode sisa terbesar). */
export function percentages(counts) {
    const total = counts.reduce((a, b) => a + b, 0);
    if (total <= 0) return counts.map(() => 0);
    const raw = counts.map(c => (c * 100) / total);
    const floors = raw.map(r => Math.floor(r));
    let remaining = 100 - floors.reduce((a, b) => a + b, 0);
    const order = raw.map((r, i) => i).sort((a, b) => ((raw[b] - floors[b]) - (raw[a] - floors[a])) || (a - b));
    for (const i of order) {
        if (remaining <= 0) break;
        floors[i] += 1;
        remaining -= 1;
    }
    return floors;
}

function statusKey(item) {
    return KEY_BY_STATUS[item.status] || 'verifikasi';
}

function statusBreakdown(items) {
    const counts = STATUS_SPECS.map(s => items.filter(it => statusKey(it) === s.key).length);
    const pcts = percentages(counts);
    return STATUS_SPECS.map((s, i) => ({ ...s, count: counts[i], percent: pcts[i] }));
}

/** Regulasi yang dirujuk klausul (hasil lama: dicocokkan dari teks regulasi_ref). */
export function itemSources(item, knownLabels) {
    const stored = item.regulasi_sumber;
    if (stored && stored.length) {
        return [...new Set(stored.filter(Boolean).map(regulationLabel))];
    }
    const ref = String(item.regulasi_ref || '').toLowerCase();
    return knownLabels.filter(label => label && ref.includes(label.toLowerCase()));
}

export function complianceStats(items, regulationNames = []) {
    items = items || [];
    const total = items.length;
    const statuses = statusBreakdown(items);
    const byKey = Object.fromEntries(statuses.map(s => [s.key, s.count]));
    const relevant = total - byKey.tidak_relevan;
    const compliant = byKey.patuh + byKey.catatan;

    const labels = [...new Set((regulationNames || []).filter(Boolean).map(regulationLabel))];
    const sources = items.map(it => itemSources(it, labels));
    sources.forEach(found => found.forEach(label => { if (!labels.includes(label)) labels.push(label); }));

    const regulations = labels.map(label => {
        const referencing = items.filter((it, i) => sources[i].includes(label));
        return {
            name: label,
            referenced: referencing.length,
            share: total ? roundHalfUp((referencing.length * 100) / total) : 0,
            statuses: statusBreakdown(referencing),
        };
    });

    return {
        total,
        statuses,
        relevant,
        compliant,
        score: relevant ? roundHalfUp((compliant * 100) / relevant) : null,
        regulations,
        unattributed: items.filter((it, i) => !sources[i].length && statusKey(it) !== 'tidak_relevan').length,
    };
}
