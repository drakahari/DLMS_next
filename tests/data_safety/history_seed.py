"""Save synthetic Study and Exam facts against a published legacy-image quiz."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    root = q.paths["root"]
    backend = q.paths["backend"]
    db = backend / "results.db"
    seed = json.loads((root / "closure-source-legacy-seed.json").read_text())
    registry = json.loads((backend / "config/quizzes.json").read_text())
    quiz = next(item for item in registry if item["id"] == seed["quiz_id"])
    out = {"profile": args.profile, "quiz_id": quiz["id"], "quiz_html": quiz["html"]}
    try:
        q.go("/quizzes/" + quiz["html"])
        q.js("document.querySelector('.study-mode-btn').click(); true")
        q.wait("document.querySelector('button.choice') !== null")
        q.js("[...document.querySelectorAll('button.choice')].find(b=>b.innerText.includes('Four')).click(); true")
        q.wait("studyLearningEventSaves.size === 0", 20)
        with sqlite3.connect(db) as conn:
            study = conn.execute("SELECT event_id,session_id,sequence,payload_json FROM study_responses WHERE kind='response' ORDER BY saved_at,event_id").fetchall()
        assert len(study) == 1
        q.go("/quizzes/" + quiz["html"])
        if q.js("!!document.querySelector('.quiz-recovery-start-over')"):
            q.js("window.confirm=()=>true; document.querySelector('.quiz-recovery-start-over').click(); true")
            q.wait("document.querySelector('.quiz-recovery-panel')?.hidden === true")
        q.js("document.querySelector('.exam-mode-btn').click(); true")
        q.wait("document.querySelector('button.choice') !== null")
        q.js("[...document.querySelectorAll('button.choice')].find(b=>b.innerText.includes('Four')).click(); true")
        q.js("window.confirm=()=>true; document.getElementById('submitBtn').click(); true")
        q.wait("document.getElementById('result')?.innerText.includes('Score')", 20)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with sqlite3.connect(db) as conn:
                if conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1:
                    break
            q.delay(0.1)
        else:
            raise TimeoutError("Exam result was visible but no durable attempt arrived")
        with sqlite3.connect(db) as conn:
            attempts = conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()
            answer_columns = [row[1] for row in conn.execute("PRAGMA table_info(attempt_answers)")]
            answers = conn.execute("SELECT * FROM attempt_answers ORDER BY id").fetchall()
            events = conn.execute("SELECT * FROM learning_events ORDER BY id").fetchall()
            missed = conn.execute("SELECT * FROM missed_questions ORDER BY id").fetchall()
            assert len(attempts) == 1 and "response_json" not in answer_columns
            assert attempts[0][1] == quiz["id"]
            assert any(row[1] == "exam_answer" and row[4] == attempts[0][0] for row in events)
            questions = conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
            choices = conn.execute("SELECT * FROM choices ORDER BY id").fetchall()
        assert not list((root / "durable-actions").glob("*.json"))
        out.update(study=[list(row) for row in study], attempts=[list(row) for row in attempts],
                   answers=[list(row) for row in answers], events=[list(row) for row in events],
                   missed=[list(row) for row in missed], questions=[list(row) for row in questions],
                   choices=[list(row) for row in choices],
                   legacy_sha=seed["legacy_asset_sha256"],
                   published_json_sha=sha((backend / seed["data_file"]).read_bytes()),
                   screenshot=str(q.screenshot("data-safety-history-before.png", width=1030, height=760)))
        assert out["study"][0][0] and out["attempts"][0]
        out["attempt_answer_columns"] = answer_columns
        out["asset_dependency"] = "saved Study/Exam facts link to the published quiz; schema-12 attempt_answers has no response_json"
        out["pass"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (root / "data-safety-history-before.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({key: out.get(key) for key in ("profile", "pass", "error")}, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
