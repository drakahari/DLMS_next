(() => {
  'use strict';
  document.querySelector('.exam-plans #menuButton')?.addEventListener('click', function () {
    const open = document.getElementById('dashboardSidebar').classList.toggle('open');
    this.setAttribute('aria-expanded', String(open));
  });
  document.querySelectorAll('[data-delete-plan]').forEach(form => form.addEventListener('submit', event => {
    if (!confirm('Delete only this plan? Quizzes, saved responses and history will be kept.')) event.preventDefault();
  }));
  const form = document.getElementById('examPlanForm');
  const token = () => window.dlmsCsrfToken || document.querySelector('[name=csrf_token]')?.value;
  async function post(url, data) {
    const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': token()}, body: JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'The request could not be saved. Reload and retry.');
    return result;
  }
  if (form) {
    const warnFolders = () => {
      const selected = [...form.querySelectorAll('[name=folders]:checked')];
      const excluded = selected.filter(n => n.dataset.excluded === 'true');
      document.getElementById('planFolderWarning').textContent = !selected.length ? 'Choose at least one folder containing study material.' :
        excluded.length === selected.length ? 'All selected folders are excluded by Learning Scope. No study material will be included. Review Learning Scope or choose an included folder.' :
        excluded.length ? `${excluded.length} selected folders are excluded by Learning Scope. Only included folders contribute study questions and workload.` :
        selected.every(n => n.dataset.missing === 'true') ? 'All selected folders are missing. Choose their replacements explicitly.' :
        'Selecting a folder does not remove its Learning Scope exclusion.';
    };
    form.querySelectorAll('[name=folders]').forEach(n => n.addEventListener('change', warnFolders));
    warnFolders();
    const zone = form.elements.calendar_timezone;
    if (!zone.value) zone.value = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    for (const name of Intl.supportedValuesOf?.('timeZone') || []) {
      const option = document.createElement('option'); option.value = name;
      document.getElementById('planTimezones').append(option);
    }
    document.getElementById('previewPlan').addEventListener('click', async () => {
      const status = document.getElementById('planPreview');
      if (!form.reportValidity()) return;
      const fields = new FormData(form), data = {};
      for (const key of ['name','exam_date','calendar_timezone']) data[key] = fields.get(key);
      for (const key of ['minutes','pace','pace_low','pace_high','reserve']) data[key] = Number(fields.get(key));
      data.weekdays = fields.getAll('weekdays').map(Number); data.folders = fields.getAll('folders');
      data.paused = fields.has('paused'); data.visible = true;
      status.textContent = 'Calculating estimate…';
      try {
        const r = await post('/api/exam-plans/preview', data);
        status.replaceChildren();
        for (const text of [r.work_state.label + '. ' + r.work_state.reason,
          `${r.stats.total} source questions; ${r.stats.blocked} excluded and ${r.stats.unavailable} unavailable.`,
          `Study time available: ${r.capacity} estimated minutes across ${r.calendar.days} study dates.`,
          r.estimate_available ? `Estimated work remaining: ${r.workload} minutes (${r.low}–${r.high} range); base shortfall ${r.shortfall} minutes. First-pass/fresh-evidence target: ${r.target}, capped by ${r.slots} daily slots. Estimates are uncertain.` :
          'A useful workload estimate is unavailable until study material is included and available.']) {
          const p = document.createElement('p'); p.textContent = text; status.append(p);
        }
        if (r.work_state.action_url === '/learning-scope') {
          const a = document.createElement('a'); a.href = '/learning-scope'; a.textContent = 'Review Learning Scope'; status.append(a);
        }
      } catch (error) { status.textContent = error.message + ' Use Calculate / retry preview after correcting the problem.'; }
    });
  }
  function initPractice(practice) {
    if (!practice || practice.dataset.bound) return;
    practice.dataset.bound = 'true';
    let pending = null;
    const retry = practice.querySelector('#retryPlanPractice');
    async function send() {
      const status = practice.querySelector('#planPracticeStatus');
      status.textContent = 'Preparing focused practice…'; retry.hidden = true;
      practice.querySelectorAll('[data-practice]').forEach(button => {button.disabled = true;});
      try {
        const result = await post(`/api/exam-plans/${encodeURIComponent(practice.dataset.planId)}/generate`, pending);
        location.assign(result.url);
      } catch (error) {
        status.textContent = error.message + ' Retry the same request, or reload to review current choices.';
        retry.hidden = false;
      }
    }
    practice.querySelectorAll('[data-practice]').forEach(button => button.addEventListener('click', () => {
      const count = Number(button.dataset.count || practice.querySelector('#practiceCount').value);
      if (!Number.isInteger(count) || count < 1 || count > 50) {
        document.getElementById('planPracticeStatus').textContent = 'Choose 1–50 questions.'; return;
      }
      pending = {request_id: practice.dataset.requestId, revision: Number(practice.dataset.revision), generation: practice.dataset.generation,
                 fingerprint: practice.dataset.fingerprint, mode: button.dataset.practice, count};
      send();
    }));
    retry.addEventListener('click', send);
  }
  window.DLMSExamPlans = {initPractice};
  initPractice(document.getElementById('planPractice'));
  window.DLMSLocalTime?.render?.(document);
})();
