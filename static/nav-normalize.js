(() => {
  const sidebar = document.querySelector('.dashboard-sidebar');
  if (!sidebar) return;

  const path = window.location.pathname || '/';
  const params = new URLSearchParams(window.location.search || '');
  const medicalBuilder = path === '/study-packs/ai-builder' && params.get('from') === 'medical';
  const itBuilder = path === '/study-packs/ai-builder' && params.get('from') === 'it';

  const isActive = (key) => {
    if (key === 'dashboard') return path === '/';
    if (key === 'library') return path === '/library' || path.startsWith('/edit_quiz') || path.startsWith('/quiz/');
    if (key === 'build') return path === '/upload' || path === '/paste' || path === '/create_short_quiz' || path === '/matching_bank_import' || path.startsWith('/pdf-import');
    if (key === 'study') return path.startsWith('/study-packs') && !medicalBuilder && !itBuilder;
    if (key === 'it') return path === '/it' || path.startsWith('/it/') || itBuilder;
    if (key === 'law') return path === '/law' || path.startsWith('/law/');
    if (key === 'medical') return path === '/medical' || path.startsWith('/medical/') || medicalBuilder;
    if (key === 'history') return path === '/history' || path.startsWith('/review');
    if (key === 'analytics') return path === '/dashboard';
    if (key === 'anki') return path === '/anki' || path.startsWith('/anki/');
    if (key === 'settings') return path === '/settings';
    if (key === 'content') return path === '/content-packs' || path.startsWith('/content-packs/');
    if (key === 'image') return path === '/admin/image-editor' || path.startsWith('/admin/image-editor/') || path.startsWith('/admin/hotspots');
    if (key === 'help') return path === '/help' || path.endsWith('help.html');
    if (key === 'maintenance') return path === '/admin/maintenance';
    return false;
  };

  const item = (key, href, icon, label) => `<a class="dashboard-nav-item${isActive(key) ? ' active' : ''}" href="${href}"${isActive(key) ? ' aria-current="page"' : ''}><span class="dashboard-nav-icon">${icon}</span><span>${label}</span></a>`;
  const sub = (href, icon, label, active=false) => `<a class="dashboard-nav-subitem${active ? ' active' : ''}" href="${href}"${active ? ' aria-current="page"' : ''}><span class="dashboard-nav-subicon">${icon}</span><span>${label}</span></a>`;

  const buildOpen = isActive('build');
  const itOpen = isActive('it');
  const medicalOpen = isActive('medical');
  const ankiOpen = isActive('anki');
  const primary = document.createElement('nav');
  primary.className = 'dashboard-nav dashboard-nav-normalized';
  primary.setAttribute('aria-label', 'Primary navigation');
  primary.innerHTML = [
    item('dashboard','/','⌂','Dashboard'),
    item('library','/library','▤','Quiz Library'),
    `<div class="dashboard-nav-group">${item('build','/upload','✎','Build Quiz')}${buildOpen ? `<div class="dashboard-nav-submenu normalized-open">${sub('/upload','↳','Quiz Builder', path === '/upload' || path === '/paste' || path === '/create_short_quiz' || path === '/matching_bank_import')}${sub('/pdf-import','↳','PDF Import & Banks', path.startsWith('/pdf-import'))}</div>` : ''}</div>`,
    item('study','/study-packs','▣','Study Packs'),
    item('it','/it','⌘','IT Study'),
    itOpen ? `<div class="dashboard-nav-submenu normalized-open">${sub('/it/matching','↳','Concepts & Matching', path === '/it/matching')}${sub('/it/images','↳','Diagrams & Images', path === '/it/images')}${sub('/study-packs/ai-builder?domain=IT%20/%20Cybersecurity&from=it','↳','AI Study Pack Builder', itBuilder)}</div>` : '',
    item('law','/law','⚖','Law Study'),
    item('medical','/medical','✚','Medical Study'),
    medicalOpen ? `<div class="dashboard-nav-submenu medical-global-submenu normalized-open">${sub('/medical/matching','↳','Terminology & Matching', path === '/medical/matching')}${sub('/medical/anatomy','↳','Anatomy & Images', path === '/medical/anatomy')}${sub('/study-packs/ai-builder?domain=Medical&from=medical','↳','AI Study Pack Builder', medicalBuilder)}</div>` : '',
    item('history','/history','↶','History'),
    item('analytics','/dashboard','▥','Analytics'),
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
})();
