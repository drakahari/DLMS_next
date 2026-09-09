"""Run an isolated, deterministic DLMS server for browser regression tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DLMS_NO_BROWSER"] = "1"

import app as dlms  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402


def _choice_question(number, question, correct_index):
    choices = [
        {"label": "A", "text": f"Answer A{number}", "is_correct": correct_index == 0},
        {"label": "B", "text": f"Answer B{number}", "is_correct": correct_index == 1},
    ]
    return {
        "number": number,
        "type": "choice",
        "question": question,
        "choices": choices,
        "correct": [choices[correct_index]["label"]],
        "explanation": f"Explanation for browser question {number}.",
        "concepts": [f"browser-concept-{number}"],
    }


def seed_browser_data():
    critical_id, critical_html = dlms._publish_quiz(
        "Browser Critical Workflow",
        [
            _choice_question(1, "Browser question one?", 0),
            _choice_question(2, "Browser question two?", 1),
        ],
        filename_prefix="browser_critical",
        exam_minutes=5,
    )
    companion_id, companion_html = dlms._publish_quiz(
        "Browser Companion",
        [_choice_question(1, "Companion question?", 0)],
        filename_prefix="browser_companion",
        exam_minutes=5,
    )

    recovery_json = "browser_recovery_mixed.json"
    recovery_html = "browser_recovery_mixed.html"
    recovery_quiz = [
        _choice_question(1, "Recovery single-choice question?", 0),
        {
            "number": 2,
            "type": "choice",
            "question": "Recovery multi-answer question?",
            "choices": [
                {"label": "A", "text": "First", "is_correct": True},
                {"label": "B", "text": "Second", "is_correct": False},
                {"label": "C", "text": "Third", "is_correct": True},
            ],
            "correct": ["A", "C"],
            "explanation": "Select the first and third answers.",
            "concepts": ["browser-recovery-multi"],
        },
        {
            "number": 3,
            "type": "matching",
            "question": "Recovery matching question?",
            "round_size": 2,
            "direction": "random",
            "pairs": [
                {"left": "Alpha", "right": "One"},
                {"left": "Beta", "right": "Two"},
                {"left": "Gamma", "right": "Three"},
            ],
            "concepts": ["browser-recovery-matching"],
        },
        {
            "number": 4,
            "type": "hotspot",
            "question": "Recovery hotspot question?",
            "image_url": "/static/favicon.ico",
            "image_alt": "Recovery test target",
            "target": {"type": "circle", "x": 0.5, "y": 0.5, "radius": 0.2},
            "target_label": "Center",
            "concepts": ["browser-recovery-hotspot"],
        },
    ]
    dlms._atomic_write_json(
        str(Path(dlms.DATA_FOLDER, recovery_json)),
        recovery_quiz,
        expected_type=list,
    )
    dlms.build_quiz_html(
        recovery_html,
        recovery_json,
        str(Path(dlms.QUIZ_FOLDER, recovery_html)),
        "DLMS",
        "Browser Recovery Mixed Types",
        None,
        "browser-recovery-mixed",
        5,
    )

    connection = dlms.get_db()
    question_rows = connection.execute(
        "SELECT id, question_number, question_text FROM questions WHERE quiz_id = ? ORDER BY question_number",
        (critical_id,),
    ).fetchall()
    connection.execute(
        """
        INSERT INTO attempts (
            id, quiz_id, user_name, started_at, completed_at,
            score, total, percent, time_remaining, mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "browser-anki-missed-attempt", critical_id, "Browser Tester",
            "2026-09-04T10:00:00", "2026-09-04T10:05:00",
            0, len(question_rows), 0, 0, "Exam",
        ),
    )
    for question in question_rows:
        connection.execute(
            """
            INSERT INTO missed_questions (
                attempt_id, question_id, correct_letters, question_text,
                choices_text, selected_letters, selected_text, correct_text,
                attempt_question_number, question_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "browser-anki-missed-attempt", question["id"], "A",
                question["question_text"], "A. Correct\nB. Incorrect",
                "B", "B. Incorrect", "A. Correct", question["question_number"], "choice",
            ),
        )
    connection.commit()
    connection.close()

    law_cases = [
        (
            "browser-law-negligence", "Palsgraf Browser Review", "Torts",
            "Q: What limits negligence duty?\nA: Foreseeability.\n\n"
            "Q: What defines proximate cause?\nA: Scope of liability.",
        ),
        (
            "browser-law-contracts", "Hadley Browser Review", "Contracts",
            "Q: What limits consequential damages?\nA: Foreseeability at formation.",
        ),
    ]
    registry = dlms.load_law_registry()
    for case_id, title, course, flashcards in law_cases:
        case_file = f"{case_id}.json"
        case_payload = {
            "id": case_id,
            "type": "law_case_review",
            "title": title,
            "course": course,
            "sections": {"rule_flashcards": flashcards},
        }
        dlms._atomic_write_json(
            str(Path(dlms.LAW_CASES_FOLDER, case_file)),
            case_payload,
            expected_type=dict,
        )
        registry["cases"].append({
            "id": case_id,
            "title": title,
            "course": course,
            "file": case_file,
            "hidden": False,
        })
    dlms.save_law_registry(registry)

    registry = dlms.load_registry()
    for quiz in registry:
        quiz["folder"] = "Browser Regression"
    dlms.save_registry(registry)
    dlms.save_quiz_folders(["Uncategorized", "Browser Regression"])

    restore_path, _ = dlms._create_dlms_backup("browser-restore-fixture")

    metadata = {
        "critical_id": critical_id,
        "critical_html": critical_html,
        "companion_id": companion_id,
        "companion_html": companion_html,
        "recovery_html": recovery_html,
        "recovery_json": recovery_json,
        "restore_path": restore_path,
    }
    Path(dlms.APP_DATA_DIR, "browser_fixture.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )


def main():
    fixture_path = Path(dlms.APP_DATA_DIR, "browser_fixture.json")
    if os.environ.get("DLMS_BROWSER_REUSE_DATA") != "1" or not fixture_path.is_file():
        seed_browser_data()
    bind_host = os.environ.get("DLMS_BROWSER_TEST_BIND_HOST", "127.0.0.1")
    test_grace = os.environ.get("DLMS_BROWSER_PRESENCE_TEST_GRACE_SECONDS")
    if test_grace:
        cfg = dlms.load_portal_config()
        cfg["automatic_browser_shutdown_enabled"] = True
        dlms._write_settings_portal_config(cfg)
        dlms.browser_presence_manager.configure_timing(
            grace_seconds=float(test_grace),
            token_ttl_seconds=float(
                os.environ.get("DLMS_BROWSER_PRESENCE_TEST_TOKEN_TTL_SECONDS", "0.8")
            ),
            poll_seconds=float(
                os.environ.get("DLMS_BROWSER_PRESENCE_TEST_POLL_SECONDS", "0.05")
            ),
            suspend_gap_seconds=60.0,
        )
    dlms.start_browser_presence_monitor(bind_host)
    port = int(os.environ["DLMS_BROWSER_TEST_PORT"])
    server = make_server(bind_host, port, dlms.app, threaded=True)
    print(f"DLMS browser test server listening on {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
