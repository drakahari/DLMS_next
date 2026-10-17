"""Qt storage/rebuild and offline external-AI prompt/validation/publish workflow."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def facts(db: Path):
    with sqlite3.connect(db) as conn:
        return {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("quizzes", "questions", "choices", "attempts", "study_responses")}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--reopen", action="store_true")
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile, "reopen": a.reopen}
    db = q.paths["backend"] / "results.db"
    try:
        before = facts(db)
        q.go("/settings/backup?storage=1")
        out["storage_text"] = q.js("document.getElementById('storage-health')?.innerText.slice(0,1300)")
        out["storage_visible"] = "DLMS data size" in out["storage_text"] and "Available disk space" in out["storage_text"]
        out["storage_screenshot"] = str(q.screenshot("parity-storage-reopen.png" if a.reopen else "parity-storage.png"))
        if not a.reopen:
            registry = json.loads((q.paths["backend"] / "config" / "quizzes.json").read_text())
            page = q.paths["backend"] / "quizzes" / registry[0]["html"]
            if page.is_symlink() or not page.is_file() or not page.resolve().is_relative_to(q.paths["backend"].resolve()):
                raise RuntimeError("Synthetic generated page path is unsafe")
            recovery_dir = q.paths["root"] / "parity-recovery-copies"
            recovery_dir.mkdir(mode=0o700, exist_ok=True)
            copied_page = recovery_dir / page.name
            if copied_page.exists():
                raise FileExistsError("Recovery copy already exists")
            shutil.copy2(page, copied_page)
            out["old_page_sha256"] = hashlib.sha256(copied_page.read_bytes()).hexdigest()
            page.unlink()
            out["page_absent_before_rebuild"] = not page.exists()
            q.go("/admin/maintenance")
            q.js("window.confirm=()=>true;document.getElementById('rebuildAllBtn').click();true")
            q.wait("document.getElementById('rebuildStatus')?.innerText.startsWith('Complete:')", 25)
            out["rebuild_status"] = q.js("document.getElementById('rebuildStatus').innerText")
            out["rebuild_screenshot"] = str(q.screenshot("parity-rebuild.png"))
            out["page_rebuilt"] = page.is_file()
            out["rebuilt_page_sha256"] = hashlib.sha256(page.read_bytes()).hexdigest() if page.exists() else None
            out["canonical_after_rebuild"] = facts(db) == before

            q.go("/external-ai/quiz-builder")
            q.js("(()=>{const f=document.getElementById('externalAiBuilderForm');f.elements.topic.value='Synthetic container classification';f.elements.question_count.value='1';f.querySelector('button[formaction]').click();return true})()")
            q.wait("document.getElementById('externalAiPrompt')?.value.includes('Synthetic container classification')", 20)
            out["prompt_has_topic"] = q.js("document.getElementById('externalAiPrompt').value.includes('Synthetic container classification')")
            out["prompt_has_schema"] = q.js("document.getElementById('externalAiPrompt').value.includes('schema_version')")
            q.click_css("#externalAiCopyPrompt")
            q.wait("document.getElementById('externalAiCopyStatus')?.innerText.includes('copied')")
            out["copy_status"] = q.js("document.getElementById('externalAiCopyStatus').innerText")
            out["clipboard_matches_prompt"] = (q.app.clipboard().text() == q.js("document.getElementById('externalAiPrompt').value"))
            out["prompt_screenshot"] = str(q.screenshot("parity-ai-prompt.png"))

            q.js("(()=>{let f=document.getElementById('externalAiBuilderForm');f.elements.ai_response.value='{\"schema_version\":1,\"schema_version\":1}';f.requestSubmit(f.querySelector('button[type=submit]:not([formaction])'));return true})()")
            q.wait("!!document.getElementById('externalAiErrors')", 20)
            out["invalid_message"] = q.js("document.getElementById('externalAiErrors').innerText")
            out["invalid_screenshot"] = str(q.screenshot("parity-ai-invalid.png"))
            envelope = {"schema_version": 1, "content_type": "quiz", "title": "Parity AI Synthetic Quiz",
                        "source": {"organization":"Neutral Group","dataset":"Synthetic notes","version":"1",
                                   "url":"https://example.org/synthetic","license":"CC0"},
                        "questions": [{"question":"Which synthetic item is blue?","answer_mode":"single",
                                       "choices":[{"text":"Blue square","is_correct":True},
                                                  {"text":"Red circle","is_correct":False}],
                                       "explanation":"The square is blue.","concepts":["color"]}]}
            q.js("(()=>{let f=document.getElementById('externalAiBuilderForm');f.elements.ai_response.value=" + json.dumps(json.dumps(envelope)) + ";f.requestSubmit(f.querySelector('button[type=submit]:not([formaction])'));return true})()")
            q.wait("location.pathname.startsWith('/external-ai/review/')", 25)
            out["review_path"] = q.js("location.pathname")
            out["review_has_question"] = q.js("document.querySelector('[data-pdf-role=question]')?.value === 'Which synthetic item is blue?'")
            out["review_screenshot"] = str(q.screenshot("parity-ai-review.png"))
            q.js("(()=>{document.querySelector('[data-pdf-role=correctness-confirmed]').click();document.getElementById('pdfReviewForm').requestSubmit();return true})()")
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                with sqlite3.connect(db) as conn:
                    committed = conn.execute("SELECT 1 FROM quizzes WHERE title='Parity AI Synthetic Quiz'").fetchone() is not None
                if committed:
                    break
                q.delay(.12)
            else:
                raise TimeoutError("AI Review publication did not commit")
            out["publish_path"] = q.js("location.pathname")
            with sqlite3.connect(db) as conn:
                quiz = conn.execute("SELECT id,title FROM quizzes WHERE title='Parity AI Synthetic Quiz'").fetchone()
                out["published_quiz"] = quiz
                if quiz:
                    question = conn.execute("SELECT id,question_text FROM questions WHERE quiz_id=?",(quiz[0],)).fetchone()
                    choices = conn.execute("SELECT id,label,text,is_correct,choice_order FROM choices WHERE question_id=? ORDER BY choice_order",(question[0],)).fetchall()
                    out["published_question"] = question
                    out["published_choices"] = choices
            after = facts(db)
            out["old_rows_preserved"] = all(all(row in after[t] for row in before[t]) for t in before)
        else:
            with sqlite3.connect(db) as conn:
                quiz = conn.execute("SELECT id,title FROM quizzes WHERE title='Parity AI Synthetic Quiz'").fetchone()
                out["published_quiz"] = quiz
                if quiz:
                    question = conn.execute("SELECT id,question_text FROM questions WHERE quiz_id=?",(quiz[0],)).fetchone()
                    out["published_question"] = question
                    out["published_choices"] = conn.execute("SELECT id,label,text,is_correct,choice_order FROM choices WHERE question_id=? ORDER BY choice_order",(question[0],)).fetchall()
            q.go("/library")
            out["library_has_ai_quiz"] = q.js("document.body.innerText.includes('Parity AI Synthetic Quiz')")
            prior = json.loads((q.paths["root"] / "parity-tools-ai.json").read_text())
            out["records_match_prior"] = all(
                json.loads(json.dumps(out.get(key))) == prior.get(key)
                for key in ("published_quiz", "published_question", "published_choices"))
        out["pass"] = (out["storage_visible"] and bool(out.get("published_quiz"))
                       and out.get("published_question", [None,None])[1] == "Which synthetic item is blue?"
                       and [tuple(x[1:]) for x in out.get("published_choices", [])] ==
                           [("A","Blue square",1,0),("B","Red circle",0,1)]
                       and (out.get("records_match_prior") and out.get("library_has_ai_quiz") if a.reopen else
                            (out.get("page_absent_before_rebuild") and out.get("page_rebuilt")
                             and out.get("canonical_after_rebuild") and out.get("prompt_has_topic")
                             and out.get("prompt_has_schema") and "copied" in out.get("copy_status", "")
                             and out.get("clipboard_matches_prompt")
                             and "duplicate" in out.get("invalid_message", "").lower()
                             and out.get("review_has_question") and out.get("old_rows_preserved"))))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / ("parity-tools-ai-reopen.json" if a.reopen else "parity-tools-ai.json")).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
