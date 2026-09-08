"""Classic upload, paste, matching-bank, and manual quiz authoring routes."""

import csv
from functools import wraps
import io
from io import BytesIO
import os
import re
import time

from flask import (
    Blueprint,
    current_app as app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
)

from .dependencies import QuizAuthoringDependencies


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view

def upload_page(dependencies):
    get_portal_title = dependencies.get_portal_title

    portal_title = get_portal_title()

    return render_template("quiz/upload.html", portal_title=portal_title)

def paste_page(dependencies):
    get_portal_title = dependencies.get_portal_title
    load_portal_config = dependencies.load_portal_config

    portal_title = get_portal_title()
    cfg = load_portal_config()

    return render_template("quiz/paste.html", portal_title=portal_title, cfg=cfg)

def matching_bank_import(dependencies):
    MATCHING_CSV_UPLOAD_MAX_BYTES = dependencies.matching_csv_upload_max_bytes()
    UploadTooLargeError = dependencies.upload_too_large_error()
    _matching_case_only_term_warnings = dependencies.matching_case_only_term_warnings
    _matching_record_validation_errors = dependencies.matching_record_validation_errors
    _publish_quiz = dependencies.publish_quiz
    _read_bounded_upload = dependencies.read_bounded_upload

    if request.method == "POST":
        quiz_title = request.form.get("quiz_title", "").strip()
        question_text = request.form.get("question_text", "Match each term with its correct definition.").strip()
        direction = request.form.get("direction", "term_to_definition").strip()
        if direction not in {"term_to_definition", "definition_to_term", "random"}:
            direction = "term_to_definition"
        raw_round_size = request.form.get("round_size", "10").strip()
        try:
            round_size = max(2, min(int(raw_round_size), 100))
        except (TypeError, ValueError):
            round_size = 10

        source = {
            "organization": request.form.get("source_organization", "").strip(),
            "dataset": request.form.get("source_dataset", "").strip(),
            "version": request.form.get("source_version", "").strip(),
            "url": request.form.get("source_url", "").strip(),
            "license": request.form.get("source_license", "").strip(),
        }
        upload = request.files.get("csv_file")
        if not quiz_title or not upload or not upload.filename:
            flash("Quiz title and CSV file are required.", "error")
            return redirect("/matching_bank_import")
        try:
            text = _read_bounded_upload(upload, MATCHING_CSV_UPLOAD_MAX_BYTES, "Matching CSV").decode("utf-8-sig")
        except UploadTooLargeError as exc:
            flash(str(exc), "error")
            return redirect("/matching_bank_import")
        except UnicodeDecodeError:
            flash("CSV must be UTF-8 encoded.", "error")
            return redirect("/matching_bank_import")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            flash("CSV is missing a header row.", "error")
            return redirect("/matching_bank_import")
        normalized = {name.strip().lower(): name for name in reader.fieldnames if name}
        term_col = normalized.get("term") or normalized.get("left")
        def_col = normalized.get("definition") or normalized.get("right") or normalized.get("match")
        if not term_col or not def_col:
            flash("CSV must contain term + definition columns (left + right are also accepted).", "error")
            return redirect("/matching_bank_import")
        pairs = []
        for row in reader:
            left = (row.get(term_col) or "").strip()
            right = (row.get(def_col) or "").strip()
            if not left or not right:
                continue
            pairs.append({"left": left, "right": right})
        matching_errors = _matching_record_validation_errors(
            pairs,
            context="matching CSV import",
            left_key="left",
            right_key="right",
            record_name="row",
        )
        if matching_errors:
            flash("; ".join(matching_errors), "error")
            return redirect("/matching_bank_import")
        for warning in _matching_case_only_term_warnings(
            pairs,
            context="matching CSV import",
            left_key="left",
            record_name="row",
        ):
            flash(warning, "warning")
        round_size = min(round_size, len(pairs))
        quiz_data = [{
            "number": 1,
            "type": "matching",
            "question": question_text or "Match each term with its correct definition.",
            "pairs": pairs,
            "round_size": round_size,
            "direction": direction,
            "source": source,
        }]
        quiz_id, _ = _publish_quiz(
            quiz_title,
            quiz_data,
            filename_prefix="matching_bank",
            exam_minutes=90,
        )
        flash(f"Matching bank imported: {len(pairs)} pairs; {round_size} shown per attempt.", "success")
        return redirect(f"/edit_quiz/{quiz_id}")

    return render_template("quiz/matching-bank-import.html")

