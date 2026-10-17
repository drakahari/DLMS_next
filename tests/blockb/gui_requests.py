"""Exercise both Review entry points in the actual isolated Qt window."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--fail-cleanup", action="store_true")
    args = parser.parse_args()
    q = QtChecks(args.profile, fail_request_cleanup=args.fail_cleanup)
    result = {"profile": args.profile}
    try:
        previous = json.loads((q.paths["root"] / "foundation-create.json").read_text())
        print("[Block B Qt] opening saved quiz", flush=True)
        q.go(urlsplit(previous["quiz_url"]).path)
        if q.js("!!document.querySelector('.quiz-recovery-resume')"):
            q.js("document.querySelector('.quiz-recovery-resume').click(); true")
        else:
            q.wait("document.querySelector('.study-mode-btn')?.disabled === false")
            q.js("document.querySelector('.study-mode-btn').click(); true")
        print("[Block B Qt] entering Study mark", flush=True)
        q.wait("document.getElementById('studyAnkiBtn')?.style.display !== 'none'", 15)
        q.js("document.getElementById('studyAnkiBtn').click(); true")
        q.wait("/saved in DLMS|cleanup failed/.test(document.getElementById('reviewMarkStatus')?.innerText || '')", 20)
        result["quiz_mark_message"] = q.js("document.getElementById('reviewMarkStatus').innerText")
        result["quiz_mark_screenshot"] = str(q.screenshot("blockb-review-mark.png"))
        print("[Block B Qt] opening marked questions", flush=True)
        q.go("/marked-questions")
        q.wait("!!document.querySelector('[data-mark-id]')", 15)
        q.js("document.querySelector('[data-mark-id]').click(); true")
        q.wait("!document.getElementById('practiceMarks').disabled", 15)
        q.js("document.getElementById('practiceMarks').click(); true")
        q.wait("/Focused quiz ready|cleanup failed/.test(document.getElementById('markActionStatus')?.innerText || '')", 30)
        result["practice_message"] = q.js("document.getElementById('markActionStatus').innerText")
        result["practice_link"] = q.js("document.querySelector('#markPracticeResult a')?.getAttribute('href')")
        result["practice_screenshot"] = str(q.screenshot("blockb-review-practice.png"))
        with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
            result["mark_rows"] = conn.execute("SELECT count(*) FROM review_marks WHERE marked=1").fetchone()[0]
            result["actions"] = conn.execute("SELECT state,count(*) FROM review_mark_actions GROUP BY state ORDER BY state").fetchall()
        result["remaining_desktop_records"] = len(list((q.paths["root"] / "pending-requests").glob("*.json")))
        expected_records = 2 if args.fail_cleanup else 0
        result["status"] = "pass" if (result["mark_rows"] >= 1
            and (result["practice_link"] or args.fail_cleanup)
            and result["remaining_desktop_records"] == expected_records) else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "blockb-review-requests.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
