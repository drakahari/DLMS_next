"""Compose a mixed quiz from distinct captured source quizzes in Qt."""
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
    a = p.parse_args()
    q = QtChecks(a.profile)
    db = q.paths["backend"] / "results.db"
    out = {}
    try:
        with sqlite3.connect(db) as conn:
            source = conn.execute("SELECT id,quiz_id,question_text,canonical_question_uid FROM questions WHERE id IN (5,9) ORDER BY id").fetchall()
            old = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
                   for t in ("questions","choices","matching_pairs","attempts","study_responses")}
        if len(source) != 2 or source[0][1] == source[1][1]:
            raise ValueError("This synthetic fixture does not have the required disjoint source quizzes")
        out["selected_source"] = source
        q.go("/quiz-composer")
        out["visible_ids"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('input[name=question_ids]')].map(e=>e.value))"))
        q.js("(()=>{let f=document.getElementById('mixedQuizForm');f.elements.title.value='Parity Mixed Synthetic Quiz';[...f.querySelectorAll('input[name=question_ids]')].filter(x=>['5','9'].includes(x.value)).forEach(x=>x.click());f.requestSubmit();return true})()")
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            with sqlite3.connect(db) as conn:
                quiz=conn.execute("SELECT id,title,generation_kind FROM quizzes WHERE title='Parity Mixed Synthetic Quiz'").fetchone()
            if quiz:break
            q.delay(.12)
        else:raise TimeoutError("Mixed quiz not committed")
        out["mixed_quiz"] = quiz
        with sqlite3.connect(db) as conn:
            rows=conn.execute("SELECT id,question_text,question_type,source_question_uid,canonical_question_uid,is_generated_copy FROM questions WHERE quiz_id=? ORDER BY question_number",(quiz[0],)).fetchall()
            after={t:conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in old}
        out["mixed_questions"] = rows
        with sqlite3.connect(db) as conn:
            child_fields = {
                "choices": "choice_order,label,text,is_correct",
                "matching_pairs": "pair_order,left_text,right_text,category,explanation,verification_json",
            }
            child_comparison = []
            for original, copy in zip(source, rows):
                per_question = {"source_id": original[0], "copy_id": copy[0],
                                "lineage": copy[3] == original[3] == copy[4]}
                for table, fields in child_fields.items():
                    order = fields.split(",")[0]
                    old_child = conn.execute(f"SELECT {fields} FROM {table} WHERE question_id=? ORDER BY {order}", (original[0],)).fetchall()
                    new_child = conn.execute(f"SELECT {fields} FROM {table} WHERE question_id=? ORDER BY {order}", (copy[0],)).fetchall()
                    per_question[table] = {"source": old_child, "copy": new_child, "equal": old_child == new_child}
                child_comparison.append(per_question)
            out["child_comparison"] = child_comparison
        out["old_rows_preserved"] = all(all(row in after[t] for row in old[t]) for t in old)
        registry=json.loads((q.paths["backend"] / "config/quizzes.json").read_text())
        entry=next(x for x in registry if x["id"]==quiz[0])
        out["generation"] = entry.get("generation")
        q.go("/library")
        out["library_has_mix"] = q.js("document.body.innerText.includes('Parity Mixed Synthetic Quiz')")
        out["screenshot"] = str(q.screenshot("parity-mixed-library.png"))
        out["pass"] = bool(len(rows)==2 and {r[1] for r in rows}=={s[2] for s in source}
                           and all(r[5] for r in rows) and out["old_rows_preserved"] and out["library_has_mix"]
                           and all(item["lineage"] and all(item[t]["equal"] for t in child_fields)
                                   for item in child_comparison))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "parity-mixed.json").write_text(json.dumps(out,indent=2)+"\n")
        q.close()
    print(json.dumps(out,indent=2))
    return 0 if out.get("pass") else 1


if __name__=="__main__":
    raise SystemExit(main())
