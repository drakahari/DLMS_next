"""Interrupt one synthetic Study mistakes publication and retry its same request."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback

from tests.gate1.qt_checks import QtChecks


def count(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT count(*) FROM quizzes WHERE title='Gate 1 Interrupted Batch'").fetchone()[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("create", "reopen"), required=True)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    result = {"phase": args.phase}
    try:
        quiz_id = json.loads((q.paths["root"] / "foundation-create.json").read_text())["quiz_id"]
        q.go(f"/quiz-composer/study-mistakes?quizzes={quiz_id}")
        db = q.paths["backend"] / "results.db"
        if args.phase == "create":
            q.js("document.getElementById('startMistakePass').click(); true")
            q.wait("!document.getElementById('createMistakeMix').disabled")
            q.window.interceptor.blocked_internal_paths.add("/api/quiz-composer/study-mistakes/create")
            q.js("document.getElementById('mistakeTitle').value='Gate 1 Interrupted Batch'; document.getElementById('mistakeCount').value='1'; document.getElementById('createMistakeMix').click(); true")
            q.wait("!document.getElementById('retryMistakeMix').hidden", 15)
            result["retained_request"] = bool(q.js("localStorage.getItem('dlms-study-mistakes-request')"))
            result["saved_before"] = count(db)
            result["screenshot"] = str(q.screenshot("publication-interrupted.png"))
            result["status"] = "pass" if result["retained_request"] and result["saved_before"] == 0 else "fail"
        else:
            result["retained_request_after_restart"] = bool(q.js("localStorage.getItem('dlms-study-mistakes-request')"))
            result["retry_visible"] = q.js("!document.getElementById('retryMistakeMix').hidden")
            if result["retry_visible"]:
                q.js("document.getElementById('retryMistakeMix').click(); true")
                q.wait("!document.getElementById('openMistakeMix').hidden", 20)
            result["saved_after"] = count(db)
            result["pass_after"] = q.js("document.getElementById('mistakePassSummary').innerText")
            result["screenshot"] = str(q.screenshot("publication-recovered.png"))
            result["status"] = "pass" if result["retained_request_after_restart"] and result["saved_after"] == 1 else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / f"publication-{args.phase}.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
