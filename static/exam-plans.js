(() => {
  'use strict';
  document.getElementById('menuButton')?.addEventListener('click', function () {
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
      data.paused = fields.has('paused'); data.visible = fields.has('visible');
      status.textContent = 'Calculating estimate…';
      try {
        const r = await post('/api/exam-plans/preview', data);
        status.textContent = `${r.stats.total} source questions; ${r.stats.blocked} excluded and ${r.stats.unavailable} unavailable. ${r.calendar.days} study dates; ${r.capacity} estimated minutes remaining. Work: ${r.workload} minutes (${r.low}–${r.high} range); base shortfall ${r.shortfall} minutes. Today’s first-pass/fresh-evidence target: ${r.target}, within ${r.slots} daily slots. Estimates are uncertain.`;
      } catch (error) { status.textContent = error.message + ' Use Calculate / retry preview after correcting the problem.'; }
    });
  }
  const practice = document.getElementById('planPractice');
  if (practice) {
    let pending = null;
    const retry = document.getElementById('retryPlanPractice');
    async function send() {
      const status = document.getElementById('planPracticeStatus');
      status.textContent = 'Preparing focused practice…'; retry.hidden = true;
      practice.querySelectorAll('[data-practice]').forEach(button => {button.disabled = true;});
      try {
        const result = await post(`/api/exam-plans/${practice.dataset.planId}/generate`, pending);
        location.assign(result.url);
      } catch (error) {
        status.textContent = error.message + ' Retry the same request, or reload to review current choices.';
        retry.hidden = false;
      }
    }
    practice.querySelectorAll('[data-practice]').forEach(button => button.addEventListener('click', () => {
      const count = Number(button.dataset.count || document.getElementById('practiceCount').value);
      if (!Number.isInteger(count) || count < 1 || count > 50) {
        document.getElementById('planPracticeStatus').textContent = 'Choose 1–50 questions.'; return;
      }
      pending = {request_id: practice.dataset.requestId, revision: Number(practice.dataset.revision), generation: practice.dataset.generation,
                 fingerprint: practice.dataset.fingerprint, mode: button.dataset.practice, count};
      send();
    }));
    retry.addEventListener('click', send);
  }
  window.DLMSLocalTime?.render?.(document);
})();
