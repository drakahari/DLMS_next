/* Presentation enhancement only: existing links, buttons, listeners and native
   disclosures remain authoritative. No requests or saved application state. */
(() => {
    'use strict';
    const root = document.querySelector('[data-home-dashboard], #studyHistory');
    if (!root) return;
    const selector = root.id === 'studyHistory'
        ? '[aria-label="History navigation"] a, .study-history-pages a, [data-session-content] > a, [data-session-content] button'
        : '.daily-review-action, .daily-review-remove, #retryPlanPractice, .dashboard-plan-actions > a, .dashboard-plan-explanation > a, #reviewSuggestionsExplanation > a, #recentActivity a:not(p a), #dailyReviewEmpty > button';
    const tips = new Map([
        ['View plan', 'View your plan, study material changes and estimates.'],
        ['Open current quiz', 'Open the current quiz content. This does not start or finish a review.'],
        ['Open next quiz', 'Open the next regular quiz in this folder’s saved Quiz Library order.'],
        ['Review attempt', 'View the answers and score saved for this Exam attempt.'],
        ['Study Help', 'Read about Study sessions, saved responses and safe recovery.'],
    ]);
    const descriptions = new Map();
    let serial = 0, active = null, closeTimer;
    function label(node) { return node.textContent.trim(); }
    function icon(node) {
        const text = label(node);
        if (/Retry/.test(text)) return 'refresh';
        if (/Clear/.test(text)) return 'trash';
        if (/Previous|Newer/.test(text)) return 'back';
        if (/next|Next|Older|Start|Resume/.test(text)) return 'forward';
        if (/Help/.test(text)) return 'help';
        if (/History|Review attempt|session details/.test(text)) return 'history';
        if (text === 'Dashboard') return 'home';
        if (/quiz|Quiz|plan|Plan/.test(text)) return 'library';
        return 'settings';
    }
    function close() {
        clearTimeout(closeTimer);
        if (active) descriptions.get(active).hidden = true;
        active = null;
    }
    function position() {
        if (!active) return;
        const tip = descriptions.get(active), box = active.getBoundingClientRect();
        const bounds = tip.getBoundingClientRect();
        const blockers = [...root.querySelectorAll('a, button, summary, input, select, textarea')]
            .filter(node => node !== active)
            .map(node => ({rect: node.getBoundingClientRect(), primary: node.hasAttribute('data-dashboard-primary')}))
            .filter(({rect}) => rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight);
        // Prefer an adjacent placement, but keep another action (especially
        // Start suggested work) usable while a focus/hover tooltip is open.
        const candidates = [
            [box.left, box.top - bounds.height - 8],
            [box.left, box.bottom + 8],
            [box.right + 8, box.top],
            [box.left - bounds.width - 8, box.top],
            ...blockers.flatMap(({rect}) => [
                [box.left, rect.top - bounds.height - 8], [box.left, rect.bottom + 8],
            ]),
        ];
        let best, overlap = Infinity;
        for (const [x, y] of candidates) {
            const left = Math.max(12, Math.min(x, innerWidth - bounds.width - 12));
            const top = Math.max(12, Math.min(y, innerHeight - bounds.height - 12));
            const area = blockers.reduce((total, {rect, primary}) => total
                + Math.max(0, Math.min(left + bounds.width, rect.right) - Math.max(left, rect.left))
                * Math.max(0, Math.min(top + bounds.height, rect.bottom) - Math.max(top, rect.top))
                * (primary ? 100 : 1), 0);
            if (area < overlap) { best = {left, top}; overlap = area; }
            if (area === 0) break;
        }
        tip.style.left = best.left + 'px';
        tip.style.top = best.top + 'px';
    }
    function show(node) {
        clearTimeout(closeTimer);
        if (node.dataset.tooltipDismissed || node.disabled) return;
        close();
        const tip = descriptions.get(node);
        tip.textContent = tips.get(label(node));
        tip.hidden = false;
        active = node;
        position();
    }
    function leave(node) {
        closeTimer = setTimeout(() => {
            const tip = descriptions.get(node);
            if (!tip) return; // A live widget may have removed this control.
            if (!node.matches(':hover, :focus') && !tip.matches(':hover')) {
                delete node.dataset.tooltipDismissed;
                if (active === node) close();
            }
        }, 150); // Let the pointer cross the small gap to the hoverable tip.
    }
    function enhance() {
        for (const [node, tip] of descriptions) {
            if (!node.isConnected) {
                if (active === node) close();
                tip.remove(); descriptions.delete(node);
            }
        }
        root.querySelectorAll(selector).forEach(node => {
            node.classList.add('dlms-action-control');
            if (!node.querySelector(':scope > .dlms-icon')) {
                const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svg.setAttribute('class', 'dlms-icon');
                svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('focusable', 'false');
                const use = document.createElementNS(svg.namespaceURI, 'use');
                use.setAttribute('href', '/static/icons.svg#' + icon(node));
                svg.append(use); node.prepend(svg);
            }
            if (!tips.has(label(node)) || descriptions.has(node)) return;
            const tip = document.createElement('div');
            tip.id = 'dlms-action-tooltip-' + (++serial);
            tip.className = 'dlms-action-tooltip'; tip.setAttribute('role', 'tooltip'); tip.hidden = true;
            tip.textContent = tips.get(label(node));
            document.body.append(tip); descriptions.set(node, tip);
            node.setAttribute('aria-describedby', [node.getAttribute('aria-describedby'), tip.id].filter(Boolean).join(' '));
            // Use one focus/hover description rather than a competing native title.
            node.removeAttribute('title');
            node.addEventListener('pointerenter', () => show(node));
            node.addEventListener('focus', () => show(node));
            node.addEventListener('pointerleave', () => leave(node));
            node.addEventListener('blur', () => { delete node.dataset.tooltipDismissed; leave(node); });
            tip.addEventListener('pointerenter', () => clearTimeout(closeTimer));
            tip.addEventListener('pointerleave', () => leave(node));
        });
    }
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && active) {
            active.dataset.tooltipDismissed = 'true'; close();
        }
    });
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    enhance();
    new MutationObserver(enhance).observe(root, {childList: true, subtree: true});
})();