def create_short_quiz_page(dependencies):
    get_portal_title = dependencies.get_portal_title

    portal_title = get_portal_title()

    # Two-stage manual builder:
    # 1) Ask how many question blocks to start with.
    # 2) Render exactly that many blocks. Users can still add/delete afterward.
    raw_count = request.args.get("count")
    builder_ready = raw_count is not None

    if builder_ready:
        try:
            starting_question_count = int(str(raw_count).strip())
        except (TypeError, ValueError):
            starting_question_count = 10

        # Keep the initial render reasonable while preserving the existing
        # dynamic Add/Delete Question controls once the builder is open.
        starting_question_count = max(1, min(starting_question_count, 100))
    else:
        starting_question_count = 10

    questions = []
    if builder_ready:
        for qnum in range(1, starting_question_count + 1):
            questions.append({
                "number": qnum,
                "choices": ["A", "B", "C", "D"]
            })

    return render_template("quiz/short-builder.html",
        portal_title=portal_title,
        questions=questions,
        builder_ready=builder_ready,
        starting_question_count=starting_question_count
    )

def save_short_quiz(dependencies):
    _matching_case_only_term_warnings = dependencies.matching_case_only_term_warnings
    _matching_record_validation_errors = dependencies.matching_record_validation_errors
    _publish_quiz = dependencies.publish_quiz
    normalize_exam_minutes = dependencies.normalize_exam_minutes
    finalize_logo_from_request = dependencies.finalize_logo_from_request

    quiz_title = request.form.get("quiz_title", "").strip()
    exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))

    if not quiz_title:
        flash("Quiz title is required.", "error")
        return redirect("/create_short_quiz")

    quiz_data = []

    # Dynamically detect all submitted questions
    question_numbers = sorted(
        int(key.replace("question_", ""))
        for key in request.form.keys()
        if key.startswith("question_")
        and key.replace("question_", "").isdigit()
    )

    for qnum in question_numbers:
        question_text = request.form.get(f"question_{qnum}", "").strip()
        question_type = request.form.get(f"question_type_{qnum}", "choice").strip().lower()

        if not question_text:
            continue

        if question_type == "matching":
            pairs = []
            pair_prefix = f"match_left_{qnum}_"
            pair_indexes = sorted(
                int(key.replace(pair_prefix, ""))
                for key in request.form.keys()
                if key.startswith(pair_prefix) and key.replace(pair_prefix, "").isdigit()
            )

            for pair_index in pair_indexes:
                left = request.form.get(f"match_left_{qnum}_{pair_index}", "").strip()
                right = request.form.get(f"match_right_{qnum}_{pair_index}", "").strip()
                if not left and not right:
                    continue
                if not left or not right:
                    flash(f"Question {qnum} has an incomplete matching pair.", "error")
                    return redirect("/create_short_quiz")
                pairs.append({"left": left, "right": right})

            if len(pairs) < 2:
                flash(f"Question {qnum} needs at least two matching pairs.", "error")
                return redirect("/create_short_quiz")

            matching_errors = _matching_record_validation_errors(
                pairs,
                context=f"manual matching question {qnum}",
                left_key="left",
                right_key="right",
                record_name="pair",
            )
            if matching_errors:
                flash("; ".join(matching_errors), "error")
                return redirect("/create_short_quiz")
            for warning in _matching_case_only_term_warnings(
                pairs,
                context=f"manual matching question {qnum}",
                left_key="left",
                record_name="pair",
            ):
                flash(warning, "warning")

            raw_round_size = request.form.get(f"matching_round_size_{qnum}", "").strip()
            try:
                round_size = int(raw_round_size) if raw_round_size else None
            except ValueError:
                round_size = None
            if round_size is not None:
                round_size = max(2, min(round_size, len(pairs)))
            direction = request.form.get(f"matching_direction_{qnum}", "term_to_definition").strip()
            if direction not in {"term_to_definition", "definition_to_term", "random"}:
                direction = "term_to_definition"
            quiz_data.append({
                "number": len(quiz_data) + 1,
                "type": "matching",
                "question": question_text,
                "pairs": pairs,
                "round_size": round_size,
                "direction": direction
            })
            continue

        choices = []
        correct_letters = []
        choice_prefix = f"choice_{qnum}_"
        choice_labels = sorted(
            [key.replace(choice_prefix, "") for key in request.form.keys() if key.startswith(choice_prefix)],
            key=lambda label: ord(label[0]) if label else 999
        )

        for label in choice_labels:
            choice_text = request.form.get(f"choice_{qnum}_{label}", "").strip()
            is_correct = bool(request.form.get(f"correct_{qnum}_{label}"))
            if not choice_text:
                continue
            if is_correct:
                correct_letters.append(label)
            choices.append({"label": label, "text": choice_text, "is_correct": is_correct})

        if not choices:
            flash(f"Question {qnum} must have at least one answer choice.", "error")
            return redirect("/create_short_quiz")
        if not correct_letters:
            flash(f"Question {qnum} must have at least one correct answer.", "error")
            return redirect("/create_short_quiz")

        quiz_data.append({
            "number": len(quiz_data) + 1,
            "type": "choice",
            "question": question_text,
            "choices": choices,
            "correct": correct_letters
        })

    if not quiz_data:
        flash("You must enter at least one question.", "error")
        return redirect("/create_short_quiz")

    ts = int(time.time())

    quiz_logo = request.files.get("quiz_logo")

    logo_filename = finalize_logo_from_request(
        app,
        ts,
        logo_file=quiz_logo
    )

    quiz_id, _ = _publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix="short_quiz",
        exam_minutes=exam_minutes,
        logo_filename=logo_filename,
        rollback_logo_filename=logo_filename,
    )

    flash("Short quiz created successfully.", "success")
    return redirect(f"/edit_quiz/{quiz_id}")

