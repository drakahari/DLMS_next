"""Seed one factual Review mark through authenticated Qt requests for reset fixtures."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile}
    try:
        foundation = json.loads((q.paths["root"] / "foundation-create.json").read_text())
        quiz_id = foundation["quiz_id"]
        q.go(foundation["quiz_url"].removeprefix(f"http://127.0.0.1:{q.window.port}"))
        q.wait("!!quizContentFingerprint", 15)
        payload = {"quiz_id": quiz_id, "fingerprint": q.js("quizContentFingerprint")}
        q.js("""(async()=>{const r=await fetch('/api/review-marks/context',{method:'POST',
          credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify("""
          + json.dumps(payload) + """)});window.__reviewContext={status:r.status,data:await r.json()}})()""")
        q.wait("!!window.__reviewContext", 15)
        context = json.loads(q.js("JSON.stringify(window.__reviewContext)"))
        out["context"] = context
        if context["status"] != 200:
            raise AssertionError("Review context refused synthetic source")
        q.js("loadReviewMarks(); true")
        q.wait("!!reviewMarkContext", 15)
        q.js("saveReviewMarkIndexes([0], true); true")
        q.wait("document.getElementById('reviewMarkStatus')?.innerText.includes('Review marks saved')", 15)
        out["save_status"] = q.js("document.getElementById('reviewMarkStatus').innerText")
        with sqlite3.connect(q.paths["backend"] / "results.db") as c:
            out["marks"] = c.execute("SELECT id,question_uid,question_revision,quiz_id,marked FROM review_marks").fetchall()
            out["actions"] = c.execute("SELECT request_id,state FROM review_mark_actions").fetchall()
        q.go("/marked-questions")
        out["page_visible"] = q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        out["screenshot"] = str(q.screenshot("completion-seeded-review.png", width=970, height=720))
        out["pass"] = (len(out["marks"]) == 1 and out["marks"][0][-1] == 1 and
                       len(out["actions"]) == 1 and out["actions"][0][1] == "done" and
                       out["page_visible"])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "completion-seed-review.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
