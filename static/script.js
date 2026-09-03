/* =====================================================
   GLOBAL STATE
===================================================== */
let quiz = [];
let index = 0;
let examMode = false;
let userAnswers = {};
let matchingOptionOrders = {};
let matchingInteractionMode = "drag";
let matchingPendingRightIndex = null;
let studyAnkiSelections = new Set();
let paused = false;
let examTimer = null;
const DEFAULT_EXAM_MINUTES = 90;
const configuredExamMinutes = Number(window.examDurationMinutes);
const examDurationMinutes =
    Number.isFinite(configuredExamMinutes) && configuredExamMinutes > 0
        ? Math.floor(configuredExamMinutes)
        : DEFAULT_EXAM_MINUTES;
let timeRemaining = examDurationMinutes * 60;
let examStartTime = null;
let examStartedAt = null;
let learningSessionId = null;
let studyAIConfig = null;
let studyAIConfigRequest = null;
let pendingExamAttempt = null;
let examAttemptSaveInProgress = false;
let studyLearningEventSequence = 0;
const studyLearningEventSaves = new Map();

function loadStudyAIConfig() {
    if (studyAIConfigRequest) return studyAIConfigRequest;

    studyAIConfigRequest = fetch("/config/portal.json", { cache: "no-store" })
        .then(res => res.json())
        .then(config => {
            studyAIConfig = config;
            return config;
        })
        .catch(err => {
            console.error("[AI Study Mode] Failed to load config:", err);
            studyAIConfig = null;
            return null;
        })
        .finally(() => {
            studyAIConfigRequest = null;
        });

    return studyAIConfigRequest;
}

loadStudyAIConfig();