def preview_paste(dependencies):
    load_portal_config = dependencies.load_portal_config
    normalize_exam_minutes = dependencies.normalize_exam_minutes
    save_preview_logo = dependencies.save_preview_logo
    get_confidence_setting = dependencies.get_confidence_setting
    analyze_confidence = dependencies.analyze_confidence

    #cleanup_temp_logos()   # 🧹 optional cleanup (leave commented)

    quiz_text = request.form.get("quiz_text", "").strip()
    quiz_title = request.form.get("quiz_title", "Generated Quiz From Paste")
    exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))
    strip_rules_raw = request.form.get("strip_text", "").strip()

    # =========================
    # HANDLE LOGO PREVIEW (TEMP ONLY)
    # =========================
    preview_logo_name = save_preview_logo(
        app,
        request.files.get("quiz_logo")
    )





    if not quiz_text:
        return "No text provided.", 400

    # Start with raw text
    clean_text = quiz_text

    # Normalize ALL newline styles (Windows, Linux, literal \n)
    clean_text = (
        clean_text
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    # =========================
    # APPLY STRIP RULES (optional regex mode)
    # =========================
    strip_rules = []
    if strip_rules_raw:
        strip_rules = [r.strip() for r in strip_rules_raw.splitlines() if r.strip()]

    cfg = load_portal_config()
    regex_mode = cfg.get("enable_regex_strip", False)
    regex_replace_enabled = cfg.get("enable_regex_replace", False)

    if strip_rules:
        cleaned_lines = []

        for line in clean_text.splitlines():
            test = line
            remove = False

            for rule in strip_rules:

                # --- REGEX MODE ---
                if regex_mode:
                    try:
                        if re.search(rule, test, re.IGNORECASE):
                            remove = True
                            break
                    except re.error:
                        # Ignore bad regex patterns
                        pass

                # --- PLAIN TEXT MODE ---
                else:
                    if rule.lower() in test.lower():
                        remove = True
                        break

            if not remove:
                cleaned_lines.append(line)

        clean_text = "\n".join(cleaned_lines)

    # =========================
    # REGEX REPLACE ENGINE
    # =========================
    regex_replace_enabled = cfg.get("enable_regex_replace", False)

    replace_rules_raw = request.form.get("replace_rules", "").strip()
    applied_rules = []

    # -------------------------
    # MANUAL USER REGEX RULES
    # -------------------------
    if regex_replace_enabled and replace_rules_raw:
        for line in replace_rules_raw.splitlines():
            line = line.strip()
            if "=>" not in line:
                continue

            pattern, replacement = line.split("=>", 1)
            pattern = pattern.strip()
            replacement = replacement.strip()

            if not pattern:
                continue

            try:
                new_text = re.sub(
                    pattern,
                    replacement,
                    clean_text,
                    flags=re.IGNORECASE | re.MULTILINE
                )

                if new_text != clean_text:
                    applied_rules.append(pattern)

                clean_text = new_text

            except re.error:
                applied_rules.append(f"[INVALID REGEX] {pattern}")

    # =========================================================
    # REGEX PRESETS (state preserved for the template)
    # =========================================================
    preset_number_prefix_checked = bool(request.form.get("preset_number_prefix"))
    preset_pdf_spacing_checked = bool(request.form.get("preset_pdf_spacing"))
    preset_headers_checked = bool(request.form.get("preset_headers"))

    if regex_replace_enabled:
        preset_patterns = []

    # 1️⃣ Remove numbered prefixes FIRST
    if preset_number_prefix_checked:
        preset_patterns.append((
            r"^\s*\d+\.\s*",
            "",
            "Removed numbered prefixes"
        ))

    # 2️⃣ REMOVE HEADERS / FOOTERS SECOND
    if preset_headers_checked:
        preset_patterns.append((
            r"^\s*(Page\s+\d+.*|Copyright.*|All\s+Rights\s+Reserved.*)$",
            "",
            "Removed header/footer text"
        ))

    # 2️⃣ Fix PDF / Microsoft wrapped lines + hyphenation
    if preset_pdf_spacing_checked:
        preset_patterns.append((
            r"-\s*\n\s*",
            "",
            "Fixed PDF hyphen wraps"
        ))

        # SUPER SAFE PDF WRAP JOIN
        # Will NOT join across question boundaries
        preset_patterns.append((
            r"(?<=[a-z,;])\n(?=\s*[a-z])",
            " ",
            "Joined wrapped lines safely"
        ))





        # ---------- APPLY PRESETS ----------
        for pattern, replacement, label in preset_patterns:
            try:
                new_text = re.sub(
                    pattern,
                    replacement,
                    clean_text,
                    flags=re.IGNORECASE | re.MULTILINE
                )

                if new_text != clean_text:
                    applied_rules.append(label)

                clean_text = new_text

            except re.error:
                applied_rules.append(f"[INVALID PRESET REGEX] {pattern}")

    # =========================
    # AUTO MULTI-QUESTION SPLIT FIX
    # =========================
    safe_split_pattern = re.compile(
        r"(Correct\s*Answer[s]?:.*?\n)(?=\S)",
        re.IGNORECASE
    )

    # Also support Suggested Answer
    safe_split_pattern_2 = re.compile(
        r"(Suggested\s*Answer[s]?:.*?\n)(?=\S)",
        re.IGNORECASE
    )

    new_text = clean_text

    new_text = safe_split_pattern.sub(r"\1\n", new_text)
    new_text = safe_split_pattern_2.sub(r"\1\n", new_text)

    if new_text != clean_text:
        applied_rules.append("Auto Question Splitter")
        clean_text = new_text

    # =========================
    # FORCE MCQ OPTIONS ON CLEAN LINES
    # =========================
    # 1️⃣ Ensure every choice letter starts a new line
    choice_line_fix = re.compile(
        r"\s+(?=([A-Z]\.\s))"
    )

    new_text = clean_text
    new_text = choice_line_fix.sub(r"\n", new_text)

    # 2️⃣ Remove accidental double newlines caused by above
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)

    if new_text != clean_text:
        applied_rules.append("Normalized MCQ Choices")
        clean_text = new_text




    # =========================
    # AUTO BOM / INVISIBLE CLEAN
    # =========================
    invis_cleanup_enabled = cfg.get("auto_bom_clean", False)
    removed_unicode = []

    if invis_cleanup_enabled:
        invisibles = [
            ("\uFEFF", "BOM"),
            ("\u200B", "Zero-Width Space"),
            ("\u200C", "Zero-Width Non-Joiner"),
            ("\u200D", "Zero-Width Joiner"),
            ("\u2060", "Word Joiner"),
        ]

        before = clean_text

        for char, label in invisibles:
            if char in clean_text:
                removed_unicode.append(label)
                clean_text = clean_text.replace(char, "")

        # Normalize multiple blank lines
        clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)

        # If BOM only at start
        if before != clean_text and "BOM" not in removed_unicode:
            if before.startswith("\uFEFF"):
                removed_unicode.append("BOM")
                clean_text = clean_text.lstrip("\uFEFF")

    # -------- CONFIDENCE ANALYSIS --------
    conf_summary = conf_details = None
    if get_confidence_setting():
        conf_summary, conf_details = analyze_confidence(clean_text)

    # -------- SMART SUGGESTIONS --------
    smart_suggestions = []

    def add_suggestion(title, detail, recommend, rule=None):
        smart_suggestions.append({
            "title": title,
            "detail": detail,
            "recommend": recommend,
            "suggest_rule": rule
        })

    text = clean_text

    # 1️⃣ Detect wrapped PDF text
    if re.search(r"(?<![.!?])\n(?!\n)", text):
        add_suggestion(
            "Possible PDF Wrap Detected",
            "Lines appear split where they should be continuous sentences.",
            "Enable PDF Line Wrapping Fix preset.",
            "Enable preset: PDF Wrapping"
        )

    # 2️⃣ Detect numbered prefixes like 1. Question
    if re.search(r"^\s*\d+\.\s+", text, re.MULTILINE):
        add_suggestion(
            "Numbered Question Prefixes Found",
            "Detected numbering like '1.' or '22.' before questions.",
            "Enable Number Prefix Removal preset.",
            r"^\s*\d+\.\s* => "
        )

    # 3️⃣ Detect repeated header/footer patterns
    if re.search(r"Page\s+\d+", text) or re.search(r"Copyright", text, re.I):
        add_suggestion(
            "Likely Headers/Footers Detected",
            "Repeated structural text such as page numbers or copyright text found.",
            "Enable Header/Footer Cleanup preset.",
            "Enable preset: Headers"
        )

    # 4️⃣ Detect if nothing changed
    if quiz_text == clean_text:
        add_suggestion(
            "No Formatting Changes Applied",
            "None of your strip or regex rules changed the text.",
            "Try enabling presets or adding regex rules."
        )

    # 5️⃣ If no warnings, say it’s clean
    if len(smart_suggestions) == 0:
        add_suggestion(
            "Formatting Looks Excellent",
            "No structural or formatting problems detected.",
            "You can safely continue 👍"
        )


    # =========================
    # UI SUPPORT LOGIC — ensure template displays correctly
    # =========================

    # If global regex replace enabled but user did not submit rules,
    # keep replace_rules list empty but still treat engine as active
    replace_rules = replace_rules_raw.splitlines() if replace_rules_raw else []

    # Make template show replace rules section when enabled globally
    if regex_replace_enabled and not replace_rules:
        replace_rules = ["(Regex engine enabled — no manual rules entered)"]


    # ---------- RENDER PREVIEW ----------
    return render_template("quiz/paste-preview.html",

        quiz_title=quiz_title,
        exam_minutes=exam_minutes,
        original=quiz_text,
        cleaned=clean_text,
        conf_summary=conf_summary,
        conf_details=conf_details,
        preview_logo_name=preview_logo_name,
        regex_mode=regex_mode,
        strip_rules=strip_rules,
        replace_rules=replace_rules,
        applied_rules=applied_rules,
        invis_cleanup_enabled=invis_cleanup_enabled,
        removed_unicode=removed_unicode,
        preset_number_prefix_checked=preset_number_prefix_checked,
        preset_pdf_spacing_checked=preset_pdf_spacing_checked,
        preset_headers_checked=preset_headers_checked,
        smart_suggestions=smart_suggestions
        )

