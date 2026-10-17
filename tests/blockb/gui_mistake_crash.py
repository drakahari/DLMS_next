"""Deterministic accepted/committed Study mistakes crashes and Qt retry."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def facts(q):
    with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
        return {"actions": conn.execute("SELECT request_id,state,quiz_id FROM study_mistake_actions ORDER BY request_id").fetchall(),
                "quizzes": conn.execute("SELECT id,title FROM quizzes WHERE title='Block B Crash Batch'").fetchall(),
                "members": conn.execute("SELECT pass_id,question_id,used_by,reserved_by FROM study_mistake_members ORDER BY question_id").fetchall()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("accepted", "committed", "reopen"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, abort_request=args.phase if args.phase != "reopen" else None)
    result = {"profile": args.profile, "phase": args.phase}
    try:
        quiz_id = json.loads((q.paths["root"] / "foundation-create.json").read_text())["quiz_id"]
        q.go(f"/quiz-composer/study-mistakes?quizzes={quiz_id}")
        q.wait("document.getElementById('startMistakePass') && !document.getElementById('startMistakePass').disabled || !document.getElementById('retryMistakeMix').hidden", 20)
        if args.phase == "reopen":
            q.wait("!document.getElementById('retryMistakeMix').hidden", 15)
            result["pending_message"] = q.js("document.getElementById('mistakeStatus').innerText")
            result["before"] = facts(q)
            q.js("document.getElementById('retryMistakeMix').click(); true")
            q.wait("!document.getElementById('openMistakeMix').hidden", 25)
            result["saved_message"] = q.js("document.getElementById('mistakeStatus').innerText")
            q.js("document.getElementById('mistakeStatus').scrollIntoView({block:'center'}); true")
            result["screenshot"] = str(q.screenshot("blockb-mistake-recovered.png"))
            result["after"] = facts(q)
            result["pending_files"] = len(list((q.paths["root"] / "pending-requests").glob("*.json")))
            result["status"] = "pass" if ("conflict" not in result["pending_message"].lower()
                and len(result["after"]["quizzes"]) == 1 and result["pending_files"] == 0) else "fail"
        else:
            q.js("document.getElementById('startMistakePass').click(); true")
            q.wait("!document.getElementById('createMistakeMix').disabled", 20)
            q.js("document.getElementById('mistakeTitle').value='Block B Crash Batch'; document.getElementById('mistakeCount').value='1'; document.getElementById('createMistakeMix').click(); true")
            q.wait("document.getElementById('retryMistakeMix') && !document.getElementById('retryMistakeMix').hidden", 10)
            deadline = time.monotonic() + 10
            while q.window.backend.poll() is None and time.monotonic() < deadline:
                q.delay(0.1)
            result["backend_exited"] = q.window.backend.poll() is not None
            result["after"] = facts(q)
            result["pending_files"] = len(list((q.paths["root"] / "pending-requests").glob("*.json")))
            result["status"] = "pass" if result["backend_exited"] and result["pending_files"] == 1 else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / f"blockb-mistake-{args.phase}.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
