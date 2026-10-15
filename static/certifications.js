/* The combined action keeps the same copy-before-window.open user gesture as
   Study's question/answer AI review. It never records Study assistance. */
(() => {
    'use strict';
    const prompt = document.querySelector('#certPrompt');
    if (!prompt) return;
    const status = document.querySelector('#certCopyStatus');
    const manual = document.querySelector('#certProviderLink');
    const selectForManualCopy = () => {document.querySelector('#certPreviewDetails').open=true; prompt.focus(); prompt.select();};
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
        document.querySelector('#certLaunchRecovery').open=true;
        try {if (manual) window.open(manual.href, '_blank', 'noopener,noreferrer');} catch (_) {}
        // noopener can return null even when a tab opens: never claim success
        // from that value. The real link always works for a manual second click.
        status.textContent = copied
            ? 'Prompt copied. Paste it into your AI. If no tab opened, select Open AI manually.'
            : 'Copy failed. Select and copy the preview manually, then paste it into your AI. If no tab opened, select Open AI manually.';
    });
})();
/* Optional requirements editor: load only after explicit review. */
(() => {
    const apply=document.querySelector('#applyCertPreset');
    if (!apply) return;
    const form=apply.closest('form'), categories=document.querySelector('#certCategories');
    const add=document.querySelector('#addCertCategory');
    const reindex=()=>{
        categories.querySelectorAll('[data-category-row]').forEach((row,i)=>{
            row.querySelector('legend').textContent=`Category ${i+1}`;
            row.querySelectorAll('input').forEach(input=>{input.name=`category_${i}_${input.name.split('_').at(-1)}`;});
        });
        add.disabled=categories.children.length>=6;
    };
    const addRow=(data={})=>{
        if(categories.children.length>=6)return;
        const row=document.createElement('fieldset');row.dataset.categoryRow='';
        row.innerHTML='<legend></legend><div class="cert-fields"></div><button type="button" class="dlms-action-control" data-remove-category>Remove category</button>';
        for(const [key,label] of [['name','Name'],['minimum','Minimum (optional)'],['cap','Maximum counted (optional)']]){
            const wrapper=document.createElement('label'),input=document.createElement('input');
            wrapper.textContent=label;input.name=`category_0_${key}`;input.type=key==='name'?'text':'number';
            if(key==='name')input.maxLength=100;else{input.min='0';input.max='100000';input.step='0.01';}
            input.value=data[key]??'';wrapper.append(input);row.querySelector('.cert-fields').append(wrapper);
        }
        categories.append(row);reindex();return row;
    };
    add.addEventListener('click',()=>{addRow()?.querySelector('input').focus();});
    categories.addEventListener('click',event=>{
        if(event.target.closest('[data-remove-category]')){event.target.closest('[data-category-row]').remove();reindex();add.focus();}
    });reindex();
    const dependencies=()=>{
        const kind=form.elements.track_annual_kind.value,basis=form.elements.track_year_basis.value;
        form.elements.track_annual_amount.closest('label').hidden=!['minimum','pacing'].includes(kind);
        form.elements.track_year_anchor.closest('label').hidden=basis!=='anniversary';
    };
    form.elements.track_annual_kind.addEventListener('change',dependencies);
    form.elements.track_year_basis.addEventListener('change',dependencies);dependencies();
    const presetSelect=document.querySelector('#certRulePreset');
    const updatePreset=()=>{apply.disabled=!presetSelect.value;document.querySelector('#certPresetReview').hidden=true;};
    presetSelect.addEventListener('change',updatePreset);updatePreset();
    const all=JSON.parse(document.querySelector('#certRulePresets').textContent);
    let pending=null;
    apply.addEventListener('click',()=>{
        pending=all[document.querySelector('#certRulePreset').value];
        const status=document.querySelector('#presetStatus');
        if(!pending){status.textContent='Choose suggested requirements, or keep your custom values.';return;}
        const review=document.querySelector('#certPresetReview');
        review.hidden=false;
        document.querySelector('#certPresetSource').textContent=pending.policy || 'Source not recorded';
        document.querySelector('#certPresetSummary').textContent=`${pending.tracking.version || 'Version not specified'} · ${pending.tracking.route || 'Route not specified'}. Source checked: ${pending.tracking.checked || 'not recorded'}. Your requirements remain unverified until you check them.`;
        review.querySelector('button').focus();
    });
    document.querySelector('#cancelCertPreset').addEventListener('click',()=>{document.querySelector('#certPresetReview').hidden=true;pending=null;apply.focus();});
    document.querySelector('#confirmCertPreset').addEventListener('click',()=>{
        if(!pending)return;
        const set=(name,value)=>{const input=form.elements.namedItem(name);if(input)input.value=value??'';};
        for(const name of ['required','unit','policy'])set('field_'+name,pending[name]);
        for(const [name,value] of Object.entries(pending.tracking))if(!['categories','requirement_known'].includes(name))set('track_'+name,value);
        set('track_annual_amount',pending.tracking.annual_amount??'');
        categories.replaceChildren();for(const category of pending.tracking.categories??[])addRow(category);
        reindex();dependencies();document.querySelector('#certPresetReview').hidden=true;
        document.querySelector('#presetStatus').textContent='Suggested requirements loaded for review; nothing saved. Personal reporting dates stay unchanged. Review before Save changes.';
        pending=null;form.elements.field_required.focus();
    });
})();

