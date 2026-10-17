"""Disposable real-Qt clear-Exam transaction, browser checkpoint and restart."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def rows(db):
    with sqlite3.connect(db) as conn:
        return {name: conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                for name in ("quizzes", "questions", "choices", "attempts", "attempt_answers",
                             "missed_questions", "study_sessions", "study_responses", "learning_events",
                             "certifications", "certification_training")}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--phase", choices=("run", "reopen"), required=True)
    a = p.parse_args()
    q = QtChecks(a.profile, automated=True)
    db = q.paths["backend"] / "results.db"
    out = {"profile": a.profile, "phase": a.phase}
    try:
        if a.phase == "run":
            before = rows(db)
            out["before"] = before
            if not before["attempts"] or not before["study_responses"]:
                raise AssertionError("Maintenance fixture needs Exam and Study facts")
            if not q.window.begin_maintenance("exam", confirmed=True):
                raise AssertionError("Qt maintenance action refused")
            q.window.grab().save(str(q.paths["root"] / "completion-exam-maintenance-progress.png"))
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                q.delay(.15)
                marker_path = q.paths["root"].parent.parent / "maintenance" / a.profile / "active.json"
                if marker_path.exists():
                    marker = json.loads(marker_path.read_text())
                    if marker["phase"] == "browser_check_pending":
                        break
            else:
                raise TimeoutError("Browser cleanup did not reach separate-process checkpoint")
            out["marker"] = marker
            after = rows(db)
            out["after"] = after
            out["pass"] = (not after["attempts"] and not after["attempt_answers"]
                           and not after["missed_questions"]
                           and all(after[name] == before[name] for name in before
                                   if name not in {"attempts", "attempt_answers", "missed_questions"}))
            q.paths["root"].joinpath("completion-exam-before.json").write_text(json.dumps(before, indent=2) + "\n")
        else:
            marker_path = q.paths["root"].parent.parent / "maintenance" / a.profile / "active.json"
            out["normal_page"] = q.js("location.pathname")
            out["marker_absent"] = not marker_path.exists()
            out["rows"] = rows(db)
            out["history_text"] = q.js("document.body.innerText.slice(0,500)")
            out["study_recovery_keys"] = json.loads(q.js("JSON.stringify(Object.keys(localStorage).filter(k=>k.startsWith('dlms.quiz-progress.v1:')))"))
            out["pass"] = (out["normal_page"] == "/" and out["marker_absent"]
                           and not out["rows"]["attempts"] and bool(out["rows"]["study_responses"]))
            q.screenshot("completion-exam-maintenance-reopen.png", width=970, height=720)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / f"completion-exam-maintenance-{a.phase}.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
