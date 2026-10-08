/* One form, one atomic save; prompt defaults edit the form only. */
(() => {
    'use strict';
    const form=document.querySelector('#aiSettingsForm');
    if(!form)return;
    const status=document.querySelector('#aiSettingsStatus');
    const row=form.querySelector('.ai-settings-actions');
    const snapshot=()=>JSON.stringify([...new FormData(form)].filter(([name])=>name!=='csrf_token'));
    const initial=snapshot();
    let leaving=false;
    const dirty=()=>form.dataset.unsaved==='true'||snapshot()!==initial;
    const update=()=>{status.textContent=dirty()?'Unsaved changes — Save AI settings to apply all edits.':'No unsaved changes.';};
    form.addEventListener('input',update);
    form.addEventListener('change',update);
    form.addEventListener('submit',()=>{leaving=true;});
    document.querySelector('#cancelAISettings').addEventListener('click',event=>{
        if(dirty()&&!window.confirm('Discard unsaved AI settings and reload the saved values?')){event.preventDefault();return;}
        leaving=true;
    });
    window.addEventListener('beforeunload',event=>{
        if(dirty()&&!leaving){event.preventDefault();event.returnValue='';}
    });
    // Keep a sticky row from covering keyboard focus, including native zoom.
    const measure=()=>form.style.setProperty('--ai-action-height',`${row.getBoundingClientRect().height+20}px`);
    new ResizeObserver(measure).observe(row);measure();
    form.addEventListener('focusin',event=>requestAnimationFrame(()=>{
        if(row.contains(event.target))return;
        const target=event.target.getBoundingClientRect(),bar=row.getBoundingClientRect();
        if(target.bottom>bar.top&&target.top<bar.bottom)event.target.scrollIntoView({block:'center'});
    }));
})();
