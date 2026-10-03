(() => {
    "use strict";
    const activity = document.getElementById("recentActivity");
    if (!activity) return;

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
        const time = element("time", new Date(value).toLocaleString());
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
        if (entry.quiz_url) {
            const open = link("Open quiz", entry.quiz_url);
            open.title = "Open the current quiz; its content may have changed since this activity.";
            row.append(open);
        } else {
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
            quizDetails(data.entry, section);
            if (!study) section.append(score(data.entry));
            section.append(timeLabel(study ? "Last response saved" : "Completed", study ? data.entry.saved_at : data.entry.completed_at));
            actions(data.entry, section, !study);
        } else if (data.record_count) {
            section.append(element("p", study
                ? "Saved Study responses exist, but their saved times cannot be determined."
                : "Saved Exam attempts exist, but their completion times cannot be determined."));
        } else {
            section.append(element("p", study ? "No saved Study responses yet." : "No saved Exam completions yet."));
        }
        if (data.entry && data.undated_count) {
            section.append(element("p", `${data.undated_count} ${study ? "Study response" : "Exam attempt"} record(s) have times that cannot be determined. Latest shown uses reliably dated records.`, "dashboard-activity-detail"));
        }
        if (!study && data.undated_count) section.append(link("Find undated attempts in History", "/history"));
        return section;
    }

    function render(data) {
        const summaries = element("div", null, "dashboard-activity-summaries");
        summaries.append(summary("study", data.study), summary("exam", data.exam));
        activity.replaceChildren(summaries);
        activity.append(element("h3", "Recent saved attempts"));
        if (!data.recent_attempts.length) activity.append(element("p", "No saved quiz attempts yet."));
        for (const entry of data.recent_attempts.slice(0, 3)) {
            const row = element("div", null, "dashboard-activity-row dashboard-recent-attempt");
            const copy = element("div", null, "dashboard-activity-copy");
            copy.append(element("strong", entry.quiz_title));
            const mode = String(entry.mode || "").trim().toLowerCase();
            const label = mode === "exam" ? (entry.completed_at ? "Exam completed" : "Exam — saved attempt")
                : mode === "study" ? "Study — saved attempt" : "Saved attempt — mode unavailable";
            copy.append(element("span", label));
            copy.append(timeLabel(mode === "exam" ? "Completed" : "Recorded time", entry.completed_at));
            const rowActions = element("div", null, "dashboard-activity-actions");
            rowActions.append(link("Review attempt", `/review?attempt=${encodeURIComponent(entry.id)}`));
            copy.append(rowActions);
            const context = [entry.origin, entry.folder, entry.availability].filter(Boolean).join(" · ");
            if (context) copy.append(element("p", context, "dashboard-activity-detail dashboard-attempt-context"));
            row.append(copy, score(entry, false));
            activity.append(row);
        }
        const detail = element("details", null, "dashboard-activity-explanation");
        detail.append(element("summary", "About this activity"));
        detail.append(element("p", "A saved Study response does not indicate quiz completion. Latest Exam completed uses reliably dated saved attempts. Undated attempts remain in History. Open quiz opens the current content, which may differ from the version used for this activity."));
        activity.append(detail);
    }

    async function load(restoreFocus = false) {
        activity.setAttribute("aria-busy", "true");
        activity.replaceChildren(element("p", "Loading recent quiz activity…", "dashboard-loading"));
        try {
            const response = await fetch("/api/dashboard/quiz-activity", {cache: "no-store"});
            if (!response.ok) throw new Error("Activity unavailable");
            render(await response.json());
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
    void load();
})();
