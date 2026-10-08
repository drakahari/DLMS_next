/* Manual copy only; no AI requests, clipboard dependency or security override. */
(() => {
    'use strict';
    document.querySelector('[data-cert-copy]')?.addEventListener('click', () => {
        const prompt = document.querySelector('#certPrompt');
        const status = document.querySelector('#certCopyStatus');
        prompt.focus(); prompt.select();
        let copied = false;
        try { copied = document.execCommand('copy'); } catch (_) { /* keep selected for manual copy */ }
        status.textContent = copied ? 'Prompt copied. Open your AI and paste it yourself.' : 'Text selected. Use Ctrl+C or your device’s Copy action, then paste it into your AI.';
    });
})();
