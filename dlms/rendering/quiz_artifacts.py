"""Generated quiz HTML/JSON rendering and persisted-artifact rebuild helpers."""

import json
import os
import re
import secrets
import time

from dlms.rendering.safety import (
    _html_attribute,
    _html_text,
    _json_for_inline_script,
)


def _write_staged_quiz_json(
    path,
    payload,
    *,
    open_file=open,
    json_module=json,
    fsync=os.fsync,
):
    """Write and parse-validate one staged quiz JSON artifact."""
    with open_file(path, "w", encoding="utf-8") as f:
        json_module.dump(payload, f, indent=4, ensure_ascii=False)
        f.flush()
        fsync(f.fileno())
    with open_file(path, "r", encoding="utf-8") as f:
        validated = json_module.load(f)
    if not isinstance(validated, list):
        raise ValueError("Generated quiz JSON must contain a question list")


def _generated_quiz_artifact_identity(
    *, time_ns=time.time_ns, token_hex=secrets.token_hex
):
    """Return a collision-resistant identity shared by generated quiz artifacts."""
    return f"{time_ns() // 1_000_000}_{token_hex(4)}"


def _generated_quiz_artifact_names(
    prefix, *, artifact_identity=_generated_quiz_artifact_identity
):
    """Return unique HTML/JSON artifact names for one generated quiz."""
    safe_prefix = (
        re.sub(r"[^a-z0-9_]+", "_", str(prefix or "study").lower()).strip("_")
        or "study"
    )
    stem = f"{safe_prefix}_{artifact_identity()}"
    return f"{stem}.html", f"{stem}.json"


def _quiz_json_payload_from_db(
    cur,
    quiz_id,
    *,
    question_concepts,
    json_module=json,
):
    """Serialize one quiz from the caller's current SQLite transaction."""
    questions = cur.execute(
        """
        SELECT id, question_number, question_text,
               COALESCE(question_type, 'choice') AS question_type,
               matching_round_size,
               COALESCE(matching_direction, 'term_to_definition') AS matching_direction,
               COALESCE(explanation, '') AS explanation,
               COALESCE(media_json, '{}') AS media_json,
               source_organization, source_dataset, source_version, source_url, source_license
        FROM questions
        WHERE quiz_id = ?
        ORDER BY question_number, id
        """,
        (quiz_id,)
    ).fetchall()

    quiz_data = []

    for q in questions:
        if q["question_type"] == "matching":
            pairs = cur.execute(
                """
                SELECT left_text, right_text, category, explanation, verification_json
                FROM matching_pairs
                WHERE question_id = ?
                ORDER BY pair_order, id
                """,
                (q["id"],)
            ).fetchall()
            item = {
                "number": q["question_number"],
                "type": "matching",
                "question": q["question_text"],
                "pairs": [
                    {
                        "left": pair["left_text"],
                        "right": pair["right_text"],
                        "category": pair["category"] or "",
                        "explanation": pair["explanation"] or "",
                        "verification": (
                            json_module.loads(pair["verification_json"])
                            if pair["verification_json"] else {}
                        ),
                    }
                    for pair in pairs
                ],
                "round_size": q["matching_round_size"],
                "direction": q["matching_direction"],
                "explanation": q["explanation"] or "",
                "concepts": question_concepts(cur, q["id"]),
            }
            try:
                media = json_module.loads(q["media_json"] or "{}")
            except Exception:
                media = {}
            if isinstance(media, dict):
                item.update(media)
            source = {
                "organization": q["source_organization"],
                "dataset": q["source_dataset"],
                "version": q["source_version"],
                "url": q["source_url"],
                "license": q["source_license"],
            }
            if any(source.values()):
                item["source"] = source
            quiz_data.append(item)
            continue

        choices = cur.execute(
            """
            SELECT label, text, is_correct
            FROM choices
            WHERE question_id = ?
            ORDER BY label
            """,
            (q["id"],)
        ).fetchall()

        correct_letters = [c["label"] for c in choices if c["is_correct"]]

        choice_item = {
            "number": q["question_number"],
            "type": "choice",
            "question": q["question_text"],
            "explanation": q["explanation"] or "",
            "concepts": question_concepts(cur, q["id"]),
            "choices": [
                {
                    "label": c["label"],
                    "text": c["text"],
                    "is_correct": bool(c["is_correct"])
                }
                for c in choices
            ],
            "correct": correct_letters
        }
        try:
            media = json_module.loads(q["media_json"] or "{}")
        except Exception:
            media = {}
        if isinstance(media, dict):
            choice_item.update(media)
        source = {
            "organization": q["source_organization"],
            "dataset": q["source_dataset"],
            "version": q["source_version"],
            "url": q["source_url"],
            "license": q["source_license"],
        }
        if any(source.values()):
            choice_item["source"] = source
        quiz_data.append(choice_item)

    return quiz_data


