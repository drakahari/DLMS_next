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
