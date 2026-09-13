(() => {
  "use strict";

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
    return listed.records.slice(0, 2).flatMap(record => {
      const quiz = quizIndex.get(String(record.quizId));
      if (!quiz) return [];
      const finishSaving = record.phase === "submitting";
      const updated = new Date(record.updatedAt);
      const updatedText = Number.isNaN(updated.getTime())
        ? "recently"
        : updated.toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
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
    const list = document.getElementById("dailyReviewList");
    const empty = document.getElementById("dailyReviewEmpty");
    const count = document.getElementById("dailyReviewCount");
    if (!list || !empty || !count) return;
    const items = plan.items || [];
    count.textContent = `${items.length} action${items.length === 1 ? "" : "s"}`;
    list.hidden = items.length === 0;
    empty.hidden = items.length !== 0;
    if (!items.length) {
      const state = plan.empty_state || {};
      empty.innerHTML = `<strong>${escapeHtml(state.title || "Nothing needs immediate attention")}</strong><span>${escapeHtml(state.detail || "Keep studying to build recommendations.")}</span>${actionMarkup(state.action)}`;
      return;
    }
    list.innerHTML = items.map((item, index) => `
      <article class="daily-review-item daily-review-${escapeHtml(item.kind)}">
        <div class="daily-review-rank" aria-hidden="true">${index + 1}</div>
        <div class="daily-review-copy">
          <span>${escapeHtml(String(item.kind || "study").replaceAll("_", " "))}</span>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.reason)}</p>
        </div>
        <div class="daily-review-item-action">${actionMarkup(item.action)}</div>
      </article>`).join("");
    list.querySelectorAll("form").forEach(form => window.dlmsProtectForm?.(form));
  }

  async function loadDailyReview() {
    try {
      const response = await fetch("/api/daily-review-plan", {cache: "no-store"});
      if (!response.ok) throw new Error("Daily review plan was unavailable");
      renderDailyReview(mergeBrowserSessions(await response.json()));
    } catch (error) {
      const list = document.getElementById("dailyReviewList");
      const empty = document.getElementById("dailyReviewEmpty");
      const count = document.getElementById("dailyReviewCount");
      if (list) list.hidden = true;
      if (count) count.textContent = "Unavailable";
      if (empty) {
        empty.hidden = false;
        empty.innerHTML = "<strong>Today’s Review could not be loaded.</strong><span>The rest of DLMS remains available below.</span>";
      }
      console.error("Daily review plan failed:", error);
    }
  }

  window.DLMSDailyReview = {mergeBrowserSessions, renderDailyReview, loadDailyReview};
  loadDailyReview();
})();
