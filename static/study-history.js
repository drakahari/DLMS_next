/* Disclosure preferences are tab-local UI state, never learning evidence. */
(() => {
  'use strict';
  const root = document.getElementById('studyHistory');
  if (!root) return;
  const key = 'dlms-study-history-view:' + root.dataset.generation;
  let opened = [], pages = {};
  try { const saved = JSON.parse(sessionStorage.getItem(key)); if (Array.isArray(saved?.opened)) opened = saved.opened.filter(x => typeof x === 'string').slice(-100); if (saved?.pages && typeof saved.pages === 'object') pages = saved.pages; } catch (_) {}
  function remember(node) {
    const id = node.dataset.historySession || node.id;
    opened = opened.filter(x => x !== id);
    if (node.open) opened.push(id);
    opened = opened.slice(-100);
    try { sessionStorage.setItem(key, JSON.stringify({opened, pages:Object.fromEntries(Object.entries(pages).filter(([id])=>opened.includes(id)).slice(-100))})); } catch (_) {}
  }
  async function load(node, url, focus = false) {
    const content = node.querySelector('[data-session-content]');
    if (node.dataset.loading) return;
    node.dataset.loading = 'true';
    content.setAttribute('aria-busy', 'true');
    content.textContent = 'Loading session details…';
    try {
      const target = new URL(url, location.href);
      const expected = new URL(node.dataset.historyUrl, location.href);
      if (target.origin !== expected.origin || target.pathname !== expected.pathname) throw new Error('Reload this history page to open session details.');
      target.searchParams.set('fragment', '1');
      const response = await fetch(target, {headers: {'Accept':'text/html'}});
      if (!response.ok) throw new Error(response.status === 404 ? 'This session is unavailable. It may have been deleted or restored.' : 'Session details could not be loaded.');
      content.innerHTML = await response.text();
      content.querySelectorAll('[data-local-instant]').forEach(n => { n.textContent = DLMSLocalTime.format(n.dataset.localInstant); });
      node.dataset.loaded = 'true';
      pages[node.dataset.historySession] = target.pathname + target.search; remember(node);
      if (focus) content.querySelector('[data-detail-heading]').focus();
    } catch (error) {
      const message = document.createElement('p'); message.setAttribute('role','status'); message.textContent = error.message;
      const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Retry session details';
      retry.addEventListener('click', () => load(node, url, true));
      content.replaceChildren(message, retry);
    } finally { delete node.dataset.loading; content.removeAttribute('aria-busy'); }
  }
  root.querySelectorAll('[data-history-session], [data-history-disclosure]').forEach(node => {
    if (opened.includes(node.dataset.historySession || node.id)) node.open = true;
    node.addEventListener('toggle', () => {
      remember(node);
      if (node.open && node.dataset.historySession && !node.dataset.loaded) load(node, pages[node.dataset.historySession] || node.dataset.historyUrl);
    });
    if (node.open && node.dataset.historySession) load(node, pages[node.dataset.historySession] || node.dataset.historyUrl);
    node.addEventListener('click', event => {
      const link = event.target.closest('[data-session-page]');
      if (link && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
        event.preventDefault(); load(node, link.href, true);
      }
    });
  });
})();
