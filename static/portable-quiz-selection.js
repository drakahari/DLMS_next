/* Selection is global; filtering/pagination changes visibility, never identity. */
(() => {
    const form = document.getElementById('portableBundleExportForm');
    if (!form) return;
    const rows = [...form.querySelectorAll('.portable-bundle-quiz')];
    const search = document.getElementById('bundleSearch');
    const folder = document.getElementById('bundleFolder');
    const count = document.getElementById('bundleQuizCount');
    const matches = document.getElementById('bundleMatchCount');
    const all = document.getElementById('selectAllBundleQuizzes');
    const download = document.getElementById('bundleDownload');
    const previous = document.getElementById('bundlePrevious');
    const next = document.getElementById('bundleNext');
    const pageLabel = document.getElementById('bundlePage');
    const pageSize = 50;
    let page = 0;
    let filtered = [];
    const checkbox = row => row.querySelector('input[name=quiz_ids]');
    const update = () => {
        const query = search.value.trim().toLocaleLowerCase();
        filtered = rows.filter(row => (!folder.value || row.dataset.folder === folder.value)
            && `${row.dataset.title} ${row.dataset.folder}`.toLocaleLowerCase().includes(query));
        const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
        page = Math.min(page, pages - 1);
        rows.forEach(row => { row.hidden = true; });
        filtered.slice(page * pageSize, (page + 1) * pageSize).forEach(row => { row.hidden = false; });
        const selected = rows.filter(row => checkbox(row).checked);
        const outside = selected.filter(row => !filtered.includes(row)).length;
        count.textContent = `${selected.length} selected${outside ? ` · ${outside} outside this filter` : ''}`;
        matches.textContent = `${filtered.length} matching of ${rows.length} available sources`;
        all.textContent = `Select all filtered results (${filtered.length})`;
        all.disabled = filtered.length === 0;
        download.disabled = selected.length === 0 || selected.length > 1000;
        if (selected.length > 1000) count.textContent += ' · Limit: 1,000 per download; deselect some quizzes';
        pageLabel.textContent = filtered.length ? `Page ${page + 1} of ${pages}` : 'No matching pages';
        previous.disabled = page === 0;
        next.disabled = page >= pages - 1;
        document.getElementById('bundleNoMatches').hidden = filtered.length !== 0;
    };
    rows.forEach(row => checkbox(row).addEventListener('change', update));
    [search, folder].forEach(control => control.addEventListener('input', () => { page = 0; update(); }));
    all.addEventListener('click', () => { filtered.forEach(row => { checkbox(row).checked = true; }); update(); });
    document.getElementById('clearBundleQuizzes').addEventListener('click', () => {
        rows.forEach(row => { checkbox(row).checked = false; }); update();
    });
    previous.addEventListener('click', () => { page -= 1; update(); });
    next.addEventListener('click', () => { page += 1; update(); });
    form.addEventListener('submit', event => { if (download.disabled) event.preventDefault(); });
    update();
})();
