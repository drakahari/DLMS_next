/* Explicit, retry-safe composition. No answer/recovery or learning writes. */
(() => {
    'use strict';
    const context = document.getElementById('studyMistakeContext');
    if (!context) return;
    const data = JSON.parse(context.textContent);
    const form = document.getElementById('mistakeCreateForm');
    const mode = document.getElementById('mistakeMode');
    const create = document.getElementById('createMistakeMix');
    const start = document.getElementById('startMistakePass');
    const retry = document.getElementById('retryMistakeMix');
    const change = document.getElementById('changeMistakeRequest');
    const status = document.getElementById('mistakeStatus');
    const open = document.getElementById('openMistakeMix');
    const key = 'dlms-study-mistakes-request';
    const draftKey = 'dlms-study-mistakes-draft.' + data.generation + '.' + JSON.stringify(data.scope);
    try {
        const draft = JSON.parse(sessionStorage.getItem(draftKey));
        if (draft) {
            document.getElementById('mistakeTitle').value = draft.title || '';
            document.getElementById('mistakeCount').value = draft.count;
            if (['random', 'without-repeats'].includes(draft.mode)) mode.value = draft.mode;
        }
    } catch (_error) { /* No valid draft. */ }
    form.addEventListener('input', () => {
        try { sessionStorage.setItem(draftKey, JSON.stringify({title: document.getElementById('mistakeTitle').value,
            count: document.getElementById('mistakeCount').value, mode: mode.value})); } catch (_error) { /* Creation verifies recovery storage separately. */ }
    });
    let pending = null, busy = false, completed = false;
    try { pending = JSON.parse(sessionStorage.getItem(key)); } catch (_error) { /* No saved request. */ }
    function sync() {
        create.disabled = completed || busy || !!pending || (mode.value === 'random' ? !data.eligible : !data.pass_id || !data.remaining);
        start.disabled = completed || busy || !!pending || !data.eligible;
        retry.hidden = !pending;
        retry.disabled = busy;
    }
    async function post(url, body) {
        const token = window.dlmsCsrfToken || document.querySelector('[name=csrf-token]')?.content;
        if (!token) throw new Error('Security verification is unavailable. Keep this request and reload the builder before retrying.');
        const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': token}, body: JSON.stringify(body)});
        const result = await response.json();
        if (!response.ok) {
            change.hidden = !result.can_change_request;
            throw new Error(result.error || 'The request failed. Keep the selection and retry.');
        }
        return result;
    }
    async function send() {
        if (busy || !pending) return;
        busy = true; sync(); status.textContent = 'Creating your saved mix…';
        try {
            const result = await post('/api/quiz-composer/study-mistakes/create', pending);
            status.textContent = `${result.title} is saved in Quiz Library as a Mixed Quiz. Open it, or reload to see the current pass counts.`;
            open.href = result.url; open.hidden = false;
            sessionStorage.removeItem(draftKey);
            pending = null; completed = true; change.hidden = true;
            sessionStorage.removeItem(key);
            // Do not offer another batch against stale remaining counts.
            data.remaining = 0;
        } catch (error) {
            status.textContent = `${error.message} Retry same request keeps its original selection and name.`;
        } finally { busy = false; sync(); }
    }
    form.addEventListener('submit', event => {
        event.preventDefault();
        if (pending || busy || !form.reportValidity()) return;
        pending = {request_id: data.request_id, generation: data.generation, scope: data.scope, fingerprint: data.fingerprint,
            mode: mode.value, count: Number(document.getElementById('mistakeCount').value), title: document.getElementById('mistakeTitle').value,
            pass_id: mode.value === 'random' ? null : data.pass_id};
        try { sessionStorage.setItem(key, JSON.stringify(pending)); }
        catch (_error) { pending = null; status.textContent = 'Browser request recovery is unavailable. Enable session storage before creating a mix.'; sync(); return; }
        send();
    });
    retry.addEventListener('click', send);
    change.addEventListener('click', () => {
        if (busy || change.hidden || !confirm('Change this rejected request? Only this creation request will be cleared. Saved quizzes, answers and passes stay unchanged.')) return;
        pending = null;
        sessionStorage.removeItem(key);
        // The server confirmed no uncertain publication remains. A fresh page
        // supplies a new server-generated request ID and current counts/epoch.
        location.reload();
    });
    start.addEventListener('click', async () => {
        if (busy || pending) return;
        if (data.pass_id && !confirm('Start a new pass? Questions used before may appear again. The previous pass and saved quizzes remain stored.')) return;
        busy = true; sync();
        try {
            await post('/api/quiz-composer/study-mistakes/pass', {scope: data.scope, generation: data.generation, fingerprint: data.fingerprint, expected_pass: data.pass_id});
            location.reload();
        } catch (error) { status.textContent = error.message; busy = false; sync(); }
    });
    mode.addEventListener('change', sync);
    if (pending) status.textContent = `A retained creation request for “${pending.title}” needs an acknowledgement. Retry it before creating another mix; its selection will not change.`;
    sync();
})();
