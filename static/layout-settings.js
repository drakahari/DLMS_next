(() => {
    "use strict";
    const form = document.querySelector('form[action="/settings/layout/save"]');
    if (!form) return;
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
