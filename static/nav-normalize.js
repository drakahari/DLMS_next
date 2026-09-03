(() => {
  const readCookie = (name) => {
    const prefix = `${name}=`;
    const match = document.cookie.split(';').map(value => value.trim()).find(value => value.startsWith(prefix));
    return match ? decodeURIComponent(match.slice(prefix.length)) : '';
  };
  const csrfToken = readCookie('dlms_csrf_token');
  const unsafeMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
  const isSameOrigin = (value) => {
    try { return new URL(value || window.location.href, window.location.href).origin === window.location.origin; }
    catch (_error) { return false; }
  };
  const protectForm = (form) => {
    const method = (form.getAttribute('method') || 'GET').toUpperCase();
    if (!csrfToken || !unsafeMethods.has(method) || !isSameOrigin(form.getAttribute('action'))) return form;
    let field = form.querySelector('input[name="csrf_token"]');
    if (!field) {
      field = document.createElement('input');
      field.type = 'hidden';
      field.name = 'csrf_token';
      form.appendChild(field);
    }
    field.value = csrfToken;
    return form;
  };
  window.dlmsCsrfToken = csrfToken;
  window.dlmsProtectForm = protectForm;
  document.querySelectorAll('form').forEach(protectForm);

  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const requestUrl = typeof input === 'string' || input instanceof URL ? input : input.url;
    const method = String(init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (!csrfToken || !unsafeMethods.has(method) || !isSameOrigin(requestUrl)) return originalFetch(input, init);
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
    if (!headers.has('X-CSRFToken')) headers.set('X-CSRFToken', csrfToken);
    return originalFetch(input, {...init, headers});
  };

  const sidebar = document.querySelector('.dashboard-sidebar');
  if (!sidebar) return;

  const path = window.location.pathname || '/';
  const params = new URLSearchParams(window.location.search || '');
  const medicalBuilder = path === '/study-packs/ai-builder' && params.get('from') === 'medical';
  const itBuilder = path === '/study-packs/ai-builder' && params.get('from') === 'it';
  const otherBuilder = path === '/study-packs/ai-builder' && params.get('from') === 'other';
  const otherStudies = path === '/study-packs' && params.get('domain_group') === 'other';

  const isActive = (key) => {
    if (key === 'dashboard') return path === '/';
    if (key === 'library') return path === '/library' || path.startsWith('/edit_quiz') || path.startsWith('/quiz/');
    if (key === 'build') return path === '/upload' || path === '/paste' || path === '/create_short_quiz' || path === '/matching_bank_import' || path.startsWith('/pdf-import');
    if (key === 'study') return path.startsWith('/study-packs') && !medicalBuilder && !itBuilder && !otherBuilder && !otherStudies;
    if (key === 'it') return path === '/it' || path.startsWith('/it/') || itBuilder;
    if (key === 'law') return path === '/law' || path.startsWith('/law/');
    if (key === 'medical') return path === '/medical' || path.startsWith('/medical/') || medicalBuilder;
    if (key === 'other') return otherStudies || otherBuilder;
    if (key === 'history') return path === '/history' || path.startsWith('/review');
    if (key === 'analytics') return path === '/dashboard';
    if (key === 'learning') return path === '/learning-intelligence' || path === '/learning-profile' || path === '/review-schedule' || path === '/learning-diagnostics';
    if (key === 'anki') return path === '/anki' || path.startsWith('/anki/');
    if (key === 'settings') return path === '/settings' || path.startsWith('/settings/') || path === '/admin/maintenance';
    if (key === 'content') return path === '/content-packs' || path.startsWith('/content-packs/');
    if (key === 'image') return path === '/admin/image-editor' || path.startsWith('/admin/image-editor/') || path.startsWith('/admin/hotspots');
    if (key === 'help') return path === '/help' || path.startsWith('/help/') || path.startsWith('/regex-help') || path.endsWith('help.html');
    return false;
  };

  const buildOpen = isActive('build');
  const learningOpen = isActive('learning');
  const ankiOpen = isActive('anki');
  const isActiveParent = (key) => (
    (key === 'build' && buildOpen) ||
    (key === 'learning' && learningOpen) ||
    (key === 'anki' && ankiOpen && path !== '/anki')
  );
  const item = (key, href, icon, label) => {
    const active = isActive(key);
    const current = active && !isActiveParent(key);
    const context = active && isActiveParent(key);
    return `<a class="dashboard-nav-item${active ? ' active' : ''}${context ? ' nav-context' : ''}" data-nav-key="${key}" href="${href}"${current ? ' aria-current="page"' : ''}><span class="dashboard-nav-icon">${icon}</span><span>${label}</span></a>`;
  };
  const sub = (href, icon, label, active=false) => `<a class="dashboard-nav-subitem${active ? ' active' : ''}" href="${href}"${active ? ' aria-current="page"' : ''}><span class="dashboard-nav-subicon">${icon}</span><span>${label}</span></a>`;
  const primarySection = (label) => `<div class="dashboard-nav-section-label dashboard-nav-primary-section-label"><span>${label}</span></div>`;
  const defaultStudyAreaVisibility = {it: true, law: true, medical: true, other: true};
  const studyAreaVisibilityCacheKey = 'dlms.studyAreaVisibility.v1';
  const normalizeStudyAreaVisibility = (value) => {
    const configured = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    return Object.fromEntries(Object.keys(defaultStudyAreaVisibility).map(key => [
      key,
      typeof configured[key] === 'boolean' ? configured[key] : true
    ]));
  };
  const readCachedStudyAreaVisibility = () => {
    try {
      const cached = JSON.parse(localStorage.getItem(studyAreaVisibilityCacheKey) || 'null');
      if (!cached || typeof cached !== 'object' || Array.isArray(cached)) return null;
      if (!Object.keys(defaultStudyAreaVisibility).every(key => typeof cached[key] === 'boolean')) return null;
      return normalizeStudyAreaVisibility(cached);
    } catch (_error) {
      return null;
    }
  };
  const cacheStudyAreaVisibility = (visibility) => {
    try {
      localStorage.setItem(studyAreaVisibilityCacheKey, JSON.stringify(visibility));
    } catch (_error) {
      // Private browsing and locked-down local storage must not affect navigation.
    }
  };
  const applyStudyAreaVisibility = (visibility) => {
    const normalized = normalizeStudyAreaVisibility(visibility);
    Object.entries(normalized).forEach(([key, visible]) => {
      const navItem = sidebar.querySelector(`.dashboard-nav-normalized [data-nav-key="${key}"]`);
      if (navItem) navItem.hidden = !visible;
    });
  };

  const mountNavigation = (studyAreaVisibility) => {
    // Learning Intelligence pages ship with this exact canonical sidebar
    // because their content is otherwise ready to paint before this shared
    // script can replace the one-link template seed. Keep that stable DOM.
    const canonicalSeed = sidebar.querySelector(':scope > .dashboard-nav-normalized[data-navigation-seed="canonical"]');
    if (canonicalSeed) {
      applyStudyAreaVisibility(studyAreaVisibility);
      return;
    }

    const primary = document.createElement('nav');
    primary.className = 'dashboard-nav dashboard-nav-normalized';
    primary.setAttribute('aria-label', 'Primary navigation');
    primary.innerHTML = [
      item('dashboard','/','⌂','Dashboard'),
      item('library','/library','▤','Quiz Library'),
      `<div class="dashboard-nav-group">${item('build','/upload','✎','Build Quiz')}${buildOpen ? `<div class="dashboard-nav-submenu normalized-open">${sub('/upload','↳','Quiz Builder', path === '/upload' || path === '/paste' || path === '/create_short_quiz' || path === '/matching_bank_import')}${sub('/pdf-import','↳','PDF Import & Banks', path.startsWith('/pdf-import'))}</div>` : ''}</div>`,
      primarySection('Study'),
      item('study','/study-packs','▣','Study Packs'),
      // IT and Medical landing pages already present their genuinely distinct
      // matching/image/builder workflows as cards. Keep the global sidebar
      // concise instead of duplicating those destinations in expandable menus.
      item('it','/it','⌘','IT Study'),
      item('law','/law','⚖','Law Study'),
      item('medical','/medical','✚','Medical Study'),
      item('other','/study-packs?domain_group=other','◇','Other Studies'),
      primarySection('Progress & tools'),
      item('history','/history','↶','History'),
      item('analytics','/dashboard','▥','Analytics'),
      `<div class="dashboard-nav-group">${item('learning','/learning-intelligence','◈','Learning Intelligence')}${learningOpen ? `<div class="dashboard-nav-submenu normalized-open">${sub('/learning-intelligence','↳','Topic Intelligence', path === '/learning-intelligence')}${sub('/learning-profile','↳','Learning Profile', path === '/learning-profile')}${sub('/review-schedule','↳','Review Schedule', path === '/review-schedule')}${sub('/learning-diagnostics','↳','Diagnostics', path === '/learning-diagnostics')}</div>` : ''}</div>`,
      `<div class="dashboard-nav-group">${item('anki','/anki','◆','Anki Tools')}${ankiOpen ? `<div class="dashboard-nav-submenu normalized-open">${sub('/anki/custom','↳','Custom Deck', path === '/anki/custom')}${sub('/anki/custom#printableCards','↳','Printable Cards', path === '/anki/printable')}${sub('/anki/law','↳','Law Study Anki', path === '/anki/law')}</div>` : ''}</div>`
    ].join('');

    const section = document.createElement('div');
    section.className = 'dashboard-nav-section-label';
    section.innerHTML = '<span>System</span>';

    const system = document.createElement('nav');
    system.className = 'dashboard-nav dashboard-nav-system dashboard-nav-normalized';
    system.setAttribute('aria-label', 'System navigation');
    system.innerHTML = [
      item('settings','/settings','⚙','Settings'),
      item('content','/content-packs','⬡','Content Packs'),
      item('image','/admin/image-editor','◎','Image Study Editor'),
      item('help','/help','?','Help')
    ].join('');

    const oldNavs = Array.from(sidebar.querySelectorAll(':scope > nav.dashboard-nav'));
    const oldLabels = Array.from(sidebar.querySelectorAll(':scope > .dashboard-nav-section-label'));
    const anchor = oldNavs[0] || oldLabels[0] || sidebar.querySelector('.dashboard-shutdown') || sidebar.querySelector('.dashboard-sidebar-version');
    if (!anchor) return;
    anchor.before(primary, section, system);
    oldNavs.forEach(el => el.remove());
    oldLabels.forEach(el => el.remove());
    applyStudyAreaVisibility(studyAreaVisibility);
  };

  const initialStudyAreaVisibility = readCachedStudyAreaVisibility() || defaultStudyAreaVisibility;
  mountNavigation(initialStudyAreaVisibility);

  document.querySelector('[data-settings-menu]')?.addEventListener('click', () => {
    sidebar.classList.toggle('open');
  });

  // The Learning Intelligence parent and Topic Intelligence lead to the
  // same landing page. Once already there, do not reload the page merely for
  // a repeated parent click; the section stays expanded while it is current.
  sidebar.addEventListener('click', event => {
    const learningParent = event.target.closest('.dashboard-nav-item[data-nav-key="learning"]');
    if (!learningParent || path !== '/learning-intelligence' || event.defaultPrevented) return;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
  });

  // Quick theme chooser. Settings > Appearance remains the authoritative
  // place to manage appearance; this compact control is only a convenience.
  const themeQuick = document.createElement('div');
  themeQuick.className = 'dashboard-theme-quick';
  themeQuick.innerHTML = `<label for="dlmsQuickTheme">Theme</label><select id="dlmsQuickTheme" aria-label="DLMS theme"><option value="dark">Dark</option><option value="light">Light</option><option value="purple-gold">Purple & Gold</option><option value="maroon-gold">Maroon & Gold</option></select>`;
  const themeAnchor = sidebar.querySelector('.dashboard-sidebar-version');
  if (themeAnchor) themeAnchor.before(themeQuick); else sidebar.appendChild(themeQuick);
  const navigationCustomize = document.createElement('a');
  navigationCustomize.className = 'dashboard-navigation-customize';
  navigationCustomize.href = '/settings/navigation';
  navigationCustomize.textContent = 'Customize navigation';
  themeQuick.after(navigationCustomize);
  const themeSelect = themeQuick.querySelector('select');
  fetch('/config/portal.json', {cache:'no-store'}).then(r => r.ok ? r.json() : null).then(cfg => {
    if (cfg?.theme) themeSelect.value = cfg.theme;
    const visibility = normalizeStudyAreaVisibility(cfg?.study_area_visibility);
    applyStudyAreaVisibility(visibility);
    cacheStudyAreaVisibility(visibility);
  }).catch(()=>{});
  document.querySelector('form[action="/settings/navigation/save"]')?.addEventListener('submit', event => {
    const form = event.currentTarget;
    cacheStudyAreaVisibility({
      it: form.elements.study_area_it.checked,
      law: form.elements.study_area_law.checked,
      medical: form.elements.study_area_medical.checked,
      other: form.elements.study_area_other.checked,
    });
  });
  themeSelect.addEventListener('change', async () => {
    const previous = themeSelect.dataset.previous || '';
    themeSelect.disabled = true;
    try {
      const response = await fetch('/api/theme', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:themeSelect.value})});
      if (!response.ok) throw new Error('Theme update failed');
      window.location.reload();
    } catch (error) {
      if (previous) themeSelect.value = previous;
      themeSelect.disabled = false;
      alert('DLMS could not change the theme.');
    }
  });
  themeSelect.addEventListener('focus', () => { themeSelect.dataset.previous = themeSelect.value; });

  // Help screenshots open inside DLMS instead of forcing a new browser tab.
  const helpShots = Array.from(document.querySelectorAll('.help-shot img'));
  if (helpShots.length) {
    const modal = document.createElement('div');
    modal.className = 'help-lightbox';
    modal.hidden = true;
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-label', 'Help screenshot viewer');
    modal.innerHTML = `
      <div class="help-lightbox-backdrop" data-help-lightbox-close></div>
      <div class="help-lightbox-dialog" role="document">
        <button class="help-lightbox-close" type="button" aria-label="Close image viewer" data-help-lightbox-close>×</button>
        <img class="help-lightbox-image" alt="">
        <div class="help-lightbox-caption"></div>
      </div>`;
    document.body.appendChild(modal);

    const modalImage = modal.querySelector('.help-lightbox-image');
    const modalCaption = modal.querySelector('.help-lightbox-caption');
    const closeButton = modal.querySelector('.help-lightbox-close');
    let previousFocus = null;

    const closeLightbox = () => {
      if (modal.hidden) return;
      modal.hidden = true;
      document.body.classList.remove('help-lightbox-open');
      modalImage.removeAttribute('src');
      if (previousFocus && typeof previousFocus.focus === 'function') previousFocus.focus();
      previousFocus = null;
    };

    const openLightbox = (img) => {
      const link = img.closest('a');
      const src = link?.getAttribute('href') || img.currentSrc || img.src;
      if (!src) return;
      previousFocus = document.activeElement;
      modalImage.src = src;
      modalImage.alt = img.alt || 'Help screenshot';
      modalCaption.textContent = img.closest('figure')?.querySelector('figcaption')?.textContent?.replace(/\s*[—-]\s*click the image to open it full size\.?\s*$/i, '') || img.alt || '';
      modal.hidden = false;
      document.body.classList.add('help-lightbox-open');
      closeButton.focus();
    };

    helpShots.forEach(img => {
      const link = img.closest('a');
      if (!link) return;
      link.removeAttribute('target');
      link.removeAttribute('rel');
      link.setAttribute('aria-label', `${img.alt || 'Help screenshot'} — open enlarged view`);
      link.addEventListener('click', event => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        openLightbox(img);
      });
    });

    modal.querySelectorAll('[data-help-lightbox-close]').forEach(el => el.addEventListener('click', closeLightbox));
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !modal.hidden) closeLightbox();
    });
  }
})();
