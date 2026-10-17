"""Actual Qt Review practice accepted-before-commit crash and exact-ID retry."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def facts(q):
    with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
        return {"actions": conn.execute("SELECT request_id,state,quiz_id FROM review_mark_actions WHERE quiz_id IS NOT NULL ORDER BY request_id").fetchall(),
                "quizzes": conn.execute("SELECT id FROM quizzes WHERE generation_kind='marked_practice' ORDER BY id").fetchall()}


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--profile", required=True)
    p.add_argument("--phase", choices=("accepted", "reopen"), required=True)
    args = p.parse_args()
    q = QtChecks(args.profile, abort_request="accepted" if args.phase == "accepted" else None)
    result = {"profile": args.profile, "phase": args.phase}
    try:
        q.go("/marked-questions")
        q.wait("!!document.querySelector('[data-mark-id]')", 15)
        if args.phase == "accepted":
            q.js("document.querySelector('[data-mark-id]').click(); true")
            q.wait("!document.getElementById('practiceMarks').disabled", 15)
            q.js("document.getElementById('practiceMarks').click(); true")
            deadline = time.monotonic() + 10
            while q.window.backend.poll() is None and time.monotonic() < deadline: q.delay(.1)
            result["backend_exited"] = q.window.backend.poll() is not None
            result["pending_files"] = len(list((q.paths["root"] / "pending-requests").glob("*.json")))
            result["facts"] = facts(q)
            result["status"] = "pass" if result["backend_exited"] and result["pending_files"] == 1 and not result["facts"]["quizzes"] else "fail"
        else:
            q.wait("!document.getElementById('retryMarkAction').hidden", 15)
            result["before"] = facts(q)
            q.js("document.getElementById('retryMarkAction').click(); true")
            q.wait("document.getElementById('markActionStatus')?.innerText.includes('Focused quiz ready')", 25)
            result["message"] = q.js("document.getElementById('markActionStatus').innerText")
            result["link"] = q.js("document.querySelector('#markPracticeResult a')?.getAttribute('href')")
            q.js("document.getElementById('markActionStatus').scrollIntoView({block:'center'}); true")
            result["screenshot"] = str(q.screenshot("blockb-review-generate-recovered.png"))
            result["facts"] = facts(q)
            result["pending_files"] = len(list((q.paths["root"] / "pending-requests").glob("*.json")))
            result["status"] = "pass" if (len(result["facts"]["quizzes"]) == 1
                and len(result["facts"]["actions"]) == 1 and result["link"]
                and result["pending_files"] == 0) else "fail"
    except Exception as exc:
        result["status"] = "error"; result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / f"blockb-review-generate-{args.phase}.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
