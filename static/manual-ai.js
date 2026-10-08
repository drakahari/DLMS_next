/* Shared with Study question AI review. Copies only; no network or evidence. */
(() => {
"use strict";
function copySynchronously(text) {
    const previousFocus = document.activeElement;
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    textarea.style.top = "-9999px";

    try {
        document.body.appendChild(textarea);
        textarea.focus({preventScroll: true});
        textarea.select();
        return document.execCommand("copy");
    } finally {
        if (textarea.parentNode) textarea.parentNode.removeChild(textarea);
        if (previousFocus?.isConnected) previousFocus.focus({preventScroll: true});
        if (window.scrollX !== scrollX || window.scrollY !== scrollY) {
            window.scrollTo(scrollX, scrollY);
        }
    }
}

async function copyWithFallback(text) {
    try {
        if (window.isSecureContext && typeof navigator.clipboard?.writeText === "function") {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch (error) {
        // Copy denial falls back without logging prompt text.
    }
    return copySynchronously(text) === true;
}

function provider(config) {
    if (!config?.ai_helper_enabled) return '';
    const providers = {chatgpt:'https://chatgpt.com/',claude:'https://claude.ai/',gemini:'https://gemini.google.com/'};
    return config.ai_provider === 'local' ? (config.ai_custom_url || '').trim() : (providers[config.ai_provider] || '');
}
window.dlmsManualAI = {copySynchronously, copyWithFallback, provider};
})();
