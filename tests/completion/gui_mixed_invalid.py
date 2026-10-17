"""Reject a stale/invalid mixed source ID in the actual Qt builder."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import traceback

from tests.gate1.qt_checks import QtChecks


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile}
    try:
        backend = q.paths["backend"]
        db = backend / "results.db"
        with sqlite3.connect(db) as c:
            before = {t: c.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
                      for t in ("quizzes", "questions", "choices", "matching_pairs")}
        files = {str(p.relative_to(backend)): digest(p) for folder in ("data", "quizzes")
                 for p in (backend / folder).glob("*") if p.is_file()}
        registry = digest(backend / "config/quizzes.json")
        q.go("/quiz-composer")
        valid = json.loads(q.js("JSON.stringify([...document.querySelectorAll('input[name=question_ids]')].slice(0,2).map(x=>x.value))"))
        if len(valid) != 2:
            raise AssertionError("At least two real source choices are needed")
        q.js("(()=>{const f=document.getElementById('mixedQuizForm');f.elements.title.value='Must Not Publish';"
             "[...f.querySelectorAll('input[name=question_ids]')].filter(x=>"
             + json.dumps(valid) + ".includes(x.value)).forEach(x=>x.click());"
             "const hidden=document.createElement('input');hidden.name='question_ids';hidden.value='999999999';"
             "hidden.type='hidden';f.append(hidden);f.requestSubmit();return true})()")
        q.wait("document.body.innerText.includes('selected questions are no longer available')", 15)
        out["message"] = q.js("document.querySelector('.mixed-builder-error')?.innerText")
        q.js("document.querySelector('.mixed-builder-error')?.scrollIntoView({block:'center'}); true")
        out["screenshot"] = str(q.screenshot("completion-mixed-invalid.png", width=1000, height=760))
        with sqlite3.connect(db) as c:
            out["rows_unchanged"] = all(c.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall() == rows
                                        for t, rows in before.items())
        out["files_unchanged"] = files == {str(p.relative_to(backend)): digest(p)
            for folder in ("data", "quizzes") for p in (backend / folder).glob("*") if p.is_file()}
        out["registry_unchanged"] = registry == digest(backend / "config/quizzes.json")
        out["pass"] = ("no longer available" in (out["message"] or "") and
                       out["rows_unchanged"] and out["files_unchanged"] and out["registry_unchanged"])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "completion-mixed-invalid.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
