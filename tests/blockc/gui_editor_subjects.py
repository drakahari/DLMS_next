"""Edit a synthetic quiz in Qt, then inspect neighboring existing workflows."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--reopen", action="store_true")
    args = parser.parse_args()
    q = QtChecks(args.profile)
    report = {}
    try:
        db = q.paths["backend"] / "results.db"
        with sqlite3.connect(db) as conn:
            quiz_id = conn.execute("SELECT id FROM quizzes WHERE title=? ORDER BY id LIMIT 1",
                ("Block C Edited Quiz" if args.reopen else "Gate 1 Neutral Quiz",)).fetchone()[0]
            original = conn.execute("SELECT id,label,text,is_correct,choice_order FROM choices WHERE text=? AND is_correct=1",
                ("Four edited" if args.reopen else "Four",)).fetchone()
            question = conn.execute("SELECT id,question_text FROM questions WHERE quiz_id=? ORDER BY question_number LIMIT 1", (quiz_id,)).fetchone()
        q.go(f"/edit_quiz/{quiz_id}")
        report["editor_existing_choice"] = q.js(f"document.querySelector('[name=choice_{original[0]}]')?.value")
        report["editor_screenshot"] = str(q.screenshot("blockc-editor-reopen.png" if args.reopen else "blockc-editor-before.png"))
        if not args.reopen:
            q.js(f"document.querySelector('[name=choice_{original[0]}]').value='Four edited';document.querySelector('#edit-quiz-form [name=quiz_title]').value='Block C Edited Quiz';document.querySelector('#edit-quiz-form').requestSubmit();true")
            deadline = time.monotonic() + 20
            committed = False
            while time.monotonic() < deadline:
                with sqlite3.connect(db) as conn:
                    committed = conn.execute("SELECT text FROM choices WHERE id=?", (original[0],)).fetchone()[0] == "Four edited"
                if committed:
                    break
                q.delay(0.12)
            if not committed:
                raise TimeoutError("Qt editor submission did not commit; the page and source data were retained")
        q.wait("document.querySelector('#edit-quiz-form [name=quiz_title]')?.value === 'Block C Edited Quiz'", 20)
        with sqlite3.connect(db) as conn:
            saved = conn.execute("SELECT id,label,text,is_correct,choice_order FROM choices WHERE id=?", (original[0],)).fetchone()
            question_after = conn.execute("SELECT id,question_text FROM questions WHERE id=?", (question[0],)).fetchone()
            title = conn.execute("SELECT title FROM quizzes WHERE id=?", (quiz_id,)).fetchone()[0]
        registry = json.loads((q.paths["backend"] / "config" / "quizzes.json").read_text())
        entry = next(item for item in registry if item["id"] == quiz_id)
        report["choice_before"] = original
        report["choice_after"] = saved
        report["question_unchanged"] = question_after == question
        report["title"] = title
        report["generated_html_sha256"] = hashlib.sha256((q.paths["backend"] / "quizzes" / entry["html"]).read_bytes()).hexdigest()
        q.go(f"/quizzes/{entry['html']}")
        q.js("window.__blockcRuntime=null;fetch(QUIZ_FILE).then(r=>r.json()).then(data=>window.__blockcRuntime=data);true")
        q.wait("!!window.__blockcRuntime")
        report["generated_runtime_has_edit"] = q.js("window.__blockcRuntime[0].choices.some(c=>c.text==='Four edited'&&c.label==='B'&&c.is_correct)")
        if q.js("!!document.querySelector('.quiz-recovery-start-over')"):
            q.js("window.confirm=()=>true;document.querySelector('.quiz-recovery-start-over').click();true")
            q.wait("document.querySelector('.quiz-recovery-panel')?.hidden === true")
        q.wait("document.querySelector('.study-mode-btn')?.disabled === false")
        q.js("document.querySelector('.study-mode-btn').click();true")
        q.wait("document.querySelector('button.choice') !== null")
        report["generated_page_has_edit"] = q.js("document.body.innerText.includes('Four edited')")
        q.go("/library")
        report["library_has_edit"] = q.js("document.body.innerText.includes('Block C Edited Quiz')")
        views = json.loads(q.js("JSON.stringify([...document.querySelectorAll('.library-smart-view-link')].map(a=>({label:a.innerText.trim(),href:a.getAttribute('href')})))"))
        report["smart_views"] = views
        if views:
            q.go(views[0]["href"].replace("&amp;", "&"))
            report["smart_view_active"] = q.js("!!document.querySelector('.library-smart-view-link.active[aria-current=page]')")
        report["subject_pages"] = {}
        for path in ("/it", "/medical", "/law", "/external-ai/quiz-builder", "/admin/maintenance"):
            q.go(path)
            report["subject_pages"][path] = {"title": q.js("document.title"),
                                              "visible": q.js("document.body.innerText.length > 300")}
        report["subjects_screenshot"] = str(q.screenshot("blockc-system-tools-reopen.png" if args.reopen else "blockc-system-tools.png"))
        report["pass"] = (report["editor_existing_choice"] == ("Four edited" if args.reopen else "Four")
                          and saved == (original[0], original[1], "Four edited", original[3], original[4])
                          and report["question_unchanged"] and title == "Block C Edited Quiz"
                          and report["generated_runtime_has_edit"] and report["generated_page_has_edit"] and report["library_has_edit"]
                          and report.get("smart_view_active") and
                          all(page["visible"] for page in report["subject_pages"].values()))
    finally:
        (q.paths["root"] / ("blockc-editor-subjects-reopen.json" if args.reopen else "blockc-editor-subjects.json")).write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
