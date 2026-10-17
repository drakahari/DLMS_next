"""Reopen the accepted source-edited/deduplicated mixed quiz in a new Qt process."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="paritylib05")
    args = parser.parse_args()
    q = QtChecks(args.profile)
    root = q.paths["root"]
    prior = json.loads((root / "closure-mixed-stale-edit.json").read_text())
    assert prior["pass"] is True
    expected = prior["copied"]
    db = q.paths["backend"] / "results.db"
    out = {"profile": args.profile, "prior_test": "closure-mixed-stale-edit.json"}
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            mixed = conn.execute("SELECT id,source_file FROM quizzes WHERE title=?", ("Closure Current Source Mixed",)).fetchall()
            assert len(mixed) == 1
            quiz_id = mixed[0]["id"]
            copied = [list(row) for row in conn.execute(
                "SELECT id,question_text,question_type,source_question_uid FROM questions WHERE quiz_id=? ORDER BY question_number", (quiz_id,))]
            source_rows = [dict(row) for row in conn.execute("SELECT id,question_uid,question_text FROM questions WHERE id IN (5,9) ORDER BY id")]
            copy_choices = [list(row) for row in conn.execute(
                "SELECT choice_order,label,text,is_correct FROM choices WHERE question_id=? ORDER BY choice_order", (copied[0][0],))]
            copy_pairs = [list(row) for row in conn.execute(
                "SELECT pair_order,left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order", (copied[1][0],))]
            source_choices = [list(row) for row in conn.execute(
                "SELECT choice_order,label,text,is_correct FROM choices WHERE question_id=5 ORDER BY choice_order")]
            source_pairs = [list(row) for row in conn.execute(
                "SELECT pair_order,left_text,right_text FROM matching_pairs WHERE question_id=9 ORDER BY pair_order")]
        registry = json.loads((q.paths["backend"] / "config/quizzes.json").read_text())
        entries = [item for item in registry if item["id"] == quiz_id]
        assert len(entries) == 1
        html = entries[0]["html"]
        runtime = json.loads((q.paths["backend"] / "data" / html.replace(".html", ".json")).read_text())
        q.go("/quizzes/" + html)
        out.update(quiz_id=quiz_id, copied=copied, source_rows=source_rows,
                   copy_choices=copy_choices, copy_pairs=copy_pairs,
                   source_choices=source_choices, source_pairs=source_pairs,
                   runtime_question_count=len(runtime),
                   qt_title=q.js("document.title"))
        assert copied == expected and len(copied) == 2
        assert copy_choices == source_choices == prior["copy_choices"]
        assert copy_pairs == source_pairs == prior["copy_pairs"]
        assert len({row[3] for row in copied}) == 2
        assert {row[3] for row in copied} == {row["question_uid"] for row in source_rows}
        assert len(runtime) == 2
        assert [(choice["label"], choice["text"], bool(choice["is_correct"]))
                for choice in runtime[0]["choices"]] == [
                    ("A", "Three", False), ("B", "Four current closure", True),
                    ("C", "Five", False)]
        assert (q.paths["backend"] / "quizzes" / html).is_file()
        out["pass"] = True
    finally:
        (root / "data-safety-mixed-reopen.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({"profile": args.profile, "pass": out.get("pass"), "quiz_id": out.get("quiz_id")}, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