def download_cleaned(dependencies):
    cleaned = request.form.get("clean_text", "").strip()

    if not cleaned:
        return "No cleaned text available.", 400

    buf = BytesIO()
    buf.write(cleaned.encode("utf-8"))
    buf.seek(0)

    return send_file(
        buf,
        mimetype="text/plain",
        as_attachment=True,
        download_name="cleaned_quiz_text.txt"
    )

def process_paste(dependencies):
    DATA_FOLDER = dependencies.data_folder()
    LOGO_FOLDER = dependencies.logo_folder()
    PARSE_LOG = dependencies.parse_log_path()
    UPLOAD_FOLDER = dependencies.upload_folder()
    _publish_quiz = dependencies.publish_quiz
    normalize_exam_minutes = dependencies.normalize_exam_minutes
    finalize_logo_from_request = dependencies.finalize_logo_from_request
    parse_questions = dependencies.parse_questions
    dprint = dependencies.debug_print

    #cleanup_temp_logos()   # 🧹 clean abandoned logos again

    quiz_text = request.form.get("quiz_text", "").strip()
    quiz_title = request.form.get("quiz_title", "Generated Quiz From Paste")
    exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))

    # Checkbox flag (Auto Junk Cleanup)
    auto_cleanup = request.form.get("auto_cleanup") == "1"

    if not quiz_text:
        return "No text provided.", 400

    clean_text = quiz_text

    # Normalize ALL newline styles (Windows, Linux, Literal \n)
    clean_text = (
        clean_text
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    # Optional auto cleanup (only runs if you wire a checkbox)
    if auto_cleanup:
        cleaned_lines = []
        junk_patterns = [
            "topic",
            "chapter",
            "exam version",
            "objective",
            "learning goal",
            "case study",
            "scenario",
            "explanation",
            "rationale",
            "reference",
            "page",
        ]

        for line in clean_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            low = stripped.lower()
            if any(p in low for p in junk_patterns):
                continue
            cleaned_lines.append(line)

        clean_text = "\n".join(cleaned_lines)

    # Save cleaned text (for debugging / consistency)
    path = os.path.join(UPLOAD_FOLDER, "pasted.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(clean_text)

    # =========================
    # PARSE QUIZ
    # =========================
    quiz_data = parse_questions(clean_text)

    # Always save a parse log (success or failure)
    ts = int(time.time())
    log_filename = f"parse_log_{ts}.txt"
    with open(os.path.join(DATA_FOLDER, log_filename), "w", encoding="utf-8") as f:
        f.write("\n".join(PARSE_LOG))

    # If no questions parsed, show failure UI + log link
    if not quiz_data:
        return render_template("quiz/parse-failed.html", log_filename=log_filename), 400

    # =========================
    # HANDLE LOGO (FINAL, SINGLE SOURCE OF TRUTH)
    # =========================
    logo_filename = finalize_logo_from_request(
        app,
        ts,
        logo_file=request.files.get("quiz_logo"),
        temp_logo_name=request.form.get("temp_logo_name"),
    )


    # =========================
    # REGISTRY ID (CANONICAL)
    # =========================



    # =========================
    # SAVE QUIZ
    # =========================
    source_file = f"quiz_upload_{ts}_{int(time.time() * 1000)}"

    db_quiz_id, html_name = _publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix="quiz",
        exam_minutes=exam_minutes,
        logo_filename=logo_filename,
        source_file=source_file,
        rollback_logo_filename=logo_filename,
    )


    # FINAL SAFETY: only register logo if file actually exists
    if logo_filename:
        final_logo_path = os.path.join(LOGO_FOLDER, logo_filename)
        if not os.path.exists(final_logo_path):
            dprint("[LOGO FIX] Prevented registering missing logo:", logo_filename)
            logo_filename = None

    #add_quiz_to_registry(html_name, quiz_title, logo_filename)

    return redirect("/library")

def process_file(dependencies):
    DATA_FOLDER = dependencies.data_folder()
    PARSE_LOG = dependencies.parse_log_path()
    QUIZ_TEXT_UPLOAD_MAX_BYTES = dependencies.quiz_text_upload_max_bytes()
    UploadTooLargeError = dependencies.upload_too_large_error()
    _publish_quiz = dependencies.publish_quiz
    _read_bounded_upload = dependencies.read_bounded_upload
    normalize_exam_minutes = dependencies.normalize_exam_minutes
    finalize_logo_from_request = dependencies.finalize_logo_from_request
    parse_questions = dependencies.parse_questions
    dprint = dependencies.debug_print

    #cleanup_temp_logos()  # 🧹 clean abandoned logos
    file = request.files.get("file")
    quiz_title = request.form.get("quiz_title", "Generated Quiz")
    quiz_logo = request.files.get("quiz_logo")
    exam_minutes = normalize_exam_minutes(request.form.get("exam_minutes"))

    logo_filename = None  # ✅ ensure always defined
    source_file = None    # ✅ canonical quiz identifier

    if not file:
        return "No file uploaded", 400

    # ---- determine source_file (required by schema) ----
    if file.filename:
        now = int(time.time())
        source_file = f"quiz_upload_{now}_{int(time.time() * 1000)}"



    else:
        source_file = f"manual_paste_{int(time.time())}"

    # The uploaded source is needed only for this parse. Read it through the
    # workflow ceiling instead of persisting an unbounded temporary file.
    try:
        raw_text = _read_bounded_upload(file, QUIZ_TEXT_UPLOAD_MAX_BYTES, "Quiz text file").decode(
            "utf-8", errors="ignore"
        ).strip()
    except UploadTooLargeError as exc:
        return str(exc), 413

    if not raw_text:
        return "Uploaded file is empty.", 400

    # Normalize ALL newline styles (MATCH PASTE MODE)
    clean_text = (
        raw_text
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    # =========================
    # PARSE QUIZ (SAME AS PASTE MODE)
    # =========================
    quiz_data = parse_questions(clean_text)

    # Always save a parse log (success or failure)
    ts = int(time.time())
    log_filename = f"parse_log_{ts}.txt"
    with open(os.path.join(DATA_FOLDER, log_filename), "w", encoding="utf-8") as f:
        f.write("\n".join(PARSE_LOG))

    if not quiz_data:
        return render_template("quiz/parse-failed.html", log_filename=log_filename), 400

    print("UPLOAD MODE FINAL PARSE COUNT:", len(quiz_data))

    # =========================
    # PARSE DIAGNOSTICS (TEMP)
    # =========================
    for i, q in enumerate(quiz_data, 1):
        choices = q.get("choices", [])
        has_correct = any(c.get("is_correct") for c in choices)

        if not choices or not has_correct:
            dprint(f"[PARSE WARNING] Q{i} missing choices or correct answer")


    # =========================
    # HANDLE LOGO (FINAL, SINGLE SOURCE OF TRUTH)
    # =========================
    logo_filename = finalize_logo_from_request(
        app,
        ts,
        logo_file=quiz_logo,
    )

    # =========================
    # REGISTRY ID (CANONICAL)
    # =========================


    quiz_id, html_name = _publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix="quiz",
        exam_minutes=exam_minutes,
        logo_filename=logo_filename,
        source_file=source_file,
        rollback_logo_filename=logo_filename,
    )


    return redirect("/library")

def register_authoring_routes(
    blueprint: Blueprint, dependencies: QuizAuthoringDependencies
) -> None:
    """Register classic Quiz authoring and parsing routes."""
    routes = (
        ("/upload", "upload_page", upload_page, ["GET"]),
        ("/paste", "paste_page", paste_page, ["GET"]),
        ("/matching_bank_import", "matching_bank_import", matching_bank_import, ["GET", "POST"]),
        ("/create_short_quiz", "create_short_quiz_page", create_short_quiz_page, ["GET"]),
        ("/create_short_quiz", "save_short_quiz", save_short_quiz, ["POST"]),
        ("/preview_paste", "preview_paste", preview_paste, ["POST"]),
        ("/download_cleaned", "download_cleaned", download_cleaned, ["GET", "POST"]),
        ("/process_paste", "process_paste", process_paste, ["POST"]),
        ("/process", "process_file", process_file, ["POST"]),
    )
    for rule, endpoint, view_func, methods in routes:
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=_bind_dependencies(view_func, dependencies),
            methods=methods,
        )
