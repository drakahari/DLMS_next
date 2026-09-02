(() => {
  const topics = [
    ['getting-started', 'Getting Started & Navigation'],
    ['quizzes', 'Taking Quizzes'],
    ['build-quiz', 'Building Quizzes'],
    ['smart-pdf', 'Smart PDF'],
    ['study-packs', 'Study Packs & AI Builder'],
    ['study-modules', 'Study Areas & Case Review'],
    ['content-management', 'Content Packs & Images'],
    ['history-analytics', 'History & Analytics'],
    ['learning-intelligence', 'Learning Intelligence'],
    ['anki', 'Anki & Printable Cards'],
    ['settings', 'Settings & Personalization'],
    ['maintenance', 'System Tools & Data Management'],
    ['troubleshooting', 'Troubleshooting'],
  ];

  const activeTopic = document.body?.dataset.helpTopic || '';
  document.querySelectorAll('.help-toc').forEach(toc => {
    toc.replaceChildren();
    const heading = document.createElement('strong');
    heading.textContent = 'Help topics';
    toc.appendChild(heading);

    topics.forEach(([slug, label]) => {
      const link = document.createElement('a');
      link.href = `/help/${slug}`;
      link.textContent = label;
      if (slug === activeTopic) {
        link.className = 'active';
        link.setAttribute('aria-current', 'page');
      }
      toc.appendChild(link);
    });

    const anchors = Array.from(document.querySelectorAll('article .help-anchor[id]'));
    if (!anchors.length) return;
    const localHeading = document.createElement('strong');
    localHeading.className = 'help-toc-local-heading';
    localHeading.textContent = 'On this page';
    toc.appendChild(localHeading);
    anchors.forEach(section => {
      const title = section.querySelector('h2, h3')?.textContent?.trim();
      if (!title) return;
      const link = document.createElement('a');
      link.href = `#${section.id}`;
      link.textContent = `↳ ${title}`;
      toc.appendChild(link);
    });
  });
})();