def _quiz_registry_entry(registry, quiz_id):
    return next(
        (entry for entry in registry if str(entry.get("id")) == str(quiz_id)),
        None,
    )


def _quiz_artifact_names(quiz_entry, *, basename=os.path.basename):
    html_name = str((quiz_entry or {}).get("html") or "")
    if (
        not html_name.lower().endswith(".html")
        or html_name != basename(html_name)
        or "/" in html_name
        or "\\" in html_name
    ):
        raise ValueError("Quiz registry entry has an unsafe or missing HTML filename")
    return html_name, html_name[:-5] + ".json"


def rebuild_quiz_json_from_db(
    quiz_id,
    *,
    conn=None,
    quiz_entry=None,
    output_path=None,
    get_db,
    row_factory,
    load_registry,
    quiz_registry_entry,
    quiz_artifact_names,
    quiz_json_payload_from_db,
    data_folder,
    write_staged_quiz_json,
    token_hex=secrets.token_hex,
    makedirs=os.makedirs,
    dirname=os.path.dirname,
    join_path=os.path.join,
    replace_file=os.replace,
    exists=os.path.exists,
    remove_file=os.remove,
    print_message=print,
):
    owns_connection = conn is None
    if owns_connection:
        conn = get_db()
    conn.row_factory = row_factory
    cur = conn.cursor()

    if quiz_entry is None:
        quiz_entry = quiz_registry_entry(load_registry(), quiz_id)
    if not quiz_entry:
        if owns_connection:
            conn.close()
        print_message("[EDIT] Could not find quiz registry entry for JSON rebuild:", quiz_id)
        return False

    _, json_name = quiz_artifact_names(quiz_entry)
    json_path = output_path or join_path(data_folder, json_name)
    temp_path = None
    try:
        payload = quiz_json_payload_from_db(cur, quiz_id)
        if output_path is None:
            makedirs(dirname(json_path), exist_ok=True)
            temp_path = json_path + f".tmp-{token_hex(8)}"
            write_staged_quiz_json(temp_path, payload)
            replace_file(temp_path, json_path)
            temp_path = None
        else:
            write_staged_quiz_json(json_path, payload)
    finally:
        if temp_path and exists(temp_path):
            remove_file(temp_path)
        if owns_connection:
            conn.close()

    print_message("[EDIT] Rebuilt quiz JSON:", json_path)
    return True


def rebuild_quiz_html_from_registry(
    quiz_id,
    *,
    quiz_entry=None,
    output_path=None,
    load_registry,
    quiz_registry_entry,
    quiz_artifact_names,
    quiz_folder,
    build_quiz_html,
    get_portal_title,
    token_hex=secrets.token_hex,
    makedirs=os.makedirs,
    dirname=os.path.dirname,
    join_path=os.path.join,
    isfile=os.path.isfile,
    getsize=os.path.getsize,
    replace_file=os.replace,
    exists=os.path.exists,
    remove_file=os.remove,
    print_message=print,
):
    if quiz_entry is None:
        quiz_entry = quiz_registry_entry(load_registry(), quiz_id)

    if not quiz_entry:
        print_message("[EDIT] Could not find quiz registry entry for HTML rebuild:", quiz_id)
        return False

    html_name, json_name = quiz_artifact_names(quiz_entry)
    html_path = output_path or join_path(quiz_folder, html_name)
    temp_path = None
    try:
        render_path = html_path
        if output_path is None:
            makedirs(dirname(html_path), exist_ok=True)
            temp_path = html_path + f".tmp-{token_hex(8)}"
            render_path = temp_path
        build_quiz_html(
            html_name,
            json_name,
            render_path,
            get_portal_title(),
            quiz_entry.get("title") or "Edited Quiz",
            quiz_entry.get("logo"),
            quiz_id,
            quiz_entry.get("exam_minutes", 90)
        )
        if not isfile(render_path) or getsize(render_path) == 0:
            raise RuntimeError("Generated quiz HTML is empty or missing")
        if temp_path:
            replace_file(temp_path, html_path)
            temp_path = None
    finally:
        if temp_path and exists(temp_path):
            remove_file(temp_path)

    print_message("[EDIT] Rebuilt quiz HTML:", html_path)
    return True


def build_quiz_html(
    name,
    jsonfile,
    outpath,
    portal_title,
    quiz_title,
    logo_filename,
    quiz_id,
    exam_minutes=90,
    *,
    normalize_exam_minutes,
    html_text=_html_text,
    html_attribute=_html_attribute,
    json_for_inline_script=_json_for_inline_script,
    open_file=open,
):
    exam_minutes = normalize_exam_minutes(exam_minutes)
    portal_title_html = html_text(portal_title)
    quiz_title_html = html_text(quiz_title)
    quiz_title_json = json_for_inline_script(str(quiz_title or ""))
    quiz_file_json = json_for_inline_script(f"/data/{jsonfile}")
    quiz_id_json = json_for_inline_script(quiz_id)
    # Optional logo for mode banner (left/right)
    if logo_filename:
        logo_url = html_attribute(f"/user-static/logos/{logo_filename}")
        mode_logo = f'<img src="{logo_url}" class="mode-badge">'
    else:
        mode_logo = ""


    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{quiz_title_html}</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.ico">

