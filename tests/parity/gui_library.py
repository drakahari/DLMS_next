"""Qt Library search, advisory duplicates, hide, and keyboard reorder fidelity."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import traceback

from desktop.isolation import PROJECT
from tests.gate1.qt_checks import QtChecks


def db_facts(path: Path):
    with sqlite3.connect(path) as conn:
        return {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("questions", "choices", "attempts", "study_responses")}


def wait_for(q, predicate, label, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        q.delay(.12)
    raise TimeoutError(label)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--reopen", action="store_true")
    args = p.parse_args()
    q = QtChecks(args.profile)
    out = {"profile": args.profile, "reopen": args.reopen}
    db = q.paths["backend"] / "results.db"
    registry_path = q.paths["backend"] / "config" / "quizzes.json"
    try:
        before = db_facts(db)
        with sqlite3.connect(db) as conn:
            before_ids = {row[0] for row in conn.execute("SELECT id FROM quizzes")}
        if not args.reopen:
            q.go("/library/duplicates")
            out["duplicates_before"] = q.js("document.querySelector('.duplicate-question-summary')?.innerText")
            text = (PROJECT / "fixtures" / "gate1-neutral-quiz.txt").read_text()
            q.go("/library")
            script = """window.__parityImport=null;(async()=>{let form=new FormData();
                form.append('quiz_title','Parity Duplicate Quiz');
                form.append('file',new File([TEXT],'parity.txt',{type:'text/plain'}));
                let csrf=document.cookie.split('; ').find(x=>x.startsWith('dlms_csrf_token='));
                form.append('csrf_token',decodeURIComponent(csrf?.split('=')[1]||''));
                let r=await fetch('/process',{method:'POST',body:form,credentials:'same-origin'});
                window.__parityImport={status:r.status,url:r.url};})();true""".replace("TEXT", json.dumps(text))
            q.js(script)
            q.wait("!!window.__parityImport", 25)
            out["import"] = json.loads(q.js("JSON.stringify(window.__parityImport)"))
            wait_for(q, lambda: len(json.loads(registry_path.read_text())) == len(before_ids)+1,
                     "duplicate quiz publication")
        registry = json.loads(registry_path.read_text())
        ids = {entry["id"] for entry in registry}
        out["quiz_ids"] = sorted(ids)
        out["new_id_distinct"] = len(ids) == len(before_ids) if args.reopen else len(ids-before_ids) == 1

        q.go("/library/duplicates")
        out["duplicate_groups"] = q.js("document.querySelectorAll('.duplicate-question-group').length")
        out["duplicate_text"] = q.js("document.querySelector('.duplicate-question-group')?.innerText.slice(0,500)")
        out["duplicate_screenshot"] = str(q.screenshot("parity-duplicates-reopen.png" if args.reopen else "parity-duplicates.png"))
        q.go("/library")
        q.js("(()=>{let e=document.getElementById('librarySearch');e.value='Parity Duplicate';e.dispatchEvent(new Event('input',{bubbles:true}));return true})()")
        out["search_matches"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('.library-quiz-card')].filter(x=>x.style.display!=='none').map(x=>x.dataset.quizId))"))
        q.js("(()=>{let e=document.getElementById('librarySearch');e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));return true})()")
        out["search_clear_matches"] = q.js("[...document.querySelectorAll('.library-quiz-card')].filter(x=>x.style.display!=='none').length")

        if not args.reopen:
            target = next(x for x in registry if x["title"] == "Parity Duplicate Quiz")
            q.js(f"document.querySelector('.quiz-card[data-quiz-id=\"{target['id']}\"] form[action=\"/toggle_hidden\"]').requestSubmit();true")
            wait_for(q, lambda: next(x for x in json.loads(registry_path.read_text()) if x["id"] == target["id"]).get("hidden") is True,
                     "hide quiz")
            q.go("/library?view=hidden")
            out["hidden_view_has_quiz"] = q.js(f"!!document.querySelector('.quiz-card[data-quiz-id=\"{target['id']}\"]')")
            q.js(f"document.querySelector('.quiz-card[data-quiz-id=\"{target['id']}\"] form[action=\"/toggle_hidden\"]').requestSubmit();true")
            wait_for(q, lambda: not next(x for x in json.loads(registry_path.read_text()) if x["id"] == target["id"]).get("hidden"),
                     "unhide quiz")
            q.go("/library")
            cards = json.loads(q.js("JSON.stringify([...document.querySelectorAll('.library-quiz-card')].map(x=>x.dataset.quizId))"))
            out["order_before"] = cards
            if len(cards) >= 2:
                q.js("document.querySelector('.library-quiz-card [data-library-reorder=quiz][data-library-reorder-direction=\"1\"]').click();true")
                q.wait("document.getElementById('libraryReorderStatus')?.innerText.includes('moved down')")
                out["order_after"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('.library-quiz-card')].map(x=>x.dataset.quizId))"))
                out["reorder_status"] = q.js("document.getElementById('libraryReorderStatus').innerText")
                q.go("/library")
                out["order_after_reload"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('.library-quiz-card')].map(x=>x.dataset.quizId))"))
        else:
            prior = json.loads((q.paths["root"] / "parity-library.json").read_text())
            out["order_after_process_restart"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('.library-quiz-card')].map(x=>x.dataset.quizId))"))
            # Later parity checks may add quizzes to this same synthetic profile.
            # Preserve the relative order of the two original cards without
            # assuming the Library inventory stopped growing.
            original_ids = set(prior["order_after"])
            out["order_matches_prior"] = [x for x in out["order_after_process_restart"] if x in original_ids] == prior["order_after"]
        out["library_screenshot"] = str(q.screenshot("parity-library-reopen.png" if args.reopen else "parity-library.png", width=800, height=760))
        after = db_facts(db)
        out["factual_rows_unchanged"] = all(all(row in after[t] for row in before[t]) for t in before)
        out["question_choice_hash"] = hashlib.sha256(repr((after["questions"], after["choices"])).encode()).hexdigest()
        out["pass"] = bool(out["new_id_distinct"] and out["duplicate_groups"] >= 1
                       and "What is two plus two?" in (out["duplicate_text"] or "")
                       and len(out["search_matches"]) == 1 and out["search_clear_matches"] == len(ids)
                       and out["factual_rows_unchanged"] and ((args.reopen and out.get("order_matches_prior")) or
                       (out.get("hidden_view_has_quiz") and out.get("order_after") == list(reversed(out["order_before"]))
                        and out.get("order_after_reload") == out.get("order_after"))))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / ("parity-library-reopen.json" if args.reopen else "parity-library.json")).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
