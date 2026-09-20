/* Native details remain operable without JavaScript; bulk actions affect this page. */
(() => {
    const groups = [...document.querySelectorAll('details.duplicate-question-group')];
    const sync = group => group.querySelector('summary').setAttribute('aria-expanded', String(group.open));
    groups.forEach(group => { sync(group); group.addEventListener('toggle', () => sync(group)); });
    document.getElementById('expandDuplicateGroups')?.addEventListener('click', () => {
        groups.forEach(group => { group.open = true; sync(group); });
    });
    document.getElementById('collapseDuplicateGroups')?.addEventListener('click', () => {
        groups.forEach(group => { group.open = false; sync(group); });
    });
})();
