(() => {
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
    if (key === 'settings') return path === '/settings';
    if (key === 'content') return path === '/content-packs' || path.startsWith('/content-packs/');
    if (key === 'image') return path === '/admin/image-editor' || path.startsWith('/admin/image-editor/') || path.startsWith('/admin/hotspots');
    if (key === 'help') return path === '/help' || path.startsWith('/help/') || path.startsWith('/regex-help') || path.endsWith('help.html');
    if (key === 'maintenance') return path === '/admin/maintenance';
    return false;
  };

  const item = (key, href, icon, label) => `<a class="dashboard-nav-item${isActive(key) ? ' active' : ''}" href="${href}"${isActive(key) ? ' aria-current="page"' : ''}><span class="dashboard-nav-icon">${icon}</span><span>${label}</span></a>`;
  const sub = (href, icon, label, active=false) => `<a class="dashboard-nav-subitem${active ? ' active' : ''}" href="${href}"${active ? ' aria-current="page"' : ''}><span class="dashboard-nav-subicon">${icon}</span><span>${label}</span></a>`;

  const buildOpen = isActive('build');
  const learningOpen = isActive('learning');
  const ankiOpen = isActive('anki');
  const primary = document.createElement('nav');
  primary.className = 'dashboard-nav dashboard-nav-normalized';
  primary.setAttribute('aria-label', 'Primary navigation');
  primary.innerHTML = [
    item('dashboard','/','⌂','Dashboard'),
    item('library','/library','▤','Quiz Library'),
    `<div class="dashboard-nav-group">${item('build','/upload','✎','Build Quiz')}${buildOpen ? `<div class="dashboard-nav-submenu normalized-open">${sub('/upload','↳','Quiz Builder', path === '/upload' || path === '/paste' || path === '/create_short_quiz' || path === '/matching_bank_import')}${sub('/pdf-import','↳','PDF Import & Banks', path.startsWith('/pdf-import'))}</div>` : ''}</div>`,
    item('study','/study-packs','▣','Study Packs'),
    // IT and Medical landing pages already present their genuinely distinct
    // matching/image/builder workflows as cards. Keep the global sidebar
    // concise instead of duplicating those destinations in expandable menus.
    item('it','/it','⌘','IT Study'),
    item('law','/law','⚖','Law Study'),
    item('medical','/medical','✚','Medical Study'),
    item('other','/study-packs?domain_group=other','◇','Other Studies'),
    item('history','/history','↶','History'),
    item('analytics','/dashboard','▥','Analytics'),
    `<div class="dashboard-nav-group">${item('learning','/learning-intelligence','◈','Learning Intelligence')}${learningOpen ? `<div class="dashboard-nav-submenu normalized-open">${sub('/learning-intelligence','↳','Topic Intelligence', path === '/learning-intelligence')}${sub('/learning-profile','↳','Learning Profile', path === '/learning-profile')}${sub('/review-schedule','↳','Review Schedule', path === '/review-schedule')}${sub('/learning-diagnostics','↳','Diagnostics', path === '/learning-diagnostics')}</div>` : ''}</div>`,
    `<div class="dashboard-nav-group">${item('anki','/anki','◆','Anki Tools')}${ankiOpen ? `<div class="dashboard-nav-submenu normalized-open">${sub('/anki/custom','↳','Custom Deck', path === '/anki/custom')}${sub('/anki/law','↳','Law Study Anki', path === '/anki/law')}</div>` : ''}</div>`
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
    item('help','/help','?','Help'),
    item('maintenance','/admin/maintenance','⌘','Maintenance')
  ].join('');

  const oldNavs = Array.from(sidebar.querySelectorAll(':scope > nav.dashboard-nav'));
  const oldLabels = Array.from(sidebar.querySelectorAll(':scope > .dashboard-nav-section-label'));
  const anchor = oldNavs[0] || oldLabels[0] || sidebar.querySelector('.dashboard-shutdown') || sidebar.querySelector('.dashboard-sidebar-version');
  if (!anchor) return;
  anchor.before(primary, section, system);
  oldNavs.forEach(el => el.remove());
  oldLabels.forEach(el => el.remove());

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