function createLearningSessionId() {
    return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : `study-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createStudyLearningEventId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    studyLearningEventSequence += 1;
    return `${learningSessionId || "study"}-${Date.now()}-${studyLearningEventSequence}-${Math.random().toString(16).slice(2)}`;
}

function ensureStudyLearningEventStatus() {
    let status = document.getElementById("studyLearningEventStatus");
    if (status) return status;

    const choices = document.getElementById("choices");
    if (!choices) return null;

    status = document.createElement("div");
    status.id = "studyLearningEventStatus";
    status.className = "study-learning-save-status";
    status.hidden = true;
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");

    const message = document.createElement("span");
    message.className = "study-learning-save-message";
    status.appendChild(message);

    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "study-learning-save-retry";
    retry.textContent = "Retry";
    retry.addEventListener("click", () => {
        void retryStudyLearningEventSaves();
    });
    status.appendChild(retry);

    choices.insertAdjacentElement("afterend", status);
    return status;
}

function updateStudyLearningEventStatus() {
    const failed = Array.from(studyLearningEventSaves.values())
        .filter(record => record.state === "failed");
    const retrying = Array.from(studyLearningEventSaves.values())
        .some(record => record.retrying === true);
    const status = document.getElementById("studyLearningEventStatus")
        || ((failed.length || retrying) ? ensureStudyLearningEventStatus() : null);
    if (!status) return;

    const message = status.querySelector(".study-learning-save-message");
    const retry = status.querySelector(".study-learning-save-retry");
    if (!failed.length && !retrying) {
        status.hidden = true;
        return;
    }

    status.hidden = false;
    status.classList.toggle("is-retrying", retrying && !failed.length);
    if (message) {
        message.textContent = retrying && !failed.length
            ? "Retrying learning progress save…"
            : "Learning progress was not saved.";
    }
    if (retry) {
        retry.hidden = failed.length === 0;
        retry.disabled = retrying;
    }
}

async function saveStudyLearningEvent(record, retrying = false) {
    const current = studyLearningEventSaves.get(record.questionKey);
    if (!current || current.eventId !== record.eventId) return false;

    record.state = "saving";
    record.retrying = retrying;
    updateStudyLearningEventStatus();
    try {
        const response = await fetch("/api/learning-events/study-response", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(record.payload)
        });
        let data = null;
        try {
            data = await response.json();
        } catch (_error) {
            data = null;
        }
        if (
            !response.ok
            || !data
            || data.ok !== true
            || String(data.event_id || "") !== record.eventId
        ) {
            throw new Error(`Learning event acknowledgement failed (HTTP ${response.status})`);
        }

        const latest = studyLearningEventSaves.get(record.questionKey);
        if (latest && latest.eventId === record.eventId) {
            studyLearningEventSaves.delete(record.questionKey);
            updateStudyLearningEventStatus();
        }
        return true;
    } catch (error) {
        const latest = studyLearningEventSaves.get(record.questionKey);
        if (latest && latest.eventId === record.eventId) {
            record.state = "failed";
            record.retrying = false;
            updateStudyLearningEventStatus();
        }
        console.warn("Learning event save failed (quiz remains usable):", error);
        return false;
    }
}

async function retryStudyLearningEventSaves() {
    const failed = Array.from(studyLearningEventSaves.values())
        .filter(record => record.state === "failed");
    if (!failed.length) return;

    failed.forEach(record => {
        record.retrying = true;
    });
    updateStudyLearningEventStatus();
    await Promise.all(failed.map(record => saveStudyLearningEvent(record, true)));
}

async function recordStudyLearningEvent(q, wasCorrect, selected) {
    if (examMode || !q || !window.QUIZ_ID) return;
    const eventId = createStudyLearningEventId();
    const payload = {
        quizId: window.QUIZ_ID,
        questionOrdinal: index + 1,
        questionType: q.type || "choice",
        eventId: eventId,
        sessionId: learningSessionId,
        wasCorrect: wasCorrect,
        selected: selected
    };
    const record = {
        eventId: eventId,
        questionKey: `${learningSessionId || "study"}:${payload.questionOrdinal}`,
        payload: payload,
        state: "saving",
        retrying: false
    };
    studyLearningEventSaves.set(record.questionKey, record);
    await saveStudyLearningEvent(record);
}



/* =====================================================
   SAFELY RELOCATE SUBMIT BUTTON (OLD QUIZZES → NEW UI)
===================================================== */
document.addEventListener("DOMContentLoaded", () => {
    // Find submit button
    const submitBtn = document.getElementById("submitBtn");
    if (!submitBtn) return;   // nothing to do

    // Find top-left bar target
    const topLeft = document.querySelector(".top-left");
    if (!topLeft) return;     // quiz HTML doesn't support it → do nothing

    // If it's already in top-left, leave it alone
    if (submitBtn.parentElement === topLeft) return;

    console.log("Relocating Submit Exam button to top-left...");
    topLeft.appendChild(submitBtn);
});





/* =====================================================
   LOAD QUIZ JSON
===================================================== */
async function loadQuiz() {
    try {
        const file = (typeof QUIZ_FILE !== "undefined") ? QUIZ_FILE : "quiz.json";
        console.log("Loading quiz:", file);
        const res = await fetch(file);
        if (!res.ok) throw new Error("HTTP " + res.status);
        quiz = await res.json();
        quiz = quiz.map(q => prepareQuestionForAttempt({ ...q, type: (q.type || "choice").toLowerCase() }));
        console.log("Quiz loaded. Questions:", quiz.length);
    } catch (err) {
        console.error("Failed to load quiz:", err);
        alert("Failed to load quiz questions.");
    }
}
loadQuiz();

/* =====================================================
   UI UPGRADE — Create Top Bar + Move Submit + Timer
   Works for OLD quizzes only.
   If new layout already exists → does nothing.
===================================================== */
document.addEventListener("DOMContentLoaded", () => {

    // If new top-bar already exists (new quizzes), do nothing
    if (document.querySelector(".top-bar")) {
        console.log("Top bar already exists — layout OK");
        return;
    }

    const quizDiv = document.getElementById("quiz");
    const progress = document.getElementById("progressBarOuter");
    const timer = document.getElementById("timer");
    const controls = document.querySelector(".controls");

    // Fail-safe: if we can't find required elements, do nothing
    if (!quizDiv || !progress || !timer || !controls) {
        console.warn("Top bar patch skipped — layout elements missing");
        return;
    }

    // Find submit button
    const submitBtn =
        document.getElementById("submitBtn") ||
        document.querySelector("button[onclick='submitQuiz()']");

    if (!submitBtn) {
        console.warn("Submit button not found — skipping patch");
        return;
    }

    console.log("Applying TOP BAR UI upgrade...");

    // Create top bar containers
    const topBar = document.createElement("div");
    topBar.className = "top-bar";

    const left = document.createElement("div");
    left.className = "top-left";

    const right = document.createElement("div");
    right.className = "top-right";

    // Move submit into left
    left.appendChild(submitBtn);

    // Move timer into right
    right.appendChild(timer);

    // Assemble bar
    topBar.appendChild(left);
    topBar.appendChild(right);

    // Insert bar RIGHT AFTER progress bar
    progress.insertAdjacentElement("afterend", topBar);
});




function prepareQuestionForAttempt(q) {
    if (q.type !== "matching" || !Array.isArray(q.pairs)) return q;
    let pairs = q.pairs.map(pair => ({
        ...pair,
        verification: (pair && typeof pair.verification === "object" && pair.verification) ? {...pair.verification} : {},
        source: (pair && typeof pair.source === "object" && pair.source) ? {...pair.source} : {}
    }));
    const requested = Number(q.round_size);
    if (Number.isFinite(requested) && requested >= 2 && requested < pairs.length) {
        const order = shuffledIndexes(pairs.length).slice(0, Math.floor(requested));
        pairs = order.map(i => pairs[i]);
    }
    let direction = q.direction || "term_to_definition";
    if (direction === "random") direction = Math.random() < 0.5 ? "term_to_definition" : "definition_to_term";
    if (direction === "definition_to_term") {
        pairs = pairs.map(pair => ({ left: pair.right, right: pair.left }));
    }
    return { ...q, pairs, active_direction: direction };
}

/* =====================================================
   RENDER QUESTION
===================================================== */
function renderQuestionMedia(q) {
    if (!q || !q.image_url) return "";
    const source = (q.image_source && typeof q.image_source === "object") ? q.image_source : {};
    const attribution = source.attribution
        ? `<div class="question-media-attribution">${escapeHtml(source.attribution)}${source.license ? ` · ${escapeHtml(source.license)}` : ""}</div>`
        : "";
    return `<div class="question-media-block">
        <div class="question-media-wrap">
            <img class="question-media-image" src="${escapeHtml(q.image_url)}" alt="${escapeHtml(q.image_alt || "Question image")}" draggable="false">
            ${renderImageStudyEdits(q.image_edits)}
        </div>
        ${attribution}
    </div>`;
}


function renderQuestion() {
    if (!quiz.length) return;

    const q = quiz[index];
    const key = `q${index}`;
    const selected = userAnswers[key] || [];

    const headerEl = document.getElementById("qHeader");
    const textEl = document.getElementById("qText");
    const choicesEl = document.getElementById("choices");

    if (headerEl) {
        headerEl.innerText = `Question ${index + 1} of ${quiz.length}`;
    }
    if (textEl) {
        textEl.innerText = q.question || "";
    }

    if (!choicesEl) return;

    // Matching v1 is intentionally kept out of AI/Anki single-choice helpers.
    // Those workflows assume A-Z choices and can be extended separately later.
    const studyAiBtn = document.getElementById("studyAiBtn");
    const studyAnkiBtn = document.getElementById("studyAnkiBtn");
    if (studyAiBtn) studyAiBtn.style.display = (!examMode && q.type === "choice") ? "inline-block" : "none";
    if (studyAnkiBtn) studyAnkiBtn.style.display = (!examMode && q.type === "choice") ? "inline-block" : "none";

    if (q.type === "hotspot") {
        renderHotspotQuestion(q, key, selected, choicesEl);
        updateProgressBar();
        updateNavButtons();
        updatePauseButtonUI();
        updateTimerLabelUI();
        updateStudyModeBadge();
        updateStudyAnkiButton();
        updateStudyAnkiExportButton();
        return;
    }

    if (q.type === "matching") {
        renderMatchingQuestion(q, key, selected, choicesEl);
        updateProgressBar();
        updateNavButtons();
        updatePauseButtonUI();
        updateTimerLabelUI();
        updateStudyModeBadge();
        updateStudyAnkiButton();
        updateStudyAnkiExportButton();
        return;
    }

    choicesEl.innerHTML = renderQuestionMedia(q);
    const isMultiChoice = Array.isArray(q.correct) && q.correct.length > 1;
    choicesEl.setAttribute("role", "group");
    choicesEl.setAttribute(
        "aria-label", isMultiChoice ? "Select all correct answers" : "Select one answer"
    );
    (q.choices || []).forEach((choice, i) => {
        let cls = "choice";


// Only visually “select” answers in EXAM MODE
if (examMode && selected.includes(i)) {
    cls += " selected";
}


        const choiceElement = document.createElement("button");
        choiceElement.type = "button";
        choiceElement.className = cls;
        choiceElement.dataset.index = String(i);
        choiceElement.setAttribute("aria-pressed", String(selected.includes(i)));
        choiceElement.setAttribute(
            "aria-label", `${String(choice.label ?? "")}. ${String(choice.text ?? "")}`
        );
        choiceElement.addEventListener("click", () => selectChoice(i));

        const labelElement = document.createElement("b");
        labelElement.textContent = `${String(choice.label ?? "")}.`;
        choiceElement.appendChild(labelElement);
        choiceElement.appendChild(document.createTextNode(` ${String(choice.text ?? "")}`));
        choicesEl.appendChild(choiceElement);
    });

    // Study mode: immediately show correct/incorrect colors
   if (!examMode && selected.length > 0) {
    applyStudyFeedback();
}


    updateProgressBar();
    updateNavButtons();
    updatePauseButtonUI();
    updateTimerLabelUI();
    updateStudyModeBadge();
    updateStudyAnkiButton();
    updateStudyAnkiExportButton();
}


function pointInHotspot(x, y, shape) {
    if (!shape || typeof shape !== "object") return false;

    if (shape.type === "circle") {
        const dx = x - Number(shape.x);
        const dy = y - Number(shape.y);
        const radius = Number(shape.radius);
        return Number.isFinite(radius) && (dx * dx + dy * dy) <= radius * radius;
    }

    if (shape.type === "polygon" && Array.isArray(shape.points) && shape.points.length >= 3) {
        let inside = false;
        const pts = shape.points;
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
            const xi = Number(pts[i][0]), yi = Number(pts[i][1]);
            const xj = Number(pts[j][0]), yj = Number(pts[j][1]);
            const intersects = ((yi > y) !== (yj > y)) &&
                (x < (xj - xi) * (y - yi) / ((yj - yi) || Number.EPSILON) + xi);
            if (intersects) inside = !inside;
        }
        return inside;
    }

    return false;
}

function hotspotCenter(shape) {
    if (!shape || typeof shape !== "object") return {x: 0.5, y: 0.5};
    if (shape.type === "circle") return {x: Number(shape.x), y: Number(shape.y)};
    if (shape.type === "polygon" && Array.isArray(shape.points) && shape.points.length) {
        const sum = shape.points.reduce((acc, p) => ({x: acc.x + Number(p[0]), y: acc.y + Number(p[1])}), {x: 0, y: 0});
        return {x: sum.x / shape.points.length, y: sum.y / shape.points.length};
    }
    return {x: 0.5, y: 0.5};
}

function renderImageStudyEdits(edits) {
    if (!Array.isArray(edits) || !edits.length) return "";
    return `<div class="quiz-image-edit-overlay">${edits.map(edit => {
        if (!edit || typeof edit !== "object") return "";
        if (edit.type === "mask") {
            const style = ["blur","white","black"].includes(edit.style) ? edit.style : "blur";
            return `<span class="quiz-image-edit mask ${style}" style="left:${Number(edit.x)*100}%;top:${Number(edit.y)*100}%;width:${Number(edit.w)*100}%;height:${Number(edit.h)*100}%"></span>`;
        }
        if (edit.type === "text") {
            const tone = edit.tone === "dark" ? "dark" : "light";
            return `<span class="quiz-image-edit text ${tone}" style="left:${Number(edit.x)*100}%;top:${Number(edit.y)*100}%;font-size:${Math.max(10,Math.min(48,Number(edit.size)||18))}px">${escapeHtml(edit.text || "")}</span>`;
        }
        return "";
    }).join("")}</div>`;
}

function renderHotspotQuestion(q, key, selected, choicesEl) {
    const answer = (selected && typeof selected === "object" && !Array.isArray(selected)) ? selected : null;
    const hasAnswer = answer && Number.isFinite(Number(answer.x)) && Number.isFinite(Number(answer.y));
    const isCorrect = hasAnswer ? pointInHotspot(Number(answer.x), Number(answer.y), q.target) : false;

    let marker = "";
    if (hasAnswer) {
        marker = `<span class="hotspot-click-marker ${(!examMode && isCorrect) ? "correct" : (!examMode ? "wrong" : "")}"
            style="left:${Number(answer.x) * 100}%;top:${Number(answer.y) * 100}%"></span>`;
    }

    let feedback = "";
    if (!examMode && hasAnswer) {
        let details = `<div>Try another location on the image.</div>`;
        if (isCorrect) {
            const verification = q.verification || {};
            const verified = verification.status === "source-checked"
                ? `<span class="matching-study-chip verified">✓ Source checked</span>` : "";
            const explanation = q.explanation
                ? `<div class="matching-study-explanation">${escapeHtml(q.explanation)}</div>` : "";
            const referenceBasis = verification.reference_basis
                ? `<div class="matching-study-source">Reference basis: ${escapeHtml(verification.reference_basis)}</div>` : "";
            details = `<div class="matching-study-correct-answer"><strong>Structure:</strong> ${escapeHtml(q.target_label || "")}</div>
                <div class="matching-study-meta">${verified}</div>
                ${explanation}
                ${referenceBasis}`;
        }

        feedback = `<div class="matching-study-feedback ${isCorrect ? "is-correct" : "is-wrong"}">
            <div class="matching-study-feedback-title">${isCorrect ? "✓ Correct" : "✕ Not quite"}</div>
            ${details}
        </div>`;
    }

    const source = q.image_source || {};
    const attribution = source.attribution
        ? `<div class="hotspot-attribution">${escapeHtml(source.attribution)}${source.license ? ` · ${escapeHtml(source.license)}` : ""}</div>`
        : "";

    choicesEl.innerHTML = `
        <div class="hotspot-question">
            <div class="matching-instructions">Click the requested structure on the image.</div>
            <div class="hotspot-image-wrap" onclick="selectHotspot(event)">
                <img class="hotspot-image" src="${escapeHtml(q.image_url || "")}" alt="${escapeHtml(q.image_alt || "Anatomy image")}" draggable="false">
                ${renderImageStudyEdits(q.image_edits)}
                ${marker}
            </div>
            ${attribution}
            ${feedback}
        </div>`;
}

function selectHotspot(event) {
    if (!quiz.length) return;
    const q = quiz[index];
    if (!q || q.type !== "hotspot") return;

    const wrap = event.currentTarget;
    const img = wrap.querySelector(".hotspot-image");
    if (!img) return;

    const rect = img.getBoundingClientRect();
    if (!rect.width || !rect.height) return;

    const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));

    userAnswers[`q${index}`] = {x, y};
    if (!examMode) {
        void recordStudyLearningEvent(q, pointInHotspot(x, y, q.target), {x, y});
    }
    renderQuestion();
}

function shuffledIndexes(length) {
    const arr = Array.from({length}, (_, i) => i);
    for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
}

function matchingFeedbackHtml(q, pair, leftIndex, chosen) {
    if (examMode || chosen === "") return "";
    const isCorrect = Number(chosen) === leftIndex;
    let details = `<div>Try a different match.</div>`;
    if (isCorrect) {
        const category = pair.category ? `<span class="matching-study-chip">${escapeHtml(pair.category)}</span>` : "";
        const verification = (pair.verification && typeof pair.verification === "object") ? pair.verification : {};
        const source = (pair.source && typeof pair.source === "object")
            ? pair.source
            : ((q.source && typeof q.source === "object") ? q.source : {});
        const verificationStatus = String(verification.status || "").toLowerCase();
        const isSourceChecked = ["source-checked", "source-aligned", "source-basis-verified", "verified"].includes(verificationStatus);
        const verified = isSourceChecked ? `<span class="matching-study-chip verified">✓ Source checked</span>` : "";
        const explanation = pair.explanation ? `<div class="matching-study-explanation">${escapeHtml(pair.explanation)}</div>` : "";
        const referenceText = verification.reference_basis || safeProvenanceLabel(source);
        const sourceUrls = Array.isArray(verification.source_urls) ? verification.source_urls.filter(Boolean) : [];
        const sourceUrl = safeExternalUrl(sourceUrls[0] || source.url || "");
        const referenceBasis = referenceText ? `<div class="matching-study-source"><strong>Reference basis:</strong> ${escapeHtml(referenceText)}</div>` : "";
        const sourceLink = sourceUrl ? `<div class="matching-study-source"><strong>Source:</strong> <a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(sourceUrl)}</a></div>` : "";
        details = `<div class="matching-study-meta">${category}${verified}</div>${explanation}${referenceBasis}${sourceLink}`;
    }
    return `<div class="matching-study-feedback ${isCorrect ? "is-correct" : "is-wrong"}">
        <div class="matching-study-feedback-title">${isCorrect ? "✓ Correct" : "✕ Not quite"}</div>
        ${details}
    </div>`;
}

function getMatchingAnswers(key) {
    const selected = userAnswers[key];
    return (selected && typeof selected === "object" && !Array.isArray(selected)) ? selected : {};
}

function renderMatchingQuestion(q, key, selected, choicesEl) {
    const pairs = Array.isArray(q.pairs) ? q.pairs : [];
    if (!matchingOptionOrders[key] || matchingOptionOrders[key].length !== pairs.length) {
        matchingOptionOrders[key] = shuffledIndexes(pairs.length);
    }
    const answers = (selected && typeof selected === "object" && !Array.isArray(selected)) ? selected : {};
    const order = matchingOptionOrders[key];
    const modeControls = `<div class="matching-mode-controls" role="group" aria-label="Matching interaction">
        <button type="button" class="matching-mode-button ${matchingInteractionMode === "drag" ? "active" : ""}" onclick="setMatchingInteractionMode('drag')">Drag &amp; Drop</button>
        <button type="button" class="matching-mode-button ${matchingInteractionMode === "select" ? "active" : ""}" onclick="setMatchingInteractionMode('select')">Dropdowns</button>
    </div>`;

    if (matchingInteractionMode === "select") {
        const options = order.map(idx => `<option value="${idx}">${escapeHtml(pairs[idx].right)}</option>`).join("");
        choicesEl.innerHTML = renderQuestionMedia(q) + `<div class="matching-question">${modeControls}<div class="matching-instructions">Choose the matching answer for each item. You can switch back to Drag &amp; Drop at any time.</div>${pairs.map((pair, leftIndex) => {
            const chosen = answers[leftIndex] === undefined ? "" : String(answers[leftIndex]);
            let cls = "matching-row";
            if (!examMode && chosen !== "") cls += Number(chosen) === leftIndex ? " matching-correct" : " matching-wrong";
            return `<div class="${cls}"><div class="matching-left"><span class="matching-left-number">${leftIndex + 1}</span>${escapeHtml(pair.left)}</div><select class="matching-select" onchange="selectMatch(${leftIndex}, this.value)"><option value="">Select a match…</option>${options}</select>${matchingFeedbackHtml(q, pair, leftIndex, chosen)}</div>`;
        }).join("")}</div>`;
        choicesEl.querySelectorAll(".matching-select").forEach((select, idx) => {
            if (answers[idx] !== undefined) select.value = String(answers[idx]);
        });
        return;
    }

    const assigned = new Set(Object.values(answers).map(Number).filter(Number.isFinite));
    const pool = order.filter(idx => !assigned.has(idx));
    const poolHtml = pool.map(idx => `<button type="button" class="matching-answer-chip${matchingPendingRightIndex === idx ? " selected" : ""}" draggable="true" data-match-answer="${idx}" aria-pressed="${matchingPendingRightIndex === idx ? "true" : "false"}">${escapeHtml(pairs[idx].right)}</button>`).join("");
    const rowsHtml = pairs.map((pair, leftIndex) => {
        const chosen = answers[leftIndex] === undefined ? "" : String(answers[leftIndex]);
        const chosenIndex = chosen === "" ? null : Number(chosen);
        let cls = "matching-drag-row";
        if (!examMode && chosen !== "") cls += chosenIndex === leftIndex ? " matching-correct" : " matching-wrong";
        const targetText = chosenIndex !== null && pairs[chosenIndex] ? escapeHtml(pairs[chosenIndex].right) : "Drop or tap an answer here";
        return `<div class="${cls}">
            <div class="matching-left"><span class="matching-left-number">${leftIndex + 1}</span>${escapeHtml(pair.left)}</div>
            <button type="button" class="matching-drop-target${chosen !== "" ? " filled" : ""}" data-match-target="${leftIndex}" aria-label="Match for ${escapeHtml(pair.left)}">${targetText}</button>
            ${chosen !== "" ? `<button type="button" class="matching-clear-match" onclick="clearMatch(${leftIndex})" aria-label="Clear match for ${escapeHtml(pair.left)}">×</button>` : '<span class="matching-clear-spacer"></span>'}
            ${matchingFeedbackHtml(q, pair, leftIndex, chosen)}
        </div>`;
    }).join("");

    choicesEl.innerHTML = renderQuestionMedia(q) + `<div class="matching-question">${modeControls}
        <div class="matching-instructions"><strong>Drag &amp; Drop:</strong> drag an answer into a target. On touch or keyboard, tap/select an answer first, then tap/select its target.</div>
        <div class="matching-answer-pool" aria-label="Answer pool"><div class="matching-answer-pool-title">Answer pool</div><div class="matching-answer-pool-items">${poolHtml || '<span class="matching-pool-empty">All answers are placed.</span>'}</div></div>
        <div class="matching-drag-list">${rowsHtml}</div>
    </div>`;
    bindMatchingDragInteractions();
}

function setMatchingInteractionMode(mode) {
    matchingInteractionMode = mode === "select" ? "select" : "drag";
    matchingPendingRightIndex = null;
    renderQuestion();
}

function commitMatchingAnswer(leftIndex, rightIndex) {
    if (!quiz.length) return;
    const q = quiz[index];
    const key = `q${index}`;
    let answers = getMatchingAnswers(key);
    answers = {...answers};
    Object.keys(answers).forEach(existingLeft => {
        if (Number(answers[existingLeft]) === Number(rightIndex) && Number(existingLeft) !== Number(leftIndex)) delete answers[existingLeft];
    });
    answers[leftIndex] = Number(rightIndex);
    userAnswers[key] = answers;
    matchingPendingRightIndex = null;
    if (!examMode) {
        const pairs = Array.isArray(q.pairs) ? q.pairs : [];
        const complete = pairs.length >= 2 && pairs.every((_, pairIndex) => answers[pairIndex] !== undefined);
        const correct = complete ? pairs.every((_, pairIndex) => Number(answers[pairIndex]) === pairIndex) : null;
        void recordStudyLearningEvent(q, correct, answers);
    }
    renderQuestion();
}

function clearMatch(leftIndex) {
    const key = `q${index}`;
    const answers = {...getMatchingAnswers(key)};
    delete answers[leftIndex];
    userAnswers[key] = answers;
    matchingPendingRightIndex = null;
    renderQuestion();
}

function bindMatchingDragInteractions() {
    document.querySelectorAll("[data-match-answer]").forEach(chip => {
        const rightIndex = Number(chip.dataset.matchAnswer);
        chip.addEventListener("dragstart", event => {
            event.dataTransfer.setData("text/plain", String(rightIndex));
            event.dataTransfer.effectAllowed = "move";
            chip.classList.add("dragging");
        });
        chip.addEventListener("dragend", () => chip.classList.remove("dragging"));
        chip.addEventListener("click", () => {
            matchingPendingRightIndex = matchingPendingRightIndex === rightIndex ? null : rightIndex;
            renderQuestion();
        });
    });
    document.querySelectorAll("[data-match-target]").forEach(target => {
        const leftIndex = Number(target.dataset.matchTarget);
        target.addEventListener("dragover", event => {
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            target.classList.add("drag-over");
        });
        target.addEventListener("dragleave", () => target.classList.remove("drag-over"));
        target.addEventListener("drop", event => {
            event.preventDefault();
            target.classList.remove("drag-over");
            const rightIndex = Number(event.dataTransfer.getData("text/plain"));
            if (Number.isInteger(rightIndex)) commitMatchingAnswer(leftIndex, rightIndex);
        });
        target.addEventListener("click", () => {
            if (Number.isInteger(matchingPendingRightIndex)) commitMatchingAnswer(leftIndex, matchingPendingRightIndex);
        });
    });
}

function selectMatch(leftIndex, rightIndexValue) {
    if (!quiz.length) return;
    if (rightIndexValue === "") {
        clearMatch(leftIndex);
        return;
    }
    commitMatchingAnswer(leftIndex, Number(rightIndexValue));
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[ch]));
}

function safeExternalUrl(value) {
    const raw = String(value ?? "").trim();
    if (!raw) return "";
    try {
        const url = new URL(raw);
        if (!["http:", "https:"].includes(url.protocol)) return "";
        const hostname = url.hostname.toLowerCase().replace(/\.$/, "");
        const isLoopback = hostname === "localhost"
            || hostname.endsWith(".localhost")
            || hostname === "0.0.0.0"
            || hostname === "::1"
            || hostname === "[::1]"
            || /^127(?:\.\d{1,3}){3}$/.test(hostname);
        if (isLoopback || url.origin === window.location.origin) return "";
        return url.href;
    } catch (_error) {
        return "";
    }
}

function safeProvenanceLabel(source, fallback = "") {
    const values = [source?.dataset, source?.work, source?.organization];
    for (const value of values) {
        const label = String(value ?? "").trim();
        if (!label) continue;
        if (/^https?:/i.test(label) && !safeExternalUrl(label)) continue;
        if (/(?:^|[\\/])[^\\/]+\.(?:html?|json)(?:[?#].*)?$/i.test(label)) continue;
        return label;
    }
    return fallback;
}

function choiceStudyState(q, selected) {
    const correctIndexes = (q.correct || [])
        .map(letter => String(letter).toUpperCase().charCodeAt(0) - 65)
        .sort((a, b) => a - b);
    const isMulti = correctIndexes.length > 1;
    const evaluable = !isMulti || selected.length === correctIndexes.length;
    const isCorrect = evaluable
        ? selected.length === correctIndexes.length && selected.every((value, idx) => value === correctIndexes[idx])
        : null;
    return {
        correctIndexes,
        isCorrect,
        hasIncorrectSelection: selected.some(value => !correctIndexes.includes(value)),
    };
}

/* =====================================================
   SELECT CHOICE
===================================================== */
function selectChoice(i) {
    if (!quiz.length) return;

    const q = quiz[index];
    const key = `q${index}`;

    const isMulti = Array.isArray(q.correct) && q.correct.length > 1;
    let arr = userAnswers[key] || [];

    // --- STUDY MODE ---
    if (!examMode) {

        if (!isMulti) {
            // single-answer question → normal behavior
            arr = [i];
        } else {
            // MULTI-ANSWER STUDY MODE → toggle selections
            if (arr.includes(i)) {
                arr = arr.filter(v => v !== i);
            } else {
                arr.push(i);
                arr.sort();
            }
        }

        userAnswers[key] = arr;
        const state = choiceStudyState(q, arr);
        void recordStudyLearningEvent(q, state.isCorrect, arr.map(idx => String.fromCharCode(65 + idx)));
        renderQuestion();
        return;
    }

    // --- EXAM MODE ---
    if (!isMulti) {
        arr = [i];
    } else {
        if (arr.includes(i)) {
            arr = arr.filter(v => v !== i);
        } else {
            arr.push(i);
            arr.sort();
        }
    }

    userAnswers[key] = arr;
    renderQuestion();
}



/* =====================================================
   NAVIGATION
===================================================== */
function next() {
    if (!quiz.length) return;
    if (index < quiz.length - 1) {
        index++;
        renderQuestion();
    }
}

function prev() {
    if (!quiz.length) return;
    if (index > 0) {
        index--;
        renderQuestion();
    }
}

/* =====================================================
   NAV BUTTON VISIBILITY (HIDE NEXT ON LAST QUESTION)
===================================================== */
function updateNavButtons() {
    // Try common ways to find the buttons (works across old/new quiz HTML)
    const buttons = Array.from(document.querySelectorAll("button"));

    const nextBtn =
        document.getElementById("nextBtn") ||
        buttons.find(b => (b.getAttribute("onclick") || "").includes("next(")) ||
        buttons.find(b => (b.textContent || "").trim().toLowerCase() === "next") ||
        buttons.find(b => (b.textContent || "").toLowerCase().includes("next"));

    const prevBtn =
        document.getElementById("prevBtn") ||
        buttons.find(b => (b.getAttribute("onclick") || "").includes("prev(")) ||
        buttons.find(b => (b.textContent || "").trim().toLowerCase() === "prev") ||
        buttons.find(b => (b.textContent || "").toLowerCase().includes("prev"));

    // If we can't find the buttons on this quiz HTML, do nothing safely
    if (!quiz.length) return;

    // Prev disabled on first question (nice UX; safe)
    if (prevBtn) prevBtn.disabled = (index === 0);

    // Hide Next on last question; show otherwise
    if (nextBtn) {
        const isLast = (index === quiz.length - 1);
        nextBtn.style.display = isLast ? "none" : "inline-block";
    }
}

/* =====================================================
   STUDY MODE UI VISIBILITY
===================================================== */
function updateStudyModeUI() {
    const timer = document.getElementById("timer");
    const pauseBtn =
        document.getElementById("pauseBtn") ||
        document.querySelector("button[onclick='pauseQuiz()']");

    if (!examMode) {
        // Study mode → hide timer + pause
        if (timer) timer.style.display = "none";
        if (pauseBtn) pauseBtn.style.display = "none";
    } else {
        // Exam mode → restore
        if (timer) timer.style.display = "";
        if (pauseBtn) pauseBtn.style.display = "";
    }
}


/* =====================================================
   PAUSE BUTTON VISIBILITY
===================================================== */
function updatePauseButtonUI() {
    const pauseBtn =
        document.getElementById("pauseBtn") ||
        document.querySelector("button[onclick='pauseQuiz()']");

    if (!pauseBtn) return;

    // Study mode → hide pause
    pauseBtn.style.display = examMode ? "inline-block" : "none";
}


/* =====================================================
   TIMER LABEL VISIBILITY
===================================================== */
function updateTimerLabelUI() {
    const timerLabel = document.querySelector(
        "#timer, .timer, .time-remaining, #timeRemaining"
    );

    if (!timerLabel) return;

    timerLabel.style.display = examMode ? "" : "none";
}


/* =====================================================
   STUDY MODE BADGE
===================================================== */
function updateStudyModeBadge() {
    let badge = document.getElementById("studyModeBadge");

    if (!examMode) {
        if (!badge) {
            badge = document.createElement("div");
            badge.id = "studyModeBadge";
            badge.innerHTML = `
                <div style="font-size:16px;font-weight:600;letter-spacing:.3px">
                    📘 Study Mode
                </div>
                <div style="font-size:12px;opacity:.9;margin-top:2px">
                    Learn at your own pace
                </div>
            `;

            badge.style.padding = "10px 14px";
            badge.style.borderRadius = "8px";
            badge.style.background = "rgba(255,255,255,0.15)";
            badge.style.border = "1px solid rgba(255,255,255,0.25)";
            badge.style.textAlign = "center";
            badge.style.boxShadow = "0 0 10px rgba(0,0,0,.35)";


            const timer = document.getElementById("timer");
            if (timer && timer.parentNode) {
                timer.parentNode.insertBefore(badge, timer.nextSibling);
            }
        }
        badge.style.display = "block";
    } else {
        if (badge) badge.style.display = "none";
    }
}



/* =====================================================
   STUDY-MODE FEEDBACK
===================================================== */
function applyStudyFeedback() {
    if (!quiz.length) return;

    const q = quiz[index];
    if (!q.correct || !Array.isArray(q.correct)) return;

    const key = `q${index}`;
    const selected = userAnswers[key] || [];

    const state = choiceStudyState(q, selected);
    const correctIndexes = state.correctIndexes;

    const buttons = document.querySelectorAll("#choices .choice");

    // Clear previous feedback
    buttons.forEach(btn => {
        btn.classList.remove("correct-choice", "wrong-choice");
        btn.setAttribute("aria-pressed", String(selected.includes(Number(btn.dataset.index))));
    });

    // Mark ONLY what the user picked
    selected.forEach(idx => {
        if (!buttons[idx]) return;

        if (correctIndexes.includes(idx)) {
            buttons[idx].classList.add("correct-choice");   // green
            buttons[idx].setAttribute("aria-label", `${buttons[idx].getAttribute("aria-label")}. Correct.`);
        } else {
            buttons[idx].classList.add("wrong-choice");     // red
            buttons[idx].setAttribute("aria-label", `${buttons[idx].getAttribute("aria-label")}. Incorrect.`);
        }
    });

    const choicesEl = document.getElementById("choices");
    if (choicesEl) {
        choicesEl.querySelector(".choice-study-explanation")?.remove();
        if (selected.length) {
            if (state.isCorrect) {
                const source = (q.source && typeof q.source === "object") ? q.source : {};
                const explanation = q.explanation
                    ? `<div class="matching-study-explanation">${escapeHtml(q.explanation)}</div>` : "";
                const sourceUrl = safeExternalUrl(source.url);
                const sourceLine = sourceUrl
                    ? `<div class="matching-study-source"><strong>Source:</strong> <a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(safeProvenanceLabel(source, sourceUrl))}</a></div>` : "";
                choicesEl.insertAdjacentHTML("beforeend", `<div class="matching-study-feedback is-correct choice-study-explanation"><div class="matching-study-feedback-title">✓ Correct</div>${explanation}${sourceLine}</div>`);
            } else {
                const message = state.hasIncorrectSelection
                    ? "✕ Not quite — try another answer."
                    : "Keep going — select all correct answers.";
                choicesEl.insertAdjacentHTML("beforeend", `<div class="matching-study-feedback is-wrong choice-study-explanation"><div class="matching-study-feedback-title">${message}</div></div>`);
            }
        }
    }
}




function toggleCurrentQuestionForAnki() {
    if (examMode) return;

    if (studyAnkiSelections.has(index)) {
        studyAnkiSelections.delete(index);
    } else {
        studyAnkiSelections.add(index);
    }

    updateStudyAnkiButton();
    updateStudyAnkiExportButton();
}

function updateStudyAnkiButton() {
    const btn = document.getElementById("studyAnkiBtn");
    if (!btn) return;

    if (examMode) {
        btn.style.display = "none";
        return;
    }

    btn.style.display = "inline-block";

    if (studyAnkiSelections.has(index)) {
        btn.textContent = "✓ Marked for Anki";
    } else {
        btn.textContent = "⭐ Mark for Anki";
    }
}

function updateStudyAnkiExportButton() {
    const btn = document.getElementById("studyAnkiExportBtn");
    if (!btn) return;

    const isLastQuestion = (index === quiz.length - 1);
    const selectedCount = studyAnkiSelections.size;

    if (!examMode && isLastQuestion && selectedCount > 0) {
        btn.style.display = "inline-block";
        btn.textContent = `📦 Export ${selectedCount} Selected to Anki`;
    } else {
        btn.style.display = "none";
    }
}

async function exportStudyAnkiSelections() {
    if (examMode) return;

    const selectedIndexes = Array.from(studyAnkiSelections).sort((a, b) => a - b);

    if (selectedIndexes.length === 0) {
        alert("No questions are marked for Anki.");
        return;
    }

    const questionNumbers = selectedIndexes.map(i => i + 1);

    try {
        const response = await fetch("/export/anki/study", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                quiz_id: window.QUIZ_ID,
                question_numbers: questionNumbers
            })
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(errorText || "Anki export failed");
        }

        const blob = await response.blob();

        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");

        link.href = url;
        link.download = `study_selected_${window.QUIZ_ID}.apkg`;

        document.body.appendChild(link);
        link.click();
        link.remove();

        URL.revokeObjectURL(url);

    } catch (err) {
        console.error("Study Anki export failed:", err);
        alert("Unable to export the selected questions to Anki.");
    }
}


/* =====================================================
   PROGRESS BAR
===================================================== */
function updateProgressBar() {
    const bar = document.getElementById("progressBarInner");
    if (!bar || !quiz.length) return;

    const pct = ((index + 1) / quiz.length) * 100;
    bar.style.width = pct + "%";
}

/* =====================================================
   START QUIZ (Study or Exam)
===================================================== */
function startQuiz(isExam) {
    examMode = isExam;
    index = 0;
    userAnswers = {};
    matchingOptionOrders = {};
    matchingPendingRightIndex = null;
    studyAnkiSelections.clear();
    learningSessionId = createLearningSessionId();
    studyLearningEventSequence = 0;
    studyLearningEventSaves.clear();
    updateStudyLearningEventStatus();

    if (examMode) {
        examStartTime = new Date().toISOString();
    } else {
        examStartTime = null;
    }

    const studyAiBtn = document.getElementById("studyAiBtn");
    if (studyAiBtn) {
        studyAiBtn.style.display = examMode ? "none" : "inline-block";
    }

    const studyAnkiBtn = document.getElementById("studyAnkiBtn");
    if (studyAnkiBtn) {
        studyAnkiBtn.style.display = examMode ? "none" : "inline-block";
    }



    console.log("START QUIZ. examMode =", examMode);

    // Show Submit ONLY in Exam Mode
    const submitBtn = document.querySelector("button[onclick='submitQuiz()']");
    if (submitBtn) submitBtn.style.display = examMode ? "inline-block" : "none";

    const modeSelect = document.getElementById("modeSelect");
    const quizDiv = document.getElementById("quiz");
    const resultDiv = document.getElementById("result");
    const timerDiv = document.getElementById("timer");

    if (modeSelect) modeSelect.classList.add("hidden");
    if (quizDiv) quizDiv.classList.remove("hidden");
    if (resultDiv) {
        resultDiv.classList.add("hidden");
        resultDiv.style.display = "none";
    }

    updatePauseButtonUI(); // 👈 ADD THIS LINE EXACTLY HERE
    updateTimerLabelUI();
    updateStudyModeBadge();

    // Reset pause overlay / blur
    const overlay = document.getElementById("pauseOverlay");
    if (overlay) overlay.classList.remove("show");
    document.body.classList.remove("blurred");
    paused = false;

    // In Study mode: no timer
    if (!examMode) {
        if (timerDiv) timerDiv.classList.add("hidden");
        stopExamTimer();
    } else {
        // Exam mode: show timer + start the quiz-specific countdown.
        // Older quizzes without a configured duration safely default to 90 minutes.
        if (timerDiv) timerDiv.classList.remove("hidden");
        timeRemaining = examDurationMinutes * 60;
        startExamTimer();
    }
    // NEW: record start time
    examStartTime = new Date().toISOString();


    renderQuestion();
}


/* =====================================================
   EXAM TIMER + PAUSE / RESUME
===================================================== */
function startExamTimer() {
    console.log("TIMER START");
    const display = document.getElementById("timeDisplay");

    if (examTimer) {
        clearInterval(examTimer);
        examTimer = null;
    }

    examTimer = setInterval(() => {
        if (paused) return;

        timeRemaining--;

        const m = Math.floor(timeRemaining / 60);
        const s = timeRemaining % 60;

        if (display) {
            display.innerText = `${m}:${s.toString().padStart(2, "0")}`;
        }

        if (timeRemaining <= 0) {
            clearInterval(examTimer);
            examTimer = null;
            submitQuiz(true);

        }
    }, 1000);
}

function pauseExam() {
    if (!examMode) return;
    console.log("PAUSE CLICKED");

    paused = true;

    const overlay = document.getElementById("pauseOverlay");
    if (overlay) {
        overlay.classList.add("show");
        console.log("Overlay class after pause:", overlay.className);
    }

    document.body.classList.add("blurred");
}

function resumeExam() {
    if (!examMode) return;
    console.log("RESUME CLICKED");

    paused = false;

    const overlay = document.getElementById("pauseOverlay");
    if (overlay) {
        overlay.classList.remove("show");
    }

    document.body.classList.remove("blurred");
}

function stopExamTimer() {
    if (examTimer) {
        clearInterval(examTimer);
        examTimer = null;
    }
}

function renderExamResult(pending, state) {
    const quizDiv = document.getElementById("quiz");
    const resultDiv = document.getElementById("result");
    if (quizDiv) quizDiv.classList.add("hidden");
    if (!resultDiv) return;

    const saved = state === "saved";
    const saving = state === "saving";
    const reviewAttempt = encodeURIComponent(String(pending.attemptId));
    const persistenceStatus = saved
        ? `<p role="status">Your attempt was saved successfully.</p>`
        : saving
            ? `<p role="status">Saving your attempt…</p>`
            : `<p role="alert">Your score was calculated, but this attempt was not saved. Retry before leaving this page if you want it in History, Analytics, Learning Intelligence, and Review.</p>`;
    const persistenceAction = saved
        ? `<button onclick="location.href='/history?attempt=${reviewAttempt}'">
                📌 Review This Attempt
            </button>`
        : saving
            ? `<button disabled aria-disabled="true">Saving Attempt…</button>`
            : `<button onclick="retryExamAttemptSave()">Retry Saving Attempt</button>`;

    resultDiv.classList.remove("hidden");
    resultDiv.style.display = "block";
    resultDiv.innerHTML = `
        <h2>Exam Results</h2>
        <p><b>Score:</b> ${pending.score} / ${pending.total} (${pending.percent}%)</p>
        ${persistenceStatus}
        ${persistenceAction}

        <button onclick="location.href='/history'">
            📜 View Full History
        </button>

        <button onclick="location.reload()">
            🔁 Retake Exam
        </button>

        <button onclick="location.href='/'">
            🏠 Return to Dashboard
        </button>
    `;
}

async function savePendingExamAttempt() {
    const pending = pendingExamAttempt;
    if (!pending || examAttemptSaveInProgress) return;

    examAttemptSaveInProgress = true;
    renderExamResult(pending, "saving");
    try {
        const response = await fetch("/record_attempt", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(pending.payload)
        });
        const data = await response.json().catch(() => ({}));
        if (
            !response.ok ||
            data.ok !== true ||
            String(data.attempt_id || "") !== String(pending.attemptId)
        ) {
            throw new Error(data.error || `Attempt save failed (HTTP ${response.status})`);
        }

        try {
            saveHistory(
                pending.percent,
                pending.score,
                pending.total,
                pending.missed,
                pending.attemptId
            );
        } catch (historyError) {
            console.warn("Local history mirror could not be updated:", historyError);
        }
        pendingExamAttempt = null;
        renderExamResult(pending, "saved");
        console.log("RESULT UI RENDERED. Attempt ID:", pending.attemptId);
    } catch (error) {
        console.error("Attempt persistence failed:", error);
        renderExamResult(pending, "failed");
    } finally {
        examAttemptSaveInProgress = false;
    }
}

function retryExamAttemptSave() {
    void savePendingExamAttempt();
}

/* =====================================================
   SUBMIT — EXAM ONLY
===================================================== */
/* =====================================================
   SUBMIT — EXAM ONLY
===================================================== */
async function submitQuiz(force = false) {

    // Do nothing in Study Mode
    if (!examMode) {
        console.log("submitQuiz called but examMode = false; ignoring.");
        return;
    }

    if (pendingExamAttempt || examAttemptSaveInProgress) {
        return;
    }

    // Manual submit confirmation
    if (!force) {
        const ok = confirm("Are you sure you want to submit your exam?");
        if (!ok) {
            console.log("User cancelled exam submission.");
            return;
        }
    }


    console.log("SUBMIT EXAM");

    if (!quiz || !Array.isArray(quiz) || quiz.length === 0) {
        console.error("Quiz is empty or not loaded.");
        alert("Quiz failed to load.");
        return;
    }

    let correct = 0;
    let missed = [];
    let answerDetails = [];

    console.log("QUESTIONS:", quiz.length);

    try {
        for (let i = 0; i < quiz.length; i++) {
            const q = quiz[i];

            if (!q) continue;

            const key = `q${i}`;
            let ans = userAnswers[key];

            if (q.type === "hotspot") {
                const point = (ans && typeof ans === "object" && !Array.isArray(ans)) ? ans : null;
                const isCorrect = point &&
                    Number.isFinite(Number(point.x)) &&
                    Number.isFinite(Number(point.y)) &&
                    pointInHotspot(Number(point.x), Number(point.y), q.target);

                answerDetails.push({
                    attemptQuestionNumber: i + 1,
                    questionType: "hotspot",
                    wasCorrect: !!isCorrect,
                    selected: point ? {x: Number(point.x), y: Number(point.y)} : null
                });
                if (isCorrect) {
                    correct++;
                } else {
                    missed.push({
                        attemptQuestionNumber: i + 1,
                        number: q.number || (i + 1),
                        question: q.question,
                        questionType: "hotspot",
                        choices: [{label: "A", text: q.target_label || "Target structure"}],
                        correctLetters: ["A"],
                        correctText: [q.target_label || "Target structure"],
                        selectedIndexes: [],
                        selectedLetters: [],
                        selectedText: [point ? "Image location selected" : "[No answer]"],
                        hotspot: {
                            selected: point ? {x: Number(point.x), y: Number(point.y)} : null,
                            target: q.target || {},
                            targetLabel: q.target_label || "Target structure",
                            imageUrl: q.image_url || "",
                            imageAlt: q.image_alt || "Study image",
                            imageEdits: q.image_edits || [],
                            explanation: q.explanation || "",
                            verification: q.verification || {},
                            imageSource: q.image_source || {}
                        }
                    });
                }
                continue;
            }

            if (q.type === "matching") {
                const pairs = Array.isArray(q.pairs) ? q.pairs : [];
                const matchAns = (ans && typeof ans === "object" && !Array.isArray(ans)) ? ans : {};
                const isCorrect = pairs.length >= 2 && pairs.every((pair, pairIndex) => Number(matchAns[pairIndex]) === pairIndex);
                answerDetails.push({
                    attemptQuestionNumber: i + 1,
                    questionType: "matching",
                    wasCorrect: !!isCorrect,
                    selected: matchAns
                });
                if (isCorrect) {
                    correct++;
                } else {
                    missed.push({
                        attemptQuestionNumber: i + 1,
                        number: q.number || (i + 1),
                        question: q.question,
                        questionType: "matching",
                        choices: pairs.map((pair, pairIndex) => ({ label: String(pairIndex + 1), text: `${pair.left} ↔ ${pair.right}` })),
                        correctLetters: [],
                        correctText: pairs.map(pair => `${pair.left} ↔ ${pair.right}`),
                        selectedIndexes: [],
                        selectedLetters: [],
                        selectedText: pairs.map((pair, pairIndex) => {
                            const chosenIndex = matchAns[pairIndex];
                            const chosen = pairs[chosenIndex];
                            return `${pair.left} ↔ ${chosen ? chosen.right : "[No answer]"}`;
                        })
                    });
                }
                continue;
            }

            if (!q.correct || !Array.isArray(q.correct)) {
                console.warn("Choice question missing 'correct' field:", q);
                continue;
            }

            // Normalize answer to an array of indexes
            if (!Array.isArray(ans)) {
                ans = (ans === undefined || ans === null) ? [] : [ans];
            }

            // Convert ["A"] -> [0], ["D"] -> [3], etc.
            const correctIndexes = q.correct.map(
                l => String(l).toUpperCase().charCodeAt(0) - 65
            );

            // Compare arrays safely
            const isCorrect =
                ans.length === correctIndexes.length &&
                ans.every((v, idx) => v === correctIndexes[idx]);

            answerDetails.push({
                attemptQuestionNumber: i + 1,
                questionType: "choice",
                wasCorrect: !!isCorrect,
                selected: ans.map(idx => String.fromCharCode(65 + idx))
            });

            if (isCorrect) {
                correct++;
            } else {
    missed.push({
        attemptQuestionNumber: i + 1,
        number: q.number || (i + 1),
        question: q.question,

        // 🔑 FULL SNAPSHOT OF ALL CHOICES (THIS IS THE FIX)
        choices: q.choices.map(c => ({
            label: c.label,
            text: c.text
        })),

        // Correct Answers
        correctLetters: q.correct,
        correctText: q.correct.map(letter => {
            const choice = q.choices.find(
                c => c.label.toUpperCase() === letter.toUpperCase()
            );

            if (!choice) {
                console.error(
                    "SCORING ERROR: Missing choice for letter",
                    letter,
                    "Question:",
                    q
                );
                return `${letter} — [Missing choice]`;
            }

            return `${letter} — ${choice.text}`;
        }),

        // What the user actually selected
        selectedIndexes: ans,
        selectedLetters: ans.map(idx => String.fromCharCode(65 + idx)),
        selectedText: ans.map(idx =>
            `${String.fromCharCode(65 + idx)} — ${q.choices[idx].text}`
        )
    });

}

        }
    } catch (e) {
        console.error("ERROR DURING SCORING:", e);
        alert("Something went wrong while scoring the exam.");
        return;
    }

    console.log("SCORING COMPLETE. Correct:", correct);

    const total = quiz.length;
    const percent = Math.round((correct / total) * 100);

    stopExamTimer();

    const attemptId = (window.crypto && crypto.randomUUID)
        ? crypto.randomUUID()
        : String(Date.now());

    const attemptPayload = {
            quizTitle: window.quiz_title || QUIZ_FILE || "Unknown Quiz",
            quizId: window.QUIZ_ID,

            score: correct,
            total: total,
            percent: percent,
            attemptId: attemptId,
            startedAt: examStartTime,
            completedAt: new Date().toISOString(),
            timeRemaining: timeRemaining,

            mode: "Exam",
            sessionId: learningSessionId,
            responseDetails: answerDetails,

            missedDetails: missed
    };
    pendingExamAttempt = {
        attemptId: attemptId,
        score: correct,
        total: total,
        percent: percent,
        missed: missed,
        payload: attemptPayload
    };
    await savePendingExamAttempt();
}


/* =====================================================
   SAVE HISTORY (localStorage, per-quiz)
===================================================== */
/* =====================================================
   SAVE HISTORY (localStorage, per-quiz)
===================================================== */
function saveHistory(percent, correct, total, missed, attemptId) {
    const HISTORY_KEY = "serverplus_history_v2";

    let store;
    try {
        store = JSON.parse(localStorage.getItem(HISTORY_KEY) || "{}");
    } catch (e) {
        console.warn("Failed to parse history store, resetting.", e);
        store = {};
    }

    /* --------------------------------------------
       Determine Quiz KEY for grouping history
       Priority:
       1️⃣ User-supplied quiz name (from your portal)
       2️⃣ Existing QUIZ_FILE fallback (old behavior)
    -------------------------------------------- */
    let quizKey = "Unnamed Quiz";

    // If you already store quiz title globally, catch it
    if (window.quiz_title && window.quiz_title.trim()) {
        quizKey = window.quiz_title.trim();
    }

    // If you capture quiz name from an input box
    else if (document.getElementById("quiz_title")) {
        const val = document.getElementById("quiz_title").value.trim();
        if (val) quizKey = val;
    }

    // FINAL fallback to filename (keeps compatibility)
    else if (typeof QUIZ_FILE !== "undefined") {
        quizKey = QUIZ_FILE;
    }

    if (!store[quizKey]) {
        store[quizKey] = [];
    }

    store[quizKey].push({
        id: attemptId,
        date: new Date().toLocaleString(),
        score: correct,      
        total: total,        
        percent: percent,    
        timeRemaining: timeRemaining,
        mode: "Exam",
        missed: missed       
    });

    localStorage.setItem(HISTORY_KEY, JSON.stringify(store));
    console.log("History saved for quizKey:", quizKey, "Attempt:", attemptId);
}

function resetDatabase() {
    const msg =
        "⚠️ WARNING ⚠️\n\n" +
        "This will permanently delete:\n" +
        "• ALL quizzes\n" +
        "• ALL attempts\n" +
        "• ALL missed-question history\n\n" +
        "Quiz numbering will restart from the beginning.\n\n" +
        "This action CANNOT be undone.\n\n" +
        "Click OK to continue.";

    if (!confirm(msg)) {
        return;
    }

    fetch("/wipe_database", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        }
    })
    .then(res => {
        if (!res.ok) {
            throw new Error("Database reset failed");
        }
        return res.json();
    })
    .then(() => {
        alert("Database reset complete.");
        window.location.reload();
    })
    .catch(err => {
        console.error(err);
        alert("Error resetting database. See console.");
    });
}

/* =====================================================
   Review Study Question with AI (NEW FEATURE)
===================================================== */
function copyStudyAIPromptSynchronously(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    textarea.style.top = "-9999px";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();

    try {
        return document.execCommand("copy");
    } finally {
        document.body.removeChild(textarea);
    }
}

window.reviewCurrentQuestionWithAI = function() {
    try {
        const aiConfig = studyAIConfig;

        if (!aiConfig) {
            loadStudyAIConfig();
            alert("AI Helper settings are still loading. Please try again.");
            return;
        }

        if (!aiConfig || !aiConfig.ai_helper_enabled) {
            alert("AI Helper is disabled in Settings.");
            return;
        }

        // =========================
        // READ CURRENT QUESTION FROM DOM
        // =========================
        const questionEl = document.getElementById("qText");
        if (!questionEl) {
            throw new Error("Could not find question text on page");
        }

        const questionText = questionEl.innerText.trim();

        // Get all answer choices
        const choiceEls = document.querySelectorAll("#choices label, #choices div, #choices button");
        let choicesText = "";

        choiceEls.forEach(el => {
            const txt = el.innerText.trim();
            if (txt) {
                choicesText += txt + "\n";
            }
        });

        // Try to find correct answer (Study Mode usually shows it)
        let correctText = "(Correct answer not visible)";
        const correctEl = document.querySelector(".correct, .correct-answer");
        if (correctEl) {
            correctText = correctEl.innerText.trim();
        }

        let userAnswer = "Not answered yet — I am studying this question and want help understanding it.";

        // Study Mode marks the chosen answer visually.
        // Look for the selected/highlighted answer inside #choices.
        const selectedChoice = Array.from(document.querySelectorAll("#choices button, #choices div, #choices label"))
            .find(el => {
                const cls = (el.className || "").toString().toLowerCase();
                const style = (el.getAttribute("style") || "").toLowerCase();

                return (
                    cls.includes("selected") ||
                    cls.includes("wrong") ||
                    cls.includes("incorrect") ||
                    cls.includes("correct") ||
                    style.includes("green") ||
                    style.includes("red") ||
                    style.includes("00ff80") ||
                    style.includes("ff4d4d")
                );
            });

        if (selectedChoice) {
            userAnswer = selectedChoice.innerText.trim();
        }

        const questionBlock = `Question