// Only checked rows are candidates for this atomic save; unchecked links persist.
document.querySelectorAll('[data-renewal-choice]').forEach(row=>{
    const checkbox=row.querySelector('[name=certifications]'), editor=row.querySelector('[data-renewal-edit]');
    const update=()=>{editor.hidden=!checkbox.checked;};
    checkbox.addEventListener('change',update);update();
    const select=row.querySelector('[data-renewal-period]');
    select.addEventListener('change',()=>{
        const option=select.selectedOptions[0];
        row.querySelector('[data-renewal-unit]').textContent=option.dataset.unit;
        row.querySelector('input[type=number]').value=option.dataset.estimate;
        row.querySelector('[data-renewal-status]').textContent='Period changed. Review this period’s estimate before saving.';
    });
});

const selectionForm=document.querySelector('[data-match-selection]');
if(selectionForm){
    const selection=()=>JSON.stringify([...new FormData(selectionForm)].filter(([name])=>['credentials','training','question'].includes(name)));
    const preparedSelection=selection();
    const update=()=>{
        const certs=selectionForm.querySelectorAll('[name=credentials]:checked').length,courses=selectionForm.querySelectorAll('[name=training]:checked').length;
        document.querySelector('#certMatchCount').textContent=`${certs} certification${certs===1?'':'s'} · ${courses} course${courses===1?'':'s'}`;
        document.querySelector('#certNoTraining').hidden=courses>0;
        if(document.querySelector('#certAIPreview')){
            const changed=selection()!==preparedSelection;
            document.querySelectorAll('[data-cert-copy],[data-cert-launch]').forEach(button=>{button.disabled=changed;});
            document.querySelector('#certCopyStatus').textContent=changed?'Selection or question changed. Prepare prompt again before copying.':'';
        }
    };selectionForm.addEventListener('change',update);selectionForm.addEventListener('input',update);update();
}

// Selecting a row opts into an add/update; it never opts out of a saved link.
const renewalForm=document.querySelector('.cert-use-form');
if(renewalForm){
    const update=()=>{
        const count=renewalForm.querySelectorAll('[name=certifications]:checked').length;
        document.querySelector('#renewalSelectionCount').textContent=`${count} certification${count===1?'':'s'} selected. ${count?'Selected rows will be added or updated.':'Select rows to add or update.'}`;
        const submit=renewalForm.querySelector('[data-renewal-submit]');if(submit)submit.disabled=count===0;
    };
    renewalForm.addEventListener('change',update);update();
}
