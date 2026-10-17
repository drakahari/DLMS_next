"""One Study choice and one Exam submission per rapid double activation in Qt."""
from __future__ import annotations

import argparse
import json
import sqlite3
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def ids(db, table, column):
    with sqlite3.connect(db) as conn:
        return [row[0] for row in conn.execute(f"SELECT {column} FROM {table}")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", choices=("study", "exam"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    try:
        path = urlsplit(json.loads((q.paths["root"] / "foundation-create.json").read_text())["quiz_url"]).path
        q.go(path)
        if q.js("!!document.querySelector('.quiz-recovery-start-over')"):
            q.js("window.confirm=()=>true; document.querySelector('.quiz-recovery-start-over').click(); true")
            q.wait("document.querySelector('.quiz-recovery-panel')?.hidden === true")
        db = q.paths["backend"] / "results.db"
        if args.kind == "study":
            before = set(ids(db, "study_responses", "event_id"))
            q.js("document.querySelector('.study-mode-btn').click(); true")
            q.wait("document.querySelector('button.choice') !== null")
            q.js("let choice=document.querySelector('button.choice');choice.click();choice.click();true")
            q.wait("studyLearningEventSaves.size === 0", 20)
            after = set(ids(db, "study_responses", "event_id"))
        else:
            before = set(ids(db, "attempts", "id"))
            q.js("document.querySelector('.exam-mode-btn').click(); true")
            q.wait("document.querySelector('button.choice') !== null")
            q.js("document.querySelector('button.choice').click();window.confirm=()=>true;let submit=document.getElementById('submitBtn');submit.click();submit.click();true")
            q.wait("document.body.innerText.includes('Your attempt was saved successfully')", 20)
            after = set(ids(db, "attempts", "id"))
        result = {"kind": args.kind, "new_ids": sorted(after-before),
                  "journal": [p.name for p in (q.paths["root"] / "durable-actions").glob("*.json")],
                  "screenshot": str(q.screenshot(f"{args.kind}-double-click.png"))}
        result["status"] = "pass" if len(result["new_ids"]) == 1 and not result["journal"] else "fail"
        (q.paths["root"] / f"{args.kind}-double-click.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "pass" else 1
    finally:
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
