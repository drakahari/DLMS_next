(() => {
  "use strict";

  if (!document.getElementById("dailyReviewList")) return;

  let serverPlan = null;
  let latestReviewRequest = 0;
  let completedStudySessions = new Set();

  const escapeHtml = value => String(value ?? "").replace(
    /[&<>"']/g,
    character => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"})[character],
  );

  const quizUrl = filename => "/quizzes/" + String(filename || "")
    .split("/")
    .map(segment => encodeURIComponent(segment))
    .join("/");

  function unfinishedReviewItems(plan) {
    const quizIndex = new Map(
      (plan.quiz_index || []).map(quiz => [String(quiz.id), quiz]),
    );
    const activeQuizIds = [...quizIndex.keys()];
    const recovery = window.DLMSQuizRecovery;
    if (!recovery?.listStoredRecords) return [];
    recovery.pruneStoredRecords({activeQuizIds});
    const listed = recovery.listStoredRecords({activeQuizIds});
    if (!listed.available) return [];
    return listed.records.filter(record => record.mode !== "Study" || !completedStudySessions.has(record.learningSessionId)).slice(0, 2).flatMap(record => {
      const quiz = quizIndex.get(String(record.quizId));
      if (!quiz) return [];
      const finishSaving = record.phase === "submitting";
      const pendingStudy = record.pendingStudyCount > 0;
      const updated = new Date(record.updatedAt);
      const updatedText = Number.isNaN(updated.getTime())
        ? "recently"
        : window.DLMSLocalTime.format(updated.toISOString());
      return [{
        id: `unfinished-${record.quizId}`,
        kind: "unfinished",
        quizTitle: quiz.title,
        needsSave: finishSaving || pendingStudy,
        priority: quiz.generated_kind === "native_due"
          ? 10
          : quiz.generated_kind === "concept_review" ? 20 : 30,
        title: finishSaving ? `Finish saving ${quiz.title}` : `Resume ${quiz.title}`,
        reason: finishSaving
          ? `A completed Exam attempt is waiting to finish saving; last updated ${updatedText}.`
          : pendingStudy ? `${record.pendingStudyCount} Study ${record.pendingStudyCount === 1 ? "response needs" : "responses need"} saving in this browser. Last updated ${updatedText}.`
          : `${record.mode} checkpoint at question ${record.questionIndex + 1} · ${updatedText}.`,
        scope: "This browser",
        recovery: record,
        action: {
          label: finishSaving ? "Finish saving Exam" : pendingStudy ? "Resolve Study saves"
            : record.mode === "Exam" ? "Resume Exam — this browser"
            : quiz.generated_kind ? "Resume focused practice" : "Resume Study review",
          url: quizUrl(quiz.html),
          method: "GET",
          fields: {},
        },
      }];
    });
  }

  function mergeBrowserSessions(plan) {
    const unfinished = unfinishedReviewItems(plan);
    // Recovery belongs to this browser. It must not suppress shared server
    // recommendations: one unfinished batch does not cover the full due queue.
    const items = [...(plan.items || []), ...unfinished];
    items.sort((left, right) => (
      Number(left.priority || 999) - Number(right.priority || 999)
      || String(left.id).localeCompare(String(right.id))
    ));
    return {
      ...plan,
      items,
      summary: {...(plan.summary || {}), unfinished_sessions: unfinished.length},
    };
  }

  function actionMarkup(action) {
    if (!action?.url || !action?.label) return "";
    if (String(action.method || "GET").toUpperCase() !== "POST") {
      return `<a class="daily-review-action" href="${escapeHtml(action.url)}">${escapeHtml(action.label)}</a>`;
    }
    const fields = Object.entries(action.fields || {}).map(([name, value]) => (
      `<input type="hidden" name="${escapeHtml(name)}" value="${escapeHtml(value)}">`
    )).join("");
    return `<form method="post" action="${escapeHtml(action.url)}">${fields}<button class="daily-review-action" type="submit">${escapeHtml(action.label)}</button></form>`;
  }

  function matchingContinuation(saved, item) {
    const record = item.recovery;
    return Boolean(saved && record && record.mode === "Study" && !saved.completed_at
      && saved.unchanged && saved.session_id && saved.fingerprint
      && String(saved.quiz_id) === String(record.quizId)
      && saved.session_id === record.learningSessionId && saved.fingerprint === record.fingerprint);
  }

  function recoveryControls(item, savedTime = "") {
    return `${actionMarkup(item.action)}<details class="dashboard-resume-management"><summary aria-label="Manage browser resume point for ${escapeHtml(item.quizTitle)}">Manage browser resume point</summary>${savedTime}<p>${escapeHtml(item.reason)} This browser.</p><button class="daily-review-remove" type="button" data-clear-recovery="${escapeHtml(item.id)}" aria-label="Clear browser resume point for ${escapeHtml(item.quizTitle)}">Clear browser resume point</button></details>`;
  }

  function renderContinuations(plan) {
    const panel = document.getElementById("continueStudyPanel"), regular = document.getElementById("regularStudyContinuity");
    const unfinished = (plan.items || []).filter(item => item.kind === "unfinished");
    const saved = plan.regular_study;
    const matched = unfinished.find(item => matchingContinuation(saved, item));
    panel.hidden = !saved && !unfinished.length;
    const continuing = unfinished.length || (saved && !saved.completed_at && saved.unchanged);
    document.getElementById("continueStudyHeading").textContent = continuing ? "Continue studying" : "Last regular quiz";
    regular.hidden = !saved;
    regular.replaceChildren();
    if (saved) {
      const integrity = saved.sequence_complete === false || saved.coverage_incomplete;
      const state = integrity ? "Saved review needs attention" : !saved.unchanged ? "Content changed; previous coverage is historical" : saved.completed_at ? "Review finished" : "Review not finished";
      const action = saved.completed_at || !saved.unchanged ? "Open current quiz" : "Resume Study review";
      const savedTime = `<p>Last response saved: ${escapeHtml(window.DLMSLocalTime.format(saved.saved_at))}</p>`;
      const controls = matched ? recoveryControls(matched, savedTime) : saved.url
        ? `<a class="daily-review-action${saved.completed_at || !saved.unchanged ? ' daily-review-secondary' : ''}" href="${escapeHtml(saved.url)}">${action}</a>` : "Quiz unavailable";
      regular.innerHTML = `<article data-quiz-id="${escapeHtml(saved.quiz_id)}" class="daily-review-item${matched ? ' daily-review-unfinished' : ''}" ${matched?.needsSave ? 'data-needs-save' : ''} ${!saved.completed_at && saved.unchanged ? 'data-unfinished-study' : ''}><div class="daily-review-copy">${continuing ? '<span>Last regular quiz</span>' : ''}<h3>${escapeHtml(saved.title)}</h3><p>${escapeHtml(state)} · ${saved.reviewed} / ${saved.total} reviewed</p>${integrity ? '<p class="dashboard-save-warning">Earlier saves or complete answers are missing. Check Study History; saved records have not been repaired.</p>' : ''}${matched?.needsSave ? `<p class="dashboard-save-warning">${escapeHtml(matched.reason)} This browser.</p>` : ''}</div><div class="daily-review-item-action">${controls}${!matched ? `<details class="dashboard-study-detail"><summary>Study details</summary>${savedTime}${saved.completed_at ? `<p>Review finished: ${escapeHtml(window.DLMSLocalTime.format(saved.completed_at))}</p>` : ''}</details>` : ''}</div></article>`;
    }
    document.getElementById("continuationList").innerHTML = unfinished.filter(item => item !== matched).map(item => `<article data-quiz-id="${escapeHtml(item.recovery.quizId)}" class="daily-review-item daily-review-unfinished" ${item.needsSave ? 'data-needs-save' : ''}><div class="daily-review-copy"><span>This browser · ${escapeHtml(item.recovery.mode)}</span><h3>${escapeHtml(item.quizTitle)}</h3>${item.needsSave ? `<p class="dashboard-save-warning">${escapeHtml(item.reason)}</p>` : ''}</div><div class="daily-review-item-action">${recoveryControls(item)}</div></article>`).join('');
    panel.querySelectorAll('[data-clear-recovery]').forEach(button => {
      button.addEventListener('click', () => clearUnfinishedItem(unfinished.find(item => item.id === button.dataset.clearRecovery)));
    });
  }

  function emphasizeNextAction() {
    const root = document.querySelector('.daily-review-panel');
    root.querySelectorAll('[data-dashboard-primary]').forEach(node => node.removeAttribute('data-dashboard-primary'));
    // This is visual priority only. Candidate order, schedules and destinations
    // remain owned by the existing services and recovery controller.
    const primary = root.querySelector('[data-needs-save] .daily-review-action')
      || root.querySelector('#planPractice [data-practice="suggested"]')
      || root.querySelector('#dailyReviewList > .daily-review-item .daily-review-action')
      || root.querySelector('#continueStudyPanel .daily-review-unfinished .daily-review-action, [data-unfinished-study] .daily-review-action')
      || root.querySelector('#activeExamPlan .daily-review-action')
      || root.querySelector('#dailyReviewEmpty .daily-review-action');
    primary?.setAttribute('data-dashboard-primary', 'true');
  }

  function renderDailyReview(plan) {
    renderContinuations(plan);
    const list = document.getElementById("dailyReviewList");
    const empty = document.getElementById("dailyReviewEmpty");
    const count = document.getElementById("dailyReviewCount");
    if (!list || !empty || !count) return;
    const planCard = document.getElementById("activeExamPlan");
    const exam = plan.exam_plan;
    document.getElementById("reviewSuggestionsExplanation").hidden = Boolean(exam);
    planCard.hidden = !exam && !plan.exam_plan_error;
    if (exam) {
      const config = exam.plan.config, url = `/exam-plans/${encodeURIComponent(exam.plan.id)}`;
      const work = exam.work_state;
      const changes = Object.values(exam.changes).some(values => values.length) || exam.missing_folders.length;
      const labels = {new: 'with no saved answer', refresh: 'answered before', mistakes: 'mistakes to revisit', due: 'due for review', other: 'extra practice'};
      const breakdown = (exam.breakdown || []).map(item => `${item.count} ${labels[item.key] || item.label.toLowerCase()}`).join(' · ');
      const minutes = Math.max(1, Math.round(exam.estimated_batch));
      const risk = exam.shortfall > 0 ? `<p class="plan-workload-warning"><strong>Estimated workload exceeds available study time by about ${exam.shortfall_rounded} minutes.</strong> Practice can be ready while the overall budget is short.${work.action_url !== url + '/edit' ? ` <a href="${url}/edit">Edit plan</a>.` : ''}</p>` : '';
      const material = `<div class="dashboard-plan-coverage"><p>${exam.stats.included_reviewed} / ${exam.stats.included} included questions reviewed.</p>${exam.stats.included > 0 ? `<progress aria-label="Included questions reviewed" value="${exam.stats.included_reviewed}" max="${exam.stats.included}"></progress>` : ''}</div>`;
      const warnings = `${exam.stats.unavailable ? `<p class="dashboard-material-warning">${exam.stats.unavailable} included but unavailable.</p>` : ''}${exam.stats.blocked ? `<p class="dashboard-material-warning">${exam.stats.blocked} questions excluded by Learning Scope. <a href="/learning-scope">Review exclusions</a>.</p>` : ''}${work.warnings.filter(message=>!message.includes('excluded by Learning Scope') && message !== `${exam.stats.unavailable} included questions are unavailable.`).map(message=>`<p class="dashboard-material-warning">${escapeHtml(message)}</p>`).join('')}${changes ? `<p class="dashboard-material-warning">Study material has changed. Use <strong>View plan</strong> to check what changed.</p>` : ''}`;
      const requestId = crypto.randomUUID?.() || ('plan-' + Date.now().toString(16) + Math.random().toString(16).slice(2));
      const primary = exam.selected_count ? `<div id="planPractice" data-plan-id="${escapeHtml(exam.plan.id)}" data-revision="${exam.plan.revision}" data-generation="${escapeHtml(exam.generation)}" data-fingerprint="${escapeHtml(exam.fingerprint)}" data-request-id="${escapeHtml(requestId)}"><button class="daily-review-action" type="button" data-practice="suggested" data-count="${exam.selected_count}">Start suggested work</button><p id="planPracticeStatus" role="status"></p><button id="retryPlanPractice" type="button" hidden>Retry same request</button></div>` :
        work.action_url && work.action_url !== url && work.action_url !== '/learning-scope' ? `<a class="daily-review-action" href="${escapeHtml(work.action_url)}">${escapeHtml(work.action_label)}</a>` : '';
      planCard.innerHTML = `<article class="daily-review-item"><div class="daily-review-copy">
        <h3 class="dashboard-plan-eyebrow">Your exam plan</h3>
        <h4>${escapeHtml(config.name)} · Exam ${escapeHtml(config.exam_date)}</h4>
        <p class="dashboard-plan-state"><strong>${escapeHtml(work.label)}</strong></p>
        ${exam.selected_count ? `<p class="dashboard-batch-size"><strong>${exam.selected_count}</strong> ${exam.selected_count === 1 ? 'question' : 'questions'} <span>· about ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}</span></p><p class="plan-breakdown">${escapeHtml(breakdown)}</p>` : `<p>${escapeHtml(work.reason)}</p>`}
        ${risk}${warnings}
        ${!exam.selected_count && work.next_study_date ? `<p>${config.paused ? 'Next study date if resumed' : 'Next study date'}: ${escapeHtml(work.next_study_date)} · ${escapeHtml(config.calendar_timezone)}.</p>` : ''}
        <div class="daily-review-item-action dashboard-plan-actions">${primary}<a href="${url}">View plan</a></div>
        ${material}
        <details class="dashboard-plan-explanation"><summary>Why this suggestion?</summary>
          ${exam.selected_count ? `<p>${escapeHtml(work.reason)}</p>` : ''}
          <p>Each question is counted once. “No saved answer” means DLMS cannot identify a saved answer for it, not that you have never seen it. “Answered before” means saved answers exist but the plan needs a current Study response or fresh learning evidence. Questions can return after content changes, incomplete current reviews or a Learning Intelligence reset; your factual history is kept. For tracked Study reviews, corrections keep the original first-answer difficulty.</p>
          <p>${exam.stats.total} selected questions in total; ${exam.stats.reviewed} reviewed across included and excluded material. Excluded questions are not counted as finished. Included but unavailable questions stay in the total and can add work when restored.</p>
          <p>${exam.stats.today} different questions answered today reduce today’s allowance. Today’s coverage target: ${exam.target}. Plan timezone: ${escapeHtml(config.calendar_timezone)}.${exam.estimate_available ? ` Estimated time shortfall: ${exam.shortfall} minutes.` : ' A useful workload estimate needs included, available material.'} Practice time is rounded for display and estimated from your plan’s pace and review allowance, not measured study time.</p>
          ${exam.selected_count && work.next_study_date ? `<p>${config.paused ? 'Next study date if resumed' : 'Next study date'}: ${escapeHtml(work.next_study_date)}.</p>` : ''}
          ${work.next_review_date ? `<p>Next scheduled review: ${escapeHtml(work.next_review_date)}.</p>` : ''}
          ${work.next_review_date && work.next_study_date && work.next_review_date !== work.next_study_date ? '<p>The review date comes from spaced review; the study date comes from your chosen Study days. Neither date changes the other.</p>' : ''}
          <p>${exam.stats.blocked ? 'Learning Scope controls included material.' : '<a href="/learning-scope">Manage Learning Scope</a> to choose included material.'} Browser resume points are separate from recommendations.</p><a href="/exam-plans">Exam Plans</a>
        </details>
      </div></article>`;
      window.DLMSExamPlans?.initPractice(planCard.querySelector('#planPractice'));
    } else if (plan.exam_plan_error) {planCard.textContent = plan.exam_plan_error;}
    const items = (plan.items || []).filter(item => item.kind !== "unfinished");
    count.textContent = "";
    list.hidden = items.length === 0 && !exam;
    empty.hidden = items.length !== 0 || Boolean(exam);
    if (!items.length && !exam) {
      const state = plan.empty_state || {};
      empty.innerHTML = `<strong>${escapeHtml(state.title || "Nothing needs immediate attention")}</strong><span>${escapeHtml(state.detail || "Keep studying to build recommendations.")}</span>${actionMarkup(state.action)}`;
    }
    const itemMarkup = item => {
      const baseline = item.kind === 'adaptive' && item.title === 'Build your learning baseline';
      const title = baseline ? 'Start with a practice set' : item.title;
      const reason = baseline ? 'DLMS needs fresh practice to guide this suggestion. Try a balanced Adaptive Study set. Saved history is kept.' : String(item.reason).replace("Adaptive Study's highest remaining signal is: ", 'Suggested because: ').replace('Not studied yet', 'Fresh practice can guide future suggestions');
      return `<article class="daily-review-item daily-review-${escapeHtml(item.kind)}"><div class="daily-review-copy"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(reason)}</p></div><div class="daily-review-item-action">${actionMarkup(item.action)}</div></article>`;
    };
    // A dashboard plan takes visual priority, not ownership of other eligible
    // recommendations. Keep canonical actions and browser-recovery filtering.
    const secondary = exam ? items : items.slice(1);
    list.innerHTML = (!exam && items.length ? itemMarkup(items[0]) : '')
      + (secondary.length ? `<details class="dashboard-other-options"><summary>More review options</summary>${exam ? '<p>Optional review across your Learning Scope, including material outside this plan.</p>' : ''}${secondary.map(itemMarkup).join('')}</details>` : '')
      + (exam && !items.length ? '<p>No additional review suggestions are available right now.</p>' : '');
    list.querySelectorAll("form").forEach(form => window.dlmsProtectForm?.(form));
    emphasizeNextAction();
  }

  function announce(message) {
    const status = document.getElementById("dailyReviewStatus");
    if (status) status.textContent = message;
  }

  function confirmClear(item) {
    const dialog = document.getElementById("dailyReviewClearDialog");
    document.getElementById("dailyReviewClearQuiz").textContent = item.title;
    dialog.returnValue = "cancel";
    return new Promise(resolve => {
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "clear"), {once: true});
      dialog.showModal();
    });
  }

  async function clearUnfinishedItem(item) {
    if (!await confirmClear(item)) return;
    const result = window.DLMSQuizRecovery.clearUnfinishedQuiz(item.recovery.quizId, item.recovery);
    if (result.status === "pending_study") {
      announce("This session has Study answers waiting to be saved. Use Resolve Study saves before clearing its browser resume point.");
      return;
    }
    if (result.status === "pending_exam") {
      announce("This submitted Exam attempt is waiting for save confirmation. Use Finish saving Exam before clearing its browser resume point.");
      return;
    }
    if (result.status === "storage_error") {
      announce("The saved resume point could not be cleared in this browser. Nothing was removed. Check browser storage permissions and try again.");
      return;
    }
    // Remerge the original server plan, never an already merged plan.
    if (serverPlan) renderDailyReview(mergeBrowserSessions(serverPlan));
    const refreshed = await loadDailyReview({keepCurrent: true});
    announce(result.status === "removed"
      ? `Browser resume point cleared for “${item.quizTitle}” (${item.recovery.mode}). Saved DLMS history is kept.${serverPlan?.regular_study && String(serverPlan.regular_study.quiz_id) === String(item.recovery.quizId) ? " Saved Study progress remains available under Continue studying." : ""}${refreshed ? "" : " Recommendations could not be refreshed; refresh the page when DLMS is available."}`
      : `The unfinished session changed while confirmation was open. Nothing was cleared. Review the updated recommendations before trying again.${refreshed ? "" : " Server recommendations could not be refreshed; refresh the page when DLMS is available."}`);
    const focusTarget = document.querySelector("#continueStudyPanel:not([hidden]) a, #continueStudyPanel:not([hidden]) button")
      || document.getElementById("dailyReviewHeading");
    focusTarget?.focus();
  }

  async function loadDailyReview({keepCurrent = false} = {}) {
    const requestId = ++latestReviewRequest;
    try {
      const response = await fetch("/api/daily-review-plan", {cache: "no-store"});
      if (!response.ok) throw new Error("Daily review plan was unavailable");
      const nextPlan = await response.json();
      if (requestId !== latestReviewRequest) return false;
      if (!nextPlan || !Array.isArray(nextPlan.items) || !Array.isArray(nextPlan.quiz_index)) {
        throw new Error("Daily review plan returned an invalid response");
      }
      const completed = await window.DLMSQuizRecovery?.reconcileCompletedStudy?.({activeQuizIds: nextPlan.quiz_index.map(quiz => quiz.id)}) || new Set();
      if (requestId !== latestReviewRequest) return false;
      serverPlan = nextPlan;
      completedStudySessions = completed;
      renderDailyReview(mergeBrowserSessions(serverPlan));
      return true;
    } catch (error) {
      if (requestId !== latestReviewRequest) return false;
      if (keepCurrent) return false;
      const list = document.getElementById("dailyReviewList");
      const empty = document.getElementById("dailyReviewEmpty");
      const count = document.getElementById("dailyReviewCount");
      if (list) list.hidden = true;
      if (count) count.textContent = "Unavailable";
      if (empty) {
        empty.hidden = false;
        empty.innerHTML = "<strong>Study next could not be loaded.</strong><span>The rest of DLMS remains available below.</span>";
      }
      if (empty) {
        const retry = document.createElement("button"); retry.type = "button"; retry.textContent = "Retry Study next";
        retry.addEventListener("click", () => loadDailyReview()); empty.append(retry);
      }
      console.error("Daily review plan failed:", error);
      return false;
    }
  }

  window.DLMSDailyReview = {mergeBrowserSessions, matchingContinuation, renderDailyReview, loadDailyReview};
  loadDailyReview();
})();
