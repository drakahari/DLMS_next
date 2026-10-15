(() => {
    "use strict";
    const form = document.querySelector('form[action="/settings/layout/save"]');
    if (!form) return;
    const initial = () => JSON.stringify([...new FormData(form)].filter(([name]) => name !== 'csrf_token'));
    const mode=form.elements.certification_count_mode;
    if(mode){
        const update=()=>{const all=mode.value==='all';form.querySelector('[data-custom-certification-count]').hidden=all;form.elements.certification_display_count.disabled=all;};
        mode.addEventListener('change',update);update();
    }
    const saved=initial();
    const dirty=()=>initial()!==saved;
    form.addEventListener('submit',event=>{
        const action=event.submitter?.value;
        if(['dashboard_defaults','sidebar_defaults'].includes(action) && dirty() &&
            !window.confirm('Restore applies immediately and discards unsaved form edits. Continue?'))event.preventDefault();
    });
    for (const button of form.querySelectorAll("[data-hide-study-area]")) {
        button.addEventListener("click", () => {
            const key = button.dataset.hideStudyArea;
            form.elements[`dashboard_card_${key}`].checked = false;
            form.elements[`study_area_${key}`].checked = false;
            document.getElementById("layoutFormStatus").textContent =
                `${button.closest("fieldset").querySelector("legend").textContent} will be hidden from both locations. Save to apply.`;
        });
    }
})();
