/* Scoped presentation around the existing immutable request/publication contract. */
(() => {
    'use strict';
    const context = document.getElementById('studyMistakeContext');
    if (!context) return;
    const data = JSON.parse(context.textContent);
    const scopeForm = document.getElementById('mistakeScopeForm');
    const folders = scopeForm.querySelector('[name=folders]');
    const quizzes = document.getElementById('mistakeQuizSelect');
    const browse = document.getElementById('mistakeQuizBrowse');
    const options = [...quizzes.options].map(o => ({id: Number(o.value), title: o.dataset.title, folder: o.dataset.folder, text: o.textContent}));
    const pickedQuizzes = new Set(data.scope.quizzes);
    const pickedFolders = new Set(data.scope.folders);
    const form = document.getElementById('mistakeCreateForm');
    const mode = document.getElementById('mistakeMode');
    const count = document.getElementById('mistakeCount');
    const title = document.getElementById('mistakeTitle');
    const create = document.getElementById('createMistakeMix');
    const start = document.getElementById('startMistakePass');
    const retry = document.getElementById('retryMistakeMix');
    const change = document.getElementById('changeMistakeRequest');
    const status = document.getElementById('mistakeStatus');
    const open = document.getElementById('openMistakeMix');
    const next = document.getElementById('nextMistakeMix');
    const refreshButton = document.getElementById('refreshMistakeCounts');
    const refreshMessage = document.getElementById('mistakeRefreshMessage');
    const key = 'dlms-study-mistakes-request';
    const draftKey = 'dlms-study-mistakes-draft.' + data.generation;
    // Match Python sorted(set(...)): Unicode code points, exact folder strings, numeric quiz IDs.
    function unicodeOrder(a, b) {
        const x = Array.from(a, c => c.codePointAt(0)), y = Array.from(b, c => c.codePointAt(0));
        for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
        return x.length - y.length;
    }
    function canonical(scope) {
        return JSON.stringify({folders: [...new Set(scope.folders)].sort(unicodeOrder), quizzes: [...new Set(scope.quizzes)].sort((a,b) => a-b)});
    }
    function selection() { return {folders: [...pickedFolders], quizzes: [...pickedQuizzes]}; }
    function changed() { return canonical(selection()) !== canonical(data.scope); }
    try {
        const draft = JSON.parse(sessionStorage.getItem(draftKey) || sessionStorage.getItem(draftKey + '.' + JSON.stringify(data.scope)));
        if (draft) {
            title.value = draft.title || '';
            count.value = draft.count;
            if (['random', 'without-repeats'].includes(draft.mode)) mode.value = draft.mode;
        }
    } catch (_error) { /* No valid draft. */ }
    function saveDraft() {
        try { sessionStorage.setItem(draftKey, JSON.stringify({title: title.value, count: count.value, mode: mode.value})); }
        catch (_error) { /* Creation separately verifies recovery storage. */ }
    }
    form.addEventListener('input', saveDraft);
    let pending = null, busy = false, completed = false, freshCounts = true, recoveryCleared = true;
    try { pending = JSON.parse(sessionStorage.getItem(key)); } catch (_error) { /* No saved request. */ }

    function sync() {
        if (!context.isConnected) return;
        const stale = changed(), random = mode.value === 'random';
        document.getElementById('mistakeSelectionChanged').hidden = !stale;
        document.getElementById('studyMistakeResults').hidden = stale || !freshCounts;
        document.getElementById('studyMistakeExclusions').hidden = stale || !freshCounts;
        create.disabled = stale || completed || busy || !!pending || !freshCounts || (random ? !data.eligible : !data.pass_id || !data.remaining);
        start.disabled = !recoveryCleared || stale || busy || !!pending || !freshCounts || !data.eligible || !!data.reserved;
        start.textContent = data.pass_id ? 'Start new pass' : 'Start pass';
        count.disabled = !random && !!data.pass_id && !data.remaining;
        retry.hidden = !pending;
        retry.disabled = busy;
        next.hidden = !completed || !freshCounts || !recoveryCleared || stale || (random ? !data.eligible : !data.remaining);
        next.disabled = busy;
        scopeForm.querySelector('[type=submit]').disabled = !recoveryCleared || busy || !!pending;
        let reason = '';
        if (stale) reason = 'Selection changed. Check Study mistakes before starting a pass or creating a quiz.';
        else if (pending) reason = 'Retry the retained request; its original sources and questions stay unchanged.';
        else if (!freshCounts) reason = 'Refresh counts before preparing another quiz. The saved quiz confirmation stays available.';
        else if (completed) reason = next.hidden ? 'This quiz is saved. Start a new pass or choose Random for more practice.' : 'This quiz is saved. Prepare next quiz to create a separate batch.';
        else if (!data.eligible) reason = 'No currently usable Study mistakes in these sources.';
        else if (!random && !data.pass_id) reason = 'Choose Start pass before creating Without repeats work.';
        else if (!random && !data.remaining) reason = data.used === data.total ? 'Pass complete. Start a new pass or choose Random; both can repeat previously included questions.' : 'No questions remain available in this pass. See Pass details for reservations or unavailable sources.';
        document.getElementById('mistakeCreationReason').textContent = reason;
    }
    function renderSelection() {
        const hidden = document.getElementById('mistakeHiddenSelections'); hidden.replaceChildren();
        const visibleIds = new Set([...quizzes.options].map(o => Number(o.value)));
        function hiddenValue(name, value) { const input = document.createElement('input'); input.type = 'hidden'; input.name = name; input.value = value; hidden.append(input); }
        for (const id of pickedQuizzes) if (!visibleIds.has(id)) hiddenValue('quizzes', id);
        const visibleFolders = new Set([...folders.options].map(o => o.value));
        for (const folder of pickedFolders) if (!visibleFolders.has(folder)) hiddenValue('folders', folder);
        const summary = document.getElementById('mistakeSelectionSummary'); summary.replaceChildren();
        function group(label, values, type) {
            const p = document.createElement('p'), strong = document.createElement('strong'); strong.textContent = label + ': '; p.append(strong);
            if (!values.length) p.append(document.createTextNode('None'));
            for (const value of values) {
                const source = type === 'quiz' ? options.find(o => o.id === value) : null;
                const text = type === 'quiz' ? (source ? source.title : `Unavailable source (ID ${value})`) : value;
                const item = document.createElement('span'); item.className = 'study-mistakes-selection';
                const name = document.createElement('span'); name.textContent = text; item.append(name);
                const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'dlms-action-control'; remove.textContent = 'Remove'; remove.setAttribute('aria-label', `Remove ${text} from selected ${type === 'quiz' ? 'individual quizzes' : 'folders'}`);
                remove.addEventListener('click', () => {
                    (type === 'quiz' ? pickedQuizzes : pickedFolders).delete(value);
                    for (const option of (type === 'quiz' ? quizzes : folders).options) option.selected = type === 'quiz' ? pickedQuizzes.has(Number(option.value)) : pickedFolders.has(option.value);
                    renderBrowse(); (type === 'quiz' ? quizzes : folders).focus();
                });
                item.append(remove); p.append(item);
            }
            summary.append(p);
        }
        group('Selected folders', [...pickedFolders], 'folder'); group('Selected individual quizzes', [...pickedQuizzes], 'quiz');
        const outside = [...pickedQuizzes].filter(id => !visibleIds.has(id)).length;
        document.getElementById('mistakeBrowseStatus').textContent = `${quizzes.options.length} ${quizzes.options.length === 1 ? 'quiz' : 'quizzes'} shown · ${outside} selected individual ${outside === 1 ? 'quiz' : 'quizzes'} outside this view retained.`;
        sync();
    }
    function renderBrowse() {
        const visible = options.filter(o => browse.value === 'all' || (browse.value === 'selected' ? pickedFolders.has(o.folder) : o.folder === browse.value.slice(7)));
        quizzes.replaceChildren(); const names = document.getElementById('mistakeQuizNames'); names.replaceChildren();
        for (const source of visible) {
            const option = new Option(source.text, String(source.id), false, pickedQuizzes.has(source.id)); option.dataset.folder = source.folder; option.title = source.text; quizzes.append(option);
            const li = document.createElement('li'); li.textContent = `${source.title} · ${source.folder} (ID ${source.id})`; names.append(li);
        }
        if (!visible.length) { const li = document.createElement('li'); li.textContent = 'No source quizzes in this view. Choose All folders to browse elsewhere.'; names.append(li); }
        renderSelection();
    }
    folders.addEventListener('change', () => {
        for (const o of folders.options) { pickedFolders.delete(o.value); if (o.selected) pickedFolders.add(o.value); }
        browse.value = pickedFolders.size ? 'selected' : 'all'; renderBrowse();
    });
    quizzes.addEventListener('change', () => {
        for (const o of quizzes.options) { pickedQuizzes.delete(Number(o.value)); if (o.selected) pickedQuizzes.add(Number(o.value)); }
        renderSelection();
    });
    browse.addEventListener('change', renderBrowse);
    document.getElementById('clearMistakeScope').addEventListener('click', () => {
        pickedFolders.clear(); pickedQuizzes.clear(); for (const o of folders.options) o.selected = false;
        browse.value = 'all'; renderBrowse();
    });
    scopeForm.addEventListener('submit', event => { if (!recoveryCleared || busy || pending) event.preventDefault(); saveDraft(); });
    async function post(url, body) {
        const token = window.dlmsCsrfToken || document.querySelector('[name=csrf-token]')?.content;
        if (!token) throw new Error('Security verification is unavailable. Keep this request and reload the builder before retrying.');
        const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': token}, body: JSON.stringify(body)});
        const result = await response.json();
        if (!response.ok) { change.hidden = !result.can_change_request; throw new Error(result.error || 'The request failed. Keep the selection and retry.'); }
        return result;
    }
    async function refreshCounts() {
        const url = new URL(location.href);
        url.searchParams.delete('folders'); url.searchParams.delete('quizzes');
        for (const folder of data.scope.folders) url.searchParams.append('folders', folder);
        for (const id of data.scope.quizzes) url.searchParams.append('quizzes', id);
        const response = await fetch(url.href, {cache: 'no-store', headers: {Accept: 'text/html'}});
        if (!response.ok) throw new Error('Counts could not be refreshed.');
        const html = await response.text();
        if (!context.isConnected) return;
        const documentCopy = new DOMParser().parseFromString(html, 'text/html');
        const fresh = JSON.parse(documentCopy.getElementById('studyMistakeContext')?.textContent || 'null');
        if (!fresh || fresh.generation !== data.generation || canonical(fresh.scope) !== canonical(data.scope)) throw new Error('The profile or checked sources changed. Reload and check your sources before creating more work.');
        const replacements = ['studyMistakeResults','studyMistakeExclusions'].map(id => documentCopy.getElementById(id));
        if (replacements.some(node => !node)) throw new Error('Counts could not be refreshed.');
        replacements.forEach(node => {
            const old = document.getElementById(node.id);
            const disclosures = [...old.querySelectorAll('details')].filter(d => d.id).map(d => [d.id, d.open]);
            old.replaceWith(node);
            for (const [id, wasOpen] of disclosures) { const d = document.getElementById(id); if (d) d.open = wasOpen; }
        });
        Object.assign(data, fresh); context.textContent = JSON.stringify(data);
        freshCounts = true; refreshMessage.textContent = 'Counts updated from saved data.'; refreshButton.hidden = true;
    }
    async function updateCounts() {
        try { await refreshCounts(); }
        catch (error) { freshCounts = false; refreshMessage.textContent = `${error.message} Your saved quiz remains confirmed. Use Refresh counts or reload; do not create a replacement for it.`; refreshButton.hidden = false; }
    }
    async function send() {
        if (busy || !pending) return;
        busy = true; sync(); status.textContent = 'Creating your saved mix…';
        let result;
        try { result = await post('/api/quiz-composer/study-mistakes/create', pending); }
        catch (error) { status.textContent = `${error.message} Retry same request keeps its original selection and name.`; busy = false; sync(); return; }
        // A known acknowledgement is never turned into a failed publication by a display-refresh error.
        status.textContent = `${result.title} is saved in Quiz Library as a Mixed Quiz.`;
        open.href = result.url; open.hidden = false;
        pending = null; completed = true; change.hidden = true;
        try { sessionStorage.removeItem(key); } catch (_error) { recoveryCleared = false; }
        saveDraft(); freshCounts = false; refreshMessage.textContent = 'Updating saved counts…'; sync(); await updateCounts();
        if (!recoveryCleared) refreshMessage.textContent += ' Browser request recovery could not be cleared; reload before preparing another quiz.';
        busy = false; sync();
    }
    form.addEventListener('submit', event => {
        event.preventDefault();
        if (create.disabled || changed() || pending || busy || completed || !freshCounts || !form.reportValidity()) return;
        saveDraft();
        pending = {request_id: data.request_id, generation: data.generation, scope: data.scope, fingerprint: data.fingerprint,
            mode: mode.value, count: Number(count.value), title: title.value, pass_id: mode.value === 'random' ? null : data.pass_id};
        try { sessionStorage.setItem(key, JSON.stringify(pending)); }
        catch (_error) { pending = null; status.textContent = 'Browser request recovery is unavailable. Enable session storage before creating a mix.'; sync(); return; }
        send();
    });
    retry.addEventListener('click', send);
    next.addEventListener('click', () => { if (next.hidden || next.disabled) return; completed = false; sync(); title.focus(); });
    refreshButton.addEventListener('click', async () => { if (busy) return; busy = true; sync(); await updateCounts(); busy = false; sync(); });
    change.addEventListener('click', () => {
        if (busy || change.hidden || !confirm('Change this rejected request? Only this creation request will be cleared. Saved quizzes, answers and passes stay unchanged.')) return;
        pending = null; sessionStorage.removeItem(key); saveDraft(); location.reload();
    });
    start.addEventListener('click', async () => {
        if (start.disabled || changed() || busy || pending) return;
        if (data.pass_id && !confirm('Start a new pass? Questions used before may appear again. The previous pass and saved quizzes remain stored.')) return;
        saveDraft(); busy = true; sync();
        try { await post('/api/quiz-composer/study-mistakes/pass', {scope: data.scope, generation: data.generation, fingerprint: data.fingerprint, expected_pass: data.pass_id}); location.reload(); }
        catch (error) { status.textContent = error.message; busy = false; sync(); }
    });
    mode.addEventListener('change', () => { if (mode.value === 'random' && !count.value && data.eligible) count.value = Math.min(20, data.eligible); saveDraft(); sync(); });
    if (pending) status.textContent = `A retained creation request for “${pending.title}” needs an acknowledgement. Retry it before creating another mix; its original sources will not change.`;
    browse.value = pickedFolders.size ? 'selected' : 'all';
    renderBrowse(); sync();
})();
