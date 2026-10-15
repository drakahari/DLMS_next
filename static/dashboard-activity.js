(() => {
    "use strict";
    const activity = document.getElementById("recentActivity");
    if (!activity) return;
    let loadedData = null;
    let linkedContinuation = false;

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

    function examSummary(data) {
        const section = element("section", null, "dashboard-activity-summary");
        section.append(element("h3", "Latest Exam completed"));
        if (data.entry) {
            quizDetails(data.entry, section);
            section.append(score(data.entry));
            section.append(timeLabel("Completed", data.entry.completed_at));
            actions(data.entry, section, true);
        } else if (data.record_count) {
            section.append(element("p", "Saved Exam attempts exist, but their completion times cannot be determined."));
        } else {
            section.append(element("p", "No completed Exam attempts yet. Study reviews are separate in Study History."));
        }
        if (data.entry && data.undated_count) {
            section.append(element("p", `${data.undated_count} Exam attempt record(s) have times that cannot be determined. Latest shown uses reliably dated records.`, "dashboard-activity-detail"));
        }
        if (data.undated_count) section.append(link("View undated results in Exam History", "/history"));
        return section;
    }

    function sequence(data) {
        const section = element("section", null, "dashboard-activity-summary dashboard-quiz-sequence");
        section.append(element("h3", "Continue your quiz sequence"));
        if (!data) {
            section.append(element("p", "Quiz sequence could not be determined."));
            section.append(link("Choose another quiz", "/library"));
            return section;
        }
        const anchor = data.anchor;
        const shared = anchor && continuationFor({quiz_id: anchor.quiz_id, quiz_url: anchor.url});
        const messages = {
            empty: "Save a Study answer in a regular quiz to start a sequence.",
            unfinished: "Finish your current regular review before moving to the next quiz.",
            incomplete_saves: "Your current review needs attention before the sequence can continue. Check its saves in Study History.",
            changed: "Your regular quiz has changed. Finish a new review of the current content before continuing.",
            unavailable: "Your last regular quiz is unavailable. Choose a quiz to start another sequence.",
            hidden: "Your regular quiz or folder is hidden in Quiz Library. Choose a quiz or change its visibility there.",
            excluded: "This folder is excluded by Learning Scope. The sequence will not select work outside your included material.",
            next_hidden: "The next regular quiz is hidden in Quiz Library. It has not been skipped.",
            next_excluded: "The next regular quiz is excluded by Learning Scope. It has not been skipped.",
            next_unavailable: "The next regular quiz is unavailable. It has not been skipped.",
            end: "You have reached the end of this folder’s regular quizzes. Choose another quiz when you are ready.",
        };
        if (data.state === "next") {
            quizDetails(data.next, section);
            section.append(element("p", data.next.review_status, "dashboard-activity-detail"));
            if (data.next.completed_at) section.append(timeLabel("Review finished", data.next.completed_at));
            const open = link("Open next quiz", data.next.quiz_url);
            open.className = "dashboard-sequence-link";
            section.append(open);
        } else {
            section.append(element("p", messages[data.state] || "Quiz sequence could not be determined."));
            if (data.folder) section.append(element("p", `Folder: ${data.folder}`, "dashboard-activity-detail"));
            if (data.next) {
                quizDetails(data.next, section);
                if (data.next.availability) section.append(element("p", data.next.availability, "dashboard-activity-detail"));
            }
            if (shared && ["unfinished", "incomplete_saves", "changed"].includes(data.state)) {
                section.append(element("p", "Use the current quiz action in Continue studying above.", "dashboard-activity-detail"));
            } else if (anchor?.url && ["unfinished", "changed"].includes(data.state)) {
                section.append(element("strong", anchor.title));
                const open = link(data.state === "unfinished" ? "Resume Study review" : "Open current quiz", anchor.url);
                open.className = "dashboard-sequence-link";
                section.append(open);
            }
            if (data.state === "incomplete_saves") section.append(link("Check Study History", "/study-history"));
            if (["excluded", "next_excluded"].includes(data.state)) section.append(link("Manage Learning Scope", "/learning-scope"));
            if (!["unfinished", "incomplete_saves", "changed"].includes(data.state)) section.append(link("Choose another quiz", "/library"));
        }
        const details = element("details", null, "dashboard-activity-context");
        details.append(element("summary", "About the quiz sequence"));
        details.append(element("p", "Uses the saved quiz order in this folder’s Quiz Library. Change the order with drag-and-drop or Up and Down. Generated focused practice is left out; reviewed quizzes are not skipped. Only a saved Finish Review for the current regular quiz content advances the sequence. Opening a quiz earns no review credit."));
        if (anchor) details.append(timeLabel("Anchor’s last response saved", anchor.saved_at));
        section.append(details);
        return section;
    }

    function render(data) {
        const anchor = data.quiz_sequence?.anchor;
        linkedContinuation = Boolean(anchor && continuationFor({quiz_id: anchor.quiz_id, quiz_url: anchor.url}));
        const summaries = element("div", null, "dashboard-activity-summaries");
        summaries.append(sequence(data.quiz_sequence), examSummary(data.exam));
        activity.replaceChildren(summaries);
        const detail = element("details", null, "dashboard-activity-explanation");
        detail.append(element("summary", "About this activity"));
        detail.append(element("p", "A saved Study response does not indicate quiz completion. Latest Exam completed uses reliably dated saved attempts. Undated attempts remain in History. Quiz links open today’s content, which may differ from a historical review. Study History keeps individual reviews and legacy saved responses."));
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
            const anchor = loadedData.quiz_sequence?.anchor;
            const shared = Boolean(anchor && continuationFor({quiz_id: anchor.quiz_id, quiz_url: anchor.url}));
            if (shared !== linkedContinuation) render(loadedData);
        }).observe(
            continuation, {childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"]});
    }
    void load();
})();
