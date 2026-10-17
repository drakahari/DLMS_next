"""Two real Qt Without repeats batches, completion, and Random isolation."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    args = p.parse_args()
    q = QtChecks(args.profile)
    db = q.paths["backend"] / "results.db"
    out = {"profile": args.profile}
    try:
        prior = json.loads((q.paths["root"] / "foundation-create.json").read_text())
        with sqlite3.connect(db) as conn:
            existing_count = conn.execute("SELECT count(*) FROM study_responses WHERE kind='response'").fetchone()[0]
        if existing_count == 1:
            q.go(prior["quiz_url"].removeprefix(f"http://127.0.0.1:{q.window.port}"))
            q.wait("!!document.querySelector('.quiz-recovery-resume')")
            q.js("document.querySelector('.quiz-recovery-resume').click(); true")
            q.wait("document.body.innerText.includes('Which shape has three sides?')")
            q.js("document.querySelector('button.choice')?.click(); true")
            q.wait("!!document.getElementById('nextBtn') && !document.getElementById('nextBtn').disabled")
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                with sqlite3.connect(db) as conn:
                    if conn.execute("SELECT count(*) FROM study_responses WHERE kind='response'").fetchone()[0] == 2:
                        break
                q.delay(.12)
        with sqlite3.connect(db) as conn:
            wrong = conn.execute("SELECT question_id,was_correct,payload_json FROM study_responses WHERE kind='response' ORDER BY rowid").fetchall()
        if len(wrong) != 2 or wrong[0][0] == wrong[1][0] or any(row[1] for row in wrong):
            raise AssertionError(f"Expected two distinct saved wrong responses: {wrong}")
        out["wrong_responses"] = wrong
        q.go(f"/quiz-composer/study-mistakes?quizzes={prior['quiz_id']}")
        q.wait("!document.getElementById('startMistakePass').disabled")
        out["eligible"] = q.js("document.getElementById('mistakeCounts').innerText")
        q.js("document.getElementById('startMistakePass').click(); true")
        q.wait("!document.getElementById('createMistakeMix').disabled")
        for index in (1, 2):
            title = f"Completion Mistakes {index}"
            q.js("(()=>{let t=document.getElementById('mistakeTitle');t.value=" + json.dumps(title) +
                 ";document.getElementById('mistakeCount').value='1';document.getElementById('createMistakeMix').click();return true})()")
            q.wait("!document.getElementById('openMistakeMix').hidden && document.getElementById('mistakeStatus').innerText.includes(" + json.dumps(title) + ")", 25)
            with sqlite3.connect(db) as conn:
                rows = conn.execute("SELECT question_id,used_by FROM study_mistake_members WHERE used_by IS NOT NULL ORDER BY position").fetchall()
            out[f"used_after_{index}"] = rows
            out[f"summary_{index}"] = q.js("document.getElementById('mistakePassSummary').innerText")
            if index == 1:
                q.js("document.getElementById('nextMistakeMix').click(); true")
                q.wait("!document.getElementById('createMistakeMix').disabled")
        if len(out["used_after_2"]) != 2 or len({r[0] for r in out["used_after_2"]}) != 2:
            raise AssertionError("Without repeats batches overlapped")
        if len({r[1] for r in out["used_after_2"]}) != 2:
            raise AssertionError("Batch operation IDs were not distinct")
        q.wait("!document.getElementById('mistakePassComplete').hidden")
        out["pass_complete"] = q.js("document.getElementById('mistakePassComplete').innerText")
        q.js("(()=>{let m=document.getElementById('mistakeMode');m.value='random';m.dispatchEvent(new Event('change'));document.getElementById('nextMistakeMix').click();return true})()")
        q.wait("!document.getElementById('createMistakeMix').disabled")
        q.js("(()=>{document.getElementById('mistakeTitle').value='Completion Random';document.getElementById('mistakeCount').value='1';document.getElementById('createMistakeMix').click();return true})()")
        q.wait("!document.getElementById('openMistakeMix').hidden && document.getElementById('mistakeStatus').innerText.includes('Completion Random')", 25)
        with sqlite3.connect(db) as conn:
            out["members_after_random"] = conn.execute("SELECT question_id,used_by FROM study_mistake_members WHERE used_by IS NOT NULL ORDER BY position").fetchall()
            out["actions"] = conn.execute("SELECT request_id,pass_id,quiz_id,state FROM study_mistake_actions ORDER BY rowid").fetchall()
            out["titles"] = conn.execute("SELECT title FROM quizzes WHERE title LIKE 'Completion %' ORDER BY title").fetchall()
        out["pass"] = (out["members_after_random"] == out["used_after_2"] and
                       len(out["actions"]) == 3 and len(out["titles"]) == 3)
        out["screenshot"] = str(q.screenshot("completion-mistakes-disjoint.png", width=1000, height=800))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "completion-mistakes-disjoint.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
