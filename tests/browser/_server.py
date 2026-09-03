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
    _, companion_html = dlms._publish_quiz(
        "Browser Companion",
        [_choice_question(1, "Companion question?", 0)],
        filename_prefix="browser_companion",
        exam_minutes=5,
    )

    registry = dlms.load_registry()
    for quiz in registry:
        quiz["folder"] = "Browser Regression"
    dlms.save_registry(registry)
    dlms.save_quiz_folders(["Uncategorized", "Browser Regression"])

    restore_path, _ = dlms._create_dlms_backup("browser-restore-fixture")

    metadata = {
        "critical_id": critical_id,
        "critical_html": critical_html,
        "companion_html": companion_html,
        "restore_path": restore_path,
    }
    Path(dlms.APP_DATA_DIR, "browser_fixture.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )


def main():
    seed_browser_data()
    port = int(os.environ["DLMS_BROWSER_TEST_PORT"])
    server = make_server("127.0.0.1", port, dlms.app, threaded=True)
    print(f"DLMS browser test server listening on {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
