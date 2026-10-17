"""Qt matching authoring/review and mixed-source composition, with exact rows."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def wait_db(q, db, statement, args=(), timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with sqlite3.connect(db) as conn:
            row = conn.execute(statement, args).fetchone()
        if row:
            return row
        q.delay(.12)
    raise TimeoutError(statement)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    db = q.paths["backend"] / "results.db"
    out = {}
    try:
        with sqlite3.connect(db) as conn:
            original = {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                        for table in ("questions", "choices", "attempts", "study_responses")}
        q.go("/external-ai/quiz-builder")
        envelope = {"schema_version":1,"content_type":"matching","title":"Parity Matching Synthetic Quiz",
                    "source":{"organization":"Neutral Group","dataset":"Synthetic terms","version":"1",
                              "url":"https://example.org/synthetic","license":"CC0"},
                    "questions":[{"question":"Match each synthetic term.","direction":"term_to_definition",
                                  "round_size":2,"pairs":[{"left":"Alpha tool","right":"First tool","category":"tools"},
                                                          {"left":"Beta tool","right":"Second tool","category":"tools"}],
                                  "explanation":"Match the synthetic terms.","concepts":["tools"]}]}
        q.js("(()=>{let f=document.getElementById('externalAiBuilderForm');f.elements.content_type.value='matching';f.elements.topic.value='Synthetic tools';f.elements.question_count.value='2';f.elements.ai_response.value="+json.dumps(json.dumps(envelope))+";f.requestSubmit(f.querySelector('button[type=submit]:not([formaction])'));return true})()")
        q.wait("location.pathname.startsWith('/external-ai/review/')", 20)
        out["review_path"] = q.js("location.pathname")
        out["review_pair_rows"] = q.js("document.querySelectorAll('[data-matching-role=pair-row]').length")
        out["review_question"] = q.js("document.querySelector('[data-pdf-role=question]')?.value")
        out["review_screenshot"] = str(q.screenshot("parity-matching-review.png"))
        q.js("(()=>{document.querySelector('[data-matching-role=review-confirmed]').click();document.getElementById('pdfReviewForm').requestSubmit();return true})()")
        quiz = wait_db(q, db, "SELECT id,title FROM quizzes WHERE title='Parity Matching Synthetic Quiz'")
        out["quiz"] = quiz
        with sqlite3.connect(db) as conn:
            question = conn.execute("SELECT id,question_text,question_type FROM questions WHERE quiz_id=?",(quiz[0],)).fetchone()
            pairs = conn.execute("SELECT left_text,right_text,pair_order FROM matching_pairs WHERE question_id=? ORDER BY pair_order",(question[0],)).fetchall()
            out["question"] = question
            out["pairs"] = pairs
            after = {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in original}
        out["old_rows_preserved"] = all(all(row in after[t] for row in original[t]) for t in original)
        registry = json.loads((q.paths["backend"] / "config" / "quizzes.json").read_text())
        entry = next(x for x in registry if x["id"] == quiz[0])
        q.go("/quizzes/"+entry["html"])
        q.wait("document.querySelector('.study-mode-btn')?.disabled === false")
        q.js("document.querySelector('.study-mode-btn').click();true")
        q.wait("document.body.innerText.includes('Alpha tool')")
        out["playable_text"] = q.js("document.body.innerText.slice(-1600)")
        out["playable_controls"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('main select, main button, .matching-question select, .matching-question button')].map(e=>({tag:e.tagName,cls:e.className,id:e.id,text:e.innerText.slice(0,60),options:e.options?[...e.options].map(o=>({value:o.value,text:o.text})):null})).slice(-35))"))
        out["playable_screenshot"] = str(q.screenshot("parity-matching-play.png"))
        out["pass"] = (out["review_pair_rows"] == 2 and out["review_question"] == "Match each synthetic term."
                       and question[1] == "Match each synthetic term." and len(pairs) == 2
                       and [(x[0],x[1]) for x in pairs] == [("Alpha tool","First tool"),("Beta tool","Second tool")]
                       and out["old_rows_preserved"] and "Alpha tool" in out["playable_text"])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "parity-matching-mixed.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