---------------------
${questionText}

Answer Choices:
${choicesText.trim()}

Correct Answer:
${correctText}

My Answer:
${userAnswer}`;

// =========================
// STUDY MODE AI PROMPT
// =========================
const finalPrompt = `I am studying this question and want help understanding it.

Please:
1. Explain the core concept being tested in simple terms.
2. Identify the correct answer.
3. Explain why the correct answer is correct.
4. Briefly explain why the other answer choices are not the best answer.
5. Keep the explanation concise and beginner-friendly, and offer to go deeper if I ask.

---

${questionBlock.trim()}`;

        // =========================
        // COPY TO CLIPBOARD
        // =========================
        try {
            copyStudyAIPromptSynchronously(finalPrompt);
        } catch (copyErr) {
            console.warn("[AI Study Mode] Clipboard copy failed:", copyErr);
        }

        // =========================
        // OPEN AI
        // =========================
        const providers = {
            chatgpt: "https://chatgpt.com/",
            claude: "https://claude.ai/",
            gemini: "https://gemini.google.com/"
        };

        const url = aiConfig.ai_provider === "local"
            ? (aiConfig.ai_custom_url || "").trim()
            : providers[aiConfig.ai_provider];

        if (!url) {
            alert("No AI provider configured in Settings.");
            return;
        }

        window.open(url, "_blank", "noopener,noreferrer");

    } catch (err) {
        console.error("[AI Study Mode] Failed:", err);
        alert("AI feature failed:\n\n" + err.message);
    }
};
