/* The combined action keeps the same copy-before-window.open user gesture as
   Study's question/answer AI review. It never records Study assistance. */
(() => {
    'use strict';
    const prompt = document.querySelector('#certPrompt');
    if (!prompt) return;
    const status = document.querySelector('#certCopyStatus');
    const manual = document.querySelector('#certProviderLink');
    const selectForManualCopy = () => {prompt.focus(); prompt.select();};
    document.querySelector('[data-cert-copy]')?.addEventListener('click', async () => {
        let copied = false;
        try {copied = await window.dlmsManualAI.copyWithFallback(prompt.value);} catch (_) {}
        if (!copied) selectForManualCopy();
        status.textContent = copied ? 'Prompt copied.' : 'Copy failed. Text selected: use Ctrl+C or your device’s Copy action.';
    });
    document.querySelector('[data-cert-launch]')?.addEventListener('click', () => {
        let copied = false;
        try {copied = window.dlmsManualAI.copySynchronously(prompt.value) === true;} catch (_) {}
        if (!copied) selectForManualCopy();
        try {if (manual) window.open(manual.href, '_blank', 'noopener,noreferrer');} catch (_) {}
        // noopener can return null even when a tab opens: never claim success
        // from that value. The real link always works for a manual second click.
        status.textContent = copied
            ? 'Prompt copied. Paste it into your AI. If no tab opened, select Open AI manually.'
            : 'Copy failed. Select and copy the preview manually, then paste it into your AI. If no tab opened, select Open AI manually.';
    });
})();
/* Presets only edit the unsaved form. They never set personal dates or credits. */
(() => {
    const apply = document.querySelector('#applyCertPreset');
    if (!apply) return;
    apply.addEventListener('click', () => {
        const all = JSON.parse(document.querySelector('#certRulePresets').textContent);
        const preset = all[document.querySelector('#certRulePreset').value];
        const status = document.querySelector('#presetStatus');
        if (!preset) { status.textContent = 'Choose a preset, or keep entering your own rules.'; return; }
        const form = apply.closest('form');
        const set = (name, value) => { const input = form.elements.namedItem(name); if (input) input.value = value ?? ''; };
        for (const name of ['required','unit','policy']) set('field_'+name, preset[name]);
        for (const [name,value] of Object.entries(preset.tracking)) {
            if (!['categories','requirement_known'].includes(name)) set('track_'+name,value);
        }
        // Reset only the rule fields supplied by presets, not personal reporting dates.
        set('track_annual_amount',preset.tracking.annual_amount ?? '');
        for (let i=0;i<6;i++) for (const key of ['name','minimum','cap']) set(`category_${i}_${key}`,preset.tracking.categories?.[i]?.[key]);
        status.textContent = 'Rule fields filled for your review; nothing saved. Check the version, route, unknown requirements and your reporting dates, then save.';
    });
})();

// Choosing another period is explicit; never retain a conversion from another unit.
document.querySelectorAll('[data-renewal-period]').forEach(select => {
    select.addEventListener('change', () => {
        const row=select.closest('[data-renewal-choice]'), option=select.selectedOptions[0];
        row.querySelector('[data-renewal-unit]').textContent=option.dataset.unit;
        row.querySelector('input[type=number]').value=option.dataset.estimate;
        row.querySelector('[data-renewal-status]').textContent='Period changed. Review this period’s estimate before saving.';
    });
});