<!-- 🔑 Canonical quiz identity for script.js + DB -->
<script>
  window.quiz_title = {quiz_title_json};
  window.examDurationMinutes = {exam_minutes};
</script>

</head>

<body>

<!-- 🔹 Background is handled by /static/style.css importing /dynamic.css -->

<!-- 🔹 Overlay shown when exam is paused -->
<div id="pauseOverlay" class="pause-overlay">
    <div class="pause-overlay-content">
        <h2>Exam Paused</h2>
        <p>Your time is frozen. Click Resume to continue.</p>
        <button onclick="resumeExam()">Resume</button>
    </div>
</div>

<!-- 🔹 Everything that should blur goes inside this wrapper -->
<div id="quizWrapper" class="blur-wrapper">
    <div class="container">

        <!-- Readable Centered Banner -->
        <h1 class="hero-title">
            {portal_title_html}<br>
            <span style="font-size:20px;opacity:.85">{quiz_title_html}</span>
        </h1>

                <!-- Mode Select -->
        <div id="modeSelect" class="card quiz-mode-card">
            <div class="mode-banner">
                <div class="mode-logo-slot">
                    {mode_logo}
                </div>

                <div class="mode-center">
                    <h2>Select Mode</h2>

                    <div class="mode-button-row">
                        <button class="mode-btn study-mode-btn" onclick="startQuiz(false)">
                            📖 Study Mode
                        </button>

                        <button class="mode-btn exam-mode-btn" onclick="startQuiz(true)">
                            🛡️ Exam Mode
                        </button>
                    </div>
                </div>

                <div class="mode-logo-slot">
                    {mode_logo}
                </div>
            </div>
        </div>

                <!-- Quiz Area -->
        <div id="quiz" class="hidden quiz-shell">
                        <!-- Active Quiz Logo Banner -->
            <div class="active-quiz-logo-banner">
                <div class="active-logo-slot">
                    {mode_logo}
                </div>

                <div class="active-quiz-title">
                    {quiz_title_html}
                </div>

                <div class="active-logo-slot">
                    {mode_logo}
                </div>
            </div>

            <!-- TOP BAR -->
            <div class="top-bar quiz-toolbar">

                <!-- LEFT -->
                <div class="top-left">
                    <button onclick="submitQuiz()" id="submitBtn" class="danger">
                        📄 Submit Exam
                    </button>
                </div>

                <!-- RIGHT -->
                <div id="timer" class="hidden timerBox top-right quiz-timer-group">
                    <span id="timerLabel">Time Remaining:</span>
                    <span id="timeDisplay">--:--</span>
                    <button id="pauseBtn" onclick="pauseExam()">⏸ Pause</button>
                </div>

            </div>

            <!-- Progress Bar -->
            <div class="quiz-progress-card">
                <div class="quiz-progress-meta">
                    <span>Question Progress</span>
                    <span></span>
                </div>

                <div id="progressBarOuter">
                    <div id="progressBarInner"></div>
                </div>
            </div>

            <!-- Question Area -->
            <div class="quiz-question-card">
                <div id="qHeader"></div>
                <div id="qText"></div>
                <div id="choices"></div>
            </div>

            <!-- Navigation Controls -->
            <div class="controls quiz-nav-buttons">
                <button id="prevBtn" onclick="prev()">← Previous Question</button>

                <button id="nextBtn" onclick="next()">Next Question →</button>

                <button id="studyAiBtn"
                        type="button"
                        class="hidden"
                        onclick="reviewCurrentQuestionWithAI()">
                    ✨ Review This Question with AI
                </button>

                <button id="studyAnkiBtn"
                        type="button"
                        class="hidden"
                        onclick="toggleCurrentQuestionForAnki()">
                    ⭐ Mark for Anki
                </button>

                <button id="studyAnkiExportBtn"
                        type="button"
                        class="hidden"
                        onclick="exportStudyAnkiSelections()">
                    📦 Export Selected to Anki
                </button>
            </div>
        </div>

        <div id="result" class="hidden"></div>

        <br>

        <div class="quiz-return-buttons">
            <a id="returnPortalBtn" href="/">
                🏠 Return To Dashboard
            </a>

            <a id="returnLibraryBtn" href="/library">
                📚 Return To Quiz Library
            </a>
        </div>
</div>
</div>

<!-- 🔹 Tell script.js which quiz + JSON file to load -->
<script>
  const QUIZ_FILE = {quiz_file_json};
  window.QUIZ_ID = {quiz_id_json};
</script>

<script src="/static/script.js"></script>


<script src="/static/nav-normalize.js"></script>
</body>
</html>
"""

    with open_file(outpath, "w", encoding="utf-8") as f:
        f.write(html)
