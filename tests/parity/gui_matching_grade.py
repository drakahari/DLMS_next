"""Grade a synthetic matching quiz through Qt's dropdown interaction."""
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
    p.add_argument("--reopen", action="store_true")
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {}
    db = q.paths["backend"] / "results.db"
    try:
        with sqlite3.connect(db) as conn:
            quiz = conn.execute("SELECT id FROM quizzes WHERE title='Parity Matching Synthetic Quiz'").fetchone()
            question = conn.execute("SELECT id FROM questions WHERE quiz_id=?",quiz).fetchone()
            before = conn.execute("SELECT event_id,was_correct,payload_json FROM study_responses WHERE question_id=? AND kind='response' ORDER BY rowid",question).fetchall()
            source_rows = conn.execute("SELECT left_text,right_text,pair_order FROM matching_pairs WHERE question_id=? ORDER BY pair_order",question).fetchall()
        entry = next(x for x in json.loads((q.paths["backend"] / "config/quizzes.json").read_text()) if x["id"] == quiz[0])
        if not a.reopen:
            q.go("/quizzes/"+entry["html"])
            if q.js("!!document.querySelector('.quiz-recovery-start-over')"):
                q.js("window.confirm=()=>true;document.querySelector('.quiz-recovery-start-over').click();true")
                q.wait("document.querySelector('.quiz-recovery-panel')?.hidden === true")
            q.wait("document.querySelector('.study-mode-btn')?.disabled === false")
            q.js("document.querySelector('.study-mode-btn').click();true")
            q.wait("document.querySelector('.matching-mode-button')!==null")
            q.click_css(".matching-mode-button:nth-child(2)")
            q.wait("document.querySelectorAll('.matching-select').length === 2")
            q.js("(()=>{let e=document.querySelectorAll('.matching-select')[0];e.value='0';e.dispatchEvent(new Event('change',{bubbles:true}));return true})()")
            q.js("(()=>{let e=document.querySelectorAll('.matching-select')[1];e.value='1';e.dispatchEvent(new Event('change',{bubbles:true}));return true})()")
            q.wait("document.querySelectorAll('.matching-correct').length === 2",20)
            deadline = time.monotonic()+20
            while time.monotonic()<deadline:
                with sqlite3.connect(db) as conn:
                    saved=conn.execute("SELECT event_id,was_correct,payload_json FROM study_responses WHERE question_id=? AND kind='response' ORDER BY rowid",question).fetchall()
                if len(saved) == len(before)+2 and saved[-1][1] == 1:
                    break
                q.delay(.12)
        else:
            prior=json.loads((q.paths["root"] / "parity-matching-grade.json").read_text())
            with sqlite3.connect(db) as conn:
                saved=conn.execute("SELECT event_id,was_correct,payload_json FROM study_responses WHERE question_id=? AND kind='response' ORDER BY rowid",question).fetchall()
            out["records_match_prior"]=json.loads(json.dumps(saved))==prior["saved_responses"]
            q.go("/quizzes/"+entry["html"])
        out["saved_responses"] = saved
        out["before_count"] = len(before)
        out["correct_rows"] = q.js("document.querySelectorAll('.matching-correct').length") if not a.reopen else None
        new=saved[len(before):] if not a.reopen else saved[-2:]
        out["new_event_ids_unique"] = len({r[0] for r in new}) == len(new) and (
            a.reopen or not {r[0] for r in new}.intersection({r[0] for r in before}))
        out["new_payloads_valid"] = (len(new)==2 and
            [json.loads(r[2]).get("selected") for r in new] == [{"0":0},{"0":0,"1":1}] and
            [r[1] for r in new] == [None,1] and
            all(json.loads(r[2]).get("eventId")==r[0] for r in new))
        with sqlite3.connect(db) as conn:
            out["source_rows_unchanged"] = conn.execute("SELECT left_text,right_text,pair_order FROM matching_pairs WHERE question_id=? ORDER BY pair_order",question).fetchall() == source_rows
        out["screenshot"] = str(q.screenshot("parity-matching-reopen.png" if a.reopen else "parity-matching-correct.png"))
        out["pass"] = bool(out["new_event_ids_unique"] and out["new_payloads_valid"]
                           and out["source_rows_unchanged"] and
                           (out.get("records_match_prior") if a.reopen else
                            out["correct_rows"] == 2 and len(saved)==len(before)+2))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / ("parity-matching-grade-reopen.json" if a.reopen else "parity-matching-grade.json")).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
