"""Actual Qt repeated choice text and two correct answers across restart."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--reopen", action="store_true")
    parser.add_argument("--grade", action="store_true")
    a = parser.parse_args()
    q = QtChecks(a.profile)
    db = q.paths["backend"] / "results.db"
    out = {"profile": a.profile, "reopen": a.reopen}
    try:
        if not a.reopen and not a.grade:
            q.go("/create_short_quiz?count=1")
            q.js("""(()=>{const f=document.querySelector('form');f.elements.quiz_title.value='Completion Multi Answer';
              const b=document.querySelector('.question-block');b.querySelector('.question-text').value='Select both repeated descriptions.';
              const rows=[...b.querySelectorAll('.choices-list li')];
              [['A','Shared description',true],['B','Shared description',true],['C','Different description',false]].forEach((v,i)=>{
                rows[i].querySelector('.choice-text').value=v[1];rows[i].querySelector('.choice-correct').checked=v[2];
              });return true})()""")
            q.click_css('button[type=submit]')
            q.wait("location.pathname.startsWith('/edit_quiz/')", 25)
        with sqlite3.connect(db) as conn:
            quiz = conn.execute("SELECT id FROM quizzes WHERE title='Completion Multi Answer'").fetchone()
            question = conn.execute("SELECT id,question_text FROM questions WHERE quiz_id=?", quiz).fetchone()
            choices = conn.execute("SELECT id,choice_order,label,text,is_correct FROM choices WHERE question_id=? ORDER BY choice_order", (question[0],)).fetchall()
        out.update(quiz_id=quiz[0], question=question, choices=choices)
        out["pass"] = (question[1] == "Select both repeated descriptions."
                       and [row[1:] for row in choices] == [
                           (0, "A", "Shared description", 1),
                           (1, "B", "Shared description", 1),
                           (2, "C", "Different description", 0)])
        q.go(f"/edit_quiz/{quiz[0]}")
        out["ui_values"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('.edit-quiz-choice-list li')].map(r=>({label:r.querySelector('[name^=label_]')?.value,text:r.querySelector('[name^=choice_]')?.value,correct:r.querySelector('[name^=correct_]')?.checked})))"))
        out["pass"] = out["pass"] and [x["text"] for x in out["ui_values"]] == ["Shared description", "Shared description", "Different description"]
        if a.grade:
            registry = json.loads((q.paths["backend"] / "config/quizzes.json").read_text())
            entry = next(item for item in registry if item["id"] == quiz[0])
            q.go("/quizzes/" + entry["html"])
            q.wait("document.querySelector('.study-mode-btn')?.disabled === false")
            q.js("document.querySelector('.study-mode-btn').click(); true")
            q.wait("document.querySelectorAll('button.choice').length === 3")
            q.js("document.querySelectorAll('button.choice')[0].click(); true")
            q.wait("document.querySelectorAll('button.choice')[0].getAttribute('aria-pressed') === 'true'")
            q.js("document.querySelectorAll('button.choice')[1].click(); true")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                with sqlite3.connect(db) as conn:
                    responses = conn.execute("SELECT event_id,was_correct,payload_json FROM study_responses WHERE kind='response' ORDER BY sequence").fetchall()
                if any(row[1] == 1 for row in responses):
                    break
                q.delay(.12)
            else:
                raise TimeoutError("Correct multi-answer Study response was not committed")
            out["responses"] = responses
            out["pass"] = out["pass"] and any(row[1] == 1 and json.loads(row[2])["selected"] == ["A", "B"] for row in responses)
        image_name = "completion-multi-answer-graded.png" if a.grade else ("completion-multi-answer-reopen.png" if a.reopen else "completion-multi-answer.png")
        out["screenshot"] = str(q.screenshot(image_name, width=1000, height=800))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        output_name = "completion-multi-answer-graded.json" if a.grade else ("completion-multi-answer-reopen.json" if a.reopen else "completion-multi-answer.json")
        (q.paths["root"] / output_name).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
