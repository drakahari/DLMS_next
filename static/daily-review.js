(() => {
  "use strict";

  if (!document.getElementById("dailyReviewList")) return;

  let serverPlan = null;
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
      const updated = new Date(record.updatedAt);
      const updatedText = Number.isNaN(updated.getTime())
        ? "recently"
        : window.DLMSLocalTime.format(updated.toISOString());
      return [{
        id: `unfinished-${record.quizId}`,
        kind: "unfinished",
        replaces: quiz.generated_kind || null,
        priority: quiz.generated_kind === "native_due"
          ? 10
          : quiz.generated_kind === "concept_review" ? 20 : 30,
        title: finishSaving ? `Finish saving ${quiz.title}` : `Resume ${quiz.title}`,
        reason: finishSaving
          ? `A completed Exam attempt is waiting to finish saving; last updated ${updatedText}.`
          : `Unfinished ${record.mode} session at question ${record.questionIndex + 1}; last updated ${updatedText}.`,
        scope: "This browser",
        recovery: record,
        action: {
          label: finishSaving ? "Finish Saving" : "Resume Quiz",
          url: quizUrl(quiz.html),
          method: "GET",
          fields: {},
        },
      }];
    });
  }

  function mergeBrowserSessions(plan) {
    const unfinished = unfinishedReviewItems(plan);
    const replacedKinds = new Set(
      unfinished.map(item => item.replaces).filter(Boolean),
    );
    const items = (plan.items || []).filter(
      item => !replacedKinds.has(item.kind),
    );
    items.push(...unfinished);
    items.sort((left, right) => (
      Number(left.priority || 999) - Number(right.priority || 999)
      || String(left.id).localeCompare(String(right.id))
    ));
    return {
      ...plan,
      items: items.slice(0, 5),
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

  function renderDailyReview(plan) {
    const regular = document.getElementById("regularStudyContinuity");
    if (regular) {
      const saved = plan.regular_study;
      regular.hidden = !saved;
      if (saved) {
        const state = !saved.unchanged ? "Content changed; previous coverage is historical" : saved.completed_at ? "Review finished" : "Review not finished";
        const action = saved.completed_at || !saved.unchanged ? "Open current quiz" : "Continue regular quiz";
        regular.innerHTML = `<article class="daily-review-item"><div class="daily-review-copy"><h3>Last regular quiz: ${escapeHtml(saved.title)}</h3><p>${escapeHtml(state)} · ${saved.reviewed} / ${saved.total} questions reviewed</p><p>Last response saved: ${escapeHtml(window.DLMSLocalTime.format(saved.saved_at))}</p>${!saved.completed_at && saved.unchanged ? '<p>Finish Review has not been saved.</p>' : ''}</div><div class="daily-review-item-action">${saved.url ? `<a class="${saved.completed_at ? 'daily-review-secondary' : 'daily-review-action'}" href="${escapeHtml(saved.url)}">${action}</a>` : "Quiz unavailable"}</div></article>`;
      }
    }
    const list = document.getElementById("dailyReviewList");
    const empty = document.getElementById("dailyReviewEmpty");
    const count = document.getElementById("dailyReviewCount");
    if (!list || !empty || !count) return;
    let planCard = document.getElementById("activeExamPlan");
    if (!planCard) {planCard = document.createElement("div"); planCard.id = "activeExamPlan"; (regular || list).before(planCard);}
    const exam = plan.exam_plan;
    planCard.hidden = !exam && !plan.exam_plan_error;
    if (exam) {
      const config = exam.plan.config, url = `/exam-plans/${encodeURIComponent(exam.plan.id)}`;
      const work = exam.work_state;
      const changes = Object.values(exam.changes).some(values => values.length) || exam.missing_folders.length;
      const breakdown = (exam.breakdown || []).map(item => `${item.count} ${item.label.toLowerCase()}`).join(' · ');
      const risk = exam.shortfall > 0 ? `<p class="plan-workload-warning"><strong>Estimated workload exceeds available study time by about ${exam.shortfall_rounded} minutes.</strong> Practice can be ready while the overall budget is short.${work.action_url !== url + '/edit' ? ` <a href="${url}/edit">Edit plan</a>.` : ''}</p>` : '';
      const material = `<p>${exam.stats.included_reviewed} / ${exam.stats.included} included questions reviewed · ${exam.stats.unavailable} included but unavailable.</p>${exam.stats.blocked ? `<p>${exam.stats.blocked} questions excluded by Learning Scope. <a href="/learning-scope">Review exclusions</a>.</p>` : ''}`;
      const requestId = crypto.randomUUID?.() || ('plan-' + Date.now().toString(16) + Math.random().toString(16).slice(2));
      const primary = exam.selected_count ? `<div id="planPractice" data-plan-id="${escapeHtml(exam.plan.id)}" data-revision="${exam.plan.revision}" data-generation="${escapeHtml(exam.generation)}" data-fingerprint="${escapeHtml(exam.fingerprint)}" data-request-id="${escapeHtml(requestId)}"><button class="daily-review-action" type="button" data-practice="suggested" data-count="${exam.selected_count}">Start suggested work</button><p id="planPracticeStatus" role="status"></p><button id="retryPlanPractice" type="button" hidden>Retry same request</button></div>` :
        work.action_url && work.action_url !== '/learning-scope' ? `<a class="daily-review-action" href="${escapeHtml(work.action_url)}">${escapeHtml(work.action_label)}</a>` : '';
      planCard.innerHTML = `<article class="daily-review-item"><div class="daily-review-copy"><h3>Your exam plan</h3><h4>${escapeHtml(config.name)} · Exam ${escapeHtml(config.exam_date)}</h4><p><strong>${escapeHtml(work.label)}</strong></p><p>${escapeHtml(work.reason)}</p>${risk}${material}${exam.selected_count ? `<p>${exam.selected_count} questions · about ${exam.estimated_batch} estimated minutes</p><p class="plan-breakdown">${escapeHtml(breakdown)}</p>` : ''}${!exam.selected_count && work.next_study_date ? `<p>${config.paused ? 'Next study date if resumed' : 'Next study date'}: ${escapeHtml(work.next_study_date)} · ${escapeHtml(config.calendar_timezone)}.</p>` : ''}<details><summary>Why this?</summary><p>Breakdown counts each selected question once: coverage needs first, then mistakes, due reviews and other practice. “No recorded answer” means no identifiable saved answer, not proof it was never seen. Coverage / fresh evidence includes previously answered material needing current Study coverage or post-reset evidence.</p><p>${exam.stats.total} selected questions in total; ${exam.stats.reviewed} reviewed across included and excluded material. Exclusions do not imply completion. Unavailable included questions stay in the coverage denominator and can add estimated work when restored.</p><p>${exam.stats.today} distinct questions answered today reduce the budget. First-pass/fresh-evidence target: ${exam.target}. Calendar: ${escapeHtml(config.calendar_timezone)}.${exam.estimate_available ? ` Base shortfall: ${exam.shortfall} estimated minutes.` : ' A useful workload estimate needs included, available material.'} Estimates are uncertain.</p>${exam.selected_count && work.next_study_date ? `<p>${config.paused ? 'Next study date if resumed' : 'Next study date'}: ${escapeHtml(work.next_study_date)}.</p>` : ''}${work.next_review_date ? `<p>Next scheduled review: ${escapeHtml(work.next_review_date)}.</p>` : ''}${work.next_review_date && work.next_study_date && work.next_review_date !== work.next_study_date ? '<p>The review date comes from spaced review; the study date comes from your chosen weekdays. Neither date changes the other.</p>' : ''}${work.warnings.filter(message=>!message.includes('excluded by Learning Scope')).map(message=>`<p>${escapeHtml(message)}</p>`).join('')}${changes ? '<p>Study material changed; inspect the plan.</p>' : ''}</details><div class="daily-review-item-action">${primary}<a href="${url}">View plan</a></div></div></article>`;
      window.DLMSExamPlans?.initPractice(planCard.querySelector('#planPractice'));
    } else if (plan.exam_plan_error) {planCard.textContent = plan.exam_plan_error;}
    const items = plan.items || [];
    count.textContent = exam ? `${exam.selected_count} plan questions${items.length ? ` · ${items.length} other actions` : ""}` : `${items.length} action${items.length === 1 ? "" : "s"}`;
    list.hidden = items.length === 0;
    empty.hidden = items.length !== 0 || Boolean(exam);
    if (!items.length && exam) return;
    if (!items.length) {
      const state = plan.empty_state || {};
      empty.innerHTML = `<strong>${escapeHtml(state.title || "Nothing needs immediate attention")}</strong><span>${escapeHtml(state.detail || "Keep studying to build recommendations.")}</span>${actionMarkup(state.action)}`;
      return;
    }
    list.innerHTML = items.map((item, index) => `
      <article class="daily-review-item daily-review-${escapeHtml(item.kind)}">
        <div class="daily-review-rank" aria-hidden="true">${index + 1}</div>
        <div class="daily-review-copy">
          <span>${escapeHtml(String(item.kind || "study").replaceAll("_", " "))}${item.scope ? ` · ${escapeHtml(item.scope)}` : ""}</span>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.reason)}</p>
        </div>
        <div class="daily-review-item-action">${actionMarkup(item.action)}${item.kind === "unfinished" && item.recovery ? '<button class="daily-review-remove" type="button">Remove from Today’s Review</button>' : ""}</div>
      </article>`).join("");
    list.querySelectorAll("form").forEach(form => window.dlmsProtectForm?.(form));
    list.querySelectorAll(".daily-review-item").forEach((card, index) => {
      const button = card.querySelector(".daily-review-remove");
      if (!button) return;
      button.setAttribute("aria-label", `Remove unfinished session for ${items[index].title.replace(/^Resume |^Finish saving /, "")} from Today’s Review`);
      button.addEventListener("click", () => clearUnfinishedItem(items[index]));
    });
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
      announce("This session has Study answers waiting to be saved. Resume Quiz and finish saving or retry the failed save before removing it.");
      return;
    }
    if (result.status === "pending_exam") {
      announce("This submitted Exam attempt is waiting for save confirmation. Use Finish Saving before removing it.");
      return;
    }
    if (result.status === "storage_error") {
      announce("The saved resume point could not be cleared in this browser. Nothing was removed. Check browser storage permissions and try again.");
      return;
    }
    // Remerge the original server plan, never an already merged/suppressed plan.
    if (serverPlan) renderDailyReview(mergeBrowserSessions(serverPlan));
    const refreshed = await loadDailyReview({keepCurrent: true});
    announce(result.status === "removed"
      ? `Saved resume point cleared in this browser. The quiz and saved activity are kept.${refreshed ? "" : " Recommendations could not be refreshed; refresh the page when DLMS is available."}`
      : `The unfinished session changed while confirmation was open. Nothing was cleared. Review the updated recommendations before trying again.${refreshed ? "" : " Server recommendations could not be refreshed; refresh the page when DLMS is available."}`);
    const focusTarget = document.querySelector("#dailyReviewList a, #dailyReviewList button")
      || document.getElementById("dailyReviewHeading");
    focusTarget?.focus();
  }

  async function loadDailyReview({keepCurrent = false} = {}) {
    try {
      const response = await fetch("/api/daily-review-plan", {cache: "no-store"});
      if (!response.ok) throw new Error("Daily review plan was unavailable");
      serverPlan = await response.json();
      completedStudySessions = await window.DLMSQuizRecovery?.reconcileCompletedStudy?.({activeQuizIds: (serverPlan.quiz_index || []).map(quiz => quiz.id)}) || new Set();
      renderDailyReview(mergeBrowserSessions(serverPlan));
      return true;
    } catch (error) {
      if (keepCurrent) return false;
      const list = document.getElementById("dailyReviewList");
      const empty = document.getElementById("dailyReviewEmpty");
      const count = document.getElementById("dailyReviewCount");
      if (list) list.hidden = true;
      if (count) count.textContent = "Unavailable";
      if (empty) {
        empty.hidden = false;
        empty.innerHTML = "<strong>Today’s Review could not be loaded.</strong><span>The rest of DLMS remains available below.</span>";
      }
      if (empty) {
        const retry = document.createElement("button"); retry.type = "button"; retry.textContent = "Retry Today’s Review";
        retry.addEventListener("click", () => loadDailyReview()); empty.append(retry);
      }
      console.error("Daily review plan failed:", error);
      return false;
    }
  }

  window.DLMSDailyReview = {mergeBrowserSessions, renderDailyReview, loadDailyReview};
  loadDailyReview();
})();
