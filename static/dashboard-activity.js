(() => {
    "use strict";
    const activity = document.getElementById("recentActivity");
    if (!activity) return;
    let loadedData = null;
    let linkedHeading = null;

    // Display consolidation only: a matching current-quiz destination does not
    // establish that two records belong to the same Study session.
    function continuationFor(entry) {
        const panel = document.getElementById("continueStudyPanel");
        if (!entry.quiz_id || !entry.quiz_url || !panel || panel.hidden) return null;
        const destination = new URL(entry.quiz_url, location.href).href;
        return [...panel.querySelectorAll("[data-quiz-id]")].find(row =>
            row.dataset.quizId === String(entry.quiz_id)
            && [...row.querySelectorAll("a.daily-review-action")].some(a => a.href === destination));
    }

    function element(tag, text, className) {
        const node = document.createElement(tag);
        if (text != null) node.textContent = text;
        if (className) node.className = className;
        return node;
    }

    function link(label, href) {
        const node = element("a", label);
        node.href = href;
        return node;
    }

    function timeLabel(label, value) {
        const wrapper = element("p", `${label}: `, "dashboard-activity-detail");
        if (!value) {
            wrapper.append("Time cannot be determined");
            return wrapper;
        }
        const time = element("time", window.DLMSLocalTime.format(value));
        time.dateTime = value;
        wrapper.append(time);
        return wrapper;
    }

    function quizDetails(entry, container) {
        container.append(element("strong", entry.quiz_title));
        const context = [entry.origin, entry.folder].filter(Boolean).join(" · ");
        if (context) container.append(element("p", context, "dashboard-activity-detail"));
    }

    function actions(entry, container, review = false) {
        const row = element("div", null, "dashboard-activity-actions");
        if (review) row.append(link("Review attempt", `/review?attempt=${encodeURIComponent(entry.id)}`));
        if (entry.quiz_url && !review) {
            const open = link("Open current quiz", entry.quiz_url);
            open.title = "Open the current quiz; its content may have changed since this activity.";
            row.append(open);
        } else if (!entry.quiz_url) {
            row.append(element("span", entry.availability || "Quiz unavailable"));
        }
        container.append(row);
    }

    function score(entry, detailed = true) {
        const percent = Number(entry.percent);
        const label = detailed ? `${entry.score} / ${entry.total} (${percent}%)` : `${percent}%`;
        return element("span", label,
            `dashboard-score ${percent >= 80 ? "score-good" : percent >= 70 ? "score-warn" : "score-bad"}`);
    }

    function summary(mode, data) {
        const section = element("section", null, "dashboard-activity-summary");
        const study = mode === "study";
        section.append(element("h3", study ? "Last studied" : "Latest Exam completed"));
        if (data.entry) {
            const shared = study && continuationFor(data.entry);
            if (shared) {
                const heading = document.getElementById("continueStudyHeading").textContent;
                section.append(element("p", `Quiz shown in “${heading}” above.`, "dashboard-activity-detail"));
            } else quizDetails(data.entry, section);
            if (!study) section.append(score(data.entry));
            section.append(timeLabel(study ? "Last response saved" : "Completed", study ? data.entry.saved_at : data.entry.completed_at));
            if (shared) {
                const detail = element("details", null, "dashboard-activity-context");
                detail.append(element("summary", "Study activity details"));
                quizDetails(data.entry, detail);
                section.append(detail);
            } else actions(data.entry, section, !study);
        } else if (data.record_count) {
            section.append(element("p", study
                ? "Saved Study responses exist, but their saved times cannot be determined."
                : "Saved Exam attempts exist, but their completion times cannot be determined."));
        } else {
            section.append(element("p", study ? "No saved Study responses yet." : "No completed Exam attempts yet. Study reviews are separate in Study History."));
        }
        if (data.entry && data.undated_count) {
            section.append(element("p", `${data.undated_count} ${study ? "Study response" : "Exam attempt"} record(s) have times that cannot be determined. Latest shown uses reliably dated records.`, "dashboard-activity-detail"));
        }
        if (!study && data.undated_count) section.append(link("View undated results in Exam History", "/history"));
        return section;
    }

    function render(data) {
        linkedHeading = data.study.entry && continuationFor(data.study.entry)
            ? document.getElementById("continueStudyHeading").textContent : null;
        const summaries = element("div", null, "dashboard-activity-summaries");
        summaries.append(summary("study", data.study), summary("exam", data.exam));
        activity.replaceChildren(summaries);
        const detail = element("details", null, "dashboard-activity-explanation");
        detail.append(element("summary", "About this activity"));
        detail.append(element("p", "A saved Study response does not indicate quiz completion. A quiz shown above may be a different review of the same quiz; the saved response time here is historical activity. Latest Exam completed uses reliably dated saved attempts. Undated attempts remain in History. Open current quiz opens today’s content, which may differ from the version used for this activity."));
        activity.append(detail);
    }

    async function load(restoreFocus = false) {
        loadedData = null;
        activity.setAttribute("aria-busy", "true");
        activity.replaceChildren(element("p", "Loading recent quiz activity…", "dashboard-loading"));
        try {
            const response = await fetch("/api/dashboard/quiz-activity", {cache: "no-store"});
            if (!response.ok) throw new Error("Activity unavailable");
            const next = await response.json();
            render(next);
            loadedData = next;
        } catch (_error) {
            const retry = element("button", "Retry activity", "daily-review-remove");
            retry.type = "button";
            retry.addEventListener("click", () => { void load(true); });
            activity.replaceChildren(element("p", "Couldn’t load recent quiz activity. Your saved history has not changed."), retry);
        } finally {
            activity.setAttribute("aria-busy", "false");
            if (restoreFocus) {
                const target = activity.querySelector("button, h3");
                if (target) {
                    if (target.tagName === "H3") target.tabIndex = -1;
                    target.focus();
                }
            }
        }
    }
    const continuation = document.getElementById("continueStudyPanel");
    if (continuation) {
        new MutationObserver(() => {
            if (!loadedData) return;
            const nextHeading = loadedData.study.entry && continuationFor(loadedData.study.entry)
                ? document.getElementById("continueStudyHeading").textContent : null;
            if (nextHeading !== linkedHeading) render(loadedData);
        }).observe(
            continuation, {childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"]});
    }
    void load();
})();
