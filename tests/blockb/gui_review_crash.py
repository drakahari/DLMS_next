"""Qt Review mark acceptance/commit crash with immutable-ID recovery."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import traceback
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def facts(q):
    with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
        return {"marks": conn.execute("SELECT id,question_uid,question_revision,marked FROM review_marks ORDER BY id").fetchall(),
                "actions": conn.execute("SELECT request_id,state,input_hash FROM review_mark_actions ORDER BY request_id").fetchall()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("accepted", "committed", "reopen"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, abort_request=args.phase if args.phase != "reopen" else None)
    result = {"profile": args.profile, "phase": args.phase}
    try:
        previous = json.loads((q.paths["root"] / "foundation-create.json").read_text())
        q.go(urlsplit(previous["quiz_url"]).path)
        if q.js("!!document.querySelector('.quiz-recovery-resume')"):
            q.js("document.querySelector('.quiz-recovery-resume').click(); true")
        else:
            q.wait("document.querySelector('.study-mode-btn')?.disabled === false")
            q.js("document.querySelector('.study-mode-btn').click(); true")
        q.wait("document.getElementById('studyAnkiBtn')?.style.display !== 'none'", 15)
        result["before"] = facts(q)
        if args.phase == "reopen":
            q.wait("document.getElementById('reviewMarkStatus')?.innerText.includes('awaiting confirmation')", 15)
        q.js("document.getElementById('studyAnkiBtn').click(); true")
        if args.phase == "reopen":
            q.wait("document.getElementById('reviewMarkStatus')?.innerText.includes('saved in DLMS')", 20)
            result["message"] = q.js("document.getElementById('reviewMarkStatus').innerText")
            q.js("document.getElementById('reviewMarkStatus').scrollIntoView({block:'center'}); true")
            result["screenshot"] = str(q.screenshot("blockb-review-recovered.png"))
            result["after"] = facts(q)
            result["pending_files"] = len(list((q.paths["root"] / "pending-requests").glob("*.json")))
            result["status"] = "pass" if len(result["after"]["marks"]) == 1 and len(result["after"]["actions"]) == 1 and result["pending_files"] == 0 else "fail"
        else:
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
        (q.paths["root"] / f"blockb-review-{args.phase}.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
