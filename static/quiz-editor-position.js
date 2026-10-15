/* Restore only the editing position after the existing save-on-add redirect.
   Quiz content, validation and persistence remain owned by the editor form. */
(() => {
    'use strict';
    const form = document.getElementById('edit-quiz-form');
    if (!form) return;
    const key = `dlms.editor.add-choice-position:${location.pathname}`;
    form.addEventListener('submit', event => {
        const match = /^add_choices_(\d+)$/.exec(event.submitter?.value || '');
        if (!match || event.defaultPrevented) return;
        const question = document.getElementById(`quiz-question-${match[1]}`);
        if (!question) return;
        const intent = {
            question: match[1],
            fields: [...question.querySelectorAll('input[name^="choice_"]')].map(input => input.name),
            time: Date.now(),
        };
        // Run after other submit listeners so a rejected submission leaves no
        // navigation intent. This tab-local record contains no answer text.
        queueMicrotask(() => {
            if (event.defaultPrevented) return;
            try { sessionStorage.setItem(key, JSON.stringify(intent)); } catch (_) { /* Storage unavailable. */ }
        });
    });
    let intent;
    try {
        intent = JSON.parse(sessionStorage.getItem(key) || 'null');
        sessionStorage.removeItem(key);
    } catch (_) { return; }
    if (!intent || !/^\d+$/.test(intent.question) || !Array.isArray(intent.fields)
        || !Number.isFinite(intent.time) || Date.now() - intent.time > 120000 || Date.now() < intent.time) return;
    const question = document.getElementById(`quiz-question-${intent.question}`);
    if (!question) return;
    const added = [...question.querySelectorAll('input[name^="choice_"]')]
        .find(input => !intent.fields.includes(input.name));
    requestAnimationFrame(() => {
        if (added) added.focus({preventScroll: true});
        (added?.closest('li') || question).scrollIntoView({block: 'center', behavior: 'instant'});
    });
})();
