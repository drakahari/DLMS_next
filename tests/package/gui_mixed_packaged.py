"""Build and reopen one mixed quiz in the frozen Qt WebEngine window."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time

from tests.gate1.qt_checks import QtChecks


def question(conn, quiz_id):
    return conn.execute("SELECT id,question_text,question_type FROM questions "
                        "WHERE quiz_id=? ORDER BY question_number,id LIMIT 1", (quiz_id,)).fetchone()


def children(conn, question_id):
    return {
        "choices": [list(row) for row in conn.execute(
            "SELECT choice_order,label,text,is_correct FROM choices WHERE question_id=? ORDER BY choice_order,id",
            (question_id,))],
        "pairs": [list(row) for row in conn.execute(
            "SELECT pair_order,left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order",
            (question_id,))],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("create", "reopen"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    root = q.paths["root"]
    db = q.paths["backend"] / "results.db"
    report_path = root / "packaged-mixed-create.json"
    try:
        with sqlite3.connect(db) as conn:
            available = conn.execute("SELECT id,title FROM quizzes ORDER BY id").fetchall()
            assert len(available) >= 2
            selected = [question(conn, available[0][0]), question(conn, available[1][0])]
            assert all(selected) and selected[0][0] != selected[1][0]
            original = {str(item[0]): children(conn, item[0]) for item in selected}
            source_before = {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                             for table in ("questions", "choices", "matching_pairs")}
        if args.phase == "create":
            q.go("/quiz-composer")
            ids = [str(item[0]) for item in selected]
            q.js("(()=>{let f=document.getElementById('mixedQuizForm');"
                 "f.elements.title.value='Packaged Mixed Synthetic Quiz';"
                 "for(const x of f.querySelectorAll('input[name=question_ids]'))"
                 f"if({json.dumps(ids)}.includes(x.value))x.click();"
                 "f.requestSubmit();return true})()")
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                with sqlite3.connect(db) as conn:
                    mix = conn.execute("SELECT id FROM quizzes WHERE title='Packaged Mixed Synthetic Quiz'").fetchone()
                if mix:
                    break
                q.delay(0.12)
            else:
                raise TimeoutError("Mixed quiz was not saved")
            mix_id = mix[0]
        else:
            prior = json.loads(report_path.read_text())
            assert prior["pass"] is True
            mix_id = prior["mix_id"]
            assert [list(item) for item in selected] == prior["source_questions"]
        with sqlite3.connect(db) as conn:
            mixed = conn.execute("SELECT id,question_text,question_type,source_question_uid "
                                 "FROM questions WHERE quiz_id=? ORDER BY question_number,id", (mix_id,)).fetchall()
            after = {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                     for table in source_before}
            copied = [children(conn, item[0]) for item in mixed]
        registry = json.loads((q.paths["backend"] / "config/quizzes.json").read_text())
        entry = next(item for item in registry if item["id"] == mix_id)
        runtime = json.loads((q.paths["backend"] / "data" / entry["html"].replace(".html", ".json")).read_text())
        q.go("/quizzes/" + entry["html"])
        report = {"phase": args.phase, "mix_id": mix_id,
                  "source_questions": [list(item) for item in selected],
                  "mixed_questions": [list(item) for item in mixed],
                  "source_children": original, "copied_children": copied,
                  "source_rows_preserved": all(all(row in after[table] for row in source_before[table])
                                               for table in source_before),
                  "runtime_questions": len(runtime), "page_title": q.js("document.title"),
                  "screenshot": str(q.screenshot(f"packaged-mixed-{args.phase}.png"))}
        report["pass"] = (len(mixed) == 2 and len(runtime) == 2
                          and [item[1:3] for item in mixed] == [item[1:3] for item in selected]
                          and copied == [original[str(item[0])] for item in selected]
                          and report["source_rows_preserved"])
        (root / f"packaged-mixed-{args.phase}.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k not in {"source_children", "copied_children"}}, indent=2))
        return 0 if report["pass"] else 1
    finally:
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
